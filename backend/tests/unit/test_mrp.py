"""Unit tests for app.decisioning.mrp — uses real DB via `db` fixture."""

from __future__ import annotations

import pytest

from app.decisioning.mrp import _normalize, lookup, upsert
from app.enums import MrpSource


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("BASMATI RICE") == "basmati rice"

    def test_strips_whitespace(self):
        assert _normalize("  dal  ") == "dal"

    def test_lower_and_strip(self):
        assert _normalize("  TEA Powder  ") == "tea powder"


class TestUpsertAndLookup:
    @pytest.mark.asyncio
    async def test_upsert_new_item(self, db):
        entry = await upsert(db, "test unique dal xyz", "grocery", 99.0)
        assert entry is not None
        assert entry.item_normalized_name == "test unique dal xyz"
        assert float(entry.unit_price_inr) == 99.0

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_price(self, db):
        await upsert(db, "test price update item", "grocery", 50.0)
        await upsert(db, "test price update item", "grocery", 75.0)
        entry = await lookup(db, "test price update item")
        assert entry is not None
        assert float(entry.unit_price_inr) == 75.0

    @pytest.mark.asyncio
    async def test_lookup_exact_match(self, db):
        await upsert(db, "test lookup exact item", "cosmetics", 120.0)
        found = await lookup(db, "test lookup exact item")
        assert found is not None
        assert found.item_normalized_name == "test lookup exact item"

    @pytest.mark.asyncio
    async def test_lookup_normalizes_input(self, db):
        """Lookup should normalize the query the same way upsert does."""
        await upsert(db, "test norm item", "grocery", 55.0)
        found = await lookup(db, "  TEST NORM ITEM  ")
        assert found is not None

    @pytest.mark.asyncio
    async def test_lookup_returns_none_for_unknown(self, db):
        result = await lookup(db, "totally unknown item xyz123")
        assert result is None

    @pytest.mark.asyncio
    async def test_source_stored_correctly(self, db):
        await upsert(db, "test source item", "hardware", 30.0, source=MrpSource.OPUS_ESTIMATE)
        entry = await lookup(db, "test source item")
        assert entry is not None
        assert entry.source == MrpSource.OPUS_ESTIMATE
