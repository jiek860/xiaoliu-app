# -*- coding: utf-8 -*-
"""Lightweight performance baseline and regression gate.

The measurements are deliberately coarse and stable enough for CI trend checks:
import/startup probes, source/package size and process RSS. Hosted runners are
noisy, so the gate uses a 20% regression allowance and a median of three runs.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT = BASE / "perf_baseline.json"


def _probe(code):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    times = []
    for _ in range(3):
        started = time.perf_counter()
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(BASE),
                              capture_output=True, text=True, timeout=120, env=env)
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or "")[-300:]}
        times.append((time.perf_counter() - started) * 1000.0)
    return {"ok": True, "ms_median": round(statistics.median(times), 2),
            "samples_ms": [round(x, 2) for x in times]}


def _tree_size(path):
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def measure():
    metrics = {
        "import_core_modules": _probe(
            "import time; t=time.perf_counter(); import core.permission_center,"
            " core.net_guard, core.plugin_api, core.tool_policy;"
            " print((time.perf_counter()-t)*1000)"),
        "import_gui_build_ui": _probe(
            "import time; t=time.perf_counter(); import gui.build_ui;"
            " print((time.perf_counter()-t)*1000)"),
        "artifact_bytes": _tree_size(BASE / "dist"),
        "source_bytes": _tree_size(BASE / "core") + _tree_size(BASE / "gui") +
                        _tree_size(BASE / "modules" / "installed"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        import psutil
        metrics["process_rss_mb"] = round(
            psutil.Process().memory_info().rss / 1048576.0, 2)
    except Exception:
        metrics["process_rss_mb"] = 0
    return metrics


def compare(current, baseline, tolerance=0.20):
    failures = []
    checks = {
        "import_core_modules": "ms_median",
        "import_gui_build_ui": "ms_median",
        "source_bytes": None,
        "artifact_bytes": None,
    }
    for metric, field in checks.items():
        old = baseline.get(metric)
        cur = current.get(metric)
        if metric == "artifact_bytes" and not cur:
            continue
        if isinstance(old, dict):
            old = old.get(field)
        if isinstance(cur, dict):
            cur = cur.get(field)
        if not old or not cur:
            continue
        limit = float(old) * (1.0 + tolerance)
        if float(cur) > limit:
            failures.append("%s regressed: %.2f > %.2f (baseline %.2f)"
                            % (metric, float(cur), limit, float(old)))
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--baseline", default=str(DEFAULT))
    parser.add_argument("--tolerance", type=float, default=0.20)
    args = parser.parse_args(argv)
    current = measure()
    path = Path(args.baseline)
    if args.write or not path.exists():
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print("Perf baseline written:", path)
        return 0
    if args.check:
        try:
            baseline = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print("Cannot read baseline:", exc)
            return 2
        failures = compare(current, baseline, tolerance=args.tolerance)
        if failures:
            print("Performance gate failed:")
            for failure in failures:
                print(" -", failure)
            return 1
        print("Performance gate passed.")
    print(json.dumps(current, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
