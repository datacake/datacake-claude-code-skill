# Datacake platform concepts

How Datacake is structured, written for building on the GraphQL API. Every noun here maps to a GraphQL type; the type names are given in parentheses.

## Contents

- Entity model and ID cheat sheet
- Organization
- Workspace
- Members, API users and permissions
- White label sites
- Product
- Device
- Measurement fields
- Configuration fields
- Field roles and field semantics
- Tags, metadata and folders
- Zones
- Rules (Rule Engine)
- Dashboards and public links
- Reports and exports
- Claiming vs moving devices
- Plans, quotas and data retention
- Device connectivity and integrations
- Real-time outputs (MQTT, webhooks)
- Data residency

## Entity model and ID cheat sheet

```
Organization (billing, quotas, admins, white label)
└── Workspace (tenant: members, devices, rules, dashboards, reports, exports, webhooks, zones, gateways, folders)
    └── Product (template: fields, decoder, downlinks, dashboard layout, online timeout, integration config)
        └── Device (one product, own data, tags, metadata, plan)
            └── Field values (time series per device per field; field definitions live on the product)
```

| Thing | GraphQL type | Identifier | Notes |
|---|---|---|---|
| Organization | `OrganizationType` | `id` UUID | Owns billing plan and quotas; one or more workspaces |
| Workspace | `WorkspaceType` | `id` UUID, `slug` (immutable, URL) | `workspace(id:)` or `workspace(slug:)` |
| Product | `ProductType` | `id` UUID, `slug` (immutable, used in MQTT topics) | Workspace-bound; clone to reuse elsewhere |
| Device | `DeviceType` | `id` UUID, `serialNumber` (DevEUI for LoRaWAN, custom/auto serial for API devices) | `device(deviceId:)`, `workspace.device(id:|serialNumber:)` |
| Field definition | `ProductMeasurementFieldType` | `id` UUID, `fieldName` (identifier, UPPER_SNAKE by convention, immutable) | `verboseFieldName` is the editable display name |
| Field value | `DeviceCurrentMeasurementType` | device + `fieldName` | Latest value plus time-range functions |
| User | `UserType` | `id` UUID, `email` | Also API users (`isApiuser`) |
| Workspace membership | `UserWorkspaceRelationshipType` | `id` UUID | user + workspace + permissions + device relationships; `apiUserRelationships` for API users |
| Organization admin | `UserOrganizationRelationshipType` | `id` (Relay) | user + organization permissions; ids used by the organization member mutations |
| Pending invite | `UserWorkspaceInviteType` | `id` UUID, `email` | `workspace.invitedUsers`; resolves at signup |
| White label site | `WhitelabelSiteType` | `id` (Relay, usable as UUID), `brand`, `domain` | `user.whitelabelSites`, `whitelabelSite(id:)`, `branding`, `brandingForDomain(domain:)` |
| White label user / audit entry | `WhitelabelUserType` / `AuditLogEntryType` | `id` (Relay) | connections on the site; user ids differ from `UserType.id` |
| Rule (new engine) | `RuleNGType` | `id` UUID | Workspace-level, one product per rule, optional device/tag filter; see `rules-ng.md` |
| Dashboard (global) | `DashboardType` | `id` UUID | Device dashboards live in `product.dashboards` |
| Zone | `ZoneType` | `id` (Relay global ID) | Relay connections: `edges { node { … } }` |
| Export / Report Builder report | `ExportType` / `ReportBuilderReportType` | `id` (Relay global ID) | Runs produce downloadable artifacts |

Relay-style types (`Node` interface, `*Connection`, `edges`, `pageInfo`, `totalCount`) are used for organizations, zones, gateways, exports, report builder, device move requests and rule execution logs. Everything device-related uses plain lists or `page`/`pageSize`.

## Organization

