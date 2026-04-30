"""RuleOverride — admin control surface over the deterministic rule catalog.

Every rule emitted by a ``run_level_*`` orchestrator carries a
``sub_step_id`` (e.g. ``gps_vs_aadhaar``). An MD with admin rights can
suppress individual rules — the engine filters matching issues out of
the persisted list before they surface to the MD queue. The row also
stores a free-form note so whoever comes along later can see *why*
the rule was disabled.

This is the editable surface behind the "Learning Model Rules" tab —
what the AI is learning, what it's been told to skip, and who made
the call.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RuleOverride(TimestampMixin, Base):
    __tablename__ = "rule_overrides"

    # sub_step_id is the natural key — one override per rule. Keyed as
    # primary because a rule either has an override or it doesn't; there's
    # no reason to version or duplicate.
    sub_step_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    is_suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit — who last touched this override, when.
    updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    last_edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
