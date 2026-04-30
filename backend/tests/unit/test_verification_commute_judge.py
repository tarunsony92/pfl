"""Tests for the Opus commute-reasonableness judge.

Mocks ``ClaudeService`` so no real API calls are made. The judge is only
invoked when ``travel_minutes > 30``, and its floor verdict is WARNING —
never PASS — by contract.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.verification.services.commute_judge import (
    CommuteJudgeVerdict,
    judge_commute_reasonableness,
)


def _mock_claude(
    json_payload: dict | None,
    *,
    raw: str | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    mock_msg = MagicMock(name="Message")
    c = MagicMock(name="ClaudeService")
    if raise_exc is not None:
        c.invoke = AsyncMock(side_effect=raise_exc)
    else:
        c.invoke = AsyncMock(return_value=mock_msg)
    text = raw if raw is not None else json.dumps(json_payload or {})
    c.extract_text = MagicMock(return_value=text)
    c.usage_dict = MagicMock(return_value={"input_tokens": 1200, "output_tokens": 180})
    c.cost_usd = MagicMock(return_value=0.022)
    return c


# Happy-path inputs — reused across tests.
_BASE_INPUTS = dict(
    travel_minutes=42.0,
    distance_km=28.0,
    applicant_occupation_from_form="wholesale grain dealer",
    applicant_business_type_hint="wholesale_shop",
    loan_amount_inr=250_000,
    area_class="rural",
    bureau_occupation_history="AGRI / WHOLESALE TRADE",
    bank_income_pattern="mixed",
    house_derived_address="Sadipur Village, Hisar, Haryana",
    business_derived_address="Hisar Main Market, Haryana",
)


async def test_judge_returns_warning_verdict_on_valid_warning_json():
    payload = {
        "severity": "WARNING",
        "reason": (
            "Wholesale grain dealer with a market-adjacent business — a 28 km "
            "drive to the mandi is normal for this trade."
        ),
        "confidence": "medium",
    }
    claude = _mock_claude(payload)

    v = await judge_commute_reasonableness(**_BASE_INPUTS, claude=claude)

    assert v is not None
    assert isinstance(v, CommuteJudgeVerdict)
    assert v.severity == "WARNING"
    assert "wholesale" in v.reason.lower()
    assert v.confidence == "medium"
    assert v.cost_usd == Decimal("0.022")

    # Opus tier + prompt caching enforced.
    kwargs = claude.invoke.call_args.kwargs
    assert kwargs["tier"] == "opus"
    assert kwargs.get("cache_system") is True
    assert kwargs.get("max_tokens") == 400


async def test_judge_returns_critical_verdict_on_valid_critical_json():
    payload = {
        "severity": "CRITICAL",
        "reason": (
            "Tea-stall owner on a ₹40k loan, village resident, 95-min commute "
            "is implausible — strongly suggests proxy borrower."
        ),
        "confidence": "high",
    }
    claude = _mock_claude(payload)

    inputs = {
        **_BASE_INPUTS,
        "travel_minutes": 95.0,
        "distance_km": 70.0,
        "applicant_occupation_from_form": "tea stall owner",
        "loan_amount_inr": 40_000,
    }
    v = await judge_commute_reasonableness(**inputs, claude=claude)

    assert v is not None
    assert v.severity == "CRITICAL"
    assert v.confidence == "high"


async def test_judge_returns_none_on_unparseable_response():
    claude = _mock_claude(None, raw="This is not JSON at all — just prose.")
    v = await judge_commute_reasonableness(**_BASE_INPUTS, claude=claude)
    assert v is None


async def test_judge_returns_none_on_invalid_severity_label():
    """Opus returned JSON but severity is not in the allowed set — treat as
    a parse failure so the caller falls back to WARNING with 'unavailable'
    copy instead of silently trusting a malformed verdict."""
    payload = {
        "severity": "PASS",  # not allowed — judge must never return PASS
        "reason": "looks fine",
        "confidence": "low",
    }
    claude = _mock_claude(payload)
    v = await judge_commute_reasonableness(**_BASE_INPUTS, claude=claude)
    assert v is None


async def test_judge_returns_none_on_claude_error():
    claude = _mock_claude(None, raise_exc=RuntimeError("network down"))
    v = await judge_commute_reasonableness(**_BASE_INPUTS, claude=claude)
    assert v is None


async def test_judge_includes_profile_inputs_in_user_message():
    """Smoke test that the input dict actually reaches the model — regression
    guard so someone can't accidentally drop a field from the prompt."""
    payload = {
        "severity": "WARNING",
        "reason": "reasonable given wholesale trade",
        "confidence": "medium",
    }
    claude = _mock_claude(payload)
    await judge_commute_reasonableness(**_BASE_INPUTS, claude=claude)

    messages = claude.invoke.call_args.kwargs["messages"]
    user_text = json.dumps(messages)
    assert "wholesale grain dealer" in user_text
    assert "250000" in user_text or "2,50,000" in user_text or "250,000" in user_text
    assert "rural" in user_text
    assert "42" in user_text  # travel_minutes
    assert "28" in user_text  # distance_km


async def test_judge_tolerates_null_profile_fields():
    """Fields can legitimately be None — the judge still runs."""
    payload = {
        "severity": "WARNING",
        "reason": "insufficient profile data — reviewable",
        "confidence": "low",
    }
    claude = _mock_claude(payload)

    inputs = {
        "travel_minutes": 35.0,
        "distance_km": 20.0,
        "applicant_occupation_from_form": None,
        "applicant_business_type_hint": None,
        "loan_amount_inr": None,
        "area_class": None,
        "bureau_occupation_history": None,
        "bank_income_pattern": None,
        "house_derived_address": None,
        "business_derived_address": None,
    }
    v = await judge_commute_reasonableness(**inputs, claude=claude)
    assert v is not None
    assert v.severity == "WARNING"
