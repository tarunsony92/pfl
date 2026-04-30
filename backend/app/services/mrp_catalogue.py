"""CRUD + lookup/upsert helpers for the MRP catalogue.

Used by:
  - The admin API (CRUD endpoints)
  - The L3 orchestrator (lookup-or-insert when the scorer surfaces a
    new item)
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mrp_catalogue_entry import MrpCatalogueEntry

_CANONICALISE_RE = re.compile(r"[^a-z0-9]+")


def canonicalise(description: str) -> str:
    """Normalise a free-text item description to a snake_case key.
    'Barber Chair (Hydraulic)' -> 'barber_chair_hydraulic'.
    Drops parentheses, slashes, dashes; collapses runs of non-alnum
    into single underscores; strips leading/trailing underscores.
    """
    s = _CANONICALISE_RE.sub("_", description.strip().lower())
    return s.strip("_")


async def get_entry(
    session: AsyncSession,
    *,
    business_type: str,
    item_canonical: str,
) -> MrpCatalogueEntry | None:
    stmt = select(MrpCatalogueEntry).where(
        MrpCatalogueEntry.business_type == business_type,
        MrpCatalogueEntry.item_canonical == item_canonical,
    )
    return (await session.execute(stmt)).scalars().first()


async def list_entries(
    session: AsyncSession,
    *,
    business_type: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[MrpCatalogueEntry]:
    stmt = select(MrpCatalogueEntry)
    if business_type:
        stmt = stmt.where(MrpCatalogueEntry.business_type == business_type)
    stmt = stmt.order_by(
        MrpCatalogueEntry.business_type, MrpCatalogueEntry.item_canonical
    ).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def upsert_from_ai(
    session: AsyncSession,
    *,
    business_type: str,
    item_description: str,
    category: str,
    mrp_inr: int,
    confidence: str | None,
    rationale: str | None,
) -> MrpCatalogueEntry:
    """Lookup-or-insert with `source = AI_ESTIMATED`.

    If an entry already exists at (business_type, item_canonical):
      - bump `observed_count`
      - DO NOT overwrite mrp_inr / category (admin edits or
        first-AI value is sticky)
      - DO update `updated_at` to track most-recent-sighting

    If no entry: insert one with `source = AI_ESTIMATED` and
    `observed_count = 1`.
    """
    canonical = canonicalise(item_description)
    if not canonical:
        # Edge case: description was all punctuation. Synthesize a key.
        canonical = "unknown_item"

    existing = await get_entry(
        session, business_type=business_type, item_canonical=canonical
    )
    now = datetime.now(UTC)
    if existing is not None:
        existing.observed_count += 1
        existing.updated_at = now
        return existing

    entry = MrpCatalogueEntry(
        id=uuid.uuid4(),
        business_type=business_type,
        item_canonical=canonical,
        item_description=item_description,
        category=category,
        mrp_inr=mrp_inr,
        source="AI_ESTIMATED",
        confidence=confidence,
        rationale=rationale,
        observed_count=1,
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    return entry


async def create_manual(
    session: AsyncSession,
    *,
    business_type: str,
    item_description: str,
    category: str,
    mrp_inr: int,
    rationale: str | None,
    actor_user_id: uuid.UUID,
) -> MrpCatalogueEntry:
    canonical = canonicalise(item_description)
    if not canonical:
        raise ValueError("item_description normalises to empty canonical key")
    entry = MrpCatalogueEntry(
        id=uuid.uuid4(),
        business_type=business_type,
        item_canonical=canonical,
        item_description=item_description,
        category=category,
        mrp_inr=mrp_inr,
        source="MANUAL",
        confidence=None,
        rationale=rationale,
        observed_count=0,
        updated_by_user_id=actor_user_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def update_entry(
    session: AsyncSession,
    *,
    entry_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    mrp_inr: int | None = None,
    item_description: str | None = None,
    category: str | None = None,
    rationale: str | None = None,
) -> MrpCatalogueEntry | None:
    """Patch fields on an existing row. Returns None if not found.

    If the row was AI_ESTIMATED and any field is set, source flips to
    OVERRIDDEN_FROM_AI so the audit trail reflects human curation.
    """
    entry = await session.get(MrpCatalogueEntry, entry_id)
    if entry is None:
        return None
    touched = False
    if mrp_inr is not None and mrp_inr != entry.mrp_inr:
        entry.mrp_inr = mrp_inr
        touched = True
    if item_description is not None and item_description != entry.item_description:
        entry.item_description = item_description
        touched = True
    if category is not None and category != entry.category:
        entry.category = category
        touched = True
    if rationale is not None:
        entry.rationale = rationale
        touched = True
    if touched:
        if entry.source == "AI_ESTIMATED":
            entry.source = "OVERRIDDEN_FROM_AI"
        entry.updated_by_user_id = actor_user_id
        entry.updated_at = datetime.now(UTC)
        await session.flush()
    return entry


async def delete_entry(
    session: AsyncSession,
    *,
    entry_id: uuid.UUID,
) -> bool:
    entry = await session.get(MrpCatalogueEntry, entry_id)
    if entry is None:
        return False
    await session.delete(entry)
    await session.flush()
    return True
