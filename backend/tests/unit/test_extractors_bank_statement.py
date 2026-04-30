"""Tests for BankStatementExtractor — happy path and degraded paths."""

from pathlib import Path

from app.enums import ExtractionStatus
from app.worker.extractors.bank_statement import BankStatementExtractor
from tests.fixtures.builders.bank_statement_builder import build_bank_statement_pdf

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_bank_statement_extracts_header_fields(tmp_path: Path):
    p = build_bank_statement_pdf(tmp_path / "stmt.pdf")
    result = await BankStatementExtractor().extract("stmt.pdf", p.read_bytes())

    assert result.status == ExtractionStatus.SUCCESS
    assert result.schema_version == "1.0"
    assert result.warnings == []
    assert result.error_message is None

    data = result.data
    assert data["account_number"] == "0012345678901"
    assert data["account_holder"] == "SEEMA DEVI"
    assert data["ifsc"] == "SBIN0001234"
    assert data["opening_balance"] == "12,500.00"


async def test_bank_statement_transaction_lines_detected(tmp_path: Path):
    p = build_bank_statement_pdf(tmp_path / "stmt.pdf")
    result = await BankStatementExtractor().extract("stmt.pdf", p.read_bytes())

    assert result.status == ExtractionStatus.SUCCESS
    tx_lines = result.data["transaction_lines"]
    assert isinstance(tx_lines, list)
    # At least some transaction lines start with a date
    assert any(line.startswith("2024-") for line in tx_lines)


async def test_bank_statement_metadata_fields(tmp_path: Path):
    p = build_bank_statement_pdf(tmp_path / "stmt.pdf")
    result = await BankStatementExtractor().extract("stmt.pdf", p.read_bytes())

    assert result.data["total_pages"] >= 1
    assert result.data["full_text_length"] > 0


async def test_bank_statement_extractor_name_and_schema_version():
    extractor = BankStatementExtractor()
    assert extractor.extractor_name == "bank_statement"
    assert extractor.schema_version == "1.0"


# ---------------------------------------------------------------------------
# Degraded: corrupt bytes → FAILED
# ---------------------------------------------------------------------------


async def test_bank_statement_failed_on_corrupt_bytes():
    result = await BankStatementExtractor().extract("bad.pdf", b"not a pdf")

    assert result.status == ExtractionStatus.FAILED
    assert result.error_message is not None
    assert "bad.pdf" in result.error_message


# ---------------------------------------------------------------------------
# Degraded: PDF with no account header → PARTIAL
# ---------------------------------------------------------------------------


async def test_bank_statement_partial_when_no_account_header(tmp_path: Path):
    """PDF with text but no account number or account holder → PARTIAL."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    out = tmp_path / "nohdr.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(out), pagesize=A4)
    doc.build([Paragraph("This is a random PDF without account info.", styles["Normal"])])

    result = await BankStatementExtractor().extract("nohdr.pdf", out.read_bytes())

    assert result.status == ExtractionStatus.PARTIAL
    assert "no_account_header_detected" in result.warnings
    assert result.data["account_number"] is None
    assert result.data["account_holder"] is None


# ---------------------------------------------------------------------------
# Edge: custom account holder
# ---------------------------------------------------------------------------


async def test_bank_statement_custom_account_holder(tmp_path: Path):
    p = build_bank_statement_pdf(tmp_path / "stmt2.pdf", account_holder="RAJESH KUMAR")
    result = await BankStatementExtractor().extract("stmt2.pdf", p.read_bytes())

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["account_holder"] == "RAJESH KUMAR"
