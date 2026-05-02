"""Live smoke tests against the real Google Maps Platform.

These are SKIPPED by default. They make real API calls (using the key from
.env), spend a tiny amount of quota, and require an internet connection.

Run them with:

    RUN_LIVE_TESTS=1 .venv/bin/pytest tests/test_live_smoke.py -v

Their job is narrow: catch the class of regressions hermetic mocks can't —
Google quietly renaming a field, the request shape diverging from the docs,
the API key losing the right restrictions, etc. Assertions are intentionally
loose ("at least one result", "duration > 0") to avoid breaking on day-to-day
business changes (a cafe closing, a route detour).
"""

from __future__ import annotations

import os

import pytest

import server

LIVE_ENABLED = os.environ.get("RUN_LIVE_TESTS") == "1"
HAS_REAL_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "") not in {
    "",
    "TEST_KEY",
    "YOUR_API_KEY",
    "YOUR_KEY",
}

pytestmark = [
    pytest.mark.skipif(
        not LIVE_ENABLED,
        reason="set RUN_LIVE_TESTS=1 to run live tests against real Google APIs",
    ),
    pytest.mark.skipif(
        not HAS_REAL_KEY,
        reason="GOOGLE_MAPS_API_KEY missing or set to a placeholder — "
        "fill .env with a real key before running live tests",
    ),
]


async def test_search_nearby_places_live_against_google():
    """Search a globally well-known area; verify response shape end-to-end."""
    results = await server.search_nearby_places(
        query="coffee",
        area_name="Times Square, New York",
        max_results=3,
    )

    assert isinstance(results, list)
    assert len(results) >= 1, "Expected at least one coffee result near Times Square"

    first = results[0]
    # Required fields per the tool contract.
    for key in (
        "name",
        "address",
        "lat",
        "lng",
        "place_id",
        "maps_url",
        "types",
        "weekday_hours",
        "reviews",
        "phone_number",
    ):
        assert key in first, f"missing key {key!r} in response"

    # Times Square coffee shops should have at least one type and very likely
    # opening hours and reviews — but we stay loose to avoid breaking on
    # business-info changes.
    assert isinstance(first["types"], list) and len(first["types"]) >= 1
    assert isinstance(first["weekday_hours"], list)
    assert isinstance(first["reviews"], list)
    # phone_number may legitimately be None for some places.

    # Sanity-check types on the must-have fields. Optional fields (rating,
    # price_level) may legitimately be None for places Google hasn't classified.
    assert isinstance(first["name"], str) and first["name"]
    assert isinstance(first["address"], str) and first["address"]
    assert isinstance(first["place_id"], str) and first["place_id"]
    assert isinstance(first["maps_url"], str) and first["maps_url"].startswith("http")
    assert isinstance(first["lat"], (int, float))
    assert isinstance(first["lng"], (int, float))
    # Times Square is roughly (40.76, -73.99); make sure we're at least on the
    # right continent — guards against a lat/lng swap or unit confusion.
    assert 40.0 < first["lat"] < 41.0
    assert -75.0 < first["lng"] < -73.0


async def test_get_route_live_against_google():
    """Walk between two stable midtown landmarks; verify response shape."""
    # Times Square → Empire State Building, both pinned by lat/lng so we don't
    # depend on Google's address-resolution layer.
    result = await server.get_route(
        origin=server.LatLng(lat=40.7580, lng=-73.9855),
        destination=server.LatLng(lat=40.7484, lng=-73.9857),
        travel_mode="WALK",
    )

    assert isinstance(result, dict)
    for key in (
        "distance_m",
        "duration_s",
        "duration_in_traffic_s",
        "departure_time",
        "arrival_time",
        "polyline",
        "steps",
    ):
        assert key in result, f"missing key {key!r} in response"

    # ~1km walk; we'd expect 500m–2km regardless of routing tweaks.
    assert 200 < result["distance_m"] < 3000
    assert result["duration_s"] is not None and result["duration_s"] > 0
    assert isinstance(result["polyline"], str) and len(result["polyline"]) > 10
    assert isinstance(result["steps"], list) and len(result["steps"]) >= 1

    first_step = result["steps"][0]
    assert isinstance(first_step["instruction"], str) and first_step["instruction"]
    assert isinstance(first_step["distance_m"], int) and first_step["distance_m"] >= 0

    # No times provided → both should be derived ("leave now" semantics).
    assert result["departure_time"] is not None
    assert result["arrival_time"] is not None
