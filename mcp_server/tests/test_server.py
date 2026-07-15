import json

import httpx
import pytest
import respx

import server
from google_maps import PLACES_SEARCH_TEXT_URL, ROUTES_COMPUTE_URL


def test_oauth_provider_disabled_without_credentials(monkeypatch):
    """No creds → no auth (unauth'd dev / hermetic test mode)."""
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    assert server._build_auth_provider() is None


def test_oauth_provider_disabled_with_partial_credentials(monkeypatch):
    """Half-configured creds must not silently authenticate — fail closed."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    assert server._build_auth_provider() is None


def test_oauth_provider_built_when_credentials_present(monkeypatch):
    """Creds set, no allowlist → standard GoogleProvider (Phase 2 posture)."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "GOCSPX-test")
    monkeypatch.delenv("GOOGLE_OAUTH_ALLOWED_EMAILS", raising=False)
    from fastmcp.server.auth.providers.google import GoogleProvider

    provider = server._build_auth_provider()
    assert isinstance(provider, GoogleProvider)


def test_oauth_provider_uses_allowlist_when_emails_configured(monkeypatch):
    """Creds + allowlist set → OAuthProxy with our custom verifier (Phase 3 posture)."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "GOCSPX-test")
    monkeypatch.setenv("GOOGLE_OAUTH_ALLOWED_EMAILS", "user@example.com")
    from fastmcp.server.auth.oauth_proxy import OAuthProxy

    provider = server._build_auth_provider()
    assert isinstance(provider, OAuthProxy)
    # The verifier carries the (lowercased) email allowlist.
    assert "user@example.com" in provider._token_validator._allowed_emails


async def test_allowlist_verifier_rejects_non_allowlisted_email(monkeypatch):
    """A token that's valid against Google but for a non-allowlisted user is rejected."""
    verifier = server.AllowlistedGoogleTokenVerifier(
        allowed_emails=["user@example.com"]
    )

    # Stub the parent verify_token: pretend Google said "valid token, email=stranger@x.com".
    # Patching at class level → the descriptor is bound, so `self` is passed.
    async def fake_super_verify(self, token):
        from fastmcp.server.auth.providers.google import AccessToken

        return AccessToken(
            token=token,
            client_id="some-sub",
            scopes=["openid", verifier.EMAIL_SCOPE],
            expires_at=None,
            claims={"email": "stranger@example.com"},
        )

    monkeypatch.setattr(
        server.GoogleTokenVerifier, "verify_token", fake_super_verify
    )

    assert await verifier.verify_token("any-token") is None


async def test_allowlist_verifier_accepts_allowlisted_email(monkeypatch):
    """A valid token whose email IS on the allowlist passes through unchanged."""
    verifier = server.AllowlistedGoogleTokenVerifier(
        allowed_emails=["user@example.com"]
    )

    async def fake_super_verify(self, token):
        from fastmcp.server.auth.providers.google import AccessToken

        return AccessToken(
            token=token,
            client_id="some-sub",
            scopes=["openid", verifier.EMAIL_SCOPE],
            expires_at=None,
            claims={"email": "User@Example.com"},  # Mixed case on purpose.
        )

    monkeypatch.setattr(
        server.GoogleTokenVerifier, "verify_token", fake_super_verify
    )

    result = await verifier.verify_token("any-token")
    assert result is not None
    assert result.claims["email"] == "User@Example.com"


async def test_allowlist_verifier_passes_through_none(monkeypatch):
    """When the parent verifier rejects (returns None), we don't override."""
    verifier = server.AllowlistedGoogleTokenVerifier(allowed_emails=["x@y.com"])

    async def fake_super_verify(self, token):
        return None

    monkeypatch.setattr(
        server.GoogleTokenVerifier, "verify_token", fake_super_verify
    )

    assert await verifier.verify_token("invalid") is None


