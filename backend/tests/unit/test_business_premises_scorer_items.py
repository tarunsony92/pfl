"""L3 Phase 2: BusinessPremisesScorer surfaces per-item array."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.enums import ExtractionStatus
from app.verification.services.vision_scorers import BusinessPremisesScorer


def test_empty_data_includes_items_key():
    """_EMPTY_DATA must include 'items' so failure paths return a
    consistent shape downstream consumers can iterate."""
    assert "items" in BusinessPremisesScorer._EMPTY_DATA
    assert BusinessPremisesScorer._EMPTY_DATA["items"] == []


def test_schema_version_bumped_to_2_0_on_no_images_path():
    """No-images path returns schema_version='2.0' (was '1.0')."""
    import asyncio

    scorer = BusinessPremisesScorer(claude=MagicMock())
    res = asyncio.run(scorer.score([], loan_amount_inr=100_000))
    assert res.schema_version == "2.0"
    assert res.status == ExtractionStatus.PARTIAL
    assert res.data["items"] == []


@pytest.mark.asyncio
async def test_items_array_passes_through_from_claude():
    """When Claude returns an items array, it ends up in result.data['items']
    unchanged."""

    class _StubClaude:
        async def invoke(self, **kwargs):
            return MagicMock()

        def extract_text(self, message):
            return """{
              "business_type": "service",
              "business_type_confidence": 0.9,
              "business_subtype": "barbershop",
              "stock_value_estimate_inr": 1500,
              "visible_equipment_value_inr": 20000,
              "stock_condition": "ok",
              "stock_variety": "narrow",
              "cattle_count": 0,
              "cattle_health": "not_applicable",
              "infrastructure_rating": "ok",
              "infrastructure_details": [],
              "recommended_loan_amount_inr": 60000,
              "recommended_loan_rationale": "service biz floor 40%",
              "concerns": [],
              "positives": [],
              "items": [
                {"description": "barber chair", "qty": 2, "category": "equipment",
                 "mrp_estimate_inr": 8500, "mrp_confidence": "medium",
                 "rationale": "two visible hydraulic chairs"},
                {"description": "shampoo bottle", "qty": 6, "category": "consumable",
                 "mrp_estimate_inr": 250, "mrp_confidence": "low",
                 "rationale": "small bottles partially visible"}
              ]
            }"""

        def usage_dict(self, message):
            return {"input_tokens": 100, "output_tokens": 200}

        def cost_usd(self, model, usage):
            return 0.05

    scorer = BusinessPremisesScorer(claude=_StubClaude())
    res = await scorer.score([("photo.jpg", b"fake")], loan_amount_inr=100_000)

    assert res.status == ExtractionStatus.SUCCESS
    assert res.schema_version == "2.0"
    assert len(res.data["items"]) == 2
    assert res.data["items"][0]["description"] == "barber chair"
    assert res.data["items"][0]["qty"] == 2
    assert res.data["items"][1]["mrp_estimate_inr"] == 250
    assert res.data["items"][1]["mrp_confidence"] == "low"
