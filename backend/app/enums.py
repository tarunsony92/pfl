from enum import StrEnum


class UserRole(StrEnum):
    """Roles per spec §3.1."""

    ADMIN = "admin"
    CEO = "ceo"
    CREDIT_HO = "credit_ho"
    AI_ANALYSER = "ai_analyser"
    UNDERWRITER = "underwriter"


# Roles that require MFA (spec §3.3)
MFA_REQUIRED_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.ADMIN,
        UserRole.CEO,
        UserRole.CREDIT_HO,
    }
)


class CaseStage(StrEnum):
    """Workflow stages per parent spec §9 + PHASE_1_REJECTED.

    Postgres enum created in a migration. Append-only — never reorder or rename.
    """

    UPLOADED = "UPLOADED"
    CHECKLIST_VALIDATION = "CHECKLIST_VALIDATION"
    CHECKLIST_MISSING_DOCS = "CHECKLIST_MISSING_DOCS"
    CHECKLIST_VALIDATED = "CHECKLIST_VALIDATED"
    INGESTED = "INGESTED"
    PHASE_1_DECISIONING = "PHASE_1_DECISIONING"
    PHASE_1_REJECTED = "PHASE_1_REJECTED"  # hard-rule reject from Phase 1
    PHASE_1_COMPLETE = "PHASE_1_COMPLETE"
    PHASE_2_AUDITING = "PHASE_2_AUDITING"
    PHASE_2_COMPLETE = "PHASE_2_COMPLETE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED_TO_CEO = "ESCALATED_TO_CEO"


class ArtifactType(StrEnum):
    """Artifact types for CaseArtifact. M3+ may extend."""

    ORIGINAL_ZIP = "ORIGINAL_ZIP"
    ADDITIONAL_FILE = "ADDITIONAL_FILE"
    REUPLOAD_ARCHIVE = "REUPLOAD_ARCHIVE"


class ArtifactSubtype(StrEnum):
    """Fine-grained classification of case artifacts. M3 classifier output."""

    KYC_AADHAAR = "KYC_AADHAAR"
    KYC_PAN = "KYC_PAN"
    KYC_VOTER = "KYC_VOTER"
    KYC_DL = "KYC_DL"
    KYC_PASSPORT = "KYC_PASSPORT"
    RATION_CARD = "RATION_CARD"
    ELECTRICITY_BILL = "ELECTRICITY_BILL"
    BANK_ACCOUNT_PROOF = "BANK_ACCOUNT_PROOF"
    INCOME_PROOF = "INCOME_PROOF"
    CO_APPLICANT_AADHAAR = "CO_APPLICANT_AADHAAR"
    CO_APPLICANT_PAN = "CO_APPLICANT_PAN"
    AUTO_CAM = "AUTO_CAM"
    CHECKLIST = "CHECKLIST"
    PD_SHEET = "PD_SHEET"
    EQUIFAX_HTML = "EQUIFAX_HTML"
    CIBIL_HTML = "CIBIL_HTML"
    HIGHMARK_HTML = "HIGHMARK_HTML"
    EXPERIAN_HTML = "EXPERIAN_HTML"
    BANK_STATEMENT = "BANK_STATEMENT"
    HOUSE_VISIT_PHOTO = "HOUSE_VISIT_PHOTO"
    BUSINESS_PREMISES_PHOTO = "BUSINESS_PREMISES_PHOTO"
    KYC_VIDEO = "KYC_VIDEO"
    LOAN_AGREEMENT = "LOAN_AGREEMENT"
    DPN = "DPN"
    LAPP = "LAPP"
    LAGR = "LAGR"
    NACH = "NACH"
    KFS = "KFS"
    UDYAM_REG = "UDYAM_REG"
    UNKNOWN = "UNKNOWN"
    DEDUPE_REPORT = "DEDUPE_REPORT"
    TVR_AUDIO = "TVR_AUDIO"
    # Screenshot from the LMS Personal-Discussion screen showing the borrower's
    # references + contact details have been punched in. Required for L5
    # row #30 (BCM Cross-Verification).
    REFERENCES_SCREENSHOT = "REFERENCES_SCREENSHOT"
    # Audio recording of the independent fraud / verification call placed by
    # Credit HO. Must be a SEPARATE file from TVR_AUDIO. Required for L5
    # row #32 (Fraud / Verification Call).
    FRAUD_CALL_AUDIO = "FRAUD_CALL_AUDIO"
    BUSINESS_PREMISES_CROP = "BUSINESS_PREMISES_CROP"
    # Post-dated cheque (PDC) given by the borrower as EMI security alongside
    # the NACH e-mandate. Verified by L5.5 via a Claude vision call that
    # confirms the artifact is actually a cheque + reads bank / IFSC / a/c.
    PDC_CHEQUE = "PDC_CHEQUE"


class ExtractionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DedupeMatchType(StrEnum):
    AADHAAR = "AADHAAR"
    PAN = "PAN"
    MOBILE = "MOBILE"
    DOB_NAME = "DOB_NAME"


class DecisionStatus(StrEnum):
    """Lifecycle state of a decision_result run. M5."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DecisionOutcome(StrEnum):
    """The recommendation produced by Step 11. M5."""

    APPROVE = "APPROVE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    REJECT = "REJECT"
    ESCALATE_TO_CEO = "ESCALATE_TO_CEO"


class StepStatus(StrEnum):
    """Lifecycle state of a single decision step. M5."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class MrpSource(StrEnum):
    """Source of an MRP entry price. M5."""

    MANUAL = "MANUAL"
    WEB_KNOWLEDGE = "WEB_KNOWLEDGE"
    OPUS_ESTIMATE = "OPUS_ESTIMATE"


class FeedbackVerdict(StrEnum):
    """Human verdict on a case, for AI learning."""

    APPROVE = "APPROVE"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECT = "REJECT"


class VerificationLevelNumber(StrEnum):
    """The pre-Phase-1 verification levels.

    Ordering mirrors the gate sequence: L1 address → L1.5 credit history →
    L2 banking → L3 vision → L4 agreement → L5 scoring → L5.5 dedupe + TVR.
    """

    L1_ADDRESS = "L1_ADDRESS"
    L1_5_CREDIT = "L1_5_CREDIT"
    L2_BANKING = "L2_BANKING"
    L3_VISION = "L3_VISION"
    L4_AGREEMENT = "L4_AGREEMENT"
    L5_SCORING = "L5_SCORING"
    L5_5_DEDUPE_TVR = "L5_5_DEDUPE_TVR"


class VerificationLevelStatus(StrEnum):
    """Lifecycle state of a single level run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    PASSED_WITH_MD_OVERRIDE = "PASSED_WITH_MD_OVERRIDE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class LevelIssueStatus(StrEnum):
    """Per-sub-step issue state (open → resolved → MD decision)."""

    OPEN = "OPEN"
    ASSESSOR_RESOLVED = "ASSESSOR_RESOLVED"
    MD_APPROVED = "MD_APPROVED"
    MD_REJECTED = "MD_REJECTED"


class LevelIssueSeverity(StrEnum):
    """Severity of a level sub-step issue."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class DocType(StrEnum):
    """Identity / address documents scanned during L1. M4-level gate."""

    AADHAAR = "AADHAAR"
    PAN = "PAN"
    RATION = "RATION"
    ELECTRICITY_BILL = "ELECTRICITY_BILL"


class Party(StrEnum):
    """Which party a scanned L1 document belongs to."""

    APPLICANT = "APPLICANT"
    CO_APPLICANT = "CO_APPLICANT"


class DiscrepancySeverity(StrEnum):
    """CAM discrepancy severity. CRITICAL blocks Phase 1; WARNING does not."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"


class DiscrepancyResolutionKind(StrEnum):
    """How the assessor resolved a discrepancy between SystemCam and CM CAM IL.

    - CORRECTED_CM_IL: the assessor edited the CM CAM IL side to match
      SystemCam (or to the correct value). Self-serve.
    - SYSTEMCAM_EDIT_REQUESTED: the assessor believes SystemCam (finpage /
      bureau) is wrong. Requires CEO / admin approval — goes through
      system_cam_edit_requests.
    - JUSTIFIED: both values left as-is; the assessor has recorded a
      narrative explaining why the divergence is acceptable for this case.
    """

    CORRECTED_CM_IL = "CORRECTED_CM_IL"
    SYSTEMCAM_EDIT_REQUESTED = "SYSTEMCAM_EDIT_REQUESTED"
    JUSTIFIED = "JUSTIFIED"


class SystemCamEditRequestStatus(StrEnum):
    """Lifecycle of a SystemCam edit approval request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
