# Measurements, history and consumption

## Contents

- Current values
- Time-range statistics on one field
- Historical data (`history`)
- `historyNg` and `historyStats`
- Consumption, meters and counters
- Local time boundaries (JavaScript, Python)
- Strings, booleans and locations
- Performance rules

Terminology: **identifier** = `fieldName` (e.g. `TEMPERATURE`), always UPPER_SNAKE. Measurement queries take identifiers; semantics are only for filtering and aggregation (see `semantics-and-kpis.md`).

## Current values

On a device (`DeviceType`) or on `publicDevice` role fields; on any device list (`devicesFiltered.devices`, `allDevices`):

```graphql
query Current($deviceId: String!) {
  device(deviceId: $deviceId) {
    id
    verboseName
    lastHeard
    selected: currentMeasurements(fieldNames: ["TEMPERATURE", "HUMIDITY", "BATTERY"]) {
      value
      valueString
      modified
      field { fieldName verboseFieldName unit fieldType semantic role }
    }
    everything: currentMeasurements(allActiveFields: true) {
      value
      modified
      field { fieldName unit }
    }
    single: currentMeasurement(fieldName: "TEMPERATURE") { value modified }
  }
}
```

`DeviceCurrentMeasurementType`:

| Field | Meaning |
|---|---|
| `value` | latest numeric value (`Float`); `null` for string/geo fields or when no data |
| `valueString` | latest value as string (use for `STRING` and `GEO` fields, e.g. `"(52.5,13.4)"`) |
| `valueCounterAbs` | absolute counter reading for `COUNTER` fields |
| `modified` | timestamp of the latest value (UTC) |
| `field { … }` | the field definition (`fieldName`, `verboseFieldName`, `unit`, `displayUnit`, `fieldType`, `role`, `semantic`, `floatDigits`, `color`) |
| `sum`, `average`, `minimum`, `maximum`, `change` | time-range functions, below |

Selection variants: `fieldNames: [...]` (explicit identifiers, preferred), `allActiveFields: true` (everything active; only for detail views), `fieldVerboseNames: [...]` (by label, avoid). Unknown or inactive identifiers are silently dropped (the list is just shorter, no error), so validate identifiers against `product.measurementFields`.

Root shortcuts `currentMeasurement(deviceId:, fieldName:)` and `currentMeasurements(deviceId:, fieldNames: [String!]!)` exist but returned `null`/`[]` for an API-user token in tests; prefer `device(deviceId:) { currentMeasurements }`.

## Time-range statistics on one field

Every current measurement carries server-side aggregations over an arbitrary window (`DateTime!` arguments, UTC, start inclusive, end exclusive):

```graphql
query Stats($deviceId: String!, $start: DateTime!, $end: DateTime!) {
  device(deviceId: $deviceId) {
    currentMeasurement(fieldName: "TEMPERATURE") {
      latest: value
      avg: average(timeRangeStart: $start, timeRangeEnd: $end)
      min: minimum(timeRangeStart: $start, timeRangeEnd: $end)
      max: maximum(timeRangeStart: $start, timeRangeEnd: $end)
      total: sum(timeRangeStart: $start, timeRangeEnd: $end)
      delta: change(timeRangeStart: $start, timeRangeEnd: $end)
    }
  }
}
```

- `average`/`minimum`/`maximum` are computed over the raw datapoints in the window.
- `sum` adds datapoints (event counts, pulses); it returned `0` for an ordinary numeric field in tests, so verify it on your field type and use `change` for meters.
- `change` = value at the end of the window minus value at its start (consumption from a cumulative meter reading).
- `value(timeRangeStart:, timeRangeEnd:)` returned the latest reading in tests; do not rely on the range arguments for "value as of" without verifying.
- These are cheap (~100 ms) and ideal for KPI cards ("today", "yesterday", "this month"); batch several windows with aliases. Use `historyStats` when you want all fields at once.

## Historical data (`history`)

```graphql
query History($deviceId: String!, $from: String!, $to: String!, $resolution: String!) {
  device(deviceId: $deviceId) {
    history(
      fields: ["TEMPERATURE", "HUMIDITY"]
      timerangestart: $from
      timerangeend: $to
      resolution: $resolution
    )
  }
}
```

Variables: `{"deviceId": "…", "from": "2026-03-01T00:00:00Z", "to": "2026-03-02T00:00:00Z", "resolution": "15m"}`.

Arguments:

| Argument | Notes |
|---|---|
| `fields` | identifiers; when omitted the result contains the fields that have data in the range (heavier) |
| `timerangestart`, `timerangeend` | ISO strings, UTC unless an offset is given (`+02:00` is honoured); end must be after start; an end in the future is accepted (trailing buckets are `null`) |
| `resolution` | `"raw"` (stored datapoints, short ranges only) or a bucket size in the compact form `<n>m`, `<n>h`, `<n>d`, `<n>w`: `"5m"`, `"15m"`, `"1h"`, `"6h"`, `"24h"`, `"7d"`, `"1w"`; buckets are averaged (no other aggregation). MUST use the compact form: word forms such as `"30 minutes"` (seen in older docs) and unknown strings are silently replaced by an automatic resolution |
| `locf` | `true` carries the last value forward into empty buckets after the first datapoint (step charts, meters); buckets before the first datapoint stay `null` |
| `nodatathreshold` | portal gap-filling switch; showed no visible effect in API tests, leave unset |

Buckets are aligned to UTC boundaries (a `24h` bucket always starts at 00:00 UTC, a `6h` bucket at 00/06/12/18 UTC), not to `timerangestart`; the first bucket may therefore begin before the requested start. For local-day totals in other time zones use `change()` per local day or aggregate `1h` buckets yourself.

Response: a **JSON string** of an array ordered by time, one object per bucket with a `time` key (`…Z`) plus one key per identifier (`null` when empty). Bucket averages may be serialized as numeric **strings** (`"19.000000"`) instead of numbers: coerce with `Number()` / `float()` before charting.

```json
"[{\"time\": \"2026-03-01T00:00:00Z\", \"TEMPERATURE\": 21.4, \"HUMIDITY\": 48.2}, {\"time\": \"2026-03-01T00:15:00Z\", \"TEMPERATURE\": 21.3, \"HUMIDITY\": null}]"
```

Parse: `const rows = JSON.parse(data.device.history)` / `rows = json.loads(data["device"]["history"])`.

Resolution guide (aim for ≤ 500–2000 points per field):

| Range | Resolution | Points |
|---|---|---|
| last 1–6 h | `raw` or `1m`/`5m` | up to 360 |
| 24–48 h | `5m`/`15m` | 96–576 |
| 7 days | `1h` | 168 |
| 30 days | `6h`/`24h` (`24h` for bars) | 30–120 |
| 90 days | `24h` | 90 |
| 12 months | `24h`/`7d` | 52–365 |

For several devices, issue one `history` request per device (in parallel, throttled) rather than `devicesFiltered { devices { history } }`; the latter multiplies cost and cannot page safely.

## `historyNg` and `historyStats`

- `historyNg(start: DateTime!, end: DateTime!, resolution: String)` returns a `JSONString` object with two entries per active field: `"FIELD"` (bucket averages, numbers or numeric strings, `null` for empty buckets) and `"FIELD-LOCF"` (forward-filled numbers); each is a map of ISO timestamp → value (`{ "2026-09-01T12:00:00.000Z": "19.000000", … }`); fields without data are `null`. The resolution argument is only a hint (the server chose ~17 buckets regardless in tests). Use it for an all-fields overview; use `history` for charts.
- `historyStats(start: DateTime, end: DateTime)` returns a `JSONString` object keyed by identifier: `{ "TEMPERATURE": { "min": 19.0, "min_time": "2026-09-02T16:00:00+00:00", "max": 30.0, "max_time": "…", "last_value": 30.0, "last_time": "…", "avg": "22.800000" }, … }` (`avg` arrives as a string; all values `null` when the field has no data in the window). One call replaces many `average/minimum/maximum` aliases when you need all fields.

## Consumption, meters and counters

Energy, water, gas and heat meters, people counters and production counters store **cumulative** readings. Consumption for a period is the difference between the readings at its start and end:

```
2026-03-01 00:00  31 000.0 kWh
2026-03-02 00:00  31 092.3 kWh   → consumption on 1 March = 92.3 kWh
```

Use `change()` for period KPIs (one round trip, server-side):

