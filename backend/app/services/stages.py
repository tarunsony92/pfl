"""Case workflow state machine.

Defines which stage transitions are permitted. M2 only executes
UPLOADED → CHECKLIST_VALIDATION; other transitions live here but are invoked
only in later milestones.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateTransition
from app.enums import CaseStage
from app.models.case import Case
from app.services import audit as audit_svc

ALLOWED_TRANSITIONS: dict[CaseStage, set[CaseStage]] = {
    CaseStage.UPLOADED: {CaseStage.CHECKLIST_VALIDATION},
    CaseStage.CHECKLIST_VALIDATION: {
        CaseStage.CHECKLIST_MISSING_DOCS,
        CaseStage.CHECKLIST_VALIDATED,
    },
    CaseStage.CHECKLIST_MISSING_DOCS: {CaseStage.CHECKLIST_VALIDATION},
    CaseStage.CHECKLIST_VALIDATED: {CaseStage.INGESTED, CaseStage.CHECKLIST_VALIDATION},
    CaseStage.INGESTED: {CaseStage.PHASE_1_DECISIONING, CaseStage.CHECKLIST_VALIDATION},
    CaseStage.PHASE_1_DECISIONING: {
        CaseStage.PHASE_1_COMPLETE,
        CaseStage.PHASE_1_REJECTED,
        CaseStage.INGESTED,  # failure rollback / cancel
    },
    CaseStage.PHASE_1_COMPLETE: {CaseStage.PHASE_2_AUDITING},
    CaseStage.PHASE_2_AUDITING: {CaseStage.PHASE_2_COMPLETE},
    CaseStage.PHASE_2_COMPLETE: {CaseStage.HUMAN_REVIEW},
    CaseStage.HUMAN_REVIEW: {
        CaseStage.APPROVED,
        CaseStage.REJECTED,
        CaseStage.ESCALATED_TO_CEO,
    },
    CaseStage.ESCALATED_TO_CEO: {CaseStage.APPROVED, CaseStage.REJECTED},
    # Terminal states:
    CaseStage.PHASE_1_REJECTED: set(),
    CaseStage.APPROVED: set(),
    CaseStage.REJECTED: set(),
}


def validate_transition(from_stage: CaseStage, to_stage: CaseStage) -> None:
    """Raises InvalidStateTransition if the transition is not permitted."""
    allowed = ALLOWED_TRANSITIONS.get(from_stage, set())
    if to_stage not in allowed:
        raise InvalidStateTransition(
            f"{from_stage} → {to_stage} not allowed. "
            f"Permitted from {from_stage}: {sorted(s.value for s in allowed) or 'none (terminal)'}"
        )


async def transition_stage(
    session: AsyncSession,
    *,
    case: Case,
    to: CaseStage,
    actor_user_id: UUID,
) -> Case:
    """Move a case to a new stage, validating + logging."""
    validate_transition(case.current_stage, to)
    before = {"stage": case.current_stage.value}
    case.current_stage = to
    await audit_svc.log_action(
        session,
        actor_user_id=actor_user_id,
        action="case.stage_changed",
        entity_type="case",
        entity_id=str(case.id),
        before=before,
        after={"stage": case.current_stage.value},
    )
    return case
