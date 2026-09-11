# Building custom web frontends on Datacake (Next.js)

## Contents

- Ask before building
- Recommended stack
- Authentication architectures
- Project structure and data layer
- Page map
- Admin and white label tools
- Purpose-driven dashboards
- Data fetching, caching, polling and realtime
- Time zones and formatting
- Design guidance
- Snippets: server client, login action, proxy route, device list, KPI cards, history chart
- Generic mode (no token yet)
- Delivery checklist

Only scaffold a Next.js app when the user asked for a web app. For a script or analysis, stay with `analytics-recipes.md`.

## Ask before building

Collect (or confirm assumptions for) these before writing code; each changes the architecture:

1. Purpose and audience: internal operations, customer portal, public kiosk, sales demo? Which decisions should the screens support?
2. Sign-in model: (A) users log in with their Datacake account, (B) app serves one workspace through a single API user, (C) public dashboards only, or a mix.
3. Workspace(s) and products: one workspace or workspace picker; which products, tags and field identifiers matter (run `discover.py`).
4. Must-have pages and KPIs; alerts; history ranges; downlinks/set-value needed (write access)?
5. Branding: customer logo and colours if they have them, otherwise the Datacake default (`branding.md`: bundled assets, tokens, dark mode included); white label domains resolve branding at runtime. Languages, mobile usage.
6. Hosting (Vercel, Docker, on-prem) and whether a backend already exists.

Offer 2–3 dashboard alternatives keyed to the purpose (see table below) and let the user pick.

## Recommended stack

| Concern | Default | Escape hatch |
|---|---|---|
| Framework | Next.js (App Router, TypeScript, server components + server actions) | Remix/SvelteKit if the user prefers; same auth rules apply |
| Styling/UI | Tailwind CSS v4 + shadcn/ui new-york (`sidebar`, `card`, `table`, `badge`, `tabs`, `sheet`, `dialog`, `command`, `skeleton`, `sonner`), tokens and fonts from `branding.md`, `next-themes` for dark mode | any component library |
| Data fetching | server components for initial data, TanStack Query in client components for polling/pagination | SWR |
| GraphQL client | plain `fetch` wrapper (below) or `graphql-request`; optional `@graphql-codegen/cli` + `client-preset` against `reference/schema.graphql` for types | Apollo/urql if subscriptions-like caching is wanted (there are no subscriptions) |
| Validation | `zod` for env vars and form input | |
| Charts | `recharts` (line/area/bar, responsive) | `@nivo`, `echarts` for heatmaps |
| Dates | `date-fns` + `date-fns-tz` | `luxon` |
| Maps | `react-leaflet` or MapLibre with OpenStreetMap tiles | Google Maps |
| Auth session | httpOnly cookie holding the Datacake token, set by a server action | NextAuth Credentials provider wrapping `login` |

## Authentication architectures

**A. Users sign in with Datacake credentials** (customer/operator portals)
- Login form → server action calls the `login` mutation → store `token` in an httpOnly, `Secure`, `SameSite=Lax` cookie → redirect. Logout deletes the cookie.
- Every GraphQL call runs on the server (server components, server actions, route handlers) using the cookie token; the browser never sees it. Permissions are enforced by Datacake per user, so the app inherits workspace/device permissions for free.
- Workspace picker from `allWorkspaces`; remember the choice in a cookie or URL segment.

**B. One shared API user** (kiosks, embedded dashboards, public portals with curated data)
- Create an API user with read-only device access; token in `DATACAKE_TOKEN` env var on the server only.
- The app exposes its own routes/actions that run fixed queries; add your own auth (or none for public kiosks) in front.

**C. Public dashboards** (no backend secrets at all)
- Use `publicDevice(id:, token:)` and `dashboardPublicLink(publicLink: { id, token })` with the public link token, which is safe to embed; limited to semantics, role fields and dashboard data.

Admin and white label tools use model A only: organization administration (`organizations`, `organization.userRelationships`, invites across workspaces) needs a real user token; API users are workspace-scoped and have no organization rights. Gate navigation like the portal: organization section when `organization.permissions` contains `billing`, `members`, `manage_workspaces` or `whitelabel`; members pages when `workspace.myPermissions` contains `members`; white label pages when `user.whitelabelSites` is non-empty.

