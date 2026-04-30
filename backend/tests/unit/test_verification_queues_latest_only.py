"""Tests for the MD + assessor queues: only issues from the latest VR
per ``(case, level)`` must appear. Superseded VRs (older re-runs) leave
orphaned issues in the DB — the queues must drop them automatically.

We call the endpoint functions directly with a stubbed authorization
dependency so the tests run inside the unit-test transaction fixture
(`db`) without going through HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest_asyncio

from app.api.routers.verification import assessor_queue, md_queue
from app.enums import (
    LevelIssueSeverity,
    LevelIssueStatus,
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.level_issue import LevelIssue
from app.models.user import User
from app.models.verification_result import VerificationResult
from app.services import users as users_svc


@pytest_asyncio.fixture
async def _seeded_case(db):
    user = await users_svc.create_user(
        db,
        email="queue-test@pfl.com",
        password="Pass123!",
        full_name="Queue Test",
        role=UserRole.ADMIN,
    )
    await db.flush()

    case = Case(
        loan_id="QUEUE-LATEST-001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="queue/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()
    return case, user


async def _mk_vr(db, case_id, *, level, status, created_offset_seconds: int = 0):
    vr = VerificationResult(
        case_id=case_id,
        level_number=level,
        status=status,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(vr)
    await db.flush()
    # Force a deterministic ordering — newer VR must compare greater
    # regardless of microsecond resolution.
    if created_offset_seconds:
        vr.created_at = datetime.now(UTC) + timedelta(seconds=created_offset_seconds)
        await db.flush()
    return vr


async def _mk_issue(db, vr_id, sub_step_id, *, status=LevelIssueStatus.OPEN):
    iss = LevelIssue(
        verification_result_id=vr_id,
        sub_step_id=sub_step_id,
        severity=LevelIssueSeverity.CRITICAL,
        description=f"fail: {sub_step_id}",
        status=status,
    )
    db.add(iss)
    await db.flush()
    return iss


async def test_md_queue_drops_issues_from_superseded_vr(db, _seeded_case):
    case, user = _seeded_case

    # Prior run on L1: one OPEN issue that must NOT appear — it lives on
    # the superseded VR.
    prior_vr = await _mk_vr(
        db,
        case.id,
        level=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.BLOCKED,
    )
    prior_iss = await _mk_issue(db, prior_vr.id, "stale_sub_step")

    # Latest run on L1: same or different sub_step, one OPEN issue that
    # must appear.
    latest_vr = await _mk_vr(
        db,
        case.id,
        level=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.BLOCKED,
        created_offset_seconds=10,
    )
    latest_iss = await _mk_issue(db, latest_vr.id, "live_sub_step")

    resp = await md_queue(_actor=user, session=db)
    issue_ids = {it.issue.id for it in resp.items}
    assert latest_iss.id in issue_ids
    assert prior_iss.id not in issue_ids


async def test_assessor_queue_drops_issues_from_superseded_vr(db, _seeded_case):
    case, user = _seeded_case

    prior_vr = await _mk_vr(
        db,
        case.id,
        level=VerificationLevelNumber.L2_BANKING,
        status=VerificationLevelStatus.BLOCKED,
    )
    prior_iss = await _mk_issue(db, prior_vr.id, "old_banking_rule")

    latest_vr = await _mk_vr(
        db,
        case.id,
        level=VerificationLevelNumber.L2_BANKING,
        status=VerificationLevelStatus.BLOCKED,
        created_offset_seconds=10,
    )
    latest_iss = await _mk_issue(db, latest_vr.id, "new_banking_rule")

    resp = await assessor_queue(_actor=user, session=db)
    issue_ids = {it.issue.id for it in resp.items}
    assert latest_iss.id in issue_ids
    assert prior_iss.id not in issue_ids


async def test_md_queue_scopes_latest_per_level(db, _seeded_case):
    """L1 has been re-run (latest), L2 ran only once. Both latest VRs'
    issues must show."""
    case, user = _seeded_case

    l1_prior = await _mk_vr(
        db, case.id,
        level=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.BLOCKED,
    )
    await _mk_issue(db, l1_prior.id, "stale_l1_sub_step")
    l1_latest = await _mk_vr(
        db, case.id,
        level=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.BLOCKED,
        created_offset_seconds=20,
    )
    l1_live = await _mk_issue(db, l1_latest.id, "live_l1_sub_step")

    l2_vr = await _mk_vr(
        db, case.id,
        level=VerificationLevelNumber.L2_BANKING,
        status=VerificationLevelStatus.BLOCKED,
    )
    l2_live = await _mk_issue(db, l2_vr.id, "live_l2_sub_step")

    resp = await md_queue(_actor=user, session=db)
    issue_ids = {it.issue.id for it in resp.items}
    # Both latest-per-level issues are present
    assert l1_live.id in issue_ids
    assert l2_live.id in issue_ids
    # The superseded L1 issue is hidden
    assert all(it.issue.sub_step_id != "stale_l1_sub_step" for it in resp.items)
