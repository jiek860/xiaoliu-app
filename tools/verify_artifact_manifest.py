# -*- coding: utf-8 -*-
"""Verify an uploaded Windows artifact by its build-time SHA256 manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SENSITIVE_NAMES = (".env", "config.json", "permissions.json",
                   "network_rules.json", "audit.jsonl")
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args(argv)
    root = Path(args.dist).resolve()
    manifest_path = Path(args.manifest) if args.manifest else root / "artifact-manifest.json"
    if not manifest_path.exists():
        print("artifact manifest missing:", manifest_path)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print("cannot parse manifest:", exc)
        return 2
    failures = []
    expected_paths = set()
    for row in manifest.get("files") or []:
        rel = str(row.get("path") or "").replace("\\", "/")
        expected_paths.add(rel)
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            failures.append("path escapes artifact root: " + rel)
            continue
        if not target.is_file():
            failures.append("missing file: " + rel)
            continue
        actual = sha256(target)
        if actual != str(row.get("sha256") or "").lower():
            failures.append("sha256 mismatch: " + rel)
        if int(row.get("size") or -1) != target.stat().st_size:
            failures.append("size mismatch: " + rel)
    # A few obvious secret-bearing names must never be shipped.
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        low = rel.lower()
        if path.name.lower() in SENSITIVE_NAMES or low.endswith(SENSITIVE_SUFFIXES):
            if "公钥" in path.name or path.name.lower().endswith("public.pem"):
                continue
            failures.append("sensitive file in artifact: " + rel)
        if rel == "artifact-manifest.json":
            continue
        if rel not in expected_paths:
            failures.append("file not covered by manifest: " + rel)
    if failures:
        print("Artifact verification failed:")
        for failure in failures[:80]:
            print(" -", failure)
        return 1
    print("Artifact verification passed: %d files, commit %s"
          % (len(expected_paths), manifest.get("commit", "?")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
