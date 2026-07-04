# Manual install walkthrough

> **For most users, the one-command installer is the right path:**
> ```bash
> python install.py
> ```
> It walks you through every step in this document end-to-end, deploys to Cloud Run,
> and gets you a working MCP endpoint in your own GCP account in ~10 minutes.
> See `install.py --help` for flags, or `python uninstall.py` to tear it all down.

This document is for people who want to do the same setup **by hand** — useful when
debugging the installer, when you want to understand each step, or when you're
intentionally diverging (different region, custom project layout, etc.).

It covers Phase 1 (local MCP server with a real API key) and gestures at Phase 2
(local OAuth) and Phase 3 (Cloud Run deploy). The full Phase 2/3 setup is automated
by `install.py`; the deeper manual recipe lives in `infra/setup-secrets.sh` +
`infra/deploy.sh`.

The Phase 1 exit criterion is: **both tools (`search_nearby_places`, `get_route`)
return live, correct data when called from MCP Inspector or Claude Desktop.**

---

## 1. Google Cloud setup (one-time)

You need a Google Cloud project, two enabled APIs, an API key, and billing set up. ~10 minutes.

### 1.1 Create / pick a project

1. Open the [Cloud Console](https://console.cloud.google.com/) signed in as your Google account.
2. Top bar → project picker → **New Project**. Name it something like `google-maps-mcp`.
3. Make sure that project is selected for the rest of the steps (the project name shows in the top bar).

### 1.2 Enable a billing account

Google requires a billing account on file even though you'll stay in the free tier:

1. Hamburger menu → **Billing** → **Link a billing account**.
2. Add a payment method if you don't have one.
3. Stay defensive: the free credit covers more than this project will use, but you should still cap quota in step 1.5.

### 1.3 Enable the two APIs we need

In the Cloud Console search bar, search for and click **Enable** on each:

1. **Places API (New)** — used by `search_nearby_places`.
2. **Routes API** — used by `get_route`.

> Do **not** enable the legacy "Places API" (without "(New)") — we use the new endpoint. You also do **not** need to enable the Geocoding API; the MCP server uses Places `searchText` with a location bias instead.

### 1.4 Create an API key

1. **APIs & Services → Credentials → Create Credentials → API key**.
2. Copy the key. Treat it like a password.
3. Click **Edit API key** on the row that just appeared and **restrict** it:
   - **API restrictions → Restrict key →** select *Places API (New)* and *Routes API*.
   - Under **Application restrictions** you can leave "None" for local dev. (For Phase 3, we'll restrict by IP / Cloud Run service.)
4. Save.

### 1.5 Set a daily quota cap (cheap insurance)

1. **APIs & Services → Quotas & System Limits**.
2. For both *Places API (New)* and *Routes API*, find the per-day request quota and set it to a low number (e.g. 500/day) while developing. You can raise it later.

---

## 2. Local repo setup

You're already inside the repo at `~/Hacking/google-maps-connector`. The Phase 1 code lives in `mcp_server/`.

### 2.1 Add your API key

```bash
cd mcp_server
cp .env.example .env
# edit .env and replace YOUR_API_KEY with the key you created above
```

`.env` is gitignored — it will not be committed. **Never paste your real key into any other file in this repo, including this one.**

### 2.2 Install Python dependencies

You need Python 3.11+ (you have 3.13 already). Either toolchain works:

**Option A — `uv` (recommended, fast):**
```bash
# Install uv if you don't have it: https://docs.astral.sh/uv/
brew install uv

cd mcp_server
uv sync --extra dev    # creates .venv/ and installs runtime + test deps
```

**Option B — plain venv + pip:**
```bash
cd mcp_server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2.3 Run the unit tests

```bash
cd mcp_server
.venv/bin/pytest        # or: uv run pytest
```

You should see `22 passed, 2 skipped`. The 22 are hermetic — they mock Google's APIs with `respx`, so they pass without a real key or internet. The 2 skipped are the live smoke tests (see §2.4).

### 2.4 (Optional) Run the live smoke tests

Two tests, one per tool, that hit real Google APIs with your real key. They cost two API calls (well inside any sane quota) and exist to catch the class of regressions hermetic mocks can't — Google renaming a field, drift between docs and reality, key restrictions getting misconfigured.

```bash
cd mcp_server
RUN_LIVE_TESTS=1 .venv/bin/pytest tests/test_live_smoke.py -v
```

You should see both tests pass. Run them once now to confirm your setup, and again before any future deploy. They're skipped automatically when the env var isn't set, so the everyday `pytest` run stays fast and offline.

---

## 3. Run the MCP server

Two transports. Use whichever your client wants.

### 3.1 Streamable HTTP (default — what Cloud Run will eventually serve)

```bash
cd mcp_server
.venv/bin/python server.py
```

Server listens on `http://localhost:8000/mcp`. Set `PORT=…` to override. Ctrl-C to stop.

### 3.2 Stdio (drop-in for Claude Desktop's local-server config)

```bash
cd mcp_server
.venv/bin/python server.py --stdio
```

The process reads JSON-RPC frames on stdin and writes responses on stdout. You won't normally invoke this directly — Claude Desktop spawns it for you (see §4.2).

---

## 4. Verify both tools work end-to-end

### 4.1 (Easiest) MCP Inspector

`@modelcontextprotocol/inspector` is the official MCP test client. It speaks the protocol and gives you a UI to call each tool with arbitrary arguments.

1. Start the server in one terminal: `.venv/bin/python server.py`.
2. In another terminal, run the inspector:
   ```bash
   npx @modelcontextprotocol/inspector
   ```
3. In the inspector UI:
   - **Transport Type:** *Streamable HTTP*
   - **URL:** `http://localhost:8000/mcp`
   - Click **Connect**.
4. You should see three tools listed: `search_nearby_places`, `get_route`, and `get_events`.

**Phase 1 acceptance run** — call each tool and confirm the JSON looks reasonable:

- `search_nearby_places` with `queries=["bookstores"]`, `area_name="Soho, Manhattan"`, `max_results=5` → expect markdown sections of NYC bookstores with addresses, ratings, and map links.
- `search_nearby_places` with `queries=["coffee"]`, `coordinates={"lat": 40.7223, "lng": -74.0030}`, `radius_m=500` → expect coffee shops near that point.
- `search_nearby_places` with `queries=["wine bars", "comedy clubs"]`, `area_name="West Village, Manhattan"` → expect a merged, deduplicated list where each place has a `Matched` line naming the queries that surfaced it.
- `get_route` with `origin="Times Square, New York"`, `destination="Brooklyn Bridge"`, `travel_mode="WALK"` → expect a `distance_m`, `duration_s`, `polyline`, and a list of `steps`.
- `get_route` with `origin="JFK Airport"`, `destination="Penn Station, NYC"`, `travel_mode="TRANSIT"`, `arrival_time="2026-04-27T18:00:00Z"` → expect a `departure_time` derived from the arrival.

If all four return sensible data, **Phase 1 is done.**

Optionally exercise the event-discovery composition too (needs `GEMINI_API_KEY`
in `.env` and `playwright install chromium` in the venv):

- `search_nearby_places` with `queries=["live music venues"]`, `area_name="Williamsburg, Brooklyn"`, `max_results=3` → note each result's Website line.
- `get_events` with `websites=[<two or three of those URLs>]` → expect a dict keyed by URL where each value is a JSON list of structured events (`event_title_derived`, `start_date`, `start_time`, `price`, ...), `[]` if the site has no events page, or `{"error": ...}` for bot-walled sites. The sites scrape concurrently in one shared browser; the whole call takes 20 seconds to ~3 minutes (longer when Gemini rate-limit windows are being waited out).

### 4.2 (Optional) Claude Desktop with stdio

If you'd rather drive it from Claude Desktop:

1. Edit `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

   ```json
   {
     "mcpServers": {
       "Google Maps": {
         "command": "/absolute/path/to/google-maps-connector/mcp_server/.venv/bin/python",
         "args": [
           "/absolute/path/to/google-maps-connector/mcp_server/server.py",
           "--stdio"
         ],
         "env": {
           "GOOGLE_MAPS_API_KEY": "your-key-here"
         }
       }
     }
   }
   ```

   Use absolute paths. The `env` block overrides `.env` only if set; you can also leave it out and rely on the `.env` file (Claude Desktop runs `command` from your home dir, so make sure `dotenv` finds it — easier to just put the key in `env` here).

2. Quit and relaunch Claude Desktop.
3. In a new chat, you should see a tool indicator. Try: *"What bookstores are near Soho in Manhattan?"* and *"How long would it take to walk from Times Square to the Brooklyn Bridge?"*

> Claude Desktop does **not** support Streamable HTTP local servers directly today, which is why this path uses stdio. The Cloud Run deployment in Phase 3 is the one that Claude mobile (and Desktop's "custom connector" feature) will reach over HTTPS.

---

## 5. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `RuntimeError: GOOGLE_MAPS_API_KEY is not set` at startup | `.env` missing or you're running from the repo root — `cd mcp_server` first, or export the env var. |
| `places:searchText returned 403` | API key not enabled for Places API (New), or API restrictions don't include it. Re-check §1.4. |
| `places:searchText returned 400` with "field mask" in the body | The server should be sending the mask; if you've edited `google_maps.py`, verify `X-Goog-FieldMask` is still set. |
| `computeRoutes returned 400` "REQUEST_DENIED" | Routes API not enabled, or not allowed by the key restriction. |
| Empty `places: []` for an area-name search | Try a more specific area (e.g. `"Soho, Manhattan, NY"` instead of just `"Soho"`). The query is appended literally to your search text. |
| Inspector shows tools but calls hang | Server is up but the MCP session probably needs a fresh connection — click *Reconnect* in the inspector. |
| `get_events` raises `GEMINI_API_KEY is not set` | Create a free key at https://aistudio.google.com/apikey and add it to `.env` (locally) or Secret Manager (Cloud Run). |
| `get_events` fails with a Playwright launch error | Browser not installed in the venv — run `.venv/bin/playwright install chromium`. |
| `get_events` returns `{"error": "...bot-challenge wall..."}` for a site | Expected for Cloudflare-protected sites, especially from datacenter IPs; the agent should report that venue as unchecked. Other sites in the same call are unaffected. |

---

## 6. What happens next

This walkthrough only covers Phase 1 (local server, no auth). To get a deployed,
OAuth-protected MCP endpoint, two paths:

- **Recommended:** run `python install.py` from the repo root. It picks up where this
  walkthrough leaves off, walks through OAuth setup (one browser visit), pushes secrets
  to Google Secret Manager, and deploys to Cloud Run.
- **Manual:** the helper scripts in `infra/` cover the gcloud parts:
  - `./infra/setup-secrets.sh` — push secrets to Secret Manager (reads from `.env`).
  - `./infra/deploy.sh` — wraps `gcloud run deploy --source .`.
  You'll still need to set up the OAuth consent screen + Client ID in the GCP web
  console manually (see the install.py output for click-paths).

`python uninstall.py` tears the whole thing down when you're ready to clean up.
