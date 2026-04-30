"""Shared helpers for verification-level orchestrators.

``carry_forward_prior_decisions`` preserves terminal MD / assessor
decisions across level re-runs. Without it, every re-trigger creates a
fresh ``VerificationResult`` + ``LevelIssue`` set and silently orphans
any MD_APPROVED / MD_REJECTED / ASSESSOR_RESOLVED stamps from prior
runs. The MD would then have to re-adjudicate identical issues — or
worse, the audit trail would show the final run's issues as unresolved
even though the MD already cleared them.

Called by every ``run_level_*`` orchestrator just before the final
``await session.flush()``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    LevelIssueSeverity,
    LevelIssueStatus,
    VerificationLevelNumber,
    VerificationLevelStatus,
)
from app.models.level_issue import LevelIssue
from app.models.verification_result import VerificationResult


async def _fetch_previous_vr(
    session: AsyncSession,
    case_id: UUID,
    level_number: VerificationLevelNumber,
    *,
    exclude_id: UUID,
) -> VerificationResult | None:
    """Return the most recent VR for ``(case_id, level_number)`` other than
    the current run (``exclude_id``). ``None`` when the current run is the
    first."""
    stmt = (
        select(VerificationResult)
        .where(VerificationResult.case_id == case_id)
        .where(VerificationResult.level_number == level_number)
        .where(VerificationResult.id != exclude_id)
        .order_by(desc(VerificationResult.created_at))
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def carry_forward_prior_decisions(
    session: AsyncSession,
    *,
    result: VerificationResult,
) -> None:
    """Copy terminal MD + assessor decisions from the previous run onto the
    newly created issues of ``result``, keyed by ``sub_step_id``.

    Also recomputes ``result.status``: if any BLOCKED-causing issue was
    carried forward as ``MD_APPROVED`` *and* every remaining critical
    issue ends up settled, the level is promoted from ``BLOCKED`` to
    ``PASSED_WITH_MD_OVERRIDE``.

    Safe to call when there is no prior run — it's a no-op in that case.
    Must be called after the orchestrator has added this run's issues +
    called ``session.flush()`` so that ``LevelIssue.verification_result_id``
    rows for ``result.id`` are readable.
    """
    prev_vr = await _fetch_previous_vr(
        session,
        result.case_id,
        result.level_number,
        exclude_id=result.id,
    )
    if prev_vr is None:
        return

    prev_issues_stmt = select(LevelIssue).where(
        LevelIssue.verification_result_id == prev_vr.id
    )
    prev_issues = list((await session.execute(prev_issues_stmt)).scalars().all())
    if not prev_issues:
        return
    prev_by_step: dict[str, LevelIssue] = {i.sub_step_id: i for i in prev_issues}

    new_issues_stmt = select(LevelIssue).where(
        LevelIssue.verification_result_id == result.id
    )
    new_issues = list((await session.execute(new_issues_stmt)).scalars().all())
    if not new_issues:
        return

    terminal_md = {
        LevelIssueStatus.MD_APPROVED,
        LevelIssueStatus.MD_REJECTED,
    }
    for new_iss in new_issues:
        prev = prev_by_step.get(new_iss.sub_step_id)
        if prev is None:
            continue
        if prev.status in terminal_md:
            new_iss.status = prev.status
            new_iss.md_user_id = prev.md_user_id
            new_iss.md_reviewed_at = prev.md_reviewed_at
            new_iss.md_rationale = prev.md_rationale
            # Assessor stamp rides along so the audit chain stays intact.
            new_iss.assessor_user_id = prev.assessor_user_id
            new_iss.assessor_resolved_at = prev.assessor_resolved_at
            new_iss.assessor_note = prev.assessor_note
        elif prev.status == LevelIssueStatus.ASSESSOR_RESOLVED:
            new_iss.status = prev.status
            new_iss.assessor_user_id = prev.assessor_user_id
            new_iss.assessor_resolved_at = prev.assessor_resolved_at
            new_iss.assessor_note = prev.assessor_note

    # Recompute the level status: if the carry-forward turned all BLOCKED-
    # causing CRITICALs into MD_APPROVED (or there were no MD_REJECTED), we
    # promote the level to PASSED_WITH_MD_OVERRIDE. We only touch the case
    # where the orchestrator itself landed on BLOCKED — a PASS stays PASS,
    # a FAILED stays FAILED.
    if result.status == VerificationLevelStatus.BLOCKED:
        any_rejected = any(
            i.status == LevelIssueStatus.MD_REJECTED for i in new_issues
        )
        any_unsettled_critical = any(
            i.severity == LevelIssueSeverity.CRITICAL
            and i.status not in terminal_md
            for i in new_issues
        )
        if not any_rejected and not any_unsettled_critical:
            result.status = VerificationLevelStatus.PASSED_WITH_MD_OVERRIDE

    # Flush mutations so callers that ``refresh()`` the issue / VR
    # afterwards see the carried-forward state, and so the orchestrator's
    # own trailing flush doesn't need to remember to re-touch these rows.
    await session.flush()


__all__: list[str] = ["carry_forward_prior_decisions"]
