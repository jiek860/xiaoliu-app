# -*- coding: utf-8 -*-
"""重新生成 docs/00 的「3.1 core」模块表（B7，2026-11-02）

为什么要有这个脚本
------------------
`docs/00_产品架构与UI主文档.md` 的 3.1 core 表是 2026-10-25 的快照，手写维护
必然越来越不像代码：行数变了、模块补全了、接线方式换了，表还是旧的。
B7 要给表加「已接线」列 + 把 B3–B6 补齐的 23 个模块标「完整版」，
手改 190 行不现实，所以做成可重跑的生成器。

列的口径
--------
    行数    当前文件实际行数（含注释/文档字符串）
    测试    tests/ 里是否有用例提到这个模块名（启发式，只看名字出现）
    完整度  B3–B6 补齐的 23 个 → **完整版**（按 8 条验收标准交付，见 docs/101）；
            其余仍是 2026-10-25 的启发式：docstring + 有测试 + ≥80 行 各 1 分
    已接线  能力表（core_caps 声明 / 模块自己有 TOOLS）
            主链路（core/pipeline、core/ 其他文件、gui/ 里出现 trunk.call 或名字）
            工具链（tool_caller 能分发 / 在能力表里）
            测试  （tests/ 有对应用例）
            `—` = 四条都没有（判"幽灵模块"的直接依据）

用法
----
    py -3 tools/gen_module_map.py            # 只打印统计，不改文档
    py -3 tools/gen_module_map.py --write    # 重写 docs/00 的 3.1 表
"""
import ast
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(BASE, "core")
DOC = os.path.join(BASE, "docs", "00_产品架构与UI主文档.md")
START = "### 3.1 core（稳定核心"
END = "### 3.2 core/pipeline"

# B3–B6 补齐的 23 个模块（名单与 docs/101 的组 A–E 一一对应）
FULL_VERSION = {
    # B3 记忆
    "memory_organizer": "B3", "memory_archiver": "B3",
    "memory_crypto": "B3", "memory_optimizer": "B3",
    # B4 报告/统计
    "mood_report": "B4", "growth_report": "B4", "stats_report": "B4",
    "data_cleaner": "B4", "dream_system": "B4",
    # B5 自动/兜底
    "local_fallback": "B5", "model_vote": "B5", "group_debate": "B5",
    "startup_optimizer": "B5", "gpu_detector": "B5",
    # B6 录放/流程/市场/迁移/签名/崩溃/脱敏
    "action_recorder": "B6", "agent_flow": "B6", "tool_call_logger": "B6",
    "browser_session": "B6", "personality_market": "B6", "migration": "B6",
    "plugin_signer": "B6", "crash_export": "B6", "sensitive_detector": "B6",
}

SCAN_DIRS = ("core", "core/pipeline", "gui", "gui/mixins", "modules/installed",
             "tests")


def _iter_py(top):
    for root, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                yield os.path.join(root, f)


