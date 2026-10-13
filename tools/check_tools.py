# -*- coding: utf-8 -*-
"""工具预算守卫 —— 防止能力越加越多把 LLM 提示词撑爆

背景
----
实测（2026-10-13）tool_caller._llm_decide 的提示词：
    19 个工具 -> 1213 字符
    35 个工具 -> 2021 字符（1.7 倍）
    53 个工具 -> 1747 字符（描述更短，所以没线性涨）
    100 个工具 -> 约 5855 字符（4.8 倍）
**工具越多，模型选错的概率越高。** 所以能力不能无限往一张表里塞。

两道防线
--------
    第 0 级  context_builder._TOOL_HINTS  不像要动手就不进 tool_caller
    第 1 级  tool_caller._candidates()    按 hints 粗筛，上限 15 个

本脚本检查：
    · 注册表里的能力总数 / 只读 / 需确认 分布
    · 每条能力是否声明了 hints（没有 hints 的能力只能靠兜底才进候选）
    · 粗筛后的提示词最大长度是否在预算内
    · 重名（同一工具名被两个来源声明）

用法
----
    py -3 tools\\check_tools.py            # 检查
    py -3 tools\\check_tools.py --rebase   # 下调提示词预算
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGET = os.path.join(BASE, "tools", "tool_budget.json")
sys.path.insert(0, BASE)

# 粗筛后提示词的字符上限。实测最坏 443 字符（命中 15 条），留一倍余量。
DEFAULT_PROMPT_BUDGET = 1200
# 进 LLM 的候选上限（与 tool_caller._MAX_CANDIDATES 保持一致）
CAND_LIMIT = 15

# 用来试探最坏情况的查询（都不该命中太多）
PROBES = ["随便说点什么", "今天天气怎么样", "帮我个忙", "嗯", "你觉得呢",
          "看看我的统计报表", "帮我整理一下记忆", "杭州今天天气"]


def _probe_worst(tc, limit=CAND_LIMIT):
    """返回 (最坏字符数, 触发它的查询)，用与主检查**完全一致**的格式

    踩过的坑：--rebase 里原来用的是不含「，参数:」的短格式（443 字符），
    而主检查用的是真实格式（889 字符），于是 rebase 写出来的预算
    立刻就被主检查判为超标。两处必须用同一个构造函数。
    """
    from core import module_caps
    worst_n, worst_q = 0, ""
    for q in PROBES:
        sub = module_caps.shortlist(tc.tools, q, limit)
        text = _as_prompt(sub)
        if len(text) > worst_n:
            worst_n, worst_q = len(text), q
    return worst_n, worst_q


def _as_prompt(pairs):
    """把候选工具渲染成 _llm_decide 里那一段（格式必须与 tool_caller 一致）"""
    return "\n".join('- "%s": %s，参数: %s'
                     % (k, v["desc"], json.dumps(v["args"], ensure_ascii=False))
                     for k, v in pairs)


def main():
    ap = argparse.ArgumentParser(description="工具/提示词预算检查")
    ap.add_argument("--rebase", action="store_true", help="下调提示词预算")
    args = ap.parse_args()

    try:
        b = json.load(open(BUDGET, encoding="utf-8"))
    except Exception:
        b = {"prompt_chars": DEFAULT_PROMPT_BUDGET}
    budget = int(b.get("prompt_chars", DEFAULT_PROMPT_BUDGET))

    if args.rebase:
        tc = _load_tool_caller()
        if tc is None:
            print("  [X] tool_caller 加载不了，无法测基线")
            return 1
        worst_n, worst_q = _probe_worst(tc)
        b["prompt_chars"] = max(400, int(worst_n * 1.3))
        b["_说明"] = ("粗筛后提示词字符上限（格式与 _llm_decide 一致）。"
                      "加能力请声明 hints，否则只能靠兜底进候选。")
        json.dump(b, open(BUDGET, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("  预算已设为 %d 字符（当前最坏 %d，查询「%s」）"
              % (b["prompt_chars"], worst_n, worst_q))
        return 0

    print("=" * 72)
    print("工具 / 提示词预算检查")
    print("=" * 72)

    from core import module_caps  # noqa: E402
    caps = module_caps.load_tools(BASE)
    desc = module_caps.describe(BASE)
    print("  注册表能力: %d 条 %s" % (desc.get("能力数", 0), desc.get("按来源", {})))

    problems = []

    # ① 没有 hints 的能力：只能靠兜底进候选，加多了会把候选挤满
    no_hint = [n for n, v in caps.items() if not v.get("hints")]
    if no_hint:
        print("  没声明 hints 的能力: %d 条" % len(no_hint))
        for n in no_hint[:8]:
            print("     · %s" % n)
        if len(no_hint) > 8:
            print("     … 还有 %d 条" % (len(no_hint) - 8))
        print("     建议补 hints，否则用户提到它时可能进不了候选")

    # ② 重名（同工具名被两处声明）
    dup = _dups(BASE)
    if dup:
        problems.append("重名工具: %s" % "、".join(dup))
        for d in dup:
            print("  ❌ 重名: %s（两个来源都声明了）" % d)

    # ③ 提示词最坏长度
    tool_caller = _load_tool_caller()
    if tool_caller is None:
        print("  ⚠️ tool_caller 加载不了，跳过提示词测量")
    else:
        worst_n, worst_q = _probe_worst(tool_caller)
        full = _as_prompt(list(tool_caller.tools.items()))
        print("  工具表 %d 个，不筛选时提示词 %d 字符"
              % (len(tool_caller.tools), len(full)))
        print("  粗筛后最坏: %d 字符（查询「%s」）预算 %d  %s"
              % (worst_n, worst_q, budget, "✅" if worst_n <= budget else "❌"))
        if worst_n > budget:
            problems.append("提示词最坏 %d 字符，超预算 %d" % (worst_n, budget))

    print("=" * 72)
    if problems:
        print("发现 %d 个问题：" % len(problems))
        for p in problems:
            print("   · %s" % p)
        return 1
    print("工具预算通过 ✅")
    return 0


def _dups(base):
    """找出被两个来源同时声明的工具名"""
    out = []
    try:
        from core.core_caps import CORE_CAPS
        core_names = {c.get("name") for c in CORE_CAPS}
    except Exception:
        core_names = set()
    try:
        import json as _j
        man = _j.load(open(os.path.join(base, "modules_repo", "manifest.json"),
                           encoding="utf-8-sig"))
        from core.module_caps import tools_of_source
        for m in man:
            p = os.path.join(base, "modules", "installed", str(m.get("file") or ""))
            if not os.path.exists(p):
                continue
            for t in tools_of_source(p, str(m.get("cls") or "") or None):
                if t.get("name") in core_names:
                    out.append(t["name"])
    except Exception:
        pass
    return sorted(set(out))


def _load_tool_caller():
    try:
        import os as _os
        sys.path.insert(0, _os.path.join(BASE, "libs"))
        from core.trunk import Trunk
        t = Trunk()
        return t._load_lazy("tool_caller")
    except Exception:
        return None


def _measure():
    try:
        tc = _load_tool_caller()
        if tc is None:
            return "", 0
        import json as _j
        worst_n, worst_q = 0, ""
        for q in PROBES:
            from core import module_caps
            sub = module_caps.shortlist(tc.tools, q, CAND_LIMIT)
            text = "\n".join('- "%s": %s' % (k, v["desc"]) for k, v in sub)
            if len(text) > worst_n:
                worst_n, worst_q = len(text), q
        return worst_q, worst_n
    except Exception:
        return "", 0


if __name__ == "__main__":
    sys.exit(main())
