"""DecisionStep — one row per step per DecisionResult run.

Steps 1–11 are recorded here with their status, token usage, cost, output data,
and citations. Unique index on (decision_result_id, step_number) enables upsert
idempotency when a worker is killed and the message is redelivered.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import StepStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DecisionStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Records the execution of a single step within a Phase 1 pipeline run."""

    __tablename__ = "decision_steps"
    __table_args__ = (
        UniqueConstraint(
            "decision_result_id",
            "step_number",
            name="uq_decision_steps_result_step",
        ),
    )

    decision_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("decision_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[StepStatus] = mapped_column(
        PgEnum(
            StepStatus,
            name="step_status",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
        default=StepStatus.PENDING,
    )

    # Token accounting (nullable — Step 1 is pure Python, no LLM)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    # Step output + evidence
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    citations: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<DecisionStep result_id={self.decision_result_id} "
            f"step={self.step_number} name={self.step_name} status={self.status}>"
        )
