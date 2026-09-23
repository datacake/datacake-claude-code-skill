# Rule Engine NG: alerts and automations

How the new rule engine (`RuleNGType`, "Rule NG") works and how to list, read, create, update, delete and debug rules through the API. Verified against `reference/schema.graphql`, the portal's rule form and the platform documentation (https://docs.datacake.de/portal/rule-engine/new-rule-engine). Legacy rules (`CloudRuleType`) are only mentioned at the end.

## Contents

- Model
- Prerequisites: permission, feature, quota
- Resolve the ids a rule needs
- List rules
- Read one rule
- Execution mode
- Triggers
- Conditions
- Actions
- Create a rule
- Update a rule
- Enable, disable, delete
- Template language (email, SMS, push, webhook)
- Execution logs
- Recipes
- Pitfalls
- Legacy rules

## Model

```
Rule (workspace-scoped, needs the `rules` permission)
├─ FOR   scope: one product (productFilter) + all its devices | explicit devices (devicesFilter) | tag filter (tagsFilter, AND/OR)
│        executionMode: DEVICE_LEVEL (run per device) | GATEWAY_LEVEL (run per gateway) | SYSTEM_LEVEL (run once)
├─ WHEN  triggers: new measurement · device offline/online · gateway offline/online · schedule (cron in the rule's timezone) · zone entry/exit/length of stay
├─ IF    conditions (optional): left operand ⟨kind⟩ right operand, chained with AND/OR, optional hysteresis and time-range operation
└─ THEN  actions: EMAIL · SMS · PUSH · WEBHOOK · SINGLE_DEVICE_DOWNLINK · MULTI_DEVICE_DOWNLINK · SET_VALUE
         each with firing flags (become hot / stay hot / become cold), cooldown, execution limit, weekday/time restrictions
```

Rule-level fields: `name`, `description`, `enabled`, `timezone` (IANA name; used by the schedule trigger and the `datetime` template filter), `whitelabelSiteId` (branding of emails and push; empty = workspace default or Datacake). One rule covers up to 1000 devices. Rules are defined per product: one product per rule, so a fleet with three products needs three rules.

Evaluation: a trigger fires for one device (or gateway, or once for `SYSTEM_LEVEL`), the conditions are evaluated, and the result is compared with the previous result of that device: conditions "become hot" (false → true), "stay hot" (true → true) or "become cold" (true → false). Each action declares which of these events it reacts to. Every run is written to the execution log.

## Prerequisites: permission, feature, quota

```graphql
query RulePrerequisites($workspaceId: String!) {
  workspace(id: $workspaceId) {
    id myPermissions features
    entitlementRulesQuota entitlementRulesQuotaRemaining entitlementRulesLogRetrievableHours
    hasLegacyRules
  }
}
```

- `myPermissions` must contain `rules` for every write and for the logs (whether plain reads work without it is untested; handle a `null` `rulesNG`).
- `features` must contain `RULE_ENGINE`; the rule engine is a plan feature or add-on (Standard, Plus, Enterprise). Without it writes fail; read `error { code details }`.
- `entitlementRulesQuotaRemaining` is the number of rules that can still be created; at 0 expect an error such as `INSUFFICIENT_QUOTA`.
- `entitlementRulesLogRetrievableHours` limits how far back `executionLogEntries` reach.
- SMS actions consume organization SMS credits; push actions need the Datacake app on the recipients' phones and a branding with mobile push enabled.

## Resolve the ids a rule needs

Rule inputs reference everything by UUID: product, measurement fields (not the `fieldName` identifier), configuration fields, devices, downlinks, push recipients and the white label site. Resolve them once:

```graphql
query RuleBuildingBlocks($workspaceId: String!, $productId: String!, $tags: FilteredDeviceListTagsFilterInput) {
  product(id: $productId) {
    id name
    measurementFields(active: true) { id fieldName verboseFieldName fieldType unit }
    configurationFields { id fieldName fieldType }
    lorawanDownlinks { id name fport }
    apiConfiguration { apiDownlinks { id name } mqttDownlinks { id name } }
  }
  workspace(id: $workspaceId) {
    id
    whitelabelSite { id title }
    pushRecipientCandidates { reachable user { id email firstName lastName } }
    devicesFiltered(pageSize: 50, tags: $tags) { total devices { id verboseName serialNumber } }
  }
}
```

- `$tags` is `{ "contains": ["floor-1"] }` (all tags) or `null` for every device. One field by identifier: `product(id: $productId) { measurementField(fieldName: "CO2") { id } }`; one configuration field: `configurationField(fieldName: "TARGET_TEMPERATURE") { id }`.
- `python3 scripts/discover.py <workspace>` prints the field ids next to the identifiers, plus product downlinks; `python3 scripts/rules.py ids <workspace> --product <name>` prints only the rule building blocks.
- `pushRecipientCandidates(forWhitelabelSiteId:)` filters recipients for a white label brand; `reachable: false` means the member has not signed in to the app yet (still selectable).
- Devices in `devicesFilterIds` must belong to the product in `productFilterId`.

## List rules

`workspace.rulesNG` is a plain list (no pagination). Actions are a GraphQL union, so a list view selects only `__typename`:

