# Claude × Google Maps — Project Plan

> Source: `instructions.txt`. This document is a synthesized, structured plan derived from
> those instructions. Sections marked **[New]** are additions or sharpenings that were not in
> the original brief; sections marked **[Open]** are decisions that still need a call.

---

## 1. Goal

Give the Claude mobile app first-class access to Google Maps so a user can ask natural-language
questions about places and travel and get useful answers — backed by live Google Maps data,
not the model's training corpus.

This is a **personal, single-tenant project** scoped to one Google account.

**Architectural principle:** the system is a single MCP server. Claude mobile connects to it
directly and does all natural-language synthesis and formatting itself. The MCP server's job
is to be a thin, deterministic bridge to Google Maps — no LLM logic on the server side.

---

## 2. User-facing experience

Two anchor use cases drive the design:

### UC-1: Departure-time / directions
> *"What time do I need to leave to get to [destination] by 6pm?"*

Claude mobile calls `get_directions`, receives a structured route response, and synthesizes
the departure-time / ETA / step summary in its own reply.

**Acceptance criteria**
- Returns a departure time accounting for live traffic.
- Supports at least `WALK` and `TRANSIT` travel mode in v1; `DRIVE` and `BICYCLE` are stretch. **[New]**
- Honors a target arrival time when supplied; otherwise assumes "leave now". **[New]**

### UC-2: Nearby places search
> *"What clothing apparel stores are near Soho?"*

Claude mobile calls `search_nearby_places` with a query and a location (or area name) and
formats the returned list for the user.

**Acceptance criteria**
- Accepts a query field for subject of interest, e.g. "shopping" or "shoes"
- Accepts either a named area (e.g., "Soho") or an explicit lat/lng + radius.
- Returns name, address, rating, price level, and a maps link per result. **[New]**
- Caps results to a reasonable count (e.g., 10) to keep prompts small. **[New]**

---

## 3. Architecture

A single deployable component:

```
Claude mobile app
       │  (MCP over Streamable HTTP, OAuth2)
       ▼
Maps MCP Server   (Google Cloud Run)        ← Deterministic, no LLM
       │
       ▼
Google Maps APIs  (Places New, Routes)
```

**The whole stack is Google + Claude — no AWS dependencies.** Hosting is Google Cloud Run; data
sources are Google Maps APIs; the only LLM is Claude (running on the user's mobile device, talking
to Anthropic).

### Why a single component?
- Claude mobile is already an LLM client. Any synthesis the mobile app needs (computing
  "leave at 5:42pm to arrive by 6pm", summarizing a list of places) it can do itself with the
  structured tool output.
- A second LLM hop would add latency, cost, and a second context to keep coherent for no
  clear win at this scale.
- The MCP server stays small, deterministic, and easy to verify: tool call → API call →
  formatted response. No prompts, no model fees, no nondeterminism. Funded by free-tier
  Google credits each month.

---

## 4. Components

### 4.1 Maps MCP Server (`mcp_server/`)
- **Framework:** FastMCP, transport = Streamable HTTP, listening on `0.0.0.0:$PORT/mcp`. Cloud Run
  injects the `PORT` env var (defaults to `8080`); the server must bind to it rather than a
  hard-coded port.
- **Responsibilities:** expose tools, call Google APIs, return structured responses.
- **No LLM calls.** The server has no foundation-model dependency — Claude mobile does all
  natural-language synthesis itself.
- **Tools (v1):**

  | Tool | Inputs | Output |
  |---|---|---|
  | `search_nearby_places` | `query: str`, `location: {lat, lng}` *or* `area_name: str`, `radius_m: int = 1500`, `max_results: int = 10` | List of `{name, address, lat, lng, rating, user_rating_count, price_level, place_id, maps_url}` |
  | `get_directions` | `origin: str \| {lat, lng}`, `destination: str \| {lat, lng}`, `travel_mode: "WALK" \| "TRANSIT"` (required in v1), `arrival_time?: ISO8601`, `departure_time?: ISO8601` | `{distance_m, duration_s, duration_in_traffic_s, departure_time, arrival_time, polyline, steps[]}` |

