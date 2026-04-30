"""Pydantic read schemas for DecisionResult and DecisionStep. M5."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.enums import DecisionOutcome, DecisionStatus, StepStatus


class DecisionStepRead(BaseModel):
    """Read schema for a single DecisionStep row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    decision_result_id: UUID
    step_number: int
    step_name: str
    model_used: str | None
    status: StepStatus

    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    cost_usd: Decimal | None

    output_data: dict[str, Any] | None
    citations: Any | None
    error_message: str | None

    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DecisionResultRead(BaseModel):
    """Read schema for a DecisionResult row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    phase: str
    status: DecisionStatus
    final_decision: DecisionOutcome | None

    recommended_amount: int | None
    recommended_tenure: int | None
    conditions: Any | None
    reasoning_markdown: str | None
    pros_cons: Any | None
    deviations: Any | None
    risk_summary: Any | None
    confidence_score: int | None

    token_usage: dict[str, Any] | None
    total_cost_usd: Decimal | None
    error_message: str | None

    triggered_by: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
