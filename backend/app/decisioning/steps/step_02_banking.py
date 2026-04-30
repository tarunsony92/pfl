"""Step 2: Banking Check — Haiku.

Classifies bank credits, computes ABB, counts bounces/NACH returns.
System block is cached (policy FOIR cap + heuristics about banking patterns).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 2
STEP_NAME = "banking_check"
_TIER = "haiku"
_MODEL_ID = MODELS[_TIER]

_SYSTEM_TEMPLATE = """\
You are a credit analyst at PFL Finance, India. Analyze bank statement data.
Policy FOIR cap: {foir_cap}%.
Banking heuristics:
- More than 3 bounces/NACH returns is a strong negative signal.
- Round deposits on the 1st or 15th may indicate cash infusion.
- Classify credits as: business/salary/transfer/refund/suspicious.

Respond ONLY with valid JSON matching this exact schema:
{{
  "abb_inr": <integer or null>,
  "bounce_count": <integer>,
  "nach_return_count": <integer>,
  "suspicious_flag": <boolean>,
  "notes": <string>
}}
"""

_USER_TEMPLATE = """\
Bank statement data:
Transaction lines (first 50):
{transaction_lines}

Closing balance history:
{closing_balances}
"""


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run banking check using Haiku."""
    policy = ctx.policy
    foir_cap = int(policy.get("hard_rules", {}).get("foir_cap_pct", 50))

    # Get bank statement extraction
    bank_data = (
        ctx.extractions.get("bank_statement")
        or ctx.extractions.get("bank_statements")
        or {}
    )
    transaction_lines_raw = bank_data.get("transaction_lines", bank_data.get("transactions", []))
    closing_balances = bank_data.get("closing_balances", bank_data.get("month_end_balances", []))

    # Take first 50 transactions
    if isinstance(transaction_lines_raw, list):
        tx_text = "\n".join(
            str(t) for t in transaction_lines_raw[:50]
        ) or "No transaction data available"
    else:
        tx_text = str(transaction_lines_raw)[:2000]

    cb_text = (
        json.dumps(closing_balances[:12]) if closing_balances else "No closing balance data"
    )

    system_prompt = _SYSTEM_TEMPLATE.format(foir_cap=foir_cap)
    user_message = _USER_TEMPLATE.format(
        transaction_lines=tx_text,
        closing_balances=cb_text,
    )

    try:
        message = await claude.invoke(
            tier=_TIER,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            cache_system=True,
            max_tokens=512,
        )
        response_text = claude.extract_text(message)
        output_data = _extract_json_from_text(response_text)
        # Ensure required fields
        output_data.setdefault("abb_inr", None)
        output_data.setdefault("bounce_count", 0)
        output_data.setdefault("nach_return_count", 0)
        output_data.setdefault("suspicious_flag", False)
        output_data.setdefault("notes", "")

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
        _log.exception("Step 2 banking check failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
