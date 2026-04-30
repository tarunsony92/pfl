"""OpenStreetMap Nominatim reverse-geocoding — free fallback.

Invoked by the L1 engine when Google Maps returns ``None`` (API disabled, over
quota, invalid key, etc.). Nominatim is free, no API key, but caps public use
at roughly 1 req/sec and requires a descriptive User-Agent header per
https://operations.osmfoundation.org/policies/nominatim/.

Returns a ``GPSAddress`` dataclass carrying both the human-readable
``display_name`` and a structured breakdown (state / district / village /
postcode) so the verification engine can do smart, village-level matching
against Aadhaar addresses rather than relying on the pincode — Indian
pincodes cover dozens of villages each, so a raw "125001 vs 127045" diff
is a false-positive mismatch when both are inside the same district.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import httpx

_log = logging.getLogger(__name__)

_BASE_URL = "https://nominatim.openstreetmap.org/reverse"
_DEFAULT_TIMEOUT_S = 8.0
_USER_AGENT = "PFLCreditAI/1.0 (internal credit-verification tool)"


@dataclass
class GPSAddress:
    """Common shape returned by any reverse-geocoder adapter.

    All fields are optional because coverage varies widely between providers
    and regions (rural India in particular often lacks village-level OSM tags
    so the best we get is a road/block name).
    """

    display_name: str
    state: str | None = None
    district: str | None = None
    village: str | None = None
    postcode: str | None = None
    country: str | None = None
    raw: dict[str, Any] | None = None  # the original provider response

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "state": self.state,
            "district": self.district,
            "village": self.village,
            "postcode": self.postcode,
            "country": self.country,
        }


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT_S,
        headers={"User-Agent": _USER_AGENT},
    )


def _pick_village(addr: dict[str, Any]) -> str | None:
    """Extract the most specific locality field Nominatim gives us.

    Priority: village > hamlet > suburb > neighbourhood > town > city_district
    > municipality. Skips "city" because for rural queries city is usually
    just the district admin town, not the actual residence locality.
    """
    for key in (
        "village",
        "hamlet",
        "suburb",
        "neighbourhood",
        "town",
        "city_district",
        "municipality",
    ):
        v = addr.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _pick_district(addr: dict[str, Any]) -> str | None:
    for key in ("state_district", "county", "district"):
        v = addr.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


async def reverse_geocode_nominatim(
    *,
    lat: float,
    lon: float,
    client_factory: Callable[[], Any] = _default_client_factory,
) -> GPSAddress | None:
    """Return a ``GPSAddress`` from OSM Nominatim, or None on any failure.

    Uses ``addressdetails=1`` so the caller can do structured comparison
    rather than relying on a single formatted string.
    """
    params = {
        "lat": f"{lat}",
        "lon": f"{lon}",
        "format": "json",
        "zoom": "18",
        "addressdetails": "1",
    }

    try:
        async with client_factory() as client:
            response = await client.get(_BASE_URL, params=params)
    except Exception as exc:  # noqa: BLE001
        _log.warning("nominatim: network error: %s", exc)
        return None

    if getattr(response, "status_code", 0) != 200:
        _log.warning(
            "nominatim: HTTP %s — %s",
            getattr(response, "status_code", "?"),
            (getattr(response, "text", "") or "")[:200],
        )
        return None

    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        _log.warning("nominatim: non-JSON response: %s", exc)
        return None

    if not isinstance(body, dict):
        return None
    if body.get("error"):
        _log.warning("nominatim: API error: %s", body["error"])
        return None

    display_name = body.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        return None

    addr = body.get("address") if isinstance(body.get("address"), dict) else {}
    return GPSAddress(
        display_name=display_name.strip(),
        state=(addr.get("state") or None),
        district=_pick_district(addr),
        village=_pick_village(addr),
        postcode=(addr.get("postcode") or None),
        country=(addr.get("country") or None),
        raw=body,
    )
