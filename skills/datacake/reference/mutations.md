# Mutations: writing to Datacake

## Contents

- Conventions and safety
- Operation index
- Account and login
- Devices: create, edit, remove, claim, move, public links
- Products, fields and configuration fields
- Recording data (REST, MQTT, set value)
- Downlinks
- Workspaces, members and API users
- Rules (Rule Engine NG)
- Dashboards and views
- Exports and reports
- Zones, webhooks, folders, gateways
- Everything else

## Conventions and safety

- Mutation root type is `Mutations`. Most take one `input` argument (`<Name>InputType`); some take flat arguments. Grep `reference/schema.graphql` for the exact input before writing code.
- Payloads return `ok` plus the object; errors are either `error: String`, `error { code details }` or `errors` (JSON). Check `ok` and surface the error.
- Permissions are workspace permissions (`devices`, `rules`, `members`, `dashboards`, `exports`, `zones`, …) or device permissions (`edit_basics`, `edit_product`, `record_measurements`). A `NOT_AUTHORIZED` error means the token lacks one of them.
- Before running a destructive mutation (`removeDevice`, `deleteDeviceData`, `deleteWorkspace`, `deleteRuleNG`, `deleteZones`, `revokeDeviceClaims`, `cancelAllSubscriptions`) confirm with the user; use `dryRun: true` where offered. Data recovery after deletion is a paid support service.
- Ids: `String` arguments accept UUID strings; `UUID` arguments require valid UUIDs; `BlankableUUID` accepts `""` to clear.

## Operation index

| Task | Mutation | Permission |
|---|---|---|
| Sign in / get token | `login(email, password, otpToken)` | – |
| Create LoRaWAN devices | `createLoraDevices(input)` | `devices` (+ billing for paid plans) |
| Create API (HTTP/MQTT) devices | `createApiDevices(input)` | `devices` |
| Add a device by serial + claim code | `addPincodeDevice(input)` | `devices` |
| Rename, tag, locate, set metadata, claim settings | `updateDevice(deviceId, input)` | `edit_basics` on the device |
| Change serial | `changeDeviceSerial(id, serial)` | `edit_basics` |
| Remove device from workspace | `removeDevice(input)` | `devices` |
| Delete measurements in a window | `deleteDeviceData(input)` | `devices` |
| Share access (claim) / revoke | `updateDevice` (claim code), `claimDeviceIntoWorkspace`, `revokeDeviceClaims` | `devices` |
| Transfer devices | `createDeviceMoveRequest`, `acceptDeviceMoveRequest`, `rejectDeviceMoveRequest`, `cancelDeviceMoveRequest` | `devices` in both workspaces |
| Public device dashboard link | `createDevicePublicLink`, `updateDevicePublicLink`, `deleteDevicePublicLink` | `edit_basics` |
| Offline email for me | `setNotifyOffline(input)` | device view |
| Add / edit / delete product field | `addProductMeasurementField(...)`, `updateProductMeasurementField(...)`, `deleteProductMeasurementField(id)` | `edit_product` / `devices` |
| Product settings (timeout, decoder, dashboards) | `updateProduct(input)` | `edit_product` |
| Clone / delete product | `cloneProduct(input)`, `deleteProduct(input)` | `devices` |
| Configuration fields | `createConfigurationField`, `updateConfigurationField`, `deleteConfigurationField(field)`, `setDeviceConfigurationValue(input)` | `edit_product` / `edit_basics` |
| Test decoder / formula | `tryPayloadDecoder(input)`, `tryFormula(input)` | `edit_product` |
| Record values | REST `POST /v1/devices/<id>/record/?batch=true`, MQTT `dtck-pub/...`, `setValue(input)` | `record_measurements` |
| Send downlink | `sendDownlink(device, downlink)` | device access (+ WRITE public link) |
| Create workspace | `addWorkspace(name, organizationId)` | org `create_workspaces` |
| Rename workspace, set home dashboard | `updateWorkspace(id, name, homeDashboardId)` | `basics` |
| Invite user, remove user | `addUserToWorkspace(input)`, `removeUserFromWorkspace(userId, workspaceId)`, `deleteUserInvite(email, workspace)` | `members` |
| Set permissions | `setWorkspaceUserPermissions(input)`, `setUserDevicePermissions(input)`, `addDevicePermissions`, `removeDevicePermissions` | `members` |
| API users | `addApiUser(input)`, `updateApiUser(id, name)`, `deleteApiUser(id)` | `members` |
| Rules | `createRuleNG(workspaceId, input)`, `updateRuleNG(id, input)`, `deleteRuleNG(id)` | `rules` |
| Global dashboards | `addDashboard(input)`, `updateDashboard(input)`, `deleteDashboard(dashboard, workspace)`, `createDashboardPublicLink(input)` | `dashboards` |
| Exports | `createManualExport(input)`, `createPeriodicExport(input)`, `updatePeriodicExport(input)`, `deleteExport(input)` | `exports` |
| Reports | `createReportBuilderReport(input)`, `runReportBuilderReport(input)`, `createReport(input)` (energy/legacy CSV), `runReport(report)` | `reports` |
| Zones | `createZones(input)`, `updateZone(input)`, `deleteZones(input)` | `zones` |
| Outgoing webhooks | `createWebhook(input)`, `updateWebhook`, `deleteWebhook`, `tryWebhook` | `basics`/admin |
| Folders | `updateDeviceFolders(input)` | `devices` |
| Datacake LNS gateways | `createGateway(input)`, `claimGateway(input)`, `updateGateway`, `deleteGateway` | `gateways` |

