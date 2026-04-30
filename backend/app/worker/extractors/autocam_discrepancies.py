"""CAM discrepancy detector.

Scans the ``auto_cam`` extraction payload for numeric / identity fields that
appear in BOTH the SystemCam sheet (auto-populated from finpage / bureau) and
the CM CAM IL sheet (manually filled by BCM or Credit HO) and flags any
divergence beyond tolerance.

Spec reference: memory/project_autocam_sheet_authority.md and
docs/superpowers/RESUME_HERE.md §A30.

Pure function — no DB or IO. Persistence is handled by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal

# Severity determines whether the discrepancy blocks Phase 1 (CRITICAL) or
# just needs an assessor's attention (WARNING).
Severity = Literal["CRITICAL", "WARNING"]

# Stable string codes so resolutions can survive re-extraction by field key.
# Each entry represents a field that must match between SystemCam (auto) and
# CM CAM IL (manual). The field_key is also used as the stable id.
FIELD_APPLICANT_NAME = "applicant_name"
FIELD_PAN = "pan"
FIELD_DATE_OF_BIRTH = "date_of_birth"
FIELD_LOAN_AMOUNT = "loan_amount"
FIELD_FOIR = "foir"
FIELD_CIBIL = "cibil"
FIELD_TOTAL_MONTHLY_INCOME = "total_monthly_income"
FIELD_TENURE = "tenure_months"


@dataclass(frozen=True)
class Discrepancy:
    """One detected conflict. The field_key is the stable identifier the UI
    and the resolutions table use to link the persisted resolution back to
    the flag. ``system_cam_value`` / ``cm_cam_il_value`` are the raw extracted
    values (either side may be None if the field was missing from one sheet).
    ``diff_abs`` and ``diff_pct`` are only populated for numeric fields.
    """

    field_key: str
    field_label: str
    system_cam_value: str | None
    cm_cam_il_value: str | None
    diff_abs: float | None
    diff_pct: float | None
    severity: Severity
    tolerance_description: str
    # A brief user-facing explanation of WHY this flagged. Shown in the UI
    # under the discrepancy row so the assessor knows what to look at.
    note: str = ""


# ---------------------------------------------------------------------------
# Value extractors — map the raw auto_cam data dict to (system, manual) pairs
# for every field we cross-check. Each returns (system_value, manual_value)
# both as raw strings / numbers (or None when absent).
# ---------------------------------------------------------------------------


def _get(data: dict[str, Any], *path: str) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_non_empty(*values: Any) -> Any:
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _extract_pairs(data: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Return a mapping field_key → (system_value, manual_value).

    SystemCam and Elegibilty are system-sourced (finpage / bureau); CM CAM IL
    and Health Sheet are manual. Per the memory note, Elegibilty CIBIL comes
    from bureau so we treat it as a SYSTEM value when present.
    """
    sc = _get(data, "system_cam") or {}
    el = _get(data, "eligibility") or {}
    cm = _get(data, "cm_cam_il") or {}
    hs = _get(data, "health_sheet") or {}

    pairs: dict[str, tuple[Any, Any]] = {
        # Identity fields — SystemCam is finpage-sourced; CM CAM IL is manual.
        FIELD_APPLICANT_NAME: (
            _first_non_empty(sc.get("applicant_name"), el.get("applicant_name")),
            cm.get("borrower_name"),
        ),
        FIELD_PAN: (
            sc.get("pan"),
            cm.get("pan_number"),
        ),
        FIELD_DATE_OF_BIRTH: (
            sc.get("date_of_birth"),
            cm.get("date_of_birth"),
        ),
        # Financial fields.
        FIELD_LOAN_AMOUNT: (
            sc.get("loan_amount"),
            _first_non_empty(cm.get("loan_required"), el.get("eligible_amount")),
        ),
        FIELD_FOIR: (
            # SystemCam exposes "foir_installment" and "foir_overall"; prefer overall.
            _first_non_empty(sc.get("foir_overall"), sc.get("foir")),
            _first_non_empty(cm.get("foir"), hs.get("foir")),
        ),
        FIELD_CIBIL: (
            el.get("cibil_score"),
            cm.get("cibil"),
        ),
        FIELD_TOTAL_MONTHLY_INCOME: (
            hs.get("total_monthly_income"),
            cm.get("total_monthly_income"),
        ),
        FIELD_TENURE: (
            sc.get("tenure"),
            cm.get("tenure"),
        ),
    }
    return pairs


# ---------------------------------------------------------------------------
# Value coercion + normalisation
# ---------------------------------------------------------------------------


_NUMERIC_STRIP = re.compile(r"[₹,\s%]")


