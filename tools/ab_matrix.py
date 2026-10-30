# -*- coding: utf-8 -*-
"""批次 49.1：开关组合矩阵 + 默认值决策表 + 41.3 基线对比。

为什么不是"把所有 2^N 种都跑一遍"
--------------------------------
16 个开关的笛卡尔积上万种，本地跑不完，而且大多数组合没有独立行为。
本工具用**成对覆盖（pairwise）**：任意两个开关的任意取值组合至少出现一次，
把组合数压到几十条；需要全量时用 ``--full``（超过 256 条会拒绝执行）。

它做三件事：
1. 生成矩阵（默认 pairwise；``--full`` 笛卡尔积）；
2. **本地探针**：每组配置下检查开关是否能正确读取，并验证 48 的
   off/shadow/on 语义（反思维度、主动搭话、语音情绪）——不调模型、不联网；
3. 写报告：开关表、默认决策表、覆盖统计、探针结果、41.3 基线对比。
   真实 A/B（拟人度/采纳率）仍需 ``run_eval.py --with-model`` 的数据，
   本工具不编造指标；没有 ``--current`` 时明确写"待采集"。

用法
----
    py -3 tools\\ab_matrix.py                         # 打印摘要
    py -3 tools\\ab_matrix.py --run --write-doc docs/101_功能深化方案与批次计划.md
    py -3 tools\\ab_matrix.py --full --cases 200       # 笛卡尔积（小规模）
    py -3 tools\\ab_matrix.py --current data/eval/report_20261029.json
"""
import argparse
import itertools
import json
import os
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# key / 模块 / 默认 / 取值 / 批次 / 回滚方式 / 看什么指标
SWITCHES = [
    {"key": "聊天.状态层", "module": "对话状态", "default": "shadow",
     "values": ["off", "shadow", "on"], "batch": "42.1",
     "rollback": "改回 shadow/off 即回到旧链路", "metric": "状态回放、首包延迟"},
    {"key": "聊天.规划器", "module": "回应规划", "default": "shadow",
     "values": ["off", "shadow", "rule", "model"], "batch": "42.2",
     "rollback": "改回 off", "metric": "回复长度相关、延迟"},
    {"key": "聊天.校验器", "module": "生成后校验", "default": "shadow",
     "values": ["off", "shadow", "on"], "batch": "42.3",
     "rollback": "改回 off", "metric": "重复率、超长率"},
    {"key": "聊天.人格卡", "module": "分层人格卡", "default": "shadow",
     "values": ["off", "shadow", "on"], "batch": "42.4",
     "rollback": "改回 off", "metric": "人格一致性、长度"},
    {"key": "聊天.人格风格", "module": "人格风格", "default": "",
     "values": ["", "温柔", "直率"], "batch": "42.4",
     "rollback": "清空风格", "metric": "风格命中"},
    {"key": "聊天.灰度比例", "module": "灰度比例", "default": 0,
     "values": [0, 10, 100], "batch": "42.5",
     "rollback": "调回 0", "metric": "灰度组/对照组差异"},
    {"key": "memory.v2", "module": "记忆 v2", "default": False,
     "values": [False, True], "batch": "43.5",
     "rollback": "改回 false", "metric": "记忆命中率、token"},
    {"key": "nl.intent_v2", "module": "NL 意图", "default": "shadow",
     "values": ["off", "shadow", "on"], "batch": "44.1",
     "rollback": "改回 off", "metric": "意图准确率、误执行"},
    {"key": "code.index_v2", "module": "代码索引 v2", "default": False,
     "values": [False, True], "batch": "45.1",
     "rollback": "改回 false", "metric": "索引刷新、Top-10 命中"},
    {"key": "code.context_v2", "module": "上下文 v2", "default": "shadow",
     "values": ["off", "shadow", "on"], "batch": "45.3",
     "rollback": "改回 off", "metric": "引用准确率、token"},
    {"key": "code_agent.background", "module": "后台任务", "default": False,
     "values": [False, True], "batch": "46.1",
     "rollback": "改回 false", "metric": "取消恢复、UI 卡顿"},
    {"key": "code_agent.auto_apply", "module": "自动应用 L2", "default": False,
     "values": [False, True], "batch": "46.2",
     "rollback": "改回 false", "metric": "误应用率、审批量"},
    {"key": "code_qa.enabled", "module": "代码问答", "default": False,
     "values": [False, True], "batch": "47.3",
     "rollback": "改回 false", "metric": "引用准确率、采纳率"},
    {"key": "反思.多维评分", "module": "多维反思", "default": "shadow",
     "values": ["off", "shadow", "on"], "batch": "48.1",
     "rollback": "改回 off（完全回 v2.1）", "metric": "低分复现率"},
    {"key": "反思.建议晋升", "module": "建议晋升", "default": True,
     "values": [False, True], "batch": "48.2",
     "rollback": "改回 false；已晋升规则可逐条撤销", "metric": "误晋升率、审计"},
    {"key": "主动.事件驱动", "module": "主动搭话", "default": "shadow",
     "values": ["off", "shadow", "on"], "batch": "48.3",
     "rollback": "改回 off", "metric": "接受率、打扰投诉"},
    {"key": "语音.情绪", "module": "语音情绪", "default": "on",
     "values": ["off", "on"], "batch": "48.3",
     "rollback": "改回 off", "metric": "首包 ≤1.5s"},
]