## Account and login

```graphql
mutation Login($email: String!, $password: String!) {
  login(email: $email, password: $password) { ok token error user { id email } }
}
```

Also: `requestPasswordReset(email)`, `passwordReset(userid, token, password)`, `changePassword(email, passwordOld, passwordNew, passwordNewCheck)`, `updateUser(firstName, lastName, language, phoneNumber)`, `signup(...)` (needs a captcha token; not for automation).

## Devices

### Create LoRaWAN devices

```graphql
mutation CreateLora($input: CreateLoraDevicesInputType!) {
  createLoraDevices(input: $input) {
    ok
    error
    devices { id verboseName serialNumber product { id name slug } }
  }
}
```

```json
{
  "input": {
    "workspace": "<workspace uuid>",
    "plan": "free",
    "planCode": "",
    "networkServer": "TTI",
    "productKind": "EXISTING",
    "existingProduct": "<product uuid>",
    "devices": [
      { "devEui": "70B3D57ED0001234", "name": "Room 101", "tags": ["floor-1", "co2"], "location": "Building A" }
    ]
  }
}
```

- `productKind`: `NEW` (+ `newProductName`), `EXISTING` (+ `existingProduct`), `TEMPLATE` (+ `templateSlug`).
- `networkServer`: `DATACAKELNS`, `TTI`, `TTN`, `HELIUM`, `LORIOT`, `CHIRPSTACK`, `ACTILITY`, `SENET`, `MELITA`, `WANESY`, `KPN`, `WIOTYS`, `TEKTELIC`, `MILESIGHTGATEWAY`, `EVERYNET`, `CATTELECOM`, `ORBIWISE`, `NETMORE` (case-insensitive). External LNS still need their forwarding configured (per product, `updateProduct` integration fields or the portal).
- Datacake LNS devices additionally need per device `appeui`, `appkey`, `frequency` (`EU_863_870_TTN`, `US_902_928_FSB_2`, `AU_915_928_FSB_2`, `AU_915_928_FSB_2_NAM`, `AS_920_923`, `AS_920_923_LBT`) and `deviceClass` (`A` or `C`).
- `plan`: `free`, `hobby`, `light`, `standard`, `plus`, or a package plan slug (`devicePlans { slug }`); `planCode` for redeem codes. Paid plans require billing details.

### Create API devices

```graphql
mutation CreateApi($input: CreateApiDevicesInputType!) {
  createApiDevices(input: $input) { ok error devices { id serialNumber verboseName product { id } } }
}
```

