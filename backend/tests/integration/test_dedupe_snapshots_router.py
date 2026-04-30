"""Dedupe snapshots router HTTP-layer tests."""

from pathlib import Path

import pytest
import pytest_asyncio

from app.core.security import create_access_token
from app.enums import UserRole
from app.services import users as users_svc
from app.services.storage import StorageService, reset_storage_for_tests
from tests.fixtures.builders.dedupe_builder import build_dedupe_xlsx

# Content type for xlsx files
_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_storage_for_tests()
    yield
    reset_storage_for_tests()


@pytest_asyncio.fixture
async def initialized_storage(mock_aws_services):
    """Pre-create S3 bucket + set singleton for router tests."""
    import app.services.storage as _st_mod

    storage = StorageService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        bucket="pfl-cases-dev",
    )
    await storage.ensure_bucket_exists()
    _st_mod._instance = storage
    yield storage
    reset_storage_for_tests()


async def _token_for(db, email: str, role: UserRole) -> tuple[str, str]:
    """Create a user and return (user_id, access_token)."""
    user = await users_svc.create_user(
        db,
        email=email,
        password="Pass123!",
        full_name="T",
        role=role,
    )
    await db.commit()
    return str(user.id), create_access_token(subject=str(user.id))


async def test_admin_can_upload_new_dedupe_snapshot(client, db, initialized_storage, tmp_path):
    """Admin uploads valid xlsx → 201 with snapshot in DB."""
    _, token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {token}"}

    # Build valid dedupe xlsx
    xlsx_path = Path(tmp_path) / "test.xlsx"
    build_dedupe_xlsx(xlsx_path)

    with open(xlsx_path, "rb") as f:
        r = await client.post(
            "/dedupe-snapshots",
            headers=hdrs,
            files={"file": ("test.xlsx", f, _CONTENT_TYPE)},
        )

    assert r.status_code == 201
    body = r.json()
    assert body["id"]
    assert body["uploaded_by"]
    assert body["row_count"] == 2  # Two default customers
    assert body["is_active"] is True


async def test_non_admin_cannot_upload(client, db, initialized_storage, tmp_path):
    """Credit HO cannot upload → 403."""
    _, token = await _token_for(db, "credit_ho@pfl.com", UserRole.CREDIT_HO)
    hdrs = {"Authorization": f"Bearer {token}"}

    xlsx_path = Path(tmp_path) / "test.xlsx"
    build_dedupe_xlsx(xlsx_path)

    with open(xlsx_path, "rb") as f:
        r = await client.post(
            "/dedupe-snapshots",
            headers=hdrs,
            files={"file": ("test.xlsx", f, _CONTENT_TYPE)},
        )

    assert r.status_code == 403


async def test_upload_deactivates_previous_active(client, db, initialized_storage, tmp_path):
    """Upload snapshot B → previous snapshot A becomes inactive."""
    _, admin_token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {admin_token}"}

    # Upload A
    xlsx_path_a = Path(tmp_path) / "a.xlsx"
    build_dedupe_xlsx(xlsx_path_a)
    with open(xlsx_path_a, "rb") as f:
        r1 = await client.post(
            "/dedupe-snapshots",
            headers=hdrs,
            files={"file": ("a.xlsx", f, _CONTENT_TYPE)},
        )
    assert r1.status_code == 201
    snapshot_a_id = r1.json()["id"]
    assert r1.json()["is_active"] is True

    # Upload B
    xlsx_path_b = Path(tmp_path) / "b.xlsx"
    build_dedupe_xlsx(xlsx_path_b, customers=[{"Customer Name": "NEW"}])
    with open(xlsx_path_b, "rb") as f:
        r2 = await client.post(
            "/dedupe-snapshots",
            headers=hdrs,
            files={"file": ("b.xlsx", f, _CONTENT_TYPE)},
        )
    assert r2.status_code == 201
    snapshot_b_id = r2.json()["id"]
    assert r2.json()["is_active"] is True

    # Check A is now inactive
    from sqlalchemy import select

    from app.models.dedupe_snapshot import DedupeSnapshot

    stmt = select(DedupeSnapshot).where(DedupeSnapshot.id == snapshot_a_id)
    result = await db.execute(stmt)
    snapshot_a = result.scalar_one()
    assert snapshot_a.is_active is False

    # Check B is active
    stmt = select(DedupeSnapshot).where(DedupeSnapshot.id == snapshot_b_id)
    result = await db.execute(stmt)
    snapshot_b = result.scalar_one()
    assert snapshot_b.is_active is True


async def test_file_too_large_returns_413(client, db, initialized_storage):
    """Upload > 50 MB → 413."""
    _, token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {token}"}

    # Simulate large file by reading more than max_artifact_size_bytes
    from app.config import get_settings

    max_bytes = get_settings().max_artifact_size_bytes
    large_content = b"x" * (max_bytes + 1)

    r = await client.post(
        "/dedupe-snapshots",
        headers=hdrs,
        files={"file": ("huge.xlsx", large_content)},
    )

    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


async def test_invalid_xlsx_returns_400(client, db, initialized_storage):
    """Upload non-xlsx binary → 400."""
    _, token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {token}"}

    invalid_content = b"not a valid xlsx file"

    r = await client.post(
        "/dedupe-snapshots",
        headers=hdrs,
        files={"file": ("bad.xlsx", invalid_content)},
    )

    assert r.status_code == 400
    assert "Invalid xlsx" in r.json()["detail"]


