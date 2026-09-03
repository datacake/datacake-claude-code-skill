#!/usr/bin/env python3
"""Validate every ```graphql code block in the skill's Markdown files against
reference/schema.graphql.

Usage:
  python3 tools/validate_examples.py                 # all skills/datacake/**/*.md
  python3 tools/validate_examples.py path/to/file.md # specific files
  python3 tools/validate_examples.py --quiet          # only print failures

Blocks fenced as ```graphql-snippet are intentionally partial and are skipped.
Requires: pip install graphql-core
"""
import argparse
import glob
import os
import re
import sys

try:
    from graphql import build_schema, parse, validate
    from graphql.error import GraphQLSyntaxError
except ImportError:
    sys.exit("graphql-core is missing: python3 -m pip install --user graphql-core")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "datacake")
SCHEMA = os.path.join(SKILL, "reference", "schema.graphql")
FENCE = re.compile(r"^```graphql[ \t]*\n(.*?)^```", re.S | re.M)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--quiet", "-q", action="store_true")
    ap.add_argument("--schema", default=SCHEMA)
    args = ap.parse_args()

    schema = build_schema(open(args.schema, encoding="utf-8").read())
    files = args.files or sorted(glob.glob(os.path.join(SKILL, "**", "*.md"), recursive=True))
    total = failures = 0
    for path in files:
        text = open(path, encoding="utf-8").read()
        for match in FENCE.finditer(text):
            total += 1
            block = match.group(1)
            line_no = text.count("\n", 0, match.start()) + 2
            rel = os.path.relpath(path, ROOT)
            try:
                document = parse(block)
            except GraphQLSyntaxError as exc:
                failures += 1
                print("FAIL %s:%d syntax: %s" % (rel, line_no, exc.message))
                continue
            errors = validate(schema, document)
            if errors:
                failures += 1
                print("FAIL %s:%d" % (rel, line_no))
                for err in errors:
                    where = ",".join("L%d" % (line_no + loc.line - 1) for loc in err.locations or [])
                    print("     %s %s" % (where, err.message))
            elif not args.quiet:
                first = next((l.strip() for l in block.splitlines() if l.strip() and not l.strip().startswith("#")), "")
                print("ok   %s:%d  %s" % (rel, line_no, first[:70]))
    print("\n%d graphql blocks checked, %d failed" % (total, failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