`input`: `{ workspace, plan, planCode, productKind: NEW|EXISTING|TEMPLATE, newProductName|existingProduct|template, devices: [{ serial, name, tags, location }] }`. The serial is what the HTTP decoder uses for routing; choose stable values (hardware ids).

### Add by pincode claiming

```graphql
mutation Claim($input: AddPincodeDeviceInputType!) {
  addPincodeDevice(input: $input) { ok error device { id verboseName } }
}
```

`input`: `{ workspace: "<uuid>", serialNumber: "...", pinCode: "..." }`. `claimDeviceIntoWorkspace(deviceId | deviceSerialNumber, workspaceId)` is the owner-side variant.

### Edit a device

```graphql
mutation EditDevice($deviceId: String!, $input: UpdateDeviceInputType) {
  updateDevice(deviceId: $deviceId, input: $input) {
    ok
    device { id verboseName tags metadata location }
  }
}
```

`input` fields: `verboseName`, `location`, `tags` (full replacement), `metadata` (JSON string), `iconOverride`, `image`/`resetImage`, claim settings `canBeClaimed`, `claimCode`, `claimSerialNumber`, LNS ids `ttnDevId`, `ttiDevId`, `heliumDevId`. Example variables: `{"deviceId": "<uuid>", "input": {"tags": ["floor-1", "co2"], "metadata": "{\"asset\":\"A-17\"}"}}`.

### Remove and delete data

```graphql
mutation Remove($deviceId: String!, $workspaceId: String!) {
  removeDevice(input: { deviceId: $deviceId, workspaceId: $workspaceId }) { ok }
}
```

Removing from the owning workspace deletes the device and its data; removing from a claiming workspace only drops the claim.

```graphql
mutation Purge($deviceId: UUID!, $start: DateTime!, $end: DateTime!, $dryRun: Boolean!) {
  deleteDeviceData(input: { deviceId: $deviceId, fieldNames: ["TEMPERATURE"], start: $start, end: $end, dryRun: $dryRun }) {
    ok
    datapointsAffected
  }
}
```

Run with `dryRun: true` first, show `datapointsAffected`, then repeat with `false` after confirmation. Omit `fieldNames` to target all fields.

### Claims and moves

- Enable claiming: `updateDevice(input: { canBeClaimed: true, claimCode: "1234" })`; multiple claims via `updateProduct(input: { allowMultipleClaims: true })`.
- Revoke: `revokeDeviceClaims(input: { workspaceId, deviceIds })` (owner).
- Move: `createDeviceMoveRequest(input: { sourceWorkspaceId, targetWorkspaceId, deviceIds, includeIntegrations, message })` → target admin runs `acceptDeviceMoveRequest(input: { moveRequestId, planOverrides: [{ deviceId, planSlug }], planCode })` or `rejectDeviceMoveRequest`; sender may `cancelDeviceMoveRequest`. Track with `workspace.incomingDeviceMoveRequests` / `outgoingDeviceMoveRequests` (Relay connections; `status`, `deviceCount`, `expiresAt`).

### Public device links

```graphql
mutation PublicLink($deviceId: String!) {
  createDevicePublicLink(device: $deviceId, input: { token: "optional-password", mode: READ }) {
    ok
    device { publicLinks { id token mode } }
  }
}
```

`mode: WRITE` allows set-value and downlink widgets. The public URL is built by the frontend (`https://app.datacake.de/pd/<device id>`, or the white-label domain); viewers query `publicDevice(id:, token:)`.

## Products, fields and configuration fields

```graphql
mutation AddField($productId: String!) {
  addProductMeasurementField(
    productId: $productId
    fieldName: "TEMPERATURE"
    verboseFieldName: "Temperature"
    fieldType: FLOAT
    unit: "°C"
    role: PRIMARY
    semantic: TEMPERATURE
    floatDigits: 1
  ) {
    ok
    field { id fieldName fieldType unit role semantic }
  }
}
```

```graphql
mutation EditField($fieldId: String!) {
  updateProductMeasurementField(fieldId: $fieldId, verboseFieldName: "Room temperature", semantic: TEMPERATURE, role: PRIMARY, active: true, floatDigits: 1) {
    ok
    field { id fieldName verboseFieldName semantic role active }
  }
}
```