async def test_list_snapshots_returns_all_ordered_desc(client, db, initialized_storage, tmp_path):
    """Admin lists → array of snapshots ordered by uploaded_at DESC."""
    _, admin_token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {admin_token}"}

    # Upload two snapshots
    xlsx_path_a = Path(tmp_path) / "a.xlsx"
    build_dedupe_xlsx(xlsx_path_a)
    with open(xlsx_path_a, "rb") as f:
        await client.post(
            "/dedupe-snapshots",
            headers=hdrs,
            files={"file": ("a.xlsx", f, _CONTENT_TYPE)},
        )

    xlsx_path_b = Path(tmp_path) / "b.xlsx"
    build_dedupe_xlsx(xlsx_path_b)
    with open(xlsx_path_b, "rb") as f:
        await client.post(
            "/dedupe-snapshots",
            headers=hdrs,
            files={"file": ("b.xlsx", f, _CONTENT_TYPE)},
        )

    # List
    r = await client.get("/dedupe-snapshots", headers=hdrs)
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 2
    # Check ordered DESC by uploaded_at
    for i in range(len(body) - 1):
        assert body[i]["uploaded_at"] >= body[i + 1]["uploaded_at"]


async def test_list_forbidden_to_ai_analyser(client, db, initialized_storage):
    """AI_ANALYSER cannot list → 403."""
    _, token = await _token_for(db, "ai@pfl.com", UserRole.AI_ANALYSER)
    hdrs = {"Authorization": f"Bearer {token}"}

    r = await client.get("/dedupe-snapshots", headers=hdrs)
    assert r.status_code == 403


async def test_get_active_returns_active_snapshot(client, db, initialized_storage, tmp_path):
    """Any user GETs /active → active snapshot."""
    _, admin_token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}

    # Admin uploads
    xlsx_path = Path(tmp_path) / "test.xlsx"
    build_dedupe_xlsx(xlsx_path)
    with open(xlsx_path, "rb") as f:
        r = await client.post(
            "/dedupe-snapshots",
            headers=admin_hdrs,
            files={"file": ("test.xlsx", f, _CONTENT_TYPE)},
        )
    uploaded_id = r.json()["id"]

    # Any user (e.g., UNDERWRITER) can get active
    _, user_token = await _token_for(db, "user@pfl.com", UserRole.UNDERWRITER)
    user_hdrs = {"Authorization": f"Bearer {user_token}"}

    r = await client.get("/dedupe-snapshots/active", headers=user_hdrs)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == uploaded_id
    assert body["is_active"] is True


async def test_get_active_404_when_none(client, db):
    """GET /active with no active snapshot → 404."""
    _, token = await _token_for(db, "user@pfl.com", UserRole.UNDERWRITER)
    hdrs = {"Authorization": f"Bearer {token}"}

    r = await client.get("/dedupe-snapshots/active", headers=hdrs)
    assert r.status_code == 404


async def test_get_active_allowed_for_ai_analyser(client, db, initialized_storage, tmp_path):
    """AI_ANALYSER can get active (any authenticated user)."""
    _, admin_token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}

    # Admin uploads
    xlsx_path = Path(tmp_path) / "test.xlsx"
    build_dedupe_xlsx(xlsx_path)
    with open(xlsx_path, "rb") as f:
        await client.post(
            "/dedupe-snapshots",
            headers=admin_hdrs,
            files={"file": ("test.xlsx", f, _CONTENT_TYPE)},
        )

    # AI_ANALYSER gets active
    _, ai_token = await _token_for(db, "ai@pfl.com", UserRole.AI_ANALYSER)
    ai_hdrs = {"Authorization": f"Bearer {ai_token}"}

    r = await client.get("/dedupe-snapshots/active", headers=ai_hdrs)
    assert r.status_code == 200
    assert r.json()["is_active"] is True


async def test_upload_without_filename_returns_422(client, db, initialized_storage):
    """Upload without filename → 422 (form validation)."""
    _, token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    hdrs = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/dedupe-snapshots",
        headers=hdrs,
        files={"file": (None, b"content")},
    )

    assert r.status_code == 422


async def test_list_returns_download_urls(client, db, initialized_storage, tmp_path):
    """Snapshots in list include download_url field."""
    _, admin_token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}

    # Admin uploads
    xlsx_path = Path(tmp_path) / "test.xlsx"
    build_dedupe_xlsx(xlsx_path)
    with open(xlsx_path, "rb") as f:
        await client.post(
            "/dedupe-snapshots",
            headers=admin_hdrs,
            files={"file": ("test.xlsx", f, _CONTENT_TYPE)},
        )

    # List
    r = await client.get("/dedupe-snapshots", headers=admin_hdrs)
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    assert body[0]["download_url"] is not None


async def test_audit_logs_upload_and_activation(client, db, initialized_storage, tmp_path):
    """Upload creates two audit logs: uploaded + activated."""
    _, admin_token = await _token_for(db, "admin@pfl.com", UserRole.ADMIN)
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}

    # Admin uploads
    xlsx_path = Path(tmp_path) / "test.xlsx"
    build_dedupe_xlsx(xlsx_path)
    with open(xlsx_path, "rb") as f:
        r = await client.post(
            "/dedupe-snapshots",
            headers=admin_hdrs,
            files={"file": ("test.xlsx", f, _CONTENT_TYPE)},
        )
    assert r.status_code == 201
    snapshot_id = r.json()["id"]

    # Check audit logs
    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == "dedupe_snapshot")
        .where(AuditLog.entity_id == snapshot_id)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    assert len(logs) >= 2
    actions = [log.action for log in logs]
    assert "dedupe_snapshot.uploaded" in actions
    assert "dedupe_snapshot.activated" in actions
