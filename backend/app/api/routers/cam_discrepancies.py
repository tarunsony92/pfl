"""CAM discrepancy + SystemCam-edit approval endpoints.

Mounted under /cases/{case_id}/cam-discrepancies/* and
/cases/{case_id}/system-cam-edit-requests/*.

Permissions (per user domain rule):
- View: any authenticated user who can view the case.
- Resolve (including filing a SystemCam edit request): ai_analyser or admin.
- Approve / reject a SystemCam edit request: admin or ceo only.

Phase 1 gate lives in cases.py; this router only surfaces + mutates
discrepancy state.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db import get_session
from app.enums import UserRole
from app.models.case import Case
from app.models.user import User
from app.schemas.cam_discrepancy import (
    CamDiscrepancyResolutionRead,
    CamDiscrepancyResolveRequest,
    CamDiscrepancySummary,
    SystemCamEditDecisionRequest,
    SystemCamEditRequestRead,
)
from app.services import audit as audit_svc
from app.services.cam_discrepancy import (
    DiscrepancyError,
    DiscrepancyNotFound,
    InvalidResolutionPayload,
    decide_edit_request,
    get_summary,
    render_markdown_report,
    upsert_resolution,
)

router = APIRouter(prefix="/cases", tags=["cam-discrepancies"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _load_case_or_404(session: AsyncSession, case_id: UUID) -> Case:
    case = await session.get(Case, case_id)
    if case is None or case.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get(
    "/{case_id}/cam-discrepancies",
    response_model=CamDiscrepancySummary,
)
async def list_cam_discrepancies(
    case_id: UUID,
    actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.ADMIN,
            UserRole.CREDIT_HO,
            UserRole.CEO,
            UserRole.UNDERWRITER,
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> CamDiscrepancySummary:
    await _load_case_or_404(session, case_id)
    return await get_summary(session, case_id)


@router.get(
    "/{case_id}/cam-discrepancies/report",
    response_class=PlainTextResponse,
)
async def cam_discrepancy_report_markdown(
    case_id: UUID,
    actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.ADMIN,
            UserRole.CREDIT_HO,
            UserRole.CEO,
            UserRole.UNDERWRITER,
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Markdown audit-trail report for the case."""
    case = await _load_case_or_404(session, case_id)
    summary = await get_summary(session, case_id)
    md = render_markdown_report(summary, case_loan_id=case.loan_id)
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{case.loan_id}_cam_discrepancy_report.md"'
            ),
        },
    )


@router.get("/{case_id}/cam-discrepancies/report.xlsx")
async def cam_discrepancy_report_xlsx(
    case_id: UUID,
    actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.ADMIN,
            UserRole.CREDIT_HO,
            UserRole.CEO,
            UserRole.UNDERWRITER,
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """XLSX audit-trail report — two-sheet workbook (Summary + Details)
    with severity-coloured rows and column widths pre-set for review.
    """
    from io import BytesIO

    from app.services.cam_discrepancy_report import build_xlsx

    case = await _load_case_or_404(session, case_id)
    summary = await get_summary(session, case_id)
    data = build_xlsx(summary, case_loan_id=case.loan_id)
    return StreamingResponse(
        BytesIO(data),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{case.loan_id}_cam_discrepancy_report.xlsx"'
            ),
        },
    )


# ---------------------------------------------------------------------------
# Write — resolve a discrepancy
# ---------------------------------------------------------------------------


@router.post(
    "/{case_id}/cam-discrepancies/{field_key}/resolve",
    response_model=CamDiscrepancyResolutionRead,
)
async def resolve_cam_discrepancy(
    case_id: UUID,
    field_key: str,
    payload: CamDiscrepancyResolveRequest,
    actor: User = Depends(require_role(UserRole.AI_ANALYSER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> CamDiscrepancyResolutionRead:
    await _load_case_or_404(session, case_id)
    try:
        resolution, edit_req = await upsert_resolution(
            session,
            case_id=case_id,
            field_key=field_key,
            actor=actor,
            payload=payload,
        )
    except DiscrepancyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidResolutionPayload as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DiscrepancyError as exc:  # safety net
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    after_log = {
        "field_key": field_key,
        "kind": payload.kind.value,
        "comment_length": len(payload.comment),
    }
    if edit_req is not None:
        after_log["edit_request_id"] = str(edit_req.id)
    await audit_svc.log_action(
        session=session,
        actor_user_id=actor.id,
        action="cam_discrepancy.resolved",
        entity_type="cam_discrepancy_resolution",
        entity_id=str(resolution.id),
        after=after_log,
    )
    await session.commit()
    await session.refresh(resolution)
    return CamDiscrepancyResolutionRead.model_validate(resolution)


# ---------------------------------------------------------------------------
# SystemCam edit approval flow
# ---------------------------------------------------------------------------


@router.get(
    "/{case_id}/system-cam-edit-requests",
    response_model=list[SystemCamEditRequestRead],
)
async def list_system_cam_edit_requests(
    case_id: UUID,
    actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.ADMIN,
            UserRole.CREDIT_HO,
            UserRole.CEO,
            UserRole.UNDERWRITER,
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> list[SystemCamEditRequestRead]:
    from sqlalchemy import select

    from app.models.system_cam_edit_request import SystemCamEditRequest

    await _load_case_or_404(session, case_id)
    result = await session.execute(
        select(SystemCamEditRequest)
        .where(SystemCamEditRequest.case_id == case_id)
        .order_by(SystemCamEditRequest.requested_at.desc())
    )
    return [SystemCamEditRequestRead.model_validate(r) for r in result.scalars()]


@router.post(
    "/{case_id}/system-cam-edit-requests/{request_id}/decide",
    response_model=SystemCamEditRequestRead,
)
async def decide_system_cam_edit_request(
    case_id: UUID,
    request_id: UUID,
    payload: SystemCamEditDecisionRequest,
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO)),
    session: AsyncSession = Depends(get_session),
) -> SystemCamEditRequestRead:
    await _load_case_or_404(session, case_id)
    try:
        req = await decide_edit_request(
            session,
            request_id=request_id,
            approver=actor,
            payload=payload,
        )
    except DiscrepancyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidResolutionPayload as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if req.case_id != case_id:
        # Guard against cross-case tampering via path mismatch
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Request does not belong to the given case",
        )

    await audit_svc.log_action(
        session=session,
        actor_user_id=actor.id,
        action=(
            "system_cam_edit_request.approved"
            if payload.approve
            else "system_cam_edit_request.rejected"
        ),
        entity_type="system_cam_edit_request",
        entity_id=str(req.id),
        after={
            "field_key": req.field_key,
            "requested_value": req.requested_system_cam_value,
            "decision_comment_length": len(payload.decision_comment),
        },
    )
    await session.commit()
    await session.refresh(req)
    return SystemCamEditRequestRead.model_validate(req)
