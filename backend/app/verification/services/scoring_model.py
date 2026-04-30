"""PFL 32-Point Scoring Model — the final NBFC FINPAGE Individual Loan Audit.

Mirrors the ops team's "32 Point Scoring Model Draft.xlsx":

- Section A · Credit Assessment & Eligibility (45 pts, 13 items)
- Section B · QR and Banking Check             (35 pts, 11 items)
- Section C · Assets & Living Standard         (13 pts,  5 items)
- Section D · Reference Checks & TVR           ( 7 pts,  3 items)
- Total: 100 pts

Each parameter carries its weight, the role responsible, and a resolver
that reads existing extractions + verification results to auto-fill
(Status, Score, Evidence). Parameters where no signal is available yet
are returned with status=``PENDING`` and score 0 — the assessor then
supplies the value manually before the final report is generated.

This module is pure-Python and deterministic (no Claude call). The
L5 engine wires these resolvers up + adds an optional Opus fallback
pass for PENDING items that might be recoverable from artifact OCR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from uuid import UUID

from app.enums import VerificationLevelNumber


# ── Types ────────────────────────────────────────────────────────────────────


Status = Literal["PASS", "FAIL", "PENDING", "NA"]


@dataclass
class ScoreRow:
    """Result for one scoring parameter."""

    sno: int
    section: str
    parameter: str
    expected: str
    weight: int
    role: str
    status: Status
    score: int
    evidence: str = ""
    remarks: str = ""
    # Populated by the L5 orchestrator AFTER scoring for rows that pass on
    # subtype-presence (e.g. #28 Business Ownership Proof). Same shape as
    # other levels' source_artifacts: {artifact_id, filename, relevance}.
    # Lets the FE render the actual file behind a "PASS" verdict instead of
    # showing "Source files not yet attached for this rule."
    source_artifacts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SectionScore:
    section_id: str
    title: str
    max_score: int
    earned: int
    rows: list[ScoreRow] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return (self.earned / self.max_score * 100.0) if self.max_score else 0.0


@dataclass
class ScoringResult:
    sections: list[SectionScore]
    eb_verdict: str = "PASS"  # PASS / CONCERN / FAIL — Eligibility vs Banking
    deviation_count: int = 0
    critical_deviation_count: int = 0

    @property
    def max_score(self) -> int:
        return sum(s.max_score for s in self.sections)

    @property
    def earned_score(self) -> int:
        return sum(s.earned for s in self.sections)

    @property
    def overall_pct(self) -> float:
        return (self.earned_score / self.max_score * 100.0) if self.max_score else 0.0

    @property
    def grade(self) -> str:
        """
        ≥90  A+ — low risk, fast-track
        ≥80  A  — standard approval
        ≥70  B  — MD review
        ≥60  C  — high risk, restructure
        <60  D  — reject
        """
        p = self.overall_pct
        if p >= 90:
            return "A+"
        if p >= 80:
            return "A"
        if p >= 70:
            return "B"
        if p >= 60:
            return "C"
        return "D"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [
                {
                    "section_id": s.section_id,
                    "title": s.title,
                    "max_score": s.max_score,
                    "earned": s.earned,
                    "pct": round(s.pct, 1),
                    "rows": [r.__dict__ for r in s.rows],
                }
                for s in self.sections
            ],
            "max_score": self.max_score,
            "earned_score": self.earned_score,
            "overall_pct": round(self.overall_pct, 1),
            "grade": self.grade,
            "eb_verdict": self.eb_verdict,
            "deviation_count": self.deviation_count,
            "critical_deviation_count": self.critical_deviation_count,
        }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _gnum(d: Any, *path: str) -> float | None:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if cur is None or cur == "":
        return None
    try:
        return float(cur)
    except (TypeError, ValueError):
        return None


def _gint(d: Any, *path: str) -> int | None:
    v = _gnum(d, *path)
    return int(v) if v is not None else None


def _gstr(d: Any, *path: str) -> str | None:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if cur is None:
        return None
    s = str(cur).strip()
    return s or None


@dataclass
class ScoringContext:
    """Everything the resolvers can read. All keys are optional; resolvers
    must handle None gracefully and downgrade to status=PENDING."""

    # CAM
    auto_cam: dict[str, Any] | None = None  # best/multi-sheet payload
    # Bureau
    primary_equifax: dict[str, Any] | None = None
    coapp_equifax: dict[str, Any] | None = None
    # Banking CA analyser output (from L2)
    bank_ca: dict[str, Any] | None = None
    # L3 Vision biz + house data
    l3_house: dict[str, Any] | None = None
    l3_business: dict[str, Any] | None = None
    # L4 agreement
    l4_scanner: dict[str, Any] | None = None
    # Artifacts
    artifact_subtypes: set[str] = field(default_factory=set)
    # Case
    applicant_name: str | None = None
    co_applicant_name: str | None = None
    loan_amount_inr: int | None = None
    tenure_months: int | None = None
    proposed_emi_inr: int | None = None
    # L1 verification result (for address match)
    l1_gps_match_verdict: str | None = None
    # Every L1-flagged issue keyed by sub_step_id → {severity, status}. Lets
    # L5 rubric resolvers ask "did L1's aadhaar_vs_bureau_address fire?"
    # rather than re-running the check. Empty dict when L1 passed cleanly.
    l1_issues_by_step: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Union of L1..L4 issues, same shape, for resolvers that need a
    # cross-level view (deviation-approved, section-B status, …).
    all_level_issues: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Latest ``VerificationResult.id`` per level for this case. Lets
    # resolvers distinguish "level ran and passed" (level key present,
    # but no flagging issue) from "level never ran" (key absent) — the
    # latter must stay PENDING rather than silently PASS.
    latest_vr_by_level: dict[VerificationLevelNumber, UUID] = field(
        default_factory=dict
    )
    # Whether the assessor has already manually marked any rows
    manual_overrides: dict[int, dict[str, Any]] = field(default_factory=dict)
    # Negative-area lookup: applicant pincode + whether it appears on the
    # active /admin/negative-areas list. Both pre-resolved by the orchestrator
    # so r_a11 can stay a pure function.
    case_pincode: str | None = None
    case_pincode_in_negative_list: bool | None = None
    # Free-text reason from the negative-area row, surfaced in the FAIL evidence.
    negative_area_reason: str | None = None
    # Opus-4.7 income-proof analysis (see services/income_proof_analyzer.py).
    # When the L5 orchestrator finds income-proof artifacts on the case AND
    # a declared CAM income, it runs the analyzer and stuffs the structured
    # result here. Powers row #16 (proof accuracy verdict) and row #18
    # (distinct-income-sources count). None when the analyzer didn't run
    # (no proof artifacts uploaded, or storage fetch failed).
    income_proof_analysis: dict[str, Any] | None = None


# ── Scoring primitives ───────────────────────────────────────────────────────


def _pass(weight: int, evidence: str = "", remarks: str = "") -> tuple[Status, int, str, str]:
    return ("PASS", weight, evidence, remarks)


def _fail(weight: int, evidence: str = "", remarks: str = "") -> tuple[Status, int, str, str]:
    return ("FAIL", 0, evidence, remarks)


def _pending(weight: int, remarks: str = "Assessor must fill manually") -> tuple[Status, int, str, str]:
    return ("PENDING", 0, "", remarks)


def _graded(status_score: int, weight: int, evidence: str, remarks: str) -> tuple[Status, int, str, str]:
    """For graded rules (DSCR, ABB) where the score is the raw graded value."""
    return ("PASS" if status_score > 0 else "FAIL", status_score, evidence, remarks)


# ── Section A resolvers (13 params, 45 pts) ─────────────────────────────────


def r_a01_household_income(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Total Household Income — declared in CAM, cross-verified against the
    bank statement's 3-month credit inflow.

    Trusting the CAM number blindly was the prior behaviour; in practice an
    inflated declared income with a thin bank statement is exactly the
    pattern that needs MD attention. We mirror the L2
    ``credits_vs_declared_income`` floor (3M credits ≥ 50% of 3× declared)
    here so row #1 itself flags the inconsistency rather than passing
    silently and leaving the proof check buried in L2.
    """
    inc = _gint(ctx.auto_cam, "cm_cam_il", "total_monthly_income") or _gint(
        ctx.auto_cam, "system_cam", "total_household_income"
    )
    if inc is None:
        return _pending(w, "Not in CAM — credit manager to enter.")
    evidence = f"Total monthly household income ₹{inc:,} (from CAM)."

    # Bank-credit cross-check. Only kicks in when both numbers are present;
    # if the bank statement isn't extracted yet we fall through to a clean
    # PASS rather than blocking on missing infrastructure.
    bank_3m = _gnum(ctx.bank_ca, "three_month_credit_sum_inr")
    if bank_3m is not None and inc > 0:
        expected_3m = inc * 3
        floor = expected_3m * 0.50
        if bank_3m < floor:
            shortfall_pct = (1 - bank_3m / expected_3m) * 100 if expected_3m else 0
            implied_monthly = bank_3m / 3
            return _pending(
                w,
                (
                    f"Income proof inadequate: 3-month bank credits "
                    f"₹{int(bank_3m):,} (~₹{int(implied_monthly):,}/mo) cover "
                    f"only {bank_3m / expected_3m:.0%} of declared "
                    f"₹{inc:,}/mo × 3 = ₹{int(expected_3m):,}; shortfall "
                    f"~{shortfall_pct:.0f}%. Assessor to record the "
                    "justification (cash income, additional account, "
                    "household earner, …) and route to MD for approval."
                ),
            )
        return _pass(
            w,
            evidence
            + f" Bank credits ₹{int(bank_3m):,} over 3 months corroborate at "
            f"{bank_3m / expected_3m:.0%} of declared.",
            "CAM income corroborated by bank statement.",
        )

    return _pass(w, evidence, "Verified by CAM Sheet.")


