"""L3 Claude-Sonnet vision scorers for house + business-premises photos.

Each scorer bundles multiple JPEG/PNG images into a single Sonnet vision call
with a structured scoring prompt, and returns an ExtractionResult whose data
field carries the JSON rating the Level 3 engine turns into CRITICAL / WARNING
issues.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from app.enums import ExtractionStatus
from app.worker.extractors.base import ExtractionResult

_log = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _detect_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    return "image/jpeg"


def _extract_json(text: str) -> dict[str, Any]:
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"no JSON in response: {text[:200]!r}")
    return json.loads(m.group(0))


def _build_image_blocks(images: list[tuple[str, bytes]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for fname, body in images:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _detect_media_type(fname),
                    "data": base64.standard_b64encode(body).decode("ascii"),
                },
            }
        )
    return blocks


# ───────────────────────────── HousePremisesScorer ───────────────────────────


_HOUSE_SYSTEM = """You are a PFL Finance field-visit auditor rating a rural microfinance
borrower's home from photos.

Score the home on an Anglo-Indian rural scale — {worst, bad, ok, good, excellent}.
The borrower's loan depends on the home being at least ``ok``.

Return ONLY valid JSON matching exactly this schema:

{
  "overall_rating": "<worst|bad|ok|good|excellent>",
  "space_rating": "<same scale>",
  "furnishing_rating": "<same scale>",
  "upkeep_rating": "<same scale — paint / cleanliness>",
  "high_value_assets_visible": ["<each asset as printed, e.g. 'LED TV', 'refrigerator', 'washing machine', 'computer'>"],
  "construction_type": "<pakka | kachha | mixed | unknown>",
  "flooring": "<tiled | cemented | mud | marble | unknown>",
  "kitchen_condition": "<same scale — or 'not_visible'>",
  "concerns": ["<short evidence-cited concern>"],
  "positives": ["<short evidence-cited positive>"]
}

Rules:
- Give the overall rating as the bottleneck of the three component ratings
  (space, furnishing, upkeep). A dirt floor + thatched roof = pakka is NOT
  pakka — call it ``kachha``.
- Do not invent assets you can't clearly see.
- Respond with the JSON only.
"""


_HOUSE_USER_INSTRUCTION = (
    "Rate this home based on the attached photos per the schema above."
)


class HousePremisesScorer:
    """Scores house-visit photos on living conditions.

    Uses Opus rather than Sonnet because L3 vision is a credit-critical
    PASS/FAIL — mis-rating a kachha house as ``ok`` directly drives wrong
    ticket sizing. Pairs with BusinessPremisesScorer which is also on Opus,
    so the entire L3 visual layer is on the strongest model."""

    _TIER = "opus"
    _EMPTY_DATA = {
        "overall_rating": None,
        "space_rating": None,
        "furnishing_rating": None,
        "upkeep_rating": None,
        "high_value_assets_visible": [],
        "construction_type": None,
        "flooring": None,
        "kitchen_condition": None,
        "concerns": [],
        "positives": [],
    }

    def __init__(self, claude: Any = None) -> None:
        self._claude = claude

    async def score(self, images: list[tuple[str, bytes]]) -> ExtractionResult:
        if not images:
            return ExtractionResult(
                status=ExtractionStatus.PARTIAL,
                schema_version="1.0",
                data=dict(self._EMPTY_DATA),
                warnings=[
                    "no house visit photos uploaded — L3 cannot score living conditions"
                ],
            )

        claude = self._claude
        if claude is None:
            from app.services.claude import get_claude_service

            claude = get_claude_service()

        content = _build_image_blocks(images) + [
            {"type": "text", "text": _HOUSE_USER_INSTRUCTION}
        ]
        messages = [{"role": "user", "content": content}]

        try:
            message = await claude.invoke(
                tier=self._TIER,
                system=_HOUSE_SYSTEM,
                messages=messages,
                cache_system=True,
                max_tokens=1024,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("house scorer vision call failed")
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={},
                error_message=f"vision_call_failed: {exc}",
            )

        raw_text = claude.extract_text(message)
        try:
            parsed = _extract_json(raw_text)
        except (ValueError, json.JSONDecodeError) as exc:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="1.0",
                data={"raw_text": raw_text[:500]},
                error_message=f"json_parse_failed: {exc}",
            )

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        data = {**self._EMPTY_DATA, **parsed, "model_used": model, "cost_usd": cost, "usage": usage}
        return ExtractionResult(
            status=ExtractionStatus.SUCCESS,
            schema_version="1.0",
            data=data,
        )


# ──────────────────────────── BusinessPremisesScorer ─────────────────────────


_BUSINESS_SYSTEM = """You are a PFL Finance field-visit auditor assessing whether a rural
microfinance borrower's business premises can support the proposed loan.

