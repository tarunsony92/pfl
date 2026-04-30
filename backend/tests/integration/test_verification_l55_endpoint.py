"""Integration test: POST /cases/{case_id}/verification/L5_5_DEDUPE_TVR
routes to run_level_5_5_dedupe_tvr and persists a VerificationResult.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.enums import (
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.services import users as users_svc


async def _seed_case_for_l55(db, role=UserRole.AI_ANALYSER):
    user = await users_svc.create_user(
        db,
        email=f"l55-endpoint-{datetime.now(UTC).timestamp()}@pfl.com",
        password="Pass123!",
        full_name="L5.5 Endpoint Tester",
        role=role,
    )
    await db.flush()
    case = Case(
        loan_id=f"L55E{int(datetime.now(UTC).timestamp() * 1000) % 10_000_000}",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key=f"l55e/{user.id}/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()
    return case.id, user


async def _login(client, email: str, password: str = "Pass123!") -> str:
    res = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


async def test_trigger_l55_endpoint_dispatches_and_persists(client, db):
    """POST to L5.5 endpoint creates a VerificationResult row.
    On a case with no dedupe + no TVR artefacts, expect BLOCKED with
    2 critical issues persisted."""
    case_id, user = await _seed_case_for_l55(db)
    await db.commit()

    token = await _login(client, user.email)
    res = await client.post(
        f"/cases/{case_id}/verification/L5_5_DEDUPE_TVR",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "verification_result_id" in body
    # Confirm a row landed in the DB
    vr = (await db.execute(
        select(VerificationResult).where(
            VerificationResult.case_id == case_id,
            VerificationResult.level_number == VerificationLevelNumber.L5_5_DEDUPE_TVR,
        )
    )).scalars().first()
    assert vr is not None
    assert vr.status == VerificationLevelStatus.BLOCKED
    # Earn the integration-test scope: assert the orchestrator's two
    # CRITICAL issues (dedupe_clear + tvr_present) actually committed
    # through the router boundary into the DB.
    issues = (await db.execute(
        select(LevelIssue).where(LevelIssue.verification_result_id == vr.id)
    )).scalars().all()
    assert {i.sub_step_id for i in issues} == {"dedupe_clear", "tvr_present"}


async def test_trigger_l55_endpoint_returns_400_for_unknown_level(client, db):
    """Sanity: an unknown level slug still 400s. Belt-and-braces against
    the dispatcher chain accidentally swallowing unrecognised values."""
    case_id, user = await _seed_case_for_l55(db)
    await db.commit()
    token = await _login(client, user.email)
    res = await client.post(
        f"/cases/{case_id}/verification/L9_NONSENSE",
        headers={"Authorization": f"Bearer {token}"},
    )
    # FastAPI rejects unknown enum values at validation time -> 422
    assert res.status_code in (400, 422)
