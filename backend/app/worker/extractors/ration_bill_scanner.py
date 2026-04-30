"""RationBillScanner — Claude-vision extractor for ration / electricity / utility bills.

Accepts image (JPEG/PNG) or PDF input. For PDFs, the bytes are sent directly to
Claude as a ``document`` content block (native PDF support in Anthropic vision,
no rasterisation needed). Extracts owner name, co-owners, address, and document
number/type. Part of Level 1 — the owner-name cross-check rule runs on this.
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


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


_SYSTEM_PROMPT = """You are reading a scanned Indian address-proof document — typically:
  • a ration card (issued by the state food & supplies department), OR
  • an electricity bill (DHBVN, UHBVN, BSES, MSEB, TATA POWER, etc.), OR
  • a water / gas / other utility bill.

Your job is to READ the document, not to interpret or infer. Thermal-paper
fading, crumpled folds, torn corners, and photographed-at-an-angle images are
all common. If a field is not clearly legible, return null for it. Do NOT
substitute a plausible-looking Indian name for unclear text — a null is always
safer than a fabrication.

On Indian electricity bills the owner line is typically printed under a
"NAME & ADDRESS:" or "CONSUMER NAME:" label and very often includes a
father / husband relationship printed as "S/O SH. <FATHER NAME>" or
"W/O <HUSBAND NAME>". Capture the relation verbatim — it is a critical
signal for downstream address verification.

Respond with ONE JSON object. No prose, no markdown fences.

Schema:
{
  "name": "<exact printed owner name, WITHOUT any S/O or W/O prefix — just the owner's own name>",
  "father_or_husband_name": "<full name after S/O or W/O, or null>",
  "relation": "<SON_OF | DAUGHTER_OF | WIFE_OF | HUSBAND_OF | null>",
  "co_owners": ["<other names printed in the same NAME block, or []>"],
  "address": "<full printed address block; do not include phone, email, meter ID, or bill ID>",
  "document_number": "<consumer number / K-number / account number / ration card number>",
  "document_type": "<ration_card | electricity_bill | water_bill | gas_bill | utility_bill | other>"
}

Hard rules:
- Do NOT invent a name that isn't clearly printed. Null is safer.
- Preserve exact spelling even if unusual (e.g. "CHOUDHAR Y" → still return it verbatim).
- Return the address as a single string trimmed of the other fields around it.
- If the document is a ration card, the relation field is typically absent
  (the ration card just lists a household head); leave father_or_husband_name
  and relation as null in that case.
"""

_USER_INSTRUCTION = (
    "Read this document and extract the fields per the schema above. "
    "If you cannot clearly read a field, return null — never guess a name."
)


def _detect_media_type(filename: str) -> tuple[str, str]:
    """Return ``(content_block_type, media_type)`` for the given filename.

    - PDFs → ``("document", "application/pdf")``
    - PNG → ``("image", "image/png")``
    - JPG/JPEG/other → ``("image", "image/jpeg")``
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        return "document", "application/pdf"
    if ext == "png":
        return "image", "image/png"
    if ext == "gif":
        return "image", "image/gif"
    if ext == "webp":
        return "image", "image/webp"
    return "image", "image/jpeg"


def _extract_json_from_text(text: str) -> dict[str, Any]:
    match = _JSON_RE.search(text)
    if not match:
        raise ValueError(f"no JSON object found in response: {text[:200]!r}")
    return json.loads(match.group(0))


def _null_empties(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if v in ("", "null", None):
            out[k] = None
        else:
            out[k] = v
    return out


class RationBillScanner(BaseExtractor):
    """Claude-vision scanner for ration / electricity bills. Sonnet tier, JPEG or PDF.

    Uses Sonnet rather than Haiku because rural thermal-paper bills are commonly
    crumpled, faded, or photographed at an angle, and a hallucinated name
    (Haiku will substitute a plausible Indian name like "HARJEET KAUR" when it
    can't read the text) makes the address sub-step emit a false CRITICAL issue.
    The cost delta (~$0.01 per call) is worth the correctness.
    """

    extractor_name: str = "ration_bill_scanner"
    schema_version: str = "1.1"

    _TIER = "sonnet"
    _REQUIRED_FIELDS: tuple[str, ...] = ("name", "address")

    def __init__(self, claude: Any = None) -> None:
        self._claude = claude

    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult:
        claude = self._claude
        if claude is None:
            from app.services.claude import get_claude_service

            claude = get_claude_service()

        b64 = base64.standard_b64encode(body_bytes).decode("ascii")
        block_type, media_type = _detect_media_type(filename)

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": block_type,
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
                max_tokens=768,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("ration bill vision call failed")
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
            _log.warning("ration bill JSON parse failed: %s", exc)
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=self.schema_version,
                data={"raw_text": raw_text[:500]},
                error_message=f"json_parse_failed: {exc}",
            )

        parsed = _null_empties(parsed_raw)
        co_owners = parsed.get("co_owners") or []
        if not isinstance(co_owners, list):
            co_owners = [co_owners] if co_owners else []

        warnings: list[str] = [
            f"missing required field: {field}"
            for field in self._REQUIRED_FIELDS
            if not parsed.get(field)
        ]

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        father_or_husband = parsed.get("father_or_husband_name")
        data: dict[str, Any] = {
            "name": parsed.get("name"),
            # Alias ``father_name`` so the L1 mapper (which keys on that name
            # for all document types) picks it up without special-casing.
            "father_name": father_or_husband,
            "father_or_husband_name": father_or_husband,
            "relation": parsed.get("relation"),
            "co_owners": co_owners,
            "address": parsed.get("address"),
            "document_number": parsed.get("document_number"),
            "document_type": parsed.get("document_type"),
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
