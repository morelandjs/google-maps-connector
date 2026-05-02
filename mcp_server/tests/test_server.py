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
                        "reviews": [
                            {"text": {"text": "Great coffee!"}, "rating": 5},
                            {"text": {"text": "Cozy spot."}, "rating": 4},
                            # A review with no text body should be filtered out.
                            {"rating": 3},
                        ],
                        "internationalPhoneNumber": "+1 555-0100",
                    }
                ]
            },
        )
    )

    out = await server.search_nearby_places(
        query="coffee",
        coordinates=server.LatLng(lat=40.7, lng=-74.0),
        radius_m=500,
        max_results=5,
    )
    assert out == [
        {
            "name": "X",
            "address": "addr",
            "lat": 1.0,
            "lng": 2.0,
            "rating": 4.0,
            "user_rating_count": 10,
            "price_level": "PRICE_LEVEL_INEXPENSIVE",
            "types": ["coffee_shop", "cafe"],
            "weekday_hours": [
                "Monday: 8:00 AM – 4:00 PM",
                "Tuesday: 8:00 AM – 4:00 PM",
            ],
            "reviews": ["Great coffee!", "Cozy spot."],
            "phone_number": "+1 555-0100",
            "place_id": "x",
            "maps_url": "https://maps.example/x",
        }
    ]


@respx.mock
async def test_search_nearby_places_handles_missing_optional_fields():
    """Google omits hours / reviews / phone for many places — must default to empty / None."""
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
        query="x", coordinates=server.LatLng(lat=40.7, lng=-74.0)
    )
    assert out[0]["types"] == []
    assert out[0]["weekday_hours"] == []
    assert out[0]["reviews"] == []
    assert out[0]["phone_number"] is None


@respx.mock
async def test_search_nearby_places_with_area_name_appends_to_query():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(200, json={"places": []})
    )
    await server.search_nearby_places(query="bookstores", area_name="Soho")

    import json as _json

    body = _json.loads(respx.calls.last.request.content)
    assert body["textQuery"] == "bookstores in Soho"
    assert "locationBias" not in body


async def test_search_nearby_places_requires_coordinates_or_area():
    with pytest.raises(ValueError, match="Provide either"):
        await server.search_nearby_places(query="anything")


async def test_search_nearby_places_rejects_both_coordinates_and_area():
    with pytest.raises(ValueError, match="not both"):
        await server.search_nearby_places(
            query="anything",
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
        travel_mode="WALK",
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
