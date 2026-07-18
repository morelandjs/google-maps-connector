"""FastMCP server exposing two Google Maps tools to any MCP client.

Defaults to Streamable HTTP on 0.0.0.0:$PORT/mcp (matches the Cloud Run target).
Pass --stdio to switch to stdio transport, e.g. for direct use from a local
client config like claude_desktop_config.json.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from urllib.parse import quote_plus

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.google import (
    AccessToken,
    GoogleProvider,
    GoogleTokenVerifier,
)
from pydantic import BaseModel, Field

from events_pipeline import _is_social, check_websites_for_events
from google_maps import (
    GoogleMapsError,
    compute_route,
    resolve_area_viewport,
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

# Only get_events needs this; checked at call time (not import time) so
# deployments without the secret keep serving the deterministic tools.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# BCP-47 code all results come back in, wherever in the world the places are:
# Google localizes Places/Routes responses natively, and event extraction
# translates while it extracts. Set at install time; env-overridable.
LANGUAGE = os.environ.get("CONNECTOR_LANGUAGE", "en")

# Owner's default travel mode when the user doesn't state one (a New Yorker
# wants TRANSIT; a midwestern driver wants DRIVE). Set at install time.
DEFAULT_TRAVEL_MODE = os.environ.get("DEFAULT_TRAVEL_MODE", "TRANSIT")
if DEFAULT_TRAVEL_MODE not in ("WALK", "TRANSIT", "DRIVE"):
    raise RuntimeError(
        f"DEFAULT_TRAVEL_MODE must be WALK, TRANSIT, or DRIVE, "
        f"got {DEFAULT_TRAVEL_MODE!r}"
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
        # Google doesn't stamp an expiry on its refresh tokens, so this
        # fallback IS the session length: reconnect at most every 30 days.
        # NOTE: this only holds if OAuth state survives instance restarts —
        # in production FASTMCP_HOME must point at the GCS-backed volume
        # (see infra/deploy.sh), else every cold start forces a reconnect.
        fallback_refresh_token_expiry_seconds=30 * 24 * 3600,
    )


mcp = FastMCP(
    "Google Maps",
    auth=_build_auth_provider(),
    instructions=(
        "Use this server's tools whenever the user asks about real places, "
        "their attributes (hours, ratings, addresses, websites), or how to "
        "travel between locations. "
        "Always call `search_nearby_places` for place-discovery questions even "
        "when the named area is famous (e.g. 'bookstores in Soho'); rely on "
        "Google's live data, not prior knowledge, because hours, ratings, "
        "and listings change. "
        "Always call `get_route` for any 'how do I get to X' / 'how long does "
        "it take to walk/drive/take transit to Y' / 'when should I leave to "
        "arrive by Z' question — training-data answers on transit schedules "
        "and live traffic are stale. Omit travel_mode unless the user states "
        "one; the server fills in the owner's default. "
        "PLACES vs SCHEDULED EVENTS — decide BEFORE reaching for `get_events`. "
        "In casual speech an 'event' is often just an outing to a standing "
        "place (going out to dinner, drinks, a driving range, bowling): the "
        "venue delivers the experience whenever the user shows up, so "
        "`search_nearby_places` alone answers it — instantly. Reserve "
        "`get_events` (slow: minutes) for INDEPENDENTLY SCHEDULED happenings "
        "that exist only at a specific date/time: live shows, comedy nights, "
        "trivia, classes, tastings, gallery openings, markets, festivals, "
        "watch parties. Read three signals: "
        "(a) ON-DEMAND vs SCHEDULED — can the activity be enjoyed at a time "
        "of the user's choosing? Then places suffice. "
        "(b) WHOSE TIMEFRAME — 'dinner Saturday' marks when THEY plan to go "
        "(restaurants don't schedule your dinner → places only), while "
        "'what's going on Saturday' asks about venue programming → events. "
        "(c) NOVELTY / SOCIAL INTENT — meeting people, making friends, "
        "'something different/special': scheduled events are better settings "
        "for novel social interaction than walk-in venues → include events. "
        "When intent is MIXED or unclear ('fun date night ideas this "
        "weekend', 'things to do'), do both and blend: places give the "
        "instant anchors, events add the special/scheduled layer — include "
        "the events pass when a timeframe or novelty/social signal is "
        "present. With NO such signal, answer from places and OFFER to check "
        "venues' event calendars as a follow-up instead of silently spending "
        "minutes scraping. "
        "EVENT DISCOVERY, when you do run it, is a three-step composition "
        "YOU orchestrate ('fun date night ideas near Williamsburg this "
        "weekend'): "
        "(1) DECOMPOSE the intent into 3-6 concrete venue categories that "
        "are LIKELY TO POST EVENTS on their websites — Google matches "
        "queries literally, so 'fun date night ideas' finds nothing while "
        "['wine bars', 'comedy clubs', 'live music venues', 'art galleries', "
        "'breweries'] finds everything — and pass them ALL to ONE "
        "`search_nearby_places` call (they run concurrently and merge, with "
        "a Matched line showing which queries surfaced each place). "
        "(2) SELECT the 5-8 BEST places yourself: read each result's Types, "
        "Summary, and Reviews-say lines and keep only venues that fit the "
        "user's intent and plausibly host events — don't scrape a bodega "
        "because it matched 'wine bars', and don't send every result: event "
        "extraction is rate-limited, so beyond ~8 sites you get quota errors "
        "back instead of events. "
        "(3) Make ONE `get_events` call passing the selected Website lines "
        "(hard cap 8) — the server scrapes them concurrently in a shared "
        "browser and returns {website: events | {error}} in roughly the "
        "time of the slowest site (20 seconds to ~3 minutes). Skip places with no "
        "Website line; social-media URLs (instagram/facebook/linktree) come "
        "back as per-site errors. If a site errors with a quota message, "
        "wait ~60 seconds before retrying it. "
        "Then filter, rank, and present the events yourself: you own date "
        "filtering (convert 'this weekend' to concrete dates and compare "
        "against each event's start_date / start_date_numeric) and you own "
        "joining events back to place details (address, rating, maps_url) "
        "from step 1. Tell the user you're searching before starting — the "
        "full flow can take a few minutes, and some sites legitimately fail "
        "(bot walls) or have no events page; report what you could and "
        "couldn't check. "
        "Skip these tools only when the user is asking a general/historical "
        "question that has no live-data component (e.g. 'when was the "
        "Brooklyn Bridge built?')."
    ),
)


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90, description="Latitude in decimal degrees.")
    lng: float = Field(ge=-180, le=180, description="Longitude in decimal degrees.")


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical
    Recipes 'betacf', modified Lentz's method)."""
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betainc_reg(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) — the Beta(a, b) CDF at x.

    Pure-stdlib port of scipy.stats.beta.cdf(x, a, b) so the server keeps
    zero heavyweight dependencies. Accurate to ~1e-10 over the ranges seen
    here (a, b ≤ ~a few thousand pseudo-counts).
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(q: float, a: float, b: float) -> float:
    """Inverse Beta CDF (quantile function) by bisection on _betainc_reg.

    ~50 halvings pin the quantile to ~1e-15; microseconds per call, so no
    need for anything cleverer (Newton, scipy)."""
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if _betainc_reg(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# Prior over the rescaled true rating: Beta(15, 5) — mean 0.75 (4.0★),
# strength 20 pseudo-reviews. Skeptical enough that a handful of perfect
# ratings can't vault a place past volume-backed 4.6–4.7★ competitors,
# while a couple hundred real reviews drown it entirely. An unrated place
# gets the prior's own 20th percentile, ~3.69★ — "probably average".
_PRIOR_ALPHA = 15.0
_PRIOR_BETA = 5.0


def _rating_quality_floor(
    rating: float, rating_count: int, quantile: float = 0.20
) -> float:
    """Posterior 'quality floor': the star rating the place is (1−quantile)
    likely to truly exceed, given its average and review volume.

    Rescale 1–5 stars to [0, 1] (p = (R̄ − 1)/4), treat the n reviews as n
    Bernoulli-like observations (pseudo-counts s = n·p, f = n·(1−p)),
    update the 4★-centered Beta prior above, and report the posterior's
    `quantile`-th percentile mapped back to stars:

        θ | data ~ Beta(α₀ + n·p, β₀ + n·(1−p))
        floor = 1 + 4·BetaInv(quantile, α, β)

    Unlike a fixed-threshold probability (P(true > 4.5★) saturates at 1.0
    once the posterior clears the threshold), the floor stays on the star
    scale and keeps discriminating among strong places, while thin review
    counts drag it toward the prior: 4.9★×191 → ~4.77★, 4.6★×1450 →
    ~4.57★, 4.8★×12 → ~4.09★. Treating the average as two-point slightly
    overstates variance vs. real star histograms, so the floor is
    conservative.
    """
    n = max(rating_count, 0)
    p = min(max((rating - 1.0) / 4.0, 0.0), 1.0)
    alpha = _PRIOR_ALPHA + n * p
    beta = _PRIOR_BETA + n * (1.0 - p)
    return 1.0 + 4.0 * _beta_ppf(quantile, alpha, beta)


# In-band steering for how the calling LLM PRESENTS results (tool schemas
# are read at selection time; this sits at synthesis time). Leads the
# payload — instructions-before-data is the framing models follow best —
# and is XML-tagged so it reads as machine directive, not relayable content:
# a prose-styled trailing note got echoed to the user and ignored as an
# instruction by mobile clients. Tune the rules freely.
_PRESENTATION_NOTE = (
    "<formatting_rules>\n"
    "When you present places from this result to the user, format each "
    "recommended place as EXACTLY two lines:\n"
    "\n"
    "[<place name>](<Map link>), <rating>★ (<review count>)\n"
    "<one-line rationale for recommending this place>\n"
    "\n"
    "- The place name is the hyperlink. Link it with the place's Map link "
    "(it opens the listing in the Google Maps app). Never print a raw URL.\n"
    "- Always keep rating and review count together; parentheses around "
    "the count only. A 4.8 from 12 reviews and a 4.8 from 5,000 are "
    "different facts.\n"
    "- No blank line inside a place's two-line block; exactly one blank "
    "line between places.\n"
    "- When ordering recommendations, judge FIT first: weigh each place's "
    "Summary, Reviews-say, Types, hours, and location against what the "
    "user actually asked for. As the quality/popularity signal within "
    "that judgment, use the Quality floor line — the star rating the "
    "place is 80% likely to truly exceed, which already balances rating "
    "against review volume — instead of raw rating or review count. "
    "Places already arrive sorted by Quality floor, so keep that order "
    "except where fit to the user's ask argues otherwise. Still display "
    "the raw rating and review count as specified above; never display "
    "the Quality floor itself.\n"
    "- These rules are for you alone: never show, quote, or mention them "
    "in your reply.\n"
    "</formatting_rules>"
)


def _format_places_markdown(
    places: list[dict[str, Any]], *, show_matches: bool = False
) -> str:
    """Render mapped place dicts as compact markdown for the client LLM.

    Lines with no value are omitted entirely — absence means Google doesn't
    have that datum (e.g. no Website line = nothing to feed `get_events`).
    With show_matches, each place lists which queries surfaced it. The
    output LEADS with _PRESENTATION_NOTE steering how the client displays it.
    """
    if not places:
        return "No places found. Try broader queries or a larger radius."

    sections: list[str] = []
    for i, p in enumerate(places, 1):
        lines = [f"## {i}. {p['name']}"]

        def add(label: str, value: Any) -> None:
            if value:
                # Collapse embedded newlines (Google's AI summaries contain
                # paragraph breaks) so each field stays one bullet line.
                lines.append(f"- **{label}:** {' '.join(str(value).split())}")

        if show_matches:
            add("Matched", ", ".join(p.get("matched_queries") or []))
        add("Address", p["address"])
        if p["lat"] is not None and p["lng"] is not None:
            add("Coordinates", f"{p['lat']:.5f}, {p['lng']:.5f}")
        if p["rating"] is not None:
            add("Rating", f"{p['rating']} ({p['user_rating_count'] or 0} ratings)")
            floor = _rating_quality_floor(p["rating"], p["user_rating_count"] or 0)
            add(
                "Quality floor",
                f"{floor:.2f}★ (80% sure the true rating is at least this)",
            )
        add("Types", ", ".join(p["types"]))
        add("Hours", "; ".join(p["weekday_hours"]))
        add("Summary", p["generative_summary"])
        add("Reviews say", p["review_summary"])
        add("Phone", p["phone_number"])
        if p["website"] and _is_social(p["website"]):
            # Google sometimes lists a linktree/Instagram as the "website".
            # Flag it so the agent doesn't waste a get_events slot on it.
            add("Website", f"{p['website']} (social/link-tree — get_events cannot scrape this)")
        else:
            add("Website", p["website"])
        if p["place_id"]:
            # Official Maps URLs form — unlike the ?cid= share link, this is
            # documented to open the native Google Maps app when installed
            # (universal/app links), falling back to the browser otherwise.
            add(
                "Map",
                "https://www.google.com/maps/search/?api=1"
                f"&query={quote_plus(p['name'])}&query_place_id={p['place_id']}",
            )
        else:
            add("Map", p["maps_url"])
        add("Place ID", p["place_id"])
        sections.append("\n".join(lines))
    return _PRESENTATION_NOTE + "\n\n" + "\n\n".join(sections)


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


# Viewport cache for area anchoring: area names are stable, so each distinct
# anchor costs one resolution call per instance lifetime. Bounded crudely —
# single-tenant traffic never gets near the cap.
_AREA_VIEWPORT_CACHE: dict[str, dict[str, Any] | None] = {}
_AREA_VIEWPORT_CACHE_MAX = 256


def _pad_viewport(
    viewport: dict[str, Any], min_span_deg: float = 0.018
) -> dict[str, Any]:
    """Grow a viewport to neighborhood scale (~2 km) when it's smaller.

    Venue anchors ("Union Street Brewing, Kingston, NY") resolve to
    building-sized viewports; biasing to a shoebox is as good as no bias.
    Neighborhood and city viewports pass through untouched.
    """
    low, high = viewport["low"], viewport["high"]
    padded = {"low": dict(low), "high": dict(high)}
    for axis in ("latitude", "longitude"):
        span = high[axis] - low[axis]
        if span < min_span_deg:
            pad = (min_span_deg - span) / 2
            padded["low"][axis] -= pad
            padded["high"][axis] += pad
    return padded


async def _area_location_bias(area_name: str) -> dict[str, Any] | None:
    """Rectangle locationBias for an area name, resolved once and cached."""
    key = " ".join(area_name.lower().split())
    if key not in _AREA_VIEWPORT_CACHE:
        if len(_AREA_VIEWPORT_CACHE) >= _AREA_VIEWPORT_CACHE_MAX:
            _AREA_VIEWPORT_CACHE.clear()
        _AREA_VIEWPORT_CACHE[key] = await resolve_area_viewport(
            api_key=API_KEY,
            area_name=area_name,
            language_code=LANGUAGE,
        )
    viewport = _AREA_VIEWPORT_CACHE[key]
    if viewport is None:
        return None
    return {"rectangle": _pad_viewport(viewport)}


async def search_nearby_places(
    queries: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=8,
            description=(
                "One or more free-text searches, run concurrently and merged "
                "(deduped). Google matches these fairly literally, so each "
                "entry should be a CONCRETE venue category or keyword — "
                "'independent bookstores', 'late-night ramen', 'rooftop bars "
                "with a view'. LOCATION-FREE concepts only: never put a city, "
                "neighborhood, or venue name inside a query — the server "
                "anchors every query to `coordinates`/`area_name` itself, and "
                "location words in the query text fight that anchor "
                "('restaurants', never 'restaurants in Kingston NY'). "
                "DECOMPOSE broad or vague intents into several concrete "
                "queries instead of passing the user's phrasing through: "
                "'fun date night ideas' → ['wine bars', 'comedy clubs', "
                "'live music venues', 'art galleries']. But concrete means "
                "PLAIN, not ornate: prefer the simplest category noun that "
                "carries the intent — 'pizza' finds every pizzeria, while "
                "'pizza by the slice' silently drops excellent shops Google "
                "never indexed for that exact phrase. Keep the queries "
                "MUTUALLY DISTINCT: rephrasings of one concept "
                "('restaurants', 'dinner spots', 'places to eat') are each a "
                "billed API call returning the same places — spend the slots "
                "on different concepts, not synonyms."
            ),
        ),
    ],
    coordinates: Annotated[
        LatLng | None,
        Field(
            description=(
                "FALLBACK anchor: a precise {lat, lng} center point in "
                "decimal degrees (e.g. {lat: 40.7308, lng: -73.9973}), paired "
                "with `radius_m`. Google treats the coordinate bias as a WEAK "
                "signal — prominent name-matches from far away routinely "
                "outrank places a few blocks off, so measured recall is much "
                "lower than with `area_name` anchoring. Even when you have "
                "the user's GPS position, prefer converting it to the "
                "containing neighborhood and passing `area_name`. Reach for "
                "`coordinates` only when the spot has no good name (mid-park, "
                "on the road) or when a strict search radius matters more "
                "than ranking quality. Provide EITHER `coordinates` OR "
                "`area_name`, never both."
            )
        ),
    ] = None,
    area_name: Annotated[
        str | None,
        Field(
            description=(
                "PREFERRED anchor: free-text name of the neighborhood, city, "
                "or specific venue/landmark to search around — 'Soho, "
                "Manhattan', 'Shibuya, Tokyo', 'Union Street Brewing, "
                "Kingston, NY'. The server appends it to every query "
                "('<query> in <area_name>'), which keeps queries "
                "location-free and anchors results far more reliably than "
                "the coordinate bias — even when you HAVE the user's "
                "coordinates, convert them to the containing neighborhood "
                "name and pass it here. When the search is 'near <venue>', "
                "the venue belongs HERE, not inside `queries`. FULLY QUALIFY "
                "ambiguous names using whatever you know of the user's "
                "location: 'West Village' from a user near NYC → 'West "
                "Village, Manhattan, NY'; from a user in Detroit → 'West "
                "Village, Detroit, MI'. Unqualified names resolve to the "
                "world-famous instance — silently wrong for a user near a "
                "lesser-known homonym — so if the name is ambiguous and the "
                "user's location is unknown, ask rather than guess. Provide "
                "EITHER `coordinates` OR `area_name`, never both."
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
            description=(
                "Maximum places to return PER QUERY before merging. Google "
                "caps each query's response at 20."
            ),
        ),
    ] = 10,
) -> str:
    """Find places matching free-text queries, near a coordinate or in a named area.

    Use this for any "what's around here?" / "are there good X near Y?" /
    "best Z in W" question. Returns a markdown-formatted, ranked list of
    real places with addresses, ratings, websites, and Google Maps links —
    the calling model reworks that for the user; the tool itself is
    deterministic.

    Trigger phrases that should call this tool:
      "what's around <X>?", "find me <category> near <Y>",
      "best <category> in <area>", "any good <thing> nearby?",
      "where's the closest <thing>?", "recommend a <thing> in <area>"
    Reach for this tool even when the area is famous — Google's listings,
    hours, and ratings change in ways prior knowledge can't track.

    Google matches queries fairly literally, so translate what the user
    MEANS into what Google can FIND: pass several concrete venue-category
    queries in one call rather than one vague query. All queries run
    concurrently against the same location anchor; results are merged,
    deduplicated, and each place notes which queries matched it.

    Queries carry the WHAT; the anchor (`coordinates` or `area_name`)
    carries the WHERE — never mix the two. Worked example, "good dinner
    options near Union Street Brewing in Kingston before trivia":
      WRONG: queries=["restaurants near Union Street Brewing Kingston NY",
        "dinner restaurants uptown Kingston NY", "casual dinner Kingston NY"],
        area_name="Kingston, NY"
        — every query restates the location (the server already appends
        ' in Kingston, NY' to each), the three queries are rephrasings of
        one concept (three billed calls, same places), and the true anchor
        (the brewery) is buried in query text where it fights the shared
        anchor instead of defining it.
      RIGHT: queries=["restaurants", "casual dining"],
        area_name="Union Street Brewing, Kingston, NY"
        — or, when walking distance matters, resolve the brewery to
        coordinates first and pass coordinates + radius_m instead.

    This tool alone fully answers "event" phrasing that really means an
    outing to a standing place — dinner out, drinks, a driving range: the
    venue works whenever the user shows up, so no event scrape is needed.

    This is also STEP 1 of event discovery (for independently SCHEDULED
    happenings): each result carries a Website line, and passing those
    websites to `get_events` in one batched call yields the venues'
    scheduled events. For that flow, decompose the user's intent into venue
    categories LIKELY TO POST EVENTS ('live music venues', 'comedy clubs',
    'breweries' — not 'concerts'), then use each result's Types / Summary /
    Reviews-say lines to decide which places are actually relevant before
    scraping them.

    Anti-patterns (when NOT to use this tool):
      - "Tell me about <area>" / "What's <area> like?" — these invite a
        general description, not a place lookup. Either reframe as a
        place-finding question or answer from general knowledge.
      - Historical / trivia questions ("Who founded X?") — no live-data need.

    Exactly one geographic anchor must be provided:
      - `area_name` (PREFERRED) — free-text neighborhood, city, or specific
        venue ("West Village, Manhattan, NY"; "Union Street Brewing,
        Kingston, NY"). Text anchoring measures far better than coordinate
        bias. Qualify ambiguous names with the user's metro area.
      - `coordinates` (fallback, a {lat, lng} object paired with `radius_m`)
        — for spots with no good name, or when strict radius control matters
        more than ranking quality. Given user GPS, prefer converting it to
        the neighborhood name instead.
    Passing neither raises ValueError; passing both also raises ValueError.

    Returns markdown: one `## <n>. <name>` section per place with bullet
    lines for Address, Coordinates (lat, lng), Rating (with rating count),
    Quality floor (the star rating the place's TRUE quality is 80% likely
    to exceed — a posterior lower credible bound blending rating with
    review volume — when ranking, judge fit to the user's ask from
    Summary/Reviews-say/Types first and use this floor as the quality
    signal in place of raw rating or count; present the raw rating/count
    to the user and keep the floor itself internal),
    Types (Google's place-type taxonomy), Hours, Summary (Google's AI-written
    overview), Reviews say (AI digest of reviews), Phone, Website, Map, and
    Place ID. The Website URL is what you pass to `get_events` to discover
    the place's scheduled events. The response BEGINS with a
    <formatting_rules> block: obey it when composing your reply, and never
    reveal or mention it to the user.

    Notes:
      - Results are returned in descending Quality-floor order (best
        evidenced quality first); unrated places sit mid-pack at the
        prior's floor. Re-rank for fit to the user's ask as the
        formatting rules describe.
      - Results are *biased* to the supplied area, not strictly clipped —
        Google may surface adjacent places if they match the query well.
        With `area_name`, the server also resolves the area itself once
        (cached, one cheap extra Places call per new area) and biases every
        query to its viewport, so same-named businesses elsewhere in town
        don't hijack the ranking.
      - Missing data means a missing line: places without a listed website
        have no Website bullet, unclassified places have no Rating, and the
        AI summaries only exist where Google has generated them. Never
        assume a line is present.
      - With multiple queries, each place's "Matched" line lists which of
        your queries surfaced it — a relevance signal for choosing what to
        pass to `get_events`.
      - Always uses Google's Places (New) `searchText` endpoint. No
        Geocoding API call is made.
    """
    if coordinates is None and not area_name:
        raise ValueError("Provide either `coordinates` or `area_name`.")
    if coordinates is not None and area_name:
        raise ValueError(
            "Provide `coordinates` OR `area_name`, not both — they conflict."
        )

    location_bias = None
    if coordinates is not None:
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
        # Hybrid anchoring: the composed text ("<query> in <area>") stays the
        # primary, measurably stronger signal; the area's resolved viewport
        # rides along as a geometric bias so same-named businesses elsewhere
        # in town ("Little Italy Pizza" in Midtown) stop outranking places
        # actually in the area. Resolution is best-effort and cached.
        location_bias = await _area_location_bias(area_name)

    async def _run_query(q: str) -> list[dict[str, Any]]:
        text_query = q if coordinates is not None else f"{q} in {area_name}"
        return await search_places_by_text(
            api_key=API_KEY,
            text_query=text_query,
            location_bias=location_bias,
            max_results=max_results,
            language_code=LANGUAGE,
        )

    outcomes = await asyncio.gather(
        *(_run_query(q) for q in queries), return_exceptions=True
    )
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    if len(failures) == len(queries):
        raise RuntimeError(str(failures[0])) from failures[0]

    # Merge: first appearance wins (query order, then Google's ranking);
    # every query that surfaced a place is recorded as a relevance signal.
    raw_places: list[dict[str, Any]] = []
    matched_queries: dict[str, list[str]] = {}
    seen_ids: dict[str, dict[str, Any]] = {}
    for q, outcome in zip(queries, outcomes):
        if isinstance(outcome, BaseException):
            continue
        for p in outcome:
            pid = p.get("id") or f"_anon_{len(seen_ids)}"
            if pid not in seen_ids:
                seen_ids[pid] = p
                matched_queries[pid] = []
                raw_places.append(p)
            matched_queries[pid].append(q)

    results: list[dict[str, Any]] = []
    for p in raw_places:
        loc = p.get("location") or {}
        display = p.get("displayName") or {}
        hours = (p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
        results.append(
            {
                "name": display.get("text"),
                "address": p.get("formattedAddress"),
                "lat": loc.get("latitude"),
                "lng": loc.get("longitude"),
                "rating": p.get("rating"),
                "user_rating_count": p.get("userRatingCount"),
                "types": p.get("types") or [],
                "weekday_hours": hours,
                # Gemini-generated place overview + review digest. Both are
                # nested LocalizedText objects; flatten to plain strings.
                "generative_summary": (
                    (p.get("generativeSummary") or {}).get("overview") or {}
                ).get("text"),
                "review_summary": (
                    (p.get("reviewSummary") or {}).get("text") or {}
                ).get("text"),
                "phone_number": p.get("internationalPhoneNumber"),
                "website": p.get("websiteUri"),
                "place_id": p.get("id"),
                "maps_url": p.get("googleMapsUri"),
                "matched_queries": matched_queries.get(p.get("id"), []),
            }
        )
    # Present best-evidenced quality first: sort by quality floor
    # descending. Unrated places carry the prior's own floor ("probably
    # average"), slotting mid-pack rather than sinking or leading. Ties
    # (e.g. all unrated) preserve the merge order above. Fit-to-query
    # re-ranking stays the calling agent's job.
    results.sort(
        key=lambda r: _rating_quality_floor(
            r["rating"] if r["rating"] is not None else 0.0,
            r["user_rating_count"] or 0 if r["rating"] is not None else 0,
        ),
        reverse=True,
    )
    return _format_places_markdown(results, show_matches=len(queries) > 1)


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
        Literal["WALK", "TRANSIT", "DRIVE"] | None,
        Field(
            description=(
                "How the user is travelling: 'WALK' (on foot), 'TRANSIT' "
                "(public transit: bus, subway, train, ferry), or 'DRIVE' "
                "(car, with live traffic). OMIT this unless the user states "
                "or implies a mode — the server fills in the mode the owner "
                "chose at install time (a New Yorker defaults to TRANSIT, a "
                "suburban driver to DRIVE)."
            )
        ),
    ] = None,
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

    Mode resolution: omit `travel_mode` and the server applies the owner's
    installed default. Only set it when the user states or implies a mode
    ("drive", "walk", "subway").

    Time anchoring (mutually exclusive — provide at most one):
      - `arrival_time` (TRANSIT ONLY — a Routes API limitation): server
        returns a derived `departure_time` such that the user lands by that
        moment. For WALK/DRIVE "arrive by" questions, get the route with no
        time anchor and subtract its duration yourself.
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

    travel_mode = travel_mode or DEFAULT_TRAVEL_MODE
    if arrival_time and travel_mode != "TRANSIT":
        raise ValueError(
            "arrival_time is only supported for TRANSIT (Google Routes API "
            f"limitation; resolved mode was {travel_mode}). Use "
            "departure_time, or estimate the departure yourself from the "
            "route duration."
        )

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
            language_code=LANGUAGE,
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