def r_a02_business_vintage(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    # Not directly extracted in current AutoCAM schema — check free-text.
    # The Indian CAM typically has "Vintage of Business: 5 Yrs." in CM CAM IL.
    # We mark PENDING until extractor captures it.
    return _pending(w, "Business vintage not extracted — assessor to confirm from CAM.")


def r_a03_applicant_cibil(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    score = _gint(ctx.primary_equifax, "credit_score") or _gint(
        ctx.auto_cam, "eligibility", "cibil_score"
    ) or _gint(ctx.auto_cam, "cm_cam_il", "cibil")
    if score is None or score < 0:
        return _pending(w, "Credit score not available — verify bureau hit.")
    evidence = f"Applicant CIBIL score = {score}."
    if score >= 750:
        return _pass(w, evidence, "≥750 pass.")
    return _fail(w, evidence, "Below 750 — CRO rejection threshold.")


def r_a04_coapp_cibil(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Rubric: Co-App CIBIL Checked.

    "Checked & recorded" means a real bureau hit. Score -1 / 0 / -888 are
    Equifax sentinels for "no credit footprint / credit-invisible" — they
    do NOT satisfy the rubric (the co-app still needs a bureau hit or
    independent income corroboration). Treat them as NA rather than PASS
    so the section drop is visible instead of hidden as a false 3 points.
    """
    if not ctx.co_applicant_name:
        return ("NA", w, "No co-applicant on file.", "Not applicable.")
    score = _gint(ctx.coapp_equifax, "credit_score")
    if score is None:
        return _fail(
            w,
            f"Co-applicant {ctx.co_applicant_name}: no bureau report pulled.",
            "Co-app bureau check missing.",
        )
    # Equifax returns -1 (or very small negatives) for thin-file / credit-
    # invisible borrowers. That's a distinct signal from a real low score
    # and should not count as "checked + good".
    if score < 300:
        return (
            "NA",
            w,
            f"Co-applicant {ctx.co_applicant_name} is credit-invisible "
            f"(bureau score = {score}, zero trade lines).",
            "No credit footprint — cannot score; requires independent "
            "repayment / income corroboration.",
        )
    return _pass(w, f"Co-applicant CIBIL = {score} (checked).", "Co-app bureau checked.")


def r_a05_unsecured_outstanding(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    bal_raw = _gstr(ctx.primary_equifax, "summary", "total_outstanding_balance")
    if bal_raw is None:
        # Numeric fallback — some extractors surface this as a number.
        num = _gnum(ctx.primary_equifax, "summary", "total_outstanding_balance")
        if num is None:
            return _pending(w, "Bureau outstanding balance not captured.")
        bal_raw = str(int(num))
    # Normalise "0.00" / "₹0" / "0" to a clean "0" so the PASS evidence
    # doesn't read "₹0.00" (reads as a missing field to the MD).
    try:
        bal_int = int(float(bal_raw.replace(",", "").replace("₹", "").strip()))
        bal_display = f"₹{bal_int:,}"
    except (ValueError, AttributeError):
        bal_display = f"₹{bal_raw}"
    return _pass(
        w,
        f"Bureau total outstanding balance: {bal_display}.",
        "Captured from credit bureau.",
    )


def r_a06_dpd_12m(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    past_due = _gint(ctx.primary_equifax, "summary", "past_due_accounts")
    if past_due is None:
        return _pending(w, "Past-due count not captured by bureau extractor.")
    if past_due == 0:
        return _pass(w, "0 past-due accounts on bureau.", "No DPD in last 12 months.")
    return _fail(
        w,
        f"{past_due} past-due accounts on bureau.",
        "DPD present in last 12 months — CRO must review.",
    )


_WO_PAT = re.compile(r"\b(wo|write[-\s]*off|lss|loss|settled|compromised)\b", re.IGNORECASE)


def r_a07_writeoff_settled_3y(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    accounts = (ctx.primary_equifax or {}).get("accounts") or []
    hits = [a for a in accounts if _WO_PAT.search(str(a.get("status") or ""))]
    if not hits:
        return _pass(w, "No WO / LSS / SETTLED accounts on bureau.", "Clean in last 3 years.")
    inst = ", ".join((a.get("institution") or a.get("lender") or "?") for a in hits[:3])
    return _fail(
        w,
        f"{len(hits)} flagged account(s): {inst}.",
        "Write-off / settled detected — willful-default indicator.",
    )


def r_a08_enquiries_3m(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Rubric #8 — fewer than 3 credit-bureau enquiries in the last 3 MONTHS.

    The previous implementation counted *every* enquiry on the bureau report
    (``len(enqs) < 3``), which misread the rule: a clean applicant with 4
    historic enquiries (e.g. one each year over the last 4 years) was
    failing as "credit-hungry" while a fresh credit-card runner with 2
    enquiries this week passed. The rule's intent — and the rubric label
    "(3M)" — is a recency window, not a lifetime count. Filter by date
    and count only enquiries within the last 3 months.
    """
    from datetime import UTC, datetime, timedelta

    enqs = (ctx.primary_equifax or {}).get("enquiries") or []
    if not enqs:
        count = (
            _gint(ctx.primary_equifax, "summary", "enquiries_last_3_months")
            or _gint(ctx.primary_equifax, "summary", "enquiries_3m")
            or _gint(ctx.primary_equifax, "summary", "enquiry_count_3m")
        )
        if count is not None:
            if count < 3:
                return _pass(
                    w,
                    f"{count} enquiries in last 3 months (per bureau summary).",
                    "Under 3 threshold.",
                )
            return _fail(
                w,
                f"{count} enquiries in last 3 months (per bureau summary).",
                "≥3 enquiries — credit-hungry signal.",
            )
        # A bureau hit with zero enquiries captured + no summary count
        # more likely means the applicant has no recent enquiries than
        # that extraction silently failed — pass if we have a scored
        # bureau record at all.
        if ctx.primary_equifax and _gint(ctx.primary_equifax, "credit_score") is not None:
            return _pass(
                w,
                "Bureau report has no enquiries logged.",
                "No recent enquiries — credit-calm applicant.",
            )
        return _pending(w, "Enquiry list not extracted; verify manually from CB report.")

    # Structured-list path. Filter by date so the rule honours its 3-month
    # window. Bureau enquiry dates come in two flavours:
    #   - DMY: 29-06-2025, 29/06/2025
    #   - YMD: 2025-06-29
    # Be permissive on parse (return None on failure → the row is excluded
    # from the recent count, NOT counted as recent).
    cutoff = datetime.now(UTC).date() - timedelta(days=92)  # ≈ 3 months

    def _parse(date_str: Any) -> Any:
        if not isinstance(date_str, str) or not date_str.strip():
            return None
        s = date_str.strip()
        for sep in ("-", "/", "."):
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
                except ValueError:
                    return None
                # YMD when the first component is 4 digits
                if a > 31:
                    try:
                        from datetime import date as _date
                        return _date(a, b, c)
                    except ValueError:
                        return None
                # DMY otherwise (Indian default).
                # 2-digit year heuristic: ``< 80`` → 20xx, ``≥ 80`` → 19xx.
                # Picks 1980 as the pivot because no real bureau enquiry pre-
                # dates that, and dates 80 years in the future would be
                # nonsense — keeps both bureau dumps and bad OCR safe.
                year = c if c >= 100 else (2000 + c if c < 80 else 1900 + c)
                try:
                    from datetime import date as _date
                    return _date(year, b, a)
                except ValueError:
                    return None
        return None

    recent_count = 0
    parseable = 0
    for e in enqs:
        if not isinstance(e, dict):
            continue
        d = _parse(e.get("date"))
        if d is None:
            continue
        parseable += 1
        if d >= cutoff:
            recent_count += 1

    # If no enquiry had a parseable date, the structured list is unreliable
    # — fall back to the conservative "total count" interpretation rather
    # than silently passing a credit-hungry applicant.
    if parseable == 0:
        if len(enqs) < 3:
            return _pass(
                w,
                f"{len(enqs)} enquiries on bureau (dates unparseable; total count used).",
                "Under 3 threshold.",
            )
        return _fail(
            w,
            f"{len(enqs)} enquiries on bureau (dates unparseable; total count used).",
            "≥3 enquiries — credit-hungry signal. Verify recent-window dates manually.",
        )

    # Compact list of the recent enquiries (lender + date) so the assessor /
    # MD can see *who* pulled the bureau without opening the HTML. Falls back
    # to the most-recent few when no enquiry was inside the 3-month window
    # (still useful context — e.g. "last enquiry was 2 years ago").
    def _enq_label(e: dict[str, Any]) -> str:
        lender = (
            e.get("member_name")
            or e.get("lender")
            or e.get("institution")
            or e.get("subscriber")
            or "—"
        )
        date_str = e.get("date") or "—"
        purpose = e.get("purpose") or e.get("loan_type")
        amount = e.get("amount")
        bits = [f"{lender} on {date_str}"]
        if purpose:
            bits.append(str(purpose))
        if amount:
            bits.append(f"₹{amount}")
        return " · ".join(bits)

    def _enq_list(items: list[dict[str, Any]], cap: int = 6) -> str:
        labels = [_enq_label(e) for e in items if isinstance(e, dict)][:cap]
        if not labels:
            return ""
        more = len(items) - len(labels)
        suffix = f" (+{more} more)" if more > 0 else ""
        return "; ".join(labels) + suffix

    # Sort enquiries newest-first when picking the list to surface, so the
    # assessor sees the most relevant ones first.
    def _enq_sort_key(e: dict[str, Any]) -> Any:
        d = _parse(e.get("date")) if isinstance(e, dict) else None
        return d or datetime.now(UTC).date().replace(year=1900)

    sorted_enqs = sorted(
        (e for e in enqs if isinstance(e, dict)),
        key=_enq_sort_key,
        reverse=True,
    )
    recent_enqs = [e for e in sorted_enqs if (_parse(e.get("date")) or cutoff.replace(year=1900)) >= cutoff]
    enq_listing = _enq_list(recent_enqs or sorted_enqs)
    listing_suffix = f"\nEnquiries: {enq_listing}." if enq_listing else ""

    if recent_count < 3:
        return _pass(
            w,
            f"{recent_count} enquiries in last 3 months ({len(enqs)} total on file).{listing_suffix}",
            "Under 3 threshold.",
        )
    return _fail(
        w,
        f"{recent_count} enquiries in last 3 months ({len(enqs)} total on file).{listing_suffix}",
        "≥3 recent enquiries — credit-hungry signal.",
    )


def r_a09_cibil_address_match(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Rubric: CIBIL Address Match.

    The bureau-stored address must reconcile with the KYC (Aadhaar) address.
    L1 already runs exactly this check under ``aadhaar_vs_bureau_address`` —
    if that sub-step didn't emit an issue, the addresses reconcile.
    Equifax is a CIC like CIBIL, so a passing Equifax match satisfies the
    rubric.

    The legacy GPS-match path is kept as a secondary signal for cases where
    L1 didn't run / didn't ingest a bureau report.
    """
    # Guardrail: if L1 has never run, we cannot infer a PASS from
    # ``l1_issues_by_step == {}`` — empty dict just means "no L1 issues
    # on record", which could mean "passed" OR "never ran". Distinguish
    # the two using ``latest_vr_by_level`` and stay PENDING when the
    # level hasn't been triggered yet.
    if ctx.latest_vr_by_level.get(VerificationLevelNumber.L1_ADDRESS) is None:
        return _pending(
            w,
            "L1 has not run yet — trigger L1 so the bureau-address check "
            "can fire before this rubric is scored.",
        )
    bureau_iss = ctx.l1_issues_by_step.get("aadhaar_vs_bureau_address")
    if bureau_iss is None:
        # L1 ran and didn't flag aadhaar_vs_bureau_address — PASS.
        if ctx.primary_equifax is not None:
            return _pass(
                w,
                "L1 did not flag aadhaar_vs_bureau_address; Aadhaar address appears on the bureau record.",
                "CIC-recorded address reconciles with KYC.",
            )
        # No bureau extraction at all — fall through to GPS-verdict fallback.
    else:
        iss_status = (bureau_iss.get("status") or "").upper()
        if iss_status in ("MD_APPROVED",):
            return _pass(
                w,
                "L1 flagged aadhaar_vs_bureau_address but MD overrode the block.",
                "Address mismatch approved by MD.",
            )
        return _fail(
            w,
            "L1 flagged aadhaar_vs_bureau_address — Aadhaar address does not appear on any bureau record.",
            "Bureau address does not match KYC; verify manually.",
        )

    # Fallback: GPS verdict (proxy for CIBIL address match).
    v = (ctx.l1_gps_match_verdict or "").lower()
    if v == "match":
        return _pass(
            w,
            "No bureau extraction on file; L1 gps_match verdict = match (proxy).",
            "Address reconciles via GPS proxy.",
        )
    if v in ("doubtful", "mismatch"):
        return _fail(
            w,
            f"No bureau extraction on file; L1 gps_match verdict = {v}.",
            "Reconcile address manually.",
        )
    return _pending(w, "L1 bureau-match + GPS-match both unavailable; confirm manually.")


def r_a10_foir(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    raw = (
        _gnum(ctx.auto_cam, "cm_cam_il", "foir")
        or _gnum(ctx.auto_cam, "eligibility", "foir")
        or _gnum(ctx.auto_cam, "health_sheet", "foir")
    )
    if raw is None:
        return _pending(w, "FOIR not in CAM; assessor to confirm.")
    pct = raw * 100 if raw <= 1 else raw
    if pct < 20:
        return _pass(w, f"FOIR = {pct:.1f}%.", "Within policy (<40% comfort).")
    if pct <= 40:
        return _pass(w, f"FOIR = {pct:.1f}%.", "Within policy 20-40%.")
    if pct <= 50:
        return ("PASS", max(w - 1, 0), f"FOIR = {pct:.1f}%.", "40-50% — partial credit.")
    return _fail(w, f"FOIR = {pct:.1f}%.", ">50% — outside policy.")


def r_a11_negative_area(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Check the case's pincode against the admin-curated negative-area list.

    The list is managed at /admin/negative-areas. The orchestrator resolves
    the pincode + lookup flag before calling resolvers, so this stays pure."""
    pincode = ctx.case_pincode
    if not pincode:
        return _pending(w, "Pincode not detected on this case — manual review.")
    if ctx.case_pincode_in_negative_list is None:
        return _pending(w, "Negative-area list not loaded; manual review.")
    if ctx.case_pincode_in_negative_list:
        reason_suffix = (
            f" Reason: {ctx.negative_area_reason}" if ctx.negative_area_reason else ""
        )
        return _fail(
            w,
            f"Pincode {pincode} is on the active negative-area list.{reason_suffix}",
            "Restricted area — escalate to MD or reject.",
        )
    return _pass(
        w,
        f"Pincode {pincode} is NOT on the negative-area list.",
        "Cleared via admin pincode list.",
    )


def r_a12_dscr(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Graded: 1.2+ = 4, 1.0-1.2 = 3, 0.9-1.0 = 2, 0.75-0.9 = 1, else 0."""
    # SystemCam has DSCR on real CAMs.
    dscr = _gnum(ctx.auto_cam, "system_cam", "dscr")
    if dscr is None:
        return _pending(w, "DSCR not extracted from CAM.")
    if dscr >= 1.2:
        return _graded(4, w, f"DSCR = {dscr:.2f}.", "1.2+ grade.")
    if dscr >= 1.0:
        return _graded(3, w, f"DSCR = {dscr:.2f}.", "1.0-1.2 grade.")
    if dscr >= 0.9:
        return _graded(2, w, f"DSCR = {dscr:.2f}.", "0.9-1.0 grade.")
    if dscr >= 0.75:
        return _graded(1, w, f"DSCR = {dscr:.2f}.", "0.75-0.9 grade.")
    return _fail(w, f"DSCR = {dscr:.2f}.", "Below 0.75 — fail.")


def r_a13_deviation_approved(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Passes when every unresolved CRITICAL across L1-L4 has an MD sign-off.

    The underlying policy: the MD can sign off on policy deviations, but only
    once every blocker has either been fixed (issue closed) or explicitly
    approved (MD_APPROVED). If any CRITICAL remains OPEN / ASSESSOR_RESOLVED
    (i.e. still sitting with no MD decision), deviations cannot be "approved".

    Requires at least some L1-L4 signal to have been loaded — an empty
    context could equally mean "nothing has run yet" and we don't want to
    false-pass the deviation row before the gate has even been tried.
    """
    any_signal = bool(
        ctx.auto_cam
        or ctx.primary_equifax
        or ctx.bank_ca
        or ctx.l3_house
        or ctx.l3_business
        or ctx.l4_scanner
        or ctx.all_level_issues
    )
    if not any_signal:
        return _pending(
            w,
            "Deviation sign-off requires L1-L4 to have run first.",
        )
    crits = [
        (sid, d)
        for sid, d in ctx.all_level_issues.items()
        if d.get("severity") == "CRITICAL"
    ]
    if not crits:
        return _pass(
            w,
            "No CRITICAL gate issues flagged across L1-L4.",
            "No deviations to approve.",
        )
    unresolved = [
        sid for sid, d in crits if d.get("status") in ("OPEN", "ASSESSOR_RESOLVED")
    ]
    if not unresolved:
        return _pass(
            w,
            f"All {len(crits)} CRITICAL gate issue(s) have MD sign-off.",
            "Deviations formally approved.",
        )
    return _pending(
        w,
        f"{len(unresolved)} unresolved CRITICAL issue(s) — "
        f"{', '.join(unresolved[:3])}{'…' if len(unresolved) > 3 else ''}. "
        "Clear or MD-approve before deviation sign-off.",
    )


# ── Section B resolvers (11 params, 35 pts) ─────────────────────────────────


_QR_ARTIFACT_SUBTYPES: tuple[str, ...] = (
    "SHOP_QR",
    "SHOP_QR_SCREENSHOT",
    "QR_SCREENSHOT",
    "QR_PROOF",
    "BUSINESS_QR",
)


def _has_qr_artifact(ctx: ScoringContext) -> bool:
    return any(s in ctx.artifact_subtypes for s in _QR_ARTIFACT_SUBTYPES)


def r_b14_shop_qr(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Rubric: Shop QR Scanned.

    Section B is a hard gate at PFL — no shop QR proof means the BCM/CRO
    never confirmed the trade premises. Previously this row passed silently
    on PENDING, which left the case with no audit-defensible record. We now
    FAIL when no QR-tagged artifact is on the case so the standard
    assessor → MD-approval flow runs; the assessor records the on-the-ground
    justification (e.g. cash-only shop) and the MD signs off.
    """
    if _has_qr_artifact(ctx):
        return _pass(
            w,
            "Shop QR screenshot artifact present on case.",
            "QR proof uploaded; spot-check the file for the merchant ID.",
        )
    return _fail(
        w,
        "No shop-QR artifact uploaded on this case.",
        "Upload the QR screenshot or have the assessor record a justification "
        "(cash-only shop, QR refused, etc.) — MD approval required to clear.",
    )


def r_b15_qr_owner_match(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Rubric: QR Owner vs Borrower Match.

    Depends on a Shop QR artifact being on file — without it the auditor has
    nothing to compare against. Mirrors r_b14's strictness: missing QR is a
    FAIL routed to MD, not a silent PENDING.
    """
    if not _has_qr_artifact(ctx):
        return _fail(
            w,
            "QR-owner match cannot run — no shop-QR artifact uploaded.",
            "Upload the QR screenshot or record a justification — MD approval "
            "required to clear.",
        )
    # When a QR is on file the actual ownership comparison is a manual
    # auditor step that lives outside the rubric resolvers — keep PENDING so
    # the row still routes to the assessor for the visual check.
    return _pending(
        w,
        "QR file present — auditor to compare merchant identity vs borrower.",
    )


def r_b16_income_proof_applicant(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Rubric: Applicant Income Proof.

    Two layers:
      1. Hard presence — at least one income-proof artefact (or bank
         statement standing in) must be on file.
      2. Opus-4.7 cross-verification — when the analyzer ran, compare its
         forecasted monthly income against the BCM-declared CAM figure.
         A material mismatch (verdict=adverse) FAILs the row, which routes
         the case through the standard assessor → MD-approval flow with
         the analyzer's narrative attached.
    """
    analysis = ctx.income_proof_analysis or {}
    forecasted = analysis.get("forecasted_monthly_income_inr")
    declared = analysis.get("declared_monthly_income_inr")
    accuracy = analysis.get("accuracy_pct")
    verdict = (analysis.get("verdict") or "").lower()
    sources = analysis.get("distinct_income_sources") or 0

    if verdict == "adverse":
        return _fail(
            w,
            (
                f"Income proof inadequate: Opus-4.7 analyser forecasts "
                f"₹{forecasted:,}/mo from {sources} source(s) vs declared "
                f"₹{declared:,}/mo (accuracy {accuracy:.0f}%). "
                if forecasted and declared and accuracy is not None
                else "Income proof analyser flagged the proof as adverse. "
            )
            + (analysis.get("narrative") or "").strip(),
            "Material gap between proof and declared income — assessor to "
            "record justification, MD approval required.",
        )
    if verdict == "caution":
        return _fail(
            w,
            (
                f"Income proof partially supports the declared figure: "
                f"forecast ₹{forecasted:,}/mo vs declared ₹{declared:,}/mo "
                f"({accuracy:.0f}%). "
                if forecasted and declared and accuracy is not None
                else "Income proof analyser raised cautions on the proof. "
            )
            + (analysis.get("narrative") or "").strip(),
            "Soft mismatch — assessor to clarify before proceeding.",
        )
    if verdict == "clean" and forecasted and declared:
        return _pass(
            w,
            (
                f"Income proof corroborates declared income: forecast "
                f"₹{forecasted:,}/mo vs declared ₹{declared:,}/mo "
                f"({accuracy:.0f}%) across {sources} source(s)."
            ),
            "Opus-4.7 analyser verdict: clean.",
        )

    # Analyser did not run (no proof or storage failure) — fall back to the
    # legacy presence checks so the row doesn't go silently FAIL on a
    # missing infra path.
    has_it = any(s in ctx.artifact_subtypes for s in ("INCOME_PROOF", "SALARY_SLIP", "INCOME_SOURCE_PHOTO"))
    if has_it:
        return _pass(w, "Income proof artifact uploaded.", "Proof present (analyser did not run).")
    if "BANK_STATEMENT" in ctx.artifact_subtypes:
        return _pass(w, "Bank statement uploaded as income proof.", "Stands in for income proof.")
    return _fail(w, "No income-proof artifact uploaded.", "Missing income proof.")


def r_b17_income_proof_coapp(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    if not ctx.co_applicant_name:
        return ("NA", w, "No co-applicant on file.", "Not applicable.")
    has_it = any(
        s in ctx.artifact_subtypes
        for s in (
            "COAPP_INCOME_PROOF",
            "SALARY_SLIP",
            "CO_APPLICANT_INCOME_PROOF",
            "COAPP_BANK_STATEMENT",
        )
    )
    if has_it:
        return _pass(w, "Co-app income proof uploaded.", "Proof present.")
    # When the co-applicant is credit-invisible (e.g. a family member added
    # to satisfy co-applicant requirement but with no independent income
    # history), underwriting relies on the applicant's ability to service
    # the loan alone. Flag this as a FAIL so the gap is visible — but soften
    # the wording so the MD doesn't chase a document that may not exist.
    coapp_score = _gint(ctx.coapp_equifax, "credit_score")
    if coapp_score is not None and coapp_score < 300:
        return _fail(
            w,
            f"Co-applicant {ctx.co_applicant_name} is credit-invisible; "
            "no income proof uploaded either.",
            "Upload an income source (bank statement, salary slip) or mark "
            "the co-applicant formally as a guarantor only.",
        )
    return _fail(w, "Co-app income proof missing.", "Uploaded co-app proof not found.")


def r_b18_additional_income(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Rubric: Additional Income.

    "Additional" = at least one income source beyond the primary, supported
    by an actual proof artefact (not just a CAM declaration). The Opus-4.7
    income-proof analyser is the source of truth — a CAM line saying "wife
    earns ₹X" without a proof slip is NOT a source.
    """
    analysis = ctx.income_proof_analysis or {}
    sources = analysis.get("distinct_income_sources")
    if isinstance(sources, int):
        if sources >= 2:
            sources_label = ", ".join(
                (analysis.get("proof_types_detected") or [])[:4]
            ) or "multiple proofs"
            return _pass(
                w,
                f"{sources} distinct income source(s) detected from proof "
                f"artifacts ({sources_label}).",
                "Multiple proofs of income on file.",
            )
        if sources == 1:
            return _fail(
                w,
                "Only one distinct income source supported by proof "
                "artifacts — no additional income evidenced for either "
                "applicant or co-applicant.",
                "No proof of additional income — assessor to upload a "
                "secondary proof slip or record a justification, MD "
                "approval required.",
            )
        if sources == 0:
            return _fail(
                w,
                "No income source supported by proof artifacts.",
                "Upload at least one income-proof slip; MD approval "
                "required if proof cannot be obtained.",
            )

    # Analyser didn't run — fall back to the legacy CAM-only check.
    ai = _gnum(ctx.auto_cam, "cm_cam_il", "other_income") or _gnum(
        ctx.auto_cam, "system_cam", "total_household_income"
    )
    if ai and ai > 0:
        return _pass(w, f"Additional income recorded = ₹{int(ai):,}.", "Present (analyser did not run).")
    return _pending(w, "Additional income not captured in CAM.")


def r_b19_banking_6_12m(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    tx = _gint(ctx.bank_ca, "tx_line_count") or _gint(ctx.bank_ca, "transaction_count")
    if tx is None:
        if "BANK_STATEMENT" in ctx.artifact_subtypes:
            return _pass(w, "Bank statement uploaded.", "Statement present (span to be verified).")
        return _fail(w, "No bank statement uploaded.", "Under 6 months — fail.")
    if tx >= 50:  # rough proxy for 6 months of activity
        return _pass(w, f"{tx} transactions in statement.", "≥6 months equivalent.")
    return _fail(w, f"Only {tx} transactions.", "Statement too short — fail.")


def r_b20_total_credit(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    total = _gint(ctx.bank_ca, "three_month_credit_sum_inr")
    if total is None:
        return _pending(w, "Credit total not computed by L2 yet.")
    return _pass(w, f"3-month credit sum = ₹{total:,}.", "Captured.")


def r_b21_coapp_banking(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    if not ctx.co_applicant_name:
        return ("NA", w, "No co-applicant on file.", "Not applicable.")
    if "COAPP_BANK_STATEMENT" in ctx.artifact_subtypes:
        return _pass(w, "Co-app bank statement uploaded.", "Available.")
    # Rubric wording is "If available pass" — credit-invisible co-apps
    # typically don't maintain their own account, so treat the missing
    # statement as NA rather than PENDING. The applicant carries the loan.
    coapp_score = _gint(ctx.coapp_equifax, "credit_score")
    if coapp_score is not None and coapp_score < 300:
        return (
            "NA",
            w,
            f"Co-applicant {ctx.co_applicant_name} is credit-invisible; "
            "no own banking record expected.",
            "Not applicable — applicant banking carries the loan.",
        )
    return _pending(w, "Co-app bank statement not uploaded.")


def r_b22_abb_ratio(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Graded: 1.5+ = 4, 1.2-1.5 = 3, 1-1.2 = 2, <1 = 0."""
    abb = _gnum(ctx.bank_ca, "avg_monthly_balance_inr")
    emi = ctx.proposed_emi_inr or 0
    if abb is None or emi <= 0:
        return _pending(w, "ABB or proposed EMI missing — cannot compute ratio.")
    ratio = abb / emi
    evidence = f"ABB = ₹{int(abb):,} vs proposed EMI ₹{emi:,} → ratio {ratio:.2f}."
    if ratio >= 1.5:
        return _graded(4, w, evidence, "1.5+ grade.")
    if ratio >= 1.2:
        return _graded(3, w, evidence, "1.2-1.5 grade.")
    if ratio >= 1.0:
        return _graded(2, w, evidence, "1.0-1.2 grade.")
    return _fail(w, evidence, "<1 — fail.")


def r_b23_no_bouncing(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    nb = _gint(ctx.bank_ca, "nach_bounce_count")
    if nb is None:
        return _pending(w, "Bounce count not computed by L2.")
    if nb == 0:
        return _pass(w, "0 NACH / ECS bounces in statement.", "Clean.")
    return _fail(w, f"{nb} NACH / ECS bounce(s).", "Bounces present — prior default signal.")


def r_b24_banking_matches_income(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    cam_inc = _gnum(ctx.auto_cam, "cm_cam_il", "total_monthly_income") or 0
    credit_sum = _gnum(ctx.bank_ca, "three_month_credit_sum_inr") or 0
    if cam_inc <= 0 or credit_sum <= 0:
        return _pending(w, "Need CAM income + banking credit sum.")
    # Expect bank 3M credits ≥ 50% of declared 3M income (conservative)
    if credit_sum >= cam_inc * 3 * 0.5:
        return _pass(
            w,
            f"3M credits ₹{int(credit_sum):,} ≥ 50% of 3× declared income.",
            "Banking tracks income.",
        )
    return _fail(
        w,
        f"3M credits ₹{int(credit_sum):,} < 50% of 3× declared ₹{int(cam_inc):,}.",
        "Banking does not match declared income.",
    )


# ── Section C resolvers (5 params, 13 pts) ──────────────────────────────────


def r_c25_loan_purpose(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Loan purpose is a mandatory CAM field. Missing = policy breach,
    not "data not yet captured" — fail the row so the standard
    assessor → MD-approval flow runs (paired with ``force_critical=True``
    in the catalog so the issue lands as CRITICAL irrespective of weight).
    """
    purpose = (
        _gstr(ctx.auto_cam, "system_cam", "loan_purpose")
        or _gstr(ctx.auto_cam, "system_cam", "sub_purpose")
        or _gstr(ctx.auto_cam, "cm_cam_il", "loan_purpose")
        or _gstr(ctx.auto_cam, "cm_cam_il", "purpose_of_loan")
        or _gstr(ctx.auto_cam, "eligibility", "loan_purpose")
        or _gstr(ctx.auto_cam, "eligibility", "purpose")
    )
    if purpose:
        return _pass(w, f"Loan purpose on CAM: {purpose}.", "Purpose documented.")
    return _fail(
        w,
        "Loan purpose not declared in CAM.",
        "Mandatory CAM declaration missing — escalate to MD for approval.",
    )


def r_c26_end_use(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """End-use of funds must be declared in CAM pre-disbursal so the
    sanction record carries an explicit deployment statement. The
    post-disbursal end-use audit is a separate workflow; here we only
    gate on the declaration being present.

    Falls back to ``sub_purpose`` (most CAMs use loan_purpose +
    sub_purpose where sub_purpose is the deployment detail). Paired with
    ``force_critical=True`` so a missing declaration escalates to MD.
    """
    end_use = (
        _gstr(ctx.auto_cam, "system_cam", "end_use")
        or _gstr(ctx.auto_cam, "system_cam", "end_use_of_funds")
        or _gstr(ctx.auto_cam, "system_cam", "use_of_funds")
        or _gstr(ctx.auto_cam, "system_cam", "sub_purpose")
        or _gstr(ctx.auto_cam, "cm_cam_il", "end_use")
        or _gstr(ctx.auto_cam, "cm_cam_il", "end_use_of_funds")
        or _gstr(ctx.auto_cam, "cm_cam_il", "use_of_funds")
        or _gstr(ctx.auto_cam, "cm_cam_il", "sub_purpose")
        or _gstr(ctx.auto_cam, "eligibility", "end_use")
        or _gstr(ctx.auto_cam, "eligibility", "use_of_funds")
    )
    if end_use:
        return _pass(
            w,
            f"End-use declared in CAM: {end_use}.",
            "Pre-disbursal declaration captured; post-disbursal audit follows.",
        )
    return _fail(
        w,
        "End use of funds not declared in CAM.",
        "Mandatory CAM declaration missing — escalate to MD for approval.",
    )


def r_c27_house_ownership(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    if "HOUSE_OWNERSHIP_PROOF" in ctx.artifact_subtypes or "RATION_CARD" in ctx.artifact_subtypes:
        return _pass(w, "House-ownership / ration artifact uploaded.", "Proof present.")
    return _fail(w, "House ownership proof not uploaded.", "Missing house-ownership artifact.")


def r_c28_business_ownership(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    # Subtype enum uses ``UDYAM_REG`` in practice; the legacy list also
    # covered ``UDYAM_CERTIFICATE`` / ``SHOP_LICENCE``. Anchor on every
    # known variant so a real Udyam upload doesn't silently read as
    # "not yet tagged".
    if any(
        s in ctx.artifact_subtypes
        for s in (
            "UDYAM_REG",
            "UDYAM_CERTIFICATE",
            "SHOP_LICENCE",
            "SHOP_LICENSE",
            "SHOP_ACT",
            "BUSINESS_OWNERSHIP_PROOF",
            "GST_REG",
            "GST_CERTIFICATE",
        )
    ):
        return _pass(w, "Business-ownership artifact uploaded.", "Proof present.")
    return _fail(w, "Business ownership proof not uploaded.", "Missing business-ownership artifact.")


def r_c29_additional_assets(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    # L3 vision captures high_value_assets_visible on the house read.
    assets = (ctx.l3_house or {}).get("high_value_assets_visible") or []
    if isinstance(assets, list) and len(assets) >= 1:
        return _pass(
            w,
            f"{len(assets)} high-value asset(s) visible in photos ({', '.join(assets[:3])}).",
            "Assets visible.",
        )
    return _pending(w, "No additional assets tagged by L3 Vision.")


# ── Section D resolvers (3 params, 7 pts) ───────────────────────────────────


def r_d30_bcm_cross_verification(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """BCM cross-verification — proof is the LMS "References + Contact
    Details" screenshot showing both parties' references have been punched
    into the loan management system. PASS only when that screenshot is
    uploaded as a REFERENCES_SCREENSHOT artifact; otherwise prompt the
    assessor to add it to the case zip or upload it inline, then re-run L5.
    """
    if "REFERENCES_SCREENSHOT" in ctx.artifact_subtypes:
        return _pass(
            w,
            "References + contact-details screenshot uploaded.",
            "BCM cross-verification proof on file.",
        )
    return _pending(
        w,
        "References + contact-details screenshot not on file. Add it to the "
        "case zip or upload it on this rule, then re-run L5 scoring.",
    )


def r_d31_tvr(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """TVR by Credit HO — proof is the audio recording of the telephonic
    verification call placed by Credit HO. PASS only when a TVR_AUDIO
    artifact is on the case; otherwise prompt for upload + re-run.
    """
    if "TVR_AUDIO" in ctx.artifact_subtypes:
        return _pass(
            w,
            "TVR audio recording uploaded.",
            "Telephonic verification on file.",
        )
    return _pending(
        w,
        "TVR audio recording not on file. Add it to the case zip or upload "
        "it on this rule, then re-run L5 scoring.",
    )


def r_d32_fraud_call(ctx: ScoringContext, w: int) -> tuple[Status, int, str, str]:
    """Fraud / independent verification call — proof is a SEPARATE audio
    recording from the TVR (the fraud call is placed by HO independently
    of the Credit HO TVR). PASS only when a FRAUD_CALL_AUDIO artifact is
    on the case; otherwise prompt for upload + re-run.
    """
    if "FRAUD_CALL_AUDIO" in ctx.artifact_subtypes:
        return _pass(
            w,
            "Fraud-call audio recording uploaded.",
            "Independent verification call on file.",
        )
    return _pending(
        w,
        "Fraud-call audio recording not on file (must be a separate audio "
        "file from the TVR recording). Add it to the case zip or upload it "
        "on this rule, then re-run L5 scoring.",
    )


# ── Catalog ──────────────────────────────────────────────────────────────────


@dataclass
class ParamDef:
    sno: int
    section_id: str
    title: str
    parameter: str
    expected: str
    weight: int
    role: str
    resolver: Callable[[ScoringContext, int], tuple[Status, int, str, str]]
    # When True, a FAIL or PENDING outcome on this rule is escalated to
    # CRITICAL severity in the L5 issues panel regardless of the row's
    # weight. Reserved for rules whose missing data is itself a hard
    # policy gate that cannot ship without explicit MD sign-off
    # (e.g. mandatory CAM declarations like loan purpose / end use).
    force_critical: bool = False


SECTIONS: list[tuple[str, str, int]] = [
    ("A", "Credit Assessment & Eligibility", 45),
    ("B", "QR and Banking Check", 35),
    ("C", "Assets & Living Standard", 13),
    ("D", "Reference Checks & TVR", 7),
]


CATALOG: list[ParamDef] = [
    # Section A
    ParamDef(1, "A", "A: Credit Assessment", "Total Household Income", "Per PD assessment", 3, "BCM", r_a01_household_income),
    ParamDef(2, "A", "A: Credit Assessment", "Business Vintage", "Documented", 3, "CRO/BM", r_a02_business_vintage),
    ParamDef(3, "A", "A: Credit Assessment", "Applicant CIBIL (≥750)", "<750 rejected at CRO", 4, "CRO", r_a03_applicant_cibil),
    ParamDef(4, "A", "A: Credit Assessment", "Co-App CIBIL Checked", "Checked & recorded", 3, "CRO", r_a04_coapp_cibil),
    ParamDef(5, "A", "A: Credit Assessment", "Unsecured Outstanding", "Captured from CB", 4, "BCM", r_a05_unsecured_outstanding),
    ParamDef(6, "A", "A: Credit Assessment", "DPD in Last 12 Months", "No DPD", 4, "CRO", r_a06_dpd_12m),
    ParamDef(7, "A", "A: Credit Assessment", "Write-Off / Settled (3 Yrs)", "None in 3 years", 4, "CRO", r_a07_writeoff_settled_3y),
    ParamDef(8, "A", "A: Credit Assessment", "Credit Enquiries (3M)", "<3 flagged", 3, "BCM/Credit", r_a08_enquiries_3m),
    ParamDef(9, "A", "A: Credit Assessment", "CIBIL Address Match", "Matches proof", 2, "BM/OPS", r_a09_cibil_address_match),
    ParamDef(10, "A", "A: Credit Assessment", "FOIR Within Limits", "Within policy (<40 full / 40-50 partial)", 4, "BCM/Credit", r_a10_foir),
    ParamDef(11, "A", "A: Credit Assessment", "Negative Area Check", "Not restricted", 2, "BM/Credit", r_a11_negative_area),
    ParamDef(12, "A", "A: Credit Assessment", "DSCR", "1.2+ full / graded", 4, "BCM", r_a12_dscr),
    ParamDef(13, "A", "A: Credit Assessment", "Deviation Approved", "Formally approved", 5, "BCM/Credit", r_a13_deviation_approved),
    # Section B
    ParamDef(14, "B", "B: QR & Banking", "Shop QR Scanned", "Screenshot uploaded", 3, "CRO/BM", r_b14_shop_qr),
    ParamDef(15, "B", "B: QR & Banking", "QR Owner vs Borrower Match", "Matches", 4, "Auditor", r_b15_qr_owner_match),
    ParamDef(16, "B", "B: QR & Banking", "Applicant Income Proof", "Uploaded", 5, "CRO", r_b16_income_proof_applicant),
    ParamDef(17, "B", "B: QR & Banking", "Co-borrower Income Proof", "Uploaded", 4, "CRO", r_b17_income_proof_coapp),
    ParamDef(18, "B", "B: QR & Banking", "Additional Income", "If available", 3, "CAM", r_b18_additional_income),
    ParamDef(19, "B", "B: QR & Banking", "Banking Statement (6-12M)", "≥6 months", 3, "CRO", r_b19_banking_6_12m),
    ParamDef(20, "B", "B: QR & Banking", "Total Credit Amount", "Captured", 2, "BCM", r_b20_total_credit),
    ParamDef(21, "B", "B: QR & Banking", "Co-App Banking Available", "If available pass", 2, "BCM", r_b21_coapp_banking),
    ParamDef(22, "B", "B: QR & Banking", "ABB Ratio", "1.5+ full / graded", 4, "BCM", r_b22_abb_ratio),
    ParamDef(23, "B", "B: QR & Banking", "No Bouncing", "No bounces", 3, "BCM/Credit", r_b23_no_bouncing),
    ParamDef(24, "B", "B: QR & Banking", "Banking Matches Income", "Bank credits ≈ declared income", 2, "Auditor", r_b24_banking_matches_income),
    # Section C
    ParamDef(25, "C", "C: Assets & Living", "Purpose of Loan", "Asset / stock creation", 3, "BM/OPS", r_c25_loan_purpose, force_critical=True),
    ParamDef(26, "C", "C: Assets & Living", "End Use for Debt", "Declared", 3, "—", r_c26_end_use, force_critical=True),
    ParamDef(27, "C", "C: Assets & Living", "House Ownership Proof", "Uploaded", 2, "BM/OPS", r_c27_house_ownership),
    ParamDef(28, "C", "C: Assets & Living", "Business Ownership Proof", "Uploaded", 2, "BM/OPS", r_c28_business_ownership),
    ParamDef(29, "C", "C: Assets & Living", "Additional Assets", "Visible / declared", 3, "Auditor", r_c29_additional_assets),
    # Section D
    ParamDef(30, "D", "D: Reference & TVR", "BCM Cross-Verification", "Verified both parties", 1, "BCM", r_d30_bcm_cross_verification),
    ParamDef(31, "D", "D: Reference & TVR", "TVR by Credit HO", "Telephonic verification", 3, "Credit HO", r_d31_tvr),
    ParamDef(32, "D", "D: Reference & TVR", "Fraud / Verification Call", "Independent call from HO", 3, "Credit HO", r_d32_fraud_call),
]


# Sno-set of rules whose FAIL/PENDING outcome must escalate to CRITICAL
# severity in the L5 issues panel regardless of the row's weight. Derived
# from the ParamDef.force_critical flag so the catalog stays the single
# source of truth.
FORCE_CRITICAL_SNOS: frozenset[int] = frozenset(p.sno for p in CATALOG if p.force_critical)


def build_score(ctx: ScoringContext) -> ScoringResult:
    """Run every resolver + group into sections. Pure function."""
    section_map: dict[str, SectionScore] = {
        sid: SectionScore(section_id=sid, title=title, max_score=max_pts, earned=0)
        for sid, title, max_pts in SECTIONS
    }

    for p in CATALOG:
        # Manual assessor override wins.
        override = ctx.manual_overrides.get(p.sno)
        if override:
            status = override.get("status") or "PENDING"
            score = int(override.get("score") or 0)
            evidence = str(override.get("evidence") or "")
            remarks = str(override.get("remarks") or "")
        else:
            status, score, evidence, remarks = p.resolver(ctx, p.weight)
        row = ScoreRow(
            sno=p.sno,
            section=p.section_id,
            parameter=p.parameter,
            expected=p.expected,
            weight=p.weight,
            role=p.role,
            status=status,
            score=score,
            evidence=evidence,
            remarks=remarks,
        )
        sec = section_map[p.section_id]
        sec.rows.append(row)
        if status != "NA":
            sec.earned += score

    return ScoringResult(sections=list(section_map.values()))
