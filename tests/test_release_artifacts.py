# -*- coding: utf-8 -*-
"""Artifact manifest and sensitive-file verification tests."""
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.verify_artifact_manifest import main as verify_main  # noqa: E402


def _manifest(root):
    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "artifact-manifest.json":
            rows.append({"path": p.relative_to(root).as_posix(),
                         "size": p.stat().st_size,
                         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    (root / "artifact-manifest.json").write_text(
        json.dumps({"commit": "abc", "files": rows}), encoding="utf-8")


def test_artifact_manifest_roundtrip(tmp_path):
    (tmp_path / "xiao6.exe").write_bytes(b"MZfake")
    _manifest(tmp_path)
    assert verify_main(["--dist", str(tmp_path)]) == 0


def test_artifact_tamper_is_rejected(tmp_path):
    (tmp_path / "xiao6.exe").write_bytes(b"MZfake")
    _manifest(tmp_path)
    (tmp_path / "xiao6.exe").write_bytes(b"MZtampered")
    assert verify_main(["--dist", str(tmp_path)]) == 1


def test_sensitive_file_is_rejected(tmp_path):
    (tmp_path / "xiao6.exe").write_bytes(b"MZfake")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    _manifest(tmp_path)
    assert verify_main(["--dist", str(tmp_path)]) == 1


def test_zero_byte_file_size_is_checked_correctly(tmp_path):
    (tmp_path / "empty.py").write_bytes(b"")
    _manifest(tmp_path)
    assert verify_main(["--dist", str(tmp_path)]) == 0


def test_certifi_ca_bundle_is_not_treated_as_private_key(tmp_path):
    ca = tmp_path / "_internal" / "certifi" / "cacert.pem"
    ca.parent.mkdir(parents=True)
    ca.write_text("PUBLIC CA BUNDLE", encoding="utf-8")
    _manifest(tmp_path)
    assert verify_main(["--dist", str(tmp_path)]) == 0
