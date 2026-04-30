"""NegativeAreaPincode — admin-curated list of pincodes flagged as
restricted lending zones.

L5 rule #11 (negative_area_check) reads the active rows here to decide
PASS / FAIL — a case whose pincode is on this list (and is_active=True)
fails the rubric row. Admins manage entries via /admin/negative-areas.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NegativeAreaPincode(Base):
    __tablename__ = "negative_area_pincodes"
    __table_args__ = (
        UniqueConstraint("pincode", name="uq_negative_area_pincode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pincode: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="manual"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    uploaded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
