# -*- coding: utf-8 -*-
"""自我反思 v4 - 多维评分 + 失败库 + 建议晋升（批次 48.1/48.2）

v4.1 的教训是"分数会说谎"：LLM 挂掉照样记 5 分，规则粗筛给所有正常回答
打基线 5 分，50 条历史 48 条是假分。v4 在此基础上加三件事：

* **多维评分**：准确/贴合/人格/有用/长度各 1-5 分。规则先算底线分，
  LLM 可用时再覆盖；总分 <3.0 或任一项 ≤2 记为低分。
* **失败库**：低分样本进 ``data/chat_failures.jsonl``（脱敏、去重、可复查），
  供回归和"低分复现率"观察。
* **建议晋升**：同类建议出现 ≥3 次生成候选规则，**必须人工确认**才生效，
  生效后写入人格卡可读的 ``data/chat_promoted_rules.json``，全程审计、可撤销。

开关（``data/rules/rules.json`` 可覆盖）：
``反思.多维评分`` off/shadow/on（默认 shadow，关掉完全回到 v2.1 行为）
``反思.失败库`` true/false（默认 true；只写数据，不改变回复）
``反思.建议晋升`` true/false（默认 true；只生成候选，不自动生效）

实现分层：评分规则在 ``core.chat.critic``，失败库/晋升存储在
``core.chat.fewshot``；本模块只做开关、模型调用与对外接口。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import re
import time

from core.safe import safe
from core.chat.critic import (parse_model_json, rubric_dims, rubric_issues,
                              rubric_total)
from core.chat import fewshot
from modules.base import BaseModule

_DIM_KEYS = ("准确", "贴合", "人格", "有用", "长度")
_CAND_TTL = 30


class ReflectEngine(BaseModule):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "self_reflect"
    VERSION = "4.0"

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        # v2.1: 插件持久化必须落在 data/plugin_data/<插件名>/ 内
        _sdir = os.path.join(self.base, "data", "plugin_data", "self_reflect")
        os.makedirs(_sdir, exist_ok=True)
        self.history_path = os.path.join(_sdir, "reflect_history.json")
        _legacy = os.path.join(self.base, "data", "reflect_history.json")
        if not os.path.exists(self.history_path) and os.path.exists(_legacy):
            try: os.replace(_legacy, self.history_path)
            except OSError:  # 静默是故意的：旧数据迁移失败不阻断主流程
                pass
        self.weekly_path = os.path.join(_sdir, "reflect_weekly.json")
        self.history = self._load()
        self.reflect_count = 0

    # ---------------------------------------------------------- 存储
    def _load(self):
        if os.path.exists(self.history_path):
            try:
                return json.load(open(self.history_path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
        return []

    def _save(self):
        try:
            json.dump(self.history, open(self.history_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)

    def _rule(self, key, default):
        try:
            return self.trunk.rule(key, default)
        except Exception as e:
            _x6_swallowed(__name__, e)
            return default

    def _mode(self):
        mode = str(self._rule("反思.多维评分", "shadow") or "shadow").lower()
        return mode if mode in ("off", "shadow", "on") else "shadow"

    def _fail_enabled(self):
        return bool(self._rule("反思.失败库", True))

    def _scored(self):
        """真正被评过分的条目（分数可能是 None —— 规则粗筛的"无意见"和没评上的）"""
        return [h for h in self.history
                if isinstance(h.get("分数"), (int, float))]

    def _record_entry(self, entry):
        self.history.append(entry)
        self.reflect_count += 1
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self._save()

    # ---------------------------------------------------------- 评分
    def _ask_model(self, user_input, ai_response):
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return None, "", "LLM 未就绪"
        try:
            prompt = ("用户问：%s\n我答：%s\n按准确/贴合/人格/有用/长度五个维度各打1-5分，"
                      "只返回 JSON：{\"准确\":1-5,\"贴合\":1-5,\"人格\":1-5,"
                      "\"有用\":1-5,\"长度\":1-5,\"建议\":\"一句话改进点\"}"
                      % (str(user_input)[:100], str(ai_response)[:200]))
            raw = str(llm.chat(prompt) or "")
        except Exception as e:
            return None, "", "调用模型失败: %s" % str(e)[:60]
        parsed = parse_model_json(raw)
        if not parsed:
            return None, raw[:100], "模型没给出可用维度"
        dims, suggestion = parsed
        if len(dims) < 3:
            return None, suggestion, "模型维度不全"
        return dims, suggestion, ""

    @safe
    def reflect(self, user_input, ai_response):
        """多维反思：规则底线分 + 模型覆盖 + 失败库。

        off 模式完全走 v2.1 老逻辑（只返回旧的三个键），保证可回滚。
        """
        if self._mode() == "off":
            return self._reflect_legacy(user_input, ai_response)
        rule_dims = rubric_dims(user_input, ai_response)
        model_dims, suggestion, err = self._ask_model(user_input, ai_response)
        dims = dict(rule_dims)
        if model_dims:
            dims.update(model_dims)
        total = rubric_total(dims)
        issues = rubric_issues(dims, user_input, ai_response)
        score = round(total * 2.0, 1)
        entry = {
            "用户": str(user_input)[:50],
            "回答": str(ai_response)[:50],
            "分数": score,
            "建议": suggestion,
            "维度": dims,
            "总分": total,
            "问题": "、".join(issues) if issues else None,
            "时间": time.strftime("%m-%d %H:%M"),
            "ts": int(time.time()),
            "来源": "模型+规则" if model_dims else "规则",
        }
        if self._mode() == "shadow":
            entry["影子"] = True       # 影子：只记录维度，不改原来的模型分语义
        if err:
            entry["模型错误"] = err
        self._record_entry(entry)
        self._maybe_record_failure(entry, rule_dims, issues)
        if err and self.trunk:
            try:
                self.trunk._log("反思模型维度未用上: %s" % err, "WARN")
            except Exception as e:
                _x6_swallowed(__name__, e)
        return {"分数": score, "建议": suggestion, "未评分": err or None,
                "维度": dims, "总分": total, "问题": issues or None}

    def _reflect_legacy(self, user_input, ai_response):
        llm = self.trunk.modules.get("llm") if self.trunk else None
        score, suggestion, err = None, "", ""
        if not llm:
            err = "LLM 未就绪"
        else:
            try:
                prompt = ("用户问：%s\n我答：%s\n这个回答打几分(1-10)？一句话说改进点:"
                          % (str(user_input)[:100], str(ai_response)[:200]))
                r = str(llm.chat(prompt) or "")
                m = re.search(r"(\d+)", r)
                if m:
                    score = max(1, min(10, int(m.group(1))))
                else:
                    err = "模型没给出分数"
                suggestion = r[:100]
            except Exception as e:
                err = "调用模型失败: %s" % str(e)[:60]
        entry = {
            "用户": str(user_input)[:50],
            "回答": str(ai_response)[:50],
            "分数": score,
            "建议": suggestion,
            "时间": time.strftime("%m-%d %H:%M"),
            "来源": "模型",
        }
        if err:
            entry["未评分"] = err
        self._record_entry(entry)
        if err and self.trunk:
            try:
                self.trunk._log("自我反思未评分: %s" % err, "WARN")
            except Exception as e:
                _x6_swallowed(__name__, e)
        return {"分数": score, "建议": suggestion, "未评分": err or None}

    @safe
    def quick_eval(self, user_input, ai_response):
        """规则粗筛，不调模型。v4 同时算维度并落失败库。"""
        text = str(ai_response or "")
        if self._mode() == "off":
            score, why = None, ""
            if len(text) < 5:
                score, why = 3, "回答太短"
            elif text.startswith(("（抱歉", "本地模型错误", "（模型错误")):
                score, why = 1, "错误占位"
            elif len(text) > 3000:
                score, why = 4, "回答过长"
            entry = {
                "用户": str(user_input)[:50], "回答": text[:50], "分数": score,
                "建议": "", "时间": time.strftime("%m-%d %H:%M"), "来源": "规则",
            }
            if why:
                entry["问题"] = why
            self._record_entry(entry)
            return {"分数": score, "问题": why or None}

        dims = rubric_dims(user_input, text)
        total = rubric_total(dims)
        issues = rubric_issues(dims, user_input, text)
        mode = self._mode()
        score, why = None, ""
        if mode == "on":
            score = round(total * 2.0, 1)
            why = "、".join(issues)
        else:
            if len(text) < 5:
                score, why = 3, "回答太短"
            elif text.startswith(("（抱歉", "本地模型错误", "（模型错误")):
                score, why = 1, "错误占位"
            elif len(text) > 3000:
                score, why = 4, "回答过长"
        entry = {
            "用户": str(user_input)[:50], "回答": text[:50], "分数": score,
            "建议": "", "维度": dims, "总分": total,
            "问题": why or None,
            "时间": time.strftime("%m-%d %H:%M"), "ts": int(time.time()),
            "来源": "规则",
        }
        if mode == "shadow":
            entry["影子"] = True
        self._record_entry(entry)
        self._maybe_record_failure(entry, dims, issues)
        return {"分数": score, "问题": why or None,
                "维度": dims, "总分": total}

    # ---------------------------------------------------------- 失败库
    def _maybe_record_failure(self, entry, dims, issues):
        total = rubric_total(dims)
        critical = any(int(v) <= 2 for v in dims.values())
        if total >= 3.0 and not critical:
            return None
        category = (issues or ["general"])[0]
        return fewshot.record_failure(
            self.base, entry.get("用户", ""), entry.get("回答", ""),
            dims=dims, issues=issues, suggestion=entry.get("建议", ""),
            category=category, shadow=bool(entry.get("影子")),
            source=entry.get("来源", "规则"), enabled=self._fail_enabled())

    @safe
    def record_failure(self, user_input, ai_response, dims=None, issues=None,
                       suggestion="", category="", shadow=False, source="规则"):
        return fewshot.record_failure(
            self.base, user_input, ai_response, dims=dims, issues=issues,
            suggestion=suggestion, category=category, shadow=shadow,
            source=source, enabled=self._fail_enabled())

    @safe
    def failures(self, status="open", category="", limit=20):
        rows = fewshot.failure_rows(self.base)
        if status:
            rows = [r for r in rows if r.get("状态") == status]
        if category:
            rows = [r for r in rows if r.get("类别") == category]
        return rows[-int(limit or 20):]

    @safe
    def mark_failure(self, failure_id, status="resolved"):
        return fewshot.mark_failure(self.base, failure_id, status)

    @safe
    def recheck_failures(self, limit=20):
        return fewshot.recheck_failures(self.base, limit=limit)

    @safe
    def failure_stats(self):
        return fewshot.failure_stats(self.base)

    @safe
    def weekly_report(self):
        """近 7 天反思周报：低分、失败类别、在生效的规则、行动项。"""
        now = int(time.time())
        recent = [h for h in self.history
                  if now - int(h.get("ts") or now) <= 7 * 86400]
        scored = [h for h in recent if isinstance(h.get("分数"), (int, float))]
        fails = [r for r in fewshot.failure_rows(self.base)
                 if now - int(r.get("ts") or now) <= 7 * 86400]
        cats = {}
        for row in fails:
            cat = str(row.get("类别") or "general")
            cats[cat] = cats.get(cat, 0) + 1
        worst = sorted(scored or recent, key=lambda x: x.get("分数") or 0)[:3]
        actions = ["本周 %d 条低分样本，先复查复现率" % len(fails)] if fails else []
        if cats:
            actions.append("建议优先处理：" + "、".join(
                k for k, _ in sorted(cats.items(), key=lambda x: -x[1])[:3]))
        active = self.active_rules()
        if active:
            actions.append("已生效规则：%d 条（可在 get_advice 中约束回复）" % len(active))
        report = {
            "生成时间": time.strftime("%Y-%m-%d %H:%M"),
            "窗口天": 7,
            "反思条数": len(recent), "已评分": len(scored),
            "平均分": round(sum(h.get("分数") or 0 for h in scored) /
                            float(len(scored)), 2) if scored else 0,
            "失败样本": len(fails), "失败类别": cats,
            "最差样本": [{"用户": h.get("用户"), "分数": h.get("分数"),
                          "问题": h.get("问题")} for h in worst],
            "在生效规则": [r.get("value") for r in active],
            "行动项": actions,
        }
        try:
            json.dump(report, open(self.weekly_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)
        return report

    # ---------------------------------------------------------- 建议晋升
    @safe
    def promote_candidates(self, days=None):
        """扫描近期低分：同类建议 ≥N 次生成候选（永不自动生效）。"""
        if not bool(self._rule("反思.建议晋升", True)):
            return {"ok": False, "error": "建议晋升已关闭", "created": 0}
        threshold = max(2, int(self._rule("反思.晋升阈值", 3) or 3))
        window = max(1, int(days if days is not None
                            else self._rule("反思.TTL天", _CAND_TTL)))
        return fewshot.promote_candidates(
            self.base, threshold=threshold, days=window)

    @safe
    def list_candidates(self, status=""):
        rows = fewshot.load_candidates(self.base).get("candidates", [])
        if status:
            rows = [c for c in rows if c.get("status") == status]
        return {"候选数": len(rows), "候选": rows}

    @safe
    def confirm_candidate(self, candidate_id, by="user"):
        """人工确认后才写入生效规则文件，并记审计。"""
        return fewshot.decide_candidate(self.base, candidate_id, "confirm", by)

    @safe
    def revoke_candidate(self, candidate_id, by="user"):
        """撤销：从生效文件移除，恢复原来的回复行为，并记审计。"""
        return fewshot.decide_candidate(self.base, candidate_id, "revoke", by)

    @safe
    def active_rules(self):
        return fewshot.promoted_rules(self.base)

    @safe
    def audit_log(self, limit=30):
        return fewshot.audit_rows(self.base, limit=limit)

    # ---------------------------------------------------------- 注入 / 统计
    @safe
    def get_history(self, count=10):
        """获取反思历史"""
        return {"历史": self.history[-count:]}

    @safe
    def worst_answers(self, n=5):
        """获取最差的回答（只从真正评过分的里挑，规则粗筛的"无意见"不算）"""
        scored = self._scored()
        if not scored:
            return []
        return sorted(scored, key=lambda x: x["分数"])[:n]

    @safe
    def average_score(self):
        """平均分：只算真正被评过分的条目。"""
        scored = [h["分数"] for h in self._scored()]
        if not scored:
            return 0
        return sum(scored) / len(scored)

    def _entry_age_days(self, entry):
        if entry.get("ts"):
            return (time.time() - float(entry["ts"])) / 86400.0
        raw = str(entry.get("时间") or "")
        m = re.match(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", raw)
        if not m:
            return 0.0
        try:
            now = time.localtime()
            then = time.mktime((now.tm_year, int(m.group(1)), int(m.group(2)),
                                int(m.group(3)), int(m.group(4)), 0, 0, 0, -1))
            return abs(time.time() - then) / 86400.0
        except Exception:
            return 0.0

    @safe
    def get_advice(self):
        """注入下次 prompt：生效规则 + 30 天内低分建议（防过拟合）。"""
        if self._mode() == "off":
            if not self.history:
                return ""
            cand = [h for h in self.history[-20:]
                    if str(h.get("建议") or "").strip()
                    and isinstance(h.get("分数"), (int, float))]
            if not cand:
                return ""
            worst = min(cand, key=lambda x: x["分数"])
            return str(worst["建议"])[:80] if worst["分数"] < 6 else ""
        ttl = max(1, int(self._rule("反思.TTL天", _CAND_TTL)))
        parts = []
        for rule in self.active_rules()[:2]:
            value = str(rule.get("value") or "").strip()
            if value:
                parts.append(value)
        cand = [h for h in self.history[-30:]
                if str(h.get("建议") or "").strip()
                and isinstance(h.get("分数"), (int, float))
                and h.get("分数") < 6 and self._entry_age_days(h) <= ttl]
        if cand:
            parts.append(str(min(cand, key=lambda x: x["分数"])["建议"])[:80])
        return "；".join(dict.fromkeys(parts))[:120]

    @safe
    def stats(self):
        """统计"""
        scored = self._scored()
        return {
            "总反思次数": self.reflect_count,
            "平均分": round(self.average_score(), 2),
            "历史数": len(self.history),
            "已评分": len(scored),
            "多维评分": self._mode(),
            "失败库": self.failure_stats(),
            "生效规则": len(self.active_rules()),
        }

    @safe
    def clear_history(self):
        """清空反思历史（失败库另用 clear_failures）"""
        self.history = []
        self.reflect_count = 0
        self._save()
        return {"ok": True}

    @safe
    def clear_failures(self):
        fewshot.write_jsonl(fewshot._data_path(self.base, fewshot.FAIL_FILE), [])
        return {"ok": True}

    def run(self, *args):
        return self.stats()
