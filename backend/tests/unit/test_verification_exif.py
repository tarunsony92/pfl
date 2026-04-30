"""Tests for the EXIF GPS extraction service.

Splits the logic into:
- ``dms_to_decimal`` — pure conversion, testable with plain tuples.
- ``extract_gps_from_exif`` — bytes → (lat, lon) or None. Wraps PIL.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.verification.services.exif import (
    dms_to_decimal,
    extract_gps_from_exif,
)


def test_dms_to_decimal_north_latitude():
    # 29° 9' 27.96" N = 29.1577667
    decimal = dms_to_decimal((29, 9, 27.96), "N")
    assert decimal == pytest.approx(29.1577667, rel=1e-6)


def test_dms_to_decimal_south_latitude_is_negative():
    decimal = dms_to_decimal((12, 30, 0), "S")
    assert decimal == pytest.approx(-12.5, rel=1e-6)


def test_dms_to_decimal_east_longitude():
    decimal = dms_to_decimal((75, 43, 12), "E")
    assert decimal == pytest.approx(75.72, rel=1e-3)


def test_dms_to_decimal_west_longitude_is_negative():
    decimal = dms_to_decimal((77, 30, 0), "W")
    assert decimal == pytest.approx(-77.5, rel=1e-6)


def test_dms_to_decimal_accepts_rational_tuples_too():
    """PIL sometimes returns IFDRational-like objects that cast to float."""
    # Using plain floats here; PIL IFDRational also implements __float__.
    decimal = dms_to_decimal((29.0, 9.0, 27.96), "N")
    assert decimal == pytest.approx(29.1577667, rel=1e-6)


def test_extract_gps_returns_none_for_image_without_exif():
    """A freshly-created PIL image has no EXIF block → no GPS → None."""
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="white")
    img.save(buf, format="JPEG")
    result = extract_gps_from_exif(buf.getvalue())
    assert result is None


def test_extract_gps_returns_none_for_non_image_bytes():
    """Garbage bytes → gracefully return None, no crash."""
    assert extract_gps_from_exif(b"not an image") is None


def test_extract_gps_returns_none_for_empty_bytes():
    assert extract_gps_from_exif(b"") is None


def test_extract_gps_from_mocked_exif_dict(monkeypatch):
    """If PIL returns a GPS-containing EXIF, we decode to (lat, lon)."""
    from app.verification.services import exif as exif_mod

    class _FakeImg:
        def getexif(self):
            # EXIF tag 34853 = GPSInfo. Values inside the sub-IFD:
            #   1=GPSLatitudeRef, 2=GPSLatitude, 3=GPSLongitudeRef, 4=GPSLongitude
            return {
                34853: {
                    1: "N",
                    2: (29, 9, 27.96),
                    3: "E",
                    4: (75, 43, 12),
                }
            }

    def _fake_open(_):
        return _FakeImg()

    monkeypatch.setattr(exif_mod.Image, "open", _fake_open)

    lat, lon = extract_gps_from_exif(b"fake-jpeg-bytes")  # type: ignore[misc]
    assert lat == pytest.approx(29.1577667, rel=1e-6)
    assert lon == pytest.approx(75.72, rel=1e-3)


def test_extract_gps_returns_none_when_exif_has_no_gps_tag(monkeypatch):
    from app.verification.services import exif as exif_mod

    class _FakeImg:
        def getexif(self):
            # EXIF present but no GPSInfo (key 34853)
            return {271: "Apple", 272: "iPhone 14"}

    monkeypatch.setattr(exif_mod.Image, "open", lambda _: _FakeImg())
    assert extract_gps_from_exif(b"fake") is None