Step 1 — CLASSIFY THE BUSINESS FIRST before estimating any collateral value:
  - product_trading   — kirana / grocery / general store / wholesale / retail
                         shop where the inventory on the shelves IS the
                         primary collateral.
  - service           — barbershop / salon / tailor / repair shop / laundry
                         / beauty parlour / mobile-recharge shop. These
                         businesses have minimal "stock" — their income
                         comes from SERVICES, not selling physical goods.
                         DO NOT inflate consumables (shampoo bottles,
                         scissors, hair clippers) into a large stock value.
  - cattle_dairy      — dairy / cattle rearing / livestock operation.
  - manufacturing     — tailoring unit, carpentry, small fabrication.
  - mixed             — a genuine combination (e.g. a shop that also runs
                         a small dairy behind it).
  - other / unknown   — can't tell from photos.

Step 2 — VALUE THE VISIBLE COLLATERAL:
  - For ``product_trading``: estimate stock_value_estimate_inr from the
    SHELVED inventory (photos of racks of goods). Be conservative.
  - For ``service``: stock_value_estimate_inr should be the SMALL consumable
    inventory only (likely < ₹20,000 for a village barbershop). Do NOT
    inflate. ALSO fill visible_equipment_value_inr with the fixed equipment
    visible (chairs, mirrors, sinks, washing basin, clippers, tools) —
    this is what a service business actually uses as its productive asset.
  - For ``cattle_dairy``: stock_value_estimate_inr is approximately
    ``cattle_count × ₹60,000`` per Indian crossbreed cow in 2026. Fill
    cattle_count + cattle_health.
  - For any type: flag in concerns[] if the visible collateral clearly
    cannot support the loan amount given below.

Step 3 — RECOMMEND:
  - ``recommended_loan_amount_inr`` — a realistic ticket in INR based on
    what is genuinely collateralisable in the photos (stock for trading,
    fixed equipment for service, cattle for dairy). If the proposed
    loan amount is defensible, echo it back; if not, return a LOWER
    figure that you would approve. Null ONLY if you cannot tell.

Step 4 — ITEMISE THE VISIBLE COLLATERAL:
  - List EACH visible inventory line / fixed-equipment item separately in
    `items[]`. Group identical items into one row with qty (e.g. don't
    list "chair" three times — return {description:"barber chair", qty:3}).
  - For each item, include your best 2026 Indian retail MRP estimate
    (`mrp_estimate_inr`) and your confidence (`mrp_confidence`).
    For service consumables (shampoo, hair dye, scissors), use
    PER-UNIT MRP — line total will be qty × MRP.
  - The aggregate `stock_value_estimate_inr` should equal the sum of
    line totals where category ∈ {stock, consumable}; the aggregate
    `visible_equipment_value_inr` should equal the sum of line totals
    where category = equipment.
  - If you cannot price an item at all, return mrp_estimate_inr=null
    with mrp_confidence="low" so the assessor sees the gap rather
    than a fabricated number.
  - For each item, provide `source_image` (1-indexed into the photos
    you received, in the order I sent them) — pick the photo where
    the item is MOST visible. Multi-photo items: pick the clearest one.
  - For each item, provide `bbox` as [x0, y0, x1, y1] in normalised
    0.0-1.0 coordinates (origin top-left) on that source_image. The
    bbox should tightly enclose the visible item. If you cannot
    localise the item precisely (e.g. it's spread across the photo
    or you only saw it in passing), return bbox=null. The downstream
    image-cropper will skip null-bbox items rather than render
    a useless empty crop.

Return ONLY valid JSON matching this exact schema:

