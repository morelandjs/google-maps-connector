"""End-to-end tests that pretend to be Claude Mobile.

These exercise the full FastMCP layer — JSON Schema validation, tool dispatch,
result serialization — by driving an in-process MCP Client. The Google API is
mocked with respx so tests are hermetic.

Each test is named after the natural-language prompt a user would type into
Claude Mobile. The arguments are what we'd expect Claude to synthesize from
that prompt.
"""

import json

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
    mock = respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=_places_response(
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
    )

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_nearby_places",
            {"query": "independent bookstores", "area_name": "Soho, Manhattan"},
        )

    assert result.is_error is False
    assert result.data[0]["name"] == "McNally Jackson"
    assert result.data[0]["maps_url"] == "https://maps.example/p1"

    # The MCP layer dispatched the area-name path: text query carries the area,
    # no locationBias was sent.
    body = json.loads(mock.calls.last.request.content)
    assert body["textQuery"] == "independent bookstores in Soho, Manhattan"
    assert "locationBias" not in body


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
                "query": "coffee shops",
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
                "travel_mode": "WALK",
                "arrival_time": "2026-04-27T18:00:00",  # naive
            },
        )

    body = json.loads(respx.calls.last.request.content)
    assert body["arrivalTime"] == "2026-04-27T18:00:00Z"


# ---------- failure-mode scenarios ----------


async def test_schema_rejects_oversized_radius():
    """Pydantic should reject radius_m > 50_000 at the MCP boundary, before any
    Google call is attempted.
    """
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="less_than_equal|50000"):
            await client.call_tool(
                "search_nearby_places",
                {"query": "x", "area_name": "Soho", "radius_m": 999_999},
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
