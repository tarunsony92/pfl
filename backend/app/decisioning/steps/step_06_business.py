"""Step 6: Business Premises Evaluation — Sonnet.

Evaluates premises quality, ownership, and GPS distance between
house and business location.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 6
STEP_NAME = "business_premises"
_TIER = "sonnet"
_MODEL_ID = MODELS[_TIER]

_SYSTEM = """\
You are a business premises evaluator at PFL Finance, India.
Evaluate premises quality (kuccha=mud/temporary, pucca=concrete/permanent),
ownership status (house or business must be owned per policy),
and GPS distance between house and business (≤25km policy, >10km flag).
Respond ONLY with valid JSON matching this exact schema:
{
  "premises_type": "kuccha"|"pucca"|"thela"|"rehdi"|"unknown",
  "ownership_status": "house_owned"|"business_owned"|"both"|"neither",
  "gps_distance_km": <float or null>,
  "distance_flag": <boolean>,
  "passes": <boolean>
}
"""

_USER_TEMPLATE = """\
Business premises data from AutoCAM:
{autocam_business}

PD Sheet business information:
{pd_business}

GPS coordinates:
House GPS: {house_gps}
Business GPS: {business_gps}
"""


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run business premises evaluation using Sonnet."""
    autocam = (
        ctx.extractions.get("auto_cam")
        or ctx.extractions.get("autocam")
        or {}
    )
    pd_data = ctx.extractions.get("pd_sheet") or {}

    autocam_business = {
        k: v
        for k, v in autocam.items()
        if any(
            kw in k.lower()
            for kw in [
                "business", "premises", "ownership", "pucca", "kuccha",
                "shop", "establishment", "property",
            ]
        )
    }
    pd_business = {
        k: v
        for k, v in pd_data.items()
        if any(
            kw in k.lower()
            for kw in ["business", "premises", "shop", "location", "ownership"]
        )
    }

    house_gps = autocam.get("house_gps") or autocam.get("residential_gps", "N/A")
    business_gps = autocam.get("business_gps") or autocam.get("shop_gps", "N/A")

    _no_autocam = "No business data in AutoCAM"
    _no_pd = "No business data in PD Sheet"
    user_message = _USER_TEMPLATE.format(
        autocam_business=str(autocam_business) if autocam_business else _no_autocam,
        pd_business=str(pd_business) if pd_business else _no_pd,
        house_gps=house_gps,
        business_gps=business_gps,
    )

    try:
        message = await claude.invoke(
            tier=_TIER,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            cache_system=False,
            max_tokens=512,
        )
        response_text = claude.extract_text(message)
        output_data = _extract_json_from_text(response_text)
        output_data.setdefault("premises_type", "unknown")
        output_data.setdefault("ownership_status", "neither")
        output_data.setdefault("gps_distance_km", None)
        output_data.setdefault("distance_flag", False)
        output_data.setdefault("passes", False)

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
        _log.exception("Step 6 business premises failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
