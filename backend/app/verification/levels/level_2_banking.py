"""Level 2 — Banking + income (CA-grade MVP).

Phase B scope (this module): run the Claude-Haiku CA analyzer over the bank
statement transactions and apply five hard rules on its structured output:

- NACH / ECS bounces → CRITICAL
- Avg monthly balance < 1.5× proposed EMI → CRITICAL
- Three-month credit sum << 3× declared monthly income → WARNING
- Single credit payer with ≥₹15k declared income → WARNING (concentration)
- Impulsive debit total > declared monthly income → WARNING

Deferred to follow-ups (not in this commit): SystemCam ↔ CM CAM IL
discrepancy check (primary session's work), the Equifax-EMI timing match,
the "challenge the credit person" Q&A flow, and the learning-engine
precedents table.
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

_log = logging.getLogger(__name__)


# ───────────────────────────── Pure cross-checks ─────────────────────────────


def cross_check_nach_bounces(nach_bounce_count: int) -> dict[str, Any] | None:
    """Fire CRITICAL when the bank statement shows any NACH / ECS bounce.

    Even one prior EMI default is a strong recurrence signal — the rule
    is intentionally zero-tolerance and routes any bounce straight to MD
    approval. Returns ``None`` when the analyser found a clean account.
    """
    if nach_bounce_count <= 0:
        return None
    return {
        "sub_step_id": "nach_bounces",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"{nach_bounce_count} NACH / ECS bounce(s) detected in the bank "
            "statement. Prior EMI defaults are the single strongest predictor "
            "of repayment failure — MD approval required before disbursal."
        ),
    }


def cross_check_avg_balance_vs_emi(
    *,
    avg_monthly_balance_inr: int,
    proposed_emi_inr: int,
    multiplier: float = 1.5,
) -> dict[str, Any] | None:
    """Fire CRITICAL when avg monthly balance < ``multiplier`` × proposed EMI.

    Skips silently (returns ``None``) when no proposed EMI is on file —
    the upstream loan-amount-missing rule covers that scenario. The
    fired evidence includes the raw ratio so the FE's
    ``AvgBalanceVsEmiCard`` can render a numeric bar without recomputing.
    """
    if proposed_emi_inr <= 0:
        return None  # cannot run the rule without a proposed EMI
    if avg_monthly_balance_inr >= proposed_emi_inr * multiplier:
        return None
    return {
        "sub_step_id": "avg_balance_vs_emi",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"Avg monthly balance ₹{avg_monthly_balance_inr:,} is below "
            f"{multiplier}× the proposed EMI (₹{proposed_emi_inr:,}). "
            "The account will not reliably carry the NACH debit — risk of "
            "bounce + default."
        ),
        # Rule-specific fields the AvgBalanceVsEmiCard renders (Required
        # floor + ratio bar). These are CASE-level inputs not present in the
        # CA-analyzer's `ca_data`, so the orchestrator must MERGE this dict
        # rather than overwrite it with the analyzer payload.
        "evidence": {
            "avg_monthly_balance_inr": avg_monthly_balance_inr,
            "proposed_emi_inr": proposed_emi_inr,
            "multiplier": multiplier,
            "ratio": avg_monthly_balance_inr / proposed_emi_inr,
        },
    }


def cross_check_credits_vs_declared_income(
    *,
    three_month_credit_sum_inr: int,
    declared_monthly_income_inr: int,
    floor_ratio: float = 0.50,
) -> dict[str, Any] | None:
    """WARNING when 3-month bank credits cover < ``floor_ratio`` of declared income.

    Catches both income-overstatement and cash-only borrowers. The 50%
    default is a deliberately loose floor — rural microfinance customers
    legitimately keep some income out of the bank, but a sub-50% ratio
    means the bank statement isn't a reliable income view at all.
    """
    if declared_monthly_income_inr <= 0:
        return None
    expected_3m = declared_monthly_income_inr * 3
    if three_month_credit_sum_inr >= expected_3m * floor_ratio:
        return None
    return {
        "sub_step_id": "credits_vs_declared_income",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"3-month credits (₹{three_month_credit_sum_inr:,}) cover only "
            f"{three_month_credit_sum_inr / expected_3m:.0%} of the declared "
            f"₹{declared_monthly_income_inr:,}/month income. Either income is "
            "overstated or the borrower banks mostly in cash — re-verify."
        ),
    }


def cross_check_distinct_payer_concentration(
    *,
    distinct_credit_payers: int,
    declared_monthly_income_inr: int,
    min_income_for_rule_inr: int = 15_000,
) -> dict[str, Any] | None:
    """WARNING when income comes from a single payer above the income floor.

    Single-source dependence is a concentration-risk signal: if the
    payer pauses, repayment vanishes overnight. Skipped at low declared
    income because most micro-borrowers genuinely have one customer
    cluster and we'd flood the queue with non-actionable warnings.
    """
    if declared_monthly_income_inr < min_income_for_rule_inr:
        return None
    if distinct_credit_payers >= 2:
        return None
    return {
        "sub_step_id": "single_payer_concentration",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            "Income is concentrated from a single payer "
            f"({distinct_credit_payers} distinct payer(s) over the statement "
            f"period; declared income ₹{declared_monthly_income_inr:,}/month). "
            "If that source stops, repayment capacity vanishes. Consider "
            "reducing ticket size or requesting a second income-source "
            "attestation."
        ),
    }


def cross_check_impulsive_debits(
    *,
    impulsive_debit_total_inr: int,
    declared_monthly_income_inr: int,
) -> dict[str, Any] | None:
    """WARNING when impulsive / retail debits exceed one month of declared income.

    The CA analyser tags transactions as "impulsive" — gambling, online
    shopping, eating-out splurges. When that bucket alone overruns a
    full month of declared income, EMI discipline is at meaningful risk
    even before the loan EMI lands on the account.
    """
    if declared_monthly_income_inr <= 0:
        return None
    if impulsive_debit_total_inr <= declared_monthly_income_inr:
        return None
    return {
        "sub_step_id": "impulsive_debit_overspend",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"Impulsive / retail debits (₹{impulsive_debit_total_inr:,}) exceed "
            "one month of declared income. Borrower's discretionary spend is "
            "high — EMI discipline at risk."
        ),
    }


def cross_check_chronic_low_balance(
    avg_monthly_balance_inr: int,
    min_floor_inr: int = 1000,
) -> dict[str, Any] | None:
    """CRITICAL when the avg balance is pathologically low, regardless of EMI.

    Catches chronically-near-zero accounts that the EMI-comparison rule misses
    when loan_amount is null (the EMI defaults to 0 and the comparison skips).
    """
    if avg_monthly_balance_inr >= min_floor_inr:
        return None
    return {
        "sub_step_id": "chronic_low_balance",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"Avg monthly balance is only ₹{avg_monthly_balance_inr:,} — "
            "the account is chronically near zero and cannot sustain any "
            "meaningful EMI via NACH debit."
        ),
    }


def cross_check_statement_months_coverage(
    *,
    months_of_coverage: float | None,
    minimum_months: float = 6.0,
) -> dict[str, Any] | None:
    """CRITICAL when the bank statement spans fewer than ``minimum_months``.

    Returns ``None`` when ``months_of_coverage`` is ``None`` (extractor could
    not parse any dates) — the missing-statement check covers that scenario
    on its own; raising a second CRITICAL on the same input would just
    clutter the panel without giving the MD new information.
    """
    if months_of_coverage is None:
        return None
    if months_of_coverage >= minimum_months:
        return None
    deficit = round(max(0.0, minimum_months - months_of_coverage), 1)
    return {
        "sub_step_id": "bank_statement_months_coverage",
        "severity": LevelIssueSeverity.CRITICAL.value,
        "description": (
            f"Bank statement covers only {months_of_coverage:.1f} months — "
            f"policy minimum is {minimum_months:.0f} months "
            f"({deficit:.1f} more month(s) needed). Re-upload an earlier "
            "statement to extend the window, or seek MD approval to proceed "
            "on a shorter window with a documented justification."
        ),
    }


def cross_check_ca_narrative(ca_concerns: list[str]) -> dict[str, Any] | None:
    """Surface the Claude CA-analyzer's narrative concerns as a WARNING issue.

    Lets the assessor see the qualitative findings even when the hard-numeric
    rules above can't run (e.g., declared income missing on the case record).
    The bulleted concern list lives on the structured `evidence.ca_concerns`
    array — the CaNarrativeCard on the front-end renders it as its own block,
    so the description stays a single-line summary to avoid duplicating the
    same text twice on the same card.
    """
    if not ca_concerns:
        return None
    return {
        "sub_step_id": "ca_narrative_concerns",
        "severity": LevelIssueSeverity.WARNING.value,
        "description": (
            f"Claude CA analyser raised {len(ca_concerns)} qualitative "
            "concern(s) — see the Concerns / Positives breakdown below."
        ),
    }


# ───────────────────────────── Pass-evidence helper ────────────────────────
#
# Mirrors Part A's ``build_pass_evidence`` in level_3_vision. Populates
# ``sub_step_results.pass_evidence`` for every L2 rule that DIDN'T fire by
# slicing ``ca_data`` per rule. ``source_artifacts`` always cites the bank
# statement PDF on the same fire-path shape so the FE's
# LevelSourceFilesPanel aggregates passes + concerns.
#
# Key naming: MUST match the rule's ``sub_step_id`` in RULE_CATALOG exactly.


# Rule-level constants (re-used by the fire path). Keeping them centralised
# prevents drift between the cross_check_* signatures and the pass evidence.
_L2_AVG_BAL_MULTIPLIER = 1.5
_L2_CREDITS_FLOOR_RATIO = 0.50
_L2_SINGLE_PAYER_MIN_INCOME = 15_000
_L2_CHRONIC_BAL_FLOOR = 1_000


def _l2_bank_sources(
    bank_art: CaseArtifact | None, *, highlight_field: str
) -> list[dict[str, Any]]:
    """Build the standard ``source_artifacts`` list pointing at the bank statement.

    Returns an empty list when no statement was uploaded so callers can
    splat the result unconditionally. ``highlight_field`` (e.g.
    ``avg_balance``, ``nach_bounces``) feeds the FE's "View source"
    button so it can deep-link to the right transaction cluster.
    """
    if bank_art is None:
        return []
    return _pack(
        _ref(
            bank_art,
            relevance="Bank statement — transaction log",
            highlight_field=highlight_field,
        ),
    )


def build_pass_evidence_l2(
    *,
    ca_data: dict[str, Any],
    declared_income: int,
    proposed_emi: int,
    tx_line_count: int,
    bank_art: CaseArtifact | None,
    fired_rules: set[str],
    months_of_coverage: float | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Return the ``sub_step_results.pass_evidence`` dict for L2.

    One entry per L2 ``sub_step_id`` in ``RULE_CATALOG.L2_BANKING`` that
    passed. Each entry slices ``ca_data`` for the specific fields the rule
    judges against and mirrors the threshold constants the fire path uses.

    Skipping rule: an entry is omitted when its required input is missing
    (e.g. ``avg_balance_vs_emi`` needs a non-zero ``proposed_emi`` — the
    fire-path short-circuits to None in the same scenario, so the pass-
    side shouldn't invent one).
    """
    out: dict[str, Any] = {}

    # bank_statement_missing — narrated on the pass side as extraction_status=ok
    if "bank_statement_missing" not in fired_rules:
        out["bank_statement_missing"] = {
            "extraction_status": "ok",
            "tx_line_count": tx_line_count,
            "source_artifacts": _l2_bank_sources(
                bank_art, highlight_field="transactions"
            ),
        }

    # bank_statement_months_coverage — passes when ≥6 months of transactions
    if "bank_statement_months_coverage" not in fired_rules:
        if months_of_coverage is None:
            out["bank_statement_months_coverage"] = {
                "skipped_reason": (
                    "extractor could not parse transaction dates (older "
                    "extraction or unusual date format)"
                ),
            }
        else:
            out["bank_statement_months_coverage"] = {
                "available_months": months_of_coverage,
                "required_months": 6.0,
                "period_start": period_start,
                "period_end": period_end,
                "tx_line_count": tx_line_count,
                "source_artifacts": _l2_bank_sources(
                    bank_art, highlight_field="period"
                ),
            }

    # nach_bounces — passes when count is 0
    if "nach_bounces" not in fired_rules:
        out["nach_bounces"] = {
            "nach_bounce_count": int(ca_data.get("nach_bounce_count") or 0),
            "nach_bounces": list(ca_data.get("nach_bounces") or []),
            "source_artifacts": _l2_bank_sources(
                bank_art, highlight_field="nach_bounces"
            ),
        }

    # avg_balance_vs_emi — needs avg_monthly_balance_inr AND a non-zero EMI
    if "avg_balance_vs_emi" not in fired_rules:
        avg_bal_raw = ca_data.get("avg_monthly_balance_inr")
        if avg_bal_raw is None:
            out["avg_balance_vs_emi"] = {
                "skipped_reason": "ca_analyser did not surface avg_monthly_balance_inr",
            }
        elif proposed_emi <= 0:
            out["avg_balance_vs_emi"] = {
                "skipped_reason": "no proposed EMI on file",
            }
        else:
            avg_bal = int(avg_bal_raw)
            out["avg_balance_vs_emi"] = {
                "avg_monthly_balance_inr": avg_bal,
                "proposed_emi_inr": proposed_emi,
                "multiplier": _L2_AVG_BAL_MULTIPLIER,
                "ratio": avg_bal / proposed_emi,
                "source_artifacts": _l2_bank_sources(
                    bank_art, highlight_field="avg_balance"
                ),
            }

    # credits_vs_declared_income — needs three_month_credit_sum_inr AND
    # declared_monthly_income_inr > 0
    if "credits_vs_declared_income" not in fired_rules:
        three_m_sum_raw = ca_data.get("three_month_credit_sum_inr")
        if declared_income <= 0:
            out["credits_vs_declared_income"] = {
                "skipped_reason": "no declared monthly income on file",
            }
        elif three_m_sum_raw is None:
            out["credits_vs_declared_income"] = {
                "skipped_reason": "ca_analyser did not surface three_month_credit_sum_inr",
            }
        else:
            three_m = int(three_m_sum_raw)
            expected_3m = declared_income * 3
            out["credits_vs_declared_income"] = {
                "three_month_credit_sum_inr": three_m,
                "declared_monthly_income_inr": declared_income,
                "floor_ratio": _L2_CREDITS_FLOOR_RATIO,
                "ratio": three_m / expected_3m,
                "source_artifacts": _l2_bank_sources(
                    bank_art, highlight_field="credits"
                ),
            }

    # single_payer_concentration — rule only runs above the income floor
    if "single_payer_concentration" not in fired_rules:
        if declared_income < _L2_SINGLE_PAYER_MIN_INCOME:
            out["single_payer_concentration"] = {
                "skipped_reason": (
                    f"rule only runs at declared income ≥ ₹{_L2_SINGLE_PAYER_MIN_INCOME:,}; "
                    f"this case is at ₹{declared_income:,}"
                ),
            }
        else:
            out["single_payer_concentration"] = {
                "distinct_credit_payers": int(
                    ca_data.get("distinct_credit_payers") or 0
                ),
                "declared_monthly_income_inr": declared_income,
                "min_income_for_rule_inr": _L2_SINGLE_PAYER_MIN_INCOME,
                "source_artifacts": _l2_bank_sources(
                    bank_art, highlight_field="credit_payers"
                ),
            }

    # impulsive_debit_overspend — needs declared_income > 0
    if "impulsive_debit_overspend" not in fired_rules:
        impulsive_raw = ca_data.get("impulsive_debit_total_inr")
        if declared_income <= 0:
            out["impulsive_debit_overspend"] = {
                "skipped_reason": "no declared monthly income on file",
            }
        elif impulsive_raw is None:
            out["impulsive_debit_overspend"] = {
                "skipped_reason": "ca_analyser did not surface impulsive_debit_total_inr",
            }
        else:
            out["impulsive_debit_overspend"] = {
                "impulsive_debit_total_inr": int(impulsive_raw),
                "declared_monthly_income_inr": declared_income,
                "source_artifacts": _l2_bank_sources(
                    bank_art, highlight_field="impulsive_debits"
                ),
            }

    # chronic_low_balance — judged purely on avg balance
    if "chronic_low_balance" not in fired_rules:
        avg_bal_raw = ca_data.get("avg_monthly_balance_inr")
        if avg_bal_raw is None:
            out["chronic_low_balance"] = {
                "skipped_reason": "ca_analyser did not surface avg_monthly_balance_inr",
            }
        else:
            out["chronic_low_balance"] = {
                "avg_monthly_balance_inr": int(avg_bal_raw),
                "min_floor_inr": _L2_CHRONIC_BAL_FLOOR,
                "source_artifacts": _l2_bank_sources(
                    bank_art, highlight_field="avg_balance"
                ),
            }

    # ca_narrative_concerns — passes when concerns list is empty
    if "ca_narrative_concerns" not in fired_rules:
        out["ca_narrative_concerns"] = {
            "ca_concerns": list(ca_data.get("ca_concerns") or []),
            "ca_positives": list(ca_data.get("ca_positives") or []),
            "overall_verdict": "clean",
            "source_artifacts": _l2_bank_sources(
                bank_art, highlight_field="concerns"
            ),
        }

    return out


