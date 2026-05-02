# Google Maps MCP Server

> Personal, OAuth-protected Google Maps access for any MCP client — Claude
> Mobile / Desktop / Web, ChatGPT, MCP Inspector, anything that speaks the
> Model Context Protocol.

A small FastMCP server that bridges your favorite LLM to the Google Maps
Platform — Places API (New) `searchText` and the Routes API `computeRoutes` —
hosted in **your own** Google Cloud account, gated by **your own** Google sign-in.

## Quickstart

One command to install, one to remove, free tier covers single-user usage.

```bash
git clone https://github.com/morelandjs/google-maps-mcp
cd google-maps-mcp
python install.py
```

The installer walks you through every step and prints the MCP endpoint URL when
done. ~10 minutes; one short browser detour for OAuth setup.

---

## Why

LLMs are great at synthesis but terrible at live data. *"What time should I
leave to be at JFK by 6pm?"* needs current transit schedules. *"What are the
top-rated bookstores in Soho?"* needs current Google ratings, not training-corpus
recall.

This MCP server gives any compatible client deterministic access to Google's data
with two tools:

| Tool | Use case |
|---|---|
| `search_nearby_places` | "What's around here?" / "Best ramen in the East Village" / "Coffee within a 5-min walk" |
| `get_route` | "How long to walk to the bridge?" / "When should I leave for JFK?" / "What's the best transit route?" |

The server itself is a thin, deterministic bridge — no LLM logic on the server
side. The model in your client app does all the prose; this just hands back
clean JSON.

---

## Architecture

```
MCP-capable client (Claude Mobile/Desktop/Web, ChatGPT, MCP Inspector, ...)
       │  (MCP over Streamable HTTP, OAuth2)
       ▼
Maps MCP Server   (Google Cloud Run)        ← Deterministic, no LLM
       │
       ▼
Google Maps APIs  (Places New, Routes)
```

- **Hosting:** Google Cloud Run, scale-to-zero. $0 idle.
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
| Artifact Registry | 0.5 GB storage | $0.10/GB-month |
| Places API (New) | Maps Platform free tier (see [pricing](https://mapsplatform.google.com/pricing/)) | per-call by SKU |
| Routes API | shares the same Maps Platform free tier | per-call by SKU |

**For single-user usage you should expect $0/month.** The installer creates a
restricted API key (Places + Routes only) and the Maps Platform free tier covers
far more requests than one human would generate. If you want belt-and-suspenders,
set a daily quota cap in the GCP console under **APIs & Services → Quotas**.

---

## What `install.py` does to your Google account

Full transparency on every state-changing operation, in order:

| # | Operation | Why |
|---|---|---|
| 1 | `gcloud auth login` | sign you in |
| 2 | `gcloud projects create <id>` (if new) | container for all the resources below |
| 3 | Confirm billing account linked (browser if needed) | required by GCP for any non-trivial API |
| 4 | `gcloud services enable` for 7 APIs | Places, Routes, Cloud Run, Cloud Build, Secret Manager, Artifact Registry, API Keys |
| 5 | `gcloud services api-keys create` | restricted Maps API key (Places + Routes only) |
| 6 | `gcloud secrets create + versions add` × 4 | Maps key, OAuth client ID/secret, allowlist |
| 7 | `gcloud secrets add-iam-policy-binding` × 4 | Cloud Run runtime SA gets read access |
| 8 | `gcloud run deploy --source .` | builds container via Cloud Build, deploys |

The OAuth consent screen + OAuth Client ID still require a manual web-console
visit (Google has no API for either) — install.py prints exact click-paths
and validates the values you paste back.

It does **not** touch any other resources in your Google account, modify your
existing IAM, or set any organization-level policies.

---

## Tools exposed

### `search_nearby_places`

Find places matching a free-text query, near a coordinate or in a named area.

```json
{
  "query": "independent bookstores",
  "area_name": "Soho, Manhattan"
}
```

Returns up to 10 places with name, address, lat/lng, rating, review count, price
level, place type, weekday hours, recent reviews, phone number, place ID, and a
Google Maps link.

### `get_route`

Compute a route between two points. Supports `WALK` and `TRANSIT`.

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
`FEWER_TRANSFERS` for transit (fewer connections, simpler routes).

Both tools are 100% deterministic — same inputs, same outputs (modulo Google's
own data refresh).

---

## Install options

```bash
python install.py                              # interactive, default everything
python install.py --project-id my-project-id   # use a specific project
python install.py --region europe-west1        # different region
python install.py --allowed-emails a@x.com,b@x.com   # multiple users
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

Removes Cloud Run service, all 4 secrets, the Maps API key, and the Cloud Build
Artifact Registry repo. The OAuth Client + consent screen require web-console
deletion; uninstall.py prints the exact URLs.

---

## Connecting your MCP client

After install completes, copy the printed `https://...run.app/mcp` URL.

- **Claude Mobile / Desktop / Web** — Settings → Connectors → Add custom
  connector → paste URL → sign in with an allowlisted Google account when
  prompted.
- **MCP Inspector** — Transport: Streamable HTTP, URL: paste, Connect.
- **ChatGPT** — when MCP custom connectors land, same pattern.

The first connection bounces you through Google's OAuth flow. Tokens are stored
on the client side; the server only validates them.

---

## Customizing the server

Most users won't need to. If you want to:

- **Add tools / change field masks** — `mcp_server/server.py` and
  `mcp_server/google_maps.py`. 34 hermetic tests cover the shape; 2 live smoke
  tests hit real Google APIs (`RUN_LIVE_TESTS=1 pytest`).
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
│   ├── server.py         # FastMCP entrypoint, two tools, OAuth wiring
│   ├── google_maps.py    # Places (New) + Routes HTTP clients
│   └── tests/            # 34 hermetic + 2 live smoke
├── infra/
│   ├── deploy.sh         # gcloud run deploy wrapper (used by install.py)
│   └── setup-secrets.sh  # secret push + IAM grants (used by install.py)
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
- Google Maps Platform — for the underlying APIs and the $200/month free tier
  that makes single-user usage a no-op cost-wise.
