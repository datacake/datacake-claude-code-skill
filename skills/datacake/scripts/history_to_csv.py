#!/usr/bin/env python3
"""Download historical measurements from Datacake into one CSV.

Usage:
  python3 scripts/history_to_csv.py --device <uuid> --fields TEMPERATURE,HUMIDITY \
      --start 2026-03-01 --end 2026-03-08 --resolution 1h --tz Europe/Berlin --out temp.csv
  python3 scripts/history_to_csv.py --workspace <uuid|slug> --tag meter --tag building-a \
      --fields ACTIVE_ENERGY_IMPORT_KWH --start 2026-02-01 --end 2026-03-01 --resolution 1d --aggregation LAST

Devices: repeat --device, or select by --workspace plus --tag (all tags must match; --any-tag for any).
Times: ISO dates or datetimes; naive values are interpreted in --tz (default UTC), end is exclusive.
Resolution: "raw" or <number><s|m|h|d|w> in lowercase, e.g. "30s", "5m", "15m", "1h", "1d", "1w"
  (the API silently replaces anything else by 30m, so the script rejects it).
Aggregation per bucket: AVG (API default), MIN, MAX, SUM, FIRST, LAST; LAST gives meter readings at the
  end of each bucket, FIRST the opening reading. Ignored for raw data.
LOCF: on by default (as in the API); --no-locf leaves empty buckets empty.
Long ranges are split into requests the API answers completely (raw: 30 days, bucketed: 1000 buckets,
  split on the bucket grid), and LOCF values are carried across the splits.
Output columns: time_utc, time_local, device_id, device_name, <one column per field>.
Token: $DATACAKE_TOKEN or ~/.datacake/token. Standard library only (Python 3.9+).
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ENDPOINT = "https://api.datacake.co/graphql/"
TIMEOUT = 120          # long ranges at fine resolution can take a while
PAUSE_BETWEEN_DEVICES = 0.2   # be gentle with the API when looping over many devices
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
RESOLUTION_RE = re.compile(r"^(\d+)([smhdw])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
AGGREGATIONS = ("AVG", "MIN", "MAX", "SUM", "FIRST", "LAST")
# API limits: raw returns only the most recent 31 days of a range, bucketed data at most 1024 buckets
# (beyond that the buckets are coarsened to odd sizes). Stay below both with some margin.
RAW_WINDOW = timedelta(days=30)
MAX_BUCKETS = 1000
# Buckets sit on a fixed UTC grid anchored at Monday 2000-01-03 (verified for 1h, 1d, 2d, 1w and odd sizes).
GRID_ORIGIN = datetime(2000, 1, 3, tzinfo=timezone.utc)

DEVICES_QUERY = """
query Devices($id: String, $slug: String, $tags: FilteredDeviceListTagsFilterInput, $page: Int!) {
  workspace(id: $id, slug: $slug) {
    devicesFiltered(page: $page, pageSize: 100, tags: $tags, orderBy: { verboseName: ASC }) {
      total
      devices { id verboseName }
    }
  }
}
"""

HISTORY_QUERY = """
query History($deviceId: String!, $fields: [String], $start: String!, $end: String!, $resolution: String!,
              $locf: Boolean = true, $aggregation: DeviceHistoryAggregation = AVG) {
  device(deviceId: $deviceId) {
    id
    verboseName
    history(fields: $fields, timerangestart: $start, timerangeend: $end, resolution: $resolution,
            locf: $locf, aggregation: $aggregation)
  }
}
"""


def token():
    if os.environ.get("DATACAKE_TOKEN"):
        return os.environ["DATACAKE_TOKEN"]
    path = os.path.expanduser("~/.datacake/token")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip()
    sys.exit("no token: export DATACAKE_TOKEN=<token>")


def gql(query, variables, tok):
    req = urllib.request.Request(ENDPOINT, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Token " + tok,
                                          "User-Agent": "datacake-skill/history_to_csv.py"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"), strict=False)
            break
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == 2:
                sys.exit("HTTP %s: %s%s" % (exc.code, exc.read().decode("utf-8", "replace")[:500],
                                            " (token rejected: invalid or revoked)" if exc.code == 401 else ""))
        except (urllib.error.URLError, OSError) as exc:
            if attempt == 2:
                sys.exit("network error: %s" % exc)
        time.sleep(2 ** attempt)
    if data.get("errors"):
        for err in data["errors"]:
            sys.stderr.write("GraphQL error %s: %s\n" % ((err.get("extensions") or {}).get("code", ""), err.get("message")))
        if not data.get("data"):
            sys.exit(1)
    return data["data"]


def parse_time(value, tz):
    """ISO date or datetime; naive values are local to tz. Returns an aware UTC datetime."""
    text = value.strip().replace("Z", "+00:00")
    if len(text) == 10:
        text += "T00:00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        sys.exit("cannot parse time %r (use ISO 8601, e.g. 2026-03-01 or 2026-03-01T06:00:00+01:00)" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def bucket_size(resolution):
    """timedelta of one bucket, None for raw; exits on values the API would silently replace by 30m."""
    if resolution == "raw":
        return None
    m = RESOLUTION_RE.match(resolution)
    if not m or int(m.group(1)) == 0:
        sys.exit("invalid --resolution %r: use raw or <number><s|m|h|d|w> in lowercase, e.g. 15m, 1h, 1d, 1w" % resolution)
    return timedelta(seconds=int(m.group(1)) * UNIT_SECONDS[m.group(2)])


def windows(start, end, bucket):
    """Split [start, end) into requests within the API limits; bucketed splits fall on the bucket grid."""
    step = RAW_WINDOW if bucket is None else bucket * MAX_BUCKETS
    cur = start
    while cur < end:
        nxt = cur + step
        if bucket is not None:
            nxt = GRID_ORIGIN + ((nxt - GRID_ORIGIN) // bucket) * bucket
            if nxt <= cur:
                nxt = cur + bucket
        nxt = min(nxt, end)
        yield cur, nxt
        cur = nxt


def select_devices(args, tok):
    if args.device:
        return [{"id": d, "verboseName": None} for d in args.device]
    if not args.workspace:
        sys.exit("select devices with --device or --workspace [--tag ...]")
    variables = {"page": 0, "tags": None}
    variables["id" if UUID_RE.match(args.workspace) else "slug"] = args.workspace
    if args.tag:
        variables["tags"] = {"overlap": args.tag} if args.any_tag else {"contains": args.tag}
    devices = []
    while True:
        data = gql(DEVICES_QUERY, variables, tok)
        ws = data.get("workspace")
        if not ws:
            sys.exit("workspace not found or no access: %s" % args.workspace)
        chunk = ws["devicesFiltered"]
        devices.extend(chunk["devices"] or [])
        if len(devices) >= (chunk["total"] or 0) or not chunk["devices"]:
            break
        variables["page"] += 1
    return devices


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", action="append", help="device UUID (repeatable)")
    ap.add_argument("--workspace", help="workspace UUID or slug (with --tag to select devices)")
    ap.add_argument("--tag", action="append", help="tag filter (repeatable; all must match unless --any-tag)")
    ap.add_argument("--any-tag", action="store_true", help="match devices having any of the tags")
    ap.add_argument("--fields", required=True, help="comma-separated field identifiers, e.g. TEMPERATURE,HUMIDITY")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True, help="exclusive end")
    ap.add_argument("--resolution", default="1h", help="raw or <number><s|m|h|d|w>, e.g. 15m, 1h, 1d (default 1h)")
    ap.add_argument("--aggregation", type=str.upper, choices=AGGREGATIONS,
                    help="how readings inside a bucket are combined (API default AVG); LAST for meter readings")
    ap.add_argument("--tz", default="UTC", help="IANA zone for naive --start/--end and the time_local column")
    ap.add_argument("--locf", dest="locf", action="store_true", default=None,
                    help="carry the last value forward into empty buckets (API default, kept for compatibility)")
    ap.add_argument("--no-locf", dest="locf", action="store_false", help="leave empty buckets empty")
    ap.add_argument("--out", help="CSV path (default: stdout)")
    args = ap.parse_args()

    try:
        tz = ZoneInfo(args.tz)
    except Exception:
        sys.exit("unknown time zone %r" % args.tz)
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    start, end = parse_time(args.start, tz), parse_time(args.end, tz)
    if end <= start:
        sys.exit("--end must be after --start")
    bucket = bucket_size(args.resolution)
    if bucket is None and args.aggregation:
        sys.stderr.write("note: --aggregation is ignored for raw data\n")
    carry = bucket is not None and args.locf is not False
    chunks = list(windows(start, end, bucket))
    tok = token()
    devices = select_devices(args, tok)
    if not devices:
        sys.exit("no devices selected")
    sys.stderr.write("fetching %d field(s) for %d device(s), %s -> %s, resolution %s%s, %d request(s) per device\n" % (
        len(fields), len(devices), start.isoformat(), end.isoformat(), args.resolution,
        ", aggregation " + args.aggregation if args.aggregation and bucket else "", len(chunks)))

    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    writer = csv.writer(out)
    writer.writerow(["time_utc", "time_local", "device_id", "device_name"] + fields)
    rows_written = 0
    for i, dev in enumerate(devices):
        name, count, last_seen, found = dev["verboseName"], 0, {}, True
        for chunk_start, chunk_end in chunks:
            variables = {"deviceId": dev["id"], "fields": fields, "start": chunk_start.isoformat(),
                         "end": chunk_end.isoformat(), "resolution": args.resolution}
            if args.locf is not None:
                variables["locf"] = args.locf
            if args.aggregation:
                variables["aggregation"] = args.aggregation
            d = gql(HISTORY_QUERY, variables, tok).get("device")
            if not d:
                found = False
                break
            name = d["verboseName"]
            for row in json.loads(d["history"]) if d.get("history") else []:
                values = []
                for f in fields:
                    v = row.get(f)
                    if v is None and carry:
                        v = last_seen.get(f)       # the API carries values forward only within one request
                    elif v is not None:
                        last_seen[f] = v
                    values.append(v)
                t = datetime.fromisoformat(row["time"].replace("Z", "+00:00")).astimezone(timezone.utc)
                writer.writerow([t.isoformat(), t.astimezone(tz).isoformat(), dev["id"], name] + values)
                count += 1
        if not found:
            sys.stderr.write("skip %s: not found or no access\n" % dev["id"])
            continue
        rows_written += count
        sys.stderr.write("  %s (%s): %d rows\n" % (name, dev["id"], count))
        if i + 1 < len(devices):
            time.sleep(PAUSE_BETWEEN_DEVICES)
    if args.out:
        out.close()
    sys.stderr.write("wrote %d rows%s\n" % (rows_written, " to " + args.out if args.out else ""))


if __name__ == "__main__":
    main()
