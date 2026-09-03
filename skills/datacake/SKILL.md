---
name: datacake
description: Build tools, scripts, analytics and custom web or mobile frontends on the Datacake IoT platform using its GraphQL API (api.datacake.co). Covers the Datacake data model (organizations, workspaces, products, devices, fields, semantics, roles, tags, rules, dashboards, permissions), authentication, ready-made queries for device lists, current measurements, historical data, KPIs and cross-device aggregations, consumption and meter analysis, plus core mutations (device creation, data ingestion via REST/MQTT, downlinks, rules, members). Use whenever the user mentions Datacake, api.datacake.co, Datacake devices, workspaces, measurements, LoRaWAN sensor data in Datacake, or wants a dashboard, app, report or integration built on Datacake data.
license: MIT
metadata:
  version: 0.1.0
  api: https://api.datacake.co/graphql/
  docs: https://docs.datacake.de
---

# Datacake GraphQL API

Datacake is an IoT platform (LoRaWAN, cellular, API/MQTT devices) with one GraphQL endpoint: `https://api.datacake.co/graphql/`. This skill turns it into tools, analytics and custom frontends. `reference/…` and `scripts/…` below live next to this file; in Claude Code the absolute skill directory is `${CLAUDE_SKILL_DIR}` (use it when reading `reference/schema.graphql` or running scripts from another working directory).

## Mental model

```
Organization  → billing, quotas, admins, white label
└─ Workspace  → the tenant: members, devices, rules, dashboards, reports, exports, webhooks, zones
   └─ Product → template: field definitions, decoder, downlinks, dashboard layout, online timeout
      └─ Device → one product; own time-series data; tags, metadata, location, online/lastHeard
         └─ Field value → per device per field identifier (e.g. TEMPERATURE)
```

- A **field** is defined on the product; its **identifier** (`fieldName`, UPPER_SNAKE, immutable) is what every measurement query needs. `verboseFieldName` is only a label.
- **Semantics** (`TEMPERATURE`, `CO2`, `BATTERY`, `DOOR_OPENED`, …) label fields across products and enable filters, KPIs and aggregations. **Roles** (`PRIMARY`, `SECONDARY`, `DEVICE_BATTERY`, `DEVICE_SIGNAL`, `DEVICE_LOCATION`) mark the main fields of any product. **Tags** group devices.
- Members are users or **API users** (token-only); permissions exist per workspace (`devices`, `rules`, `members`, …) and per device (`edit_basics`, `edit_product`, `record_measurements`). A personal token carries everything its user may do.
- Rules, global dashboards, reports, exports, zones and webhooks are workspace-scoped. Full detail: `reference/platform-concepts.md`.

## Setup and first request

1. Token: personal (portal Account Settings > API Token) or an API user (Members > API Users) with minimal permissions. Expect it in `DATACAKE_TOKEN` (or `~/.datacake/token`); never write it into files or client bundles.
2. Header on every request: `Authorization: Token <token>`. Body: `{"query": "...", "variables": {...}}` via POST.
3. Verify: `python3 scripts/dc.py 'query { user { id email } }'` (a `null` user means the token is wrong).
4. Map the workspace before writing queries: `python3 scripts/discover.py` (lists workspaces), then `python3 scripts/discover.py <workspace-id-or-slug>` (products, field identifiers, units, roles, semantics, tags, sample devices).
5. Ad-hoc queries: `python3 scripts/dc.py --file q.graphql --vars '{"id": "..."}'`. Scripts need only Python 3.

## Essential queries

Workspaces the token can see:

```graphql
query { allWorkspaces { id name slug deviceCount myPermissions } }
```

Devices in a workspace (always paginate; `page` is 0-based):

```graphql
query Devices($workspaceId: String!, $page: Int!) {
  workspace(id: $workspaceId) {
    devicesFiltered(page: $page, pageSize: 25, orderBy: { verboseName: ASC }) {
      total
      devices { id verboseName serialNumber online lastHeard tags product { name } }
    }
  }
}
```

Field identifiers of a device's product:

```graphql
query Fields($deviceId: String!) {
  device(deviceId: $deviceId) {
    product { name measurementFields(active: true) { fieldName verboseFieldName fieldType unit role semantic } }
  }
}
```

Current values (identifiers, not semantics):

```graphql
query Current($deviceId: String!) {
  device(deviceId: $deviceId) {
    online lastHeard
    currentMeasurements(fieldNames: ["TEMPERATURE", "HUMIDITY"]) { value modified field { fieldName unit } }
  }
}
```

