"""MRP (Maximum Retail Price) database helpers for stock quantification (Step 7).

Provides fuzzy lookup via pg_trgm similarity and idempotent upsert. Also
ships with a seed dataset of 50 common Kirana/retail items.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import MrpSource
from app.models.mrp_entry import MrpEntry

if TYPE_CHECKING:
    from uuid import UUID

_log = logging.getLogger(__name__)

# ── Seed data ─────────────────────────────────────────────────────────────────
# 50 common Kirana / retail items with realistic INR unit prices (2026 approx).

SEED_ITEMS: list[dict[str, object]] = [
    # ── Grocery / Kirana ──────────────────────────────────────────────────
    {"name": "toor dal", "category": "grocery", "price": 110.0},
    {"name": "moong dal", "category": "grocery", "price": 95.0},
    {"name": "chana dal", "category": "grocery", "price": 85.0},
    {"name": "urad dal", "category": "grocery", "price": 120.0},
    {"name": "basmati rice 1kg", "category": "grocery", "price": 80.0},
    {"name": "wheat flour 5kg", "category": "grocery", "price": 200.0},
    {"name": "sunflower oil 1l", "category": "grocery", "price": 130.0},
    {"name": "mustard oil 1l", "category": "grocery", "price": 155.0},
    {"name": "sugar 1kg", "category": "grocery", "price": 42.0},
    {"name": "salt 1kg", "category": "grocery", "price": 22.0},
    {"name": "tea powder 250g", "category": "grocery", "price": 80.0},
    {"name": "instant noodles maggi", "category": "grocery", "price": 15.0},
    {"name": "biscuits parle-g 200g", "category": "grocery", "price": 20.0},
    {"name": "biscuits marie 200g", "category": "grocery", "price": 25.0},
    {"name": "turmeric powder 100g", "category": "grocery", "price": 40.0},
    {"name": "red chilli powder 100g", "category": "grocery", "price": 45.0},
    {"name": "coriander powder 100g", "category": "grocery", "price": 38.0},
    {"name": "cumin seeds 100g", "category": "grocery", "price": 50.0},
    {"name": "refined flour maida 1kg", "category": "grocery", "price": 30.0},
    {"name": "poha 500g", "category": "grocery", "price": 35.0},
    # ── Personal care / Cosmetics ─────────────────────────────────────────
    {"name": "toothpaste colgate 200g", "category": "cosmetics", "price": 85.0},
    {"name": "bathing soap lifebuoy 125g", "category": "cosmetics", "price": 32.0},
    {"name": "shampoo head shoulders 200ml", "category": "cosmetics", "price": 165.0},
    {"name": "talcum powder 300g", "category": "cosmetics", "price": 110.0},
    {"name": "hair oil parachute 300ml", "category": "cosmetics", "price": 95.0},
    {"name": "face cream ponds 50g", "category": "cosmetics", "price": 85.0},
    {"name": "lip balm nivea 4.8g", "category": "cosmetics", "price": 75.0},
    {"name": "fairness cream fair and lovely 50g", "category": "cosmetics", "price": 95.0},
    {"name": "deo spray axe 150ml", "category": "cosmetics", "price": 180.0},
    {"name": "sunscreen lotion spf50 50ml", "category": "cosmetics", "price": 150.0},
    # ── Household / Cleaning ──────────────────────────────────────────────
    {"name": "washing powder 1kg", "category": "household", "price": 75.0},
    {"name": "dishwash bar 200g", "category": "household", "price": 30.0},
    {"name": "floor cleaner phenyl 1l", "category": "household", "price": 55.0},
    {"name": "toilet cleaner harpic 500ml", "category": "household", "price": 95.0},
    {"name": "mosquito coil good knight 10pc", "category": "household", "price": 40.0},
    {"name": "matchbox 3pc", "category": "household", "price": 10.0},
    {"name": "candle plain 6pc", "category": "household", "price": 35.0},
    {"name": "plastic bucket 10l", "category": "household", "price": 120.0},
    {"name": "scrub pad scotch-brite", "category": "household", "price": 45.0},
    {"name": "steel glass 300ml", "category": "household", "price": 60.0},
    # ── Stationery ────────────────────────────────────────────────────────
    {"name": "ballpoint pen blue cello", "category": "stationery", "price": 5.0},
    {"name": "notebook 200 pages", "category": "stationery", "price": 55.0},
    {"name": "pencil apsara hb 12pc", "category": "stationery", "price": 30.0},
    {"name": "eraser natraj 20g", "category": "stationery", "price": 5.0},
    {"name": "sticky tape 1 roll", "category": "stationery", "price": 30.0},
    # ── Hardware / Misc ───────────────────────────────────────────────────
    {"name": "aa battery 2pc", "category": "hardware", "price": 40.0},
    {"name": "led bulb 9w", "category": "hardware", "price": 80.0},
    {"name": "electric plug 6amp", "category": "hardware", "price": 25.0},
    {"name": "cycle lock iron chain", "category": "hardware", "price": 120.0},
    {"name": "cellotape dispenser", "category": "hardware", "price": 90.0},
]


# ── CRUD helpers ──────────────────────────────────────────────────────────────


def _normalize(name: str) -> str:
    """Lowercase and strip whitespace for consistent matching."""
    return name.lower().strip()


async def lookup(
    session: AsyncSession,
    item_name: str,
    fuzzy_threshold: float = 0.5,
) -> MrpEntry | None:
    """Fuzzy-match ``item_name`` against ``mrp_entries.item_normalized_name``.

    First tries exact match, then pg_trgm similarity. Returns ``None`` if no
    match is found above ``fuzzy_threshold``.
    """
    normalized = _normalize(item_name)

    # 1. Exact match
    stmt = select(MrpEntry).where(MrpEntry.item_normalized_name == normalized)
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is not None:
        return entry

    # 2. Trigram fuzzy match
    try:
        sql = text(
            """
            SELECT id
            FROM mrp_entries
            WHERE similarity(item_normalized_name, :name) > :threshold
            ORDER BY similarity(item_normalized_name, :name) DESC
            LIMIT 1
            """
        )
        result2 = await session.execute(sql, {"name": normalized, "threshold": fuzzy_threshold})
        row = result2.fetchone()
        if row is None:
            return None
        return await session.get(MrpEntry, row[0])
    except Exception as exc:  # noqa: BLE001
        # pg_trgm extension not available
        _log.debug("Trigram lookup unavailable: %s", exc)
        return None


async def upsert(
    session: AsyncSession,
    item_name: str,
    category: str | None,
    price: float,
    source: MrpSource = MrpSource.WEB_KNOWLEDGE,
    source_case_id: UUID | None = None,
) -> MrpEntry:
    """Insert or update an MRP entry.

    On conflict (same normalized name), uses PostgreSQL's ``ON CONFLICT DO UPDATE``
    to update the price and source.
    """
    normalized = _normalize(item_name)

    stmt = (
        pg_insert(MrpEntry)
        .values(
            item_normalized_name=normalized,
            category=category,
            unit_price_inr=Decimal(str(price)),
            source=source.value,
            source_case_id=source_case_id,
        )
        .on_conflict_do_update(
            constraint="uq_mrp_entries_name",
            set_={
                "unit_price_inr": Decimal(str(price)),
                "source": source.value,
                "source_case_id": source_case_id,
            },
        )
        .returning(MrpEntry.id)
    )
    result = await session.execute(stmt)
    row = result.fetchone()
    await session.flush()
    entry = await session.get(MrpEntry, row[0])  # type: ignore[index]
    return entry  # type: ignore[return-value]


async def seed_mrp_entries(session: AsyncSession) -> int:
    """Seed 50 common items into ``mrp_entries``. Idempotent — uses upsert.

    Returns the number of items processed.
    """
    count = 0
    for item in SEED_ITEMS:
        await upsert(
            session,
            item_name=str(item["name"]),
            category=str(item["category"]) if item.get("category") else None,
            price=float(item["price"]),  # type: ignore[arg-type]
            source=MrpSource.WEB_KNOWLEDGE,
        )
        count += 1
    return count
