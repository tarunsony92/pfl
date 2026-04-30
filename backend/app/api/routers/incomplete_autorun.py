"""Endpoints powering the auto-run completeness gate.

  GET   /cases/{case_id}/missing-required-artifacts
        → list missing required artefacts for the case (used by the FE
          before posting an auto-run trigger so the user can be prompted
          to upload them)

  POST  /cases/{case_id}/incomplete-autorun-log
        → record an auto-run started while artefacts were still missing
          (the user "skipped" the gate)

  GET   /admin/incomplete-autorun-logs
        → list defaulter entries (admin sidebar tab)
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_role
from app.enums import UserRole
from app.models.case import Case
from app.models.incomplete_autorun_log import IncompleteAutorunLog
from app.models.user import User
from app.services.case_completeness import compute_missing_required_artifacts


case_router = APIRouter(prefix="/cases", tags=["case-completeness"])
admin_router = APIRouter(prefix="/admin", tags=["admin-incomplete-autorun"])


class MissingArtifactRead(BaseModel):
    subtype: str
    label: str
    optional_alternatives: list[str] | None = None


class MissingArtifactsResponse(BaseModel):
    case_id: UUID
    missing: list[MissingArtifactRead]
    is_complete: bool


@case_router.get(
    "/{case_id}/missing-required-artifacts",
    response_model=MissingArtifactsResponse,
)
async def list_missing_artifacts(
    case_id: UUID,
    actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.ADMIN,
            UserRole.UNDERWRITER,
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> MissingArtifactsResponse:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    missing = await compute_missing_required_artifacts(session, case_id)
    return MissingArtifactsResponse(
        case_id=case_id,
        missing=[MissingArtifactRead(**m.to_dict()) for m in missing],
        is_complete=not missing,
    )


class IncompleteAutorunLogCreate(BaseModel):
    missing_subtypes: list[str] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=500)


class IncompleteAutorunLogRead(BaseModel):
    id: UUID
    case_id: UUID
    user_id: UUID
    user_email: str | None = None
    user_full_name: str | None = None
    case_loan_id: str | None = None
    case_applicant_name: str | None = None
    missing_subtypes: list[str]
    reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True


@case_router.post(
    "/{case_id}/incomplete-autorun-log",
    response_model=IncompleteAutorunLogRead,
    status_code=status.HTTP_201_CREATED,
)
async def record_incomplete_autorun(
    case_id: UUID,
    payload: IncompleteAutorunLogCreate,
    actor: User = Depends(
        require_role(
            UserRole.AI_ANALYSER,
            UserRole.ADMIN,
            UserRole.UNDERWRITER,
        )
    ),
    session: AsyncSession = Depends(get_session),
) -> IncompleteAutorunLogRead:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    row = IncompleteAutorunLog(
        case_id=case_id,
        user_id=actor.id,
        missing_subtypes=list(payload.missing_subtypes or []),
        reason=(payload.reason or None),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return IncompleteAutorunLogRead(
        id=row.id,
        case_id=row.case_id,
        user_id=row.user_id,
        user_email=actor.email,
        user_full_name=getattr(actor, "full_name", None),
        case_loan_id=getattr(case, "loan_id", None),
        case_applicant_name=getattr(case, "applicant_name", None),
        missing_subtypes=row.missing_subtypes,
        reason=row.reason,
        created_at=row.created_at,
    )


@admin_router.get(
    "/incomplete-autorun-logs",
    response_model=list[IncompleteAutorunLogRead],
)
async def list_incomplete_autorun_logs(
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO)),
    session: AsyncSession = Depends(get_session),
    limit: int = 200,
    offset: int = 0,
) -> list[IncompleteAutorunLogRead]:
    """Return defaulter rows joined with user + case context, newest first."""
    stmt = (
        select(IncompleteAutorunLog, User, Case)
        .join(User, User.id == IncompleteAutorunLog.user_id)
        .join(Case, Case.id == IncompleteAutorunLog.case_id)
        .order_by(desc(IncompleteAutorunLog.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    return [
        IncompleteAutorunLogRead(
            id=log.id,
            case_id=log.case_id,
            user_id=log.user_id,
            user_email=user.email,
            user_full_name=getattr(user, "full_name", None),
            case_loan_id=getattr(case, "loan_id", None),
            case_applicant_name=getattr(case, "applicant_name", None),
            missing_subtypes=log.missing_subtypes,
            reason=log.reason,
            created_at=log.created_at,
        )
        for log, user, case in rows
    ]
