"""Google Maps Geocoding API — reverse-geocode (lat, lon) → formatted address.

Used by Level 1 sub-step 3: take a house-visit photo's GPS EXIF, resolve it to
a human-readable address, then fuzzy-compare that address against the
applicant's Aadhaar address.

Always returns ``None`` on any failure (missing key, network error, non-OK
status). Caller must treat ``None`` as "unable to verify via GPS" and raise
an Issue, not silently skip the sub-step.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

_log = logging.getLogger(__name__)

_BASE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# Modern Routes API (computeRoutes). The legacy Distance Matrix REST
# endpoint is being deprecated and is not enabled by default on new GCP
# projects, which routinely returns REQUEST_DENIED. The Routes API is the
# official replacement and ships enabled on every new project.
_ROUTES_BASE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_DEFAULT_TIMEOUT_S = 8.0
# FieldMask is mandatory on the Routes API — without it the request 400s.
# We only need duration + distance for the commute check.
_ROUTES_FIELD_MASK = "routes.duration,routes.distanceMeters"


@dataclass
class DistanceMatrixResult:
    """Outcome of a driving Distance Matrix query.

    ``raw_status`` separates the infra-OK / no-route-available case
    ("zero_results", "not_found") from the infra-failure case (the
    helper returns ``None`` on those). This lets L1 issue a CRITICAL
    "no drivable route" vs a WARNING "service unavailable".
    """

    distance_km: float
    travel_minutes: float
    raw_status: str  # "ok" | "zero_results" | "not_found"


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S)


async def reverse_geocode(
    *,
    lat: float,
    lon: float,
    api_key: str | None,
    client_factory: Callable[[], Any] = _default_client_factory,
) -> str | None:
    """Return the top ``formatted_address`` for ``(lat, lon)``, or None.

    Args:
        lat: signed latitude in decimal degrees.
        lon: signed longitude in decimal degrees.
        api_key: Google Maps Geocoding API key. If empty/None, returns None.
        client_factory: callable producing an async context manager that is
            an ``httpx.AsyncClient``-compatible object. Used for dependency
            injection in tests.
    """
    if not api_key:
        _log.warning("reverse_geocode: empty api_key — skipping call")
        return None

    params = {
        "latlng": f"{lat},{lon}",
        "key": api_key,
    }

    try:
        async with client_factory() as client:
            response = await client.get(_BASE_URL, params=params)
    except Exception as exc:  # noqa: BLE001
        _log.warning("reverse_geocode: network/connection error: %s", exc)
        return None

    try:
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        _log.warning("reverse_geocode: HTTP error: %s", exc)
        return None

    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        _log.warning("reverse_geocode: non-JSON response: %s", exc)
        return None

    status = body.get("status")
    if status != "OK":
        # ZERO_RESULTS is expected for coords in empty regions (oceans, Antarctica).
        # REQUEST_DENIED / OVER_QUERY_LIMIT / INVALID_REQUEST / UNKNOWN_ERROR all
        # signal a misconfiguration or infra problem — those deserve WARNING-level
        # noise in the logs so the operator notices.
        if status == "ZERO_RESULTS":
            _log.info(
                "reverse_geocode: Google returned ZERO_RESULTS for (%s, %s)", lat, lon
            )
        else:
            _log.warning(
                "reverse_geocode: Google Maps returned status %s — %s",
                status,
                body.get("error_message", ""),
            )
        return None

    results = body.get("results") or []
    if not results:
        return None

    return results[0].get("formatted_address")


async def forward_geocode(
    *,
    address: str,
    api_key: str | None,
    client_factory: Callable[[], Any] = _default_client_factory,
) -> tuple[float, float] | None:
    """Resolve a free-text address to ``(lat, lon)`` via Google Maps Geocoding.

    Inverse of :func:`reverse_geocode`. Returns the best-match coordinates or
    ``None`` on any failure (missing key, network error, non-OK status, no
    results). Caller MUST treat ``None`` as "could not geocode" rather than
    silently dropping the check — the L1 engine surfaces a soft note in the
    evidence dict ("distance_km": null) so the assessor knows distance isn't
    available, instead of pretending the addresses are nearby.
    """
    if not api_key:
        _log.warning("forward_geocode: empty api_key — skipping call")
        return None
    addr = (address or "").strip()
    if not addr:
        return None

    params = {"address": addr, "key": api_key}
    try:
        async with client_factory() as client:
            response = await client.get(_BASE_URL, params=params)
    except Exception as exc:  # noqa: BLE001
        _log.warning("forward_geocode: network/connection error: %s", exc)
        return None

    try:
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        _log.warning("forward_geocode: HTTP/JSON error: %s", exc)
        return None

    status = body.get("status")
    if status != "OK":
        if status not in ("ZERO_RESULTS",):
            _log.warning(
                "forward_geocode: Google Maps returned status %s — %s",
                status,
                body.get("error_message", ""),
            )
        return None

    results = body.get("results") or []
    if not results:
        return None
    loc = (results[0].get("geometry") or {}).get("location") or {}
    lat, lon = loc.get("lat"), loc.get("lng")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance between two (lat, lon) points in **kilometres**.

    Used by L1 to surface "addresses are X km apart" alongside an Aadhaar ↔
    GPS or applicant ↔ co-applicant address mismatch — so the assessor can
    distinguish "200 m / photo angle issue" from "50 km / different state".
    Pure math, no I/O — safe to call inside any sync context.
    """
    r = 6371.0088  # mean Earth radius (km)
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _parse_routes_duration_seconds(raw: Any) -> float | None:
    """Routes API returns durations as ``"1080s"`` (Protobuf Duration string).
    We accept fractional seconds (``"1080.5s"``) and bare numbers as a
    defensive fallback. Returns None on any unparseable shape.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if s.endswith("s"):
        s = s[:-1]
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


async def distance_matrix_driving(
    *,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    api_key: str | None,
    client_factory: Callable[[], Any] = _default_client_factory,
) -> DistanceMatrixResult | None:
    """Return the driving duration + distance between two points, or None on
    infra failure.

    Backed by Google's Routes API (computeRoutes). ``routingPreference`` is
    fixed to ``TRAFFIC_UNAWARE`` so results are deterministic across L1
    re-runs and don't drift hour-to-hour with live traffic.
    """
    if not api_key:
        _log.warning("distance_matrix_driving: empty api_key — skipping call")
        return None

    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _ROUTES_FIELD_MASK,
        "Content-Type": "application/json",
    }
    payload = {
        "origin": {
            "location": {"latLng": {"latitude": origin_lat, "longitude": origin_lon}}
        },
        "destination": {
            "location": {"latLng": {"latitude": dest_lat, "longitude": dest_lon}}
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
    }

    try:
        async with client_factory() as client:
            response = await client.post(
                _ROUTES_BASE_URL, headers=headers, json=payload
            )
    except Exception as exc:  # noqa: BLE001
        _log.warning("distance_matrix_driving: network/connection error: %s", exc)
        return None

    try:
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        _log.warning("distance_matrix_driving: HTTP error: %s", exc)
        return None

    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        _log.warning("distance_matrix_driving: non-JSON response: %s", exc)
        return None

    if not isinstance(body, dict):
        return None

    # Some invalid-request cases surface as HTTP 200 with an error envelope.
    if isinstance(body.get("error"), dict):
        err = body["error"]
        _log.warning(
            "distance_matrix_driving: API error %s — %s",
            err.get("status") or err.get("code"),
            err.get("message", ""),
        )
        return None

    routes = body.get("routes")
    # Both ``{}`` and ``{"routes": []}`` mean "no route available" per the
    # Routes API contract — collapse to zero_results so the L1 helper can
    # raise the CRITICAL "no drivable route" issue.
    if not routes:
        return DistanceMatrixResult(
            distance_km=0.0,
            travel_minutes=0.0,
            raw_status="zero_results",
        )

    route = routes[0] if isinstance(routes, list) and routes else None
    if not isinstance(route, dict):
        return None

    duration_s = _parse_routes_duration_seconds(route.get("duration"))
    distance_m = route.get("distanceMeters")
    if duration_s is None or not isinstance(distance_m, (int, float)):
        _log.warning(
            "distance_matrix_driving: malformed route entry — duration=%r distance=%r",
            route.get("duration"),
            distance_m,
        )
        return None

    return DistanceMatrixResult(
        distance_km=float(distance_m) / 1000.0,
        travel_minutes=duration_s / 60.0,
        raw_status="ok",
    )
