"""CamDiscrepancyResolution — assessor's resolution of a SystemCam vs
CM CAM IL conflict for a specific field on a specific case.

Resolutions are keyed by ``(case_id, field_key)`` so they survive a
re-extraction: if the freshly-extracted values still differ on the same
field, the previously-stored resolution is shown alongside. If the values
now agree, the detector simply emits no discrepancy and the resolution
effectively becomes historical record.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import DiscrepancyResolutionKind, DiscrepancySeverity
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CamDiscrepancyResolution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cam_discrepancy_resolutions"
    __table_args__ = (
        # Only one resolution per (case, field) at a time. A new resolution
        # for the same field replaces the previous one (UPSERT).
        UniqueConstraint("case_id", "field_key", name="uq_cam_disc_res_case_field"),
    )

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Captured from the discrepancy at resolution time so the audit trail is
    # self-contained even if the extractor re-runs and produces different
    # values next time.
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    field_label: Mapped[str] = mapped_column(String(128), nullable=False)
    system_cam_value_at_resolve: Mapped[str | None] = mapped_column(Text, nullable=True)
    cm_cam_il_value_at_resolve: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity_at_resolve: Mapped[DiscrepancySeverity] = mapped_column(
        PgEnum(
            DiscrepancySeverity,
            name="discrepancy_severity",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        nullable=False,
    )
    # How the assessor resolved this.
    kind: Mapped[DiscrepancyResolutionKind] = mapped_column(
        PgEnum(
            DiscrepancyResolutionKind,
            name="discrepancy_resolution_kind",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        nullable=False,
    )
    # For CORRECTED_CM_IL: the value the assessor wrote into CM CAM IL.
    # For SYSTEMCAM_EDIT_REQUESTED: the value the assessor is asking to
    # put into SystemCam (subject to approval).
    # For JUSTIFIED: null.
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Assessor's narrative explanation — always required.
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<CamDiscrepancyResolution case={self.case_id} "
            f"field={self.field_key} kind={self.kind}>"
        )
