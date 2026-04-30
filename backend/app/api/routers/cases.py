"""Case HTTP endpoints."""

import logging
from datetime import UTC, datetime
from uuid import UUID

_log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_decisioning_queue_dep,
    get_queue_dep,
    get_session,
    get_storage_dep,
    require_role,
)
from app.core.exceptions import InvalidStateTransition
from app.enums import ArtifactType, CaseStage, DecisionStatus, UserRole
from app.models.audit_log import AuditLog
from app.models.case import Case
from app.models.case_extraction import CaseExtraction
from app.models.case_feedback import CaseFeedback
from app.models.checklist_validation_result import ChecklistValidationResult
from app.models.decision_result import DecisionResult
from app.models.decision_step import DecisionStep
from app.models.dedupe_match import DedupeMatch
from app.models.user import User
from app.schemas.audit import AuditLogRead
from app.schemas.case import (
    ApproveReuploadRequest,
    CaseArtifactRead,
    CaseInitiateRequest,
    CaseInitiateResponse,
    CaseListResponse,
    CaseRead,
    RejectDeletionPayload,
    RequestDeletionPayload,
)
from app.schemas.decision import DecisionResultRead, DecisionStepRead
from app.schemas.extraction import (
    CaseExtractionRead,
    ChecklistValidationResultRead,
    DedupeMatchRead,
)
from app.schemas.feedback import FeedbackCreate, FeedbackRead
from app.services import audit as audit_svc
from app.services import cases as case_svc
from app.services import stages as stages_svc
from app.services.queue import QueueService
from app.services.storage import StorageService

router = APIRouter(prefix="/cases", tags=["cases"])


async def _attach_artifacts(case: Case, session: AsyncSession, storage: StorageService) -> CaseRead:
    """Build CaseRead with artifacts + download URLs.

    Each artefact exposes two signed URLs:
      * ``download_url`` — Content-Disposition: inline, for previewing
        inside the "View source" modal without auto-download.
      * ``attachment_url`` — Content-Disposition: attachment; filename=...,
        used only when the MD clicks the explicit Download button.
    """
    artifacts = await case_svc.list_artifacts(session, case.id)
    artifact_reads = []
    for a in artifacts:
        inline_url = await storage.generate_presigned_download_url(
            a.s3_key, expires_in=900, disposition="inline", filename=a.filename,
        )
        attach_url = await storage.generate_presigned_download_url(
            a.s3_key, expires_in=900, disposition="attachment", filename=a.filename,
        )
        artifact_reads.append(
            CaseArtifactRead.model_validate(a).model_copy(
                update={"download_url": inline_url, "attachment_url": attach_url},
            )
        )

    # Unresolved LevelIssue count — drives the stage-badge red override on
    # the case-detail header the same way it does on the cases list.
    from app.enums import LevelIssueStatus
    from app.models.level_issue import LevelIssue
    from app.models.verification_result import VerificationResult

    open_count = (
        await session.execute(
            select(func.count(LevelIssue.id))
            .join(
                VerificationResult,
                LevelIssue.verification_result_id == VerificationResult.id,
            )
            .where(
                VerificationResult.case_id == case.id,
                LevelIssue.status.in_(
                    [LevelIssueStatus.OPEN, LevelIssueStatus.ASSESSOR_RESOLVED]
                ),
            )
        )
    ).scalar() or 0

    return CaseRead.model_validate(case).model_copy(
        update={
            "artifacts": artifact_reads,
            "open_issue_count": int(open_count),
        }
    )


