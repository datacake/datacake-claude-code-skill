# Dashboards: workspace and device dashboards, widgets, layouts

How Datacake stores dashboards, how to read, create and edit them through the API, and what every widget's
configuration looks like. Verified against `reference/schema.graphql`, the portal's dashboard editor
(`DashboardEditorNG`) and checked live on 2026-10-02 in a sandbox workspace (every widget below was written with
`scripts/dashboards.py`, read back and previewed server-side; the portal rendering was checked after a reload).
Statements marked *untested* were out of reach. Companion script: `scripts/dashboards.py`.

## Contents

- Model: two kinds of dashboards
- No live update, whole-layout writes
- Reading dashboards
- Layout JSON: tabs, widgets, grid, mobile, translations
- Field references, timeframes, ranges
- Design guide: gauges, ranges, charts, layout
- Widget catalogue
- Writing: create, save, tabs, delete, home, restore
- Recipes
- Pitfalls

## Model: two kinds of dashboards

```
Workspace
├─ dashboards: [DashboardType]            # workspace dashboards (portal: "Dashboards")
│    id, name, type CUSTOM|CLIMATE|IAQ, icon, sharingPolicy public|workspace|restricted (+ sharedWith),
│    dashboards: JSONString (the layout, CUSTOM only), metaJSON (CLIMATE/IAQ settings),
│    publicLinks, dashboardChangelog, dashboardBg*/dashboardText* colours
├─ homeDashboard, dashboard(id); updateWorkspace(homeDashboardId)
└─ Product
     └─ dashboards: JSONString            # the device dashboard, shared by EVERY device of the product
        dashboardChangelog; legacy: dashboardJsx, dashboardConfig, legacyDashboardDisabled
   Device: dashboardData(...) only (the server computes widget values); no per-device layout override
```

| | Workspace dashboard | Device dashboard |
|---|---|---|
| Stored on | `DashboardType.dashboards` (one object per dashboard) | `ProductType.dashboards`; every device of the product shows the same layout, filled with its own values |
| Devices in widgets | explicit `device` ids, tag filters (Table, MapNG), semantics | the viewed device is implicit: any `device` value in a field reference is replaced by the device being viewed (verified: `""` and a foreign device id both resolve to the viewed device) |
| Read | `dashboard(id) { dashboards }` or `workspace.dashboard(id)` | `device(deviceId) { product { id dashboards } }` or `product(id) { dashboards }` |
| Write | `updateDashboard(input: { workspace, dashboard, dashboards, changeMessage })` | `updateProduct(input: { product, dashboards, changeMessage })` |
| Create / delete | `addDashboard`, `deleteDashboard` | created with the product (one empty tab); "delete" = save a layout without widgets |
| Permission | workspace `dashboards` | device `edit_product` (workspace `devices`); product feature `locked_dashboard` locks the portal editor |
| Tabs | array entries, every tab shows its `name` | array entries; tab 0 is always labelled "Dashboard" in the portal, tabs ≥ 1 show `name` and honour `hideOnWhitelabel` |
| Widgets not available | `Map` (legacy), `DeviceFields`, `OnlineStatus` | `Table`, `MapNG` |
| Sharing | `sharingPolicy`, `sharedWith`, public links (`createDashboardPublicLink`, viewers use `dashboardPublicLink(publicLink: { id, token })`) | public device links (`createDevicePublicLink`), see `mutations.md` |
| History | `dashboardChangelog` | `dashboardChangelog(filter: { historyChangeReason: { isnull: false } })` |

`type` other than `CUSTOM` (`CLIMATE`, `IAQ`): the dashboard is a fixed use-case page configured through
`metaJSON` (`{"settings": {temperatureMin, temperatureMax, humidityMin, humidityMax, …, selectedDevices}}`), it has
no widgets; create it with `addDashboard(type: "CLIMATE"|"IAQ")` and `updateDashboard(metaJSON)`. Everything
below is about `CUSTOM` dashboards and device dashboards.

## No live update, whole-layout writes

- The portal never reloads a dashboard definition on its own (MQTT only refreshes values). After every write,
  tell the user to **reload the dashboard page** in the portal.
- A write replaces the **entire** `dashboards` array (all tabs, all widgets). There is no per-widget mutation and
  no version check on the server: the last writer wins. Always read the current layout immediately before
  changing it, modify it, and write the whole array back. Never save from a stale copy, and ask before writing
  when the user may have the portal editor open in edit mode (leaving edit mode saves the editor's copy over
  yours).
- Set `changeMessage` (≤ 100 characters) on every write; it appears in the changelog on plans with
  `entitlementDashboardHistoryEnabled`.
- `scripts/dashboards.py` does all of this: every write command re-reads the dashboard, shows a diff, validates,
  refuses when the server copy changed since it was read (`--force` overrides), writes with a change message,
  reads back and prints the reload reminder. Prefer it over hand-written mutations.

## Reading dashboards

Workspace dashboards of a workspace (the layout is a JSON string, parse it):

```graphql
query WorkspaceDashboards($workspaceId: String!) {
  workspace(id: $workspaceId) {
    myPermissions entitlementDashboardHistoryEnabled
    homeDashboard { id }
    dashboards { id name type icon sharingPolicy dashboards }
  }
}
```

One workspace dashboard with its sharing and public links (`dashboard(id)` needs no workspace id):

```graphql
query Dashboard($id: String!) {
  dashboard(id: $id) {
    id name type icon sharingPolicy sharedWith { id email } dashboards metaJSON
    workspace { id slug }
    publicLinks { id name mode }
  }
}
```

Device dashboard of a product, with the fields every widget may reference:

```graphql
query DeviceDashboard($deviceId: String!) {
  device(deviceId: $deviceId) {
    id verboseName
    product {
      id name hardware features deviceCount dashboards
      measurementFields(active: true) { fieldName verboseFieldName fieldType unit role semantic }
    }
  }
}
```

Changelog (Relay connection; product entries without a change reason are automatic saves, filter them out):

```graphql
query DashboardHistory($workspace: String!, $dashboard: String!, $product: String!) {
  workspace(id: $workspace) {
    dashboard(id: $dashboard) {
      dashboardChangelog(first: 10) { edges { node { historyId historyDate historyUserName historyChangeReason dashboards } } }
    }
  }
  product(id: $product) {
    dashboardChangelog(first: 10, filter: { historyChangeReason: { isnull: false } }) {
      edges { node { historyId historyDate historyUserName historyChangeReason dashboards } }
    }
  }
}
```

Server-side preview (what the portal editor does while editing): `dashboardData` evaluates a layout you pass in
and returns the widget values without saving. It is the only way to check a widget against the server before
writing. `dashboardConfig` is ONE tab object (`{"widgets": {...}}`), `widgetIds` selects widgets, the result is a
JSON string `[valuesByKey, usedDevices, …]` (keys such as `val<hash>`, `table<uuid>`; `NaN` can appear, replace it).

```graphql
query Preview($deviceId: String!, $dashboardId: String!, $config: JSONString, $ids: [String!]) {
  device(deviceId: $deviceId) { dashboardData(dashboard: 0, dashboardConfig: $config, widgetIds: $ids) }
  dashboard(id: $dashboardId) { dashboardData(dashboard: 0, dashboardConfig: $config, widgetIds: $ids) deviceInformation(dashboardConfig: $config) }
}
```

Widgets without a server data request (Headline, Image, Iframe, Button, Downlink, OnlineStatus, MapNG, Histogram)
return nothing here; an unknown widget type returns nothing either (no error), so validate types locally.
`dashboards.py check <target>` runs this per widget. `dashboardData` is not a way to read the layout.

## Layout JSON: tabs, widgets, grid, mobile, translations

`dashboards` is a JSON array; each entry is a tab. The same format is used for workspace and device dashboards:

```json dashboard-device
[
  {
    "id": "4394304a-c4e5-4438-9a1a-17d69d0c2c67",
    "name": "Dashboard",
    "widgets": {
      "4b8de285-5f3e-4c4e-9f14-0d0a2a0a1b11": {
        "widget": "Headline",
        "layouts": { "lg": { "i": "4b8de285-5f3e-4c4e-9f14-0d0a2a0a1b11", "x": 0, "y": 0, "w": 12, "h": 1 } },
        "meta": { "title": { "en": "Fridge" }, "hideBackground": true, "size": 2, "layout": "vertical" }
      },
      "4a8d02ea-1c7f-4a0c-8d2e-3b7b9f0e5c22": {
        "widget": "Value",
        "layouts": { "lg": { "i": "4a8d02ea-1c7f-4a0c-8d2e-3b7b9f0e5c22", "x": 0, "y": 1, "w": 4, "h": 3 } },
        "meta": {
          "title": { "en": "Temperature" },
          "field": { "device": "", "fieldName": "TEMPERATURE", "fieldType": "NUMERIC", "verboseFieldName": "Temperature" },
          "unit": { "en": "°C" }, "decimalPlaces": 1, "gaugeType": "linear",
          "gaugeRanges": [ { "value": 0, "color": "#10B981", "name": "OK" }, { "value": 6, "color": "#F59E0B", "name": "Warm" }, { "value": 8, "color": "#EF4444", "name": "Too warm" } ],
          "isTextColorStateBased": true
        }
      }
    }
  }
]
```

- **Tab**: `name` (string), `widgets` (object keyed by widget id). Device dashboard tabs carry an `id` (uuid4)
  and optionally `hideOnWhitelabel` (tabs ≥ 1 only); workspace tabs have neither. Keep at least one tab. The
  server also accepts `"widgets": []` for an empty tab, but write `{}`.
- **Widget**: `widget` (type name, see catalogue), `layouts`, `meta`. The key is a uuid4 and must equal
  `layouts.<bp>.i`.
- **Grid**: `lg` (desktop, ≥ 768 px) has 12 columns, `sm` (phones) 4 columns; one row is 48 px, gaps 10 px.
  `x`, `y`, `w`, `h` are integers, `x + w ≤ 12` (`≤ 4` for `sm`), `w, h ≥ 1`. The portal compacts vertically:
  gaps above a widget disappear and overlapping widgets are pushed down in an order you do not control, so place
  widgets without overlaps (new widgets go below the current bottom: `y = max(y + h)`). The grid may add
  `minW/maxW/isDraggable/isResizable/static/moved` to a layout; keep such keys.
- **Mobile**: there is no `sm` entry on a desktop widget. The portal's "Create from desktop" clones every `lg`
  widget as a **separate widget** (new uuid) with only an `sm` layout. Desktop renders widgets with `lg`; if any
  widget has `sm`, phones render only the `sm` widgets, otherwise they reuse `lg`. Consequences: write `lg`
  only, never touch or delete `sm`-only widgets, and warn the user that new widgets are missing on phones when a
  dashboard already has a mobile layout (mobile layouts are built in the portal).
- **Translations**: text values are objects `{"en": "…", "de": "…"}` (33 language codes, `en` is the key the
  portal looks for, fallback en → de). The dashboard's language set is derived from these objects; the editor
  adds `""` for the other languages on new widgets. Plain strings render but the editor expects objects.
- **Common appearance keys** (most widgets): `hideBackground`, `hideLastUpdate`, `tintColor`, `highlightColor`
  (hex), `icon` (Font Awesome name such as `thermometer-half`, `tint`, `bolt`, `wifi`), `isFullScreenHeight`.
