---
name: datacake
description: Build tools, scripts, analytics and custom web or mobile frontends on the Datacake IoT platform using its GraphQL API (api.datacake.co). Covers the data model (organizations, workspaces, products, devices, fields, semantics, roles, tags, rules, dashboards, permissions), authentication, ready-made queries for device lists, current and historical measurements, KPIs, cross-device aggregations and meter consumption, core mutations (device creation, data ingestion via REST/MQTT, downlinks), the Rule Engine NG (list, create and update rules, conditions, actions, notification templates, logs), and the administration model (organization admins, workspace members, invites, permissions, API users, white label sites, audit logs) for admin consoles and bulk onboarding. Use whenever the user mentions Datacake, api.datacake.co, Datacake devices, workspaces, members, measurements, rules or alerts, LoRaWAN data in Datacake, or wants a dashboard, app, report, admin tool, alerting rule or integration on Datacake data.
license: MIT
metadata:
  version: 0.3.1
  api: https://api.datacake.co/graphql/
  docs: https://docs.datacake.de
---

# Datacake GraphQL API

Datacake is an IoT platform (LoRaWAN, cellular, API/MQTT devices) with one GraphQL endpoint: `https://api.datacake.co/graphql/`. This skill turns it into tools, analytics and custom frontends. `reference/…`, `scripts/…` and `assets/…` below live next to this file; in Claude Code the absolute skill directory is `${CLAUDE_SKILL_DIR}` (use it when reading `reference/schema.graphql`, copying `assets/brand/` files or running scripts from another working directory).

## Start here

Pick the mode from the request before doing anything else:

| Request looks like | Do |
|---|---|
| Concrete task ("query for…", "explain products", "fix this mutation", "chart this device") | Answer it with the references; use the scripts if a token is present. No intake. |
| Open-ended ("build me something on Datacake", `/datacake` without details, "what can I do with my sensor data") | Run the intake below, then follow the matching workflow. |

Intake: ask both questions at once (as a structured choice when the agent supports it). If the user does not answer, state the assumption and continue.

1. **What do you want to build?** Cold-chain monitoring · Fleet health / operations · Energy & meters · Indoor air quality · Asset tracking with zones · Occupancy / people counting · Water, tanks & fill level · Alerting & automation (rules, notifications, scheduled downlinks) · Admin or white label tool (organizations, workspaces, members, invites) · Analysis or script · Something else (describe it). Each archetype maps to a row of the purpose table in `reference/frontend-nextjs.md` (KPIs, widgets, queries, semantics).
2. **Connect a workspace, or start generic?**
   - *Connect*: the user provides a token via `DATACAKE_TOKEN` or `~/.datacake/token`. Recommend a read-only API user (Members > API Users, view-only device access) over a personal token, which carries every workspace of that user. Then `scripts/discover.py` yields real product identifiers, semantics, tags and sample devices, and results can be tested live.
   - *Generic*: no token yet. Build against `reference/schema.graphql` with one config module (workspace id, identifiers), semantics and role fields instead of hardcoded identifiers, mock data for the UI, and finish with the connect steps. Never block on the token.

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
- People come in four kinds: **organization admins** (`organization.userRelationships`, permissions `members`, `billing`, `whitelabel`, `manage_workspaces`, `create_workspaces`; one owner), **workspace members** (`workspace.userRelationships`), **API users** and **pending invites** (`invitedUsers`, resolved when the invitee signs up). Admins are not members and vice versa; `organization.permissions` and `workspace.myPermissions` describe the caller. **White label sites** brand the portal for customers and carry their own user list, audit log and SSO. Full model and admin recipes: `reference/organizations-and-members.md`.
- Rules, global dashboards, reports, exports, zones and webhooks are workspace-scoped. Full detail: `reference/platform-concepts.md`. A rule (Rule Engine NG) is scope (one product, optional device/tag filter, execution mode) + triggers + optional conditions + actions with notification templates; everything about it: `reference/rules-ng.md`.

## Setup and first request

