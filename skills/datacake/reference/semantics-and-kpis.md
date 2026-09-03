# Semantics, cross-device filters and KPIs

## Contents

- What semantics are
- Semantic catalogue (numeric, boolean, location)
- Discovering semantics in a workspace
- Filtering devices by semantic values
- Aggregations over a device list (KPIs)
- Per-device semantic values
- Sorting by semantic
- Filter aggregation vs result aggregation
- KPI patterns
- Nulls, limits and workarounds
- Assigning semantics

## What semantics are

A semantic is a label on a product field that states what the field measures (`TEMPERATURE`, `CO2`, `DOOR_OPENED`). Different products name their fields differently (`temp_01`, `TEMPC_SHT`, `TEMPERATURE`); semantics make them comparable. The platform uses them for workspace/folder KPI overviews, IAQ dashboards, exports by semantic, and the API exposes them as filters, aggregations and per-device accessors.

Use semantics for: KPI cards, cross-product device lists, alert counts, fleet health, anything spanning more than one product.
Use identifiers for: history charts, exact current values of a known product, writes.

## Semantic catalogue

Numeric (`numericSemanticField`, numeric filters, `aggregatedNumericSemanticValue`):

| Semantic | Typical unit | Filter argument |
|---|---|---|
| `TEMPERATURE` | °C | `temperature` |
| `HUMIDITY` | % | `humidity` |
| `CO2` | ppm | `co2` |
| `VOC` | ppb / index | `voc` |
| `AIR_POLLUTION` | µg/m³ (PM) | `airPollution` |
| `AMBIENT_LIGHT` | lux | `ambientLight` |
| `LOUDNESS` | dB | `loudness` |
| `BATTERY` | % or V | `battery` |
| `SIGNAL` | dBm (RSSI) | `signal` |
| `SNR` | dB | `snr` |
| `POWER` | W / kW | `power` |
| `ENERGY_CONSUMPTION` | kWh (cumulative) | `energyConsumption` |
| `WATER_CONSUMPTION` | m³ / L (cumulative) | `waterConsumption` |
| `WATER_DEPTH` | m / cm | `waterDepth` |
| `FILL_LEVEL` | % | `fillLevel` |
| `SOIL_MOISTURE` | % | `soilMoisture` |
| `PEOPLE_COUNT` | count | `peopleCount` |
| `RUNTIME_HOURS` | h | `runtimeHours` |
| `HOURS_UNTIL_MAINTENANCE` | h | `hoursUntilMaintenance` |

Boolean (`booleanSemanticField`, boolean filters, `aggregatedBooleanSemanticCount`): `BATTERY_LOW` (`batteryLow`), `BUTTON_PRESSED`, `DESK_OCCUPIED`, `DEVICE_POWERED`, `DOOR_OPENED`, `EMERGENCY_TRIGGERED`, `GAS_LEAK_DETECTED`, `HVAC_ACTIVE`, `LIGHT_ON`, `MAINTENANCE_REQUIRED`, `MOTION_DETECTED`, `PARKING_OCCUPIED`, `POWER_OUTAGE_DETECTED`, `RAIN_DETECTED`, `ROOM_OCCUPIED`, `SMOKE_DETECTED`, `TAMPER_DETECTED`, `VALVE_OPENED`, `WATER_LEAK_DETECTED`, `WINDOW_OPENED`. Filter argument names are the lowerCamelCase form (`doorOpened`, `waterLeakDetected`).

`LOCATION` marks position fields (no numeric filter; use `currentLocation` and zones).

The authoritative list is `enum FieldSemantic` in `reference/schema.graphql`; new semantics appear there first.

## Discovering semantics in a workspace

```graphql
query Semantics($workspaceId: String!) {
  workspace(id: $workspaceId) {
    semantics
    products { name measurementFields(active: true) { fieldName semantic } }
  }
}
```

`semantics` lists every semantic assigned somewhere in the workspace; use it to decide which KPI cards to render.

## Filtering devices by semantic values

Numeric filter input: `{ gt, gte, lt, lte, range: { start, end }, aggregation: AVG|SUM|MAX|MIN }`. `aggregation` says how several fields with the same semantic on one device are combined before comparing (default `AVG`). Multiple semantic arguments are ANDed and each requires the device to have that semantic.

