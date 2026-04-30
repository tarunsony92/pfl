"""Tests for RationBillScanner — Claude vision on ration / electricity / utility bills.

Accepts both image (JPEG/PNG) and PDF input. Extracts owner name, co-owners (if
printed), address, and document number. Required fields for SUCCESS are
``name`` + ``address``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.enums import ExtractionStatus
from app.worker.extractors.ration_bill_scanner import RationBillScanner


def _make_mock_claude(json_payload: dict) -> MagicMock:
    mock_msg = MagicMock(name="Message")
    mock_claude = MagicMock(name="ClaudeService")
    mock_claude.invoke = AsyncMock(return_value=mock_msg)
    mock_claude.extract_text = MagicMock(return_value=json.dumps(json_payload))
    mock_claude.usage_dict = MagicMock(
        return_value={"input_tokens": 1800, "output_tokens": 120}
    )
    mock_claude.cost_usd = MagicMock(return_value=0.0019)
    return mock_claude


async def test_ration_scanner_extracts_from_jpeg():
    payload = {
        "name": "RAM SINGH",
        "co_owners": ["AJAY SINGH", "SUMAN DEVI"],
        "address": "H NO 123, VILLAGE XYZ, HISAR, HARYANA 125001",
        "document_number": "HR-RC-0012345",
        "document_type": "ration_card",
    }
    mock_claude = _make_mock_claude(payload)
    scanner = RationBillScanner(claude=mock_claude)

    fake_jpeg = b"\xff\xd8\xff\xe0" + b"x" * 100
    result = await scanner.extract("10006079_RATION_1.jpeg", fake_jpeg)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["name"] == "RAM SINGH"
    assert "AJAY SINGH" in result.data["co_owners"]
    assert result.data["address"].startswith("H NO 123")
    assert result.data["document_number"] == "HR-RC-0012345"
    assert result.data["document_type"] == "ration_card"
    assert result.data["cost_usd"] == 0.0019


async def test_ration_scanner_sends_image_content_block_for_jpeg():
    mock_claude = _make_mock_claude(
        {"name": "X", "address": "Y"}
    )
    scanner = RationBillScanner(claude=mock_claude)
    await scanner.extract("bill.jpeg", b"\xff\xd8\xff\xe0aaa")

    kwargs = mock_claude.invoke.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    block = next(b for b in content if b.get("type") == "image")
    assert block["source"]["media_type"] == "image/jpeg"


async def test_ration_scanner_sends_document_content_block_for_pdf():
    """A .pdf input must be sent as a ``document`` content block (Claude native)."""
    mock_claude = _make_mock_claude(
        {"name": "GAURAV KUMAR", "address": "Panipat address"}
    )
    scanner = RationBillScanner(claude=mock_claude)
    await scanner.extract("10006570_RATION_1.pdf", b"%PDF-1.4\npdf body here")

    kwargs = mock_claude.invoke.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    doc_block = next(b for b in content if b.get("type") == "document")
    assert doc_block["source"]["type"] == "base64"
    assert doc_block["source"]["media_type"] == "application/pdf"
    # There should NOT be an image block in the same message
    assert not any(b.get("type") == "image" for b in content)


async def test_ration_scanner_partial_when_name_missing():
    payload = {"address": "Some addr", "document_type": "ration_card"}
    mock_claude = _make_mock_claude(payload)
    scanner = RationBillScanner(claude=mock_claude)

    result = await scanner.extract("r.jpeg", b"\xff\xd8\xff\xe0aaa")

    assert result.status == ExtractionStatus.PARTIAL
    assert any("name" in w for w in result.warnings)


async def test_ration_scanner_failed_on_non_json_response():
    mock_msg = MagicMock(name="Message")
    mock_claude = MagicMock(name="ClaudeService")
    mock_claude.invoke = AsyncMock(return_value=mock_msg)
    mock_claude.extract_text = MagicMock(return_value="Cannot read.")
    mock_claude.usage_dict = MagicMock(
        return_value={"input_tokens": 1700, "output_tokens": 5}
    )
    mock_claude.cost_usd = MagicMock(return_value=0.0014)
    scanner = RationBillScanner(claude=mock_claude)

    result = await scanner.extract("r.jpeg", b"\xff\xd8\xff\xe0aaa")
    assert result.status == ExtractionStatus.FAILED


async def test_ration_scanner_name_and_schema_version():
    assert RationBillScanner.extractor_name == "ration_bill_scanner"
    # Bumped to "1.1" in commit 4d60f18 alongside the L1 smart-match work
    # (Haryana pincode master, Nominatim, GPS watermark, S/O relation,
    # inline LAGR scan) — output shape changed enough to invalidate any
    # cached extractions persisted under the v1.0 schema.
    assert RationBillScanner.schema_version == "1.1"
