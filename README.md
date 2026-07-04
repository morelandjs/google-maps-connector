# Google Maps MCP Server

> Personal, OAuth-protected Google Maps access for any MCP client — Claude
> Mobile / Desktop / Web, ChatGPT, MCP Inspector, anything that speaks the
> Model Context Protocol.

A small FastMCP server that bridges your favorite LLM to the Google Maps
Platform — Places API (New) `searchText`, the Routes API `computeRoutes`, and
live event discovery (headless scraping of venue websites + Gemini extraction)
— hosted in **your own** Google Cloud account, gated by **your own** Google
sign-in.

## Quickstart

One command to install, one to remove.

```bash
git clone https://github.com/morelandjs/google-maps-mcp
cd google-maps-mcp
python install.py
```

The installer creates the whole project, mints both API keys, deploys, and
prints the MCP endpoint URL. ~10 minutes; the only manual browser step is the
OAuth consent screen (billing too, if you don't already have an account).

---

## Why

LLMs are great at synthesis but terrible at live data. *"What time should I
leave to be at JFK by 6pm?"* needs current transit schedules. *"What are the
top-rated bookstores in Soho?"* needs current Google ratings, not training-corpus
recall.

This MCP server gives any compatible client live access to Google's data
with three tools:

| Tool | Use case |
|---|---|
| `search_nearby_places` | "What's around here?" / "Best ramen in the East Village" / "Coffee within a 5-min walk" — each result includes the place's `website` |
| `get_route` | "How long to walk to the bridge?" / "When should I leave for JFK?" / "What's the best transit route?" |
| `get_events` | Given a list of venue website URLs, scrape them concurrently and return each venue's scheduled events as structured JSON |

The two Maps tools are a thin, deterministic bridge — no LLM logic on the
server side. `get_events` goes further: it visits each venue's website
with a headless browser, finds its events/calendar page, and extracts
structured events (title, date, time, price, description, keywords) with
Gemini Flash. Event discovery is a composition your agent drives: *"What's
happening in Williamsburg this weekend?"* becomes one `search_nearby_places`
call ("live music venues and bars") followed by ONE `get_events` call
carrying all the returned websites — the server scrapes them concurrently as
tabs in a single shared browser, so ten sites take about as long as the
slowest one (20 seconds to ~3 minutes), and each site comes back as either its events
or a per-site error (bot wall, social-media URL) so the agent can say what
it could and couldn't verify. The agent then filters by date, joins events
back to place details, and ranks. In every case the model in your client
app does all the prose; the server hands back clean JSON.

---

## Architecture

```
MCP-capable client (Claude Mobile/Desktop/Web, ChatGPT, MCP Inspector, ...)
       │  (MCP over Streamable HTTP, OAuth2)
       ▼
Maps MCP Server   (Google Cloud Run, single instance)
       ├────────────► Google Maps APIs (Places New, Routes) — deterministic
       └────────────► get_events: headless Chromium scrape → Gemini extraction
```

- **Hosting:** Google Cloud Run, scale-to-zero, pinned to one instance (OAuth
  session state lives in a mounted GCS bucket that isn't cross-instance
  consistent). $0 idle.
- **Auth:** Google OAuth 2.1 + PKCE via FastMCP's `OAuthProxy`. Single-tenant
  email allowlist enforced server-side — only emails you list during install
  can authenticate, even after token validation succeeds.
- **Secrets:** Google Secret Manager. Nothing committed to the image.
- **Region:** `us-central1` by default; override with `--region`.

---

## What it costs

| Resource | What you get free | What you'd pay if you exceed |
|---|---|---|
| Cloud Run | 2M requests/month, 360K GiB-sec memory, 180K vCPU-sec | ~$0.40 per 1M requests beyond free |
| Secret Manager | 6 secret versions, 10K accesses/month | $0.06 per secret version/month after |
| Cloud Build | 120 build-minutes/day | $0.003/min after |
| Artifact Registry | 0.5 GB storage | $0.10/GB-month — **the ~1.4 GB image lands here → ~$0.10/month** |
| Places API (New) | Maps Platform free tier (see [pricing](https://mapsplatform.google.com/pricing/)) | per-call by SKU |
| Routes API | shares the same Maps Platform free tier | per-call by SKU |
| Gemini API (AI Studio key, `get_events` only) | **20 requests/day/model — only ~1-2 event searches/day** | with billing enabled on the key: ~$0.05–0.15 per event search ([pricing](https://ai.google.dev/pricing)) |

**Realistic single-user cost: ~$0.10/month standing, plus Gemini usage for
event searches.** Places/Routes free caps cover far more searching and routing
than one human generates, and Cloud Run scale-to-zero is $0 idle. The one real
decision is Gemini: the free tier's 20 requests/day supports only a search or
two (each event search costs ~10–16 model calls), so enable billing on the
AI Studio key if you'll use event discovery. Belt-and-suspenders: set daily
quota caps in **APIs & Services → Quotas**.

---

## What `install.py` does to your Google account

Full transparency on every state-changing operation, in order:

| # | Operation | Why |
|---|---|---|
| 1 | `gcloud auth login` | sign you in |
| 2 | `gcloud projects create <id>` (if new) | container for all the resources below |
| 3 | Link a billing account (browser only if you have none) | required by GCP for any non-trivial API |
| 4 | `gcloud services enable` for 8 APIs | Places, Routes, Cloud Run, Cloud Build, Secret Manager, Artifact Registry, API Keys, Generative Language |
| 5 | `gcloud services api-keys create` × 2 | restricted Maps key (Places + Routes) and Gemini key (Generative Language) |
| 6 | `gcloud secrets create + versions add` × 5 | Maps key, Gemini key, OAuth client ID/secret, allowlist |
| 7 | `gcloud secrets add-iam-policy-binding` × 5 | Cloud Run runtime SA gets read access |
| 8 | `gcloud storage buckets create` | OAuth-state bucket (mounted into the service) |
| 9 | `gcloud run deploy --source .` | builds container via Cloud Build, deploys |

You'll also be asked two personalization questions: your results **language**
(all output localized/translated to it) and your default **travel mode** for
`get_route`.

The OAuth consent screen + Client ID are the one remaining manual step (Google
has no API for either) — install.py prints exact click-paths and validates the
values you paste back.

It does **not** touch any other resources in your Google account, modify your
existing IAM, or set any organization-level policies.

---

## Tools exposed

### `search_nearby_places`

Find places matching one or more free-text queries, near a coordinate or in a
named area. Multiple queries run concurrently and merge (deduplicated, with a
"Matched" line per place) — the intended pattern for vague intents: decompose
"fun date night ideas" into concrete categories like `["wine bars", "comedy
clubs", "live music venues"]`.

```json
{
  "queries": ["independent bookstores"],
  "area_name": "Soho, Manhattan"
}
```

Returns up to 10 places as markdown sections with name, address, lat/lng,
rating, rating count, place type, weekday hours, AI-generated place and
review summaries, phone number, website, place ID, and a Google Maps link.
Lines with no data are omitted.

### `get_route`

Compute a route between two points. Supports `WALK`, `TRANSIT`, and `DRIVE`
(traffic-aware). Omit `travel_mode` to use the default you chose at install
time (`DEFAULT_TRAVEL_MODE`).

```json
{
  "origin": "Penn Station, New York",
  "destination": "JFK Airport",
  "travel_mode": "TRANSIT",
  "arrival_time": "2026-04-30T18:00:00-04:00"
}
```

Returns distance, traffic-aware duration, derived departure/arrival times,
encoded polyline, and per-step navigation instructions. Defaults to
`FEWER_TRANSFERS` for transit; `arrival_time` is TRANSIT-only (a Routes API
limitation).

`search_nearby_places` and `get_route` are 100% deterministic — same inputs,
same outputs (modulo Google's own data refresh).

### `get_events`

Given a list of venue website URLs (e.g. the `Website` lines from
`search_nearby_places`), scrape each one and return its scheduled events. The
agent orchestrates: decompose intent → `search_nearby_places` → curate the best
5–8 venues → one `get_events` call.

```json
{ "websites": ["https://venue-a.example", "https://venue-b.example"] }
```

Returns a dict keyed by URL; each value is either a list of events
(`event_title_derived`, `start_date`, `start_time`, `price`, `keywords`,
`emoji`, `event_page_url`) or `{"error": "..."}` (bot wall, social-media URL,
extraction failure). Sites scrape concurrently as tabs in one headless browser;
a batch takes 20 seconds to ~3 minutes. Foreign-language sites are translated
to your configured language during extraction. Not deterministic (it reads live
websites through an LLM).

---

## Install options

```bash
python install.py                              # interactive, default everything
python install.py --dry-run                    # print the plan + costs, then exit
python install.py --project-id my-project-id   # use a specific project
python install.py --region europe-west1        # different region
python install.py --allowed-emails a@x.com,b@x.com   # multiple users
python install.py --language es                # results language (BCP-47)
python install.py --travel-mode DRIVE          # default get_route mode
python install.py --reset                      # discard saved state
python install.py --help                       # see all options
```

State is saved at `~/.config/google-maps-mcp/install-state.json`. If a step
fails, fix the issue and re-run — it picks up where it left off.

---

## Uninstall

```bash
python uninstall.py                  # surgical: deletes resources, leaves project
python uninstall.py --yes            # skip per-resource confirmations
python uninstall.py --delete-project # nuke the entire project (GCP holds it
                                     # recoverable for 30 days before final purge)
```

Removes the Cloud Run service, all 5 secrets, both API keys (Maps + Gemini),
the OAuth-state bucket, and the Cloud Build Artifact Registry repo. The OAuth
Client + consent screen require web-console deletion; uninstall.py prints the
exact URLs.

---

## Connecting your MCP client

After install completes, copy the printed `https://...run.app/mcp` URL.

- **Claude Mobile / Desktop / Web** — Settings → Connectors → Add custom
  connector → paste URL → **leave the OAuth Client ID/Secret fields blank**
  (the server registers clients dynamically) → sign in with an allowlisted
  Google account when prompted.
- **MCP Inspector** — Transport: Streamable HTTP, URL: paste, Connect.
- **ChatGPT** — when MCP custom connectors land, same pattern.

The first connection bounces you through Google's OAuth flow. The server keeps
its OAuth session state in the mounted GCS bucket; sessions survive restarts and
you re-authenticate at most every 30 days.

---

## Customizing the server

Most users won't need to. If you want to:

- **Add tools / change field masks** — `mcp_server/server.py` and
  `mcp_server/google_maps.py`. ~80 hermetic tests cover the shape; live smoke
  tests hit real Google/Gemini APIs (`RUN_LIVE_TESTS=1 pytest`). `ux_test.py`
  drives real headless Claude sessions against the local server for end-to-end
  UX checks.
- **Use a different IdP** — replace `GoogleProvider` in `_build_auth_provider`.
  FastMCP ships providers for Auth0, GitHub, Workos, etc.
- **Run locally instead of on Cloud Run** — see `INSTRUCTIONS.md` for the
  manual walkthrough. The same code runs locally with no auth (in dev) or with
  OAuth (matching production).

---

## Project layout

```
.
├── install.py            # one-command installer
├── uninstall.py          # companion teardown
├── Dockerfile            # multi-stage Python 3.13-slim, non-root
├── mcp_server/           # the actual MCP server
│   ├── server.py         # FastMCP entrypoint, three tools, OAuth wiring
│   ├── google_maps.py    # Places (New) + Routes HTTP clients
│   ├── gemini.py         # Gemini client (event extraction + link-pick)
│   ├── scraper.py        # headless Playwright: scrape venue event pages
│   ├── events_pipeline.py# get_events orchestration (batch scrape + extract)
│   └── tests/            # ~80 hermetic + live smoke
├── infra/
│   ├── deploy.sh         # gcloud run deploy wrapper (used by install.py)
│   └── setup-secrets.sh  # secret push + IAM grants (used by install.py)
├── ux_test.py            # headless-Claude end-to-end UX harness
├── INSTRUCTIONS.md       # manual install walkthrough
└── README.md             # this file
```

---

## Caveats

- **OAuth consent screen stays in "Testing" mode** by default — fine for personal
  use, but tokens expire after 7 days. If you flip to "In production" in the GCP
  console for longer-lived tokens, the server-side allowlist is what keeps
  random Google users from authenticating.
- **Test users on the consent screen also gate access.** Any email you want to
  authenticate must be both (a) on `GOOGLE_OAUTH_ALLOWED_EMAILS` and (b) listed
  as a test user on the consent screen.
- **The service runs as a single instance** (`--max-instances=1`) on purpose:
  OAuth session state lives in the mounted GCS bucket, which isn't
  cross-instance consistent, so scaling out causes intermittent 401s and an
  auth loop. Fine for a personal single-user server; to scale out, move OAuth
  state to a shared KV backend (Firestore/Redis) first.
- **Cloud Run cold starts** add ~2-5s to the first request after idle. Set
  `--min-instances=1` on the service if this bothers you (~$5/month for a hot
  instance).
- **No write tools.** The server only reads from Google Maps. No
  reservations, no listings creation, etc. — those need separate APIs and
  separate IAM scopes.

---

## License

MIT. See `LICENSE`.

---

## Acknowledgments

- [FastMCP](https://github.com/jlowin/fastmcp) for the OAuth proxy and
  GoogleProvider that made the auth wiring trivial.
- [Anthropic](https://anthropic.com) for the MCP spec and the Claude clients
  that drove this project.
- Google Maps Platform — for the underlying APIs whose free tier covers
  single-user place search and routing, and Gemini for cheap event extraction.
