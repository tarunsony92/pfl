"""Step 3: Income Analysis — Haiku.

Classifies each credit, computes business-income share, counts
distinct income sources and earning family members.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 3
STEP_NAME = "income_analysis"
_TIER = "haiku"
_MODEL_ID = MODELS[_TIER]

_SYSTEM = """\
You are a credit income analyst at PFL Finance, India.
Classify each credit entry and summarize income composition.
Respond ONLY with valid JSON matching this exact schema:
{
  "business_income_share": <float between 0 and 1>,
  "distinct_income_sources": <integer>,
  "earning_family_members": <integer>,
  "total_monthly_inflow_inr": <integer or null>
}
"""

_USER_TEMPLATE = """\
Step 2 banking output:
{banking_output}

AutoCAM income fields:
{autocam_income}
"""


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run income analysis using Haiku."""
    step2 = ctx.prior_steps.get(2)
    banking_output = step2.output_data if step2 else {}

    autocam = (
        ctx.extractions.get("auto_cam")
        or ctx.extractions.get("autocam")
        or {}
    )
    autocam_income = {
        k: v
        for k, v in autocam.items()
        if any(
            kw in k.lower()
            for kw in ["income", "earning", "salary", "business", "family", "member"]
        )
    }

    user_message = _USER_TEMPLATE.format(
        banking_output=str(banking_output),
        autocam_income=str(autocam_income),
    )

    try:
        message = await claude.invoke(
            tier=_TIER,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            cache_system=True,
            max_tokens=256,
        )
        response_text = claude.extract_text(message)
        output_data = _extract_json_from_text(response_text)
        output_data.setdefault("business_income_share", 0.0)
        output_data.setdefault("distinct_income_sources", 1)
        output_data.setdefault("earning_family_members", 1)
        output_data.setdefault("total_monthly_inflow_inr", None)

        usage = build_usage(message, _MODEL_ID)
        return StepOutput(
            status=StepStatus.SUCCEEDED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data=output_data,
            citations=[],
            **usage,
        )
    except Exception as exc:  # noqa: BLE001
        _log.exception("Step 3 income analysis failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
