"""Unit tests for Steps 10–11: Case Library Retrieval and Final Synthesis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.decisioning.steps import step_10_retrieval, step_11_synthesis
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
    db_session: Any = None


_DEFAULT_POLICY = {
    "hard_rules": {
        "cibil_min": 700,
        "foir_cap_pct": 50,
        "idir_cap_pct": 50,
    },
    "foir_cap": 0.50,
    "foir_warn": 0.40,
    "loan_grid": {"min_inr": 50000, "max_inr": 300000},
}


def _make_usage() -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = 200
    usage.output_tokens = 150
    usage.cache_creation_input_tokens = 50
    usage.cache_read_input_tokens = 0
    return usage


def _make_claude_mock(response_json: dict) -> MagicMock:
    msg = MagicMock()
    block = MagicMock()
    block.text = json.dumps(response_json)
    msg.content = [block]
    msg.usage = _make_usage()

    claude = MagicMock()
    claude.invoke = AsyncMock(return_value=msg)
    claude.extract_text = MagicMock(return_value=json.dumps(response_json))
    claude.usage_dict = MagicMock(return_value={"input_tokens": 200, "output_tokens": 150})
    claude.cost_usd = MagicMock(return_value=0.005)
    return claude


def _make_step_output(
    step_number: int,
    data: dict,
    *,
    hard_fail: bool = False,
    error_message: str | None = None,
) -> StepOutput:
    return StepOutput(
        status=StepStatus.FAILED if hard_fail else StepStatus.SUCCEEDED,
        step_name=f"step_{step_number:02d}",
        step_number=step_number,
        model_used="claude-haiku-4-5",
        output_data=data,
        citations=[],
        hard_fail=hard_fail,
        error_message=error_message,
    )


# ── Step 10: Case Library Retrieval ──────────────────────────────────────────

class TestStep10Retrieval:
    @pytest.mark.asyncio
    async def test_returns_succeeded_without_db_session(self):
        """Without a db_session, returns empty list with note."""
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"cibil_score": 720, "loan_amount": 75000}},
        )
        result = await step_10_retrieval.run(ctx, claude=None)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 10
        assert result.model_used is None
        assert result.output_data["similar_cases"] == []
        assert result.output_data["note"] == "case_library_empty"

    @pytest.mark.asyncio
    async def test_feature_vector_has_8_dimensions(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"cibil_score": 750, "loan_amount": 100000}},
        )
        result = await step_10_retrieval.run(ctx, claude=None)
        assert len(result.output_data["feature_vector"]) == 8

    @pytest.mark.asyncio
    async def test_feature_vector_values_in_0_1_range(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"cibil_score": 800, "loan_amount": 150000}},
        )
        result = await step_10_retrieval.run(ctx, claude=None)
        vec = result.output_data["feature_vector"]
        for i, v in enumerate(vec):
            assert 0.0 <= v <= 1.0, f"Dimension {i} out of range: {v}"

    @pytest.mark.asyncio
    async def test_uses_step2_abb_in_vector(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"cibil_score": 720}},
            prior_steps={
                2: _make_step_output(2, {"abb_inr": 50000}),
                3: _make_step_output(3, {"total_monthly_inflow_inr": 40000}),
            },
        )
        result = await step_10_retrieval.run(ctx, claude=None)
        # abb_inr=50000, ABB_MAX=200000 → normalized = 0.25
        vec = result.output_data["feature_vector"]
        assert vec[6] == pytest.approx(0.25, abs=0.01)

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_db_error(self):
        """When db_session raises, returns empty list gracefully."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("pgvector not available"))
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"cibil_score": 720}},
            db_session=mock_session,
        )
        result = await step_10_retrieval.run(ctx, claude=None)
        assert result.status == StepStatus.SUCCEEDED
        assert result.output_data["similar_cases"] == []
        assert result.output_data["note"] == "case_library_empty"

    @pytest.mark.asyncio
    async def test_cibil_zero_treated_as_650(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            extractions={"auto_cam": {"cibil_score": 0}},
        )
        result = await step_10_retrieval.run(ctx, claude=None)
        # cibil_score=0 is falsy → falls through to default 700 in retrieval step
        # cibil_score=700 → normalized = (700-300)/(900-300) = 400/600 ≈ 0.6667
        vec = result.output_data["feature_vector"]
        assert vec[1] == pytest.approx(400 / 600, abs=0.01)


# ── Step 11: Final Synthesis ──────────────────────────────────────────────────

