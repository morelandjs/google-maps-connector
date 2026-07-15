import json

import httpx
import pytest
import respx

from google_maps import (
    AREA_RESOLVE_FIELD_MASK,
    PLACES_FIELD_MASK,
    PLACES_SEARCH_TEXT_URL,
    ROUTES_COMPUTE_URL,
    ROUTES_FIELD_MASK,
    GoogleMapsError,
    compute_route,
    resolve_area_viewport,
    search_places_by_text,
)


@respx.mock
async def test_resolve_area_viewport_returns_viewport_with_minimal_mask():
    route = respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "x",
                        "location": {"latitude": 40.7, "longitude": -74.0},
                        "viewport": {
                            "low": {"latitude": 40.69, "longitude": -74.01},
                            "high": {"latitude": 40.71, "longitude": -73.99},
                        },
                    }
                ]
            },
        )
    )

    viewport = await resolve_area_viewport(api_key="k", area_name="Soho")

    assert viewport == {
        "low": {"latitude": 40.69, "longitude": -74.01},
        "high": {"latitude": 40.71, "longitude": -73.99},
    }
    request = route.calls.last.request
    assert request.headers["X-Goog-FieldMask"] == AREA_RESOLVE_FIELD_MASK
    body = json.loads(request.content)
    assert body == {
        "textQuery": "Soho",
        "maxResultCount": 1,
        "languageCode": "en",
    }


@respx.mock
async def test_resolve_area_viewport_swallows_http_failures():
    """Resolution is a ranking enhancement — a 500 must yield None, not raise."""
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(500, text="boom")
    )
    assert await resolve_area_viewport(api_key="k", area_name="Soho") is None


@respx.mock
async def test_resolve_area_viewport_handles_unresolvable_names():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(200, json={})
    )
    assert await resolve_area_viewport(api_key="k", area_name="Xyzzy") is None


@respx.mock
async def test_search_places_sends_required_headers_and_body():
    route = respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "abc",
                        "displayName": {"text": "Test Cafe", "languageCode": "en"},
                        "formattedAddress": "1 Main St",
                        "location": {"latitude": 1.0, "longitude": 2.0},
                        "rating": 4.6,
                        "userRatingCount": 42,
                        "priceLevel": "PRICE_LEVEL_MODERATE",
                        "googleMapsUri": "https://maps.google.com/?cid=abc",
                    }
                ]
            },
        )
    )

    places = await search_places_by_text(
        api_key="TEST_KEY",
        text_query="coffee",
        location_bias={
            "circle": {
                "center": {"latitude": 1.0, "longitude": 2.0},
                "radius": 1500.0,
            }
        },
        max_results=5,
    )

    assert route.called
    req = route.calls.last.request
    assert req.headers["X-Goog-Api-Key"] == "TEST_KEY"
    assert req.headers["X-Goog-FieldMask"] == PLACES_FIELD_MASK

    body = json.loads(req.content)
    assert body["textQuery"] == "coffee"
    assert body["maxResultCount"] == 5
    assert body["locationBias"]["circle"]["radius"] == 1500.0
    assert body["languageCode"] == "en"  # default results language

    assert places[0]["id"] == "abc"


@respx.mock
async def test_search_places_clamps_max_results_to_20():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(200, json={"places": []})
    )
    await search_places_by_text(api_key="K", text_query="x", max_results=999)
    body = json.loads(respx.calls.last.request.content)
    assert body["maxResultCount"] == 20


@respx.mock
async def test_search_places_raises_on_non_200():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(403, text="forbidden")
    )
    with pytest.raises(GoogleMapsError):
        await search_places_by_text(api_key="K", text_query="x")


@respx.mock
async def test_compute_route_sends_required_headers_and_body():
    route = respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distanceMeters": 1234,
                        "duration": "600s",
                        "staticDuration": "550s",
                        "polyline": {"encodedPolyline": "ENC"},
                        "legs": [
                            {
                                "steps": [
                                    {
                                        "distanceMeters": 100,
                                        "staticDuration": "60s",
                                        "navigationInstruction": {
                                            "instructions": "Head north",
                                            "maneuver": "DEPART",
                                        },
                                        "polyline": {"encodedPolyline": "S1"},
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
        )
    )

    result = await compute_route(
        api_key="TEST_KEY",
        origin={"address": "A"},
        destination={"address": "B"},
        travel_mode="WALK",
        arrival_time="2026-04-26T18:00:00Z",
    )

    assert route.called
    req = route.calls.last.request
    assert req.headers["X-Goog-Api-Key"] == "TEST_KEY"
    assert req.headers["X-Goog-FieldMask"] == ROUTES_FIELD_MASK

    body = json.loads(req.content)
    assert body["travelMode"] == "WALK"
    assert body["arrivalTime"] == "2026-04-26T18:00:00Z"
    assert body["origin"] == {"address": "A"}

    assert result["distanceMeters"] == 1234
    assert result["duration"] == "600s"


@respx.mock
async def test_compute_route_drive_is_traffic_aware():
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=httpx.Response(
            200, json={"routes": [{"distanceMeters": 1, "duration": "1s"}]}
        )
    )
    await compute_route(
        api_key="K",
        origin={"address": "A"},
        destination={"address": "B"},
        travel_mode="DRIVE",
    )
    body = json.loads(respx.calls.last.request.content)
    assert body["travelMode"] == "DRIVE"
    # DRIVE defaults to TRAFFIC_UNAWARE upstream; we must opt into traffic.
    assert body["routingPreference"] == "TRAFFIC_AWARE"

    await compute_route(
        api_key="K",
        origin={"address": "A"},
        destination={"address": "B"},
        travel_mode="WALK",
    )
    body = json.loads(respx.calls.last.request.content)
    assert "routingPreference" not in body  # invalid for WALK/TRANSIT


@respx.mock
async def test_compute_route_raises_when_no_routes():
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=httpx.Response(200, json={"routes": []})
    )
    with pytest.raises(GoogleMapsError):
        await compute_route(
            api_key="K",
            origin={"address": "A"},
            destination={"address": "B"},
            travel_mode="WALK",
        )