- `fieldType` for new fields: `FLOAT`, `INT`, `NUMERIC`, `BOOL`, `STRING`, `COUNTER`, `GEO`. Identifiers cannot be changed later; delete and recreate instead (`deleteProductMeasurementField(id)` drops the data of that field on all devices).
- Formulas: `updateProductMeasurementField(fieldId, formula: "TEMPERATURE * 1.8 + 32", useFormula: true)`; test with `tryFormula(input: { device, formula })`.
- Unit display: prefer `displayUnitOverride` (label only); `displayUnit` conversion is deprecated.
- Product settings: `updateProduct(input: { product, lastHeardThreshold, icon, lorawanPayloadDecoder, dashboards, allowMultipleClaims, ... })`; test decoders with `tryPayloadDecoder(input: { product, code, payload, port, device })`.
- Clone into another workspace: `cloneProduct(input: { productId, targetWorkspaceId, copyIntegrations, productName })`; delete an empty product: `deleteProduct(input: { id })`.
- Configuration fields: `createConfigurationField(input: { product, fieldType: NUMBER|STRING|BOOL, fieldName, verboseFieldName, unit, description, defaultValueNumber, defaultValueBool, defaultValueString })` (all defaults required, use the matching one); per device:

```graphql
mutation SetConfig($deviceId: String!) {
  setDeviceConfigurationValue(input: { device: $deviceId, field: "THRESHOLD", valueNumber: 25 }) {
    ok
    configurationField { fieldName }
  }
}
```

Use `resetToDefault: true` to clear an override.

## Recording data

REST batch endpoint (API devices and any device the token may write to; needs `record_measurements`):

```bash
curl -X POST "https://api.datacake.co/v1/devices/<deviceId>/record/?batch=true" \
  -H "Authorization: Token $DATACAKE_TOKEN" -H "Content-Type: application/json" \
  -d '[{"field":"TEMPERATURE","value":23.5},{"field":"HUMIDITY","value":42,"timestamp":"1741000000"}]'
```

- `field` = identifier, `value` number/string/bool, optional `timestamp` (Unix epoch seconds) for backfilling; limit 1 write per second per field.
- Product webhook: `POST https://api.datacake.co/integrations/api/<product id>/` with any JSON; the product's HTTP decoder returns `[{ device: "<serial>", field, value }]`.
- MQTT: publish the value to `dtck-pub/<product_slug>/<device_id>/<FIELD>` on `mqtt.datacake.co:8883` (token as username and password).
- GraphQL `setValue` writes one value (used by dashboards; works with public links in WRITE mode):

```graphql
mutation SetValue($input: SetValueInputType!) {
  setValue(input: $input) { ok error { code details } }
}
```

`input`: `{ deviceId, fieldName, value, publicDeviceAuth?: { link, token }, publicDashboardAuth?: { id, token } }`. `value` is the `MeasurementValueInput` scalar: pass a number, boolean or string (geo as `"(lat,lng)"`), e.g. `{"deviceId": "…", "fieldName": "SETPOINT", "value": 21.5}`. `internalAddMeasurement` is internal; prefer REST for scripts.

## Downlinks

Discover: `product { lorawanDownlinks { id name description fport fieldsUsed { fieldName } } apiConfiguration { apiDownlinks { id name } } }`. Send:

```graphql
mutation Downlink($deviceId: String!, $downlinkId: String!) {
  sendDownlink(device: $deviceId, downlink: $downlinkId) { ok }
}
```

Downlinks whose encoder reads fields take their input from the current field values; write them first (REST/`setValue`) or use the portal form. Public dashboards pass `publicDeviceAuth`/`publicDashboardAuth`. Legacy product functions: `callProductFunction(deviceId, functionId)`. Fleet-wide downlinks: a rule with a `MULTI_DEVICE_DOWNLINK` action.

## Workspaces, members and API users

