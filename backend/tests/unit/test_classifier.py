"""File classifier unit tests — TDD first."""

import pytest

from app.enums import ArtifactSubtype
from app.worker.classifier import classify


class TestFilenamePatterns:
    """Test filename regex patterns — primary classification mechanism."""

    @pytest.mark.parametrize(
        "filename,folder_path,body_bytes,expected",
        [
            # Seema-style KYC filenames (image extensions)
            ("10006484_AADHAR_1.jpeg", None, None, ArtifactSubtype.KYC_AADHAAR),
            ("10006484_AADHAAR_1.jpeg", None, None, ArtifactSubtype.KYC_AADHAAR),
            ("aadhaar_card.jpg", None, None, ArtifactSubtype.KYC_AADHAAR),
            ("AADHAR.png", None, None, ArtifactSubtype.KYC_AADHAAR),
            # PAN — word boundary check (not PANIPAT)
            ("10006484_PAN_1.jpeg", None, None, ArtifactSubtype.KYC_PAN),
            ("PAN_CARD.jpg", None, None, ArtifactSubtype.KYC_PAN),
            ("pan.png", None, None, ArtifactSubtype.KYC_PAN),
            # VOTER
            ("10006484_VOTER_1.jpeg", None, None, ArtifactSubtype.KYC_VOTER),
            ("voter_id.jpg", None, None, ArtifactSubtype.KYC_VOTER),
            # DL (Driving License)
            ("10006484_DL_1.jpeg", None, None, ArtifactSubtype.KYC_DL),
            ("driving_license.jpg", None, None, ArtifactSubtype.KYC_DL),
            ("DRIVING LICENSE.png", None, None, ArtifactSubtype.KYC_DL),
            # PASSPORT
            ("10006484_PASSPORT_1.jpeg", None, None, ArtifactSubtype.KYC_PASSPORT),
            ("passport.jpg", None, None, ArtifactSubtype.KYC_PASSPORT),
            # AUTO_CAM — xlsx only
            ("AUTO_CAM-SEEMA.xlsx", None, None, ArtifactSubtype.AUTO_CAM),
            ("AUTOCAM.xlsx", None, None, ArtifactSubtype.AUTO_CAM),
            ("auto_cam_2024.xlsx", None, None, ArtifactSubtype.AUTO_CAM),
            # CHECKLIST — xlsx only
            ("Checklist_-Seema.xlsx", None, None, ArtifactSubtype.CHECKLIST),
            ("checklist.xlsx", None, None, ArtifactSubtype.CHECKLIST),
            ("CHECKLIST.xls", None, None, ArtifactSubtype.CHECKLIST),
            # PD_SHEET — docx only
            ("PD_Sheet.docx", None, None, ArtifactSubtype.PD_SHEET),
            ("PD Sheet.docx", None, None, ArtifactSubtype.PD_SHEET),
            ("pd_sheet.docx", None, None, ArtifactSubtype.PD_SHEET),
            # EQUIFAX_HTML — html only
            ("EQUIFAX_CREDIT_REPORT.html", None, None, ArtifactSubtype.EQUIFAX_HTML),
            ("equifax_report.html", None, None, ArtifactSubtype.EQUIFAX_HTML),
            # CIBIL_HTML
            ("CIBIL_REPORT.html", None, None, ArtifactSubtype.CIBIL_HTML),
            ("cibil.html", None, None, ArtifactSubtype.CIBIL_HTML),
            # HIGHMARK_HTML
            ("HIGHMARK_REPORT.html", None, None, ArtifactSubtype.HIGHMARK_HTML),
            ("highmark.html", None, None, ArtifactSubtype.HIGHMARK_HTML),
            # EXPERIAN_HTML
            ("EXPERIAN_REPORT.html", None, None, ArtifactSubtype.EXPERIAN_HTML),
            ("experian.html", None, None, ArtifactSubtype.EXPERIAN_HTML),
            # BANK_STATEMENT — pdf only
            ("BANK_STATEMENT_(1).pdf", None, None, ArtifactSubtype.BANK_STATEMENT),
            ("BANK STATEMENT.pdf", None, None, ArtifactSubtype.BANK_STATEMENT),
            ("bank_statement.pdf", None, None, ArtifactSubtype.BANK_STATEMENT),
            # KYC_VIDEO — mp4/mov only
            ("KYCVideo.mp4", None, None, ArtifactSubtype.KYC_VIDEO),
            ("kyc_video.mov", None, None, ArtifactSubtype.KYC_VIDEO),
            ("KYC_VIDEO.mp4", None, None, ArtifactSubtype.KYC_VIDEO),
            # Loan docs (any extension)
            ("10006484_LAPP_1.pdf", None, None, ArtifactSubtype.LAPP),
            ("LAPP.doc", None, None, ArtifactSubtype.LAPP),
            ("lapp.xlsx", None, None, ArtifactSubtype.LAPP),
            ("10006484_LAGR_1.pdf", None, None, ArtifactSubtype.LAGR),
            ("LAGR.docx", None, None, ArtifactSubtype.LAGR),
            ("lagr.txt", None, None, ArtifactSubtype.LAGR),
            ("10006484_DPN_1.pdf", None, None, ArtifactSubtype.DPN),
            ("DPN.doc", None, None, ArtifactSubtype.DPN),
            ("dpn.xlsx", None, None, ArtifactSubtype.DPN),
            ("10006484_NACH_1.jpeg", None, None, ArtifactSubtype.NACH),
            ("NACH.pdf", None, None, ArtifactSubtype.NACH),
            ("nach.doc", None, None, ArtifactSubtype.NACH),
            # KFS — pdf only
            ("10006484_KFS_1.pdf", None, None, ArtifactSubtype.KFS),
            ("KFS.pdf", None, None, ArtifactSubtype.KFS),
            # UDYAM_REG — any extension
            ("UDYAM.pdf", None, None, ArtifactSubtype.UDYAM_REG),
            ("UDYAM_REGISTRATION.xlsx", None, None, ArtifactSubtype.UDYAM_REG),
            # LOAN_AGREEMENT — pdf only
            ("LOAN_AGREEMENT.pdf", None, None, ArtifactSubtype.LOAN_AGREEMENT),
            ("loan agreement.pdf", None, None, ArtifactSubtype.LOAN_AGREEMENT),
            # RATION_CARD — image or pdf
            ("RATION_CARD.jpg", None, None, ArtifactSubtype.RATION_CARD),
            ("ration_card.pdf", None, None, ArtifactSubtype.RATION_CARD),
            # ELECTRICITY_BILL — image or pdf
            ("ELECTRICITY_BILL.jpg", None, None, ArtifactSubtype.ELECTRICITY_BILL),
            ("electricity bill.pdf", None, None, ArtifactSubtype.ELECTRICITY_BILL),
            ("elec_bill.jpeg", None, None, ArtifactSubtype.ELECTRICITY_BILL),
        ],
    )
    def test_filename_patterns(self, filename, folder_path, body_bytes, expected):
        """Test all filename-based classification patterns."""
        result = classify(filename, folder_path, body_bytes)
        assert result == expected, f"Failed for {filename}: expected {expected}, got {result}"


