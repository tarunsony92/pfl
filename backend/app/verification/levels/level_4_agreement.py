"""Level 4 — Loan-agreement asset audit.

Reads the signed loan-agreement PDF artifact (subtype LAGR), runs Claude vision
on it to extract the hypothecation / asset annexure, and raises CRITICAL issues
for anything missing that breaks recovery enforceability:

- No annexure / schedule section → CRITICAL.
- No hypothecation clause in the agreement body → CRITICAL.
- Asset annexure is empty (zero assets) → CRITICAL.

Phase D scope: extract the agreement's own asset list + flag structural gaps.
The CAM-vs-agreement asset diff will land in a follow-up once the ``auto_cam``
extractor surfaces a structured asset list (it currently doesn't).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    ArtifactSubtype,
    LevelIssueSeverity,
    LevelIssueStatus,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case_artifact import CaseArtifact
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.verification.levels._common import carry_forward_prior_decisions
from app.verification.levels.level_1_address import (
    _pack,
    _ref,
    filter_suppressed_issues,
)

_log = logging.getLogger(__name__)


# ───────────────────────────── Pure cross-checks ─────────────────────────────


def cross_check_annexure_present(annexure_present: bool) -> dict[str, Any] | None:
    """Fire CRITICAL when the signed agreement has no annexure / schedule.

    A missing annexure breaks recovery enforceability — the lender can't
    auction unenumerated hypothecated assets. Returns ``None`` (no issue)
    when the scanner confirms an annexure section is present.
    """
    if annexure_present:
        return None
    return {
        "sub_step_id": "loan_agreement_annexure",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "The signed loan agreement does not contain a distinct schedule / "
            "annexure / hypothecation list. Assessor must have the borrower "
            "re-sign an agreement with the asset annexure filled in — recovery "
            "enforceability requires every hypothecated asset be enumerated."
        ),
    }


def cross_check_hypothecation_clause(
    hypothecation_clause_present: bool,
) -> dict[str, Any] | None:
    """Fire CRITICAL when the agreement body lacks a hypothecation clause.

    Without this clause the loan reads as unsecured on paper regardless of
    what the CAM declares — pre-disbursal must reissue with the standard
    secured-asset clause.
    """
    if hypothecation_clause_present:
        return None
    return {
        "sub_step_id": "hypothecation_clause",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "No hypothecation / secured-asset clause detected in the loan "
            "agreement body. The agreement appears to be unsecured on paper, "
            "regardless of what the CAM says — re-issue with the standard "
            "hypothecation clause before disbursal."
        ),
    }


def cross_check_asset_count(asset_count: int) -> dict[str, Any] | None:
    """Fire CRITICAL when the annexure is present but enumerates zero assets.

    Distinct from the annexure-missing rule: this fires when the section
    exists but the borrower / agent left it blank, which is just as
    unenforceable as no annexure at all.
    """
    if asset_count > 0:
        return None
    return {
        "sub_step_id": "asset_annexure_empty",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            "Asset annexure is present but empty — zero assets enumerated. "
            "Assessor must list all hypothecated assets (household items, "
            "livestock, business stock) before proceeding."
        ),
    }


# ───────────────────────────── Pass-evidence helper ─────────────────────────
#
# Mirrors Part A's ``build_pass_evidence`` in level_3_vision. Populates
# ``sub_step_results.pass_evidence`` for every L4 rule that DIDN'T fire by
# slicing ``scanner_data`` from the LoanAgreementScanner. ``source_artifacts``
# cites the LAGR PDF on the same shape the fire path uses so the FE's
# LevelSourceFilesPanel aggregates passes + concerns.
#
# ``loan_agreement_scan_failed`` is error-only — it never appears on the pass
# side; a successful scan means it didn't fire and there's nothing to narrate.


def _l4_lagr_sources(
    agreement_artifact: CaseArtifact | None, *, relevance: str, highlight_field: str
) -> list[dict[str, Any]]:
    """Build the standard ``source_artifacts`` list pointing at the LAGR PDF.

    Returns an empty list when no agreement was uploaded so callers can
    splat the result unconditionally. ``relevance`` and ``highlight_field``
    feed the FE's "View source" button so it can deep-link to the right
    section of the PDF (annexure / hypothecation clause / body).
    """
    if agreement_artifact is None:
        return []
    return _pack(
        _ref(
            agreement_artifact,
            relevance=relevance,
            highlight_field=highlight_field,
        ),
    )


def build_pass_evidence_l4(
    *,
    scanner_data: dict[str, Any],
    agreement_artifact: CaseArtifact | None,
    fired_rules: set[str],
) -> dict[str, Any]:
    """Return the ``sub_step_results.pass_evidence`` dict for L4.

    Entries populated only when the corresponding cross-check would have
    returned None (e.g., ``asset_annexure_empty`` is narrated on pass
    only when ``asset_count > 0``; the fire path fires on 0). Rules in
    ``fired_rules`` are excluded so the FE reads LevelIssue.evidence on
    fails.

    ``loan_agreement_scan_failed`` is never populated here — it's an
    error-only meta-rule.
    """
    out: dict[str, Any] = {}

    # loan_agreement_missing — narrated only when an agreement was uploaded.
    # No artefact means the fire path raised it already; no pass to show.
    if (
        "loan_agreement_missing" not in fired_rules
        and agreement_artifact is not None
    ):
        out["loan_agreement_missing"] = {
            "agreement_filename": agreement_artifact.filename,
            "artifact_id": str(agreement_artifact.id),
            "source_artifacts": _l4_lagr_sources(
                agreement_artifact,
                relevance="Loan agreement PDF",
                highlight_field="body",
            ),
        }

    # loan_agreement_annexure — fires when annexure_present is False, so
    # only narrate a pass when it's True.
    if (
        "loan_agreement_annexure" not in fired_rules
        and bool(scanner_data.get("annexure_present"))
    ):
        out["loan_agreement_annexure"] = {
            "annexure_present": True,
            "annexure_page_hint": scanner_data.get("annexure_page_hint"),
            "source_artifacts": _l4_lagr_sources(
                agreement_artifact,
                relevance="Loan agreement — asset annexure section",
                highlight_field="asset_annexure",
            ),
        }

    # hypothecation_clause — fires when False, so narrate pass only when True.
    if (
        "hypothecation_clause" not in fired_rules
        and bool(scanner_data.get("hypothecation_clause_present"))
    ):
        out["hypothecation_clause"] = {
            "hypothecation_clause_present": True,
            "source_artifacts": _l4_lagr_sources(
                agreement_artifact,
                relevance="Loan agreement — hypothecation / secured-asset clause",
                highlight_field="hypothecation_clause",
            ),
        }

    # asset_annexure_empty — fires when count==0, so narrate pass only
    # when count≥1. Embed the full assets list so the FE can render the
    # annexure contents on click-to-expand.
    asset_count = int(scanner_data.get("asset_count") or 0)
    if (
        "asset_annexure_empty" not in fired_rules
        and asset_count > 0
    ):
        assets_raw = scanner_data.get("assets") or []
        assets_list = list(assets_raw) if isinstance(assets_raw, list) else []
        out["asset_annexure_empty"] = {
            "asset_count": asset_count,
            "assets": assets_list,
            "source_artifacts": _l4_lagr_sources(
                agreement_artifact,
                relevance="Loan agreement — asset annexure section",
                highlight_field="asset_annexure",
            ),
        }

    return out


# ─────────────────────────────── Orchestrator ────────────────────────────────


async def run_level_4_agreement(
    session: AsyncSession,
    case_id: UUID,
    *,
    actor_user_id: UUID,
    claude: Any,
    storage: Any,
) -> VerificationResult:
    """Run Level 4 on ``case_id`` and persist the result + issues."""
    from app.worker.extractors.loan_agreement_scanner import LoanAgreementScanner

    started = datetime.now(UTC)
    result = VerificationResult(
        case_id=case_id,
        level_number=VerificationLevelNumber.L4_AGREEMENT,
        status=VerificationLevelStatus.RUNNING,
        started_at=started,
        triggered_by=actor_user_id,
    )
    session.add(result)
    await session.flush()

    # Gather artifacts; the signed agreement subtype is LAGR (or LAPP / DPN as
    # packaged single PDFs — they're identical files in current uploads).
    artifacts = (
        (await session.execute(select(CaseArtifact).where(CaseArtifact.case_id == case_id)))
        .scalars()
        .all()
    )

    def _sub(a: CaseArtifact) -> str | None:
        meta = a.metadata_json or {}
        return meta.get("subtype")

    preferred_subtypes = (
        ArtifactSubtype.LAGR.value,
        ArtifactSubtype.LOAN_AGREEMENT.value,
        ArtifactSubtype.LAPP.value,
        ArtifactSubtype.DPN.value,
    )

    agreement_artifact: CaseArtifact | None = None
    for subtype in preferred_subtypes:
        matches = [a for a in artifacts if _sub(a) == subtype and a.filename.lower().endswith(".pdf")]
        if matches:
            agreement_artifact = matches[0]
            break

    issues: list[dict[str, Any]] = []
    scanner_result: dict[str, Any] = {}
    total_cost = Decimal("0")

    if agreement_artifact is None:
        issues.append(
            {
                "sub_step_id": "loan_agreement_missing",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    "No signed loan agreement PDF was uploaded for this case. "
                    "Upload LAGR / LOAN_AGREEMENT artifact before proceeding."
                ),
                "evidence": {
                    "expected_subtypes": list(preferred_subtypes),
                },
            }
        )
    else:
        try:
            body = await storage.download_object(agreement_artifact.s3_key)
            scanner = LoanAgreementScanner(claude=claude)
            res = await scanner.extract(agreement_artifact.filename, body)
            scanner_result = res.data
            total_cost += Decimal(str(res.data.get("cost_usd") or "0"))

            # Relevance label + highlight hint per sub-step — lets the
            # "View source" button open the LAGR at (approximately) the
            # right section. Page numbers in signed-agreement templates
            # are stable (annexure is last page; hypothecation clause on
            # page 2) — the scanner doesn't return exact page anchors
            # today, so we point at the whole doc with a field hint.
            _L4_HIGHLIGHTS: dict[str, tuple[str, str]] = {
                "annexure_empty": (
                    "Loan agreement — asset annexure section",
                    "asset_annexure",
                ),
                "asset_annexure_empty": (
                    "Loan agreement — asset annexure section",
                    "asset_annexure",
                ),
                "hypothecation_clause": (
                    "Loan agreement — hypothecation / secured-asset clause",
                    "hypothecation_clause",
                ),
            }

            for fn, arg in (
                (cross_check_annexure_present, bool(res.data.get("annexure_present"))),
                (
                    cross_check_hypothecation_clause,
                    bool(res.data.get("hypothecation_clause_present")),
                ),
                (cross_check_asset_count, int(res.data.get("asset_count") or 0)),
            ):
                iss = fn(arg)
                if iss:
                    sub = iss["sub_step_id"]
                    relevance, field = _L4_HIGHLIGHTS.get(
                        sub,
                        ("Loan agreement PDF", "body"),
                    )
                    iss["evidence"] = {
                        "agreement_filename": agreement_artifact.filename,
                        "artifact_id": str(agreement_artifact.id),
                        "source_artifacts": [
                            {
                                "artifact_id": str(agreement_artifact.id),
                                "filename": agreement_artifact.filename,
                                "relevance": relevance,
                                "highlight_field": field,
                            }
                        ],
                        **{k: v for k, v in res.data.items() if k != "usage"},
                    }
                    issues.append(iss)
        except Exception as exc:  # noqa: BLE001
            _log.exception("L4: scanner/storage error on %s", agreement_artifact.s3_key)
            issues.append(
                {
                    "sub_step_id": "loan_agreement_scan_failed",
                    "severity": LevelIssueSeverity.CRITICAL.value,
                    "description": f"Scanner failed: {exc}",
                    "evidence": {
                        "error_message": str(exc),
                        "artifact_id": str(agreement_artifact.id),
                    },
                }
            )

    # Honour /admin/learning-rules suppressions.
    issues, suppressed_rules = await filter_suppressed_issues(session, issues)

    for iss in issues:
        session.add(
            LevelIssue(
                verification_result_id=result.id,
                sub_step_id=iss["sub_step_id"],
                severity=LevelIssueSeverity(iss["severity"]),
                description=iss["description"],
                evidence=iss.get("evidence"),
                status=LevelIssueStatus.OPEN,
                artifact_id=agreement_artifact.id if agreement_artifact else None,
            )
        )

    has_critical = any(
        i["severity"] == LevelIssueSeverity.CRITICAL.value for i in issues
    )
    result.status = (
        VerificationLevelStatus.BLOCKED if has_critical else VerificationLevelStatus.PASSED
    )
    fired_sub_step_ids = {i["sub_step_id"] for i in issues}
    pass_evidence = build_pass_evidence_l4(
        scanner_data=scanner_result,
        agreement_artifact=agreement_artifact,
        fired_rules=fired_sub_step_ids,
    )
    result.sub_step_results = {
        "agreement_artifact_id": str(agreement_artifact.id) if agreement_artifact else None,
        "agreement_filename": agreement_artifact.filename if agreement_artifact else None,
        "scanner": {
            k: v for k, v in scanner_result.items() if k not in ("usage",)
        },
        "issue_count": len(issues),
        "suppressed_rules": suppressed_rules,
        "pass_evidence": pass_evidence,
    }
    result.cost_usd = total_cost
    result.completed_at = datetime.now(UTC)
    await session.flush()
    # Carry forward terminal MD / assessor decisions from any prior run on
    # the same (case, level) so re-triggers don't orphan the MD's audit
    # trail. May promote ``result.status`` to PASSED_WITH_MD_OVERRIDE.
    await carry_forward_prior_decisions(session, result=result)
    return result
