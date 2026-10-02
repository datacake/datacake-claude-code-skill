#!/usr/bin/env python3
"""Validate the examples in the skill's Markdown files against reference/schema.graphql:

- every ```graphql block is parsed and validated as a GraphQL document (fields, arguments,
  enum values and inline input literals are checked);
- every ```json <InputType> block (for example ```json CreateRuleNGInputType) is parsed as
  JSON and coerced into that GraphQL input type, so variable payloads are checked too.
  Append [] to the type name to validate a list (```json CreateRuleNGActionInputType[]);
- every ```json dashboard / ```json dashboard-device block (a dashboards array) and every
  ```json widget <Type> [device|workspace] block (one widget meta) is checked with the
  structural validator of scripts/dashboards.py (layouts, contexts, required meta).

Usage:
  python3 tools/validate_examples.py                 # all skills/datacake/**/*.md
  python3 tools/validate_examples.py path/to/file.md # specific files
  python3 tools/validate_examples.py --quiet          # only print failures

Blocks fenced as ```graphql-snippet are intentionally partial and are skipped, as are
plain ```json blocks without a type name.
Requires: pip install graphql-core
"""
import argparse
import glob
import json
import os
import re
import sys

try:
    from graphql import GraphQLInputObjectType, GraphQLList, build_schema, parse, validate
    from graphql.error import GraphQLSyntaxError
    from graphql.utilities import coerce_input_value
except ImportError:
    sys.exit("graphql-core is missing: python3 -m pip install --user graphql-core")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "datacake")
SCHEMA = os.path.join(SKILL, "reference", "schema.graphql")
FENCE = re.compile(r"^```graphql[ \t]*\n(.*?)^```", re.S | re.M)
FENCE_JSON = re.compile(r"^```json[ \t]+([A-Za-z_][A-Za-z0-9_]*)(\[\])?[ \t]*\n(.*?)^```", re.S | re.M)
# Dashboard layouts and widgets (reference/dashboards.md) are checked by scripts/dashboards.py:
#   ```json dashboard            a dashboards array for a workspace dashboard
#   ```json dashboard-device     a dashboards array for a device (product) dashboard
#   ```json widget Value [device|workspace]   one widget meta (or a full widget object) of that type
FENCE_DASHBOARD = re.compile(r"^```json[ \t]+dashboard(-device)?[ \t]*\n(.*?)^```", re.S | re.M)
FENCE_WIDGET = re.compile(r"^```json[ \t]+widget[ \t]+([A-Za-z]+)(?:[ \t]+(device|workspace))?[ \t]*\n(.*?)^```", re.S | re.M)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import dashboards  # noqa: E402


def check_dashboard(block, kind):
    """Validate a dashboards array (kind 'dashboard' = workspace, 'product' = device dashboard) offline."""
    try:
        value = json.loads(block)
    except json.JSONDecodeError as exc:
        return ["invalid JSON: %s" % exc]
    if not isinstance(value, list):
        return ["a dashboards block must be a JSON array of tabs"]
    dashboards.normalize(value)
    errors, _ = dashboards.validate(value, kind)
    return errors


def check_widget(block, widget_type, context):
    """Validate one widget meta (or a complete widget object) of the given type."""
    try:
        value = json.loads(block)
    except json.JSONDecodeError as exc:
        return ["invalid JSON: %s" % exc]
    spec = dashboards.WIDGETS.get(widget_type)
    if not spec:
        return ["unknown widget type %s" % widget_type]
    key = "11111111-2222-3333-4444-555555555555"
    if isinstance(value, dict) and "widget" in value and "meta" in value:
        widget = value
        if widget.get("widget") != widget_type:
            return ["widget object is of type %s, fence says %s" % (widget.get("widget"), widget_type)]
        widget.setdefault("layouts", {"lg": {"i": key, "x": 0, "y": 0, "w": spec["size"][0], "h": spec["size"][1]}})
    else:
        widget = {"widget": widget_type, "layouts": {"lg": {"i": key, "x": 0, "y": 0, "w": spec["size"][0], "h": spec["size"][1]}}, "meta": value}
    if context is None:
        context = "workspace" if spec["contexts"] == "workspace" else "device"
    kind = "product" if context == "device" else "dashboard"
    errors, _ = dashboards.validate([{"name": "example", "widgets": {key: widget}}], kind)
    return [e.replace("tab 0 widget 11111111: ", "") for e in errors]


