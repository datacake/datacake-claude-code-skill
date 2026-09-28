# Measurements, history and consumption

## Contents

- Current values
- Time-range statistics on one field
- Historical data (`history`): arguments, resolution, limits, bucket grid, aggregation, response
- `historyStats`
- Consumption, meters and counters (`change()` vs. `LAST` readings, energy overview over many meters)
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
- `change` = last reading **inside** the window minus the first reading inside the window (verified against raw data). Consumption between the previous window's last reading and this window's first reading belongs to neither window, so per-day `change()` values do not add up to the month; see "Consumption" for the `LAST`-reading alternative.
- `value(timeRangeStart:, timeRangeEnd:)` returned the latest reading in tests; do not rely on the range arguments for "value as of". For the reading as of a time T use `history(timerangeend: T, resolution: "1d", aggregation: LAST)` over a window that ends at T and take the last non-null row.
- These are cheap (~100 ms) and ideal for KPI cards ("today", "yesterday", "this month"); batch several windows with aliases. Use `historyStats` when you want all fields at once.

## Historical data (`history`)

`history` is the only API for time series. `historyNg` in the schema is an internal fork API: never use it.

```graphql
query History($deviceId: String!, $from: String!, $to: String!, $resolution: String!) {
  device(deviceId: $deviceId) {
    history(
      fields: ["TEMPERATURE", "HUMIDITY"]
      timerangestart: $from
      timerangeend: $to
      resolution: $resolution
      aggregation: AVG
    )
  }
}
```

Variables: `{"deviceId": "…", "from": "2026-03-01T00:00:00Z", "to": "2026-03-02T00:00:00Z", "resolution": "15m"}`.

Arguments:

| Argument | Notes |
|---|---|
| `fields` | identifiers; when omitted, every field that has data in the range (heavier); unknown identifiers are dropped silently |
| `timerangestart`, `timerangeend` | required (`String!`), ISO 8601, UTC unless an offset is given (`+02:00` is honoured); end must be after start; an end in the future is accepted, buckets after the current time are simply not returned |
| `resolution` | omitted, `"raw"` or `""` = raw datapoints (default); otherwise a bucket size `<number><unit>` with unit `s`, `m`, `h`, `d` or `w`: `"30s"`, `"5m"`, `"15m"`, `"1h"`, `"6h"`, `"1d"` (= `"24h"`), `"7d"`, `"1w"`. Write units in lowercase: `M` is not minutes. An invalid value does **not** return an error, it silently falls back to `30m` (verified: `"1M"`, `"30 minutes"`, `"1mo"`, `"0m"`, even `"RAW"` in capitals) |
| `aggregation` | `DeviceHistoryAggregation`: `AVG` (default), `MIN`, `MAX`, `SUM`, `FIRST`, `LAST`; how the readings inside one bucket become one value (table below). Enum literal (`aggregation: LAST`) or a variable of type `DeviceHistoryAggregation`; ignored for raw data; unknown values are rejected (HTTP 400) |
| `locf` | default **`true`**: empty buckets carry the last value forward (after the first datapoint inside the window; buckets before it stay `null`, there is no look-back before `timerangestart`). Pass `locf: false` to see gaps as `null` (data-availability charts, "no reading in this hour") |
| `nodatathreshold` | deprecated, hidden from introspection, no effect; leave unset |

### Limits

- Raw data returns at most the **most recent 31 days** of the requested range (a 90-day raw request returns only the last 31 days, without a warning). Split longer raw downloads into ≤ 31-day windows or use an Export.
- Bucketed data returns at most **1024 buckets**. A finer resolution is coarsened automatically to `ceil(range / 1024)` rounded up to a whole minute (verified: 7 d at `1m` → 10-minute buckets, 30 d at `1m` → 43-minute buckets, 365 d at `1h` → 8 h 34 min buckets). Coarsened buckets sit on their own odd grid (43-minute buckets starting at 23:47) and no longer line up with hours or days, so never let a request exceed 1024 buckets when the bucket boundaries matter: split the range instead (limits per resolution in the guide below).
- Every range is limited to the data retention of the device's plan (7 days on free devices; check `device.plan(workspace:)`).

### Bucket grid

Buckets sit on a fixed UTC grid anchored at Monday 2000-01-03 00:00 UTC, not on `timerangestart`: `1h` at full UTC hours, `6h` at 00/06/12/18 UTC, `1d` at 00:00 UTC, `1w`/`7d` on Mondays 00:00 UTC. Only datapoints inside the window are bucketed, so the first and the last bucket can be partial and the first bucket's `time` can lie before the requested start: `2026-09-23T22:00Z → 2026-09-27T22:00Z` at `1d` returns five buckets, the first labelled `2026-09-23T00:00:00Z` containing only 22:00–24:00 UTC. For local calendar days in other time zones see "Consumption" below.

### Aggregation

