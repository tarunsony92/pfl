"""ChecklistValidationResult — one row per case; upsert semantics on re-validation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChecklistValidationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "checklist_validation_results"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    missing_docs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    present_docs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
