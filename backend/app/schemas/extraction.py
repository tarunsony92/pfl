from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.enums import DedupeMatchType, ExtractionStatus


class CaseExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    artifact_id: UUID | None
    extractor_name: str
    schema_version: str
    status: ExtractionStatus
    data: dict[str, Any]
    warnings: list[str] | None
    error_message: str | None
    extracted_at: datetime
    created_at: datetime


class ChecklistValidationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    is_complete: bool
    missing_docs: list[dict[str, Any]]
    present_docs: list[dict[str, Any]]
    validated_at: datetime


class DedupeMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    snapshot_id: UUID
    match_type: DedupeMatchType
    match_score: float
    matched_customer_id: str | None
    matched_details_json: dict[str, Any]
    created_at: datetime
