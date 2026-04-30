"""Step 4: KYC Verification — Haiku (text-only for M5, vision deferred).

Checks name variants and DOB consistency across ID documents.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 4
STEP_NAME = "kyc_verification"
_TIER = "haiku"
_MODEL_ID = MODELS[_TIER]

_SYSTEM = """\
You are a KYC officer at PFL Finance, India.
Check name variants and DOB consistency across ID documents.
Minor spelling variations (e.g., "Mohd" vs "Mohammad") are acceptable.
Respond ONLY with valid JSON matching this exact schema:
{
  "name_variants_allowed": <boolean>,
  "dob_consistent_across_ids": <boolean>,
  "id_count": <integer>,
  "mismatches": [{"id_type": <string>, "field": <string>, "detail": <string>}]
}
"""

_USER_TEMPLATE = """\
KYC extraction data:
{kyc_data}

AutoCAM name/DOB:
Name: {name}
DOB: {dob}
"""


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run KYC verification using Haiku."""
    autocam = (
        ctx.extractions.get("auto_cam")
        or ctx.extractions.get("autocam")
        or {}
    )
    name = autocam.get("applicant_name", autocam.get("name", "N/A"))
    dob = autocam.get("date_of_birth", autocam.get("dob", "N/A"))

    # Gather KYC extractions
    kyc_keys = [k for k in ctx.extractions if "kyc" in k.lower() or "aadhaar" in k.lower()
                or "pan" in k.lower() or "voter" in k.lower()]
    kyc_data = {k: ctx.extractions[k] for k in kyc_keys}

    user_message = _USER_TEMPLATE.format(
        kyc_data=str(kyc_data) if kyc_data else "No KYC extraction data available",
        name=name,
        dob=dob,
    )

    try:
        message = await claude.invoke(
            tier=_TIER,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            cache_system=True,
            max_tokens=512,
        )
        response_text = claude.extract_text(message)
        output_data = _extract_json_from_text(response_text)
        output_data.setdefault("name_variants_allowed", True)
        output_data.setdefault("dob_consistent_across_ids", True)
        output_data.setdefault("id_count", len(kyc_keys))
        output_data.setdefault("mismatches", [])

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
        _log.exception("Step 4 KYC verification failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