MUST NOT: call `api.datacake.co` from the browser with a personal or API user token. MUST: keep tokens in env vars/secret stores; validate env with zod at boot.

## Project structure and data layer

```
app/
  (auth)/login/page.tsx            # login form → server action
  (app)/layout.tsx                 # shell: sidebar, workspace switcher, user menu
  (app)/page.tsx                   # welcome / overview KPIs
  (app)/devices/page.tsx           # paginated device list (search, tags, online)
  (app)/devices/[id]/page.tsx      # device detail: current values, charts, meta
  (app)/dashboards/[purpose]/page.tsx
  api/graphql/route.ts             # optional proxy for client components (allow-listed operations)
lib/datacake/
  client.ts                        # server-only fetch wrapper
  operations.ts                    # GraphQL documents (strings) + TypeScript result types
  fields.ts                        # hardcoded identifiers per product (from discover.py)
  time.ts                          # period boundaries in the user's zone
  format.ts                        # units, numbers, relative time
components/
  devices/…  kpi/…  charts/…  layout/…
```

Data layer rules: one module owns the GraphQL documents; components receive typed props; identifiers per product come from `fields.ts`, never typed inline in components; every list query takes `page`/`pageSize`; every history query takes range + resolution from `time.ts`.

## Page map

| Page | Data | Notes |
|---|---|---|
| Login | `login` mutation | error message from `error`; OTP field only if 2FA |
| Welcome / overview | `allWorkspaces`, KPI header (`devicesFiltered` aggregates), recent activity (`orderBy: { lastHeard: DESC }`) | first screen after login |
| Device list | `devicesFiltered(page, pageSize, search, tags, online, orderBy)` with `roleFields` or one semantic per row | server pagination, URL-synced filters, tag chips from `allTags` |
| Device detail | `device(deviceId)` + `currentMeasurements(fieldNames)` + `history` per chart + `currentConfigurationValues` | tabs: Overview, History, Details; resolution selector |
| Purpose dashboard | semantic KPIs, per-tag aliases, alert lists, meter `change()` windows | see next section |
| Map | devices with `currentLocation`, zones | cluster markers, status colour |
| Alerts | `devicesFiltered` with thresholds; optionally `rulesNG` + `executionLogEntries` | counts first, paginated lists |
| Settings | workspace switch, time zone, units, refresh interval | store in cookie/localStorage |

## Admin and white label tools

For "a portal where our admins (or a customer's admin) manage organizations, workspaces and members". Queries and mutations by name are in `organizations-and-members.md`; read it before building. Sign-in model A; the operator's own permissions decide what is visible.

| Page | Data | Notes |
|---|---|---|
| Organizations | `MyOrganizations` (`organizations(permissionFilter:)` with `permissions`, `owner`, counts, quotas) | entry point; one card per organization; hide organizations without admin permissions |
| Organization admins | `OrganizationAdmins` (search, sort, `first`/`offset`) | add via `createUserOrganizationRelationships` (existing accounts only), edit with `updateUserOrganizationRelationships`, transfer ownership behind a confirmation |
| Workspaces | `OrganizationWorkspaces` (`memberCount`, `deviceCount`, `myPermissions`, `whitelabelSite`) | mark workspaces the operator cannot read (`myPermissions` lacks `members`); create with `addWorkspace(organizationId, brand)` |
| Members | `WorkspaceMembers` (members, invites, API users with device relationships) | tabs Members / Invites / API users; permission chips; `isOrganizationOwner` badge; never render `apiKey` |
| Member detail | `MemberDetail` + `DeviceAccess` | workspace permission toggles → `updateWorkspacePermissions` changeset; device grid → `setUserDevicePermissions` |
| Invite wizard | emails textarea, permission preset, device picker (`devicesFiltered` by tag), branding (`workspace.whitelabelSite` or `user.whitelabelSites`) | loop `addUserToWorkspace` per email (≤5 in flight), show "added" vs "invitation sent" per address |
| Move member | source `MemberDetail`, target workspace picker | add to target with mapped device relationships → verify → remove from source; explain the no-move-mutation caveat in the UI |
| White label users | `WhitelabelUsers` (search, `LAST_VISIT_DESC`) | entitlement-gated; link a user to their memberships via `OrganizationMemberDirectory` matched on email |
| Audit log | `WhitelabelAuditLog` (filter by `action`, user email) | paginated table, action badges, `details` expandable |
| SSO | `WhitelabelSso`, `attachSsoDomain`, `generateWorkosAdminPortalLink` | show DNS TXT record until `verified`; the portal link is single-use |