BASELINE_41_3 = {
    "safe": {"通过": "20/20", "通过率": "100%"},
    "nl": {"通过": "40/40", "期望匹配": "32/40 (80%)"},
    "code": {"通过": "20/20", "说明": "fixture 初始健康度符合预期"},
    "chat": {"通过": "0/60", "说明": "跳过，需 --with-model"},
}


class CaseTrunk:
    """只读 rules 字典的假躯干，够 48 的模块/探针用。"""

    def __init__(self, base, rules, mood="开心"):
        self.base = base
        self.rules = dict(rules)
        self.config = {}
        self.modules = {}
        self.logs = []
        self.data = {"mood": mood}

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def _log(self, msg, level="INFO"):
        self.logs.append((level, msg))


def pairwise_cases(switches):
    """贪心成对覆盖：返回覆盖所有两两取值组合的最小候选集（近似）。"""
    reqs = set()
    for i, left in enumerate(switches):
        for value in left["values"]:
            reqs.add((i, value))
        for j in range(i + 1, len(switches)):
            right = switches[j]
            for lv in left["values"]:
                for rv in right["values"]:
                    reqs.add((i, lv, j, rv))
    cases = []
    while reqs:
        first = sorted(reqs, key=lambda r: (len(r), r))[0]
        case = [s["default"] for s in switches]
        if len(first) == 2:
            case[first[0]] = first[1]
        else:
            case[first[0]], case[first[2]] = first[1], first[3]
        # 其余开关：选能覆盖最多未覆盖要求的取值
        for i, item in enumerate(switches):
            if i in ([first[0]] if len(first) == 2 else [first[0], first[2]]):
                continue
            best, best_gain = case[i], -1
            for value in item["values"]:
                trial = list(case)
                trial[i] = value
                gain = _covered(trial, reqs)
                if gain > best_gain:
                    best, best_gain = value, gain
            case[i] = best
        cases.append(case)
        reqs -= set(_matches(case))
    return cases


def _matches(case):
    out = []
    for i, value in enumerate(case):
        out.append((i, value))
        for j in range(i + 1, len(case)):
            out.append((i, value, j, case[j]))
    return out


def _covered(case, reqs):
    return len(set(_matches(case)) & reqs)


def cartesian_cases(switches, limit=256):
    total = 1
    for item in switches:
        total *= len(item["values"])
    if total > limit:
        raise ValueError("笛卡尔积 %d 超过上限 %d；请用 --cases 或默认 pairwise"
                         % (total, limit))
    return [list(row) for row in itertools.product(
        *[item["values"] for item in switches])]


