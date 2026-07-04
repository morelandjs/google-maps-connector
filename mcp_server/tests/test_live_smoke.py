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
import re

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
    """Search a globally well-known area; verify markdown shape end-to-end."""
    out = await server.search_nearby_places(
        queries=["coffee"],
        area_name="Times Square, New York",
        max_results=3,
    )

    assert isinstance(out, str)
    assert out.startswith("## 1. "), "Expected at least one coffee result"

    # Must-have lines for a Times Square coffee shop.
    for label in ("Address", "Coordinates", "Types", "Map", "Place ID"):
        assert f"- **{label}:** " in out, f"missing {label!r} line"

    # Times Square is roughly (40.76, -73.99); make sure we're at least on the
    # right continent — guards against a lat/lng swap or unit confusion.
    coords = re.search(r"- \*\*Coordinates:\*\* (-?[\d.]+), (-?[\d.]+)", out)
    assert coords, "missing Coordinates line"
    lat, lng = float(coords.group(1)), float(coords.group(2))
    assert 40.0 < lat < 41.0
    assert -75.0 < lng < -73.0


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


HAS_REAL_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "") not in {
    "",
    "TEST_GEMINI_KEY",
    "YOUR_AI_STUDIO_KEY",
}


@pytest.mark.skipif(
    not HAS_REAL_GEMINI_KEY,
    reason="GEMINI_API_KEY missing or set to a placeholder — "
    "fill .env with a real AI Studio key before running live get_events",
)
async def test_place_search_then_get_events_live():
    """The composed agent flow, live: find venues, then check all their
    websites in one batched call.

    Content is nondeterministic (live websites, live model), so assertions
    are structural only. Zero events and per-site errors (bot walls) are
    legitimate outcomes; every site erroring IS a regression.
    """
    places_md = await server.search_nearby_places(
        queries=["live music venues and bars"],
        area_name="Williamsburg, Brooklyn",
        max_results=5,
    )
    candidates = re.findall(r"- \*\*Website:\*\* (\S+)", places_md)
    assert candidates, "expected at least one venue with a website"

    result = await server.get_events(websites=candidates[:3])
    assert set(result) == set(candidates[:3])

    succeeded = {
        site: value for site, value in result.items() if isinstance(value, list)
    }
    failed = {site: value for site, value in result.items() if isinstance(value, dict)}
    for value in failed.values():
        assert value.get("error")  # failures must carry a reason
    assert succeeded, f"every site failed: {failed}"

    expected_keys = {
        "event_title_derived",
        "event_description_derived",
        "start_date",
        "start_date_numeric",
        "start_time",
        "price",
        "keywords",
        "emoji",
        "event_page_url",
    }
    for events in succeeded.values():
        for event in events:
            assert set(event) == expected_keys
            assert event["event_page_url"].startswith("http")
            if event["start_date"]:
                assert event["start_date_numeric"] is not None
