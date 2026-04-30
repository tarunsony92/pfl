"""Pydantic schemas for case feedback endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.enums import FeedbackVerdict


class FeedbackCreate(BaseModel):
    verdict: FeedbackVerdict
    notes: str | None = Field(None, max_length=4000)
    phase: str = Field("phase1", max_length=32)


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: UUID
    case_id: UUID
    actor_user_id: UUID
    verdict: FeedbackVerdict
    notes: str | None
    phase: str
    created_at: datetime
