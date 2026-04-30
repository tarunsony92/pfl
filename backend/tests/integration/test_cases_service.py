"""Case service tests — business logic for case lifecycle."""

import json
from datetime import UTC, datetime

import pytest

from app.enums import ArtifactType, CaseStage, UserRole
from app.models.case import Case
from app.services import cases as case_svc
from app.services import users as users_svc


async def _make_user(db, email="u@pfl.com", role=UserRole.AI_ANALYSER):
    user = await users_svc.create_user(
        db,
        email=email,
        password="Pass123!",
        full_name="U",
        role=role,
    )
    await db.flush()
    return user


# ---------------- initiate ----------------


async def test_initiate_creates_case_row(db, storage_svc):
    user = await _make_user(db)
    result = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="LOAN000001",
        applicant_name="Alice",
    )
    assert result.case.loan_id == "LOAN000001"
    assert result.case.uploaded_by == user.id
    assert result.case.current_stage == CaseStage.UPLOADED
    assert result.upload_url
    assert "policy" in result.upload_fields


async def test_request_deletion_marks_case_with_request_metadata(db, storage_svc):
    """Any logged-in user can request a case be deleted; the case is NOT
    actually deleted until an MD-role user approves."""
    user = await _make_user(db, role=UserRole.AI_ANALYSER)
    result = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="DEL001",
        applicant_name="Bob",
    )
    case = result.case

    updated = await case_svc.request_deletion(
        db,
        actor=user,
        case_id=case.id,
        reason="Duplicate upload — cancelled by branch",
    )
    assert updated.is_deleted is False  # still soft-not-deleted
    assert updated.deletion_requested_by == user.id
    assert updated.deletion_requested_at is not None
    assert updated.deletion_reason == "Duplicate upload — cancelled by branch"


async def test_request_deletion_blocked_when_already_pending(db, storage_svc):
    """Re-requesting on a case that already has a pending request raises;
    ops must approve / reject the existing request first."""
    user = await _make_user(db, role=UserRole.AI_ANALYSER)
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=user, loan_id="DEL002", applicant_name="C"
    )
    await case_svc.request_deletion(
        db, actor=user, case_id=result.case.id, reason="r1"
    )
    with pytest.raises(ValueError, match="already pending"):
        await case_svc.request_deletion(
            db, actor=user, case_id=result.case.id, reason="r2"
        )


async def test_approve_deletion_requires_md_role(db, storage_svc):
    """A non-MD role attempting to approve raises PermissionError; the
    case stays un-deleted with the request metadata intact."""
    requester = await _make_user(db, role=UserRole.AI_ANALYSER)
    underwriter = await _make_user(db, role=UserRole.UNDERWRITER, email="uw@x.com")
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=requester, loan_id="DEL003", applicant_name="D"
    )
    await case_svc.request_deletion(
        db, actor=requester, case_id=result.case.id, reason="r"
    )

    with pytest.raises(PermissionError, match="MD"):
        await case_svc.approve_deletion(
            db, md_actor=underwriter, case_id=result.case.id
        )

    refetched = await db.get(Case, result.case.id)
    assert refetched is not None
    assert refetched.is_deleted is False  # still not deleted
    assert refetched.deletion_requested_by == requester.id  # request preserved


async def test_approve_deletion_by_md_actually_deletes(db, storage_svc):
    """An MD-role user (CEO or ADMIN) approving the request flips the
    case to is_deleted=True and stamps deleted_by with the MD's id."""
    requester = await _make_user(db, role=UserRole.AI_ANALYSER)
    md = await _make_user(db, role=UserRole.CEO, email="ceo@x.com")
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=requester, loan_id="DEL004", applicant_name="E"
    )
    await case_svc.request_deletion(
        db, actor=requester, case_id=result.case.id, reason="dup"
    )
    deleted = await case_svc.approve_deletion(
        db, md_actor=md, case_id=result.case.id
    )
    assert deleted.is_deleted is True
    assert deleted.deleted_by == md.id
    assert deleted.deleted_at is not None


