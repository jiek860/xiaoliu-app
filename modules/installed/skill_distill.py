# -*- coding: utf-8 -*-
"""技能沉淀 v2.0 - 成功任务沉淀为可复用技能 + 高频技能 + 清空 + 统计"""
import os, json, time, sys
from core.safe import safe
from modules.base import BaseModule


class SkillDistill(BaseModule):
    NAME = "skill_distill"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.skills_path = os.path.join(self.base, "data", "skills_distilled.json")
        self.skills = self._load()
        self.distill_count = 0

    def _load(self):
        if os.path.exists(self.skills_path):
            try:
                return json.load(open(self.skills_path, encoding="utf-8"))
            except: pass
        return []

    def _save(self):
        from core.safe import atomic_write_json
        try:
            atomic_write_json(self.skills_path, self.skills)
        except: pass

    @safe
    def distill(self, task, result, success=True):
        """沉淀成功任务为技能"""
        if not success:
            return {"跳过": "失败任务不沉淀"}

        skill = {
            "名称": task[:30],
            "怎么做": result[:200],
            "次数": 1,
            "时间": time.strftime("%m-%d %H:%M")
        }

        # 合并相似技能
        for s in self.skills:
            if s["名称"] == skill["名称"]:
                s["次数"] += 1
                return {"已合并": s["名称"], "次数": s["次数"]}

        self.skills.append(skill)
        self.distill_count += 1
        self._save()
        return {"已沉淀": skill["名称"]}

    @safe
    def list_skills(self):
        """列出所有技能"""
        return {"技能数": len(self.skills), "技能": [s["名称"] for s in self.skills]}

    @safe
    def top_skills(self, n=5):
        """高频技能"""
        if not self.skills:
            return []
        sorted_s = sorted(self.skills, key=lambda x: x["次数"], reverse=True)
        return sorted_s[:n]

    @safe
    def delete_skill(self, name):
        """删除技能"""
        before = len(self.skills)
        self.skills = [s for s in self.skills if s["名称"] != name]
        self._save()
        return {"ok": len(self.skills) < before}

    @safe
    def clear_all(self):
        """清空所有技能"""
        self.skills = []
        self.distill_count = 0
        self._save()
        return {"ok": True}

    @safe
    def stats(self):
        """统计"""
        return {
            "总沉淀次数": self.distill_count,
            "技能总数": len(self.skills)
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        top = self.top_skills(5)
        report = f"""技能沉淀报告
==========
总沉淀次数: {s['总沉淀次数']}
技能总数: {s['技能总数']}
高频技能: {[t['名称'] for t in top]}
"""
        return {"报告": report}

    def run(self, *args):
        return self.stats()

