# -*- coding: utf-8 -*-
"""Changed-lines coverage gate backed by coverage.py JSON."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines(base_ref):
    try:
        diff = subprocess.run(
            ["git", "diff", "--ignore-space-at-eol", "--unified=0",
             "--diff-filter=ACMRT", "%s...HEAD" % base_ref,
             "--", "core", "gui", "modules"],
            cwd=str(BASE), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
    except Exception as exc:
        return None, "git diff failed: %s" % exc
    if diff.returncode != 0:
        return None, (diff.stderr or "git diff failed")[-300:]
    current = None
    out = {}
    for line in diff.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].replace("\\", "/")
            out.setdefault(current, set())
            continue
        match = HUNK_RE.match(line or "")
        if not match or not current:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        for lineno in range(start, start + count):
            out[current].add(lineno)
    return out, ""


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", default="coverage.json")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--threshold", type=float, default=70.0)
    parser.add_argument("--require-base", action="store_true")
    args = parser.parse_args(argv)
    changes, error = changed_lines(args.base)
    if changes is None:
        msg = "changed-lines coverage skipped: %s" % error
        print(msg)
        return 1 if args.require_base else 0
    try:
        data = json.loads(Path(args.coverage).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print("cannot read coverage JSON:", exc)
        return 2
    files = data.get("files") or {}
    executable = 0
    covered = 0
    details = []
    for rel, lines in changes.items():
        item = files.get(rel) or files.get(rel.replace("/", "\\"))
        if not item:
            continue
        executed = set(item.get("executed_lines") or [])
        missing = set(item.get("missing_lines") or [])
        for line in lines:
            if line not in executed and line not in missing:
                continue
            executable += 1
            if line in executed:
                covered += 1
            else:
                details.append("%s:%d" % (rel, line))
    pct = covered * 100.0 / executable if executable else 100.0
    print("Changed-lines coverage: %.2f%% (%d/%d)" % (pct, covered, executable))
    if details:
        print("Uncovered changed lines:", ", ".join(details[:40]))
    if pct + 1e-9 < args.threshold:
        print("Changed-lines coverage below %.2f%%" % args.threshold)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
