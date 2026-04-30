"""Non-regression test for ``decide_issue``.

The defensive ``SELECT ... FOR UPDATE`` on the ``VerificationResult``
serialises concurrent MD decisions on sibling issues. We can't easily
write a deterministic race test from inside pytest, but we can at least
verify the single-actor happy path still behaves correctly under the
new lock-read code path: one MD decides the last outstanding issue →
level promotes to ``PASSED_WITH_MD_OVERRIDE``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio

from app.api.routers.verification import decide_issue
from app.enums import (
    LevelIssueSeverity,
    LevelIssueStatus,
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.schemas.verification import IssueDecideRequest
from app.services import users as users_svc


@pytest_asyncio.fixture
async def _seeded_case(db):
    actor = await users_svc.create_user(
        db,
        email="m2-actor@pfl.com",
        password="Pass123!",
        full_name="M2 MD",
        role=UserRole.ADMIN,
    )
    await db.flush()
    case = Case(
        loan_id="M2-TOCTOU-001",
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="m2/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()
    return case, actor


async def test_decide_issue_promotes_level_when_all_settled(db, _seeded_case):
    case, actor = _seeded_case
    vr = VerificationResult(
        case_id=case.id,
        level_number=VerificationLevelNumber.L1_ADDRESS,
        status=VerificationLevelStatus.BLOCKED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(vr)
    await db.flush()

    iss = LevelIssue(
        verification_result_id=vr.id,
        sub_step_id="lonely_rule",
        severity=LevelIssueSeverity.CRITICAL,
        description="sole blocker",
        status=LevelIssueStatus.ASSESSOR_RESOLVED,
        assessor_user_id=actor.id,
        assessor_resolved_at=datetime.now(UTC),
        assessor_note="fixed",
    )
    db.add(iss)
    await db.flush()

    payload = IssueDecideRequest(
        decision=LevelIssueStatus.MD_APPROVED,
        md_rationale="approved after review",
    )
    result = await decide_issue(
        issue_id=iss.id,
        payload=payload,
        actor=actor,
        session=db,
    )
    assert result.status == LevelIssueStatus.MD_APPROVED

    await db.refresh(vr)
    assert vr.status == VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE


async def test_decide_issue_keeps_level_blocked_when_sibling_unsettled(db, _seeded_case):
    case, actor = _seeded_case
    vr = VerificationResult(
        case_id=case.id,
        level_number=VerificationLevelNumber.L2_BANKING,
        status=VerificationLevelStatus.BLOCKED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(vr)
    await db.flush()

    iss_a = LevelIssue(
        verification_result_id=vr.id,
        sub_step_id="rule_a",
        severity=LevelIssueSeverity.CRITICAL,
        description="a",
        status=LevelIssueStatus.ASSESSOR_RESOLVED,
    )
    iss_b = LevelIssue(
        verification_result_id=vr.id,
        sub_step_id="rule_b",
        severity=LevelIssueSeverity.CRITICAL,
        description="b",
        status=LevelIssueStatus.OPEN,
    )
    db.add_all([iss_a, iss_b])
    await db.flush()

    payload = IssueDecideRequest(
        decision=LevelIssueStatus.MD_APPROVED,
        md_rationale="ok for rule_a",
    )
    await decide_issue(
        issue_id=iss_a.id,
        payload=payload,
        actor=actor,
        session=db,
    )
    await db.refresh(vr)
    # rule_b still OPEN → level must stay BLOCKED.
    assert vr.status == VerificationLevelStatus.BLOCKED
