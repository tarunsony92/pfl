"""Unit tests for the MRP catalogue service helpers."""
from __future__ import annotations

import pytest

from app.services.mrp_catalogue import (
    canonicalise,
    upsert_from_ai,
    update_entry,
    get_entry,
    create_manual,
)


def test_canonicalise_basic():
    assert canonicalise("Barber Chair (Hydraulic)") == "barber_chair_hydraulic"
    assert canonicalise("LED Tube Light / Strip") == "led_tube_light_strip"
    assert canonicalise("  TRIMMER  ") == "trimmer"


@pytest.mark.asyncio
async def test_upsert_from_ai_inserts_then_increments(db):
    e1 = await upsert_from_ai(
        db, business_type="service", item_description="Barber Chair",
        category="equipment", mrp_inr=8500, confidence="medium",
        rationale="two visible chairs",
    )
    assert e1.observed_count == 1
    assert e1.source == "AI_ESTIMATED"

    # Same item, different case + punctuation -> same canonical -> increment
    e2 = await upsert_from_ai(
        db, business_type="service", item_description="barber chair",
        category="equipment", mrp_inr=9000, confidence="high",
        rationale="seen again",
    )
    assert e2.id == e1.id
    assert e2.observed_count == 2
    # mrp_inr and category MUST NOT be overwritten on subsequent sightings
    assert e2.mrp_inr == 8500


@pytest.mark.asyncio
async def test_update_entry_flips_ai_to_overridden(db, user_factory=None):
    # Seed via AI
    e = await upsert_from_ai(
        db, business_type="service", item_description="hair clipper",
        category="equipment", mrp_inr=2500, confidence="medium", rationale="x",
    )
    assert e.source == "AI_ESTIMATED"

    # Need an actor user_id — use a UUID not tied to the users table
    # since updated_by_user_id is nullable / SET NULL on FK.
    from app.services import users as users_svc
    from app.enums import UserRole
    from datetime import datetime, UTC
    actor = await users_svc.create_user(
        db, email=f"mrp-actor-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="MRP Actor", role=UserRole.ADMIN,
    )
    await db.flush()

    updated = await update_entry(
        db, entry_id=e.id, actor_user_id=actor.id, mrp_inr=3000,
    )
    assert updated is not None
    assert updated.mrp_inr == 3000
    assert updated.source == "OVERRIDDEN_FROM_AI"
    assert updated.updated_by_user_id == actor.id


@pytest.mark.asyncio
async def test_create_manual_then_lookup(db):
    from app.services import users as users_svc
    from app.enums import UserRole
    from datetime import datetime, UTC
    actor = await users_svc.create_user(
        db, email=f"mrp-mk-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="MRP Maker", role=UserRole.ADMIN,
    )
    await db.flush()

    e = await create_manual(
        db, business_type="cattle_dairy",
        item_description="Crossbreed Cow",
        category="stock", mrp_inr=60000, rationale="market 2026",
        actor_user_id=actor.id,
    )
    assert e.source == "MANUAL"
    assert e.observed_count == 0

    # Lookup by canonical
    looked = await get_entry(
        db, business_type="cattle_dairy", item_canonical="crossbreed_cow"
    )
    assert looked is not None
    assert looked.id == e.id
