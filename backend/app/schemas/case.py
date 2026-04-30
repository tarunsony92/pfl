"""Pydantic request/response schemas for case endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.enums import ArtifactType, CaseStage

LOAN_ID_PATTERN = r"^[A-Za-z0-9-]{3,32}$"


class CaseInitiateRequest(BaseModel):
    loan_id: str = Field(pattern=LOAN_ID_PATTERN, description="Unique Finpage loan ID")
    applicant_name: str | None = Field(None, max_length=255)
    loan_amount: int | None = Field(None, ge=0)
    loan_tenure_months: int | None = Field(None, ge=1, le=360)
    co_applicant_name: str | None = Field(None, max_length=255)
    occupation: str | None = Field(
        None,
        max_length=255,
        description=(
            "Free-text applicant occupation. Surfaced to the L1 commute "
            "judge as one input in the profile bundle."
        ),
    )


class CaseInitiateResponse(BaseModel):
    case_id: UUID
    upload_url: str
    upload_fields: dict[str, str]
    upload_key: str
    expires_at: datetime
    reupload: bool = False


class ApproveReuploadRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class RequestDeletionPayload(BaseModel):
    reason: str = Field(
        min_length=5,
        max_length=500,
        description="Why the case should be deleted (MD will see this).",
    )


class RejectDeletionPayload(BaseModel):
    rationale: str = Field(
        min_length=5,
        max_length=500,
        description="Why the MD is rejecting this deletion request.",
    )


class CaseArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    artifact_type: ArtifactType
    size_bytes: int | None
    content_type: str | None
    uploaded_at: datetime
    download_url: str | None = None
    # Presigned URL with Content-Disposition: attachment — used only by the
    # explicit Download button so the browser opens the save dialog instead
    # of previewing inline.
    attachment_url: str | None = None
    # Classifier-assigned subtype (e.g. AUTO_CAM, EQUIFAX_HTML). Read-only;
    # surfaced so the UI can show classification coverage at a glance.
    subtype: str | None = None


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    loan_id: str
    applicant_name: str | None
    uploaded_by: UUID
    uploaded_at: datetime
    finalized_at: datetime | None
    current_stage: CaseStage
    assigned_to: UUID | None
    reupload_count: int
    reupload_allowed_until: datetime | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    artifacts: list[CaseArtifactRead] = Field(default_factory=list)
    # M4: wizard-captured fields
    loan_amount: int | None = None
    loan_tenure_months: int | None = None
    co_applicant_name: str | None = None
    occupation: str | None = None
    # Two-step deletion flow — exposed so UI can decorate cases with a
    # "DELETE PENDING" badge and show the MD approve/reject controls.
    deletion_requested_at: datetime | None = None
    deletion_requested_by: UUID | None = None
    deletion_reason: str | None = None
    # Count of OPEN / ASSESSOR_RESOLVED LevelIssues across the case.
    # Drives the cases-list stage badge colour: the badge turns red while
    # this is non-zero so "P1 COMPLETE · 46 open criticals" doesn't look
    # green. Populated by the list endpoint; ``None`` when not computed.
    open_issue_count: int | None = None


class CaseListResponse(BaseModel):
    cases: list[CaseRead]
    total: int
    limit: int
    offset: int
