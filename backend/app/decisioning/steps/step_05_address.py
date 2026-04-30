"""Step 5: Address Verification — Sonnet.

Normalizes addresses from 6 sources and checks the 4-of-6 match rule.
"""

from __future__ import annotations

import logging
from typing import Any

from app.decisioning.steps._llm_helpers import _extract_json_from_text, build_usage
from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus
from app.services.claude import MODELS

_log = logging.getLogger(__name__)

STEP_NUMBER = 5
STEP_NAME = "address_verification"
_TIER = "sonnet"
_MODEL_ID = MODELS[_TIER]

_SYSTEM = """\
You are an address verification specialist at PFL Finance, India.
Normalize each address to village + pincode (primary keys in rural India).
Apply the 4-of-6 match rule: at least 4 of 6 sources must match.
Consider minor spelling variations and abbreviations as matching.
Respond ONLY with valid JSON matching this exact schema:
{
  "addresses_by_source": {<source>: <normalized_address_string>},
  "match_count": <integer>,
  "match_ratio": <float between 0 and 1>,
  "passes_rule": <boolean>,
  "mismatches": [{"source1": <string>, "source2": <string>, "detail": <string>}]
}
"""

_USER_TEMPLATE = """\
Address data from 6 sources:
Aadhaar: {aadhaar}
PAN: {pan}
CIBIL/Equifax: {cibil}
Electricity Bill: {electricity}
Bank Statement: {bank}
GPS House Visit: {gps}
"""

_SOURCES = ["aadhaar", "pan", "cibil", "electricity", "bank", "gps"]


def _get_address(extractions: dict[str, dict[str, Any]], *keys: str) -> str:
    """Try multiple extraction keys to find an address."""
    for key in keys:
        data = extractions.get(key, {})
        if data:
            addr = (
                data.get("address")
                or data.get("permanent_address")
                or data.get("residential_address")
                or data.get("registered_address")
                or data.get("address_line1")
            )
            if addr:
                return str(addr)
    return "N/A"


async def run(ctx: StepContext, claude: Any) -> StepOutput:
    """Run address verification using Sonnet."""
    extractions = ctx.extractions
    autocam = extractions.get("auto_cam") or extractions.get("autocam") or {}

    aadhaar_addr = _get_address(extractions, "kyc_aadhaar", "aadhaar") or autocam.get(
        "aadhaar_address", "N/A"
    )
    pan_addr = _get_address(extractions, "kyc_pan", "pan") or autocam.get("pan_address", "N/A")
    cibil_addr = _get_address(extractions, "cibil", "equifax") or autocam.get(
        "cibil_address", "N/A"
    )
    electricity_addr = _get_address(extractions, "electricity_bill", "electricity") or autocam.get(
        "electricity_address", "N/A"
    )
    bank_addr = _get_address(extractions, "bank_statement", "bank") or autocam.get(
        "bank_address", "N/A"
    )
    gps_addr = (
        str(autocam.get("gps_address") or autocam.get("house_visit_address") or "N/A")
    )

    user_message = _USER_TEMPLATE.format(
        aadhaar=aadhaar_addr,
        pan=pan_addr,
        cibil=cibil_addr,
        electricity=electricity_addr,
        bank=bank_addr,
        gps=gps_addr,
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
        output_data.setdefault("addresses_by_source", {})
        output_data.setdefault("match_count", 0)
        output_data.setdefault("match_ratio", 0.0)
        output_data.setdefault("passes_rule", False)
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
        _log.exception("Step 5 address verification failed: %s", exc)
        return StepOutput(
            status=StepStatus.FAILED,
            step_name=STEP_NAME,
            step_number=STEP_NUMBER,
            model_used=_MODEL_ID,
            output_data={},
            citations=[],
            error_message=str(exc),
        )
