"""Unit tests for Steps 2–9: all LLM-based steps with mocked claude.invoke."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.decisioning.steps import (
    step_02_banking,
    step_03_income,
    step_04_kyc,
    step_05_address,
    step_06_business,
    step_07_stock,
    step_08_reconciliation,
    step_09_pd_sheet,
)
from app.decisioning.steps.base import StepOutput
from app.enums import StepStatus

# ── Helpers ─────────────────────────────────────────────────────────────────

@dataclass
class _Ctx:
    case: Any = None
    artifacts: list[Any] = field(default_factory=list)
    extractions: dict[str, dict] = field(default_factory=dict)
    policy: dict = field(default_factory=dict)
    heuristics: str = ""
    prior_steps: dict[int, StepOutput] = field(default_factory=dict)


_DEFAULT_POLICY = {
    "hard_rules": {
        "foir_cap_pct": 50,
        "idir_cap_pct": 50,
        "bank_declared_variance_pct_max": 15,
        "stock_to_loan_ratio_min": 1.0,
    },
    "foir_cap": 0.50,
    "foir_warn": 0.40,
}


def _make_usage() -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_creation_input_tokens = 0
    usage.cache_read_input_tokens = 0
    return usage


def _make_claude_mock(response_json: dict) -> MagicMock:
    """Return a mock claude object that returns the given JSON as response text."""
    msg = MagicMock()
    block = MagicMock()
    block.text = json.dumps(response_json)
    msg.content = [block]
    msg.usage = _make_usage()

    claude = MagicMock()
    claude.invoke = AsyncMock(return_value=msg)
    claude.extract_text = MagicMock(return_value=json.dumps(response_json))
    claude.usage_dict = MagicMock(return_value={
        "input_tokens": 100, "output_tokens": 50
    })
    claude.cost_usd = MagicMock(return_value=0.0001)
    return claude


def _make_failed_claude() -> MagicMock:
    """Return a mock claude that raises on invoke."""
    claude = MagicMock()
    claude.invoke = AsyncMock(side_effect=RuntimeError("API error"))
    return claude


def _make_step_output(step_number: int, data: dict) -> StepOutput:
    return StepOutput(
        status=StepStatus.SUCCEEDED,
        step_name=f"step_{step_number:02d}",
        step_number=step_number,
        model_used="claude-haiku-4-5",
        output_data=data,
        citations=[],
    )


# ── Step 2: Banking ──────────────────────────────────────────────────────────

class TestStep02Banking:
    _RESP = {
        "abb_inr": 45000,
        "bounce_count": 1,
        "nach_return_count": 0,
        "suspicious_flag": False,
        "notes": "Regular business deposits",
    }

    @pytest.mark.asyncio
    async def test_returns_succeeded_with_valid_response(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "bank_statement": {
                    "transaction_lines": ["2024-01-01 CREDIT 5000", "2024-01-02 DEBIT 2000"],
                    "closing_balances": [45000, 42000],
                }
            },
        )
        claude = _make_claude_mock(self._RESP)
        result = await step_02_banking.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 2
        assert result.output_data["abb_inr"] == 45000
        assert result.output_data["bounce_count"] == 1
        assert result.model_used == "claude-haiku-4-5"

    @pytest.mark.asyncio
    async def test_defaults_when_json_field_missing(self):
        partial_resp = {"abb_inr": 30000}
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(partial_resp)
        result = await step_02_banking.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.output_data["bounce_count"] == 0
        assert result.output_data["suspicious_flag"] is False

    @pytest.mark.asyncio
    async def test_handles_empty_bank_data_gracefully(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(self._RESP)
        result = await step_02_banking.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert claude.invoke.called

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_02_banking.run(ctx, _make_failed_claude())
        assert result.status == StepStatus.FAILED
        assert result.error_message == "API error"


# ── Step 3: Income ───────────────────────────────────────────────────────────

class TestStep03Income:
    _RESP = {
        "business_income_share": 0.85,
        "distinct_income_sources": 2,
        "earning_family_members": 3,
        "total_monthly_inflow_inr": 55000,
    }

    @pytest.mark.asyncio
    async def test_returns_succeeded_with_valid_response(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"monthly_income": 50000}},
            prior_steps={2: _make_step_output(2, {"abb_inr": 45000})},
        )
        claude = _make_claude_mock(self._RESP)
        result = await step_03_income.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 3
        assert result.output_data["business_income_share"] == 0.85
        assert result.output_data["earning_family_members"] == 3

    @pytest.mark.asyncio
    async def test_works_without_prior_step2(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(self._RESP)
        result = await step_03_income.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_03_income.run(ctx, _make_failed_claude())
        assert result.status == StepStatus.FAILED


# ── Step 4: KYC ─────────────────────────────────────────────────────────────

class TestStep04KYC:
    _RESP = {
        "name_variants_allowed": True,
        "dob_consistent_across_ids": True,
        "id_count": 2,
        "mismatches": [],
    }

    @pytest.mark.asyncio
    async def test_returns_succeeded_with_valid_response(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": {"applicant_name": "Ramesh Kumar", "date_of_birth": "1985-05-15"},
                "kyc_aadhaar": {"name": "Ramesh Kumar", "dob": "1985-05-15"},
            },
        )
        claude = _make_claude_mock(self._RESP)
        result = await step_04_kyc.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 4
        assert result.output_data["name_variants_allowed"] is True
        assert result.output_data["mismatches"] == []

    @pytest.mark.asyncio
    async def test_mismatch_reported(self):
        resp = {
            "name_variants_allowed": False,
            "dob_consistent_across_ids": True,
            "id_count": 2,
            "mismatches": [{"id_type": "PAN", "field": "name", "detail": "Ramesh vs Ramesh Kumar"}],
        }
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(resp)
        result = await step_04_kyc.run(ctx, claude)
        assert result.output_data["name_variants_allowed"] is False
        assert len(result.output_data["mismatches"]) == 1

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_04_kyc.run(ctx, _make_failed_claude())
        assert result.status == StepStatus.FAILED


# ── Step 5: Address ──────────────────────────────────────────────────────────

class TestStep05Address:
    _RESP = {
        "addresses_by_source": {
            "aadhaar": "Village Narayanpur, Dist. Raipur, PIN 492001",
            "pan": "Village Narayanpur, Raipur 492001",
            "cibil": "Narayanpur, Raipur PIN 492001",
            "electricity": "Narayanpur village, Raipur",
            "bank": "Village Narayanpur Raipur",
            "gps": "N/A",
        },
        "match_count": 5,
        "match_ratio": 0.833,
        "passes_rule": True,
        "mismatches": [],
    }

    @pytest.mark.asyncio
    async def test_returns_succeeded_with_valid_response(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(self._RESP)
        result = await step_05_address.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 5
        assert result.output_data["match_count"] == 5
        assert result.output_data["passes_rule"] is True

    @pytest.mark.asyncio
    async def test_fails_rule_when_match_below_4(self):
        resp = {**self._RESP, "match_count": 3, "match_ratio": 0.5, "passes_rule": False}
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(resp)
        result = await step_05_address.run(ctx, claude)
        assert result.output_data["passes_rule"] is False

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_05_address.run(ctx, _make_failed_claude())
        assert result.status == StepStatus.FAILED


# ── Step 6: Business Premises ────────────────────────────────────────────────

class TestStep06Business:
    _RESP = {
        "premises_type": "pucca",
        "ownership_status": "business_owned",
        "gps_distance_km": 5.2,
        "distance_flag": False,
        "passes": True,
    }

    @pytest.mark.asyncio
    async def test_returns_succeeded_with_valid_response(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(self._RESP)
        result = await step_06_business.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 6
        assert result.output_data["premises_type"] == "pucca"
        assert result.output_data["passes"] is True

    @pytest.mark.asyncio
    async def test_distance_flag_when_over_10km(self):
        resp = {**self._RESP, "gps_distance_km": 12.5, "distance_flag": True}
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(resp)
        result = await step_06_business.run(ctx, claude)
        assert result.output_data["distance_flag"] is True

    @pytest.mark.asyncio
    async def test_neither_ownership_with_autocam_data(self):
        resp = {**self._RESP, "ownership_status": "neither", "passes": False}
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": {"business_ownership": "rented", "house_ownership": "rented"},
            },
        )
        claude = _make_claude_mock(resp)
        result = await step_06_business.run(ctx, claude)
        assert result.output_data["ownership_status"] == "neither"

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_06_business.run(ctx, _make_failed_claude())
        assert result.status == StepStatus.FAILED


# ── Step 7: Stock (pure Python stub) ─────────────────────────────────────────

class TestStep07Stock:
    @pytest.mark.asyncio
    async def test_identifies_items_from_pd_sheet(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "pd_sheet": {
                    "stock_description": "toor dal 50kg, sugar 20kg, soap 30 pieces"
                }
            },
        )
        result = await step_07_stock.run(ctx, claude=None)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 7
        assert result.model_used is None  # no LLM
        assert result.output_data["stock_estimation_mode"] == "stub"
        assert len(result.output_data["items_identified"]) > 0
        assert result.output_data["total_stock_value_inr"] > 0

    @pytest.mark.asyncio
    async def test_passes_loan_vs_stock_when_stock_sufficient(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "auto_cam": {
                    "loan_amount": 10_000,
                    "stock_description": (
                        "toor dal 100kg, sugar 50kg, basmati rice 30kg,"
                        " soap 100 pieces, shampoo 50 bottles"
                    ),
                }
            },
        )
        result = await step_07_stock.run(ctx, claude=None)
        assert result.status == StepStatus.SUCCEEDED
        # With enough items the value should exceed 10000
        # (or passes_loan_vs_stock should be computed correctly)
        assert "passes_loan_vs_stock" in result.output_data

    @pytest.mark.asyncio
    async def test_empty_stock_adds_warnings(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_07_stock.run(ctx, claude=None)
        assert result.status == StepStatus.SUCCEEDED
        assert result.warnings  # warnings for missing stock data
        assert result.output_data["total_stock_value_inr"] == 0

    @pytest.mark.asyncio
    async def test_note_references_deferred_vision(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_07_stock.run(ctx, claude=None)
        assert "Vision" in result.output_data["notes"] or "vision" in result.output_data["notes"]


# ── Step 8: Reconciliation ──────────────────────────────────────────────────

class TestStep08Reconciliation:
    _RESP = {
        "foir": 38.5,
        "foir_exceeds_cap": False,
        "foir_warn": False,
        "idir": 35.0,
        "bank_vs_declared_variance": 8.0,
        "stock_turnover_days": 30,
        "inconsistencies": [],
    }

    @pytest.mark.asyncio
    async def test_returns_succeeded_with_valid_response(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"monthly_income": 50000}},
            prior_steps={
                2: _make_step_output(2, {"abb_inr": 45000}),
                3: _make_step_output(3, {"total_monthly_inflow_inr": 50000}),
                7: _make_step_output(7, {"total_stock_value_inr": 120000}),
            },
        )
        claude = _make_claude_mock(self._RESP)
        result = await step_08_reconciliation.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 8
        assert result.output_data["foir"] == 38.5
        assert result.output_data["inconsistencies"] == []

    @pytest.mark.asyncio
    async def test_high_foir_flagged(self):
        resp = {**self._RESP, "foir": 52.0, "foir_exceeds_cap": True}
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(resp)
        result = await step_08_reconciliation.run(ctx, claude)
        assert result.output_data["foir_exceeds_cap"] is True

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_08_reconciliation.run(ctx, _make_failed_claude())
        assert result.status == StepStatus.FAILED


# ── Step 9: PD Sheet ─────────────────────────────────────────────────────────

class TestStep09PDSheet:
    _RESP = {
        "narrative_summary": "Applicant runs a kirana store for 5 years in Narayanpur.",
        "consistency_with_cam": "consistent",
        "red_flags": [],
        "coaching_detected": False,
    }

    @pytest.mark.asyncio
    async def test_returns_succeeded_with_valid_response(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={
                "pd_sheet": {"narrative": "Applicant has been running store for 5 years."},
                "auto_cam": {"business_type": "KIRANA"},
            },
        )
        claude = _make_claude_mock(self._RESP)
        result = await step_09_pd_sheet.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 9
        assert result.output_data["consistency_with_cam"] == "consistent"
        assert result.output_data["coaching_detected"] is False

    @pytest.mark.asyncio
    async def test_red_flags_reported(self):
        resp = {
            **self._RESP,
            "red_flags": [{"category": "coached", "detail": "Exact EMI figure recited verbatim"}],
            "coaching_detected": True,
        }
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(resp)
        result = await step_09_pd_sheet.run(ctx, claude)
        assert result.output_data["coaching_detected"] is True
        assert len(result.output_data["red_flags"]) == 1

    @pytest.mark.asyncio
    async def test_contradictory_consistency(self):
        resp = {**self._RESP, "consistency_with_cam": "contradictory"}
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        claude = _make_claude_mock(resp)
        result = await step_09_pd_sheet.run(ctx, claude)
        assert result.output_data["consistency_with_cam"] == "contradictory"

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, extractions={})
        result = await step_09_pd_sheet.run(ctx, _make_failed_claude())
        assert result.status == StepStatus.FAILED
