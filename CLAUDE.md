# Agent context for this repo

## What this project is

A self-hosted MCP server that bridges any MCP-capable client (Claude Mobile/Desktop/Web,
ChatGPT, MCP Inspector, etc.) to Google Maps Platform — Places API (New) `searchText`
and Routes API `computeRoutes` — plus a `get_events` tool that scrapes a batch of
venue websites (headless Playwright, concurrent tabs in one shared browser) and extracts
structured events with Gemini Flash. Event discovery is agent-orchestrated by design:
`search_nearby_places` returns each place's `website`, the calling agent passes those
websites to `get_events` in one call, and then filters/joins/ranks the per-site
results itself. Single-tenant: each install runs in the user's own GCP account behind
their own OAuth flow.

User-facing entry points are the README and `install.py`. This file is for AI agents
helping maintain or extend the codebase.

## Architectural commitments — don't break

- **Single component; deterministic tools stay deterministic.** `search_nearby_places`
  and `get_route` have no LLM dependency and must stay that way. `get_events` is
  the one deliberate exception: it scrapes venue websites with headless Playwright and
  extracts events with Gemini (AI Studio key — still an all-Google stack). Do not
  "fix" that as a regression, and do not let LLM calls creep into the other tools. In
  every case the calling client does the natural-language synthesis; tools return
  structured JSON.
- **The server batches scraping; the agent orchestrates discovery.**
  `get_events` takes a LIST of websites and scrapes them concurrently as tabs in
  one shared Chromium (stealth-search's batch model — never one browser launch per
  site), returning `{website: events | {error}}`. Per-site failures are error entries,
  never batch failures. The calling agent still owns the rest: discovering venues via
  `search_nearby_places` (which includes `website` per place), date filtering, joining
  events back to place details, and ranking. Don't move venue discovery or ranking
  into the server.
- **Stack is Google + the chosen MCP client only**, no AWS. Hosting target is
  Google Cloud Run; secrets via Google Secret Manager; logs via Google Cloud Logging.
- **Framework: FastMCP**, transport = Streamable HTTP, bound to `0.0.0.0:$PORT/mcp`
  (Cloud Run injects `PORT`; do not hard-code `8080`).
- **Two auth boundaries — keep them separate.** (a) Maps server → Google APIs uses an
  API key (OAuth not required). (b) MCP client → Maps server uses OAuth2 in front of
  Cloud Run, validated server-side against an email allowlist.

## Secrets — never commit API keys

Never check API keys, OAuth client secrets, service-account JSON, or any other
credentials into this repo. This includes the Google Maps API key, OAuth provider
secrets, and any Cloud Run / Secret Manager values. Concretely:

- Local development reads secrets from `mcp_server/.env` (gitignored). The example
  is `mcp_server/.env.example` with placeholders.
- Production reads secrets from Google Secret Manager, mounted into the Cloud Run
  container as env vars via `--update-secrets`. Do not bake keys into `Dockerfile`,
  `infra/deploy.sh`, or example configs.
- Do not paste real keys into committed Markdown, code comments, commit messages, or
  test fixtures. Use placeholders (`YOUR_API_KEY`, `GOCSPX-test`) in any committed
  example.
- The installer pipes secret values via stdin to gcloud so they never touch argv or
  the install log.
- If a key is committed by accident, **rotate it immediately** in Google Cloud Console
  — `git` history makes a deleted commit insufficient on its own.

## Non-obvious constraints (easy to miss, expensive to discover late)

- **`X-Goog-FieldMask` is mandatory** on every Places (New) and Routes request.
  No default field set — without it, calls fail or return almost nothing. Field masks
  also drive cost; surface them in `mcp_server/google_maps.py` rather than burying
  them in helpers.
- **Use the new Places API**, not legacy. The server calls `places.searchText`
  (`https://places.googleapis.com/v1/places:searchText`).
- **Geocoding is intentionally avoided.** Area-name lookups go through Places
  `searchText` with a location bias rather than enabling a third API surface
  (Geocoding). Don't silently add a Geocoding dependency. Since 2026-07 the
  server does **hybrid anchoring** for `area_name`: one cached `searchText`
  call (minimal field mask, `resolve_area_viewport`) resolves the area's
  viewport, which every query then carries as a rectangle `locationBias` on
  top of the composed `"<query> in <area>"` text. Text pins semantics,
  viewport pins geometry — this exists because same-named businesses
  elsewhere in town ("Little Italy Pizza" in Midtown) measurably hijacked
  text-only ranking. Resolution is best-effort: on failure the search runs
  unbiased, never errors.
