"""Tests for Google Maps reverse-geocode service.

Mocks ``httpx.AsyncClient`` so tests don't hit the real API.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.verification.services.google_maps import reverse_geocode


def _make_response(status_code: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(body)
    resp.json = MagicMock(return_value=body)
    resp.raise_for_status = MagicMock()
    return resp


def _make_client(response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    # ``reverse_geocode`` uses GET, ``distance_matrix_driving`` (Routes API)
    # uses POST. Mock both so a single fixture serves both call sites.
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    return client


async def test_reverse_geocode_returns_formatted_address_on_ok():
    body = {
        "status": "OK",
        "results": [
            {
                "formatted_address": (
                    "H No 123, Village Sadipur, Hisar, Haryana 125001, India"
                ),
                "place_id": "xyz",
            },
            {"formatted_address": "Haryana 125001, India"},
        ],
    }
    client = _make_client(_make_response(200, body))

    addr = await reverse_geocode(
        lat=29.1577,
        lon=75.72,
        api_key="FAKE_KEY",
        client_factory=lambda: client,
    )

    assert addr is not None
    assert "Sadipur" in addr
    assert "Hisar" in addr
    assert "Haryana" in addr
    # Ensure the URL was called with the right params
    call_args = client.get.call_args
    assert call_args is not None
    params = call_args.kwargs.get("params") or call_args.args[1] if call_args.args else {}
    assert str(params.get("latlng")) == "29.1577,75.72"
    assert params.get("key") == "FAKE_KEY"


async def test_reverse_geocode_returns_none_on_zero_results():
    body = {"status": "ZERO_RESULTS", "results": []}
    client = _make_client(_make_response(200, body))
    addr = await reverse_geocode(
        lat=0.0, lon=0.0, api_key="FAKE_KEY", client_factory=lambda: client
    )
    assert addr is None


async def test_reverse_geocode_returns_none_on_http_error():
    resp = _make_response(500, {"error_message": "server down"})
    resp.raise_for_status.side_effect = Exception("500 server error")
    client = _make_client(resp)
    addr = await reverse_geocode(
        lat=0.0, lon=0.0, api_key="FAKE_KEY", client_factory=lambda: client
    )
    assert addr is None


async def test_reverse_geocode_returns_none_with_empty_api_key():
    """Safety: don't call the API without a key; return None."""
    # No client_factory call should be made → use a sentinel that would fail if called.
    def _boom():  # pragma: no cover — must not be invoked
        raise AssertionError("client_factory must not be called when api_key is empty")

    assert await reverse_geocode(lat=1.0, lon=2.0, api_key="", client_factory=_boom) is None
    assert await reverse_geocode(lat=1.0, lon=2.0, api_key=None, client_factory=_boom) is None


async def test_reverse_geocode_returns_none_on_connection_error():
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=RuntimeError("network down"))
    addr = await reverse_geocode(
        lat=1.0, lon=2.0, api_key="FAKE_KEY", client_factory=lambda: client
    )
    assert addr is None


async def test_reverse_geocode_status_request_denied_is_none():
    body = {"status": "REQUEST_DENIED", "error_message": "API key invalid"}
    client = _make_client(_make_response(200, body))
    addr = await reverse_geocode(
        lat=1.0, lon=2.0, api_key="FAKE_KEY", client_factory=lambda: client
    )
    assert addr is None


# ─────────────────────────── Routes API (driving) ──────────────────────────
# ``distance_matrix_driving`` is the public name kept for backward-compat
# with the L1 orchestrator, but underneath it now calls Google's modern
# Routes API (computeRoutes) — the legacy Distance Matrix REST endpoint
# is being deprecated and is not enabled by default on new GCP projects.
#
# Routes API contract:
#   - POST https://routes.googleapis.com/directions/v2:computeRoutes
#   - Headers: X-Goog-Api-Key, X-Goog-FieldMask, Content-Type: application/json
#   - Body: {origin: {location: {latLng: {latitude, longitude}}},
#            destination: {location: {latLng: {latitude, longitude}}},
#            travelMode: "DRIVE", routingPreference: "TRAFFIC_UNAWARE"}
#   - Response 200: {routes: [{duration: "1080s", distanceMeters: 9200}]}
#   - No route / unreachable: 200 with {} or {routes: []}
#   - Errors: HTTP 4xx/5xx OR 200 with {error: {code, message}}