```graphql
mutation NewWorkspace($name: String!, $orgId: BlankableUUID) {
  addWorkspace(name: $name, organizationId: $orgId) { ok workspace { id slug name } }
}
```

```graphql
mutation Invite($input: AddUserToWorkspaceInputType!) {
  addUserToWorkspace(input: $input) { ok invited }
}
```

`input`: `{ workspace, email, wsPermissions: ["devices", "rules"], deviceRelationships: [{ device: "<uuid>", permissions: ["edit_basics"] }] }` (`deviceRelationships: []` for an observer; permissions are the enum values `basics`, `members`, `billing`, `devices`, `rules`, `dashboards`, `reports`, `exports`, `zones`, `gateways`, `cakered`, `whitelabel`).

```graphql
mutation ApiUser($input: ApiUserInput!) {
  addApiUser(input: $input) { ok apiUser { id name apiKey } }
}
```

`input`: `{ workspace, name, wsPermissions: [], deviceRelationships: [{ device, permissions: [] }] }`. The returned `apiKey` is the token; store it immediately. Update/delete: `updateApiUser(id, name)`, `deleteApiUser(id)`.

Permissions: `setWorkspaceUserPermissions(input: { workspace, users: [{ user, permissions }] })`, `setUserDevicePermissions(input: { workspace, user, permissions: [{ device, permissions }] })`, `addDevicePermissions` / `removeDevicePermissions(input: { workspace, device, permissions: [{ user, permissions }] })`, `removeUserFromWorkspace(userId, workspaceId)`, `deleteUserInvite(email, workspace)`.

## Rules (Rule Engine NG)

```graphql
mutation CreateRule($workspaceId: UUID!, $input: CreateRuleNGInputType!) {
  createRuleNG(workspaceId: $workspaceId, input: $input) {
    ok
    error { code details }
    ruleNG { id name enabled }
  }
}
```

Example `input` (email + webhook when CO₂ exceeds 1000 ppm on all devices of one product):

```json
{
  "name": "High CO2",
  "description": "Notify facility team",
  "timezone": "Europe/Berlin",
  "enabled": true,
  "executionMode": "DEVICE_LEVEL",
  "productFilterId": "<product uuid>",
  "triggerOnMeasurement": true,
  "triggeringMeasurementFields": ["<CO2 field uuid>"],
  "conditions": [
    {
      "id": "<client-generated uuid>",
      "description": "",
      "conjunction": "AND",
      "kind": "GREATER_THAN",
      "leftOperand": { "kind": "TRIGGERING_DEVICE_FIELD_VALUE", "fieldId": "<CO2 field uuid>" },
      "rightOperand": { "kind": "STATIC_NUMBER_VALUE", "numberValue": 1000, "hysteresis": 50 }
    }
  ],
  "createActions": [
    {
      "kind": "EMAIL",
      "description": "Mail",
      "emailReceivers": ["facility@example.com"],
      "emailSubject": "CO2 high in {{ triggering_device[\"name\"] }}",
      "emailBody": "CO2 is {{ triggering_device[\"values\"][\"CO2\"] }} ppm",
      "fireWhenConditionsBecomeHot": true,
      "fireWhenConditionsStayHot": false,
      "fireWhenConditionsBecomeCold": true,
      "minSecondsBetweenHotConditions": 3600,
      "maxConsecutiveActionExecutions": 0
    },
    {
      "kind": "WEBHOOK",
      "description": "Ticket",
      "webhookUrl": "https://example.com/hooks/datacake",
      "webhookHeaders": [{ "key": "Authorization", "value": "Bearer …" }],
      "webhookPayload": "{\"device\": \"{{ triggering_device[\"id\"] }}\", \"co2\": {{ triggering_device[\"values\"][\"CO2\"] }} }",
      "fireWhenConditionsBecomeHot": true,
      "fireWhenConditionsStayHot": false,
      "fireWhenConditionsBecomeCold": false
    }
  ]
}
```