async def test_approve_deletion_without_request_raises(db, storage_svc):
    """MD cannot pre-emptively approve — there must be a pending request."""
    md = await _make_user(db, role=UserRole.CEO, email="ceo2@x.com")
    requester = await _make_user(db, role=UserRole.AI_ANALYSER, email="r2@x.com")
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=requester, loan_id="DEL005", applicant_name="F"
    )
    with pytest.raises(ValueError, match="no pending"):
        await case_svc.approve_deletion(
            db, md_actor=md, case_id=result.case.id
        )


async def test_reject_deletion_clears_request_keeps_case(db, storage_svc):
    """MD rejecting the request clears the pending fields without deleting."""
    requester = await _make_user(db, role=UserRole.AI_ANALYSER, email="r3@x.com")
    md = await _make_user(db, role=UserRole.CEO, email="ceo3@x.com")
    result = await case_svc.initiate(
        db, storage=storage_svc, actor=requester, loan_id="DEL006", applicant_name="G"
    )
    await case_svc.request_deletion(
        db, actor=requester, case_id=result.case.id, reason="oops"
    )
    rejected = await case_svc.reject_deletion(
        db,
        md_actor=md,
        case_id=result.case.id,
        rationale="Case has been disbursed — cannot delete",
    )
    assert rejected.is_deleted is False
    assert rejected.deletion_requested_by is None
    assert rejected.deletion_requested_at is None
    assert rejected.deletion_reason is None


async def test_initiate_persists_occupation(db, storage_svc):
    """The wizard captures applicant occupation so the L1 commute judge has
    a richer profile to reason over (spec §7). Plumbed end-to-end through
    initiate()."""
    user = await _make_user(db)
    result = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="OCC001",
        applicant_name="Alice",
        occupation="wholesale grain dealer",
    )
    assert result.case.occupation == "wholesale grain dealer"


async def test_initiate_duplicate_loan_id_raises(db, storage_svc):
    user = await _make_user(db)
    await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="DUP001",
        applicant_name=None,
    )
    await db.flush()
    with pytest.raises(ValueError, match="already exists"):
        await case_svc.initiate(
            db,
            storage=storage_svc,
            actor=user,
            loan_id="DUP001",
            applicant_name=None,
        )


# ---------------- finalize ----------------


async def test_finalize_transitions_stage_and_enqueues(db, storage_svc, queue_svc):
    user = await _make_user(db)
    result = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="FIN001",
        applicant_name="F",
    )
    await storage_svc.upload_object(result.case.zip_s3_key, b"zipbytes")

    case = await case_svc.finalize(
        db,
        storage=storage_svc,
        queue=queue_svc,
        actor=user,
        case_id=result.case.id,
    )
    assert case.current_stage == CaseStage.CHECKLIST_VALIDATION
    assert case.zip_size_bytes == 8
    msgs = await queue_svc.peek_messages()
    assert len(msgs) == 1


async def test_finalize_without_upload_raises(db, storage_svc, queue_svc):
    user = await _make_user(db)
    result = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="FIN002",
        applicant_name=None,
    )
    with pytest.raises(ValueError, match="not found"):
        await case_svc.finalize(
            db,
            storage=storage_svc,
            queue=queue_svc,
            actor=user,
            case_id=result.case.id,
        )


async def test_finalize_enforces_ownership_for_ai_analyser(db, storage_svc, queue_svc):
    owner = await _make_user(db, email="owner@pfl.com", role=UserRole.AI_ANALYSER)
    stranger = await _make_user(db, email="stranger@pfl.com", role=UserRole.AI_ANALYSER)
    result = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=owner,
        loan_id="FIN003",
        applicant_name=None,
    )
    await storage_svc.upload_object(result.case.zip_s3_key, b"x")
    with pytest.raises(PermissionError):
        await case_svc.finalize(
            db,
            storage=storage_svc,
            queue=queue_svc,
            actor=stranger,
            case_id=result.case.id,
        )


