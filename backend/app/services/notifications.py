"""Notifications service — computes actionable issues across cases.

Every notification points at a specific case + tab the user can click to
resolve the issue (missing doc, failed extractor, critical CAM discrepancy,
etc.). Notifications are derived on the fly from existing tables — we do NOT
store notifications in their own table (yet). Poll /notifications every N
seconds for a live bell feed.

Sources covered in v1:
  - CHECKLIST_MISSING_DOCS cases → "Missing documents"
  - case_extractions.status == FAILED → "Extractor failed"
  - case_extractions critical warnings (missing_credit_score, no_accounts,
    no_account_header_detected, no_known_fields_matched,
    missing_applicant_name) → "Extraction issue"
  - cam_discrepancy_resolutions not covering every CRITICAL flag →
    "Discrepancy blocking Verification 2" (reuses the discrepancy service
    to compute phase1_blocked)

Out of scope (future):
  - Per-user read/dismiss state (needs a notifications table)
  - Real-time push (would need WebSocket / SSE)
  - Scope filtering by assigned_to
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import CaseStage, ExtractionStatus
from app.models.case import Case
from app.models.case_extraction import CaseExtraction

# CAM discrepancy service only exists on branches that carry the
# cam-discrepancy engine; the bell still works without it (it just won't
# surface discrepancy notifications on branches that lack the service).
try:
    from app.services.cam_discrepancy import get_summary as get_disc_summary
except ImportError:
    get_disc_summary = None  # type: ignore[assignment]

NotificationKind = Literal[
    "MISSING_DOCS",
    "EXTRACTOR_FAILED",
    "EXTRACTION_CRITICAL_WARNING",
    "DISCREPANCY_BLOCKING",
]
Severity = Literal["CRITICAL", "WARNING"]

# Warnings that mean the extractor couldn't recover the primary output.
# Non-critical warnings (e.g. missing_sheet:SystemCam on a rich CAM) stay
# quiet on the bell.
_CRITICAL_WARNING_PREFIXES: tuple[str, ...] = (
    "missing_credit_score",
    "no_accounts",
    "no_account_header_detected",
    "missing_applicant_name",
    "no_known_fields_matched",
)


@dataclass
class Notification:
    """Single actionable issue for a case.

    ``id`` is a stable composite so SWR can dedupe and so the frontend can
    mark one dismissed without re-fetching.
    """

    id: str
    case_id: UUID
    loan_id: str
    applicant_name: str | None
    kind: NotificationKind
    severity: Severity
    title: str
    description: str
    action_label: str
    action_tab: str  # which tab to land on when clicked
    created_at: datetime

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": str(self.case_id),
            "loan_id": self.loan_id,
            "applicant_name": self.applicant_name,
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "action_label": self.action_label,
            "action_tab": self.action_tab,
            "created_at": self.created_at.isoformat(),
        }


async def _missing_docs_notifications(session: AsyncSession) -> list[Notification]:
    stmt = select(Case).where(
        and_(Case.current_stage == CaseStage.CHECKLIST_MISSING_DOCS, Case.is_deleted == False)  # noqa: E712
    )
    result = await session.execute(stmt)
    out: list[Notification] = []
    for case in result.scalars():
        out.append(
            Notification(
                id=f"missing-docs:{case.id}",
                case_id=case.id,
                loan_id=case.loan_id,
                applicant_name=case.applicant_name,
                kind="MISSING_DOCS",
                severity="CRITICAL",
                title=f"Missing documents on {case.loan_id}",
                description=(
                    "Checklist validation flagged missing documents. "
                    "Open the Checklist tab to see which files are still required, "
                    "then use the 'Re-upload' or 'Add artifact' action to fix it."
                ),
                action_label="Open Checklist",
                action_tab="checklist",
                created_at=case.updated_at or case.created_at,
            )
        )
    return out


async def _extraction_notifications(session: AsyncSession) -> list[Notification]:
    stmt = (
        select(CaseExtraction, Case)
        .join(Case, Case.id == CaseExtraction.case_id)
        .where(Case.is_deleted == False)  # noqa: E712
        .where(
            CaseExtraction.status.in_((ExtractionStatus.FAILED, ExtractionStatus.PARTIAL))
        )
    )
    result = await session.execute(stmt)
    out: list[Notification] = []
    for extraction, case in result.all():
        warnings = extraction.warnings or []
        critical_hit = [
            w
            for w in warnings
            if isinstance(w, str)
            and any(w.startswith(prefix) for prefix in _CRITICAL_WARNING_PREFIXES)
        ]

        if extraction.status == ExtractionStatus.FAILED:
            out.append(
                Notification(
                    id=f"ext-fail:{extraction.id}",
                    case_id=case.id,
                    loan_id=case.loan_id,
                    applicant_name=case.applicant_name,
                    kind="EXTRACTOR_FAILED",
                    severity="CRITICAL",
                    title=f"{extraction.extractor_name} failed on {case.loan_id}",
                    description=(
                        extraction.error_message
                        or f"The {extraction.extractor_name} extractor couldn't parse its input. "
                        "Open the Extractions tab to inspect, or re-upload a clean file."
                    ),
                    action_label="Open Extractions",
                    action_tab="extractions",
                    created_at=extraction.extracted_at,
                )
            )
        elif critical_hit:
            out.append(
                Notification(
                    id=f"ext-warn:{extraction.id}",
                    case_id=case.id,
                    loan_id=case.loan_id,
                    applicant_name=case.applicant_name,
                    kind="EXTRACTION_CRITICAL_WARNING",
                    severity="WARNING",
                    title=f"{extraction.extractor_name} missing critical fields on {case.loan_id}",
                    description=(
                        f"Extractor reported: {', '.join(critical_hit)}. "
                        "Review the Extractions tab — you may need to replace the source file "
                        "if the data genuinely isn't there."
                    ),
                    action_label="Open Extractions",
                    action_tab="extractions",
                    created_at=extraction.extracted_at,
                )
            )
    return out


async def _discrepancy_notifications(session: AsyncSession) -> list[Notification]:
    """Emit one notification per case with ≥1 unresolved CRITICAL CAM discrepancy.

    Uses the service's get_summary() so the logic stays in one place (and
    resolutions stop the notification automatically on next poll).
    No-ops when the discrepancy service isn't importable on this branch.
    """
    if get_disc_summary is None:
        return []
    # Candidate cases — anything with an auto_cam extraction. Reusing the
    # case_extractions row as the fan-out is cheaper than scanning all cases.
    stmt = (
        select(Case)
        .distinct()
        .join(CaseExtraction, CaseExtraction.case_id == Case.id)
        .where(Case.is_deleted == False)  # noqa: E712
        .where(CaseExtraction.extractor_name == "auto_cam")
    )
    result = await session.execute(stmt)
    out: list[Notification] = []
    for case in result.scalars():
        summary = await get_disc_summary(session, case.id)
        if summary.unresolved_critical == 0:
            continue
        out.append(
            Notification(
                id=f"disc-critical:{case.id}",
                case_id=case.id,
                loan_id=case.loan_id,
                applicant_name=case.applicant_name,
                kind="DISCREPANCY_BLOCKING",
                severity="CRITICAL",
                title=(
                    f"{summary.unresolved_critical} CAM discrepanc"
                    f"{'y' if summary.unresolved_critical == 1 else 'ies'} "
                    f"on {case.loan_id}"
                ),
                description=(
                    "SystemCam (finpage) and CM CAM IL (manual) disagree on one or more "
                    "critical fields. Verification 2 is blocked until each is corrected or "
                    "justified on the Discrepancies tab."
                ),
                action_label="Open Discrepancies",
                action_tab="discrepancies",
                created_at=summary.generated_at,
            )
        )
    return out


async def list_notifications(session: AsyncSession) -> list[Notification]:
    """Return all current notifications, CRITICAL first, then by recency."""
    all_notifs: list[Notification] = []
    all_notifs.extend(await _missing_docs_notifications(session))
    all_notifs.extend(await _extraction_notifications(session))
    try:
        all_notifs.extend(await _discrepancy_notifications(session))
    except Exception:
        # Discrepancy service depends on tables that may not exist in all
        # branches yet (see cam-discrepancy vs 4level-l1 merge note).
        # Bell should still render for other sources.
        import logging

        logging.getLogger(__name__).warning(
            "Skipping discrepancy notifications — service unavailable", exc_info=True
        )

    # Sort: CRITICAL first, then newest first.
    severity_rank = {"CRITICAL": 0, "WARNING": 1}
    all_notifs.sort(
        key=lambda n: (
            severity_rank.get(n.severity, 9),
            -(n.created_at.replace(tzinfo=UTC).timestamp() if n.created_at else 0),
        )
    )
    return all_notifs