Building blocks:
- Scope: `productFilterId` (required for measurement triggers) plus either nothing (all devices), `devicesFilterIds`, or `tagsFilter` + `tagsFilterConjunction` (copy the values an existing rule reports in `rulesNG { tagsFilterConjunction }`).
- Triggers: `triggerOnMeasurement` (+ `triggeringMeasurementFields`), `triggerOnDeviceGoesOffline`, `triggerOnDeviceGoesOnline`, `triggerOnGatewayGoesOffline/Online`, `triggerOnSchedule` + `scheduleTriggerCrontab` (5-field cron in `timezone`), `triggerOnZoneEntry/Exit/LengthOfStay` + `zoneTagsFilter`, `zoneLengthOfStayTriggerMinutes`.
- Condition operands: left `{ kind: TRIGGERING_DEVICE_FIELD_VALUE | STATIC_DEVICE_FIELD_VALUE, fieldId, deviceId?, timerangeOperation?: { kind: AVERAGE|MIN|MAX|SUM|COUNT|ABSOLUTE_CHANGE|RELATIVE_CHANGE, start: "1 hour ago", end: "now" } }`; right `{ kind: STATIC_NUMBER_VALUE | STATIC_RANGE_VALUE | STATIC_BOOLEAN_VALUE | STATIC_STRING_VALUE | DYNAMIC_TRIGGERING_DEVICE_FIELD_VALUE | DYNAMIC_DEVICE_FIELD_VALUE | DYNAMIC_CONFIGURATION_FIELD_VALUE, numberValue | rangeValue: { start, end, includeBoundaries } | booleanValue | stringValue | fieldId (+ deviceId), hysteresis }`; `kind` operations: `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS`, `LESS_THAN`, `LESS_THAN_OR_EQUAL`, `GREATER_THAN`, `GREATER_THAN_OR_EQUAL`, `INSIDE_RANGE`, `OUTSIDE_RANGE`.
- Actions (`CreateRuleNGActionInputType`): `kind` `EMAIL` (`emailReceivers`, `emailSubject`, `emailBody`), `SMS` (`smsReceivers`, `smsBody`), `WEBHOOK` (`webhookUrl`, `webhookHeaders`, `webhookPayload`), `PUSH` (`pushTitle`, `pushBody`, `pushRecipientIds` from `workspace.pushRecipientCandidates`), `SINGLE_DEVICE_DOWNLINK` (`singleDeviceDownlinkId`, optional `singleDeviceDownlinkDeviceId`), `MULTI_DEVICE_DOWNLINK` (`multiDeviceDownlinkProductId`, `multiDeviceDownlinkId`, `multiDeviceDownlinkTagsFilter`), `SET_VALUE` (`setValueFieldId`, optional `setValueDeviceId`, one of `setValueNumeric`/`setValueBool`/`setValueString`/`setValueGeo`); firing flags `fireWhenConditionsBecomeHot/StayHot/BecomeCold`, `minSecondsBetweenHotConditions`, `maxConsecutiveActionExecutions` (0 = unlimited), `timeRestrictions`.
- Update: `updateRuleNG(id, input)` with the same fields plus `updateActions` (each with `id`) and `deleteActions: [id]`; toggling: `updateRuleNG(id: $id, input: { enabled: false })`. Delete: `deleteRuleNG(id)`.
- Inspect: `ruleNG(id) { … executionLogEntries(first: 20) { edges { node { triggerTimestamp conditionsResult anyActionFired triggeringDevice { verboseName } conditionsPrettyEvaluationTrace } } } }`.
- Legacy: `createRule(workspace, input: CloudRuleInputType)`, `updateRule`, `deleteRule(rule, workspace)`; avoid for new work.

## Dashboards and views

```graphql
mutation NewDashboard($input: AddDashboardInputType!) {
  addDashboard(input: $input) { ok dashboard { id name } }
}
```

`input`: `{ workspace, name, icon: "dashboard", sharingPolicy: workspace|public|restricted, sharedWith: [userIds], isHomeDashboard, dashboards: "<JSON>", metaJSON: "<JSON>" }`. The `dashboards` JSON is the portal's widget layout; copy one from an existing dashboard (`dashboard(id) { dashboards }`) rather than writing it by hand. `updateDashboard(input: { dashboard, workspace, name, sharingPolicy, dashboards, changeMessage })`, `deleteDashboard(dashboard, workspace)`.