History (returns a JSON **string**; parse it):

```graphql
query History($deviceId: String!) {
  device(deviceId: $deviceId) {
    history(fields: ["TEMPERATURE"], timerangestart: "2026-03-01T00:00:00Z", timerangeend: "2026-03-02T00:00:00Z", resolution: "15m")
  }
}
```

KPIs across the fleet (platform aggregates, no device payload):

```graphql
query Kpis($workspaceId: String!) {
  workspace(id: $workspaceId) {
    online: devicesFiltered(online: true) {
      total
      avgTemperature: aggregatedNumericSemanticValue(semantic: TEMPERATURE)
      maxCo2: aggregatedNumericSemanticValue(semantic: CO2, aggregation: MAX)
    }
    lowBattery: devicesFiltered(battery: { lt: 20 }, pageSize: 10) {
      total
      devices { id verboseName battery: numericSemanticField(semantic: BATTERY) { value } }
    }
    offline: devicesFiltered(online: false) { total }
  }
}
```

## Decision guide

| Question | Answer |
|---|---|
| How do I read a device's values? | Known product → `currentMeasurements(fieldNames: [...])` with hardcoded identifiers. Mixed products → `roleFields`. Cross-product KPIs/filters → semantics (`numericSemanticField`, `devicesFiltered(temperature: {...})`, `aggregatedNumericSemanticValue`). |
| Which device list query? | `workspace.devicesFiltered` (filters, sorting, `total`, pages) for apps; `allDevices(inWorkspace:, searchTags:)` only for small fixed groups; `device(deviceId:)` for one device. |
| Counts vs details? | Counts and aggregates come from `devicesFiltered { total, aggregated… }` without `devices`; add `devices` only with `pageSize`. |
| Period statistics of one field? | `currentMeasurement(fieldName:) { average/minimum/maximum/sum/change(timeRangeStart, timeRangeEnd) }`, `historyStats`. Consumption from cumulative meters = `change`. |
| Charts? | `history(fields, timerangestart, timerangeend, resolution)`; resolution in compact form only (`15m`, `1h`, `24h`, `7d`, `raw`; word forms fall back to auto): ≤48 h `5m`–`15m`, 7 d `1h`, 30 d `6h`–`24h`, 1 y `24h`–`7d`; `locf: true` for meters; values may be numeric strings. One request per device. |
| Real-time? | No subscriptions: poll every 30–60 s, or bridge the MQTT broker (`dtck/<product_slug>/<device_id>/<FIELD>`) server-side. |
| Bulk historical data? | Exports (`createManualExport`) or `scripts/history_to_csv.py`, not thousands of `history` calls. |
| Writes? | REST record endpoint for values, `sendDownlink`, `updateDevice`, `createRuleNG`, … see `reference/mutations.md`; check permissions and confirm destructive actions. |

## Hard rules