```graphql
query Rules($workspaceId: String!) {
  workspace(id: $workspaceId) {
    rulesNG {
      id name enabled executionMode timezone
      productFilter { id name }
      devicesFilter { id }
      tagsFilter tagsFilterConjunction
      triggerOnMeasurement triggerOnDeviceGoesOffline triggerOnDeviceGoesOnline
      triggerOnGatewayGoesOffline triggerOnGatewayGoesOnline
      triggerOnSchedule scheduleTriggerCrontab
      triggerOnZoneEntry triggerOnZoneExit triggerOnZoneLengthOfStay
      conditions { id kind description }
      actions { __typename }
    }
  }
}
```

Across an organization: loop over `organization.workspaces` and query `rulesNG` per workspace; where the token lacks access the field comes back `null` or with an error, report those workspaces instead of failing. `python3 scripts/rules.py list <workspace>` prints this table; `--json` dumps it.

## Read one rule

`ruleNG(id:)` returns the full definition. Each action type carries the same common fields, but unions need one inline fragment per member:

```graphql
query Rule($id: UUID!) {
  ruleNG(id: $id) {
    id name description enabled timezone executionMode
    whitelabelSite { id title }
    productFilter { id name }
    devicesFilter { id verboseName }
    tagsFilter tagsFilterConjunction
    triggerOnMeasurement triggeringMeasurementFields { id fieldName }
    triggerOnDeviceGoesOffline triggerOnDeviceGoesOnline
    triggerOnGatewayGoesOffline triggerOnGatewayGoesOnline
    triggerOnSchedule scheduleTriggerCrontab
    triggerOnZoneEntry triggerOnZoneExit triggerOnZoneLengthOfStay
    zoneLengthOfStayTriggerMinutes zoneTagsFilter zoneTagsFilterConjunction
    conditions {
      id description conjunction kind
      leftOperand { kind fieldId deviceId timerangeOperation { kind start end } }
      rightOperand { kind numberValue rangeValue { start end includeBoundaries } hysteresis booleanValue stringValue geofenceValue fieldId deviceId }
    }
    actions {
      __typename
      ... on RuleNGEmailActionType { id description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold minSecondsBetweenHotConditions maxConsecutiveActionExecutions timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } } emailReceivers emailSubject emailBody }
      ... on RuleNGSmsActionType { id description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold minSecondsBetweenHotConditions maxConsecutiveActionExecutions timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } } smsReceivers smsBody }
      ... on RuleNGPushActionType { id description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold minSecondsBetweenHotConditions maxConsecutiveActionExecutions timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } } pushTitle pushBody pushRecipients { id email } }
      ... on RuleNGWebhookActionType { id description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold minSecondsBetweenHotConditions maxConsecutiveActionExecutions timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } } webhookUrl webhookHeaders { key value } webhookPayload }
      ... on RuleNGSingleDeviceDownlinkActionType { id description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold minSecondsBetweenHotConditions maxConsecutiveActionExecutions timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } } singleDeviceDownlinkDevice { id verboseName } singleDeviceDownlink { ... on LoRaWanDownlinkType { id name } ... on ApiDownlinkType { id name } ... on MqttDownlinkType { id name } ... on Cellular1nceDownlinkType { id name } ... on ParticleDownlinkType { id name } ... on ProductFunctionType { id } } }
      ... on RuleNGMultiDeviceDownlinkActionType { id description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold minSecondsBetweenHotConditions maxConsecutiveActionExecutions timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } } multiDeviceDownlinkProduct { id name } multiDeviceDownlinkTagsFilter multiDeviceDownlinkTagsFilterConjunction multiDeviceDownlink { ... on LoRaWanDownlinkType { id name } ... on ApiDownlinkType { id name } ... on MqttDownlinkType { id name } ... on Cellular1nceDownlinkType { id name } ... on ParticleDownlinkType { id name } ... on ProductFunctionType { id } } }
      ... on RuleNGSetValueActionType { id description fireWhenConditionsBecomeHot fireWhenConditionsStayHot fireWhenConditionsBecomeCold minSecondsBetweenHotConditions maxConsecutiveActionExecutions timeRestrictions { kind timeRestrictions { start { dayOfWeek time } end { dayOfWeek time } } } setValueDevice { id verboseName } setValueField { id fieldName } setValueNumeric setValueBool setValueString setValueGeo }
    }
  }
}
```

`python3 scripts/rules.py get <rule-id>` runs this query; `rules.py export <rule-id> --file rule.json` converts the result into a `CreateRuleNGInputType` payload (ids of fields, devices and actions stripped where needed) that can be edited and re-created in another workspace.

## Execution mode

`executionMode` decides how often a trigger runs the rule and which template variables exist. The API defaults to `DEVICE_LEVEL` when the field is omitted; always set it explicitly.

| Mode | Runs | Template context | Portal templates that use it |
|---|---|---|---|
| `DEVICE_LEVEL` | once per device in scope (per triggering device for measurements, per device for offline/online, per device for a schedule) | `triggering_device` | New measurement, device goes offline/online, device-dependent scheduler, zone entry/exit/length of stay |
| `GATEWAY_LEVEL` | once per Datacake LNS gateway of the workspace | `triggering_gateway` | Gateway goes offline/online, gateway scheduler |
| `SYSTEM_LEVEL` | once per trigger, independent of devices | no `triggering_device`; use `devices["<uuid>"]` and `STATIC_DEVICE_FIELD_VALUE` operands | System scheduler (one report or downlink batch at a time) |

A schedule with `DEVICE_LEVEL` on a product with 100 devices runs 100 times at 09:00 and can send 100 emails; use `SYSTEM_LEVEL` for one summary.

## Triggers

Any combination of the flags below can be enabled on one rule; a rule with no trigger never runs.

