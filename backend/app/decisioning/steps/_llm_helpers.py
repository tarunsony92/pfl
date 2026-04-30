"""Internal helpers shared across LLM-based step modules."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.claude import ClaudeService

_log = logging.getLogger(__name__)


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Parse JSON from LLM output, handling markdown code fences."""
    result: dict[str, Any]
    # Try direct parse first
    try:
        result = json.loads(text)
        return result
    except json.JSONDecodeError:
        pass
    # Strip markdown code fence
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1))
            return result
        except json.JSONDecodeError:
            pass
    # Last resort: find first { ... } block
    brace_match = re.search(r"\{[\s\S]+\}", text)
    if brace_match:
        try:
            result = json.loads(brace_match.group(0))
            return result
        except json.JSONDecodeError:
            pass
    _log.warning("Could not parse JSON from LLM response: %r", text[:200])
    return {}


def build_usage(message: Any, model_id: str) -> dict[str, Any]:
    """Extract token counts and cost from a ClaudeService Message."""
    usage = ClaudeService.usage_dict(message)
    cost = ClaudeService.cost_usd(model_id, usage)
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        "cost_usd": cost,
    }
