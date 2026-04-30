"""LoanAgreementScanner — Claude-vision extractor for the signed loan-agreement PDF.

Typical rural-microfinance LAGR packet is a 30-50 page scanned PDF combining
LAGR + LAPP + DPN. It has no text layer (every page is two images), so we send
it to Claude Haiku as a ``document`` content block (native PDF support, no
rasterisation). Claude returns a structured JSON with the asset annexure /
hypothecation-schedule so Level 4 can diff it against the SystemCam asset
list and raise CRITICAL issues for missing assets the assessor must add
before disbursal.
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


_SYSTEM_PROMPT = """You are an expert at reading Indian micro-loan agreement PDFs.

A typical rural-microfinance loan-agreement kit (LAGR) combines several
documents: the LAGR body, LAPP (application), DPN (demand promissory note),
sometimes a guarantor form and a hypothecation schedule. Extract the
counterparties who signed, plus the hypothecation / asset annexure.

A "guarantor" is anyone listed under the label **Guarantor**, **Surety**,
**जमानती**, or **ज़ामिन** (Hindi) on either the LAGR/LAPP cover page or on
a separate guarantor form bound into the same PDF. A guarantor is NOT the
same as a co-applicant / co-borrower — treat them as distinct lists. A
witness is also distinct from both.

Return ONLY valid JSON matching this schema:

{
  "loan_id": "<loan ID printed on the agreement, or null>",
  "borrower_name": "<primary borrower name as printed, or null>",
  "co_applicants": ["<name>", ...],
  "guarantors": ["<name>", ...],
  "witnesses": ["<name>", ...],
  "annexure_present": <bool — whether a distinct 'Schedule' / 'Annexure' /
                       'Hypothecation List' section exists>,
  "annexure_page_hint": <integer page number where the annexure starts, or null>,
  "hypothecation_clause_present": <bool — whether the agreement body contains
                                   a hypothecation / secured-asset clause>,
  "assets": [
    {
      "description": "<asset description as printed (e.g. 'Refrigerator Samsung 192L', 'Cattle - 2 buffalo')>",
      "value_inr": <declared value in INR (integer), or null>,
      "identifier": "<serial / tag / ID printed on the asset row, or null>"
    }
  ]
}

Rules:
- Each name list is an array of strings — the bare printed names, NO prefix
  like "S/O", "W/O", "Mr.", etc.  If a label has no names under it (e.g. no
  guarantor was named) use an empty list ``[]``.
- If there is no annexure, set ``annexure_present = false`` and ``assets = []``.
- Preserve the asset description exactly as printed (including any
  quantity / model info).
- ``value_inr`` must be an integer — strip rupee symbols and commas.
- Do NOT invent names or assets. If the scan is illegible for a row, skip it.
- Respond with the JSON only — no leading or trailing text.
"""

_USER_INSTRUCTION = (
    "Extract the hypothecation / asset annexure from this loan agreement "
    "per the schema above."
)


def _extract_json_from_text(text: str) -> dict[str, Any]:
    match = _JSON_RE.search(text)
    if not match:
        raise ValueError(f"no JSON object found in response: {text[:200]!r}")
    return json.loads(match.group(0))


class LoanAgreementScanner(BaseExtractor):
    """PDF-only Claude-vision scanner for signed loan agreements."""

    extractor_name: str = "loan_agreement_scanner"
    schema_version: str = "1.0"

    _TIER = "haiku"

    def __init__(self, claude: Any = None) -> None:
        self._claude = claude

    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext != "pdf":
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=self.schema_version,
                data={},
                error_message=(
                    f"loan agreement must be a PDF, got {filename!r}. "
                    "Re-upload as .pdf."
                ),
            )

        claude = self._claude
        if claude is None:
            from app.services.claude import get_claude_service

            claude = get_claude_service()

        b64 = base64.standard_b64encode(body_bytes).decode("ascii")
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
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
                max_tokens=4096,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("loan agreement vision call failed")
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=self.schema_version,
                data={},
                error_message=f"vision_call_failed: {exc}",
            )

        raw_text = claude.extract_text(message)

        try:
            parsed = _extract_json_from_text(raw_text)
        except (ValueError, json.JSONDecodeError) as exc:
            _log.warning("loan agreement JSON parse failed: %s", exc)
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version=self.schema_version,
                data={"raw_text": raw_text[:500]},
                error_message=f"json_parse_failed: {exc}",
            )

        annexure_present = bool(parsed.get("annexure_present"))
        hyp_clause = bool(parsed.get("hypothecation_clause_present"))
        assets = parsed.get("assets") or []
        if not isinstance(assets, list):
            assets = []

        def _as_str_list(v: Any) -> list[str]:
            if not isinstance(v, list):
                return []
            return [str(x).strip() for x in v if isinstance(x, (str, int)) and str(x).strip()]

        co_applicants = _as_str_list(parsed.get("co_applicants"))
        guarantors = _as_str_list(parsed.get("guarantors"))
        witnesses = _as_str_list(parsed.get("witnesses"))

        warnings: list[str] = []
        if not annexure_present:
            warnings.append(
                "loan_agreement_missing_annexure: no distinct schedule/annexure "
                "section found — recovery enforceability at risk."
            )
        if not hyp_clause:
            warnings.append(
                "loan_agreement_missing_hypothecation_clause: no hypothecation "
                "clause detected in agreement body."
            )

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        data: dict[str, Any] = {
            "loan_id": parsed.get("loan_id"),
            "borrower_name": parsed.get("borrower_name"),
            "co_applicants": co_applicants,
            "guarantors": guarantors,
            "witnesses": witnesses,
            "annexure_present": annexure_present,
            "annexure_page_hint": parsed.get("annexure_page_hint"),
            "hypothecation_clause_present": hyp_clause,
            "assets": assets,
            "asset_count": len(assets),
            "model_used": model,
            "cost_usd": cost,
            "usage": usage,
        }

        status = (
            ExtractionStatus.SUCCESS
            if annexure_present and hyp_clause
            else ExtractionStatus.PARTIAL
        )

        return ExtractionResult(
            status=status,
            schema_version=self.schema_version,
            data=data,
            warnings=warnings,
        )