| `aggregation` | Numeric fields | Boolean fields | String and geo fields |
|---|---|---|---|
| `AVG` (default) | average | `true` if most readings were `true` | `null` |
| `MIN` | minimum | `true` only if all readings were `true` | `null` |
| `MAX` | maximum | `true` if any reading was `true` | `null` |
| `SUM` | sum | number of `true` readings (integer) | `null` |
| `FIRST` | first reading in the bucket | first reading | first reading |
| `LAST` | last reading in the bucket | last reading | last reading |

All six were checked against raw data (energy meter, motion sensor, GPS tracker): `FIRST`/`LAST` return the exact first/last stored reading of each bucket, `SUM` on a boolean counts `true` readings (uplinks), not false→true transitions. Typical uses: `LAST` for meter readings at the end of each day/week (consumption, see below), `FIRST` + `LAST` for open/close readings per period, `MAX` of a boolean for "was the door open at all this hour", `SUM` of a boolean for "readings with motion", `MIN`/`MAX` of numeric fields for min/max bands in charts, `LAST` for the latest status string or position per bucket.

### Response

A **JSON string** of an array ordered by time, one row per bucket (or per stored datapoint for raw data) with a `time` key in UTC (`…Z`) plus one key per field:

```json
"[{\"time\": \"2026-03-01T00:00:00Z\", \"TEMPERATURE\": 21.4, \"HUMIDITY\": 48.2}, {\"time\": \"2026-03-01T00:15:00Z\", \"TEMPERATURE\": 21.3, \"HUMIDITY\": null}]"
```

- A field that has no data in the whole range is **left out** of every row (key missing, not `null`); if no requested field has data the result is `"[]"`. A field without a value in one bucket is `null`.
- Numeric fields come as JSON numbers, boolean fields as `true`/`false` (integers under `SUM`), string fields as strings, geo fields as `"(lat,lng)"` strings. Earlier API versions returned averages as numeric strings (`"19.000000"`); keep coercing with `Number()` / `float()`, it costs nothing.

Parse: `const rows = JSON.parse(data.device.history)` / `rows = json.loads(data["device"]["history"])`.

Resolution guide (aim for ≤ 500–1000 points per field; never more than 1024 buckets):

| Range | Resolution | Points | Longest range at this resolution (1024 buckets) |
|---|---|---|---|
| last 1–6 h | `raw` or `30s`/`1m`/`5m` | up to 720 | `30s`: 8.5 h, `1m`: 17 h |
| 24–48 h | `5m`/`15m` | 96–576 | `5m`: 3.5 d, `15m`: 10.6 d |
| 7 days | `1h` | 168 | `1h`: 42 d |
| 30 days | `6h`/`1d` (`1d` for bars) | 30–120 | `6h`: 256 d |
| 90 days | `1d` | 90 | `1d`: 2.8 years |
| 12 months | `1d`/`1w` | 52–365 | `1w`: 19 years |

For several devices, issue one `history` request per device (in parallel, throttled) or batch a handful of devices with aliases in one document (`m1: device(deviceId: "…") { history(…) } m2: device(…) { … }`; two meters × 8 days took 0.8 s). Do not use `devicesFiltered { devices { history } }`: it multiplies cost and cannot page safely.

## `historyStats`

`historyStats(start: DateTime, end: DateTime)` returns a `JSONString` object keyed by identifier: `{ "TEMPERATURE": { "min": 19.0, "min_time": "2026-09-02T16:00:00+00:00", "max": 30.0, "max_time": "…", "last_value": 30.0, "last_time": "…", "avg": "22.800000" }, … }` (`avg` arrives as a string; all values `null` when the field has no data in the window). One call replaces many `average/minimum/maximum` aliases when you need all fields.

## Consumption, meters and counters

Energy, water, gas and heat meters, people counters and production counters store **cumulative** readings. Consumption for a period is the difference between the readings at its start and end:

```
2026-03-01 00:00  31 000.0 kWh
2026-03-02 00:00  31 092.3 kWh   → consumption on 1 March = 92.3 kWh
```

| Need | Use |
|---|---|
| KPI numbers for one meter: today, yesterday, this month | `change()` windows (one round trip, ~100 ms) |
| Consumption per day/week over a range, energy overview across several meters, totals that must add up | `history(resolution: "1d", aggregation: LAST)` per meter = reading at the end of each bucket; consumption = difference of successive readings |
| Open and close reading per period (like the Energy Report) | `FIRST` and `LAST` with the same resolution |

Why `LAST` differences for series: `change()` only sees readings inside its window (last minus first), so the consumption between the last reading of one day and the first reading of the next day is lost, and daily `change()` values do not sum to the monthly value. Measured on a meter with 15-minute uplinks: one UTC day gave 28.263 kWh via `change()` and 28.415 kWh via `LAST` differences. Differences of successive `LAST` readings telescope: their sum is exactly reading(end) − reading(start). This also replaces the old workarounds (one `change()` alias per day and meter, or downloading raw data over long ranges).

### KPI cards with `change()`

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

### Readings per day with `LAST` (several meters in one request)

