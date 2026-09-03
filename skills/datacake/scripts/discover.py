#!/usr/bin/env python3
"""Print a compact map of a Datacake workspace: products, field identifiers, tags,
semantics, permissions and sample devices. Use it before hardcoding field names.

Usage:
  python3 scripts/discover.py                         # list the workspaces the token can access
  python3 scripts/discover.py <workspace-id|slug>     # map one workspace
  python3 scripts/discover.py <workspace> --devices 20 --inactive --product "Sensor"
  python3 scripts/discover.py <workspace> --json      # machine-readable output

Token: $DATACAKE_TOKEN or ~/.datacake/token (or --token). Standard library only.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://api.datacake.co/graphql/"
TIMEOUT = 60
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

WORKSPACES_QUERY = """
query Workspaces { allWorkspaces { id name slug deviceCount memberCount myPermissions } }
"""

WORKSPACE_QUERY = """
query Discover($id: String, $slug: String, $pageSize: Int) {
  workspace(id: $id, slug: $slug) {
    id name slug deviceCount memberCount myPermissions features semantics allTags allMetadataKeys
    organization { id name }
    products {
      id name slug hardware deviceCount lastHeardThreshold
      measurementFields { fieldName verboseFieldName fieldType unit role semantic active useFormula }
      configurationFields { fieldName verboseFieldName fieldType unit }
    }
    devicesFiltered(page: 0, pageSize: $pageSize) {
      total
      devices { id verboseName serialNumber online lastHeard tags product { name } }
    }
  }
}
"""


def token_from_env(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("DATACAKE_TOKEN"):
        return os.environ["DATACAKE_TOKEN"]
    path = os.path.expanduser("~/.datacake/token")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip()
    sys.exit("no token: export DATACAKE_TOKEN=<token> (Account Settings > API Token, or an API user)")


def gql(query, variables, token, endpoint):
    req = urllib.request.Request(endpoint, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Token " + token,
                                          "User-Agent": "datacake-skill/discover.py"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"), strict=False)
    except urllib.error.HTTPError as exc:
        sys.exit("HTTP %s: %s%s" % (exc.code, exc.read().decode("utf-8", "replace")[:500],
                                    " (token rejected: invalid or revoked)" if exc.code == 401 else ""))
    except urllib.error.URLError as exc:
        sys.exit("network error: %s" % exc.reason)
    if data.get("errors"):
        for err in data["errors"]:
            code = (err.get("extensions") or {}).get("code", "")
            sys.stderr.write("GraphQL error %s: %s\n" % (code, err.get("message")))
        if not data.get("data"):
            sys.exit(1)
    return data["data"]


def table(rows, headers):
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    out.extend("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))) for r in rows)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workspace", nargs="?", help="workspace UUID or slug; omit to list workspaces")
    ap.add_argument("--devices", type=int, default=10, help="number of sample devices to show (default 10)")
    ap.add_argument("--inactive", action="store_true", help="include inactive fields")
    ap.add_argument("--product", help="only show products whose name contains this text")
    ap.add_argument("--json", action="store_true", help="print raw JSON instead of tables")
    ap.add_argument("--token")
    ap.add_argument("--endpoint", default=ENDPOINT)
    args = ap.parse_args()
    token = token_from_env(args.token)

    if not args.workspace:
        data = gql(WORKSPACES_QUERY, {}, token, args.endpoint)
        ws = data.get("allWorkspaces") or []
        if args.json:
            print(json.dumps(ws, indent=2))
            return
        if not ws:
            print("no workspaces visible for this token (is it valid? run: dc.py 'query { user { id } }')")
            return
        print(table([[w["id"], w["slug"], w["name"], w["deviceCount"], w["memberCount"],
                      ",".join(w["myPermissions"] or [])] for w in ws],
                    ["id", "slug", "name", "devices", "members", "myPermissions"]))
        print("\nNext: python3 scripts/discover.py <id-or-slug>")
        return

    variables = {"pageSize": args.devices}
    variables["id" if UUID_RE.match(args.workspace) else "slug"] = args.workspace
    data = gql(WORKSPACE_QUERY, variables, token, args.endpoint)
    ws = data.get("workspace")
    if not ws:
        sys.exit("workspace not found or no access: %s" % args.workspace)
    if args.product:
        needle = args.product.lower()
        ws["products"] = [p for p in ws["products"] or [] if needle in (p["name"] or "").lower()]
    if not args.inactive:
        for p in ws["products"] or []:
            p["measurementFields"] = [f for f in p["measurementFields"] or [] if f["active"]]
    if args.json:
        print(json.dumps(ws, indent=2, ensure_ascii=False))
        return

    org = ws.get("organization") or {}
    print("WORKSPACE %s  (slug: %s, id: %s)" % (ws["name"], ws["slug"], ws["id"]))
    print("organization: %s (%s)" % (org.get("name"), org.get("id")))
    print("devices: %s  members: %s" % (ws["deviceCount"], ws["memberCount"]))
    print("myPermissions: %s" % ", ".join(ws["myPermissions"] or []))
    print("features: %s" % ", ".join(ws["features"] or []))
    print("semantics in use: %s" % (", ".join(ws["semantics"] or []) or "-"))
    print("tags: %s" % (", ".join(ws["allTags"] or []) or "-"))
    print("metadata keys: %s" % (", ".join(ws["allMetadataKeys"] or []) or "-"))

    for p in ws["products"] or []:
        print("\nPRODUCT %s  (id: %s, slug: %s, hardware: %s, devices: %s, offline after %s min)" % (
            p["name"], p["id"], p["slug"], p["hardware"], p["deviceCount"], p["lastHeardThreshold"]))
        fields = p["measurementFields"] or []
        if fields:
            print(table([[f["fieldName"], f["verboseFieldName"], f["fieldType"], f["unit"], f["role"] or "",
                          f["semantic"] or "", "yes" if f["useFormula"] else "", "" if f["active"] else "INACTIVE"]
                         for f in fields],
                        ["fieldName (identifier)", "verboseFieldName", "type", "unit", "role", "semantic",
                         "formula", "state"]))
        else:
            print("  (no fields)")
        cfg = p["configurationFields"] or []
        if cfg:
            print("  configuration fields: " + ", ".join(
                "%s (%s%s)" % (c["fieldName"], c["fieldType"], ", " + c["unit"] if c["unit"] else "") for c in cfg))

    dl = ws["devicesFiltered"] or {}
    devices = dl.get("devices") or []
    print("\nSAMPLE DEVICES (%d of %s)" % (len(devices), dl.get("total")))
    if devices:
        print(table([[d["id"], d["verboseName"], d["serialNumber"], "online" if d["online"] else "offline",
                      (d["lastHeard"] or "")[:19], (d["product"] or {}).get("name"), ",".join(d["tags"] or [])]
                     for d in devices],
                    ["id", "verboseName", "serialNumber", "status", "lastHeard", "product", "tags"]))
    print("\nUse fieldName identifiers (left column) in currentMeasurements(fieldNames: [...]) and history(fields: [...]).")


if __name__ == "__main__":
    main()
