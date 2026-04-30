"""Tests for LoanAgreementScanner — Claude-vision extractor over the signed
loan-agreement PDF (typically a 30-50 page scanned packet: LAGR + LAPP + DPN).

Extracts the asset annexure / hypothecation schedule so Level 4 can diff it
against the SystemCam asset list.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.enums import ExtractionStatus
from app.worker.extractors.loan_agreement_scanner import LoanAgreementScanner


def _mock_claude(json_payload: dict) -> MagicMock:
    mock_msg = MagicMock(name="Message")
    c = MagicMock(name="ClaudeService")
    c.invoke = AsyncMock(return_value=mock_msg)
    c.extract_text = MagicMock(return_value=json.dumps(json_payload))
    c.usage_dict = MagicMock(return_value={"input_tokens": 70_000, "output_tokens": 800})
    c.cost_usd = MagicMock(return_value=0.059)
    return c


async def test_loan_agreement_scanner_extracts_asset_list():
    payload = {
        "loan_id": "10006079",
        "borrower_name": "AJAY SINGH",
        "annexure_present": True,
        "annexure_page_hint": 22,
        "assets": [
            {"description": "Refrigerator Samsung 192L", "value_inr": 18000, "identifier": None},
            {"description": "LED TV Onida 32 inch", "value_inr": 14500, "identifier": None},
            {"description": "Cattle — 2 buffalo", "value_inr": 80000, "identifier": "Tag A-12, A-13"},
        ],
        "hypothecation_clause_present": True,
    }
    mock_claude = _mock_claude(payload)
    scanner = LoanAgreementScanner(claude=mock_claude)

    result = await scanner.extract(
        "10006079_LAGR_1.pdf", b"%PDF-1.4\n<<fake scanned pdf>>"
    )

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["loan_id"] == "10006079"
    assert result.data["annexure_present"] is True
    assert len(result.data["assets"]) == 3
    assert result.data["assets"][0]["description"].startswith("Refrigerator")
    assert result.data["cost_usd"] == 0.059
    assert result.data["model_used"].startswith("claude-haiku")


async def test_loan_agreement_scanner_sends_document_content_block_for_pdf():
    mock_claude = _mock_claude(
        {"annexure_present": True, "assets": [], "hypothecation_clause_present": False}
    )
    scanner = LoanAgreementScanner(claude=mock_claude)
    await scanner.extract("x.pdf", b"%PDF-1.4 data")

    kwargs = mock_claude.invoke.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    doc_block = next(b for b in content if b.get("type") == "document")
    assert doc_block["source"]["type"] == "base64"
    assert doc_block["source"]["media_type"] == "application/pdf"


async def test_loan_agreement_scanner_partial_when_annexure_missing():
    """Agreement with no hypothecation/asset annexure → PARTIAL + warning."""
    payload = {
        "loan_id": "10006079",
        "annexure_present": False,
        "assets": [],
        "hypothecation_clause_present": False,
    }
    mock_claude = _mock_claude(payload)
    scanner = LoanAgreementScanner(claude=mock_claude)

    result = await scanner.extract("a.pdf", b"%PDF-1.4 x")

    assert result.status == ExtractionStatus.PARTIAL
    assert any(
        "annexure" in w.lower() or "hypothecation" in w.lower() for w in result.warnings
    )


async def test_loan_agreement_scanner_failed_on_non_json_response():
    mock_msg = MagicMock()
    mock_claude = MagicMock()
    mock_claude.invoke = AsyncMock(return_value=mock_msg)
    mock_claude.extract_text = MagicMock(return_value="Cannot read document.")
    mock_claude.usage_dict = MagicMock(return_value={"input_tokens": 1000, "output_tokens": 10})
    mock_claude.cost_usd = MagicMock(return_value=0.001)
    scanner = LoanAgreementScanner(claude=mock_claude)

    result = await scanner.extract("a.pdf", b"%PDF-1.4 x")
    assert result.status == ExtractionStatus.FAILED
    assert result.error_message is not None


async def test_loan_agreement_scanner_rejects_non_pdf():
    """A non-PDF filename must fail fast — this scanner is PDF-only."""
    mock_claude = _mock_claude(
        {"annexure_present": True, "assets": [], "hypothecation_clause_present": False}
    )
    scanner = LoanAgreementScanner(claude=mock_claude)

    result = await scanner.extract("wrong.jpeg", b"\xff\xd8\xff")

    assert result.status == ExtractionStatus.FAILED
    assert "pdf" in (result.error_message or "").lower()
    mock_claude.invoke.assert_not_called()


async def test_loan_agreement_scanner_name_and_schema_version():
    assert LoanAgreementScanner.extractor_name == "loan_agreement_scanner"
    assert LoanAgreementScanner.schema_version == "1.0"
