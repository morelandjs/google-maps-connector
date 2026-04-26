---
name: google-maps-docs
description: Read Google Maps Platform documentation, specifically the Places API (New) Nearby Search and the Routes API. Use when designing or implementing the FastMCP tools that wrap `places.searchNearby` or compute directions/travel time, when figuring out request/response shapes, field masks, authentication (API key vs OAuth), pricing/quota, or enabling these APIs in Google Cloud.
---

# Google Maps Platform documentation

Local reference material lives in `reference_material/google_maps/`. **This directory is currently empty** — fetch upstream docs with WebFetch and, when useful, save trimmed copies into `reference_material/google_maps/` so future sessions have a local cache.

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

## Project-specific notes

- This project uses the **new** Places API (`places.searchNearby`), not the legacy Nearby Search. When fetching docs, prefer pages titled "(New)" or under `/places/web-service/`. Avoid the legacy `/places/web-service/search-nearby` endpoint.
- Both Places (New) and Routes API **require a `X-Goog-FieldMask` header** on every request — there is no default field set. Always include it in the FastMCP tool implementation.
- Scope is single-user (the user's personal Google account), so a restricted **API key** is sufficient — OAuth is not required for the Google APIs themselves. (The OAuth in this project is between Claude and the MCP server, not between the MCP server and Google.)

## How to use

1. Before implementing a Google Maps tool, WebFetch the relevant endpoint doc above and record the exact request body, required headers (especially `X-Goog-FieldMask`), and response shape.
2. Save trimmed copies of the most-used pages into `reference_material/google_maps/` (e.g., `nearby_search_new.md`, `routes_compute.md`) so subsequent reads are cheap.
3. When writing setup instructions for the user (per `instructions.txt`), pull the exact "Enable API" steps from the cloud-setup page above.
