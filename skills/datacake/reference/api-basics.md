# Datacake GraphQL API basics

## Contents

- Endpoint and tooling
- Authentication and tokens
- Making requests (curl, JavaScript, Python, dc.py)
- Query techniques (variables, aliases, fragments)
- Responses, errors and ErrorCode
- Pagination styles
- Scalars and JSON strings
- Time handling
- Limits and performance
- Schema and introspection
- Troubleshooting

## Endpoint and tooling

- Single endpoint for queries and mutations: `https://api.datacake.co/graphql/` (POST, JSON). No subscriptions.
- GraphiQL with a "Docs" browser lives at the same URL; paste a token in its Authorization field to explore.
- Introspection is public. The bundled `reference/schema.graphql` is the offline copy; refresh it with `python3 scripts/fetch_schema.py`.
- REST exists only for ingest: `POST https://api.datacake.co/v1/devices/<deviceId>/record/?batch=true` (see `mutations.md`).
- Official Python wrapper (optional): https://github.com/datacake/python-datacake-api-wrapper. Any GraphQL client works (fetch, graphql-request, Apollo, urql, gql).

## Authentication and tokens

Header on every request:

```
Authorization: Token <token>
```

| Token kind | Where | Scope | Use for |
|---|---|---|---|
| Personal access token | Portal: Account Settings > API Token, or `user { apiKey }` | everything the user may do in every workspace they belong to | development, personal scripts |
| API user token | Workspace > Members > API Users (`addApiUser`, returns `apiUser { apiKey }`) | only the workspace permissions and devices granted to that API user | backends, kiosks, integrations, anything shared |
| Login-issued token | `login` mutation | same as the personal token of that user | apps where people sign in with Datacake credentials |
| Public dashboard token | public link `token` (+ optional password) | one device dashboard or one global dashboard | unauthenticated viewers via `publicDevice` / `dashboardPublicLink` |

Login with email and password (OTP only when 2FA is enabled). The `token` field is what the `Authorization: Token` header expects; `accessToken`/`refreshToken` are JWTs used by Datacake's own frontends.

```graphql
mutation Login($email: String!, $password: String!, $otp: String) {
  login(email: $email, password: $password, otpToken: $otp) {
    ok
    token
    error
    user { id email firstName lastName primaryWorkspace { id name slug } }
  }
}
```

Verify a token: `query { user { id email isApiuser } }`. Without a token the API answers normally with `user: null`; a malformed or revoked token is rejected with **HTTP 401 and an empty body** (no GraphQL envelope), so clients must handle both cases.

Rules that MUST hold in generated code:
- Never embed a personal or API token in browser or mobile bundles. Put it in a backend (route handler, server action, serverless function) and proxy GraphQL calls, or let users log in and keep the token in an httpOnly cookie or secure storage.
- Prefer an API user with the minimum permissions and explicit device list for any shared deployment.
- Treat tokens like passwords: environment variables or secret stores, never source files; `.env` in `.gitignore`.

## Making requests

Body shape: `{"query": "...", "variables": {...}, "operationName": "..."}`.

curl:

```bash
curl -s https://api.datacake.co/graphql/ \
  -H "Authorization: Token $DATACAKE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"query { allWorkspaces { id name slug deviceCount } }"}'
```

JavaScript (Node 18+, or server-side in Next.js; never with a personal token in the browser):

```javascript
export async function datacake(query, variables = {}, token = process.env.DATACAKE_TOKEN) {
  const res = await fetch("https://api.datacake.co/graphql/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Token ${token}` },
    body: JSON.stringify({ query, variables }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  if (json.errors?.length) throw new Error(json.errors.map((e) => e.message).join("; "));
  return json.data;
}
```

Python (standard library):

```python
import json, os, urllib.request

