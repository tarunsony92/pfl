"""Async wrapper around the Anthropic SDK.

Features:
- Prompt caching via ``cache_control: {"type": "ephemeral"}`` on system blocks.
- Per-model cost tracking (USD).
- Exponential-backoff retry on ``RateLimitError`` / ``APIConnectionError`` /
  ``APIStatusError`` (5xx). ``AuthenticationError`` is re-raised immediately.
- Module-level singleton accessible via ``get_claude_service()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message

_log = logging.getLogger(__name__)

# ── Model name constants ──────────────────────────────────────────────────────

MODELS: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}

# ── Per-million-token pricing (USD) ─────────────────────────────────────────
# Keep in sync with Anthropic pricing page.

PRICING_USD_PER_M: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-opus-4-7": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
}

# Retry delays in seconds for transient errors (3 attempts total)
_RETRY_DELAYS_S: list[float] = [1.0, 2.0, 4.0]


# ── ClaudeService ─────────────────────────────────────────────────────────────


class ClaudeService:
    """Async wrapper around ``AsyncAnthropic`` with caching + cost tracking."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url is not None:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)

    async def invoke(
        self,
        *,
        tier: Literal["haiku", "sonnet", "opus"],
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        cache_system: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> Message:
        """Call Claude with optional prompt caching on the system block.

        Args:
            tier: Model tier — "haiku", "sonnet", or "opus".
            system: System prompt text or pre-built content list.
            messages: Conversation messages.
            cache_system: If True *and* ``system`` is a plain string, wrap it in
                a ``cache_control: ephemeral`` content block so Anthropic caches
                the system prompt across requests that share the same block.
            max_tokens: Maximum response tokens.
            temperature: Sampling temperature (0 = deterministic).

        Returns:
            Raw ``anthropic.types.Message`` object.
        """
        model = MODELS[tier]

        sys_param: Any
        if cache_system and isinstance(system, str):
            sys_param = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            sys_param = system

        # Claude 4.7 (Opus) rejects the `temperature` parameter as deprecated
        # for that model family. Other tiers (Haiku 4.5, Sonnet 4.6) still
        # accept it, so we only omit for opus.
        create_kwargs: dict[str, Any] = {
            "model": model,
            "system": sys_param,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tier != "opus":
            create_kwargs["temperature"] = temperature

        last_exc: Exception | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS_S, start=1):
            try:
                return await self._client.messages.create(**create_kwargs)  # type: ignore[arg-type]
            except anthropic.AuthenticationError:
                # Config issue — no point retrying
                raise
            except (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.APIStatusError,
            ) as exc:
                last_exc = exc
                if attempt < len(_RETRY_DELAYS_S):
                    _log.warning(
                        "Claude API transient error (attempt %d/%d), "
                        "retrying in %.0fs: %s",
                        attempt,
                        len(_RETRY_DELAYS_S),
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    _log.error(
                        "Claude API error after %d attempts: %s",
                        len(_RETRY_DELAYS_S),
                        exc,
                    )

        # All retries exhausted
        assert last_exc is not None
        raise last_exc

    # ── Cost helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def cost_usd(model: str, usage: dict[str, int]) -> float:
        """Calculate cost in USD from token usage dict.

        ``usage`` keys mirror the Anthropic ``Usage`` object attributes:
        ``input_tokens``, ``output_tokens``,
        ``cache_creation_input_tokens``, ``cache_read_input_tokens``.
        """
        rates = PRICING_USD_PER_M.get(model, PRICING_USD_PER_M["claude-sonnet-4-6"])
        input_cost = usage.get("input_tokens", 0) * rates["input"] / 1_000_000
        output_cost = usage.get("output_tokens", 0) * rates["output"] / 1_000_000
        cache_write = (
            usage.get("cache_creation_input_tokens", 0) * rates["cache_write"] / 1_000_000
        )
        cache_read = (
            usage.get("cache_read_input_tokens", 0) * rates["cache_read"] / 1_000_000
        )
        return round(input_cost + output_cost + cache_write + cache_read, 6)

    @staticmethod
    def usage_dict(message: Message) -> dict[str, int]:
        """Extract token usage from a ``Message`` into a plain dict."""
        u = message.usage
        result: dict[str, int] = {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
        }
        # Prompt-cache fields are optional (Pydantic model may not have them)
        if hasattr(u, "cache_creation_input_tokens") and u.cache_creation_input_tokens:
            result["cache_creation_input_tokens"] = u.cache_creation_input_tokens
        if hasattr(u, "cache_read_input_tokens") and u.cache_read_input_tokens:
            result["cache_read_input_tokens"] = u.cache_read_input_tokens
        return result

    @staticmethod
    def extract_text(message: Message) -> str:
        """Return the concatenated text content from a response message."""
        parts: list[str] = []
        for block in message.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts)


# ── Module-level singleton ────────────────────────────────────────────────────

_svc: ClaudeService | None = None


def get_claude_service(settings: Any = None) -> ClaudeService:
    """Return the module-level ``ClaudeService`` singleton.

    Initialised on first call from ``app.config.get_settings()``.
    Pass ``settings`` explicitly in tests to avoid importing the real config.
    """
    global _svc
    if _svc is None:
        from app.config import get_settings as _get_settings

        s = settings or _get_settings()
        _svc = ClaudeService(
            api_key=s.anthropic_api_key,
            base_url=s.anthropic_base_url,
        )
    return _svc


def reset_claude_service_for_tests() -> None:
    """Clear the singleton — call in test teardown to prevent state leakage."""
    global _svc
    _svc = None
