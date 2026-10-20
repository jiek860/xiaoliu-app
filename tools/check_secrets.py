# -*- coding: utf-8 -*-
"""High-confidence secret scanner for tracked files.

GitHub secret scanning remains the authoritative service, but this local gate
keeps contributor machines and PRs from committing obvious credentials even
when repository secret scanning is not enabled yet.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe-live-key", re.compile(r"\bsk_live_[0-9A-Za-z]{20,}\b")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
]

SAFE_MARKERS = (
    "pragma: allowlist secret",
    "example",
    "dummy",
    "fake",
    "placeholder",
    "your_",
    "xxx",
    "***",
    "x6enc:",
    "abcdefghijklmnopqrstuvwx",  # explicit synthetic fixture in tests
)

TEXT_EXTS = {
    ".py", ".pyi", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".txt", ".md", ".bat", ".ps1", ".sh", ".spec",
    ".js", ".ts", ".html", ".sql", ".env", ".example",
}
SKIP_PARTS = {".git", ".venv", ".runtime-venv", ".build-venv", "libs",
              "optional_libs", "node_modules", "__pycache__", "dist", "build",
              "backups", "updates", "staging", "_ci_sim", "_ci_sim2"}


def tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=str(BASE), capture_output=True,
            timeout=20, check=True,
        ).stdout
        paths = [p for p in out.decode("utf-8", "replace").split("\x00") if p]
    except Exception:
        paths = []
    if paths:
        return [BASE / p for p in paths]
    return [p for p in BASE.rglob("*") if p.is_file()]


def _allowed(line: str) -> bool:
    low = line.lower()
    return any(marker in low for marker in SAFE_MARKERS)


def scan_file(path: Path):
    if any(part in SKIP_PARTS for part in path.parts):
        return []
    if path.suffix.lower() not in TEXT_EXTS and path.name not in (".env", ".env.example"):
        return []
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if _allowed(line):
            continue
        for rule, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((rule, path, lineno))
                break
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(BASE))
    args = parser.parse_args(argv)
    root = Path(args.root)
    findings = []
    for path in tracked_files():
        if root not in path.parents and path != root:
            continue
        findings.extend(scan_file(path))
    if findings:
        print("Potential secrets found:")
        for rule, path, lineno in findings:
            try:
                rel = path.relative_to(BASE)
            except ValueError:
                rel = path
            print(" - %s:%s (%s)" % (rel, lineno, rule))
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
