# Analytics and scripting recipes

## Contents

- Setup for scripts
- No token yet
- Recipe: inventory of a workspace
- Recipe: bulk history for many devices
- Recipe: consumption analysis for meters
- Recipe: energy overview across meters (daily `LAST` readings)
- Recipe: fleet health report
- Recipe: period comparisons
- Recipe: pandas analysis
- Recipe: bulk export instead of API loops
- Batching, retries and rate limits
- Node.js variant

## Setup for scripts

- Token in `DATACAKE_TOKEN` (or `~/.datacake/token`). Identify targets with `python3 scripts/discover.py <workspace>`.
- `scripts/dc.py` runs ad-hoc queries; `scripts/history_to_csv.py` dumps history to CSV; both are dependency-free Python 3.
- In your own scripts, reuse the `gql()` helper pattern from `api-basics.md` (stdlib) or `pip install requests`.

## No token yet

Do not stop. Draft the queries against `reference/schema.graphql`, keep identifiers as clearly marked placeholders, and give the user the exact commands to run on their side:

```bash
export DATACAKE_TOKEN=...                      # read-only API user preferred
python3 scripts/discover.py                    # find the workspace id/slug
python3 scripts/discover.py <workspace> --json > inventory.json
```

Ask them to paste the relevant part of the output (products with field identifiers, semantics, tags) or run the script themselves; then finish the analysis with real identifiers. For fleet-wide questions (counts, averages, offline devices) semantics work without knowing any identifier, so those queries can be final immediately.

## Recipe: inventory of a workspace

```bash
python3 scripts/discover.py                         # workspaces the token can see
python3 scripts/discover.py <workspace-id> --devices 50 --json > inventory.json
python3 scripts/dc.py --data-only 'query { workspace(id: "<id>") { allTags semantics deviceCount } }'
```

All devices with product and identifiers (paged):

```graphql
query Inventory($workspaceId: String!, $page: Int!) {
  workspace(id: $workspaceId) {
    devicesFiltered(page: $page, pageSize: 100, orderBy: { verboseName: ASC }) {
      total
      devices { id verboseName serialNumber online lastHeard tags product { id name } }
    }
  }
}
```

Loop `page` until `page * 100 >= total`.

## Recipe: bulk history for many devices

```bash
# one CSV, all devices tagged "meter", meter reading at the end of every hour, local time in Berlin
python3 scripts/history_to_csv.py --workspace <id> --tag meter \
  --fields ACTIVE_ENERGY_IMPORT_KWH --start 2026-02-01 --end 2026-03-01 \
  --resolution 1h --aggregation LAST --tz Europe/Berlin --out meters-feb.csv

# power as hourly averages and peaks
python3 scripts/history_to_csv.py --workspace <id> --tag meter --fields POWER \
  --start 2026-02-01 --end 2026-03-01 --resolution 1h --aggregation MAX --out peaks-feb.csv
```

The script splits every range into requests the API answers completely (≤ 30 days for `raw`, ≤ 1000 buckets otherwise, split on the bucket grid so no bucket is cut in two), carries `locf` values across those splits, and rejects resolutions the API would silently replace by `30m`. `locf` is on by default (as in the API); `--no-locf` leaves empty buckets empty.

Pattern in your own code: resolve devices (paged `devicesFiltered` or `allDevices(searchTags:)`), then one `history` request per device, sequentially or with a small pool (3–5 concurrent), resolution from the table in `queries-measurements.md`, parse the JSON string, append rows with `device_id`. Keep each request within the API limits (raw: most recent 31 days of the range only; bucketed: 1024 buckets, beyond that the buckets are coarsened to odd sizes). Respect retention: free devices hold 7 days.

## Recipe: consumption analysis for meters

Period consumption straight from the API (no download):

```graphql
query MeterKpis($deviceId: String!, $dayStart: DateTime!, $dayEnd: DateTime!, $monthStart: DateTime!, $monthEnd: DateTime!) {
  device(deviceId: $deviceId) {
    verboseName
    meter: currentMeasurement(fieldName: "ACTIVE_ENERGY_IMPORT_KWH") {
      reading: value
      day: change(timeRangeStart: $dayStart, timeRangeEnd: $dayEnd)
      month: change(timeRangeStart: $monthStart, timeRangeEnd: $monthEnd)
    }
  }
}
```