def _probe(case, switches):
    """本地探针：开关读取 + 48 的 off/shadow/on 语义。"""
    rules = {s["key"]: v for s, v in zip(switches, case)}
    tmp = tempfile.mkdtemp(prefix="x6_ab_")
    trunk = CaseTrunk(tmp, rules)
    checks = []

    # 1) 开关读回
    for s, value in zip(switches, case):
        checks.append((s["key"], trunk.rule(s["key"]) == value))

    # 2) 反思：off 无维度，shadow/on 有维度
    from modules.installed.self_reflect import ReflectEngine
    engine = ReflectEngine(trunk)
    out = engine.quick_eval("怎么学 Python", "作为AI，希望对你有所帮助。")
    mode = str(rules.get("反思.多维评分", "shadow"))
    has_dims = "维度" in out
    checks.append(("反思.多维评分=" + mode, has_dims == (mode != "off")))

    # 3) 主动：off 不发，shadow 只记录，on 每天一条
    from modules.installed.personality import PersonalityEngine
    pe = PersonalityEngine(trunk)
    pe.base = tmp
    pe.path = os.path.join(tmp, "data", "personality.json")
    os.makedirs(os.path.dirname(pe.path), exist_ok=True)
    pe.data["last_active"] = time.time()
    at = time.mktime((2026, 10, 29, 10, 0, 0, 0, 0, -1))
    mode = str(rules.get("主动.事件驱动", "shadow"))
    queued = pe.queue_proactive("task_done", now=at)
    line = pe.consume_proactive(now=at)
    if mode == "off":
        expected = (queued is False and line is None)
    elif mode == "shadow":
        expected = (queued is True and line is None)
    else:
        expected = (line is not None)
    checks.append(("主动.事件驱动=" + mode, bool(expected)))

    # 4) 语音情绪：off 无参数，on 有参数
    from modules.installed.tts import TTS
    tts = TTS(trunk)
    mode = str(rules.get("语音.情绪", "on"))
    params = tts.emotion_params("开心", mode)
    checks.append(("语音.情绪=" + mode, bool(params) == (mode == "on")))
    return checks


def run_cases(cases, switches):
    results = []
    for index, case in enumerate(cases):
        try:
            checks = _probe(case, switches)
            ok = all(item[1] for item in checks)
            failed = [name for name, passed in checks if not passed]
        except Exception as exc:  # 工具要报告失败，不掩盖
            ok, failed = False, ["异常: %s" % str(exc)[:120]]
        results.append({"case": index + 1, "ok": ok, "failed": failed,
                        "config": {s["key"]: v for s, v in zip(switches, case)}})
    return results


def load_current(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}
    return data.get("domains") or {}


