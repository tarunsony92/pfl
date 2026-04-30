"""Admin endpoint to bulk-rerun L3 vision for stale cases.

Per spec §8 of the L3 Phase 2 MVP design, the per-case auto-refresh hook on
first view only catches cases an assessor opens. Cases that never get viewed
stay on the legacy schema (no `items[]`). This admin endpoint rolls them
forward in one shot:

  GET  /admin/l3/stale-extractions   → preview count + sample case ids
  POST /admin/l3/rerun-stale         → schedule one background re-run per
                                       stale case (returns count immediately)

Both require UserRole.ADMIN. The background task path uses FastAPI's built-in
BackgroundTasks — fire-and-forget, runs in the same process. At ~30s/case +
~$0.05/case Opus cost, a 100-case sweep takes <1 hour and <$5. If the volume
grows beyond ~500 cases, migrate to SQS via QueueService.

The per-case orchestrator already has a 5-min concurrency guard at
verification.py:trigger_level — running a duplicate re-run for a case that's
already mid-rerun is a no-op (it just finds the running VR and returns).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_role
from app.config import Settings, get_settings
from app.enums import UserRole, VerificationLevelNumber
from app.models.user import User
from app.models.verification_result import VerificationResult

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/l3", tags=["admin-l3"])

_PER_CASE_COST_USD = 0.05  # Opus business-premises scorer per call (spec §7.4)
_PREVIEW_CAP = 200  # cap case_ids list returned in preview to keep payload small


class StaleL3Preview(BaseModel):
    stale_count: int
    case_ids: list[UUID]
    estimated_cost_usd: float


class StaleL3RerunResponse(BaseModel):
    queued_count: int
    estimated_cost_usd: float


async def _query_stale_case_ids(session: AsyncSession) -> list[UUID]:
    """Return case_ids whose LATEST L3 VerificationResult is missing the v2
    `items[]` field — i.e., legacy schema, needs a re-run.

    Strategy: pull the latest L3 VR per case, filter in-Python to those whose
    sub_step_results.stock_analysis.items is missing. PostgreSQL window-function
    paths exist but this dataset is small (one row per case per level), so the
    direct path is clearer and has no edge-cases around JSONB null vs missing.
    """
    stmt = (
        select(VerificationResult)
        .where(VerificationResult.level_number == VerificationLevelNumber.L3_VISION)
        .order_by(VerificationResult.case_id, desc(VerificationResult.created_at))
    )
    rows = (await session.execute(stmt)).scalars().all()

    # First-seen-per-case is the latest because of the ORDER BY. dict insert
    # order is preserved on Python 3.7+.
    latest_by_case: dict[UUID, VerificationResult] = {}
    for vr in rows:
        if vr.case_id not in latest_by_case:
            latest_by_case[vr.case_id] = vr

    stale: list[UUID] = []
    for case_id, vr in latest_by_case.items():
        sub: dict[str, Any] | None = vr.sub_step_results
        if not sub:
            # No sub_step_results at all → this is a malformed/stub row, leave it.
            continue
        stock_analysis = sub.get("stock_analysis")
        if not isinstance(stock_analysis, dict):
            stale.append(case_id)
            continue
        if "items" not in stock_analysis:
            stale.append(case_id)
    return stale


@router.get("/stale-extractions", response_model=StaleL3Preview)
async def preview_stale(
    _actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> StaleL3Preview:
    """Show how many cases need a re-run + the cost estimate."""
    stale = await _query_stale_case_ids(session)
    return StaleL3Preview(
        stale_count=len(stale),
        case_ids=stale[:_PREVIEW_CAP],
        estimated_cost_usd=round(len(stale) * _PER_CASE_COST_USD, 2),
    )


async def _rerun_one_case(
    case_id: UUID,
    *,
    actor_id: UUID,
    settings: Settings,
) -> None:
    """Background task: open a fresh session, run L3 for the case, commit.

    Each task gets its own session (the request session is closed before the
    response is sent). Errors are logged but not raised — one bad case must
    not block the rest of the sweep.
    """
    # Lazy imports keep this module light on cold-start and avoid pulling in
    # storage / claude singletons at module load.
    from app.db import AsyncSessionLocal
    from app.services.claude import get_claude_service
    from app.services.storage import get_storage
    from app.verification.levels.level_3_vision import run_level_3_vision

    try:
        async with AsyncSessionLocal() as session:
            await run_level_3_vision(
                session,
                case_id,
                actor_user_id=actor_id,
                claude=get_claude_service(settings),
                storage=get_storage(settings),
            )
            await session.commit()
    except Exception:
        _log.exception("bulk-rerun L3 failed for case %s", case_id)


@router.post("/rerun-stale", response_model=StaleL3RerunResponse)
async def rerun_stale(
    background: BackgroundTasks,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> StaleL3RerunResponse:
    """Schedule a re-run for every stale case. Returns immediately."""
    stale = await _query_stale_case_ids(session)
    for case_id in stale:
        background.add_task(
            _rerun_one_case,
            case_id,
            actor_id=actor.id,
            settings=settings,
        )
    return StaleL3RerunResponse(
        queued_count=len(stale),
        estimated_cost_usd=round(len(stale) * _PER_CASE_COST_USD, 2),
    )