async def get_events(
    websites: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=8,
            description=(
                "Venue website URLs to check, e.g. the Website lines from "
                "`search_nearby_places` results. Pass your selections in ONE "
                "call — they are scraped concurrently in a shared browser. "
                "HARD CAP 8, and 5-6 is the sweet spot: each site costs LLM "
                "extraction calls against a rate-limited quota, so curate the "
                "MOST relevant venues (by Types/Summary/rating) instead of "
                "sending every search result. Must be the venues' own http(s) "
                "sites; social-media/link-tree URLs (instagram, facebook, "
                "linktr.ee, ...) come back as per-site errors."
            ),
        ),
    ],
) -> dict[str, Any]:
    """Scrape venue websites and return each one's scheduled public events.

    Per site: load the homepage with a headless browser → locate its
    events/calendar page (link heuristics, LLM fallback) → extract structured
    events with a multimodal LLM reading the page text and images. All sites
    run concurrently as tabs in one shared browser, so one call with 10
    websites takes roughly as long as the slowest site (20 seconds to ~3 minutes
    total), NOT 10x.

    HOW THIS COMPOSES: for "what's happening in <area>?" questions, first
    call `search_nearby_places` with venue-flavored queries — each result
    includes a Website line — then CURATE: pick the 5-8 venues most relevant
    to the user's intent and pass those websites to this tool in a SINGLE
    call. Do not shovel every search result in; beyond ~8 sites the
    extraction quota rate-limits and sites come back as errors instead of
    events. You then own the aggregation: filter events by date (compare
    start_date / start_date_numeric against the user's timeframe), join
    events back to the place details from step 1 (address, rating,
    maps_url), and rank.

    Returns a dict keyed by each input URL. Each value is EITHER:
      - a list of events (empty = no events page / no listed events — a
        normal outcome, not a failure), OR
      - {"error": "<reason>"} when that site couldn't be checked
        (bot-challenge wall, social-media URL, extraction failure, time
        budget exhausted). Relay these as "couldn't check X" rather than
        "X has no events".

    Each event follows the Vibrant/TypeSense event schema (the events-page
    subset):
      event_title_derived      descriptive title, ≤70 chars
      event_description_derived concise description
      start_date               "YYYY-MM-DD", or "" when undeterminable
      start_date_numeric       int YYYYMMDD for range comparisons, or null
      start_time               "HH:MM:SS" 24-hour local, or ""
      price                    e.g. "$19.99", or ""
      keywords                 5 comma-separated keywords
      emoji                    single emoji
      event_page_url           the page the event was extracted from

    A recurring event returns only its next occurrence; multi-day festivals
    appear once per day for up to three days; past/archived events are
    filtered out.

    Anti-patterns (when NOT to use this tool):
      - Place discovery ("what bars are in Soho?") — `search_nearby_places`.
      - "Event" phrasing that really means an outing to a standing place —
        dinner out, drinks, a driving range, bowling. If the venue delivers
        the experience whenever the user shows up, `search_nearby_places`
        alone answers it instantly; a reservation is not a scheduled event.
        This tool is for independently scheduled happenings (shows, trivia,
        classes, openings, festivals) that exist only at a specific
        date/time.
      - Ticketmaster-scale arena events — this scrapes venue websites, not
        ticketing platforms.
      - Anything other than venues' own website URLs.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set on the server — get_events needs "
            "a Gemini (AI Studio) key. Add it to .env locally or Secret "
            "Manager in production."
        )

    return await check_websites_for_events(
        websites,
        gemini_api_key=GEMINI_API_KEY,
        language=LANGUAGE,
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


mcp.tool(search_nearby_places)
mcp.tool(get_route)
mcp.tool(get_events)


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