def check_graphql(schema, block):
    """Return a list of problem strings (empty = valid)."""
    try:
        document = parse(block)
    except GraphQLSyntaxError as exc:
        return ["syntax: %s" % exc.message]
    problems = []
    for err in validate(schema, document):
        where = ",".join("L%d" % loc.line for loc in err.locations or [])
        problems.append("%s %s" % (where, err.message))
    return problems


def check_json(schema, type_name, is_list, block):
    """Coerce a JSON payload into a GraphQL input type; return problem strings."""
    type_ = schema.get_type(type_name)
    if not isinstance(type_, GraphQLInputObjectType):
        return ["unknown input type %s" % type_name]
    if is_list:
        type_ = GraphQLList(type_)
    try:
        value = json.loads(block)
    except json.JSONDecodeError as exc:
        return ["invalid JSON: %s" % exc]
    problems = []

    def on_error(path, invalid_value, error):
        problems.append("%s: %s" % (".".join(str(p) for p in path) or "<root>", error.message))

    coerce_input_value(value, type_, on_error)
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--quiet", "-q", action="store_true")
    ap.add_argument("--schema", default=SCHEMA)
    args = ap.parse_args()

    schema = build_schema(open(args.schema, encoding="utf-8").read())
    files = args.files or sorted(glob.glob(os.path.join(SKILL, "**", "*.md"), recursive=True))
    counts = {"graphql": 0, "json": 0, "dashboard": 0, "widget": 0}
    failures = 0
    for path in files:
        text = open(path, encoding="utf-8").read()
        rel = os.path.relpath(path, ROOT)
        blocks = [("graphql", m.start(), m.group(1), None, False) for m in FENCE.finditer(text)]
        blocks += [("json", m.start(), m.group(3), m.group(1), bool(m.group(2))) for m in FENCE_JSON.finditer(text) if m.group(1) != "dashboard"]
        blocks += [("dashboard", m.start(), m.group(2), "product" if m.group(1) else "dashboard", False) for m in FENCE_DASHBOARD.finditer(text)]
        blocks += [("widget", m.start(), m.group(3), m.group(1), m.group(2)) for m in FENCE_WIDGET.finditer(text)]
        for kind, start, block, type_name, is_list in sorted(blocks, key=lambda b: b[1]):
            counts[kind] += 1
            line_no = text.count("\n", 0, start) + 2
            if kind == "graphql":
                problems = check_graphql(schema, block)
                label = next((l.strip() for l in block.splitlines() if l.strip() and not l.strip().startswith("#")), "")
            elif kind == "dashboard":
                problems = check_dashboard(block, type_name)
                label = "json dashboard%s" % ("-device" if type_name == "product" else "")
            elif kind == "widget":
                problems = check_widget(block, type_name, is_list)
                label = "json widget %s%s" % (type_name, " " + is_list if is_list else "")
            else:
                problems = check_json(schema, type_name, is_list, block)
                label = "json %s%s" % (type_name, "[]" if is_list else "")
            if problems:
                failures += 1
                print("FAIL %s:%d  %s" % (rel, line_no, label[:70]))
                for p in problems:
                    print("     %s" % p)
            elif not args.quiet:
                print("ok   %s:%d  %s" % (rel, line_no, label[:70]))
    print("\n%d graphql, %d json, %d dashboard and %d widget blocks checked, %d failed" % (
        counts["graphql"], counts["json"], counts["dashboard"], counts["widget"], failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