- Created with the user's first workspace. Groups workspaces that share billing, device quota, SMS credits, add-ons, white label sites and SSO.
- Billing plan (`billingPlan`, Starter/paid packages, monthly or yearly) defines entitlements: device quota, rules quota, webhooks quota, workspaces quota, exports options, rule log retention, dashboard history, SSO. Device quota can be shared across workspaces or assigned per workspace (`deviceQuotaDistributionMode`, `assignWorkspaceQuota`). SMS credits likewise (`smsQuotaDistributionMode`, `transferSmsQuota`).
- Administrators (`userRelationships`, `UserOrganizationRelationshipType` with `UserOrganizationPermissions`): `create_workspaces`, `members` (manage admins), `billing`, `whitelabel`, `manage_workspaces`. One owner (`owner`, transferable with `transferOrganizationOwnership`). Admins are managed with `createUserOrganizationRelationships` (bulk, existing accounts), `updateUserOrganizationRelationships` (set/add/remove) and `deleteUserOrganizationRelationships`.
- Organization admins and workspace members are separate lists: an admin is not automatically a member of the workspaces, and a member has no organization rights. `organization.permissions` returns the caller's own admin permissions (use it to gate admin UI); `organizations(permissionFilter:)` lists every organization the caller administers. API users have no organization relationships.
- Organization Overview (portal) lists rules, reports and exports across all workspaces; API: `organization(id:) { workspaces { edges { node { … } } } }` shows every workspace of the organization including those the caller is not a member of (with `memberCount`, `deviceCount`, empty `myPermissions`). Full admin recipes: `organizations-and-members.md`.
- Billing runs through Stripe; `billingPlans`, `devicePlans`, `availableAddOnPackages`, `previewPlanSwitch` expose pricing data. Custom frontends normally never touch billing.

## Workspace

- The tenant boundary. Members only see workspaces they belong to; a personal token sees every workspace of that user (`allWorkspaces`).
- Holds: devices (`devices`, `devicesFiltered`, `deviceCount`), products (`products`), tags (`allTags`), metadata keys (`allMetadataKeys`), semantics in use (`semantics`), folders (`deviceFolders` JSON), members (`userRelationships`, `apiUserRelationships`, `invitedUsers`), rules (`rulesNG`, legacy `rules`), global dashboards (`dashboards`, `homeDashboard`), reports (`reports`, `reportBuilderReports`), exports (`exports`, `exportRuns`), outgoing webhooks (`webhooks`), zones (`zones`), Datacake LNS gateways (`gateways`), MQTT servers, integration configs, SMS settings and log, device move requests.
- `myPermissions` returns the caller's `WorkspacePermissions`; `features` returns enabled features (`RULE_ENGINE`, `ZONES`, `WHITELABEL_USERS`, `MANAGED_HELIUM`, `LIVE_CHAT`); `entitlement*` fields expose quotas relevant to this workspace.
- Name and logo are editable (`updateWorkspace`); the slug is fixed at creation. Deleting requires no active subscriptions.
- New workspaces: `addWorkspace(name, organizationId)`; without `organizationId` a new organization (separate billing) is created.

## Members, API users and permissions

Two member kinds share the same permission model:

| Kind | Auth | Created by | Typical use |
|---|---|---|---|
| User | email + password (optionally OTP), personal API token in Account Settings | `addUserToWorkspace` (by email; `invited: false` = account existed and is a member now, `invited: true` = invitation email sent) | Humans; token carries all rights of that user in all their workspaces |
| API user | token only (`apiUser.apiKey`) | `addApiUser` (Members > API Users) | Backends, kiosks, scripts; scope it to the minimum permissions and devices |

Workspace permissions (`WorkspacePermissions`, checked on writes and admin reads):

| Value | Grants |
|---|---|
| `basics` | edit workspace name and logo |
| `members` | invite/remove members and API users, set permissions |
| `billing` | billing, invoices, payment methods, SMS credits |
| `devices` | create, remove, move, claim devices; edit products |
| `rules` | rule engine (create, edit, delete rules, read logs) |
| `dashboards` | create/delete global dashboards |
| `reports`, `exports`, `zones`, `gateways`, `cakered`, `whitelabel` | the respective feature |

Device permissions (`DevicePermissions`, per user per device, or workspace-wide when `allDevicesPermissionExists`): viewing is implicit for any granted device; `edit_basics` (device definition: name, location, tags, metadata, image), `edit_product` (the shared product configuration: fields, decoder, dashboard, downlinks), `record_measurements` (write values via API, MQTT or manual input). Query `device.myPermissions(workspace:)` or `user.workspaceRelationship(workspace:)`. Change them with `setUserDevicePermissions` (per user) or `addDevicePermissions`/`removeDevicePermissions` (per device); workspace permissions change with `updateWorkspacePermissions` (a changeset of `{ permission, permitted }`).

