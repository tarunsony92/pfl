"""Pydantic schemas for the Learning Rules admin surface."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RuleOverrideRead(BaseModel):
    sub_step_id: str
    is_suppressed: bool
    admin_note: str | None = None
    updated_by: UUID | None = None
    last_edited_at: datetime | None = None

    model_config = {"from_attributes": True}


class RuleOverrideUpsertRequest(BaseModel):
    """PUT body — partial update, either field may be omitted."""

    is_suppressed: bool | None = None
    admin_note: str | None = Field(default=None, max_length=2000)


class RuleMDDecisionSample(BaseModel):
    """A single past MD decision on this rule — the AI's 'learning signal'."""

    issue_id: UUID
    case_id: UUID
    decision: Literal["MD_APPROVED", "MD_REJECTED"]
    rationale: str | None = None
    reviewed_at: datetime


class RuleStatRead(BaseModel):
    """Aggregated view of a single rule across all cases.

    Used by the Learning Rules page to show the operator how often a
    rule has fired, what the MD population has decided on it, and
    whether it's currently active.
    """

    sub_step_id: str
    # Fire counts (how often this rule has emitted an issue).
    total_fires: int
    open_count: int
    assessor_resolved_count: int
    md_approved_count: int
    md_rejected_count: int
    # Override status.
    is_suppressed: bool
    admin_note: str | None = None
    last_edited_at: datetime | None = None
    # Up to 5 recent MD rationales — the closest thing to "what the AI is
    # learning" from MDs so far.
    recent_md_samples: list[RuleMDDecisionSample] = []
