"""End-to-end tests that pretend to be Claude Mobile.

These exercise the full FastMCP layer — JSON Schema validation, tool dispatch,
result serialization — by driving an in-process MCP Client. The Google API is
mocked with respx so tests are hermetic.

Each test is named after the natural-language prompt a user would type into
Claude Mobile. The arguments are what we'd expect Claude to synthesize from
that prompt.
"""

import json
import re

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server
from google_maps import PLACES_SEARCH_TEXT_URL, ROUTES_COMPUTE_URL


def _places_response(places: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"places": places})


def _route_response(route: dict) -> httpx.Response:
    return httpx.Response(200, json={"routes": [route]})


# ---------- search_nearby_places scenarios ----------


@respx.mock
async def test_user_asks_for_bookstores_near_soho():
    """User: 'What independent bookstores are near Soho?'"""

    def respond(request):
        body = json.loads(request.content)
        if body["textQuery"] == "Soho, Manhattan":  # the area-resolution call
            return httpx.Response(
                200,
                json={
                    "places": [
                        {
                            "id": "soho",
                            "location": {"latitude": 40.723, "longitude": -74.001},
                            "viewport": {
                                "low": {"latitude": 40.718, "longitude": -74.008},
                                "high": {"latitude": 40.729, "longitude": -73.995},
                            },
                        }
                    ]
                },
            )
        return _places_response(
            [
                {
                    "id": "p1",
                    "displayName": {"text": "McNally Jackson"},
                    "formattedAddress": "134 Prince St, New York",
                    "location": {"latitude": 40.724, "longitude": -73.999},
                    "rating": 4.5,
                    "userRatingCount": 1200,
                    "googleMapsUri": "https://maps.example/p1",
                }
            ]
        )

    mock = respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=respond)

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_nearby_places",
            {"queries": ["independent bookstores"], "area_name": "Soho, Manhattan"},
        )

    assert result.is_error is False
    assert "## 1. McNally Jackson" in result.data
    assert "- **Map:** https://maps.example/p1" in result.data

    # The MCP layer dispatched the area-name path: the text query carries the
    # area, and the resolved viewport rides along as a rectangle bias.
    body = json.loads(mock.calls.last.request.content)
    assert body["textQuery"] == "independent bookstores in Soho, Manhattan"
    assert "rectangle" in body["locationBias"]


@respx.mock
async def test_user_asks_for_coffee_within_five_minute_walk():
    """User: 'Coffee within five minutes walk?' (Claude picks ~400m radius)"""
    mock = respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=_places_response(
            [{"id": "c1", "displayName": {"text": "Cafe One"}}]
        )
    )

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_nearby_places",
            {
                "queries": ["coffee shops"],
                "coordinates": {"lat": 40.7308, "lng": -73.9973},
                "radius_m": 400,
                "max_results": 5,
            },
        )

    assert result.is_error is False
    body = json.loads(mock.calls.last.request.content)
    assert body["textQuery"] == "coffee shops"
    assert body["maxResultCount"] == 5
    assert body["locationBias"]["circle"]["radius"] == 400.0
    assert body["locationBias"]["circle"]["center"] == {
        "latitude": 40.7308,
        "longitude": -73.9973,
    }


# ---------- get_route scenarios ----------


@respx.mock
async def test_user_asks_walking_route_via_latlng():
    """User points at the map: 'How do I walk from here to the Brooklyn Bridge?'"""
    mock = respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=_route_response(
            {
                "distanceMeters": 1800,
                "duration": "1500s",
                "staticDuration": "1450s",
                "polyline": {"encodedPolyline": "abc"},
                "legs": [
                    {
                        "steps": [
                            {
                                "distanceMeters": 200,
                                "staticDuration": "150s",
                                "navigationInstruction": {
                                    "instructions": "Head south on Centre St",
                                    "maneuver": "DEPART",
                                },
                                "polyline": {"encodedPolyline": "s1"},
                            }
                        ]
                    }
                ],
            }
        )
    )

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_route",
            {
                "origin": {"lat": 40.7128, "lng": -74.0060},
                "destination": {"lat": 40.7061, "lng": -73.9969},
                "travel_mode": "WALK",
            },
        )

    assert result.is_error is False
    out = result.data
    assert out["distance_m"] == 1800
    assert out["duration_in_traffic_s"] == 1500
    assert out["polyline"] == "abc"
    assert out["steps"][0]["instruction"] == "Head south on Centre St"

    body = json.loads(mock.calls.last.request.content)
    assert body["origin"] == {
        "location": {"latLng": {"latitude": 40.7128, "longitude": -74.0060}}
    }
    assert body["travelMode"] == "WALK"