class TestFolderBasedClassification:
    """Test folder path heuristics for image files."""

    @pytest.mark.parametrize(
        "filename,folder_path,expected",
        [
            # BUSINESS_PREMISES photo
            (
                "photo.jpeg",
                "/some/path/20007897_BUSINESS_PREMISES/photo.jpeg",
                ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ),
            (
                "photo.jpg",
                "/path/BUSINESS_PREMISES/image.jpg",
                ArtifactSubtype.BUSINESS_PREMISES_PHOTO,
            ),
            ("photo.png", "/20007897_BUSINESS_PREMISES", ArtifactSubtype.BUSINESS_PREMISES_PHOTO),
            # HOUSE_VISIT photo
            (
                "photo.jpeg",
                "/some/path/20007897_HOUSE_VISIT/photo.jpeg",
                ArtifactSubtype.HOUSE_VISIT_PHOTO,
            ),
            ("photo.jpg", "/path/HOUSE_VISIT/image.jpg", ArtifactSubtype.HOUSE_VISIT_PHOTO),
            ("photo.png", "/20007897_HOUSE_VISIT", ArtifactSubtype.HOUSE_VISIT_PHOTO),
        ],
    )
    def test_folder_based_classification(self, filename, folder_path, expected):
        """Test folder-path heuristics for images when filename doesn't match."""
        result = classify(filename, folder_path, None)
        assert (
            result == expected
        ), f"Failed for {filename} in {folder_path}: expected {expected}, got {result}"