Invites: an email without an account becomes a `UserWorkspaceInviteType` in `workspace.invitedUsers` (with the pending workspace and device permissions, `deviceInvites`). It turns into a membership when the person signs up with exactly that email; there is no accept, resend or expiry mutation, only `deleteUserInvite`. The `brand` argument of `addUserToWorkspace` (and of `signup`, `addWorkspace`, `requestPasswordReset`) selects the white label site whose branding the email carries. Reading any member list needs the `members` permission in that workspace.

Organization-level admins are separate from workspace members (see Organization). Everything about listing, inviting, moving and auditing members lives in `organizations-and-members.md`.

## White label sites

- A white label site (`WhitelabelSiteType`) is a branded copy of the portal on the customer's domain: title, logo, colours, login screen, sender address, hidden features (`hideProductConfiguration`, `disableDashboardEditing`, …), allowed device types and integrations. It belongs to an organization (`organization.whitelabelSites`, quota `entitlementWhitelabelSiteQuota`) and is managed by admins with the `whitelabel` permission; `user.whitelabelSites` lists the sites the caller may administer, `branding`/`brandingForDomain(domain:)` return the site for a login page without a token.
- Workspaces are attached to a site (`workspace.whitelabelSite`, `updateWorkspace(whitelabelSiteId:)`, or `addWorkspace(brand:)`); the site's `brand` is passed as `brand` on `signup`, `addUserToWorkspace`, `addWorkspace` and `requestPasswordReset` so emails and links use that branding.
- Sign-up policy: `allowSignup`, `restrictLoginToWhitelabelSite` (users of the site cannot log in on app.datacake.de or other sites), `autoAssignSignupsToOrganization` (new sign-ups land in the site's organization and share its billing instead of creating their own), `allowAddWorkspace`.
- Users and audit: `whitelabelSite.users` (accounts that signed up on or were invited through the site, with `dateJoined`, `lastVisit`, search and sort) and `auditLogEntries` (`AuditLogEntryAction`: logins, password changes, invites, removals, permission changes, device and product deletions, downlinks, organization admin changes). Both need `organization.entitlementWhitelabelShowUsersAndLogs`. Workspace feature `WHITELABEL_USERS` marks workspaces whose members are managed through a site.
- Enterprise SSO (WorkOS): `ssoEnabled`, `ssoDomains` with DNS verification records, `attachSsoDomain`/`detachSsoDomain`, `generateWorkosAdminPortalLink` for the customer's IT to connect their identity provider, `allowPasswordLogin: false` to enforce SSO; needs `entitlementEnterpriseSsoEnabled`.
- Site configuration mutations (`createWhitelabelSite`, `updateWhitelabelSite`, domain and email verification, cancel/reactivate) are indexed in `schema-map.md`; ask before touching them, they change what customers see.

## Product

- A product is the template every device inherits: database fields, payload decoder(s), downlinks/encoders, dashboard layout(s), icon, online timeout (`lastHeardThreshold` in minutes), configuration fields, gauges and integration settings (LNS credentials, MQTT server, HTTP decoder). Data is stored per device; definitions are shared. Changing a product changes all its devices immediately.
- Created when adding devices: from the template catalog (hundreds of LoRaWAN and API templates: decoder, fields, dashboard included), as a new empty product, or by adding devices to an existing product. `productKind: NEW | EXISTING | TEMPLATE` in the create mutations.
- Workspace-bound. Reuse in another workspace by cloning (`cloneProduct`, optionally with integration settings). Products with no devices can be deleted (`deleteProduct`) and disappear when the last device is removed.
- API products expose a per-product webhook URL `https://api.datacake.co/integrations/api/<id>/` whose HTTP decoder routes payloads to devices by serial number.
- `product.measurementFields` is the authoritative list of field identifiers for all devices of the product; `product.deviceCount` counts devices regardless of the caller's permissions.

## Device

- Belongs to exactly one product and one owning workspace; can additionally be claimed into other workspaces (`claims`, `inWorkspaces`).
- Core attributes: `verboseName`, `serialNumber`, `tags`, `metadata` (JSON string of key/value pairs), `location` (free-text description), `currentLocation { lat lng }` (from the field with role `DEVICE_LOCATION`), `online`/`lastHeard`/`lastHeardThreshold` (offline when no message within the product's online timeout), `image`, `icon`, `created`, `softwareVersion`, `features`.
- Data: `currentMeasurements`, `currentMeasurement`, `history`, `historyNg`, `historyStats`, `roleFields`, `numericSemanticField`, `booleanSemanticField`, `currentConfigurationValues`, `dashboardData`, `measurements24h`.
- Commercial: `plan(workspace:)`, `isOverQuota` (datapoint limit exceeded, new data dropped until reset), `active`/`activationProviders` (time-based activation windows).
- Kinds by connectivity: LoRaWAN (any supported LNS or the built-in Datacake LNS), API (HTTP webhook, external MQTT broker, REST record endpoint), Particle, NB-IoT (Dragino, 1NCE), D Zero gateways, plus devices added by pincode claiming.

## Measurement fields

- Defined on the product (`ProductMeasurementFieldType`); each stored value is a datapoint in the time-series database.
- Types (`FieldType` for creation): `FLOAT`, `INT`, `NUMERIC`, `BOOL`, `STRING`, `COUNTER`, `GEO` (stored as the string `"(lat,lng)"`). Existing fields may also report `OUTPUT`.
- `fieldName` (identifier) is immutable and is what the API, MQTT topics, decoders and rules use. `verboseFieldName` is the label. Convention: identifiers in UPPER_SNAKE_CASE.
- Extras: `unit` and `displayUnit`/`displayUnitOverride` (unit conversion or relabel), `floatDigits`, `color` (charts), `active` (inactive fields are hidden and not counted), `formula`/`useFormula` (calculated field from other fields; test with `tryFormula`), mapping fields (linear scaling, lookup table, reverse geocoding via `addFieldMapping`), `gauges` (value ranges with colors), `role`, `semantic`.
- Suggested fields: when a decoder emits identifiers that do not exist yet, they appear as `measurementFieldSuggestions` until created or ignored.
- Every write to a field also publishes an MQTT message and can trigger rules and outgoing webhooks, whether the value came from a device, the API, a downlink form or a rule action.

## Configuration fields

- Product-level settings with a default value and optional per-device override (`ConfigurationFieldType`, types `NUMBER`, `STRING`, `BOOL`).
- Read on a device with `currentConfigurationValues` (`isDefault` tells whether the default applies); set with `setDeviceConfigurationValue` (or `resetToDefault: true`).
- Available inside payload decoders and downlink encoders as the global `configurationValues` object and as a rule condition operand. Typical use: per-device thresholds, send intervals, external IDs.

## Field roles and field semantics

Roles (`RoleChoices`, at most one field per role per product): `PRIMARY`, `SECONDARY`, `DEVICE_BATTERY`, `DEVICE_SIGNAL`, `DEVICE_LOCATION`. They drive the device list/grid/map views and `device.roleFields`, and `DEVICE_LOCATION` is required for maps, `currentLocation` and zones. Roles are the product-agnostic way to show "the main value" of any device.

Semantics (`FieldSemantic`) label what a field measures so the platform can aggregate across products:

- Numeric: `TEMPERATURE`, `HUMIDITY`, `CO2`, `VOC`, `AIR_POLLUTION`, `AMBIENT_LIGHT`, `LOUDNESS`, `BATTERY`, `SIGNAL`, `SNR`, `POWER`, `ENERGY_CONSUMPTION`, `WATER_CONSUMPTION`, `WATER_DEPTH`, `FILL_LEVEL`, `SOIL_MOISTURE`, `PEOPLE_COUNT`, `RUNTIME_HOURS`, `HOURS_UNTIL_MAINTENANCE`; plus `LOCATION`.
- Boolean: `BATTERY_LOW`, `BUTTON_PRESSED`, `DESK_OCCUPIED`, `DEVICE_POWERED`, `DOOR_OPENED`, `EMERGENCY_TRIGGERED`, `GAS_LEAK_DETECTED`, `HVAC_ACTIVE`, `LIGHT_ON`, `MAINTENANCE_REQUIRED`, `MOTION_DETECTED`, `PARKING_OCCUPIED`, `POWER_OUTAGE_DETECTED`, `RAIN_DETECTED`, `ROOM_OCCUPIED`, `SMOKE_DETECTED`, `TAMPER_DETECTED`, `VALVE_OPENED`, `WATER_LEAK_DETECTED`, `WINDOW_OPENED`.

Semantics power the workspace and folder "Overview" KPIs, `devicesFiltered` semantic filters, `aggregatedNumericSemanticValue`, `aggregatedBooleanSemanticCount`, semantic exports and the built-in climate/IAQ dashboards. A device can have several fields with the same semantic (aggregated with AVG/SUM/MIN/MAX per device). See `semantics-and-kpis.md`.

## Tags, metadata and folders

- Tags: free-form strings on a device, the primary grouping mechanism (building, floor, room, customer, device class…). Filter with `devicesFiltered(tags: { contains: [...] })` (all tags) or `overlap` (any tag); `allDevices(searchTags:, searchTagsAnyAll:)`. Rules, exports, reports, folders and dashboards all filter by tags. Keep a consistent convention (`floor-1`, `room-101`).
- Metadata: arbitrary key/value pairs per device (`metadata` JSON string, keys listed in `workspace.allMetadataKeys`), for attributes that are not measurements (asset number, customer, install date). Editable with `updateDevice(input: { metadata })`.
- Folders: saved device subsets defined by tag filters (match all / match any, optionally online only) with selectable views (Overview with semantic KPIs, List, Grid, Map). Stored as JSON on the workspace (`deviceFolders`, `updateDeviceFolders`); they are a UI convenience, not a data-model entity.

## Zones

- Circular geofences (`ZoneType`: name, center lat/lng, radius in meters, tags) for asset tracking. Requires devices whose location field has the `DEVICE_LOCATION` role and the `ZONES` workspace feature.
- Data: `workspace.zones`, `zone.devicesInZone` (device, `enteredAt`), `workspace.deviceZoneEvents` (`ENTRY`/`EXIT` with timestamps), zone KPIs in the portal.
- Rules can trigger on zone entry, exit and length of stay, filtered by zone tags. Mutations: `createZones`, `updateZone`, `deleteZones`.

## Rules (Rule Engine)

New Rule Engine (`RuleNGType`, `workspace.rulesNG`, `ruleNG(id)`, mutations `createRuleNG`/`updateRuleNG`/`deleteRuleNG`; needs the `rules` permission and the `RULE_ENGINE` feature/add-on; quota `entitlementRulesQuota`, `entitlementRulesQuotaRemaining`). Full reference with list/read queries, id resolution, update semantics, template variables, logs and recipes: `rules-ng.md`.

| Part | Options |
|---|---|
| Scope | one product (`productFilter`) and either all its devices, explicit devices (`devicesFilter`) or tag filters (`tagsFilter` + `tagsFilterConjunction` `"AND"`/`"OR"`); one rule can cover up to 1000 devices |
| Execution mode | `DEVICE_LEVEL` (runs once per device; `triggering_device` in templates), `GATEWAY_LEVEL` (once per Datacake LNS gateway; `triggering_gateway`), `SYSTEM_LEVEL` (once per trigger, e.g. one scheduled report; address devices as `devices["<uuid>"]`). The API defaults to `DEVICE_LEVEL` |
| Triggers | new measurement (optionally only specific fields, by field UUID), device goes offline/online, gateway goes offline/online, schedule (`scheduleTriggerCrontab`, 5-field cron in the rule's `timezone`), zone entry/exit/length of stay |
| Conditions | optional; each compares a left operand (a field of the triggering device or of a fixed device, evaluated as current value or a time-range operation such as average/min/max/sum/count/change over e.g. `"1 hour ago"` to `"now"`) with a right operand (constant number with hysteresis, range, boolean, string, a field of the triggering or another device, or a configuration field of the triggering device) using `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS`, `LESS_THAN(_OR_EQUAL)`, `GREATER_THAN(_OR_EQUAL)`, `INSIDE_RANGE`, `OUTSIDE_RANGE`; chained with `AND`/`OR` |
| Actions | `EMAIL`, `SMS` (needs credits), `WEBHOOK` (URL, headers, payload template), `PUSH` (Datacake mobile app, workspace members), `SINGLE_DEVICE_DOWNLINK`, `MULTI_DEVICE_DOWNLINK` (by product + tags), `SET_VALUE` (write a field on the triggering or another device); each action fires when conditions become hot, stay hot and/or become cold, with `minSecondsBetweenHotConditions`, `maxConsecutiveActionExecutions` and weekday/time restrictions |
| Templates | email/SMS/push/webhook texts use `{{ … }}` placeholders (no `{% %}` tags): `{{ triggering_device['name'] }}`, `{{ triggering_device['measurements']['TEMPERATURE'] }}`, `{{ triggering_device['timestamps']['TEMPERATURE'] | datetime }}`, `{{ rule['name'] }}`; also `triggering_gateway`, `triggering_zone`, `devices["<uuid>"]`, filters `round(2)`, `datetime`, `json` (the only ones; an unknown filter leaves the text unrendered) |
| Logs | `ruleNG.executionLogEntries` (trigger, evaluation trace, fired actions, filterable), retrievable for `entitlementRulesLogRetrievableHours` |

Legacy rules (`workspace.rules`, `CloudRuleType`, `hasLegacyRules`) are per-device condition/action sets with hysteresis, retriggering and rate limits. Prefer the new engine for anything new. Per-user offline emails exist separately (`device.notifyOffline`, `setNotifyOffline`).

## Dashboards and public links

| | Device dashboard | Global dashboard |
|---|---|---|
| Defined on | product (`product.dashboards` JSON: tabs/sub-dashboards, widgets); rendered per device with `device.dashboardData` | workspace (`DashboardType.dashboards` JSON), can mix many devices, table widgets, tabs, sidebar folders |
| Sharing | public link per device: `device.publicLinks`, `createDevicePublicLink(device, input: { token, mode: READ|WRITE })`; viewers use `publicDevice(id:, token:)` | `sharingPolicy` `public`/`workspace`/`restricted` (+ `sharedWith`), public links with optional password: `createDashboardPublicLink`, viewers use `dashboardPublicLink(publicLink: { id, token })` |
| Write access | WRITE mode allows set-value and downlink widgets through `PublicDeviceAuthType` | WRITE mode likewise via `DashboardPublicLinkAuthInputType` |
| History | `dashboardChangelog` (entitlement-gated) | `dashboardChangelog` |

Widgets (portal): value, chart, map, image map, table, measurement list, boolean, heatmap, histogram, scatter, ASHRAE, cooling health, text, iframe, image, menu, SOS, downlink, set value. Custom frontends do not need the dashboard JSON; they query fields directly.

## Reports and exports

- Exports (`ExportType`, `workspace.exports`, `createManualExport`, `createPeriodicExport`): raw datapoints as CSV or XLSX for devices selected by tags (`AND`/`OR`), name or all; fields by `ALL`, `FIELD_NAMES` or `SEMANTICS`; manual (time range limited by `entitlementExportsManualMaxDays`) or periodic (`DAILY`/`WEEKLY`/`MONTHLY`); results are `ExportRunType` with `artifacts { downloadUrl }` and an `expiresAt`. Use exports for bulk historical data instead of thousands of `history` calls.
- Reports (`ReportType`, `workspace.reports`): Energy report (Excel; time buckets day/week/month with open/close/consumption per device, ideal for meters) and the deprecated Simple CSV; Report Builder (`ReportBuilderReportType`, `workspace.reportBuilderReports`): scheduled PDF/web reports with cover page, summary, trends, device health, delivered by email or link.

## Claiming vs moving devices

| | Claiming | Moving |
|---|---|---|
| Effect | another workspace gets access; the device stays owned and billed by the original workspace | ownership and billing transfer permanently |
| Mechanism | owner enables claiming and sets a claim code (`updateDevice(input: { canBeClaimed, claimCode })`); receiver adds the device with serial + code (`addPincodeDevice`); paid plans only; claiming switches itself off after use unless `allowMultipleClaims` | sender creates a move request (`createDeviceMoveRequest`); target workspace admin accepts (`acceptDeviceMoveRequest`, choosing plans) or rejects; sender can cancel |
| Visibility | owner sees `device.claims` and can `revokeDeviceClaims` | `workspace.incomingDeviceMoveRequests` / `outgoingDeviceMoveRequests` |
| Caveats | claimed devices show no datapoint usage to the claimer | rules, webhooks, reports are not moved; product is copied so the MQTT product slug changes |

## Plans, quotas and data retention

- Every device has a device plan (`DevicePlanType`: `datapointsPerDay`, `dataRetentionDays`/`dataRetentionMonths`, `maxPerWorkspace`; 0 = unlimited). Package plans fill devices from the organization quota; individual device subscriptions may also exist.
- A datapoint is one stored field value. The daily counter resets at 00:00 UTC; over the limit the device is `isOverQuota` and new data is dropped. Retention deletes the oldest data first. Documented tiers at the time of writing: Free 7 days retention / 500 datapoints per day; paid tiers 12 months / 7500 per day (older pay-as-you-go plans differ). Always read the numbers from `devicePlans` rather than hardcoding them.
- Implication for analytics: `history` can only return what retention still holds; free-tier devices lose data after a week.

## Device connectivity and integrations

| Path | How data arrives | Decoder |
|---|---|---|
| LoRaWAN via Datacake LNS | gateways registered in the workspace (`gateways`, `claimGateway`), devices with DevEUI/AppEUI/AppKey, class A or C, regional frequency plan | JavaScript `Decoder(bytes, port)` on the product returning `[{ field, value }]` |
| LoRaWAN via external LNS | TTN/TTI, ChirpStack, Loriot, Helium, Actility, Kerlink Wanesy, Senet, KPN, Netmore, Tektelic, Milesight gateway, Everynet, Orbiwise, CAT Telecom, Melita, Wiotys; the LNS forwards uplinks to a Datacake webhook | same |
| API device (HTTP) | any HTTPS client posts to the product webhook URL; optional paths and query params | `Decoder(request)` returning `[{ device: serial, field, value }]` (routing by serial) |
| API device (MQTT) | Datacake subscribes to an external broker (`mqttServers`) | MQTT decoders per topic |
| REST record | `POST https://api.datacake.co/v1/devices/<deviceId>/record/?batch=true` with `[{ field, value, timestamp? }]` | none (identifiers directly) |
| Internal MQTT publish | `dtck-pub/<product_slug>/<device_id>/<FIELD>` | none |
| Others | Particle, Sigfox, Dragino NB-IoT, 1NCE, Blues Notecard, Golioth, Swarm, Modbus gateways, D Zero, Cake Red (hosted Node-RED) | integration-specific |

Downlinks: defined per product (`lorawanDownlinks`, `apiDownlinks`, `mqttDownlinks`, Particle functions) with a JavaScript `Encoder(measurements, port)` returning bytes; sent with `sendDownlink(device, downlink)`, from dashboard widgets, or by rule actions. Encoders can read field values and configuration values.

## Real-time outputs (MQTT, webhooks)

- GraphQL has no subscriptions. For live data either poll (typically every 30 to 60 s) or use the internal MQTT broker: `mqtt.datacake.co` port 8883 (TLS; 1883 unencrypted; WebSocket `wss://mqtt.datacake.co:9001`), username and password both set to an access token, subscribe to `dtck/<product_slug>/<device_id>/<FIELD>` (wildcards `+`/`#`, e.g. `dtck/<product_slug>/+/TEMPERATURE`). Every field write publishes the new value. The product slug is shown in the device metadata section and in `product.slug`.
- Outgoing webhooks (`WebhookType`, `createWebhook`): per workspace, events `decoder_output`, device measurements, downlinks; JSON payloads with `device`, `field`, `value`, `timestamp`; call logs and error rate available. Quota `entitlementWebhooksQuota`.
- Rule engine webhooks and push/email/SMS complete the picture for alerting.

## Data residency

Hosted in the EU (Frankfurt primary, Amsterdam backup and failover), daily backups. Device data is transmitted with opaque IDs only. Access is strictly token-scoped: nobody outside the workspace, including Datacake staff, can read data unless invited.
