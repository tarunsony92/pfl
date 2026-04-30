"""Level 5 — Final 32-Point Scoring (NBFC FINPAGE Individual Loan Audit).

Gathers every signal produced by L0 (CAM discrepancy) through L4
(agreement audit), feeds it into the 32-parameter scoring model, and
persists the result + issues for any FAIL rows. Downstream the final
report generator reads the same sub_step_results payload.
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
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.verification.levels._common import carry_forward_prior_decisions
from app.verification.levels.level_1_address import (
    _pack,
    _ref,
    filter_suppressed_issues,
)
from app.verification.services.address_normalizer import fuzzy_name_match
from app.verification.services.income_proof_analyzer import (
    analyse_income_proofs,
)
from app.verification.services.scoring_model import (
    FORCE_CRITICAL_SNOS,
    ScoringContext,
    build_score,
)


_INCOME_PROOF_SUBTYPES: frozenset[str] = frozenset(
    {
        # Recognised income-proof subtypes the classifier emits today, plus
        # plausible synonyms the manual upload UI may use. Cheap to overshoot
        # — non-existent subtypes simply yield zero artefacts.
        "INCOME_PROOF",
        "SALARY_SLIP",
        "INCOME_SOURCE_PHOTO",
        "BANK_ACCOUNT_PROOF",
        "BUSINESS_INCOME_PROOF",
        "COAPP_INCOME_PROOF",
        "CO_APPLICANT_INCOME_PROOF",
    }
)


async def _run_income_proof_analyser(
    session: AsyncSession,
    case_id: UUID,
    *,
    storage: Any,
    claude: Any,
    ctx: ScoringContext,
) -> dict[str, Any] | None:
    """Find income-proof artifacts on the case, download their bytes, and
    invoke the Opus-4.7 income-proof analyser.

    Returns the analyser's structured result dict (suitable for direct
    assignment to ``ScoringContext.income_proof_analysis``), or None when
    there is nothing to analyse / the analyser failed catastrophically.
    """
    arts = (
        (
            await session.execute(
                select(CaseArtifact).where(CaseArtifact.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    proof_arts = [
        a
        for a in arts
        if (a.metadata_json or {}).get("subtype") in _INCOME_PROOF_SUBTYPES
    ]
    if not proof_arts:
        return None

    declared = None
    cam = ctx.auto_cam or {}
    for path in (
        ("cm_cam_il", "total_monthly_income"),
        ("system_cam", "total_household_income"),
    ):
        node = cam
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = None
                break
        if isinstance(node, (int, float)) and node > 0:
            declared = int(node)
            break
        if isinstance(node, str):
            try:
                declared = int(float(node.replace(",", "").replace("₹", "")))
                if declared > 0:
                    break
            except (TypeError, ValueError):
                continue

    proofs: list[tuple[str, bytes]] = []
    for a in proof_arts[:8]:  # cap at 8 to keep Opus latency bounded
        try:
            data = await storage.download_object(a.s3_key)
            if data:
                proofs.append((a.filename or a.s3_key, data))
        except Exception as exc:  # noqa: BLE001 — storage may flake
            _log.warning(
                "L5 income-proof: storage fetch failed for %s: %s",
                a.s3_key,
                exc,
            )

    if not proofs:
        return None

    analysis = await analyse_income_proofs(
        proofs=proofs,
        declared_monthly_income_inr=declared,
        applicant_name=ctx.applicant_name,
        co_applicant_name=ctx.co_applicant_name,
        business_type=None,  # not yet wired through ScoringContext
        claude=claude,
    )
    return analysis.to_dict()

_log = logging.getLogger(__name__)


# Rows that pass on artifact-subtype presence — the orchestrator looks up
# matching artefacts after build_score and attaches them as source_artifacts
# so the FE can render the actual file instead of "Source files not yet
# attached." Keep aligned with the resolvers' subtype lists in
# scoring_model.py (r_b16, r_b17, r_b19, r_b21, r_c27, r_c28).
SCORING_ROW_SUBTYPES: dict[int, list[str]] = {
    16: ["INCOME_PROOF", "SALARY_SLIP", "INCOME_SOURCE_PHOTO"],
    17: ["INCOME_PROOF", "SALARY_SLIP", "INCOME_SOURCE_PHOTO", "BANK_STATEMENT"],
    19: ["BANK_STATEMENT"],
    21: ["COAPP_BANK_STATEMENT"],
    27: ["HOUSE_OWNERSHIP_PROOF", "RATION_CARD"],
    28: [
        "UDYAM_REG",
        "UDYAM_CERTIFICATE",
        "SHOP_LICENCE",
        "SHOP_LICENSE",
        "SHOP_ACT",
        "BUSINESS_OWNERSHIP_PROOF",
        "GST_REG",
        "GST_CERTIFICATE",
    ],
    # Section D evidence — each rubric row has a distinct artifact:
    #   #30  References + contact-details screenshot from the LMS PD page
    #   #31  TVR audio recording (Credit HO telephonic verification)
    #   #32  Fraud-call audio recording (independent HO call — separate file
    #        from the TVR audio).
    # When the expected artifact is not on the case, the row-attachment
    # loop below leaves source_artifacts empty rather than citing
    # PD/AutoCAM as a fallback — those documents do not back this
    # rubric and showing them on the issue card was misleading.
    30: ["REFERENCES_SCREENSHOT"],
    31: ["TVR_AUDIO"],
    32: ["FRAUD_CALL_AUDIO"],
}


# Rows whose source-files panel must reflect the actual upload state of
# their expected subtype only — don't fall back to PD / AutoCAM as a
# stand-in when the artifact is missing. The rubric description already
# tells the assessor exactly which file to upload.
_NO_FALLBACK_SNOS: frozenset[int] = frozenset({30, 31, 32})


# Per-row provenance fallback for PASS rows that don't match an explicit
# subtype (most rubric rows derive from a CAM extraction or bureau report,
# not a single uploaded artifact). Returns an ordered list of the
# resolver-implied source artefacts. Mirrors what ``scoring_model.py`` actually
# reads to make its verdict, keep this aligned when a resolver changes its
# inputs.
_BUREAU_DEPENDENT_SNOS: frozenset[int] = frozenset(
    {
        3,  # Applicant CIBIL ≥750
        4,  # Co-App CIBIL Checked
        5,  # Unsecured Outstanding
        6,  # DPD in Last 12 Months
        7,  # Write-offs / Settlements
        8,  # Closed Accounts ratio
    }
)
_BANK_DEPENDENT_SNOS: frozenset[int] = frozenset(
    {
        18,  # Avg balance / FOIR
        19,  # ≥6-month statement on file
        20,  # NACH bounce count
    }
)
_PD_DEPENDENT_SNOS: frozenset[int] = frozenset({29, 30, 31, 32})


def _default_sources_for_sno(
    sno: int,
    *,
    autocam_art: CaseArtifact | None,
    bureau_art: CaseArtifact | None,
    bank_art: CaseArtifact | None,
    pd_art: CaseArtifact | None,
) -> list[CaseArtifact | None]:
    """Resolver-aware fallback source list for a PASS rubric row.

    Most resolvers in ``scoring_model.py`` read from one of: AutoCAM
    (CAM sheet), the primary bureau report, the bank statement, or the
    PD sheet. Cite whichever one the resolver actually consults so the
    MD's "View source" button opens the right document.
    """
    out: list[CaseArtifact | None] = []
    if sno in _BUREAU_DEPENDENT_SNOS:
        out.append(bureau_art)
        out.append(autocam_art)  # CAM is the secondary source for credit
    elif sno in _BANK_DEPENDENT_SNOS:
        out.append(bank_art)
        out.append(autocam_art)
    elif sno in _PD_DEPENDENT_SNOS:
        out.append(pd_art)
        out.append(autocam_art)
    else:
        # Default for every other Section A/B/C row: the CAM is what the
        # resolver reads.
        out.append(autocam_art)
    return out


def _relevance_for_sno_subtype(sno: int, subtype: str | None) -> str:
    """Human-readable relevance string for the source-files panel.

    Falls back to "Tagged as {subtype}" for the explicit
    ``SCORING_ROW_SUBTYPES`` mapping (the existing behaviour) and uses a
    resolver-aware label for the implicit fallback path.
    """
    if subtype in {
        "AUTO_CAM",
    }:
        return "AutoCAM — CAM sheet (resolver source)"
    if subtype in {
        "EQUIFAX_HTML",
        "CIBIL_HTML",
        "HIGHMARK_HTML",
        "EXPERIAN_HTML",
    }:
        return "Bureau report — score / accounts (resolver source)"
    if subtype == "BANK_STATEMENT":
        return "Bank statement — transaction log (resolver source)"
    if subtype == "PD_SHEET":
        return "PD sheet — personal-discussion notes (resolver source)"
    if subtype:
        return f"Tagged as {subtype}"
    return "Resolver source"


# ── Context builder ──────────────────────────────────────────────────────────


def _pick_best_autocam(rows: list[CaseExtraction]) -> dict[str, Any] | None:
    """Prefer the 4-sheet CAM over single-sheet; among equals, most-populated."""
    if not rows:
        return None

    def variant(r: CaseExtraction) -> int:
        return 1 if ((r.data or {}).get("variant") == "single_sheet_cam") else 0

    def populated(r: CaseExtraction) -> int:
        d = r.data or {}
        return sum(len(v) for v in d.values() if isinstance(v, dict))

    rows_sorted = sorted(rows, key=lambda r: (variant(r), -populated(r)))
    return rows_sorted[0].data or None


def _pick_primary_equifax(
    rows: list[CaseExtraction], applicant_name: str | None
) -> dict[str, Any] | None:
    """Choose the bureau extraction that represents the APPLICANT.

    Preference order:
      1. Bureau-hit rows with a ``customer_info.name`` substring match.
      2. Bureau-hit rows with a fuzzy (rapidfuzz token-set ≥ 0.85) match —
         tolerates KYC vs bureau spelling drift like "Gaurav Baroka" vs
         "GOURAV BAROKA".
      3. Highest-credit-score row (deterministic tie-break across runs).
      4. ``None`` only when ``rows`` is empty.

    Mirrors the L1.5 picker but returns the raw ``data`` dict because L5
    consumers don't need the ORM row reference.
    """
    if not rows:
        return None
    hit_rows = [r for r in rows if (r.data or {}).get("bureau_hit")]
    pool = hit_rows or rows
    if applicant_name:
        tgt = applicant_name.strip().lower()
        for r in pool:
            info = (r.data or {}).get("customer_info") or {}
            nm = (info.get("name") or "").strip().lower() if isinstance(info, dict) else ""
            if nm and tgt in nm:
                return r.data
        for r in pool:
            info = (r.data or {}).get("customer_info") or {}
            nm = (info.get("name") or "").strip() if isinstance(info, dict) else ""
            if nm and fuzzy_name_match(applicant_name, nm):
                return r.data
    best = max(
        pool,
        key=lambda r: (r.data or {}).get("credit_score")
        if isinstance((r.data or {}).get("credit_score"), int)
        else -1,
        default=None,
    )
    return best.data if best else None


def _pick_coapp_equifax(
    rows: list[CaseExtraction],
    primary: dict[str, Any] | None,
    co_applicant_name: str | None,
) -> dict[str, Any] | None:
    """Choose the bureau extraction that represents the CO-APPLICANT.

    Strict-match version: requires ``co_applicant_name`` to be set on
    the case AND a substring match on the bureau row's
    ``customer_info.name``. Returns ``None`` otherwise — L5 prefers a
    silent absence over guessing co-app from a non-primary row (the L1.5
    picker is more lenient because its rules need a name regardless).
    """
    if not rows or not co_applicant_name:
        return None
    tgt = co_applicant_name.strip().lower()
    # Pass 1 — substring (cheap, exact-ish).
    for r in rows:
        if primary and r.data is primary:
            continue
        info = (r.data or {}).get("customer_info") or {}
        nm = (info.get("name") or "").strip().lower() if isinstance(info, dict) else ""
        if nm and tgt in nm:
            return r.data
    # Pass 2 — fuzzy match for KYC vs bureau spelling drift.
    for r in rows:
        if primary and r.data is primary:
            continue
        info = (r.data or {}).get("customer_info") or {}
        nm = (info.get("name") or "").strip() if isinstance(info, dict) else ""
        if nm and fuzzy_name_match(co_applicant_name, nm):
            return r.data
    return None


async def _build_context(
    session: AsyncSession, case_id: UUID
) -> ScoringContext:
    case = await session.get(Case, case_id)

    # Pull artifacts + compute distinct subtypes
    arts = (
        (
            await session.execute(
                select(CaseArtifact).where(CaseArtifact.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    subtypes = {
        (a.metadata_json or {}).get("subtype")
        for a in arts
        if (a.metadata_json or {}).get("subtype")
    }
    subtypes.discard(None)

    # Extractions by name
    exts = (
        (
            await session.execute(
                select(CaseExtraction).where(CaseExtraction.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    autocam_rows = [e for e in exts if e.extractor_name == "auto_cam"]
    equifax_rows = [e for e in exts if e.extractor_name == "equifax"]
    l2_rows = [e for e in exts if e.extractor_name == "bank_ca_analyzer"]

    autocam = _pick_best_autocam(autocam_rows)
    primary_equifax = _pick_primary_equifax(
        equifax_rows, getattr(case, "applicant_name", None) if case else None
    )
    # Co-applicant name fallback chain. ``case.co_applicant_name`` is the
    # canonical source but is frequently null on cases imported via the ZIP
    # path (the intake form doesn't always capture it). When that's the
    # case, infer the co-app's name from one of the secondary extractions
    # so the resolver doesn't false-NA on rule #4 (Co-App CIBIL Checked):
    #
    #   1. ``customer_info.name`` of any Equifax extraction whose
    #      ``data is not primary_equifax`` (the second bureau report in
    #      the ZIP IS the co-applicant's, by construction).
    #   2. The co-applicant Aadhaar / PAN extraction's ``name`` field.
    case_coapp_name = getattr(case, "co_applicant_name", None) if case else None
    if not case_coapp_name and equifax_rows:
        for r in equifax_rows:
            if primary_equifax is not None and r.data is primary_equifax:
                continue
            ci = (r.data or {}).get("customer_info") or {}
            nm = ci.get("name") if isinstance(ci, dict) else None
            if isinstance(nm, str) and nm.strip():
                case_coapp_name = nm.strip()
                break
    if not case_coapp_name:
        # Last-ditch fallback: scan extractions for a co-applicant Aadhaar
        # or PAN entry. ``aadhaar_scanner`` / ``pan_scanner`` write
        # ``data["name"]`` for the artefact they parsed; the orchestrator
        # tags by artefact subtype, so we filter on the artifact's
        # metadata via the existing ``CaseArtifact`` query path. Cheap to
        # do here — single linear pass over the already-loaded extractions.
        from app.models.case_extraction import CaseExtraction as _CE
        coapp_ext = (
            await session.execute(
                select(_CE).where(
                    _CE.case_id == case_id,
                    _CE.extractor_name.in_(["aadhaar_scanner", "pan_scanner"]),
                )
            )
        ).scalars().all()
        for r in coapp_ext:
            # Match the artefact's subtype to a co-applicant slot. The
            # extractor row's ``artifact_id`` joins to ``CaseArtifact``;
            # we look up the subtype on ``arts`` (already loaded).
            ar = next((a for a in arts if a.id == r.artifact_id), None)
            if ar is None:
                continue
            sub = (ar.metadata_json or {}).get("subtype") or ""
            if "CO_APPLICANT" in sub or "COAPP" in sub:
                nm = (r.data or {}).get("name")
                if isinstance(nm, str) and nm.strip():
                    case_coapp_name = nm.strip()
                    break

    coapp_equifax = _pick_coapp_equifax(
        equifax_rows,
        primary_equifax,
        case_coapp_name,
    )

    # L2 CA analyser output is stored on verification_results.sub_step_results
    # for the latest L2 run, not a separate extraction row.
    bank_ca = None
    l3_house = None
    l3_business = None
    l4_scanner = None
    l1_gps_verdict = None
    for vr in (
        (
            await session.execute(
                select(VerificationResult)
                .where(VerificationResult.case_id == case_id)
                .order_by(VerificationResult.created_at.desc())
            )
        )
        .scalars()
        .all()
    ):
        sub = vr.sub_step_results or {}
        if vr.level_number == VerificationLevelNumber.L2_BANKING and bank_ca is None:
            bank_ca = sub.get("ca_analyser") or {}
            # Ensure proposed EMI from L2 sub-step result surfaces
            if "proposed_emi_inr" not in bank_ca and "proposed_emi_inr" in sub:
                bank_ca["proposed_emi_inr"] = sub["proposed_emi_inr"]
            if "tx_line_count" not in bank_ca and "tx_line_count" in sub:
                bank_ca["tx_line_count"] = sub["tx_line_count"]
        if vr.level_number == VerificationLevelNumber.L3_VISION and l3_house is None:
            l3_house = sub.get("house") or {}
            l3_business = sub.get("business") or {}
        if vr.level_number == VerificationLevelNumber.L4_AGREEMENT and l4_scanner is None:
            l4_scanner = sub.get("scanner") or {}
        if (
            vr.level_number == VerificationLevelNumber.L1_ADDRESS
            and l1_gps_verdict is None
        ):
            gm = (sub.get("gps_match") or {})
            l1_gps_verdict = gm.get("verdict")

    # Build sub_step_id → {severity, status} for the latest run of each
    # level so rubric resolvers can ask "did Lx flag this specific check?"
    # instead of re-running it. Absence from the dict means that rule
    # passed on the corresponding level.
    from app.models.level_issue import LevelIssue

    l1_issues_by_step: dict[str, dict[str, Any]] = {}
    all_level_issues: dict[str, dict[str, Any]] = {}
    # Latest VerificationResult per level for the case.
    latest_vr_by_level: dict[VerificationLevelNumber, UUID] = {}
    for vr in (
        (
            await session.execute(
                select(VerificationResult)
                .where(VerificationResult.case_id == case_id)
                .order_by(VerificationResult.created_at.desc())
            )
        )
        .scalars()
        .all()
    ):
        latest_vr_by_level.setdefault(vr.level_number, vr.id)
    if latest_vr_by_level:
        rows = (
            (
                await session.execute(
                    select(LevelIssue).where(
                        LevelIssue.verification_result_id.in_(
                            list(latest_vr_by_level.values())
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for li in rows:
            entry = {
                "severity": li.severity.value,
                "status": li.status.value,
                "verification_result_id": str(li.verification_result_id),
            }
            all_level_issues[li.sub_step_id] = entry
            if li.verification_result_id == latest_vr_by_level.get(
                VerificationLevelNumber.L1_ADDRESS
            ):
                l1_issues_by_step[li.sub_step_id] = entry

    # L2 rows (if someone stored ca output as an extraction)
    if bank_ca is None and l2_rows:
        bank_ca = l2_rows[0].data or {}

    loan_amount = int(getattr(case, "loan_amount", 0) or 0) if case else None
    tenure = getattr(case, "loan_tenure_months", None) if case else None
    # Proposed EMI — prefer L2's computed value, else CAM servable_emi, else
    # flat estimate.
    proposed_emi = None
    if bank_ca:
        proposed_emi = int(bank_ca.get("proposed_emi_inr") or 0) or None
    if proposed_emi is None and autocam:
        proposed_emi = (
            int((autocam.get("cm_cam_il") or {}).get("servable_emi") or 0)
            or int((autocam.get("system_cam") or {}).get("expected_emi") or 0)
            or None
        )

    case_pincode, in_negative, neg_reason = await _resolve_negative_area(
        session, autocam=autocam,
    )

    return ScoringContext(
        auto_cam=autocam,
        primary_equifax=primary_equifax,
        coapp_equifax=coapp_equifax,
        bank_ca=bank_ca,
        l3_house=l3_house,
        l3_business=l3_business,
        l4_scanner=l4_scanner,
        artifact_subtypes=set(subtypes),
        applicant_name=getattr(case, "applicant_name", None) if case else None,
        # Use the fallback-inferred name so rule #4 (Co-App CIBIL Checked)
        # doesn't NA-out when ``case.co_applicant_name`` is null but the
        # ZIP clearly contained a co-applicant's bureau / KYC.
        co_applicant_name=case_coapp_name,
        loan_amount_inr=loan_amount,
        tenure_months=tenure,
        proposed_emi_inr=proposed_emi,
        l1_gps_match_verdict=l1_gps_verdict,
        l1_issues_by_step=l1_issues_by_step,
        all_level_issues=all_level_issues,
        latest_vr_by_level=dict(latest_vr_by_level),
        case_pincode=case_pincode,
        case_pincode_in_negative_list=in_negative,
        negative_area_reason=neg_reason,
    )


_PINCODE_RE = __import__("re").compile(r"\b(\d{6})\b")


def _extract_pincode_from_dict(d: Any) -> str | None:
    """Find a 6-digit token in any string value of a (possibly nested) dict."""
    if d is None:
        return None
    if isinstance(d, str):
        m = _PINCODE_RE.search(d)
        return m.group(1) if m else None
    if isinstance(d, dict):
        for v in d.values():
            p = _extract_pincode_from_dict(v)
            if p:
                return p
    if isinstance(d, list):
        for v in d:
            p = _extract_pincode_from_dict(v)
            if p:
                return p
    return None


async def _resolve_negative_area(
    session: Any,
    *,
    autocam: dict[str, Any] | None,
) -> tuple[str | None, bool | None, str | None]:
    """Returns (pincode, in_negative_list, reason). The lookup flag is None when
    we couldn't extract a pincode at all — the resolver downgrades to PENDING."""
    pincode = _extract_pincode_from_dict(autocam)
    if not pincode:
        return None, None, None
    from app.models.negative_area_pincode import NegativeAreaPincode

    row = (
        await session.execute(
            select(NegativeAreaPincode)
            .where(NegativeAreaPincode.pincode == pincode)
            .where(NegativeAreaPincode.is_active.is_(True))
        )
    ).scalars().first()
    if row is None:
        return pincode, False, None
    return pincode, True, row.reason


