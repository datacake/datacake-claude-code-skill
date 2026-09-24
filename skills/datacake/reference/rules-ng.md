# Rule Engine NG: alerts and automations

How the new rule engine (`RuleNGType`, "Rule NG") works and how to list, read, create, update, delete and debug rules through the API. Verified against `reference/schema.graphql`, the portal's rule form and the platform documentation (https://docs.datacake.de/portal/rule-engine/new-rule-engine), and checked live on 2026-09-23 against a test workspace (create, update, delete, evaluation traces, action firing, template rendering, logs); statements marked *untested* were out of reach of that token. Legacy rules (`CloudRuleType`) are only mentioned at the end.

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

- `myPermissions` must contain `rules` for every write and for the logs. The portal hides the Rule Engine pages without it; whether `rulesNG` is readable without it is *untested* (the test token had the permission), so handle a `null` `rulesNG`.
- `features` must contain `RULE_ENGINE`; the rule engine is a plan feature or add-on (Standard, Plus, Enterprise). Without it writes fail; read `error { code details }`.
- `entitlementRulesQuotaRemaining` is the number of rules that can still be created; `-1` means unlimited. At 0 expect `ok: false` from `createRuleNG` (the code is *untested*; input problems come back as `VALIDATION_ERROR` with a `details` list).
- `entitlementRulesLogRetrievableHours` limits how far back `executionLogEntries` reach (24 on the test workspace).
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
- `python3 scripts/discover.py <workspace>` prints the field ids next to the identifiers, plus product downlinks; `python3 scripts/rules.py ids <workspace> --product <name>` prints only the rule building blocks. `apiConfiguration.apiDownlinks` already contains MQTT-kind downlinks (`kind: MQTT | HTTP`); `mqttDownlinks` repeats them under the same id. A product without downlinks needs one first (`createApiDownlink` / `createMqttDownlink`, see `mutations.md`).
- `pushRecipientCandidates(forWhitelabelSiteId:)` filters recipients for a white label brand; `reachable: false` means the member has not signed in to the app yet (still selectable).
- Devices in `devicesFilterIds` must belong to the product in `productFilterId`. Unknown or foreign ids in `devicesFilterIds`, `triggeringMeasurementFields` and `pushRecipientIds` are dropped silently (the rule is created with the remaining ids, or an empty list), so read the rule back after creating it. A random `fieldId` in a condition fails with a generic GraphQL error ("An unexpected error occurred"), not with `VALIDATION_ERROR`.

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

Conditions are optional for offline/online, gateway, schedule and zone triggers. For measurement triggers define at least one condition, or the rule fires on every uplink. Verified behaviour:

- A rule without conditions runs every action on every trigger and ignores the `fireWhen…` flags, the cooldown and the execution limit (log: `actionFiringEvent: NONE`, `conditionsResult: null`).
- A rule with conditions evaluates them on every trigger: the first true evaluation is `CONDITIONS_BECOME_HOT`, later ones are `CONDITIONS_STAY_HOT` until the conditions turn false (`CONDITIONS_BECOME_COLD`). This also holds for schedule ticks, so a scheduled check that stays true fires its become-hot actions once; reminders need `fireWhenConditionsStayHot`.
- A value recorded on a field that is not in `triggeringMeasurementFields` does not trigger the rule.

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
| `STATIC_NUMBER_VALUE` | `numberValue`, `hysteresis` (`0` for none; omitting it stores `null`, an explicit `null` is rejected) | constant threshold |
| `STATIC_RANGE_VALUE` | `rangeValue: { start, end, includeBoundaries }`, optional `hysteresis` | with `INSIDE_RANGE` / `OUTSIDE_RANGE` |
| `STATIC_BOOLEAN_VALUE` | `booleanValue` | with `EQUALS` / `NOT_EQUALS` |
| `STATIC_STRING_VALUE` | `stringValue` | with `EQUALS`, `CONTAINS`, … |
| `DYNAMIC_TRIGGERING_DEVICE_FIELD_VALUE` | `fieldId` | another field of the same device (e.g. setpoint field) |
| `DYNAMIC_DEVICE_FIELD_VALUE` | `fieldId`, `deviceId` | a field of a fixed device (e.g. outdoor sensor) |
| `DYNAMIC_CONFIGURATION_FIELD_VALUE` | `fieldId` = configuration field id | per-device threshold from a configuration field of the triggering device (default value or device override) |

