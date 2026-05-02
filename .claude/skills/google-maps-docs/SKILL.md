---
name: google-maps-docs
description: Read Google documentation for this project — Google Maps Platform (Places API New `searchNearby` / `searchText`, Routes API `computeRoutes`) **and Google Cloud Run** (container contract, deploying with `gcloud run deploy`, request authentication, Secret Manager integration). Use when designing or implementing the FastMCP tools, when figuring out Maps request/response shapes, field masks, API-key vs OAuth, pricing/quota, enabling APIs in Google Cloud, or when planning/executing the Cloud Run deployment (Phase 3).
---

# Google Maps Platform + Google Cloud Run documentation

Local reference material lives in `ref/google/`. Read these files first — they are the canonical source for this project. If a topic is not covered locally, fetch the upstream URL listed below and, when useful, save a trimmed copy back into `ref/google/` so future sessions have a local cache.

## Local files

- `ref/google/places_api_overview.md` — Places API (New) overview.
- `ref/google/places_nearby_search.md` — `places.searchNearby` request/response, field masks.
- `ref/google/compute_routes_api.md` — Routes API `computeRoutes` request body, headers, traffic-aware routing.
- `ref/google/host_mcp_servers_on_cloud_run.md` — Cloud Run deployment contract for MCP servers (PORT env var, container requirements, request timeouts, authenticated invocations, Secret Manager integration). **Start here for Phase 3 deployment work.**

## Primary upstream URLs (WebFetch these)

### Places API (New) — Nearby Search
- Overview: `https://developers.google.com/maps/documentation/places/web-service/op-overview`
- Nearby Search (New): `https://developers.google.com/maps/documentation/places/web-service/nearby-search`
- Place data fields / FieldMask: `https://developers.google.com/maps/documentation/places/web-service/data-fields`
- Place types (for `includedTypes` filter): `https://developers.google.com/maps/documentation/places/web-service/place-types`
- Migration from legacy Places: `https://developers.google.com/maps/documentation/places/web-service/migrate-nearby`

### Routes API
- Overview: `https://developers.google.com/maps/documentation/routes/overview`
- Compute Routes: `https://developers.google.com/maps/documentation/routes/compute_route_directions`
- Travel modes & traffic-aware routing: `https://developers.google.com/maps/documentation/routes/traffic-model`
- Field masks (required): `https://developers.google.com/maps/documentation/routes/choose_fields`

### Auth, setup, billing
- Get an API key: `https://developers.google.com/maps/documentation/places/web-service/get-api-key`
- Enable APIs in Google Cloud: `https://developers.google.com/maps/documentation/places/web-service/cloud-setup`
- API key restrictions / security: `https://developers.google.com/maps/api-security-best-practices`

### Google Cloud Run
- Cloud Run landing: `https://cloud.google.com/run`
- Docs index: `https://cloud.google.com/run/docs`
- Container runtime contract (PORT, request timeouts, signal handling): `https://cloud.google.com/run/docs/container-contract`
- Deploying a service: `https://cloud.google.com/run/docs/deploying`
- `gcloud run deploy` reference: `https://cloud.google.com/sdk/gcloud/reference/run/deploy`
- Request authentication / IAM (`--no-allow-unauthenticated`, ID tokens): `https://cloud.google.com/run/docs/authenticating/overview`
- Configure secrets from Secret Manager: `https://cloud.google.com/run/docs/configuring/services/secrets`
- Secret Manager docs: `https://cloud.google.com/secret-manager/docs`

## Project-specific notes

- This project uses the **new** Places API (`places.searchNearby`), not the legacy Nearby Search. When fetching docs, prefer pages titled "(New)" or under `/places/web-service/`. Avoid the legacy `/places/web-service/search-nearby` endpoint.
- Both Places (New) and Routes API **require a `X-Goog-FieldMask` header** on every request — there is no default field set. Always include it in the FastMCP tool implementation.
- Scope is single-user (the user's personal Google account), so a restricted **API key** is sufficient — OAuth is not required for the Google APIs themselves. (The OAuth in this project is between Claude and the MCP server, not between the MCP server and Google.)

## How to use

1. Before implementing a Google Maps tool, WebFetch the relevant endpoint doc above and record the exact request body, required headers (especially `X-Goog-FieldMask`), and response shape.
2. Save trimmed copies of the most-used pages into `reference_material/google_maps/` (e.g., `nearby_search_new.md`, `routes_compute.md`) so subsequent reads are cheap.
3. When writing setup instructions for the user (per `instructions.txt`), pull the exact "Enable API" steps from the cloud-setup page above.