```graphql
query DailyReadings($from: String!, $to: String!) {
  main: device(deviceId: "<main-meter-uuid>") {
    history(fields: ["ACTIVE_ENERGY_IMPORT_KWH"], timerangestart: $from, timerangeend: $to, resolution: "1d", aggregation: LAST)
  }
  heatPump: device(deviceId: "<heat-pump-meter-uuid>") {
    history(fields: ["ACTIVE_ENERGY_TOTAL_KWH"], timerangestart: $from, timerangeend: $to, resolution: "1d", aggregation: LAST)
  }
}
```

Variables `{"from": "2026-08-31T00:00:00Z", "to": "2026-10-01T00:00:00Z"}` for September: start **one period early**, because the first day's consumption needs the reading at the end of the day before. Each row's value is the meter reading at the end of that UTC day; `consumption[d] = reading[d] − reading[d − 1]`. For a site total, compute the deltas per meter first and then sum per day (a meter with a gap then only misses its own delta). Python version with local days: `analytics-recipes.md` ("Energy overview across meters").

### Local calendar days, weeks and months

- `1d` buckets are UTC days. For local days use `resolution: "1h"` with `aggregation: LAST` and pick, for every local midnight, the bucket that starts one hour before it (Europe/Berlin: `21:00Z` in summer, `22:00Z` in winter; convert with `zoneinfo`/`date-fns-tz`, DST handled). That bucket's value is the reading at the end of the local day. At `1h` one request covers at most 42 days (1024 buckets); split longer ranges at local midnights. Time zones with half-hour offsets need `30m` (≤ 21 days per request).
- Alternative: one request per local day window (local midnight → next local midnight) with `resolution: "1d"`; the window spans two UTC-day buckets, the last non-null row is the reading at the end of the local day.
- Weeks: `1w` buckets start on Monday 00:00 UTC; for local weeks sum the local daily deltas.
- Months: there is no month unit; sum the daily deltas per month, or take the reading as of each local month end (window ending at local midnight, last non-null row).

Rules:
- Boundaries are local midnight converted to UTC; end = start of the next period (exclusive). Never `23:59:59`.
- "Today" and "this month" windows may end in the future; `change` handles that (uses the latest reading), `history` returns no buckets after the current time.
- `locf` is on by default: a day without uplinks carries the previous reading (delta 0) and the next reading gets the whole amount. Pass `locf: false` when a missing day must show up as `null`.
- Clamp negative deltas to `null` and flag them (counter reset or device replacement); never let them reduce a site total.
- Keep `change()` KPI queries and `history()` series queries in separate requests; the first answers in ~100 ms, the second may take seconds.
- Hourly load profile: `resolution: "1h"`, `aggregation: LAST`, successive differences (≤ 42 days per request). For power fields (W, kW) use `AVG` per bucket instead, and `MAX` for peak demand.
- Peak/off-peak, business hours: `change` with sub-day windows (e.g. 08:00–20:00 local) or sums of hourly `LAST` deltas over those hours.
- Comparisons: same window last year, yesterday vs today; percent change = (current − previous) / previous.
- `COUNTER` fields: `valueCounterAbs` is the absolute reading; `value` may hold the increment. Semantics `ENERGY_CONSUMPTION` and `WATER_CONSUMPTION` mark meter fields for cross-device totals (`aggregatedNumericSemanticValue(semantic: ENERGY_CONSUMPTION, aggregation: SUM)` gives the sum of current readings, not consumption).
- Fields that store per-uplink increments (pulses per interval) instead of a cumulative reading: use `aggregation: SUM` per bucket, no differences.
- For hundreds of meters, the Energy Report (Excel, per-device open/close/consumption per bucket) or an Export may still be cheaper than one request per meter.

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

- `STRING` fields: read `valueString`; `value` is `0.0` (meaningless). History returns them as strings; with a resolution they only have a value under `aggregation: FIRST` or `LAST` (`null` under `AVG`, the default).
- `BOOL` fields: `value` is `1`/`0` and `valueString` is empty; prefer boolean semantics for fleet-wide state counts. `valueCounterAbs` is `0.0` for non-counter fields. History returns `true`/`false`; per bucket `MAX` = "any true", `MIN` = "all true", `SUM` = number of `true` readings.
- `GEO` fields: `valueString` `"(lat,lng)"`; parsed coordinates also come from `device.currentLocation { lat lng }` when the field has the `DEVICE_LOCATION` role. History of a geo field yields a track (raw, or one position per bucket with `aggregation: LAST`).
- Formula fields behave like normal fields (values are computed at ingest).

## Performance rules

- Identifiers hardcoded per product; no field discovery per request.
- KPIs via `change/average/minimum/maximum/sum` or semantics, not via history downloads.
- Period series (daily readings, open/close, min/max bands) via `resolution` + `aggregation`, not raw downloads aggregated in the client.
- One `history` request per device (or a few devices batched with aliases); resolution from the table; at most 1024 buckets per request; `raw` only for short ranges (capped at the most recent 31 days anyway).
- Cache current values for 30–60 s in dashboards; history per (device, range, resolution, aggregation).
- Datapoint retention limits what `history` can return (7 days on free devices); check `device.plan(workspace:)`.
