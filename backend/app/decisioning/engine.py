"""Pipeline orchestrator for Phase 1 decisioning.

Runs all 11 steps in order, persists after each step, supports resume-from-last-successful.
"""
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.decisioning.case_library import compute_feature_vector
from app.models.verification_result import VerificationResult
from app.enums import VerificationLevelNumber
from app.decisioning.steps import (
    step_01_policy_gates,
    step_02_banking,
    step_03_income,
    step_04_kyc,
    step_05_address,
    step_06_business,
    step_07_stock,
    step_08_reconciliation,
    step_09_pd_sheet,
    step_10_retrieval,
    step_11_synthesis,
)
from app.decisioning.steps.base import StepOutput
from app.enums import CaseStage, DecisionStatus, StepStatus
from app.memory.loader import load_heuristics, load_policy
from app.models.case import Case
from app.models.case_artifact import CaseArtifact
from app.models.case_extraction import CaseExtraction
from app.models.decision_result import DecisionResult
from app.models.decision_step import DecisionStep
from app.services import audit as audit_svc
from app.services import stages as stages_svc
from app.services.claude import get_claude_service

_log = logging.getLogger(__name__)

_STEP_MODULES = [
    step_01_policy_gates,
    step_02_banking,
    step_03_income,
    step_04_kyc,
    step_05_address,
    step_06_business,
    step_07_stock,
    step_08_reconciliation,
    step_09_pd_sheet,
    step_10_retrieval,
    step_11_synthesis,
]

# Steps whose job is already done by the 4-Level Verification gate when it
# has run. Step 11's prompt already tells Opus to weight Verification
# highest and treat these as supporting evidence only — so running them is
# pure token waste and can confuse the synthesis by repeating (worse-quality)
# judgments about the same evidence. When at least one VerificationResult
# exists for the case we mark these as SKIPPED with a rationale line.
#   2 banking_check       ← covered by L2 Banking (CA-grade)
#   4 kyc_verification    ← covered by L1 Address (Aadhaar/PAN/ration scan)
#   5 address_verification← covered by L1 Address (GPS + pincode master)
#   6 business_premises   ← covered by L3 Vision
#   7 stock_quantification← covered by L3 Vision + L4 Loan-Agreement assets
_VERIFICATION_COVERED_STEPS: frozenset[int] = frozenset({2, 4, 5, 6, 7})

_SKIP_COVERAGE_MAP: dict[int, str] = {
    2: "L2 Banking (CA-grade)",
    4: "L1 Address (Aadhaar / PAN / ration document scan)",
    5: "L1 Address (GPS cross-check + pincode master)",
    6: "L3 Vision (house + business premises scoring)",
    7: "L3 Vision + L4 Loan-Agreement asset audit",
}


class SimpleContext:
    """Concrete implementation of StepContext Protocol."""

    def __init__(
        self,
        case: Any,
        artifacts: Any,
        extractions: Any,
        policy: Any,
        heuristics: Any,
        db_session: Any = None,
        verification_results: dict[str, Any] | None = None,
    ) -> None:
        self.case = case
        self.artifacts = artifacts
        self.extractions = extractions
        self.policy = policy
        self.heuristics = heuristics
        self.prior_steps: dict[int, StepOutput] = {}
        self.db_session = db_session
        # Latest VerificationResult per level (L1/L2/L3/L4) — feeds Step 11
        # as the highest-weight evidence block. Keys are the enum value
        # strings so Step 11 doesn't need to import the enum.
        self.verification_results: dict[str, Any] = verification_results or {}