{
  "business_type": "<product_trading | service | cattle_dairy | manufacturing | mixed | other | unknown>",
  "business_type_confidence": <0.0 – 1.0>,
  "business_subtype": "<short free-text label, e.g. 'barbershop', 'kirana store', 'buffalo dairy (crossbreed)'>",
  "stock_value_estimate_inr": <integer or null>,
  "visible_equipment_value_inr": <integer or null>,
  "stock_condition": "<fresh | good | ok | stale | unknown | not_applicable>",
  "stock_variety": "<wide | ok | narrow | unknown | not_applicable>",
  "cattle_count": <integer or null>,
  "cattle_health": "<healthy | ok | unhealthy | unknown | not_applicable>",
  "infrastructure_rating": "<excellent | good | ok | bad | worst>",
  "infrastructure_details": ["<each detail as printed>"],
  "recommended_loan_amount_inr": <integer or null>,
  "recommended_loan_rationale": "<one sentence — why this amount, what you saw>",
  "concerns": ["<evidence-cited concern>"],
  "positives": ["<evidence-cited positive>"],
  "items": [
    {
      "description": "<short item label, lowercase, e.g. 'barber chair (hydraulic)' or 'shampoo bottle (assorted)'>",
      "qty": "<integer — your best count of identical units, no nulls>",
      "category": "<equipment | stock | consumable | other>",
      "mrp_estimate_inr": "<integer per-unit MRP in 2026 Indian retail prices, OR null if you have no idea>",
      "mrp_confidence": "<high | medium | low>",
      "rationale": "<≤80 chars — why you priced it this way, what you saw>",
      "source_image": "<1-indexed integer — which photo from the bundle this item is most visible in>",
      "bbox": [<x0>, <y0>, <x1>, <y1>]
    }
  ]
}

Hard rules:
- A service business MUST have ``cattle_count = 0`` and ``cattle_health =
  "not_applicable"``.  A product_trading business that isn't dairy MUST
  also have cattle fields as not_applicable.  Only a cattle_dairy or
  mixed business should carry real cattle numbers.
- Do NOT claim "stock is adequate" for a service business just because
  you see some consumables on a shelf. Service businesses require a
  FIXED-EQUIPMENT assessment, not a stock assessment.
- Respond with JSON only — no prose, no markdown.
"""


class BusinessPremisesScorer:
    """Scores business-premises photos for stock value + infra.

    Uses Opus rather than Sonnet because:
      - Business-type classification is non-obvious in rural Indian
        photos — a barbershop photographed with some product bottles
        on a shelf is easy for Sonnet to mis-classify as "product
        trading with adequate stock", leading to a false PASS.
      - The loan-reduction recommendation is a credit-critical call
        that warrants the stronger model's judgement.
    Cost is ~3× Sonnet; worth it on a single-call-per-case basis.
    """

    _TIER = "opus"
    _EMPTY_DATA = {
        "business_type": None,
        "business_type_confidence": None,
        "business_subtype": None,
        "stock_value_estimate_inr": None,
        "visible_equipment_value_inr": None,
        "stock_condition": None,
        "stock_variety": None,
        "cattle_count": None,
        "cattle_health": None,
        "infrastructure_rating": None,
        "infrastructure_details": [],
        "recommended_loan_amount_inr": None,
        "recommended_loan_rationale": None,
        "concerns": [],
        "positives": [],
        "items": [],
    }

    def __init__(self, claude: Any = None) -> None:
        self._claude = claude

    async def score(
        self,
        images: list[tuple[str, bytes]],
        loan_amount_inr: int | None = None,
    ) -> ExtractionResult:
        if not images:
            return ExtractionResult(
                status=ExtractionStatus.PARTIAL,
                schema_version="2.0",
                data=dict(self._EMPTY_DATA),
                warnings=[
                    "no business premises photos uploaded — L3 cannot assess stock"
                ],
            )

        claude = self._claude
        if claude is None:
            from app.services.claude import get_claude_service

            claude = get_claude_service()

        anchor = (
            f"Proposed loan amount: ₹{loan_amount_inr:,}. "
            if loan_amount_inr
            else "Proposed loan amount: unknown. "
        )
        instruction = anchor + (
            "Assess the attached business-premises photos per the schema above."
        )

        content = _build_image_blocks(images) + [
            {"type": "text", "text": instruction}
        ]
        messages = [{"role": "user", "content": content}]

        try:
            message = await claude.invoke(
                tier=self._TIER,
                system=_BUSINESS_SYSTEM,
                messages=messages,
                cache_system=True,
                max_tokens=4096,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("business scorer vision call failed")
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="2.0",
                data={},
                error_message=f"vision_call_failed: {exc}",
            )

        raw_text = claude.extract_text(message)
        try:
            parsed = _extract_json(raw_text)
        except (ValueError, json.JSONDecodeError) as exc:
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                schema_version="2.0",
                data={"raw_text": raw_text[:500]},
                error_message=f"json_parse_failed: {exc}",
            )

        from app.services.claude import MODELS

        model = MODELS.get(self._TIER, self._TIER)
        usage = claude.usage_dict(message)
        cost = claude.cost_usd(model, usage)

        data = {**self._EMPTY_DATA, **parsed, "model_used": model, "cost_usd": cost, "usage": usage}
        return ExtractionResult(
            status=ExtractionStatus.SUCCESS,
            schema_version="2.0",
            data=data,
        )