- **Response shape is JSON, not prose.** Claude mobile is doing the formatting; the server
  should hand back machine-friendly fields and let the model write the user-facing sentence. **[New]**
- **[New] Field masks are mandatory.** Both Places (New) and Routes require
  `X-Goog-FieldMask`; without it the call fails or returns very little. This also keeps cost
  down — request only the fields we render.
- **[New] Geocoding for area names.** "Soho" needs to become coordinates before
  `searchNearby`. Two options: (a) use Places `searchText` with a location bias instead of
  `searchNearby` when only a name is provided, or (b) add a Geocoding API call. Pick one and
  document the choice. Recommendation: prefer `searchText` because it avoids enabling a third
  API.

---

## 5. Google Maps API setup

This will become a one-page checklist in `README.md` once verified. The plan:

1. **Enable APIs** in Google Cloud Console for the project tied to the user's Google account:
   - **Places API (New)** — for `places.searchNearby` / `places.searchText`.
   - **Routes API** — for `computeRoutes`.
2. **Provision credentials**:
   - **API key** is sufficient for both APIs in this single-user setup. Restrict the key by
     API and (eventually) by referrer/IP.
   - OAuth client is **not** needed for the Google Maps calls themselves — these accept API
     keys. OAuth in this project is between Claude mobile and our Cloud Run deployment, not
     between our server and Google. **[New — clarification, since the original instructions
     conflated the two.]**
3. **Store the key**: locally in a `.env` (gitignored); in Cloud Run via Google Secret
   Manager, mounted into the container as an env var or file (Phase 3).
4. **Quota / billing**: Google requires a billing account even for free-tier traffic. Set a
   low daily quota cap to bound cost while developing. **[New]**

---

## 6. Authentication strategy

Two distinct auth boundaries — keep them separate in the design:

| Boundary | Mechanism |
|---|---|
| Maps server → Google Maps API | API key (per §5) |
| Claude mobile → Maps MCP server | OAuth2 in front of Cloud Run (Phases 2 & 3) |

Since this is single-tenant, the OAuth flow can authorize exactly one identity. On Cloud Run
the natural options are:
- **Google Identity Platform / Firebase Auth** as the OAuth2/OIDC provider, with the
  FastMCP server validating bearer tokens itself.
- **Cloud Run "require authentication" + IAP / OIDC** if the Claude mobile app can be
  configured to send a Google-issued ID token. This is simpler but ties the auth to a Google
  account specifically.
- A minimal app-level OAuth stub during Phase 2 (e.g., Auth0 free tier or a self-hosted
  OAuth provider) if we want to validate the wiring before committing to a Google-native flow.

Pick a provider during Phase 2; the same choice carries into Phase 3.

---

## 7. Repository layout

Monorepo, shallow, **one deployable**:

```
claude-maps-agent/
├── mcp_server/         # FastMCP + Google Maps clients
│   ├── pyproject.toml
│   ├── server.py       # FastMCP entrypoint, 0.0.0.0:$PORT/mcp
│   ├── google_maps.py  # Places (New) + Routes clients
│   └── tests/
├── infra/
│   ├── Dockerfile      # container image for the MCP server
│   ├── service.yaml    # Cloud Run service config (optional)
│   └── deploy.sh       # wraps `gcloud run deploy` calls
├── reference_material/
├── instructions.txt    # original brief
├── plan.md             # this file
├── README.md
└── .gitignore
```