Rules: every write goes through a server action that re-checks `ok` and surfaces `extensions.code`; bulk actions render a per-row result list; removals and ownership transfer need a typed confirmation; `org-list` style directory pages deduplicate users by `user.id` and list their workspaces.

## Purpose-driven dashboards

| Purpose | KPI cards | Widgets | Queries |
|---|---|---|---|
| Environmental / indoor air quality | avg/max CO₂, avg temperature, avg humidity, rooms above 1000 ppm, offline count | per-floor cards (tag aliases), worst rooms table, 24 h CO₂ chart per room, comfort band indicator | `aggregatedNumericSemanticValue`, `devicesFiltered(co2: { gt })`, `history` per device |
| Energy and meters | consumption today / yesterday / month vs last month, total power now, top consumers | per-meter table (`change` windows), daily bar chart from `history(locf: true)` deltas, cost estimate | `currentMeasurement(fieldName).change(...)`, `history` 24h buckets, `aggregatedNumericSemanticValue(POWER, SUM)` |
| Asset tracking | devices in zones, entered/left today, moving vs idle, battery low | map with zones, event timeline, per-zone occupancy | `zones`, `devicesInZones`, `deviceZoneEvents`, `currentLocation` |
| Fleet health / operations | online %, offline list, low battery, weak signal, silent > 24 h, over quota | status table with `lastHeard`, battery histogram, product breakdown | `devicesFiltered(online:false)`, `battery { lt }`, `signal { lt }`, `lastHeard { lt }`, `isOverQuota` |
| Occupancy / people counting | occupied desks/rooms now, utilisation %, visitors today | floor plan or grid, hourly occupancy chart | boolean semantics counts, `PEOPLE_COUNT` `change`/`history` |
| Water, tanks, fill level | fill level min/avg, tanks below threshold, leaks detected, consumption | tank gauges, refill schedule | `fillLevel { lt }`, `waterLeakDetected { exact: true }`, `WATER_CONSUMPTION` `change` |
| Cold chain | temperature excursions, doors open, min/max per unit | timeline with thresholds, excursion list | `temperature { gt/lt }`, `doorOpened`, `minimum/maximum` windows |

Present the two or three most relevant rows as alternatives; build the chosen one first.

## Data fetching, caching, polling and realtime

- Initial render on the server (`fetch` with `next: { revalidate: 30 }` or `cache: "no-store"` for personalised data). Client components that poll use TanStack Query with `refetchInterval: 30_000` for current values, `60_000` for KPIs, none for history (refetch on range change).
- Keys: `["workspace", id, "devices", page, filters]`, `["device", id, "current"]`, `["device", id, "history", field, from, to, resolution]`.
- Batch KPIs with aliases in one document; keep history in separate requests (slow).
- Realtime: no GraphQL subscriptions. Polling is sufficient for most dashboards. For sub-second updates run a server-side MQTT bridge (Node `mqtt` client on `mqtts://mqtt.datacake.co:8883` with the API user token, topics `dtck/<product_slug>/<device_id>/<FIELD>`) and push to the browser via Server-Sent Events. Never connect the browser directly with a token.
- Errors: map `NOT_AUTHENTICATED` to a redirect to login, `NOT_AUTHORIZED` to an inline notice, network errors to retry with backoff; always show stale data with a "last updated" stamp rather than a blank screen.

## Time zones and formatting

- Detect the viewer's zone with `Intl.DateTimeFormat().resolvedOptions().timeZone`, send it to the server, and compute period windows there (`lib/datacake/time.ts`, see `queries-measurements.md`).
- Display with the viewer's zone and locale; keep API values in UTC.
- Units come from `field.unit` / `displayUnit`; round with `floatDigits`; show "–" for `null`.
- Relative freshness: "3 min ago" from `lastHeard`/`modified`; badge offline when `online` is false.