@respx.mock
async def test_user_asks_to_arrive_at_jfk_by_6pm_eastern():
    """User: 'When do I need to leave to be at JFK by 6pm Eastern?'

    Claude sends an offset-form arrival_time. Server should normalize to UTC
    on the wire and derive a UTC departure_time from the route duration.
    """
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=_route_response(
            {
                "distanceMeters": 30000,
                "duration": "3600s",
                "staticDuration": "3600s",
                "polyline": {"encodedPolyline": "p"},
                "legs": [
                    {
                        "steps": [
                            {
                                "distanceMeters": 30000,
                                "staticDuration": "3600s",
                                "navigationInstruction": {
                                    "instructions": "Take the LIRR",
                                    "maneuver": "DEPART",
                                },
                                "polyline": {"encodedPolyline": "p"},
                            }
                        ]
                    }
                ],
            }
        )
    )

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_route",
            {
                "origin": "Penn Station, New York",
                "destination": "JFK Airport, New York",
                "travel_mode": "TRANSIT",
                "arrival_time": "2026-04-27T18:00:00-04:00",
            },
        )

    assert result.is_error is False
    out = result.data
    # 6pm Eastern = 22:00Z; subtract 3600s → 21:00Z departure.
    assert out["arrival_time"] == "2026-04-27T22:00:00Z"
    assert out["departure_time"].startswith("2026-04-27T21:00:00")

    # And that's the form Google saw on the wire.
    body = json.loads(respx.calls.last.request.content)
    assert body["arrivalTime"] == "2026-04-27T22:00:00Z"


@respx.mock
async def test_user_asks_to_leave_now_for_penn_station():
    """User: 'Walk me to Penn Station from where I am.' No times given."""
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=_route_response(
            {
                "distanceMeters": 800,
                "duration": "600s",
                "staticDuration": "600s",
                "polyline": {"encodedPolyline": "x"},
                "legs": [{"steps": []}],
            }
        )
    )

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_route",
            {
                "origin": {"lat": 40.7505, "lng": -73.9934},
                "destination": "Penn Station, New York",
                "travel_mode": "WALK",
            },
        )

    out = result.data
    assert out["duration_in_traffic_s"] == 600
    # Both times should be derived ("leave now" / arrive in 10 min).
    assert out["departure_time"] is not None
    assert out["arrival_time"] is not None


@respx.mock
async def test_naive_timestamp_from_claude_is_normalized():
    """Regression: Claude sometimes generates a naive timestamp without 'Z'.

    The server must normalize before hitting Google. This test would have
    caught the original 400/INVALID_ARGUMENT bug.
    """
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=_route_response(
            {
                "distanceMeters": 100,
                "duration": "60s",
                "staticDuration": "60s",
                "polyline": {"encodedPolyline": "x"},
                "legs": [{"steps": []}],
            }
        )
    )

    async with Client(server.mcp) as client:
        await client.call_tool(
            "get_route",
            {
                "origin": "A",
                "destination": "B",
                "travel_mode": "TRANSIT",
                "arrival_time": "2026-04-27T18:00:00",  # naive
            },
        )

    body = json.loads(respx.calls.last.request.content)
    assert body["arrivalTime"] == "2026-04-27T18:00:00Z"


# ---------- get_events scenarios ----------


