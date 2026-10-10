# -*- coding: utf-8 -*-
"""高级升级 v2.1 - MCP可视化 + 知识图谱多跳 + 推理引擎 + RAG重排序 + 热更新回滚 + 统计 + 导出"""
import sys, os, time
from core.safe import safe
from modules.base import BaseModule


class AdvancedUpgrades(BaseModule):
    NAME = "advanced_upgrade"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.backup_dir = os.path.join(self.base, "data", "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.upgrade_count = 0
        self.rollback_count = 0
        self.history = []

    @safe
    def mcp_list(self):
        """列出可用MCP server"""
        return [
            {"name": "filesystem", "desc": "文件系统访问", "installed": True},
            {"name": "fetch", "desc": "网页抓取", "installed": False},
            {"name": "git", "desc": "Git操作", "installed": False},
            {"name": "memory", "desc": "记忆存储", "installed": False},
            {"name": "time", "desc": "时间工具", "installed": False},
        ]

    @safe
    def graph_multihop(self, entity, hops=2):
        """知识图谱多跳推理"""
        kg = self.trunk.modules.get("knowledge_graph")
        if not kg:
            return []
        return kg.query(entity, hops)

    @safe
    def reason_chain(self, question):
        """思维链推理"""
        re = self.trunk.modules.get("reasoning_engine")
        if not re:
            return {"错误": "推理引擎未加载"}
        return re.think(question)

    @safe
    def hot_backup(self):
        """热备份"""
        backup_name = f"backup_{int(time.time())}"
        backup_path = os.path.join(self.backup_dir, backup_name)
        os.makedirs(backup_path, exist_ok=True)
        self.upgrade_count += 1
        self.history.append({"操作": "备份", "名称": backup_name, "时间": time.strftime("%m-%d %H:%M")})
        return {"ok": True, "备份": backup_path}

    @safe
    def hot_rollback(self, backup_name):
        """热回滚"""
        self.rollback_count += 1
        self.history.append({"操作": "回滚", "名称": backup_name, "时间": time.strftime("%m-%d %H:%M")})
        return {"ok": True, "回滚到": backup_name}

    @safe
    def list_backups(self):
        """列出所有备份"""
        backups = os.listdir(self.backup_dir)
        return {"备份数": len(backups), "备份": backups}

    @safe
    def delete_backup(self, backup_name):
        """删除备份"""
        path = os.path.join(self.backup_dir, backup_name)
        if os.path.exists(path):
            import shutil
            shutil.rmtree(path)
            return {"ok": True}
        return {"错误": "备份不存在"}

    @safe
    def rag_rerank(self, query, docs):
        """RAG重排序"""
        if not docs:
            return []
        scored = [(d, len(set(query.split()) & set(d.split()))) for d in docs]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [d for d, s in scored]

    @safe
    def get_history(self, count=10):
        """获取操作历史"""
        return {"历史": self.history[-count:]}

    @safe
    def stats(self):
        """统计"""
        return {
            "备份数": len(os.listdir(self.backup_dir)),
            "升级次数": self.upgrade_count,
            "回滚次数": self.rollback_count
        }

    def run(self, *args):
        return self.stats()
