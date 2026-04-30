"""Tests for L3 Claude-Sonnet vision scorers — house + business premises."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.enums import ExtractionStatus
from app.verification.services.vision_scorers import (
    HousePremisesScorer,
    BusinessPremisesScorer,
)


def _mock(payload: dict, cost: float = 0.045) -> MagicMock:
    mock_msg = MagicMock()
    c = MagicMock()
    c.invoke = AsyncMock(return_value=mock_msg)
    c.extract_text = MagicMock(return_value=json.dumps(payload))
    c.usage_dict = MagicMock(return_value={"input_tokens": 10_000, "output_tokens": 500})
    c.cost_usd = MagicMock(return_value=cost)
    return c


# ---- HousePremisesScorer ----


async def test_house_scorer_returns_structured_rating():
    payload = {
        "overall_rating": "good",
        "space_rating": "good",
        "furnishing_rating": "ok",
        "upkeep_rating": "good",
        "high_value_assets_visible": ["LED TV", "refrigerator", "washing machine"],
        "construction_type": "pakka",
        "flooring": "tiled",
        "kitchen_condition": "good",
        "concerns": [],
        "positives": [
            "Large living room with sofa + TV",
            "Pakka brick-and-plaster construction, tiled floor",
        ],
    }
    claude = _mock(payload)
    scorer = HousePremisesScorer(claude=claude)

    imgs = [(f"house{i}.jpeg", b"\xff\xd8\xff\xe0" + bytes([i])) for i in range(3)]
    result = await scorer.score(imgs)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["overall_rating"] == "good"
    assert result.data["construction_type"] == "pakka"
    assert "LED TV" in result.data["high_value_assets_visible"]
    assert result.data["cost_usd"] == 0.045
    assert result.data["model_used"].startswith("claude-opus")


async def test_house_scorer_sends_all_images_as_vision_blocks():
    claude = _mock(
        {"overall_rating": "ok", "concerns": [], "positives": []}
    )
    scorer = HousePremisesScorer(claude=claude)
    imgs = [(f"h{i}.jpeg", b"\xff\xd8\xff\xe0") for i in range(4)]

    await scorer.score(imgs)

    content = claude.invoke.call_args.kwargs["messages"][0]["content"]
    image_blocks = [b for b in content if b.get("type") == "image"]
    assert len(image_blocks) == 4
    for b in image_blocks:
        assert b["source"]["type"] == "base64"


async def test_house_scorer_empty_image_list_returns_partial():
    claude = _mock({"overall_rating": None, "concerns": [], "positives": []})
    scorer = HousePremisesScorer(claude=claude)
    result = await scorer.score([])

    assert result.status == ExtractionStatus.PARTIAL
    assert any("no house visit photos" in w.lower() for w in result.warnings)


# ---- BusinessPremisesScorer ----


async def test_business_scorer_estimates_stock_and_infra():
    payload = {
        "stock_value_estimate_inr": 250000,
        "stock_condition": "good",
        "stock_variety": "wide",
        "cattle_count": 2,
        "cattle_health": "healthy",
        "infrastructure_rating": "good",
        "infrastructure_details": ["shed 10x12 ft", "water trough", "feed bags"],
        "concerns": [],
        "positives": ["Fresh stock on shelves; display well-organised"],
    }
    claude = _mock(payload, cost=0.055)
    scorer = BusinessPremisesScorer(claude=claude)
    imgs = [(f"biz{i}.jpeg", b"\xff\xd8\xff\xe0") for i in range(6)]

    result = await scorer.score(imgs, loan_amount_inr=100000)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["stock_value_estimate_inr"] == 250000
    assert result.data["cattle_count"] == 2
    assert result.data["cost_usd"] == 0.055


async def test_business_scorer_prompt_includes_loan_amount_anchor():
    claude = _mock(
        {
            "stock_value_estimate_inr": 50000,
            "stock_condition": "ok",
            "concerns": [],
            "positives": [],
        }
    )
    scorer = BusinessPremisesScorer(claude=claude)

    await scorer.score(
        [("b.jpeg", b"\xff\xd8\xff\xe0")],
        loan_amount_inr=125_000,
    )
    # The prompt should mention the loan amount so Sonnet can compare.
    user_text = next(
        b["text"]
        for b in claude.invoke.call_args.kwargs["messages"][0]["content"]
        if b["type"] == "text"
    )
    assert "125" in user_text


async def test_business_scorer_failed_on_non_json():
    mock_msg = MagicMock()
    c = MagicMock()
    c.invoke = AsyncMock(return_value=mock_msg)
    c.extract_text = MagicMock(return_value="cannot score")
    c.usage_dict = MagicMock(return_value={"input_tokens": 10000, "output_tokens": 10})
    c.cost_usd = MagicMock(return_value=0.03)
    scorer = BusinessPremisesScorer(claude=c)
    result = await scorer.score([("b.jpeg", b"\xff\xd8\xff\xe0")])
    assert result.status == ExtractionStatus.FAILED