def test_normalize_timestamp():
    # None passes through.
    assert server._normalize_timestamp(None) is None
    # Already-canonical UTC stays put.
    assert server._normalize_timestamp("2026-04-27T18:00:00Z") == "2026-04-27T18:00:00Z"
    # Naive timestamps are treated as UTC, gain a 'Z'.
    assert server._normalize_timestamp("2026-04-27T18:00:00") == "2026-04-27T18:00:00Z"
    # Numeric offsets are converted to UTC.
    assert (
        server._normalize_timestamp("2026-04-27T14:00:00-04:00")
        == "2026-04-27T18:00:00Z"
    )
    # Garbage raises a ValueError mentioning the bad value.
    with pytest.raises(ValueError, match="not a date"):
        server._normalize_timestamp("not a date")


def test_parse_duration_seconds():
    assert server._parse_duration_seconds("4137s") == 4137
    assert server._parse_duration_seconds("4137.6s") == 4137
    assert server._parse_duration_seconds(None) is None
    assert server._parse_duration_seconds("garbage") is None


def test_waypoint_from_address_string():
    assert server._waypoint_from("1 Infinite Loop") == {"address": "1 Infinite Loop"}


def test_waypoint_from_latlng_model():
    wp = server._waypoint_from(server.LatLng(lat=37.4, lng=-122.1))
    assert wp == {"location": {"latLng": {"latitude": 37.4, "longitude": -122.1}}}


@respx.mock
async def test_search_nearby_places_with_coordinates_uses_bias():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "x",
                        "displayName": {"text": "X"},
                        "formattedAddress": "addr",
                        "location": {"latitude": 1.0, "longitude": 2.0},
                        "rating": 4.0,
                        "userRatingCount": 10,
                        "priceLevel": "PRICE_LEVEL_INEXPENSIVE",
                        "googleMapsUri": "https://maps.example/x",
                        "types": ["coffee_shop", "cafe"],
                        "regularOpeningHours": {
                            "weekdayDescriptions": [
                                "Monday: 8:00 AM – 4:00 PM",
                                "Tuesday: 8:00 AM – 4:00 PM",
                            ]
                        },
                        # No longer in the field mask; the mapper must ignore
                        # extra fields Google might still send.
                        "reviews": [
                            {"text": {"text": "Great coffee!"}, "rating": 5},
                        ],
                        "generativeSummary": {
                            "overview": {
                                "text": "A cozy neighborhood espresso bar.",
                                "languageCode": "en",
                            }
                        },
                        "reviewSummary": {
                            "text": {
                                "text": "Reviewers praise the flat whites.",
                                "languageCode": "en",
                            }
                        },
                        "internationalPhoneNumber": "+1 555-0100",
                    }
                ]
            },
        )
    )

    out = await server.search_nearby_places(
        queries=["coffee"],
        coordinates=server.LatLng(lat=40.7, lng=-74.0),
        radius_m=500,
        max_results=5,
    )
    assert isinstance(out, str)
    assert "## 1. X" in out
    assert "- **Address:** addr" in out
    assert "- **Coordinates:** 1.00000, 2.00000" in out
    assert "- **Rating:** 4.0 (10 ratings)" in out
    assert "- **Types:** coffee_shop, cafe" in out
    assert "- **Hours:** Monday: 8:00 AM – 4:00 PM; Tuesday: 8:00 AM – 4:00 PM" in out
    assert "- **Summary:** A cozy neighborhood espresso bar." in out
    assert "- **Reviews say:** Reviewers praise the flat whites." in out
    assert "- **Phone:** +1 555-0100" in out
    # The Map line is the official Maps-URLs deep link (opens the native
    # app), built from name + place_id — not Google's ?cid= share URL.
    assert (
        "- **Map:** https://www.google.com/maps/search/?api=1"
        "&query=X&query_place_id=x" in out
    )
    assert "- **Place ID:** x" in out
    # No websiteUri in the mock → the Website line must be absent entirely.
    assert "- **Website:**" not in out
    # Dropped-from-mask fields Google might still send must not leak through.
    assert "PRICE_LEVEL" not in out and "Great coffee!" not in out


