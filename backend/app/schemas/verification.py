"""Pydantic schemas for the 4-level verification gate HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.enums import (
    DocType,
    LevelIssueSeverity,
    LevelIssueStatus,
    Party,
    VerificationLevelNumber,
    VerificationLevelStatus,
)


class L1ExtractedDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    artifact_id: UUID | None
    doc_type: DocType
    party: Party
    extracted_name: str | None
    extracted_father_name: str | None
    extracted_address: str | None
    extracted_number: str | None
    extracted_dob: date | None
    extracted_gender: str | None
    model_used: str | None
    cost_usd: Decimal | None
    error_message: str | None
    created_at: datetime


class LevelIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    verification_result_id: UUID
    sub_step_id: str
    severity: LevelIssueSeverity
    description: str
    evidence: dict[str, Any] | None
    status: LevelIssueStatus
    assessor_user_id: UUID | None
    assessor_note: str | None
    assessor_resolved_at: datetime | None
    md_user_id: UUID | None
    md_rationale: str | None
    md_reviewed_at: datetime | None
    artifact_id: UUID | None
    created_at: datetime
    updated_at: datetime


class VerificationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    level_number: VerificationLevelNumber
    status: VerificationLevelStatus
    sub_step_results: dict[str, Any] | None = None
    md_override_records: dict[str, Any] | None = None
    cost_usd: Decimal | None
    error_message: str | None
    triggered_by: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class VerificationOverview(BaseModel):
    """Top-level view of all level runs for a case — the latest by level."""

    case_id: UUID
    levels: list[VerificationResultRead]
    gate_open_for_phase_1: bool = Field(
        description="True iff all levels are PASSED / PASSED_WITH_MD_OVERRIDE."
    )
    open_issue_count: int = Field(
        default=0,
        description=(
            "Total LevelIssues across all levels in OPEN status — still "
            "need assessor action."
        ),
    )
    awaiting_md_count: int = Field(
        default=0,
        description=(
            "Total LevelIssues in ASSESSOR_RESOLVED status — assessor has "
            "written a resolution, awaiting MD approve/reject."
        ),
    )
    md_approved_count: int = Field(
        default=0,
        description=(
            "Total LevelIssues in MD_APPROVED status (settled — includes AI "
            "auto-justified clears). Counts toward the resolution progress bar."
        ),
    )
    md_rejected_count: int = Field(
        default=0,
        description=(
            "Total LevelIssues in MD_REJECTED status (settled — concern "
            "rejected by MD). Counts as resolved for gate purposes even though "
            "the case will not approve."
        ),
    )


class VerificationLevelDetail(BaseModel):
    """Level result + its child documents + its open/resolved issues."""

    result: VerificationResultRead
    extracted_documents: list[L1ExtractedDocumentRead]
    issues: list[LevelIssueRead]


class TriggerLevelResponse(BaseModel):
    verification_result_id: UUID
    case_id: UUID
    level_number: VerificationLevelNumber
    status: VerificationLevelStatus


class IssueResolveRequest(BaseModel):
    assessor_note: str = Field(min_length=4, max_length=4000)


class IssueDecideRequest(BaseModel):
    decision: LevelIssueStatus = Field(
        description="Only MD_APPROVED or MD_REJECTED are accepted."
    )
    md_rationale: str = Field(min_length=4, max_length=4000)


class MDQueueItem(BaseModel):
    """One row in the MD approvals queue — an unresolved issue with enough
    case + level context for the queue UI to render without extra fetches."""

    model_config = ConfigDict(from_attributes=True)

    issue: LevelIssueRead
    case_id: UUID
    loan_id: str
    applicant_name: str | None
    co_applicant_name: str | None
    loan_amount: int | None
    level_number: VerificationLevelNumber
    level_status: VerificationLevelStatus
    level_completed_at: datetime | None


class MDQueueResponse(BaseModel):
    items: list[MDQueueItem]
    total_open: int
    total_awaiting_md: int


class CasePhotoItem(BaseModel):
    """One photo with a presigned download URL for inline rendering."""

    model_config = ConfigDict(from_attributes=True)

    artifact_id: UUID
    filename: str
    subtype: str
    download_url: str


class CasePhotosResponse(BaseModel):
    case_id: UUID
    subtype: str
    items: list[CasePhotoItem]


class PrecedentItem(BaseModel):
    """A past MD-adjudicated issue on the same sub-step — shown as context to
    help the MD decide consistently with prior rulings."""

    model_config = ConfigDict(from_attributes=True)

    issue_id: UUID
    case_id: UUID
    loan_id: str
    applicant_name: str | None
    sub_step_id: str
    severity: str
    decision: str  # MD_APPROVED or MD_REJECTED
    md_rationale: str | None
    md_reviewed_at: datetime | None


class PrecedentsResponse(BaseModel):
    sub_step_id: str
    items: list[PrecedentItem]
    approved_count: int
    rejected_count: int