**Layout principles**
- Single `pyproject.toml`; flat layout under `mcp_server/` (no `src/` nesting, since the
  server isn't published as a library).
- All deployment config lives in `infra/`.

---

## 8. Development phases

Each phase has a single, testable exit criterion. **Don't move to the next phase until the
current one is demonstrably working.**

### Phase 1 — Local MCP server, no auth
- FastMCP server runs locally via stdio or HTTP.
- Both tools (`search_nearby_places`, `get_directions`) call live Google APIs successfully
  against the developer's API key.
- **Exit criterion:** running the server and pointing Claude Desktop at it via the MCP
  inspector returns correct results for both anchor use cases. **[New — concrete, demoable.]**

### Phase 2 — Local server with OAuth
- Add OAuth2 in front of the local server using whichever provider we plan to use on Cloud
  Run (Google Identity Platform / Firebase Auth, Auth0, or similar — see §6).
- **Exit criterion:** the server rejects unauthenticated calls and accepts a token from the
  chosen provider end-to-end.

### Phase 3 — Deploy to Google Cloud Run
- Containerize the MCP server (Dockerfile under `infra/`) and deploy to Cloud Run via
  `gcloud run deploy`.
- Wire OAuth in front of the Cloud Run service per the §6 decision.
- Inject the Google Maps API key from Google Secret Manager.
- Configure Claude mobile with the Cloud Run MCP endpoint as a custom connector.
- **Exit criterion:** the Claude mobile app, configured against the Cloud Run MCP endpoint,
  answers both anchor use cases.

---

## 9. Testing strategy **[New]**

The original brief did not specify testing. Recommended baseline:

- **Unit tests** in `mcp_server/tests/`. Mock the Google Maps API at the HTTP boundary (e.g.,
  with `respx` or recorded fixtures) so tests are hermetic.
- **One live smoke test** per tool, gated on an env var, that hits real Google APIs. Run it
  before each deploy.
- **Tool contract tests:** assert tool input/output schemas match what the MCP client expects.

---

## 10. Observability & cost control **[New]**

- Log every tool call with input shape, latency, and Google API response status. Cloud Run
  captures container stdout/stderr into Google Cloud Logging automatically.
- Surface Google API field masks in code (don't hide them in helpers) — they directly drive
  cost.
- Set Google Cloud daily quota caps.

---

## 11. Research to do before coding

Before writing code, review:
- Anthropic's MCP server best-practices guidance (skill: `claude-docs`).
- Google Cloud Run deployment contract — `PORT` env var, container requirements, request
  timeouts, authenticated invocations, and Secret Manager integration. (No pre-loaded skill;
  use Google's official Cloud Run docs.)
- Google Maps Places API (New) `searchNearby` and Routes API request/response shapes,
  required field masks, auth options (skill: `google-maps-docs`).

The two relevant Claude Code skills (`claude-docs`, `google-maps-docs`) are pre-loaded for
exactly this purpose.

---

## 12. Open questions to resolve

Collected from above so they're not lost:

1. **OAuth provider** for Phase 2 — Google Identity Platform / Firebase Auth vs. Auth0 vs. minimal local stub. (§6)
2. **Geocoding approach** — `searchText` with location bias vs. enabling Geocoding API. (§4.1)
3. **Travel-mode defaults** — should `travel_mode` be required, or default to `WALK`? (§4.1)

---

## 13. Suggested deltas vs. the original brief **[New]**

In one place, the substantive things this plan changes or adds beyond `instructions.txt`:

- **Collapsed the architecture to a single MCP server.** Per direction: Claude mobile is the
  only LLM in the system; the intermediary agent and Bedrock dependency are removed.
- **Switched cloud hosting from AWS AgentCore to Google Cloud Run.** The whole stack is now
  Google + Claude with no AWS dependency: hosting on Cloud Run, secrets in Google Secret
  Manager, logs in Google Cloud Logging.
- Disentangled the two auth boundaries (Google APIs vs. mobile→Cloud Run).
- Made tool input/output schemas explicit so they can be reviewed before coding.
- Called out **field masks** as a first-class concern (cost + correctness).
- Added geocoding as a real design choice rather than an implicit assumption.
- Added testing, observability, and cost-control sections.
- Added explicit, demoable exit criteria per development phase.