@respx.mock
async def test_agent_composes_place_search_with_batched_event_check(monkeypatch):
    """User: 'What's happening near Williamsburg this weekend?'

    The agent-side flow: search_nearby_places surfaces venues with `website`
    fields, then the agent passes ALL websites to get_events in one
    call. The scrape/extract pipeline is stubbed at its seam so the test
    exercises schema validation, the website plumbing, and serialization.
    """
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=_places_response(
            [
                {
                    "id": "v1",
                    "displayName": {"text": "Test Hall"},
                    "formattedAddress": "1 Wythe Ave, Brooklyn",
                    "location": {"latitude": 40.72, "longitude": -73.96},
                    "websiteUri": "https://testhall.example",
                    "googleMapsUri": "https://maps.example/v1",
                },
                {
                    "id": "v2",
                    "displayName": {"text": "Blocked Bar"},
                    "websiteUri": "https://blockedbar.example",
                },
            ]
        )
    )

    extracted = [
        {
            "event_title_derived": "Jazz Night at Test Hall",
            "event_description_derived": "Live jazz.",
            "start_date": "2026-07-04",
            "start_date_numeric": 20260704,
            "start_time": "20:00:00",
            "price": "$15",
            "keywords": "jazz, music, live, bar, night",
            "emoji": "🎷",
            "event_page_url": "https://testhall.example/events",
        }
    ]
    captured: dict = {}

    async def fake_batch(websites, **kwargs):
        captured["websites"] = websites
        return {
            "https://testhall.example": extracted,
            "https://blockedbar.example": {"error": "bot-challenge wall"},
        }

    monkeypatch.setattr(server, "check_websites_for_events", fake_batch)

    async with Client(server.mcp) as client:
        # Step 1: the agent finds venues; websites appear as markdown lines
        # it reads out of the response.
        places = await client.call_tool(
            "search_nearby_places",
            {
                "queries": ["live music venues and bars"],
                "area_name": "Williamsburg, Brooklyn",
            },
        )
        websites = re.findall(r"- \*\*Website:\*\* (\S+)", places.data)
        assert websites == [
            "https://testhall.example",
            "https://blockedbar.example",
        ]

        # Step 2: one batched call for every website.
        result = await client.call_tool("get_events", {"websites": websites})

    assert result.is_error is False
    assert result.data["https://testhall.example"] == extracted
    assert result.data["https://blockedbar.example"]["error"] == "bot-challenge wall"
    assert captured["websites"] == websites


async def test_get_events_bad_urls_become_error_entries():
    """Social/invalid URLs don't fail the batch — they come back per-site."""
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_events",
            {"websites": ["https://www.instagram.com/venue", "not a url"]},
        )
    assert "social-media" in result.data["https://www.instagram.com/venue"]["error"]
    assert "http" in result.data["not a url"]["error"]


async def test_get_events_rejects_empty_list():
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="at least 1|too_short|min_length"):
            await client.call_tool("get_events", {"websites": []})


async def test_get_events_requires_gemini_key(monkeypatch):
    monkeypatch.setattr(server, "GEMINI_API_KEY", None)
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="GEMINI_API_KEY"):
            await client.call_tool(
                "get_events", {"websites": ["https://venue.test"]}
            )


# ---------- failure-mode scenarios ----------


async def test_schema_rejects_oversized_radius():
    """Pydantic should reject radius_m > 50_000 at the MCP boundary, before any
    Google call is attempted.
    """
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="less_than_equal|50000"):
            await client.call_tool(
                "search_nearby_places",
                {"queries": ["x"], "area_name": "Soho", "radius_m": 999_999},
            )


@respx.mock
async def test_omitted_travel_mode_uses_owner_default(monkeypatch):
    """User: 'How do I get to the airport?' — no mode stated. The server
    fills in the install-time default (here, a midwestern driver)."""
    monkeypatch.setattr(server, "DEFAULT_TRAVEL_MODE", "DRIVE")
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=_route_response(
            {
                "distanceMeters": 100,
                "duration": "60s",
                "staticDuration": "60s",
                "polyline": {"encodedPolyline": "x"},
                "legs": [{"steps": []}],
            }
        )
    )
    async with Client(server.mcp) as client:
        await client.call_tool(
            "get_route", {"origin": "A", "destination": "B"}
        )
    body = json.loads(respx.calls.last.request.content)
    assert body["travelMode"] == "DRIVE"
    assert body["routingPreference"] == "TRAFFIC_AWARE"


async def test_arrival_time_rejected_for_non_transit():
    """Routes API only honors arrivalTime for TRANSIT; fail with guidance
    instead of forwarding a request Google will 400."""
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="only supported for TRANSIT"):
            await client.call_tool(
                "get_route",
                {
                    "origin": "A",
                    "destination": "B",
                    "travel_mode": "DRIVE",
                    "arrival_time": "2026-07-05T18:00:00Z",
                },
            )


async def test_runtime_rejects_both_arrival_and_departure():
    """Tool body should reject ambiguous timing rather than silently picking one."""
    async with Client(server.mcp) as client:
        with pytest.raises(
            ToolError, match="at most one of `arrival_time` or `departure_time`"
        ):
            await client.call_tool(
                "get_route",
                {
                    "origin": "A",
                    "destination": "B",
                    "travel_mode": "WALK",
                    "arrival_time": "2026-04-27T18:00:00Z",
                    "departure_time": "2026-04-27T17:00:00Z",
                },
            )
