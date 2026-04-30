"""CaseArtifact — individual file belonging to a case.

One per uploaded/generated artifact (original ZIP, additional missing docs,
re-upload archive JSONs). `metadata_json` holds type-specific info.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import ArtifactType
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaseArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "case_artifacts"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_type: Mapped[ArtifactType] = mapped_column(
        PgEnum(
            ArtifactType,
            name="artifact_type",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )
    s3_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    @property
    def subtype(self) -> str | None:
        """Classifier-assigned subtype (e.g. AUTO_CAM, EQUIFAX_HTML). Lives in
        metadata_json so extraction/classification updates don't touch the
        column schema. Surfaced as a first-class field to the API layer."""
        if not self.metadata_json:
            return None
        value = self.metadata_json.get("subtype")
        return str(value) if value is not None else None

    def __repr__(self) -> str:
        return f"<CaseArtifact type={self.artifact_type} filename={self.filename}>"
