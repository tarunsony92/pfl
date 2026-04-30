"""EXIF GPS extraction for house-visit photos.

Phone-captured JPEGs carry a GPSInfo EXIF block with latitude / longitude in
degrees-minutes-seconds + hemisphere refs (N/S/E/W). This module converts the
DMS tuple to a signed decimal pair that Google Maps can reverse-geocode.

Design:
- ``dms_to_decimal`` is pure — unit-testable with plain tuples.
- ``extract_gps_from_exif`` is the thin IO wrapper around ``PIL.Image``;
  returns ``None`` on any failure (missing EXIF, no GPSInfo, corrupt bytes).
"""

from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image

_log = logging.getLogger(__name__)

# Standard EXIF tag for GPSInfo sub-IFD (from the EXIF spec)
_GPS_IFD_TAG = 34853

# GPSInfo sub-IFD keys (from EXIF GPS tags)
_GPS_LAT_REF = 1
_GPS_LAT = 2
_GPS_LON_REF = 3
_GPS_LON = 4


def dms_to_decimal(dms: tuple, ref: str) -> float:
    """Convert degrees-minutes-seconds + hemisphere ref to signed decimal degrees.

    ``dms`` is a 3-tuple like ``(29, 9, 27.96)``. ``ref`` is one of
    ``"N" | "S" | "E" | "W"``.
    """
    d, m, s = (float(x) for x in dms)
    decimal = d + (m / 60.0) + (s / 3600.0)
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def extract_gps_from_exif(image_bytes: bytes) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` as signed decimals, or ``None`` if unavailable.

    Never raises. Logs a debug message when the EXIF block is present but
    missing a GPSInfo sub-IFD (the common case for photos that had GPS
    stripped by a messaging app).
    """
    if not image_bytes:
        return None

    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:  # noqa: BLE001 — PIL can raise many things
        _log.debug("exif: cannot open image: %s", exc)
        return None

    try:
        exif = img.getexif()
    except Exception as exc:  # noqa: BLE001
        _log.debug("exif: getexif() failed: %s", exc)
        return None

    if not exif:
        return None

    gps_info: Any = exif.get(_GPS_IFD_TAG)
    if not gps_info:
        _log.debug("exif: no GPSInfo sub-IFD")
        return None

    lat_ref = gps_info.get(_GPS_LAT_REF)
    lat_dms = gps_info.get(_GPS_LAT)
    lon_ref = gps_info.get(_GPS_LON_REF)
    lon_dms = gps_info.get(_GPS_LON)

    if not (lat_ref and lat_dms and lon_ref and lon_dms):
        _log.debug("exif: incomplete GPSInfo: %s", gps_info)
        return None

    try:
        lat = dms_to_decimal(lat_dms, str(lat_ref))
        lon = dms_to_decimal(lon_dms, str(lon_ref))
    except Exception as exc:  # noqa: BLE001
        _log.debug("exif: DMS conversion failed: %s", exc)
        return None

    return lat, lon
