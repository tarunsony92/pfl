"""Enum hygiene tests — values are stable identifiers."""

from app.enums import (
    ArtifactType,
    CaseStage,
    DecisionOutcome,
    DecisionStatus,
    MrpSource,
    StepStatus,
    UserRole,
)


class TestCaseStage:
    def test_has_exactly_14_values(self):
        # If this breaks, the enum was extended; update count + review migrations.
        assert len(list(CaseStage)) == 14

    def test_uploaded_is_first_and_matches_string(self):
        assert CaseStage.UPLOADED == "UPLOADED"

    def test_phase_1_rejected_is_distinct_from_rejected(self):
        assert CaseStage.PHASE_1_REJECTED != CaseStage.REJECTED


class TestArtifactType:
    def test_has_three_values(self):
        assert len(list(ArtifactType)) == 3

    def test_original_zip(self):
        assert ArtifactType.ORIGINAL_ZIP == "ORIGINAL_ZIP"


class TestUserRole:
    """Sanity — unchanged from M1."""

    def test_user_exists(self):
        assert UserRole.USER == "user"

    def test_admin_exists(self):
        assert UserRole.ADMIN == "admin"


class TestArtifactSubtype:
    def test_has_36_values(self):
        from app.enums import ArtifactSubtype

        assert len(list(ArtifactSubtype)) == 36

    def test_unknown_is_present(self):
        from app.enums import ArtifactSubtype

        assert ArtifactSubtype.UNKNOWN == "UNKNOWN"


class TestExtractionStatus:
    def test_three_values(self):
        from app.enums import ExtractionStatus

        assert len(list(ExtractionStatus)) == 3


class TestDedupeMatchType:
    def test_four_values(self):
        from app.enums import DedupeMatchType

        assert len(list(DedupeMatchType)) == 4


class TestDecisionStatus:
    def test_five_values(self):
        assert len(list(DecisionStatus)) == 5

    def test_pending_value(self):
        assert DecisionStatus.PENDING == "PENDING"

    def test_cancelled_value(self):
        assert DecisionStatus.CANCELLED == "CANCELLED"


class TestDecisionOutcome:
    def test_four_values(self):
        assert len(list(DecisionOutcome)) == 4

    def test_approve_value(self):
        assert DecisionOutcome.APPROVE == "APPROVE"

    def test_escalate_to_ceo_value(self):
        assert DecisionOutcome.ESCALATE_TO_CEO == "ESCALATE_TO_CEO"


class TestStepStatus:
    def test_five_values(self):
        assert len(list(StepStatus)) == 5

    def test_skipped_value(self):
        assert StepStatus.SKIPPED == "SKIPPED"

    def test_succeeded_value(self):
        assert StepStatus.SUCCEEDED == "SUCCEEDED"


class TestMrpSource:
    def test_three_values(self):
        assert len(list(MrpSource)) == 3

    def test_manual_value(self):
        assert MrpSource.MANUAL == "MANUAL"

    def test_opus_estimate_value(self):
        assert MrpSource.OPUS_ESTIMATE == "OPUS_ESTIMATE"