def estimate_proposed_emi_inr(
    *, loan_amount_inr: int | None, tenure_months: int | None, annual_rate_pct: float = 24.0
) -> int:
    """Flat-rate EMI estimate for rural microfinance.

    flat-rate EMI = (principal + principal * rate * tenure/12) / tenure

    Returns 0 if either input is missing — calling rule-helpers will skip.
    """
    if not loan_amount_inr or not tenure_months or tenure_months <= 0:
        return 0
    total_interest = loan_amount_inr * (annual_rate_pct / 100.0) * (tenure_months / 12.0)
    return int((loan_amount_inr + total_interest) / tenure_months)


# ─────────────────────────────── Orchestrator ────────────────────────────────


async def run_level_2_banking(
    session: AsyncSession,
    case_id: UUID,
    *,
    actor_user_id: UUID,
    claude: Any,
) -> VerificationResult:
    """Run Level 2 on ``case_id`` and persist the result + issues.

    Reads the latest ``bank_statement`` extraction for the case, fetches
    declared monthly income from SystemCam (if extracted), estimates EMI from
    the case's loan amount + tenure, calls the Claude-Haiku CA analyzer, and
    applies the five pure rules above.
    """
    from app.verification.services.bank_ca_analyzer import BankCaAnalyzer

    started = datetime.now(UTC)
    result = VerificationResult(
        case_id=case_id,
        level_number=VerificationLevelNumber.L2_BANKING,
        status=VerificationLevelStatus.RUNNING,
        started_at=started,
        triggered_by=actor_user_id,
    )
    session.add(result)
    await session.flush()

    # Pull bank statement extraction (M3)
    bank_ext = (
        await session.execute(
            select(CaseExtraction)
            .where(CaseExtraction.case_id == case_id)
            .where(CaseExtraction.extractor_name == "bank_statement")
            .order_by(CaseExtraction.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    cam_ext = (
        await session.execute(
            select(CaseExtraction)
            .where(CaseExtraction.case_id == case_id)
            .where(CaseExtraction.extractor_name == "auto_cam")
            .order_by(CaseExtraction.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    case = await session.get(Case, case_id)

    # Bank statement artefact — used below to annotate every issue so the MD
    # can open the PDF. First-match on subtype (BANK_STATEMENT).
    all_artifacts = (
        (await session.execute(select(CaseArtifact).where(CaseArtifact.case_id == case_id)))
        .scalars()
        .all()
    )
    bank_art: CaseArtifact | None = next(
        (
            a for a in all_artifacts
            if (a.metadata_json or {}).get("subtype") == ArtifactSubtype.BANK_STATEMENT.value
        ),
        None,
    )

    issues: list[dict[str, Any]] = []
    ca_data: dict[str, Any] = {}
    total_cost = Decimal("0")

    tx_lines: list[str] = []
    months_of_coverage: float | None = None
    period_start: str | None = None
    period_end: str | None = None
    extraction_status: str | None = None
    extraction_warnings: list[str] = []
    if bank_ext and bank_ext.data:
        raw = bank_ext.data.get("transaction_lines") or []
        if isinstance(raw, list):
            tx_lines = [str(x) for x in raw]
        moc_raw = bank_ext.data.get("months_of_coverage")
        if isinstance(moc_raw, (int, float)):
            months_of_coverage = float(moc_raw)
        ps_raw = bank_ext.data.get("period_start")
        if isinstance(ps_raw, str):
            period_start = ps_raw
        pe_raw = bank_ext.data.get("period_end")
        if isinstance(pe_raw, str):
            period_end = pe_raw
        extraction_status = bank_ext.status.value if bank_ext.status else None
        warnings_raw = bank_ext.warnings or []
        if isinstance(warnings_raw, list):
            extraction_warnings = [str(w) for w in warnings_raw]
    if not tx_lines:
        # Distinguish three failure shapes for the MD:
        #   - extraction never ran        → "No extraction available"
        #   - extraction ran, 0 tx lines  → "Parsed 0 transactions"
        #   - extraction ran, errored     → status=FAILED + warnings
        if bank_ext is None:
            description = (
                "No bank statement extraction available for this case. "
                "Upload a 6-month bank statement PDF and re-ingest."
            )
        elif extraction_status == "FAILED":
            description = (
                "Bank statement upload could not be parsed by the PDF "
                "extractor — the file is likely image-based (scan), "
                "password-protected, or corrupted. Re-upload a text-PDF "
                "statement (downloaded directly from net-banking) or seek "
                "MD approval to proceed."
            )
        else:
            description = (
                "Bank statement uploaded but the extractor recovered 0 "
                "transaction lines — the date format on this statement is "
                "not recognised. Re-upload a different statement format "
                "(text PDF from net-banking is preferred) or seek MD "
                "approval to proceed."
            )
        iss_missing: dict[str, Any] = {
            "sub_step_id": "bank_statement_missing",
            "severity": LevelIssueSeverity.CRITICAL.value,
            "description": description,
            "evidence": {
                "expected_subtype": ArtifactSubtype.BANK_STATEMENT.value,
                "tx_line_count": 0,
                "extraction_status": extraction_status,
                "extraction_warnings": extraction_warnings,
            },
        }
        # When the file WAS uploaded but PARTIAL-with-zero-tx (Kotak parser
        # issue for example), cite the broken PDF so the MD can eyeball it.
        if bank_art is not None:
            iss_missing["evidence"]["source_artifacts"] = _pack(
                _ref(
                    bank_art,
                    relevance="Bank statement — upload that failed parsing",
                    highlight_field="transactions",
                ),
            )
        issues.append(iss_missing)

    # Resolve declared income (CAM system_cam.total_monthly_income if present,
    # else fall back to 0 which disables the income-based rules)
    declared_income: int = 0
    if cam_ext and cam_ext.data:
        sc = cam_ext.data.get("system_cam") or {}
        for key in (
            "total_monthly_income",
            "monthly_income",
            "declared_monthly_income",
        ):
            v = sc.get(key)
            if isinstance(v, (int, float)) and v > 0:
                declared_income = int(v)
                break

    declared_foir_pct: float = 0.0
    if cam_ext and cam_ext.data:
        for key in ("foir", "foir_pct"):
            v = (cam_ext.data.get("eligibility") or {}).get(key)
            if isinstance(v, (int, float)) and v > 0:
                declared_foir_pct = float(v)
                break

    loan_amount = getattr(case, "loan_amount", None) if case else None
    tenure_months = getattr(case, "loan_tenure_months", None) if case else None
    proposed_emi = estimate_proposed_emi_inr(
        loan_amount_inr=int(loan_amount) if loan_amount else None,
        tenure_months=int(tenure_months) if tenure_months else None,
    )

    if tx_lines:
        # Months-of-coverage gate runs BEFORE the CA analyser so it surfaces
        # even when the analyser later errors out (we still owe the user a
        # clear "X months available, Y more needed" prompt).
        coverage_iss = cross_check_statement_months_coverage(
            months_of_coverage=months_of_coverage,
        )
        if coverage_iss is not None:
            coverage_iss["evidence"] = {
                "available_months": months_of_coverage,
                "required_months": 6.0,
                "deficit_months": round(
                    max(0.0, 6.0 - (months_of_coverage or 0.0)), 1
                ),
                "period_start": period_start,
                "period_end": period_end,
                "tx_line_count": len(tx_lines),
                "source_artifacts": _l2_bank_sources(
                    bank_art, highlight_field="period"
                ),
            }
            issues.append(coverage_iss)

        analyzer = BankCaAnalyzer(claude=claude)
        ca_res = await analyzer.analyze(
            tx_lines=tx_lines,
            declared_monthly_income_inr=declared_income,
            declared_foir_pct=declared_foir_pct,
            proposed_emi_inr=proposed_emi,
        )
        ca_data = ca_res.data
        total_cost += Decimal(str(ca_data.get("cost_usd") or "0"))
        if ca_res.error_message:
            issues.append(
                {
                    "sub_step_id": "ca_analyzer_failed",
                    "severity": LevelIssueSeverity.CRITICAL.value,
                    "description": f"CA analyser failed: {ca_res.error_message}",
                    "evidence": {
                        "error_message": ca_res.error_message,
                        "tx_line_count": len(tx_lines),
                        # Cite the bank statement PDF so the MD panel's
                        # "View source" button opens the file the analyser
                        # was attempting to read when it failed.
                        "source_artifacts": _pack(
                            _ref(
                                bank_art,
                                relevance="Bank statement (analyser attempt)",
                                highlight_field="transactions",
                            )
                        ),
                    },
                }
            )
        else:
            for rule in (
                lambda: cross_check_nach_bounces(int(ca_data.get("nach_bounce_count") or 0)),
                lambda: cross_check_avg_balance_vs_emi(
                    avg_monthly_balance_inr=int(ca_data.get("avg_monthly_balance_inr") or 0),
                    proposed_emi_inr=proposed_emi,
                ),
                lambda: cross_check_chronic_low_balance(
                    int(ca_data.get("avg_monthly_balance_inr") or 0),
                ),
                lambda: cross_check_credits_vs_declared_income(
                    three_month_credit_sum_inr=int(ca_data.get("three_month_credit_sum_inr") or 0),
                    declared_monthly_income_inr=declared_income,
                ),
                lambda: cross_check_distinct_payer_concentration(
                    distinct_credit_payers=int(ca_data.get("distinct_credit_payers") or 0),
                    declared_monthly_income_inr=declared_income,
                ),
                lambda: cross_check_impulsive_debits(
                    impulsive_debit_total_inr=int(ca_data.get("impulsive_debit_total_inr") or 0),
                    declared_monthly_income_inr=declared_income,
                ),
                lambda: cross_check_ca_narrative(ca_data.get("ca_concerns") or []),
            ):
                iss = rule()
                if iss:
                    # Merge (don't overwrite) — preserve any rule-specific
                    # evidence the cross_check_* function emitted (e.g.
                    # avg_balance_vs_emi carries proposed_emi_inr + multiplier
                    # which aren't in ca_data) on top of the analyzer payload.
                    rule_ev = iss.pop("evidence", None) or {}
                    iss["evidence"] = {
                        **{
                            k: v
                            for k, v in ca_data.items()
                            if k not in ("usage",)
                        },
                        **rule_ev,
                    }
                    # Every L2 rule is backed by the same bank-statement PDF
                    # — cite it with a sub-step-specific highlight hint so
                    # a future extraction pass can pinpoint the offending row.
                    iss["evidence"]["source_artifacts"] = _pack(
                        _ref(
                            bank_art,
                            relevance="Bank statement — transaction log",
                            highlight_field={
                                "nach_bounces": "nach_bounces",
                                "avg_balance_vs_emi": "avg_balance",
                                "chronic_low_balance": "avg_balance",
                                "credits_vs_declared_income": "credits",
                                "single_payer_concentration": "credit_payers",
                                "impulsive_debit_overspend": "impulsive_debits",
                                "ca_narrative_concerns": "concerns",
                            }.get(iss["sub_step_id"], "transactions"),
                        ),
                    )
                    issues.append(iss)

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
    pass_evidence = build_pass_evidence_l2(
        ca_data=ca_data,
        declared_income=declared_income,
        proposed_emi=proposed_emi,
        tx_line_count=len(tx_lines),
        bank_art=bank_art,
        fired_rules=fired_sub_step_ids,
        months_of_coverage=months_of_coverage,
        period_start=period_start,
        period_end=period_end,
    )
    result.sub_step_results = {
        "ca_analyser": {k: v for k, v in ca_data.items() if k != "usage"},
        "declared_monthly_income_inr": declared_income,
        "declared_foir_pct": declared_foir_pct,
        "proposed_emi_inr": proposed_emi,
        "tx_line_count": len(tx_lines),
        "months_of_coverage": months_of_coverage,
        "period_start": period_start,
        "period_end": period_end,
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