def datacake(query, variables=None):
    req = urllib.request.Request(
        "https://api.datacake.co/graphql/",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Token " + os.environ["DATACAKE_TOKEN"]},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]
```

Bundled CLI (no dependencies): `python3 scripts/dc.py 'query { user { id } }'`, `--file q.graphql --vars '{"id":"..."}'`, `--login you@example.com`. Token from `DATACAKE_TOKEN` or `~/.datacake/token`.

## Query techniques

- Declare variables with the exact schema types: `workspace(id:)` takes `String`, `device(deviceId:)` takes `String`, semantic filters take `FieldSemantic`, `change(timeRangeStart:)` takes `DateTime!`, `history(timerangestart:)` takes `String`. Copy types from `reference/schema.graphql`.
- Aliases let one request compute several KPIs or lists:

```graphql
query Overview($workspaceId: String!) {
  workspace(id: $workspaceId) {
    online: devicesFiltered(online: true) { total }
    offline: devicesFiltered(online: false) { total }
    lowBattery: devicesFiltered(battery: { lt: 20 }) { total }
  }
}
```

- Fragments keep device selections consistent across queries:

```graphql
fragment DeviceCard on DeviceType {
  id verboseName serialNumber online lastHeard tags
  product { id name }
}
query Cards($workspaceId: String!) {
  workspace(id: $workspaceId) {
    devicesFiltered(pageSize: 20, page: 0, orderBy: { verboseName: ASC }) {
      total
      devices { ...DeviceCard }
    }
  }
}
```

- Request only the fields you render. Wide device selections (all measurements, product definitions) on long lists are the main cause of slow requests.

## Responses, errors and ErrorCode

Standard GraphQL envelope: `{"data": {...}, "errors": [...]}` with HTTP 200 for executed operations (including permission errors); documents that fail validation come back as **HTTP 400** with an `errors` array, and a bad token as HTTP 401 with no body. Partial data is possible: a field you may not read becomes `null` with an entry in `errors`; check both. Lookups of ids the token cannot see return `null` without an error (`workspace`, `device`, `currentMeasurement`).

Error entries carry `message`, `path`, `locations` and usually `extensions.code` with an `ErrorCode`:

| ErrorCode | Meaning | Typical fix |
|---|---|---|
| `NOT_AUTHENTICATED` | no or invalid token | check header format `Token <token>` |
| `NOT_AUTHORIZED` | token lacks the workspace or device permission | use a token with the right permissions, see `platform-concepts.md` |
| `NOT_FOUND` / `DEVICE_NOT_FOUND` | wrong id, or object not visible to this token | verify ids with `discover.py` |
| `VALIDATION_ERROR` | input rejected | compare input type in `schema.graphql` |
| `FIELD_DOES_NOT_EXIST` | unknown field identifier on a write | use `fieldName` values from `product.measurementFields` (reads such as `currentMeasurements` silently drop unknown identifiers instead) |
| `CANNOT_PERFORM_OPERATION` | state does not allow it (e.g. claiming disabled) | read the message |
| `INSUFFICIENT_QUOTA`, `QUOTA_SHORTFALL_NOT_COVERED`, `INSUFFICIENT_REPLACEMENT_QUOTA`, `NO_REPLACEMENT_AVAILABLE`, `ADDON_TRANSITION_REQUIRED`, `ADDON_NOT_AVAILABLE`, `INVALID_BILLING_INFORMATION` | billing/quota problems on device creation or plan changes | resolve in the portal billing section |
| `INVALID_AUTHENTICATION_CODE` | OTP/2FA code wrong | retry login with `otpToken` |
| `GATEWAY_ALREADY_CLAIMED` | gateway EUI in use | |

Mutation payload conventions differ by age of the mutation: older ones return `{ ok, error: String, <object> }`, newer ones return `{ ok, error: { code, details } }` (`Error` type) or `errors: GenericScalar`. Always select `ok` plus the error field and check `ok` before using the object.

## Pagination styles

| Where | Style | How |
|---|---|---|
| `workspace.devicesFiltered`, `workspace.devices` | offset pages | `page` (0-based) and `pageSize`; `total` gives the full count; omit `devices` when you only need `total` |
| `allDevices` | none | returns every matching device; only for small filtered sets |
| `organizations`, `organization.workspaces`, `workspace.zones`, `devicesInZones`, `deviceZoneEvents`, `gateways`, `exports`, `exportRuns`, `reportBuilderReports`, `*MoveRequests`, `rule.executionLogEntries`, `dashboardChangelog` | Relay connections | `first`/`after` (or `offset`), read `edges { node { … } }`, `pageInfo { hasNextPage endCursor }`, `totalCount`; `filter`/`orderBy` inputs are per connection (grep the `*FilterInputType` in the schema) |
| `products`, `rulesNG`, `dashboards`, `reports`, `webhooks`, `allWorkspaces` | plain lists | no pagination; usually small |

Relay example:

```graphql
query Zones($workspaceId: String!, $after: String) {
  workspace(id: $workspaceId) {
    zones(first: 50, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { node { id name radius center tags } }
    }
  }
}
```

## Scalars and JSON strings

| Scalar | Wire format | Notes |
|---|---|---|
| `UUID`, `UUIDString`, `BlankableUUID` | string `"2f1c…"` | `BlankableUUID` also accepts `""` to clear a reference |
| `ID` | string | Relay global ids on `Node` types (zones, exports, organizations); still usable in `zone(id:)` etc. |
| `DateTime` | ISO 8601 string, e.g. `"2026-03-01T00:00:00Z"` or `"2026-03-01T00:00:00+02:00"` | returned values are UTC with offset `+00:00` |
| `Date` | `"2026-03-01"` | |
| `JSONString` | a JSON document **encoded as a string** | `history`, `historyNg`, `historyStats`, `metadata`, `dashboardData`, `deviceFolders`, `product.dashboards`, `sidebarConfig`, rule log variables. Parse it (`JSON.parse`, `json.loads`) before use; when sending, stringify first |
| `LatLng` | object `{ "latitude": 52.5, "longitude": 13.4 }` | zone centers |
| `LatLngString` | `"(52.5,13.4)"` | geo field values, set-value actions |
| `GenericScalar` | any JSON value | error details, validation errors |
| `BigInt`, `Decimal` | numbers (may arrive as strings for large values) | |
| `Upload` | multipart file | logos and images; not needed for data apps |

## Time handling

- The API speaks UTC. Timestamps you send without an offset are treated as UTC. Send explicit `Z` or offsets to avoid ambiguity.
- Ranges are start-inclusive and end-exclusive: "March 2026" is `2026-03-01T00:00:00Z` to `2026-04-01T00:00:00Z`; "today" in Berlin is local midnight converted to UTC (`2026-03-10T23:00:00Z` to `2026-03-11T23:00:00Z` in winter).
- Convert local boundaries to UTC in your code (`date-fns-tz`, `luxon`, Python `zoneinfo`) or let the API do it: `query { parseDate(date: "2026-03-11 00:00", timezone: "Europe/Berlin") }` returns the UTC `DateTime`.
- `history(timerangestart:, timerangeend:)` arguments are `String`s in ISO format (offsets honoured); `change`/`sum`/`average`/`minimum`/`maximum` take `DateTime!`. An end in the future is accepted.
- Device timestamps: `lastHeard`, `DeviceCurrentMeasurementType.modified` (time of the latest value), `DeviceRoleFieldValue.datetime`.
- Rules have their own `timezone`; the workspace has none.

## Limits and performance

- Documented write limit: 1 write per second per field on the REST record endpoint. Read rate limits are not published; be conservative: cache, batch KPIs with aliases, poll dashboards every 30 to 60 s, back off on HTTP 429/5xx.
- Request cost grows with device count times selected fields. Rules of thumb: `pageSize` ≤ 50 for lists with measurements; never fetch `devices { history }` for many devices in one request; one `history` call per device and field group, with a resolution that keeps points per field under a few thousand (see `queries-measurements.md`).
- Use platform aggregation (`aggregatedNumericSemanticValue`, `total`, `sum/average/minimum/maximum/change`) instead of downloading raw data to compute in the client.
- Use Exports (`createManualExport`) for bulk historical dumps.
- Timeouts: allow 60 s for history-heavy requests; typical device list requests answer in well under a second.

## Schema and introspection

- `reference/schema.graphql` (SDL, ~230 KB) is the full contract. Grep it rather than reading it whole:
  - `grep -n "^type WorkspaceType" -A 130 reference/schema.graphql`
  - `grep -n "^input CreateRuleNGInputType" -A 40 reference/schema.graphql`
  - `grep -n "^enum FieldSemantic" -A 45 reference/schema.graphql`
  - `grep -n "  devicesFiltered(" -A 60 reference/schema.graphql`
- `reference/schema-map.md` lists every root query and mutation with signatures.
- Live introspection: `python3 scripts/fetch_schema.py --check` reports what changed since the bundled copy.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `user` is `null` (HTTP 200) | no `Authorization` header sent | add `Authorization: Token <token>` (not `Bearer`) |
| HTTP 401, empty body | token malformed, revoked or from another environment | create a new token; check for whitespace/newlines in the env var |
| HTTP 400 with `errors` | document invalid (unknown field, wrong variable type, e.g. `[String]` passed where `[String!]!` is required) | validate against `reference/schema.graphql` |
| `workspace` is `null` (no error) | id/slug wrong or token not a member | `allWorkspaces` shows what the token can see |
| `NOT_AUTHORIZED` on a mutation | missing workspace permission or device permission | check `workspace.myPermissions`, `device.myPermissions(workspace:)` |
| `history` returns a string | it is a `JSONString` | parse it |
| `history` empty (`"[]"`) | range outside retention, wrong or inactive identifiers, device silent in that window | check `product.measurementFields`, `lastHeard`, retention of the device plan |
| Request very slow or times out | too many devices × measurements, `raw` resolution on a long range | paginate, coarser resolution, split requests |
| Semantic value `null` | no field with that semantic on the device, or no data | assign semantics in field settings; handle `null` in UI |
| `total` correct but `devices` short | pagination | iterate `page` |
| Values look shifted by hours | local time interpreted as UTC | send offsets, convert boundaries |
| `Cannot query field X on type DeviceCurrentMeasurementType` | measurement metadata sits under `field { … }` | select `field { fieldName unit }`, `value`, `modified` |