1. Token: personal (portal Account Settings > API Token) or an API user (Members > API Users) with minimal permissions. Expect it in `DATACAKE_TOKEN` (or `~/.datacake/token`); never write it into files or client bundles.
2. Header on every request: `Authorization: Token <token>`. Body: `{"query": "...", "variables": {...}}` via POST.
3. Verify: `python3 scripts/dc.py 'query { user { id email } }'` (a `null` user means the token is wrong).
4. Map the workspace before writing queries: `python3 scripts/discover.py` (lists workspaces), then `python3 scripts/discover.py <workspace-id-or-slug>` (products, field identifiers, units, roles, semantics, tags, sample devices).
5. Ad-hoc queries: `python3 scripts/dc.py --file q.graphql --vars '{"id": "..."}'`. Scripts need only Python 3.
6. No token available: do not stop and do not search the filesystem for one. Continue in generic mode (see Start here): schema-valid queries, placeholder identifiers in one config module, mock data, and a short list of what the user must provide later (token, workspace id). `discover.py` prints exactly this message when it finds no token.

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
| Alerts, notifications, scheduled downlinks? | Rule Engine NG: list with `workspace.rulesNG`, read with `ruleNG(id)`, write with `createRuleNG`/`updateRuleNG`; one product per rule, field/device/downlink UUIDs from `scripts/rules.py ids`, templates such as `{{ triggering_device['measurements']['CO2'] }}`, logs via `executionLogEntries`. All in `reference/rules-ng.md`. |
| Writes? | REST record endpoint for values, `sendDownlink`, `updateDevice`, `createRuleNG`, … see `reference/mutations.md`; check permissions and confirm destructive actions. |

## Hard rules

