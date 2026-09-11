#!/usr/bin/env python3
"""Members, invites and API users of Datacake workspaces: list, export, invite, move, remove.

Usage:
  python3 scripts/members.py list <workspace>                       # members, pending invites, API users
  python3 scripts/members.py list <workspace> --csv members.csv     # one row per membership/invite/API user
  python3 scripts/members.py org-list <organization-id>             # every workspace of the organization, deduplicated by user
  python3 scripts/members.py org-list <organization-id> --csv org.csv
  python3 scripts/members.py invite <workspace> --emails a@x.io,b@y.io --permissions devices,rules
  python3 scripts/members.py invite <workspace> --file emails.txt --device <device-uuid>:edit_basics --brand <site-id>
  python3 scripts/members.py move --user a@x.io --from <workspace> --to <workspace> [--keep-source]
  python3 scripts/members.py remove <workspace> --user a@x.io       # member, pending invite or API user (by name)

<workspace> is a UUID or slug. --user accepts a user UUID, an email, or an API user name.
Write commands (invite, move, remove) only print their plan; add --execute to run it.
Token: $DATACAKE_TOKEN or ~/.datacake/token (or --token). Standard library only; reuses dc.py.
"""
import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dc import ENDPOINT, gql, report_errors, resolve_token  # noqa: E402

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
WORKSPACE_PERMISSIONS = ["basics", "members", "billing", "devices", "rules", "cakered", "whitelabel",
                         "gateways", "reports", "dashboards", "zones", "exports"]
DEVICE_PERMISSIONS = ["edit_basics", "edit_product", "record_measurements"]
CONCURRENCY = 5

MEMBERS_QUERY = """
query WorkspaceMembers($id: String, $slug: String) {
  workspace(id: $id, slug: $slug) {
    id name slug myPermissions
    organization { id name }
    userRelationships {
      id permissions allDevicesPermissionExists allDevicePermissions isOrganizationOwner
      user { id email fullName }
      deviceRelationships { id permissions device { id verboseName serialNumber } }
    }
    invitedUsers { id email permissions deviceInvites { id permissions device { id verboseName } } }
    apiUserRelationships {
      id permissions user { id name created }
      deviceRelationships { id permissions device { id verboseName serialNumber } }
    }
  }
}
"""

ORG_WORKSPACES_QUERY = """
query OrganizationWorkspaces($id: UUID!, $after: String) {
  organization(id: $id) {
    id name permissions
    workspaces(first: 100, after: $after, orderBy: NAME_ASC) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { node { id name slug memberCount myPermissions } }
    }
  }
}
"""

TARGET_DEVICE_QUERY = """
query TargetDevice($workspaceId: String!, $serial: String!) {
  workspace(id: $workspaceId) { id device(serialNumber: $serial) { id verboseName } }
}
"""

INVITE_MUTATION = """
mutation Invite($input: AddUserToWorkspaceInputType!) {
  addUserToWorkspace(input: $input) { ok invited }
}
"""

REMOVE_MUTATION = """
mutation RemoveMember($userId: String!, $workspaceId: String!) {
  removeUserFromWorkspace(userId: $userId, workspaceId: $workspaceId) { ok }
}
"""

DELETE_INVITE_MUTATION = """
mutation CancelInvite($email: String!, $workspaceId: String!) {
  deleteUserInvite(email: $email, workspace: $workspaceId) { ok }
}
"""

DELETE_API_USER_MUTATION = """
mutation DeleteApiUser($id: String!) { deleteApiUser(id: $id) { ok } }
"""


class Api:
    def __init__(self, token, endpoint):
        self.token, self.endpoint = token, endpoint

    def run(self, query, variables=None, quiet=False):
        """Return (data, errors). Prints GraphQL errors unless quiet."""
        resp = gql(query, variables, self.token, self.endpoint)
        if not quiet:
            report_errors(resp)
        return resp.get("data") or {}, resp.get("errors") or []

    def workspace(self, ref, quiet=False):
        variables = {"id" if UUID_RE.match(ref) else "slug": ref}
        data, errors = self.run(MEMBERS_QUERY, variables, quiet=quiet)
        ws = data.get("workspace")
        if not ws:
            if quiet:
                return None, errors
            sys.exit("workspace not found or no access: %s" % ref)
        return ws, errors


