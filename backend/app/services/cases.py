"""Case business logic: initiate, finalize, list, re-upload, delete.

All functions are pure async, take session + services as args; no HTTP concerns.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import ArtifactType, CaseStage, UserRole
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.user import User
from app.services import audit as audit_svc
from app.services import stages as stages_svc
from app.services.queue import QueueService
from app.services.storage import StorageService


@dataclass
class InitiateResult:
    case: Case
    upload_url: str
    upload_fields: dict[str, str]
    upload_key: str
    expires_at: datetime
    reupload: bool


@dataclass
class CaseListPage:
    cases: list[Case]
    total: int


def _original_zip_key(case_id: UUID) -> str:
    return f"cases/{case_id}/original.zip"


def _archive_json_key(case_id: UUID, version: int) -> str:
    return f"cases/{case_id}/archives/_archive_v{version}.json"


async def _archive_existing_state(
    session: AsyncSession,
    storage: StorageService,
    case: Case,
    *,
    reupload_by: User,
    approving_admin_id: UUID | None,
    approval_reason: str | None,
) -> None:
    """Copy prior ZIP aside, mutate old ORIGINAL_ZIP artifact, write archive JSON.

    NOTE (M2 simplification): `approving_admin_id` and `approval_reason` are passed
    as None by the M2 `initiate` caller because the admin identity/reason are only
    captured transiently on the Case row (via `approve_reupload` → audit log entry)
    and not carried forward to this function in M2. The archive JSON therefore has
    null values for `reupload_approved_by` and `reupload_approval_reason`. M3+ will
    plumb these through (join the audit log entry for `case.reupload_approved` to
    enrich the archive payload). The archive format is versioned so this enrichment
    is non-breaking.
    """
    version = case.reupload_count + 1

    old_key = case.zip_s3_key
    archived_key = f"{old_key}.archived_v{version}"
    if await storage.object_exists(old_key):
        await storage.copy_object(old_key, archived_key)
        await storage.delete_object(old_key)

    # Retire the existing ORIGINAL_ZIP artifact row, if any
    result = await session.execute(
        select(CaseArtifact).where(
            and_(
                CaseArtifact.case_id == case.id,
                CaseArtifact.artifact_type == ArtifactType.ORIGINAL_ZIP,
            )
        )
    )
    old_artifact = result.scalar_one_or_none()
    if old_artifact is not None:
        before = {
            "s3_key": old_artifact.s3_key,
            "artifact_type": old_artifact.artifact_type.value,
        }
        old_artifact.s3_key = archived_key
        old_artifact.artifact_type = ArtifactType.REUPLOAD_ARCHIVE
        await audit_svc.log_action(
            session,
            actor_user_id=reupload_by.id,
            action="case.artifact_retired",
            entity_type="case",
            entity_id=str(case.id),
            before=before,
            after={"s3_key": archived_key, "artifact_type": ArtifactType.REUPLOAD_ARCHIVE.value},
        )

    archive_payload = {
        "archive_version": version,
        "archived_at": datetime.now(UTC).isoformat(),
        "archived_by": str(reupload_by.id),
        "reupload_approved_by": str(approving_admin_id) if approving_admin_id else None,
        "reupload_approval_reason": approval_reason,
        # Note: M2 does not store the admin's approval timestamp separately;
        # only the 24h window expiry is persisted. M7+ may add a proper
        # `reupload_approved_at` column to the Case model.
        "reupload_allowed_until": case.reupload_allowed_until.isoformat()
        if case.reupload_allowed_until
        else None,
        "previous_state": {
            "zip_s3_key": archived_key,
            "stage_at_archive": case.current_stage.value,
            "applicant_name": case.applicant_name,
            "uploaded_by": str(case.uploaded_by),
            "uploaded_at": case.uploaded_at.isoformat(),
            "finalized_at": case.finalized_at.isoformat() if case.finalized_at else None,
            "notes_and_feedback": [],  # populated in M7
        },
    }
    archive_key = _archive_json_key(case.id, version)
    await storage.upload_object(
        archive_key,
        json.dumps(archive_payload, indent=2).encode("utf-8"),
        content_type="application/json",
    )

    archive_artifact = CaseArtifact(
        case_id=case.id,
        filename=f"_archive_v{version}.json",
        artifact_type=ArtifactType.REUPLOAD_ARCHIVE,
        s3_key=archive_key,
        uploaded_by=reupload_by.id,
        uploaded_at=datetime.now(UTC),
        content_type="application/json",
    )
    session.add(archive_artifact)

    case.reupload_count = version
    case.reupload_allowed_until = None
    case.current_stage = CaseStage.UPLOADED
    case.finalized_at = None
    case.zip_size_bytes = None
    case.uploaded_by = reupload_by.id
    case.uploaded_at = datetime.now(UTC)

    await audit_svc.log_action(
        session,
        actor_user_id=reupload_by.id,
        action="case.reuploaded",
        entity_type="case",
        entity_id=str(case.id),
        after={"archive_version": version},
    )


async def initiate(
    session: AsyncSession,
    *,
    storage: StorageService,
    actor: User,
    loan_id: str,
    applicant_name: str | None,
    loan_amount: int | None = None,
    loan_tenure_months: int | None = None,
    co_applicant_name: str | None = None,
    occupation: str | None = None,
) -> InitiateResult:
    """Initiate (or re-upload) a case and return a presigned upload URL."""
    settings = get_settings()

    existing_result = await session.execute(
        select(Case).where(and_(Case.loan_id == loan_id, Case.is_deleted.is_(False)))
    )
    existing = existing_result.scalar_one_or_none()

    reupload = False
    if existing is not None:
        now = datetime.now(UTC)
        if existing.reupload_allowed_until is None or existing.reupload_allowed_until < now:
            raise ValueError(f"Case with loan_id '{loan_id}' already exists")
        await _archive_existing_state(
            session,
            storage,
            existing,
            reupload_by=actor,
            approving_admin_id=None,
            approval_reason=None,
        )
        case = existing
        reupload = True
        case.zip_s3_key = _original_zip_key(case.id)
        case.applicant_name = applicant_name
        if loan_amount is not None:
            case.loan_amount = loan_amount
        if loan_tenure_months is not None:
            case.loan_tenure_months = loan_tenure_months
        if co_applicant_name is not None:
            case.co_applicant_name = co_applicant_name
        if occupation is not None:
            case.occupation = occupation
    else:
        case = Case(
            loan_id=loan_id,
            uploaded_by=actor.id,
            uploaded_at=datetime.now(UTC),
            zip_s3_key="pending",
            current_stage=CaseStage.UPLOADED,
            applicant_name=applicant_name,
            loan_amount=loan_amount,
            loan_tenure_months=loan_tenure_months,
            co_applicant_name=co_applicant_name,
            occupation=occupation,
        )
        session.add(case)
        try:
            await session.flush()
        except IntegrityError as e:
            await session.rollback()
            raise ValueError(f"Case with loan_id '{loan_id}' already exists") from e
        case.zip_s3_key = _original_zip_key(case.id)

    presigned = await storage.generate_presigned_upload_url(
        case.zip_s3_key,
        expires_in=settings.presigned_url_expires_seconds,
        max_size_bytes=settings.max_zip_size_bytes,
        content_type="application/zip",
    )

    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.initiated",
        entity_type="case",
        entity_id=str(case.id),
        after={"loan_id": loan_id, "case_id": str(case.id), "reupload": reupload},
    )

    return InitiateResult(
        case=case,
        upload_url=cast(str, presigned["url"]),
        upload_fields=cast("dict[str, str]", presigned["fields"]),
        upload_key=cast(str, presigned["key"]),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.presigned_url_expires_seconds),
        reupload=reupload,
    )


async def finalize(
    session: AsyncSession,
    *,
    storage: StorageService,
    queue: QueueService,
    actor: User,
    case_id: UUID,
) -> tuple[Case, dict[str, Any]]:
    """Finalize the case: stamp finalized_at, transition to CHECKLIST_VALIDATION,
    log the audit entry. Returns ``(case, ingestion_payload)`` — the caller is
    responsible for publishing the payload to the ingestion queue *after* the
    transaction commits, otherwise the worker can race the commit and read a
    pre-transition snapshot."""
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise ValueError(f"Case {case_id} not found")

    if actor.role == UserRole.AI_ANALYSER and case.uploaded_by != actor.id:
        raise PermissionError("Only the uploader or an admin can finalize this case")

    if case.current_stage != CaseStage.UPLOADED:
        from app.core.exceptions import InvalidStateTransition

        raise InvalidStateTransition(
            f"Case {case_id} is in stage {case.current_stage.value}, expected UPLOADED"
        )

    if not await storage.object_exists(case.zip_s3_key):
        raise ValueError(f"Upload not found at {case.zip_s3_key}")
    meta = await storage.get_object_metadata(case.zip_s3_key)
    case.zip_size_bytes = cast("int | None", meta["size_bytes"]) if meta else None
    case.finalized_at = datetime.now(UTC)

    artifact = CaseArtifact(
        case_id=case.id,
        filename="original.zip",
        artifact_type=ArtifactType.ORIGINAL_ZIP,
        s3_key=case.zip_s3_key,
        size_bytes=case.zip_size_bytes,
        content_type="application/zip",
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
    )
    session.add(artifact)

    await stages_svc.transition_stage(
        session,
        case=case,
        to=CaseStage.CHECKLIST_VALIDATION,
        actor_user_id=actor.id,
    )

    # Build the ingestion payload here but DO NOT publish — the route handler
    # publishes after `session.commit()` so the worker can never read an
    # uncommitted UPLOADED snapshot when it pulls the SQS message.
    ingestion_payload: dict[str, Any] = {
        "case_id": str(case.id),
        "loan_id": case.loan_id,
        "zip_s3_key": case.zip_s3_key,
    }
    _ = queue  # kept in signature for symmetry; publish happens post-commit

    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.finalized",
        entity_type="case",
        entity_id=str(case.id),
        after={"case_id": str(case.id), "zip_size_bytes": case.zip_size_bytes},
    )

    return case, ingestion_payload


async def approve_reupload(
    session: AsyncSession,
    *,
    actor: User,
    case_id: UUID,
    reason: str,
) -> Case:
    if actor.role != UserRole.ADMIN:
        raise PermissionError("Only admin can approve reuploads")
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise ValueError(f"Case {case_id} not found")
    now = datetime.now(UTC)
    case.reupload_allowed_until = now + timedelta(hours=24)
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.reupload_approved",
        entity_type="case",
        entity_id=str(case.id),
        after={"reason": reason, "valid_until": case.reupload_allowed_until.isoformat()},
    )
    return case


async def soft_delete(
    session: AsyncSession,
    *,
    actor: User,
    case_id: UUID,
) -> Case:
    if actor.role != UserRole.ADMIN:
        raise PermissionError("Only admin can delete cases")
    case = await session.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")
    case.is_deleted = True
    case.deleted_at = datetime.now(UTC)
    case.deleted_by = actor.id
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.soft_deleted",
        entity_type="case",
        entity_id=str(case.id),
    )
    return case


# ─────────────────────────── MD-approval delete flow ────────────────────────
# Any logged-in user can request a case be deleted (typical trigger: the
# branch uploaded the wrong ZIP, a duplicate file, or the applicant
# withdrew before processing). Only MD-role users (CEO + ADMIN) can
# approve the request and actually soft-delete the row. This mirrors
# the MD-approval flow already in place for verification-level CRITICALs.

# Roles treated as "MD" — keep in sync with the MD gating in
# ``verification.py`` (md_decide, get_md_queue, etc.).
_MD_ROLES: frozenset[UserRole] = frozenset({UserRole.CEO, UserRole.ADMIN})


async def request_deletion(
    session: AsyncSession,
    *,
    actor: User,
    case_id: UUID,
    reason: str,
) -> Case:
    """Mark a case as pending deletion. Does NOT actually delete — an MD
    must subsequently call ``approve_deletion`` to flip ``is_deleted``."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A deletion reason is required")

    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise ValueError(f"Case {case_id} not found")

    if case.deletion_requested_at is not None:
        raise ValueError(
            "A deletion request is already pending for this case — the MD "
            "must approve or reject it before a new request can be filed."
        )

    case.deletion_requested_at = datetime.now(UTC)
    case.deletion_requested_by = actor.id
    case.deletion_reason = reason[:500]

    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.deletion_requested",
        entity_type="case",
        entity_id=str(case.id),
        after={"reason": case.deletion_reason},
    )
    return case