| Trigger | Input fields | Notes | Log `initiator` |
|---|---|---|---|
| New measurement | `triggerOnMeasurement: true`, `triggeringMeasurementFields: [<field uuid>]` | needs `productFilterId`; empty field list = any field of the product. Without conditions the rule fires on every stored value | `NEW_MEASUREMENTS` |
| Device goes offline / online | `triggerOnDeviceGoesOffline`, `triggerOnDeviceGoesOnline` | based on the product's online timeout (`lastHeardThreshold`); one execution per device that changes state | `DEVICE_GOES_OFFLINE`, `DEVICE_GOES_ONLINE` |
| Gateway goes offline / online | `triggerOnGatewayGoesOffline`, `triggerOnGatewayGoesOnline` | `executionMode: GATEWAY_LEVEL`; Datacake LNS gateways only | `GATEWAY_GOES_OFFLINE`, `GATEWAY_GOES_ONLINE` |
| Schedule | `triggerOnSchedule: true`, `scheduleTriggerCrontab: "0 8 * * 1-5"` | 5-field cron (`min hour day month weekday`, `*` `,` `-` `/`), evaluated in the rule's `timezone`; `DEVICE_LEVEL` runs per device, `SYSTEM_LEVEL` once | `SCHEDULE` |
| Zone entry / exit / length of stay | `triggerOnZoneEntry`, `triggerOnZoneExit`, `triggerOnZoneLengthOfStay` + `zoneLengthOfStayTriggerMinutes`, `zoneTagsFilter` + `zoneTagsFilterConjunction` | needs the `ZONES` feature and a field with the `DEVICE_LOCATION` role; zone tags select which zones count | `ZONE_ENTRY`, `ZONE_EXIT`, `ZONE_LENGTH_OF_STAY` |

Conditions are optional for offline/online, gateway, schedule and zone triggers. For measurement triggers define at least one condition, or the rule fires on every uplink.

## Conditions

Each condition compares a left operand with a right operand. `RuleNGConditionInputType`:

| Field | Value |
|---|---|
| `id` | client-generated UUID v4; keep it stable across updates so logs stay readable |
| `description` | required string, `""` allowed (the portal autogenerates a label) |
| `conjunction` | `AND` or `OR`: how this condition joins the previous one (the portal sets `AND` on the first condition) |
| `kind` | `EQUALS`, `NOT_EQUALS`, `CONTAINS`, `NOT_CONTAINS` (strings), `LESS_THAN`, `LESS_THAN_OR_EQUAL`, `GREATER_THAN`, `GREATER_THAN_OR_EQUAL`, `INSIDE_RANGE`, `OUTSIDE_RANGE` (with `rangeValue`) |
| `leftOperand` | `{ kind: TRIGGERING_DEVICE_FIELD_VALUE, fieldId }` (the device being evaluated; do not send `deviceId`) or `{ kind: STATIC_DEVICE_FIELD_VALUE, fieldId, deviceId }` (a fixed device, also from another product); optional `timerangeOperation` |
| `rightOperand` | one of the kinds below |

Right operand kinds (`RuleNGRightOperandInputType`):

| `kind` | Fields | Meaning |
|---|---|---|
| `STATIC_NUMBER_VALUE` | `numberValue`, `hysteresis` (send `0`, not `null`) | constant threshold |
| `STATIC_RANGE_VALUE` | `rangeValue: { start, end, includeBoundaries }` | with `INSIDE_RANGE` / `OUTSIDE_RANGE` |
| `STATIC_BOOLEAN_VALUE` | `booleanValue` | with `EQUALS` / `NOT_EQUALS` |
| `STATIC_STRING_VALUE` | `stringValue` | with `EQUALS`, `CONTAINS`, … |
| `DYNAMIC_TRIGGERING_DEVICE_FIELD_VALUE` | `fieldId` | another field of the same device (e.g. setpoint field) |
| `DYNAMIC_DEVICE_FIELD_VALUE` | `fieldId`, `deviceId` | a field of a fixed device (e.g. outdoor sensor) |
| `DYNAMIC_CONFIGURATION_FIELD_VALUE` | `fieldId` = configuration field id | per-device threshold from a configuration field of the triggering device (default value or device override) |

`geofenceValue` is a string for location fields; the portal writes it, the format is undocumented: copy it from an existing rule (`rules.py get`).

Hysteresis: with `GREATER_THAN 30` and `hysteresis: 2` the condition becomes hot above 30 and becomes cold only once the value drops below 28, which suppresses flapping around the threshold.

Time-range operation on the left operand (`timerangeOperation: { kind, start, end }`): instead of the current value, evaluate an aggregate over a window given in plain English relative phrases (`"15 minutes ago"`, `"24 hours ago"`, `"7 days ago"`, `"now"`; English only). Kinds: `AVERAGE`, `MIN`, `MAX`, `SUM`, `COUNT` (number of datapoints; use it to detect missing uplinks), `ABSOLUTE_CHANGE` (last minus first value in the window), `RELATIVE_CHANGE` (the same change as a percentage). The platform docs describe the two change kinds inconsistently, so confirm the behaviour on a test rule with `conditionsPrettyEvaluationTrace`. The window must be longer than the device's send interval, otherwise `MIN`/`MAX` see a single value.

"Stays above/below for N minutes" is expressed with `MIN`/`MAX`: `MIN` over the last 30 minutes `GREATER_THAN 10` means every value in the window was above 10; `MAX` over the last 60 minutes `LESS_THAN -10` means it never rose above -10.