1. MUST paginate every device list (`pageSize` ≤ 50 with measurements, ≤ 100 for ids/names). NEVER compute KPIs by downloading all devices; use `aggregatedNumericSemanticValue`, `aggregatedBooleanSemanticCount`, `total`, `change/average/minimum/maximum`.
2. Identifiers for `currentMeasurements`/`currentMeasurement`/`history`; semantics only in `devicesFiltered` filters, `numericSemanticField`/`booleanSemanticField` and aggregates. Both semantic field accessors return objects, so always select `{ value }`. There is no semantic history.
3. `history`, `historyNg`, `historyStats`, `metadata`, `dashboardData`, `deviceFolders`, `product.dashboards` are `JSONString`: parse before use, stringify before sending.
4. Times are UTC ISO 8601; ranges are start-inclusive, end-exclusive; convert local day/week/month boundaries (user's time zone) before querying; `change()` for "today" = local midnight → next local midnight.
5. Run `scripts/discover.py` (or read `product.measurementFields`) once, then hardcode identifiers per product in a single module. Do not discover fields on every request.
6. Tokens never reach browsers or app bundles: backend proxy / server components / httpOnly cookie, or an API user with least privilege. Never print or commit tokens.
7. Handle `null` (device lacks the semantic, no data, no permission) and partial `errors`; show "–", not 0.
8. Before building a frontend, ask about purpose, users, sign-in model, products/identifiers and required pages; propose dashboard variants. Do not scaffold Next.js or Expo projects unless the user asked for a web or mobile app.
9. Write operations: verify the token's `myPermissions` first, select `ok` and the error field, confirm with the user before deleting or moving anything, use `dryRun` where available.
10. Validate every GraphQL document against `reference/schema.graphql` when unsure (`grep -n "^type DeviceType" -A 100 reference/schema.graphql`).

## Workflows

**A. Analytics or script** (ad-hoc question, report, data pull)
1. Confirm workspace and token; run `discover.py` to get ids, identifiers, units, semantics, tags.
2. Choose the cheapest source: aggregates/`change` for KPIs, `history` per device for series, Exports for bulk.
3. Compute local period boundaries in the user's time zone; state them in the answer.
4. Run queries with `dc.py` or a short script (`reference/analytics-recipes.md`); save CSV via `history_to_csv.py` if the user wants a file.
5. Report numbers with units and the time window; mention gaps, offline devices and retention limits.

**B. Custom web frontend** (`reference/frontend-nextjs.md`)
1. Ask: purpose/audience, sign-in model (user login vs single API user vs public links), workspace(s), products and identifiers, pages and KPIs, branding, hosting.
2. Propose 2–3 dashboard variants keyed to the purpose (environmental, energy/meters, asset tracking, fleet health, occupancy, cold chain) and get a choice.
3. Architecture: Next.js App Router + TypeScript + Tailwind + shadcn/ui; GraphQL only server-side; login via `login` mutation into an httpOnly cookie; typed operations module; identifiers module.
4. Build in this order: login → workspace/welcome → device list (paginated, filters) → device detail (current + history) → purpose dashboard (aggregates) → extras.
5. Verify: paginated lists, aggregates for KPIs, resolution table respected, loading/empty/error/stale states, time zone handling, no tokens client-side.

**C. Mobile app** (`reference/mobile-expo.md`)
1. Ask about platforms, distribution, sign-in model, offline needs, push notifications.
2. Expo + Expo Router + TanStack Query + `expo-secure-store` for the user's token; single API user tokens stay on a backend.
3. Screens: login, workspace, device list, device detail, KPI dashboard, map, settings.

**D. Write operations** (`reference/mutations.md`)
1. Identify the mutation and its input type in the schema; check `workspace.myPermissions` / `device.myPermissions`.
2. Show the user the exact payload; for destructive actions confirm and prefer `dryRun`.
3. Execute, check `ok`/error, re-query to confirm the new state.

## Reference index

| Read when | File |
|---|---|
| You need the meaning of any Datacake concept, permission, plan, rule, dashboard, export, claiming vs moving | `reference/platform-concepts.md` |
| Auth, request format, errors and ErrorCode, pagination styles, scalars/JSONString, time handling, limits, troubleshooting | `reference/api-basics.md` |
| Listing/filtering/sorting devices, product and field discovery, role fields, tags/metadata/folders, members, public devices | `reference/queries-devices.md` |
| Current values, time-range statistics, `history` and resolution, meters/consumption (`change`), local time boundaries | `reference/queries-measurements.md` |
| Semantic catalogue, semantic filters, aggregations, KPI query patterns, sorting by semantic | `reference/semantics-and-kpis.md` |
| Creating devices/fields, recording data, downlinks, members/API users, rules, dashboards, exports, zones, webhooks | `reference/mutations.md` |
| Signature of any root query or mutation, enum values, key type fields, grep recipes | `reference/schema-map.md` (then `reference/schema.graphql`) |
| Web app architecture, auth flows, page map, purpose-driven dashboards, snippets | `reference/frontend-nextjs.md` |
| Mobile app architecture and snippets | `reference/mobile-expo.md` |
| Scripts, bulk history, consumption analysis, fleet health, pandas, exports | `reference/analytics-recipes.md` |

Scripts (Python 3, no dependencies): `scripts/dc.py` (run queries, `--login`), `scripts/discover.py` (workspace map), `scripts/history_to_csv.py` (history → CSV with local time), `scripts/fetch_schema.py` (refresh schema and schema map).

## Keeping the skill current

The API evolves (new semantics, root queries, mutations). Run `python3 scripts/fetch_schema.py --check` to see what changed since the bundled schema, and `python3 scripts/fetch_schema.py` to refresh `reference/schema.graphql` and the generated blocks of `reference/schema-map.md`. Platform documentation: https://docs.datacake.de (every page is also available as Markdown by appending `.md` to its URL; index at https://docs.datacake.de/llms.txt).