- Keys to preserve but never set: `timerangeOperation.operator` (dead), `hasMobileVersion`, Slider `devices`,
  Table `uuid` (data key, set once).

## Field references, timeframes, ranges

**Field reference** (Value, Boolean, Switch, Slider, SetValue, MeasurementList): the editor writes all four keys.

```json
{ "device": "2fcc6915-a3f9-49a0-9416-249ce6c9b9c5", "fieldName": "TEMPERATURE", "fieldType": "NUMERIC", "verboseFieldName": "Temperature" }
```

- `fieldName` is the product field identifier (`measurementFields.fieldName`). A field that does not exist on
  the device's product renders an empty widget without any error.
- Workspace dashboards need a real `device` id. Device dashboards: use `""` (the viewed device is injected;
  the portal editor stores the id of the device it was opened on, which is equivalent).
- Field types per widget (the editor's picker filter): Boolean/Switch `BOOL`; Value `FLOAT|INT|NUMERIC|COUNTER|STRING`;
  Slider `FLOAT|INT|NUMERIC`; SetValue any except `GEO`; LineChart numeric or `BOOL`; Histogram/Heatmap numeric;
  MeasurementList any. New product fields are `NUMERIC` (the API rejects `FLOAT`/`INT` for new fields).

**Series** (LineChart): one entry per series, `fields` holds exactly one field (the editor edits `fields[0]`):

```json
{ "device": "<device id or \"\">", "label": "Fridge 1",
  "fields": [ { "field": "TEMPERATURE", "color": "#ef4444", "verboseName": "Temperature", "chartKind": "line", "strokeWidth": 1 } ],
  "yAxis": { "id": 1, "orientation": "left", "hidden": false, "scale": "auto", "unit": "°C" },
  "interpolationType": "linear" }
```

`chartKind` `line|area|bar` (missing = area); `yAxis.id` groups series on one axis (`id: 2, orientation: "right"`
for a second unit); `yAxis.domain: ["auto", 100]`; `interpolationType` linear, monotone, step, basis, natural, …;
`isDeltaEnabled` with `colorPositive`/`colorNegative` for consumption deltas of counters (then the chart's
`historyFunction` must be `"max"`, see the design guide). Histogram and Heatmap use a flat list instead:
`[{ "device", "fieldName", "color" | "verboseName", "unit", "rangeSettings" }]`.

**Timeframe** (LineChart, Map, ScatterPlot, …): `{"start": "24 hours ago", "end": "now", "resolution": "15m",
"otherTimeframe": false, "timezone": "Europe/Berlin"}`. Presets of the editor: hourly `1 hour ago`/`5m`, daily
`24 hours ago`/`15m`, weekly `7 days ago`/`6h`, two weeks `14 days ago`/`24h`, monthly `31 days ago`/`24h`;
`otherTimeframe: true` marks a custom range. `resolution` must match `<n>m|h|d|w`; `raw` is served as 30 minute
buckets (verified). `start`/`end` are free English expressions parsed by `query { parseDate(date: "7 days ago",
timezone: "UTC") }`; use it to validate your own expressions. Heatmap: `timeframe` is the string `"1h"` (hourly
cells) or `"24h"` (daily cells) plus a top-level `timezone`.

**Time range operation** (Value, aggregated instead of live): `{"other": true, "operation": "average", "start":
"24 hours ago", "end": "now", "timezone": "UTC"}` with `operation` `minimum|maximum|average|sum|abschange|percchange|count`
(`abschange`/`percchange` = consumption-style change over the window). `other: false` shows the current value.
Table columns use their own keys (`measurementTimerangeOperation` `current|average|sum|minimum|maximum|abschange|percchange|count`,
`measurementTimerangeStart`, `measurementTimerangeEnd`, `measurementTimerangeTimezone`).

**Ranges** (`gaugeRanges` on Value, MeasurementList, MapNG/ImageMap with `usesValueBasedColors`):
`[{ "value": 0, "color": "#10B981", "name": "OK" }, { "value": 6, "color": "#F59E0B", "name": "Warm" }]`. `value` is
the **lower bound** of a range: the widget takes the highest `value` that is ≤ the current value; a value below
the first range gets no colour, so start at the minimum. **Reference lines** (Value, LineChart):
`[{ "value": "8", "color": "#EF4444", "lineText": "max", "lineType": "solid", "strokeWidth": 1, "yAxisId": 1 }]`.

**Text variables**: `{{ TEMPERATURE }}` on device dashboards, `{{ <device id>[TEMPERATURE] }}` on workspace
dashboards (Markdown body). Value titles accept `{ device_name }` on workspace dashboards.

## Design guide: gauges, ranges, charts, layout

What makes a Datacake dashboard look right (Datacake's own guidance plus the editor's presets). `dashboards.py
generate` applies all of it; `add-widget --preset` applies the Value part.

**Gauges (Value widget).** Circular gauges read best and are the default for bounded quantities (humidity, CO₂,
soil moisture, signal, light). The gradient ramp (`gradientramp`, `gradientRampDirection: "ltr"`) suits banded
quantities such as temperature, where the colour bands tell the story. `battery` for battery fields, `fill` with
`fillLevelShape: "tank"` for fill levels, `compass` for directions. Use `linear`/`vertical` only where height is
scarce, and `none` for plain numbers (counters, strings, totals). Always set `unit`, a matching `icon`, sensible
`decimalPlaces` and `isTextColorStateBased: true` so the number takes the range colour.

**Ranges.** Ascending lower bounds, three to six bands, green for the good band, amber for attention, red for
alarm, blue/cyan for cold or excellent; name every band (`showCurrentRangeName` shows it under the value). The
editor's presets (`widgets/Value/index.tsx`, `VALUE_PRESETS`) are the reference values; the script carries them
with the gauge choices above (`dashboards.py schema presets`):

| Preset | Semantic | Gauge | Unit | Range lower bounds |
|---|---|---|---|---|
| `temperature` | TEMPERATURE | gradientramp | °C | 0 Cold · 10 Cool · 20 Comfortable · 25 Warm · 30 Hot |
| `humidity` | HUMIDITY | circular | % | 0 Too Dry · 30 Dry · 40 Comfortable · 60 Comfortable · 70 Humid · 80 Too Humid |
| `co2` | CO2 | circular | ppm | 0 Excellent · 450 Good · 600 Moderate · 1000 Poor · 1500 Unhealthy |
| `co2Concentration` | – | gradientramp | % | 0 Optimal · 30 Good · 50 Moderate · 70 High · 85 Critical |
| `battery` / `batteryPercent` | BATTERY | battery | V / % | 0 · 1.85 · 3.7 (volts) / 0 Low · 20 Medium · 50 Good (percent, skill addition) |
| `fillLevel` | FILL_LEVEL | fill (tank) | % | 0 · 100 |
| `signalStrength` | SIGNAL | circular | dBm | -90 Very Poor · -80 Poor · -70 Fair · -60 Good · -50 Excellent · -30 Perfect |
| `soilMoisture` | SOIL_MOISTURE | circular | % | 0 Extreme stress · 21 Stress · 41 Good · 61 Excess · 100 Excess |
| `ambientLight` | AMBIENT_LIGHT | circular | lux | 0 Night · 10 Very Dark · 50 Dark · 200 Dim · 500 Moderate · 1000 Bright |

Cold-chain or process limits differ per customer: ask for the limits and replace the bands, keep the colour logic.

**Charts.** `chartKind: "area"` looks best for continuous measurements (a matter of taste; `line` is the plain
alternative, `bar` for discrete values). One series per `devices` entry, distinct colours, `verboseName`/`label`
per series, a second axis (`yAxis.id: 2, orientation: "right"`) when units differ, a `referenceLines` entry for
the alarm threshold. Default window `7 days ago` at `1h`, `24 hours ago` at `15m` for live views.

**Counters and deltas.** For an absolute counter (energy, water, pulses) that should be shown as consumption per
bucket, enable the delta function on the data source: `fields[0].isDeltaEnabled: true` (plus `colorPositive`/
`colorNegative`, `chartKind: "bar"`). The chart then subtracts consecutive bucket values, so the chart's
`historyFunction` **must be `"max"`**: with the default average, bucketing changes the counter readings and the
deltas come out wrong. The script sets `max` automatically when a delta series is added and warns otherwise.

**Layout rhythm.** A `Headline` (12×1) per section; Value widgets 4×3 in rows of three; state widgets (Boolean,
OnlineStatus) 4×2; the main chart 12×4, secondary charts 6×4 in pairs; tables 12×4; controls (Switch 4×2, Slider
6×2, SetValue/Downlink 3×1) in their own section at the bottom. Order: identity and key values first, states,
history, controls. Titles are short nouns ("Temperature", "Door"), units live in `unit`, not in the title.

## Widget catalogue

Availability (the portal's add-widget rules) and default sizes (`w×h`) come from the editor; `dashboards.py schema
<Type>` prints the full default meta. The AI assistant inside the portal uses the same types.

| Widget | Device | Workspace | Size | Required meta | Purpose |
|---|---|---|---|---|---|
| `Headline` | yes | yes | 4×1 (use 12×1) | `title` | section heading |
| `Value` | yes | yes | 4×3 | `field` | one value, gauges, ranges, aggregation |
| `Boolean` | yes | yes | 4×2 | `field` (BOOL) | on/off state |
| `Text` | yes | yes | 4×2 | `text` | Markdown with variables |
| `LineChart` | yes | yes | 8×4 | `devices` | time series |
| `Histogram` | yes | yes | 8×3 | `devices` | bar/pie of current values across devices |
| `Heatmap` | yes | yes | 8×3 | `devices` | hourly/daily cells |
| `MeasurementList` | yes | yes | 4×9 | `field` | last n readings |
| `Table` | no | yes | 4×4 (use 12×4) | `columns` | device table by tags |
| `MapNG` | no | yes | 4×4 | – | map of located devices by tags |
| `OnlineStatus` | yes | no | 4×2 | – | online state of the viewed device |
| `Switch` | yes | yes | 4×2 | `field` (BOOL) | writes 1/0 |
| `Slider` | yes | yes | 6×2 | `field` | writes a number |
| `SetValue` | yes | yes | 3×1 | `field` | input + button |
| `Downlink` | yes | yes | 3×1 | `downlink` | sends a product downlink |
| `Button` | dzero | dzero | 3×1 | `function` | product function (dzero hardware only) |
| `Image` | yes | yes | 4×3 | `image` | uploaded image (upload id, portal only) |
| `Iframe` | yes | yes | 4×4 | `source` | embedded URL |
| `Map` (legacy), `DeviceFields` | yes | no | 4×4 | – | configure in the portal, copy the JSON |
| `ImageMap` 4×3, `Menu` 3×6, `ScatterPlot` 6×5, `AshraeChart` 8×4, `CoolingHealth` 8×6, `Emergency` (SOS) 2×4 | yes | yes | | – | configure in the portal, copy the JSON |

`TextInput` exists but is hidden in the portal. Unknown type names render as empty tiles.

**Value** (`gaugeType` `none|linear|vertical|circular|fill|battery|compass|gradientramp`): `unit` (translated),
`decimalPlaces`, `gaugeRanges`, `referenceLines`, `isTextColorStateBased`/`isBgColorStateBased` (colour follows the
current range), `showRangeLegend`, `showCurrentRangeName` (default true), `hideValue`, `isAbbreviatedNumber`,
`fontSize` (40), `icon`, `timerangeOperation`; fill: `fillLevelShape` `circular|square|tank`, `showFloatingParticles`,
`hasAnimation`; vertical: `verticalDirection` `ascending|descending`; gradient ramp: `gradientRampDirection` `ltr|rtl`,
`gradientRampMode` `ascending|descending`; compass: `showDegree`. `widgetPreset` only records which editor preset
was picked (`temperature`, `humidity`, `co2`, `battery`, `fillLevel`, `soilMoisture`, `signalStrength`,
`ambientLight`). Workspace dashboards can aggregate by semantic instead of a field: `dataSourceMode: "semantics"`,
`semantics: [{ "identity": "semantic_<id>", "includeDevices": false, "aggregatedSemanticRequests": [{ "kind":
"AGGREGATED_NUMERIC_SEMANTIC_VALUE", "semantic": "temperature", "aggregation": "Avg" }], "tags": { "contains": ["fridge"] } }]`
(verified: returns `aggregatedValues.semanticTemperatureAvg`).

```json widget Value device
{
  "title": { "en": "Humidity" }, "unit": { "en": "%" }, "decimalPlaces": 0, "icon": "tint",
  "field": { "device": "", "fieldName": "HUMIDITY", "fieldType": "NUMERIC", "verboseFieldName": "Humidity" },
  "gaugeType": "circular",
  "gaugeRanges": [ { "value": 0, "color": "#EF4444", "name": "Too dry" }, { "value": 40, "color": "#10B981", "name": "Comfortable" }, { "value": 60, "color": "#F59E0B", "name": "Humid" } ],
  "isTextColorStateBased": true, "showCurrentRangeName": true,
  "timerangeOperation": { "other": true, "operation": "average", "start": "24 hours ago", "end": "now", "timezone": "Europe/Berlin" }
}
```

**Boolean**: `displayOn`/`displayOff` (translated), `displayOnColor`/`displayOffColor`, `icon`, `isBgColorStateBased`.
**OnlineStatus** (device dashboards): same keys without `field`.

```json widget Boolean device
{ "title": { "en": "Door" }, "field": { "device": "", "fieldName": "DOOR_OPEN", "fieldType": "BOOL", "verboseFieldName": "Door open" },
  "displayOn": { "en": "Open" }, "displayOff": { "en": "Closed" }, "displayOnColor": "#EF4444", "displayOffColor": "#10B981", "isBgColorStateBased": true }
```

**Headline**: `size` 1–5 (1 largest), `layout` `vertical|horizontal`, `center`, `description`, `textColor`,
`backgroundColor`, `useGradient` + `gradientStartColor`/`gradientEndColor`/`gradientDirection` (`to bottom`, `to right`, …),
`showBottomBorder`, `bottomBorderColor`, `bottomBorderSize`; `hideBackground` defaults to true.

**Text**: `text` (translated Markdown), `center`, `textColor`.

**LineChart**: `devices` (series above), `timeframe`, `historyFunction` `""` (average) `|min|max|sum` (per bucket),
`referenceLines` (with `yAxisId`), `dateFormat` (Luxon preset such as `DATE_SHORT`, `DATETIME_MED`), `showXGrid`,
`disableGapfill`, `allowTimeframeSelect` (viewer can change the range), `showExportViewButton`, `showStatisticsButton`.
`events` and `referenceAreas` (time slots) exist; configure them in the portal.

```json widget LineChart workspace
{
  "title": { "en": "Both fridges" },
  "timeframe": { "start": "7 days ago", "end": "now", "resolution": "1h", "otherTimeframe": false, "timezone": "UTC" },
  "historyFunction": "",
  "devices": [
    { "device": "2fcc6915-a3f9-49a0-9416-249ce6c9b9c5", "fields": [ { "field": "TEMPERATURE", "color": "#ef4444", "verboseName": "Fridge 1", "chartKind": "line" } ],
      "yAxis": { "id": 1, "orientation": "left", "hidden": false, "scale": "auto", "unit": "°C" } },
    { "device": "0a78be90-ac8c-472d-bf50-ec470245fec4", "fields": [ { "field": "TEMPERATURE", "color": "#3b82f6", "verboseName": "Fridge 2", "chartKind": "line" } ],
      "yAxis": { "id": 1, "orientation": "left", "hidden": false, "scale": "auto" } }
  ],
  "referenceLines": [ { "value": "8", "color": "#EF4444", "lineText": "max", "lineType": "solid", "strokeWidth": 1, "yAxisId": 1 } ]
}
```

**Histogram**: `devices: [{ device, fieldName, color, title }]` (current values only), `chartType` `bar|pie`,
`decimalPlaces`, `showStatisticsTable`, `showValuesOnBars`, `enableValueRanges` + `valueRanges: [{ id, min, max, color, name }]`,
`unit`; semantics mode like Value (`aggregatedSemanticDeviceRequests`).

**Heatmap**: `devices: [{ device, fieldName, verboseName, unit, isDeltaEnabled, historyFunction: ""|"min"|"max",
rangeSettings: [{ value, color, text }] }]`, `timeframe` `"1h"|"24h"`, `cellCount`, `cellSize` `small|normal`,
`orientation` `horizontal|vertical`, `hasGradient`, `hasWeekDays`, `markStaleData`, `decimalPlaces`, `timezone`.
Semantic mode uses `dataSourceMode: "semantic"` (singular) with `semantic`, `historyFunction`, `tagsFilter: { contains|overlap: [...] }`.

**MeasurementList**: `field`, `limit` (string), `gaugeRanges` + `useValueBasedColors`, `showRangeName`,
`numericalColumnHeader`, boolean texts/colours (`booleanTrueText`, `booleanTrueColor`, …).

**Table** (workspace): devices by `tagsFilter` (array of tags, empty = all) and `nameFilter`; `columns` (every
column needs a uuid `id`); `conditionalFormatting: [{ column: <column id>, condition: smaller|smallerequals|equals|equalsnot|largerequals|larger,
target: "8", textColor, backgroundColor, applyToFooter, hideRow }]`; `defaultSortByColumn` (index), `defaultSortDirection`
`asc|desc`, `defaultPaginateBy` `"10"|"25"|"50"`, `showPagination` `auto|always|never`, `tableSize` `small|medium|large`,
`showFooter` + per-column `footerOperation` `none|average|sum|minimum|maximum|count|countBooleanTrue|countBooleanFalse|countThreshold`,
`showExcelExport`, `hideHeaderBackground`. `meta.uuid` is the widget's data key (set once, keep it).

```json widget Table workspace
{
  "title": { "en": "Fridges" }, "tagsFilter": [ "fridge" ], "nameFilter": "", "uuid": "9c0d2f6e-6a52-4a28-9d6e-7f1b0d3c4e55",
  "columns": [
    { "id": "7e1a3c2b-0f4d-4b7a-8c9e-1a2b3c4d5e01", "name": "Device", "dataKind": "meta", "metaKind": "LinkedName" },
    { "id": "7e1a3c2b-0f4d-4b7a-8c9e-1a2b3c4d5e02", "name": "Online", "dataKind": "meta", "metaKind": "Online" },
    { "id": "7e1a3c2b-0f4d-4b7a-8c9e-1a2b3c4d5e03", "name": "Temperature", "dataKind": "measurement", "measurementFieldName": "TEMPERATURE",
      "measurementTimerangeOperation": "current", "floatDigits": 1, "unit": "°C", "footerOperation": "average" },
    { "id": "7e1a3c2b-0f4d-4b7a-8c9e-1a2b3c4d5e04", "name": "Door", "dataKind": "measurement", "measurementFieldName": "DOOR_OPEN",
      "measurementTimerangeOperation": "current", "booleanTrueText": "open", "booleanFalseText": "closed", "booleanShowAsTags": true }
  ],
  "conditionalFormatting": [ { "column": "7e1a3c2b-0f4d-4b7a-8c9e-1a2b3c4d5e03", "condition": "larger", "target": "8", "textColor": "#ffffff", "backgroundColor": "#EF4444" } ],
  "showFooter": true, "defaultSortByColumn": 2, "defaultSortDirection": "desc"
}
```

**MapNG** (workspace): shows every workspace device that has a location field (role `DEVICE_LOCATION`), filtered
by `allDevicesFilterTags` + `allDevicesFilterTagsAnyAll` `any|all`; `mapStyle` `light|dark|streets|outdoor|satellite|basic`,
`mapMode` `marker|heatmap`, `markerRoleChoice` `None|Primary|Secondary|DeviceBattery|DeviceSignal` (which role field
labels/colours the marker), `usesValueBasedColors` + `gaugeRanges`, `markerSize` `"30"|"70"|"120"|"180"`,
`isClusterDisabled`, `isDeviceNameVisible`, `showFilterPanel`, `location: { latitude, longitude, zoom }` for the
initial view, `isFullScreenHeight`.

**Switch**: `field` (BOOL). **Slider**: `field`, `min`, `max`, `step`, `unit`, `orientation`, `isRangeVisible`.
**SetValue**: `fieldType` `measurement` (+ `field`) or `config` (+ `configurationField` with the same four keys),
`widgetTitle`, `description`, `icon`. All three write through `setValue` (also on public links in WRITE mode).

**Downlink**: `downlink: { "device": "<id or \"\">", "downlink": "<downlink id>" }` (ids from
`product.lorawanDownlinks { id name }` or `product.apiConfiguration { apiDownlinks { id name } }`), optional
`additionalDownlinks: [{ device, fields: [{ field: <downlink id>, name }] }]`. **Button**: `function: { device, function,
functionId, fieldStates }` (product functions, dzero hardware only).

**Image**: `image` is the id returned by the portal upload (`uploadDashboardImage` is reserved for the editor), `size`
`contain|cover`, `link: { url, newTab }`, `useDeviceImage` on device dashboards. **Iframe**: `source` URL.

## Writing: create, save, tabs, delete, home, restore

Create a workspace dashboard in one call (verified: `dashboards` and `isHomeDashboard` are honoured; a dashboard
with `sharingPolicy: public` gets a public link automatically):

```graphql
mutation AddDashboard($input: AddDashboardInputType!) {
  addDashboard(input: $input) { ok dashboard { id name dashboards } }
}
```

```json AddDashboardInputType
{ "workspace": "7f4d8d92-ade9-417f-961a-e8445d618f9f", "name": "Cold chain", "icon": "chart-line", "type": "CUSTOM",
  "sharingPolicy": "restricted", "sharedWith": ["03da7781-2118-437c-bc34-8a435fa21f6a"], "isHomeDashboard": false,
  "dashboards": "[{\"name\": \"Dashboard\", \"widgets\": {}}]" }
```

`icon` is a Font Awesome name (`chart-line`, `cloud`, `wind`, `snowflake`, …). The portal creates in two steps
(`addDashboard` without a layout, then `updateDashboard` with the empty tab); both work.

Save a layout (workspace dashboard; only the fields you pass change, `name`, `icon`, `sharingPolicy` and
`sharedWith` stay as they are, verified):

```graphql
mutation SaveDashboard($input: UpdateDashboardInputType!) {
  updateDashboard(input: $input) { ok dashboard { id dashboards } }
}
```

```json UpdateDashboardInputType
{ "workspace": "7f4d8d92-ade9-417f-961a-e8445d618f9f", "dashboard": "a001905e-c8a0-4a99-b0f1-d3bab00f7d22",
  "dashboards": "[{\"name\": \"Dashboard\", \"widgets\": {}}]", "changeMessage": "Add fridge overview" }
```

The same input renames (`name`), changes sharing (`sharingPolicy`, `sharedWith`), the icon and the colours
(`dashboardBgColor`, `dashboardOverlayColor`, `dashboardTextColorLight`, `dashboardTextColorDark`); `metaJSON` is
for CLIMATE/IAQ settings.

Save a device dashboard (applies to every device of the product):

```graphql
mutation SaveDeviceDashboard($input: UpdateProductInputType!) {
  updateProduct(input: $input) { ok product { id dashboards } }
}
```

```json UpdateProductInputType
{ "product": "9c2481ee-4b9e-4b6e-9304-a2cdb6532b99", "dashboards": "[{\"id\": \"4394304a-c4e5-4438-9a1a-17d69d0c2c67\", \"name\": \"Dashboard\", \"widgets\": {}}]",
  "changeMessage": "Rebuilt from the field list" }
```

`updateProductDashboard(config, id)` is the legacy mutation; do not use it.

Tabs are array edits: append `{ "name": "Energy", "widgets": {} }` (device dashboards: plus `"id": "<uuid4>"` and
optionally `"hideOnWhitelabel": true`), rename by changing `name`, remove by dropping the entry (never tab 0 of a
device dashboard, never the last tab). Delete a workspace dashboard with `deleteDashboard(dashboard, workspace)`;
set the home dashboard with `updateWorkspace(id: $workspaceId, homeDashboardId: $dashboardId)` (a UUID, or `""`
to unset). Restore a version: take `dashboards` from a changelog node and save it back with
`changeMessage: "Restored version from <date>"` (there is no restore mutation).

With the script:

```bash
python3 scripts/dashboards.py list <workspace>                                   # targets: dashboard ids, product:<id>
python3 scripts/dashboards.py get product:<product-id>                           # tabs, widgets, layout, fields; --json / --out layout.json
python3 scripts/dashboards.py schema Value ; schema presets                      # default meta, required keys, field types; Value presets
python3 scripts/dashboards.py generate product:<product-id> --execute            # complete device dashboard from the product's fields (design guide applied)
python3 scripts/dashboards.py generate product:<product-id> --new-tab "Overview" --controls VALVE_OPEN,SETPOINT --timeframe "24 hours ago" --resolution 15m --execute
python3 scripts/dashboards.py generate product:<product-id> --exclude '*_INST,*_RAW,LATITUDE,LONGITUDE' --replace --execute   # only the fields that belong on the dashboard
python3 scripts/dashboards.py generate <dashboard-id> --product <product-id> --tags fridge --fields TEMPERATURE,HUMIDITY,CO2,BATTERY --execute   # fleet overview on a workspace dashboard
python3 scripts/dashboards.py check device:<device-id> --type Value --field TEMPERATURE --preset temperature   # server preview, writes nothing
python3 scripts/dashboards.py add-widget product:<product-id> --type Headline --title "Fridge" --w 12 --execute
python3 scripts/dashboards.py add-widget product:<product-id> --type Value --field HUMIDITY --preset humidity --execute
python3 scripts/dashboards.py add-widget product:<product-id> --type Value --field TEMPERATURE --meta @value.json --execute
python3 scripts/dashboards.py add-widget <dashboard-id> --type Value --field TEMPERATURE@<device-id> --next --execute   # workspace: device id required
python3 scripts/dashboards.py update-widget <target> <widget-id> --meta '{"title":{"en":"Fridge temperature"}}' --execute
python3 scripts/dashboards.py move-widget <target> <widget-id> --x 4 --y 1 --w 4 --h 3 --execute
python3 scripts/dashboards.py tab add product:<product-id> --name "Energy" --execute
python3 scripts/dashboards.py save <target> --file layout.json --message "Rebuilt layout" --execute   # whole array; no-op when unchanged
python3 scripts/dashboards.py create <workspace> --name "Cold chain" --sharing workspace --home --execute
python3 scripts/dashboards.py changelog <target> ; restore <target> <historyId> --execute ; delete <dashboard-id> --execute
```

`generate` reads the product's fields and builds a whole tab. On a device dashboard (`product:`/`device:` target):
headline, one `Value` per numeric/string field (preset by semantic: temperature, humidity, CO₂, battery, fill
level, signal, soil moisture, light; otherwise a plain value with the field's unit and decimals; primary and
secondary fields first, battery and signal last), `OnlineStatus` and a `Boolean` per BOOL field, a "History"
section with an area chart of the primary field (12×4) and up to four more charts (6×4; COUNTER fields as delta
bars with `historyFunction: "max"`), and an optional "Controls" section (`--controls`: Switch for BOOL, Slider for
numeric fields). On a workspace dashboard (`--product` required, `--tags` recommended): a fleet overview with
semantic KPI `Value` widgets (average temperature/humidity/fill level/soil moisture/light, highest CO₂, lowest
battery/signal; scoped to the tags, or, without tags, only for semantics no other product of the workspace uses), a
`Table` of the devices (LinkedName, Online, Last heard, every field as a current-value column with units and a
footer average, BOOL fields as tags), `MapNG` when the product has a location field, and for the primary field a
per-device `LineChart` (area up to two devices, line above), a daily `Heatmap` and a `Histogram` of the current
values (`--max-devices`, default 12). `--fields A,B,C` limits and orders the fields (the first numeric one is the
main chart), `--exclude '*_INST,*_RAW'` drops fields by glob pattern (products often carry installation, raw or
coordinate fields that do not belong on a dashboard). It fills an empty tab 0, needs `--replace` for a tab with
widgets, or writes a new tab with `--new-tab`. Adjust afterwards with `update-widget`/`move-widget`.
`add-widget` merges your `--meta` over the editor defaults (and a `--preset` for Value widgets), fills
`fieldType`/`verboseFieldName` and the unit from the product, generates uuids (widget, Table `uuid`, column ids),
places the widget below the last row (`--next`: to the right when it fits) and validates: type allowed in this
context, grid bounds, required meta, field exists on the product, field type fits, time expressions parse, delta
series have `historyFunction: "max"`. `update-widget` is a shallow merge: pass nested objects (`timeframe`,
`field`, `devices`) complete; `null` removes a key.

## Recipes

**Device dashboard from the product's fields** (one product, hundreds of devices): `dashboards.py generate
product:<id>` (dry run shows every widget), then `--execute`; it applies the design guide (presets, area charts,
layout rhythm). Refine: customer-specific limits via `update-widget <id> --meta '{"gaugeRanges": [...]}'`, a
reference line on the main chart, `Downlink` widgets for LoRaWAN commands (`add-widget --type Downlink --meta
'{"downlink": {"device": "", "downlink": "<id>"}}'`), `--controls` for setpoints. Field references use
`"device": ""`. Check with `dashboards.py check device:<id>` (one device of the product), then ask the user to open
any device of the product and reload. Building by hand follows the same order: `Headline` (12×1) → `Value` rows of
three with presets → `Boolean`/`OnlineStatus` → `LineChart` (12×4) → controls.

**Workspace overview** (fleet of one product, tags per site): make sure the fleet carries a tag (`updateDevice(deviceId,
input: { tags })` per device; the table and the map can only filter by tags), then `dashboards.py create <workspace>
--name "Fridges" --execute` and `dashboards.py generate <dashboard-id> --product <product-id> --tags fridge --fields
TEMPERATURE,HUMIDITY,DOOR_OPEN,BATTERY --execute` (pick the columns the table should show). The result
is `Headline` → semantic KPI `Value` widgets (`AGGREGATED_NUMERIC_SEMANTIC_VALUE`, tag filter) → `Table` (12×4 or
8×4 next to `MapNG`; `tagsFilter`, columns `LinkedName`, `Online`, `LastHeardDevice`, measurements with `current`,
footer `average`) → per-device `LineChart` (12×4, one series per device) → daily `Heatmap` → `Histogram` of the
current values. Refine with conditional formatting on the table (out-of-range values), customer limits on the KPI
ranges, and `--tags` per site for one dashboard per site. Workspace widgets need device ids (`FIELD@<device id>`
in the script) except Table, MapNG and semantics widgets.

**Bulk edits and copies**: `dashboards.py get <target> --out layout.json`, edit the JSON (rename titles, swap a
field name in every widget, copy a tab into another product's layout), `dashboards.py validate --file layout.json
--kind device`, then `dashboards.py save <target> --file layout.json --execute`. Copying a device dashboard to
another product works when the field identifiers match; widgets whose field does not exist there stay empty (the
script reports them). Widget ids may stay the same across products; inside one layout every id must be unique.

**Rollback**: `dashboards.py changelog <target>` (needs the history entitlement) → `restore <target> <historyId>
--execute`; without the entitlement, keep your own copies (`get --out`) before large changes.

## Pitfalls

- `dashboards` is a JSONString: `JSON.stringify` the array once; a double-encoded string or a JSON object instead
  of an array is stored as-is and breaks the page (the schema validator cannot catch it).
- `widgets` must be an object keyed by uuid; `layouts.lg.i` must equal that key; `x + w ≤ 12`; a widget type the
  portal does not know renders an empty tile without an error, and so does a `fieldName` the product lacks.
- Overlapping widgets are re-stacked by the grid on the next portal save, in an order you do not control.
- Mobile: once a dashboard has `sm` widgets, every widget without an `sm` twin is invisible on phones. Do not
  delete `sm`-only widgets, do not add `sm` layouts yourself.
- `Table`/`MapNG` on a device dashboard and `OnlineStatus`/`DeviceFields`/`Map` on a workspace dashboard are not
  offered by the portal; a workspace `Value` with `"device": ""` shows nothing.
- `gaugeRanges.value` is the lower bound (ascending), not the upper bound; `timerangeOperation` uses `operation`
  (`operator` in old layouts is ignored); Heatmap `timeframe` is a string; chart `resolution` `raw` becomes 30 m.
- A delta series (`isDeltaEnabled`) with the default `historyFunction` (average) shows wrong consumption: set
  `historyFunction: "max"` on that chart.
- Writes replace everything: never save a layout read before another write; `changeMessage` ≤ 100 characters;
  without `entitlementDashboardHistoryEnabled` the changelog stays empty (no error).
- The portal shows the change only after a reload; the editor in edit mode overwrites your write when the user
  leaves edit mode. Ask before writing while someone is editing.
- `dashboardData` returns widget values, not the layout; Histogram, MapNG and the non-data widgets return nothing
  there even when they are fine.
- Images and mobile layouts are created in the portal; `uploadDashboardImage` is reserved for the editor.
- *Untested*: `dashboardBgImg` uploads, public-link WRITE mode through widgets, dashboards with `sm` layouts
  written by the API (mobile rendering was only checked without them).
