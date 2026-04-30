"""Admin Learning Rules HTTP endpoints.

Surfaces the editable control surface behind /admin/learning-rules:

  GET  /admin/rule-stats             → aggregated fire counts + MD decisions
  GET  /admin/rule-overrides          → current override list
  PUT  /admin/rule-overrides/{id}     → upsert (suppress + admin note)
  DELETE /admin/rule-overrides/{id}   → clear override

All endpoints require UserRole.ADMIN.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_role
from app.enums import LevelIssueStatus, UserRole
from app.models.level_issue import LevelIssue
from app.models.rule_override import RuleOverride
from app.models.user import User
from app.schemas.rule_override import (
    RuleMDDecisionSample,
    RuleOverrideRead,
    RuleOverrideUpsertRequest,
    RuleStatRead,
)

router = APIRouter(prefix="/admin/rules", tags=["admin-rules"])


@router.get("/stats", response_model=list[RuleStatRead])
async def list_rule_stats(
    _actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> list[RuleStatRead]:
    """Aggregate every rule that has ever fired + its current override.

    Per-rule counts come straight from LevelIssue. Rules that have never
    fired don't appear here — the frontend pairs this against its own
    RULE_CATALOG to fill in rule metadata (title / description / level)
    and to show zero-fire rules explicitly.
    """
    # Fire counts by (sub_step_id, status).
    count_q = (
        select(
            LevelIssue.sub_step_id,
            LevelIssue.status,
            func.count().label("n"),
        )
        .group_by(LevelIssue.sub_step_id, LevelIssue.status)
    )
    count_rows = (await session.execute(count_q)).all()

    stats_by_rule: dict[str, dict[str, int]] = {}
    for row in count_rows:
        bucket = stats_by_rule.setdefault(
            row.sub_step_id,
            {
                "total": 0,
                "open": 0,
                "assessor_resolved": 0,
                "md_approved": 0,
                "md_rejected": 0,
            },
        )
        bucket["total"] += int(row.n)
        st = row.status
        if st == LevelIssueStatus.OPEN:
            bucket["open"] += int(row.n)
        elif st == LevelIssueStatus.ASSESSOR_RESOLVED:
            bucket["assessor_resolved"] += int(row.n)
        elif st == LevelIssueStatus.MD_APPROVED:
            bucket["md_approved"] += int(row.n)
        elif st == LevelIssueStatus.MD_REJECTED:
            bucket["md_rejected"] += int(row.n)

    # Overrides keyed by sub_step_id.
    override_rows = (await session.execute(select(RuleOverride))).scalars().all()
    overrides_by_rule: dict[str, RuleOverride] = {
        o.sub_step_id: o for o in override_rows
    }

    # Include override-only rules (suppressed before ever firing) so the
    # operator can still see them.
    all_ids = set(stats_by_rule.keys()) | set(overrides_by_rule.keys())

    # Recent MD samples per rule — at most 5, most recent first. One round
    # trip per rule is fine at this scale (<100 distinct rules).
    out: list[RuleStatRead] = []
    for sub_id in sorted(all_ids):
        bucket = stats_by_rule.get(
            sub_id,
            {
                "total": 0,
                "open": 0,
                "assessor_resolved": 0,
                "md_approved": 0,
                "md_rejected": 0,
            },
        )
        override = overrides_by_rule.get(sub_id)

        samples_q = (
            select(LevelIssue)
            .where(LevelIssue.sub_step_id == sub_id)
            .where(
                LevelIssue.status.in_(
                    (LevelIssueStatus.MD_APPROVED, LevelIssueStatus.MD_REJECTED)
                )
            )
            .where(LevelIssue.md_reviewed_at.is_not(None))
            .order_by(desc(LevelIssue.md_reviewed_at))
            .limit(5)
        )
        samples_rows = (await session.execute(samples_q)).scalars().all()
        vr_cache: dict = {}
        samples: list[RuleMDDecisionSample] = []
        for li in samples_rows:
            # We need case_id — pull it off the VerificationResult FK.
            from app.models.verification_result import VerificationResult
            vr = vr_cache.get(li.verification_result_id)
            if vr is None:
                vr = await session.get(
                    VerificationResult, li.verification_result_id
                )
                vr_cache[li.verification_result_id] = vr
            if vr is None:
                continue
            samples.append(
                RuleMDDecisionSample(
                    issue_id=li.id,
                    case_id=vr.case_id,
                    decision=li.status.value,  # type: ignore[arg-type]
                    rationale=li.md_rationale,
                    reviewed_at=li.md_reviewed_at,  # type: ignore[arg-type]
                )
            )

        out.append(
            RuleStatRead(
                sub_step_id=sub_id,
                total_fires=bucket["total"],
                open_count=bucket["open"],
                assessor_resolved_count=bucket["assessor_resolved"],
                md_approved_count=bucket["md_approved"],
                md_rejected_count=bucket["md_rejected"],
                is_suppressed=bool(override and override.is_suppressed),
                admin_note=override.admin_note if override else None,
                last_edited_at=override.last_edited_at if override else None,
                recent_md_samples=samples,
            )
        )
    return out


@router.get("/overrides", response_model=list[RuleOverrideRead])
async def list_rule_overrides(
    _actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> list[RuleOverride]:
    """Return every rule override row, ordered by sub_step_id.

    The FE pairs this list with its RULE_CATALOG so suppressed rules can
    be highlighted in the Learning Rules table even when their stats
    bucket is empty.
    """
    rows = (
        (await session.execute(select(RuleOverride).order_by(RuleOverride.sub_step_id)))
        .scalars()
        .all()
    )
    return list(rows)


@router.put("/overrides/{sub_step_id}", response_model=RuleOverrideRead)
async def upsert_rule_override(
    sub_step_id: str,
    body: RuleOverrideUpsertRequest,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> RuleOverride:
    """Create or patch the override row for ``sub_step_id``.

    Fields supplied as ``None`` on the request are left untouched on an
    existing override (lets callers PATCH just one column). The actor
    + ``last_edited_at`` are always refreshed so the audit trail is
    accurate even when the operator only edits the admin note.
    """
    if not sub_step_id or len(sub_step_id) > 128:
        raise HTTPException(status_code=400, detail="invalid sub_step_id")

    override = await session.get(RuleOverride, sub_step_id)
    if override is None:
        override = RuleOverride(
            sub_step_id=sub_step_id,
            is_suppressed=bool(body.is_suppressed) if body.is_suppressed is not None else False,
            admin_note=body.admin_note,
            updated_by=actor.id,
            last_edited_at=datetime.now(UTC),
        )
        session.add(override)
    else:
        if body.is_suppressed is not None:
            override.is_suppressed = body.is_suppressed
        if body.admin_note is not None:
            override.admin_note = body.admin_note
        override.updated_by = actor.id
        override.last_edited_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(override)
    return override


@router.delete("/overrides/{sub_step_id}")
async def clear_rule_override(
    sub_step_id: str,
    _actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Delete the override row (rule reverts to default behaviour).

    Idempotent — returns ``{ok: True}`` whether the row existed or not so
    the FE doesn't need to special-case "already cleared".
    """
    override = await session.get(RuleOverride, sub_step_id)
    if override is None:
        return {"ok": True}
    await session.delete(override)
    await session.commit()
    return {"ok": True}
