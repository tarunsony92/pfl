"""Unit tests for Step 1: Policy Gates (pure Python, no LLM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.decisioning.steps.step_01_policy_gates import run
from app.enums import StepStatus

# ── Minimal StepContext ──────────────────────────────────────────────────────

@dataclass
class _Ctx:
    case: Any = None
    artifacts: list[Any] = field(default_factory=list)
    extractions: dict[str, dict] = field(default_factory=dict)
    policy: dict = field(default_factory=dict)
    heuristics: str = ""
    prior_steps: dict = field(default_factory=dict)


_DEFAULT_POLICY = {
    "hard_rules": {
        "cibil_min": 700,
        "coapplicant_cibil_min": 700,
        "max_total_indebtedness_inr": 500_000,
        "applicant_age_min": 21,
        "applicant_age_max": 60,
        "max_business_distance_km": 25,
        "foir_cap_pct": 50,
        "negative_statuses": ["WRITTEN_OFF", "SUIT_FILED", "LSS"],
    }
}


def _good_autocam(**overrides) -> dict:
    base = {
        "cibil_score": 750,
        "applicant_age": 35,
        "total_existing_indebtedness_inr": 100_000,
        "cibil_account_statuses": [],
    }
    base.update(overrides)
    return base


def _good_checklist(**overrides) -> dict:
    base = {"all_required_present": True, "missing_docs": []}
    base.update(overrides)
    return base


class TestPolicyGatesPass:
    @pytest.mark.asyncio
    async def test_all_gates_pass_returns_succeeded(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.status == StepStatus.SUCCEEDED
        assert result.hard_fail is False
        assert result.output_data["passed_all"] is True
        assert result.output_data["pause_for_upload"] is False
        assert result.model_used is None  # no LLM

    @pytest.mark.asyncio
    async def test_no_warnings_when_all_data_present(self):
        # Provide geo distance so the "no geo data" warning is not raised
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(business_distance_km=5.0),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_per_rule_results_populated(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        rules = result.output_data["per_rule_results"]
        assert "applicant_cibil" in rules
        assert rules["applicant_cibil"]["passed"] is True


class TestCIBILGate:
    @pytest.mark.asyncio
    async def test_cibil_below_700_hard_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(cibil_score=680),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.status == StepStatus.FAILED
        assert result.hard_fail is True
        assert result.error_message == "cibil_below_700"
        assert result.output_data["per_rule_results"]["applicant_cibil"]["passed"] is False

    @pytest.mark.asyncio
    async def test_cibil_exactly_700_passes(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(cibil_score=700),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.output_data["per_rule_results"]["applicant_cibil"]["passed"] is True

    @pytest.mark.asyncio
    async def test_cibil_zero_treated_as_650(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(cibil_score=0),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is True
        assert result.error_message == "cibil_below_700"

    @pytest.mark.asyncio
    async def test_missing_cibil_adds_warning(self):
        autocam = _good_autocam()
        del autocam["cibil_score"]
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": autocam, "checklist_validator": _good_checklist()},
        )
        result = await run(ctx, claude=None)
        assert any("cibil" in w.lower() for w in result.warnings)


class TestAgeGate:
    @pytest.mark.asyncio
    async def test_age_below_min_hard_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(applicant_age=20),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is True
        assert result.error_message == "age_out_of_bounds"

    @pytest.mark.asyncio
    async def test_age_above_max_hard_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(applicant_age=61),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is True
        assert result.error_message == "age_out_of_bounds"

    @pytest.mark.asyncio
    async def test_age_at_boundary_passes(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(applicant_age=60),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.output_data["per_rule_results"]["applicant_age"]["passed"] is True


class TestIndebtednessGate:
    @pytest.mark.asyncio
    async def test_indebtedness_at_cap_hard_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(total_existing_indebtedness_inr=500_000),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is True
        assert result.error_message == "indebtedness_exceeds_cap"

    @pytest.mark.asyncio
    async def test_indebtedness_below_cap_passes(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(total_existing_indebtedness_inr=499_999),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.output_data["per_rule_results"]["indebtedness"]["passed"] is True


class TestNegativeStatusGate:
    @pytest.mark.asyncio
    async def test_written_off_hard_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(cibil_account_statuses=["WRITTEN_OFF"]),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is True
        assert result.error_message == "negative_cibil_status"

    @pytest.mark.asyncio
    async def test_no_negative_statuses_passes(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(cibil_account_statuses=["STANDARD", "ACTIVE"]),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.output_data["per_rule_results"]["cibil_negative_status"]["passed"] is True


class TestGeoGate:
    @pytest.mark.asyncio
    async def test_geo_exceeds_limit_hard_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(business_distance_km=30.0),
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is True
        assert result.error_message == "business_outside_serviceable_area"

    @pytest.mark.asyncio
    async def test_geo_missing_adds_warning_not_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(),  # no business_distance_km
                "checklist_validator": _good_checklist(),
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is False
        assert any("geo" in w.lower() or "distance" in w.lower() for w in result.warnings)


class TestChecklistGate:
    @pytest.mark.asyncio
    async def test_missing_docs_sets_pause_flag_not_hard_fail(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": _good_autocam(),
                "checklist_validator": {
                    "all_required_present": False,
                    "missing_docs": ["bank_statement", "aadhaar"],
                },
            },
        )
        result = await run(ctx, claude=None)
        assert result.hard_fail is False
        assert result.output_data["pause_for_upload"] is True
        assert result.output_data["passed_all"] is False

    @pytest.mark.asyncio
    async def test_empty_extractions_skips_gracefully(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={},
        )
        result = await run(ctx, claude=None)
        # Should not raise; warnings should contain missing data notices
        assert result is not None
        assert result.warnings  # Some warnings expected for missing data
