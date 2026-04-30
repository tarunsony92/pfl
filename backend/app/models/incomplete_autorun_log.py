"""IncompleteAutorunLog — one row per auto-run started while one or more
required artefacts were missing from the case.

Surfaces in the admin "Incomplete Auto-Runs" sidebar so we can spot users
who repeatedly bypass the file-completeness gate ("defaulters" in the
ops-team's wording). Auto-run can still proceed when the user has a
business reason; we just record who skipped what so audit can chase.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IncompleteAutorunLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "incomplete_autorun_log"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    # ArtifactSubtype values that the completeness checker reported missing
    # at the moment of skip. Stored as a JSON list of strings so future
    # required-set changes don't invalidate historic rows.
    missing_subtypes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    # Optional free-text reason the user typed in the gate modal.
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
