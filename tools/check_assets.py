#!/usr/bin/env python3
"""Offline check of the brand assets bundled with the skill.

Usage:
  python3 tools/check_assets.py

Lists every file that reference/branding.md expects in skills/datacake/assets/brand/,
reports size and (for SVG/PNG) dimensions, and exits non-zero when a required file is missing.
"""
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "skills", "datacake", "assets", "brand")
REQUIRED = ["datacake-logo-black.svg", "datacake-logo-white.svg", "datacake-mark-black.svg", "datacake-mark-white.svg", "favicon.png"]
OPTIONAL = ["icon-1024.png", "adaptive-icon.png", "splash-icon.png"]
MAX_TOTAL = 400 * 1024


def dims(path):
    with open(path, "rb") as fh:
        head = fh.read(4096)
    if path.endswith(".png") and head[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", head[16:24])
        return "%dx%d" % (w, h)
    if path.endswith(".svg"):
        m = re.search(rb'viewBox="([^"]+)"', head)
        return ("viewBox " + m.group(1).decode()) if m else "no viewBox"
    return ""


def main():
    if not os.path.isdir(BRAND):
        sys.exit("missing directory %s" % BRAND)
    missing, total = [], 0
    for name in REQUIRED + OPTIONAL:
        path = os.path.join(BRAND, name)
        req = name in REQUIRED
        if os.path.exists(path):
            size = os.path.getsize(path)
            total += size
            print("OK   %-26s %7d B  %s" % (name, size, dims(path)))
        else:
            print("%s %-26s (%s)" % ("MISS" if req else "opt ", name, "required" if req else "optional, mobile only"))
            if req:
                missing.append(name)
    extra = sorted(f for f in os.listdir(BRAND) if f not in REQUIRED + OPTIONAL and f != "README.md" and not f.startswith("."))
    if extra:
        print("unexpected files (not referenced by the skill): %s" % ", ".join(extra))
    print("total %d KB%s" % (total // 1024, "  (over %d KB budget)" % (MAX_TOTAL // 1024) if total > MAX_TOTAL else ""))
    if missing:
        print("missing required: %s" % ", ".join(missing))
        sys.exit(1)


if __name__ == "__main__":
    main()
