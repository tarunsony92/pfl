"""PanScanner — Claude-vision extractor for PAN card images.

Reads a PAN card scan (JPEG/PNG) and extracts: full name, father/guardian name,
DOB, 10-char alphanumeric PAN number (pattern ``[A-Z]{5}[0-9]{4}[A-Z]``) using
Claude Haiku vision. Part of Level 1 in the 4-level pre-Phase-1 gate.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from app.enums import ExtractionStatus
from app.worker.extractors.base import BaseExtractor, ExtractionResult

_log = logging.getLogger(__name__)


_PAN_NUMBER_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


_SYSTEM_PROMPT = """You are an expert at reading Indian PAN (Permanent Account Number) cards from scanned images.
Extract the following fields as JSON. If a field is not visible, return null.

Respond ONLY with valid JSON matching exactly this schema:
{
  "name": "<cardholder full name as printed>",
  "father_name": "<father/guardian name as printed, or null if absent>",
  "dob": "<date of birth, format DD/MM/YYYY as printed>",
  "pan_number": "<10-char alphanumeric PAN, e.g. ABCDE1234F>"
}

Do not add any text before or after the JSON. Preserve exact spelling and
casing. The PAN number must be uppercase letters and digits only.
"""

_USER_INSTRUCTION = (
    "Read this PAN card image and extract the fields per the schema above."
)


def _detect_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "png":
        return "image/png"
    if ext == "gif":
        return "image/gif"
    if ext == "webp":
        return "image/webp"
    return "image/jpeg"


def _extract_json_from_text(text: str) -> dict[str, Any]:
    match = _JSON_RE.search(text)
    if not match:
        raise ValueError(f"no JSON object found in response: {text[:200]!r}")
    return json.loads(match.group(0))


def _null_empties(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if v not in ("", "null", None) else None) for k, v in raw.items()}


class PanScanner(BaseExtractor):
    """Claude-vision scanner for PAN card images. Haiku tier."""

    extractor_name: str = "pan_scanner"
    schema_version: str = "1.0"

    _TIER = "haiku"
    _REQUIRED_FIELDS: tuple[str, ...] = ("name", "pan_number")

    def __init__(self, claude: Any = None) -> None:
        self._claude = claude

    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult:
        claude = self._claude
        if claude is None:
            from app.services.claude import get_claude_service

            claude = get_claude_service()

        b64 = base64.standard_b64encode(body_bytes).decode("ascii")
        media_type = _detect_media_type(filename)

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _USER_INSTRUCTION},
                ],
            }
        ]

        try:
            message = await claude.invoke(
                tier=self._TIER,
                system=_SYSTEM_PROMPT,
                messages=messages,
                cache_system=True,
                max_tokens=256,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("pan vision call failed")
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=self.schema_version,
                data={},
                error_message=f"vision_call_failed: {exc}",
            )

        raw_text = claude.extract_text(message)

        try:
            parsed_raw = _extract_json_from_text(raw_text)
        except (ValueError, json.JSONDecodeError) as exc:
            _log.warning("pan JSON parse failed: %s", exc)
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=self.schema_version,
                data={"raw_text": raw_text[:500]},
                error_message=f"json_parse_failed: {exc}",
            )

        parsed = _null_empties(parsed_raw)

        warnings: list[str] = [
            f"missing required field: {field}"
            for field in self._REQUIRED_FIELDS
            if not parsed.get(field)
        ]

        pan_number = parsed.get("pan_number")
        if pan_number and not _PAN_NUMBER_RE.match(str(pan_number).strip().upper()):
            warnings.append(
                f"pan_number_format_invalid: {pan_number!r} does not match [A-Z]{{5}}[0-9]{{4}}[A-Z]"
            )

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        data: dict[str, Any] = {
            "name": parsed.get("name"),
            "father_name": parsed.get("father_name"),
            "dob": parsed.get("dob"),
            "pan_number": pan_number,
            "model_used": model,
            "cost_usd": cost,
            "usage": usage,
        }

        status = ExtractionStatus.SUCCESS if not warnings else ExtractionStatus.PARTIAL

        return ExtractionResult(
            status=status,
            schema_version=self.schema_version,
            data=data,
            warnings=warnings,
        )
