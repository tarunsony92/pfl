"""Tests for ``_compute_commute_sub_step`` — the orchestration unit that
combines Distance Matrix + judge + cross-check to produce the 3b sub-step
result. Mocks the two external deps (Distance Matrix fn, judge fn) so no
real HTTP / Claude calls are made.

The helper is the seam that L1's ``run_level_1_address`` delegates to.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

from app.enums import LevelIssueSeverity
from app.verification.levels.level_1_address import _compute_commute_sub_step
from app.verification.services.commute_judge import CommuteJudgeVerdict
from app.verification.services.google_maps import DistanceMatrixResult


def _profile() -> dict:
    return {
        "applicant_occupation_from_form": "tailor",
        "applicant_business_type_hint": None,
        "loan_amount_inr": 60_000,
        "area_class": "rural",
        "bureau_occupation_history": None,
        "bank_income_pattern": "cash_deposits",
        "house_derived_address": "Village Sadipur, Hisar",
        "business_derived_address": "Hisar Main Market",
    }


# ── 1. Happy path: under 30 min ─────────────────────────────────────────────


async def test_commute_happy_path_under_30_min_no_issue():
    dm = AsyncMock(
        return_value=DistanceMatrixResult(
            distance_km=9.2, travel_minutes=18.0, raw_status="ok"
        )
    )
    judge = AsyncMock()  # must NOT be called

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.16, 75.72),
        business_coords=(29.15, 75.73),
        prior_house_coords=None,
        prior_business_coords=None,
        prior_commute_fields=None,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert issues == []
    assert fields["commute_sub_step_status"] == "pass"
    assert fields["commute_travel_minutes"] == 18.0
    assert fields["commute_distance_km"] == 9.2
    assert fields["commute_judge_verdict"] is None
    assert cost == Decimal("0")
    dm.assert_awaited_once()
    judge.assert_not_awaited()


# ── 2. Over 30 min, judge returns WARNING ───────────────────────────────────


async def test_commute_over_30_min_judge_warning():
    dm = AsyncMock(
        return_value=DistanceMatrixResult(
            distance_km=28.0, travel_minutes=42.0, raw_status="ok"
        )
    )
    judge = AsyncMock(
        return_value=CommuteJudgeVerdict(
            severity="WARNING",
            reason="Wholesale trader — 28 km drive is normal for this trade.",
            confidence="medium",
            model_used="claude-opus-4-7",
            cost_usd=Decimal("0.022"),
        )
    )

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.16, 75.72),
        business_coords=(28.9, 75.9),
        prior_house_coords=None,
        prior_business_coords=None,
        prior_commute_fields=None,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert len(issues) == 1
    assert issues[0]["sub_step_id"] == "house_business_commute"
    assert issues[0]["severity"] == LevelIssueSeverity.WARNING.value
    assert fields["commute_sub_step_status"] == "flag_reviewable"
    assert fields["commute_judge_verdict"]["severity"] == "WARNING"
    assert cost == Decimal("0.022")
    judge.assert_awaited_once()


# ── 3. Over 30 min, judge returns CRITICAL ──────────────────────────────────


async def test_commute_over_30_min_judge_critical():
    dm = AsyncMock(
        return_value=DistanceMatrixResult(
            distance_km=70.0, travel_minutes=95.0, raw_status="ok"
        )
    )
    judge = AsyncMock(
        return_value=CommuteJudgeVerdict(
            severity="CRITICAL",
            reason="Tailor on a ₹60k loan with 95-min commute is implausible.",
            confidence="high",
            model_used="claude-opus-4-7",
            cost_usd=Decimal("0.044"),
        )
    )

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.16, 75.72),
        business_coords=(28.5, 76.5),
        prior_house_coords=None,
        prior_business_coords=None,
        prior_commute_fields=None,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.CRITICAL.value
    assert fields["commute_sub_step_status"] == "block_absurd"
    assert fields["commute_judge_verdict"]["severity"] == "CRITICAL"


# ── 4. Over 30 min, judge call failed ───────────────────────────────────────


async def test_commute_over_30_min_judge_unavailable():
    dm = AsyncMock(
        return_value=DistanceMatrixResult(
            distance_km=32.0, travel_minutes=55.0, raw_status="ok"
        )
    )
    judge = AsyncMock(return_value=None)

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.16, 75.72),
        business_coords=(28.9, 75.9),
        prior_house_coords=None,
        prior_business_coords=None,
        prior_commute_fields=None,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.WARNING.value
    assert fields["commute_sub_step_status"] == "warn_judge_unavailable"
    assert fields["commute_judge_verdict"] is None


# ── 5. Distance Matrix ZERO_RESULTS ─────────────────────────────────────────


async def test_commute_dm_zero_results_emits_critical():
    dm = AsyncMock(
        return_value=DistanceMatrixResult(
            distance_km=0.0, travel_minutes=0.0, raw_status="zero_results"
        )
    )
    judge = AsyncMock()  # must NOT be called

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.16, 75.72),
        business_coords=(28.9, 75.9),
        prior_house_coords=None,
        prior_business_coords=None,
        prior_commute_fields=None,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.CRITICAL.value
    assert fields["commute_sub_step_status"] == "block_no_route"
    judge.assert_not_awaited()


# ── 6. Distance Matrix infra error ──────────────────────────────────────────


async def test_commute_dm_returns_none_emits_warning():
    dm = AsyncMock(return_value=None)
    judge = AsyncMock()

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.16, 75.72),
        business_coords=(28.9, 75.9),
        prior_house_coords=None,
        prior_business_coords=None,
        prior_commute_fields=None,
        profile_inputs=_profile(),
        claude=None,
        api_key="",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.WARNING.value
    assert fields["commute_sub_step_status"] == "warn_dm_unavailable"
    judge.assert_not_awaited()


# ── 7. Cache reuse — unchanged coords short-circuit both DM and judge ───────


async def test_commute_cache_hit_reuses_prior_fields():
    dm = AsyncMock()  # must NOT be called
    judge = AsyncMock()  # must NOT be called

    prior_fields = {
        "commute_distance_km": 28.0,
        "commute_travel_minutes": 42.0,
        "commute_judge_verdict": {
            "severity": "WARNING",
            "reason": "Wholesale trader.",
            "confidence": "medium",
        },
        "commute_sub_step_status": "flag_reviewable",
    }

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.160001, 75.720001),  # rounded equal to prior
        business_coords=(28.900001, 75.900001),
        prior_house_coords=(29.16, 75.72),
        prior_business_coords=(28.9, 75.9),
        prior_commute_fields=prior_fields,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    # Cache hit → emit the same issue, fields copied verbatim, $0 new cost.
    assert fields["commute_travel_minutes"] == 42.0
    assert fields["commute_sub_step_status"] == "flag_reviewable"
    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.WARNING.value
    assert cost == Decimal("0")
    dm.assert_not_awaited()
    judge.assert_not_awaited()


# ── 8. Cache miss when coords drift > 5 dp ──────────────────────────────────


async def test_commute_cache_hit_reissues_warn_dm_unavailable():
    """Regression: if the prior L1 run saw a DM failure (warn_dm_unavailable),
    a cache-reuse run must re-emit the same WARNING. Previously the cache
    path hardcoded dm_status='ok' which silently dropped the warning."""
    dm = AsyncMock()  # must NOT be called
    judge = AsyncMock()  # must NOT be called

    prior_fields = {
        "commute_distance_km": None,
        "commute_travel_minutes": None,
        "commute_judge_verdict": None,
        "commute_sub_step_status": "warn_dm_unavailable",
    }

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.01, 75.60),
        business_coords=(29.00, 75.60),
        prior_house_coords=(29.01, 75.60),
        prior_business_coords=(29.00, 75.60),
        prior_commute_fields=prior_fields,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert fields["commute_sub_step_status"] == "warn_dm_unavailable"
    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.WARNING.value
    assert issues[0]["sub_step_id"] == "house_business_commute"
    dm.assert_not_awaited()
    judge.assert_not_awaited()


async def test_commute_cache_hit_reissues_block_no_route():
    """Regression: same bug class for a prior block_no_route (CRITICAL)."""
    dm = AsyncMock()
    judge = AsyncMock()

    prior_fields = {
        "commute_distance_km": 0.0,
        "commute_travel_minutes": 0.0,
        "commute_judge_verdict": None,
        "commute_sub_step_status": "block_no_route",
    }

    _, issues, _ = await _compute_commute_sub_step(
        house_coords=(29.01, 75.60),
        business_coords=(29.00, 75.60),
        prior_house_coords=(29.01, 75.60),
        prior_business_coords=(29.00, 75.60),
        prior_commute_fields=prior_fields,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.CRITICAL.value


async def test_commute_cache_hit_without_status_key_does_not_crash():
    """Schema drift: a prior L1 row from an older deploy may carry the
    coord pair but lack ``commute_sub_step_status``. The replay path must
    treat this as 'no issue to replay' rather than crashing on a KeyError
    or dispatching into an unknown branch."""
    dm = AsyncMock()  # must NOT be called when cache hits
    judge = AsyncMock()

    prior_fields = {
        "commute_distance_km": 9.0,
        "commute_travel_minutes": 18.0,
        "commute_judge_verdict": None,
        # commute_sub_step_status deliberately omitted
    }

    fields, issues, cost = await _compute_commute_sub_step(
        house_coords=(29.01, 75.60),
        business_coords=(29.00, 75.60),
        prior_house_coords=(29.01, 75.60),
        prior_business_coords=(29.00, 75.60),
        prior_commute_fields=prior_fields,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert issues == []  # unknown status → no replay
    assert cost == Decimal("0")
    dm.assert_not_awaited()
    judge.assert_not_awaited()


async def test_commute_cache_hit_reissues_warn_judge_unavailable():
    """Regression: prior run had >30 min + judge failed. Cache must replay
    the WARNING with the 'review manually' copy."""
    dm = AsyncMock()
    judge = AsyncMock()

    prior_fields = {
        "commute_distance_km": 32.0,
        "commute_travel_minutes": 55.0,
        "commute_judge_verdict": None,
        "commute_sub_step_status": "warn_judge_unavailable",
    }

    _, issues, _ = await _compute_commute_sub_step(
        house_coords=(29.01, 75.60),
        business_coords=(29.00, 75.60),
        prior_house_coords=(29.01, 75.60),
        prior_business_coords=(29.00, 75.60),
        prior_commute_fields=prior_fields,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert len(issues) == 1
    assert issues[0]["severity"] == LevelIssueSeverity.WARNING.value
    assert "manually" in issues[0]["description"].lower()


async def test_commute_cache_miss_when_coords_change():
    dm = AsyncMock(
        return_value=DistanceMatrixResult(
            distance_km=10.0, travel_minutes=20.0, raw_status="ok"
        )
    )
    judge = AsyncMock()

    prior_fields = {
        "commute_distance_km": 28.0,
        "commute_travel_minutes": 42.0,
        "commute_judge_verdict": None,
        "commute_sub_step_status": "flag_reviewable",
    }

    fields, _, _ = await _compute_commute_sub_step(
        house_coords=(29.16, 75.72),
        business_coords=(28.95, 75.95),  # meaningfully moved from 28.9, 75.9
        prior_house_coords=(29.16, 75.72),
        prior_business_coords=(28.9, 75.9),
        prior_commute_fields=prior_fields,
        profile_inputs=_profile(),
        claude=None,
        api_key="FAKE",
        distance_matrix_fn=dm,
        judge_fn=judge,
    )

    assert fields["commute_travel_minutes"] == 20.0  # fresh, not cached
    dm.assert_awaited_once()
