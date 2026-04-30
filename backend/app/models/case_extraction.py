"""CaseExtraction — per-(case, extractor) JSONB store of parsed data.

One row per (case, extractor_name, artifact_id) tuple. For aggregate extractors
(e.g. dedupe), artifact_id is NULL. Partial unique indexes ensure uniqueness
correctly given NULLs — also declared here so Base.metadata.create_all works
in tests (in addition to the Alembic migration that creates them in production).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # noqa: N811
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import ExtractionStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaseExtraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "case_extractions"
    __table_args__ = (
        # Partial unique index for artifact-bound extractions
        Index(
            "uq_case_extractions_per_artifact",
            "case_id",
            "extractor_name",
            "artifact_id",
            unique=True,
            postgresql_where=text("artifact_id IS NOT NULL"),
        ),
        # Partial unique index for aggregate (case-level) extractions
        Index(
            "uq_case_extractions_aggregate",
            "case_id",
            "extractor_name",
            unique=True,
            postgresql_where=text("artifact_id IS NULL"),
        ),
    )

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("case_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    extractor_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    status: Mapped[ExtractionStatus] = mapped_column(
        PgEnum(
            ExtractionStatus,
            name="extraction_status",
            values_callable=lambda e: [v.value for v in e],
            create_type=True,
        ),
        nullable=False,
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
