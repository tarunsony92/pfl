"""Level 5.5 — Dedupe + TVR + NACH + PDC presence-check orchestrator.

Four cross-checks (three deterministic, one Claude-vision):

  dedupe_clear   — DEDUPE_REPORT artefact must be present and its extraction
                   must show row_count == 0.  Any non-zero row_count means a
                   potential duplicate identity match (CRITICAL; requires
                   assessor + MD review to flip to PASSED_WITH_MD_OVERRIDE).
                   Missing artefact → CRITICAL "not uploaded".

  tvr_present    — At least one TVR_AUDIO artefact must exist.  Missing → CRITICAL.

  nach_present   — At least one NACH artefact (Nupay registration / e-mandate
                   PDF or screenshot) must exist so EMI auto-debit is set up
                   before disbursal. Missing → CRITICAL.

  pdc_present    — At least one PDC_CHEQUE artefact must exist AND a single
                   Claude Sonnet vision call must confirm the image actually
                   depicts a bank cheque (extracts bank / IFSC / a/c / name).
                   Missing → CRITICAL. Vision says "not a cheque" → CRITICAL.
                   Vision API failed (transient) → WARNING (MD can clear).

  pdc_matches_bank — Cross-validates the PDC vision read against the bank
                   statement extraction. IFSC mismatch or account-tail
                   mismatch → CRITICAL (cheque is from a different account
                   than EMI debits will hit, useless as recovery instrument).
                   Account-holder name fuzz < 70 → WARNING. Either side
                   missing → SKIPPED (no false positives when the bank
                   statement extractor partially failed).

Tie-breaker rules when multiple artefacts exist:
  - Multiple DEDUPE_REPORT → newest by created_at
  - Multiple TVR_AUDIO     → largest by size_bytes
  - Multiple NACH          → newest by created_at
  - Multiple PDC_CHEQUE    → newest by created_at

The ``claude`` kwarg is now used for the PDC vision call. ``storage`` is
used to download the PDC artifact bytes. Both are still optional — when the
caller passes ``None`` for ``claude`` we lazily resolve the default service,
and when ``storage`` is ``None`` we skip the vision call (degrading the PDC
check to presence-only with a WARNING).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    ArtifactSubtype,
    ExtractionStatus,
    LevelIssueSeverity,
    LevelIssueStatus,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.verification.levels._common import carry_forward_prior_decisions
from app.verification.levels.level_1_address import filter_suppressed_issues


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _latest_extraction_for_artifact(
    session: AsyncSession, artifact_id: UUID
) -> CaseExtraction | None:
    """Return the most recent ``dedupe_report`` extraction for ``artifact_id``."""
    stmt = (
        select(CaseExtraction)
        .where(CaseExtraction.artifact_id == artifact_id)
        .where(CaseExtraction.extractor_name == "dedupe_report")
        .order_by(desc(CaseExtraction.created_at))
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_level_5_5_dedupe_tvr(
    session: AsyncSession,
    case_id: UUID,
    *,
    actor_user_id: UUID,
    claude: Any = None,
    storage: Any = None,
) -> VerificationResult:
    """Run Level 5.5 on ``case_id`` and persist the result + issues."""
    # claude + storage are used by the PDC vision check below; the dedupe /
    # TVR / NACH presence checks remain deterministic.
    from app.verification.services.pdc_verifier import (
        cross_validate_pdc_vs_bank_statement,
        verify_pdc_cheque,
    )

    started = datetime.now(UTC)
    result = VerificationResult(
        case_id=case_id,
        level_number=VerificationLevelNumber.L5_5_DEDUPE_TVR,
        status=VerificationLevelStatus.RUNNING,
        started_at=started,
        triggered_by=actor_user_id,
    )
    session.add(result)
    await session.flush()

    # ── Gather all artefacts for this case ──────────────────────────────────
    artifacts: list[CaseArtifact] = (
        (await session.execute(select(CaseArtifact).where(CaseArtifact.case_id == case_id)))
        .scalars()
        .all()
    )

    def _sub(a: CaseArtifact) -> str | None:
        meta = a.metadata_json or {}
        return meta.get("subtype")

    # ── Pick DEDUPE_REPORT artefact (newest by created_at) ──────────────────
    dedupe_candidates = [a for a in artifacts if _sub(a) == ArtifactSubtype.DEDUPE_REPORT.value]
    dedupe_artifact: CaseArtifact | None = (
        max(dedupe_candidates, key=lambda a: a.created_at)
        if dedupe_candidates
        else None
    )

    # ── Pick TVR_AUDIO artefact (largest by size_bytes) ──────────────────────
    tvr_candidates = [a for a in artifacts if _sub(a) == ArtifactSubtype.TVR_AUDIO.value]
    tvr_artifact: CaseArtifact | None = (
        max(tvr_candidates, key=lambda a: (a.size_bytes or 0))
        if tvr_candidates
        else None
    )

    # ── Pick NACH artefact (newest by created_at) ────────────────────────────
    nach_candidates = [a for a in artifacts if _sub(a) == ArtifactSubtype.NACH.value]
    nach_artifact: CaseArtifact | None = (
        max(nach_candidates, key=lambda a: a.created_at)
        if nach_candidates
        else None
    )

    # ── Pick PDC_CHEQUE artefact (newest by created_at) ──────────────────────
    pdc_candidates = [a for a in artifacts if _sub(a) == ArtifactSubtype.PDC_CHEQUE.value]
    pdc_artifact: CaseArtifact | None = (
        max(pdc_candidates, key=lambda a: a.created_at)
        if pdc_candidates
        else None
    )

    issues: list[dict[str, Any]] = []
    pass_evidence: dict[str, Any] = {}

    # ── Cross-check 1: dedupe_clear ─────────────────────────────────────────
    # Cache the extraction once and reuse (eliminates the second DB read below).
    dedupe_extraction: CaseExtraction | None = None
    if dedupe_artifact is not None:
        dedupe_extraction = await _latest_extraction_for_artifact(session, dedupe_artifact.id)

    if dedupe_artifact is None:
        # Case A: no DEDUPE_REPORT artefact at all
        issues.append(
            {
                "sub_step_id": "dedupe_clear",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    "Customer dedupe report not uploaded for this case. "
                    "Upload the Finpage Customer_Dedupe xlsx so identity "
                    "uniqueness can be verified."
                ),
                "evidence": {
                    "expected_subtype": ArtifactSubtype.DEDUPE_REPORT.value,
                    "row_count": None,
                    "matched_rows": [],
                    "source_artifacts": [],
                },
            }
        )
    elif dedupe_extraction is None:
        # Case B: artefact uploaded but extractor hasn't run yet
        issues.append(
            {
                "sub_step_id": "dedupe_clear",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    "Dedupe report uploaded but not yet parsed. Wait for the "
                    "extraction worker to finish, or re-trigger ingestion from "
                    "the case detail page."
                ),
                "evidence": {
                    "artifact_id": str(dedupe_artifact.id),
                    "filename": dedupe_artifact.filename,
                    "row_count": None,
                    "matched_rows": [],
                    "source_artifacts": [
                        {
                            "artifact_id": str(dedupe_artifact.id),
                            "filename": dedupe_artifact.filename,
                            "relevance": "Customer dedupe report — pending extraction",
                            "highlight_field": "extraction",
                        }
                    ],
                },
            }
        )
    elif dedupe_extraction.status != ExtractionStatus.SUCCESS:
        # Case C: extraction ran but failed
        issues.append(
            {
                "sub_step_id": "dedupe_clear",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    f"Dedupe extraction failed: "
                    f"{dedupe_extraction.error_message or 'unknown error'}. "
                    f"Re-trigger from the case detail page."
                ),
                "evidence": {
                    "artifact_id": str(dedupe_artifact.id),
                    "filename": dedupe_artifact.filename,
                    "extraction_status": dedupe_extraction.status.value,
                    "error_message": dedupe_extraction.error_message,
                    "row_count": None,
                    "matched_rows": [],
                    "source_artifacts": [
                        {
                            "artifact_id": str(dedupe_artifact.id),
                            "filename": dedupe_artifact.filename,
                            "relevance": "Customer dedupe report — extraction failed",
                            "highlight_field": "extraction",
                        }
                    ],
                },
            }
        )
    else:
        # Case D: SUCCESS extraction; check row_count
        data = dedupe_extraction.data or {}
        row_count: int = int(data.get("row_count") or 0)
        matched_rows: list[Any] = list(data.get("matched_rows") or [])
        matched_fields: list[Any] = list(data.get("matched_fields") or [])
        field_count = len(matched_fields)

        if row_count > 0:
            issues.append(
                {
                    "sub_step_id": "dedupe_clear",
                    "severity": LevelIssueSeverity.CRITICAL.value,
                    "description": (
                        f"Potential duplicate identity match — {row_count} record(s) "
                        f"matched on {field_count} field(s). Assessor + MD review "
                        f"required before proceeding."
                    ),
                    "evidence": {
                        "row_count": row_count,
                        "matched_rows": matched_rows,
                        "matched_fields": matched_fields,
                        "source_artifacts": [
                            {
                                "artifact_id": str(dedupe_artifact.id),
                                "filename": dedupe_artifact.filename,
                                "relevance": "Customer dedupe report",
                                "highlight_field": "matched_rows",
                            }
                        ],
                    },
                }
            )
        else:
            # row_count == 0 → clean; record pass evidence
            pass_evidence["dedupe_clear"] = {
                "row_count": 0,
                "source_artifacts": [
                    {
                        "artifact_id": str(dedupe_artifact.id),
                        "filename": dedupe_artifact.filename,
                        "relevance": "Customer dedupe report — no matches",
                        "highlight_field": "row_count",
                    }
                ],
            }

    # ── Cross-check 2: tvr_present ──────────────────────────────────────────
    if tvr_artifact is None:
        issues.append(
            {
                "sub_step_id": "tvr_present",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    "TVR (Tele-Verification Report) audio not uploaded. "
                    "Upload the assessor's call recording (mp3/wav/m4a) "
                    "to proceed."
                ),
                "evidence": {
                    "expected_subtype": ArtifactSubtype.TVR_AUDIO.value,
                    "source_artifacts": [],
                },
            }
        )
    else:
        pass_evidence["tvr_present"] = {
            "filename": tvr_artifact.filename,
            "size_bytes": tvr_artifact.size_bytes,
            "source_artifacts": [
                {
                    "artifact_id": str(tvr_artifact.id),
                    "filename": tvr_artifact.filename,
                    "relevance": "TVR audio recording",
                    "highlight_field": "audio_file",
                }
            ],
        }

    # ── Cross-check 4: pdc_present (Claude vision) ──────────────────────────
    # Run BEFORE the nach check just so the level cost log lists it next to
    # the other vision-dependent calls if we ever extend.
    pdc_verify: Any = None
    pdc_cost: float = 0.0
    if pdc_artifact is None:
        issues.append(
            {
                "sub_step_id": "pdc_present",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    "PDC (post-dated cheque) not uploaded. Attach the "
                    "borrower's bank cheque so it can be lodged as the "
                    "back-up EMI-recovery instrument alongside the NACH "
                    "e-mandate."
                ),
                "evidence": {
                    "expected_subtype": ArtifactSubtype.PDC_CHEQUE.value,
                    "source_artifacts": [],
                },
            }
        )
    else:
        # Download the artifact bytes and run the vision verifier. Both calls
        # are wrapped — a transient S3 / Claude failure must NOT crash the
        # level; degrade to WARNING so MD can still clear and the case moves.
        image_bytes = b""
        download_error: str | None = None
        if storage is not None:
            try:
                image_bytes = await storage.download_object(pdc_artifact.s3_key)
            except Exception as exc:  # noqa: BLE001
                download_error = f"download_failed: {type(exc).__name__}: {exc}"
        else:
            download_error = "storage_not_provided"

        if image_bytes:
            pdc_verify = await verify_pdc_cheque(
                filename=pdc_artifact.filename,
                image_bytes=image_bytes,
                claude=claude,
            )
            pdc_cost = float(pdc_verify.cost_usd or 0.0)

        if pdc_verify is None:
            # Couldn't run vision (no bytes) — record WARNING with the reason.
            issues.append(
                {
                    "sub_step_id": "pdc_present",
                    "severity": LevelIssueSeverity.WARNING.value,
                    "description": (
                        f"PDC artefact uploaded but vision verification could "
                        f"not run: {download_error or 'unknown'}. Open the "
                        f"file and confirm it is a real cheque, then MD-clear."
                    ),
                    "evidence": {
                        "artifact_id": str(pdc_artifact.id),
                        "filename": pdc_artifact.filename,
                        "vision_error": download_error,
                        "source_artifacts": [
                            {
                                "artifact_id": str(pdc_artifact.id),
                                "filename": pdc_artifact.filename,
                                "relevance": "PDC cheque — vision skipped",
                                "highlight_field": "vision",
                            }
                        ],
                    },
                }
            )
        elif pdc_verify.vision_error:
            # Vision call ran but errored — WARNING, MD can clear after a
            # manual eyeball check.
            issues.append(
                {
                    "sub_step_id": "pdc_present",
                    "severity": LevelIssueSeverity.WARNING.value,
                    "description": (
                        f"PDC vision verification failed: "
                        f"{pdc_verify.vision_error}. Open the cheque file "
                        f"and confirm manually before MD-clearing."
                    ),
                    "evidence": {
                        "artifact_id": str(pdc_artifact.id),
                        "filename": pdc_artifact.filename,
                        **pdc_verify.to_evidence(),
                        "source_artifacts": [
                            {
                                "artifact_id": str(pdc_artifact.id),
                                "filename": pdc_artifact.filename,
                                "relevance": "PDC cheque — vision errored",
                                "highlight_field": "vision",
                            }
                        ],
                    },
                }
            )
        elif not pdc_verify.is_cheque:
            # Vision says this is NOT a cheque — CRITICAL.
            concerns_str = "; ".join(pdc_verify.concerns[:3]) or "no signal"
            issues.append(
                {
                    "sub_step_id": "pdc_present",
                    "severity": LevelIssueSeverity.CRITICAL.value,
                    "description": (
                        f"Uploaded artefact does not look like a bank cheque "
                        f"(Claude vision confidence "
                        f"{pdc_verify.confidence}%): {concerns_str}. "
                        f"Re-upload an actual PDC or have MD waive."
                    ),
                    "evidence": {
                        "artifact_id": str(pdc_artifact.id),
                        "filename": pdc_artifact.filename,
                        **pdc_verify.to_evidence(),
                        "source_artifacts": [
                            {
                                "artifact_id": str(pdc_artifact.id),
                                "filename": pdc_artifact.filename,
                                "relevance": "PDC cheque — vision rejected",
                                "highlight_field": "image",
                            }
                        ],
                    },
                }
            )
        else:
            # Vision confirmed it's a cheque — record evidence for the FE/PDF.
            pass_evidence["pdc_present"] = {
                "artifact_id": str(pdc_artifact.id),
                "filename": pdc_artifact.filename,
                **pdc_verify.to_evidence(),
                "source_artifacts": [
                    {
                        "artifact_id": str(pdc_artifact.id),
                        "filename": pdc_artifact.filename,
                        "relevance": (
                            f"PDC cheque — {pdc_verify.bank_name or 'bank?'} "
                            f"a/c {pdc_verify.account_number or '?'}"
                        ),
                        "highlight_field": "cheque",
                    }
                ],
            }

    # ── Cross-check 4b: pdc_matches_bank ────────────────────────────────────
    # Only runs when the PDC vision succeeded — otherwise we have no fields
    # to compare. Catches the operator-error case where the borrower hands in
    # a cheque from a different bank account than the one their EMIs will be
    # debited from, which would render the PDC useless as a recovery
    # instrument.
    pdc_match: Any = None
    if pdc_verify is not None and pdc_verify.is_cheque and not pdc_verify.vision_error:
        bank_artifact_ids = [
            a.id for a in artifacts if _sub(a) == ArtifactSubtype.BANK_STATEMENT.value
        ]
        bank_extraction_data: dict[str, Any] | None = None
        if bank_artifact_ids:
            bank_ext = (
                await session.execute(
                    select(CaseExtraction)
                    .where(CaseExtraction.artifact_id.in_(bank_artifact_ids))
                    .where(CaseExtraction.extractor_name == "bank_statement")
                    .where(CaseExtraction.status == ExtractionStatus.SUCCESS)
                    .order_by(desc(CaseExtraction.created_at))
                    .limit(1)
                )
            ).scalars().first()
            if bank_ext is not None:
                bank_extraction_data = bank_ext.data or {}

        pdc_match = cross_validate_pdc_vs_bank_statement(
            pdc_verify, bank_extraction_data
        )

        if pdc_match.severity == "critical":
            issues.append(
                {
                    "sub_step_id": "pdc_matches_bank",
                    "severity": LevelIssueSeverity.CRITICAL.value,
                    "description": (
                        "PDC cheque does not match the borrower's bank "
                        "statement: "
                        + "; ".join(pdc_match.mismatches[:3])
                        + ". The cheque cannot serve as an EMI recovery "
                        "instrument for the wrong account — re-collect a "
                        "cheque from the correct bank or have MD waive."
                    ),
                    "evidence": {
                        "artifact_id": str(pdc_artifact.id) if pdc_artifact else None,
                        "filename": pdc_artifact.filename if pdc_artifact else None,
                        **pdc_match.to_evidence(),
                        "source_artifacts": [
                            {
                                "artifact_id": str(pdc_artifact.id),
                                "filename": pdc_artifact.filename,
                                "relevance": "PDC cheque — account/IFSC mismatch",
                                "highlight_field": "ifsc_account",
                            }
                        ] if pdc_artifact else [],
                    },
                }
            )
        elif pdc_match.severity == "warning":
            issues.append(
                {
                    "sub_step_id": "pdc_matches_bank",
                    "severity": LevelIssueSeverity.WARNING.value,
                    "description": (
                        "PDC cheque mostly matches the bank statement but "
                        "with a soft discrepancy: "
                        + "; ".join(pdc_match.mismatches[:3])
                        + ". Sanity-check before MD-clearing."
                    ),
                    "evidence": {
                        "artifact_id": str(pdc_artifact.id) if pdc_artifact else None,
                        "filename": pdc_artifact.filename if pdc_artifact else None,
                        **pdc_match.to_evidence(),
                    },
                }
            )
        elif pdc_match.severity == "pass":
            pass_evidence["pdc_matches_bank"] = {
                "artifact_id": str(pdc_artifact.id) if pdc_artifact else None,
                "filename": pdc_artifact.filename if pdc_artifact else None,
                **pdc_match.to_evidence(),
            }
        elif pdc_match.severity == "skipped":
            # No overlapping fields between cheque + bank statement (or the
            # statement extraction is unavailable). Record the partial state
            # so the FE pass-detail card explains *why* nothing was compared
            # rather than rendering a silent "no detail" placeholder.
            pass_evidence["pdc_matches_bank"] = {
                "artifact_id": str(pdc_artifact.id) if pdc_artifact else None,
                "filename": pdc_artifact.filename if pdc_artifact else None,
                "skipped_reason": pdc_match.skip_reason
                or "no_overlapping_fields",
                **pdc_match.to_evidence(),
            }
    elif pdc_artifact is not None and (
        pdc_verify is None or not pdc_verify.is_cheque or pdc_verify.vision_error
    ):
        # PDC was uploaded but the vision read failed — pdc_matches_bank
        # cannot be evaluated. Record a skipped marker so the FE doesn't
        # leave the rule in a silent "PASS with no detail" state.
        pass_evidence["pdc_matches_bank"] = {
            "artifact_id": str(pdc_artifact.id),
            "filename": pdc_artifact.filename,
            "skipped_reason": "pdc_vision_unavailable",
        }

    # ── Cross-check 3: nach_present ─────────────────────────────────────────
    # NACH (Nupay) e-mandate registration is mandatory before disbursal so the
    # EMI auto-debit is wired up. Missing artefact → CRITICAL. We only check
    # presence here; field-level validation (UMRN format, account masking,
    # frequency = MNTH, sequence type = RCUR) is deferred to a future
    # nach_extractor — keeping L5.5 fast + deterministic for now.
    if nach_artifact is None:
        issues.append(
            {
                "sub_step_id": "nach_present",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    "NACH e-mandate (Nupay registration) not uploaded. Attach "
                    "the signed mandate PDF / screenshot showing UMRN, "
                    "customer account, frequency MNTH and RCUR sequence so "
                    "EMI auto-debit is set up before disbursal."
                ),
                "evidence": {
                    "expected_subtype": ArtifactSubtype.NACH.value,
                    "source_artifacts": [],
                },
            }
        )
    else:
        pass_evidence["nach_present"] = {
            "artifact_id": str(nach_artifact.id),
            "filename": nach_artifact.filename,
            "size_bytes": nach_artifact.size_bytes,
            "source_artifacts": [
                {
                    "artifact_id": str(nach_artifact.id),
                    "filename": nach_artifact.filename,
                    "relevance": "NACH / Nupay e-mandate registration",
                    "highlight_field": "umrn",
                }
            ],
        }

    # ── Honour /admin/learning-rules suppressions ────────────────────────────
    issues, suppressed_rules = await filter_suppressed_issues(session, issues)

    # ── Persist LevelIssue rows ──────────────────────────────────────────────
    for iss in issues:
        artifact_id_for_issue = None
        if iss["sub_step_id"] == "dedupe_clear" and dedupe_artifact is not None:
            artifact_id_for_issue = dedupe_artifact.id
        elif iss["sub_step_id"] == "nach_present" and nach_artifact is not None:
            artifact_id_for_issue = nach_artifact.id
        elif iss["sub_step_id"] == "pdc_present" and pdc_artifact is not None:
            artifact_id_for_issue = pdc_artifact.id
        elif iss["sub_step_id"] == "pdc_matches_bank" and pdc_artifact is not None:
            artifact_id_for_issue = pdc_artifact.id
        session.add(
            LevelIssue(
                verification_result_id=result.id,
                sub_step_id=iss["sub_step_id"],
                severity=LevelIssueSeverity(iss["severity"]),
                description=iss["description"],
                evidence=iss.get("evidence"),
                status=LevelIssueStatus.OPEN,
                artifact_id=artifact_id_for_issue,
            )
        )

    # ── Compute level status ─────────────────────────────────────────────────
    has_critical = any(i["severity"] == LevelIssueSeverity.CRITICAL.value for i in issues)
    result.status = (
        VerificationLevelStatus.BLOCKED if has_critical else VerificationLevelStatus.PASSED
    )

    # ── Build sub_step_results ───────────────────────────────────────────────
    result.sub_step_results = {
        "dedupe": {
            "artifact_id": str(dedupe_artifact.id) if dedupe_artifact else None,
            "filename": dedupe_artifact.filename if dedupe_artifact else None,
            "row_count": (
                int((dedupe_extraction.data or {}).get("row_count") or 0)
                if dedupe_extraction is not None
                and dedupe_extraction.status == ExtractionStatus.SUCCESS
                else None
            ),
        },
        "tvr": {
            "artifact_id": str(tvr_artifact.id) if tvr_artifact else None,
            "filename": tvr_artifact.filename if tvr_artifact else None,
            "size_bytes": tvr_artifact.size_bytes if tvr_artifact else None,
        },
        "nach": {
            "artifact_id": str(nach_artifact.id) if nach_artifact else None,
            "filename": nach_artifact.filename if nach_artifact else None,
            "size_bytes": nach_artifact.size_bytes if nach_artifact else None,
        },
        "pdc": {
            "artifact_id": str(pdc_artifact.id) if pdc_artifact else None,
            "filename": pdc_artifact.filename if pdc_artifact else None,
            "size_bytes": pdc_artifact.size_bytes if pdc_artifact else None,
            "vision": (
                pdc_verify.to_evidence() if pdc_verify is not None else None
            ),
            "bank_match": pdc_match.to_evidence() if pdc_match is not None else None,
        },
        "issue_count": len(issues),
        "suppressed_rules": suppressed_rules,
        "pass_evidence": pass_evidence,
    }
    result.cost_usd = Decimal(str(round(pdc_cost, 6)))
    result.completed_at = datetime.now(UTC)
    await session.flush()

    # Carry forward terminal MD / assessor decisions from any prior run so
    # re-triggers don't orphan the MD's audit trail.
    await carry_forward_prior_decisions(session, result=result)

    return result
