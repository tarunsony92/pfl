"""Case — one per loan application submission.

Spec §3.1 of M2 design. Soft-delete supported; audit log tracks all state
transitions. `reupload_allowed_until` is set by admin to grant a 24h re-upload
window; `reupload_count` is incremented on each actual re-upload.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import CaseStage
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Case(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (
        # Partial unique index: allows re-filing the same loan_id after soft-delete
        Index(
            "ix_cases_loan_id",
            "loan_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )

    loan_id: Mapped[str] = mapped_column(String(32), index=False, nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    zip_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    zip_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    current_stage: Mapped[CaseStage] = mapped_column(
        PgEnum(
            CaseStage,
            name="case_stage",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        default=CaseStage.UPLOADED,
        nullable=False,
        index=True,
    )

    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    applicant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reupload_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reupload_allowed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Two-step deletion approval flow: any user can submit a request,
    # but only an MD-role user (CEO / ADMIN) can approve it. These three
    # columns track the PENDING state between request and approval; once
    # an MD approves, the ``deleted_*`` columns above are stamped and the
    # ``deletion_*`` columns are cleared.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_requested_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # M4: wizard-captured fields
    loan_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loan_tenure_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    co_applicant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Free-text occupation captured at wizard time (eg "wholesale grain
    # dealer", "tailor"). Consumed by the L1 commute judge as one input
    # in the rural/urban + business-type profile bundle (spec §7).
    occupation: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<Case loan_id={self.loan_id} stage={self.current_stage}>"