async def run_phase1(
    session: AsyncSession,
    decision_result_id: UUID,
    *,
    actor_user_id: UUID,
) -> None:
    """Entry point: given a DecisionResult row, run all 11 steps to completion."""
    dr = await session.get(DecisionResult, decision_result_id)
    if dr is None or dr.status == DecisionStatus.COMPLETED:
        _log.info("run_phase1: %s skipped (not found or already complete)", decision_result_id)
        return

    # Audit start
    dr.status = DecisionStatus.RUNNING
    dr.started_at = datetime.now(UTC)
    await session.flush()

    await audit_svc.log_action(
        session, actor_user_id=actor_user_id,
        action="decision.started", entity_type="decision_result",
        entity_id=str(dr.id), after={"case_id": str(dr.case_id)},
    )

    # Build context
    case: Case = await session.get(Case, dr.case_id)  # type: ignore[assignment]
    artifacts_res = await session.execute(
        select(CaseArtifact).where(CaseArtifact.case_id == dr.case_id)
    )
    artifacts = list(artifacts_res.scalars().all())
    extractions_res = await session.execute(
        select(CaseExtraction).where(CaseExtraction.case_id == dr.case_id)
    )
    extractions_rows = list(extractions_res.scalars().all())
    extractions = {row.extractor_name: row.data or {} for row in extractions_rows}

    policy = load_policy()
    heuristics = load_heuristics()

    # Latest VerificationResult per level — feeds Step 11 as highest-weight
    # evidence. If a level has never run for this case, its entry stays None
    # and Step 11 treats it as PENDING (capping confidence at 70).
    verif_by_level: dict[str, VerificationResult | None] = {}
    for level in VerificationLevelNumber:
        latest = (
            await session.execute(
                select(VerificationResult)
                .where(VerificationResult.case_id == dr.case_id)
                .where(VerificationResult.level_number == level)
                .order_by(VerificationResult.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        verif_by_level[level.value] = latest

    ctx = SimpleContext(
        case,
        artifacts,
        extractions,
        policy,
        heuristics,
        db_session=session,
        verification_results=verif_by_level,
    )

    claude = get_claude_service()
    total_cost = Decimal("0")
    token_usage: dict[str, Any] = {}

    # If at least one Verification level has run for this case, the
    # verification-covered steps are redundant. The 4-level outputs are
    # already the highest-weight evidence Opus gets in Step 11.
    _verification_has_any_result = any(v is not None for v in verif_by_level.values())

    for mod in _STEP_MODULES:
        # Check if step already succeeded (resume) OR was skipped previously
        existing = await session.execute(
            select(DecisionStep).where(
                DecisionStep.decision_result_id == dr.id,
                DecisionStep.step_number == mod.STEP_NUMBER,
            )
        )
        existing_step = existing.scalar_one_or_none()
        if existing_step and existing_step.status in (
            StepStatus.SUCCEEDED,
            StepStatus.SKIPPED,
        ):
            # Populate ctx from prior run
            ctx.prior_steps[mod.STEP_NUMBER] = StepOutput(
                status=existing_step.status,
                step_name=existing_step.step_name,
                step_number=existing_step.step_number,
                model_used=existing_step.model_used,
                output_data=existing_step.output_data or {},
                citations=[],  # resume: citations already persisted
            )
            continue

        # Skip redundant steps when Verification has run. Persist a SKIPPED
        # row so the UI can show the user why the step had no cost, and
        # so Step 11's ctx.prior_steps still has something to iterate.
        if (
            _verification_has_any_result
            and mod.STEP_NUMBER in _VERIFICATION_COVERED_STEPS
        ):
            coverage = _SKIP_COVERAGE_MAP.get(mod.STEP_NUMBER, "verification")
            skip_output = {
                "skipped_reason": "verification_covers",
                "covered_by": coverage,
                "detail": (
                    f"Skipped — the 4-Level Verification gate covers this "
                    f"check via {coverage}. Step 11 reads Verification "
                    f"outputs directly with higher weight."
                ),
            }
            await _persist_step(
                session,
                dr.id,
                mod.STEP_NUMBER,
                mod.STEP_NAME,
                StepStatus.SKIPPED,
                None,
                skip_output,
                None,
                None,
                {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "cost_usd": "0"},
            )
            ctx.prior_steps[mod.STEP_NUMBER] = StepOutput(
                status=StepStatus.SKIPPED,
                step_name=mod.STEP_NAME,
                step_number=mod.STEP_NUMBER,
                model_used=None,
                output_data=skip_output,
                citations=[],
            )
            continue

        # Audit step start
        await audit_svc.log_action(
            session, actor_user_id=actor_user_id,
            action="decision.step_started", entity_type="decision_step",
            entity_id=None,
            after={"decision_result_id": str(dr.id), "step_number": mod.STEP_NUMBER},
        )

        # Run step
        try:
            result = await mod.run(ctx, claude)
        except Exception as exc:
            _log.exception("Step %s failed for dr=%s", mod.STEP_NUMBER, dr.id)
            await _persist_step(
                session, dr.id, mod.STEP_NUMBER, mod.STEP_NAME,
                StepStatus.FAILED, None, None, None, str(exc), None,
            )
            await audit_svc.log_action(
                session, actor_user_id=actor_user_id,
                action="decision.step_failed", entity_type="decision_step",
                entity_id=None,
                after={"step": mod.STEP_NUMBER, "error": str(exc)},
            )
            dr.status = DecisionStatus.FAILED
            dr.error_message = f"Step {mod.STEP_NUMBER} failed: {exc}"
            dr.completed_at = datetime.now(UTC)
            await session.flush()
            return

        # Persist step
        await _persist_step(
            session, dr.id, result.step_number, result.step_name,
            result.status, result.model_used, result.output_data,
            result.citations, result.error_message,
            {"input": result.input_tokens, "output": result.output_tokens,
             "cache_read": result.cache_read_tokens, "cache_creation": result.cache_creation_tokens,
             "cost_usd": str(result.cost_usd)},
        )
        total_cost += Decimal(str(result.cost_usd or 0))
        token_usage[result.step_name] = {
            "input": result.input_tokens,
            "output": result.output_tokens,
        }

        ctx.prior_steps[result.step_number] = result

        # Hard-fail short-circuit
        if result.hard_fail:
            break

    # Extract synthesis output
    synthesis = ctx.prior_steps.get(11)
    if synthesis and synthesis.status == StepStatus.SUCCEEDED:
        data = synthesis.output_data
        dr.final_decision = data.get("decision")
        dr.recommended_amount = data.get("recommended_amount")
        dr.recommended_tenure = data.get("recommended_tenure")
        dr.conditions = data.get("conditions", [])
        dr.reasoning_markdown = data.get("reasoning_markdown")
        dr.pros_cons = data.get("pros_cons")
        dr.deviations = data.get("deviations")
        dr.risk_summary = data.get("risk_summary")
        dr.confidence_score = data.get("confidence_score")

    # Compute feature vector for case library (extract params from synthesis output)
    try:
        synthesis_data = (ctx.prior_steps.get(11) or None)
        _fv_kwargs: dict[str, float | str] = {}
        if synthesis_data:
            sd = synthesis_data.output_data or {}
            if sd.get("recommended_amount"):
                _fv_kwargs["loan_amount"] = float(sd["recommended_amount"])
            if sd.get("recommended_tenure"):
                _fv_kwargs["tenure_months"] = float(sd["recommended_tenure"])
        dr.feature_vector = compute_feature_vector(**_fv_kwargs)  # type: ignore[arg-type]
    except Exception:
        _log.warning("feature_vector computation failed", exc_info=True)

    dr.status = DecisionStatus.COMPLETED
    dr.total_cost_usd = total_cost
    dr.token_usage = token_usage
    dr.completed_at = datetime.now(UTC)

    # Transition case stage
    try:
        await stages_svc.transition_stage(
            session=session, case=case, to=CaseStage.PHASE_1_COMPLETE,
            actor_user_id=actor_user_id,
        )
    except Exception:
        _log.warning("stage transition failed", exc_info=True)

    await audit_svc.log_action(
        session, actor_user_id=actor_user_id,
        action="decision.completed", entity_type="decision_result",
        entity_id=str(dr.id),
        after={"decision": dr.final_decision, "total_cost_usd": str(total_cost)},
    )


async def _persist_step(  # noqa: PLR0913
    session: Any,
    dr_id: UUID,
    step_number: int,
    step_name: str,
    status: Any,
    model_used: str | None,
    output_data: dict[str, Any] | None,
    citations: list[Any] | None,
    error_message: str | None,
    usage: dict[str, Any] | None,
) -> None:
    """Upsert DecisionStep row."""
    existing = await session.execute(
        select(DecisionStep).where(
            DecisionStep.decision_result_id == dr_id,
            DecisionStep.step_number == step_number,
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = DecisionStep(
            decision_result_id=dr_id,
            step_number=step_number,
            step_name=step_name,
            started_at=datetime.now(UTC),
        )
        session.add(row)
    row.status = status
    row.model_used = model_used
    row.output_data = output_data or {}
    row.citations = citations or []
    row.error_message = error_message
    if usage:
        row.input_tokens = usage.get("input")
        row.output_tokens = usage.get("output")
        row.cache_read_tokens = usage.get("cache_read")
        row.cache_creation_tokens = usage.get("cache_creation")
        row.cost_usd = Decimal(usage.get("cost_usd") or "0")
    row.completed_at = datetime.now(UTC)
    await session.flush()
