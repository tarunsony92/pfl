"""DedupeMatch — hits against Customer_Dedupe rows."""

from typing import Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import DedupeMatchType
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DedupeMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dedupe_matches"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("dedupe_snapshots.id"), nullable=False)
    match_type: Mapped[DedupeMatchType] = mapped_column(
        PgEnum(
            DedupeMatchType,
            name="dedupe_match_type",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    matched_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    matched_details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