async def approve_deletion(
    session: AsyncSession,
    *,
    md_actor: User,
    case_id: UUID,
) -> Case:
    """MD-only: approve a pending deletion request. Actually soft-deletes
    the case (sets ``is_deleted``, ``deleted_at``, ``deleted_by``).
    """
    if md_actor.role not in _MD_ROLES:
        raise PermissionError(
            "Only MD-level roles (CEO, ADMIN) can approve a deletion request"
        )

    case = await session.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")
    if case.is_deleted:
        raise ValueError(f"Case {case_id} is already deleted")
    if case.deletion_requested_at is None:
        raise ValueError(
            "There is no pending deletion request for this case"
        )

    case.is_deleted = True
    case.deleted_at = datetime.now(UTC)
    case.deleted_by = md_actor.id

    await audit_svc.log_action(
        session,
        actor_user_id=md_actor.id,
        action="case.deletion_approved",
        entity_type="case",
        entity_id=str(case.id),
        after={
            "deletion_reason": case.deletion_reason,
            "requested_by": str(case.deletion_requested_by)
            if case.deletion_requested_by
            else None,
        },
    )
    return case


async def reject_deletion(
    session: AsyncSession,
    *,
    md_actor: User,
    case_id: UUID,
    rationale: str,
) -> Case:
    """MD-only: reject a pending deletion request. Clears the request
    fields so the case returns to its pre-request state."""
    if md_actor.role not in _MD_ROLES:
        raise PermissionError(
            "Only MD-level roles (CEO, ADMIN) can reject a deletion request"
        )

    rationale = (rationale or "").strip()
    if not rationale:
        raise ValueError("A rejection rationale is required")

    case = await session.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")
    if case.deletion_requested_at is None:
        raise ValueError(
            "There is no pending deletion request for this case"
        )

    prior_requester = case.deletion_requested_by
    prior_reason = case.deletion_reason

    case.deletion_requested_at = None
    case.deletion_requested_by = None
    case.deletion_reason = None

    await audit_svc.log_action(
        session,
        actor_user_id=md_actor.id,
        action="case.deletion_rejected",
        entity_type="case",
        entity_id=str(case.id),
        after={
            "rejection_rationale": rationale[:500],
            "original_request_by": str(prior_requester) if prior_requester else None,
            "original_reason": prior_reason,
        },
    )
    return case


