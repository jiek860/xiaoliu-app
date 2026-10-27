# -*- coding: utf-8 -*-
"""分析专家：证据检索 + 数据/方案对比 + 风险清单。

专属工具链：
  1. deep_search 找外部证据（可选）
  2. graph_rag 找本地知识关系（可选）
  3. 本地数值对比（差值 / 变化率）
  4. llm 综合成利弊、风险与建议

不负责的事项：
  - 不负责模型选择与密钥管理（由 llm 模块做）
  - 不负责替用户做最终决策
  - 不负责修改知识图谱
  - 不负责长期记忆写入
"""
import re

from core.agent_generic import AgentGeneric

try:
    from core.plugin_errors import make_error
except ImportError:  # 独立加载时保持可用
    def make_error(code, message="", **_kwargs):
        return {"error": {"code": code, "message": message}}


class AgentAnalyst(AgentGeneric):
    """分析专家：会查证据、会算差异、会列风险。"""

    NAME = "agent_analyst"
    VERSION = "1.1.0"
    ROLE = "分析专家"
    SYSTEM_PROMPT = "你是分析专家，理性分点，指出利弊和风险。"
    NOT_RESPONSIBLE = ("模型选择", "最终决策", "知识图谱修改", "长期记忆写入")
    _NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?%?")

    TOOLS = [
        {
            "name": "agent_analyze",
            "method": "analyze",
            "desc": "分析专家：检索证据，给出利弊、风险和建议",
            "args": {"topic": "要分析的问题或对象",
                     "baseline": "对比基准/对象（可选）"},
            "readonly": True,
            "hints": ["深度分析", "分析一下", "利弊", "风险分析"],
            "contract": {
                "params": {
                    "topic": {"type": "string", "required": True},
                    "baseline": {"type": "string", "required": False},
                },
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_INTERNAL_ERROR"],
                "side_effects": ["network:llm", "network:deep_search"],
                "idempotent": False,
                "timeout_ms": 120000,
                "concurrency_safe": True,
                "description": "查本地图谱/外部搜索后，输出分点分析与风险清单",
                "not_responsible": ["替用户决策", "写记忆"],
            },
        },
        {
            "name": "agent_compare",
            "method": "compare",
            "desc": "分析专家：A/B 数据或方案对比",
            "args": {"left": "方案/数据 A", "right": "方案/数据 B",
                     "dimensions": "对比维度，逗号分隔（可选）"},
            "readonly": True,
            "hints": ["对比一下", "哪个好", "方案对比", "数据对比"],
            "contract": {
                "params": {
                    "left": {"type": "string", "required": True},
                    "right": {"type": "string", "required": True},
                    "dimensions": {"type": "string", "required": False},
                },
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_INTERNAL_ERROR"],
                "side_effects": ["network:llm", "network:deep_search"],
                "idempotent": False,
                "timeout_ms": 120000,
                "concurrency_safe": True,
                "description": "先算数值差异，再按维度给出对比结论与风险",
                "not_responsible": ["替用户决策"],
            },
        },
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self._last_error = ""

    # ------------------------------------------------------------------ 工具
    def _module(self, name):
        module = self.trunk.modules.get(name) if self.trunk else None
        if not module and self.trunk and hasattr(self.trunk, "call"):
            self.trunk.call(name, "__no__")
            module = self.trunk.modules.get(name)
        return module

    def _chat(self, system, user):
        llm = self._module("llm")
        if not llm or not hasattr(llm, "chat"):
            return "", False
        try:
            reply = llm.chat([
                {"role": "system", "content": system},
                {"role": "user", "content": str(user)[:4000]},
            ])
            return str(reply or "").strip(), bool(reply)
        except Exception as e:
            self._last_error = "LLM 调用失败: %s" % str(e)[:120]
            return "", False

    def _evidence(self, topic):
        """收集证据：外部搜索 + 本地图谱，失败不阻断分析。"""
        parts, warnings = [], []
        search = self._module("deep_search")
        if search and hasattr(search, "search"):
            try:
                result = search.search(topic)
                rows = result.get("结果") if isinstance(result, dict) else result
                for item in (rows or [])[:5]:
                    if isinstance(item, dict):
                        title = item.get("title") or item.get("标题") or ""
                        snippet = (item.get("snippet") or item.get("摘要")
                                   or item.get("content")
                                   or item.get("内容") or "")
                        parts.append("%s：%s" % (str(title)[:80],
                                                str(snippet)[:240]))
                    elif item:
                        parts.append(str(item)[:240])
            except Exception as e:
                warnings.append("外部搜索失败: %s" % str(e)[:80])
        graph = self._module("graph_rag")
        if graph and hasattr(graph, "query"):
            try:
                result = graph.query(topic)
                for row in (result.get("triples") or [])[:8]:
                    parts.append("%s --%s--> %s" % (
                        row.get("s", ""), row.get("p", ""), row.get("o", "")))
            except Exception as e:
                warnings.append("本地图谱查询失败: %s" % str(e)[:80])
        return "\n".join(parts)[:3000], warnings

    def _numbers(self, text):
        values = []
        for token in self._NUMBER_RE.findall(str(text or "")):
            try:
                values.append(float(token.rstrip("%")))
            except ValueError:
                continue
        return values

    def _numeric_rows(self, left, right):
        left_nums, right_nums = self._numbers(left), self._numbers(right)
        rows = []
        for index, (a, b) in enumerate(zip(left_nums, right_nums,
                                           strict=False)):
            diff = round(b - a, 4)
            rate = ""
            if a:
                rate = "%+.1f%%" % ((b - a) / abs(a) * 100)
            rows.append({"序号": index + 1, "左": a, "右": b,
                         "差值": diff, "变化率": rate})
        return rows

    @staticmethod
    def _risks(evidence, baseline):
        risks = ["结论建议人工复核，尤其是要花钱或影响用户的决策"]
        if not evidence:
            risks.append("缺少外部证据，当前结论主要来自推理")
        if baseline:
            risks.append("对比前需确认两边口径一致（单位、时间范围、样本）")
        return risks

    @staticmethod
    def _format_rows(rows):
        if not rows:
            return "未识别到可配对的数值；请确认输入里包含数字。"
        lines = []
        for row in rows:
            lines.append("#%d 左=%s 右=%s 差值=%s 变化率=%s" % (
                row["序号"], row["左"], row["右"], row["差值"],
                row["变化率"] or "—"))
        return "\n".join(lines)

    def analyze(self, topic, baseline=""):
        topic = str(topic or "").strip()
        baseline = str(baseline or "").strip()
        if not topic:
            return self._failure("PLUGIN_MISSING_ARG", "缺少 topic（要分析的问题）")
        evidence, warnings = self._evidence(topic)
        rows = self._numeric_rows(topic, baseline) if baseline else []
        prompt = (
            "分析对象：%s\n对比基准：%s\n可核对数据：\n%s\n证据：\n%s\n\n"
            "请用中文输出：1) 核心结论 2) 3~5 条利弊 3) 关键风险 "
            "4) 下一步建议。不要编造百分比。") % (
            topic, baseline or "无", self._format_rows(rows), evidence or "无")
        text, has_llm = self._chat("你是严谨的分析专家。", prompt)
        if not text:
            text = ("1) 目标：%s\n2) 基准：%s\n3) 数据：\n%s\n"
                    "4) 建议：补充证据后，再按目标/成本/风险三项打分。") % (
                        topic, baseline or "无", self._format_rows(rows))
        return {
            "ok": True,
            "主题": topic,
            "基准": baseline,
            "证据": evidence,
            "数据对比": rows,
            "分析": text,
            "风险": self._risks(evidence, baseline),
            "llm": has_llm,
            "警告": warnings,
        }

    def compare(self, left, right, dimensions=""):
        left = str(left or "").strip()
        right = str(right or "").strip()
        dims = str(dimensions or "").strip()
        if not left or not right:
            return self._failure("PLUGIN_MISSING_ARG",
                                 "缺少 left / right（两个对比对象）")
        rows = self._numeric_rows(left, right)
        evidence, warnings = self._evidence("%s %s 对比" % (left, right))
        prompt = (
            "对比 A：%s\n对比 B：%s\n维度：%s\n数值差异：\n%s\n证据：\n%s\n\n"
            "请输出：1) 一句话结论 2) 按维度逐项对比 3) A 的优势/风险 "
            "4) B 的优势/风险 5) 选择建议。不要编造数据。") % (
            left, right, dims or "目标契合、成本、风险、可维护性",
            self._format_rows(rows), evidence or "无")
        text, has_llm = self._chat("你是严谨的分析专家，擅长做方案对比。", prompt)
        if not text:
            verdict = "数据不足，暂不给胜负结论"
            if rows:
                better = sum(1 for row in rows if row["差值"] > 0)
                worse = sum(1 for row in rows if row["差值"] < 0)
                if better > worse:
                    verdict = "按现有数值，B 更优（%d 项领先）" % better
                elif worse > better:
                    verdict = "按现有数值，A 更优（%d 项领先）" % worse
            text = ("结论：%s\nA：%s\nB：%s\n数值：\n%s") % (
                verdict, left, right, self._format_rows(rows))
        return {
            "ok": True,
            "左": left,
            "右": right,
            "维度": dims or "目标契合、成本、风险、可维护性",
            "数据对比": rows,
            "分析": text,
            "风险": self._risks(evidence, "对比"),
            "证据": evidence,
            "llm": has_llm,
            "警告": warnings,
        }

    @staticmethod
    def _failure(code, message, **extra):
        out = {"ok": False}
        out.update(make_error(code, message, module="agent_analyst"))
        out.update(extra)
        return out