Each right operand accepts only the fields of its kind: `hysteresis` is allowed on `STATIC_NUMBER_VALUE` and `STATIC_RANGE_VALUE` only; sending it (even `0`) with a `DYNAMIC_*` kind, or `rangeValue` together with `STATIC_NUMBER_VALUE`, fails with `VALIDATION_ERROR` ("… is not valid under any of the given schemas"). Operand types must match the field type: a number field against a boolean or string operand fails with "Cannot perform EQUALS operation on NUMBER and BOOLEAN types". A `TRIGGERING_DEVICE_FIELD_VALUE` operand needs `productFilterId` or `devicesFilterIds` on the rule ("Condition with index 0 cannot reference triggering device measurement field in left operand" otherwise); `STATIC_DEVICE_FIELD_VALUE` needs `deviceId`.

`geofenceValue` exists in the schema but is dead: the API rejects it with every operand kind and the portal never writes it. Location logic uses the zone triggers instead (`triggerOnZoneEntry`/`Exit`/`LengthOfStay` with `zoneTagsFilter`).

Hysteresis: with `GREATER_THAN 30` and `hysteresis: 2` the condition becomes hot above 30 and becomes cold only once the value drops below 28, which suppresses flapping around the threshold (verified with `GREATER_THAN 4`, `hysteresis: 1`: 6.5 hot, 3.5 still hot, 2.0 cold; the trace prints `> 4.0 (+/-1.0 hysteresis)` while the hysteresis is active).

Time-range operation on the left operand (`timerangeOperation: { kind, start, end }`): instead of the current value, evaluate an aggregate over a window given in plain English relative phrases (`"15 minutes ago"`, `"24 hours ago"`, `"7 days ago"`, `"now"`; English only). Kinds: `AVERAGE`, `MIN`, `MAX`, `SUM`, `COUNT` (number of datapoints; use it to detect missing uplinks), `ABSOLUTE_CHANGE` (last value minus first value in the window), `RELATIVE_CHANGE` (that difference divided by the first value, in percent). Verified: the window is `[trigger time − N, trigger time]` and includes the value that triggered the evaluation; with the values 0.49 … −2.82 in the window the trace showed `ABSOLUTE_CHANGE` −3.31 and `RELATIVE_CHANGE` −675.51, `COUNT` 4, `AVERAGE` −0.09. `start`/`end` are stored as given and only parsed when the rule runs: a German phrase or a typo is accepted by `createRuleNG` and breaks the rule later, so keep to `N minutes|hours|days ago` and `now` (an ISO timestamp as `start` is accepted; *untested* at evaluation). The window must be longer than the device's send interval, otherwise `MIN`/`MAX` see a single value.

"Stays above/below for N minutes" is expressed with `MIN`/`MAX`: `MIN` over the last 30 minutes `GREATER_THAN 10` means every value in the window was above 10; `MAX` over the last 60 minutes `LESS_THAN -10` means it never rose above -10.

`AND` binds tighter than `OR` (verified): an `OR` starts a new group and the rule is hot when any group is completely true, so `c1 AND c2 OR c3` means `(c1 AND c2) OR c3`. Evaluation short-circuits: inside a group the remaining conditions are `Skipped` after the first false one, and everything after a true group is `Aborted`. The `conjunction` of the first condition is ignored. Keep chains readable anyway; split unrelated logic into two rules.

## Actions

Common fields of every action (`CreateRuleNGActionInputType`):