class TestCoApplicantPatterns:
    """Test CO_APPLICANT prefix handling."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            # CO_ prefix with AADHAAR
            ("CO_AADHAR_1.jpeg", ArtifactSubtype.CO_APPLICANT_AADHAAR),
            ("CO_AADHAAR_1.jpeg", ArtifactSubtype.CO_APPLICANT_AADHAAR),
            ("COAPPLICANT_AADHAR.jpg", ArtifactSubtype.CO_APPLICANT_AADHAAR),
            # COAP_ prefix (Ajay-style real data)
            ("10006079_COAP_ADHAAR_1.jpeg", ArtifactSubtype.CO_APPLICANT_AADHAAR),
            ("10006079_COAP_ADHAAR_1.png", ArtifactSubtype.CO_APPLICANT_AADHAAR),
            # CO_ prefix with PAN
            ("CO_PAN_1.jpeg", ArtifactSubtype.CO_APPLICANT_PAN),
            ("COAPPLICANT_PAN.jpg", ArtifactSubtype.CO_APPLICANT_PAN),
        ],
    )
    def test_co_applicant_patterns(self, filename, expected):
        """Test co-applicant prefix recognition."""
        result = classify(filename, None, None)
        assert result == expected, f"Failed for {filename}: expected {expected}, got {result}"


class TestLiveDataPatterns:
    """Patterns discovered while classifying real customer ZIPs (Ajay Hisar E2E)."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            # UID_* is a common Aadhaar naming convention
            ("UID_front.PNG", ArtifactSubtype.KYC_AADHAAR),
            ("UID_back.PNG", ArtifactSubtype.KYC_AADHAAR),
            ("UID_back-imageonline.co-merged.png", ArtifactSubtype.KYC_AADHAAR),
            # CAM_REPORT_* is a common AUTO CAM alias
            ("CAM_REPORT_10006079.xlsx", ArtifactSubtype.AUTO_CAM),
            ("cam-report.xlsx", ArtifactSubtype.AUTO_CAM),
            # BANK_STMT (abbreviated BANK_STATEMENT)
            ("10006079_BANK_STMT_1.pdf", ArtifactSubtype.BANK_STATEMENT),
            ("bank_stmt.pdf", ArtifactSubtype.BANK_STATEMENT),
            # bare BANK_ACCOUNT (no "proof" suffix)
            ("10006079_BANK_ACCOUNT_1.PNG", ArtifactSubtype.BANK_ACCOUNT_PROOF),
            ("bank_account_1.jpg", ArtifactSubtype.BANK_ACCOUNT_PROOF),
        ],
    )
    def test_live_data_patterns(self, filename, expected):
        assert classify(filename, None, None) == expected


