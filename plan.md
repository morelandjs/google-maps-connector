# Google Maps MCP Server — Design Plan

---

## 1. Goal

A personal MCP server that gives any MCP-capable LLM client (Claude Mobile / Desktop /
Web, ChatGPT, MCP Inspector, etc.) first-class access to Google Maps, so a user can
ask natural-language questions about places and travel and get answers backed by live
Google Maps data instead of training-corpus recall.

This is a **personal, single-tenant project** scoped to one Google account. Each
installer run provisions a private, OAuth-protected MCP endpoint that only the
installing user can authenticate against.

**Architectural principle:** the system is a single MCP server. The MCP client
connects to it directly and does all natural-language synthesis itself. The server's
job is to be a thin, deterministic bridge to Google Maps — no LLM logic on the server
side.

---

## 2. User-facing experience

Two anchor use cases drive the design:

### UC-1: Departure-time / directions
> *"What time do I need to leave to get to [destination] by 6pm?"*

The MCP client calls `get_route`, receives a structured route response, and synthesizes
the departure-time / ETA / step summary in its own reply.

**Acceptance criteria**
- Returns a departure time accounting for live traffic.
- Supports at least `WALK` and `TRANSIT` travel mode in v1; `DRIVE` and `BICYCLE` are stretch.
- Honors a target arrival time when supplied; otherwise assumes "leave now".

### UC-2: Nearby places search
> *"What clothing apparel stores are near Soho?"*

The MCP client calls `search_nearby_places` with a query and a location (or area name)
and formats the returned list for the user.

**Acceptance criteria**
- Accepts a query field for subject of interest, e.g. "shopping" or "shoes".
- Accepts either a named area (e.g., "Soho") or an explicit lat/lng + radius.
- Returns name, address, rating, price level, and a maps link per result.
- Caps results to a reasonable count (e.g., 10) to keep prompts small.
- Surfaces basic place details such as name, address, open hours, reviews, phone number.

---

## 3. Architecture

A single deployable component:

```
MCP-capable client (Claude Mobile/Desktop/Web, ChatGPT, MCP Inspector, ...)
       │  (MCP over Streamable HTTP, OAuth2)
       ▼
Maps MCP Server   (Google Cloud Run)        ← Deterministic, no LLM
       │
       ▼
Google Maps APIs  (Places New, Routes)
```

**The whole stack is Google + your chosen MCP client — no AWS dependencies.** Hosting is
Google Cloud Run; data sources are Google Maps APIs; the only LLM is the one in your
client app.

### Why a single component?
- The MCP client is already an LLM. Any synthesis it needs (computing
  "leave at 5:42pm to arrive by 6pm", summarizing a list of places) it can do itself
  with the structured tool output.
- A second LLM hop would add latency, cost, and a second context to keep coherent for
  no clear win at this scale.
- The MCP server stays small, deterministic, and easy to verify: tool call → API call →
  formatted response. No prompts, no model fees, no nondeterminism. Funded by free-tier
  Google credits.

---

## 4. Components

### 4.1 Maps MCP Server (`mcp_server/`)
- **Framework:** FastMCP, transport = Streamable HTTP, listening on `0.0.0.0:$PORT/mcp`. Cloud Run
  injects the `PORT` env var (defaults to `8080`); the server must bind to it rather than a
  hard-coded port.
- **Responsibilities:** expose tools, call Google APIs, return structured responses.
- **No LLM calls.** The server has no foundation-model dependency — the calling client does
  all natural-language synthesis itself.
- **Tools (v1):**

  | Tool | Inputs | Output |
  |---|---|---|
  | `search_nearby_places` | `query: str`, `coordinates: {lat, lng}` *or* `area_name: str`, `radius_m: int = 1500`, `max_results: int = 10` | List of `{name, address, lat, lng, rating, user_rating_count, price_level, types, weekday_hours, reviews, phone_number, place_id, maps_url}` |
  | `get_route` | `origin: str \| {lat, lng}`, `destination: str \| {lat, lng}`, `travel_mode: "WALK" \| "TRANSIT"` (required in v1), `arrival_time?: ISO8601`, `departure_time?: ISO8601`, `transit_preferences?: "FEWER_TRANSFERS" \| "LESS_WALKING"` | `{distance_m, duration_s, duration_in_traffic_s, departure_time, arrival_time, polyline, steps[]}` |