def perms(values):
    return ",".join(values or []) or "-"


def device_summary(rel):
    if rel.get("allDevicesPermissionExists"):
        return "all devices (%s)" % perms(rel.get("allDevicePermissions"))
    n = len(rel.get("deviceRelationships") or [])
    return "%d device%s" % (n, "" if n == 1 else "s")


def table(rows, headers):
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)), "  ".join("-" * w for w in widths)]
    out.extend("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))) for r in rows)
    return "\n".join(out)


def membership_rows(ws):
    """Flatten one workspace into CSV-style dicts."""
    rows = []
    for rel in ws.get("userRelationships") or []:
        rows.append({"kind": "member", "email": rel["user"]["email"], "name": rel["user"].get("fullName"),
                     "userId": rel["user"]["id"], "workspaceId": ws["id"], "workspaceSlug": ws["slug"],
                     "workspaceName": ws["name"], "permissions": perms(rel["permissions"]),
                     "devices": device_summary(rel), "deviceIds": ";".join(d["device"]["id"] for d in rel.get("deviceRelationships") or []),
                     "isOrganizationOwner": rel.get("isOrganizationOwner")})
    for inv in ws.get("invitedUsers") or []:
        rows.append({"kind": "invite", "email": inv["email"], "name": "", "userId": "", "workspaceId": ws["id"],
                     "workspaceSlug": ws["slug"], "workspaceName": ws["name"], "permissions": perms(inv["permissions"]),
                     "devices": "%d device invites" % len(inv.get("deviceInvites") or []),
                     "deviceIds": ";".join(d["device"]["id"] for d in inv.get("deviceInvites") or []), "isOrganizationOwner": False})
    for rel in ws.get("apiUserRelationships") or []:
        rows.append({"kind": "api-user", "email": "", "name": rel["user"]["name"], "userId": rel["user"]["id"],
                     "workspaceId": ws["id"], "workspaceSlug": ws["slug"], "workspaceName": ws["name"],
                     "permissions": perms(rel["permissions"]), "devices": device_summary(rel),
                     "deviceIds": ";".join(d["device"]["id"] for d in rel.get("deviceRelationships") or []), "isOrganizationOwner": False})
    return rows


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("wrote %d rows to %s" % (len(rows), path))


def print_workspace(ws):
    print("WORKSPACE %s  (slug: %s, id: %s)  organization: %s" % (
        ws["name"], ws["slug"], ws["id"], (ws.get("organization") or {}).get("name")))
    print("my permissions: %s\n" % perms(ws["myPermissions"]))
    members = ws.get("userRelationships") or []
    print("MEMBERS (%d)" % len(members))
    if members:
        print(table([[r["user"]["email"], r["user"].get("fullName"), r["user"]["id"], perms(r["permissions"]),
                      device_summary(r), "owner" if r.get("isOrganizationOwner") else ""] for r in members],
                    ["email", "name", "userId", "workspace permissions", "device access", ""]))
    invites = ws.get("invitedUsers") or []
    print("\nPENDING INVITES (%d)" % len(invites))
    if invites:
        print(table([[i["email"], perms(i["permissions"]), len(i.get("deviceInvites") or [])] for i in invites],
                    ["email", "workspace permissions", "device invites"]))
    api_users = ws.get("apiUserRelationships") or []
    print("\nAPI USERS (%d)" % len(api_users))
    if api_users:
        print(table([[r["user"]["name"], r["user"]["id"], (r["user"].get("created") or "")[:10], perms(r["permissions"]),
                      device_summary(r)] for r in api_users],
                    ["name", "id", "created", "workspace permissions", "device access"]))


def find_member(ws, ref):
    """Return (kind, record) for a user id, email or API user name in a workspace."""
    low = ref.lower()
    for rel in ws.get("userRelationships") or []:
        if rel["user"]["id"] == ref or rel["user"]["email"].lower() == low:
            return "member", rel
    for inv in ws.get("invitedUsers") or []:
        if inv["email"].lower() == low:
            return "invite", inv
    for rel in ws.get("apiUserRelationships") or []:
        if rel["user"]["id"] == ref or (rel["user"].get("name") or "").lower() == low:
            return "api-user", rel
    return None, None


def parse_permissions(text, allowed, label):
    values = [v.strip() for v in (text or "").split(",") if v.strip()]
    bad = [v for v in values if v not in allowed]
    if bad:
        sys.exit("unknown %s permission(s): %s (allowed: %s)" % (label, ", ".join(bad), ", ".join(allowed)))
    return values


def parse_devices(specs):
    rels = []
    for spec in specs or []:
        device, _, p = spec.partition(":")
        if not UUID_RE.match(device):
            sys.exit("--device needs <device-uuid>[:perm,perm]; got %r" % spec)
        rels.append({"device": device, "permissions": parse_permissions(p, DEVICE_PERMISSIONS, "device")})
    return rels


def read_emails(args):
    emails = []
    if args.emails:
        emails += [e.strip() for e in args.emails.split(",")]
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip().split(",")[0].strip()
                if line and "@" in line and not line.startswith("#"):
                    emails.append(line)
    seen, out = set(), []
    for e in emails:
        if e and e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    if not out:
        sys.exit("no emails: use --emails a@x.io,b@y.io or --file emails.txt (one address per line)")
    return out


# ------------------------------------------------------------------ commands
def cmd_list(api, args):
    ws, _ = api.workspace(args.workspace)
    if args.json:
        print(json.dumps(ws, indent=2, ensure_ascii=False))
        return
    if args.csv:
        write_csv(args.csv, membership_rows(ws), ["kind", "email", "name", "userId", "workspaceId", "workspaceSlug",
                                                 "workspaceName", "permissions", "devices", "deviceIds", "isOrganizationOwner"])
        return
    print_workspace(ws)


def cmd_org_list(api, args):
    workspaces, after, org = [], None, None
    while True:
        data, errors = api.run(ORG_WORKSPACES_QUERY, {"id": args.organization, "after": after})
        org = data.get("organization")
        if not org:
            sys.exit("organization not found or no admin access: %s" % args.organization)
        conn = org.get("workspaces") or {}
        workspaces.extend(e["node"] for e in conn.get("edges") or [] if e and e.get("node"))
        if not (conn.get("pageInfo") or {}).get("hasNextPage"):
            break
        after = conn["pageInfo"]["endCursor"]
    print("ORGANIZATION %s (id %s)  my permissions: %s  workspaces: %d\n" % (
        org["name"], org["id"], perms(org["permissions"]), len(workspaces)), file=sys.stderr)
    rows, unreadable, detailed = [], [], []
    for w in workspaces:
        ws, errors = api.workspace(w["id"], quiet=True)
        if not ws or ws.get("userRelationships") is None:
            code = ((errors or [{}])[0].get("extensions") or {}).get("code") or "no data"
            unreadable.append((w, code))
            continue
        detailed.append(ws)
        rows.extend(membership_rows(ws))
    if args.json:
        print(json.dumps({"organization": {"id": org["id"], "name": org["name"]}, "workspaces": detailed,
                          "unreadable": [{"id": w["id"], "slug": w["slug"], "reason": c} for w, c in unreadable]},
                         indent=2, ensure_ascii=False))
        return
    if args.csv:
        write_csv(args.csv, rows, ["kind", "email", "name", "userId", "workspaceId", "workspaceSlug", "workspaceName",
                                   "permissions", "devices", "deviceIds", "isOrganizationOwner"])
    else:
        people = {}
        for r in rows:
            if r["kind"] != "member":
                continue
            p = people.setdefault(r["userId"], {"email": r["email"], "name": r["name"], "memberships": []})
            p["memberships"].append("%s[%s]" % (r["workspaceSlug"], r["permissions"]))
        print("MEMBERS ACROSS %d READABLE WORKSPACES (%d distinct users)" % (len(detailed), len(people)))
        if people:
            print(table([[p["email"], p["name"], uid, len(p["memberships"]), "; ".join(p["memberships"])]
                         for uid, p in sorted(people.items(), key=lambda kv: kv[1]["email"].lower())],
                        ["email", "name", "userId", "n", "workspaces[permissions]"]))
        invites = [r for r in rows if r["kind"] == "invite"]
        if invites:
            print("\nPENDING INVITES (%d)" % len(invites))
            print(table([[r["email"], r["workspaceSlug"], r["permissions"]] for r in invites], ["email", "workspace", "permissions"]))
        api_users = [r for r in rows if r["kind"] == "api-user"]
        if api_users:
            print("\nAPI USERS (%d)" % len(api_users))
            print(table([[r["name"], r["workspaceSlug"], r["permissions"]] for r in api_users], ["name", "workspace", "permissions"]))
    if unreadable:
        print("\nUNREADABLE WORKSPACES (%d): the token lacks the 'members' permission there" % len(unreadable))
        print(table([[w["id"], w["slug"], w["name"], w.get("memberCount"), c] for w, c in unreadable],
                    ["id", "slug", "name", "members", "reason"]))


def cmd_invite(api, args):
    ws, _ = api.workspace(args.workspace)
    if "members" not in (ws["myPermissions"] or []):
        print("warning: token lacks the 'members' permission in %s; invites will fail" % ws["slug"], file=sys.stderr)
    ws_perms = parse_permissions(args.permissions, WORKSPACE_PERMISSIONS, "workspace")
    device_rels = parse_devices(args.device)
    emails = read_emails(args)
    existing = {r["user"]["email"].lower() for r in ws.get("userRelationships") or []}
    pending = {i["email"].lower() for i in ws.get("invitedUsers") or []}
    todo, skipped = [], []
    for e in emails:
        if e.lower() in existing:
            skipped.append((e, "already a member"))
        elif e.lower() in pending:
            skipped.append((e, "invite pending"))
        else:
            todo.append(e)
    print("PLAN: invite %d address(es) into %s (%s) with permissions [%s], %d device grant(s)%s" % (
        len(todo), ws["name"], ws["slug"], ",".join(ws_perms), len(device_rels),
        ", branded by white label site %s" % args.brand if args.brand else ""))
    for e in todo:
        print("  + %s" % e)
    for e, why in skipped:
        print("  = %s (%s)" % (e, why))
    if not todo:
        print("nothing to do")
        return
    if not args.execute:
        print("dry run: add --execute to send the invitations")
        return

    def invite(email):
        payload = {"workspace": ws["id"], "email": email, "wsPermissions": ws_perms, "deviceRelationships": device_rels}
        if args.brand:
            payload["brand"] = args.brand
        data, errors = api.run(INVITE_MUTATION, {"input": payload}, quiet=True)
        res = data.get("addUserToWorkspace") or {}
        if errors or not res.get("ok"):
            msg = "; ".join("%s%s" % (((e.get("extensions") or {}).get("code") + ": ") if (e.get("extensions") or {}).get("code") else "",
                                      e.get("message")) for e in errors) or "ok=false"
            return email, "ERROR", msg
        return email, "invited" if res.get("invited") else "added", ""

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        results = list(pool.map(invite, todo))
    print("\nRESULT")
    print(table([[e, status, note] for e, status, note in results], ["email", "status", "note"]))
    added = sum(1 for _, s, _ in results if s == "added")
    invited = sum(1 for _, s, _ in results if s == "invited")
    failed = [e for e, s, _ in results if s == "ERROR"]
    print("\n%d added instantly (account existed), %d invitation email(s) sent, %d failed" % (added, invited, len(failed)))
    if failed:
        sys.exit(1)


def cmd_move(api, args):
    src, _ = api.workspace(args.source)
    dst, _ = api.workspace(args.target)
    if src["id"] == dst["id"]:
        sys.exit("--from and --to are the same workspace")
    kind, rel = find_member(src, args.user)
    if kind is None:
        sys.exit("%s is not a member of %s" % (args.user, src["slug"]))
    if kind == "invite":
        sys.exit("%s is a pending invite in %s; cancel it and invite into %s instead" % (args.user, src["slug"], dst["slug"]))
    if kind == "api-user":
        sys.exit("%s is an API user; API users cannot move. Create one in %s (addApiUser), hand over the new key, then remove it here." % (
            args.user, dst["slug"]))
    user = rel["user"]
    if rel.get("isOrganizationOwner") and not args.keep_source:
        print("note: %s is the organization owner and cannot be removed from %s; proceeding with --keep-source" % (user["email"], src["slug"]))
        args.keep_source = True
    already, _ = find_member(dst, user["email"])
    mapped, missing = [], []
    for d in rel.get("deviceRelationships") or []:
        serial = d["device"].get("serialNumber")
        data, _ = api.run(TARGET_DEVICE_QUERY, {"workspaceId": dst["id"], "serial": serial}, quiet=True) if serial else ({}, [])
        target = ((data.get("workspace") or {}).get("device")) if data else None
        if target:
            mapped.append({"device": target["id"], "permissions": d["permissions"] or [], "name": target["verboseName"]})
        else:
            missing.append(d["device"]["verboseName"])
    print("PLAN: move %s (%s) from %s to %s" % (user["email"], user["id"], src["slug"], dst["slug"]))
    print("  workspace permissions: %s" % perms(rel["permissions"]))
    if rel.get("allDevicesPermissionExists"):
        print("  source has a workspace-wide device grant (%s); addUserToWorkspace cannot express that. Grant per device afterwards or set it in the portal." % perms(rel.get("allDevicePermissions")))
    print("  device grants mapped by serial number: %d" % len(mapped))
    for m in mapped:
        print("    + %s (%s)" % (m["name"], perms(m["permissions"])))
    if missing:
        print("  devices not present in target (skipped): %s" % ", ".join(missing))
    if already:
        print("  target: already a member (%s); permissions will be extended by the invite, then verified" % already)
    print("  then: %s" % ("keep membership in source" if args.keep_source else "remove from source %s" % src["slug"]))
    if not args.execute:
        print("dry run: add --execute to perform the move")
        return
    payload = {"workspace": dst["id"], "email": user["email"], "wsPermissions": rel["permissions"] or [],
               "deviceRelationships": [{"device": m["device"], "permissions": m["permissions"]} for m in mapped]}
    if args.brand:
        payload["brand"] = args.brand
    data, errors = api.run(INVITE_MUTATION, {"input": payload})
    res = data.get("addUserToWorkspace") or {}
    if errors or not res.get("ok"):
        sys.exit("adding to target failed; source untouched")
    if res.get("invited"):
        sys.exit("target reported invited=true (no account for %s?); source untouched, check the target's pending invites" % user["email"])
    check, _ = api.workspace(dst["id"])
    kind2, rel2 = find_member(check, user["email"])
    if kind2 != "member":
        sys.exit("verification failed: %s not found in %s after add; source untouched" % (user["email"], dst["slug"]))
    got = set(rel2["permissions"] or [])
    want = set(rel["permissions"] or [])
    print("verified in target: permissions %s%s, %d device grant(s)" % (
        perms(sorted(got)), "" if want <= got else " (MISSING: %s)" % ",".join(sorted(want - got)), len(rel2.get("deviceRelationships") or [])))
    if args.keep_source:
        print("done (source membership kept)")
        return
    data, errors = api.run(REMOVE_MUTATION, {"userId": user["id"], "workspaceId": src["id"]})
    if errors or not (data.get("removeUserFromWorkspace") or {}).get("ok"):
        sys.exit("removal from source failed; the user is now a member of both workspaces")
    print("removed from %s. done." % src["slug"])


def cmd_remove(api, args):
    ws, _ = api.workspace(args.workspace)
    kind, rel = find_member(ws, args.user)
    if kind is None:
        sys.exit("%s is not a member, invite or API user of %s" % (args.user, ws["slug"]))
    if kind == "member":
        label = "member %s (%s), permissions %s, %s" % (rel["user"]["email"], rel["user"]["id"], perms(rel["permissions"]), device_summary(rel))
        if rel.get("isOrganizationOwner"):
            sys.exit("%s is the organization owner and cannot be removed from workspaces of the organization" % rel["user"]["email"])
    elif kind == "invite":
        label = "pending invite for %s" % rel["email"]
    else:
        label = "API user %s (%s); its token stops working immediately" % (rel["user"]["name"], rel["user"]["id"])
    print("PLAN: remove %s from %s (%s)" % (label, ws["name"], ws["slug"]))
    if not args.execute:
        print("dry run: add --execute to remove")
        return
    if kind == "member":
        data, errors = api.run(REMOVE_MUTATION, {"userId": rel["user"]["id"], "workspaceId": ws["id"]})
        ok = (data.get("removeUserFromWorkspace") or {}).get("ok")
    elif kind == "invite":
        data, errors = api.run(DELETE_INVITE_MUTATION, {"email": rel["email"], "workspaceId": ws["id"]})
        ok = (data.get("deleteUserInvite") or {}).get("ok")
    else:
        data, errors = api.run(DELETE_API_USER_MUTATION, {"id": rel["user"]["id"]})
        ok = (data.get("deleteApiUser") or {}).get("ok")
    if errors or not ok:
        sys.exit("removal failed")
    print("removed.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token")
    ap.add_argument("--endpoint", default=ENDPOINT)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="members, invites and API users of one workspace")
    p.add_argument("workspace")
    p.add_argument("--csv", metavar="PATH")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("org-list", help="members of every workspace of an organization")
    p.add_argument("organization", help="organization id (discover.py --orgs)")
    p.add_argument("--csv", metavar="PATH")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_org_list)

    p = sub.add_parser("invite", help="invite one or many emails into a workspace")
    p.add_argument("workspace")
    p.add_argument("--emails", help="comma-separated addresses")
    p.add_argument("--file", help="file with one address per line (or a CSV whose first column is the email)")
    p.add_argument("--permissions", default="", help="comma-separated workspace permissions, e.g. devices,rules (default: none = observer)")
    p.add_argument("--device", action="append", metavar="UUID[:perm,perm]",
                   help="grant access to a device; repeatable; permissions from edit_basics,edit_product,record_measurements")
    p.add_argument("--brand", metavar="SITE-ID", help="white label site id for the invitation email")
    p.add_argument("--execute", action="store_true", help="send the invitations (default: dry run)")
    p.set_defaults(func=cmd_invite)

    p = sub.add_parser("move", help="move a member to another workspace (add there, verify, remove here)")
    p.add_argument("--user", required=True, help="user id or email")
    p.add_argument("--from", dest="source", required=True, metavar="WORKSPACE")
    p.add_argument("--to", dest="target", required=True, metavar="WORKSPACE")
    p.add_argument("--keep-source", action="store_true", help="do not remove the membership in the source workspace")
    p.add_argument("--brand", metavar="SITE-ID")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("remove", help="remove a member, cancel an invite or delete an API user")
    p.add_argument("workspace")
    p.add_argument("--user", required=True, help="user id, email, or API user name")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_remove)

    args = ap.parse_args()
    token = resolve_token(args.token)
    if not token:
        sys.exit("no token: export DATACAKE_TOKEN=<token> (a personal token of a user with the 'members' permission)")
    args.func(Api(token, args.endpoint), args)


if __name__ == "__main__":
    main()
