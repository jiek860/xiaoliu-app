# -*- coding: utf-8 -*-
"""Verify the public GitHub plugin mirror.

Checks:
  * every manifest entry has a safe single-level .py filename;
  * sha256 matches the published file;
  * RSA signature verifies with the release public key;
  * no unreferenced .py files are published;
  * published files match modules/installed when that source exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

REPO = os.path.join(BASE, "plugin_repo")
INSTALLED = os.path.join(BASE, "modules", "installed")


def main():
    from core.plugin_signer import PluginSigner

    class Trunk:
        base = BASE
        config = {}

    manifest_path = os.path.join(REPO, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("missing plugin_repo/manifest.json")
        return 1
    try:
        manifest = json.load(open(manifest_path, encoding="utf-8-sig"))
    except Exception as exc:
        print("invalid manifest:", exc)
        return 1
    if not isinstance(manifest, list) or not manifest:
        print("manifest must be a non-empty list")
        return 1
    signer = PluginSigner(Trunk())
    expected = set()
    errors = []
    for entry in manifest:
        name = str(entry.get("file") or "")
        if (not name or name != os.path.basename(name) or "/" in name
                or "\\" in name or not name.endswith(".py")):
            errors.append("invalid filename: %r" % name)
            continue
        expected.add(name)
        path = os.path.join(REPO, name)
        if not os.path.isfile(path):
            errors.append("missing: " + name)
            continue
        raw = open(path, "rb").read()
        got = hashlib.sha256(raw).hexdigest()
        if got != str(entry.get("sha256") or "").lower():
            errors.append("sha256 mismatch: " + name)
            continue
        if not signer.verify_hash(got, entry.get("signature") or ""):
            errors.append("signature mismatch: " + name)
            continue
        installed = os.path.join(INSTALLED, name)
        if os.path.isfile(installed) and open(installed, "rb").read() != raw:
            errors.append("differs from modules/installed: " + name)
    for name in os.listdir(REPO):
        if name.endswith(".py") and name not in expected:
            errors.append("unreferenced plugin file: " + name)
    if errors:
        print("plugin repo verification failed:")
        for err in errors[:50]:
            print(" -", err)
        return 1
    print("Plugin repo verified: %d signed files" % len(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
