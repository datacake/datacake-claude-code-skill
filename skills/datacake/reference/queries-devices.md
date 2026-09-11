# Querying workspaces, devices, products and fields

## Contents

- Workspaces
- Which device query to use
- `devicesFiltered` (filter, sort, paginate)
- `allDevices` (small groups)
- Single device
- Products and field discovery
- Role fields (product-agnostic display)
- Tags, metadata, location, folders
- Members and permissions (reads)
- Public device dashboards
- Performance patterns and tag strategy

## Workspaces

```graphql
query Workspaces {
  allWorkspaces { id name slug deviceCount memberCount myPermissions }
}
```

```graphql
query Workspace($id: String!) {
  workspace(id: $id) {
    id name slug deviceCount memberCount
    myPermissions features semantics allTags allMetadataKeys
    organization { id name }
    homeDashboard { id name }
  }
}
```

`workspace(slug: "my-workspace")` works as an alternative to `id`. `user { primaryWorkspace { id } }` gives a sensible default workspace.

## Which device query to use

| Need | Use | Why |
|---|---|---|
| Paginated list with filters, sorting, counts, KPIs | `workspace.devicesFiltered(...)` | the only query with `total`, semantic filters, ordering and pages; scales to thousands of devices |
| Small, fixed group (< ~50) by tag, with history in one go | `allDevices(inWorkspace:, searchTags:)` | simple, but returns everything that matches (no pagination) |
| One device by UUID | `device(deviceId:)` | shortest path, no workspace needed |
| One device by serial number | `workspace.device(serialNumber:)` | serial is what hardware and decoders know |
| Devices of a product | `devicesFiltered` + client filter, or `product.deviceCount`; `allDevices(isProduct:)` | products are workspace-bound |
| Simple search box | `devicesFiltered(search:)` | name search (`workspace.devices` ignored `pageSize` in tests; prefer `devicesFiltered`) |

Default choice for apps: `devicesFiltered`.

## `devicesFiltered`

Arguments (all optional; filters combine with AND):

| Argument | Type | Effect |
|---|---|---|
| `page`, `pageSize` | Int | 0-based page, page size; without `pageSize` the default page size applies, so always set it |
| `all` | Boolean | include every device the token can see (use with `pageSize` for paging through all) |
| `search` | String | case-insensitive match on device name |
| `tags` | `{ contains: [..] }` (device has all) / `{ overlap: [..] }` (device has any) | grouping by building, floor, customer… |
| `online` | Boolean | online/offline |
| `lastHeard` | `{ gt, gte, lt, lte: DateTime }` | activity windows ("silent for 2 days") |
| numeric semantics: `temperature`, `humidity`, `co2`, `voc`, `airPollution`, `ambientLight`, `loudness`, `battery`, `signal`, `snr`, `power`, `energyConsumption`, `waterConsumption`, `waterDepth`, `fillLevel`, `soilMoisture`, `peopleCount`, `runtimeHours`, `hoursUntilMaintenance` | `{ gt, gte, lt, lte, range: { start, end }, aggregation }` | value filters across products, see `semantics-and-kpis.md` |
| boolean semantics: `batteryLow`, `buttonPressed`, `deskOccupied`, `devicePowered`, `doorOpened`, `emergencyTriggered`, `gasLeakDetected`, `hvacActive`, `lightOn`, `maintenanceRequired`, `motionDetected`, `parkingOccupied`, `powerOutageDetected`, `rainDetected`, `roomOccupied`, `smokeDetected`, `tamperDetected`, `valveOpened`, `waterLeakDetected`, `windowOpened` | `{ exact, inList, count: {...}, aggregation }` | state filters |
| `orderBy` | `{ status | verboseName | location | serialNumber | lastHeard | product | productType | Primary | Secondary | DeviceLocation | DeviceSignal | DeviceBattery: ASC/DESC, semanticField: { semantic, order, numericAggregation }, booleanSemanticFieldCount: { semantic, order, countValue } }` | one key at a time is safest |

Result `FilteredDeviceList`: `total` (count of all matches, independent of paging), `devices` (current page), `aggregatedNumericSemanticValue(semantic, aggregation)`, `aggregatedBooleanSemanticCount(semantic, countValue)`.

Canonical list query:

```graphql
query DeviceList($workspaceId: String!, $page: Int!, $pageSize: Int!, $search: String, $tags: [String]) {
  workspace(id: $workspaceId) {
    devicesFiltered(
      page: $page
      pageSize: $pageSize
      search: $search
      tags: { contains: $tags }
      orderBy: { verboseName: ASC }
    ) {
      total
      devices {
        id
        verboseName
        serialNumber
        online
        lastHeard
        tags
        location
        product { id name hardware }
        currentLocation { lat lng }
      }
    }
  }
}
```

Variables: `{"workspaceId": "…", "page": 0, "pageSize": 25, "search": null, "tags": null}` (a `null` tag filter matches everything).

Typical filter combinations:

```graphql
query Attention($workspaceId: String!) {
  workspace(id: $workspaceId) {
    silent: devicesFiltered(lastHeard: { lt: "2026-03-01T00:00:00Z" }, pageSize: 10, orderBy: { lastHeard: ASC }) {
      total
      devices { id verboseName lastHeard }
    }
    floorOne: devicesFiltered(tags: { contains: ["floor-1"] }, online: true, pageSize: 50) {
      total
      devices { id verboseName tags }
    }
    anyMeter: devicesFiltered(tags: { overlap: ["energy", "water", "gas"] }) { total }
    hottest: devicesFiltered(temperature: { gt: 0 }, pageSize: 5,
      orderBy: { semanticField: { semantic: TEMPERATURE, order: DESC } }) {
      devices { id verboseName temperature: numericSemanticField(semantic: TEMPERATURE) { value } }
    }
  }
}
```

## `allDevices`

Arguments: `inWorkspace` (workspace id), `searchTags: [String]` with `searchTagsAnyAll: any|all`, `searchTag` (single), `searchName`, `online`, `idIn: [UUID!]`, `isProduct` (product id), `isProductKind`.

```graphql
query TagGroup($workspaceId: String!, $tags: [String]) {
  allDevices(inWorkspace: $workspaceId, searchTags: $tags, searchTagsAnyAll: all) {
    id
    verboseName
    online
    lastHeard
    currentMeasurements(fieldNames: ["TEMPERATURE", "HUMIDITY"]) {
      value
      modified
      field { fieldName unit }
    }
  }
}
```

Use it only when the group is small; it has no `total` and no paging. `idIn` is handy to re-fetch a known set of devices (e.g. favourites).

## Single device

```graphql
query Device($deviceId: String!) {
  device(deviceId: $deviceId) {
    id verboseName serialNumber online lastHeard lastHeardThreshold
    location currentLocation { lat lng }
    tags metadata image icon created
    product { id name slug hardware lastHeardThreshold }
    roleFields { role value datetime field { fieldName verboseFieldName unit } }
  }
}
```

By serial number inside a workspace:

```graphql
query BySerial($workspaceId: String!, $serial: String!) {
  workspace(id: $workspaceId) {
    device(serialNumber: $serial) { id verboseName online }
  }
}
```

Handy device fields: `measurements24h` (datapoints in the last 24 h), `isOverQuota`, `claimed`, `claims { … }` (owner only), `publicLinks { id token mode }`, `myPermissions(workspace:)`, `plan(workspace:) { name datapointsPerDay dataRetentionDays }`, `currentConfigurationValues { configurationField { fieldName } valueNumber valueString valueBool isDefault }`, `rules { id name active }` (legacy), `activationProviders`, `active`.

## Products and field discovery

Run `python3 scripts/discover.py <workspace>` for a printed map, or query:

```graphql
query Products($workspaceId: String!) {
  workspace(id: $workspaceId) {
    products {
      id name slug hardware deviceCount lastHeardThreshold
      measurementFields(active: true) {
        id fieldName verboseFieldName fieldType unit displayUnit role semantic useFormula
      }
      configurationFields { id fieldName verboseFieldName fieldType unit }
      lorawanDownlinks { id name description fport }
    }
  }
}
```

From a device: `device { product { measurementFields(active: true) { fieldName verboseFieldName fieldType unit role semantic } } }`. A single field: `product { measurementField(fieldName: "TEMPERATURE") { id unit semantic } }`.

`ProductMeasurementFieldType` cheat sheet: `fieldName` (identifier, use in every measurement query), `verboseFieldName` (label), `fieldType` (`FLOAT`, `INT`, `NUMERIC`, `BOOL`, `STRING`, `COUNTER`, `GEO`, `OUTPUT`), `unit`/`displayUnit`/`displayUnitOverride`, `floatDigits`, `color`, `role`, `semantic`, `active`, `formula`/`useFormula`, `gauges { valuesFrom valuesTo color eventName }`, `description`.

