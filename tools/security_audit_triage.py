# -*- coding: utf-8 -*-
"""Bandit audit triage with stable fingerprints and expiring waivers."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT_WAIVERS = BASE / "security_audit_waivers.json"
DEFAULT_TARGETS = ("core", "gui", "modules/installed")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE).as_posix()
    except ValueError:
        return path.as_posix()


def _context_hash(path: Path, line: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lines = []
    lo = max(0, line - 2)
    hi = min(len(lines), line + 1)
    chunk = "\n".join(re.sub(r"\s+", " ", x).strip() for x in lines[lo:hi])
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16]


def fingerprint(result) -> str:
    path = Path(result.get("filename") or "").resolve()
    rel = _rel(path)
    line = int(result.get("line_number") or 0)
    raw = "%s:%s:%s" % (rel, result.get("test_id") or "?", _context_hash(path, line))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def load_waivers(path: Path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise SystemExit("Invalid waiver file %s: %s" % (path, exc)) from exc
    items = data.get("waivers") if isinstance(data, dict) else data
    return list(items or [])


def waiver_decision(fp: str, waivers):
    for item in waivers:
        if str(item.get("fingerprint") or "") != fp:
            continue
        status = str(item.get("status") or "").lower()
        if status not in ("confirmed_safe", "accepted_risk"):
            return False, "waiver status is not approved: %s" % status
        for field in ("owner", "reason", "expires", "issue"):
            if not str(item.get(field) or "").strip():
                return False, "waiver missing required field: %s" % field
        try:
            expires = dt.date.fromisoformat(str(item["expires"]))
        except ValueError:
            return False, "waiver expires must be YYYY-MM-DD"
        if expires < dt.date.today():
            return False, "waiver expired on %s" % expires.isoformat()
        return True, str(item.get("reason") or "")
    return False, "no matching waiver"


def run_bandit(targets, timeout=180):
    fd, tmp = tempfile.mkstemp(prefix="x6_bandit_", suffix=".json")
    os.close(fd)
    try:
        cmd = [sys.executable, "-m", "bandit", "-r", *targets, "-f", "json", "-o", tmp, "-q"]
        proc = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise SystemExit("Bandit produced no JSON output (exit %s): %s"
                             % (proc.returncode, (proc.stderr or "")[-500:]))
        return json.loads(Path(tmp).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise SystemExit("Bandit is not installed: python -m pip install -r requirements-security.lock -i https://pypi.tuna.tsinghua.edu.cn/simple") from None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", nargs="+", default=list(DEFAULT_TARGETS))
    parser.add_argument("--waivers", default=str(DEFAULT_WAIVERS))
    parser.add_argument("--output", default="security-audit-report.json")
    parser.add_argument("--print-fingerprints", action="store_true")
    args = parser.parse_args(argv)

    data = run_bandit(args.targets)
    waivers = load_waivers(Path(args.waivers))
    findings = []
    failures = []
    for result in data.get("results") or []:
        severity = str(result.get("issue_severity") or "").upper()
        if severity not in ("MEDIUM", "HIGH"):
            continue
        fp = fingerprint(result)
        ok, reason = waiver_decision(fp, waivers)
        row = {
            "fingerprint": fp,
            "severity": severity,
            "test_id": result.get("test_id"),
            "file": _rel(Path(result.get("filename") or "")),
            "line": result.get("line_number"),
            "issue": result.get("issue_text"),
            "waived": ok,
            "waiver_reason": reason,
        }
        findings.append(row)
        if not ok:
            failures.append(row)
        if args.print_fingerprints:
            print("%s  %s  %s:%s  %s" % (fp, severity, row["file"], row["line"], row["test_id"]))

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "targets": list(args.targets),
        "metrics": data.get("metrics", {}).get("_totals", {}),
        "medium_high_findings": findings,
        "unwaived": failures,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    if failures:
        print("Bandit triage failed: %d unwaived medium/high finding(s)." % len(failures))
        for row in failures:
            print(" - %s %s:%s %s: %s" % (row["fingerprint"], row["file"],
                                          row["line"], row["test_id"], row["issue"]))
        print("Run with --print-fingerprints and add an owned, expiring waiver only "
              "after confirming the finding is a false positive or accepted risk.")
        return 1
    print("Bandit triage passed: %d medium/high finding(s), all waived." % len(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
