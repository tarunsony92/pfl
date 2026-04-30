"""Unit tests for the two pure classifier helpers used by the commute judge.

Both are tiny enough to live in ``app/verification/services/commute_inputs.py``
and are fully deterministic — no I/O, no Claude, no HTTP.
"""

from __future__ import annotations


# ─────────────────────────── area classifier ────────────────────────────────


def test_classify_area_rural_from_village_type():
    from app.verification.services.commute_inputs import classify_area

    # Nominatim / Google reverse-geocode returns a ``place_type`` or
    # ``types`` list. We collapse to a coarse rural / urban / None.
    assert classify_area(place_type="village") == "rural"
    assert classify_area(place_type="hamlet") == "rural"
    assert classify_area(place_type="suburb") == "rural"


def test_classify_area_urban_from_city_type():
    from app.verification.services.commute_inputs import classify_area

    assert classify_area(place_type="city") == "urban"
    assert classify_area(place_type="town") == "urban"
    assert classify_area(place_type="locality") == "urban"


def test_classify_area_unknown_returns_none():
    from app.verification.services.commute_inputs import classify_area

    assert classify_area(place_type=None) is None
    assert classify_area(place_type="") is None
    assert classify_area(place_type="country") is None  # too coarse


def test_classify_area_falls_back_to_address_keyword_rural():
    """When ``place_type`` is None (typical when Google geocoder won —
    Google's ``types`` are too coarse for rural/urban) we should still
    catch obvious rural hints in the formatted address string."""
    from app.verification.services.commute_inputs import classify_area

    assert classify_area(
        place_type=None, address="H No 12, Village Sadipur, Hisar, Haryana 125001"
    ) == "rural"
    assert classify_area(
        place_type=None, address="Tehsil Rohtak, Haryana"
    ) == "rural"
    assert classify_area(
        place_type=None, address="Vill Bhuna, Mandi Adampur"
    ) == "rural"


def test_classify_area_falls_back_to_address_keyword_urban():
    """Only catch obvious urban-administrative keywords. We deliberately
    DON'T list well-known city names (Mumbai, Delhi, Bangalore, …) — that
    list rots fast and the judge tolerates None for ambiguous addresses."""
    from app.verification.services.commute_inputs import classify_area

    assert classify_area(
        place_type=None, address="Civil Lines, Delhi Municipal Corporation"
    ) == "urban"
    assert classify_area(
        place_type=None, address="Ward 23, Bangalore Nagar Nigam"
    ) == "urban"
    # Bare city name without an admin keyword stays None — the judge can
    # reason from the rest of the profile.
    assert classify_area(
        place_type=None, address="Andheri East, Mumbai 400069"
    ) is None


def test_classify_area_place_type_wins_over_address():
    """``place_type`` is the more authoritative signal — when both are
    present, it wins."""
    from app.verification.services.commute_inputs import classify_area

    # Address looks rural but place_type says urban → urban wins.
    assert (
        classify_area(
            place_type="city", address="Village Sadipur, Hisar, Haryana"
        )
        == "urban"
    )


def test_classify_area_both_none_returns_none():
    from app.verification.services.commute_inputs import classify_area

    assert classify_area(place_type=None, address=None) is None
    assert classify_area(place_type="", address="") is None


# ─────────────────────── bank-income-pattern classifier ──────────────────────


def test_bank_income_pattern_salary_dominant():
    """Monthly NEFT/IMPS credits whose narration contains 'salary' dominate
    cash-deposit volume → salary-earner pattern."""
    from app.verification.services.commute_inputs import (
        classify_bank_income_pattern,
    )

    transactions = [
        {"type": "credit", "channel": "NEFT", "narration": "SALARY MAR 2026 ACME CO"},
        {"type": "credit", "channel": "NEFT", "narration": "SALARY FEB 2026 ACME CO"},
        {"type": "credit", "channel": "NEFT", "narration": "SALARY JAN 2026 ACME CO"},
        {"type": "credit", "channel": "CASH", "narration": "CASH DEP BY SELF"},
    ]
    assert classify_bank_income_pattern(transactions) == "salary_credits"


def test_bank_income_pattern_cash_dominant():
    """Mostly cash deposits → cash-business pattern."""
    from app.verification.services.commute_inputs import (
        classify_bank_income_pattern,
    )

    transactions = [
        {"type": "credit", "channel": "CASH", "narration": "CASH DEP"},
        {"type": "credit", "channel": "CASH", "narration": "CASH DEP"},
        {"type": "credit", "channel": "CASH", "narration": "CASH DEP"},
        {"type": "credit", "channel": "NEFT", "narration": "PAYMENT RECV"},
    ]
    assert classify_bank_income_pattern(transactions) == "cash_deposits"


def test_bank_income_pattern_mixed():
    from app.verification.services.commute_inputs import (
        classify_bank_income_pattern,
    )

    transactions = [
        {"type": "credit", "channel": "NEFT", "narration": "PAYMENT RECV"},
        {"type": "credit", "channel": "NEFT", "narration": "PAYMENT RECV"},
        {"type": "credit", "channel": "CASH", "narration": "CASH DEP"},
    ]
    assert classify_bank_income_pattern(transactions) == "mixed"


def test_bank_income_pattern_empty_returns_none():
    from app.verification.services.commute_inputs import (
        classify_bank_income_pattern,
    )

    assert classify_bank_income_pattern([]) is None
    assert classify_bank_income_pattern(None) is None
