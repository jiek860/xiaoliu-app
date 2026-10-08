# -*- coding: utf-8 -*-
"""群聊并行 v2.1 - 多角色对话 + 角色列表 + 历史记录 + 统计 + 清空"""
import sys, os, time
from core.safe import safe
from modules.base import BaseModule


class GroupChatParallel(BaseModule):
    NAME = "group_parallel"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.roles = ["产品经理", "程序员", "设计师", "测试"]
        self.history = []
        self.parallel_count = 0

    @safe
    def chat(self, topic):
        """多角色并行讨论"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}

        discussions = []
        for role in self.roles:
            try:
                r = llm.chat(f"你是{role}，讨论这个话题: {topic[:100]}")
                discussions.append({"角色": role, "观点": r[:150]})
            except: pass

        self.parallel_count += 1
        self.history.append({
            "话题": topic[:50],
            "角色数": len(discussions),
            "时间": time.strftime("%m-%d %H:%M")
        })
        if len(self.history) > 20:
            self.history = self.history[-20:]

        return {"话题": topic, "讨论": discussions}

    @safe
    def list_roles(self):
        """列出所有角色"""
        return {"角色": self.roles}

    @safe
    def add_role(self, role):
        """添加角色"""
        if role not in self.roles:
            self.roles.append(role)
            return {"ok": True, "角色": role}
        return {"错误": "角色已存在"}

    @safe
    def remove_role(self, role):
        """删除角色"""
        before = len(self.roles)
        self.roles = [r for r in self.roles if r != role]
        return {"ok": len(self.roles) < before}

    @safe
    def debate(self, topic, rounds=2):
        """多轮辩论"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}

        rounds_history = []
        for i in range(rounds):
            discussions = []
            for role in self.roles[:3]:  # 前3个角色
                try:
                    r = llm.chat(f"第{i+1}轮辩论，你是{role}，话题: {topic[:80]}")
                    discussions.append({"角色": role, "观点": r[:100]})
                except: pass
            rounds_history.append({"轮次": i+1, "讨论": discussions})

        return {"话题": topic, "轮次": rounds_history}

    @safe
    def get_history(self, count=10):
        """获取历史"""
        return {"历史": self.history[-count:]}

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.parallel_count = 0
        return {"ok": True}

    @safe
    def stats(self):
        """统计"""
        return {
            "总讨论次数": self.parallel_count,
            "角色数": len(self.roles),
            "历史数": len(self.history)
        }

    def run(self, *args):
        if args:
            return self.chat(args[0])
        return self.stats()
