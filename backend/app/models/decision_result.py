"""DecisionResult — one row per Phase 1 (or Phase 2) decisioning run per case.

M5 introduces Phase 1. Multiple runs are allowed; the latest by created_at is
canonical. The `embedding` column stores an 8-dim pgvector feature vector for
case-library similarity search.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811

# The feature_vector column stores an 8-dim float array for case-library
# similarity search. In production (with pgvector installed), the column is
# a native ``vector(8)`` type. In dev/test environments without the Postgres
# extension, we fall back to JSONB so ``Base.metadata.create_all`` still works.
#
# We always store the column as JSONB in the ORM model definition because the
# Alembic migration that runs in production detects pgvector availability and
# creates the column as ``vector(8)`` when possible. Using JSONB here avoids
# an ``asyncpg.UndefinedObjectError`` when running tests against a vanilla
# Postgres instance.
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import DecisionOutcome, DecisionStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Use JSONB as the universal column type; production migration upgrades to vector(8).
_VECTOR_TYPE: Any = JSONB


class DecisionResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stores the output and metadata of a single Phase-1 decisioning run."""

    __tablename__ = "decision_results"
    __table_args__ = (
        # Composite index for "latest result for a case" query
        Index("ix_decision_results_case_id_created", "case_id", "created_at"),
    )

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase: Mapped[str] = mapped_column(String(8), nullable=False, default="phase1")

    status: Mapped[DecisionStatus] = mapped_column(
        PgEnum(
            DecisionStatus,
            name="decision_status",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
        default=DecisionStatus.PENDING,
    )
    final_decision: Mapped[DecisionOutcome | None] = mapped_column(
        PgEnum(
            DecisionOutcome,
            name="decision_outcome",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=True,
    )

    recommended_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_tenure: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # JSONB blobs
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reasoning_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    pros_cons: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    deviations: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    risk_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    confidence_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Cost / usage tracking
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    total_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Who triggered this run
    triggered_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # pgvector 8-dim feature vector for case-library similarity search
    feature_vector: Mapped[Any | None] = mapped_column(_VECTOR_TYPE, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DecisionResult case_id={self.case_id} phase={self.phase} "
            f"status={self.status} decision={self.final_decision}>"
        )