Mixed `AND`/`OR` chains have no documented precedence; keep one conjunction per rule or split into two rules.

## Actions

Common fields of every action (`CreateRuleNGActionInputType`):

| Field | Meaning |
|---|---|
| `kind` | `EMAIL`, `SMS`, `PUSH`, `WEBHOOK`, `SINGLE_DEVICE_DOWNLINK`, `MULTI_DEVICE_DOWNLINK`, `SET_VALUE` |
| `description` | label in the portal |
| `fireWhenConditionsBecomeHot` | run when the conditions turn true (the alarm) |
| `fireWhenConditionsStayHot` | run again on every evaluation while they stay true (reminders); combine with the two limits below |
| `fireWhenConditionsBecomeCold` | run when they turn false again (all-clear, revert a set value) |
| `minSecondsBetweenHotConditions` | cooldown between two hot executions (0 = none) |
| `maxConsecutiveActionExecutions` | how many times the action may run while the conditions stay hot (0 = unlimited) |
| `timeRestrictions` | `{ kind: ENABLED_DURING | DISABLED_DURING, timeRestrictions: [{ start: { dayOfWeek, time }, end: { dayOfWeek, time } }] }`; `dayOfWeek` 0 = Sunday … 6 = Saturday, `time` `"HH:MM"` in the rule's timezone; each entry is one continuous window from start to end (Monday 08:00 to Friday 18:00 includes the nights), so business hours need one entry per day. Outside the window the action is skipped and logged as not executed |

Rules without conditions (offline, schedule, zone) fire their actions on the trigger; keep `fireWhenConditionsBecomeHot: true` for them.

Type-specific fields:

| `kind` | Fields | Notes |
|---|---|---|
| `EMAIL` | `emailReceivers: [String]`, `emailSubject`, `emailBody` | body may contain HTML and template tags; branding from `whitelabelSiteId` |
| `SMS` | `smsReceivers: [String]` (E.164), `smsBody` | needs organization SMS credits |
| `PUSH` | `pushTitle`, `pushBody` (≤ 255 characters each), `pushRecipientIds: [user uuid]` from `pushRecipientCandidates` | Datacake mobile app only; needs Datacake branding or a white label brand with mobile push. Members who leave the workspace are dropped silently |
| `WEBHOOK` | `webhookUrl`, `webhookHeaders: [{ key, value }]`, `webhookPayload` (string; usually a JSON template) | one HTTP POST per execution; the response is recorded in the log |
| `SINGLE_DEVICE_DOWNLINK` | `singleDeviceDownlinkId` (a downlink of the rule's product), optional `singleDeviceDownlinkDeviceId` | omit the device id to target the triggering device (schedule on `DEVICE_LEVEL` = every device gets its downlink) |
| `MULTI_DEVICE_DOWNLINK` | `multiDeviceDownlinkProductId`, `multiDeviceDownlinkId`, `multiDeviceDownlinkTagsFilter`, `multiDeviceDownlinkTagsFilterConjunction` (`AND`/`OR`) | downlink to every device of another product (optionally filtered by tags), e.g. when an outdoor sensor triggers |
| `SET_VALUE` | `setValueFieldId`, optional `setValueDeviceId`, exactly one of `setValueNumeric`, `setValueBool`, `setValueString`, `setValueGeo` (`"(lat,lng)"`) | writes a datapoint (publishes MQTT, can trigger other rules); omit the device id for the triggering device. `setValueFloat`/`setValueInt` are deprecated |

## Create a rule

`createRuleNG(workspaceId: UUID!, input: CreateRuleNGInputType!)`. `name` is the only required field; everything else defaults to off/empty. The example creates a product-level CO₂ alarm with an all-clear email and a webhook (the input is written inline so it validates against the schema; in code pass it as the `$input` variable):

```graphql
mutation CreateRule($workspaceId: UUID!) {
  createRuleNG(
    workspaceId: $workspaceId
    input: {
      name: "High CO2"
      description: "Notify the facility team"
      timezone: "Europe/Berlin"
      enabled: true
      executionMode: DEVICE_LEVEL
      productFilterId: "<product uuid>"
      tagsFilter: ["floor-1"]
      tagsFilterConjunction: "AND"
      triggerOnMeasurement: true
      triggeringMeasurementFields: ["<CO2 field uuid>"]
      conditions: [
        {
          id: "<client-generated uuid v4>"
          description: ""
          conjunction: AND
          kind: GREATER_THAN
          leftOperand: { kind: TRIGGERING_DEVICE_FIELD_VALUE, fieldId: "<CO2 field uuid>" }
          rightOperand: { kind: STATIC_NUMBER_VALUE, numberValue: 1000, hysteresis: 50 }
        }
      ]
      createActions: [
        {
          kind: EMAIL
          description: "Mail"
          emailReceivers: ["facility@example.com"]
          emailSubject: "CO2 high in {{ triggering_device['name'] }}"
          emailBody: "CO2 is {{ triggering_device['measurements']['CO2'] }} ppm at {{ triggering_device['timestamps']['CO2'] | datetime }}"
          fireWhenConditionsBecomeHot: true
          fireWhenConditionsStayHot: false
          fireWhenConditionsBecomeCold: true
          minSecondsBetweenHotConditions: 3600
          maxConsecutiveActionExecutions: 0
        }
        {
          kind: WEBHOOK
          description: "Ticket"
          webhookUrl: "https://example.com/hooks/datacake"
          webhookHeaders: [{ key: "Authorization", value: "Bearer …" }]
          webhookPayload: "{\"device\": \"{{ triggering_device['id'] }}\", \"co2\": {{ triggering_device['measurements']['CO2'] }}}"
          fireWhenConditionsBecomeHot: true
          fireWhenConditionsStayHot: false
          fireWhenConditionsBecomeCold: false
        }
      ]
    }
  ) {
    ok
    error { code details }
    ruleNG { id name enabled }
  }
}
```

The same payload as a variables document, in the shape `scripts/rules.py create --file rule.json` expects:

```json CreateRuleNGInputType
{
  "name": "High CO2",
  "timezone": "Europe/Berlin",
  "enabled": true,
  "executionMode": "DEVICE_LEVEL",
  "productFilterId": "<product uuid>",
  "triggerOnMeasurement": true,
  "triggeringMeasurementFields": ["<CO2 field uuid>"],
  "conditions": [
    {
      "id": "<client-generated uuid v4>", "description": "", "conjunction": "AND", "kind": "GREATER_THAN",
      "leftOperand": { "kind": "TRIGGERING_DEVICE_FIELD_VALUE", "fieldId": "<CO2 field uuid>" },
      "rightOperand": { "kind": "STATIC_NUMBER_VALUE", "numberValue": 1000, "hysteresis": 50 }
    }
  ],
  "createActions": [
    {
      "kind": "EMAIL", "description": "Mail",
      "emailReceivers": ["facility@example.com"],
      "emailSubject": "CO2 high in {{ triggering_device['name'] }}",
      "emailBody": "CO2 is {{ triggering_device['measurements']['CO2'] }} ppm",
      "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": true,
      "minSecondsBetweenHotConditions": 3600, "maxConsecutiveActionExecutions": 0
    }
  ]
}
```

Checklist before sending: `productFilterId` set for device-level triggers · field ids belong to that product · every condition has a fresh UUID `id` and `hysteresis` is a number · each action has all three `fireWhen…` flags · `executionMode` explicit · `timezone` set when a schedule is used · `ok` checked and `error { code details }` surfaced (`details` usually names the offending field).

## Update a rule

`updateRuleNG(id: UUID!, input: UpdateRuleNGInputType!)`. Send only the fields to change; omitted fields keep their value (do not send `""` to "leave unchanged"). Semantics that differ from create:

| Field | Update semantics |
|---|---|
| `devicesFilterIds` | object `{ set: [...] }` (replace), `{ add: [...] }`, `{ remove: [...] }` |
| `triggeringMeasurementFields` | same `{ set | add | remove }` object |
| `conditions` | replaces the whole list; send every condition you want to keep (with its existing `id`) |
| `createActions` | adds actions (no `id`) |
| `updateActions` | each entry needs the existing action `id`; only the given fields change |
| `deleteActions` | list of action ids to remove |
| `productFilterId`, `whitelabelSiteId` | `BlankableUUID`: `""` clears |

```graphql
mutation UpdateRule($id: UUID!) {
  updateRuleNG(
    id: $id
    input: {
      devicesFilterIds: { add: ["<device uuid>"] }
      triggeringMeasurementFields: { set: ["<field uuid>"] }
      updateActions: [{ id: "<action uuid>", emailReceivers: ["ops@example.com", "facility@example.com"], minSecondsBetweenHotConditions: 1800 }]
      deleteActions: ["<other action uuid>"]
    }
  ) {
    ok
    error { code details }
    ruleNG { id name enabled devicesFilter { id } actions { __typename } }
  }
}
```

Read the rule first (`rules.py get`), edit, then update; `rules.py update <rule-id> --file patch.json` sends a `UpdateRuleNGInputType` document.

## Enable, disable, delete

```graphql
mutation ToggleRule($id: UUID!, $enabled: Boolean!) {
  updateRuleNG(id: $id, input: { enabled: $enabled }) { ok error { code details } ruleNG { id enabled } }
}
```

```graphql
mutation DeleteRule($id: UUID!) {
  deleteRuleNG(id: $id) { ok error { code details } }
}
```

Deleting removes the rule with its conditions and actions; there is no undo and no `dryRun`. Confirm with the user first; `rules.py delete` requires `--execute`. Disabling keeps everything and stops evaluation.

## Template language (email, SMS, push, webhook)

Subjects, bodies, push texts and webhook payloads are rendered with the Django Template Language: `{{ variable }}`, filters with `|`, tags such as `{% if %}…{% else %}…{% endif %}` and `{% for %}`. Keys are accessed with brackets, single or double quotes: `{{ triggering_device['name'] }}` equals `{{ triggering_device["name"] }}`. Measurement keys are the field identifiers (`fieldName`), not the display names.

Variables (as offered by the portal's autocomplete):

| Variable | Keys | Available when |
|---|---|---|
| `rule` | `id`, `name` | always |
| `triggering_device` | `id`, `name`, `serial_number`, `location`, `tags`, `online`, `last_heard`, `dashboard_url`, `measurements[<FIELD>]` (latest value), `timestamps[<FIELD>]` (UTC ISO string of that value) | `DEVICE_LEVEL` |
| `devices["<device uuid>"]` | same keys as `triggering_device` | any mode; any device of the workspace (the basis for `SYSTEM_LEVEL` reports) |
| `triggering_gateway` | `id`, `name`, `eui`, `online`, `last_seen`, `last_check`, `connected_at`, `round_trip_median_time`, `uplink_count`, `downlink_count`, `latitude`, `longitude`, `altitude` | `GATEWAY_LEVEL` |
| `gateways["<gateway uuid>"]` | same keys as `triggering_gateway` | any mode |
| `triggering_zone` | `id`, `name`, `entered_at`, `exited_at`, `length_of_stay`, `still_in_zone_at` | zone triggers |

`triggering_device['values'][<FIELD>]` is an accepted alias of `measurements` in older docs; prefer `measurements`.

Filters:

| Filter | Effect |
|---|---|
| `\| datetime` | timestamp in the rule's `timezone`, default format |
| `\| datetime("%d.%m.%Y %H:%M")` | strftime format |
| `\| round(2)` | numeric value with two decimals |
| `\| json` | JSON literal (`true`/`false`, quoted strings, lists) for webhook payloads |
| Django built-ins | `\| default:"n/a"`, `\| floatformat:1`, `\| upper`, `\| date:"c"`, `\| timesince` |

Examples:

```
Subject: {{ rule['name'] }}: {{ triggering_device['name'] }}
Body:
{{ triggering_device['name'] }} ({{ triggering_device['serial_number'] }}) reported
{{ triggering_device['measurements']['TEMPERATURE'] | round(2) }} °C
at {{ triggering_device['timestamps']['TEMPERATURE'] | datetime("%d.%m.%Y %H:%M") }}.
{% if triggering_device['measurements']['TEMPERATURE'] > 30 %}Too warm.{% else %}Back to normal.{% endif %}
Dashboard: {{ triggering_device['dashboard_url'] }}
```

Webhook payload (a JSON template: strings quoted, numbers raw, booleans and lists through `| json`):

```
{
  "rule": "{{ rule['name'] }}",
  "device": "{{ triggering_device['id'] }}",
  "name": "{{ triggering_device['name'] }}",
  "temperature": {{ triggering_device['measurements']['TEMPERATURE'] }},
  "door_open": {{ triggering_device['measurements']['DOOR_OPENED'] | json }},
  "tags": {{ triggering_device['tags'] | json }},
  "measured_at": "{{ triggering_device['timestamps']['TEMPERATURE'] }}"
}
```

Discovering keys: add `"debug": "{{ triggering_device }}"` to a webhook payload or email body once, read the rendered object in the log or the received request, then remove it. The execution log also stores the full template context in `runtimeVariables` and `extraTemplateVariables`. In `SYSTEM_LEVEL` there is no `triggering_device`; address devices explicitly with `devices["<uuid>"]`.

## Execution logs

Every evaluation writes a `RuleExecutionLogEntryType` (Relay connection on the rule; retention `entitlementRulesLogRetrievableHours`; the portal shows them under Rule Engine > Logs):

```graphql
query RuleLogs($id: UUID!, $after: String, $since: DateTime!) {
  ruleNG(id: $id) {
    id name
    executionLogEntries(
      first: 50
      after: $after
      filter: { triggerTimestamp: { gte: $since }, anyActionFired: { exact: true } }
    ) {
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id initiator triggerTimestamp executionTimestamp completionTimestamp
          triggeringDevice { id verboseName }
          triggeringGateway { id name }
          conditionsResult conditionsPrettyEvaluationTrace
          actionFiringEvent anyActionFired
          actionExecutionLogEntries { id kind isFired isFiredByEvent isWithinActiveTimePeriod prettyTrace }
          runtimeVariables
        }
      }
    }
  }
}
```

- Filter: `triggerTimestamp { gt gte lt lte }`, `anyActionFired { exact }`, `triggeringDeviceId { exact }`, `triggeringGatewayId { exact }`, combinable with `and`, `or`, `not`.
- `initiator` is the trigger (`NEW_MEASUREMENTS`, `SCHEDULE`, `DEVICE_GOES_OFFLINE`, …); `actionFiringEvent` is `CONDITIONS_BECOME_HOT`, `CONDITIONS_STAY_HOT`, `CONDITIONS_BECOME_COLD` or `NONE`.
- `conditionsPrettyEvaluationTrace` shows each operand's value and the result; `prettyTrace` per action explains why it fired or was skipped (cooldown, limit, time restriction, `isWithinActiveTimePeriod`).
- `runtimeVariables`, `conditionsEvaluationVariables`, `actionExecutionVariables`, `extraTemplateVariables` are `JSONString`s: parse them; they hold the template context and per-action results.
- `python3 scripts/rules.py logs <rule-id> [--since 24h] [--fired]` prints a table.

## Recipes

Payloads are `CreateRuleNGInputType` documents; replace the placeholders with ids from `discover.py` or `rules.py ids`.

Offline alarm for every device of a product:

```json CreateRuleNGInputType
{
  "name": "Sensor offline", "timezone": "Europe/Berlin", "enabled": true, "executionMode": "DEVICE_LEVEL",
  "productFilterId": "<product uuid>",
  "triggerOnDeviceGoesOffline": true, "triggerOnDeviceGoesOnline": false,
  "createActions": [
    { "kind": "EMAIL", "description": "Offline mail", "emailReceivers": ["ops@example.com"],
      "emailSubject": "{{ triggering_device['name'] }} is offline",
      "emailBody": "Last heard {{ triggering_device['last_heard'] | datetime }}. {{ triggering_device['dashboard_url'] }}",
      "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false,
      "minSecondsBetweenHotConditions": 0, "maxConsecutiveActionExecutions": 0 }
  ]
}
```

Create a second rule with `triggerOnDeviceGoesOnline: true` for the all-clear (offline and online are separate triggers, not hot/cold states of one condition). With 50 devices offline you get 50 mails; a digest needs your own code on top of `devicesFiltered(online: false) { total }`.

Threshold with hysteresis, reminder every hour at most three times, all-clear mail:

```json CreateRuleNGActionInputType[]
[
  { "kind": "EMAIL", "description": "Alarm and reminders", "emailReceivers": ["cold-chain@example.com"],
    "emailSubject": "{{ triggering_device['name'] }}: {{ triggering_device['measurements']['TEMPERATURE'] | round(2) }} °C",
    "emailBody": "Threshold 8 °C exceeded at {{ triggering_device['timestamps']['TEMPERATURE'] | datetime }}.",
    "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": true, "fireWhenConditionsBecomeCold": false,
    "minSecondsBetweenHotConditions": 3600, "maxConsecutiveActionExecutions": 3 },
  { "kind": "EMAIL", "description": "All clear", "emailReceivers": ["cold-chain@example.com"],
    "emailSubject": "{{ triggering_device['name'] }} back to normal", "emailBody": "Temperature is {{ triggering_device['measurements']['TEMPERATURE'] }} °C again.",
    "fireWhenConditionsBecomeHot": false, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": true,
    "minSecondsBetweenHotConditions": 0, "maxConsecutiveActionExecutions": 0 }
]
```

with the condition `GREATER_THAN 8`, `hysteresis: 1` on the temperature field and `triggerOnMeasurement: true`.

Temperature stays below -10 °C for 15 minutes (max over the window below the limit):

```json RuleNGConditionInputType[]
[
  { "id": "<uuid v4>", "description": "max of last 15 min below -10", "conjunction": "AND", "kind": "LESS_THAN",
    "leftOperand": { "kind": "TRIGGERING_DEVICE_FIELD_VALUE", "fieldId": "<TEMPERATURE field uuid>",
                     "timerangeOperation": { "kind": "MAX", "start": "15 minutes ago", "end": "now" } },
    "rightOperand": { "kind": "STATIC_NUMBER_VALUE", "numberValue": -10, "hysteresis": 0 } }
]
```

Per-device threshold from a configuration field (one rule, different setpoints per device):

```json RuleNGConditionInputType[]
[
  { "id": "<uuid v4>", "description": "above target", "conjunction": "AND", "kind": "GREATER_THAN",
    "leftOperand": { "kind": "TRIGGERING_DEVICE_FIELD_VALUE", "fieldId": "<TEMPERATURE field uuid>" },
    "rightOperand": { "kind": "DYNAMIC_CONFIGURATION_FIELD_VALUE", "fieldId": "<TARGET_TEMPERATURE configuration field uuid>", "hysteresis": 0 } }
]
```

Missing data: no datapoint in the last 2 hours (`COUNT` over the window equals 0, evaluated by a device-level schedule every 30 minutes; complements the offline trigger when the online timeout is long):

```json CreateRuleNGInputType
{
  "name": "No data for 2 h", "timezone": "Europe/Berlin", "enabled": true, "executionMode": "DEVICE_LEVEL",
  "productFilterId": "<product uuid>",
  "triggerOnSchedule": true, "scheduleTriggerCrontab": "*/30 * * * *",
  "conditions": [
    { "id": "<uuid v4>", "description": "", "conjunction": "AND", "kind": "EQUALS",
      "leftOperand": { "kind": "TRIGGERING_DEVICE_FIELD_VALUE", "fieldId": "<TEMPERATURE field uuid>",
                       "timerangeOperation": { "kind": "COUNT", "start": "2 hours ago", "end": "now" } },
      "rightOperand": { "kind": "STATIC_NUMBER_VALUE", "numberValue": 0, "hysteresis": 0 } }
  ],
  "createActions": [
    { "kind": "PUSH", "description": "Push", "pushTitle": "No data: {{ triggering_device['name'] }}",
      "pushBody": "No temperature datapoint since 2 hours.", "pushRecipientIds": ["<user uuid>"],
      "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false }
  ]
}
```

Daily summary at 07:00 from fixed devices (`SYSTEM_LEVEL`, one email):

```json CreateRuleNGInputType
{
  "name": "Morning report", "timezone": "Europe/Berlin", "enabled": true, "executionMode": "SYSTEM_LEVEL",
  "triggerOnSchedule": true, "scheduleTriggerCrontab": "0 7 * * 1-5",
  "createActions": [
    { "kind": "EMAIL", "description": "Report", "emailReceivers": ["team@example.com"],
      "emailSubject": "Morning report",
      "emailBody": "Cold room A: {{ devices['<device uuid A>']['measurements']['TEMPERATURE'] | round(2) }} °C\nCold room B: {{ devices['<device uuid B>']['measurements']['TEMPERATURE'] | round(2) }} °C",
      "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false }
  ]
}
```

Scheduled downlink to every device of a product (device-dependent scheduler, single-device downlink to the triggering device):

```json CreateRuleNGInputType
{
  "name": "Nightly config downlink", "timezone": "Europe/Berlin", "enabled": true, "executionMode": "DEVICE_LEVEL",
  "productFilterId": "<product uuid>", "tagsFilter": ["building-a"], "tagsFilterConjunction": "AND",
  "triggerOnSchedule": true, "scheduleTriggerCrontab": "0 2 * * *",
  "createActions": [
    { "kind": "SINGLE_DEVICE_DOWNLINK", "description": "Send interval", "singleDeviceDownlinkId": "<downlink uuid of this product>",
      "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false }
  ]
}
```

Outdoor sensor drives valves of another product (multi-device downlink) and sets an alarm flag on the sensor itself:

```json CreateRuleNGActionInputType[]
[
  { "kind": "MULTI_DEVICE_DOWNLINK", "description": "Close valves", "multiDeviceDownlinkProductId": "<valve product uuid>",
    "multiDeviceDownlinkId": "<close downlink uuid>", "multiDeviceDownlinkTagsFilter": ["zone-north"], "multiDeviceDownlinkTagsFilterConjunction": "AND",
    "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false },
  { "kind": "SET_VALUE", "description": "Frost flag on", "setValueFieldId": "<FROST_ALARM field uuid>", "setValueBool": true,
    "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false },
  { "kind": "SET_VALUE", "description": "Frost flag off", "setValueFieldId": "<FROST_ALARM field uuid>", "setValueBool": false,
    "fireWhenConditionsBecomeHot": false, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": true }
]
```

Zone entry push with a night-time restriction (push only between 22:00 and 06:00, Sunday to Saturday):

```json CreateRuleNGInputType
{
  "name": "Asset entered depot at night", "timezone": "Europe/Berlin", "enabled": true, "executionMode": "DEVICE_LEVEL",
  "productFilterId": "<tracker product uuid>",
  "triggerOnZoneEntry": true, "zoneTagsFilter": ["depot"], "zoneTagsFilterConjunction": "OR",
  "createActions": [
    { "kind": "PUSH", "description": "Night entry", "pushTitle": "{{ triggering_device['name'] }} entered {{ triggering_zone['name'] }}",
      "pushBody": "At {{ triggering_zone['entered_at'] | datetime }}", "pushRecipientIds": ["<user uuid>"],
      "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false,
      "timeRestrictions": { "kind": "ENABLED_DURING", "timeRestrictions": [
        { "start": { "dayOfWeek": 0, "time": "22:00" }, "end": { "dayOfWeek": 1, "time": "06:00" } },
        { "start": { "dayOfWeek": 1, "time": "22:00" }, "end": { "dayOfWeek": 2, "time": "06:00" } },
        { "start": { "dayOfWeek": 2, "time": "22:00" }, "end": { "dayOfWeek": 3, "time": "06:00" } },
        { "start": { "dayOfWeek": 3, "time": "22:00" }, "end": { "dayOfWeek": 4, "time": "06:00" } },
        { "start": { "dayOfWeek": 4, "time": "22:00" }, "end": { "dayOfWeek": 5, "time": "06:00" } },
        { "start": { "dayOfWeek": 5, "time": "22:00" }, "end": { "dayOfWeek": 6, "time": "06:00" } },
        { "start": { "dayOfWeek": 6, "time": "22:00" }, "end": { "dayOfWeek": 0, "time": "06:00" } } ] } }
  ]
}
```

## Pitfalls

- Field ids, not identifiers: `fieldId`, `triggeringMeasurementFields` and `setValueFieldId` take the `ProductMeasurementFieldType.id` UUID; templates use the `fieldName` identifier. Mixing them up yields an error or a rule that never matches.
- `tagsFilterConjunction` (and the zone and multi-downlink variants) is the string `"AND"` or `"OR"`; leave it `""` when no tags are set.
- `hysteresis` must be a number (`0`), not `null`; `TRIGGERING_DEVICE_FIELD_VALUE` operands must not carry a `deviceId`; condition `id`s are generated by the client (UUID v4) and must be unique within the rule.
- A measurement trigger without conditions fires on every stored value of the product, multiplied by the number of actions.
- `executionMode` defaults to `DEVICE_LEVEL`; a schedule on a product with many devices then runs once per device. Use `SYSTEM_LEVEL` for one summary and `devices["<uuid>"]` in the template.
- Cron expressions run in the rule's `timezone`; the workspace has no time zone. `datetime` renders in the same zone; raw `timestamps` are UTC.
- Time-range windows must be longer than the send interval; `MIN`/`MAX`/`COUNT` over a window shorter than one uplink see zero or one value.
- `fireWhenConditionsStayHot: true` without `minSecondsBetweenHotConditions` or `maxConsecutiveActionExecutions` sends one message per uplink while the condition holds.
- Time restrictions skip the action, they do not delay it: an alarm at 07:59 outside an 08:00 window is not sent at 08:00.
- Push needs Datacake branding or a white label brand with mobile push; the portal hides the action otherwise, so create push actions only under such a branding. Titles and bodies are limited to 255 characters.
- `SET_VALUE` writes a datapoint like any device uplink: it counts against the plan, publishes on MQTT and can trigger other rules (loops are possible).
- Rules are not moved with devices (`createDeviceMoveRequest`); recreate them in the target workspace with `rules.py export` / `create`.
- Portal copy and paste uses a clipboard JSON with `productId` instead of `productFilterId` and `updateActions` entries with ids; convert it into a `CreateRuleNGInputType` (`rules.py create` accepts both spellings).
- `tryWebhook` takes legacy rule ids; test NG webhooks with a rule that targets one test device, then read `actionExecutionLogEntries`.

## Legacy rules

`workspace.rules` (`CloudRuleType`, per-device condition/action sets with `createRule`, `updateRule`, `deleteRule`, `tryWebhook`) and `workspace.hasLegacyRules` remain readable for migration. Create nothing new there: map each legacy rule to a product-level NG rule with `devicesFilterIds` or tags, the same thresholds with `hysteresis`, and actions with `fireWhenConditionsBecomeHot`. Per-user offline emails are a separate feature (`device.notifyOffline`, `setNotifyOffline`).