1. MUST paginate every device list (`pageSize` ≤ 50 with measurements, ≤ 100 for ids/names). NEVER compute KPIs by downloading all devices; use `aggregatedNumericSemanticValue`, `aggregatedBooleanSemanticCount`, `total`, `change/average/minimum/maximum`.
2. Identifiers for `currentMeasurements`/`currentMeasurement`/`history`; semantics only in `devicesFiltered` filters, `numericSemanticField`/`booleanSemanticField` and aggregates. Both semantic field accessors return objects, so always select `{ value }`. There is no semantic history.
3. `history`, `historyNg`, `historyStats`, `metadata`, `dashboardData`, `deviceFolders`, `product.dashboards` are `JSONString`: parse before use, stringify before sending.
4. Times are UTC ISO 8601; ranges are start-inclusive, end-exclusive; convert local day/week/month boundaries (user's time zone) before querying; `change()` for "today" = local midnight → next local midnight.
5. Run `scripts/discover.py` (or read `product.measurementFields`) once, then hardcode identifiers per product in a single module. Do not discover fields on every request.
6. Tokens never reach browsers or app bundles: backend proxy / server components / httpOnly cookie, or an API user with least privilege. Never print or commit tokens.
7. Handle `null` (device lacks the semantic, no data, no permission) and partial `errors`; show "–", not 0.
8. Before building a frontend, run the Start here intake (archetype, connect vs generic), then ask about users, sign-in model, products/identifiers and required pages; propose dashboard variants. Do not scaffold Next.js or Expo projects unless the user asked for a web or mobile app. Branding is never a blocker: without customer branding, build with the Datacake default (`reference/branding.md`: bundled logo files in `assets/brand/`, official colour tokens, shadcn new-york look with dark mode) and state that assumption.
9. Write operations: verify the token's `myPermissions` first, select `ok` and the error field, confirm with the user before deleting or moving anything, use `dryRun` where available.
10. Validate every GraphQL document against `reference/schema.graphql` when unsure (`grep -n "^type DeviceType" -A 100 reference/schema.graphql`).

## Workflows

**A. Analytics or script** (ad-hoc question, report, data pull)
1. Confirm workspace and token; run `discover.py` to get ids, identifiers, units, semantics, tags. Without a token: draft the queries against the schema, hand the user the `discover.py`/`dc.py` commands to run, and continue from their output.
2. Choose the cheapest source: aggregates/`change` for KPIs, `history` per device for series, Exports for bulk.
3. Compute local period boundaries in the user's time zone; state them in the answer.
4. Run queries with `dc.py` or a short script (`reference/analytics-recipes.md`); save CSV via `history_to_csv.py` if the user wants a file.
5. Report numbers with units and the time window; mention gaps, offline devices and retention limits.

**B. Custom web frontend** (`reference/frontend-nextjs.md`)
1. Intake (Start here): archetype and connect-vs-generic; then purpose/audience, sign-in model (user login vs single API user vs public links), workspace(s), products and identifiers, pages and KPIs, branding (customer files, or Datacake default from `reference/branding.md` and `assets/brand/`; white label domains resolve branding at runtime), hosting.
2. Propose 2–3 dashboard variants keyed to the purpose (environmental, energy/meters, asset tracking, fleet health, occupancy, cold chain) and get a choice.
3. Architecture: Next.js App Router + TypeScript + Tailwind + shadcn/ui (new-york, tokens and dark mode from `reference/branding.md`); GraphQL only server-side; login via `login` mutation into an httpOnly cookie; typed operations module; identifiers module. In generic mode: semantics + role fields for lists and KPIs, identifiers resolved once per product at runtime, mock data provider (`reference/frontend-nextjs.md`, "Generic mode").
4. Build in this order: login → workspace/welcome → device list (paginated, filters) → device detail (current + history) → purpose dashboard (aggregates) → extras.
5. Verify: paginated lists, aggregates for KPIs, resolution table respected, loading/empty/error/stale states, time zone handling, no tokens client-side.

**C. Mobile app** (`reference/mobile-expo.md`)
1. Ask about platforms, distribution, sign-in model, offline needs, push notifications.
2. Expo + Expo Router + TanStack Query + `expo-secure-store` for the user's token; single API user tokens stay on a backend. App icon, splash and colours from `reference/branding.md` unless the customer supplies their own.
3. Screens: login, workspace, device list, device detail, KPI dashboard, map, settings.

**D. Write operations** (`reference/mutations.md`)
1. Identify the mutation and its input type in the schema; check `workspace.myPermissions` / `device.myPermissions`.
2. Show the user the exact payload; for destructive actions confirm and prefer `dryRun`.
3. Execute, check `ok`/error, re-query to confirm the new state.

**E. Admin or white label tool** (`reference/organizations-and-members.md`)
1. Sign-in is always a real user (frontend model A); API users cannot administer organizations. Ask which scope the operator has: organization admin, workspace admin, or both, and whether a white label site is involved.
2. Discover: `python3 scripts/discover.py --orgs` (organizations, caller permissions, workspaces with member counts), then `python3 scripts/members.py list <workspace>` or `org-list <organizationId>`.
3. Gate pages by `organization.permissions` (organization section) and `workspace.myPermissions` (`members` for member pages); white label users and audit log need `whitelabel` plus the entitlement.
4. Build reads first (organizations, workspaces, members, invites, audit log), then writes: invite (`addUserToWorkspace`, `brand` for branded emails), permissions (`updateWorkspacePermissions` changeset, `setUserDevicePermissions`), organization admins, remove. Bulk operations are loops in code (no bulk invite, no move mutation); `scripts/members.py invite|move|remove` run them with a dry run by default.
5. Reading members needs `members` in each workspace; report unreadable workspaces instead of failing. Confirm removals and ownership transfers with the user.

**F. Alerting and automation (rules)** (`reference/rules-ng.md`)
1. Clarify: what should trigger (measurement threshold, offline, schedule, zone), for which product and devices (all, tags, explicit), who gets notified how (email, SMS, push, webhook) or which downlink/set value runs, and whether reminders and an all-clear are wanted.
2. Check `workspace.myPermissions` (`rules`), `features` (`RULE_ENGINE`) and `entitlementRulesQuotaRemaining`; resolve ids with `python3 scripts/rules.py ids <workspace> --product "<name>"` (field UUIDs for conditions, device ids, downlinks, push recipients). Without a token: draft the `CreateRuleNGInputType` payload with placeholders and hand over the commands.
3. Build the payload: explicit `executionMode`, one product, triggers, conditions with client-generated UUID ids (`hysteresis: 0` on static number/range operands only), actions with all three `fireWhen…` flags plus cooldown/limit, templates with `{{ triggering_device['measurements'][...] }}` and only the filters `round`, `datetime`, `json` (no `{% %}` tags). Reuse a recipe from `reference/rules-ng.md` where one fits.
4. Show the plan, then `python3 scripts/rules.py create <workspace> --file rule.json` (dry run) and `--execute`; or `createRuleNG` from code. For changes read the rule first (`rules.py get`), then `update` with only the changed fields.
5. Verify with `rules.py logs <rule-id> --since 24h --trace` (or `executionLogEntries`): conditions evaluate as expected, actions fire once per event (become hot / stay hot / become cold), no flood; then hand over the rule id and how to disable it.

## Reference index

| Read when | File |
|---|---|
| You need the meaning of any Datacake concept, permission, plan, rule, dashboard, export, claiming vs moving | `reference/platform-concepts.md` |
| Auth, request format, errors and ErrorCode, pagination styles, scalars/JSONString, time handling, limits, troubleshooting | `reference/api-basics.md` |
| Listing/filtering/sorting devices, product and field discovery, role fields, tags/metadata/folders, members, public devices | `reference/queries-devices.md` |
| Current values, time-range statistics, `history` and resolution, meters/consumption (`change`), local time boundaries | `reference/queries-measurements.md` |
| Semantic catalogue, semantic filters, aggregations, KPI query patterns, sorting by semantic | `reference/semantics-and-kpis.md` |
| Creating devices/fields, recording data, downlinks, members/API users, dashboards, exports, zones, webhooks; rule mutations in short | `reference/mutations.md` |
| Rule Engine NG: list/read queries, ids a rule needs, execution modes, triggers, conditions, actions, create/update/delete semantics, template variables and filters, execution logs, recipes, pitfalls | `reference/rules-ng.md` |
| Organizations and their admins, workspace members, invites, permissions, API users, white label users, audit log, SSO; recipes for mass invite, moving members, offboarding, admin UI gating | `reference/organizations-and-members.md` |
| Signature of any root query or mutation, enum values, key type fields, grep recipes | `reference/schema-map.md` (then `reference/schema.graphql`) |
| Web app architecture, auth flows, page map, purpose-driven dashboards, snippets | `reference/frontend-nextjs.md` |
| Default Datacake branding (logo files in `assets/brand/`, colour tokens light/dark, Geist, shadcn new-york look), customer branding swap, runtime white label branding (`branding`, `brandingForDomain`) | `reference/branding.md` |
| Mobile app architecture and snippets | `reference/mobile-expo.md` |
| Scripts, bulk history, consumption analysis, fleet health, pandas, exports | `reference/analytics-recipes.md` |

Scripts (Python 3, no dependencies): `scripts/dc.py` (run queries, `--login`), `scripts/discover.py` (workspace map; `--orgs` for organizations and their workspaces), `scripts/members.py` (list/export members, invite, move, remove; writes need `--execute`), `scripts/rules.py` (rule ids, list, get, export, create, update, enable/disable, delete, logs; writes need `--execute`), `scripts/history_to_csv.py` (history → CSV with local time), `scripts/fetch_schema.py` (refresh schema and schema map).

## Keeping the skill current

The API evolves (new semantics, root queries, mutations). Run `python3 scripts/fetch_schema.py --check` to see what changed since the bundled schema, and `python3 scripts/fetch_schema.py` to refresh `reference/schema.graphql` and the generated blocks of `reference/schema-map.md`. Platform documentation: https://docs.datacake.de (every page is also available as Markdown by appending `.md` to its URL; index at https://docs.datacake.de/llms.txt).
