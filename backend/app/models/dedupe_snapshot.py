"""DedupeSnapshot — versioned uploaded Customer_Dedupe.xlsx files."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DedupeSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dedupe_snapshots"

    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
