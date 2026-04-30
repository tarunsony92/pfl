"""Step 7: Stock Quantification — Stub for M5 (no LLM, vision deferred).

Reads declared stock from PD Sheet, parses item names via regex,
looks each up in the MRP database, and reports total estimated stock value.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.decisioning.steps.base import StepContext, StepOutput
from app.enums import StepStatus

_log = logging.getLogger(__name__)

STEP_NUMBER = 7
STEP_NAME = "stock_quantification"

# Common Indian retail items to match against text
_ITEM_PATTERNS: list[tuple[str, int]] = [
    # (pattern, approximate_unit_price_inr)
    (r"toor\s*dal", 110),
    (r"moong\s*dal", 95),
    (r"chana\s*dal", 85),
    (r"urad\s*dal", 120),
    (r"basmati\s*rice", 80),
    (r"wheat\s*flour|atta", 200),
    (r"sunflower\s*oil", 130),
    (r"mustard\s*oil", 155),
    (r"sugar", 42),
    (r"salt", 22),
    (r"tea\s*powder|chai", 80),
    (r"maggi|instant\s*noodles", 15),
    (r"parle.?g|biscuits?", 20),
    (r"turmeric|haldi", 40),
    (r"red\s*chilli|lal\s*mirch", 45),
    (r"coriander|dhania", 38),
    (r"toothpaste|colgate", 85),
    (r"soap|sabun", 32),
    (r"shampoo", 165),
    (r"hair\s*oil|parachute", 95),
    (r"washing\s*powder|detergent", 75),
    (r"floor\s*cleaner|phenyl", 55),
    (r"led\s*bulb", 80),
    (r"battery", 40),
    (r"notebook|copy", 55),
    (r"pen\b", 5),
    (r"pencil", 30),
]


def _parse_items_from_text(text: str) -> list[dict[str, Any]]:
    """Extract stock items from free text using regex patterns."""
    text_lower = text.lower()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pattern, price in _ITEM_PATTERNS:
        if re.search(pattern, text_lower):
            # Try to extract quantity
            qty_match = re.search(
                rf"(\d+)\s*(?:kg|pc|packet|pcs|pack|unit|nos)?\s*{pattern}|"
                rf"{pattern}\s*[-:]?\s*(\d+)",
                text_lower,
            )
            qty = 1
            if qty_match:
                raw = qty_match.group(1) or qty_match.group(2)
                if raw and int(raw) <= 500:
                    qty = int(raw)

            item_name = pattern.replace(r"\s*", " ").replace(r"\b", "").replace("?", "").strip()
            if item_name not in seen:
                seen.add(item_name)
                items.append({
                    "name": item_name,
                    "quantity": qty,
                    "unit_price_inr": price,
                })

    return items


async def run(ctx: StepContext, claude: Any) -> StepOutput:  # noqa: ARG001
    """Stub stock quantification — pure Python, no LLM."""
    pd_data = ctx.extractions.get("pd_sheet") or {}
    autocam = ctx.extractions.get("auto_cam") or ctx.extractions.get("autocam") or {}

    # Collect stock-related text from PD Sheet + AutoCam
    stock_text_parts: list[str] = []
    for key in ("stock_description", "inventory", "stock_items", "goods_description"):
        val = pd_data.get(key) or autocam.get(key)
        if val:
            stock_text_parts.append(str(val))
    # Also check narrative paragraphs
    for key in ("text", "narrative", "remarks", "observations"):
        val = pd_data.get(key)
        if val:
            stock_text_parts.append(str(val)[:500])

    stock_text = " ".join(stock_text_parts)

    items = _parse_items_from_text(stock_text) if stock_text else []

    total_value = sum(item["name"] and item["quantity"] * item["unit_price_inr"] for item in items)

    # Get loan amount from case or AutoCAM
    loan_amount = 0
    if hasattr(ctx, "case") and ctx.case is not None:
        loan_amount = getattr(ctx.case, "loan_amount", 0) or 0
    if loan_amount == 0:
        loan_amount = int(autocam.get("loan_amount_requested", autocam.get("loan_amount", 0)) or 0)

    stock_to_loan_min = float(
        ctx.policy.get("hard_rules", {}).get("stock_to_loan_ratio_min", 1.0)
    )
    passes_loan_vs_stock = (
        total_value >= loan_amount * stock_to_loan_min if loan_amount > 0 else True
    )

    output_data: dict[str, Any] = {
        "stock_estimation_mode": "stub",
        "items_identified": items,
        "total_stock_value_inr": int(total_value),
        "passes_loan_vs_stock": passes_loan_vs_stock,
        "notes": "Vision-based stock extraction deferred to M5.1",
    }

    warnings: list[str] = []
    if not stock_text:
        warnings.append("No stock description found in PD Sheet or AutoCAM")
    if not items:
        warnings.append("No recognizable stock items detected in text")

    return StepOutput(
        status=StepStatus.SUCCEEDED,
        step_name=STEP_NAME,
        step_number=STEP_NUMBER,
        model_used=None,
        output_data=output_data,
        citations=[],
        warnings=warnings,
    )
