"""Tests for PanScanner — Claude-vision extractor for PAN cards.

PAN cards hold: name, father's name, DOB, 10-char alphanumeric PAN number
(pattern ``[A-Z]{5}[0-9]{4}[A-Z]``). Haiku tier.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.enums import ExtractionStatus
from app.worker.extractors.pan_scanner import PanScanner


def _make_mock_claude(json_payload: dict) -> MagicMock:
    mock_msg = MagicMock(name="Message")
    mock_claude = MagicMock(name="ClaudeService")
    mock_claude.invoke = AsyncMock(return_value=mock_msg)
    mock_claude.extract_text = MagicMock(return_value=json.dumps(json_payload))
    mock_claude.usage_dict = MagicMock(
        return_value={"input_tokens": 1400, "output_tokens": 60}
    )
    mock_claude.cost_usd = MagicMock(return_value=0.0013)
    return mock_claude


async def test_pan_scanner_extracts_name_number_father_dob():
    payload = {
        "name": "AJAY SINGH",
        "father_name": "RAM SINGH",
        "dob": "17/11/2001",
        "pan_number": "OWLPS6441C",
    }
    mock_claude = _make_mock_claude(payload)
    scanner = PanScanner(claude=mock_claude)

    fake_jpeg = b"\xff\xd8\xff\xe0" + b"x" * 50
    result = await scanner.extract("10006079_PAN_1.jpeg", fake_jpeg)

    assert result.status == ExtractionStatus.SUCCESS
    assert result.error_message is None
    assert result.data["name"] == "AJAY SINGH"
    assert result.data["father_name"] == "RAM SINGH"
    assert result.data["dob"] == "17/11/2001"
    assert result.data["pan_number"] == "OWLPS6441C"
    assert result.data["cost_usd"] == 0.0013
    assert result.data["model_used"].startswith("claude-haiku")


async def test_pan_scanner_uses_haiku_tier_and_sends_image_block():
    mock_claude = _make_mock_claude(
        {"name": "X", "pan_number": "ABCDE1234F"}
    )
    scanner = PanScanner(claude=mock_claude)
    await scanner.extract("p.jpeg", b"\xff\xd8\xff\xe0aaa")

    kwargs = mock_claude.invoke.call_args.kwargs
    assert kwargs["tier"] == "haiku"
    content = kwargs["messages"][0]["content"]
    image_block = next(b for b in content if b.get("type") == "image")
    assert image_block["source"]["media_type"] == "image/jpeg"


async def test_pan_scanner_partial_when_pan_number_missing():
    payload = {"name": "AJAY SINGH", "father_name": "RAM SINGH"}  # no pan_number
    mock_claude = _make_mock_claude(payload)
    scanner = PanScanner(claude=mock_claude)

    result = await scanner.extract("p.jpeg", b"\xff\xd8\xff\xe0aaa")

    assert result.status == ExtractionStatus.PARTIAL
    assert any("pan_number" in w for w in result.warnings)


async def test_pan_scanner_failed_on_invalid_json():
    mock_msg = MagicMock(name="Message")
    mock_claude = MagicMock(name="ClaudeService")
    mock_claude.invoke = AsyncMock(return_value=mock_msg)
    mock_claude.extract_text = MagicMock(return_value="Cannot read PAN.")
    mock_claude.usage_dict = MagicMock(
        return_value={"input_tokens": 1400, "output_tokens": 10}
    )
    mock_claude.cost_usd = MagicMock(return_value=0.001)
    scanner = PanScanner(claude=mock_claude)

    result = await scanner.extract("p.jpeg", b"\xff\xd8\xff\xe0aaa")
    assert result.status == ExtractionStatus.FAILED
    assert result.error_message is not None


async def test_pan_scanner_validates_pan_number_format():
    """PAN number must match [A-Z]{5}[0-9]{4}[A-Z]; non-matching → warning."""
    payload = {
        "name": "AJAY SINGH",
        "pan_number": "INVALID123",  # malformed
    }
    mock_claude = _make_mock_claude(payload)
    scanner = PanScanner(claude=mock_claude)

    result = await scanner.extract("p.jpeg", b"\xff\xd8\xff\xe0aaa")

    assert any("pan_number_format" in w.lower() or "format" in w.lower() for w in result.warnings)


async def test_pan_scanner_name_and_schema_version():
    assert PanScanner.extractor_name == "pan_scanner"
    assert PanScanner.schema_version == "1.0"
