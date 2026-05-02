"""FastMCP server exposing two Google Maps tools to any MCP client.

Defaults to Streamable HTTP on 0.0.0.0:$PORT/mcp (matches the Cloud Run target).
Pass --stdio to switch to stdio transport, e.g. for direct use from a local
client config like claude_desktop_config.json.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.google import (
    AccessToken,
    GoogleProvider,
    GoogleTokenVerifier,
)
from pydantic import BaseModel, Field

from google_maps import (
    GoogleMapsError,
    compute_route,
    search_places_by_text,
)

logger = logging.getLogger(__name__)

load_dotenv()

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "GOOGLE_MAPS_API_KEY is not set. Copy .env.example to .env and fill it in, "
        "or export the variable before starting the server."
    )


class AllowlistedGoogleTokenVerifier(GoogleTokenVerifier):
    """GoogleTokenVerifier that additionally enforces a single-tenant allowlist.

    Without this, any valid Google account on the internet would be accepted
    by a public Cloud Run deployment — only the OAuth consent screen's "Test
    Users" list gates access, and that list stops applying once the consent
    screen is flipped to "In production".
    """

    # Google's email scope in its full URI form. Required for the verifier to
    # accept tokens whose granted scope set advertises email permission.
    EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"

    def __init__(self, *, allowed_emails: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._allowed_emails = {e.strip().lower() for e in allowed_emails if e.strip()}

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await super().verify_token(token)
        if access_token is None:
            return None
        email = (access_token.claims.get("email") or "").lower()
        if email not in self._allowed_emails:
            logger.warning(
                "Rejecting token: email %r is not on the allowlist", email
            )
            return None
        return access_token


def _build_auth_provider() -> GoogleProvider | OAuthProxy | None:
    """Construct an OAuth provider sized for the deployment environment.

    - No creds set → returns None (unauthenticated; tests + initial dev only).
    - Creds set, no allowlist → standard GoogleProvider; relies on the OAuth
      consent screen's Test Users list to gate access. Acceptable for Phase 2
      local dev. NOT acceptable for a Production-mode public deployment.
    - Creds set + GOOGLE_OAUTH_ALLOWED_EMAILS set → an OAuthProxy with our
      AllowlistedGoogleTokenVerifier in front. Phase 3 production posture.
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None

    base_url = os.environ.get("MCP_BASE_URL", "http://localhost:8000")
    allowed_emails_raw = os.environ.get("GOOGLE_OAUTH_ALLOWED_EMAILS", "")
    allowed_emails = [e.strip() for e in allowed_emails_raw.split(",") if e.strip()]

    if not allowed_emails:
        return GoogleProvider(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            required_scopes=["openid", "email"],
        )

    # Mirror what GoogleProvider.__init__ does internally, but wire in our
    # allowlist-enforcing verifier and pass scopes in their full URI form
    # (which is what Google returns; bare "email" wouldn't match).
    return OAuthProxy(
        upstream_authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        upstream_token_endpoint="https://oauth2.googleapis.com/token",
        upstream_client_id=client_id,
        upstream_client_secret=client_secret,
        token_verifier=AllowlistedGoogleTokenVerifier(
            allowed_emails=allowed_emails,
            required_scopes=[
                "openid",
                AllowlistedGoogleTokenVerifier.EMAIL_SCOPE,
            ],
        ),
        base_url=base_url,
        redirect_path="/auth/callback",
        # Match GoogleProvider's defaults so refresh tokens are issued.
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
    )


mcp = FastMCP(
    "Google Maps",
    auth=_build_auth_provider(),
    instructions=(
        "Use this server's tools whenever the user asks about real places, "
        "their attributes (hours, ratings, addresses, price tier), or how to "
        "travel between locations. "
        "Always call `search_nearby_places` for place-discovery questions even "
        "when the named area is famous (e.g. 'bookstores in Soho'); rely on "
        "Google's live data, not prior knowledge, because hours, ratings, "
        "and listings change. "
        "Always call `get_route` for any 'how do I get to X' / 'how long does "
        "it take to walk/take transit to Y' / 'when should I leave to arrive "
        "by Z' question — training-data answers on transit schedules and live "
        "traffic are stale. "
        "Skip these tools only when the user is asking a general/historical "
        "question that has no live-data component (e.g. 'when was the "
        "Brooklyn Bridge built?')."
    ),
)


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90, description="Latitude in decimal degrees.")
    lng: float = Field(ge=-180, le=180, description="Longitude in decimal degrees.")


def _waypoint_from(value: str | LatLng | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, LatLng):
        return {"location": {"latLng": {"latitude": value.lat, "longitude": value.lng}}}
    if isinstance(value, dict):
        # Pydantic may have already coerced into a dict in some call paths.
        return {
            "location": {
                "latLng": {"latitude": value["lat"], "longitude": value["lng"]}
            }
        }
    return {"address": value}


