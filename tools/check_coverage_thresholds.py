# -*- coding: utf-8 -*-
"""Module-level coverage ratchet for coverage.py JSON reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _pct(summary):
    total = int(summary.get("num_statements") or 0)
    covered = int(summary.get("covered_lines") or 0)
    return (covered * 100.0 / total) if total else 100.0


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise SystemExit("cannot read coverage JSON %s: %s" % (path, exc)) from exc


def check(coverage, thresholds):
    failures = []
    warnings = []
    files = coverage.get("files") or {}
    totals = coverage.get("totals") or {}
    global_min = float((thresholds.get("global") or {}).get("minimum", 0))
    total_pct = float(totals.get("percent_covered") or 0)
    if total_pct + 1e-9 < global_min:
        failures.append("global coverage %.2f%% < %.2f%%" % (total_pct, global_min))

    for rel, minimum in (thresholds.get("critical_modules") or {}).items():
        item = files.get(rel) or files.get(rel.replace("/", "\\"))
        if not item:
            warnings.append("critical module not present in report: %s" % rel)
            continue
        actual = _pct(item.get("summary") or {})
        if actual + 1e-9 < float(minimum):
            failures.append("%s %.2f%% < %.2f%%" % (rel, actual, minimum))

    for prefix, minimum in (thresholds.get("directory_minimums") or {}).items():
        matched = []
        for rel, item in files.items():
            norm = rel.replace("\\", "/")
            if norm == prefix or norm.startswith(prefix.rstrip("/") + "/"):
                matched.append(item)
        if not matched:
            warnings.append("directory not present in report: %s" % prefix)
            continue
        statements = sum(int(x.get("summary", {}).get("num_statements") or 0)
                         for x in matched)
        covered = sum(int(x.get("summary", {}).get("covered_lines") or 0)
                      for x in matched)
        actual = (covered * 100.0 / statements) if statements else 100.0
        if actual + 1e-9 < float(minimum):
            failures.append("%s %.2f%% < %.2f%%" % (prefix, actual, minimum))
    return failures, warnings, total_pct


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", default="coverage.json")
    parser.add_argument("--thresholds", default=str(BASE / "coverage_thresholds.json"))
    args = parser.parse_args(argv)
    coverage = _load_json(args.coverage)
    thresholds = _load_json(args.thresholds)
    failures, warnings, total = check(coverage, thresholds)
    print("Coverage ratchet: total %.2f%%" % total)
    for warning in warnings:
        print("WARN:", warning)
    if failures:
        print("Coverage ratchet failed:")
        for failure in failures:
            print(" -", failure)
        return 1
    print("Coverage ratchet passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
