#!/usr/bin/env python3
"""Live smoke test for the Datacake skill: runs the canonical read queries against a
real workspace and prints PASS/FAIL per check plus response-shape notes. Includes an
organizations section (admin permissions, cross-workspace member visibility, white label sites).

Usage:
  DATACAKE_TOKEN=... python3 tools/smoke_test.py [--workspace <id|slug>] [--json shapes.json]

Read-only: no mutation is executed. The token is never printed.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ENDPOINT = "https://api.datacake.co/graphql/"
results = []
shapes = {}


def gql(query, variables=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Token " + token
    req = urllib.request.Request(ENDPOINT, data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"), strict=False)
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code, "body": exc.read().decode("utf-8", "replace")[:500]}


def check(name, cond, note=""):
    results.append((name, bool(cond), note))
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, ("  -- " + note) if note else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace")
    ap.add_argument("--json", help="write observed response shapes here")
    args = ap.parse_args()
    token = os.environ.get("DATACAKE_TOKEN") or (open(os.path.expanduser("~/.datacake/token")).read().strip()
                                                if os.path.exists(os.path.expanduser("~/.datacake/token")) else None)
    if not token:
        sys.exit("DATACAKE_TOKEN not set")

    # 0. unauthenticated behaviour
    r = gql("query { user { id } }")
    shapes["unauthenticated_user"] = r
    check("unauthenticated user query", "data" in r, "user=%s errors=%s" % ((r.get("data") or {}).get("user"), bool(r.get("errors"))))
    r = gql("query { user { id } }", token="invalid-token-xyz")
    shapes["bad_token_user"] = r
    check("bad token handled", "data" in r or "http_error" in r, json.dumps(r)[:160])

    # 1. user + workspaces
    r = gql("query { user { id email isApiuser primaryWorkspace { id name slug } } allWorkspaces { id name slug deviceCount memberCount myPermissions semantics allTags } }", token=token)
    user = (r.get("data") or {}).get("user")
    check("user query", bool(user), "isApiuser=%s" % (user or {}).get("isApiuser"))
    workspaces = (r.get("data") or {}).get("allWorkspaces") or []
    check("allWorkspaces", len(workspaces) > 0, "%d workspaces" % len(workspaces))
    if not workspaces:
        sys.exit(1)
    ws = None
    if args.workspace:
        ws = next((w for w in workspaces if args.workspace in (w["id"], w["slug"])), None)
    if not ws:
        ws = max(workspaces, key=lambda w: w["deviceCount"] or 0)
    wid, slug = ws["id"], ws["slug"]
    print("using workspace %s (%s), %s devices, permissions %s, semantics %s" % (ws["name"], wid, ws["deviceCount"], ws["myPermissions"], ws["semantics"]))

    # 2. workspace by slug, devicesFiltered, ordering, tags
    r = gql("""query($slug: String!) { workspace(slug: $slug) { id name deviceCount allMetadataKeys features
      list: devicesFiltered(page: 0, pageSize: 5, orderBy: { lastHeard: DESC }) { total devices { id verboseName serialNumber online lastHeard tags metadata product { id name slug } currentLocation { lat lng } } }
      online: devicesFiltered(online: true) { total }
      offline: devicesFiltered(online: false) { total }
      allTrue: devicesFiltered(all: true) { total }
      allDefault: devicesFiltered { total }
      recent: devicesFiltered(lastHeard: { gt: "2026-01-01T00:00:00Z" }) { total }
    } }""", {"slug": slug}, token)
    w = (r.get("data") or {}).get("workspace")
    check("workspace by slug + devicesFiltered", bool(w) and not r.get("errors"), "errors=%s" % json.dumps(r.get("errors"))[:200])
    if not w:
        sys.exit(1)
    shapes["workspace_lists"] = {k: (v if k != "list" else {"total": v["total"], "n": len(v["devices"])}) for k, v in w.items() if k not in ("id", "name")}
    print("   totals: list=%s online=%s offline=%s all:true=%s default=%s recent=%s" % (
        w["list"]["total"], w["online"]["total"], w["offline"]["total"], w["allTrue"]["total"], w["allDefault"]["total"], w["recent"]["total"]))
    devices = w["list"]["devices"]
    check("device list non-empty", len(devices) > 0)
    if not devices:
        sys.exit(1)
    dev = devices[0]
    shapes["device_sample"] = {k: (v if k != "metadata" else (v[:80] if isinstance(v, str) else v)) for k, v in dev.items()}
    print("   sample device: %s (%s) online=%s lastHeard=%s product=%s" % (dev["verboseName"], dev["id"], dev["online"], dev["lastHeard"], (dev["product"] or {}).get("name")))

    # 3. product fields + device by serial + allDevices idIn
    r = gql("""query($id: String!, $wid: String!, $serial: String!, $ids: [UUID!]) {
      device(deviceId: $id) { id verboseName measurements24h isOverQuota plan(workspace: $wid) { name slug datapointsPerDay dataRetentionDays dataRetentionMonths }
        product { id name slug lastHeardThreshold measurementFields { id fieldName verboseFieldName fieldType unit displayUnit role semantic active useFormula } configurationFields { fieldName fieldType } lorawanDownlinks { id name fport } }
        roleFields { role value datetime chartData field { fieldName unit fieldType } }
        currentConfigurationValues { valueNumber valueString valueBool isDefault configurationField { fieldName } }
        myPermissions(workspace: $wid)
      }
      workspace(id: $wid) { device(serialNumber: $serial) { id } }
      allDevices(idIn: $ids) { id verboseName }
    }""", {"id": dev["id"], "wid": wid, "serial": dev["serialNumber"], "ids": [dev["id"]]}, token)
    d = (r.get("data") or {}).get("device")
    check("device by id + product fields", bool(d) and not r.get("errors"), "errors=%s" % json.dumps(r.get("errors"))[:200])
    if not d:
        sys.exit(1)
    fields = [f for f in (d["product"]["measurementFields"] or []) if f["active"]]
    shapes["product_fields"] = fields
    shapes["roleFields"] = d["roleFields"]
    shapes["plan"] = d["plan"]
    shapes["configValues"] = d["currentConfigurationValues"]
    shapes["myPermissions"] = d["myPermissions"]
    print("   %d active fields: %s" % (len(fields), ", ".join("%s(%s%s%s)" % (f["fieldName"], f["fieldType"], "/" + f["role"] if f["role"] else "", "/" + f["semantic"] if f["semantic"] else "") for f in fields[:12])))
    print("   plan=%s roleFields=%s permissions=%s" % (d["plan"], [(x["role"], x["value"]) for x in d["roleFields"] or []], d["myPermissions"]))
    check("workspace.device(serialNumber)", ((r.get("data") or {}).get("workspace") or {}).get("device", {}) and (r["data"]["workspace"]["device"] or {}).get("id") == dev["id"])
    check("allDevices(idIn)", len((r.get("data") or {}).get("allDevices") or []) == 1)

    numeric = [f for f in fields if f["fieldType"] in ("FLOAT", "INT", "NUMERIC", "COUNTER")]
    # prefer a numeric field that actually has data in the last 7 days
    rs = gql("query($id: String!, $s: DateTime!, $e: DateTime!) { device(deviceId: $id) { historyStats(start: $s, end: $e) } }",
             {"id": dev["id"], "s": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(), "e": datetime.now(timezone.utc).isoformat()}, token)
    try:
        stats = json.loads(((rs.get("data") or {}).get("device") or {}).get("historyStats") or "{}")
    except Exception:
        stats = {}
    with_data = [f for f in numeric if (stats.get(f["fieldName"]) or {}).get("last_value") is not None]
    fname = ((with_data or numeric or fields)[0]["fieldName"]) if fields else None
    check("numeric field available", bool(fname), fname or "")
    if not fname:
        sys.exit(1)
    all_names = [f["fieldName"] for f in fields][:6]

    # 4. current measurements + stats
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(days=1)
    r = gql("""query($id: String!, $names: [String], $namesReq: [String!]!, $f: String!, $start: DateTime!, $end: DateTime!) {
      device(deviceId: $id) {
        sel: currentMeasurements(fieldNames: $names) { value valueString valueCounterAbs modified field { fieldName fieldType unit } }
        act: currentMeasurements(allActiveFields: true) { value field { fieldName } }
        one: currentMeasurement(fieldName: $f) { value modified
          asOf: value(timeRangeStart: $start, timeRangeEnd: $end)
          avg: average(timeRangeStart: $start, timeRangeEnd: $end)
          min: minimum(timeRangeStart: $start, timeRangeEnd: $end)
          max: maximum(timeRangeStart: $start, timeRangeEnd: $end)
          sum: sum(timeRangeStart: $start, timeRangeEnd: $end)
          change: change(timeRangeStart: $start, timeRangeEnd: $end) }
      }
      rootOne: currentMeasurement(deviceId: $id, fieldName: $f) { value }
      rootMany: currentMeasurements(deviceId: $id, fieldNames: $namesReq) { value field { fieldName } }
      parseDate(date: "2026-03-11 00:00", timezone: "Europe/Berlin")
    }""", {"id": dev["id"], "names": all_names, "namesReq": all_names, "f": fname, "start": start.isoformat(), "end": now.isoformat()}, token)
    d = (r.get("data") or {}).get("device")
    check("currentMeasurements variants + stats", bool(d) and not r.get("errors"), "errors=%s" % json.dumps(r.get("errors"))[:300])
    if d:
        shapes["current"] = d
        shapes["parseDate"] = r["data"].get("parseDate")
        print("   sel=%s" % [(m["field"]["fieldName"], m["value"], m["valueString"], m["modified"]) for m in d["sel"] or []][:4])
        print("   one=%s" % d["one"])
        print("   parseDate=%s rootOne=%s rootMany=%d" % (r["data"].get("parseDate"), r["data"].get("rootOne"), len(r["data"].get("rootMany") or [])))

    # 5. history variants
    variants = [("15m", {}), ("1h", {}), ("24h", {}), ("7d", {}), ("raw", {}), ("1h+locf", {"locf": True})]
    for label, extra in variants:
        res = label.split("+")[0]
        rng_start = now - timedelta(days=14 if res in ("24h", "7d") else 2)
        r = gql("""query($id: String!, $f: [String], $s: String!, $e: String!, $res: String!, $locf: Boolean, $ndt: Boolean) {
          device(deviceId: $id) { history(fields: $f, timerangestart: $s, timerangeend: $e, resolution: $res, locf: $locf, nodatathreshold: $ndt) } }""",
                {"id": dev["id"], "f": [fname], "s": rng_start.isoformat(), "e": now.isoformat(), "res": res,
                 "locf": extra.get("locf"), "ndt": extra.get("nodatathreshold")}, token)
        h = ((r.get("data") or {}).get("device") or {}).get("history")
        ok = isinstance(h, str) and not r.get("errors")
        rows = json.loads(h) if ok else None
        note = "rows=%s first=%s" % (len(rows) if rows is not None else None, json.dumps(rows[0])[:120] if rows else None)
        if r.get("errors"):
            note = "errors=%s" % json.dumps(r["errors"])[:200]
        check("history resolution %s" % label, ok, note)
        shapes.setdefault("history", {})[label] = {"type": type(h).__name__, "rows": len(rows) if rows is not None else None, "sample": rows[:2] if rows else None, "errors": r.get("errors")}

    # 6. historyNg / historyStats / dashboardData
    r = gql("""query($id: String!, $s: DateTime!, $e: DateTime!) { device(deviceId: $id) {
        historyNg(start: $s, end: $e, resolution: "1h") historyStats(start: $s, end: $e) } }""",
            {"id": dev["id"], "s": start.isoformat(), "e": now.isoformat()}, token)
    d = (r.get("data") or {}).get("device") or {}
    for key in ("historyNg", "historyStats"):
        val = d.get(key)
        parsed = None
        try:
            parsed = json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass
        check(key, val is not None and not r.get("errors"), ("type=%s preview=%s" % (type(parsed).__name__, json.dumps(parsed)[:300])) if val is not None else "errors=%s" % json.dumps(r.get("errors"))[:200])
        shapes[key] = json.dumps(parsed)[:2000] if parsed is not None else r.get("errors")

    # 7. semantics + boolean + ordering
    sem = ws["semantics"] or []
    numeric_sem = [s for s in sem if s not in ("LOCATION",) and not s.endswith(("_DETECTED", "_OPENED", "_PRESSED", "_OCCUPIED", "_POWERED", "_TRIGGERED", "_ACTIVE", "_ON", "_REQUIRED", "_LOW"))]
    bool_sem = [s for s in sem if s.endswith(("_DETECTED", "_OPENED", "_PRESSED", "_OCCUPIED", "_POWERED", "_TRIGGERED", "_ACTIVE", "_ON", "_REQUIRED", "_LOW"))]
    if numeric_sem:
        s0 = numeric_sem[0]
        arg = s0[0].lower() + "".join(p.capitalize() for p in s0.lower().split("_"))[1:]
        q = """query($wid: String!) { workspace(id: $wid) {
          agg: devicesFiltered(online: true) { total avg: aggregatedNumericSemanticValue(semantic: %s) mx: aggregatedNumericSemanticValue(semantic: %s, aggregation: MAX) }
          flt: devicesFiltered(%s: { gt: -1000000 }, pageSize: 3, orderBy: { semanticField: { semantic: %s, order: DESC } }) { total devices { id verboseName v: numericSemanticField(semantic: %s) { value fields { fieldName value unit } } } }
        } }""" % (s0, s0, arg, s0, s0)
        r = gql(q, {"wid": wid}, token)
        w = (r.get("data") or {}).get("workspace")
        check("semantic aggregate/filter/order (%s via %s)" % (s0, arg), bool(w) and not r.get("errors"), ("agg=%s flt_total=%s" % (w["agg"], w["flt"]["total"])) if w else "errors=%s" % json.dumps(r.get("errors"))[:300])
        shapes["semantic"] = w
    else:
        check("semantic checks", False, "no numeric semantics assigned in workspace; skipped")
    if bool_sem:
        s0 = bool_sem[0]
        arg = s0[0].lower() + "".join(p.capitalize() for p in s0.lower().split("_"))[1:]
        q = """query($wid: String!) { workspace(id: $wid) {
          cnt: devicesFiltered(all: true) { total c: aggregatedBooleanSemanticCount(semantic: %s, countValue: true) }
          flt: devicesFiltered(%s: { exact: true }, pageSize: 3) { total devices { id verboseName b: booleanSemanticField(semantic: %s) { value count(countValue: true) } } }
        } }""" % (s0, arg, s0)
        r = gql(q, {"wid": wid}, token)
        w = (r.get("data") or {}).get("workspace")
        check("boolean semantic count/filter (%s)" % s0, bool(w) and not r.get("errors"), ("cnt=%s flt_total=%s" % (w["cnt"], w["flt"]["total"])) if w else "errors=%s" % json.dumps(r.get("errors"))[:300])
        shapes["boolean_semantic"] = w
    else:
        print("   (no boolean semantics assigned; boolean checks skipped)")

    # 8. tags / search / relay connections / organization
    tag = (ws["allTags"] or [None])[0]
    r = gql("""query($wid: String!, $tags: [String], $s: String) { workspace(id: $wid) {
        byTag: devicesFiltered(tags: { contains: $tags }, pageSize: 2) { total devices { id tags } }
        anyTag: devicesFiltered(tags: { overlap: $tags }) { total }
        search: devicesFiltered(search: $s, pageSize: 2) { total }
        zones(first: 5) { totalCount pageInfo { hasNextPage endCursor } edges { node { id name radius center tags } } }
        gateways(first: 2) { totalCount edges { node { id name online } } }
        exports(first: 2) { totalCount edges { node { id name kind } } }
        rulesNG { id name enabled executionMode tagsFilterConjunction triggerOnMeasurement }
        dashboards { id name sharingPolicy }
        organization { id name permissions }
        deviceFolders
      }
      allDevices(inWorkspace: $wid, searchTags: $tags, searchTagsAnyAll: any) { id }
      organizations(first: 3) { totalCount edges { node { id name } } }
    }""", {"wid": wid, "tags": [tag] if tag else [], "s": dev["verboseName"][:4]}, token)
    w = (r.get("data") or {}).get("workspace")
    check("tags/search/relay/organization", bool(w) and not r.get("errors"), ("tag=%s byTag=%s anyTag=%s search=%s zones=%s gateways=%s exports=%s rules=%d dashboards=%d org=%s allDevices=%d orgs=%s" % (
        tag, w["byTag"]["total"], w["anyTag"]["total"], w["search"]["total"], w["zones"]["totalCount"] if w["zones"] else None,
        w["gateways"]["totalCount"] if w["gateways"] else None, w["exports"]["totalCount"] if w["exports"] else None, len(w["rulesNG"] or []), len(w["dashboards"] or []),
        (w["organization"] or {}).get("name"), len(r["data"].get("allDevices") or []), (r["data"].get("organizations") or {}).get("totalCount"))) if w else "errors=%s" % json.dumps(r.get("errors"))[:400])
    if w:
        shapes["rulesNG"] = w["rulesNG"]
        shapes["deviceFolders"] = (w.get("deviceFolders") or "")[:500]
        shapes["zones"] = w["zones"]

    # 8a. Rule Engine NG: full rule (action union fragments) and execution log of the first rule (read-only)
    rules = (w or {}).get("rulesNG") or []
    if rules:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "datacake", "scripts"))
        import rules as rules_mod  # noqa: E402
        r = gql(rules_mod.GET_QUERY, {"id": rules[0]["id"]}, token)
        rule = (r.get("data") or {}).get("ruleNG")
        shapes["ruleNG"] = rule
        check("ruleNG detail (conditions, action fragments)", bool(rule) and not r.get("errors"), ("%s: mode=%s triggers=%s conditions=%d actions=%s" % (
            rule["name"], rule.get("executionMode"), rules_mod.triggers_of(rule), len(rule.get("conditions") or []),
            rules_mod.actions_summary(rule.get("actions")))) if rule else "errors=%s" % json.dumps(r.get("errors"))[:300])
        r = gql(rules_mod.LOGS_QUERY, {"id": rules[0]["id"], "first": 3, "filter": None}, token)
        conn = ((r.get("data") or {}).get("ruleNG") or {}).get("executionLogEntries")
        shapes["ruleNG_logs"] = conn
        check("ruleNG executionLogEntries", "data" in r, "entries=%s errors=%s" % (
            len((conn or {}).get("edges") or []) if conn is not None else None, json.dumps(r.get("errors"))[:200]))
        r = gql("""query($wid: String!) { workspace(id: $wid) { entitlementRulesQuota entitlementRulesQuotaRemaining entitlementRulesLogRetrievableHours
          pushRecipientCandidates { reachable user { id email } } } }""", {"wid": wid}, token)
        w8 = (r.get("data") or {}).get("workspace") or {}
        shapes["rules_entitlements"] = w8
        check("rules entitlements + push recipients", bool(w8) and not r.get("errors"), "quota=%s/%s logHours=%s recipients=%s" % (
            w8.get("entitlementRulesQuotaRemaining"), w8.get("entitlementRulesQuota"), w8.get("entitlementRulesLogRetrievableHours"),
            len(w8.get("pushRecipientCandidates") or [])))
    else:
        print("   (no rules in %s; rule detail and log checks skipped)" % slug)

    # 8b. organizations, admins, cross-workspace member visibility, white label sites (read-only)
    r = gql("""query { user { id isApiuser whitelabelSites { id title domain brand } }
      organizations(first: 20, orderBy: NAME_ASC) { totalCount edges { node { id name permissions
        owner { id user { id email } }
        userRelationships(first: 5) { totalCount edges { node { id permissions user { id email } } } }
        workspaces(first: 50) { totalCount edges { node { id slug name memberCount deviceCount myPermissions } } }
        whitelabelSites { totalCount } } } } }""", token=token)
    orgs = [e["node"] for e in (((r.get("data") or {}).get("organizations") or {}).get("edges") or []) if e]
    shapes["organizations"] = {"errors": r.get("errors"), "count": len(orgs),
                               "sample": [{k: v for k, v in o.items() if k != "workspaces"} for o in orgs[:2]]}
    check("organizations query", "data" in r and not r.get("errors"), "%d organizations, whitelabelSites=%s errors=%s" % (
        len(orgs), len(((r.get("data") or {}).get("user") or {}).get("whitelabelSites") or []), json.dumps(r.get("errors"))[:200]))
    member_ids = {w["id"] for w in workspaces}
    if orgs:
        o = orgs[0]
        print("   org %s: permissions=%s admins=%s workspaces=%s" % (o["name"], o["permissions"],
              (o["userRelationships"] or {}).get("totalCount"), (o["workspaces"] or {}).get("totalCount")))
        org_ws = [e["node"] for e in ((o.get("workspaces") or {}).get("edges") or []) if e]
        non_member = [w for w in org_ws if w["id"] not in member_ids]
        check("org.workspaces lists non-member workspaces", True, "%d of %d workspaces are not memberships of this token; myPermissions there=%s" % (
            len(non_member), len(org_ws), [w["myPermissions"] for w in non_member[:3]]))
        if non_member:
            r2 = gql("""query($id: String!) { workspace(id: $id) { id memberCount deviceCount myPermissions
              userRelationships { id user { email } } invitedUsers { email } devicesFiltered(pageSize: 1) { total } } }""",
                     {"id": non_member[0]["id"]}, token)
            w2 = (r2.get("data") or {}).get("workspace") or {}
            shapes["non_member_workspace"] = r2
            check("non-member workspace: members readable by org admin?", "data" in r2,
                  "workspace=%s userRelationships=%s devices=%s errors=%s" % (
                      bool(w2), "readable(%d)" % len(w2["userRelationships"]) if w2.get("userRelationships") is not None else "null",
                      (w2.get("devicesFiltered") or {}).get("total") if w2 else None,
                      [((e.get("extensions") or {}).get("code"), e.get("message")) for e in r2.get("errors") or []][:2]))
        else:
            print("   (token is a member of every workspace of this organization; cross-workspace visibility not testable)")
    else:
        print("   (no organization admin permissions on this token; organization checks skipped)")
    if "members" in (ws["myPermissions"] or []):
        r3 = gql("""query($id: String!) { workspace(id: $id) {
          userRelationships { id permissions allDevicesPermissionExists isOrganizationOwner user { id email isApiuser } deviceRelationships { id permissions device { id } } }
          invitedUsers { id email permissions deviceInvites { id permissions device { id } } }
          apiUserRelationships { id permissions user { id name created } } } }""", {"id": wid}, token)
        w3 = (r3.get("data") or {}).get("workspace") or {}
        shapes["members"] = {"members": len(w3.get("userRelationships") or []), "invites": len(w3.get("invitedUsers") or []),
                             "apiUsers": len(w3.get("apiUserRelationships") or []), "errors": r3.get("errors")}
        check("workspace members/invites/api users", bool(w3) and not r3.get("errors"), json.dumps(shapes["members"])[:200])
    else:
        print("   (no 'members' permission in %s; member list check skipped)" % slug)

    # 9. error shape: nonexistent workspace + unknown field
    r = gql('query { workspace(id: "00000000-0000-0000-0000-000000000000") { id } }', token=token)
    shapes["missing_workspace"] = r
    check("missing workspace shape", "data" in r, json.dumps(r)[:200])
    r = gql('query($id: String!) { device(deviceId: $id) { currentMeasurements(fieldNames: ["DOES_NOT_EXIST_XYZ"]) { value field { fieldName } } } }', {"id": dev["id"]}, token)
    shapes["unknown_field"] = r
    check("unknown field identifier shape", "data" in r, json.dumps(r)[:200])

    failed = [n for n, ok, _ in results if not ok]
    print("\n%d checks, %d failed%s" % (len(results), len(failed), (": " + ", ".join(failed)) if failed else ""))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(shapes, fh, indent=1, default=str)
        print("shapes written to %s" % args.json)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
