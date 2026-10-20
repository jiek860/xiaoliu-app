# -*- coding: utf-8 -*-
"""GitHub Actions supply-chain and isolation policy.

This is intentionally a repository gate, not a substitute for branch
protection. It catches the common mistakes that make workflow checks
unreliable: tag-pinned actions, writable default tokens, missing timeouts,
missing concurrency groups, or workflows that never run for pull requests.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs PyYAML
    print("PyYAML is required: python -m pip install PyYAML==6.0.3 -i https://pypi.tuna.tsinghua.edu.cn/simple")
    raise SystemExit(2) from None

BASE = Path(__file__).resolve().parent.parent
WORKFLOWS = BASE / ".github" / "workflows"
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-fA-F]{40}$")


def _on_value(doc):
    # PyYAML follows YAML 1.1 and turns the unquoted key on into True.
    if "on" in doc:
        return doc["on"]
    return doc.get(True)


def _iter_steps(job):
    steps = job.get("steps")
    return steps if isinstance(steps, list) else []


def _job_pip_installs(job):
    return any("pip " + "install" in str(s.get("run") or "")
               for s in _iter_steps(job))


def _has_pip_cache(job):
    for step in _iter_steps(job):
        uses = str(step.get("uses") or "")
        if "actions/setup-python@" in uses:
            with_ = step.get("with") or {}
            if with_.get("cache") == "pip":
                return True
        if "actions/cache@" in uses:
            return True
    return False


def validate_file(path: Path):
    errors = []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ["%s: YAML parse failed: %s" % (path.name, exc)]
    if not isinstance(doc, dict):
        return ["%s: workflow root must be an object" % path.name]

    on = _on_value(doc)
    if not isinstance(on, (dict, list, str)):
        errors.append("%s: missing or invalid on: trigger" % path.name)
    elif not (isinstance(on, dict) and "pull_request" in on) and on != "pull_request":
        if "# ci-policy: no-pull-request" not in path.read_text(encoding="utf-8"):
            errors.append("%s: workflow must run on pull_request (or declare "
                          "# ci-policy: no-pull-request)" % path.name)

    perms = doc.get("permissions")
    if not isinstance(perms, dict):
        errors.append("%s: top-level permissions must be an explicit mapping" % path.name)
    else:
        if perms.get("contents") not in ("read", "none"):
            errors.append("%s: permissions.contents must be read or none" % path.name)
        if perms.get("write-all") is not None or perms.get("*") == "write":
            errors.append("%s: write-all permissions are forbidden" % path.name)

    if "concurrency" not in doc:
        errors.append("%s: missing top-level concurrency" % path.name)

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        errors.append("%s: no jobs defined" % path.name)
        return errors

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            errors.append("%s/%s: job must be an object" % (path.name, job_id))
            continue
        if "timeout-minutes" not in job:
            errors.append("%s/%s: missing timeout-minutes" % (path.name, job_id))
        if "runs-on" not in job:
            errors.append("%s/%s: missing runs-on" % (path.name, job_id))
        if "uses" in job:
            uses = str(job.get("uses") or "")
            if not PINNED_ACTION.match(uses):
                errors.append("%s/%s: reusable workflow must be pinned to a SHA: %s"
                              % (path.name, job_id, uses))
        if _job_pip_installs(job) and not _has_pip_cache(job):
            errors.append(("%s/%s: pip " + "install requires actions/setup-python cache: pip "
                           "or actions/cache") % (path.name, job_id))
        for idx, step in enumerate(_iter_steps(job)):
            uses = str(step.get("uses") or "")
            if uses and not PINNED_ACTION.match(uses):
                errors.append("%s/%s step %d: action is not pinned to a 40-char SHA: %s"
                              % (path.name, job_id, idx + 1, uses))
            run = str(step.get("run") or "")
            if "pull_request_target" in run:
                errors.append("%s/%s step %d: pull_request_target is forbidden"
                              % (path.name, job_id, idx + 1))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflows", default=str(WORKFLOWS))
    args = parser.parse_args(argv)
    root = Path(args.workflows)
    files = sorted(root.glob("*.yml")) + sorted(root.glob("*.yaml"))
    if not files:
        print("No workflow files found in", root)
        return 2
    errors = []
    for path in files:
        errors.extend(validate_file(path))
    if errors:
        print("Workflow security policy failed:")
        for err in errors:
            print(" -", err)
        return 1
    print("Workflow security policy passed (%d workflows)." % len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