| Field | Meaning |
|---|---|
| `kind` | `EMAIL`, `SMS`, `PUSH`, `WEBHOOK`, `SINGLE_DEVICE_DOWNLINK`, `MULTI_DEVICE_DOWNLINK`, `SET_VALUE` |
| `description` | label in the portal |
| `fireWhenConditionsBecomeHot` | run when the conditions turn true (the alarm) |
| `fireWhenConditionsStayHot` | run again on every evaluation while they stay true (reminders); combine with the two limits below |
| `fireWhenConditionsBecomeCold` | run when they turn false again (all-clear, revert a set value) |
| `minSecondsBetweenHotConditions` | minimum seconds between two hot-side executions of this action (become hot and stay hot), measured from its last execution; a new alarm inside the cooldown is suppressed too (0 = none) |
| `maxConsecutiveActionExecutions` | limit for reminders: the action's executions are counted consecutively (become hot, stay hot and become cold executions all count), the counter is reset when the conditions become cold, and a stay-hot execution is skipped once the counter has reached the limit. Become-hot and become-cold executions are never blocked by it: `3` = alarm + 2 reminders (0 = unlimited) |
| `timeRestrictions` | `{ kind: ENABLED_DURING | DISABLED_DURING, timeRestrictions: [{ start: { dayOfWeek, time }, end: { dayOfWeek, time } }] }`; `dayOfWeek` 0 = Sunday … 6 = Saturday, `time` `"HH:MM"` in the rule's timezone (both validated); each entry is one continuous window from start to end (Monday 08:00 to Friday 18:00 includes the nights), so business hours need one entry per day. Outside the window the action is skipped and logged as not executed |

Rules without conditions (offline, schedule, zone) run every action on every trigger; the `fireWhen…` flags, cooldown and execution limit are ignored there (verified with a schedule: an action with all three flags `false` still ran). Keep `fireWhenConditionsBecomeHot: true` anyway so the action keeps working if conditions are added later. Put the all-clear into its own action (`fireWhenConditionsBecomeCold` only): when one action fires on hot and cold, the cold execution and the next alarm both count towards `maxConsecutiveActionExecutions` and eat the reminders.

Type-specific fields:

| `kind` | Fields | Notes |
|---|---|---|
| `EMAIL` | `emailReceivers: [String]`, `emailSubject` (required), `emailBody` | body may contain HTML and template expressions; addresses are validated, an empty receiver list is accepted; branding from `whitelabelSiteId` |
| `SMS` | `smsReceivers: [String]` (E.164, validated), `smsBody` | needs organization SMS credits |
| `PUSH` | `pushTitle`, `pushBody` (≤ 255 characters each), `pushRecipientIds: [user uuid]` from `pushRecipientCandidates` | Datacake mobile app only; needs Datacake branding or a white label brand with mobile push. Unknown recipient ids and members who leave the workspace are dropped silently; the log counts `push_sent_count` and `push_skipped_no_token_count` |
| `WEBHOOK` | `webhookUrl` (static, validated as a URL, query string allowed), `webhookHeaders: [{ key, value }]` (static, sent verbatim), `webhookPayload` (template; usually JSON) | always one HTTP `POST` per execution with `User-Agent: DatacakeBot/1.0`; no `Content-Type` is added, so set `Content-Type: application/json` yourself. Only the payload is rendered: URL and headers are not templates (a `{{ }}` in the URL fails validation, in a header it is sent literally). A payload that parses as JSON is re-serialized (pretty-printed) before sending, anything else is sent as-is. Request, response status/headers/body and `webhook_body_parsable_as_json` are logged; a 4xx/5xx response still counts as fired. Hosts that do not resolve (or are not allowed) fail with `webhook_error_code: HOST_NOT_ALLOWED`. Recipe: "Webhook to a third-party platform" below |
| `SINGLE_DEVICE_DOWNLINK` | `singleDeviceDownlinkId` (a downlink of the rule's product), optional `singleDeviceDownlinkDeviceId` | omit the device id to target the triggering device (schedule on `DEVICE_LEVEL` = every device gets its downlink). Verified: the log records `single_downlink_id`, `single_downlink_device_id` and "Downlink … scheduled for device …"; an unknown downlink id fails with "Single device downlink action requires a downlink to be set" |
| `MULTI_DEVICE_DOWNLINK` | `multiDeviceDownlinkProductId`, `multiDeviceDownlinkId`, `multiDeviceDownlinkTagsFilter`, `multiDeviceDownlinkTagsFilterConjunction` (`AND`/`OR`) | downlink to every device of another product (optionally filtered by tags), e.g. when an outdoor sensor triggers. Verified: the product is required ("Multi device downlink action requires a product to be set"), tags without a conjunction are accepted, the log lists the targeted devices in `multi_downlink_devices` as `[id, serial, name]` |
| `SET_VALUE` | `setValueFieldId`, optional `setValueDeviceId`, exactly one of `setValueNumeric`, `setValueBool`, `setValueString`, `setValueGeo` (`"(lat,lng)"`) | writes a datapoint (publishes MQTT, can trigger other rules); omit the device id for the triggering device. The value must match the field type (`setValueBool` on a number field fails with "Value to be set must be set"), strings are written verbatim (no template rendering), a set value on a field that triggers the same rule is refused ("Possible loop"). `setValueFloat`/`setValueInt` are deprecated |

Single vs multi device downlink (the most common misunderstanding): the two kinds answer different questions and multiply with the execution mode.

| You want | Rule | Action | Downlinks per trigger |
|---|---|---|---|
| Every device of the product gets its own downlink (e.g. open all valves at 09:00) | `DEVICE_LEVEL`, schedule, product (optionally tags/devices) | `SINGLE_DEVICE_DOWNLINK` **without** `singleDeviceDownlinkDeviceId` (= the triggering device) | one per device in scope |
| One trigger sends the downlink to a whole product (e.g. the outdoor sensor closes all valves of another product) | `DEVICE_LEVEL` on the sensor product, or `SYSTEM_LEVEL` schedule | `MULTI_DEVICE_DOWNLINK` with `multiDeviceDownlinkProductId` (+ tags) | one per target device, per trigger |
| Wrong: "I have many devices, so multi" | `DEVICE_LEVEL` on product X | `MULTI_DEVICE_DOWNLINK` to product X | devices × devices: the rule runs once per device and each run sends to every device |

`MULTI_DEVICE_DOWNLINK` ignores the triggering device entirely; it targets the product named in the action. Combine it with `DEVICE_LEVEL` only when the rule's product is a different one (sensor triggers, actuators receive) or when the rule's scope is one device. `rules.py create` warns about a multi downlink in a `DEVICE_LEVEL` rule. Verified: a `DEVICE_LEVEL` rule with one device in scope and a multi downlink to seven tagged devices scheduled seven downlinks per trigger.

## Create a rule

`createRuleNG(workspaceId: UUID!, input: CreateRuleNGInputType!)`. `name` is the only required field; everything else defaults to off/empty (verified defaults: `executionMode` `DEVICE_LEVEL`, `timezone` `UTC`). Input problems return `ok: false` with `error { code: VALIDATION_ERROR, details: [...] }`, a list of messages such as "Invalid crontab", "Invalid timezone", "A tags filter conjunction must be set when using the tags filter", "Condition IDs must be unique", "Email subject must be set for email actions"; scalar violations (a condition `id` that is not a UUID, a bad `setValueGeo`) fail earlier as GraphQL `errors` with HTTP 400. The example creates a product-level CO₂ alarm with an all-clear email and a webhook (the input is written inline so it validates against the schema; in code pass it as the `$input` variable):

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

Checklist before sending: `productFilterId` set for device-level triggers · field ids belong to that product · every condition has a fresh UUID `id`, `hysteresis` only on static number/range operands · each action has all three `fireWhen…` flags · templates use only `{{ }}` with the filters `round`, `datetime`, `json` · `executionMode` explicit · `timezone` set when a schedule is used · `ok` checked and `error { code details }` surfaced (`details` usually names the offending field).

## Update a rule

`updateRuleNG(id: UUID!, input: UpdateRuleNGInputType!)`. Send only the fields to change; omitted fields keep their value (do not send `""` to "leave unchanged"). Semantics that differ from create:

| Field | Update semantics |
|---|---|
| `devicesFilterIds` | object `{ set: [...] }` (replace), `{ add: [...] }`, `{ remove: [...] }` (all verified); `{ set: [] }` without a product fails while a condition still references the triggering device |
| `triggeringMeasurementFields` | same `{ set | add | remove }` object |
| `conditions` | replaces the whole list; send every condition you want to keep (with its existing `id`) |
| `createActions` | adds actions (no `id`) |
| `updateActions` | each entry needs the existing action `id`; only the given fields change (verified); an unknown id is a GraphQL error |
| `deleteActions` | list of action ids to remove (unknown ids are ignored) |
| `productFilterId`, `whitelabelSiteId` | `BlankableUUID`: `""` clears (verified; the devices in `devicesFilterIds` stay) |

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

Subjects, bodies, push texts and webhook payloads are rendered by a small expression substitution, not by Django or Jinja: only `{{ expression }}` is evaluated (webhook URLs and headers are never rendered). Keys are accessed with brackets (single or double quotes) or dots: `{{ triggering_device['name'] }}`, `{{ triggering_device["name"] }}` and `{{ triggering_device.name }}` are equivalent. Measurement keys are the field identifiers (`fieldName`), not the display names. Simple arithmetic works (`{{ triggering_device['measurements']['TEMPERATURE'] * 2 }}`).

Verified limits:

- `{% if %}`, `{% for %}` and other tags are not interpreted; they stay in the text verbatim (expressions inside them still render).
- Only the filters `round`, `datetime` and `json` exist. Any other filter (`default`, `floatformat`, `upper`, `int`, `default:"x"` …), a filter applied to the wrong type (`round` on a string) or a parse error in an expression (for example `datetime(\"%H:%M\")` with escaped quotes inside a JSON payload; write `datetime('%H:%M')`) aborts the rendering of that text: the whole subject, body or payload is sent unrendered, `{{ … }}` included. The platform docs still list `date:"c"`, `timesince`, `if`/`for` tags and a `values` alias; none of them rendered in the live test. Subject and body are rendered separately, so a broken body still gets a rendered subject. `datetime` on a number renders empty instead of aborting.
- Undefined variables and missing keys render as an empty string, never as an error.
- `measurements` and `timestamps` are lazy containers: `{{ triggering_device['measurements']['CO2'] }}` works, but `{{ triggering_device['measurements'] }}`, `| json` on the container or iterating it yields `{}`.
- `triggering_device['values']` does not exist (renders empty); use `measurements`.

Variables (as offered by the portal's autocomplete; values render in Python style: `True`/`False`, `['a', 'b']`, datetimes as `2026-09-23 12:14:59.052383+00:00`):

| Variable | Keys | Available when |
|---|---|---|
| `rule` | `id`, `name` | always |
| `triggering_device` | `id`, `name`, `serial_number`, `location` (the device's location *name*, not coordinates), `tags` (list), `online`, `last_heard` (datetime), `dashboard_url` (was empty in the test workspace), `measurements[<FIELD>]` (latest value; geo fields as `"(lat,lng)"`), `timestamps[<FIELD>]` (datetime of that value) | `DEVICE_LEVEL` (renders empty elsewhere) |
| `devices["<device uuid>"]` | same keys as `triggering_device` | any mode; any device of the workspace (the basis for `SYSTEM_LEVEL` reports; verified in `DEVICE_LEVEL` and `SYSTEM_LEVEL`) |
| `triggering_gateway` | `id`, `name`, `eui`, `online`, `last_seen`, `last_check`, `connected_at`, `round_trip_median_time`, `uplink_count`, `downlink_count`, `latitude`, `longitude`, `altitude` | `GATEWAY_LEVEL` (renders `{}` elsewhere) |
| `gateways["<gateway uuid>"]` | same keys as `triggering_gateway` | any mode |
| `triggering_zone` | `id`, `name`, `entered_at`, `exited_at`, `length_of_stay`, `still_in_zone_at` | zone triggers (empty elsewhere) |

Filters (chaining works: `| round(2) | json`):

| Filter | Effect |
|---|---|
| `\| datetime` | timestamp in the rule's `timezone`, default format `2026-09-23 14:08:27` |
| `\| datetime("%d.%m.%Y %H:%M")` | strftime format |
| `\| round` / `\| round(2)` | numeric value rounded (`6.0`, `6.73`); on a string it aborts the rendering |
| `\| json` | JSON literal: `true`/`false`, strings quoted and escaped (`"Cold room 4"`), lists `["a", "b"]`, datetimes as ISO strings (`"2026-09-23T14:01:47.217906+00:00"`); use it for every string, boolean, list and timestamp inside a webhook payload |

Examples:

```
Subject: {{ rule['name'] }}: {{ triggering_device['name'] }}
Body:
{{ triggering_device['name'] }} ({{ triggering_device['serial_number'] }}) reported
{{ triggering_device['measurements']['TEMPERATURE'] | round(2) }} °C
at {{ triggering_device['timestamps']['TEMPERATURE'] | datetime("%d.%m.%Y %H:%M") }}.
Dashboard: {{ triggering_device['dashboard_url'] }}
```

Conditional wording (`{% if %}`) is not available: express the cases through the rule instead, e.g. the all-clear as a separate `fireWhenConditionsBecomeCold` action with its own text, or two rules with different thresholds.

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

Discovering keys: put `{{ triggering_device }}` into an email body once and read the rendered object in the log (`actionExecutionVariables` → `email_body`); it shows every key except the lazy `measurements`/`timestamps`. In `SYSTEM_LEVEL` there is no `triggering_device` (renders empty); address devices explicitly with `devices["<uuid>"]`.

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

- Filter: `triggerTimestamp { gt gte lt lte }`, `anyActionFired { exact }`, `triggeringDeviceId { exact }`, `triggeringGatewayId { exact }`, combinable with `and`, `or`, `not` (verified, e.g. `{ not: { anyActionFired: { exact: true } } }`). Entries come newest first; page with `after: endCursor`.
- `initiator` is the trigger (`NEW_MEASUREMENTS`, `SCHEDULE`, `DEVICE_GOES_OFFLINE`, …); `actionFiringEvent` is `CONDITIONS_BECOME_HOT`, `CONDITIONS_STAY_HOT`, `CONDITIONS_BECOME_COLD` or `NONE`.
- `conditionsPrettyEvaluationTrace` is a text table with each operand's value and result (`Skipped`/`Aborted` for short-circuited conditions, `(+/-1.0 hysteresis)` while a hysteresis is active). `prettyTrace` per action is filled only when the action ran: rendered subject/body and per-receiver send status for email, title/body and sent/skipped counts for push, `**Error:** HOST_NOT_ALLOWED …` for a refused webhook, `Set \`WARNING=True\` … on …` for a set value. A skipped action has an empty `prettyTrace`; read `isFiredByEvent`, `isWithinActiveTimePeriod` and its entry in `actionExecutionVariables` (`number_of_consecutive_action_executions`) to see why.
- `conditionsEvaluationVariables` (one JSON string per condition: `result`, `last_result`, `runtime_variables` with `left_operand_value`, `right_operand_value`, `active_hysteresis`) and `actionExecutionVariables` (one per action, same order as `actionExecutionLogEntries`: flags and limits, `is_fired`, `runtime_variables` with `email_subject`, `email_body`, `email_receivers` as `[address, status]` pairs, `push_sent_count`, `push_skipped_no_token_count`, `webhook_body` (rendered payload), `webhook_request` (full request incl. headers), `webhook_response` (status line, headers, body), `webhook_body_parsable_as_json`, `webhook_error_code`/`webhook_error_details` (connection-level failures only), `single_downlink_message`, `multi_downlink_devices`, `number_of_consecutive_action_executions`) are `JSONString`s: parse them. `runtimeVariables` and `extraTemplateVariables` were empty objects in every test entry.
- `python3 scripts/rules.py logs <rule-id> [--since 24h] [--fired] [--device <uuid>] [--trace]` prints a table; `--trace` adds the condition table and the per-action variables.

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

Threshold with hysteresis, alarm plus up to two reminders (three executions), one reminder per hour at most, all-clear mail from a separate action:

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
    "rightOperand": { "kind": "DYNAMIC_CONFIGURATION_FIELD_VALUE", "fieldId": "<TARGET_TEMPERATURE configuration field uuid>" } }
]
```

Missing data: no datapoint in the last 2 hours (`COUNT` over the window equals 0, evaluated by a device-level schedule every 30 minutes; complements the offline trigger when the online timeout is long). The condition stays hot while data is missing, so the push goes out once on the first empty window; add `fireWhenConditionsStayHot: true` with `minSecondsBetweenHotConditions` for reminders:

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

Daily summary at 07:00 from fixed devices (`SYSTEM_LEVEL`, one email; without conditions the action runs on every tick, flags and limits are ignored):

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

Scheduled downlink to every device of a product (device-dependent scheduler, single-device downlink to the triggering device; a `MULTI_DEVICE_DOWNLINK` here would send devices × devices downlinks, see "Single vs multi device downlink" above):

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

Outdoor sensor drives valves of another product (multi-device downlink: the rule runs per sensor, the downlink goes to the valve product; correct because sensor and valves are different products) and sets an alarm flag on the sensor itself:

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

Webhook to a third-party platform (Slack, Microsoft Teams, ticket systems, any REST API): the `WEBHOOK` action is a plain HTTP `POST` with a static URL, static headers and a templated body, so it reaches every service that accepts JSON over HTTPS. Slack incoming webhook (one channel post per alarm and an all-clear):

```json CreateRuleNGActionInputType[]
[
  { "kind": "WEBHOOK", "description": "Slack alarm",
    "webhookUrl": "https://hooks.slack.com/services/T000/B000/XXXX",
    "webhookHeaders": [{ "key": "Content-Type", "value": "application/json" }],
    "webhookPayload": "{\"text\": \":rotating_light: *{{ rule['name'] }}*\\n{{ triggering_device['name'] }} ({{ triggering_device['serial_number'] }}) reported {{ triggering_device['measurements']['TEMPERATURE'] | round(1) }} °C at {{ triggering_device['timestamps']['TEMPERATURE'] | datetime('%d.%m.%Y %H:%M') }}\"}",
    "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false,
    "minSecondsBetweenHotConditions": 900, "maxConsecutiveActionExecutions": 0 },
  { "kind": "WEBHOOK", "description": "Slack all clear",
    "webhookUrl": "https://hooks.slack.com/services/T000/B000/XXXX",
    "webhookHeaders": [{ "key": "Content-Type", "value": "application/json" }],
    "webhookPayload": "{\"text\": \":white_check_mark: {{ triggering_device['name'] }} back to normal ({{ triggering_device['measurements']['TEMPERATURE'] | round(1) }} °C)\"}",
    "fireWhenConditionsBecomeHot": false, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": true }
]
```

Generic REST API with authentication and a structured body (a ticket system, an automation platform such as Zapier/Make/n8n, or your own backend):

```json CreateRuleNGActionInputType[]
[
  { "kind": "WEBHOOK", "description": "Create ticket",
    "webhookUrl": "https://api.example.com/v1/incidents?source=datacake",
    "webhookHeaders": [
      { "key": "Content-Type", "value": "application/json" },
      { "key": "Authorization", "value": "Bearer <api token>" },
      { "key": "X-Source", "value": "datacake-rule-engine" }
    ],
    "webhookPayload": "{\"title\": \"{{ rule['name'] }}: {{ triggering_device['name'] }}\", \"device_id\": \"{{ triggering_device['id'] }}\", \"serial\": {{ triggering_device['serial_number'] | json }}, \"temperature\": {{ triggering_device['measurements']['TEMPERATURE'] }}, \"door_open\": {{ triggering_device['measurements']['DOOR_OPENED'] | json }}, \"tags\": {{ triggering_device['tags'] | json }}, \"measured_at\": {{ triggering_device['timestamps']['TEMPERATURE'] | json }}, \"dashboard\": \"{{ triggering_device['dashboard_url'] }}\"}",
    "fireWhenConditionsBecomeHot": true, "fireWhenConditionsStayHot": false, "fireWhenConditionsBecomeCold": false }
]
```

Rules for webhook payloads (all verified live):

- The request is always `POST`; there is no method, no basic-auth field and no retry setting. Put API keys into headers (`Authorization`, `X-Api-Key`); they are stored in plain text and visible to every member with the `rules` permission, so use a dedicated key with minimal rights.
- Set `Content-Type: application/json` explicitly; Datacake adds only `User-Agent`, `Accept`, `Content-Length`. Microsoft Teams, Slack and most REST APIs reject bodies without it.
- Quote string expressions yourself (`"{{ triggering_device['name'] }}"`) or use `| json` (also escapes quotes and newlines in the value); numbers go raw, booleans, lists and timestamps through `| json`. Inside the payload use single quotes for filter arguments (`datetime('%H:%M')`), because `\"` breaks the expression parser and the whole payload goes out unrendered.
- Dynamic values belong in the body: the URL and the headers are static. Services that want an id in the path need one action per target or a body field the receiver evaluates.
- A syntactically valid JSON payload is re-serialized (pretty-printed) before sending; the log's `webhook_body_parsable_as_json` and the `✓ JSON valid` / `✗ JSON invalid` line in `prettyTrace` tell you which case you hit. A `4xx`/`5xx` answer is logged in `webhook_response` but does not fail the action, so check the logs after the first execution.
- Loop control is the same as for emails: cooldown and `maxConsecutiveActionExecutions` for reminders, a separate action with `fireWhenConditionsBecomeCold` for the all-clear. In `SYSTEM_LEVEL` address devices as `devices['<uuid>']`.
- Legacy `tryWebhook` cannot test NG actions; trigger the rule once with a test device (or record a value via the REST endpoint) and read `rules.py logs <rule-id> --trace`.

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
- `hysteresis` belongs to `STATIC_NUMBER_VALUE`/`STATIC_RANGE_VALUE` only (send `0`, never `null`; drop it from dynamic, boolean and string operands); `TRIGGERING_DEVICE_FIELD_VALUE` operands must not carry a `deviceId`; condition `id`s are generated by the client (UUID v4) and must be unique within the rule.
- A measurement trigger without conditions runs every action on every stored value of the triggering fields; fire flags, cooldown and limits are ignored without conditions.
- Unknown ids in `devicesFilterIds`, `triggeringMeasurementFields`, `pushRecipientIds` and `deleteActions` are dropped without an error; read the rule back after writing it.
- Only `{{ }}` expressions with the filters `round`, `datetime` and `json` render; an unknown filter leaves the whole text unrendered and `{% %}` tags are printed verbatim.
- One action that fires on hot and cold shares one execution counter; use separate actions for alarm/reminders and for the all-clear.
- `MULTI_DEVICE_DOWNLINK` in a `DEVICE_LEVEL` rule on the same product sends devices × devices downlinks; "every device gets its downlink" is `SINGLE_DEVICE_DOWNLINK` without a device id, "one batch to a product" is `MULTI_DEVICE_DOWNLINK` on `SYSTEM_LEVEL` or from another product's rule.
- `executionMode` defaults to `DEVICE_LEVEL`; a schedule on a product with many devices then runs once per device. Use `SYSTEM_LEVEL` for one summary and `devices["<uuid>"]` in the template.
- Cron expressions run in the rule's `timezone`; the workspace has no time zone. `datetime` renders in the same zone; raw `timestamps` are UTC.
- Time-range windows must be longer than the send interval; `MIN`/`MAX`/`COUNT` over a window shorter than one uplink see zero or one value.
- `fireWhenConditionsStayHot: true` without `minSecondsBetweenHotConditions` or `maxConsecutiveActionExecutions` sends one message per uplink while the condition holds.
- Time restrictions skip the action, they do not delay it: an alarm at 07:59 outside an 08:00 window is not sent at 08:00.
- Push needs Datacake branding or a white label brand with mobile push; the portal hides the action otherwise, so create push actions only under such a branding. Titles and bodies are limited to 255 characters.
- `SET_VALUE` writes a datapoint like any device uplink: it counts against the plan, publishes on MQTT and can trigger other rules. Writing to a field that triggers the same rule is refused (`VALIDATION_ERROR` "Possible loop"); loops across rules are still possible. Set-value strings are not templates.
- Rules are not moved with devices (`createDeviceMoveRequest`); recreate them in the target workspace with `rules.py export` / `create`.
- Portal copy and paste puts the rule form's values on the clipboard: `productFilterId`, conditions with their ids, existing actions under `updateActions` with ids, plus `createActions`/`deleteActions`. `rules.py create` converts that into a `CreateRuleNGInputType` (ids stripped; `productId` accepted as an alias).
- Webhook URL and headers are static (no templates), the request is always `POST` and no `Content-Type` is added by default; dynamic values go into the payload, filter arguments inside a JSON payload use single quotes. `tryWebhook` takes legacy rule ids; test NG webhooks by triggering the rule once and reading `actionExecutionVariables` (`webhook_request`, `webhook_response`, `webhook_error_code` such as `HOST_NOT_ALLOWED`).

## Legacy rules

`workspace.rules` (`CloudRuleType`, per-device condition/action sets with `createRule`, `updateRule`, `deleteRule`, `tryWebhook`) and `workspace.hasLegacyRules` remain readable for migration. Create nothing new there: map each legacy rule to a product-level NG rule with `devicesFilterIds` or tags, the same thresholds with `hysteresis`, and actions with `fireWhenConditionsBecomeHot`. Per-user offline emails are a separate feature (`device.notifyOffline`, `setNotifyOffline`).
