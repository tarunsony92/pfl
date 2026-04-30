"""Step 9: PD Sheet Analysis — Sonnet.

Extracts interview narrative, checks consistency with CAM + source docs,
and flags evasive/coached/contradictory answers.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 9
STEP_NAME = "pd_sheet_analysis"
_TIER = "sonnet"
_MODEL_ID = MODELS[_TIER]

_SYSTEM = """\
You are a personal discussion (PD) analyst at PFL Finance, India.
Analyze the PD Sheet interview data for:
1. Narrative consistency with CAM and source documents
2. Red flags: evasive answers, coached responses, contradictions
3. Overall consistency assessment

Coaching indicators: overly precise financial figures, identical wording to CAM,
inability to recall basic business details.

Respond ONLY with valid JSON matching this exact schema:
{
  "narrative_summary": <string>,
  "consistency_with_cam": "consistent"|"partial"|"contradictory",
  "red_flags": [{"category": <string>, "detail": <string>}],
  "coaching_detected": <boolean>
}
"""

_USER_TEMPLATE = """\
PD Sheet extraction:
Fields: {pd_fields}
Paragraphs/Narrative: {pd_narrative}
Table data: {pd_table}

AutoCAM comparison data:
{autocam_data}
"""


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run PD Sheet analysis using Sonnet."""
    pd_data = ctx.extractions.get("pd_sheet") or {}
    autocam = (
        ctx.extractions.get("auto_cam")
        or ctx.extractions.get("autocam")
        or {}
    )

    # Extract structured PD sheet components
    pd_fields = {k: v for k, v in pd_data.items() if not isinstance(v, list | dict)}
    pd_narrative = pd_data.get("narrative") or pd_data.get("text") or pd_data.get("remarks") or ""
    pd_table = pd_data.get("table") or pd_data.get("table_data") or []

    autocam_summary = {
        k: v
        for k, v in autocam.items()
        if any(
            kw in k.lower()
            for kw in [
                "income", "business", "sales", "name", "age", "family",
                "loan", "employment", "occupation",
            ]
        )
    }

    user_message = _USER_TEMPLATE.format(
        pd_fields=str(pd_fields) if pd_fields else "No structured fields",
        pd_narrative=str(pd_narrative)[:1500] if pd_narrative else "No narrative",
        pd_table=str(pd_table)[:500] if pd_table else "No table data",
        autocam_data=str(autocam_summary) if autocam_summary else "No AutoCAM data",
    )

    try:
        message = await claude.invoke(
            tier=_TIER,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            cache_system=False,
            max_tokens=1024,
        )
        response_text = claude.extract_text(message)
        output_data = _extract_json_from_text(response_text)
        output_data.setdefault("narrative_summary", "")
        output_data.setdefault("consistency_with_cam", "partial")
        output_data.setdefault("red_flags", [])
        output_data.setdefault("coaching_detected", False)

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
        _log.exception("Step 9 PD sheet analysis failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
