"""CAM discrepancy service — glues the detector to the DB.

Reads the latest ``auto_cam`` extraction for a case, runs the detector,
merges with any persisted resolutions + pending SystemCam-edit requests,
and returns a ``CamDiscrepancySummary`` that the API + decisioning gate
consume directly.

Also exposes write paths used by the API:
  - upsert a resolution for (case, field_key)
  - create / decide a system_cam_edit_request
  - generate a markdown report of the discrepancy timeline for a case
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    DiscrepancyResolutionKind,
    SystemCamEditRequestStatus,
)
from app.models.cam_discrepancy_resolution import CamDiscrepancyResolution
from app.models.case_extraction import CaseExtraction
from app.models.system_cam_edit_request import SystemCamEditRequest
from app.models.user import User
from app.schemas.cam_discrepancy import (
    CamDiscrepancyFlag,
    CamDiscrepancyResolutionRead,
    CamDiscrepancyResolveRequest,
    CamDiscrepancySummary,
    CamDiscrepancyView,
    SystemCamEditDecisionRequest,
    SystemCamEditRequestRead,
)
from app.worker.extractors.autocam_discrepancies import (
    Discrepancy,
    detect_discrepancies,
)


class DiscrepancyError(Exception):
    """Base class for discrepancy-service errors."""


class DiscrepancyNotFound(DiscrepancyError):
    pass


class InvalidResolutionPayload(DiscrepancyError):
    pass


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------


async def _latest_autocam_data(session: AsyncSession, case_id: UUID) -> dict | None:
    """Return the ``data`` field of the most recent ``auto_cam`` extraction
    for this case. Prefers the full-CAM variant (not single_sheet_cam) when
    multiple extractions exist, because that's the one carrying both
    SystemCam AND CM CAM IL data — which is what the detector needs.
    """
    stmt = (
        select(CaseExtraction)
        .where(
            CaseExtraction.case_id == case_id,
            CaseExtraction.extractor_name == "auto_cam",
        )
        .order_by(CaseExtraction.extracted_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return None
    # Prefer the full CAM: variant != "single_sheet_cam"
    for row in rows:
        data = row.data or {}
        if data.get("variant") != "single_sheet_cam":
            return data
    return rows[0].data or {}


async def _load_resolutions(
    session: AsyncSession, case_id: UUID
) -> dict[str, CamDiscrepancyResolution]:
    stmt = select(CamDiscrepancyResolution).where(
        CamDiscrepancyResolution.case_id == case_id
    )
    result = await session.execute(stmt)
    return {r.field_key: r for r in result.scalars()}


async def _load_pending_edit_requests(
    session: AsyncSession, case_id: UUID
) -> dict[str, SystemCamEditRequest]:
    stmt = select(SystemCamEditRequest).where(
        SystemCamEditRequest.case_id == case_id,
        SystemCamEditRequest.status == SystemCamEditRequestStatus.PENDING,
    )
    result = await session.execute(stmt)
    return {r.field_key: r for r in result.scalars()}


async def get_summary(session: AsyncSession, case_id: UUID) -> CamDiscrepancySummary:
    """Build the aggregated view used by GET /cases/{id}/cam-discrepancies
    AND by the Phase 1 gate.
    """
    auto_cam_data = await _latest_autocam_data(session, case_id)
    flags: list[Discrepancy] = (
        detect_discrepancies(auto_cam_data) if auto_cam_data else []
    )
    resolutions = await _load_resolutions(session, case_id)
    edit_requests = await _load_pending_edit_requests(session, case_id)

    by_key: dict[str, CamDiscrepancyView] = {}
    for f in flags:
        by_key[f.field_key] = CamDiscrepancyView(
            field_key=f.field_key,
            field_label=f.field_label,
            flag=CamDiscrepancyFlag(
                field_key=f.field_key,
                field_label=f.field_label,
                system_cam_value=f.system_cam_value,
                cm_cam_il_value=f.cm_cam_il_value,
                diff_abs=f.diff_abs,
                diff_pct=f.diff_pct,
                severity=f.severity,
                tolerance_description=f.tolerance_description,
                note=f.note,
            ),
        )
    # Historical resolutions on fields that now agree still appear in the view.
    for field_key, res in resolutions.items():
        view = by_key.get(field_key)
        if view is None:
            view = CamDiscrepancyView(field_key=field_key, field_label=res.field_label)
            by_key[field_key] = view
        view.resolution = CamDiscrepancyResolutionRead.model_validate(res)

    for field_key, req in edit_requests.items():
        view = by_key.get(field_key)
        if view is None:
            view = CamDiscrepancyView(field_key=field_key, field_label=req.field_label)
            by_key[field_key] = view
        view.pending_edit_request = SystemCamEditRequestRead.model_validate(req)

    views = sorted(
        by_key.values(),
        key=lambda v: (
            # Unresolved criticals first, then unresolved warnings, then resolved
            0 if (v.flag and not v.resolution and v.flag.severity == "CRITICAL") else
            1 if (v.flag and not v.resolution and v.flag.severity == "WARNING") else
            2,
            v.field_key,
        ),
    )
    unresolved_critical = sum(
        1 for v in views
        if v.flag and v.flag.severity == "CRITICAL" and v.resolution is None
    )
    unresolved_warning = sum(
        1 for v in views
        if v.flag and v.flag.severity == "WARNING" and v.resolution is None
    )

    return CamDiscrepancySummary(
        case_id=case_id,
        generated_at=datetime.now(UTC),
        total=len(views),
        unresolved_critical=unresolved_critical,
        unresolved_warning=unresolved_warning,
        phase1_blocked=unresolved_critical > 0,
        views=views,
    )


# ---------------------------------------------------------------------------
# Write path — resolve a discrepancy
# ---------------------------------------------------------------------------


async def upsert_resolution(
    session: AsyncSession,
    *,
    case_id: UUID,
    field_key: str,
    actor: User,
    payload: CamDiscrepancyResolveRequest,
) -> tuple[CamDiscrepancyResolution, SystemCamEditRequest | None]:
    """Create or replace the resolution row for (case_id, field_key).

    Returns (resolution, edit_request). edit_request is non-null only when
    kind = SYSTEMCAM_EDIT_REQUESTED.
    """
    summary = await get_summary(session, case_id)
    view = next((v for v in summary.views if v.field_key == field_key), None)
    if view is None or view.flag is None:
        # Allow resolving a historical flag (view exists without a flag) only
        # if the caller is clearly acknowledging — reject otherwise.
        if view is None:
            raise DiscrepancyNotFound(
                f"No discrepancy known for field {field_key!r} on case {case_id}"
            )

    # Validate payload semantics
    if payload.kind == DiscrepancyResolutionKind.JUSTIFIED:
        if payload.corrected_value is not None:
            raise InvalidResolutionPayload(
                "JUSTIFIED resolution must not supply corrected_value"
            )
    else:
        if not payload.corrected_value or not payload.corrected_value.strip():
            raise InvalidResolutionPayload(
                f"{payload.kind.value} requires a corrected_value"
            )

    flag = view.flag if view else None
    field_label = flag.field_label if flag else (
        view.field_label if view else field_key
    )
    severity = flag.severity if flag else (
        view.flag.severity if view and view.flag else "WARNING"
    )
    sc_value = flag.system_cam_value if flag else None
    cm_value = flag.cm_cam_il_value if flag else None

    now = datetime.now(UTC)

    # UPSERT on (case_id, field_key)
    stmt = (
        pg_insert(CamDiscrepancyResolution)
        .values(
            case_id=case_id,
            field_key=field_key,
            field_label=field_label,
            system_cam_value_at_resolve=sc_value,
            cm_cam_il_value_at_resolve=cm_value,
            severity_at_resolve=severity,
            kind=payload.kind,
            corrected_value=payload.corrected_value,
            comment=payload.comment,
            resolved_by=actor.id,
            resolved_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_cam_disc_res_case_field",
            set_={
                "field_label": field_label,
                "system_cam_value_at_resolve": sc_value,
                "cm_cam_il_value_at_resolve": cm_value,
                "severity_at_resolve": severity,
                "kind": payload.kind,
                "corrected_value": payload.corrected_value,
                "comment": payload.comment,
                "resolved_by": actor.id,
                "resolved_at": now,
                "updated_at": now,
            },
        )
        .returning(CamDiscrepancyResolution)
    )
    result = await session.execute(stmt)
    resolution = result.scalar_one()
    await session.flush()

    edit_request: SystemCamEditRequest | None = None
    if payload.kind == DiscrepancyResolutionKind.SYSTEMCAM_EDIT_REQUESTED:
        edit_request = SystemCamEditRequest(
            case_id=case_id,
            resolution_id=resolution.id,
            field_key=field_key,
            field_label=field_label,
            current_system_cam_value=sc_value,
            requested_system_cam_value=payload.corrected_value or "",
            justification=payload.comment,
            status=SystemCamEditRequestStatus.PENDING,
            requested_by=actor.id,
            requested_at=now,
        )
        session.add(edit_request)
        await session.flush()

    return resolution, edit_request


async def decide_edit_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    approver: User,
    payload: SystemCamEditDecisionRequest,
) -> SystemCamEditRequest:
    req = await session.get(SystemCamEditRequest, request_id)
    if req is None:
        raise DiscrepancyNotFound(f"SystemCam edit request {request_id} not found")
    if req.status != SystemCamEditRequestStatus.PENDING:
        raise InvalidResolutionPayload(
            f"Request already {req.status.value}; no further decisions possible."
        )
    req.status = (
        SystemCamEditRequestStatus.APPROVED
        if payload.approve
        else SystemCamEditRequestStatus.REJECTED
    )
    req.decided_by = approver.id
    req.decided_at = datetime.now(UTC)
    req.decision_comment = payload.decision_comment
    await session.flush()
    return req


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def render_markdown_report(
    summary: CamDiscrepancySummary, *, case_loan_id: str | None = None
) -> str:
    lines: list[str] = []
    header = f"# CAM Discrepancy Report — Case {case_loan_id or summary.case_id}"
    lines.append(header)
    lines.append("")
    lines.append(f"Generated: {summary.generated_at.isoformat()}")
    lines.append("")
    lines.append(
        f"- Total fields checked: **{summary.total}**  "
        f"· Unresolved CRITICAL: **{summary.unresolved_critical}**  "
        f"· Unresolved WARNING: **{summary.unresolved_warning}**  "
        f"· Phase 1 gated: **{'YES' if summary.phase1_blocked else 'no'}**"
    )
    lines.append("")

    for v in summary.views:
        lines.append(f"## {v.field_label}  (`{v.field_key}`)")
        if v.flag:
            lines.append("")
            lines.append(f"- **Severity:** {v.flag.severity}")
            lines.append(f"- **SystemCam (finpage):** `{v.flag.system_cam_value}`")
            lines.append(f"- **CM CAM IL (manual):** `{v.flag.cm_cam_il_value}`")
            if v.flag.diff_abs is not None:
                lines.append(
                    f"- **Diff:** {v.flag.diff_abs} "
                    f"({v.flag.diff_pct:.2f}%) — tolerance: {v.flag.tolerance_description}"
                )
            lines.append(f"- **Why flagged:** {v.flag.note}")
        else:
            lines.append("")
            lines.append("- No active discrepancy on this field in the latest extraction.")
        if v.resolution:
            r = v.resolution
            lines.append("")
            lines.append(f"### Assessor resolution — {r.kind.value}")
            lines.append(f"- Resolved by: user `{r.resolved_by}` at {r.resolved_at.isoformat()}")
            if r.corrected_value is not None:
                lines.append(f"- Corrected value: `{r.corrected_value}`")
            lines.append(f"- Comment: {r.comment}")
        if v.pending_edit_request:
            pr = v.pending_edit_request
            lines.append("")
            lines.append("### SystemCam edit request — PENDING approval")
            lines.append(f"- Requested SystemCam value: `{pr.requested_system_cam_value}`")
            lines.append(f"- Justification: {pr.justification}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