- **Response shape is JSON, not prose.** The MCP client is doing the formatting; the
  server hands back machine-friendly fields and lets the model write the user-facing
  sentence.
- **Field masks are mandatory.** Both Places (New) and Routes require `X-Goog-FieldMask`;
  without it the call fails or returns very little. Field masks also drive cost — request
  only the fields we render.
- **Geocoding for area names.** "Soho" needs to become coordinates before searching.
  We use Places `searchText` with a location bias rather than enabling the Geocoding API
  as a third surface.

---

## 5. Google Maps API setup

The installer (`install.py`) automates this; the manual checklist (in `INSTRUCTIONS.md`):

1. **Enable APIs** in Google Cloud Console for the project tied to the user's Google account:
   - **Places API (New)** — for `places.searchNearby` / `places.searchText`.
   - **Routes API** — for `computeRoutes`.
2. **Provision credentials**:
   - **API key** is sufficient for both APIs in this single-user setup. Restrict the key by
     API.
   - OAuth client is **not** needed for the Google Maps calls themselves — these accept API
     keys. OAuth in this project is between the MCP client and our Cloud Run deployment, not
     between our server and Google.
3. **Store the key**: locally in a `.env` (gitignored); in Cloud Run via Google Secret
   Manager, mounted into the container as an env var (Phase 3).
4. **Quota / billing**: Google requires a billing account even for free-tier traffic. Set a
   low daily quota cap to bound cost while developing.

---

## 6. Authentication strategy

Two distinct auth boundaries — keep them separate in the design:

| Boundary | Mechanism |
|---|---|
| Maps server → Google Maps API | API key (per §5) |
| MCP client → Maps MCP server | OAuth2 in front of Cloud Run (Phases 2 & 3) |

Phase 2/3 use **Google as the OAuth Identity Provider** via FastMCP's built-in
`GoogleProvider` (Phase 2 local) or `OAuthProxy` with a custom email-allowlist verifier
(Phase 3 production). Single-tenant: only the email(s) listed in the
`GOOGLE_OAUTH_ALLOWED_EMAILS` secret can complete the OAuth flow. Anyone else with a
valid Google token is rejected server-side.

Identity Platform / Firebase Auth was considered and dropped — Identity Platform's
multi-provider features are overkill for a single-user deployment.

---

## 7. Repository layout

The repo is the monorepo for the project — MCP server, deployment infra, and reference
material all live here under one git history.

```
google-maps-mcp/
├── install.py            # one-shot installer (gcloud + browser)
├── uninstall.py          # tears down everything install.py creates
├── Dockerfile            # multi-stage, Python 3.13-slim, non-root
├── .dockerignore
├── mcp_server/           # FastMCP + Google Maps clients
│   ├── pyproject.toml
│   ├── server.py         # FastMCP entrypoint, 0.0.0.0:$PORT/mcp
│   ├── google_maps.py    # Places (New) + Routes clients
│   ├── .env.example
│   └── tests/
├── infra/
│   ├── deploy.sh         # gcloud run deploy wrapper
│   └── setup-secrets.sh  # idempotent Secret Manager push
├── ref/                  # vendored Claude/MCP and Google docs
├── INSTRUCTIONS.md       # manual install walkthrough (advanced)
├── plan.md               # this file
└── CLAUDE.md             # agent-facing project instructions
```