class TestContentBasedFallback:
    """Test content inspection for xlsx and html files."""

    @staticmethod
    def _xlsx_bytes(sheet_name: str, first_cell: str | None = None) -> bytes:
        import io

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        if first_cell is not None:
            ws["A1"] = first_cell
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_xlsx_with_credit_assessment_first_cell(self):
        """xlsx whose first cell says 'Credit Assessment' → AUTO_CAM."""
        body = self._xlsx_bytes("CustomTab", first_cell="CREDIT ASSESSMENT REPORT")
        assert classify("unknown_file.xlsx", None, body) == ArtifactSubtype.AUTO_CAM

    def test_xlsx_with_systemcam_sheet_name(self):
        """xlsx whose sheet is 'SystemCam' → AUTO_CAM (covers real bare-loan-id file)."""
        body = self._xlsx_bytes("SystemCam")
        assert classify("10006079.xlsx", None, body) == ArtifactSubtype.AUTO_CAM

    def test_xlsx_with_cam_report_sheet_name(self):
        """xlsx whose sheet is 'CAM_REPORT' → AUTO_CAM."""
        body = self._xlsx_bytes("CAM_REPORT")
        assert classify("something.xlsx", None, body) == ArtifactSubtype.AUTO_CAM

    def test_xlsx_with_customer_dedupe_returns_dedupe_report(self):
        """xlsx with a 'Customer_Dedupe' sheet → DEDUPE_REPORT (L5.5 ingestion)."""
        body = self._xlsx_bytes("Customer_Dedupe", first_cell="snapshot data")
        assert classify("unknown_file.xlsx", None, body) == ArtifactSubtype.DEDUPE_REPORT

    def test_xlsx_with_customer_dedupe_space_returns_dedupe_report(self):
        """xlsx with a 'Customer Dedupe' sheet → DEDUPE_REPORT (L5.5 ingestion)."""
        body = self._xlsx_bytes("Customer Dedupe")
        assert classify("unknown_file.xlsx", None, body) == ArtifactSubtype.DEDUPE_REPORT

    def test_html_with_equifax_marker(self):
        """html with 'equifax' in content → EQUIFAX_HTML."""
        filename = "unknown_report.html"
        body_bytes = b"<html><body>Your EQUIFAX credit report</body></html>"
        result = classify(filename, None, body_bytes)
        assert result == ArtifactSubtype.EQUIFAX_HTML

    def test_html_with_equifax_lowercase(self):
        """html with 'equifax' (lowercase) in content → EQUIFAX_HTML."""
        filename = "unknown_report.html"
        body_bytes = b"<html><body>Your equifax credit report</body></html>"
        result = classify(filename, None, body_bytes)
        assert result == ArtifactSubtype.EQUIFAX_HTML

    def test_html_with_cibil_marker(self):
        """html with 'cibil' in content → CIBIL_HTML."""
        filename = "unknown_report.html"
        body_bytes = b"<html><body>Your CIBIL credit report</body></html>"
        result = classify(filename, None, body_bytes)
        assert result == ArtifactSubtype.CIBIL_HTML

    def test_html_with_highmark_marker(self):
        """html with 'highmark' in content → HIGHMARK_HTML."""
        filename = "unknown_report.html"
        body_bytes = b"<html><body>Your HIGHMARK insurance report</body></html>"
        result = classify(filename, None, body_bytes)
        assert result == ArtifactSubtype.HIGHMARK_HTML

    def test_html_with_experian_marker(self):
        """html with 'experian' in content → EXPERIAN_HTML."""
        filename = "unknown_report.html"
        body_bytes = b"<html><body>Your EXPERIAN report</body></html>"
        result = classify(filename, None, body_bytes)
        assert result == ArtifactSubtype.EXPERIAN_HTML