Boolean filter input: `{ exact: Boolean, inList: [Boolean], count: { gt, gte, lt, lte, range, countValue }, aggregation: AVG|MAX|MIN }` (`count` filters on how many fields of that semantic equal `countValue`, for multi-sensor devices).

```graphql
query Filters($workspaceId: String!) {
  workspace(id: $workspaceId) {
    stuffy: devicesFiltered(co2: { gt: 1000 }, online: true, pageSize: 20) {
      total
      devices { id verboseName co2: numericSemanticField(semantic: CO2) { value } }
    }
    comfortable: devicesFiltered(
      temperature: { range: { start: 20, end: 24 } }
      humidity: { gte: 40, lte: 60 }
    ) { total }
    lowBattery: devicesFiltered(battery: { lt: 20, aggregation: MIN }) { total }
    openDoors: devicesFiltered(doorOpened: { exact: true }, pageSize: 50) {
      total
      devices { id verboseName tags }
    }
    leaks: devicesFiltered(waterLeakDetected: { exact: true }) { total }
  }
}
```

## Aggregations over a device list (KPIs)

`FilteredDeviceList` computes across every device matching the filter (not just the page):

```graphql
query Kpis($workspaceId: String!) {
  workspace(id: $workspaceId) {
    devicesFiltered(online: true) {
      total
      avgTemperature: aggregatedNumericSemanticValue(semantic: TEMPERATURE, aggregation: AVG)
      maxCo2: aggregatedNumericSemanticValue(semantic: CO2, aggregation: MAX)
      minBattery: aggregatedNumericSemanticValue(semantic: BATTERY, aggregation: MIN)
      totalPower: aggregatedNumericSemanticValue(semantic: POWER, aggregation: SUM)
      occupiedRooms: aggregatedBooleanSemanticCount(semantic: ROOM_OCCUPIED, countValue: true)
      openWindows: aggregatedBooleanSemanticCount(semantic: WINDOW_OPENED, countValue: true)
    }
  }
}
```

Leave out `devices { … }` when only aggregates are needed; the request then costs almost nothing regardless of fleet size. `AVG` for readings, `MAX`/`MIN` for peak detection, `SUM` for power or counts.

## Per-device semantic values

```graphql
query SemanticDevices($workspaceId: String!) {
  workspace(id: $workspaceId) {
    devicesFiltered(pageSize: 25, orderBy: { verboseName: ASC }) {
      total
      devices {
        id verboseName online product { name }
        temperature: numericSemanticField(semantic: TEMPERATURE) { value }
        humidity: numericSemanticField(semantic: HUMIDITY) { value }
        battery: numericSemanticField(semantic: BATTERY, aggregation: MIN) { value }
        door: booleanSemanticField(semantic: DOOR_OPENED) { value openCount: count(countValue: true) }
        temperatureDetails: numericSemanticField(semantic: TEMPERATURE) {
          value
          fields { fieldName verboseFieldName value unit }
        }
      }
    }
  }
}
```

- `value` is `null` when the device has no field with that semantic or no data.
- `fields { … }` lists the underlying fields (identifier, unit, individual value); include it only in detail views.
- `booleanSemanticField.count(countValue:)` counts matching fields on that device.
- Works on `publicDevice` too.

## Sorting by semantic

```graphql
query Coldest($workspaceId: String!) {
  workspace(id: $workspaceId) {
    devicesFiltered(
      temperature: { lt: 100 }
      pageSize: 10
      orderBy: { semanticField: { semantic: TEMPERATURE, order: ASC, numericAggregation: MIN } }
    ) {
      devices { id verboseName temperature: numericSemanticField(semantic: TEMPERATURE) { value } }
    }
  }
}
```

Boolean ordering: `orderBy: { booleanSemanticFieldCount: { semantic: DOOR_OPENED, order: DESC, countValue: true } }`. Role-based ordering (`Primary`, `DeviceBattery`, …) is the alternative when semantics are not assigned.

## Filter aggregation vs result aggregation

