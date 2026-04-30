"""AadhaarScanner — Claude-vision extractor for Aadhaar card images.

Reads a front or back Aadhaar scan (JPEG/PNG) and extracts structured fields —
name, Aadhaar number, DOB, gender, address, father/guardian name — using
Claude Haiku vision. Part of Level 1 (address verification) in the 4-level
pre-Phase-1 gate.
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


_SYSTEM_PROMPT = """You are an expert at reading Indian Aadhaar cards from scanned images.
Extract structured fields as JSON. If a field is not visible or unreadable,
return null for that field — do NOT invent values.

Indian Aadhaar cards print the guardian relationship in one of two forms on
the back-of-card address block:
  (a) "S/O <father>", "D/O <father>", or "W/O <husband>" preceding the address.
  (b) "C/O: <name>" (Care Of) at the start of the address block. "C/O: X" is
      semantically equivalent to "<cardholder> is dependent on X" — for adult
      cardholders this is almost always the father or husband.

Capture the care-of / guardian name verbatim, WITHOUT the "C/O:", "S/O ",
"D/O ", or "W/O " prefix — just the bare person name.

Respond with ONE JSON object, no prose, matching this schema:
{
  "name": "<full cardholder name exactly as printed>",
  "aadhaar_number": "<12-digit Aadhaar number, preserve grouping spaces>",
  "dob": "<DD/MM/YYYY as printed>",
  "gender": "<Male | Female | Other | null>",
  "address": "<full printed address block, back-of-card>",
  "care_of_name": "<the bare name after 'C/O:' on the address block, or null>",
  "father_name": "<the bare name after S/O or D/O, or null — leave null if the card uses C/O instead>",
  "husband_name": "<the bare name after W/O, or null>",
  "relation": "<SON_OF | DAUGHTER_OF | WIFE_OF | CARE_OF | null>"
}

Do not add any text before or after the JSON. Preserve exact spelling and
casing as printed on the card.
"""

_USER_INSTRUCTION = (
    "Read this Aadhaar card image and extract the fields per the schema above."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _detect_media_type(filename: str) -> str:
    """Map common image extensions to Claude-compatible media types."""
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
    """Treat empty strings / 'null' strings as Python None."""
    return {k: (v if v not in ("", "null", None) else None) for k, v in raw.items()}


class AadhaarScanner(BaseExtractor):
    """Claude-vision scanner for Aadhaar card images. Haiku tier."""

    extractor_name: str = "aadhaar_scanner"
    schema_version: str = "1.0"

    _TIER = "haiku"
    _REQUIRED_FIELDS: tuple[str, ...] = ("name", "aadhaar_number", "address")

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
                max_tokens=512,
            )
        except Exception as exc:  # noqa: BLE001 — wrap any vision failure
            _log.exception("aadhaar vision call failed")
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
            _log.warning("aadhaar JSON parse failed: %s", exc)
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

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        # Collapse the three guardian-name variants the model may have filled
        # (father_name, husband_name, care_of_name) into a single
        # ``father_name`` field so downstream rules have one place to look.
        # Priority: explicit S/O/D/O wins over C/O (which is inferred), which
        # wins over W/O (still a guardian but encoded differently on the card).
        guardian = (
            parsed.get("father_name")
            or parsed.get("care_of_name")
            or parsed.get("husband_name")
        )

        data: dict[str, Any] = {
            "name": parsed.get("name"),
            "aadhaar_number": parsed.get("aadhaar_number"),
            "dob": parsed.get("dob"),
            "gender": parsed.get("gender"),
            "address": parsed.get("address"),
            "father_name": guardian,
            "care_of_name": parsed.get("care_of_name"),
            "husband_name": parsed.get("husband_name"),
            "relation": parsed.get("relation"),
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