async def list_cases(
    session: AsyncSession,
    *,
    stage: CaseStage | None = None,
    uploaded_by: UUID | None = None,
    loan_id_prefix: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> CaseListPage:
    stmt = select(Case)
    count_stmt = select(func.count()).select_from(Case)
    clauses = []
    if stage is not None:
        clauses.append(Case.current_stage == stage)
    if uploaded_by is not None:
        clauses.append(Case.uploaded_by == uploaded_by)
    if loan_id_prefix:
        clauses.append(Case.loan_id.like(f"{loan_id_prefix}%"))
    if from_date:
        clauses.append(Case.uploaded_at >= from_date)
    if to_date:
        clauses.append(Case.uploaded_at <= to_date)
    if not include_deleted:
        clauses.append(Case.is_deleted.is_(False))
    if clauses:
        stmt = stmt.where(and_(*clauses))
        count_stmt = count_stmt.where(and_(*clauses))

    stmt = stmt.order_by(Case.uploaded_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(count_stmt)).scalar() or 0
    return CaseListPage(cases=list(rows), total=total)


async def get_case(
    session: AsyncSession, case_id: UUID, *, include_deleted: bool = False
) -> Case | None:
    case = await session.get(Case, case_id)
    if case is None:
        return None
    if case.is_deleted and not include_deleted:
        return None
    return case


async def list_artifacts(session: AsyncSession, case_id: UUID) -> list[CaseArtifact]:
    result = await session.execute(
        select(CaseArtifact)
        .where(CaseArtifact.case_id == case_id)
        .order_by(CaseArtifact.uploaded_at)
    )
    return list(result.scalars().all())


async def add_artifact(
    session: AsyncSession,
    *,
    storage: StorageService,
    queue: QueueService,
    actor: User,
    case_id: UUID,
    filename: str,
    content: bytes,
    artifact_type: ArtifactType = ArtifactType.ADDITIONAL_FILE,
    content_type: str | None = None,
) -> tuple[CaseArtifact, dict[str, object] | None]:
    """Upload + persist the artifact. If the case was in CHECKLIST_MISSING_DOCS
    we also transition it back to CHECKLIST_VALIDATION and return a re-ingest
    payload — caller publishes it to the queue *after* `session.commit()` so
    the worker doesn't race the transaction. Returns ``(artifact, payload|None)``."""
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise ValueError(f"Case {case_id} not found")
    if actor.role == UserRole.AI_ANALYSER and case.uploaded_by != actor.id:
        raise PermissionError("Only the uploader or an admin can add artifacts")

    artifact_id = uuid4()
    safe_filename = filename.replace("/", "_").replace("\\", "_")
    s3_key = f"cases/{case.id}/artifacts/{artifact_id}_{safe_filename}"
    await storage.upload_object(s3_key, content, content_type=content_type)

    artifact = CaseArtifact(
        id=artifact_id,
        case_id=case.id,
        filename=filename,
        artifact_type=artifact_type,
        s3_key=s3_key,
        size_bytes=len(content),
        content_type=content_type,
        uploaded_by=actor.id,
        uploaded_at=datetime.now(UTC),
    )
    session.add(artifact)
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.artifact_added",
        entity_type="case",
        entity_id=str(case.id),
        after={"artifact_id": str(artifact.id), "artifact_type": artifact_type.value},
    )

    # M3 T12: re-trigger ingestion if case is in CHECKLIST_MISSING_DOCS
    pending_payload: dict[str, object] | None = None
    if case.current_stage == CaseStage.CHECKLIST_MISSING_DOCS:
        # Transition back to CHECKLIST_VALIDATION (existing M2 transition; already allowed)
        await stages_svc.transition_stage(
            session=session,
            case=case,
            to=CaseStage.CHECKLIST_VALIDATION,
            actor_user_id=actor.id,
        )
        pending_payload = {
            "case_id": str(case.id),
            "loan_id": case.loan_id,
            "zip_s3_key": case.zip_s3_key,
            "trigger": "artifact_added",
        }
        # Audit entry
        await audit_svc.log_action(
            session=session,
            actor_user_id=actor.id,
            action="case.reingestion_triggered",
            entity_type="case",
            entity_id=str(case.id),
            after={"reason": "artifact_added"},
        )
    _ = queue  # publish happens post-commit in the route handler

    return artifact, pending_payload
