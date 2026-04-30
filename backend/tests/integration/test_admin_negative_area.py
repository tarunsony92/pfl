"""Integration tests for /admin/negative-areas CRUD + bulk upload."""
from __future__ import annotations

from datetime import UTC, datetime

from app.core.security import create_access_token
from app.enums import UserRole
from app.services import users as users_svc


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_non_admin_blocked(client, db):
    user = await users_svc.create_user(
        db, email=f"na-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Analyst", role=UserRole.AI_ANALYSER,
    )
    await db.flush()
    token = create_access_token(subject=str(user.id))
    res = await client.get("/admin/negative-areas", headers=_auth(token))
    assert res.status_code == 403


async def test_create_then_list(client, db):
    admin = await users_svc.create_user(
        db, email=f"na-admin-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))

    res = await client.post(
        "/admin/negative-areas",
        headers=_auth(token),
        json={"pincode": "560001", "reason": "fraud cluster"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["pincode"] == "560001"
    assert body["is_active"] is True

    list_res = await client.get("/admin/negative-areas", headers=_auth(token))
    assert list_res.status_code == 200
    rows = list_res.json()
    assert any(r["pincode"] == "560001" for r in rows)


async def test_create_rejects_invalid_pincode(client, db):
    admin = await users_svc.create_user(
        db, email=f"na-bad-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))
    res = await client.post(
        "/admin/negative-areas",
        headers=_auth(token),
        json={"pincode": "ABC123", "reason": "bad"},
    )
    assert res.status_code == 400


async def test_duplicate_pincode_409(client, db):
    admin = await users_svc.create_user(
        db, email=f"na-dup-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))
    await client.post(
        "/admin/negative-areas",
        headers=_auth(token),
        json={"pincode": "110001"},
    )
    res = await client.post(
        "/admin/negative-areas",
        headers=_auth(token),
        json={"pincode": "110001"},
    )
    assert res.status_code == 409


async def test_bulk_upload_dedups_and_tracks_invalid(client, db):
    admin = await users_svc.create_user(
        db, email=f"na-bulk-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))

    res = await client.post(
        "/admin/negative-areas/bulk",
        headers=_auth(token),
        json={
            "pincodes": ["400001", "400002", "400001", "abcd", "400003"],
            "reason": "RBI restricted Q2",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["inserted"] == 3
    assert body["skipped_duplicates"] == 1
    assert body["skipped_invalid"] == ["abcd"]


async def test_patch_toggles_active(client, db):
    admin = await users_svc.create_user(
        db, email=f"na-patch-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))
    create = await client.post(
        "/admin/negative-areas",
        headers=_auth(token),
        json={"pincode": "201001"},
    )
    entry_id = create.json()["id"]

    patch = await client.patch(
        f"/admin/negative-areas/{entry_id}",
        headers=_auth(token),
        json={"is_active": False, "reason": "now lifted"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["is_active"] is False
    assert patch.json()["reason"] == "now lifted"


async def test_delete_removes_entry(client, db):
    admin = await users_svc.create_user(
        db, email=f"na-del-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!", full_name="Admin", role=UserRole.ADMIN,
    )
    await db.flush()
    token = create_access_token(subject=str(admin.id))
    create = await client.post(
        "/admin/negative-areas",
        headers=_auth(token),
        json={"pincode": "302001"},
    )
    entry_id = create.json()["id"]
    res = await client.delete(
        f"/admin/negative-areas/{entry_id}", headers=_auth(token)
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    list_res = await client.get("/admin/negative-areas", headers=_auth(token))
    assert all(r["id"] != entry_id for r in list_res.json())