MUST: discover identifiers once (portal or `discover.py`), then hardcode them per product in the app. Do not re-query field definitions on every request.

## Role fields

`roleFields` returns the values of the fields assigned to `PRIMARY`, `SECONDARY`, `DEVICE_BATTERY`, `DEVICE_SIGNAL`, `DEVICE_LOCATION` for any product, so one component can render mixed fleets:

```graphql
query RoleList($workspaceId: String!) {
  workspace(id: $workspaceId) {
    devicesFiltered(pageSize: 25, orderBy: { lastHeard: DESC }) {
      total
      devices {
        id verboseName online lastHeard
        product { name }
        roleFields { role value datetime chartData field { fieldName verboseFieldName unit fieldType } }
      }
    }
  }
}
```

Notes: `value` is a `String` (parse numbers; locations arrive as `"(lat,lng)"`); `datetime` is the value timestamp; `chartData` is a short numeric series for sparklines; missing roles are simply absent. Reduce to `{ PRIMARY: {...}, DEVICE_BATTERY: {...} }` in the client.

## Tags, metadata, location, folders

- Tags: `device.tags` (list of strings), `workspace.allTags` (all tags in use). Update with `updateDevice(deviceId:, input: { tags: [...] })` (full replacement).
- Metadata: `device.metadata` is a JSON string, parse it; keys in `workspace.allMetadataKeys`. Update with `updateDevice(input: { metadata: "{\"assetNo\":\"A-17\"}" })`.
- Location: `device.location` is the free-text description; `currentLocation { lat lng }`, `currentLocationVerbose` (reverse geocoded), `currentLocationLastUpdate` come from the `DEVICE_LOCATION` role field.
- Folders: `workspace.deviceFolders` is a JSON string with the folder tree, e.g. `[{ "id": "…", "name": "Building A", "icon": "folder", "type": "DEVICE_FOLDER", "tags": ["building-a"], "tagsConjunction": "AND", "online": false, "initialView": "OVERVIEW", "availableViews": ["OVERVIEW", "LIST", "GRID"], "items": [] }]` (nested folders in `items`). Apps can reuse it to offer the same grouping as the portal: translate each folder into `devicesFiltered(tags: { contains | overlap })`.

## Members and permissions (reads)

```graphql
query Members($workspaceId: String!) {
  workspace(id: $workspaceId) {
    myPermissions
    userRelationships(includeApiUsers: true) {
      user { id email fullName isApiuser }
      permissions
      allDevicesPermissionExists
      isOrganizationOwner
      deviceRelationships { device { id verboseName } permissions }
    }
    apiUserRelationships { user { id name created } permissions }
    invitedUsers { email permissions }
  }
}
```

Reading members needs the `members` permission. For "what may I do with this device": `device { myPermissions(workspace: $workspaceId) }`. Organizations, organization admins, invites, white label users, audit logs and the admin recipes (mass invite, moving members) are in `organizations-and-members.md`.

## Public device dashboards

Viewers with a public link do not need an account:

```graphql
query Public($deviceId: String!, $token: String!) {
  publicDevice(id: $deviceId, token: $token) {
    id verboseName online lastHeard tags
    roleFields { role value field { fieldName unit } }
    temperature: numericSemanticField(semantic: TEMPERATURE) { value }
    hasWriteScope
  }
}
```

`publicDevice` exposes semantics, role fields and dashboard data, not `currentMeasurements`/`history`. Write actions in WRITE mode use `setValue`/`sendDownlink` with `publicDeviceAuth: { link, token }`.

## Performance patterns and tag strategy

- Count first, details on demand: `devicesFiltered(online: false) { total }` is cheap; add `devices { … }` only with `pageSize`.
- Keep list selections thin (`id`, `verboseName`, `online`, `lastHeard`, role fields or one semantic); load measurements and history on the detail view.
- Sort server-side (`orderBy`) instead of fetching everything to sort in the client.
- Tags beat search: `search` matches names loosely; tags are explicit and indexable. Recommend a hierarchy such as `site-berlin`, `building-a`, `floor-2`, `room-201`, plus a type tag (`co2`, `meter`, `tracker`) and operational tags (`critical`, `needs-attention`). Consistent lowercase, hyphenated.
- Products give consistent identifiers; when an app targets one product, hardcode its identifiers and filter devices by product/tag.