async def test_finalize_admin_bypasses_ownership(db, storage_svc, queue_svc):
    owner = await _make_user(db, email="owner@pfl.com", role=UserRole.AI_ANALYSER)
    admin = await _make_user(db, email="admin@pfl.com", role=UserRole.ADMIN)
    result = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=owner,
        loan_id="FIN004",
        applicant_name=None,
    )
    await storage_svc.upload_object(result.case.zip_s3_key, b"x")
    case = await case_svc.finalize(
        db,
        storage=storage_svc,
        queue=queue_svc,
        actor=admin,
        case_id=result.case.id,
    )
    assert case.current_stage == CaseStage.CHECKLIST_VALIDATION


# ---------------- re-upload flow ----------------


async def test_approve_reupload_sets_window(db):
    admin = await _make_user(db, email="admin@pfl.com", role=UserRole.ADMIN)
    other = await _make_user(db, email="other@pfl.com")
    from datetime import UTC, datetime

    from app.models.case import Case

    case = Case(
        loan_id="RE001",
        uploaded_by=other.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="x",
    )
    db.add(case)
    await db.flush()

    await case_svc.approve_reupload(
        db,
        actor=admin,
        case_id=case.id,
        reason="underwriter error in original CAM",
    )
    assert case.reupload_allowed_until is not None


async def test_reupload_archives_previous_state(db, storage_svc):
    owner = await _make_user(db, email="o@pfl.com", role=UserRole.AI_ANALYSER)
    admin = await _make_user(db, email="a@pfl.com", role=UserRole.ADMIN)

    r1 = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=owner,
        loan_id="RE002",
        applicant_name="First",
    )
    await storage_svc.upload_object(r1.case.zip_s3_key, b"first-zip")
    await db.flush()

    await case_svc.approve_reupload(
        db,
        actor=admin,
        case_id=r1.case.id,
        reason="bad CAM, re-doing",
    )

    r2 = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=owner,
        loan_id="RE002",
        applicant_name="First",
    )
    assert r2.reupload is True
    assert r2.case.reupload_count == 1

    archive_key = f"cases/{r2.case.id}/archives/_archive_v1.json"
    assert await storage_svc.object_exists(archive_key)

    # Old ZIP should have been retired
    old_zip_still_there = await storage_svc.object_exists(r1.case.zip_s3_key)
    assert old_zip_still_there is False
    assert await storage_svc.object_exists(r1.case.zip_s3_key + ".archived_v1")


# ---------------- list ----------------


async def test_list_filters_by_stage(db, storage_svc):
    user = await _make_user(db)
    for i in range(3):
        await case_svc.initiate(
            db,
            storage=storage_svc,
            actor=user,
            loan_id=f"LIST{i:03d}",
            applicant_name=None,
        )
    await db.flush()
    page = await case_svc.list_cases(db, stage=CaseStage.UPLOADED, limit=50, offset=0)
    assert page.total >= 3
    assert all(c.current_stage == CaseStage.UPLOADED for c in page.cases)


async def test_list_excludes_deleted_by_default(db, storage_svc):
    user = await _make_user(db)
    r = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="DEL001",
        applicant_name=None,
    )
    r.case.is_deleted = True
    await db.flush()
    page = await case_svc.list_cases(db, limit=50, offset=0, include_deleted=False)
    assert all(c.id != r.case.id for c in page.cases)


# ---------------- soft delete ----------------


async def test_soft_delete_marks_case(db, storage_svc):
    user = await _make_user(db, role=UserRole.ADMIN)
    r = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="SD001",
        applicant_name=None,
    )
    await case_svc.soft_delete(db, actor=user, case_id=r.case.id)
    assert r.case.is_deleted is True
    assert r.case.deleted_by == user.id


