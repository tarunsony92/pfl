"""Checklist completeness validator — spec §4.6."""

import collections
from dataclasses import dataclass, field

from app.enums import ArtifactSubtype


@dataclass
class ValidationResult:
    """Result of checklist completeness validation."""

    is_complete: bool
    missing_docs: list[dict[str, str]] = field(default_factory=list)
    present_docs: list[dict[str, object]] = field(default_factory=list)


# Spec §4.6 — Hard requirements for IL case
_HARD_REQUIREMENTS: list[tuple[ArtifactSubtype, int, str]] = [
    # Applicant KYC
    (ArtifactSubtype.KYC_AADHAAR, 1, "Applicant Aadhaar"),
    (ArtifactSubtype.KYC_PAN, 1, "Applicant PAN"),
    # Co-applicant KYC
    (ArtifactSubtype.CO_APPLICANT_AADHAAR, 1, "Co-applicant Aadhaar"),
    (ArtifactSubtype.CO_APPLICANT_PAN, 1, "Co-applicant PAN"),
    # Residence proof handled separately (ANY ONE of options)
    # Bank statement as alternate residence proof
    (ArtifactSubtype.BANK_STATEMENT, 1, "Bank statement (6 months)"),
    # Photo requirements (minimum counts)
    (ArtifactSubtype.HOUSE_VISIT_PHOTO, 3, "House-visit photos (min 3)"),
    (ArtifactSubtype.BUSINESS_PREMISES_PHOTO, 3, "Business-premises photos (min 3)"),
    # Mandatory documents
    (ArtifactSubtype.PD_SHEET, 1, "PD Sheet"),
    (ArtifactSubtype.AUTO_CAM, 1, "Auto CAM"),
    (ArtifactSubtype.CHECKLIST, 1, "Checklist xlsx"),
    (ArtifactSubtype.KYC_VIDEO, 1, "KYC video"),
    # Credit report handled separately (ANY ONE of options)
]

# Residence proof — satisfied if at least ONE is present
_RESIDENCE_PROOF_OPTIONS: set[ArtifactSubtype] = {
    ArtifactSubtype.KYC_VOTER,
    ArtifactSubtype.KYC_DL,
    ArtifactSubtype.ELECTRICITY_BILL,
    ArtifactSubtype.RATION_CARD,
    ArtifactSubtype.KYC_PASSPORT,
}

# Credit report — satisfied if at least ONE is present
_CREDIT_REPORT_OPTIONS: set[ArtifactSubtype] = {
    ArtifactSubtype.EQUIFAX_HTML,
    ArtifactSubtype.CIBIL_HTML,
    ArtifactSubtype.HIGHMARK_HTML,
    ArtifactSubtype.EXPERIAN_HTML,
}

# Soft requirements — don't fail completeness if missing
_SOFT_REQUIREMENTS: list[tuple[ArtifactSubtype, int, str]] = [
    (ArtifactSubtype.ELECTRICITY_BILL, 1, "Electricity bill"),
    (ArtifactSubtype.UDYAM_REG, 1, "Udyam registration"),
    (ArtifactSubtype.BANK_ACCOUNT_PROOF, 1, "Bank account proof / cancelled cheque"),
]


def validate_completeness(
    artifact_subtypes: list[ArtifactSubtype],
) -> ValidationResult:
    """Validate checklist completeness against spec §4.6 requirements.

    Args:
        artifact_subtypes: List of ArtifactSubtype enums from classified artifacts.

    Returns:
        ValidationResult with is_complete, missing_docs, and present_docs.
    """
    counts = collections.Counter(artifact_subtypes)
    missing_docs: list[dict[str, str]] = []
    present_docs: list[dict[str, object]] = []

    # Check hard requirements
    for subtype, min_count, description in _HARD_REQUIREMENTS:
        actual_count = counts[subtype]
        if actual_count >= min_count:
            present_docs.append({"doc_type": subtype.value, "count": actual_count})
        else:
            missing_docs.append(
                {
                    "doc_type": subtype.value,
                    "reason": (
                        f"Required: {description}; " f"have {actual_count}, need {min_count}"
                    ),
                }
            )

    # Check residence proof (ANY ONE of the options must be present)
    residence_proof_present = any(counts[opt] > 0 for opt in _RESIDENCE_PROOF_OPTIONS)
    if residence_proof_present:
        # Add which ones are present
        for opt in _RESIDENCE_PROOF_OPTIONS:
            if counts[opt] > 0:
                present_docs.append({"doc_type": opt.value, "count": counts[opt]})
    else:
        missing_docs.append(
            {
                "doc_type": "RESIDENCE_PROOF",
                "reason": ("Required: any one of voter/DL/electricity/ration/passport"),
            }
        )

    # Check credit report (ANY ONE of the options must be present)
    credit_report_present = any(counts[opt] > 0 for opt in _CREDIT_REPORT_OPTIONS)
    if credit_report_present:
        # Add which ones are present
        for opt in _CREDIT_REPORT_OPTIONS:
            if counts[opt] > 0:
                present_docs.append({"doc_type": opt.value, "count": counts[opt]})
    else:
        missing_docs.append(
            {
                "doc_type": "CREDIT_REPORT",
                "reason": ("Required: any one of Equifax/CIBIL/Highmark/Experian"),
            }
        )

    # Check soft requirements (present ones get added, missing are ignored)
    for subtype, min_count, _description in _SOFT_REQUIREMENTS:
        actual_count = counts[subtype]
        if actual_count >= min_count:
            present_docs.append({"doc_type": subtype.value, "count": actual_count})

    return ValidationResult(
        is_complete=len(missing_docs) == 0,
        missing_docs=missing_docs,
        present_docs=present_docs,
    )
