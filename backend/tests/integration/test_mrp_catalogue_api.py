"""Integration tests for the /admin/mrp-catalogue endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from app.core.security import create_access_token
from app.enums import UserRole
from app.services import users as users_svc


async def test_create_then_list_entry(client, db):
    user = await users_svc.create_user(
        db, email=f"mrp-api-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="MRP Tester", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(user.id))

    res = await client.post(
        "/admin/mrp-catalogue",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "business_type": "service",
            "item_description": "Barber Chair (Hydraulic)",
            "category": "equipment",
            "mrp_inr": 8500,
            "rationale": "manual seed",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["item_canonical"] == "barber_chair_hydraulic"
    assert body["source"] == "MANUAL"

    list_res = await client.get(
        "/admin/mrp-catalogue?business_type=service",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_res.status_code == 200
    rows = list_res.json()
    assert any(r["item_canonical"] == "barber_chair_hydraulic" for r in rows)


async def test_patch_flips_source_and_returns_updated(client, db):
    user = await users_svc.create_user(
        db, email=f"mrp-patch-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="MRP Patcher", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(user.id))

    # Create AI-source row directly via service helper
    from app.services.mrp_catalogue import upsert_from_ai
    e = await upsert_from_ai(
        db, business_type="service", item_description="hair clipper",
        category="equipment", mrp_inr=2500, confidence="medium",
        rationale="seen on station",
    )
    await db.flush()

    res = await client.patch(
        f"/admin/mrp-catalogue/{e.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"mrp_inr": 3000},
    )
    assert res.status_code == 200, res.text
    assert res.json()["mrp_inr"] == 3000
    assert res.json()["source"] == "OVERRIDDEN_FROM_AI"
