"""Notifications router — surfaces actionable issues for the Topbar bell.

GET /notifications — computes the current issue list on demand. Every
notification points at a specific case + tab, so the frontend can
navigate the user straight to the fix.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_session
from app.models.user import User
from app.services.notifications import list_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationRead(BaseModel):
    id: str
    case_id: UUID
    loan_id: str
    applicant_name: str | None
    kind: str
    severity: str
    title: str
    description: str
    action_label: str
    action_tab: str
    created_at: datetime


class NotificationListResponse(BaseModel):
    total: int
    critical: int
    warning: int
    notifications: list[NotificationRead]


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    actor: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationListResponse:
    notifs = await list_notifications(session)
    return NotificationListResponse(
        total=len(notifs),
        critical=sum(1 for n in notifs if n.severity == "CRITICAL"),
        warning=sum(1 for n in notifs if n.severity == "WARNING"),
        notifications=[NotificationRead(**n.as_dict()) for n in notifs],
    )