def _coerce_number(v: Any) -> Decimal | None:
    """Best-effort: strip currency / commas / whitespace, return Decimal.

    Returns None for '-', empty, or unparseable strings so callers can treat
    those as 'missing'.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None  # bool is int subclass in Python; we don't want True/False here
    if isinstance(v, int | float | Decimal):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None
    s = str(v).strip()
    if not s or s in {"-", "—", "NA", "N/A"}:
        return None
    cleaned = _NUMERIC_STRIP.sub("", s)
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _normalise_string(v: Any) -> str | None:
    if v is None:
        return None
    s = " ".join(str(v).strip().split())
    if not s or s in {"-", "—"}:
        return None
    return s


def _names_equivalent(a: str, b: str) -> bool:
    """Case-insensitive comparison that tolerates token re-ordering."""
    ta = sorted(a.lower().split())
    tb = sorted(b.lower().split())
    return ta == tb


def _dates_equivalent(a: str, b: str) -> bool:
    """Match across DD-MM-YYYY / DD/MM/YYYY / YYYY-MM-DD variants."""
    digits_a = re.sub(r"\D", "", a)
    digits_b = re.sub(r"\D", "", b)
    if not digits_a or not digits_b:
        return a.strip().lower() == b.strip().lower()
    # Either normalise to (day, month, year) triplet — best effort
    return digits_a == digits_b or set(digits_a) == set(digits_b) and len(digits_a) == len(digits_b) and _same_date_triplet(a, b)


def _same_date_triplet(a: str, b: str) -> bool:
    def split(d: str) -> list[int]:
        parts = re.split(r"[-/. ]", d.strip())
        return sorted(int(p) for p in parts if p.isdigit())
    try:
        return split(a) == split(b)
    except ValueError:
        return False


def _foir_to_pct(v: Decimal) -> Decimal:
    """FOIR is sometimes stored as a fraction (0.181) and sometimes as a
    percentage (18.1 / 25.35). Anything ≤ 1 is treated as a fraction.
    """
    return v * Decimal(100) if v <= Decimal(1) else v


# ---------------------------------------------------------------------------
# Per-field comparators — each returns a Discrepancy or None.
# ---------------------------------------------------------------------------


def _string_comparator(
    field_key: str,
    field_label: str,
    severity: Severity,
    equivalent: Callable[[str, str], bool] = lambda a, b: a.lower() == b.lower(),
    tolerance_description: str = "exact match (case-insensitive)",
) -> Callable[[Any, Any], Discrepancy | None]:
    def check(sv: Any, mv: Any) -> Discrepancy | None:
        sn = _normalise_string(sv)
        mn = _normalise_string(mv)
        if sn is None or mn is None:
            return None  # only one side has a value → not a discrepancy, just missing
        if equivalent(sn, mn):
            return None
        return Discrepancy(
            field_key=field_key,
            field_label=field_label,
            system_cam_value=sn,
            cm_cam_il_value=mn,
            diff_abs=None,
            diff_pct=None,
            severity=severity,
            tolerance_description=tolerance_description,
            note=(
                f"SystemCam has {sn!r} but CM CAM IL has {mn!r}. "
                "Identity fields must match across both sheets."
            ),
        )
    return check


def _numeric_comparator(
    field_key: str,
    field_label: str,
    severity: Severity,
    abs_tol: Decimal | None = None,
    pct_tol: Decimal | None = None,
    transform: Callable[[Decimal], Decimal] = lambda x: x,
    unit: str = "",
) -> Callable[[Any, Any], Discrepancy | None]:
    """Compare two numeric values. Flags when BOTH abs_tol and pct_tol are
    exceeded (if both are set) — OR when either alone exceeds (if only one).
    """

    def check(sv: Any, mv: Any) -> Discrepancy | None:
        sn = _coerce_number(sv)
        mn = _coerce_number(mv)
        if sn is None or mn is None:
            return None
        sn_t = transform(sn)
        mn_t = transform(mn)
        diff = abs(sn_t - mn_t)
        if diff == 0:
            return None
        denom = max(abs(sn_t), abs(mn_t), Decimal(1))
        diff_pct = (diff / denom) * Decimal(100)
        # Pass tolerance? Require BOTH to pass when both are set.
        abs_ok = abs_tol is None or diff <= abs_tol
        pct_ok = pct_tol is None or diff_pct <= pct_tol
        # Under either tolerance = acceptable
        if abs_ok and pct_ok:
            return None
        unit_str = f"{unit} " if unit else ""
        note = (
            f"SystemCam value {unit_str}{sn_t} vs CM CAM IL {unit_str}{mn_t} — "
            f"difference {unit_str}{diff} ({diff_pct:.2f}%)."
        )
        return Discrepancy(
            field_key=field_key,
            field_label=field_label,
            system_cam_value=str(sn_t),
            cm_cam_il_value=str(mn_t),
            diff_abs=float(diff),
            diff_pct=float(diff_pct),
            severity=severity,
            tolerance_description=_format_tolerance(abs_tol, pct_tol, unit),
            note=note,
        )

    return check


def _format_tolerance(abs_tol: Decimal | None, pct_tol: Decimal | None, unit: str) -> str:
    parts: list[str] = []
    if abs_tol is not None:
        parts.append(f"≤ {abs_tol} {unit}".strip())
    if pct_tol is not None:
        parts.append(f"≤ {pct_tol}%")
    return " AND ".join(parts) if parts else "exact"


# ---------------------------------------------------------------------------
# Field registry — tolerance choices come from the memory note (v1 defaults).
# Tune here when field-level policy changes; resolutions carry over across
# re-extractions because they key on field_key.
# ---------------------------------------------------------------------------


_COMPARATORS: list[tuple[str, Callable[[Any, Any], Discrepancy | None]]] = [
    (
        FIELD_APPLICANT_NAME,
        _string_comparator(
            FIELD_APPLICANT_NAME,
            "Applicant / Borrower Name",
            "CRITICAL",
            equivalent=_names_equivalent,
            tolerance_description="case + token-order insensitive exact match",
        ),
    ),
    (
        FIELD_PAN,
        _string_comparator(
            FIELD_PAN,
            "PAN",
            "CRITICAL",
            equivalent=lambda a, b: a.upper() == b.upper(),
            tolerance_description="exact match (case-insensitive)",
        ),
    ),
    (
        FIELD_DATE_OF_BIRTH,
        _string_comparator(
            FIELD_DATE_OF_BIRTH,
            "Date of Birth",
            "CRITICAL",
            equivalent=_dates_equivalent,
            tolerance_description="same calendar date (any format)",
        ),
    ),
    (
        FIELD_LOAN_AMOUNT,
        _numeric_comparator(
            FIELD_LOAN_AMOUNT,
            "Loan Amount",
            "CRITICAL",
            abs_tol=Decimal("500"),
            pct_tol=Decimal("2"),
            unit="INR",
        ),
    ),
    (
        FIELD_FOIR,
        _numeric_comparator(
            FIELD_FOIR,
            "FOIR (Overall)",
            "WARNING",
            abs_tol=Decimal("1"),
            transform=_foir_to_pct,
            unit="percentage points",
        ),
    ),
    (
        FIELD_CIBIL,
        _numeric_comparator(
            FIELD_CIBIL,
            "CIBIL / Credit Score",
            "CRITICAL",
            abs_tol=Decimal("0"),
            unit="points",
        ),
    ),
    (
        FIELD_TOTAL_MONTHLY_INCOME,
        _numeric_comparator(
            FIELD_TOTAL_MONTHLY_INCOME,
            "Total Monthly Income",
            "WARNING",
            pct_tol=Decimal("2"),
            unit="INR",
        ),
    ),
    (
        FIELD_TENURE,
        _numeric_comparator(
            FIELD_TENURE,
            "Tenure (months)",
            "WARNING",
            abs_tol=Decimal("0"),
            unit="months",
        ),
    ),
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def detect_discrepancies(auto_cam_data: dict[str, Any]) -> list[Discrepancy]:
    """Return a list of Discrepancy records for the given auto_cam extraction.

    Empty list means SystemCam and CM CAM IL agree on every checked field
    (within tolerance) or that one side didn't have the field at all — the
    latter is NOT flagged as a discrepancy by design; it's a separate
    "missing field" concern that the extractor already surfaces via warnings.
    """
    if not isinstance(auto_cam_data, dict):
        return []
    pairs = _extract_pairs(auto_cam_data)
    out: list[Discrepancy] = []
    for field_key, comparator in _COMPARATORS:
        sv, mv = pairs.get(field_key, (None, None))
        disc = comparator(sv, mv)
        if disc is not None:
            out.append(disc)
    return out


def serialise(discrepancies: list[Discrepancy]) -> list[dict[str, Any]]:
    """Convert Discrepancy objects to plain dicts for JSON storage."""
    return [
        {
            "field_key": d.field_key,
            "field_label": d.field_label,
            "system_cam_value": d.system_cam_value,
            "cm_cam_il_value": d.cm_cam_il_value,
            "diff_abs": d.diff_abs,
            "diff_pct": d.diff_pct,
            "severity": d.severity,
            "tolerance_description": d.tolerance_description,
            "note": d.note,
        }
        for d in discrepancies
    ]