@respx.mock
async def test_multi_query_search_merges_and_dedupes():
    """'fun date night ideas' decomposed into categories: places surfaced by
    more than one query appear once, with a Matched line as the relevance
    signal; each query runs as its own Places call."""

    def respond(request):
        body = json.loads(request.content)
        if "wine bars" in body["textQuery"]:
            places = [
                {"id": "a", "displayName": {"text": "Vine Bar"}},
                {"id": "b", "displayName": {"text": "Jazz & Wine"}},
            ]
        else:  # live music venues
            places = [
                {"id": "b", "displayName": {"text": "Jazz & Wine"}},
                {"id": "c", "displayName": {"text": "The Hall"}},
            ]
        return httpx.Response(200, json={"places": places})

    mock = respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=respond)

    out = await server.search_nearby_places(
        queries=["wine bars", "live music venues"],
        area_name="Williamsburg, Brooklyn",
    )

    assert mock.call_count == 3  # 1 area resolution + one Places call per query
    # Three unique places; the shared one appears exactly once.
    assert out.count("Jazz & Wine") == 1
    assert "## 1. Vine Bar" in out and "## 3. The Hall" in out
    assert "- **Matched:** wine bars, live music venues" in out  # the dupe
    assert "- **Matched:** wine bars\n" in out  # single-query matches too


@respx.mock
async def test_social_website_is_flagged_unscrapable():
    """Google sometimes lists linktr.ee/Instagram as a venue's website; the
    markdown must warn the agent not to send it to get_events."""
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "a",
                        "displayName": {"text": "Run Club"},
                        "websiteUri": "https://linktr.ee/runclub",
                    }
                ]
            },
        )
    )
    out = await server.search_nearby_places(queries=["run clubs"], area_name="UWS")
    assert (
        "- **Website:** https://linktr.ee/runclub "
        "(social/link-tree — get_events cannot scrape this)" in out
    )


@respx.mock
async def test_single_query_search_omits_matched_line():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200, json={"places": [{"id": "a", "displayName": {"text": "A"}}]}
        )
    )
    out = await server.search_nearby_places(queries=["bars"], area_name="Soho")
    assert "- **Matched:**" not in out


@respx.mock
async def test_search_nearby_places_handles_missing_optional_fields():
    """Google omits hours / phone for many places — must default to empty / None."""
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "y",
                        "displayName": {"text": "Y"},
                        "formattedAddress": "addr",
                        "location": {"latitude": 1.0, "longitude": 2.0},
                    }
                ]
            },
        )
    )

    out = await server.search_nearby_places(
        queries=["x"], coordinates=server.LatLng(lat=40.7, lng=-74.0)
    )
    assert "## 1. Y" in out
    for absent in ("Types", "Hours", "Phone", "Summary", "Reviews say", "Rating"):
        assert f"- **{absent}:**" not in out


_SOHO_VIEWPORT = {
    "low": {"latitude": 40.71, "longitude": -74.01},
    "high": {"latitude": 40.73, "longitude": -73.99},
}