- Filter `aggregation` (inside `temperature: { … }`) and `numericSemanticField(aggregation:)` combine several same-semantic fields **within one device**.
- `aggregatedNumericSemanticValue(aggregation:)` combines **across devices** after filtering.
- Example: `devicesFiltered(temperature: { gt: 25, aggregation: MAX }) { avg: aggregatedNumericSemanticValue(semantic: TEMPERATURE, aggregation: AVG) }` = average temperature of devices whose hottest sensor exceeds 25 °C.

## KPI patterns

Workspace header (one request, no device payload):

```graphql
query Header($workspaceId: String!) {
  workspace(id: $workspaceId) {
    all: devicesFiltered(all: true) { total }
    online: devicesFiltered(online: true) {
      total
      avgTemperature: aggregatedNumericSemanticValue(semantic: TEMPERATURE)
      avgHumidity: aggregatedNumericSemanticValue(semantic: HUMIDITY)
      avgCo2: aggregatedNumericSemanticValue(semantic: CO2)
    }
    offline: devicesFiltered(online: false) { total }
    lowBattery: devicesFiltered(battery: { lt: 20 }) { total }
    weakSignal: devicesFiltered(signal: { lt: -110 }) { total }
  }
}
```

Per area (tags + aliases):

```graphql
query Floors($workspaceId: String!) {
  workspace(id: $workspaceId) {
    floor1: devicesFiltered(tags: { contains: ["floor-1"] }) {
      total
      temperature: aggregatedNumericSemanticValue(semantic: TEMPERATURE)
      co2: aggregatedNumericSemanticValue(semantic: CO2, aggregation: MAX)
      occupied: aggregatedBooleanSemanticCount(semantic: ROOM_OCCUPIED, countValue: true)
    }
    floor2: devicesFiltered(tags: { contains: ["floor-2"] }) {
      total
      temperature: aggregatedNumericSemanticValue(semantic: TEMPERATURE)
      co2: aggregatedNumericSemanticValue(semantic: CO2, aggregation: MAX)
      occupied: aggregatedBooleanSemanticCount(semantic: ROOM_OCCUPIED, countValue: true)
    }
  }
}
```

Generate one alias per tag from `workspace.allTags` or the app's configuration; dozens of aliases in one request are fine.

Alert list = count + paginated details:

```graphql
query Alerts($workspaceId: String!) {
  workspace(id: $workspaceId) {
    highCo2: devicesFiltered(co2: { gt: 1200 }, pageSize: 10, orderBy: { semanticField: { semantic: CO2, order: DESC } }) {
      total
      devices { id verboseName tags co2: numericSemanticField(semantic: CO2) { value } }
    }
    leaks: devicesFiltered(waterLeakDetected: { exact: true }, pageSize: 10) {
      total
      devices { id verboseName tags lastHeard }
    }
  }
}
```

Fleet health: `battery { lt }`, `signal { lt }`, `online: false`, `lastHeard { lt }`, `batteryLow { exact: true }`, `maintenanceRequired { exact: true }`.

Occupancy: `deskOccupied`/`roomOccupied`/`parkingOccupied` with `aggregatedBooleanSemanticCount(countValue: true)` vs `total` gives utilisation.

## Nulls, limits and workarounds

- Devices without the semantic return `null`; render "–" and never coerce to 0.
- No semantic history: to chart "temperature of all devices on floor 1", resolve the identifiers first (`product.measurementFields` where `semantic == TEMPERATURE`, per product) and call `history` per device with those identifiers.
- No semantic `change()`/`average()` windows: use identifiers with `currentMeasurement(fieldName:)`.
- Exports support `exportFieldSelection: SEMANTICS` with `exportSemantics: [TEMPERATURE]` for bulk data by semantic.
- Filters require data: a device with an assigned semantic but no value never matches a numeric filter.

## Assigning semantics

Semantics live on the product field. Via the portal (device > Configuration > Fields > Edit > Semantic) or the API:

```graphql
mutation Tag($fieldId: String!) {
  updateProductMeasurementField(fieldId: $fieldId, semantic: TEMPERATURE, role: PRIMARY) {
    ok
    field { id fieldName semantic role }
  }
}
```

Needs the `devices` workspace permission (product editing). Field ids come from `product.measurementFields { id }`.