def _docstring(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return ""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    doc = ast.get_docstring(tree) or ""
    line = (doc.strip().splitlines() or [""])[0].strip()
    return line


def _rel(path):
    return os.path.relpath(path, BASE).replace("\\", "/")


def _read_all():
    """{相对路径: 文本}，只读一遍"""
    out = {}
    for d in SCAN_DIRS:
        top = os.path.join(BASE, d.replace("/", os.sep))
        if not os.path.isdir(top):
            continue
        for path in _iter_py(top):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    out[_rel(path)] = f.read()
            except OSError:
                continue
    return out


def _lines(path):
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _heuristic(has_doc, has_test, n_lines):
    score = int(bool(has_doc)) + int(bool(has_test)) + int(n_lines >= 80)
    return {3: "完整", 2: "基本完整", 1: "部分", 0: "骨架"}[score]


def build_rows():
    texts = _read_all()
    caps = texts.get("core/core_caps.py", "")

    files = [p for p in sorted(_iter_py(CORE), key=_rel)
             if _rel(p).count("/") == 1]      # 3.1 只收 core 顶层
    names = [os.path.basename(p)[:-3] for p in files]

    refs = {n: [] for n in names}          # 名字出现在哪些文件里
    for rel, text in texts.items():
        for n in names:
            if re.search(r"\b%s\b" % re.escape(n), text):
                refs[n].append(rel)

    rows = []
    for path, name in zip(files, names):
        rel = _rel(path)
        doc = _docstring(path)
        n_lines = _lines(path)
        where = refs.get(name, [])
        has_test = any(w.startswith("tests/") for w in where)

        wire = []
        # 能力表：core_caps 里声明过，或模块自己导出 TOOLS
        if ('"mod": "%s"' % name) in caps:
            wire.append("能力表")
        if re.search(r"^TOOLS\s*=", texts.get(rel, ""), re.M):
            wire.append("能力表")
        # 主链路：被 pipeline / 其他 core 文件 / gui 引用
        if any(w.startswith(("core/pipeline/", "gui/", "core/"))
               and w != rel for w in where):
            wire.append("主链路")
        # 插件侧：被 modules/installed 的插件 import（mixin 类模块多走这条）
        if any(w.startswith("modules/installed/") and w != rel for w in where):
            wire.append("插件侧")
        # 工具链：tool_caller 能分发到（或经能力表分发）
        if "modules/installed/tool_caller.py" in where or "能力表" in wire:
            wire.append("工具链")
        if has_test:
            wire.append("测试")

        full = name in FULL_VERSION
        rows.append({
            "file": rel,
            "what": (doc[:60] or "—").replace("|", "/"),
            "lines": n_lines,
            "test": has_test,
            "complete": "完整版" if full else _heuristic(
                bool(doc), has_test, n_lines),
            "wire": " / ".join(wire) if wire else "—",
        })
    return rows


def render(rows):
    lines = [
        "%s，%d 个）" % (START, len(rows)),
        "",
        "> 2026-11-02 由 `py -3 tools/gen_module_map.py --write` 重新生成（行数/接线是实测，"
        "不是回忆）。",
        "> `完整度`：B3–B6 补齐的 23 个模块统一为 **完整版**（按 8 条验收标准交付，"
        "明细见 `docs/101_功能深化方案与批次计划.md`）；",
        "> 其余行仍是 2026-10-25 的启发式（docstring + 有测试 + ≥80 行 各 1 分）。",
        "> `已接线`：能力表（`core_caps` 声明 / 模块自带 `TOOLS`）、主链路（`core/pipeline`、"
        "其他 core、GUI 里引用）、",
        "> 工具链（`tool_caller` 能分发）、测试（`tests/` 有对应用例）；`—` 表示四条全无。",
        "",
        "| 文件 | 作用 | 行数 | 测试 | 完整度 | 已接线 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| %s | %s | %d | %s | %s | %s |"
                     % (r["file"], r["what"], r["lines"],
                        r["test"], r["complete"], r["wire"]))
    lines.append("")
    return "\n".join(lines)


def write_doc(block):
    with open(DOC, encoding="utf-8") as f:
        text = f.read()
    start = text.find(START)
    end = text.find(END)
    if start < 0 or end < 0 or end <= start:
        raise SystemExit("找不到 3.1 / 3.2 的区间，文档结构变了，先看再改")
    text = text[:start] + block + "\n" + text[end:]
    with open(DOC, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return len(block.splitlines())


def main():
    rows = build_rows()
    print("=" * 62)
    print("core 模块表：%d 个文件（完整版 %d，已接线 %d，全无接线 %d）"
          % (len(rows),
             sum(1 for r in rows if r["complete"] == "完整版"),
             sum(1 for r in rows if r["wire"] != "—"),
             sum(1 for r in rows if r["wire"] == "—")))
    for r in rows:
        if r["file"][5:-3] in FULL_VERSION:
            print("  %-26s %-10s %s" % (r["file"], r["complete"], r["wire"]))
    missing = [n for n in FULL_VERSION
               if not os.path.isfile(os.path.join(CORE, n + ".py"))]
    if missing:
        print("[!] 名单里有但文件不存在：%s" % ", ".join(missing))
    if "--write" in sys.argv:
        n = write_doc(render(rows))
        print("\n已重写 docs/00 的 3.1 表（%d 行）" % n)
        return 0
    print("\n（只看不改：加 --write 才会重写 docs/00）")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