def _area_aware_responder(area_name, viewport, places):
    """searchText mock: the area-resolution call gets a viewport, category
    queries get `places`."""

    def respond(request):
        import json as _json

        body = _json.loads(request.content)
        if body["textQuery"] == area_name:
            assert body["maxResultCount"] == 1  # resolution asks for one hit
            return httpx.Response(
                200,
                json={
                    "places": [
                        {
                            "id": "the-area",
                            "location": {"latitude": 40.72, "longitude": -74.0},
                            "viewport": viewport,
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"places": places})

    return respond


@respx.mock
async def test_search_nearby_places_with_area_name_appends_to_query():
    """Hybrid anchoring: the area resolves to a viewport once, then every
    query carries BOTH the composed text anchor and a rectangle bias."""
    mock = respx.post(PLACES_SEARCH_TEXT_URL).mock(
        side_effect=_area_aware_responder("Soho", _SOHO_VIEWPORT, [])
    )
    await server.search_nearby_places(queries=["bookstores"], area_name="Soho")

    import json as _json

    assert mock.call_count == 2  # 1 area resolution + 1 query
    body = _json.loads(mock.calls.last.request.content)
    assert body["textQuery"] == "bookstores in Soho"
    # 0.02° spans exceed the padding minimum, so the viewport passes through.
    assert body["locationBias"]["rectangle"] == _SOHO_VIEWPORT


@respx.mock
async def test_area_resolution_failure_degrades_to_unbiased_search():
    """A name Google can't resolve must not break the search: same composed
    text query, just no locationBias."""

    def respond(request):
        import json as _json

        body = _json.loads(request.content)
        if body["textQuery"] == "Nowhereville":
            return httpx.Response(200, json={})  # resolves to nothing
        return httpx.Response(
            200,
            json={"places": [{"id": "z", "displayName": {"text": "Z"}}]},
        )

    mock = respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=respond)
    out = await server.search_nearby_places(
        queries=["cafes"], area_name="Nowhereville"
    )

    import json as _json

    assert "## 1. Z" in out
    body = _json.loads(mock.calls.last.request.content)
    assert body["textQuery"] == "cafes in Nowhereville"
    assert "locationBias" not in body


@respx.mock
async def test_area_viewport_resolved_once_per_area_and_cached():
    """N queries share one resolution call, and a second tool call for the
    same area skips resolution entirely (module-level cache)."""
    mock = respx.post(PLACES_SEARCH_TEXT_URL).mock(
        side_effect=_area_aware_responder("Red Hook, Brooklyn", _SOHO_VIEWPORT, [])
    )

    await server.search_nearby_places(
        queries=["bars", "bakeries"], area_name="Red Hook, Brooklyn"
    )
    assert mock.call_count == 3  # 1 resolution + 2 queries

    await server.search_nearby_places(
        queries=["cafes"], area_name="Red Hook, Brooklyn"
    )
    assert mock.call_count == 4  # +1 query only — viewport came from cache


def test_presentation_note_trails_results_but_not_empty_response():
    """The formatting hint rides at the END of real results (last thing the
    client LLM reads before writing) and is omitted when there's nothing to
    present."""
    place = {
        "name": "X",
        "address": "addr",
        "lat": None,
        "lng": None,
        "rating": 4.8,
        "user_rating_count": 194,
        "types": [],
        "weekday_hours": [],
        "generative_summary": "",
        "review_summary": "",
        "phone_number": "",
        "website": "",
        "maps_url": "",
        "place_id": "x",
    }
    out = server._format_places_markdown([place])
    assert out.rstrip().endswith(server._PRESENTATION_NOTE.splitlines()[-1])
    # The note prescribes the two-line pattern with angle-bracket
    # placeholders (nothing literal enough to be parroted):
    #   [<place name>](<Map link>), <rating>★ (<review count>)
    #   <one-line rationale for recommending this place>
    assert "[<place name>](<Map link>)" in server._PRESENTATION_NOTE
    assert "<rating>★ (<review count>)" in server._PRESENTATION_NOTE
    assert "rationale" in server._PRESENTATION_NOTE.lower()

    empty = server._format_places_markdown([])
    assert "Presentation note" not in empty


def test_pad_viewport_grows_venue_sized_boxes_to_neighborhood_scale():
    tiny = {
        "low": {"latitude": 40.0, "longitude": -74.0},
        "high": {"latitude": 40.001, "longitude": -73.999},
    }
    padded = server._pad_viewport(tiny)
    assert padded["high"]["latitude"] - padded["low"]["latitude"] == pytest.approx(
        0.018
    )
    assert padded["high"]["longitude"] - padded["low"]["longitude"] == pytest.approx(
        0.018
    )

    neighborhood = {
        "low": {"latitude": 40.0, "longitude": -74.0},
        "high": {"latitude": 40.05, "longitude": -73.95},
    }
    assert server._pad_viewport(neighborhood) == neighborhood


async def test_search_nearby_places_requires_coordinates_or_area():
    with pytest.raises(ValueError, match="Provide either"):
        await server.search_nearby_places(queries=["anything"])


async def test_search_nearby_places_rejects_both_coordinates_and_area():
    with pytest.raises(ValueError, match="not both"):
        await server.search_nearby_places(
            queries=["anything"],
            coordinates=server.LatLng(lat=40.7, lng=-74.0),
            area_name="Soho",
        )


@respx.mock
async def test_get_route_derives_departure_from_arrival():
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distanceMeters": 5000,
                        "duration": "1800s",
                        "staticDuration": "1800s",
                        "polyline": {"encodedPolyline": "P"},
                        "legs": [
                            {
                                "steps": [
                                    {
                                        "distanceMeters": 5000,
                                        "staticDuration": "1800s",
                                        "navigationInstruction": {
                                            "instructions": "Walk",
                                            "maneuver": "DEPART",
                                        },
                                        "polyline": {"encodedPolyline": "P"},
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
        )
    )

    # Pass a naive timestamp on purpose — server should normalize it to UTC
    # before sending to Google and before deriving departure_time.
    out = await server.get_route(
        origin="A",
        destination="B",
        travel_mode="TRANSIT",  # arrival_time is TRANSIT-only
        arrival_time="2026-04-26T18:00:00",
    )

    # The outbound request body should carry the canonical 'Z'-form.
    import json as _json

    body = _json.loads(respx.calls.last.request.content)
    assert body["arrivalTime"] == "2026-04-26T18:00:00Z"

    assert out["distance_m"] == 5000
    assert out["duration_in_traffic_s"] == 1800
    # Arrival 18:00Z minus 1800s = 17:30Z
    assert out["departure_time"].startswith("2026-04-26T17:30:00")
    assert out["arrival_time"] == "2026-04-26T18:00:00Z"
    assert out["polyline"] == "P"
    assert out["steps"][0]["instruction"] == "Walk"


@respx.mock
async def test_get_route_transit_default_sends_fewer_transfers():
    """Default for TRANSIT mode is to bias toward fewer connections."""
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distanceMeters": 100,
                        "duration": "60s",
                        "staticDuration": "60s",
                        "polyline": {"encodedPolyline": "x"},
                        "legs": [{"steps": []}],
                    }
                ]
            },
        )
    )
    await server.get_route(origin="A", destination="B", travel_mode="TRANSIT")

    import json as _json

    body = _json.loads(respx.calls.last.request.content)
    assert body["transitPreferences"] == {"routingPreference": "FEWER_TRANSFERS"}