async def test_distance_matrix_driving_returns_ok_result():
    from app.verification.services.google_maps import distance_matrix_driving

    body = {
        "routes": [
            {
                "duration": "1080s",
                "distanceMeters": 9200,
            }
        ]
    }
    client = _make_client(_make_response(200, body))

    res = await distance_matrix_driving(
        origin_lat=29.16,
        origin_lon=75.72,
        dest_lat=29.15,
        dest_lon=75.73,
        api_key="FAKE_KEY",
        client_factory=lambda: client,
    )

    assert res is not None
    assert res.raw_status == "ok"
    assert abs(res.distance_km - 9.2) < 0.01
    assert abs(res.travel_minutes - 18.0) < 0.01

    # Verify Routes API contract — POST with FieldMask + JSON body shape.
    call_args = client.post.call_args
    assert call_args is not None
    headers = call_args.kwargs.get("headers") or {}
    assert headers.get("X-Goog-Api-Key") == "FAKE_KEY"
    field_mask = headers.get("X-Goog-FieldMask", "")
    assert "duration" in field_mask
    assert "distanceMeters" in field_mask
    body_sent = call_args.kwargs.get("json") or {}
    assert body_sent["origin"]["location"]["latLng"]["latitude"] == 29.16
    assert body_sent["origin"]["location"]["latLng"]["longitude"] == 75.72
    assert body_sent["destination"]["location"]["latLng"]["latitude"] == 29.15
    assert body_sent["destination"]["location"]["latLng"]["longitude"] == 75.73
    assert body_sent["travelMode"] == "DRIVE"
    # No live-traffic — deterministic across re-runs.
    assert body_sent.get("routingPreference") == "TRAFFIC_UNAWARE"


async def test_distance_matrix_driving_no_route_returns_zero_results():
    from app.verification.services.google_maps import distance_matrix_driving

    body = {"routes": []}
    client = _make_client(_make_response(200, body))
    res = await distance_matrix_driving(
        origin_lat=0.0,
        origin_lon=0.0,
        dest_lat=1.0,
        dest_lon=1.0,
        api_key="FAKE_KEY",
        client_factory=lambda: client,
    )
    assert res is not None
    assert res.raw_status == "zero_results"
    assert res.travel_minutes == 0.0
    assert res.distance_km == 0.0


async def test_distance_matrix_driving_empty_body_returns_zero_results():
    """Routes API may respond with ``{}`` rather than ``{routes: []}`` when
    no route exists — both shapes must map to the same zero_results status."""
    from app.verification.services.google_maps import distance_matrix_driving

    client = _make_client(_make_response(200, {}))
    res = await distance_matrix_driving(
        origin_lat=0.0,
        origin_lon=0.0,
        dest_lat=1.0,
        dest_lon=1.0,
        api_key="FAKE_KEY",
        client_factory=lambda: client,
    )
    assert res is not None
    assert res.raw_status == "zero_results"


async def test_distance_matrix_driving_network_error_returns_none():
    from app.verification.services.google_maps import distance_matrix_driving

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=RuntimeError("network down"))

    res = await distance_matrix_driving(
        origin_lat=0.0,
        origin_lon=0.0,
        dest_lat=1.0,
        dest_lon=1.0,
        api_key="FAKE_KEY",
        client_factory=lambda: client,
    )
    assert res is None


async def test_distance_matrix_driving_empty_key_returns_none():
    from app.verification.services.google_maps import distance_matrix_driving

    def _boom():  # pragma: no cover — must not be invoked
        raise AssertionError("client_factory must not be called with empty api_key")

    res = await distance_matrix_driving(
        origin_lat=0.0,
        origin_lon=0.0,
        dest_lat=1.0,
        dest_lon=1.0,
        api_key="",
        client_factory=_boom,
    )
    assert res is None


async def test_distance_matrix_driving_http_403_returns_none():
    """Routes API surfaces auth failures as HTTP 403 with an error envelope."""
    from app.verification.services.google_maps import distance_matrix_driving

    body = {"error": {"code": 403, "message": "PERMISSION_DENIED", "status": "PERMISSION_DENIED"}}
    resp = _make_response(403, body)
    resp.raise_for_status.side_effect = Exception("403 forbidden")
    client = _make_client(resp)
    res = await distance_matrix_driving(
        origin_lat=0.0,
        origin_lon=0.0,
        dest_lat=1.0,
        dest_lon=1.0,
        api_key="FAKE_KEY",
        client_factory=lambda: client,
    )
    assert res is None


async def test_distance_matrix_driving_200_with_error_envelope_returns_none():
    """Routes API can also return HTTP 200 + ``{error: {...}}`` for some
    invalid-request cases — the helper must still return None."""
    from app.verification.services.google_maps import distance_matrix_driving

    body = {"error": {"code": 400, "message": "Invalid origin", "status": "INVALID_ARGUMENT"}}
    client = _make_client(_make_response(200, body))
    res = await distance_matrix_driving(
        origin_lat=0.0,
        origin_lon=0.0,
        dest_lat=1.0,
        dest_lon=1.0,
        api_key="FAKE_KEY",
        client_factory=lambda: client,
    )
    assert res is None


async def test_distance_matrix_driving_decimal_seconds_parsed():
    """Routes API may return durations like ``'1080.5s'`` — the parser must
    accept fractional seconds, not insist on integers."""
    from app.verification.services.google_maps import distance_matrix_driving

    body = {"routes": [{"duration": "1080.5s", "distanceMeters": 9250}]}
    client = _make_client(_make_response(200, body))
    res = await distance_matrix_driving(
        origin_lat=0.0, origin_lon=0.0, dest_lat=1.0, dest_lon=1.0,
        api_key="FAKE_KEY", client_factory=lambda: client,
    )
    assert res is not None
    assert res.raw_status == "ok"
    assert abs(res.travel_minutes - 18.0083333) < 0.01
    assert abs(res.distance_km - 9.25) < 0.01