**Layout principles**
- Single `pyproject.toml`; flat layout under `mcp_server/` (no `src/` nesting, since the
  server isn't published as a library).
- Container-related files (`Dockerfile`, `.dockerignore`) at the repo root so
  `gcloud run deploy --source .` auto-discovers the Dockerfile.
- All deployment-helper scripts live in `infra/`.

---

## 8. Development phases

Each phase has a single, testable exit criterion. **Don't move to the next phase until the
current one is demonstrably working.**

### Phase 1 — Local MCP server, no auth
- FastMCP server runs locally via stdio or HTTP.
- Both tools (`search_nearby_places`, `get_route`) call live Google APIs successfully
  against the developer's API key.
- **Exit criterion:** running the server and connecting via MCP Inspector or Claude
  Desktop returns correct results for both anchor use cases.

### Phase 2 — Local server with OAuth
- Add OAuth2 in front of the local server using FastMCP's `GoogleProvider`.
- **Exit criterion:** the server rejects unauthenticated calls and accepts a token from
  Google's OAuth flow end-to-end (verified via MCP Inspector's OAuth client).

### Phase 3 — Deploy to Google Cloud Run
- Containerize the MCP server (Dockerfile at repo root) and deploy to Cloud Run via
  `gcloud run deploy --source .`.
- Wire OAuth with server-side allowlist (`AllowlistedGoogleTokenVerifier` rejects tokens
  for any email not in `GOOGLE_OAUTH_ALLOWED_EMAILS`).
- Inject all secrets from Google Secret Manager.
- Configure the MCP client with the Cloud Run MCP endpoint as a custom connector.
- **Exit criterion:** the MCP client, configured against the Cloud Run endpoint, answers
  both anchor use cases.

### Phase 4 — Public installer
- Single `python install.py` walks a new user from zero (signed in to Google Cloud) to
  a deployed, OAuth-protected MCP endpoint in their own GCP account.
- Resumable via state file; web-console steps reduced to one (consent screen + OAuth
  Client in a single browser session).
- Companion `uninstall.py` cleans up all created resources.
- **Exit criterion:** a stranger from Hacker News can run the installer end-to-end and
  reach a working MCP endpoint with no manual gcloud commands.

---

## 9. Testing strategy

- **Unit tests** in `mcp_server/tests/`. Mock the Google Maps API at the HTTP boundary
  with `respx` so tests are hermetic.
- **MCP-protocol tests** that drive an in-process FastMCP `Client` to exercise the full
  JSON-Schema validation + dispatch + serialization path.
- **Live smoke tests** per tool, env-var-gated (`RUN_LIVE_TESTS=1`), that hit real Google
  APIs. Run before each deploy to catch field-rename regressions hermetic mocks can't.

---

## 10. Observability & cost control

- Log every tool call with input shape, latency, and Google API response status. Cloud Run
  captures container stdout/stderr into Google Cloud Logging automatically.
- Surface Google API field masks in code (don't hide them in helpers) — they directly drive
  cost.
- Set Google Cloud daily quota caps.

---

## 11. Reference material

Vendored docs in `ref/`:

- **Claude / MCP** — `ref/claude/`
  - `building_custom_connectors.md` — supported transports, protocol features, size limits, timeouts.
  - `connect_to_local_mcp_servers.md` — local-MCP wiring patterns.
- **Google Maps** — `ref/google/`
  - `places_api_overview.md`, `places_nearby_search.md` — request/response shapes, field masks.
  - `compute_routes_api.md` — Routes API request body, headers, traffic-aware routing.
  - `host_mcp_servers_on_cloud_run.md` — Cloud Run deployment contract.

---

## 12. Resolved decisions

These were the open questions during Phase 1-2; all resolved in the shipped implementation:

1. **OAuth provider** — Google as direct OAuth IdP via FastMCP's `GoogleProvider`. Identity
   Platform considered and rejected as overkill for single-user.
2. **Geocoding approach** — `searchText` with location bias. No Geocoding API dependency.
3. **`travel_mode` default** — required input (no default). Forces the client to be
   explicit.
4. **Transit preference default** — `FEWER_TRANSFERS`, overridable per call. Optimizes
   for "simple route" rather than Google's default "shortest time" which often returns
   multi-leg routes.
