"""Tests for Phase-E: Step 11 synthesis prompt now includes the 4-level gate
outputs as highest-weight evidence + post-synthesis escalation override.

These are pure-logic tests on ``_format_verification_outputs`` + the BLOCKED-
override branch of ``run``. The real LLM call is mocked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


def _ctx(verif: dict | None):
    return SimpleNamespace(
        policy={"rules": []},
        heuristics="heuristics",
        prior_steps={},
        verification_results=verif,
        db_session=None,
    )


def test_format_verification_outputs_empty_returns_empty_summary():
    from app.decisioning.steps.step_11_synthesis import _format_verification_outputs

    js, summary = _format_verification_outputs(_ctx(None))
    assert summary == {}
    # JSON must still be parseable
    assert json.loads(js) == {"_summary": {}}


def test_format_verification_outputs_records_statuses():
    from app.decisioning.steps.step_11_synthesis import _format_verification_outputs

    class _Row:
        def __init__(self, status_value: str):
            self.status = SimpleNamespace(value=status_value)
            self.cost_usd = None
            self.sub_step_results = {"issue_count": 0}
            self.started_at = None
            self.completed_at = None

    verif = {
        "L1_ADDRESS": _Row("PASSED"),
        "L2_BANKING": None,  # not yet run
        "L3_VISION": None,
        "L4_AGREEMENT": _Row("BLOCKED"),
    }
    js, summary = _format_verification_outputs(_ctx(verif))
    assert summary == {
        "L1_ADDRESS": "PASSED",
        "L2_BANKING": "PENDING",
        "L3_VISION": "PENDING",
        "L4_AGREEMENT": "BLOCKED",
    }
    payload = json.loads(js)
    assert payload["L1_ADDRESS"]["status"] == "PASSED"
    assert payload["L2_BANKING"]["status"] == "PENDING"
    assert payload["L4_AGREEMENT"]["status"] == "BLOCKED"
    assert payload["_summary"] == summary


async def test_step_11_escalates_on_blocked_level_regardless_of_opus_output():
    """Even if Opus returns APPROVE, a BLOCKED level must override to ESCALATE."""
    from app.decisioning.steps import step_11_synthesis as s11

    class _Row:
        def __init__(self, status_value: str):
            self.status = SimpleNamespace(value=status_value)
            self.cost_usd = None
            self.sub_step_results = {"issue_count": 1}
            self.started_at = None
            self.completed_at = None

    ctx = _ctx(
        {
            "L1_ADDRESS": _Row("BLOCKED"),
            "L2_BANKING": None,
            "L3_VISION": None,
            "L4_AGREEMENT": _Row("PASSED"),
        }
    )

    # Mock Claude to return an APPROVE verdict with high confidence
    mock_msg = MagicMock()
    mock_msg.usage.input_tokens = 1000
    mock_msg.usage.output_tokens = 100
    mock_msg.usage.cache_creation_input_tokens = 0
    mock_msg.usage.cache_read_input_tokens = 0
    claude = MagicMock()
    claude.invoke = AsyncMock(return_value=mock_msg)
    claude.extract_text = MagicMock(
        return_value=json.dumps(
            {
                "decision": "APPROVE",
                "recommended_amount": 100000,
                "recommended_tenure": 24,
                "conditions": [],
                "reasoning_markdown": "looks fine",
                "pros_cons": {"pros": [], "cons": []},
                "deviations": [],
                "risk_summary": [],
                "confidence_score": 92,
            }
        )
    )

    out = await s11.run(ctx, claude)

    assert out.output_data["decision"] == "ESCALATE_TO_CEO"
    assert out.output_data["verification_summary"]["L1_ADDRESS"] == "BLOCKED"
    # Post-processing must leave a trace of the gate in risk_summary
    rs = out.output_data.get("risk_summary") or []
    assert any("unresolved 4-level gates" in str(r) for r in rs)


async def test_step_11_passes_through_approve_when_all_gates_green():
    """All gates PASSED + confidence >= threshold → Opus's APPROVE is kept."""
    from app.decisioning.steps import step_11_synthesis as s11

    class _Row:
        def __init__(self, status_value: str):
            self.status = SimpleNamespace(value=status_value)
            self.cost_usd = None
            self.sub_step_results = {"issue_count": 0}
            self.started_at = None
            self.completed_at = None

    ctx = _ctx(
        {
            "L1_ADDRESS": _Row("PASSED"),
            "L2_BANKING": _Row("PASSED"),
            "L3_VISION": _Row("PASSED"),
            "L4_AGREEMENT": _Row("PASSED"),
        }
    )

    mock_msg = MagicMock()
    mock_msg.usage.input_tokens = 1000
    mock_msg.usage.output_tokens = 100
    mock_msg.usage.cache_creation_input_tokens = 0
    mock_msg.usage.cache_read_input_tokens = 0
    claude = MagicMock()
    claude.invoke = AsyncMock(return_value=mock_msg)
    claude.extract_text = MagicMock(
        return_value=json.dumps(
            {
                "decision": "APPROVE",
                "recommended_amount": 100000,
                "recommended_tenure": 24,
                "conditions": [],
                "reasoning_markdown": "looks fine",
                "pros_cons": {"pros": [], "cons": []},
                "deviations": [],
                "risk_summary": [],
                "confidence_score": 92,
            }
        )
    )

    out = await s11.run(ctx, claude)
    assert out.output_data["decision"] == "APPROVE"