`change()` is fine for single KPI numbers. For series (per day, per week) and for totals across days or meters use end-of-period readings with `aggregation: LAST` (next recipe): `change()` misses the consumption between the last reading of one window and the first of the next (≈ 0.9 % per day on a meter with 15-minute uplinks), `LAST` differences add up exactly.

## Recipe: energy overview across meters (daily `LAST` readings)

Meter reading at the end of every local day from hourly `LAST` buckets, daily consumption per meter, site total per day (reuses `datacake()` from `api-basics.md`; verified live with two meters: the sum of daily deltas equals the difference of the end readings to the Wh):

```python
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

HISTORY = """query($id: String!, $f: [String], $s: String!, $e: String!) {
  device(deviceId: $id) { history(fields: $f, timerangestart: $s, timerangeend: $e, resolution: "1h", aggregation: LAST) } }"""


def local_midnight_utc(day, tz):
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


def day_end_readings(device_id, field, first_day, last_day, tz):
    """Meter reading at the end of every local day from first_day - 1 to last_day (at most ~40 days per call)."""
    start = local_midnight_utc(first_day - timedelta(days=1), tz)
    end = local_midnight_utc(last_day + timedelta(days=1), tz)
    data = datacake(HISTORY, {"id": device_id, "f": [field], "s": start.isoformat(), "e": end.isoformat()})
    hourly = {r["time"]: r.get(field) for r in json.loads(data["device"]["history"])}
    readings, day = {}, first_day - timedelta(days=1)
    while day <= last_day:
        last_hour = local_midnight_utc(day + timedelta(days=1), tz) - timedelta(hours=1)   # bucket before local midnight
        readings[day] = hourly.get(last_hour.strftime("%Y-%m-%dT%H:%M:%SZ"))
        day += timedelta(days=1)
    return readings


def daily_consumption(readings):
    days = sorted(readings)
    return {cur: readings[cur] - readings[prev]
            if readings[prev] is not None and readings[cur] is not None and readings[cur] >= readings[prev] else None
            for prev, cur in zip(days, days[1:])}          # None: gap or counter reset


tz = ZoneInfo("Europe/Berlin")
meters = [("<meter-uuid-1>", "ACTIVE_ENERGY_IMPORT_KWH"), ("<meter-uuid-2>", "ACTIVE_ENERGY_TOTAL_KWH")]
site = {}
for device_id, field in meters:
    for day, kwh in daily_consumption(day_end_readings(device_id, field, date(2026, 9, 1), date(2026, 9, 30), tz)).items():
        if kwh is not None:
            site[day] = site.get(day, 0.0) + kwh
for day in sorted(site):
    print(day, round(site[day], 3))
```

Notes:
- Hourly buckets make local days exact (the bucket before local midnight holds the day-end reading) but cap one request at 42 days; loop month by month for longer ranges. With UTC days, `resolution: "1d"` covers up to 1024 days per request and the lookup is simply row by row.
- Many meters: batch 5–10 devices per document with aliases (`m1: device(deviceId: …) { history(…) }`), 3–5 documents in parallel; units differ per product (Wh vs kWh), normalise before summing.
- Weekly or monthly totals: sum the daily values per local week or month; do not mix in `change()` values.
- Counter reset or meter swap shows up as a negative delta (`None` above); report it instead of silently dropping it.
- For monthly Excel output without code, the Energy Report or an Export (below) still work.

## Recipe: fleet health report

```graphql
query Health($workspaceId: String!, $silentSince: DateTime!) {
  workspace(id: $workspaceId) {
    all: devicesFiltered(all: true) { total }
    offline: devicesFiltered(online: false, pageSize: 50, orderBy: { lastHeard: ASC }) {
      total
      devices { id verboseName lastHeard tags product { name } }
    }
    silent: devicesFiltered(lastHeard: { lt: $silentSince }) { total }
    lowBattery: devicesFiltered(battery: { lt: 20, aggregation: MIN }, pageSize: 50) {
      total
      devices { id verboseName battery: numericSemanticField(semantic: BATTERY) { value } }
    }
    weakSignal: devicesFiltered(signal: { lt: -115 }) { total }
    batteryLowFlag: devicesFiltered(batteryLow: { exact: true }) { total }
  }
}
```

