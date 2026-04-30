"""Checklist validator unit tests — spec §4.6."""

import pytest

from app.enums import ArtifactSubtype
from app.worker.checklist_validator import validate_completeness


class TestValidateCompletenessBasic:
    """Basic validation scenarios."""

    def test_all_required_present_returns_complete(self):
        """All hard, residence, and credit requirements met."""
        artifacts = [
            # Hard requirements
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            # Residence proof
            ArtifactSubtype.KYC_VOTER,
            # Credit report
            ArtifactSubtype.EQUIFAX_HTML,
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is True
        assert len(result.missing_docs) == 0
        assert len(result.present_docs) > 0

    def test_missing_applicant_aadhaar_returns_incomplete(self):
        """Missing KYC_AADHAAR → incomplete."""
        artifacts = [
            # Missing KYC_AADHAAR
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            ArtifactSubtype.KYC_VOTER,
            ArtifactSubtype.EQUIFAX_HTML,
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is False
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "KYC_AADHAAR" in missing_types
        # Check reason includes count information
        aadhaar_missing = next(d for d in result.missing_docs if d["doc_type"] == "KYC_AADHAAR")
        assert "have 0, need 1" in aadhaar_missing["reason"]

    def test_insufficient_house_visit_photos_returns_incomplete(self):
        """Insufficient house visit photos (2 instead of 3)."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,  # Only 2, need 3
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            ArtifactSubtype.KYC_VOTER,
            ArtifactSubtype.EQUIFAX_HTML,
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is False
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "HOUSE_VISIT_PHOTO" in missing_types
        house_missing = next(d for d in result.missing_docs if d["doc_type"] == "HOUSE_VISIT_PHOTO")
        assert "have 2, need 3" in house_missing["reason"]

    def test_insufficient_business_premises_photos_returns_incomplete(self):
        """Insufficient business premises photos (1 instead of 3)."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,  # Only 1, need 3
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            ArtifactSubtype.KYC_VOTER,
            ArtifactSubtype.EQUIFAX_HTML,
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is False
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "BUSINESS_PREMISES_PHOTO" in missing_types
        biz_missing = next(
            d for d in result.missing_docs if d["doc_type"] == "BUSINESS_PREMISES_PHOTO"
        )
        assert "have 1, need 3" in biz_missing["reason"]


class TestResidenceProofValidation:
    """Residence proof (ANY ONE option) validation."""

    def test_no_residence_proof_returns_incomplete(self):
        """No residence proof present → incomplete."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            # Missing all residence proof options
            ArtifactSubtype.EQUIFAX_HTML,
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is False
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "RESIDENCE_PROOF" in missing_types

    @pytest.mark.parametrize(
        "residence_subtype",
        [
            ArtifactSubtype.KYC_VOTER,
            ArtifactSubtype.KYC_DL,
            ArtifactSubtype.ELECTRICITY_BILL,
            ArtifactSubtype.RATION_CARD,
            ArtifactSubtype.KYC_PASSPORT,
        ],
    )
    def test_any_residence_proof_variant_satisfies(self, residence_subtype):
        """Each residence proof option alone satisfies requirement."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            residence_subtype,  # One of the residence proof options
            ArtifactSubtype.EQUIFAX_HTML,
        ]
        result = validate_completeness(artifacts)
        # Should not have RESIDENCE_PROOF in missing
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "RESIDENCE_PROOF" not in missing_types


class TestCreditReportValidation:
    """Credit report (ANY ONE option) validation."""

    def test_no_credit_report_returns_incomplete(self):
        """No credit report present → incomplete."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            ArtifactSubtype.KYC_VOTER,
            # Missing all credit report options
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is False
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "CREDIT_REPORT" in missing_types

    def test_cibil_only_satisfies_credit_report(self):
        """CIBIL alone satisfies credit report requirement."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            ArtifactSubtype.KYC_VOTER,
            ArtifactSubtype.CIBIL_HTML,  # Only CIBIL
        ]
        result = validate_completeness(artifacts)
        # Should not have CREDIT_REPORT in missing
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "CREDIT_REPORT" not in missing_types


