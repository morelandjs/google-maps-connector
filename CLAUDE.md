# Agent context for this repo

## What this project is

A self-hosted MCP server that bridges any MCP-capable client (Claude Mobile/Desktop/Web,
ChatGPT, MCP Inspector, etc.) to Google Maps Platform — Places API (New) `searchText`
and Routes API `computeRoutes`. Single-tenant: each install runs in the user's own
GCP account behind their own OAuth flow.

User-facing entry points are the README and `install.py`. This file is for AI agents
helping maintain or extend the codebase.

## Architectural commitments — don't break

- **Single component, deterministic.** The MCP server has no LLM dependency. Tools
  return structured JSON; the calling client does all natural-language synthesis.
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
  (Geocoding). Don't silently add a Geocoding dependency.
- **v1 travel modes:** `WALK` and `TRANSIT` only; `DRIVE` / `BICYCLE` are stretch.
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

## Tool contracts (current)

| Tool | Inputs | Output |
|---|---|---|
| `search_nearby_places` | `query: str`, `coordinates: {lat,lng}` *or* `area_name: str` (mutually exclusive), `radius_m: int = 1500`, `max_results: int = 10` | List of `{name, address, lat, lng, rating, user_rating_count, price_level, types, weekday_hours, reviews, phone_number, place_id, maps_url}` |
| `get_route` | `origin: str \| {lat,lng}`, `destination: str \| {lat,lng}`, `travel_mode: "WALK"\|"TRANSIT"`, `arrival_time?: ISO8601`, `departure_time?: ISO8601`, `transit_preferences?: "FEWER_TRANSFERS"\|"LESS_WALKING"` (default `"FEWER_TRANSFERS"`) | `{distance_m, duration_s, duration_in_traffic_s, departure_time, arrival_time, polyline, steps[]}` |

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
cd mcp_server && .venv/bin/pytest                    # 34 hermetic tests
RUN_LIVE_TESTS=1 .venv/bin/pytest tests/test_live_smoke.py   # 2 live tests against real Google APIs

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
