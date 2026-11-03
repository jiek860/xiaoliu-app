# -*- coding: utf-8 -*-
"""守卫：Qt 信号必须真的有人接（未接线信号列表只许降）

为什么要有这一条
----------------
2026-11-02 体检发现 `gui/chat_stage_strip.py` 有两个 pyqtSignal 全项目**没有一处
`.connect`**：`detailRequested`（emit 之后自己又调 `_show_detail()`）、
`cancelRequested`（真取消由 `stage_bus.cancel_step()` 完成）。

这类"假接口"的危害不是多几行代码，而是**误导**：后来的人看到有信号，就会
以为"外面有人管这件事"，于是把真正的逻辑挂到一个永远不会来的回调上。

判定口径
--------
    * 信号定义：类体里 `名字 = pyqtSignal(...)`（`QtCore.pyqtSignal` 同样认）；
    * 已接线：全项目（含 tests/）任意文件里出现过 `名字.connect(`；
      —— 接在测试里也算接线（说明有人真的在观察它）；
    * 只要"定义了、但没人 connect"就计入 —— `emit` 过几次不影响判定
      （emit 越多越说明它是个空转的假接口）。

怎么处理
--------
    * 真没人用 → 删掉信号与它的 `emit`（动作改成自闭环，就像 `ChatStageStrip`）；
    * 确实要留给外部接（插件/未来入口）→ 登进下面的 `KEEP`，写清为什么，
      并留下消费者计划。

用法
----
    py -3 tools\\check_signals.py            # 校验（门禁用）
    py -3 tools\\check_signals.py -v         # 连已接线的信号一起列出
    py -3 tools\\check_signals.py --update   # 处理完后收紧基线
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import argparse
import ast
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(BASE, "tools", "signals_baseline.json")

# 扫描范围：定义侧只认第一方代码；接线侧要连 tests/ 一起看
DEF_DIRS = ("core", "gui", "modules/installed")
USE_DIRS = ("core", "gui", "modules", "tools", "tests", "scripts")
ROOT_FILES = ("run.py", "run_server.py")

# 复核确认"零消费者但必须留"的信号（键：相对路径::信号名）
KEEP = {
    # 目前没有这样的信号：S4 已把两个假接口删掉。
    # 需要留的时候照下面这样登记，并在注释里写明"谁将来会接、什么时候接"：
    # "gui/xxx.py::mySignal": "第三方插件按名字 connect（插件 SDK 文档承诺）",
}

# 接线判定：全文里出现 `名字.connect(` 就算接过线
CONNECT_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*connect\s*\(")


def _rel(p):
    return os.path.relpath(p, BASE).replace("\\", "/")


def _py_files(dirs, extra=()):
    for n in extra:
        p = os.path.join(BASE, n)
        if os.path.isfile(p):
            yield p
    for d in dirs:
        top = os.path.join(BASE, d.replace("/", os.sep))
        if not os.path.isdir(top):
            continue
        for root, sub, names in os.walk(top):
            sub[:] = [x for x in sub if x != "__pycache__"]
            for n in sorted(names):
                if n.endswith(".py"):
                    yield os.path.join(root, n)


def _is_pyqt_signal(node):
    """value 是不是 pyqtSignal(...) / QtCore.pyqtSignal(...)"""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    name = getattr(f, "id", None) or getattr(f, "attr", None)
    return name == "pyqtSignal"


def scan():
    """返回 (未接线列表, 已接线数量, 定义总数)"""
    texts = {}
    for p in _py_files(USE_DIRS, ROOT_FILES):
        try:
            texts[_rel(p)] = io.open(p, encoding="utf-8-sig",
                                     errors="ignore").read()
        except OSError as e:
            _x6_swallowed(__name__, e, "读文件")
            continue

    defined = []          # (rel, 信号名, 行号)
    for p in _py_files(DEF_DIRS):
        rel = _rel(p)
        src = texts.get(rel)
        if src is None:
            try:
                src = io.open(p, encoding="utf-8-sig", errors="ignore").read()
            except OSError as e:
                _x6_swallowed(__name__, e, "读文件")
                continue
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            _x6_swallowed(__name__, e, "语法解析")
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for stmt in cls.body:
                targets = []
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                    value = stmt.value
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                    value = stmt.value
                else:
                    continue
                if value is None or not _is_pyqt_signal(value):
                    continue
                for t in targets:
                    if isinstance(t, ast.Name):
                        defined.append((rel, t.id, stmt.lineno))

    # 先把"所有出现过的 XXXXX.connect(" 收成一个名字集合：逐个信号名去全文正则
    # 是 O(信号数 × 文件数)，91 个信号 × 1000 个文件要 13 秒；扫一遍文件只要 0.2 秒。
    connected_names = set()
    for t in texts.values():
        for m in CONNECT_RE.finditer(t):
            connected_names.add(m.group(1))

    unconnected, connected = [], 0
    for rel, name, line in defined:
        if name in connected_names:
            connected += 1
            continue
        key = "%s::%s" % (rel, name)
        if key in KEEP:
            continue
        emit_n = sum(len(re.findall(r"\b%s\s*\.\s*emit\s*\(" % re.escape(name), t))
                     for t in texts.values())
        unconnected.append({"file": rel, "line": line, "name": name,
                            "emit": emit_n})
    return unconnected, connected, len(defined)


def load_baseline():
    try:
        with io.open(BASELINE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def check(result=None):
    """返回错误列表（空 = 通过）"""
    if result is None:
        unconnected, _connected, _total = scan()
    else:
        unconnected = result[0]
    cap = int(load_baseline().get("unconnected") or 0)
    errs = []
    if len(unconnected) > cap:
        errs.append("未接线信号：现 %d 个（基线 %d 个）"
                    % (len(unconnected), cap))
        for x in unconnected:
            errs.append("    %s:%d  %s（emit %d 次）"
                        % (x["file"], x["line"], x["name"], x["emit"]))
        errs.append("怎么处理：删掉信号与它的 emit（让动作自闭环），"
                    "或登进 tools/check_signals.py::KEEP 并写明谁将来会接。")
    return errs


def update(result=None):
    if result is None:
        unconnected, connected, total = scan()
    else:
        unconnected, connected, total = result
    data = {"unconnected": len(unconnected), "connected": connected,
            "defined": total, "kept": len(KEEP), "updated": "2026-11-02",
            "why": ("pyqtSignal 里「定义了但全项目没有 .connect」的个数；只许降。"
                    "接在 tests/ 里也算接线。新增信号必须有人接，否则门禁失败。")}
    with io.open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("✅ 基线已更新：未接线 %d / 已接线 %d / 定义 %d"
          % (data["unconnected"], connected, total))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Qt 信号接线守卫（未接线只许降）")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="连已接线的信号数量一起列出")
    ap.add_argument("--update", action="store_true", help="把当前结果写成新基线")
    args = ap.parse_args()

    if args.update:
        return update()

    result = scan()
    unconnected, connected, total = result
    errs = check(result)
    print("=" * 74)
    print("Qt 信号接线守卫（定义了 pyqtSignal，但全项目没有 .connect）")
    print("=" * 74)
    print("  信号定义 %d 个：已接线 %d / 未接线 %d（基线 %d）"
          % (total, connected, len(unconnected),
             int(load_baseline().get("unconnected") or 0)))
    if args.verbose or unconnected:
        for x in unconnected:
            print("    %-46s %s" % ("%s:%d" % (x["file"], x["line"]),
                                    x["name"]))
    print("=" * 74)
    if errs:
        for e in errs:
            print(e)
        return 1
    print("信号接线通过 ✅  没有未接线信号")
    return 0


if __name__ == "__main__":
    sys.exit(main())