class TestSoftRequirements:
    """Soft requirements do not fail completeness."""

    def test_soft_requirements_dont_fail_completeness(self):
        """All hard/residence/credit satisfied but soft ones missing → complete."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            ArtifactSubtype.KYC_VOTER,
            ArtifactSubtype.EQUIFAX_HTML,
            # Missing soft requirements: ELECTRICITY_BILL, UDYAM_REG, BANK_ACCOUNT_PROOF
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is True
        # Soft reqs should not appear in missing
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "ELECTRICITY_BILL" not in missing_types
        assert "UDYAM_REG" not in missing_types
        assert "BANK_ACCOUNT_PROOF" not in missing_types


class TestPresentDocsStructure:
    """Validate present_docs structure and content."""

    def test_present_docs_includes_counts(self):
        """present_docs entries have doc_type and count."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
        ]
        result = validate_completeness(artifacts)
        # Check structure
        for doc in result.present_docs:
            assert "doc_type" in doc
            assert "count" in doc
            assert isinstance(doc["doc_type"], str)
            assert isinstance(doc["count"], int)
            assert doc["count"] > 0

    def test_present_docs_counts_duplicates(self):
        """present_docs correctly aggregates duplicate subtypes."""
        artifacts = [
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
        ]
        result = validate_completeness(artifacts)
        house_doc = next(
            (d for d in result.present_docs if d["doc_type"] == "HOUSE_VISIT_PHOTO"),
            None,
        )
        assert house_doc is not None
        assert house_doc["count"] == 3


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_input_is_maximally_incomplete(self):
        """Empty input → incomplete with many missing entries."""
        result = validate_completeness([])
        assert result.is_complete is False
        assert len(result.missing_docs) > 0
        # Should include hard reqs, residence, and credit as missing
        missing_types = [d["doc_type"] for d in result.missing_docs]
        assert "KYC_AADHAAR" in missing_types
        assert "RESIDENCE_PROOF" in missing_types
        assert "CREDIT_REPORT" in missing_types

    def test_duplicate_subtypes_aggregated_correctly(self):
        """Duplicate subtypes are counted correctly."""
        artifacts = [
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
        ]
        result = validate_completeness(artifacts)
        house_doc = next(
            (d for d in result.present_docs if d["doc_type"] == "HOUSE_VISIT_PHOTO"),
            None,
        )
        assert house_doc is not None
        assert house_doc["count"] == 4

    def test_soft_requirements_included_in_present_docs(self):
        """Soft requirements that ARE present appear in present_docs."""
        artifacts = [
            ArtifactSubtype.KYC_AADHAAR,
            ArtifactSubtype.KYC_PAN,
            ArtifactSubtype.CO_APPLICANT_AADHAAR,
            ArtifactSubtype.CO_APPLICANT_PAN,
            ArtifactSubtype.BANK_STATEMENT,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ArtifactSubtype.PD_SHEET,
            ArtifactSubtype.AUTO_CAM,
            ArtifactSubtype.CHECKLIST,
            ArtifactSubtype.KYC_VIDEO,
            ArtifactSubtype.KYC_VOTER,
            ArtifactSubtype.EQUIFAX_HTML,
            # Soft requirements
            ArtifactSubtype.ELECTRICITY_BILL,
            ArtifactSubtype.UDYAM_REG,
            ArtifactSubtype.BANK_ACCOUNT_PROOF,
        ]
        result = validate_completeness(artifacts)
        assert result.is_complete is True
        present_types = [d["doc_type"] for d in result.present_docs]
        assert "ELECTRICITY_BILL" in present_types
        assert "UDYAM_REG" in present_types
        assert "BANK_ACCOUNT_PROOF" in present_types
