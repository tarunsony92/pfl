"""Step 8: Reconciliation — Sonnet.

Cross-checks stock turnover vs declared monthly sales, bank credits vs declared,
and calculates FOIR + IDIR.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 8
STEP_NAME = "reconciliation"
_TIER = "sonnet"
_MODEL_ID = MODELS[_TIER]

_SYSTEM_TEMPLATE = """\
You are a credit reconciliation analyst at PFL Finance, India.
Cross-check financial figures and calculate FOIR and IDIR.

Policy limits:
- FOIR cap: {foir_cap}%
- FOIR warn threshold: {foir_warn}%
- IDIR cap: {idir_cap}%
- Bank vs declared variance max: {variance_max}%

FOIR = (EMI obligations / net monthly income) × 100
IDIR = (total loan installments / gross monthly income) × 100

Respond ONLY with valid JSON matching this exact schema:
{{
  "foir": <float>,
  "foir_exceeds_cap": <boolean>,
  "foir_warn": <boolean>,
  "idir": <float>,
  "bank_vs_declared_variance": <float>,
  "stock_turnover_days": <integer or null>,
  "inconsistencies": [
    {{"metric": <string>, "expected": <string>, "actual": <string>,
      "severity": "low"|"medium"|"high"}}
  ]
}}
"""

_USER_TEMPLATE = """\
Step 2 (Banking) output:
{step2_output}

Step 3 (Income) output:
{step3_output}

Step 7 (Stock) output:
{step7_output}

AutoCAM declared figures:
{autocam_declared}
"""


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run reconciliation using Sonnet."""
    policy = ctx.policy
    hard_rules = policy.get("hard_rules", {})
    foir_cap = int(hard_rules.get("foir_cap_pct", 50))
    foir_warn = int(float(policy.get("foir_warn", 0.40)) * 100)
    idir_cap = int(hard_rules.get("idir_cap_pct", 50))
    variance_max = int(hard_rules.get("bank_declared_variance_pct_max", 15))

    step2 = ctx.prior_steps.get(2)
    step3 = ctx.prior_steps.get(3)
    step7 = ctx.prior_steps.get(7)

    autocam = (
        ctx.extractions.get("auto_cam")
        or ctx.extractions.get("autocam")
        or {}
    )
    autocam_declared = {
        k: v
        for k, v in autocam.items()
        if any(
            kw in k.lower()
            for kw in [
                "income", "sales", "turnover", "emi", "loan", "obligation",
                "monthly", "declared", "gross", "net",
            ]
        )
    }

    system_prompt = _SYSTEM_TEMPLATE.format(
        foir_cap=foir_cap,
        foir_warn=foir_warn,
        idir_cap=idir_cap,
        variance_max=variance_max,
    )
    user_message = _USER_TEMPLATE.format(
        step2_output=str(step2.output_data) if step2 else "Not available",
        step3_output=str(step3.output_data) if step3 else "Not available",
        step7_output=str(step7.output_data) if step7 else "Not available",
        autocam_declared=str(autocam_declared) if autocam_declared else "No declared figures",
    )

    try:
        message = await claude.invoke(
            tier=_TIER,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            cache_system=False,
            max_tokens=1024,
        )
        response_text = claude.extract_text(message)
        output_data = _extract_json_from_text(response_text)
        output_data.setdefault("foir", 0.0)
        output_data.setdefault("foir_exceeds_cap", False)
        output_data.setdefault("foir_warn", False)
        output_data.setdefault("idir", 0.0)
        output_data.setdefault("bank_vs_declared_variance", 0.0)
        output_data.setdefault("stock_turnover_days", None)
        output_data.setdefault("inconsistencies", [])

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
        _log.exception("Step 8 reconciliation failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
