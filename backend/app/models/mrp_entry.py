"""MrpEntry — shared MRP (Maximum Retail Price) catalog for stock valuation.

One row per unique normalized item name. Observation count grows each time a
new price sighting is recorded. pg_trgm fuzzy matching is used for lookup.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import MrpSource
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MrpEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Price catalog entry for an item used in stock quantification (Step 7)."""

    __tablename__ = "mrp_entries"
    __table_args__ = (
        UniqueConstraint("item_normalized_name", name="uq_mrp_entries_name"),
    )

    item_normalized_name: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_price_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    source: Mapped[MrpSource] = mapped_column(
        PgEnum(
            MrpSource,
            name="mrp_source",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
    )

    # FK to the case whose data provided this price (nullable — not all sources are case-derived)
    source_case_id: Mapped[UUID | None] = mapped_column(
        nullable=True
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<MrpEntry name={self.item_normalized_name!r} "
            f"price={self.unit_price_inr} source={self.source}>"
        )
