"""Integration tests for case feedback endpoints (M4 §7)."""

import pytest

from app.core.security import create_access_token
from app.enums import UserRole
from app.services import users as users_svc
from app.services.storage import StorageService, reset_storage_for_tests


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_storage_for_tests()
    yield
    reset_storage_for_tests()


@pytest.fixture
async def storage(mock_aws_services):
    import app.services.storage as _st_mod

    s = StorageService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        bucket="pfl-cases-dev",
    )
    await s.ensure_bucket_exists()
    _st_mod._instance = s
    yield s
    reset_storage_for_tests()


async def _token(db, email: str, role: UserRole) -> tuple[str, str]:
    user = await users_svc.create_user(
        db,
        email=email,
        password="Pass123!",
        full_name="Test",
        role=role,
    )
    await db.commit()
    return str(user.id), create_access_token(subject=str(user.id))


async def _make_case(client, headers: dict) -> str:
    import uuid as _uuid

    loan_id = f"FB-{str(_uuid.uuid4())[:8].upper()}"
    r = await client.post("/cases/initiate", headers=headers, json={"loan_id": loan_id})
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


async def test_submit_feedback_returns_201(client, db, storage):
    _, tok = await _token(db, "fb1@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    case_id = await _make_case(client, hdrs)

    r = await client.post(
        f"/cases/{case_id}/feedback",
        headers=hdrs,
        json={"verdict": "APPROVE", "notes": "Looks good"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["verdict"] == "APPROVE"
    assert body["notes"] == "Looks good"
    assert body["phase"] == "phase1"
    assert body["case_id"] == case_id


async def test_list_feedback_returns_most_recent_first(client, db, storage):
    _, tok = await _token(db, "fb2@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    case_id = await _make_case(client, hdrs)

    for verdict in ("APPROVE", "NEEDS_REVISION", "REJECT"):
        await client.post(
            f"/cases/{case_id}/feedback",
            headers=hdrs,
            json={"verdict": verdict},
        )

    r = await client.get(f"/cases/{case_id}/feedback", headers=hdrs)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    # Most recent first: last inserted was REJECT
    assert body[0]["verdict"] == "REJECT"


async def test_submit_feedback_requires_auth(client, db):
    from uuid import uuid4
    r = await client.post(
        f"/cases/{uuid4()}/feedback",
        json={"verdict": "APPROVE"},
    )
    assert r.status_code == 401


async def test_submit_feedback_404_for_missing_case(client, db, storage):
    from uuid import uuid4
    _, tok = await _token(db, "fb3@pfl.com", UserRole.AI_ANALYSER)
    r = await client.post(
        f"/cases/{uuid4()}/feedback",
        headers={"Authorization": f"Bearer {tok}"},
        json={"verdict": "APPROVE"},
    )
    assert r.status_code == 404


async def test_submit_feedback_invalid_verdict_422(client, db, storage):
    _, tok = await _token(db, "fb4@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    case_id = await _make_case(client, hdrs)

    r = await client.post(
        f"/cases/{case_id}/feedback",
        headers=hdrs,
        json={"verdict": "MAYBE"},
    )
    assert r.status_code == 422


async def test_multiple_feedbacks_same_case_allowed(client, db, storage):
    """Multiple feedback rows per case are allowed (no unique constraint)."""
    _, tok = await _token(db, "fb5@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {tok}"}
    case_id = await _make_case(client, hdrs)

    r1 = await client.post(
        f"/cases/{case_id}/feedback", headers=hdrs, json={"verdict": "APPROVE"}
    )
    r2 = await client.post(
        f"/cases/{case_id}/feedback", headers=hdrs, json={"verdict": "REJECT", "notes": "Changed mind"}
    )
    assert r1.status_code == 201
    assert r2.status_code == 201

    r_list = await client.get(f"/cases/{case_id}/feedback", headers=hdrs)
    assert len(r_list.json()) == 2