Add `measurements24h` and `isOverQuota` per device to spot chatty or throttled devices. Schedule the script (cron, GitHub Actions) and diff against the previous run to produce "newly offline" lists.

## Recipe: period comparisons

- Same window, previous period: compute both windows in local time, query `average`/`minimum`/`maximum`/`change` for each with aliases (`thisWeek`, `lastWeek`).
- Year over year: `change(2025-03-01 → 2025-04-01)` vs `change(2026-03-01 → 2026-04-01)` (only if retention covers it: 12 months on paid plans).
- Percent change = (current − previous) / previous; guard division by zero.
- Across a fleet: `aggregatedNumericSemanticValue` gives the current snapshot only; for period statistics per device loop `currentMeasurement(...).average(...)`.

## Recipe: pandas analysis

```python
import pandas as pd
# meters-feb.csv from history_to_csv.py --resolution 1h --aggregation LAST --tz Europe/Berlin
df = pd.read_csv("meters-feb.csv")
df["time_local"] = pd.to_datetime(df["time_local"], utc=True).dt.tz_convert("Europe/Berlin")
readings = (df.set_index("time_local").groupby("device_name")["ACTIVE_ENERGY_IMPORT_KWH"]
              .resample("1D").last())                        # reading at the end of each local day
daily = readings.groupby(level=0).diff()                    # consumption per local day
daily[daily < 0] = float("nan")                             # counter resets
print(daily.unstack(0).describe())
```

`history_to_csv.py` writes one row per bucket per device with `time_utc`, `time_local`, `device_id`, `device_name` and one column per field, so it feeds `pivot`/`resample` directly. Start the export one day before the first day you need, so the first day gets a delta.

## Recipe: bulk export instead of API loops

For weeks or months of raw data across many devices, create an export and download the artifact:

```graphql
mutation Export($workspaceId: UUID!, $from: DateTime!, $until: DateTime!) {
  createManualExport(input: {
    workspaceId: $workspaceId
    name: "february-raw"
    timezone: "Europe/Berlin"
    deviceFilterTags: ["meter"]
    deviceFilterTagsConjunction: AND
    exportFieldSelection: SEMANTICS
    exportSemantics: [ENERGY_CONSUMPTION, POWER]
    exportFormat: CSV
    csvDateFormat: ISO_8601
    exportFrom: $from
    exportUntil: $until
  }) {
    ok
    errors
    exportRun { id state }
  }
}
```

Then poll `exportRun(id:) { state artifacts { filename downloadUrl } expiresAt }` until `COMPLETED`. Requires the `exports` permission and a plan with manual exports (`workspace.entitlementExportsManualEnabled`, `entitlementExportsManualMaxDays`).

## Batching, retries and rate limits

- Combine independent small queries with aliases into one document; keep history calls in their own documents (a handful of devices per document at most).
- Concurrency 3–5 for history; back off exponentially on 5xx/429/timeouts (1 s, 2 s, 4 s); the REST write limit is 1 per second per field.
- Cache identifiers and device lists locally; only measurements change.
- Log `extensions.code` for failed requests; `NOT_AUTHORIZED` on a device means the API user lacks that device.

## Node.js variant

```javascript
// node >= 18, no dependencies: node fleet.mjs <workspaceId>
const token = process.env.DATACAKE_TOKEN;
const gql = async (query, variables) => {
  const r = await fetch("https://api.datacake.co/graphql/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Token ${token}` },
    body: JSON.stringify({ query, variables }),
  });
  const j = await r.json();
  if (j.errors) throw new Error(JSON.stringify(j.errors));
  return j.data;
};
const data = await gql(`query($w: String!) { workspace(id: $w) { offline: devicesFiltered(online: false) { total } } }`,
  { w: process.argv[2] });
console.log(data.workspace.offline.total, "devices offline");
```