# ── Drag-context helpers for MD-readable summaries ───────────────────────────


def _row_bullet(row: Any) -> str:
    """Multi-line bullet for one failing/pending param, MD-friendly phrasing.

    Renders as two lines:
      • #17 Co-borrower Income Proof — failing
          Co-app income proof missing.
    Weights are omitted from the user text (they're internal scoring mechanics).
    """
    status_word = "failing" if row.status == "FAIL" else "data pending"
    snippet = (row.evidence or row.remarks or "").strip()
    if len(snippet) > 110:
        snippet = snippet[:107].rstrip() + "…"
    first = f"  • #{row.sno} {row.parameter} — {status_word}"
    return f"{first}\n      {snippet}" if snippet else first


def _section_drag_context(sec: Any) -> str:
    """List the failing / pending rows in this section, one per bullet.

    FAILs first (most damaging), then PENDINGs. Capped at 4 so the MD gets a
    full picture without visual overload.
    """
    fails = [r for r in sec.rows if r.status == "FAIL"]
    pendings = [r for r in sec.rows if r.status == "PENDING"]
    fails.sort(key=lambda r: -r.weight)
    pendings.sort(key=lambda r: -r.weight)
    picks = (fails + pendings)[:4]
    if not picks:
        return ""
    return "\n".join(_row_bullet(r) for r in picks)


