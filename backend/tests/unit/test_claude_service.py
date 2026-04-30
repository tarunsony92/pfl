"""Unit tests for app.services.claude.

All tests mock ``AsyncAnthropic`` — no real API calls are made.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from app.services.claude import (
    MODELS,
    PRICING_USD_PER_M,
    ClaudeService,
    get_claude_service,
    reset_claude_service_for_tests,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_usage(
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_write: int = 0,
    cache_read: int = 0,
) -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_creation_input_tokens = cache_write
    usage.cache_read_input_tokens = cache_read
    return usage


def _make_message(
    text: str = "Hello",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> MagicMock:
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    msg.usage = _make_usage(input_tokens=input_tokens, output_tokens=output_tokens)
    return msg


# ── Cost calculation ──────────────────────────────────────────────────────────


class TestCostCalculation:
    def test_haiku_cost_basic(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 0}
        cost = ClaudeService.cost_usd("claude-haiku-4-5", usage)
        assert cost == pytest.approx(0.80, abs=1e-6)

    def test_sonnet_output_cost(self):
        usage = {"input_tokens": 0, "output_tokens": 1_000_000}
        cost = ClaudeService.cost_usd("claude-sonnet-4-6", usage)
        assert cost == pytest.approx(15.00, abs=1e-6)

    def test_opus_input_plus_output(self):
        usage = {"input_tokens": 100_000, "output_tokens": 10_000}
        cost = ClaudeService.cost_usd("claude-opus-4-7", usage)
        expected = (100_000 * 15.00 + 10_000 * 75.00) / 1_000_000
        assert cost == pytest.approx(expected, abs=1e-6)

    def test_cache_write_tokens_haiku(self):
        usage = {"cache_creation_input_tokens": 1_000_000}
        cost = ClaudeService.cost_usd("claude-haiku-4-5", usage)
        assert cost == pytest.approx(PRICING_USD_PER_M["claude-haiku-4-5"]["cache_write"], abs=1e-6)

    def test_cache_read_tokens_sonnet(self):
        usage = {"cache_read_input_tokens": 1_000_000}
        cost = ClaudeService.cost_usd("claude-sonnet-4-6", usage)
        assert cost == pytest.approx(PRICING_USD_PER_M["claude-sonnet-4-6"]["cache_read"], abs=1e-6)

    def test_zero_usage(self):
        assert ClaudeService.cost_usd("claude-haiku-4-5", {}) == 0.0

    def test_unknown_model_falls_back_to_sonnet_rates(self):
        usage = {"input_tokens": 1_000_000}
        cost = ClaudeService.cost_usd("unknown-model", usage)
        assert cost == pytest.approx(3.00, abs=1e-6)

    def test_all_three_tiers_have_pricing(self):
        for tier_name, model_id in MODELS.items():
            assert model_id in PRICING_USD_PER_M, f"Missing pricing for tier {tier_name}"


# ── Cache parameter shape ────────────────────────────────────────────────────


class TestCacheParameterShape:
    @pytest.mark.asyncio
    async def test_cache_system_wraps_string_in_ephemeral_block(self):
        """When cache_system=True and system is a str, it becomes a cached content block."""
        with patch("app.services.claude.AsyncAnthropic") as MockClient:  # noqa: N806
            mock_create = AsyncMock(return_value=_make_message())
            MockClient.return_value.messages.create = mock_create

            svc = ClaudeService(api_key="test-key")
            await svc.invoke(
                tier="haiku",
                system="You are a credit analyst.",
                messages=[{"role": "user", "content": "Hello"}],
                cache_system=True,
            )

        call_kwargs = mock_create.call_args.kwargs
        sys_param = call_kwargs["system"]
        assert isinstance(sys_param, list), "system should be a list when cache_system=True"
        assert len(sys_param) == 1
        block = sys_param[0]
        assert block["type"] == "text"
        assert block["text"] == "You are a credit analyst."
        assert block["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_no_cache_passes_string_directly(self):
        """When cache_system=False, system string is passed as-is."""
        with patch("app.services.claude.AsyncAnthropic") as MockClient:  # noqa: N806
            mock_create = AsyncMock(return_value=_make_message())
            MockClient.return_value.messages.create = mock_create

            svc = ClaudeService(api_key="test-key")
            await svc.invoke(
                tier="sonnet",
                system="plain system prompt",
                messages=[{"role": "user", "content": "Hello"}],
                cache_system=False,
            )

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["system"] == "plain system prompt"

    @pytest.mark.asyncio
    async def test_pre_built_list_system_passed_unchanged(self):
        """If system is already a list, it is passed unchanged regardless of cache_system."""
        pre_built: list[dict[str, Any]] = [
            {"type": "text", "text": "block1", "cache_control": {"type": "ephemeral"}}
        ]
        with patch("app.services.claude.AsyncAnthropic") as MockClient:  # noqa: N806
            mock_create = AsyncMock(return_value=_make_message())
            MockClient.return_value.messages.create = mock_create

            svc = ClaudeService(api_key="test-key")
            await svc.invoke(
                tier="opus",
                system=pre_built,
                messages=[{"role": "user", "content": "Hi"}],
                cache_system=True,  # should be ignored since system is already a list
            )

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["system"] is pre_built

    @pytest.mark.asyncio
    async def test_correct_model_id_used_for_each_tier(self):
        """Verify the right model string is passed for each tier."""
        for tier, expected_model in MODELS.items():
            with patch("app.services.claude.AsyncAnthropic") as MockClient:  # noqa: N806
                mock_create = AsyncMock(return_value=_make_message())
                MockClient.return_value.messages.create = mock_create

                svc = ClaudeService(api_key="test-key")
                await svc.invoke(
                    tier=tier,  # type: ignore[arg-type]
                    system="system",
                    messages=[{"role": "user", "content": "hi"}],
                )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["model"] == expected_model, (
                f"Tier {tier!r} should use {expected_model!r}, "
                f"got {call_kwargs['model']!r}"
            )


# ── Retry behaviour ──────────────────────────────────────────────────────────


class TestRetryBehaviour:
    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_error(self):
        """RateLimitError triggers 2 retries before succeeding on 3rd attempt."""
        with patch("app.services.claude.AsyncAnthropic") as MockClient, patch(  # noqa: N806
            "app.services.claude.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            fail = anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )
            mock_create = AsyncMock(side_effect=[fail, fail, _make_message()])
            MockClient.return_value.messages.create = mock_create

            svc = ClaudeService(api_key="test-key")
            result = await svc.invoke(
                tier="haiku",
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert result is not None
        assert mock_create.call_count == 3
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        """After 3 consecutive failures the last exception propagates."""
        with patch("app.services.claude.AsyncAnthropic") as MockClient, patch(  # noqa: N806
            "app.services.claude.asyncio.sleep", new_callable=AsyncMock
        ):
            fail = anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )
            MockClient.return_value.messages.create = AsyncMock(side_effect=[fail, fail, fail])

            svc = ClaudeService(api_key="test-key")
            with pytest.raises(anthropic.RateLimitError):
                await svc.invoke(
                    tier="haiku",
                    system="sys",
                    messages=[{"role": "user", "content": "hi"}],
                )

    @pytest.mark.asyncio
    async def test_authentication_error_not_retried(self):
        """AuthenticationError is raised immediately without retry."""
        with patch("app.services.claude.AsyncAnthropic") as MockClient, patch(  # noqa: N806
            "app.services.claude.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            auth_err = anthropic.AuthenticationError(
                message="invalid key",
                response=MagicMock(status_code=401, headers={}),
                body={},
            )
            mock_create = AsyncMock(side_effect=auth_err)
            MockClient.return_value.messages.create = mock_create

            svc = ClaudeService(api_key="bad-key")
            with pytest.raises(anthropic.AuthenticationError):
                await svc.invoke(
                    tier="sonnet",
                    system="sys",
                    messages=[{"role": "user", "content": "hi"}],
                )

        assert mock_create.call_count == 1
        assert mock_sleep.call_count == 0


# ── Singleton behaviour ───────────────────────────────────────────────────────


class TestSingleton:
    def setup_method(self):
        reset_claude_service_for_tests()

    def teardown_method(self):
        reset_claude_service_for_tests()

    def test_get_claude_service_returns_same_instance(self):
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "key"
        mock_settings.anthropic_base_url = None

        with patch("app.services.claude.AsyncAnthropic"):
            svc1 = get_claude_service(settings=mock_settings)
            svc2 = get_claude_service(settings=mock_settings)
        assert svc1 is svc2

    def test_reset_clears_singleton(self):
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "key"
        mock_settings.anthropic_base_url = None

        with patch("app.services.claude.AsyncAnthropic"):
            svc1 = get_claude_service(settings=mock_settings)
        reset_claude_service_for_tests()
        with patch("app.services.claude.AsyncAnthropic"):
            svc2 = get_claude_service(settings=mock_settings)
        assert svc1 is not svc2


# ── Utility methods ──────────────────────────────────────────────────────────


class TestUtilityMethods:
    def test_extract_text_joins_text_blocks(self):
        msg = MagicMock()
        b1 = MagicMock()
        b1.text = "Hello "
        b2 = MagicMock()
        b2.text = "world"
        msg.content = [b1, b2]
        assert ClaudeService.extract_text(msg) == "Hello world"

    def test_usage_dict_basic(self):
        msg = _make_message(input_tokens=200, output_tokens=80)
        d = ClaudeService.usage_dict(msg)
        assert d["input_tokens"] == 200
        assert d["output_tokens"] == 80

    def test_usage_dict_with_cache_fields(self):
        msg = MagicMock()
        msg.content = []
        msg.usage = _make_usage(
            input_tokens=50,
            output_tokens=20,
            cache_write=300,
            cache_read=150,
        )
        d = ClaudeService.usage_dict(msg)
        assert d["cache_creation_input_tokens"] == 300
        assert d["cache_read_input_tokens"] == 150
