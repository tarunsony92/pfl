"""Verification (4-level pre-Phase-1 gate) HTTP endpoints.

Phase A ships Level 1. Endpoints are shaped so Level 2/3/4 drop in later with
minimal changes — the path is ``/cases/{case_id}/verification/{level_number}``.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_session,
    get_storage_dep,
    require_role,
)
from app.config import Settings, get_settings
from app.enums import (
    LevelIssueStatus,
    UserRole,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.case import Case
from app.models.l1_extracted_document import L1ExtractedDocument
from app.models.level_issue import LevelIssue
from app.models.user import User
from app.models.verification_result import VerificationResult
from app.schemas.verification import (
    CasePhotoItem,
    CasePhotosResponse,
    IssueDecideRequest,
    IssueResolveRequest,
    L1ExtractedDocumentRead,
    LevelIssueRead,
    MDQueueItem,
    MDQueueResponse,
    PrecedentItem,
    PrecedentsResponse,
    TriggerLevelResponse,
    VerificationLevelDetail,
    VerificationOverview,
    VerificationResultRead,
)
from app.enums import ArtifactSubtype
from app.models.case_artifact import CaseArtifact
from app.services import audit as audit_svc
from app.services.storage import StorageService
from app.verification.levels.level_1_address import run_level_1_address
from app.verification.levels.level_1_5_credit import run_level_1_5_credit
from app.verification.levels.level_2_banking import run_level_2_banking
from app.verification.levels.level_3_vision import run_level_3_vision
from app.verification.levels.level_4_agreement import run_level_4_agreement
from app.verification.levels.level_5_scoring import run_level_5_scoring
from app.verification.levels.level_5_5_dedupe_tvr import run_level_5_5_dedupe_tvr

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["verification"])
# Separate router for cross-case endpoints (no /cases prefix) so they don't
# collide with the ``/cases/{case_id}/verification/{level_number}`` path.
md_router = APIRouter(prefix="/verification", tags=["verification"])


# ── helpers ──────────────────────────────────────────────────────────────────


async def _require_case(session: AsyncSession, case_id: UUID) -> Case:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _latest_result_for_level(
    session: AsyncSession, case_id: UUID, level: VerificationLevelNumber
) -> VerificationResult | None:
    stmt = (
        select(VerificationResult)
        .where(VerificationResult.case_id == case_id)
        .where(VerificationResult.level_number == level)
        .order_by(desc(VerificationResult.created_at))
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def _latest_by_all_levels(
    session: AsyncSession, case_id: UUID
) -> list[VerificationResult]:
    rows: list[VerificationResult] = []
    for level in VerificationLevelNumber:
        r = await _latest_result_for_level(session, case_id, level)
        if r is not None:
            rows.append(r)
    return rows


def _latest_vr_ids_subquery():
    """Return a scalar subquery of ``VerificationResult.id`` values that are
    the latest run per ``(case_id, level_number)``.

    Used by the MD + assessor queues so stale issues attached to
    superseded VR rows don't appear in the UI. Mechanics: group by
    ``(case_id, level_number)`` and pick the max ``created_at``, then
    join back to map that timestamp to the actual row id. We use a
    tuple-IN because postgres can optimise that into an index seek on
    ``ix_verification_results_case_level_created``.
    """
    max_per_group = (
        select(
            VerificationResult.case_id,
            VerificationResult.level_number,
            func.max(VerificationResult.created_at).label("max_created"),
        )
        .group_by(VerificationResult.case_id, VerificationResult.level_number)
        .subquery()
    )
    latest_ids = (
        select(VerificationResult.id)
        .join(
            max_per_group,
            (VerificationResult.case_id == max_per_group.c.case_id)
            & (VerificationResult.level_number == max_per_group.c.level_number)
            & (VerificationResult.created_at == max_per_group.c.max_created),
        )
    )
    return latest_ids


def _gate_open(results: list[VerificationResult]) -> bool:
    """Phase 1 is allowed iff *every* verification level is present + passed.

    Historically this check was ``len(results) >= 4`` — adequate when only
    L1/L2/L3/L4 existed. With L1.5 (credit) and L5 (scoring) wired in, a
    case missing either one must not open the gate even if the four older
    levels all report PASSED. We iterate every member of
    :class:`VerificationLevelNumber` so adding a future level closes the
    gate by default until the new level has its own passing run.
    """
    passed_states = {
        VerificationLevelStatus.PASSED,
        VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE,
    }
    by_level = {r.level_number: r for r in results}
    for level in VerificationLevelNumber:
        r = by_level.get(level)
        if r is None or r.status not in passed_states:
            return False
    return True


# ── endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "/{case_id}/verification/{level_number}",
    response_model=TriggerLevelResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_level(
    case_id: UUID,
    level_number: VerificationLevelNumber,
    actor: User = Depends(
        require_role(UserRole.AI_ANALYSER, UserRole.ADMIN, UserRole.UNDERWRITER)
    ),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
    settings: Settings = Depends(get_settings),
) -> TriggerLevelResponse:
    """Run the given verification level synchronously and persist the result."""
    case = await _require_case(session, case_id)

    if not settings.verification_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Verification gate disabled"
        )

    # Concurrency guard: if a VR for this (case, level) is already
    # RUNNING within the last 5 minutes, treat it as an in-flight job
    # and bounce the caller back with the existing VR id rather than
    # spawning a second Claude call + second VR row. We intentionally
    # ignore RUNNING rows older than that window — those are zombies
    # from crashed workers and should not block a fresh trigger
    # forever.
    from datetime import UTC, datetime, timedelta

    freshness_floor = datetime.now(UTC) - timedelta(minutes=5)
    inflight_stmt = (
        select(VerificationResult)
        .where(VerificationResult.case_id == case_id)
        .where(VerificationResult.level_number == level_number)
        .where(VerificationResult.status == VerificationLevelStatus.RUNNING)
        .where(VerificationResult.created_at >= freshness_floor)
        .order_by(desc(VerificationResult.created_at))
        .limit(1)
    )
    inflight = (await session.execute(inflight_stmt)).scalars().first()
    if inflight is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "error": "level_already_running",
                "message": (
                    f"Level {level_number.value} is already RUNNING for this case "
                    f"(started at {inflight.started_at}). Wait for it to finish "
                    f"before re-triggering."
                ),
                "verification_result_id": str(inflight.id),
            },
        )

    from app.services.claude import get_claude_service

    claude = get_claude_service(settings)

    try:
        if level_number is VerificationLevelNumber.L1_ADDRESS:
            result = await run_level_1_address(
                session,
                case_id,
                actor_user_id=actor.id,
                claude=claude,
                storage=storage,
                api_key=settings.google_maps_api_key,
            )
        elif level_number is VerificationLevelNumber.L1_5_CREDIT:
            result = await run_level_1_5_credit(
                session,
                case_id,
                actor_user_id=actor.id,
                claude=claude,
            )
        elif level_number is VerificationLevelNumber.L2_BANKING:
            result = await run_level_2_banking(
                session,
                case_id,
                actor_user_id=actor.id,
                claude=claude,
            )
        elif level_number is VerificationLevelNumber.L3_VISION:
            result = await run_level_3_vision(
                session,
                case_id,
                actor_user_id=actor.id,
                claude=claude,
                storage=storage,
            )
        elif level_number is VerificationLevelNumber.L4_AGREEMENT:
            result = await run_level_4_agreement(
                session,
                case_id,
                actor_user_id=actor.id,
                claude=claude,
                storage=storage,
            )
        elif level_number is VerificationLevelNumber.L5_SCORING:
            result = await run_level_5_scoring(
                session,
                case_id,
                actor_user_id=actor.id,
                claude=claude,
                storage=storage,
            )
        elif level_number is VerificationLevelNumber.L5_5_DEDUPE_TVR:
            result = await run_level_5_5_dedupe_tvr(
                session,
                case_id,
                actor_user_id=actor.id,
                claude=claude,
                storage=storage,
            )
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown level {level_number.value}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("Level %s failed for case %s", level_number, case_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Level run failed: {exc}"
        ) from exc
    await session.commit()

    _ = case  # satisfy ruff B007 — kept for clarity
    return TriggerLevelResponse(
        verification_result_id=result.id,
        case_id=case_id,
        level_number=result.level_number,
        status=result.status,
    )


@router.get(
    "/{case_id}/verification",
    response_model=VerificationOverview,
)
async def get_overview(
    case_id: UUID,
    _actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VerificationOverview:
    await _require_case(session, case_id)
    results = await _latest_by_all_levels(session, case_id)

    open_count = 0
    awaiting_md_count = 0
    md_approved_count = 0
    md_rejected_count = 0
    if results:
        issue_rows = (
            (
                await session.execute(
                    select(LevelIssue).where(
                        LevelIssue.verification_result_id.in_(
                            [r.id for r in results]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for iss in issue_rows:
            if iss.status == LevelIssueStatus.OPEN:
                open_count += 1
            elif iss.status == LevelIssueStatus.ASSESSOR_RESOLVED:
                awaiting_md_count += 1
            elif iss.status == LevelIssueStatus.MD_APPROVED:
                md_approved_count += 1
            elif iss.status == LevelIssueStatus.MD_REJECTED:
                md_rejected_count += 1

    return VerificationOverview(
        case_id=case_id,
        levels=[VerificationResultRead.model_validate(r) for r in results],
        gate_open_for_phase_1=_gate_open(results),
        open_issue_count=open_count,
        awaiting_md_count=awaiting_md_count,
        md_approved_count=md_approved_count,
        md_rejected_count=md_rejected_count,
    )


@router.get(
    "/{case_id}/verification/{level_number}",
    response_model=VerificationLevelDetail,
)
async def get_level_detail(
    case_id: UUID,
    level_number: VerificationLevelNumber,
    _actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VerificationLevelDetail:
    await _require_case(session, case_id)
    r = await _latest_result_for_level(session, case_id, level_number)
    if r is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No {level_number.value} run found"
        )
    # Collect L1 extracted docs (only populated when level_number == L1_ADDRESS)
    ext_docs_rows: list[L1ExtractedDocument] = []
    if level_number is VerificationLevelNumber.L1_ADDRESS:
        rows = (
            (
                await session.execute(
                    select(L1ExtractedDocument).where(
                        L1ExtractedDocument.case_id == case_id
                    )
                )
            )
            .scalars()
            .all()
        )
        ext_docs_rows = list(rows)

    issue_rows = (
        (
            await session.execute(
                select(LevelIssue)
                .where(LevelIssue.verification_result_id == r.id)
                .order_by(LevelIssue.created_at)
            )
        )
        .scalars()
        .all()
    )

    return VerificationLevelDetail(
        result=VerificationResultRead.model_validate(r),
        extracted_documents=[
            L1ExtractedDocumentRead.model_validate(d) for d in ext_docs_rows
        ],
        issues=[LevelIssueRead.model_validate(i) for i in issue_rows],
    )


@router.post(
    "/verification/issues/{issue_id}/resolve",
    response_model=LevelIssueRead,
)
async def resolve_issue(
    issue_id: UUID,
    payload: IssueResolveRequest,
    actor: User = Depends(
        require_role(UserRole.AI_ANALYSER, UserRole.UNDERWRITER, UserRole.ADMIN)
    ),
    session: AsyncSession = Depends(get_session),
) -> LevelIssueRead:
    from datetime import UTC, datetime

    issue = await session.get(LevelIssue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found")
    if issue.status not in (LevelIssueStatus.OPEN, LevelIssueStatus.ASSESSOR_RESOLVED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Issue is in terminal state {issue.status.value}",
        )
    prior_status = issue.status.value
    # Fetch the parent VR so the audit row carries the case_id — compliance
    # needs to pivot audit rows by case without extra joins.
    parent_vr = await session.get(VerificationResult, issue.verification_result_id)
    issue.assessor_user_id = actor.id
    issue.assessor_note = payload.assessor_note
    issue.assessor_resolved_at = datetime.now(UTC)
    issue.status = LevelIssueStatus.ASSESSOR_RESOLVED
    await session.flush()
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="ISSUE_ASSESSOR_RESOLVED",
        entity_type="level_issue",
        entity_id=str(issue.id),
        before={
            "status": prior_status,
            "sub_step_id": issue.sub_step_id,
        },
        after={
            "status": issue.status.value,
            "sub_step_id": issue.sub_step_id,
            "assessor_note": payload.assessor_note,
            "case_id": str(parent_vr.case_id) if parent_vr else None,
            "level_number": parent_vr.level_number.value if parent_vr else None,
        },
    )
    await session.commit()
    return LevelIssueRead.model_validate(issue)


@router.post(
    "/verification/issues/{issue_id}/decide",
    response_model=LevelIssueRead,
)
async def decide_issue(
    issue_id: UUID,
    payload: IssueDecideRequest,
    actor: User = Depends(require_role(UserRole.CEO, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> LevelIssueRead:
    from datetime import UTC, datetime

    if payload.decision not in (
        LevelIssueStatus.MD_APPROVED,
        LevelIssueStatus.MD_REJECTED,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "MD decision must be MD_APPROVED or MD_REJECTED",
        )
    issue = await session.get(LevelIssue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found")
    if issue.status not in (
        LevelIssueStatus.OPEN,
        LevelIssueStatus.ASSESSOR_RESOLVED,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Issue is already {issue.status.value}; cannot re-decide.",
        )
    prior_status = issue.status.value

    # Close the TOCTOU window on level promotion: two concurrent MD
    # decisions on sibling issues of the same VR would each read the
    # sibling list *before* the other committed, each see an unsettled
    # sibling (not each other's pending mutation), and neither would
    # promote the level to PASSED_WITH_MD_OVERRIDE. Locking the parent VR
    # row first serialises decides on the same level — the second caller
    # waits until the first commits, then re-reads the sibling rows and
    # sees the first caller's MD_APPROVED stamp.
    vr_lock_stmt = (
        select(VerificationResult)
        .where(VerificationResult.id == issue.verification_result_id)
        .with_for_update()
    )
    vr_locked = (await session.execute(vr_lock_stmt)).scalar_one_or_none()

    now = datetime.now(UTC)
    # MD short-circuit: if the assessor hasn't acted yet, stamp an
    # auto-resolution note so the audit log shows the MD bypassed the
    # assessor step intentionally.
    if issue.status == LevelIssueStatus.OPEN:
        issue.assessor_note = (
            "[MD short-circuit] Managing Director decided this issue directly "
            "without waiting for assessor resolution."
        )
        issue.assessor_resolved_at = now
    issue.md_user_id = actor.id
    issue.md_rationale = payload.md_rationale
    issue.md_reviewed_at = now
    issue.status = payload.decision

    # If MD approved, check whether ALL issues for this verification_result are now
    # approved/accepted. If yes, promote the level status to PASSED_WITH_MD_OVERRIDE.
    if payload.decision == LevelIssueStatus.MD_APPROVED:
        sibling_rows = (
            (
                await session.execute(
                    select(LevelIssue).where(
                        LevelIssue.verification_result_id == issue.verification_result_id
                    )
                )
            )
            .scalars()
            .all()
        )
        all_settled = all(
            s.status
            in (LevelIssueStatus.MD_APPROVED, LevelIssueStatus.MD_REJECTED)
            for s in sibling_rows
        )
        any_rejected = any(s.status == LevelIssueStatus.MD_REJECTED for s in sibling_rows)
        if all_settled and not any_rejected:
            # Use the row we already hold the lock on rather than a
            # fresh ``session.get`` — saves one round trip and keeps the
            # update bound to the locked row.
            result = vr_locked or await session.get(
                VerificationResult, issue.verification_result_id
            )
            if result is not None and result.status == VerificationLevelStatus.BLOCKED:
                result.status = VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE
    # If MD rejected, ensure the level cannot remain at PASSED_WITH_MD_OVERRIDE
    # with a rejected issue in its set. Order matters: a sibling could have
    # been MD_APPROVED first (level promoted) and only now is a sibling being
    # rejected. Without this branch the rejection silently rides under a
    # promoted level and the case proceeds incorrectly.
    elif payload.decision == LevelIssueStatus.MD_REJECTED:
        result = vr_locked or await session.get(
            VerificationResult, issue.verification_result_id
        )
        if (
            result is not None
            and result.status == VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE
        ):
            result.status = VerificationLevelStatus.BLOCKED
    await session.flush()
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="ISSUE_MD_DECIDED",
        entity_type="level_issue",
        entity_id=str(issue.id),
        before={
            "status": prior_status,
            "sub_step_id": issue.sub_step_id,
        },
        after={
            "status": issue.status.value,
            "sub_step_id": issue.sub_step_id,
            "md_rationale": payload.md_rationale,
            "case_id": str(vr_locked.case_id) if vr_locked else None,
            "level_number": vr_locked.level_number.value if vr_locked else None,
            "level_status": vr_locked.status.value if vr_locked else None,
        },
    )
    await session.commit()
    return LevelIssueRead.model_validate(issue)


# ─────────────────────────────────── MD Approvals queue ─────────────────────


@md_router.get(
    "/md-queue",
    response_model=MDQueueResponse,
)
async def md_queue(
    _actor: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO)),
    session: AsyncSession = Depends(get_session),
) -> MDQueueResponse:
    """Cross-case queue of unresolved issues for the MD / CEO.

    Returns every ``LevelIssue`` whose ``status`` is ``OPEN`` or
    ``ASSESSOR_RESOLVED`` across all cases, with enough case + level context
    embedded for the approvals UI to render without follow-up fetches. Sorted
    by severity (CRITICAL → WARNING → INFO) then ``assessor_resolved_at``
    (most recently resolved first) then ``created_at``.
    """
    latest_ids = _latest_vr_ids_subquery()
    stmt = (
        select(LevelIssue, VerificationResult, Case)
        .join(
            VerificationResult,
            LevelIssue.verification_result_id == VerificationResult.id,
        )
        .join(Case, VerificationResult.case_id == Case.id)
        .where(
            LevelIssue.status.in_(
                [LevelIssueStatus.OPEN, LevelIssueStatus.ASSESSOR_RESOLVED]
            ),
            # Only keep issues from the latest VR per (case, level). Older
            # VRs are superseded by re-runs and their issues should not
            # appear on the MD's plate.
            LevelIssue.verification_result_id.in_(latest_ids),
            # Drop issues attached to soft-deleted cases — the deletion
            # implicitly cancels any pending MD work for those cases. Without
            # this filter the approvals queue shows ghost rows for cases the
            # MD already approved for deletion, which is confusing.
            Case.is_deleted.is_(False),
        )
        .order_by(
            LevelIssue.severity.desc(),
            LevelIssue.assessor_resolved_at.desc().nulls_last(),
            LevelIssue.created_at.desc(),
        )
    )
    rows = (await session.execute(stmt)).all()

    items: list[MDQueueItem] = []
    open_count = 0
    awaiting_md = 0
    for issue, level_result, case in rows:
        if issue.status == LevelIssueStatus.OPEN:
            open_count += 1
        else:
            awaiting_md += 1
        items.append(
            MDQueueItem(
                issue=LevelIssueRead.model_validate(issue),
                case_id=case.id,
                loan_id=case.loan_id,
                applicant_name=case.applicant_name,
                co_applicant_name=case.co_applicant_name,
                loan_amount=case.loan_amount,
                level_number=level_result.level_number,
                level_status=level_result.status,
                level_completed_at=level_result.completed_at,
            )
        )

    return MDQueueResponse(
        items=items,
        total_open=open_count,
        total_awaiting_md=awaiting_md,
    )


@md_router.get(
    "/assessor-queue",
    response_model=MDQueueResponse,
)
async def assessor_queue(
    _actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.UNDERWRITER,
            UserRole.ADMIN,
            UserRole.CREDIT_HO,
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> MDQueueResponse:
    """Cross-case queue of gap-fix work for the assessor.

    Returns only ``OPEN`` issues — the pre-MD triage backlog where the
    assessor can close the gap (upload missing artifact, add a note) before
    anything reaches the MD. Reuses ``MDQueueResponse`` so the UI can share
    rendering code; ``total_awaiting_md`` is filled for informational use only
    (issues already promoted to MD aren't the assessor's job).
    """
    latest_ids = _latest_vr_ids_subquery()
    stmt = (
        select(LevelIssue, VerificationResult, Case)
        .join(
            VerificationResult,
            LevelIssue.verification_result_id == VerificationResult.id,
        )
        .join(Case, VerificationResult.case_id == Case.id)
        .where(
            LevelIssue.status == LevelIssueStatus.OPEN,
            # Only keep issues from the latest VR per (case, level) —
            # superseded re-runs should not appear on the assessor's plate.
            LevelIssue.verification_result_id.in_(latest_ids),
            # Deleted cases are off the assessor's plate — same rationale
            # as md-queue.
            Case.is_deleted.is_(False),
        )
        .order_by(
            LevelIssue.severity.desc(),
            LevelIssue.created_at.desc(),
        )
    )
    rows = (await session.execute(stmt)).all()

    items: list[MDQueueItem] = []
    for issue, level_result, case in rows:
        items.append(
            MDQueueItem(
                issue=LevelIssueRead.model_validate(issue),
                case_id=case.id,
                loan_id=case.loan_id,
                applicant_name=case.applicant_name,
                co_applicant_name=case.co_applicant_name,
                loan_amount=case.loan_amount,
                level_number=level_result.level_number,
                level_status=level_result.status,
                level_completed_at=level_result.completed_at,
            )
        )

    # How many OPEN issues have already been promoted elsewhere? We don't fetch
    # MD-bound rows so surface a second count inferred from the queue.
    return MDQueueResponse(
        items=items,
        total_open=len(items),
        total_awaiting_md=0,
    )


# ─────────────────────────── Photos + Learning endpoints ────────────────────

_PHOTO_SUBTYPES: dict[str, ArtifactSubtype] = {
    "HOUSE_VISIT_PHOTO": ArtifactSubtype.HOUSE_VISIT_PHOTO,
    "BUSINESS_PREMISES_PHOTO": ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
    "BUSINESS_PREMISES_CROP": ArtifactSubtype.BUSINESS_PREMISES_CROP,
}


@router.get(
    "/{case_id}/photos/{subtype}",
    response_model=CasePhotosResponse,
)
async def list_case_photos(
    case_id: UUID,
    subtype: str,
    _actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_dep),
) -> CasePhotosResponse:
    """List photos of a given subtype for a case with presigned download URLs.

    Used by the Verification tab to render the actual house-visit and
    business-premises photographs inline on an L3 issue, so the MD can judge
    Claude's classification visually.
    """
    await _require_case(session, case_id)
    try:
        subtype_enum = _PHOTO_SUBTYPES[subtype.upper()]
    except KeyError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported photo subtype {subtype!r}. "
            f"Supported: {list(_PHOTO_SUBTYPES)}",
        ) from exc

    stmt = (
        select(CaseArtifact)
        .where(CaseArtifact.case_id == case_id)
        .order_by(CaseArtifact.filename)
    )
    rows = (await session.execute(stmt)).scalars().all()

    out: list[CasePhotoItem] = []
    for art in rows:
        meta = art.metadata_json or {}
        if meta.get("subtype") != subtype_enum.value:
            continue
        try:
            url = await storage.generate_presigned_download_url(
                art.s3_key,
                expires_in=900,
                disposition="inline",
                filename=art.filename,
            )
        except Exception:
            continue
        out.append(
            CasePhotoItem(
                artifact_id=art.id,
                filename=art.filename,
                subtype=subtype_enum.value,
                download_url=url,
            )
        )
    return CasePhotosResponse(case_id=case_id, subtype=subtype_enum.value, items=out)


@md_router.get(
    "/precedents/{sub_step_id}",
    response_model=PrecedentsResponse,
)
async def get_precedents(
    sub_step_id: str,
    _actor: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO)),
    session: AsyncSession = Depends(get_session),
) -> PrecedentsResponse:
    """Past MD-adjudicated issues on the same ``sub_step_id`` — consistency
    context for the MD decision screen.

    Future AutoJustifier will read this endpoint to pattern-match new issues
    against past rulings and auto-suggest a decision when the MD has approved
    / rejected the same rule N times with coherent rationale.
    """
    stmt = (
        select(LevelIssue, VerificationResult, Case)
        .join(
            VerificationResult,
            LevelIssue.verification_result_id == VerificationResult.id,
        )
        .join(Case, VerificationResult.case_id == Case.id)
        .where(LevelIssue.sub_step_id == sub_step_id)
        .where(
            LevelIssue.status.in_(
                [LevelIssueStatus.MD_APPROVED, LevelIssueStatus.MD_REJECTED]
            )
        )
        .order_by(LevelIssue.md_reviewed_at.desc().nulls_last())
    )
    rows = (await session.execute(stmt)).all()
    # Dedupe per (case_id, decision): when the same rule has fired multiple
    # times on the same loan (level re-runs, multiple sibling issues with
    # near-identical rationale, test fixtures), the MD doesn't need to see
    # the same precedent 12 times — it just hides the genuinely-novel
    # precedents below the "+N hidden" cutoff. Keep only the most recent
    # decision per (case_id, decision) tuple; the SQL ordered by
    # md_reviewed_at DESC, so the first row we see for each tuple is the
    # one to keep. Counts include every original row so the
    # "12 approved · 0 rejected" headline still reflects reality.
    items: list[PrecedentItem] = []
    seen: set[tuple[Any, str]] = set()
    approved = 0
    rejected = 0
    for issue, _lr, case in rows:
        # [CASE_SPECIFIC] approvals are intentionally excluded — the MD marked
        # them as one-off decisions that should NOT inform future rulings.
        if issue.md_rationale and issue.md_rationale.startswith("[CASE_SPECIFIC]"):
            continue
        if issue.status == LevelIssueStatus.MD_APPROVED:
            approved += 1
        else:
            rejected += 1
        dedupe_key = (case.id, issue.status.value)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            PrecedentItem(
                issue_id=issue.id,
                case_id=case.id,
                loan_id=case.loan_id,
                applicant_name=case.applicant_name,
                sub_step_id=issue.sub_step_id,
                severity=issue.severity.value,
                decision=issue.status.value,
                md_rationale=issue.md_rationale,
                md_reviewed_at=issue.md_reviewed_at,
            )
        )
    return PrecedentsResponse(
        sub_step_id=sub_step_id,
        items=items,
        approved_count=approved,
        rejected_count=rejected,
    )


# ── Final verdict report ─────────────────────────────────────────────────────


@router.get(
    "/{case_id}/final-report",
    response_model=None,  # returns PDF bytes or JSON error
)
async def download_final_report(
    case_id: UUID,
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Download the 32-point Final Verdict Report as a PDF.

    Gate: every LevelIssue across all 6 levels must be in a *settled* state
    (MD_APPROVED / MD_REJECTED — the AI auto-justifier or a human MD is
    acceptable) before the report can be generated. If any OPEN or
    ASSESSOR_RESOLVED issue remains, responds 409 with the blocking list so
    the UI can render a clear "resolve these first" message.
    """
    from fastapi.responses import JSONResponse, Response

    from app.models.decision_result import DecisionResult
    from app.models.decision_step import DecisionStep
    from app.verification.services.report_generator import (
        DecisioningBrief,
        DecisioningStepBrief,
        FinalReportData,
        IssueLifecycle,
        LevelBrief,
        generate_final_report,
    )

    case = await _require_case(session, case_id)

    # Pull every verification_result + its issues
    results = (
        (
            await session.execute(
                select(VerificationResult)
                .where(VerificationResult.case_id == case_id)
                .order_by(VerificationResult.level_number, VerificationResult.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    # Keep only the *latest* result per level_number.
    latest: dict[VerificationLevelNumber, VerificationResult] = {}
    for r in results:
        latest.setdefault(r.level_number, r)

    if not latest:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "error": "gate_not_run",
                "message": (
                    "No verification levels have been run on this case yet. "
                    "Run L1 → L5 before requesting the final report."
                ),
                "blocking": [],
            },
        )

    issues_by_rid: dict[UUID, list[LevelIssue]] = {}
    if latest:
        iss_rows = (
            (
                await session.execute(
                    select(LevelIssue).where(
                        LevelIssue.verification_result_id.in_(
                            [r.id for r in latest.values()]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for iss in iss_rows:
            issues_by_rid.setdefault(iss.verification_result_id, []).append(iss)

    # Gate: every issue across every level must be MD_APPROVED / MD_REJECTED.
    unresolved: list[dict[str, str]] = []
    for rid, issues in issues_by_rid.items():
        for iss in issues:
            if iss.status not in (
                LevelIssueStatus.MD_APPROVED,
                LevelIssueStatus.MD_REJECTED,
            ):
                unresolved.append(
                    {
                        "sub_step_id": iss.sub_step_id,
                        "status": iss.status.value,
                        "severity": iss.severity.value,
                        "description": (iss.description or "")[:200],
                    }
                )
    if unresolved:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "gate_open",
                "message": (
                    f"{len(unresolved)} issue(s) still need adjudication before the "
                    "final verdict report can be generated. Resolve each one "
                    "manually or let the AI auto-justifier clear them."
                ),
                "blocking": unresolved,
            },
        )

    # Also require L5 to have been run at least once.
    l5 = latest.get(VerificationLevelNumber.L5_SCORING)
    if l5 is None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "l5_not_run",
                "message": (
                    "L5 (32-point scoring) has not been run for this case. "
                    "Trigger L5 before requesting the final report."
                ),
                "blocking": [],
            },
        )

    # ── Assemble the report data ─────────────────────────────────────────
    scoring = (l5.sub_step_results or {}).get("scoring") or {}

    level_titles: dict[VerificationLevelNumber, str] = {
        VerificationLevelNumber.L1_ADDRESS: "Address verification",
        VerificationLevelNumber.L1_5_CREDIT: "Credit history — willful-default + fraud",
        VerificationLevelNumber.L2_BANKING: "Banking — CA-grade cashflow read",
        VerificationLevelNumber.L3_VISION: "Vision — house + business premises",
        VerificationLevelNumber.L4_AGREEMENT: "Agreement — annexure + hypothecation",
        VerificationLevelNumber.L5_SCORING: "Final 32-point audit",
        VerificationLevelNumber.L5_5_DEDUPE_TVR: "Dedupe + TVR + NACH + PDC presence",
    }
    ordered_levels = [
        VerificationLevelNumber.L1_ADDRESS,
        VerificationLevelNumber.L1_5_CREDIT,
        VerificationLevelNumber.L2_BANKING,
        VerificationLevelNumber.L3_VISION,
        VerificationLevelNumber.L4_AGREEMENT,
        VerificationLevelNumber.L5_SCORING,
        VerificationLevelNumber.L5_5_DEDUPE_TVR,
    ]
    briefs: list[LevelBrief] = []
    lifecycle: list[IssueLifecycle] = []
    for ln in ordered_levels:
        r = latest.get(ln)
        if r is None:
            continue
        iss = issues_by_rid.get(r.id) or []
        crit = sum(
            1
            for i in iss
            if i.severity.value == "CRITICAL"
            and i.status.value not in ("MD_APPROVED", "MD_REJECTED")
        )
        warn = sum(
            1
            for i in iss
            if i.severity.value == "WARNING"
            and i.status.value not in ("MD_APPROVED", "MD_REJECTED")
        )
        md_app = sum(1 for i in iss if i.status == LevelIssueStatus.MD_APPROVED)
        md_rej = sum(1 for i in iss if i.status == LevelIssueStatus.MD_REJECTED)
        briefs.append(
            LevelBrief(
                level_number=ln.value,
                title=level_titles[ln],
                status=r.status.value,
                cost_usd=float(r.cost_usd or 0),
                issue_count=len(iss),
                critical_unresolved=crit,
                warning_unresolved=warn,
                md_approved_count=md_app,
                md_rejected_count=md_rej,
            )
        )
        for i in iss:
            rationale = i.md_rationale or ""
            is_ai = rationale.startswith("[AI auto-justified")
            if is_ai:
                decided_by = "ai"
            elif i.md_user_id is not None:
                decided_by = "md"
            elif i.assessor_user_id is not None:
                decided_by = "assessor"
            else:
                decided_by = "system"
            lifecycle.append(
                IssueLifecycle(
                    sub_step_id=i.sub_step_id,
                    level_number=ln.value,
                    severity=i.severity.value,
                    description=(i.description or "")[:240],
                    raised_at=(
                        i.created_at.isoformat() if i.created_at else ""
                    ),
                    assessor_resolved_at=(
                        i.assessor_resolved_at.isoformat()
                        if i.assessor_resolved_at
                        else ""
                    ),
                    assessor_note=i.assessor_note or "",
                    md_reviewed_at=(
                        i.md_reviewed_at.isoformat()
                        if i.md_reviewed_at
                        else ""
                    ),
                    md_decision=i.status.value,
                    md_rationale=rationale,
                    actor=decided_by,
                )
            )

    # Chronological by raised time so the audit trail reads top-to-bottom in
    # the order the engine surfaced concerns.
    lifecycle.sort(key=lambda x: x.raised_at or "")

    # Overall verdict: if any level is BLOCKED/FAILED → REJECT; if all
    # passed (with or without override) → APPROVE; else APPROVE_WITH_CONDITIONS.
    # This is the *gate-only* heuristic — overridden below by L6 if available.
    statuses = [b.status for b in briefs]
    if any(s in ("BLOCKED", "FAILED") for s in statuses):
        final_verdict = "REJECT"
    elif all(
        s in ("PASSED", "PASSED_WITH_MD_OVERRIDE") for s in statuses
    ):
        final_verdict = (
            "APPROVE"
            if all(s == "PASSED" for s in statuses)
            else "APPROVE_WITH_CONDITIONS"
        )
    else:
        final_verdict = "APPROVE_WITH_CONDITIONS"

    # ── L6 decisioning — fetch latest DecisionResult + its 11 steps ────
    decisioning_brief: DecisioningBrief | None = None
    dr = (
        await session.execute(
            select(DecisionResult)
            .where(DecisionResult.case_id == case_id)
            .order_by(DecisionResult.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if dr is not None:
        step_rows = (
            (
                await session.execute(
                    select(DecisionStep)
                    .where(DecisionStep.decision_result_id == dr.id)
                    .order_by(DecisionStep.step_number)
                )
            )
            .scalars()
            .all()
        )

        def _step_summary(s: DecisionStep) -> str:
            """One-line gist of a decisioning step output for the report
            table. Each step's `output_data` shape is different — pick the
            most useful field per common pattern."""
            o = s.output_data or {}
            if not isinstance(o, dict):
                return ""
            for key in (
                "verdict",
                "decision",
                "summary",
                "narrative",
                "detail",
                "skipped_reason",
                "passed_all",
            ):
                v = o.get(key)
                if isinstance(v, bool):
                    return f"{key}: {v}"
                if isinstance(v, str) and v.strip():
                    return v.strip()
            # Last resort: stringify a clipped JSON.
            try:
                return str(o)[:240]
            except Exception:  # noqa: BLE001
                return ""

        steps_brief = [
            DecisioningStepBrief(
                step_number=int(s.step_number),
                step_name=s.step_name,
                status=s.status.value if hasattr(s.status, "value") else str(s.status),
                model_used=s.model_used,
                cost_usd=float(s.cost_usd or 0),
                summary=_step_summary(s),
            )
            for s in step_rows
        ]

        # Pros / cons may live as either flat list[str] or list[{text, citations}]
        # depending on which step path produced them — normalise both.
        def _flatten_text_list(blob: Any) -> list[str]:
            if blob is None:
                return []
            if isinstance(blob, list):
                out: list[str] = []
                for item in blob:
                    if isinstance(item, str):
                        out.append(item)
                    elif isinstance(item, dict):
                        text = item.get("text") or item.get("description") or ""
                        if text:
                            out.append(str(text))
                return out
            return []

        pros_cons = dr.pros_cons or {}
        pros = _flatten_text_list(pros_cons.get("pros") if isinstance(pros_cons, dict) else None)
        cons = _flatten_text_list(pros_cons.get("cons") if isinstance(pros_cons, dict) else None)
        conditions = _flatten_text_list(dr.conditions if isinstance(dr.conditions, list) else None)
        if not conditions and isinstance(dr.conditions, dict):
            conditions = _flatten_text_list(dr.conditions.get("items"))

        # Deviations: list of {name, severity, justification}
        deviations_raw = dr.deviations or []
        if isinstance(deviations_raw, dict):
            deviations_raw = deviations_raw.get("items") or []
        dev_lines: list[str] = []
        for d_item in deviations_raw if isinstance(deviations_raw, list) else []:
            if isinstance(d_item, dict):
                name = d_item.get("name") or d_item.get("policy_rule") or "deviation"
                sev = d_item.get("severity") or "?"
                just = d_item.get("justification") or d_item.get("reason") or ""
                dev_lines.append(f"<b>{name}</b> (severity: {sev}) — {just}")
            elif isinstance(d_item, str):
                dev_lines.append(d_item)

        risk_summary_lines: list[str] = []
        rs = dr.risk_summary
        if isinstance(rs, list):
            risk_summary_lines = [str(x) for x in rs if x]
        elif isinstance(rs, dict):
            risk_summary_lines = [
                f"<b>{k}</b>: {v}" for k, v in rs.items() if v
            ]

        decisioning_brief = DecisioningBrief(
            status=dr.status.value if hasattr(dr.status, "value") else str(dr.status),
            final_decision=(
                dr.final_decision.value if dr.final_decision else None
            ),
            recommended_amount=int(dr.recommended_amount) if dr.recommended_amount else None,
            recommended_tenure=int(dr.recommended_tenure) if dr.recommended_tenure else None,
            confidence_score=int(dr.confidence_score) if dr.confidence_score is not None else None,
            reasoning_markdown=dr.reasoning_markdown or "",
            pros=pros,
            cons=cons,
            conditions=conditions,
            deviations=dev_lines,
            risk_summary_lines=risk_summary_lines,
            total_cost_usd=float(dr.total_cost_usd or 0),
            started_at=dr.created_at.isoformat() if dr.created_at else "",
            completed_at=dr.updated_at.isoformat() if dr.updated_at else "",
            steps=steps_brief,
        )

        # Override the cover verdict with the actual L6 decision when present.
        if decisioning_brief.final_decision:
            final_verdict = decisioning_brief.final_decision

    data = FinalReportData(
        case_id=str(case.id),
        loan_id=case.loan_id,
        applicant_name=case.applicant_name or "—",
        co_applicant_name=case.co_applicant_name,
        loan_amount_inr=int(case.loan_amount) if case.loan_amount else None,
        tenure_months=case.loan_tenure_months,
        uploaded_at=case.created_at.isoformat() if case.created_at else "",
        overall_pct=float(scoring.get("overall_pct") or 0),
        earned=int(scoring.get("earned_score") or 0),
        max_score=int(scoring.get("max_score") or 100),
        grade=str(scoring.get("grade") or "—"),
        eb_verdict=str(scoring.get("eb_verdict") or "PASS"),
        sections=list(scoring.get("sections") or []),
        levels=briefs,
        issue_lifecycle=lifecycle,
        decisioning=decisioning_brief,
        generated_by_email=actor.email or "",
        final_verdict=final_verdict,
        final_verdict_notes=(
            f"{sum(b.md_approved_count for b in briefs)} issue(s) cleared via MD "
            f"approval (including AI auto-justification); "
            f"{sum(b.md_rejected_count for b in briefs)} rejection(s) on file."
        ),
    )
    try:
        pdf_bytes = generate_final_report(data)
    except Exception as exc:  # noqa: BLE001 — surface the failure to the UI
        _log.exception(
            "Final report rendering failed for case %s (loan %s)",
            case.id,
            case.loan_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "render_failed",
                "message": (
                    "PDF rendering failed: "
                    f"{type(exc).__name__}: {str(exc)[:200]}. "
                    "The gate is clear and all concerns are settled — this is a "
                    "renderer bug. Engineering has been notified via the server "
                    "log; retry in a minute or download the audit log tab as a "
                    "fallback."
                ),
                "blocking": [],
            },
        )

    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="FINAL_REPORT_DOWNLOADED",
        entity_type="case",
        entity_id=str(case.id),
        after={
            "loan_id": case.loan_id,
            "grade": data.grade,
            "verdict": data.final_verdict,
        },
    )
    await session.commit()

    filename = f"PFL-Final-Report-{case.loan_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
