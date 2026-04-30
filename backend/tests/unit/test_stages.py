"""State machine unit tests. Pure logic, no DB."""

import pytest

from app.core.exceptions import InvalidStateTransition
from app.enums import CaseStage
from app.services.stages import ALLOWED_TRANSITIONS, validate_transition


class TestAllowedTransitions:
    def test_uploaded_can_go_to_checklist_validation(self):
        validate_transition(CaseStage.UPLOADED, CaseStage.CHECKLIST_VALIDATION)

    def test_checklist_validation_can_branch(self):
        validate_transition(CaseStage.CHECKLIST_VALIDATION, CaseStage.CHECKLIST_MISSING_DOCS)
        validate_transition(CaseStage.CHECKLIST_VALIDATION, CaseStage.CHECKLIST_VALIDATED)

    def test_missing_docs_returns_to_validation(self):
        validate_transition(CaseStage.CHECKLIST_MISSING_DOCS, CaseStage.CHECKLIST_VALIDATION)

    def test_phase_1_rejected_is_terminal(self):
        """Hard-rule reject has no outgoing transitions."""
        assert ALLOWED_TRANSITIONS.get(CaseStage.PHASE_1_REJECTED, set()) == set()

    def test_approved_is_terminal(self):
        assert ALLOWED_TRANSITIONS.get(CaseStage.APPROVED, set()) == set()

    def test_reingest_from_ingested_allows_checklist_validation(self):
        validate_transition(CaseStage.INGESTED, CaseStage.CHECKLIST_VALIDATION)

    def test_reingest_from_validated_allows_checklist_validation(self):
        validate_transition(CaseStage.CHECKLIST_VALIDATED, CaseStage.CHECKLIST_VALIDATION)

    def test_ingested_still_allows_phase_1_decisioning(self):
        validate_transition(CaseStage.INGESTED, CaseStage.PHASE_1_DECISIONING)


class TestInvalidTransitions:
    def test_uploaded_cannot_skip_to_approved(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(CaseStage.UPLOADED, CaseStage.APPROVED)

    def test_same_state_not_allowed(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(CaseStage.UPLOADED, CaseStage.UPLOADED)

    def test_backwards_from_ingested_not_allowed(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(CaseStage.INGESTED, CaseStage.UPLOADED)

    def test_error_message_names_both_stages(self):
        with pytest.raises(InvalidStateTransition, match="UPLOADED.*APPROVED"):
            validate_transition(CaseStage.UPLOADED, CaseStage.APPROVED)


class TestPhase1DecisioningTransitions:
    """Stage machine tests for M5 decisioning transitions."""

    def test_ingested_to_phase1_decisioning(self):
        validate_transition(CaseStage.INGESTED, CaseStage.PHASE_1_DECISIONING)

    def test_phase1_decisioning_to_complete(self):
        validate_transition(CaseStage.PHASE_1_DECISIONING, CaseStage.PHASE_1_COMPLETE)

    def test_phase1_decisioning_to_rejected(self):
        validate_transition(CaseStage.PHASE_1_DECISIONING, CaseStage.PHASE_1_REJECTED)

    def test_phase1_decisioning_reverts_to_ingested_on_cancel(self):
        """Pipeline failure or cancel rolls back stage to INGESTED."""
        validate_transition(CaseStage.PHASE_1_DECISIONING, CaseStage.INGESTED)

    def test_phase1_rejected_is_terminal_after_m5(self):
        """PHASE_1_REJECTED stage has no allowed outbound transitions."""
        from app.services.stages import ALLOWED_TRANSITIONS

        assert CaseStage.PHASE_1_REJECTED in ALLOWED_TRANSITIONS
        assert len(ALLOWED_TRANSITIONS[CaseStage.PHASE_1_REJECTED]) == 0

    def test_phase1_decisioning_cannot_go_to_uploaded(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition(CaseStage.PHASE_1_DECISIONING, CaseStage.UPLOADED)