async def test_finalize_already_validated_raises_invalid_transition(db, storage_svc, queue_svc):
    """C1 regression: finalize twice raises InvalidStateTransition, not 500."""
    from app.core.exceptions import InvalidStateTransition

    user = await _make_user(db, email="dup@pfl.com")
    r = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="DUPFIN-001",
        applicant_name=None,
    )
    await storage_svc.upload_object(r.case.zip_s3_key, b"x")
    await case_svc.finalize(
        db,
        storage=storage_svc,
        queue=queue_svc,
        actor=user,
        case_id=r.case.id,
    )
    # Second finalize should raise InvalidStateTransition
    with pytest.raises(InvalidStateTransition):
        await case_svc.finalize(
            db,
            storage=storage_svc,
            queue=queue_svc,
            actor=user,
            case_id=r.case.id,
        )


async def test_initiate_after_soft_delete_allows_new_case_same_loan_id(db, storage_svc):
    """C2 regression: soft-deleted loan_id can be re-filed."""
    admin = await _make_user(db, email="admin@pfl.com", role=UserRole.ADMIN)

    r1 = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=admin,
        loan_id="REFILE-001",
        applicant_name="First",
    )
    await db.flush()
    await case_svc.soft_delete(db, actor=admin, case_id=r1.case.id)
    await db.flush()

    # Same loan_id should be allowed now
    r2 = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=admin,
        loan_id="REFILE-001",
        applicant_name="Second",
    )
    assert r2.case.id != r1.case.id
    assert r2.case.loan_id == "REFILE-001"


# ----------- M3 T12: add_artifact re-trigger ingestion -----------


async def test_add_artifact_from_missing_docs_retriggers_pipeline(db, storage_svc, queue_svc):
    """M3 T12: artifact in CHECKLIST_MISSING_DOCS triggers re-validation."""
    user = await _make_user(db, email="art@pfl.com")

    # Create a case directly in CHECKLIST_MISSING_DOCS state
    case = Case(
        loan_id="ART001",
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
        zip_s3_key="cases/art001/original.zip",
        current_stage=CaseStage.CHECKLIST_MISSING_DOCS,
    )
    db.add(case)
    await db.flush()

    # Now add an artifact
    await case_svc.add_artifact(
        db,
        storage=storage_svc,
        queue=queue_svc,
        actor=user,
        case_id=case.id,
        filename="missing_doc.pdf",
        content=b"pdf content",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
    )

    # Assert: case transitioned back to CHECKLIST_VALIDATION
    case = await db.get(Case, case.id)
    assert case.current_stage == CaseStage.CHECKLIST_VALIDATION

    # Assert: queue has the re-trigger message
    msgs = await queue_svc.peek_messages()
    assert len(msgs) >= 1
    bodies = [json.loads(msg["Body"]) for msg in msgs]
    trigger_msgs = [b for b in bodies if b.get("trigger") == "artifact_added"]
    assert len(trigger_msgs) >= 1
    assert trigger_msgs[0]["case_id"] == str(case.id)


async def test_add_artifact_from_non_missing_state_does_not_retrigger(db, storage_svc, queue_svc):
    """M3 T12: artifact in UPLOADED state does not re-trigger."""
    user = await _make_user(db, email="art2@pfl.com")

    # Create a case in UPLOADED state
    r = await case_svc.initiate(
        db,
        storage=storage_svc,
        actor=user,
        loan_id="ART002",
        applicant_name="Test",
    )
    await db.flush()
    assert r.case.current_stage == CaseStage.UPLOADED

    # Add an artifact while in UPLOADED
    await case_svc.add_artifact(
        db,
        storage=storage_svc,
        queue=queue_svc,
        actor=user,
        case_id=r.case.id,
        filename="early_doc.pdf",
        content=b"pdf content",
        artifact_type=ArtifactType.ADDITIONAL_FILE,
    )

    # Assert: stage unchanged
    case = await db.get(Case, r.case.id)
    assert case.current_stage == CaseStage.UPLOADED

    # Assert: no new queue messages (no re-trigger)
    msgs = await queue_svc.peek_messages()
    assert len(msgs) == 0
