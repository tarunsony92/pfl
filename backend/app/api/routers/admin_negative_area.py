"""Admin endpoints to manage the negative-area pincode list.

  GET    /admin/negative-areas?active_only=true       → list pincodes
  POST   /admin/negative-areas                        → add single pincode
  POST   /admin/negative-areas/bulk                   → add many pincodes at once
  PATCH  /admin/negative-areas/{id}                   → toggle active / edit reason
  DELETE /admin/negative-areas/{id}                   → remove permanently

L5 rule #11 (negative_area_check) reads the active rows here. Admins curate the
list; the scoring rubric reads it on every L5 run.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_role
from app.enums import UserRole
from app.models.negative_area_pincode import NegativeAreaPincode
from app.models.user import User

router = APIRouter(prefix="/admin/negative-areas", tags=["admin-negative-area"])

_PINCODE_RE = re.compile(r"^\d{6}$")


class NegativeAreaRead(BaseModel):
    id: UUID
    pincode: str
    reason: str | None
    source: str
    is_active: bool
    uploaded_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NegativeAreaCreate(BaseModel):
    pincode: str = Field(..., min_length=6, max_length=6)
    reason: str | None = None
    source: str = "manual"


class NegativeAreaPatch(BaseModel):
    is_active: bool | None = None
    reason: str | None = None


class BulkUploadRequest(BaseModel):
    pincodes: list[str]
    reason: str | None = None
    source: str = "bulk_upload"


class BulkUploadResponse(BaseModel):
    inserted: int
    skipped_duplicates: int
    skipped_invalid: list[str]


def _validate_pincode(pincode: str) -> str:
    p = pincode.strip()
    if not _PINCODE_RE.match(p):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid pincode {pincode!r} — must be exactly 6 digits.",
        )
    return p


@router.get("", response_model=list[NegativeAreaRead])
async def list_negative_areas(
    active_only: bool = False,
    _actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> list[NegativeAreaPincode]:
    stmt = select(NegativeAreaPincode).order_by(desc(NegativeAreaPincode.created_at))
    if active_only:
        stmt = stmt.where(NegativeAreaPincode.is_active.is_(True))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


@router.post("", response_model=NegativeAreaRead, status_code=status.HTTP_201_CREATED)
async def create_negative_area(
    body: NegativeAreaCreate,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> NegativeAreaPincode:
    pincode = _validate_pincode(body.pincode)
    existing = (
        await session.execute(
            select(NegativeAreaPincode).where(NegativeAreaPincode.pincode == pincode)
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Pincode {pincode} already exists in the negative-area list.",
        )
    row = NegativeAreaPincode(
        pincode=pincode,
        reason=body.reason,
        source=body.source,
        is_active=True,
        uploaded_by_user_id=actor.id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.post("/bulk", response_model=BulkUploadResponse)
async def bulk_upload(
    body: BulkUploadRequest,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> BulkUploadResponse:
    """Insert many pincodes at once. Duplicates and malformed entries are skipped
    silently — the response counts each bucket so the admin can see what landed."""
    inserted = 0
    skipped_duplicates = 0
    skipped_invalid: list[str] = []

    # Pull existing once to dedupe in-memory
    existing_set = {
        p for (p,) in (
            await session.execute(select(NegativeAreaPincode.pincode))
        ).all()
    }

    seen_in_batch: set[str] = set()
    for raw in body.pincodes:
        p = raw.strip()
        if not _PINCODE_RE.match(p):
            skipped_invalid.append(raw)
            continue
        if p in existing_set or p in seen_in_batch:
            skipped_duplicates += 1
            continue
        seen_in_batch.add(p)
        session.add(
            NegativeAreaPincode(
                pincode=p,
                reason=body.reason,
                source=body.source,
                is_active=True,
                uploaded_by_user_id=actor.id,
            )
        )
        inserted += 1

    await session.commit()
    return BulkUploadResponse(
        inserted=inserted,
        skipped_duplicates=skipped_duplicates,
        skipped_invalid=skipped_invalid,
    )


@router.patch("/{entry_id}", response_model=NegativeAreaRead)
async def patch_negative_area(
    entry_id: UUID,
    body: NegativeAreaPatch,
    _actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> NegativeAreaPincode:
    row = await session.get(NegativeAreaPincode, entry_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.reason is not None:
        row.reason = body.reason
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{entry_id}")
async def delete_negative_area(
    entry_id: UUID,
    _actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    row = await session.get(NegativeAreaPincode, entry_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    await session.delete(row)
    await session.commit()
    return {"ok": True}