def _parse_duration_seconds(value: str | None) -> int | None:
    """Parse a protobuf Duration like '4137s' or '4137.5s' into integer seconds."""
    if not value:
        return None
    try:
        return int(float(value.rstrip("s")))
    except ValueError:
        return None


def _normalize_timestamp(value: str | None) -> str | None:
    """Coerce an ISO8601 timestamp into RFC3339 form Google's Routes API accepts.

    Google requires a trailing 'Z' or a numeric offset like '-04:00'. We accept
    naive timestamps (no tzinfo) and treat them as UTC, then emit the canonical
    'Z' form. Already-qualified inputs are converted to UTC and re-emitted in
    'Z' form so the wire representation stays consistent.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid ISO8601 timestamp {value!r}. Examples that work: "
            "'2026-04-27T18:00:00Z' (UTC) or '2026-04-27T14:00:00-04:00' (offset)."
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    iso = dt.astimezone(timezone.utc).isoformat()
    return iso[:-6] + "Z" if iso.endswith("+00:00") else iso


async def search_nearby_places(
    query: Annotated[
        str,
        Field(
            description=(
                "Free-text description of what to look for. Categories, types, "
                "or keywords work; specifics work better than generics. "
                "Examples: 'independent bookstores', 'late-night ramen', "
                "'rooftop bars with a view'."
            )
        ),
    ],
    coordinates: Annotated[
        LatLng | None,
        Field(
            description=(
                "A precise center point for the search, given as a {lat, lng} "
                "object in decimal degrees (e.g. {lat: 40.7308, lng: -73.9973}). "
                "Use this when you have GPS-grade coordinates — for instance, "
                "the user's current position. Combine with `radius_m` to "
                "control the search circle. Provide EITHER `coordinates` OR "
                "`area_name`, never both."
            )
        ),
    ] = None,
    area_name: Annotated[
        str | None,
        Field(
            description=(
                "Free-text name of the geographic area to search in, e.g. "
                "'Soho, Manhattan' or 'Shibuya, Tokyo'. Use this when the "
                "user named a place but no coordinates are available. Be as "
                "specific as you'd be on Google Maps — 'Soho, Manhattan, NY' "
                "returns better results than 'Soho'. Provide EITHER "
                "`coordinates` OR `area_name`, never both."
            )
        ),
    ] = None,
    radius_m: Annotated[
        int,
        Field(
            ge=1,
            le=50000,
            description=(
                "Search radius in meters around `coordinates`. Ignored when "
                "only `area_name` is given (free-text searches have no radius "
                "concept). Default 1500m ≈ a 15-minute walk."
            ),
        ),
    ] = 1500,
    max_results: Annotated[
        int,
        Field(
            ge=1,
            le=20,
            description="Maximum places to return. Google caps the response at 20.",
        ),
    ] = 10,
) -> list[dict[str, Any]]:
    """Find places matching a free-text query, near a coordinate or in a named area.

    Use this for any "what's around here?" / "are there good X near Y?" /
    "best Z in W" question. Returns a ranked list of real places with
    addresses, ratings, price tier, and Google Maps links — the calling
    model formats that for the user; the tool itself is deterministic.

    Trigger phrases that should call this tool:
      "what's around <X>?", "find me <category> near <Y>",
      "best <category> in <area>", "any good <thing> nearby?",
      "where's the closest <thing>?", "recommend a <thing> in <area>"
    Reach for this tool even when the area is famous — Google's listings,
    hours, ratings, and price tiers change in ways prior knowledge can't track.

    Anti-patterns (when NOT to use this tool):
      - "Tell me about <area>" / "What's <area> like?" — these invite a
        general description, not a place lookup. Either reframe as a
        place-finding question or answer from general knowledge.
      - Historical / trivia questions ("Who founded X?") — no live-data need.

    Exactly one geographic anchor must be provided:
      - `coordinates` (a {lat, lng} object) — for a precise point you already
        know. Pair with `radius_m` to scope the search circle.
      - `area_name` (free-text string like "Soho, Manhattan") — when the user
        named a place but no coordinates are available.
    Passing neither raises ValueError; passing both also raises ValueError.

    Each returned place contains:
      name, address, lat, lng, rating, user_rating_count, price_level,
      types (Google's place-type taxonomy, e.g. ["coffee_shop", "cafe"]),
      weekday_hours (array of formatted strings like "Monday: 8:00 AM – 4:00 PM"),
      reviews (array of review text strings, up to 5 most-relevant per place),
      phone_number (international format, e.g. "+1 201-993-9028"),
      place_id, maps_url

    Notes:
      - Results are *biased* to the supplied area, not strictly clipped —
        Google may surface adjacent places if they match the query well.
      - Many fields can be None or empty: places Google hasn't classified
        won't have rating/price_level; many places have no reviews or
        listed phone number. Never assume a value is present.
      - Always uses Google's Places (New) `searchText` endpoint. No
        Geocoding API call is made.
    """
    if coordinates is None and not area_name:
        raise ValueError("Provide either `coordinates` or `area_name`.")
    if coordinates is not None and area_name:
        raise ValueError(
            "Provide `coordinates` OR `area_name`, not both — they conflict."
        )

    if coordinates is not None:
        text_query = query
        location_bias = {
            "circle": {
                "center": {
                    "latitude": coordinates.lat,
                    "longitude": coordinates.lng,
                },
                "radius": float(radius_m),
            }
        }
    else:
        text_query = f"{query} in {area_name}"
        location_bias = None

    try:
        raw_places = await search_places_by_text(
            api_key=API_KEY,
            text_query=text_query,
            location_bias=location_bias,
            max_results=max_results,
        )
    except GoogleMapsError as exc:
        raise RuntimeError(str(exc)) from exc

    results: list[dict[str, Any]] = []
    for p in raw_places:
        loc = p.get("location") or {}
        display = p.get("displayName") or {}
        hours = (p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
        # Google returns review objects with text/rating/author/timestamp.
        # Flatten to plain text strings to mirror the built-in places tool's shape.
        reviews = [
            (r.get("text") or {}).get("text")
            for r in (p.get("reviews") or [])
            if (r.get("text") or {}).get("text")
        ]
        results.append(
            {
                "name": display.get("text"),
                "address": p.get("formattedAddress"),
                "lat": loc.get("latitude"),
                "lng": loc.get("longitude"),
                "rating": p.get("rating"),
                "user_rating_count": p.get("userRatingCount"),
                "price_level": p.get("priceLevel"),
                "types": p.get("types") or [],
                "weekday_hours": hours,
                "reviews": reviews,
                "phone_number": p.get("internationalPhoneNumber"),
                "place_id": p.get("id"),
                "maps_url": p.get("googleMapsUri"),
            }
        )
    return results


async def get_route(
    origin: Annotated[
        str | LatLng,
        Field(
            description=(
                "Where the trip starts. Either a free-text address/landmark "
                "string ('Times Square, New York') or a {lat, lng} object. "
                "Strings are resolved by Google; coordinates are used directly."
            )
        ),
    ],
    destination: Annotated[
        str | LatLng,
        Field(
            description=(
                "Where the trip ends. Same format options as `origin`."
            )
        ),
    ],
    travel_mode: Annotated[
        Literal["WALK", "TRANSIT"],
        Field(
            description=(
                "How the user is travelling. v1 supports 'WALK' (on foot) "
                "and 'TRANSIT' (public transit: bus, subway, train, ferry). "
                "DRIVE and BICYCLE are not supported yet."
            )
        ),
    ],
    arrival_time: Annotated[
        str | None,
        Field(
            description=(
                "Target arrival time as ISO8601. Prefer including a timezone, "
                "e.g. '2026-04-27T18:00:00Z' (UTC) or "
                "'2026-04-27T14:00:00-04:00' (Eastern). Naive timestamps "
                "without a timezone are interpreted as UTC. Mutually "
                "exclusive with `departure_time`."
            ),
        ),
    ] = None,
    departure_time: Annotated[
        str | None,
        Field(
            description=(
                "Departure time as ISO8601. Same format rules as "
                "`arrival_time`. Mutually exclusive with `arrival_time`. "
                "Omit both to get a 'leave now' route."
            ),
        ),
    ] = None,
    transit_preferences: Annotated[
        Literal["FEWER_TRANSFERS", "LESS_WALKING"] | None,
        Field(
            description=(
                "Optimization bias for TRANSIT routes. 'FEWER_TRANSFERS' "
                "favors routes with fewer connections (simpler, sometimes "
                "slower). 'LESS_WALKING' favors routes that minimize "
                "walking distance between stops. Pass None to fall back to "
                "Google's default (which optimizes purely for total travel "
                "time and often returns multi-leg routes). Ignored when "
                "travel_mode is WALK. Defaults to 'FEWER_TRANSFERS' to bias "
                "toward simpler routes — override if the user explicitly "
                "wants the fastest option regardless of transfers."
            ),
        ),
    ] = "FEWER_TRANSFERS",
) -> dict[str, Any]:
    """Compute a route between two points and return distance/timing/steps.

    Use this for "how do I get to X?" / "when do I need to leave to be at Y by Z?" /
    "how long does it take to walk from A to B?" questions.

    Trigger phrases that should call this tool:
      "how do I get from <A> to <B>?", "directions to <X>",
      "how long to walk to <Y>?", "how long does the subway to <Z> take?",
      "what time should I leave to be at <X> by <T>?",
      "what's the best route from <A> to <B>?",
      "is there a faster way to <X>?"
    Reach for this tool even for routes the model might already "know" —
    transit schedules and traffic conditions are not in training data.

    Anti-patterns (when NOT to use this tool):
      - "How far is <X> from <Y>?" framed as trivia (great-circle distance,
        not a route). If the user wants a walkable/driveable distance, use
        this tool; if they want as-the-crow-flies, answer from general knowledge.
      - "What's the address of <X>?" — that's `search_nearby_places` territory.

    Time anchoring (mutually exclusive — provide at most one):
      - `arrival_time`: server returns a derived `departure_time` such that
        the user lands by that moment, accounting for traffic.
      - `departure_time`: server returns a derived `arrival_time` based on
        the route's traffic-aware duration.
      - Neither: "leave now" — `departure_time` is set to current UTC and
        `arrival_time` is computed from the route duration.
    Both supplied simultaneously raises ValueError.

    Returned dict:
      distance_m            total route distance, integer meters
      duration_s            duration ignoring traffic (transit-schedule time
                            for TRANSIT), integer seconds
      duration_in_traffic_s duration with live traffic factored in, seconds.
                            For WALK this typically equals duration_s.
      departure_time        ISO8601 with 'Z' suffix (UTC)
      arrival_time          ISO8601 with 'Z' suffix (UTC)
      polyline              encoded polyline of the full route (Google's
                            standard polyline format)
      steps[]               per-leg-step list; each entry has:
                              instruction (text, e.g. 'Turn left onto 5th Ave')
                              maneuver    (enum, e.g. 'TURN_LEFT')
                              distance_m
                              duration_s
                              polyline
    """
    if arrival_time and departure_time:
        raise ValueError("Provide at most one of `arrival_time` or `departure_time`.")

    arrival_time = _normalize_timestamp(arrival_time)
    departure_time = _normalize_timestamp(departure_time)

    try:
        route = await compute_route(
            api_key=API_KEY,
            origin=_waypoint_from(origin),
            destination=_waypoint_from(destination),
            travel_mode=travel_mode,
            arrival_time=arrival_time,
            departure_time=departure_time,
            transit_routing_preference=transit_preferences,
        )
    except GoogleMapsError as exc:
        raise RuntimeError(str(exc)) from exc

    duration_in_traffic_s = _parse_duration_seconds(route.get("duration"))
    duration_s = (
        _parse_duration_seconds(route.get("staticDuration")) or duration_in_traffic_s
    )

    # The Routes API doesn't echo departure/arrival times back, so derive the
    # missing side from the duration we got.
    dep_iso: str | None = departure_time
    arr_iso: str | None = arrival_time
    if duration_in_traffic_s is not None:
        if departure_time and not arrival_time:
            dep_dt = datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
            arr_iso = (dep_dt + timedelta(seconds=duration_in_traffic_s)).isoformat()
        elif arrival_time and not departure_time:
            arr_dt = datetime.fromisoformat(arrival_time.replace("Z", "+00:00"))
            dep_iso = (arr_dt - timedelta(seconds=duration_in_traffic_s)).isoformat()
        elif not arrival_time and not departure_time:
            now = datetime.now(tz=timezone.utc)
            dep_iso = now.isoformat()
            arr_iso = (now + timedelta(seconds=duration_in_traffic_s)).isoformat()

    steps: list[dict[str, Any]] = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            nav = step.get("navigationInstruction") or {}
            poly = step.get("polyline") or {}
            steps.append(
                {
                    "instruction": nav.get("instructions"),
                    "maneuver": nav.get("maneuver"),
                    "distance_m": step.get("distanceMeters"),
                    "duration_s": _parse_duration_seconds(step.get("staticDuration")),
                    "polyline": poly.get("encodedPolyline"),
                }
            )

    return {
        "distance_m": route.get("distanceMeters"),
        "duration_s": duration_s,
        "duration_in_traffic_s": duration_in_traffic_s,
        "departure_time": dep_iso,
        "arrival_time": arr_iso,
        "polyline": (route.get("polyline") or {}).get("encodedPolyline"),
        "steps": steps,
    }


mcp.tool(search_nearby_places)
mcp.tool(get_route)


def main() -> None:
    if "--stdio" in sys.argv:
        mcp.run()  # stdio transport (default for fastmcp.run with no args)
        return

    port = int(os.environ.get("PORT", "8000"))
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
    )


if __name__ == "__main__":
    main()
