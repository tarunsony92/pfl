"""Level 1.5 — Credit history (Equifax/CIBIL) willful-default + fraud scan.

Slots in between L1 (Address) and L2 (Banking). Reads both applicant and
co-applicant bureau pulls (the ``equifax`` extractor writes one row per
artifact, one of which is typically a "Bureau Hit" and the other NTC /
co-app), runs a deterministic Python pass over the account list for the
PFL hard-stops, then defers the narrative judgment to the Opus
``CreditAnalyst``.

Hard rules (always fire without needing Opus):

- Any account whose status contains ``WO`` / ``Write-Off``       → CRITICAL
- Any account whose status contains ``LSS`` / ``Loss``           → CRITICAL
- Any account whose status contains ``SETTLED`` / ``Compromised``→ CRITICAL
- Any account whose status contains ``SUB`` / ``Substandard``    → WARNING
- Any account whose status contains ``DBT`` / ``Doubtful``       → WARNING
- Any account with DPD ≥ 90 within the last 12 months            → CRITICAL
- Applicant credit score < 680                                   → CRITICAL
- Applicant credit score < 700                                   → WARNING

The same seven hard rules (all six status scans plus credit_score_floor)
are also re-run against the co-applicant bureau, retagged with a
``coapp_`` sub_step_id prefix. The frontend's RULE_CATALOG.L1_5_CREDIT
mirrors every sub_step_id the orchestrator can emit.
"""

from __future__ import annotations

import logging
import re
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

_log = logging.getLogger(__name__)


# ── Status pattern matchers (see credit_analyst.CREDIT_GUARDRAILS) ───────────

_STATUS_WRITE_OFF = re.compile(r"\b(wo|write[-\s]*off)\b", re.IGNORECASE)
_STATUS_LOSS = re.compile(r"\b(lss|loss)\b", re.IGNORECASE)
_STATUS_SETTLED = re.compile(r"\b(settled|compromised)\b", re.IGNORECASE)
_STATUS_SUB = re.compile(r"\b(sub|substandard)\b", re.IGNORECASE)
_STATUS_DOUBTFUL = re.compile(r"\b(dbt|doubtful)\b", re.IGNORECASE)
_STATUS_SMA = re.compile(r"\bsma[-\s]*[012]\b", re.IGNORECASE)


# ── Pure cross-checks (no DB / no Claude) ────────────────────────────────────


def _count_hits(accounts: list[dict[str, Any]], pattern: re.Pattern[str]) -> list[dict[str, Any]]:
    """Return every account whose ``status`` matches ``pattern``.

    Used by each status scanner with its own pre-compiled regex (e.g.
    ``_STATUS_WRITE_OFF``). Pattern matching is forgiving — matches the
    status text loosely so legitimate lender variants ("WO/Settled",
    "Written-Off — Compromised") still register.
    """
    hits: list[dict[str, Any]] = []
    for a in accounts:
        status = str(a.get("status") or "")
        if pattern.search(status):
            hits.append(a)
    return hits


def _format_account_refs(hits: list[dict[str, Any]]) -> str:
    """Render up to 5 hits as a human-readable list for issue descriptions.

    Tail is truncated with "(+N more)" so issue text stays readable when
    a borrower has many derogatory accounts. Each entry includes
    institution, status and open date so the assessor can locate the
    row in the bureau report quickly.
    """
    if not hits:
        return ""
    bits: list[str] = []
    for h in hits[:5]:
        inst = h.get("institution") or h.get("lender") or "?"
        status = h.get("status") or "?"
        opened = h.get("date_opened") or h.get("opened") or "?"
        bits.append(f"{inst} — status={status}, opened={opened}")
    more = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
    return "; ".join(bits) + more


