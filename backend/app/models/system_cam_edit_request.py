"""SystemCamEditRequest — approval-gated change to the SystemCam (finpage)
side of a CAM discrepancy.

Editing CM CAM IL is a self-serve assessor action; editing SystemCam
(finpage / bureau data) requires an explicit approval from CEO or admin.
This table records the request, the approver, and the outcome.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import SystemCamEditRequestStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SystemCamEditRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "system_cam_edit_requests"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Link back to the resolution row that spawned this request, for easy
    # traversal. Nullable so we can later issue stand-alone requests.
    resolution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cam_discrepancy_resolutions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    field_label: Mapped[str] = mapped_column(String(128), nullable=False)
    current_system_cam_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_system_cam_value: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SystemCamEditRequestStatus] = mapped_column(
        PgEnum(
            SystemCamEditRequestStatus,
            name="system_cam_edit_request_status",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        nullable=False,
        default=SystemCamEditRequestStatus.PENDING,
    )
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<SystemCamEditRequest case={self.case_id} "
            f"field={self.field_key} status={self.status}>"
        )
