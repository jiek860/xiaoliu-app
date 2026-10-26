# -*- coding: utf-8 -*-
"""冻结版守卫（v25.2.32）—— Feature / 模块 / 按钮 / 覆盖率门槛只许降不许升

背景
----
产品的问题不是功能不够，而是每个功能都停在 60 分。冻结一个版本，
先把 10 条主链路做到 90 分；冻结期内只允许修 Bug、补测试、撤按钮。

这个脚本把冻结开始时的事实写成基线，之后：
    · Feature 数不能增加（一进一出也必须先删再报）
    · core/ 与 gui/ 的 .py 文件数不能增加（允许重构替换，不允许加新模块）
    · 按钮预算不能增加（与 check_buttons.py 互补）
    · 覆盖率门槛不能下调（与 coverage_thresholds.json 互补）
    · CHANGELOG 当前版本节不能出现“新增功能”标题

用法
----
    py -3 tools\\check_feature_freeze.py            # 检查（默认）
    py -3 tools\\check_feature_freeze.py --explain  # 打印当前与基线
    py -3 tools\\check_feature_freeze.py --init     # 首次建立基线
    py -3 tools\\check_feature_freeze.py --rebase   # 锁定下降后的新基线
    py -3 tools\\check_feature_freeze.py --rebase --force  # 确需提升时

冻结结束后把 freeze_baseline.json 的 active 改成 false，守卫自动跳过。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BASELINE = BASE / "tools" / "freeze_baseline.json"
FREEZE_UNTIL = "2026-11-23"


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _py_files(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(
        p.relative_to(BASE).as_posix()
        for p in folder.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _feature_ids():
    sys.path.insert(0, str(BASE))
    from core.feature_registry import FEATURES

    return sorted(FEATURES)


def _coverage_snapshot():
    raw = _read_json(BASE / "coverage_thresholds.json")
    return {
        "global": raw.get("global") or {},
        "critical_modules": raw.get("critical_modules") or {},
        "directory_minimums": raw.get("directory_minimums") or {},
    }


def snapshot():
    """当前仓库的冻结相关事实。"""
    budget = _read_json(BASE / "tools" / "button_budget.json")
    ids = _feature_ids()
    try:
        from core.version import __version__
        version = __version__
    except Exception:
        version = "unknown"
    return {
        "version": version,
        "features": len(ids),
        "feature_ids": ids,
        "core_files": len(_py_files(BASE / "core")),
        "gui_files": len(_py_files(BASE / "gui")),
        "test_files": len(list((BASE / "tests").glob("test_*.py"))),
        "button_total": int(budget.get("total") or 0),
        "button_widgets": int(budget.get("_widgets") or budget.get("total") or 0),
        "coverage_thresholds": _coverage_snapshot(),
    }


def _flatten(prefix, node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            label = "%s.%s" % (prefix, key) if prefix else str(key)
            _flatten(label, value, out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out[prefix] = float(node)


def compare(current, baseline):
    """返回 (errors, warnings)。只比较冻结相关的四项 + 覆盖率门槛。"""
    errors = []
    warnings = []

    if current.get("features", 0) > baseline.get("features", 0):
        errors.append("Feature 数增加：%d > %d"
                      % (current.get("features", 0),
                         baseline.get("features", 0)))

    new_ids = sorted(set(current.get("feature_ids") or [])
                     - set(baseline.get("feature_ids") or []))
    if new_ids:
        warnings.append("Feature id 有变化（确认是“一进一出”）：%s"
                        % "、".join(new_ids))

    for key, label in (("core_files", "core"), ("gui_files", "gui")):
        if current.get(key, 0) > baseline.get(key, 0):
            errors.append("%s/ 模块文件数增加：%d > %d"
                          % (label, current.get(key, 0),
                             baseline.get(key, 0)))

    if current.get("button_total", 0) > baseline.get("button_total", 0):
        errors.append("按钮预算增加：%d > %d"
                      % (current.get("button_total", 0),
                         baseline.get("button_total", 0)))
    if current.get("button_widgets", 0) > baseline.get("button_widgets", 0):
        errors.append("估算控件数增加：%d > %d"
                      % (current.get("button_widgets", 0),
                         baseline.get("button_widgets", 0)))

    if current.get("test_files", 0) < baseline.get("test_files", 0):
        warnings.append("测试文件数减少：%d < %d"
                        % (current.get("test_files", 0),
                           baseline.get("test_files", 0)))

    base_cov = {}
    cur_cov = {}
    _flatten("", baseline.get("coverage_thresholds") or {}, base_cov)
    _flatten("", current.get("coverage_thresholds") or {}, cur_cov)
    for key in sorted(base_cov):
        if key not in cur_cov:
            errors.append("覆盖率门槛被删除：%s" % key)
        elif cur_cov[key] + 1e-9 < base_cov[key]:
            errors.append("覆盖率门槛被下调：%s %.1f < %.1f"
                          % (key, cur_cov[key], base_cov[key]))

    return errors, warnings


def check_changelog():
    """当前版本节不允许出现“新增功能”标题。"""
    path = BASE / "CHANGELOG.md"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("## v")), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## v")), len(lines))
    hits = []
    for i in range(start, end):
        text = lines[i].strip()
        if text.startswith("**新增功能") or text.startswith("### 新增功能") \
                or text.startswith("## 新增功能"):
            hits.append(str(i + 1))
    if not hits:
        return []
    return ["CHANGELOG 当前版本出现“新增功能”（行 %s）" % "、".join(hits)]


def load_baseline(path=None):
    return _read_json(path or BASELINE)


def write_baseline(data, path=None):
    target = Path(path or BASELINE)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def init(force=False):
    if BASELINE.exists() and not force:
        print("[X] 冻结基线已存在：%s" % BASELINE)
        print("    要重建请加 --force（会覆盖当前基线）")
        return 1
    current = snapshot()
    current.update({
        "_说明": "冻结版基线：Feature/模块/按钮/覆盖率门槛只许降不许升",
        "active": True,
        "created": date.today().isoformat(),
        "freeze_until": FREEZE_UNTIL,
    })
    write_baseline(current)
    print("✅ 已建立冻结基线（%s）" % BASELINE)
    print("   Feature %d / core %d / gui %d / 按钮 %d / 测试文件 %d"
          % (current["features"], current["core_files"], current["gui_files"],
             current["button_total"], current["test_files"]))
    return 0


def rebase(baseline, force=False):
    current = snapshot()
    errors, warnings = compare(current, baseline)
    if errors and not force:
        print("[X] 冻结期内基线只允许下降，不能上升：")
        for item in errors:
            print("   · %s" % item)
        print("    确需提升请加 --force，并在提交说明里写清理由")
        return 1
    data = dict(current)
    data.update({
        "_说明": baseline.get("_说明") or "冻结版基线",
        "active": baseline.get("active", True),
        "created": baseline.get("created") or date.today().isoformat(),
        "freeze_until": baseline.get("freeze_until") or FREEZE_UNTIL,
        "rebased": date.today().isoformat(),
    })
    write_baseline(data)
    print("✅ 已锁定新基线：Feature %d / core %d / gui %d / 按钮 %d"
          % (data["features"], data["core_files"], data["gui_files"],
             data["button_total"]))
    if warnings:
        for item in warnings:
            print("   ⚠ %s" % item)
    return 0


def report(current, baseline, errors, warnings):
    print("=" * 72)
    print("冻结守卫（Feature / 模块 / 按钮 / 覆盖率只许降不许升）")
    print("=" * 72)
    print("  指标              当前    基线")
    print("  Feature 数        %4d    %4d"
          % (current.get("features", 0), baseline.get("features", 0)))
    print("  core/ 模块文件数  %4d    %4d"
          % (current.get("core_files", 0), baseline.get("core_files", 0)))
    print("  gui/ 模块文件数   %4d    %4d"
          % (current.get("gui_files", 0), baseline.get("gui_files", 0)))
    print("  按钮预算          %4d    %4d"
          % (current.get("button_total", 0), baseline.get("button_total", 0)))
    print("  测试文件数        %4d    %4d"
          % (current.get("test_files", 0), baseline.get("test_files", 0)))
    print("  冻结截止          %s" % baseline.get("freeze_until", "未设置"))
    print()
    for item in warnings:
        print("  ⚠ %s" % item)
    if errors:
        print("  冻结守卫失败：")
        for item in errors:
            print("   · %s" % item)
        print()
        print("  冻结期内只允许：修 Bug、补测试、撤按钮、改文案、补文档。")
        print("  确需新增入口，请先删一个旧入口（一进一出）。")
        return
    print("冻结基线通过 ✅  当前没有新增 Feature / 模块 / 按钮，门槛未下调")


def main(argv=None):
    parser = argparse.ArgumentParser(description="冻结版守卫")
    parser.add_argument("--check", action="store_true", help="检查（默认）")
    parser.add_argument("--explain", action="store_true", help="打印当前与基线")
    parser.add_argument("--init", action="store_true", help="首次建立基线")
    parser.add_argument("--rebase", action="store_true", help="锁定下降后的基线")
    parser.add_argument("--force", action="store_true", help="强制覆盖或提升基线")
    args = parser.parse_args(argv)

    if args.init:
        return init(force=args.force)
    if not BASELINE.exists():
        print("[X] 没有冻结基线：先跑 py -3 tools\\check_feature_freeze.py --init")
        return 1
    try:
        baseline = load_baseline()
    except Exception as exc:
        print("[X] 读不到冻结基线：%s" % exc)
        return 1
    if not baseline.get("active", True):
        print("冻结已结束（freeze_baseline.json 的 active=false），跳过检查")
        return 0
    if args.rebase:
        return rebase(baseline, force=args.force)

    current = snapshot()
    errors, warnings = compare(current, baseline)
    errors.extend(check_changelog())
    report(current, baseline, errors, warnings)
    if args.explain:
        return 0
    return 1 if errors else 0


if __name__ == "__main__":
    from _console import use_utf8_console

    use_utf8_console()
    sys.exit(main())
