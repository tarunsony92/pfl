"""Pydantic schemas for CAM discrepancy flags, resolutions, and SystemCam
edit-approval requests.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.enums import (
    DiscrepancyResolutionKind,
    DiscrepancySeverity,
    SystemCamEditRequestStatus,
)


# ---------------------------------------------------------------------------
# Detected (transient) discrepancy — computed from the latest auto_cam
# extraction on every API read. Not persisted.
# ---------------------------------------------------------------------------


class CamDiscrepancyFlag(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field_key: str
    field_label: str
    system_cam_value: str | None
    cm_cam_il_value: str | None
    diff_abs: float | None = None
    diff_pct: float | None = None
    severity: DiscrepancySeverity
    tolerance_description: str
    note: str = ""


# ---------------------------------------------------------------------------
# Persisted resolution
# ---------------------------------------------------------------------------


class CamDiscrepancyResolutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    field_key: str
    field_label: str
    system_cam_value_at_resolve: str | None
    cm_cam_il_value_at_resolve: str | None
    severity_at_resolve: DiscrepancySeverity
    kind: DiscrepancyResolutionKind
    corrected_value: str | None
    comment: str
    resolved_by: UUID
    resolved_at: datetime
    created_at: datetime


class CamDiscrepancyResolveRequest(BaseModel):
    """Body for POST /cases/{id}/cam-discrepancies/{field_key}/resolve.

    - CORRECTED_CM_IL → ``corrected_value`` required
    - SYSTEMCAM_EDIT_REQUESTED → ``corrected_value`` required (this is the
      value the assessor wants SystemCam to read, subject to approval)
    - JUSTIFIED → ``corrected_value`` must be null
    """

    kind: DiscrepancyResolutionKind
    comment: str = Field(min_length=10, max_length=4000)
    corrected_value: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# SystemCam edit approval flow
# ---------------------------------------------------------------------------


class SystemCamEditRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    resolution_id: UUID | None
    field_key: str
    field_label: str
    current_system_cam_value: str | None
    requested_system_cam_value: str
    justification: str
    status: SystemCamEditRequestStatus
    requested_by: UUID
    requested_at: datetime
    decided_by: UUID | None
    decided_at: datetime | None
    decision_comment: str | None
    created_at: datetime


class SystemCamEditDecisionRequest(BaseModel):
    """Body for POST /cases/{id}/system-cam-edit-requests/{id}/decide.

    CEO / admin decides APPROVE or REJECT. A decision comment is required
    either way for the audit trail.
    """

    approve: bool
    decision_comment: str = Field(min_length=10, max_length=4000)


# ---------------------------------------------------------------------------
# Aggregated "discrepancies view" — what the UI reads in one shot
# ---------------------------------------------------------------------------


class CamDiscrepancyView(BaseModel):
    """One row per field. Either ``flag`` or ``resolution`` (or both) is
    present:

    - flag + no resolution → open discrepancy, needs action.
    - flag + resolution → flag still present but assessor has addressed it
      (UI shows resolution status alongside).
    - no flag + resolution → historical resolution on a now-agreeing field.
    """

    field_key: str
    field_label: str
    flag: CamDiscrepancyFlag | None = None
    resolution: CamDiscrepancyResolutionRead | None = None
    pending_edit_request: SystemCamEditRequestRead | None = None


class CamDiscrepancySummary(BaseModel):
    """Payload for GET /cases/{id}/cam-discrepancies."""

    case_id: UUID
    generated_at: datetime
    total: int
    unresolved_critical: int
    unresolved_warning: int
    phase1_blocked: bool
    views: list[CamDiscrepancyView]
