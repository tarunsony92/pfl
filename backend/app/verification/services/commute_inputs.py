"""Pure helpers that assemble "profile inputs" for the commute judge.

Level 1 never computes these from scratch — the data already exists in
``case_extractions`` (equifax, bank_statement) and in prior-run
``verification_results.sub_step_results`` (L3 business type). These helpers
just collapse raw shapes into the compact labels the Opus prompt expects.

All functions here are deterministic, synchronous, and pure: no Claude,
no HTTP, no DB. They are unit-tested in
``tests/unit/test_verification_commute_helpers.py``.
"""

from __future__ import annotations

from typing import Any, Literal

# ── Area classifier ─────────────────────────────────────────────────────────

_RURAL_PLACE_TYPES = frozenset({
    "village",
    "hamlet",
    "suburb",
    "rural",
})
_URBAN_PLACE_TYPES = frozenset({
    "city",
    "town",
    "locality",
    "metropolis",
})


_RURAL_ADDRESS_KEYWORDS = (
    "village",
    "vill ",
    "vill,",
    "gram ",
    "tehsil",
    "taluk",
    "taluka",
    "mandal",
    "hamlet",
    "panchayat",
    "rural",
)
_URBAN_ADDRESS_KEYWORDS = (
    "city",
    "municipal",
    "metropolitan",
    "metro",
    "nagar palika",
    "nagar nigam",
    "corporation",
)


def classify_area(
    *,
    place_type: str | None,
    address: str | None = None,
) -> Literal["rural", "urban"] | None:
    """Collapse signals from a reverse-geocoder into a coarse rural-vs-urban
    label.

    Two inputs, in order of authority:

    1. ``place_type`` — Nominatim's ``addresstype`` (village / hamlet /
       town / city / …). The most reliable signal when present, but only
       set on the Nominatim fallback path. Google's geocoder ``types``
       array is too coarse for this distinction (it lumps villages and
       cities under ``locality``) so we deliberately don't try to map
       Google's types here.
    2. ``address`` — the formatted address string. Heuristic keyword
       match (e.g. "Village Sadipur" → rural, "Delhi Municipal Corp" →
       urban). Cheap, no extra API calls, and works for both Google and
       Nominatim outputs.

    Returns None when neither signal yields a confident classification —
    the judge tolerates None.
    """
    if place_type:
        t = place_type.strip().lower()
        if t in _RURAL_PLACE_TYPES:
            return "rural"
        if t in _URBAN_PLACE_TYPES:
            return "urban"

    if address:
        a = address.lower()
        if any(k in a for k in _RURAL_ADDRESS_KEYWORDS):
            return "rural"
        if any(k in a for k in _URBAN_ADDRESS_KEYWORDS):
            return "urban"

    return None


# ── Bank-income-pattern classifier ──────────────────────────────────────────

_SALARY_KEYWORDS = ("salary", "sal cr", "salary cr", "payroll")
_CASH_CHANNELS = frozenset({"cash", "cash dep", "cdm"})


def _is_salary(tx: dict[str, Any]) -> bool:
    narr = str(tx.get("narration") or "").lower()
    return any(k in narr for k in _SALARY_KEYWORDS)


def _is_cash_deposit(tx: dict[str, Any]) -> bool:
    channel = str(tx.get("channel") or "").lower()
    narr = str(tx.get("narration") or "").lower()
    return channel in _CASH_CHANNELS or "cash dep" in narr


def classify_bank_income_pattern(
    transactions: list[dict[str, Any]] | None,
) -> Literal["salary_credits", "cash_deposits", "mixed"] | None:
    """Inspect a bank-statement's credit transactions and decide which
    income signal dominates.

    Heuristic — cheap, good-enough for the judge prompt:
      - count salary-keyword credits vs cash-deposit credits.
      - if one side is ≥ 3× the other → that side wins.
      - else → "mixed".
      - if neither appears → None (judge receives null and reasons without it).
    """
    if not transactions:
        return None

    salary = 0
    cash = 0
    for tx in transactions:
        if str(tx.get("type") or "").lower() != "credit":
            continue
        if _is_salary(tx):
            salary += 1
        elif _is_cash_deposit(tx):
            cash += 1

    if salary == 0 and cash == 0:
        return None
    if salary >= 3 * max(cash, 1) and salary > 0:
        return "salary_credits"
    if cash >= 3 * max(salary, 1) and cash > 0:
        return "cash_deposits"
    return "mixed"