def _pack_worst_account(hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Normalise the first hit to the real Equifax schema keys so the
    frontend can render it consistently regardless of source.

    Real Equifax schema: institution, status, date_opened, balance, type,
    product_type. Fixture schema: lender, status, opened, balance, type.
    We fall back from the real key to the fixture key so both shapes work.
    Picking the first hit is a good-enough proxy — ranking accounts by
    severity isn't in scope for this helper."""
    if not hits:
        return None
    h = hits[0]
    return {
        "institution": h.get("institution") or h.get("lender") or None,
        "status": h.get("status") or None,
        "date_opened": h.get("date_opened") or h.get("opened") or None,
        "balance": h.get("balance") or None,
        "type": h.get("type") or None,
        "product_type": h.get("product_type") or None,
    }


def _status_scanner_evidence(hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Shared evidence dict for the six status scanners — raw status strings
    of every matching account plus the normalised first-hit worst_account."""
    return {
        "statuses_seen": [h.get("status") or "" for h in hits if h.get("status")],
        "worst_account": _pack_worst_account(hits),
    }


def cross_check_write_off(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fire CRITICAL on any WRITE-OFF account in the bureau report.

    WO = lender removed the loan from its books but the borrower is
    still legally liable. Combined with normal repayments elsewhere it's
    a strong willful-default indicator.
    """
    hits = _count_hits(accounts, _STATUS_WRITE_OFF)
    if not hits:
        return None
    return {
        "sub_step_id": "credit_write_off",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"{len(hits)} WRITE-OFF account(s) in bureau. WO = loan removed from "
            f"lender's books but the borrower is still legally liable — a "
            f"textbook willful-default indicator. Cases: {_format_account_refs(hits)}."
        ),
        "evidence": _status_scanner_evidence(hits),
    }


def cross_check_loss(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fire CRITICAL on any LOSS-classified account.

    LOSS = lender has formally written off the asset as uncollectible —
    the strongest derogatory tag the bureau emits. Always escalates to
    MD review.
    """
    hits = _count_hits(accounts, _STATUS_LOSS)
    if not hits:
        return None
    return {
        "sub_step_id": "credit_loss",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"{len(hits)} LOSS (uncollectible) account(s) in bureau. Strong fraud "
            f"/ willful-default indicator. Cases: {_format_account_refs(hits)}."
        ),
        "evidence": _status_scanner_evidence(hits),
    }


def cross_check_settled(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fire CRITICAL on any SETTLED / COMPROMISED account.

    Settled = borrower closed the loan via partial payment rather than
    honouring the original contract. Indicative of repayment-aversion
    even when the rest of the bureau looks clean.
    """
    hits = _count_hits(accounts, _STATUS_SETTLED)
    if not hits:
        return None
    return {
        "sub_step_id": "credit_settled",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"{len(hits)} SETTLED / COMPROMISED account(s). Borrower closed the "
            f"loan with a partial payment rather than honouring the contract — "
            f"negative credit behaviour. Cases: {_format_account_refs(hits)}."
        ),
        "evidence": _status_scanner_evidence(hits),
    }


def cross_check_substandard(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fire WARNING on any SUBSTANDARD-classified account.

    Substandard = 90+ DPD; the loan is on its way to NPA but hasn't been
    written off yet. WARNING (not CRITICAL) because the assessor may
    have context that explains the delinquency.
    """
    hits = _count_hits(accounts, _STATUS_SUB)
    if not hits:
        return None
    return {
        "sub_step_id": "credit_substandard",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"{len(hits)} SUBSTANDARD account(s) — 90+ days overdue and moving "
            f"toward NPA. Cases: {_format_account_refs(hits)}."
        ),
        "evidence": _status_scanner_evidence(hits),
    }


def cross_check_doubtful(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fire WARNING on any DOUBTFUL-classified account.

    Doubtful = lender no longer expects full recovery but hasn't booked
    the loss yet. One step short of LOSS in the RBI grading hierarchy.
    """
    hits = _count_hits(accounts, _STATUS_DOUBTFUL)
    if not hits:
        return None
    return {
        "sub_step_id": "credit_doubtful",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"{len(hits)} DOUBTFUL account(s) — recovery uncertain. "
            f"Cases: {_format_account_refs(hits)}."
        ),
        "evidence": _status_scanner_evidence(hits),
    }


def cross_check_sma(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fire WARNING on any SMA (Special Mention) account.

    SMA-1 / SMA-2 are RBI's early-warning buckets for accounts overdue
    by 30–60 days. Surfaces here so the assessor can chase the
    repayment before the account slips to NPA.
    """
    hits = _count_hits(accounts, _STATUS_SMA)
    if not hits:
        return None
    return {
        "sub_step_id": "credit_sma",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"{len(hits)} SMA (Special Mention) account(s) — early-warning overdue. "
            f"Cases: {_format_account_refs(hits)}."
        ),
        "evidence": _status_scanner_evidence(hits),
    }


def cross_check_credit_score(credit_score: int | None) -> dict[str, Any] | None:
    """Fire on the PFL credit-score floor: <680 CRITICAL, <700 WARNING.

    Returns ``None`` for missing / negative scores — those are NTC / no-
    hit cases handled by ``bureau_report_missing`` / NTC rules instead
    of being treated as a low-score fail (which would penalise
    customers the bureau has never seen).
    """
    if credit_score is None or credit_score < 0:
        return None  # NTC / no hit — handled by its own rule elsewhere
    if credit_score < 680:
        return {
            "sub_step_id": "credit_score_floor",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": (
                f"Credit score {credit_score} is below PFL's absolute floor of "
                f"680. This ticket cannot proceed without MD override."
            ),
            "evidence": {
                "credit_score": credit_score,
                "threshold_critical": 680,
                "threshold_warning": 700,
                "band": "crit",
            },
        }
    if credit_score < 700:
        return {
            "sub_step_id": "credit_score_floor",
            "severity": LevelIssueSeverity.WARNING.value,
            "description": (
                f"Credit score {credit_score} is below the PFL comfort band of "
                f"700. Assessor must justify advancing this case."
            ),
            "evidence": {
                "credit_score": credit_score,
                "threshold_critical": 680,
                "threshold_warning": 700,
                "band": "warn",
            },
        }
    return None


# ── Pass-evidence helper ─────────────────────────────────────────────────────
#
# Mirrors Part A's ``build_pass_evidence`` in level_3_vision. Populates
# ``sub_step_results.pass_evidence`` for every L1.5 rule that DIDN'T fire:
#   - 6 status scanners × 2 parties (applicant + co-applicant)
#   - credit_score_floor × 2 parties
#   - bureau_report_missing (narrated with the actual rows-found count)
#   - opus_credit_verdict (passes the full opus_evidence dict through
#     unchanged, same shape the fire-path emits)
#
# Key naming: MUST match the rule's ``sub_step_id`` in RULE_CATALOG exactly.
# The FE lookup is keyed on that — any drift silently falls through to the
# "no pass-detail" placeholder.


# Status scanner sub_step_ids — matches the applicant/co-app re-tag loops
# in the orchestrator. Keeping the order aligned with CRITICAL → WARNING
# matches the FE's panel ordering.
_L1_5_STATUS_SCANNERS = (
    "credit_write_off",
    "credit_loss",
    "credit_settled",
    "credit_substandard",
    "credit_doubtful",
    "credit_sma",
)


def _l1_5_bureau_sources(art: CaseArtifact | None, *, party: str) -> list[dict[str, Any]]:
    """Pack a single-artefact ``source_artifacts`` list citing the
    accounts table of the given party's bureau HTML. Returns [] when the
    artefact is missing so the FE's aggregator can still iterate."""
    if art is None:
        return []
    return _pack(
        _ref(
            art,
            relevance=(
                "Co-applicant bureau report — accounts table"
                if party == "co_applicant"
                else "Applicant bureau report — accounts table"
            ),
            highlight_field="accounts",
        ),
    )


def build_pass_evidence_l1_5(
    *,
    applicant_accounts: list[dict[str, Any]],
    applicant_credit_score: int | None,
    co_applicant_accounts: list[dict[str, Any]],
    co_applicant_credit_score: int | None,
    equifax_rows_found: int,
    opus_evidence: dict[str, Any],
    fired_rules: set[str],
    applicant_bureau_art: CaseArtifact | None,
    coapp_bureau_art: CaseArtifact | None,
) -> dict[str, Any]:
    """Return the ``sub_step_results.pass_evidence`` dict for L1.5.

    Rules in ``fired_rules`` are omitted (their evidence lives on
    LevelIssue). Each entry carries ``source_artifacts`` citing the
    relevant bureau HTML on the fire-path pattern so the FE's
    LevelSourceFilesPanel aggregates passes + concerns.

    Design decisions:
      * Co-app status-scanner entries only appear when there IS a
        co-applicant account list (``co_applicant_accounts`` non-empty
        OR a score is present). Otherwise we'd emit spurious "clean"
        entries for a credit-invisible co-app that was never scanned.
      * ``coapp_credit_score_floor`` needs a real int score — None
        means no bureau hit / NTC, not "passed".
      * ``bureau_report_missing`` pass entry requires ≥1 bureau row.
      * ``opus_credit_verdict`` pass entry requires opus_evidence to
        be non-empty (else the analyst wasn't invoked and there's
        nothing to narrate).
    """
    out: dict[str, Any] = {}

    applicant_sources = _l1_5_bureau_sources(
        applicant_bureau_art, party="applicant"
    )
    coapp_sources = _l1_5_bureau_sources(
        coapp_bureau_art, party="co_applicant"
    )

    # --- Status scanners: applicant ---
    for sub in _L1_5_STATUS_SCANNERS:
        if sub in fired_rules:
            continue
        out[sub] = {
            "party": "applicant",
            "accounts_examined": len(applicant_accounts),
            "statuses_clean": True,
            "source_artifacts": applicant_sources,
        }

    # --- Status scanners: co-applicant mirrors ---
    # Only emit when the co-applicant has any bureau presence — either an
    # account list OR a score. An entirely-absent co-app (no Equifax row
    # picked) shouldn't generate fake "clean" pass entries.
    coapp_scanned = (
        bool(co_applicant_accounts) or co_applicant_credit_score is not None
    )
    if coapp_scanned:
        for sub in _L1_5_STATUS_SCANNERS:
            key = f"coapp_{sub}"
            if key in fired_rules:
                continue
            out[key] = {
                "party": "co_applicant",
                "accounts_examined": len(co_applicant_accounts),
                "statuses_clean": True,
                "source_artifacts": coapp_sources,
            }

    # --- Credit score floor × 2 parties ---
    if "credit_score_floor" not in fired_rules:
        if isinstance(applicant_credit_score, int) and applicant_credit_score >= 0:
            out["credit_score_floor"] = {
                "party": "applicant",
                "credit_score": applicant_credit_score,
                "threshold_critical": 680,
                "threshold_warning": 700,
                "source_artifacts": applicant_sources,
            }
        else:
            out["credit_score_floor"] = {
                "party": "applicant",
                "skipped_reason": "no credit score on file",
            }
    if "coapp_credit_score_floor" not in fired_rules and coapp_scanned:
        if isinstance(co_applicant_credit_score, int) and co_applicant_credit_score >= 0:
            out["coapp_credit_score_floor"] = {
                "party": "co_applicant",
                "credit_score": co_applicant_credit_score,
                "threshold_critical": 680,
                "threshold_warning": 700,
                "source_artifacts": coapp_sources,
            }
        else:
            out["coapp_credit_score_floor"] = {
                "party": "co_applicant",
                "skipped_reason": "no credit score on file",
            }

    # --- bureau_report_missing (narrated only when ≥1 row found) ---
    if (
        "bureau_report_missing" not in fired_rules
        and equifax_rows_found >= 1
    ):
        out["bureau_report_missing"] = {
            "expected_subtype": ArtifactSubtype.EQUIFAX_HTML.value,
            "equifax_rows_found": equifax_rows_found,
            "source_artifacts": applicant_sources or coapp_sources,
        }

    # --- opus_credit_verdict (carries the full opus_evidence block) ---
    if (
        "opus_credit_verdict" not in fired_rules
        and opus_evidence  # non-empty dict required
    ):
        ev = dict(opus_evidence)
        # Cite both parties' bureau reports — opus reasoned across both.
        opus_sources = _pack(
            _ref(
                applicant_bureau_art,
                relevance="Applicant bureau report",
                highlight_field="accounts",
            ),
            _ref(
                coapp_bureau_art,
                relevance="Co-applicant bureau report",
                highlight_field="accounts",
            ),
        )
        ev["source_artifacts"] = opus_sources
        out["opus_credit_verdict"] = ev

    return out


# ── Helpers to pick the applicant vs co-applicant Equifax extractions ────────


def _pick_primary_equifax(
    rows: list[CaseExtraction], applicant_name: str | None
) -> CaseExtraction | None:
    """Pick the bureau-hit row whose customer_info.name best matches the
    applicant. Fall back to the highest credit_score.

    Name match is intentionally tolerant: a strict substring check would
    miss "Gaurav Baroka" vs the bureau header "GOURAV BAROKA" because of
    the single-letter spelling variant, leaving the row unpicked and the
    case stuck reporting "no bureau on file". We try (in order) the
    cheap substring path first, then ``fuzzy_name_match`` (rapidfuzz
    token-set-ratio ≥ 0.85) which handles case, order swap, and minor
    spelling drift common in rural KYC vs bureau extracts.
    """
    if not rows:
        return None
    hit_rows = [r for r in rows if (r.data or {}).get("bureau_hit")]
    pool = hit_rows or rows
    if applicant_name:
        tgt = applicant_name.strip().lower()
        # Pass 1 — fast substring check (preserves prior behaviour).
        for r in pool:
            info = (r.data or {}).get("customer_info") or {}
            n = (info.get("name") or "").strip().lower() if isinstance(info, dict) else ""
            if n and tgt in n:
                return r
        # Pass 2 — fuzzy fallback for spelling drift.
        for r in pool:
            info = (r.data or {}).get("customer_info") or {}
            n = (info.get("name") or "").strip() if isinstance(info, dict) else ""
            if n and fuzzy_name_match(applicant_name, n):
                return r
    # Fall back to highest positive score
    return max(
        pool,
        key=lambda r: (r.data or {}).get("credit_score")
        if isinstance((r.data or {}).get("credit_score"), int)
        else -1,
        default=None,
    )


def _pick_co_applicant_equifax(
    rows: list[CaseExtraction],
    primary: CaseExtraction | None,
    co_applicant_name: str | None,
) -> CaseExtraction | None:
    """Pick the co-applicant Equifax row from the case extractions.

    Order of preference:
      1. A non-primary row whose `customer_info.name` matches the case's
         `co_applicant_name` (when available).
      2. Any non-primary row — covers the case where the assessor uploaded a
         co-applicant Equifax HTML but `case.co_applicant_name` was never
         populated. Without this fallback the engine reports "no co-applicant
         bureau on file" even though the report sits classified on the case.
    """
    if not rows:
        return None
    if co_applicant_name:
        tgt = co_applicant_name.strip().lower()
        # Pass 1 — substring (cheap, exact-ish).
        for r in rows:
            if primary and r.id == primary.id:
                continue
            info = (r.data or {}).get("customer_info") or {}
            n = (
                (info.get("name") or "").strip().lower()
                if isinstance(info, dict)
                else ""
            )
            if n and tgt in n:
                return r
        # Pass 2 — fuzzy match for KYC vs bureau spelling drift.
        for r in rows:
            if primary and r.id == primary.id:
                continue
            info = (r.data or {}).get("customer_info") or {}
            n = (info.get("name") or "").strip() if isinstance(info, dict) else ""
            if n and fuzzy_name_match(co_applicant_name, n):
                return r
    for r in rows:
        if not primary or r.id != primary.id:
            return r
    return None


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_level_1_5_credit(
    session: AsyncSession,
    case_id: UUID,
    *,
    actor_user_id: UUID,
    claude: Any,
) -> VerificationResult:
    """Run Level 1.5 on ``case_id`` and persist the result + issues."""
    from app.verification.services.credit_analyst import CreditAnalyst

    started = datetime.now(UTC)
    result = VerificationResult(
        case_id=case_id,
        level_number=VerificationLevelNumber.L1_5_CREDIT,
        status=VerificationLevelStatus.RUNNING,
        started_at=started,
        triggered_by=actor_user_id,
    )
    session.add(result)
    await session.flush()

    equifax_rows = (
        (
            await session.execute(
                select(CaseExtraction)
                .where(CaseExtraction.case_id == case_id)
                .where(CaseExtraction.extractor_name == "equifax")
                .order_by(CaseExtraction.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    # Bureau HTML artifacts — subtype is canonical (EQUIFAX_HTML today).
    # Used below to annotate each issue with its source file(s).
    all_artifacts = (
        (await session.execute(select(CaseArtifact).where(CaseArtifact.case_id == case_id)))
        .scalars()
        .all()
    )
    bureau_arts = [
        a for a in all_artifacts
        if (a.metadata_json or {}).get("subtype") in (
            ArtifactSubtype.EQUIFAX_HTML.value,
            ArtifactSubtype.CIBIL_HTML.value,
            ArtifactSubtype.HIGHMARK_HTML.value,
            ArtifactSubtype.EXPERIAN_HTML.value,
        )
    ]

    case = await session.get(Case, case_id)
    applicant_name = getattr(case, "applicant_name", None) if case else None
    co_applicant_name = getattr(case, "co_applicant_name", None) if case else None
    loan_amount = getattr(case, "loan_amount", None) if case else None
    tenure = getattr(case, "loan_tenure_months", None) if case else None

    primary_row = _pick_primary_equifax(equifax_rows, applicant_name)
    co_row = _pick_co_applicant_equifax(equifax_rows, primary_row, co_applicant_name)

    primary_data: dict[str, Any] = (primary_row.data or {}) if primary_row else {}
    co_data: dict[str, Any] = (co_row.data or {}) if co_row else {}

    # Backfill the co-applicant name from the bureau extraction when the case
    # record never had one persisted but a non-primary Equifax row exists. The
    # Opus credit analyst keys its co-applicant section off this label, so an
    # empty value here causes the narrative to address them as "unknown" or
    # skip the section entirely — even though a bureau report is on file.
    if not co_applicant_name and co_data:
        info = co_data.get("customer_info") or {}
        if isinstance(info, dict):
            derived = (info.get("name") or "").strip() or None
            if derived:
                co_applicant_name = derived

    issues: list[dict[str, Any]] = []
    total_cost = Decimal("0")

    if not equifax_rows:
        issues.append(
            {
                "sub_step_id": "bureau_report_missing",
                "severity": LevelIssueSeverity.CRITICAL.value,
                "description": (
                    "No Equifax extraction available for this case. Re-ingest "
                    "after the bureau report is uploaded."
                ),
                "evidence": {
                    "expected_subtype": ArtifactSubtype.EQUIFAX_HTML.value,
                    "equifax_rows_found": 0,
                },
            }
        )

    # Hard-rule pass over applicant accounts + credit score
    primary_accounts = primary_data.get("accounts") or [] if primary_data else []
    for rule in (
        lambda: cross_check_write_off(primary_accounts),
        lambda: cross_check_loss(primary_accounts),
        lambda: cross_check_settled(primary_accounts),
        lambda: cross_check_substandard(primary_accounts),
        lambda: cross_check_doubtful(primary_accounts),
        lambda: cross_check_sma(primary_accounts),
        lambda: cross_check_credit_score(primary_data.get("credit_score") if primary_data else None),
    ):
        iss = rule()
        if iss:
            # Merge (don't overwrite) so rule-emitted evidence (statuses_seen,
            # worst_account, credit_score thresholds, …) survives alongside
            # the blanket {party, accounts_matched} the orchestrator adds.
            rule_ev = iss.pop("evidence", None) or {}
            iss["evidence"] = {
                "party": "applicant",
                "accounts_matched": len(primary_accounts),
                **rule_ev,
            }
            issues.append(iss)

    # Hard-rule pass over co-applicant accounts (same rule set, different party tag)
    co_accounts = co_data.get("accounts") or [] if co_data else []
    if co_row is not None:
        co_credit_score = co_data.get("credit_score") if co_data else None
        for name, rule in (
            ("coapp_credit_write_off", lambda: cross_check_write_off(co_accounts)),
            ("coapp_credit_loss", lambda: cross_check_loss(co_accounts)),
            ("coapp_credit_settled", lambda: cross_check_settled(co_accounts)),
            ("coapp_credit_substandard", lambda: cross_check_substandard(co_accounts)),
            ("coapp_credit_doubtful", lambda: cross_check_doubtful(co_accounts)),
            ("coapp_credit_sma", lambda: cross_check_sma(co_accounts)),
            ("coapp_credit_score_floor", lambda: cross_check_credit_score(co_credit_score)),
        ):
            iss = rule()
            if iss:
                # Re-tag so applicant and co-app issues are distinct rows
                iss["sub_step_id"] = name
                iss["description"] = "Co-applicant — " + iss["description"]
                # Merge (don't overwrite) — see applicant loop comment above.
                rule_ev = iss.pop("evidence", None) or {}
                iss["evidence"] = {
                    "party": "co_applicant",
                    "accounts_matched": len(co_accounts),
                    **rule_ev,
                }
                issues.append(iss)

    # Opus narrative pass — only if we have at least one bureau row
    analyst_data: dict[str, Any] = {}
    # ``opus_evidence`` is hoisted here so the pass-evidence builder at
    # the end of the orchestrator can re-use the same structured dict
    # shape the fire path emits (applicant + co-applicant block verdicts,
    # concerns, positives). Empty when Opus wasn't invoked.
    opus_evidence: dict[str, Any] = {}
    if primary_row is not None or co_row is not None:
        analyst = CreditAnalyst(claude=claude)
        r = await analyst.analyse(
            applicant_equifax=primary_data or None,
            co_applicant_equifax=co_data or None,
            applicant_name=applicant_name,
            co_applicant_name=co_applicant_name,
            loan_amount_inr=int(loan_amount) if loan_amount else None,
            loan_tenure_months=int(tenure) if tenure else None,
        )
        analyst_data = r.data or {}
        total_cost += Decimal(str(analyst_data.get("cost_usd") or "0"))
        if r.error_message:
            issues.append(
                {
                    "sub_step_id": "credit_analyst_failed",
                    "severity": LevelIssueSeverity.WARNING.value,
                    "description": f"Opus credit analyst failed: {r.error_message}",
                    "evidence": {"error_message": str(r.error_message)},
                }
            )
        else:
            # Single catch-all issue if the analyst's overall verdict is adverse
            # or it wants MD review and our hard rules didn't already fire.
            rec = (analyst_data.get("recommendation") or "").lower()
            verdict = (analyst_data.get("overall_verdict") or "").lower()
            app_block = analyst_data.get("applicant") or {}
            coapp_block = analyst_data.get("co_applicant") or {}
            wf = app_block.get("willful_default_indicators") or []
            fraud = app_block.get("fraud_red_flags") or []
            coapp_wf = coapp_block.get("willful_default_indicators") or []
            coapp_fraud = coapp_block.get("fraud_red_flags") or []
            overall_concerns = analyst_data.get("overall_concerns") or []
            overall_positives = analyst_data.get("overall_positives") or []

            # Plain-English evidence fields — pulled out of the analyst dict
            # so the frontend renders them as a structured key/value panel
            # instead of dumping the whole JSON blob as a string.
            opus_evidence = {
                "applicant_verdict": app_block.get("per_party_verdict"),
                "applicant_credit_score": app_block.get("credit_score"),
                "applicant_payment_history": app_block.get("payment_history_summary"),
                "applicant_credit_utilization": app_block.get(
                    "credit_utilization_summary"
                ),
                "applicant_dpd_pattern": app_block.get("dpd_pattern_summary"),
                "applicant_willful_default_indicators": wf,
                "applicant_fraud_red_flags": fraud,
                "co_applicant_verdict": coapp_block.get("per_party_verdict"),
                "co_applicant_credit_score": coapp_block.get("credit_score"),
                "co_applicant_payment_history": coapp_block.get(
                    "payment_history_summary"
                ),
                "co_applicant_willful_default_indicators": coapp_wf,
                "co_applicant_fraud_red_flags": coapp_fraud,
                "analyst_overall_verdict": analyst_data.get("overall_verdict"),
                "analyst_recommendation": analyst_data.get("recommendation"),
                "analyst_concerns": overall_concerns,
                "analyst_positives": overall_positives,
            }
            # Drop keys where the analyst didn't supply anything — the frontend
            # treats missing keys as "not applicable" and doesn't render them.
            opus_evidence = {
                k: v for k, v in opus_evidence.items()
                if v not in (None, [], "", {})
            }

            def _describe(tone: str, headline: str) -> str:
                lines: list[str] = [f"Opus credit analyst verdict: {tone} — {headline}"]
                if app_block:
                    lines.append("")
                    lines.append(
                        "**Applicant** "
                        + (app_block.get("per_party_verdict") or "—").upper()
                        + (
                            f" · credit score {app_block.get('credit_score')}"
                            if isinstance(app_block.get("credit_score"), int)
                            and app_block.get("credit_score", -1) >= 0
                            else ""
                        )
                    )
                    if app_block.get("payment_history_summary"):
                        lines.append(
                            f"  Payment history: {app_block['payment_history_summary']}"
                        )
                    if wf:
                        lines.append("  Willful-default signals: " + "; ".join(wf[:4]))
                    if fraud:
                        lines.append("  Fraud red flags: " + "; ".join(fraud[:4]))
                if coapp_block:
                    lines.append("")
                    lines.append(
                        "**Co-applicant** "
                        + (coapp_block.get("per_party_verdict") or "—").upper()
                        + (
                            f" · credit score {coapp_block.get('credit_score')}"
                            if isinstance(coapp_block.get("credit_score"), int)
                            and coapp_block.get("credit_score", -1) >= 0
                            else " · credit-invisible (no bureau history)"
                        )
                    )
                    if coapp_block.get("payment_history_summary"):
                        lines.append(
                            f"  Payment history: {coapp_block['payment_history_summary']}"
                        )
                    if coapp_wf:
                        lines.append(
                            "  Willful-default signals: " + "; ".join(coapp_wf[:4])
                        )
                    if coapp_fraud:
                        lines.append(
                            "  Fraud red flags: " + "; ".join(coapp_fraud[:4])
                        )
                if overall_concerns:
                    lines.append("")
                    lines.append("**Overall concerns**")
                    for c in overall_concerns[:5]:
                        lines.append(f"  • {c}")
                return "\n".join(lines)

            if rec == "reject" or verdict == "adverse":
                issues.append(
                    {
                        "sub_step_id": "opus_credit_verdict",
                        "severity": LevelIssueSeverity.CRITICAL.value,
                        "description": _describe(
                            "ADVERSE", "recommends reject."
                        ),
                        "evidence": opus_evidence,
                    }
                )
            elif rec == "escalate_md" or verdict == "caution":
                issues.append(
                    {
                        "sub_step_id": "opus_credit_verdict",
                        "severity": LevelIssueSeverity.WARNING.value,
                        "description": _describe(
                            "CAUTION", "recommends MD escalation."
                        ),
                        "evidence": opus_evidence,
                    }
                )

    # Attach source_artifacts to every emitted issue — applicant-side issues
    # cite the applicant's bureau HTML, co-applicant-side issues cite theirs
    # (falls back to whatever's available). opus_credit_verdict cites both.
    #
    # Map bureau_arts by id so we can resolve applicant vs co-applicant via
    # the CaseExtraction row's ``artifact_id`` (which
    # ``_pick_primary_equifax`` / ``_pick_co_applicant_equifax`` picked by
    # customer_info.name). Previously we indexed ``bureau_arts[0]`` /
    # ``bureau_arts[1]`` — DB-order-dependent, so if the co-applicant's
    # Equifax was uploaded first, the applicant's issues would cite the
    # wrong file.
    bureau_art_by_id = {a.id: a for a in bureau_arts}
    applicant_bureau_art = (
        bureau_art_by_id.get(primary_row.artifact_id)
        if primary_row is not None and primary_row.artifact_id is not None
        else None
    )
    coapp_bureau_art = (
        bureau_art_by_id.get(co_row.artifact_id)
        if co_row is not None and co_row.artifact_id is not None
        else None
    )
    # Last-resort fallback: the picks were either orphaned or the
    # extraction wasn't linked to an artifact (legacy rows). Keep the
    # previous positional behaviour only when we have nothing better.
    if applicant_bureau_art is None and bureau_arts:
        applicant_bureau_art = next(
            (a for a in bureau_arts if a.id != (coapp_bureau_art.id if coapp_bureau_art else None)),
            None,
        )
    if coapp_bureau_art is None and len(bureau_arts) >= 2:
        coapp_bureau_art = next(
            (a for a in bureau_arts if a.id != (applicant_bureau_art.id if applicant_bureau_art else None)),
            None,
        )
    for iss in issues:
        sub = iss["sub_step_id"]
        is_co_app = sub.startswith("coapp_")
        is_opus = sub == "opus_credit_verdict"
        is_missing = sub == "bureau_report_missing"
        if is_missing:
            # Nothing to cite — the whole point is the file isn't here.
            pass
        elif is_opus:
            iss.setdefault("evidence", {})["source_artifacts"] = _pack(
                _ref(
                    applicant_bureau_art,
                    relevance="Applicant bureau report",
                    highlight_field="accounts",
                ),
                _ref(
                    coapp_bureau_art,
                    relevance="Co-applicant bureau report",
                    highlight_field="accounts",
                ),
            )
        else:
            cited = coapp_bureau_art if is_co_app else applicant_bureau_art
            if cited is None and not is_co_app:
                cited = applicant_bureau_art or coapp_bureau_art
            iss.setdefault("evidence", {})["source_artifacts"] = _pack(
                _ref(
                    cited,
                    relevance=(
                        "Co-applicant bureau report — accounts table"
                        if is_co_app
                        else "Applicant bureau report — accounts table"
                    ),
                    highlight_field="accounts",
                ),
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

    has_critical = any(
        i["severity"] == LevelIssueSeverity.CRITICAL.value for i in issues
    )
    result.status = (
        VerificationLevelStatus.BLOCKED if has_critical else VerificationLevelStatus.PASSED
    )
    fired_sub_step_ids = {i["sub_step_id"] for i in issues}
    pass_evidence = build_pass_evidence_l1_5(
        applicant_accounts=primary_accounts,
        applicant_credit_score=(
            primary_data.get("credit_score") if primary_data else None
        ),
        co_applicant_accounts=co_accounts,
        co_applicant_credit_score=(
            co_data.get("credit_score") if co_data else None
        ),
        equifax_rows_found=len(equifax_rows),
        opus_evidence=opus_evidence,
        fired_rules=fired_sub_step_ids,
        applicant_bureau_art=applicant_bureau_art,
        coapp_bureau_art=coapp_bureau_art,
    )
    result.sub_step_results = {
        "applicant": {
            "credit_score": primary_data.get("credit_score"),
            "summary": primary_data.get("summary"),
            "accounts_count": len(primary_accounts),
            "customer_info": primary_data.get("customer_info"),
        }
        if primary_data
        else {},
        "co_applicant": {
            "credit_score": co_data.get("credit_score"),
            "summary": co_data.get("summary"),
            "accounts_count": len(co_accounts),
            "customer_info": co_data.get("customer_info"),
        }
        if co_data
        else {},
        "analyst": {k: v for k, v in analyst_data.items() if k != "usage"},
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