@router.post(
    "/initiate",
    response_model=CaseInitiateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_case(
    payload: CaseInitiateRequest,
    actor: User = Depends(require_role(UserRole.AI_ANALYSER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseInitiateResponse:
    try:
        result = await case_svc.initiate(
            session,
            storage=storage,
            actor=actor,
            loan_id=payload.loan_id,
            applicant_name=payload.applicant_name,
            loan_amount=payload.loan_amount,
            loan_tenure_months=payload.loan_tenure_months,
            co_applicant_name=payload.co_applicant_name,
            occupation=payload.occupation,
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": "case_exists", "message": str(e), "requires_admin_approval": True},
        ) from e
    await session.commit()
    return CaseInitiateResponse(
        case_id=result.case.id,
        upload_url=result.upload_url,
        upload_fields=result.upload_fields,
        upload_key=result.upload_key,
        expires_at=result.expires_at,
        reupload=result.reupload,
    )


@router.post("/{case_id}/finalize", response_model=CaseRead)
async def finalize_case(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.AI_ANALYSER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
    queue: QueueService = Depends(get_queue_dep),
) -> CaseRead:
    try:
        case, ingestion_payload = await case_svc.finalize(
            session,
            storage=storage,
            queue=queue,
            actor=actor,
            case_id=case_id,
        )
    except InvalidStateTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower() and "upload" in msg.lower():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, msg) from e
        raise HTTPException(status.HTTP_404_NOT_FOUND, msg) from e
    await session.commit()
    # Publish to the ingestion queue *after* the commit so the worker can never
    # read an uncommitted UPLOADED snapshot when it pulls the message.
    await queue.publish_job(ingestion_payload)
    return await _attach_artifacts(case, session, storage)


@router.post(
    "/{case_id}/artifacts",
    response_model=CaseArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_artifact(
    case_id: UUID,
    file: UploadFile = File(...),
    artifact_type: ArtifactType = Form(ArtifactType.ADDITIONAL_FILE),
    actor: User = Depends(require_role(UserRole.AI_ANALYSER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
    queue: QueueService = Depends(get_queue_dep),
) -> CaseArtifactRead:
    from app.config import get_settings

    max_bytes = get_settings().max_artifact_size_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Artifact exceeds {max_bytes} byte limit",
        )
    try:
        artifact, reingest_payload = await case_svc.add_artifact(
            session,
            storage=storage,
            queue=queue,
            actor=actor,
            case_id=case_id,
            filename=file.filename or "upload.bin",
            content=content,
            artifact_type=artifact_type,
            content_type=file.content_type,
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    await session.commit()
    # If the artifact-add triggered a re-ingest (case was in CHECKLIST_MISSING_DOCS),
    # publish the re-ingest job *after* the commit so the worker sees the new
    # CHECKLIST_VALIDATION stage.
    if reingest_payload is not None:
        await queue.publish_job(reingest_payload)
    inline_url = await storage.generate_presigned_download_url(
        artifact.s3_key, expires_in=900, disposition="inline", filename=artifact.filename,
    )
    attach_url = await storage.generate_presigned_download_url(
        artifact.s3_key, expires_in=900, disposition="attachment", filename=artifact.filename,
    )
    return CaseArtifactRead.model_validate(artifact).model_copy(
        update={"download_url": inline_url, "attachment_url": attach_url},
    )


@router.get("/{case_id}/artifacts/zip")
async def download_artifacts_zip(
    case_id: UUID,
    actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.UNDERWRITER,
            UserRole.ADMIN,
            UserRole.CREDIT_HO,
            UserRole.CEO,
        )
    ),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
):
    """Stream a ZIP of every non-deleted artifact for the case.

    Use this after an assessor has uploaded missing documents so the ops team
    has a single bundle reflecting the updated state of the case. Writes an
    audit log entry (``ARTIFACTS_ZIP_DOWNLOADED``) for every download.
    """
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    artifacts = await case_svc.list_artifacts(session, case_id)
    if not artifacts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No artifacts on this case")

    # Resolve the loan_id so the zip filename is human-readable (not a UUID).
    case = (
        await session.execute(select(Case).where(Case.id == case_id))
    ).scalar_one_or_none()
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    # Some rows may point at S3 keys that have been cleaned up (e.g. after a
    # re-ingest). Skip missing keys and log, rather than 500ing the whole zip.
    from botocore.exceptions import ClientError

    buffer = io.BytesIO()
    used_names: dict[str, int] = {}
    included = 0
    skipped = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for a in artifacts:
            if getattr(a, "is_deleted", False):
                continue
            base = a.filename or "artifact.bin"
            if base in used_names:
                used_names[base] += 1
                stem, _, ext = base.rpartition(".")
                base = f"{stem} ({used_names[base]}).{ext}" if ext else f"{base} ({used_names[base]})"
            else:
                used_names[base] = 1
            try:
                data = await storage.download_object(a.s3_key)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("NoSuchKey", "404", "NotFound"):
                    _log.warning("zip: skipping missing artifact %s (%s)", a.id, a.s3_key)
                    skipped += 1
                    continue
                raise
            zf.writestr(base, data)
            included += 1

    if included == 0:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No artifact bytes available — all source objects are missing from storage",
        )

    buffer.seek(0)
    filename = f"{case.loan_id or case_id}_artifacts.zip"

    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="ARTIFACTS_ZIP_DOWNLOADED",
        entity_type="case",
        entity_id=str(case_id),
        after={
            "loan_id": case.loan_id,
            "artifact_count": len(artifacts),
        },
    )
    await session.commit()

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_model=CaseListResponse)
async def list_cases_endpoint(
    stage: CaseStage | None = Query(None),
    uploaded_by: UUID | None = Query(None),
    loan_id_prefix: str | None = Query(None, max_length=32),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CaseListResponse:
    effective_include_deleted = include_deleted and actor.role == UserRole.ADMIN
    # Security: underwriters may only see their own cases regardless of query param.
    effective_uploaded_by = (
        actor.id if actor.role == UserRole.UNDERWRITER else uploaded_by
    )
    page = await case_svc.list_cases(
        session,
        stage=stage,
        uploaded_by=effective_uploaded_by,
        loan_id_prefix=loan_id_prefix,
        from_date=from_date,
        to_date=to_date,
        include_deleted=effective_include_deleted,
        limit=limit,
        offset=offset,
    )

    # Count unresolved LevelIssues per case on the current page so the UI
    # can flip the stage badge red until the queue is empty. Single
    # aggregate query keyed on (case_id) — avoids an N+1 on the list.
    case_ids = [c.id for c in page.cases]
    open_issue_by_case: dict[UUID, int] = {}
    if case_ids:
        from app.enums import LevelIssueStatus
        from app.models.level_issue import LevelIssue
        from app.models.verification_result import VerificationResult

        issue_stmt = (
            select(
                VerificationResult.case_id,
                func.count(LevelIssue.id),
            )
            .join(
                LevelIssue,
                LevelIssue.verification_result_id == VerificationResult.id,
            )
            .where(
                VerificationResult.case_id.in_(case_ids),
                LevelIssue.status.in_(
                    [
                        LevelIssueStatus.OPEN,
                        LevelIssueStatus.ASSESSOR_RESOLVED,
                    ]
                ),
            )
            .group_by(VerificationResult.case_id)
        )
        for cid, cnt in (await session.execute(issue_stmt)).all():
            open_issue_by_case[cid] = int(cnt)

    reads: list[CaseRead] = []
    for c in page.cases:
        r = CaseRead.model_validate(c)
        # Pydantic can't mutate a validated instance directly — model_copy
        # with an update is the idiomatic way to stamp the count on.
        reads.append(r.model_copy(update={"open_issue_count": open_issue_by_case.get(c.id, 0)}))

    return CaseListResponse(
        cases=reads,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{case_id}", response_model=CaseRead)
async def get_case_endpoint(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseRead:
    include_deleted = actor.role == UserRole.ADMIN
    case = await case_svc.get_case(session, case_id, include_deleted=include_deleted)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return await _attach_artifacts(case, session, storage)


@router.get("/{case_id}/download")
async def download_case_zip(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> RedirectResponse:
    from app.services import audit as audit_svc

    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    url = await storage.generate_presigned_download_url(case.zip_s3_key, expires_in=900)
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="case.downloaded",
        entity_type="case",
        entity_id=str(case.id),
    )
    await session.commit()
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{case_id}/approve-reupload", response_model=CaseRead)
async def approve_reupload_endpoint(
    case_id: UUID,
    payload: ApproveReuploadRequest,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseRead:
    try:
        case = await case_svc.approve_reupload(
            session,
            actor=actor,
            case_id=case_id,
            reason=payload.reason,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    await session.commit()
    return await _attach_artifacts(case, session, storage)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def soft_delete_case(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await case_svc.soft_delete(session, actor=actor, case_id=case_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    await session.commit()


# ─────────────────────────── Deletion-approval flow ────────────────────────
# Request/approve/reject endpoints for the MD-gated delete path. Non-admin
# users file requests, MD-role users (CEO or ADMIN) approve or reject.
# The single-step DELETE endpoint above stays as an admin-only escape hatch.


@router.get("/deletion-requests/pending", response_model=CaseListResponse)
async def list_pending_deletion_requests(
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseListResponse:
    """MD-only — every case with an outstanding deletion request.
    Powers the MD Approvals page's "Deletion requests" section."""
    del actor
    stmt = (
        select(Case)
        .where(Case.deletion_requested_at.is_not(None), Case.is_deleted.is_(False))
        .order_by(desc(Case.deletion_requested_at))
    )
    cases = (await session.execute(stmt)).scalars().all()
    reads: list[CaseRead] = []
    for c in cases:
        reads.append(await _attach_artifacts(c, session, storage))
    return CaseListResponse(
        cases=reads,
        total=len(reads),
        limit=len(reads),
        offset=0,
    )


@router.post("/{case_id}/request-deletion", response_model=CaseRead)
async def request_case_deletion(
    case_id: UUID,
    payload: RequestDeletionPayload,
    actor: User = Depends(
        require_role(
            UserRole.ADMIN,
            UserRole.CEO,
            UserRole.CREDIT_HO,
            UserRole.AI_ANALYSER,
            UserRole.UNDERWRITER,
        )
    ),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseRead:
    try:
        case = await case_svc.request_deletion(
            session, actor=actor, case_id=case_id, reason=payload.reason
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    return await _attach_artifacts(case, session, storage)


@router.post("/{case_id}/approve-deletion", response_model=CaseRead)
async def approve_case_deletion(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseRead:
    try:
        case = await case_svc.approve_deletion(
            session, md_actor=actor, case_id=case_id
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    return await _attach_artifacts(case, session, storage)


@router.post("/{case_id}/reject-deletion", response_model=CaseRead)
async def reject_case_deletion(
    case_id: UUID,
    payload: RejectDeletionPayload,
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO)),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CaseRead:
    try:
        case = await case_svc.reject_deletion(
            session,
            md_actor=actor,
            case_id=case_id,
            rationale=payload.rationale,
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    return await _attach_artifacts(case, session, storage)


@router.get("/{case_id}/extractions", response_model=list[CaseExtractionRead])
async def list_extractions_endpoint(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[CaseExtractionRead]:
    """Return all extraction rows for a case."""
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    stmt = (
        select(CaseExtraction)
        .where(CaseExtraction.case_id == case_id)
        .order_by(desc(CaseExtraction.extracted_at))
    )
    result = await session.execute(stmt)
    extractions = result.scalars().all()
    return [CaseExtractionRead.model_validate(e) for e in extractions]


@router.get("/{case_id}/extractions/{extractor_name}", response_model=CaseExtractionRead)
async def get_extraction_endpoint(
    case_id: UUID,
    extractor_name: str,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CaseExtractionRead:
    """Return the most recent extraction for a specific extractor."""
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    stmt = (
        select(CaseExtraction)
        .where(CaseExtraction.case_id == case_id, CaseExtraction.extractor_name == extractor_name)
        .order_by(desc(CaseExtraction.extracted_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    extraction = result.scalar_one_or_none()
    if extraction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extraction not found")
    return CaseExtractionRead.model_validate(extraction)


@router.get("/{case_id}/checklist-validation", response_model=ChecklistValidationResultRead)
async def get_checklist_validation_endpoint(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChecklistValidationResultRead:
    """Return checklist validation result for a case."""
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    stmt = select(ChecklistValidationResult).where(ChecklistValidationResult.case_id == case_id)
    result = await session.execute(stmt)
    validation = result.scalar_one_or_none()
    if validation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist validation not found")
    return ChecklistValidationResultRead.model_validate(validation)


@router.post(
    "/{case_id}/checklist/waive",
    response_model=ChecklistValidationResultRead,
)
async def waive_missing_doc(
    case_id: UUID,
    payload: dict,  # {"doc_type": str, "justification": str}
    actor: User = Depends(require_role(UserRole.CEO, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> ChecklistValidationResultRead:
    """MD waiver for a single missing required document.

    Removes the doc_type from `missing_docs` and stamps a waiver entry into
    `present_docs` (so the audit trail keeps the justification + reviewer).
    If the waiver clears every remaining requirement, transitions the case
    out of CHECKLIST_MISSING_DOCS up to INGESTED so the auto-run can proceed.
    """
    doc_type = str(payload.get("doc_type") or "").strip()
    justification = str(payload.get("justification") or "").strip()
    if not doc_type:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "doc_type is required")
    if len(justification) < 4:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "justification must be at least 4 characters — auditors read this later",
        )

    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    stmt = select(ChecklistValidationResult).where(
        ChecklistValidationResult.case_id == case_id
    )
    validation = (await session.execute(stmt)).scalar_one_or_none()
    if validation is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No checklist validation on file yet — re-ingest the case first.",
        )

    missing = list(validation.missing_docs or [])
    present = list(validation.present_docs or [])

    matched_idx = next(
        (i for i, m in enumerate(missing) if str(m.get("doc_type")) == doc_type),
        None,
    )
    if matched_idx is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{doc_type!r} is not currently in the missing list — nothing to waive.",
        )

    waived_at = datetime.now(UTC)
    matched = missing.pop(matched_idx)
    present.append(
        {
            "doc_type": doc_type,
            "count": 0,
            "waived": True,
            "waived_by": str(actor.id),
            "waived_by_email": actor.email,
            "waived_at": waived_at.isoformat(),
            "justification": justification,
            "original_reason": matched.get("reason"),
        }
    )

    validation.missing_docs = missing
    validation.present_docs = present
    validation.is_complete = len(missing) == 0
    validation.validated_at = waived_at
    session.add(validation)

    # If the waiver cleared the last blocker, walk the case stage forward to
    # INGESTED so AutoRun's `waitForCaseReady` poll succeeds. The state-machine
    # only allows one hop at a time, so we chain explicitly.
    if validation.is_complete and case.current_stage == CaseStage.CHECKLIST_MISSING_DOCS:
        for to_stage in (
            CaseStage.CHECKLIST_VALIDATION,
            CaseStage.CHECKLIST_VALIDATED,
            CaseStage.INGESTED,
        ):
            await stages_svc.transition_stage(
                session=session,
                case=case,
                to=to_stage,
                actor_user_id=actor.id,
            )

    await audit_svc.log_action(
        session=session,
        actor_user_id=actor.id,
        action="CHECKLIST_DOC_WAIVED",
        entity_type="case",
        entity_id=str(case.id),
        after={
            "doc_type": doc_type,
            "justification": justification,
            "now_complete": validation.is_complete,
            "remaining_missing": [m.get("doc_type") for m in missing],
        },
    )

    await session.commit()
    await session.refresh(validation)
    return ChecklistValidationResultRead.model_validate(validation)


@router.get("/{case_id}/dedupe-matches", response_model=list[DedupeMatchRead])
async def list_dedupe_matches_endpoint(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[DedupeMatchRead]:
    """Return all dedupe matches for a case."""
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    stmt = (
        select(DedupeMatch)
        .where(DedupeMatch.case_id == case_id)
        .order_by(desc(DedupeMatch.created_at))
    )
    result = await session.execute(stmt)
    matches = result.scalars().all()
    return [DedupeMatchRead.model_validate(m) for m in matches]


@router.get("/{case_id}/audit-log", response_model=list[AuditLogRead])
async def get_case_audit_log(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AuditLogRead]:
    """Return the audit timeline for a case, newest first."""
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == "case")
        .where(AuditLog.entity_id == str(case_id))
        .order_by(AuditLog.created_at.desc())
    )
    result = await session.execute(stmt)
    entries = result.scalars().all()
    return [AuditLogRead.model_validate(e) for e in entries]


# Stages from which an *admin manual* reingest is allowed.
# Deliberately does NOT include CHECKLIST_VALIDATION — a case already in that
# stage is mid-pipeline (or just about to run); re-enqueueing would be a
# duplicate. The worker pipeline's own pre-flight set (see
# app/worker/pipeline.py::_REINGEST_ALLOWED_FROM) is broader because it handles
# the CHECKLIST_VALIDATION landing state from the add_artifact re-trigger
# (cases.py::add_artifact) which publishes AFTER transitioning to VALIDATION.
_REINGEST_ALLOWED_STAGES = {
    CaseStage.INGESTED,
    CaseStage.CHECKLIST_MISSING_DOCS,
    CaseStage.CHECKLIST_VALIDATED,
}


@router.post("/{case_id}/reingest", status_code=status.HTTP_202_ACCEPTED)
async def reingest_case(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    queue: QueueService = Depends(get_queue_dep),
) -> dict[str, str]:
    """Trigger reingestion of a case. Case must be in allowed stage."""
    from app.services import audit as audit_svc

    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if case.current_stage not in _REINGEST_ALLOWED_STAGES:
        raise HTTPException(
            status_code=409,
            detail=f"Case stage {case.current_stage.value} does not allow reingestion",
        )
    await queue.publish_job(
        {
            "case_id": str(case.id),
            "loan_id": case.loan_id,
            "zip_s3_key": case.zip_s3_key,
            "trigger": "reingest",
        }
    )
    await audit_svc.log_action(
        session=session,
        actor_user_id=actor.id,
        action="case.reingestion_triggered",
        entity_type="case",
        entity_id=str(case.id),
        after={"reason": "admin_manual"},
    )
    await session.commit()
    return {"detail": "Reingestion triggered"}


# ---------------------------------------------------------------------------
# Phase 1 Decisioning endpoints (T18)
# ---------------------------------------------------------------------------


async def _get_latest_decision_result(
    session: AsyncSession,
    case_id: UUID,
) -> DecisionResult | None:
    """Return the most-recent DecisionResult for a case, or None."""
    stmt = (
        select(DecisionResult)
        .where(DecisionResult.case_id == case_id)
        .order_by(desc(DecisionResult.created_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@router.post(
    "/{case_id}/phase1",
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_phase1(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.AI_ANALYSER)),
    session: AsyncSession = Depends(get_session),
    decisioning_queue: QueueService = Depends(get_decisioning_queue_dep),
) -> dict[str, str]:
    """Trigger Phase 1 decisioning. Case must be in INGESTED stage.

    Also gated on CAM discrepancies: if the auto_cam extraction has any
    CRITICAL unresolved SystemCam-vs-CM-CAM-IL flags, returns 409 with a
    ``pending_discrepancies`` list. The caller (UI) is expected to
    surface each one and require an assessor resolution first.
    """
    from app.services.cam_discrepancy import get_summary as get_disc_summary

    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if case.current_stage != CaseStage.INGESTED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Case must be INGESTED to start Phase 1 (currently {case.current_stage.value})",
        )

    # CAM discrepancy gate — unresolved CRITICAL flags block Phase 1.
    disc_summary = await get_disc_summary(session, case_id)
    if disc_summary.phase1_blocked:
        pending = [
            {
                "field_key": v.field_key,
                "field_label": v.field_label,
                "severity": v.flag.severity.value if v.flag else None,
                "system_cam_value": v.flag.system_cam_value if v.flag else None,
                "cm_cam_il_value": v.flag.cm_cam_il_value if v.flag else None,
            }
            for v in disc_summary.views
            if v.flag and v.flag.severity.value == "CRITICAL" and v.resolution is None
        ]
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "reason": "cam_discrepancies_unresolved",
                "message": (
                    f"{len(pending)} CRITICAL CAM discrepancy(ies) must be "
                    "resolved before Phase 1 can run."
                ),
                "pending_discrepancies": pending,
            },
        )

    # Create the DecisionResult row
    dr = DecisionResult(
        case_id=case.id,
        status=DecisionStatus.PENDING,
        phase="phase1",
        triggered_by=actor.id,
    )
    session.add(dr)
    await session.flush()

    # Transition case stage: INGESTED → PHASE_1_DECISIONING
    await stages_svc.transition_stage(
        session=session,
        case=case,
        to=CaseStage.PHASE_1_DECISIONING,
        actor_user_id=actor.id,
    )

    # Audit
    await audit_svc.log_action(
        session=session,
        actor_user_id=actor.id,
        action="decision.started",
        entity_type="decision_result",
        entity_id=str(dr.id),
        after={"case_id": str(case.id), "triggered_by": str(actor.id)},
    )

    # Publish SQS job
    await decisioning_queue.publish_job(
        {
            "decision_result_id": str(dr.id),
            "actor_user_id": str(actor.id),
        }
    )

    await session.commit()
    return {"decision_result_id": str(dr.id)}


@router.get("/{case_id}/phase1", response_model=DecisionResultRead)
async def get_phase1(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionResultRead:
    """Get the latest Phase 1 result for a case."""
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    dr = await _get_latest_decision_result(session, case_id)
    if dr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Phase 1 result found")
    return DecisionResultRead.model_validate(dr)


@router.get("/{case_id}/phase1/steps", response_model=list[DecisionStepRead])
async def list_phase1_steps(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[DecisionStepRead]:
    """List all steps for the latest Phase 1 result."""
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    dr = await _get_latest_decision_result(session, case_id)
    if dr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Phase 1 result found")

    stmt = (
        select(DecisionStep)
        .where(DecisionStep.decision_result_id == dr.id)
        .order_by(DecisionStep.step_number)
    )
    result = await session.execute(stmt)
    steps = result.scalars().all()
    return [DecisionStepRead.model_validate(s) for s in steps]


@router.get("/{case_id}/phase1/steps/{step_number}", response_model=DecisionStepRead)
async def get_phase1_step(
    case_id: UUID,
    step_number: int,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionStepRead:
    """Get a specific step from the latest Phase 1 result."""
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    dr = await _get_latest_decision_result(session, case_id)
    if dr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Phase 1 result found")

    stmt = select(DecisionStep).where(
        DecisionStep.decision_result_id == dr.id,
        DecisionStep.step_number == step_number,
    )
    result = await session.execute(stmt)
    step = result.scalar_one_or_none()
    if step is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Step {step_number} not found")
    return DecisionStepRead.model_validate(step)


@router.post("/{case_id}/phase1/cancel", status_code=status.HTTP_200_OK)
async def cancel_phase1(
    case_id: UUID,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Cancel an in-progress Phase 1 run and roll back case to INGESTED."""
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    dr = await _get_latest_decision_result(session, case_id)
    if dr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Phase 1 result found")

    if dr.status not in (DecisionStatus.PENDING, DecisionStatus.RUNNING):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a {dr.status.value} decisioning run",
        )

    dr.status = DecisionStatus.CANCELLED
    dr.completed_at = datetime.now(UTC)
    await session.flush()

    # Transition case back to INGESTED if it's in PHASE_1_DECISIONING
    if case.current_stage == CaseStage.PHASE_1_DECISIONING:
        import contextlib
        with contextlib.suppress(Exception):
            await stages_svc.transition_stage(
                session=session,
                case=case,
                to=CaseStage.INGESTED,
                actor_user_id=actor.id,
            )

    await audit_svc.log_action(
        session=session,
        actor_user_id=actor.id,
        action="decision.canceled",
        entity_type="decision_result",
        entity_id=str(dr.id),
        after={"case_id": str(case.id)},
    )

    await session.commit()
    return {"detail": "Phase 1 decisioning canceled"}


# ---------------------------------------------------------------------------
# Feedback endpoints (M4 — §7 phase 1)
# ---------------------------------------------------------------------------


@router.post(
    "/{case_id}/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    case_id: UUID,
    payload: FeedbackCreate,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FeedbackRead:
    """Submit a feedback verdict on a case (any authenticated user)."""
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    feedback = CaseFeedback(
        case_id=case_id,
        actor_user_id=actor.id,
        verdict=payload.verdict,
        notes=payload.notes,
        phase=payload.phase,
    )
    session.add(feedback)
    await session.flush()

    await audit_svc.log_action(
        session=session,
        actor_user_id=actor.id,
        action="case.feedback_submitted",
        entity_type="case",
        entity_id=str(case_id),
        after={"verdict": payload.verdict, "phase": payload.phase},
    )
    await session.commit()
    return FeedbackRead.model_validate(feedback)


@router.get("/{case_id}/feedback", response_model=list[FeedbackRead])
async def list_feedback(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FeedbackRead]:
    """Return all feedback entries for a case (most recent first)."""
    case = await case_svc.get_case(session, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    stmt = (
        select(CaseFeedback)
        .where(CaseFeedback.case_id == case_id)
        .order_by(desc(CaseFeedback.created_at))
    )
    result = await session.execute(stmt)
    feedbacks = result.scalars().all()
    return [FeedbackRead.model_validate(f) for f in feedbacks]
