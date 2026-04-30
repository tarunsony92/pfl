"""VerificationResult — one row per (case, level_number) run of the 4-level gate.

Multiple runs of the same level for a case are allowed (e.g., re-runs after an
assessor solution + MD approval). Latest by ``created_at DESC`` is canonical.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import VerificationLevelNumber, VerificationLevelStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VerificationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One run of a single verification level (L1/L2/L3/L4) for a case."""

    __tablename__ = "verification_results"
    __table_args__ = (
        Index(
            "ix_verification_results_case_level_created",
            "case_id",
            "level_number",
            "created_at",
        ),
    )

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    level_number: Mapped[VerificationLevelNumber] = mapped_column(
        PgEnum(
            VerificationLevelNumber,
            name="verification_level_number",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
    )

    status: Mapped[VerificationLevelStatus] = mapped_column(
        PgEnum(
            VerificationLevelStatus,
            name="verification_level_status",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
        default=VerificationLevelStatus.PENDING,
    )

    sub_step_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    md_override_records: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    triggered_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<VerificationResult case_id={self.case_id} level={self.level_number} "
            f"status={self.status}>"
        )