Public link for a global dashboard:

```graphql
mutation DashLink($dashboardId: UUID!) {
  createDashboardPublicLink(input: { dashboardId: $dashboardId, token: "optional-password", name: "Customer view", mode: READ }) {
    ok
    publicLink { id token mode }
  }
}
```

Views (saved device list configurations): `addView(workspaceId, name, icon)`, `updateView(id, name, icon, config)`, `deleteView(id)`.

## Exports and reports

Manual export (raw datapoints, CSV/XLSX):

```graphql
mutation ManualExport($input: CreateManualExportInputType!) {
  createManualExport(input: $input) { ok errors export { id name } exportRun { id state } }
}
```

`input`: `{ workspaceId, name, timezone, deviceFilterTags: ["meter"], deviceFilterTagsConjunction: AND|OR, deviceFilterName, exportFieldSelection: ALL|FIELD_NAMES|SEMANTICS, exportFieldNames, exportSemantics, exportFormat: CSV|XLSX, csvDateFormat: ISO_8601|YMD_HMS, csvDelimiter: COMMA|SEMICOLON, emailReceivers, exportFrom, exportUntil }`. Poll `exportRun(id) { state artifacts { filename downloadUrl } expiresAt }` (`QUEUED`, `PROCESSING`, `WAITING_FOR_RETRY`, `COMPLETED`, `FAILED`). Periodic: `createPeriodicExport(input: { …same filters…, periodicEnabled, periodicInterval: DAILY|WEEKLY|MONTHLY })`, `updatePeriodicExport`, `deleteExport(input: { id })`.

Reports: `createReportBuilderReport(input: { workspaceId, name, schedule, timezone, deviceFilterTags, schema, output, locale, emailDeliveryEnabled, emailReceivers, ... })` then `runReportBuilderReport(input: { reportId, relativeBase, skipDelivery })`; legacy energy/CSV: `createReport(input: { workspace, name, crontab, crontabTimezone, reportKind: ENERGY|SIMPLE_CSV, emailReceivers })`, `updateEnergyReport`, `runReport(report)`.

## Zones, webhooks, folders, gateways

```graphql
mutation Zones($workspaceId: UUID!) {
  createZones(input: { workspaceId: $workspaceId, zones: [
    { name: "Warehouse", radius: 150, center: { latitude: 52.52, longitude: 13.405 }, tags: ["site-berlin"] }
  ] }) {
    ok
    validationErrors
    zones { id name }
  }
}
```

`updateZone(input: { id, name, radius, center, tags })`, `deleteZones(input: { ids })`.

Outgoing webhook:

```graphql
mutation Hook($workspaceId: String!) {
  createWebhook(input: {
    workspace: $workspaceId
    endpointUrl: "https://example.com/datacake"
    description: "Sync measurements"
    eventsToSend: ["device_measurement"]
    requestHeaders: [{ key: "X-Api-Key", value: "…" }]
  }) {
    ok
    webhook { id status }
  }
}
```

Events: `device_measurement`, `decoder_output`, `downlink`. Test with `tryWebhook`, inspect `webhook(id) { logs(start: 0) { created successful responseCode } errorRate }`.

Folders: `updateDeviceFolders(input: { workspaceId, deviceFolders: "<JSON>" })` (read the current JSON from `workspace.deviceFolders`, modify, write back).

Gateways (Datacake LNS): `createGateway(input: { workspaceId, name, eui, frequencyId })`, `claimGateway(input: { workspaceId, name, eui, authenticationCode, frequencyId })`, `updateGateway`, `deleteGateway`.

## Everything else

Billing (`purchasePlan`, `subscribeToAddOnPackage`, `getStripeCustomerPortal`, …), white label, SSO, Particle, 1NCE, Dragino, TTI managed applications, MQTT server configuration, Cake Red and D Zero mutations are listed in `reference/schema-map.md` (Mutations by theme) with their input types in `reference/schema.graphql`. Ask the user before touching billing or organization-level settings.
