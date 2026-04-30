"""Extract GPS coordinates from a watermarked house-visit photo.

Indian microfinance field teams commonly use apps like "GPS Map Camera" that
burn the latitude / longitude / timestamp / place / employee name into the
photo as a visual overlay along the bottom edge. WhatsApp + other messaging
apps strip EXIF metadata during transfer, but the rendered text is baked
into the pixels and survives.

This module uses Claude Haiku vision to OCR the overlay and return the
coordinates as signed decimal degrees, matching the shape returned by
``exif.extract_gps_from_exif`` so the Level 1 engine can swap between the
two sources transparently.

Cost: roughly $0.002 per call on Haiku. Only invoked when EXIF GPS extraction
yielded ``None`` — not on every photo.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_log = logging.getLogger(__name__)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_PINCODE_RE = re.compile(r"\b(\d{6})\b")


@dataclass
class GPSWatermark:
    lat: float
    lon: float
    place: str | None = None
    pincode: str | None = None  # parsed from `place` when present (GPS-Map-Camera embeds it)
    timestamp_text: str | None = None
    employee_name: str | None = None
    employee_id: str | None = None
    cost_usd: Decimal = Decimal("0")
    model_used: str = ""


_SYSTEM_PROMPT = """You are reading a field-visit photograph that has a GPS
overlay burned into the pixels along the bottom edge of the image. The overlay
is produced by apps such as "GPS Map Camera" or PFL's field-ops app and
typically contains lines like:

  Lat : 27.4290883 , Long : 77.6737669
  Time: Wednesday, April 15 2026 12:31:18 PM
  place: 5, Aduki Rd, Mathura, Uttar Pradesh 281006, India
  Original Seen and Verified by
  Emp Id : 202501
  Emp Name : AJAY KUMAR
  Designation : Assistant Branch Manager

Extract the overlay values. If the image has no overlay or the coordinates
are unreadable, return ``{"lat": null, "lon": null}`` — do NOT invent values.

Output format — respond ONLY with valid JSON exactly matching:
{
  "lat": <decimal number or null>,
  "lon": <decimal number or null>,
  "place": "<short place string or null>",
  "timestamp_text": "<timestamp text or null>",
  "employee_name": "<employee name or null>",
  "employee_id": "<employee id or null>"
}

Coordinates must be signed decimal degrees. North/East are positive, South/West
negative. If the overlay reads "Lat : 27.4290883 N" or similar, return 27.4290883
(not with the "N" suffix).
"""


def _detect_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "png":
        return "image/png"
    if ext == "gif":
        return "image/gif"
    if ext == "webp":
        return "image/webp"
    return "image/jpeg"


def _extract_json(text: str) -> dict[str, Any]:
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"no JSON found in response: {text[:200]!r}")
    return json.loads(m.group(0))


async def extract_gps_from_visual_watermark(
    *,
    image_bytes: bytes,
    filename: str,
    claude: Any,
) -> GPSWatermark | None:
    """Claude Haiku vision OCR on the GPS overlay. Returns None if no
    coordinates could be read.

    Designed to be called only when ``exif.extract_gps_from_exif`` already
    returned None, so the typical per-case cost stays under $0.01 even when
    the field team uses a watermarking app.
    """
    if not image_bytes:
        return None

    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    media_type = _detect_media_type(filename)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": "Read the GPS overlay on this photo and extract the fields per the schema.",
                },
            ],
        }
    ]

    try:
        message = await claude.invoke(
            tier="haiku",
            system=_SYSTEM_PROMPT,
            messages=messages,
            cache_system=True,
            max_tokens=256,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("gps_watermark: Claude call failed: %s", exc)
        return None

    raw = claude.extract_text(message)
    try:
        parsed = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        _log.warning("gps_watermark: parse failed — %s — raw: %r", exc, raw[:200])
        return None

    lat = parsed.get("lat")
    lon = parsed.get("lon")
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None

    # Quick sanity — India roughly lies in 8°-37° N, 68°-97° E. Clip out junk.
    if not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180):
        return None

    from app.services.claude import MODELS

    model = MODELS.get("haiku", "haiku")
    usage = claude.usage_dict(message)
    cost = Decimal(str(claude.cost_usd(model, usage)))

    place_str = parsed.get("place") or None
    pincode: str | None = None
    if isinstance(place_str, str):
        m = _PINCODE_RE.search(place_str)
        if m:
            pincode = m.group(1)

    return GPSWatermark(
        lat=lat_f,
        lon=lon_f,
        place=place_str,
        pincode=pincode,
        timestamp_text=(parsed.get("timestamp_text") or None),
        employee_name=(parsed.get("employee_name") or None),
        employee_id=(parsed.get("employee_id") or None),
        cost_usd=cost,
        model_used=model,
    )