## Design guidance

Brand, tokens, fonts, the app shell and the login layout are defined in `branding.md` (Datacake default, customer swap, runtime white label). The rules below apply under any brand.

- Modern, calm dashboard look: shadcn `Card` grid for KPIs (value, unit, delta vs previous period, sparkline), dense `Table` for lists with status `Badge`, sticky filters, command palette (`Command`) for device search.
- Every data view has loading (`Skeleton`), empty ("No devices match"), error and stale states.
- Colour by state, not decoration: `--success` online, `--warning` stale/warning, `--destructive` critical, `--muted-foreground` offline (values in `branding.md`); never the brand colour for status. Dark mode is standard: class strategy, system default, toggle in the user menu.
- Responsive: KPI grid 1/2/4 columns, tables collapse to cards on small screens, charts full width.
- Accessibility: semantic headings, labelled controls, focus states, sufficient contrast, numbers formatted per locale.
- Keep the first version to the requested pages; add rules/downlinks/admin features only when asked.

## Snippets

Server-only client (`lib/datacake/client.ts`):

```typescript
import "server-only";
import { cookies } from "next/headers";

const ENDPOINT = "https://api.datacake.co/graphql/";

export class DatacakeError extends Error {
  constructor(message: string, public code?: string) { super(message); }
}

export async function datacake<T>(query: string, variables: Record<string, unknown> = {}, token?: string): Promise<T> {
  const auth = token ?? (await cookies()).get("dc_token")?.value ?? process.env.DATACAKE_TOKEN;
  if (!auth) throw new DatacakeError("Not signed in", "NOT_AUTHENTICATED");
  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Token ${auth}` },
    body: JSON.stringify({ query, variables }),
    cache: "no-store",
  });
  if (!res.ok) throw new DatacakeError(`Datacake HTTP ${res.status}`);
  const json = await res.json();
  if (json.errors?.length) {
    const first = json.errors[0];
    throw new DatacakeError(first.message, first.extensions?.code);
  }
  return json.data as T;
}
```

Login server action (`app/(auth)/login/actions.ts`):

```typescript
"use server";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { datacake } from "@/lib/datacake/client";

const LOGIN = `mutation Login($email: String!, $password: String!, $otp: String) {
  login(email: $email, password: $password, otpToken: $otp) { ok token error }
}`;

export async function loginAction(_prev: unknown, form: FormData) {
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");
  const otp = String(form.get("otp") ?? "") || undefined;
  const data = await datacake<{ login: { ok: boolean; token?: string; error?: string } }>(
    LOGIN, { email, password, otp }, "anonymous");
  if (!data.login.ok || !data.login.token) return { error: data.login.error ?? "Login failed" };
  (await cookies()).set("dc_token", data.login.token, {
    httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 30,
  });
  redirect("/");
}
```

(`login` itself does not require a token; passing a placeholder keeps the wrapper simple. Alternatively call `fetch` directly for login.)

Device list server component:

```typescript
import { datacake } from "@/lib/datacake/client";

const DEVICE_LIST = `query DeviceList($workspaceId: String!, $page: Int!, $pageSize: Int!, $search: String, $online: Boolean) {
  workspace(id: $workspaceId) {
    devicesFiltered(page: $page, pageSize: $pageSize, search: $search, online: $online, orderBy: { verboseName: ASC }) {
      total
      devices { id verboseName online lastHeard tags product { name }
        roleFields { role value datetime field { fieldName unit } } }
    }
  }
}`;

type DeviceRow = { id: string; verboseName: string; online: boolean; lastHeard: string | null; tags: string[] | null;
  product: { name: string } | null; roleFields: { role: string; value: string | null; field: { fieldName: string; unit: string | null } }[] | null };

