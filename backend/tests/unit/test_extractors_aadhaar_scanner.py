"""Tests for AadhaarScanner — Claude-vision extractor for Aadhaar cards.

The scanner takes image bytes (JPEG/PNG) + filename, calls Claude Haiku vision
with a structured-extraction prompt, and returns an ``ExtractionResult`` with
parsed fields. Claude is injected so unit tests can mock the vision call.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.enums import ExtractionStatus
from app.worker.extractors.aadhaar_scanner import AadhaarScanner


def _make_mock_claude(json_payload: dict) -> MagicMock:
    """Build a MagicMock ClaudeService that returns ``json_payload`` as JSON text."""
    mock_msg = MagicMock(name="Message")
    mock_claude = MagicMock(name="ClaudeService")
    mock_claude.invoke = AsyncMock(return_value=mock_msg)
    mock_claude.extract_text = MagicMock(return_value=json.dumps(json_payload))
    mock_claude.usage_dict = MagicMock(
        return_value={"input_tokens": 1500, "output_tokens": 80}
    )
    mock_claude.cost_usd = MagicMock(return_value=0.0016)
    return mock_claude


async def test_aadhaar_scanner_extracts_fields_from_front_scan():
    """Happy path: Claude returns valid JSON with name/number/address/DOB/gender."""
    payload = {
        "name": "AJAY SINGH",
        "aadhaar_number": "1234 5678 9012",
        "dob": "17/11/2001",
        "gender": "Male",
        "address": "H NO 123, VILLAGE XYZ, HISAR, HARYANA 125001",
        "father_name": None,
    }
    mock_claude = _make_mock_claude(payload)
    scanner = AadhaarScanner(claude=mock_claude)

    fake_jpeg = b"\xff\xd8\xff\xe0" + b"x" * 100
    result = await scanner.extract("10006079_AADHAR_1.jpeg", fake_jpeg)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.schema_version == "1.0"
    assert result.error_message is None
    assert result.data["name"] == "AJAY SINGH"
    assert result.data["aadhaar_number"] == "1234 5678 9012"
    assert result.data["dob"] == "17/11/2001"
    assert result.data["gender"] == "Male"
    assert result.data["address"].startswith("H NO 123")
    assert result.data["father_name"] is None
    assert result.data["cost_usd"] == 0.0016
    assert result.data["model_used"].startswith("claude-haiku")


async def test_aadhaar_scanner_sends_image_as_vision_content_block():
    """Scanner must encode the image into a Claude vision content block."""
    payload = {
        "name": "TEST",
        "aadhaar_number": "1111 2222 3333",
        "address": "Test Addr",
    }
    mock_claude = _make_mock_claude(payload)
    scanner = AadhaarScanner(claude=mock_claude)

    await scanner.extract("a.jpeg", b"\xff\xd8\xff\xe0aaa")

    mock_claude.invoke.assert_called_once()
    kwargs = mock_claude.invoke.call_args.kwargs
    assert kwargs["tier"] == "haiku", "Aadhaar scanner must use Haiku tier"
    messages = kwargs["messages"]
    assert isinstance(messages, list) and len(messages) == 1
    content = messages[0]["content"]
    # First block: image (vision); second: text instruction
    image_block = next(b for b in content if b.get("type") == "image")
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/jpeg"


async def test_aadhaar_scanner_partial_when_required_field_missing():
    """If Claude's JSON omits 'aadhaar_number', status must be PARTIAL, not SUCCESS."""
    payload = {
        "name": "AJAY SINGH",
        # aadhaar_number omitted
        "address": "Some address",
    }
    mock_claude = _make_mock_claude(payload)
    scanner = AadhaarScanner(claude=mock_claude)

    result = await scanner.extract("a.jpeg", b"\xff\xd8\xff\xe0aaa")

    assert result.status == ExtractionStatus.PARTIAL
    assert "aadhaar_number" in " ".join(result.warnings).lower()


async def test_aadhaar_scanner_failed_when_claude_returns_non_json():
    """If Claude's response isn't valid JSON, status must be FAILED."""
    mock_msg = MagicMock(name="Message")
    mock_claude = MagicMock(name="ClaudeService")
    mock_claude.invoke = AsyncMock(return_value=mock_msg)
    mock_claude.extract_text = MagicMock(return_value="I cannot read this image clearly.")
    mock_claude.usage_dict = MagicMock(
        return_value={"input_tokens": 1500, "output_tokens": 20}
    )
    mock_claude.cost_usd = MagicMock(return_value=0.0013)
    scanner = AadhaarScanner(claude=mock_claude)

    result = await scanner.extract("a.jpeg", b"\xff\xd8\xff\xe0garbage")

    assert result.status == ExtractionStatus.FAILED
    assert result.error_message is not None
    assert "json" in result.error_message.lower() or "parse" in result.error_message.lower()


async def test_aadhaar_scanner_detects_media_type_png():
    """A .png filename should set media_type to image/png in the vision block."""
    payload = {"name": "X", "aadhaar_number": "9999 9999 9999", "address": "Y"}
    mock_claude = _make_mock_claude(payload)
    scanner = AadhaarScanner(claude=mock_claude)

    await scanner.extract("UID_back.PNG", b"\x89PNG\r\n\x1a\nbody")

    kwargs = mock_claude.invoke.call_args.kwargs
    image_block = next(b for b in kwargs["messages"][0]["content"] if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/png"


async def test_aadhaar_scanner_name_and_schema_version():
    """Class attrs must be set so the pipeline can identify this extractor."""
    assert AadhaarScanner.extractor_name == "aadhaar_scanner"
    assert AadhaarScanner.schema_version == "1.0"