- **Travel modes:** `WALK`, `TRANSIT`, and `DRIVE` (`BICYCLE` is stretch). DRIVE
  opts into `routingPreference: TRAFFIC_AWARE` (upstream default is traffic-blind).
  `arrival_time` is TRANSIT-only — a Routes API limitation, rejected server-side
  with guidance. When the caller omits `travel_mode`, the server applies
  `DEFAULT_TRAVEL_MODE` (env; WALK/TRANSIT/DRIVE, default TRANSIT, chosen at
  install time — the owner's "how I usually get around").
- **Result caps:** `search_nearby_places` caps `max_results` at 20 (Google's hard
  limit) and defaults to 10 to keep tool output prompt-friendly.
- **Cloud Run URL prediction:** the installer relies on the project-scoped URL
  format `https://<service>-<project_number>.<region>.run.app` being deterministic
  before deploy. If Cloud Run ever changes this, the installer's "register OAuth
  redirect URI before first deploy" trick stops working.
- **OAuth allowlist must be enforced server-side for any public deployment.** The
  consent screen's "Test Users" list is NOT a sufficient allowlist once the consent
  screen flips to "In production" — `AllowlistedGoogleTokenVerifier` is what gates
  access in that mode.
- **OAuth state must persist across instance restarts.** FastMCP's OAuthProxy keeps
  client registrations and refresh tokens in a file store under `FASTMCP_HOME`;
  Cloud Run's filesystem is ephemeral, so production mounts a GCS bucket
  (`<project>-oauth-state`) at `/mnt/oauth-state` and sets `FASTMCP_HOME` to it
  (deploy.sh / install.py). Removing that volume silently reverts to
  reconnect-on-every-cold-start. Session length is the 30-day
  `fallback_refresh_token_expiry_seconds` in `_build_auth_provider`.
- **`--max-instances=1` is load-bearing for OAuth, not a cost tweak.** The GCS-fuse
  state store has no instant cross-instance read-after-write consistency, so with
  multiple instances Claude's concurrent `/mcp` calls hit instances that don't yet
  see the just-written session → intermittent 401 → the connector re-registers in an
  endless auth loop ("the circle"). One instance owns all OAuth state; fine for a
  single-user server. If this ever needs to scale out, move OAuth state to a real
  shared KV backend (Firestore/Redis via a custom AsyncKeyValue) first.
- **`get_events` runtime constraints (Playwright + Gemini):**
  - Chromium launches with `--no-sandbox` — its own sandbox cannot start inside
    Cloud Run's gVisor sandbox. `--disable-dev-shm-usage` because /dev/shm is small.
  - `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` in the Dockerfile is load-bearing for
    BOTH the browser install and runtime: it keeps Chromium outside root's home so
    the non-root `appuser` can exec it.
  - Cloud Run needs `--memory=2Gi --cpu=2 --concurrency=4` (set in deploy.sh and
    install.py); the default 512MiB OOMs Chromium.
  - Gemini calls disable/minimize thinking (it silently adds seconds per call):
    `thinkingBudget: 0` for 2.5-era models, `thinkingLevel: "low"` for Gemini 3+
    (`_thinking_config` in gemini.py picks by model id). Default model:
    `gemini-3.1-flash-lite` for both extract and classify (paid tier — the free
    tier's 20 req/day/model can't support get_events).
  - Gemini's `responseSchema` is an OpenAPI-3 subset, NOT full JSON Schema. The
    schemas in `gemini.py` are hand-written dicts; don't replace them with Pydantic
    `model_json_schema()` output.
  - The tool runs against a wall-clock budget (default 210s, env `CHECK_EVENTS_BUDGET_S` — sized to absorb one ~60s Gemini rate-limit wait);
    exhausting it raises a descriptive error so the agent reports the site as unchecked.
  - GEMINI_API_KEY is checked at CALL time, not import time, so deployments without
    the secret keep serving the deterministic tools.
- **Results language is a server-wide setting** (`CONNECTOR_LANGUAGE`, BCP-47,
  default `en`; chosen at install time). Do NOT add per-call translation hooks:
  Places/Routes are localized natively via `languageCode` on the request, and
  event extraction translates inside the extraction prompt — zero extra calls.

## Tool contracts (current)

| Tool | Inputs | Output |
|---|---|---|
| `search_nearby_places` | `queries: list[str]` (1–8 concrete category queries, run concurrently and merged — decompose vague intents), `coordinates: {lat,lng}` *or* `area_name: str` (mutually exclusive), `radius_m: int = 1500`, `max_results: int = 10` (per query) | Markdown: one `## <n>. <name>` section per place with bullet lines Address, Coordinates, Rating, Quality score (Beta-posterior P(true rating > 4.5★) with uniform prior — the agent ranks by fit-to-query first, uses this as the quality signal in place of raw rating/count, displays raw rating/count), Types, Hours, Summary (Google AI overview), Reviews say (AI review digest), Phone, Website, Map, Place ID. Empty values → line omitted. The Website line feeds `get_events` |
| `get_route` | `origin: str \| {lat,lng}`, `destination: str \| {lat,lng}`, `travel_mode?: "WALK"\|"TRANSIT"\|"DRIVE"` (omitted → server's `DEFAULT_TRAVEL_MODE`), `arrival_time?: ISO8601` (TRANSIT only), `departure_time?: ISO8601`, `transit_preferences?: "FEWER_TRANSFERS"\|"LESS_WALKING"` (default `"FEWER_TRANSFERS"`) | `{distance_m, duration_s, duration_in_traffic_s, departure_time, arrival_time, polyline, steps[]}` |
| `get_events` | `websites: list[str]` (1–8 venue website URLs, from `search_nearby_places`'s Website lines — the agent curates the most relevant 5–8 and passes them in ONE call; larger batches trip Gemini free-tier rate limits) | Dict keyed by input URL. Value = list of events in Vibrant/TypeSense shape (`{event_title_derived, event_description_derived, start_date, start_date_numeric, start_time, price, keywords, emoji, event_page_url}`; `[]` = no events page / no events, normal) OR `{"error": reason}` (social-media URL, bot wall, extraction failure, budget exhausted). Sites scrape concurrently in one shared browser — a full batch takes ~the slowest site (20s–3min), not Nx |

Both tools' Pydantic schemas + Field descriptions are the canonical source for client
LLMs — keep those tight.

## Reference material

Anthropic / MCP docs:
- https://modelcontextprotocol.io/specification — current MCP spec
- https://docs.anthropic.com/en/docs/agents-and-tools/mcp — MCP overview
- https://github.com/jlowin/fastmcp — FastMCP source (we use 3.x with `OAuthProxy`)

Google docs:
- https://developers.google.com/maps/documentation/places/web-service/text-search
- https://developers.google.com/maps/documentation/routes/compute_route_directions
- https://cloud.google.com/run/docs/configuring/services/secrets — Secret Manager + Cloud Run
- https://mapsplatform.google.com/pricing/ — current Maps pricing

`WebFetch` against any of these when you need fresh info; cache nothing into the repo.

## Commands

```bash
# Run tests
cd mcp_server && .venv/bin/pytest                    # hermetic + fixture-based browser tests
# test_scraper.py drives a real headless Chromium against local file:// fixtures;
# it auto-skips if the browser is missing (fix with: .venv/bin/playwright install chromium)
RUN_LIVE_TESTS=1 .venv/bin/pytest tests/test_live_smoke.py   # live tests against real Google APIs (+ Gemini/Playwright for get_events)
RUN_LIVE_TESTS=1 .venv/bin/pytest tests/test_inverse_recall.py -s   # retrieval-quality eval: known-good NYC places must be recovered by their inverse queries (seeds in tests/fixtures/inverse_recall_nyc.json)

# Run server locally
cd mcp_server && .venv/bin/python server.py          # streamable-http on :8000
cd mcp_server && .venv/bin/python server.py --stdio  # stdio for direct MCP client

# Provision / tear down a Cloud Run deployment
python install.py                                    # interactive, ~10 min
python install.py --reset                            # discard installer state
python uninstall.py                                  # tear down resources
python uninstall.py --delete-project                 # nuke the entire GCP project

# Manual deploy (advanced — install.py wraps this)
./infra/setup-secrets.sh                             # push secrets to Secret Manager
./infra/deploy.sh                                    # gcloud run deploy --source .
```
