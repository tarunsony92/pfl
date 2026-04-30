"""Builder for a full case ZIP fixture matching the Seema folder structure."""

import zipfile
from pathlib import Path

from .auto_cam_builder import build_auto_cam_xlsx
from .bank_statement_builder import build_bank_statement_pdf
from .checklist_builder import build_checklist_xlsx
from .equifax_builder import build_equifax_html
from .pd_sheet_builder import build_pd_sheet_docx

_DEFAULT_LOAN_ID = "10006484"

# Minimal 1x1 white JPEG bytes (valid JPEG header + EOI)
_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
    b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4\xff\xd9"
)


def build_case_zip(path: Path, **kwargs: object) -> Path:
    """Assemble all builders into a ZIP matching the Seema folder structure.

    Folders: {loan_id}_OTH/, {loan_id}_BUSINESS_PREMISES/, {loan_id}_HOUSE_VISIT/.
    Accepts loan_id kwarg (default: 10006484).
    Returns path.
    """
    loan_id = str(kwargs.get("loan_id", _DEFAULT_LOAN_ID))

    # Build sub-files into a temp dir alongside the zip
    tmp_dir = path.parent / f"_case_zip_tmp_{loan_id}"
    tmp_dir.mkdir(exist_ok=True)

    try:
        auto_cam = build_auto_cam_xlsx(tmp_dir / "auto_cam.xlsx")
        checklist = build_checklist_xlsx(tmp_dir / "checklist.xlsx")
        pd_sheet = build_pd_sheet_docx(tmp_dir / "pd_sheet.docx")
        equifax = build_equifax_html(tmp_dir / "equifax.html")
        bank_stmt = build_bank_statement_pdf(tmp_dir / "bank_statement.pdf")

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            oth = f"{loan_id}_OTH"
            bp = f"{loan_id}_BUSINESS_PREMISES"
            hv = f"{loan_id}_HOUSE_VISIT"

            zf.write(auto_cam, f"{oth}/AUTO_CAM-{loan_id}.xlsx")
            zf.write(checklist, f"{oth}/Checklist_-{loan_id}.xlsx")
            zf.write(pd_sheet, f"{oth}/PD_Sheet.docx")
            zf.write(equifax, f"{oth}/EQUIFAX_CREDIT_REPORT.html")
            zf.write(bank_stmt, f"{oth}/BANK_STATEMENT_(1).pdf")
            zf.writestr(f"{oth}/{loan_id}_AADHAR_1.jpeg", _TINY_JPEG)
            zf.writestr(f"{oth}/{loan_id}_AADHAR_2.jpeg", _TINY_JPEG)

            for i in range(1, 4):
                zf.writestr(f"{bp}/{loan_id}_BP_{i:03d}.jpeg", _TINY_JPEG)

            for i in range(1, 4):
                zf.writestr(f"{hv}/{loan_id}_HV_{i:03d}.jpeg", _TINY_JPEG)

    finally:
        # Clean up temp files
        for f in tmp_dir.iterdir():
            f.unlink()
        tmp_dir.rmdir()

    return path
