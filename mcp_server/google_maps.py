"""Thin async clients for Google Maps Platform endpoints used by the MCP server.

Two endpoints, both POST + JSON, both require an API key header AND a field-mask
header. The field mask is what tells Google which fields to return; without it
the call either fails or returns almost nothing, and it also drives billing.
"""

from __future__ import annotations

from typing import Any

import httpx

PLACES_SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_COMPUTE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.userRatingCount",
        "places.googleMapsUri",
        "places.types",
        "places.regularOpeningHours.weekdayDescriptions",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.generativeSummary",
        "places.reviewSummary",
    ]
)

ROUTES_FIELD_MASK = ",".join(
    [
        "routes.distanceMeters",
        "routes.duration",
        "routes.staticDuration",
        "routes.polyline.encodedPolyline",
        "routes.legs.distanceMeters",
        "routes.legs.duration",
        "routes.legs.steps.distanceMeters",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.navigationInstruction",
        "routes.legs.steps.polyline.encodedPolyline",
    ]
)


class GoogleMapsError(RuntimeError):
    """Raised when a Maps API call returns a non-2xx status or unparseable body."""


async def search_places_by_text(
    *,
    api_key: str,
    text_query: str,
    location_bias: dict[str, Any] | None = None,
    max_results: int = 10,
    timeout: float = 10.0,
    language_code: str = "en",
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "textQuery": text_query,
        "maxResultCount": max(1, min(max_results, 20)),
        # Google localizes names, addresses, hours, and the AI summaries
        # natively — no client-side translation needed.
        "languageCode": language_code,
    }
    if location_bias is not None:
        body["locationBias"] = location_bias

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(PLACES_SEARCH_TEXT_URL, json=body, headers=headers)

    if resp.status_code != 200:
        raise GoogleMapsError(
            f"places:searchText returned {resp.status_code}: {resp.text}"
        )
    return resp.json().get("places", [])


async def compute_route(
    *,
    api_key: str,
    origin: dict[str, Any],
    destination: dict[str, Any],
    travel_mode: str,
    arrival_time: str | None = None,
    departure_time: str | None = None,
    transit_routing_preference: str | None = None,
    timeout: float = 10.0,
    language_code: str = "en",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "travelMode": travel_mode,
        "languageCode": language_code,  # localizes navigation instructions
    }
    # Routes API defaults DRIVE to TRAFFIC_UNAWARE; live traffic is the whole
    # point of asking for a drive time. Only valid for DRIVE/TWO_WHEELER.
    if travel_mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
    if arrival_time:
        body["arrivalTime"] = arrival_time
    if departure_time:
        body["departureTime"] = departure_time
    # transitPreferences is only meaningful for TRANSIT routes; Google rejects
    # or ignores it for WALK/DRIVE/BICYCLE.
    if travel_mode == "TRANSIT" and transit_routing_preference:
        body["transitPreferences"] = {
            "routingPreference": transit_routing_preference,
        }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ROUTES_FIELD_MASK,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(ROUTES_COMPUTE_URL, json=body, headers=headers)

    if resp.status_code != 200:
        raise GoogleMapsError(
            f"computeRoutes returned {resp.status_code}: {resp.text}"
        )

    routes = resp.json().get("routes", [])
    if not routes:
        raise GoogleMapsError("computeRoutes returned no routes")
    return routes[0]
