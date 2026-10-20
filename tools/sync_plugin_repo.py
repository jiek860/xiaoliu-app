# -*- coding: utf-8 -*-
"""Publish the signed plugin repository into the main GitHub tree.

Source of truth: ``modules_repo/`` (private signing workspace).
Public mirror: ``plugin_repo/`` (tracked by the main repository and fetched
from raw.githubusercontent.com).

Only files explicitly listed in the signed manifest are copied. The command
refuses to publish if any signature or sha256 check fails, and never copies
``.git``, keys, caches or user data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
SOURCE = os.path.join(BASE, "modules_repo")
DEST = os.path.join(BASE, "plugin_repo")
MANIFEST = "manifest.json"


def _safe_name(name):
    raw = str(name or "")
    if (not raw or raw != os.path.basename(raw) or "/" in raw
            or "\\" in raw or ":" in raw):
        return None
    return raw


def _load_manifest(source):
    path = os.path.join(source, MANIFEST)
    data = json.load(open(path, encoding="utf-8-sig"))
    if not isinstance(data, list) or not data:
        raise ValueError("manifest.json must be a non-empty list")
    return data


def verify_source(source=SOURCE):
    from core.plugin_signer import PluginSigner

    class Trunk:
        base = BASE
        config = {}

    signer = PluginSigner(Trunk())
    manifest = _load_manifest(source)
    files = []
    errors = []
    for entry in manifest:
        name = _safe_name(entry.get("file"))
        if not name or not name.endswith(".py"):
            errors.append("invalid manifest filename: %r" % entry.get("file"))
            continue
        path = os.path.join(source, name)
        if not os.path.isfile(path):
            errors.append("missing file: " + name)
            continue
        raw = open(path, "rb").read()
        got = signer.calc_hash_bytes(raw)
        if got != str(entry.get("sha256") or "").lower():
            errors.append("sha256 mismatch: " + name)
            continue
        if not signer.verify_hash(got, entry.get("signature") or ""):
            errors.append("signature mismatch: " + name)
            continue
        files.append((name, path))
    if errors:
        raise ValueError("source repository is not publishable:\n  " + "\n  ".join(errors[:20]))
    return manifest, files


def sync(dest=DEST, source=SOURCE):
    manifest, files = verify_source(source)
    os.makedirs(dest, exist_ok=True)
    expected = set()
    for name, path in files:
        expected.add(name)
        shutil.copy2(path, os.path.join(dest, name))
    shutil.copy2(os.path.join(source, MANIFEST), os.path.join(dest, MANIFEST))
    for name in os.listdir(dest):
        if name.endswith(".py") and name not in expected:
            os.remove(os.path.join(dest, name))
    return {"ok": True, "files": len(files), "dest": dest}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=SOURCE)
    parser.add_argument("--dest", default=DEST)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check:
            manifest, files = verify_source(args.source)
            for name, path in files:
                target = os.path.join(args.dest, name)
                if not os.path.isfile(target):
                    raise ValueError("missing published file: " + name)
                if open(path, "rb").read() != open(target, "rb").read():
                    raise ValueError("published file differs: " + name)
            if open(os.path.join(args.source, MANIFEST), "rb").read() != \
                    open(os.path.join(args.dest, MANIFEST), "rb").read():
                raise ValueError("published manifest differs")
            print("Plugin repository is in sync: %d files" % len(files))
            return 0
        r = sync(args.dest, args.source)
        print("Published %d signed plugin files to %s" % (r["files"], r["dest"]))
        return 0
    except Exception as exc:
        print("Plugin repository sync failed:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
