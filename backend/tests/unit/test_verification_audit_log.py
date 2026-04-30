"""Tests for the audit trail on ``resolve_issue`` and ``decide_issue``.

Every MD decision and assessor resolution must write an ``AuditLog``
row with enough before/after context to reconstruct the change during a
compliance audit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import select

from app.api.routers.verification import decide_issue, resolve_issue
from app.enums import (
    LevelIssueSeverity,
    LevelIssueStatus,
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.audit_log import AuditLog
from app.models.case import Case
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult
from app.schemas.verification import IssueDecideRequest, IssueResolveRequest
from app.services import users as users_svc


@pytest_asyncio.fixture
async def _seeded(db):
    actor = await users_svc.create_user(
        db,
        email="m4-actor@pfl.com",
        password="Pass123!",
        full_name="M4 Actor",
        role=UserRole.ADMIN,
    )
    await db.flush()
    case = Case(
        loan_id="M4-AUDIT-001",
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="m4/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()
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
        sub_step_id="rule_for_audit",
        severity=LevelIssueSeverity.CRITICAL,
        description="audit-trail test",
        status=LevelIssueStatus.OPEN,
    )
    db.add(iss)
    await db.flush()
    return case, actor, vr, iss


async def test_resolve_issue_writes_audit_log(db, _seeded):
    case, actor, vr, iss = _seeded
    await resolve_issue(
        issue_id=iss.id,
        payload=IssueResolveRequest(assessor_note="fixed by uploading new doc"),
        actor=actor,
        session=db,
    )
    rows = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "ISSUE_ASSESSOR_RESOLVED")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    entry = rows[0]
    assert entry.actor_user_id == actor.id
    assert entry.entity_type == "level_issue"
    assert entry.entity_id == str(iss.id)
    assert entry.before_json and entry.before_json.get("status") == "OPEN"
    assert entry.after_json and entry.after_json.get("status") == "ASSESSOR_RESOLVED"
    assert "fixed by uploading new doc" in (entry.after_json.get("assessor_note") or "")


async def test_decide_issue_md_approved_writes_audit_log(db, _seeded):
    case, actor, vr, iss = _seeded
    # MD decides directly on an OPEN issue (short-circuit path).
    await decide_issue(
        issue_id=iss.id,
        payload=IssueDecideRequest(
            decision=LevelIssueStatus.MD_APPROVED,
            md_rationale="small defect, acceptable",
        ),
        actor=actor,
        session=db,
    )
    rows = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "ISSUE_MD_DECIDED")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    entry = rows[0]
    assert entry.actor_user_id == actor.id
    assert entry.entity_type == "level_issue"
    assert entry.entity_id == str(iss.id)
    assert entry.before_json and entry.before_json.get("status") == "OPEN"
    assert entry.after_json and entry.after_json.get("status") == "MD_APPROVED"
    assert "small defect" in (entry.after_json.get("md_rationale") or "")
    assert entry.after_json.get("case_id") == str(case.id)


async def test_decide_issue_md_rejected_writes_audit_log(db, _seeded):
    case, actor, vr, iss = _seeded
    await decide_issue(
        issue_id=iss.id,
        payload=IssueDecideRequest(
            decision=LevelIssueStatus.MD_REJECTED,
            md_rationale="not acceptable",
        ),
        actor=actor,
        session=db,
    )
    entry = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "ISSUE_MD_DECIDED")
            )
        )
        .scalars()
        .first()
    )
    assert entry is not None
    assert entry.after_json.get("status") == "MD_REJECTED"
