# -*- coding: utf-8 -*-
"""Installed-distribution license inventory and allowlist report.

This is an inventory aid, not legal advice. Unknown or copyleft licenses are
reported for human review before a release.
"""
from __future__ import annotations

import argparse
import json
import re
from importlib import metadata
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _license_text(dist):
    meta = dist.metadata or {}
    parts = []
    for key in ("License", "License-Expression"):
        value = meta.get(key)
        if value:
            parts.append(str(value))
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            parts.append(classifier.split("::")[-1].strip())
    return " | ".join(parts)[:1000]


def classify(text):
    upper = text.upper()
    for item in ("AGPL", "LGPL", "GPL", "MPL", "APACHE", "BSD", "MIT",
                 "PSF", "ISC", "UNLICENSE", "COMMERCIAL", "PROPRIETARY"):
        if item in upper:
            return item
    if re.search(r"\b(?:BSD|MIT|Apache|PSF|ISC|MPL)\b", text, re.I):
        return "UNKNOWN"
    return "UNKNOWN"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="license-report.json")
    parser.add_argument("--strict-unknown", action="store_true")
    args = parser.parse_args(argv)
    policy = json.loads((BASE / "license_allowlist.json").read_text(encoding="utf-8-sig"))
    allowed = policy.get("allowed") or []
    review = policy.get("review_required") or []
    rows = []
    unknown = []
    needs_review = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or "unknown"
        version = dist.version or ""
        text = _license_text(dist)
        kind = classify(text)
        if kind == "UNKNOWN":
            unknown.append(name)
        elif any(kind in x.upper() for x in review):
            needs_review.append(name)
        rows.append({"name": name, "version": version, "license": kind,
                     "license_text": text})
    report = {"allowed_patterns": allowed, "review_required_patterns": review,
              "unknown": sorted(set(unknown)), "needs_review": sorted(set(needs_review)),
              "packages": sorted(rows, key=lambda x: x["name"].lower())}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print("License inventory: %d packages, %d unknown, %d review-required"
          % (len(rows), len(set(unknown)), len(set(needs_review))))
    if needs_review:
        print("Review required:", ", ".join(sorted(set(needs_review))[:30]))
    if args.strict_unknown and unknown:
        print("Unknown licenses:", ", ".join(sorted(set(unknown))[:30]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