@respx.mock
async def test_get_route_walk_mode_omits_transit_preferences():
    """transitPreferences must not be sent for WALK — Google ignores or rejects it."""
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distanceMeters": 100,
                        "duration": "60s",
                        "staticDuration": "60s",
                        "polyline": {"encodedPolyline": "x"},
                        "legs": [{"steps": []}],
                    }
                ]
            },
        )
    )
    # Even with the (default) preference set, WALK must skip the field.
    await server.get_route(origin="A", destination="B", travel_mode="WALK")

    import json as _json

    body = _json.loads(respx.calls.last.request.content)
    assert "transitPreferences" not in body


@respx.mock
async def test_get_route_transit_preferences_can_be_disabled():
    """Passing None opts out and lets Google use its default (time-only) ranking."""
    respx.post(ROUTES_COMPUTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distanceMeters": 100,
                        "duration": "60s",
                        "staticDuration": "60s",
                        "polyline": {"encodedPolyline": "x"},
                        "legs": [{"steps": []}],
                    }
                ]
            },
        )
    )
    await server.get_route(
        origin="A",
        destination="B",
        travel_mode="TRANSIT",
        transit_preferences=None,
    )

    import json as _json

    body = _json.loads(respx.calls.last.request.content)
    assert "transitPreferences" not in body


async def test_get_route_rejects_both_times():
    with pytest.raises(ValueError):
        await server.get_route(
            origin="A",
            destination="B",
            travel_mode="WALK",
            arrival_time="2026-04-26T18:00:00Z",
            departure_time="2026-04-26T17:00:00Z",
        )
