## Repository status

This repo is **pre-code**: there is a plan and reference material, but no `mcp_server/`, no `infra/`, no `pyproject.toml`, no tests yet. Treat `plan.md` as the design source of truth and create the layout described there as Phase 1 work begins.

Note: `plan.md` §7 calls the docs directory `reference_material/`, but on disk it is `ref/` (with `ref/claude/` and `ref/google/`). Use the actual paths when reading.

## What this project is

A single-deployable **MCP server** that bridges Claude (mobile app) to **Google Maps Platform** APIs — Places API (New) `searchNearby` / `searchText` and the Routes API `computeRoutes`. Architectural commitments to honor:

- **Single component, deterministic.** The MCP server has **no LLM dependency** — Claude mobile does all natural-language synthesis. Tools return structured JSON, not prose.
- **Stack is Google + Claude only**, no AWS. Hosting target is **Google Cloud Run**; secrets via **Google Secret Manager**; logs via **Google Cloud Logging**.
- **Framework: FastMCP**, transport = Streamable HTTP, bound to `0.0.0.0:$PORT/mcp` (Cloud Run injects `PORT`; do not hard-code `8080`).
- **Single-tenant**, scoped to one Google account.
- **Two auth boundaries — keep them separate.** (a) Maps server → Google APIs uses an **API key** (OAuth not required). (b) Claude mobile → Maps server uses **OAuth2** in front of Cloud Run. The original brief conflated these; the plan does not.

## Secrets — never commit API keys

**Never check API keys, OAuth client secrets, service-account JSON, or any other credentials into this repo.** This includes the Google Maps API key, OAuth provider secrets, and any Cloud Run / Secret Manager values. Concretely:

- Local development reads the Maps API key from a `.env` file that **must** be listed in `.gitignore` (the `.gitignore` does not exist yet — create it before introducing any `.env` or credential file).
- Production reads secrets from **Google Secret Manager**, mounted into the Cloud Run container as env vars. Do not bake keys into `Dockerfile`, `deploy.sh`, `service.yaml`, or example configs.
- Do not paste real keys into `plan.md`, `README.md`, code comments, commit messages, or test fixtures. Use obvious placeholders (`YOUR_API_KEY`) in any committed example.
- If a key is committed by accident, **rotate it immediately** in Google Cloud Console — `git` history makes a deleted commit insufficient on its own.

## Non-obvious constraints (easy to miss, expensive to discover late)

- **`X-Goog-FieldMask` is mandatory** on every Places (New) and Routes request. There is no default field set — without it, calls fail or return almost nothing. Field masks also drive cost; surface them in tool code rather than burying them in helpers.
- **Use the new Places API**, not legacy. Prefer `places.searchNearby` / `places.searchText` under `/places/web-service/`. Avoid the legacy `/search-nearby` endpoint.
- **Geocoding is an open design choice** (plan §4.1, §12): prefer `searchText` with a location bias over enabling the Geocoding API as a third surface. Don't silently add a Geocoding dependency.
- **v1 travel modes:** `WALK` and `TRANSIT` only; `DRIVE` / `BICYCLE` are stretch.
- **Result caps:** `search_nearby_places` should cap to ~10 results to keep tool output prompt-friendly.
- **Phase gating is strict.** Don't start Phase 2 (OAuth) until Phase 1 (local server + live API calls) is demonstrably working against Claude Desktop / MCP Inspector. See plan §8 for exit criteria.

## Tool contracts (v1, from plan §4.1)

| Tool | Inputs | Output |
|---|---|---|
| `search_nearby_places` | `query: str`, `location: {lat,lng}` *or* `area_name: str`, `radius_m: int = 1500`, `max_results: int = 10` | List of `{name, address, lat, lng, rating, user_rating_count, price_level, place_id, maps_url}` |
| `get_route` | `origin: str \| {lat,lng}`, `destination: str \| {lat,lng}`, `travel_mode: "WALK"\|"TRANSIT"`, `arrival_time?: ISO8601`, `departure_time?: ISO8601` | `{distance_m, duration_s, duration_in_traffic_s, departure_time, arrival_time, polyline, steps[]}` |

## Reference material — read before designing or coding

Local docs (canonical for this repo):

- **Claude / MCP** — `ref/claude/`
  - `building_custom_connectors.md` — supported transports, protocol features, size limits, timeouts. Start here for any MCP server design question.
  - `connect_to_local_mcp_servers.md` — Claude Desktop wiring for Phase 1 testing.
  - `authentication.md` — Claude Code login flows (not Claude↔MCP auth).
- **Google Maps** — `ref/google/`
  - `places_api_overview.md`, `places_nearby_search.md` — request/response shapes, field masks.
  - `compute_routes_api.md` — Routes API request body, headers, traffic-aware routing.
  - `host_mcp_servers_on_cloud_run.md` — Cloud Run deployment contract.

Two pre-loaded skills cover these — invoke them rather than re-fetching:

- `claude-docs` skill — for any "how does Claude expect MCP servers to behave?" question (transports, OAuth between Claude and the connector, tool result limits).
- `google-maps-docs` skill — for Places (New) / Routes request shapes, required `X-Goog-FieldMask`, billing/quota, API enablement steps, **and Google Cloud Run** (container contract, `gcloud run deploy`, request authentication, Secret Manager integration). Use this for Phase 3 deployment work too.

When upstream docs are needed beyond the local cache, both skills list the canonical URLs to `WebFetch` and recommend caching trimmed copies back into `ref/`.

## Open decisions (do not silently resolve)

From plan §12 — flag these to the user before picking:

1. **OAuth provider** for Phase 2/3 — Google Identity Platform / Firebase Auth vs. Auth0 vs. local stub.
2. **Geocoding approach** — `searchText` with location bias vs. enabling the Geocoding API.
3. **`travel_mode` default** — required input vs. default to `WALK`.

## Commands

There is no build / lint / test tooling yet — none of `pyproject.toml`, `Dockerfile`, `deploy.sh` exist. When Phase 1 starts, scaffold them under `mcp_server/` and `infra/` per plan §7 and document the resulting commands here.
