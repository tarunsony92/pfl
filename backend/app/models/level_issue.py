"""LevelIssue — one row per sub-step failure within a VerificationResult.

The lifecycle is OPEN → ASSESSOR_RESOLVED → MD_APPROVED | MD_REJECTED.
Each row records the assessor's solution + the MD's rationale plus an optional
``artifact_id`` for re-uploaded corrected documents (L4's agreement re-upload flow).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import LevelIssueSeverity, LevelIssueStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LevelIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single failed sub-step inside a level run, its resolution + MD decision."""

    __tablename__ = "level_issues"
    __table_args__ = (
        Index(
            "ix_level_issues_result_status",
            "verification_result_id",
            "status",
        ),
    )

    verification_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sub_step_id: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[LevelIssueSeverity] = mapped_column(
        PgEnum(
            LevelIssueSeverity,
            name="level_issue_severity",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[LevelIssueStatus] = mapped_column(
        PgEnum(
            LevelIssueStatus,
            name="level_issue_status",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
        default=LevelIssueStatus.OPEN,
    )

    assessor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    assessor_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessor_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    md_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    md_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    md_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("case_artifacts.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<LevelIssue result_id={self.verification_result_id} "
            f"sub_step={self.sub_step_id} severity={self.severity} status={self.status}>"
        )