def _grade_drag_context(score: Any) -> str:
    """Two clearly-separated blocks: weakest sections, then top misses.

    The MD approving ``scoring_grade`` needs (a) where the holes are and
    (b) the worst individual failures to decide mitigate-vs-reject. We render
    line-by-line so the detail is scannable rather than comma-soup.
    """
    # Worst sections by absolute point deficit (max - earned). Skip sections
    # already at ≥70% — they're not dragging the score down.
    bad_sections = [s for s in score.sections if s.pct < 70]
    bad_sections.sort(key=lambda s: -(s.max_score - s.earned))
    section_lines: list[str] = []
    if bad_sections:
        section_lines.append("Weakest sections:")
        for s in bad_sections[:3]:
            section_lines.append(
                f"  • Section {s.section_id} ({s.title}) — "
                f"{s.earned} / {s.max_score} ({s.pct:.0f}%)"
            )

    # Top failing rows across the whole score.
    all_rows: list[Any] = []
    for s in score.sections:
        all_rows.extend(s.rows)
    fails = [r for r in all_rows if r.status == "FAIL"]
    pendings = [r for r in all_rows if r.status == "PENDING"]
    fails.sort(key=lambda r: -r.weight)
    pendings.sort(key=lambda r: -r.weight)
    row_picks = (fails + pendings)[:3]
    row_lines: list[str] = []
    if row_picks:
        row_lines.append("Top misses:")
        row_lines.extend(_row_bullet(r) for r in row_picks)

    blocks: list[str] = []
    if section_lines:
        blocks.append("\n".join(section_lines))
    if row_lines:
        blocks.append("\n".join(row_lines))
    return "\n\n".join(blocks)


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_level_5_scoring(
    session: AsyncSession,
    case_id: UUID,
    *,
    actor_user_id: UUID,
    claude: Any = None,
    storage: Any = None,
) -> VerificationResult:
    """Compute the 32-point audit score for the case."""
    started = datetime.now(UTC)
    result = VerificationResult(
        case_id=case_id,
        level_number=VerificationLevelNumber.L5_SCORING,
        status=VerificationLevelStatus.RUNNING,
        started_at=started,
        triggered_by=actor_user_id,
    )
    session.add(result)
    await session.flush()

    ctx = await _build_context(session, case_id)

    # Opus-4.7 income-proof analyser. Reads every income-proof image attached
    # to the case, forecasts a monthly income, and counts distinct earning
    # streams. Powers row #16 (Applicant Income Proof — accuracy verdict)
    # and row #18 (Additional Income — distinct sources). Skipped when no
    # income-proof artifacts are on the case OR the storage service is
    # unavailable; the resolvers fall back to legacy presence checks in
    # that case so the level still completes cleanly.
    if storage is not None:
        analysis = await _run_income_proof_analyser(
            session, case_id, storage=storage, claude=claude, ctx=ctx
        )
        if analysis is not None:
            ctx.income_proof_analysis = analysis

    score = build_score(ctx)

    # Re-load artefacts for issue citations. We don't know per-rubric-row
    # provenance today, so every L5 issue cites the same bundle: AutoCAM +
    # PD sheet + bureau HTMLs + bank statement — the four documents the
    # rubric derives from. Future work: per-row provenance.
    _all_artifacts = (
        (await session.execute(select(CaseArtifact).where(CaseArtifact.case_id == case_id)))
        .scalars()
        .all()
    )

    def _by_subtype(sub: str) -> CaseArtifact | None:
        return next(
            (
                a for a in _all_artifacts
                if (a.metadata_json or {}).get("subtype") == sub
            ),
            None,
        )

    autocam_art = _by_subtype(ArtifactSubtype.AUTO_CAM.value)
    bureau_art = (
        _by_subtype(ArtifactSubtype.EQUIFAX_HTML.value)
        or _by_subtype(ArtifactSubtype.CIBIL_HTML.value)
        or _by_subtype(ArtifactSubtype.HIGHMARK_HTML.value)
        or _by_subtype(ArtifactSubtype.EXPERIAN_HTML.value)
    )
    bank_art = _by_subtype(ArtifactSubtype.BANK_STATEMENT.value)
    pd_art = _by_subtype(ArtifactSubtype.PD_SHEET.value)

    # Per-row provenance for EVERY rubric verdict (PASS / NA / PENDING /
    # FAIL). The FE was rendering "Source files not yet attached for this
    # rule." for rows whose resolver derives its verdict from an
    # *extraction* (CAM sheet, bureau report) rather than an
    # artifact-subtype presence check — including NA rows like #4
    # "Co-App CIBIL Checked" where the bureau report IS the document that
    # justifies the NA. Cite the underlying source for every row so the
    # MD can always click through to the document the resolver read.
    #
    # Lookup order:
    #   1. ``SCORING_ROW_SUBTYPES`` — explicit per-row artifact subtypes
    #      (rows 16/17/19/21/27/28 — the artefact-presence rules).
    #   2. ``_default_sources_for_sno`` — sno-aware fallback citing the
    #      AutoCAM, bureau report, and / or bank statement that the row's
    #      resolver actually reads from.
    #
    # Each row is capped at 3 source files (more crowds the panel).
    # Special case for the co-applicant-bound rows (#4, #21): if the
    # case has a co-applicant bureau extraction (i.e. ``coapp_equifax`` is
    # populated), prefer the co-applicant's bureau HTML over the primary's.
    coapp_bureau_art: CaseArtifact | None = None
    if ctx.coapp_equifax is not None:
        # Query the equifax extractions in this scope (the orchestrator
        # doesn't share ``_build_context``'s local ``equifax_rows``). Match
        # by ``customer_info.name`` rather than ``is`` identity — the rows
        # loaded here are fresh ORM instances, so identity comparison
        # always fails even when the underlying data is the same row.
        target_name = (
            (ctx.coapp_equifax.get("customer_info") or {}).get("name") or ""
        ).strip().lower()
        eq_rows_for_attach = (
            (
                await session.execute(
                    select(CaseExtraction).where(
                        CaseExtraction.case_id == case_id,
                        CaseExtraction.extractor_name == "equifax",
                    )
                )
            )
            .scalars()
            .all()
        )
        for r_ext in eq_rows_for_attach:
            ci = (r_ext.data or {}).get("customer_info") or {}
            row_name = (ci.get("name") or "").strip().lower()
            if target_name and row_name == target_name:
                coapp_bureau_art = next(
                    (a for a in _all_artifacts if a.id == r_ext.artifact_id),
                    None,
                )
                break

    # ``aadhaar_art`` for r_a09's source-file alignment with L1's
    # ``aadhaar_vs_bureau_address``. The L5 rubric row #9 simply mirrors
    # L1's verdict; mirror its sources too so the MD opens the same files
    # they would have opened from the L1 panel.
    aadhaar_art = _by_subtype(ArtifactSubtype.KYC_AADHAAR.value)

    for sec in score.sections:
        for row in sec.rows:
            candidates = SCORING_ROW_SUBTYPES.get(row.sno)
            matching: list[CaseArtifact] = []
            if candidates:
                matching = [
                    a for a in _all_artifacts
                    if (a.metadata_json or {}).get("subtype") in candidates
                ]
            # Section D evidence rows (#30/#31/#32) must not fall back to
            # PD/AutoCAM when the expected subtype isn't on the case — the
            # source-files panel should reflect the actual upload state, and
            # the rubric remarks already tell the assessor what to upload.
            if not matching and row.sno in _NO_FALLBACK_SNOS:
                continue
            if not matching:
                # Resolver-aware fallback: every row that draws its
                # verdict from a known extraction surface gets the
                # corresponding source artifact attached.
                if row.sno == 4 and coapp_bureau_art is not None:
                    # Rule #4 is co-applicant-specific — cite the co-app's
                    # bureau report (not the applicant's) so the MD opens
                    # the right document.
                    fallback: list[CaseArtifact | None] = [coapp_bureau_art, autocam_art]
                elif row.sno == 9:
                    # Rule #9 (CIBIL Address Match) just mirrors L1's
                    # ``aadhaar_vs_bureau_address`` verdict — cite the SAME
                    # files L1 cited (Aadhaar + bureau) so the MD opens
                    # the same documents from either panel.
                    fallback = [aadhaar_art, bureau_art]
                else:
                    fallback = _default_sources_for_sno(
                        row.sno,
                        autocam_art=autocam_art,
                        bureau_art=bureau_art,
                        bank_art=bank_art,
                        pd_art=pd_art,
                    )
                matching = [a for a in fallback if a is not None]
            if not matching:
                continue
            row.source_artifacts = _pack(
                *[
                    _ref(
                        a,
                        relevance=_relevance_for_sno_subtype(
                            row.sno, (a.metadata_json or {}).get("subtype")
                        ),
                    )
                    for a in matching[:3]
                ]
            )

    def _l5_source_artifacts() -> list[dict[str, Any]]:
        """Generic 4-doc source bundle for SECTION-LEVEL and GRADE-LEVEL
        L5 issues (e.g. "Section A scored 60%", "Overall grade D"). Those
        roll-ups span many rules and citing one specific file is misleading,
        so the bundle lists every document an L5 rubric row could plausibly
        derive from.

        For per-row issues (FAIL/PENDING on a specific 32-pt rule) the
        evidence uses ``row.source_artifacts`` instead — that field is
        populated row-aware by the loop above so the issue card cites only
        the document(s) actually backing the verdict.
        """
        return _pack(
            _ref(autocam_art, relevance="AutoCAM — eligibility / FOIR / cashflow"),
            _ref(pd_art, relevance="PD sheet — personal-discussion notes"),
            _ref(bureau_art, relevance="Bureau report — accounts + score"),
            _ref(bank_art, relevance="Bank statement — transaction log"),
        )

    issues: list[dict[str, Any]] = []

    # One WARNING per FAIL row whose weight is ≥ 3 (critical-weight fail).
    # Every PENDING row raises a WARNING regardless of weight — the assessor
    # (or MD via waiver) must explicitly resolve each one before the final
    # report can render. Severity stays WARNING because PENDING means "data
    # not yet captured" rather than "policy breached".
    #
    # Exception: rules listed in ``FORCE_CRITICAL_SNOS`` are hard escalation
    # gates whose FAIL/PENDING outcome must reach the MD-approval flow
    # (``r_a13_deviation_approved``) regardless of weight. Their issue is
    # always emitted at CRITICAL severity.
    for sec in score.sections:
        for row in sec.rows:
            force_critical = row.sno in FORCE_CRITICAL_SNOS
            if row.status == "FAIL" and (row.weight >= 3 or force_critical):
                issues.append(
                    {
                        "sub_step_id": f"scoring_{row.sno:02d}",
                        "severity": (
                            LevelIssueSeverity.CRITICAL.value
                            if (row.weight >= 4 or force_critical)
                            else LevelIssueSeverity.WARNING.value
                        ),
                        "description": (
                            f"32-Pt #{row.sno} {row.parameter}: FAIL "
                            f"(weight {row.weight}). {row.evidence} {row.remarks}"
                        ).strip(),
                        "evidence": {
                            "row": row.__dict__,
                            "source_artifacts": list(row.source_artifacts),
                        },
                    }
                )
            elif row.status == "PENDING":
                issues.append(
                    {
                        "sub_step_id": f"scoring_{row.sno:02d}_pending",
                        "severity": (
                            LevelIssueSeverity.CRITICAL.value
                            if force_critical
                            else LevelIssueSeverity.WARNING.value
                        ),
                        "description": (
                            f"32-Pt #{row.sno} {row.parameter}: data PENDING "
                            f"(weight {row.weight}). {row.remarks or 'Capture from CAM / source doc, or have MD waive.'}"
                        ).strip(),
                        "evidence": {
                            "row": row.__dict__,
                            "source_artifacts": list(row.source_artifacts),
                        },
                    }
                )

    # Helper to serialize a rubric row as a structured dict for the FE
    # "Causing the drop" table. Keeps only the fields the MD actually reads —
    # dropping internal computation flags. ScoreRow carries the full section
    # name in ``section`` (e.g. "Credit Assessment & Eligibility"); the
    # enclosing SectionScore owns the letter id, which we stamp in at the
    # caller where it's known.
    def _row_to_dict(row: Any, section_id: str | None = None) -> dict[str, Any]:
        return {
            "sno": row.sno,
            "parameter": row.parameter,
            "status": row.status,
            "weight": row.weight,
            "section": row.section,
            "section_id": section_id,
            "evidence": row.evidence,
            "remarks": row.remarks,
        }

    # Section-level summary issues — feed the frontend RULE_CATALOG.L5_SCORING
    # section rows so they show red/amber when the section is under policy.
    # Threshold: ≥70% pass · 50-70 warn · <50 critical.
    for sec in score.sections:
        sub_id = f"scoring_section_{sec.section_id.lower()}"
        if sec.pct >= 70:
            continue
        severity = (
            LevelIssueSeverity.CRITICAL.value
            if sec.pct < 50
            else LevelIssueSeverity.WARNING.value
        )
        drag = _section_drag_context(sec)
        # Build the same failing/pending row list the drag_context uses, but
        # as structured data the frontend can render as a real table (not
        # parsed out of the description string).
        sec_fails = [r for r in sec.rows if r.status == "FAIL"]
        sec_pendings = [r for r in sec.rows if r.status == "PENDING"]
        sec_fails.sort(key=lambda r: -r.weight)
        sec_pendings.sort(key=lambda r: -r.weight)
        sec_failing_rows = [
            _row_to_dict(r, sec.section_id)
            for r in (sec_fails + sec_pendings)[:4]
        ]
        issues.append(
            {
                "sub_step_id": sub_id,
                "severity": severity,
                "description": (
                    f"Section {sec.section_id} '{sec.title}' scored "
                    f"{sec.earned}/{sec.max_score} ({sec.pct:.1f}%) — below the "
                    f"70% section floor."
                    + (f"\n\nCausing the drop:\n{drag}" if drag else "")
                ),
                "evidence": {
                    "section_id": sec.section_id,
                    "section_title": sec.title,
                    "earned": sec.earned,
                    "max_score": sec.max_score,
                    "pct": round(sec.pct, 1),
                    "failing_rows": sec_failing_rows,
                    "source_artifacts": _l5_source_artifacts(),
                },
            }
        )

    # Grade-level summary issue — wires to RULE_CATALOG.L5_SCORING 'scoring_grade'.
    if score.overall_pct < 70:
        drag = _grade_drag_context(score)
        # Structured counterpart of drag: weakest sections + top failing rows.
        weakest = [s for s in score.sections if s.pct < 70]
        weakest.sort(key=lambda s: -(s.max_score - s.earned))
        weakest_sections = [
            {
                "section_id": s.section_id,
                "title": s.title,
                "earned": s.earned,
                "max_score": s.max_score,
                "pct": round(s.pct, 1),
            }
            for s in weakest[:3]
        ]
        # Build (row, section_id) pairs so top-level serialization can cite
        # the owning section — ScoreRow itself only carries the section title.
        all_rows_with_section: list[tuple[Any, str]] = []
        for s in score.sections:
            for r in s.rows:
                all_rows_with_section.append((r, s.section_id))
        all_fails = [t for t in all_rows_with_section if t[0].status == "FAIL"]
        all_pendings = [t for t in all_rows_with_section if t[0].status == "PENDING"]
        all_fails.sort(key=lambda t: -t[0].weight)
        all_pendings.sort(key=lambda t: -t[0].weight)
        top_misses = [
            _row_to_dict(r, sid) for r, sid in (all_fails + all_pendings)[:3]
        ]
        issues.append(
            {
                "sub_step_id": "scoring_grade",
                "severity": (
                    LevelIssueSeverity.CRITICAL.value
                    if score.overall_pct < 60
                    else LevelIssueSeverity.WARNING.value
                ),
                "description": (
                    f"Overall audit score {score.earned_score}/{score.max_score} = "
                    f"{score.overall_pct:.1f}% → grade {score.grade}. Below the "
                    f"70% floor (grade B or better) required to clear the 32-point audit."
                    + (f"\n\nWhat dragged the score down\n\n{drag}" if drag else "")
                ),
                "evidence": {
                    "earned": score.earned_score,
                    "max_score": score.max_score,
                    "pct": round(score.overall_pct, 1),
                    "grade": score.grade,
                    "weakest_sections": weakest_sections,
                    "top_misses": top_misses,
                    "source_artifacts": _l5_source_artifacts(),
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
            )
        )

    has_critical = any(i["severity"] == LevelIssueSeverity.CRITICAL.value for i in issues)
    result.status = (
        VerificationLevelStatus.BLOCKED if has_critical else VerificationLevelStatus.PASSED
    )
    result.sub_step_results = {
        "scoring": score.to_dict(),
        "issue_count": len(issues),
        "suppressed_rules": suppressed_rules,
    }
    result.cost_usd = Decimal("0")  # pure-python, no Claude call
    result.completed_at = datetime.now(UTC)
    await session.flush()
    # Carry forward terminal MD / assessor decisions from any prior run on
    # the same (case, level) so re-triggers don't orphan the MD's audit
    # trail. May promote ``result.status`` to PASSED_WITH_MD_OVERRIDE.
    await carry_forward_prior_decisions(session, result=result)
    return result
