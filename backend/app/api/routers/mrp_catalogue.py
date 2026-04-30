"""Admin CRUD endpoints for the MRP catalogue.

The catalogue is the canonical Maximum Retail Price table used by the L3
vision scorers when valuing per-item business stock. Operators can curate
entries by hand here, or accept entries auto-upserted by the L3 pipeline
(``svc.upsert_from_ai`` in the worker). All endpoints sit behind the
ADMIN / UNDERWRITER role gate.

  GET    /admin/mrp-catalogue            → paged list, optional business-type filter
  POST   /admin/mrp-catalogue            → manual entry create
  PATCH  /admin/mrp-catalogue/{id}       → edit MRP / description / category / rationale
  DELETE /admin/mrp-catalogue/{id}       → 204 on success, 404 if missing
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_role
from app.enums import UserRole
from app.models.user import User
from app.services import mrp_catalogue as svc

router = APIRouter(prefix="/admin/mrp-catalogue", tags=["mrp-catalogue"])

_ADMIN = require_role(UserRole.ADMIN, UserRole.UNDERWRITER)


class MrpEntryRead(BaseModel):
    """Wire shape returned to the admin UI for one catalogue row.

    Mirrors :class:`app.models.mrp_catalogue_entry.MrpCatalogueEntry` plus
    a stringified ``updated_at`` so the FE doesn't have to reformat. The
    ``source`` and ``observed_count`` columns expose whether the row came
    from a manual edit or AI auto-upsert and how often the L3 scorers
    have hit it.
    """

    id: UUID
    business_type: str
    item_canonical: str
    item_description: str
    category: str
    mrp_inr: int
    source: str
    confidence: str | None
    rationale: str | None
    observed_count: int
    updated_at: str
    updated_by_user_id: UUID | None

    model_config = {"from_attributes": True}


class MrpEntryCreate(BaseModel):
    """Payload for ``POST /admin/mrp-catalogue`` (manual create).

    ``category`` is constrained to the four buckets the L3 scorers
    recognise; anything else would silently fail the catalogue lookup.
    """

    business_type: str = Field(..., min_length=1, max_length=64)
    item_description: str = Field(..., min_length=1, max_length=512)
    category: str = Field(..., pattern=r"^(equipment|stock|consumable|other)$")
    mrp_inr: int = Field(..., ge=1)
    rationale: str | None = Field(default=None, max_length=512)


class MrpEntryUpdate(BaseModel):
    """Partial update payload for ``PATCH /admin/mrp-catalogue/{id}``.

    Every field is optional — operators usually adjust just the price
    after observing market drift. Whichever fields are ``None`` are left
    untouched by the service layer.
    """

    mrp_inr: int | None = Field(default=None, ge=1)
    item_description: str | None = Field(default=None, max_length=512)
    category: str | None = Field(
        default=None, pattern=r"^(equipment|stock|consumable|other)$"
    )
    rationale: str | None = Field(default=None, max_length=512)


def _to_read(entry: Any) -> MrpEntryRead:
    """ORM row → wire shape. Isolated so endpoints stay declarative."""
    return MrpEntryRead(
        id=entry.id,
        business_type=entry.business_type,
        item_canonical=entry.item_canonical,
        item_description=entry.item_description,
        category=entry.category,
        mrp_inr=entry.mrp_inr,
        source=entry.source,
        confidence=entry.confidence,
        rationale=entry.rationale,
        observed_count=entry.observed_count,
        updated_at=entry.updated_at.isoformat(),
        updated_by_user_id=entry.updated_by_user_id,
    )


@router.get("", response_model=list[MrpEntryRead])
async def list_(
    business_type: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
) -> list[MrpEntryRead]:
    """List catalogue entries, optionally filtered by ``business_type``.

    Pagination is via ``limit`` + ``offset``. The default 500-row limit
    is roomy enough that a single request returns the full catalogue for
    every business type currently in production.
    """
    rows = await svc.list_entries(
        session, business_type=business_type, limit=limit, offset=offset
    )
    return [_to_read(r) for r in rows]


@router.post(
    "", response_model=MrpEntryRead, status_code=status.HTTP_201_CREATED
)
async def create(
    body: MrpEntryCreate,
    actor: User = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
) -> MrpEntryRead:
    """Manually create a catalogue entry.

    Returns 400 if the canonicalised ``(business_type, item)`` already
    exists — the service layer raises ``ValueError`` and we map that to
    HTTP semantics here so the FE can surface a friendly conflict toast.
    """
    try:
        entry = await svc.create_manual(
            session,
            business_type=body.business_type,
            item_description=body.item_description,
            category=body.category,
            mrp_inr=body.mrp_inr,
            rationale=body.rationale,
            actor_user_id=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return _to_read(entry)


@router.patch("/{entry_id}", response_model=MrpEntryRead)
async def update(
    entry_id: UUID,
    body: MrpEntryUpdate,
    actor: User = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
) -> MrpEntryRead:
    """Patch one catalogue entry; only the supplied fields are touched.

    Used by the admin "Edit MRP" inline form. ``actor.id`` is recorded on
    the row so we can show "last edited by X" in the audit trail.
    """
    entry = await svc.update_entry(
        session,
        entry_id=entry_id,
        actor_user_id=actor.id,
        mrp_inr=body.mrp_inr,
        item_description=body.item_description,
        category=body.category,
        rationale=body.rationale,
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    await session.commit()
    return _to_read(entry)


@router.delete("/{entry_id}")
async def delete_(
    entry_id: UUID,
    actor: User = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Hard-delete a catalogue entry. Returns 204 on success, 404 if missing.

    Note: deletion does NOT cascade into past L3 evidence — historic case
    runs continue to reference the (now-deleted) MRP row by frozen value.
    """
    ok = await svc.delete_entry(session, entry_id=entry_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
