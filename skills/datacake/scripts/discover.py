#!/usr/bin/env python3
"""Print a compact map of a Datacake workspace: products, field identifiers, tags,
semantics, permissions and sample devices. Use it before hardcoding field names.

Usage:
  python3 scripts/discover.py                         # list the workspaces the token can access
  python3 scripts/discover.py <workspace-id|slug>     # map one workspace
  python3 scripts/discover.py <workspace> --devices 20 --inactive --product "Sensor"
  python3 scripts/discover.py <workspace> --json      # machine-readable output (includes field, downlink and device ids)
  python3 scripts/discover.py --orgs                  # organizations the token administers, with their workspaces

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

ORGS_QUERY = """
query Organizations($after: String) {
  user { id email isApiuser }
  organizations(orderBy: NAME_ASC, first: 50, after: $after) {
    totalCount
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id name permissions totalDevices subscriptionUnpaid
        entitlementWorkspacesQuota entitlementRemainingWorkspacesQuota
        owner { user { email } }
        userRelationships { totalCount }
        whitelabelSites { totalCount edges { node { id title domain } } }
        workspaces(first: 100, orderBy: NAME_ASC) {
          totalCount
          edges { node { id name slug deviceCount memberCount myPermissions } }
        }
      }
    }
  }
}
"""

WORKSPACE_QUERY = """
query Discover($id: String, $slug: String, $pageSize: Int) {
  workspace(id: $id, slug: $slug) {
    id name slug deviceCount memberCount myPermissions features semantics allTags allMetadataKeys
    organization { id name }
    products {
      id name slug hardware deviceCount lastHeardThreshold
      measurementFields { id fieldName verboseFieldName fieldType unit role semantic active useFormula }
      configurationFields { id fieldName verboseFieldName fieldType unit }
      lorawanDownlinks { id name fport }
      apiConfiguration { apiDownlinks { id name } mqttDownlinks { id name } }
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


def print_orgs(token, args):
    orgs, after, user = [], None, None
    while True:
        data = gql(ORGS_QUERY, {"after": after}, token, args.endpoint)
        user = user or data.get("user")
        conn = data.get("organizations") or {}
        orgs.extend(e["node"] for e in conn.get("edges") or [] if e and e.get("node"))
        if not (conn.get("pageInfo") or {}).get("hasNextPage"):
            break
        after = conn["pageInfo"]["endCursor"]
    if args.json:
        print(json.dumps({"user": user, "organizations": orgs}, indent=2, ensure_ascii=False))
        return
    if user and user.get("isApiuser"):
        print("token belongs to an API user: API users have no organization relationships (use a personal token)")
    if not orgs:
        print("no organizations: this token holds no organization admin permissions (workspace membership alone is not enough)")
        return
    print("user: %s\norganizations administered: %d\n" % ((user or {}).get("email"), len(orgs)))
    for o in orgs:
        wl = (o.get("whitelabelSites") or {})
        print("ORGANIZATION %s  (id: %s)" % (o["name"], o["id"]))
        print("  my permissions: %s   owner: %s   admins: %s   devices: %s   workspaces: %s/%s%s" % (
            ", ".join(o["permissions"] or []) or "-", ((o.get("owner") or {}).get("user") or {}).get("email"),
            (o.get("userRelationships") or {}).get("totalCount"), o.get("totalDevices"),
            (o.get("workspaces") or {}).get("totalCount"), o.get("entitlementWorkspacesQuota"),
            "   SUBSCRIPTION UNPAID" if o.get("subscriptionUnpaid") else ""))
        sites = [e["node"] for e in wl.get("edges") or [] if e and e.get("node")]
        if sites:
            print("  white label sites: " + ", ".join("%s (%s, id %s)" % (x["title"], x.get("domain") or "no domain", x["id"]) for x in sites))
        ws = [e["node"] for e in (o.get("workspaces") or {}).get("edges") or [] if e and e.get("node")]
        if ws:
            print(table([[w["id"], w["slug"], w["name"], w.get("deviceCount"), w.get("memberCount"),
                          ",".join(w["myPermissions"] or []) or "(not a member)"] for w in ws],
                        ["id", "slug", "name", "devices", "members", "myPermissions"]))
        if (o.get("workspaces") or {}).get("totalCount", 0) > len(ws):
            print("  (first %d of %d workspaces shown; use --json or OrganizationWorkspaces in organizations-and-members.md to page)" % (
                len(ws), o["workspaces"]["totalCount"]))
        print()
    print("Workspaces marked '(not a member)' cannot be read for members or devices with this token; invite the operator with the 'members' permission first.")
    print("Next: python3 scripts/members.py list <workspace>   or   python3 scripts/members.py org-list <organization id>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workspace", nargs="?", help="workspace UUID or slug; omit to list workspaces")
    ap.add_argument("--devices", type=int, default=10, help="number of sample devices to show (default 10)")
    ap.add_argument("--inactive", action="store_true", help="include inactive fields")
    ap.add_argument("--product", help="only show products whose name contains this text")
    ap.add_argument("--orgs", action="store_true", help="list organizations (admin view) instead of workspaces")
    ap.add_argument("--json", action="store_true", help="print raw JSON instead of tables")
    ap.add_argument("--token")
    ap.add_argument("--endpoint", default=ENDPOINT)
    args = ap.parse_args()
    token = token_from_env(args.token)

    if args.orgs:
        print_orgs(token, args)
        return

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
                          f["semantic"] or "", "yes" if f["useFormula"] else "", "" if f["active"] else "INACTIVE", f["id"]]
                         for f in fields],
                        ["fieldName (identifier)", "verboseFieldName", "type", "unit", "role", "semantic",
                         "formula", "state", "field id (rules)"]))
        else:
            print("  (no fields)")
        cfg = p["configurationFields"] or []
        if cfg:
            print("  configuration fields: " + ", ".join(
                "%s (%s%s, id %s)" % (c["fieldName"], c["fieldType"], ", " + c["unit"] if c["unit"] else "", c["id"]) for c in cfg))
        api_cfg = p.get("apiConfiguration") or {}
        downlinks = [("lorawan", d) for d in p.get("lorawanDownlinks") or []]
        downlinks += [("api", d) for d in api_cfg.get("apiDownlinks") or []] + [("mqtt", d) for d in api_cfg.get("mqttDownlinks") or []]
        if downlinks:
            print("  downlinks: " + ", ".join(
                "%s (%s%s, id %s)" % (d["name"], kind, ", fport %s" % d["fport"] if d.get("fport") is not None else "", d["id"])
                for kind, d in downlinks))

    dl = ws["devicesFiltered"] or {}
    devices = dl.get("devices") or []
    print("\nSAMPLE DEVICES (%d of %s)" % (len(devices), dl.get("total")))
    if devices:
        print(table([[d["id"], d["verboseName"], d["serialNumber"], "online" if d["online"] else "offline",
                      (d["lastHeard"] or "")[:19], (d["product"] or {}).get("name"), ",".join(d["tags"] or [])]
                     for d in devices],
                    ["id", "verboseName", "serialNumber", "status", "lastHeard", "product", "tags"]))
    print("\nUse fieldName identifiers (left column) in currentMeasurements(fieldNames: [...]), history(fields: [...]) and rule templates;")
    print("use the field/device/downlink ids in rule inputs (reference/rules-ng.md, scripts/rules.py ids).")


if __name__ == "__main__":
    main()