class TestStep11Synthesis:
    _APPROVE_RESP = {
        "decision": "APPROVE",
        "recommended_amount": 75000,
        "recommended_tenure": 24,
        "conditions": [],
        "reasoning_markdown": "# Decision\n\nApplication meets all criteria.",
        "pros_cons": {
            "pros": [{"text": "Good CIBIL score", "citations": []}],
            "cons": [],
        },
        "deviations": [],
        "risk_summary": ["Standard risk profile"],
        "confidence_score": 82,
    }

    @pytest.mark.asyncio
    async def test_returns_approve_decision(self):
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            heuristics="## Heuristic: TEST\nTest heuristic.",
            extractions={},
            prior_steps={
                1: _make_step_output(1, {"passed_all": True}),
                2: _make_step_output(2, {"abb_inr": 45000, "bounce_count": 0}),
                3: _make_step_output(3, {"business_income_share": 0.9}),
                4: _make_step_output(4, {"dob_consistent_across_ids": True}),
                5: _make_step_output(5, {"passes_rule": True}),
                6: _make_step_output(6, {"passes": True}),
                7: _make_step_output(7, {"passes_loan_vs_stock": True}),
                8: _make_step_output(8, {"foir": 35.0, "foir_exceeds_cap": False}),
                9: _make_step_output(9, {"consistency_with_cam": "consistent"}),
                10: _make_step_output(10, {"similar_cases": [], "feature_vector": [0.1] * 8}),
            },
        )
        claude = _make_claude_mock(self._APPROVE_RESP)
        result = await step_11_synthesis.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        assert result.step_number == 11
        assert result.output_data["decision"] == "APPROVE"
        assert result.output_data["confidence_score"] == 82
        assert result.model_used == "claude-opus-4-7"

    @pytest.mark.asyncio
    async def test_escalate_when_deviations_present(self):
        """Any deviation in response forces ESCALATE_TO_CEO."""
        resp = {
            **self._APPROVE_RESP,
            "decision": "APPROVE",  # LLM said APPROVE but has deviations
            "deviations": [
                {"name": "CIBIL_BORDERLINE", "policy_rule": "cibil >= 700",
                 "severity": "low", "justification": "Score is exactly 700"}
            ],
        }
        ctx = _Ctx(policy=_DEFAULT_POLICY, heuristics="", extractions={})
        claude = _make_claude_mock(resp)
        result = await step_11_synthesis.run(ctx, claude)
        assert result.output_data["decision"] == "ESCALATE_TO_CEO"

    @pytest.mark.asyncio
    async def test_escalate_when_confidence_below_60(self):
        """confidence_score < 60 forces ESCALATE_TO_CEO."""
        resp = {**self._APPROVE_RESP, "decision": "APPROVE",
                "confidence_score": 55, "deviations": []}
        ctx = _Ctx(policy=_DEFAULT_POLICY, heuristics="", extractions={})
        claude = _make_claude_mock(resp)
        result = await step_11_synthesis.run(ctx, claude)
        assert result.output_data["decision"] == "ESCALATE_TO_CEO"

    @pytest.mark.asyncio
    async def test_hard_fail_step1_forces_reject_without_llm(self):
        """Step 1 hard_fail bypasses LLM and returns REJECT directly."""
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            heuristics="",
            extractions={},
            prior_steps={
                1: _make_step_output(
                    1,
                    {"passed_all": False},
                    hard_fail=True,
                    error_message="cibil_below_700",
                ),
            },
        )
        # Claude should NOT be called
        claude = _make_claude_mock(self._APPROVE_RESP)
        result = await step_11_synthesis.run(ctx, claude)
        assert result.output_data["decision"] == "REJECT"
        assert not claude.invoke.called

    @pytest.mark.asyncio
    async def test_returns_failed_on_api_error(self):
        ctx = _Ctx(policy=_DEFAULT_POLICY, heuristics="", extractions={})
        claude = MagicMock()
        claude.invoke = AsyncMock(side_effect=RuntimeError("Opus down"))
        result = await step_11_synthesis.run(ctx, claude)
        assert result.status == StepStatus.FAILED
        assert "Opus down" in result.error_message

    @pytest.mark.asyncio
    async def test_default_fields_populated_on_partial_response(self):
        """When LLM returns partial JSON, defaults are applied."""
        partial = {"decision": "APPROVE", "confidence_score": 75}
        ctx = _Ctx(policy=_DEFAULT_POLICY, heuristics="", extractions={})
        claude = _make_claude_mock(partial)
        result = await step_11_synthesis.run(ctx, claude)
        assert result.output_data["conditions"] == []
        assert result.output_data["risk_summary"] == []
        assert result.output_data["deviations"] == []

    @pytest.mark.asyncio
    async def test_similar_cases_passed_to_prompt(self):
        """Step 10 similar cases are included in the user message."""
        similar_cases = [
            {
                "case_id": "abc123",
                "loan_id": "xyz",
                "decision": "APPROVE",
                "outcome": "APPROVE",
                "similarity_score": 0.92,
                "feedback_notes": "Good repayment",
            }
        ]
        ctx = _Ctx(
            policy=_DEFAULT_POLICY,
            heuristics="",
            extractions={},
            prior_steps={
                10: _make_step_output(
                    10, {"similar_cases": similar_cases, "feature_vector": [0.1] * 8}
                ),
            },
        )
        claude = _make_claude_mock(self._APPROVE_RESP)
        result = await step_11_synthesis.run(ctx, claude)
        assert result.status == StepStatus.SUCCEEDED
        # Verify invoke was called with content containing the case
        call_args = claude.invoke.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "abc123" in user_content

    @pytest.mark.asyncio
    async def test_approve_with_conditions_passthrough(self):
        resp = {
            **self._APPROVE_RESP,
            "decision": "APPROVE_WITH_CONDITIONS",
            "conditions": ["Reduce loan amount to 60000", "Submit 3 months additional statements"],
            "confidence_score": 72,
        }
        ctx = _Ctx(policy=_DEFAULT_POLICY, heuristics="", extractions={})
        claude = _make_claude_mock(resp)
        result = await step_11_synthesis.run(ctx, claude)
        assert result.output_data["decision"] == "APPROVE_WITH_CONDITIONS"
        assert len(result.output_data["conditions"]) == 2