class TestUnknownClassification:
    """Test default UNKNOWN classification."""

    @pytest.mark.parametrize(
        "filename,folder_path,body_bytes",
        [
            ("random.txt", None, None),
            ("document.doc", None, None),
            ("image.bmp", None, None),
            ("data.csv", None, None),
            ("unknown_file.xlsx", None, None),  # xlsx without markers
            ("unknown_file.html", None, None),  # html without credit markers
        ],
    )
    def test_unknown_defaults(self, filename, folder_path, body_bytes):
        """Test files that don't match any pattern default to UNKNOWN."""
        result = classify(filename, folder_path, body_bytes)
        assert (
            result == ArtifactSubtype.UNKNOWN
        ), f"Failed for {filename}: expected UNKNOWN, got {result}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_word_boundary_pan_does_not_match_panipat(self):
        """PAN should not match PANIPAT."""
        # PANIPAT does not contain isolated PAN word
        result = classify("PANIPAT_DOCUMENT.jpg", None, None)
        assert result == ArtifactSubtype.UNKNOWN

    def test_case_insensitivity(self):
        """All patterns should be case-insensitive."""
        assert classify("aADhAr_card.jpg", None, None) == ArtifactSubtype.KYC_AADHAAR
        assert classify("KYc_VidEo.mp4", None, None) == ArtifactSubtype.KYC_VIDEO
        assert classify("auto_cam.XLSX", None, None) == ArtifactSubtype.AUTO_CAM

    def test_filename_with_spaces(self):
        """Test handling of spaces in filenames."""
        assert classify("PAN CARD.jpeg", None, None) == ArtifactSubtype.KYC_PAN
        assert classify("BANK STATEMENT.pdf", None, None) == ArtifactSubtype.BANK_STATEMENT

    def test_multiple_underscores(self):
        """Test handling of multiple underscores."""
        assert classify("10006484_LAPP_1_FINAL.pdf", None, None) == ArtifactSubtype.LAPP
        assert classify("DPN_OLD_VERSION.doc", None, None) == ArtifactSubtype.DPN

    def test_extension_only_no_folder(self):
        """Test .xls variant (not just .xlsx)."""
        assert classify("checklist.xls", None, None) == ArtifactSubtype.CHECKLIST

    def test_empty_body_bytes(self):
        """Test with empty body_bytes doesn't crash."""
        result = classify("unknown_file.xlsx", None, b"")
        assert result == ArtifactSubtype.UNKNOWN

    def test_folder_path_without_image_extension_returns_unknown(self):
        """Folder hints only apply to images."""
        result = classify("document.pdf", "/path/HOUSE_VISIT/doc.pdf", None)
        assert result == ArtifactSubtype.UNKNOWN

    def test_none_parameters(self):
        """Test with None folder_path and body_bytes."""
        result = classify("AADHAR.jpg", None, None)
        assert result == ArtifactSubtype.KYC_AADHAAR


class TestIncomeAndBankProofPatterns:
    """Patterns for BANK_ACCOUNT_PROOF and INCOME_PROOF."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("CANCELLED_CHEQUE.jpg", ArtifactSubtype.BANK_ACCOUNT_PROOF),
            ("CancelledChq.pdf", ArtifactSubtype.BANK_ACCOUNT_PROOF),
            ("passbook.jpeg", ArtifactSubtype.BANK_ACCOUNT_PROOF),
            ("BANK_ACC_PROOF.pdf", ArtifactSubtype.BANK_ACCOUNT_PROOF),
            ("SALARY_SLIP.pdf", ArtifactSubtype.INCOME_PROOF),
            ("SalarySlip_Oct.pdf", ArtifactSubtype.INCOME_PROOF),
            ("ITR_2023.pdf", ArtifactSubtype.INCOME_PROOF),
            ("Form16_2022.pdf", ArtifactSubtype.INCOME_PROOF),
            ("INCOME_PROOF.jpg", ArtifactSubtype.INCOME_PROOF),
        ],
    )
    def test_income_and_bank_proof(self, filename, expected):
        assert classify(filename, None, None) == expected


class TestCoverageEdgeCases:
    """Explicit tests for the default-UNKNOWN branches in each helper."""

    def test_filename_with_no_extension(self):
        # body_bytes forces _get_extension to run; no dot -> "" -> default UNKNOWN
        assert classify("noextfile", None, b"some bytes") == ArtifactSubtype.UNKNOWN

    def test_image_with_non_matching_folder(self):
        # Hits _classify_by_folder terminal UNKNOWN
        assert classify("photo.jpg", "/RANDOM_FOLDER/", None) == ArtifactSubtype.UNKNOWN

    def test_xlsx_body_without_markers(self):
        # Hits _classify_xlsx_by_content terminal UNKNOWN
        assert classify("other.xlsx", None, b"nothing interesting here") == ArtifactSubtype.UNKNOWN

    def test_html_body_without_markers(self):
        # Hits _classify_html_by_content terminal UNKNOWN
        assert (
            classify("other.html", None, b"<html>no bureau here</html>") == ArtifactSubtype.UNKNOWN
        )