```graphql
query Consumption(
  $deviceId: String!
  $todayStart: DateTime!, $tomorrowStart: DateTime!
  $yesterdayStart: DateTime!
  $weekStart: DateTime!, $nextWeekStart: DateTime!
  $monthStart: DateTime!, $nextMonthStart: DateTime!
  $lastMonthStart: DateTime!
) {
  device(deviceId: $deviceId) {
    verboseName
    lastHeard
    meter: currentMeasurement(fieldName: "ACTIVE_ENERGY_IMPORT_KWH") {
      reading: value
      readingTime: modified
      today: change(timeRangeStart: $todayStart, timeRangeEnd: $tomorrowStart)
      yesterday: change(timeRangeStart: $yesterdayStart, timeRangeEnd: $todayStart)
      thisWeek: change(timeRangeStart: $weekStart, timeRangeEnd: $nextWeekStart)
      thisMonth: change(timeRangeStart: $monthStart, timeRangeEnd: $nextMonthStart)
      lastMonth: change(timeRangeStart: $lastMonthStart, timeRangeEnd: $monthStart)
    }
  }
}
```

Rules:
- Boundaries are local midnight converted to UTC; end = start of the next period (exclusive). Never `23:59:59`.
- "Today" and "this month" windows may end in the future; `change` handles that (uses the latest reading).
- Consumption profiles (bar charts per hour/day/week): fetch `history(fields: ["METER"], resolution: "1h" | "24h" | "7d", locf: true)` and compute successive differences; clamp negative deltas to 0 or flag them (counter reset or device replacement). Daily buckets are UTC days; for local calendar days sum `1h` deltas per local day or issue one `change()` per day.
- Keep `change()` KPI queries and `history()` chart queries in separate requests; the first answers in ~100 ms, the second may take seconds.
- Peak/off-peak, business hours: use `change` with sub-day windows (e.g. 08:00–20:00 local).
- Comparisons: same window last year, yesterday vs today; percent change = (current − previous) / previous.
- `COUNTER` fields: `valueCounterAbs` is the absolute reading; `value` may hold the increment. Semantics `ENERGY_CONSUMPTION` and `WATER_CONSUMPTION` mark meter fields for cross-device totals (`aggregatedNumericSemanticValue(semantic: ENERGY_CONSUMPTION, aggregation: SUM)` gives the sum of current readings, not consumption).
- For fleets of meters, the Energy Report (Excel, per-device open/close/consumption per bucket) or an Export may be cheaper than hundreds of API calls.

## Local time boundaries

JavaScript (`date-fns-tz`):

```javascript
import { fromZonedTime, toZonedTime } from "date-fns-tz";
import { startOfDay, startOfMonth, startOfWeek, addDays, addMonths, addWeeks } from "date-fns";

export function periodUtc(kind, tz = "Europe/Berlin", now = new Date()) {
  const local = toZonedTime(now, tz);
  const startLocal = kind === "day" ? startOfDay(local)
    : kind === "week" ? startOfWeek(local, { weekStartsOn: 1 })
    : startOfMonth(local);
  const endLocal = kind === "day" ? addDays(startLocal, 1)
    : kind === "week" ? addWeeks(startLocal, 1)
    : addMonths(startLocal, 1);
  return { start: fromZonedTime(startLocal, tz).toISOString(), end: fromZonedTime(endLocal, tz).toISOString() };
}
```

Python 3.9+:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def day_window_utc(day, tz="Europe/Berlin"):
    z = ZoneInfo(tz)
    start = datetime(day.year, day.month, day.day, tzinfo=z)
    end = start + timedelta(days=1)          # DST-safe: arithmetic in local time
    return start.astimezone(ZoneInfo("UTC")).isoformat(), end.astimezone(ZoneInfo("UTC")).isoformat()
```

Or delegate to the API: `parseDate(date: "2026-03-11 00:00", timezone: "Europe/Berlin")`.

## Strings, booleans and locations

- `STRING` fields: read `valueString`; `value` is `0.0` (meaningless). History returns them as strings.
- `BOOL` fields: `value` is `1`/`0` and `valueString` is empty; prefer boolean semantics for fleet-wide state counts. `valueCounterAbs` is `0.0` for non-counter fields.
- `GEO` fields: `valueString` `"(lat,lng)"`; parsed coordinates also come from `device.currentLocation { lat lng }` when the field has the `DEVICE_LOCATION` role. History of a geo field yields a track.
- Formula fields behave like normal fields (values are computed at ingest).

## Performance rules

- Identifiers hardcoded per product; no field discovery per request.
- KPIs via `change/average/minimum/maximum/sum` or semantics, not via history downloads.
- One `history` request per device; resolution from the table; never `raw` beyond a couple of days.
- Cache current values for 30–60 s in dashboards; history per (device, range, resolution).
- Datapoint retention limits what `history` can return (7 days on free devices); check `device.plan(workspace:)`.
