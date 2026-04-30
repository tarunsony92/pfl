"""CaseFeedback — human verdict on a case, for AI learning (phase 1 of §7)."""

from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import FeedbackVerdict
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaseFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "case_feedbacks"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    verdict: Mapped[FeedbackVerdict] = mapped_column(
        PgEnum(
            FeedbackVerdict,
            name="feedback_verdict",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="phase1")

    def __repr__(self) -> str:
        return f"<CaseFeedback case={self.case_id} verdict={self.verdict}>"
