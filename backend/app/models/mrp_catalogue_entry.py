"""MrpCatalogueEntry — canonical MRP per (business_type, item).

Populated automatically by the L3 orchestrator when its vision pass
returns an item that doesn't yet exist in the catalogue (`source =
AI_ESTIMATED`). Admins can manually edit any row through the admin
UI; an edited AI-source row flips to `source = OVERRIDDEN_FROM_AI`.
A row created from scratch by an admin uses `source = MANUAL`.

The unique key is (business_type, item_canonical). `item_canonical`
is the snake_case normalised description.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MrpCatalogueEntry(Base):
    __tablename__ = "mrp_catalogue_entries"
    __table_args__ = (
        UniqueConstraint(
            "business_type", "item_canonical", name="uq_mrp_business_type_item"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    item_canonical: Mapped[str] = mapped_column(String(255), nullable=False)
    item_description: Mapped[str] = mapped_column(String(512), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    mrp_inr: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AI_ESTIMATED"
    )
    confidence: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    observed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