def _cell(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value == "":
        return "（空）"
    return str(value)


def render_doc(cases, switches, results, current):
    now = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        "# v25.3.0 开关矩阵与默认值决策",
        "",
        "日期：%s  " % now,
        "工具：`py -3 tools/ab_matrix.py --run --write-doc <本文件>`  ",
        "方法：成对覆盖（任意两个开关的任意取值组合至少出现一次）；本地探针不调模型。",
        "",
        "## 1. 默认值决策表",
        "",
        "| 开关 | 默认 | 取值 | 批次 | 回滚 | 观察指标 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for s in switches:
        lines.append("| `%s` | `%s` | %s | %s | %s | %s |" % (
            s["key"], _cell(s["default"]),
            " / ".join("`%s`" % _cell(v) for v in s["values"]),
            s["batch"], s["rollback"], s["metric"]))
    lines += [
        "",
        "原则：新链路默认 `off`/`shadow`，`shadow` 只记录不改回复；",
        "只有 48.3 的语音情绪默认 `on`（只在用户主动朗读时生效，关掉即回旧行为）。",
        "",
        "## 2. 组合矩阵（%d 组，成对覆盖）" % len(cases),
        "",
        "| # | " + " | ".join(s["key"] for s in switches) + " |",
        "| --- | " + " | ".join("---" for _ in switches) + " |",
    ]
    for index, case in enumerate(cases, 1):
        lines.append("| %d | " % index + " | ".join(
            "`%s`" % _cell(v) for v in case) + " |")
    lines += ["", "## 3. 本地探针结果", ""]
    if not results:
        lines += ["未执行本地探针（去掉 `--run` 时的默认状态）。"]
    else:
        passed = len([r for r in results if r["ok"]])
        lines += ["%d/%d 组通过；每组检查开关读回、反思维度、主动预算、语音情绪。"
                  % (passed, len(results)), "",
                  "| # | 结果 | 失败项 |", "| --- | --- | --- |"]
        for row in results:
            lines.append("| %d | %s | %s |" % (
                row["case"], "✅" if row["ok"] else "❌",
                "；".join(row["failed"]) or ""))
    lines += [
        "",
        "## 4. 与 41.3 基线对比",
        "",
        "| 域 | 41.3 基线 | 当前 | 结论 |",
        "| --- | --- | --- | --- |",
    ]
    for domain, base in BASELINE_41_3.items():
        cur = current.get(domain)
        if not cur:
            current_text, verdict = "待采集", "需 `--with-model`"
        elif cur.get("total") and cur.get("skipped") == cur.get("total"):
            current_text = "待采集（%d 跳过）" % cur.get("skipped")
            verdict = "需 `--with-model`"
        else:
            current_text = "%d/%d（跳过 %d）" % (
                cur.get("passed", 0), cur.get("total", 0), cur.get("skipped", 0))
            verdict = "无失败" if not cur.get("failed") else "%d 失败" % cur.get("failed")
        lines.append("| %s | %s | %s | %s |" % (
            domain, base.get("通过", ""), current_text, verdict))
    lines += [
        "",
        "**口径**：本地矩阵只验证开关接线和回滚语义，不代表拟人度/采纳率；",
        "这些指标要跑 `py -3 tools/run_eval.py --domain all --with-model` 并产出报告后再填。",
        "本工具不写入编造的数字。",
        "",
        "## 5. 回滚演练",
        "",
        "1. 任一组配置改回默认值；`--run` 中对应探针必须恢复为默认行为；",
        "2. 48.2 已晋升规则用 `self_reflect.revoke_candidate(id)` 撤销，人格卡/校验器立即不再读取；",
        "3. 48.3 语音情绪改 `语音.情绪=off`，`emotion_params` 返回空，合成参数回到旧行为。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="开关组合矩阵与默认值决策")
    parser.add_argument("--run", action="store_true", help="执行本地探针")
    parser.add_argument("--full", action="store_true", help="笛卡尔积（默认 pairwise）")
    parser.add_argument("--cases", type=int, default=256, help="笛卡尔积上限")
    parser.add_argument("--write-doc", default="", help="Markdown 报告路径")
    parser.add_argument("--json", default="", help="JSON 结果路径")
    parser.add_argument("--current", default="", help="当前评测报告 JSON")
    args = parser.parse_args()

    switches = SWITCHES
    if args.full:
        cases = cartesian_cases(switches, args.cases)
    else:
        cases = pairwise_cases(switches)
    # 基线配置必须是第一组，方便人工核对默认行为
    default_case = [s["default"] for s in switches]
    cases = [default_case] + [c for c in cases if c != default_case]

    results = run_cases(cases, switches) if args.run else []
    current = load_current(args.current)
    passed = len([r for r in results if r["ok"]])
    print("开关 %d 个，组合 %d 组%s" % (
        len(switches), len(cases),
        "，探针 %d/%d 通过" % (passed, len(results)) if results else ""))
    if args.write_doc:
        doc = render_doc(cases, switches, results, current)
        os.makedirs(os.path.dirname(os.path.abspath(args.write_doc)), exist_ok=True)
        open(args.write_doc, "w", encoding="utf-8").write(doc)
        print("报告: %s" % args.write_doc)
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        json.dump({"cases": cases, "results": results, "switches": switches},
                  open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("JSON: %s" % args.json)
    if results and passed != len(results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