export async function loadDevices(workspaceId: string, page: number, search?: string, online?: boolean) {
  const data = await datacake<{ workspace: { devicesFiltered: { total: number; devices: DeviceRow[] } } }>(
    DEVICE_LIST, { workspaceId, page, pageSize: 25, search: search || null, online: online ?? null });
  return data.workspace.devicesFiltered;
}
```

KPI cards (aliases, no device payload):

```typescript
const KPIS = `query Kpis($workspaceId: String!) {
  workspace(id: $workspaceId) {
    all: devicesFiltered(all: true) { total }
    online: devicesFiltered(online: true) {
      total
      temperature: aggregatedNumericSemanticValue(semantic: TEMPERATURE)
      co2: aggregatedNumericSemanticValue(semantic: CO2, aggregation: MAX)
    }
    lowBattery: devicesFiltered(battery: { lt: 20 }) { total }
  }
}`;
```

History to chart series (client util):

```typescript
export type HistoryRow = { time: string } & Record<string, number | string | null>;

export function parseHistory(raw: string | null): HistoryRow[] {
  return raw ? (JSON.parse(raw) as HistoryRow[]) : [];
}

// recharts data: [{ t: Date, TEMPERATURE: 21.4, HUMIDITY: 48 }]
export function toSeries(rows: HistoryRow[], fields: string[]) {
  // bucket values may arrive as numeric strings; coerce
  return rows.map((r) => ({ t: new Date(r.time), ...Object.fromEntries(fields.map((f) => [f, r[f] == null ? null : Number(r[f])])) }));
}

// consumption bars from a cumulative meter series fetched with locf: true
export function toDeltas(rows: HistoryRow[], field: string) {
  return rows.slice(1).map((r, i) => {
    const prev = Number(rows[i][field] ?? NaN), cur = Number(r[field] ?? NaN);
    const delta = cur - prev;
    return { t: new Date(r.time), value: Number.isFinite(delta) && delta >= 0 ? delta : null };
  });
}
```

Optional client proxy (`app/api/graphql/route.ts`) for TanStack Query in client components: accept `{ op: "deviceList", variables }`, look up the document in an allow-list on the server, run it with the cookie token, return `data`. Never forward arbitrary query strings from the browser.

## Generic mode (no token yet)

When the user cannot provide a token up front, build so that connecting later is a configuration change, not a rewrite:

- One config module, `lib/datacake/config.ts`: `WORKSPACE_ID`, refresh intervals, and an `identifiers` map per product with `TODO` placeholders derived from the archetype (cold chain: temperature + door; energy: meter reading + power; …). Everything else imports from it.
- Prefer product-agnostic reads: device lists and KPI cards via semantics (`numericSemanticField`, `aggregatedNumericSemanticValue`, boolean semantics) and `roleFields`; they work on any workspace without knowing identifiers.
- Resolve identifiers once per product at runtime for the few places that need them (history charts, `change()` windows): `products { id name measurementFields(active: true) { fieldName semantic role unit } }`, cached per product for the process lifetime, picking the field whose `semantic` (or `role`) matches; fall back to the config placeholders.
- Mock data provider behind the same interface as the server client (`DATACAKE_MOCK=1`): a few devices with realistic semantics and a synthetic history series, so pages, charts and empty states can be developed and demoed.
- Ship a `CONNECT.md` with the three steps: create a read-only API user (Members > API Users, view-only devices), set `DATACAKE_TOKEN`, run `python3 scripts/discover.py <workspace>` and paste the identifiers into `config.ts`. Then run the app against the workspace and remove the mock flag.
- Do not guess identifiers silently. Placeholders must be visibly marked, and the UI must show "–" for unresolved fields.

## Delivery checklist

- [ ] Archetype and connect-vs-generic decided; purpose, sign-in model, workspace and identifiers confirmed with the user (or placeholders visibly marked in generic mode)
- [ ] `.env.example` with `DATACAKE_TOKEN` (model B) and zod validation; `.env` ignored
- [ ] Tokens only server-side; cookie httpOnly; logout clears it
- [ ] Lists paginated (`pageSize` ≤ 50), KPIs via aggregates, history per device with sane resolution
- [ ] Loading/empty/error/stale states on every data view; "last updated" stamps
- [ ] Time zone handled explicitly; units from field definitions; `null` rendered as "–"
- [ ] Polling intervals ≥ 30 s; history cached per range
- [ ] Lighthouse-level basics: responsive, accessible, both themes checked
- [ ] Branding applied per `branding.md` (assets copied, tokens in `globals.css`, `brand` module, logo swaps with theme); assumption stated if Datacake default was used
- [ ] README with setup, env vars and how identifiers were chosen (`discover.py` output)
