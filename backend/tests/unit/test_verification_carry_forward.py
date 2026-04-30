"""Tests for ``carry_forward_prior_decisions``.

Every orchestrator creates a fresh ``VerificationResult`` + ``LevelIssue``
set on each trigger. Without carry-forward logic, any terminal MD decision
(``MD_APPROVED`` / ``MD_REJECTED``) or assessor resolution on the previous
run is silently orphaned. This test seeds a prior VR with a settled issue,
runs the helper against a new VR sharing the same ``sub_step_id``, and
asserts the new issue inherits the prior decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

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
from app.services import users as users_svc
from app.verification.levels._common import carry_forward_prior_decisions


@pytest_asyncio.fixture
async def _seeded_case(db):
    user = await users_svc.create_user(
        db,
        email="cf-test@pfl.com",
        password="Pass123!",
        full_name="CF Test",
        role=UserRole.AI_ANALYSER,
    )
    await db.flush()

    case = Case(
        loan_id="CF-BASE-001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="cf/case.zip",
        loan_amount=100_000,
    )
    db.add(case)
    await db.flush()
    return case, user


async def _mk_vr(db, case_id, level, status):
    vr = VerificationResult(
        case_id=case_id,
        level_number=level,
        status=status,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(vr)
    await db.flush()
    return vr


async def _mk_issue(db, vr_id, sub_step_id, **kwargs):
    iss = LevelIssue(
        verification_result_id=vr_id,
        sub_step_id=sub_step_id,
        severity=kwargs.pop("severity", LevelIssueSeverity.CRITICAL),
        description=kwargs.pop("description", f"fail for {sub_step_id}"),
        status=kwargs.pop("status", LevelIssueStatus.OPEN),
        **kwargs,
    )
    db.add(iss)
    await db.flush()
    return iss


async def test_no_prior_vr_is_noop(db, _seeded_case):
    case, _ = _seeded_case
    vr = await _mk_vr(
        db, case.id, VerificationLevelNumber.L1_ADDRESS, VerificationLevelStatus.PASSED
    )
    # No prior VR — helper should be a no-op.
    await carry_forward_prior_decisions(db, result=vr)
    assert vr.status == VerificationLevelStatus.PASSED


async def test_md_approved_carries_forward(db, _seeded_case):
    case, user = _seeded_case

    # Prior VR: BLOCKED, issue MD_APPROVED
    prior_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L1_ADDRESS,
        VerificationLevelStatus.BLOCKED,
    )
    reviewed_at = datetime.now(UTC)
    await _mk_issue(
        db,
        prior_vr.id,
        "aadhaar_vs_bureau_address",
        status=LevelIssueStatus.MD_APPROVED,
        md_user_id=user.id,
        md_reviewed_at=reviewed_at,
        md_rationale="MD approved — small spelling difference only.",
    )

    # New VR: fresh BLOCKED with the same sub_step_id
    new_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L1_ADDRESS,
        VerificationLevelStatus.BLOCKED,
    )
    new_iss = await _mk_issue(
        db,
        new_vr.id,
        "aadhaar_vs_bureau_address",
        status=LevelIssueStatus.OPEN,
    )

    await carry_forward_prior_decisions(db, result=new_vr)
    await db.refresh(new_iss)
    await db.refresh(new_vr)

    assert new_iss.status == LevelIssueStatus.MD_APPROVED
    assert new_iss.md_user_id == user.id
    assert new_iss.md_rationale and "spelling difference" in new_iss.md_rationale
    # Because the only issue carries forward as MD_APPROVED, the level
    # must be promoted to PASSED_WITH_MD_OVERRIDE.
    assert new_vr.status == VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE


async def test_md_rejected_carries_forward_and_blocks_level(db, _seeded_case):
    case, user = _seeded_case
    prior_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L2_BANKING,
        VerificationLevelStatus.BLOCKED,
    )
    await _mk_issue(
        db,
        prior_vr.id,
        "nach_bounces",
        status=LevelIssueStatus.MD_REJECTED,
        md_user_id=user.id,
        md_reviewed_at=datetime.now(UTC),
        md_rationale="NACH bounces material; not overridable.",
    )

    new_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L2_BANKING,
        VerificationLevelStatus.BLOCKED,
    )
    new_iss = await _mk_issue(
        db,
        new_vr.id,
        "nach_bounces",
        status=LevelIssueStatus.OPEN,
    )

    await carry_forward_prior_decisions(db, result=new_vr)
    await db.refresh(new_iss)
    await db.refresh(new_vr)
    assert new_iss.status == LevelIssueStatus.MD_REJECTED
    # Rejected CRITICAL → level stays BLOCKED.
    assert new_vr.status == VerificationLevelStatus.BLOCKED


async def test_assessor_resolved_carries_forward(db, _seeded_case):
    case, user = _seeded_case
    prior_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L3_VISION,
        VerificationLevelStatus.BLOCKED,
    )
    await _mk_issue(
        db,
        prior_vr.id,
        "house_rating_low",
        status=LevelIssueStatus.ASSESSOR_RESOLVED,
        assessor_user_id=user.id,
        assessor_resolved_at=datetime.now(UTC),
        assessor_note="Re-visit scheduled; provisional sign-off.",
    )

    new_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L3_VISION,
        VerificationLevelStatus.BLOCKED,
    )
    new_iss = await _mk_issue(db, new_vr.id, "house_rating_low")

    await carry_forward_prior_decisions(db, result=new_vr)
    await db.refresh(new_iss)
    await db.refresh(new_vr)
    assert new_iss.status == LevelIssueStatus.ASSESSOR_RESOLVED
    assert new_iss.assessor_note and "Re-visit" in new_iss.assessor_note
    # Only ASSESSOR_RESOLVED (not MD decided) — level must stay BLOCKED
    # until the MD signs off.
    assert new_vr.status == VerificationLevelStatus.BLOCKED


async def test_mismatched_sub_step_does_not_leak(db, _seeded_case):
    case, user = _seeded_case
    prior_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L1_ADDRESS,
        VerificationLevelStatus.BLOCKED,
    )
    await _mk_issue(
        db,
        prior_vr.id,
        "old_sub_step_no_longer_emitted",
        status=LevelIssueStatus.MD_APPROVED,
        md_user_id=user.id,
        md_reviewed_at=datetime.now(UTC),
        md_rationale="OK",
    )
    new_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L1_ADDRESS,
        VerificationLevelStatus.BLOCKED,
    )
    new_iss = await _mk_issue(db, new_vr.id, "different_sub_step")

    await carry_forward_prior_decisions(db, result=new_vr)
    await db.refresh(new_iss)
    # No prior record for this sub_step → stays OPEN.
    assert new_iss.status == LevelIssueStatus.OPEN


async def test_partial_approval_keeps_level_blocked(db, _seeded_case):
    case, user = _seeded_case
    prior_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L2_BANKING,
        VerificationLevelStatus.BLOCKED,
    )
    # Issue A: prior MD_APPROVED
    await _mk_issue(
        db,
        prior_vr.id,
        "rule_a",
        status=LevelIssueStatus.MD_APPROVED,
        md_user_id=user.id,
        md_reviewed_at=datetime.now(UTC),
        md_rationale="ok",
    )
    new_vr = await _mk_vr(
        db,
        case.id,
        VerificationLevelNumber.L2_BANKING,
        VerificationLevelStatus.BLOCKED,
    )
    await _mk_issue(db, new_vr.id, "rule_a")
    # Issue B: brand new, no prior — stays unsettled CRITICAL.
    await _mk_issue(db, new_vr.id, "rule_b_new")

    await carry_forward_prior_decisions(db, result=new_vr)
    await db.refresh(new_vr)
    # One critical still unsettled → no promotion.
    assert new_vr.status == VerificationLevelStatus.BLOCKED
