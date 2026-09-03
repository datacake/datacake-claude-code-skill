# Analytics and scripting recipes

## Contents

- Setup for scripts
- Recipe: inventory of a workspace
- Recipe: bulk history for many devices
- Recipe: consumption analysis for meters
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
# one CSV, all devices tagged "meter", two fields, daily buckets, local time in Berlin
python3 scripts/history_to_csv.py --workspace <id> --tag meter \
  --fields ACTIVE_ENERGY_IMPORT_KWH,POWER --start 2026-02-01 --end 2026-03-01 \
  --resolution 24h --tz Europe/Berlin --locf --out meters-feb.csv
```

Pattern in code: resolve devices (paged `devicesFiltered` or `allDevices(searchTags:)`), then one `history` request per device, sequentially or with a small pool (3–5 concurrent), resolution from the table in `queries-measurements.md`, parse the JSON string, append rows with `device_id`. Split long ranges into monthly chunks to keep each response small. Respect retention: free devices hold 7 days.

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

Daily profile from history deltas (Python):

```python
import json
rows = json.loads(history_json)                      # from device.history(..., resolution="24h", locf=True)
prev = None
for row in rows:
    cur = row.get("ACTIVE_ENERGY_IMPORT_KWH")
    if prev is not None and cur is not None:
        delta = cur - prev
        print(row["time"], delta if delta >= 0 else None)   # None = counter reset / replacement
    prev = cur if cur is not None else prev
```

Notes: boundaries at local midnight converted to UTC (`zoneinfo`); use `locf: true` so empty days carry the last reading; for many meters prefer the Energy Report or an Export (below).

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
df = pd.read_csv("meters-feb.csv", parse_dates=["time_utc", "time_local"])
daily = (df.set_index("time_local").groupby("device_name")["ACTIVE_ENERGY_IMPORT_KWH"]
           .resample("1D").last().groupby(level=0).diff().clip(lower=0))
print(daily.unstack(0).describe())
```

`history_to_csv.py` writes one row per bucket per device with `time_utc`, `time_local`, `device_id`, `device_name` and one column per field, so it feeds `pivot`/`resample` directly.

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

- Combine independent small queries with aliases into one document; keep history calls separate.
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
