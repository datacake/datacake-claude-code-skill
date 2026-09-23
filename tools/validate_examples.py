#!/usr/bin/env python3
"""Validate the examples in the skill's Markdown files against reference/schema.graphql:

- every ```graphql block is parsed and validated as a GraphQL document (fields, arguments,
  enum values and inline input literals are checked);
- every ```json <InputType> block (for example ```json CreateRuleNGInputType) is parsed as
  JSON and coerced into that GraphQL input type, so variable payloads are checked too.
  Append [] to the type name to validate a list (```json CreateRuleNGActionInputType[]).

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
    counts = {"graphql": 0, "json": 0}
    failures = 0
    for path in files:
        text = open(path, encoding="utf-8").read()
        rel = os.path.relpath(path, ROOT)
        blocks = [("graphql", m.start(), m.group(1), None, False) for m in FENCE.finditer(text)]
        blocks += [("json", m.start(), m.group(3), m.group(1), bool(m.group(2))) for m in FENCE_JSON.finditer(text)]
        for kind, start, block, type_name, is_list in sorted(blocks, key=lambda b: b[1]):
            counts[kind] += 1
            line_no = text.count("\n", 0, start) + 2
            if kind == "graphql":
                problems = check_graphql(schema, block)
                label = next((l.strip() for l in block.splitlines() if l.strip() and not l.strip().startswith("#")), "")
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
    print("\n%d graphql blocks and %d json blocks checked, %d failed" % (counts["graphql"], counts["json"], failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
