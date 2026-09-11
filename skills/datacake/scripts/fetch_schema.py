#!/usr/bin/env python3
"""Fetch the Datacake GraphQL schema by introspection and write it as SDL.

Also regenerates the generated blocks inside reference/schema-map.md so the
curated schema index never drifts from the live API.

Usage (paths default to this skill's reference/ folder, run from anywhere):
  python3 scripts/fetch_schema.py               # write reference/schema.graphql, update schema-map.md
  python3 scripts/fetch_schema.py --check       # fetch and print the diff only, write nothing
  python3 scripts/fetch_schema.py --out /tmp/schema.graphql --no-map
  python3 scripts/fetch_schema.py --json /tmp/introspection.json   # also keep the raw JSON

Introspection is public: no token is required. DATACAKE_TOKEN is sent when set.
Standard library only.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://api.datacake.co/graphql/"
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(SKILL_DIR, "reference", "schema.graphql")
DEFAULT_MAP = os.path.join(SKILL_DIR, "reference", "schema-map.md")
# The introspection response is ~1.1 MB; 60 s leaves room for slow connections.
TIMEOUT = 60

TYPE_REF = ("kind name ofType { kind name ofType { kind name ofType { kind name ofType "
            "{ kind name ofType { kind name ofType { kind name ofType { kind name } } } } } } }")
INTROSPECTION = """
query IntrospectionQuery {
  __schema {
    queryType { name } mutationType { name } subscriptionType { name }
    types { ...FullType }
    directives { name description locations args { ...InputValue } }
  }
}
fragment FullType on __Type {
  kind name description
  fields(includeDeprecated: true) {
    name description args { ...InputValue } type { ...TypeRef } isDeprecated deprecationReason
  }
  inputFields { ...InputValue }
  interfaces { ...TypeRef }
  enumValues(includeDeprecated: true) { name description isDeprecated deprecationReason }
  possibleTypes { ...TypeRef }
}
fragment InputValue on __InputValue { name description type { ...TypeRef } defaultValue }
fragment TypeRef on __Type { %s }
""" % TYPE_REF

BUILTIN_SCALARS = {"String", "Int", "Float", "Boolean", "ID"}
BUILTIN_DIRECTIVES = {"include", "skip", "deprecated", "specifiedBy"}
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Enums worth listing verbatim in schema-map.md (names must exist in the schema).
MAP_ENUMS = [
    "FieldSemantic", "NumericSemanticFieldAggregation", "BooleanSemanticFieldAggregation",
    "WorkspacePermissions", "DevicePermissions", "UserOrganizationPermissions",
    "ErrorCode", "FieldType", "ProductMeasurementFieldFieldType", "RoleChoices",
    "DeviceKind", "SearchTagsAnyAll", "DashboardSharingPolicy", "DevicePublicLinkMode",
    "DashboardPublicLinkMode", "RuleExecutionMode", "ExportKind", "ExportFormat",
    "ExportFieldSelection", "ExportPeriodicInterval", "WorkspaceFeatures",
    "AuditLogEntryAction", "OrganizationUserRelationshipsOrder", "OrganizationWorkspacesOrder",
    "WhitelabelUserOrder", "WhitelabelAuditLogEntryOrder",
]

# Mutation themes for the generated index: first matching substring wins.
THEMES = [
    ("Auth & account", ["login", "signup", "passwordreset", "changepassword", "otp", "closeaccount",
                        "updateuser", "pushtoken"]),
    ("Members & permissions", ["usertoworkspace", "userfromworkspace", "permission", "apiuser",
                               "userinvite", "userorganizationrelationship", "transferorganizationownership"]),
    ("Workspaces & organization", ["workspace", "organization", "sso", "workos"]),
    ("Rules & alerts", ["rule", "alert", "condition", "emailsettings", "smssettings",
                        "functionsettings", "setoutputsettings"]),
    ("Dashboards & views", ["dashboard", "view"]),
    ("Reports & exports", ["report", "export"]),
    ("Zones", ["zone"]),
    ("Webhooks", ["webhook"]),
    ("Billing, plans & add-ons", ["billing", "stripe", "purchase", "addon", "coupon", "subscription",
                                  "quote", "taxid", "smscredit", "smsquota", "autotopup", "smsmode",
                                  "gsm7", "plan"]),
    ("Gateways & LoRaWAN", ["gateway", "lora", "ttn", "tti", "thingpark", "devnonce"]),
    ("Devices", ["device", "claim", "pincode", "kemper", "serial", "folder", "suggestion",
                 "notifyoffline"]),
    ("Products & fields", ["product", "measurementfield", "configurationfield", "fieldmapping",
                           "lookuptable", "formula", "gauge", "encoder", "decoder", "function"]),
    ("Data & downlinks", ["setvalue", "measurement", "downlink", "aw3", "publishqueues"]),
    ("Integrations", ["mqtt", "particle", "cellular1nce", "draginonbiot", "api", "dzeroos", "cakered"]),
    ("White label", ["whitelabel", "branding", "heretoken"]),
]


def fetch(endpoint, token=None):
    body = json.dumps({"query": INTROSPECTION}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "datacake-skill/fetch_schema"}
    if token:
        headers["Authorization"] = "Token " + token
    req = urllib.request.Request(endpoint, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        sys.exit("HTTP %s from %s: %r" % (exc.code, endpoint, exc.read()[:500]))
    except urllib.error.URLError as exc:
        sys.exit("Network error contacting %s: %s" % (endpoint, exc.reason))
    # Some descriptions contain raw control characters, which strict JSON parsing rejects.
    data = json.loads(raw, strict=False)
    if data.get("errors"):
        sys.exit("Introspection errors: " + json.dumps(data["errors"])[:1000])
    return data["data"]["__schema"]


def ref(t):
    if t["kind"] == "NON_NULL":
        return ref(t["ofType"]) + "!"
    if t["kind"] == "LIST":
        return "[" + ref(t["ofType"]) + "]"
    return t["name"]


def clean(text):
    return CTRL.sub("", text or "").strip()


def desc(text, indent=""):
    text = clean(text).replace('"""', '\\"""')
    if not text:
        return ""
    if "\n" in text:
        body = "\n".join((indent + line.rstrip()) if line.strip() else "" for line in text.split("\n"))
        return '%s"""\n%s\n%s"""\n' % (indent, body, indent)
    return '%s"""%s"""\n' % (indent, text)


def deprecated(node):
    if not node.get("isDeprecated"):
        return ""
    reason = clean(node.get("deprecationReason")).replace('"', '\\"').replace("\n", " ")
    return ' @deprecated(reason: "%s")' % reason if reason else " @deprecated"


def input_value(iv):
    s = "%s: %s" % (iv["name"], ref(iv["type"]))
    if iv.get("defaultValue") is not None:
        s += " = %s" % iv["defaultValue"]
    return s


def args_block(args, indent):
    if not args:
        return ""
    if any(clean(a.get("description")) for a in args):
        inner = "".join(desc(a.get("description"), indent + "  ") + indent + "  " + input_value(a) + "\n"
                        for a in args)
        return "(\n" + inner + indent + ")"
    return "(" + ", ".join(input_value(a) for a in args) + ")"


def print_type(t):
    kind, name = t["kind"], t["name"]
    if name.startswith("__"):
        return ""
    out = desc(t.get("description"))
    if kind == "SCALAR":
        return "" if name in BUILTIN_SCALARS else out + "scalar %s\n\n" % name
    if kind == "ENUM":
        out += "enum %s {\n" % name
        for v in t["enumValues"]:
            out += desc(v.get("description"), "  ") + "  %s%s\n" % (v["name"], deprecated(v))
        return out + "}\n\n"
    if kind == "INPUT_OBJECT":
        out += "input %s {\n" % name
        for f in t["inputFields"]:
            out += desc(f.get("description"), "  ") + "  " + input_value(f) + "\n"
        return out + "}\n\n"
    if kind == "UNION":
        return out + "union %s = %s\n\n" % (name, " | ".join(p["name"] for p in t["possibleTypes"]))
    if kind in ("OBJECT", "INTERFACE"):
        keyword = "type" if kind == "OBJECT" else "interface"
        impl = ""
        if t.get("interfaces"):
            impl = " implements " + " & ".join(i["name"] for i in t["interfaces"])
        out += "%s %s%s {\n" % (keyword, name, impl)
        for f in t["fields"] or []:
            out += desc(f.get("description"), "  ") + "  %s%s: %s%s\n" % (
                f["name"], args_block(f["args"], "  "), ref(f["type"]), deprecated(f))
        return out + "}\n\n"
    return ""


def to_sdl(schema, endpoint):
    q, m, s = schema["queryType"], schema["mutationType"], schema["subscriptionType"]
    header = ("# Datacake GraphQL schema (SDL)\n"
              "# Generated by scripts/fetch_schema.py from %s on %s\n"
              "# Grep this file instead of reading it whole, e.g.:\n"
              "#   grep -n '^type DeviceType' -A 120 reference/schema.graphql\n"
              "#   grep -n '^input CreateRuleNGInputType' -A 60 reference/schema.graphql\n\n"
              % (endpoint, datetime.date.today().isoformat()))
    out = header + "schema {\n  query: %s\n" % q["name"]
    if m:
        out += "  mutation: %s\n" % m["name"]
    if s:
        out += "  subscription: %s\n" % s["name"]
    out += "}\n\n"
    for d in sorted(schema["directives"], key=lambda d: d["name"]):
        if d["name"] in BUILTIN_DIRECTIVES:
            continue
        out += desc(d.get("description")) + "directive @%s%s on %s\n\n" % (
            d["name"], args_block(d["args"], ""), " | ".join(d["locations"]))
    roots = [n for n in (q["name"], m["name"] if m else None, s["name"] if s else None) if n]
    by_name = {t["name"]: t for t in schema["types"]}
    ordered = [by_name[n] for n in roots] + sorted(
        (t for t in schema["types"] if t["name"] not in roots), key=lambda t: t["name"])
    for t in ordered:
        out += print_type(t)
    return out.rstrip() + "\n"


# ---------------------------------------------------------------- diff report
DEF_RE = re.compile(r"^(?:type|input|enum|interface|union|scalar) (\w+)", re.M)
DOC_RE = re.compile(r'"""[\s\S]*?"""')


def type_names(sdl):
    return set(DEF_RE.findall(DOC_RE.sub("", sdl)))


def root_fields(sdl, root):
    m = re.search(r"^type %s \{\n(.*?)^\}" % re.escape(root), DOC_RE.sub("", sdl), re.S | re.M)
    return set(re.findall(r"^  (\w+)", m.group(1), re.M)) if m else set()


def diff_report(old_sdl, new_sdl, roots):
    lines = []

    def section(label, old, new):
        added, removed = sorted(new - old), sorted(old - new)
        if added:
            lines.append("  + %s added (%d): %s" % (label, len(added), ", ".join(added)))
        if removed:
            lines.append("  - %s removed (%d): %s" % (label, len(removed), ", ".join(removed)))

    section("types", type_names(old_sdl), type_names(new_sdl))
    for root in roots:
        section("%s fields" % root, root_fields(old_sdl, root), root_fields(new_sdl, root))
    return lines or ["  no changes in type names or root fields"]


# ------------------------------------------------------------ schema-map blocks
def field_line(f):
    args = ", ".join(input_value(a) for a in f["args"])
    line = "`%s%s -> %s`" % (f["name"], "(%s)" % args if args else "", ref(f["type"]))
    note = clean(f.get("description")).split("\n")[0]
    if f.get("isDeprecated"):
        note = ("DEPRECATED: %s. " % clean(f.get("deprecationReason"))) + note
    return line + (" - " + note if note else "")


def gen_query_roots(schema, by_name):
    root = by_name[schema["queryType"]["name"]]
    return "\n".join("- " + field_line(f) for f in root["fields"] if f["name"] != "_debug")


def gen_mutations(schema, by_name):
    root = by_name[schema["mutationType"]["name"]]
    groups = {label: [] for label, _ in THEMES}
    groups["Other"] = []
    for f in root["fields"]:
        low = f["name"].lower()
        for label, keys in THEMES:
            if any(k in low for k in keys):
                groups[label].append(f)
                break
        else:
            groups["Other"].append(f)
    out = []
    for label in list(dict.fromkeys([l for l, _ in THEMES] + ["Other"])):
        fields = groups[label]
        if not fields:
            continue
        out.append("### %s (%d)\n" % (label, len(fields)))
        out.extend("- " + field_line(f) for f in sorted(fields, key=lambda f: f["name"]))
        out.append("")
    return "\n".join(out).rstrip()


def gen_enums(schema, by_name):
    out = []
    for name in MAP_ENUMS:
        t = by_name.get(name)
        if not t or t["kind"] != "ENUM":
            continue
        values = ", ".join("`%s`" % v["name"] for v in t["enumValues"] if not v.get("isDeprecated"))
        out.append("- **%s**: %s" % (name, values))
    return "\n".join(out)


def update_map(path, schema, by_name):
    if not os.path.exists(path):
        print("schema-map: %s not found, skipping generated blocks" % path)
        return
    text = open(path, encoding="utf-8").read()
    generators = {"query-roots": gen_query_roots, "mutations": gen_mutations, "enums": gen_enums}
    for block, gen in generators.items():
        start, end = "<!-- generated:start:%s -->" % block, "<!-- generated:end:%s -->" % block
        if start not in text or end not in text:
            print("schema-map: markers for '%s' missing, skipped" % block)
            continue
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        text = head + start + "\n" + gen(schema, by_name) + "\n" + end + tail
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("schema-map: generated blocks updated in %s" % path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", default=ENDPOINT)
    ap.add_argument("--out", default=DEFAULT_OUT, help="SDL output path (default: reference/schema.graphql)")
    ap.add_argument("--map", default=DEFAULT_MAP, help="schema-map.md to update (default: reference/schema-map.md)")
    ap.add_argument("--no-map", action="store_true", help="do not touch schema-map.md")
    ap.add_argument("--json", metavar="PATH", help="also write the raw introspection JSON here")
    ap.add_argument("--check", action="store_true", help="fetch and report the diff, write nothing")
    args = ap.parse_args()

    schema = fetch(args.endpoint, os.environ.get("DATACAKE_TOKEN"))
    by_name = {t["name"]: t for t in schema["types"]}
    sdl = to_sdl(schema, args.endpoint)
    roots = [r["name"] for r in (schema["queryType"], schema["mutationType"], schema["subscriptionType"]) if r]

    kinds = {}
    for t in schema["types"]:
        if not t["name"].startswith("__"):
            kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    print("fetched %d types (%s); %s fields: %d; %s fields: %d" % (
        sum(kinds.values()), ", ".join("%s=%d" % kv for kv in sorted(kinds.items())),
        roots[0], len(by_name[roots[0]]["fields"]),
        roots[1] if len(roots) > 1 else "-", len(by_name[roots[1]]["fields"]) if len(roots) > 1 else 0))

    if os.path.exists(args.out):
        old = open(args.out, encoding="utf-8").read()
        print("diff against %s:" % args.out)
        print("\n".join(diff_report(old, sdl, roots)))
    else:
        print("no previous %s" % args.out)

    if args.check:
        print("--check: nothing written")
        return
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(sdl)
    print("wrote %s (%d bytes)" % (args.out, len(sdl.encode("utf-8"))))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"data": {"__schema": schema}}, fh)
        print("wrote %s" % args.json)
    if not args.no_map:
        update_map(args.map, schema, by_name)


if __name__ == "__main__":
    main()
