# -*- coding: utf-8 -*-
"""Trunk 记忆与知识库读写。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class TrunkMemoryMixin:
    def _load_memory(self):
        """修复：无文件时返回空字典，兼容旧列表格式"""
        if os.path.exists(self.memory_path):
            try:
                d = json.load(open(self.memory_path, "r", encoding="utf-8"))
                if isinstance(d, dict):
                    return d
                if isinstance(d, list):
                    return {"default": d}
            except Exception as e:
                self._log("异常: " + str(e)[:80])
        return {}

    def save_memory(self):
        """MED-01: 原子写 + 加锁，防止多线程写坏文件"""
        if not hasattr(self, "_mem_lock"):
            self._mem_lock = threading.Lock()
        with self._mem_lock:
            _tmp = self.memory_path + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False)
            os.replace(_tmp, self.memory_path)

    def _load_kb(self):
        if os.path.exists(self.kb_index):
            try:
                return json.load(open(self.kb_index, "r", encoding="utf-8"))
            except Exception as e:
                self._log("异常: " + str(e)[:80])
        return []

    def save_kb(self):
        """原子写"""
        _tmp = self.kb_index + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as f:
            json.dump(self.kb_items, f, ensure_ascii=False, indent=2)
        os.replace(_tmp, self.kb_index)

    def kb_add(self, title, content, category="默认"):
        self.kb_items.append({"title": title, "content": content, "category": category, "time": time.time()})
        self.save_kb()

    def kb_search(self, query, category=None):
        results = []
        for item in self.kb_items:
            if category and item.get("category") != category:
                continue
            if query in item.get("title", "") or query in item.get("content", ""):
                results.append(item)
        return results

    def kb_categories(self):
        cats = set()
        for item in self.kb_items:
            cats.add(item.get("category", "默认"))
        return list(cats)

    def _compress_old(self, items):
        """D6: 把最旧的若干条对话压缩成一条摘要记忆（规则式，不调 LLM）"""
        try:
            users = [str(it.get("u", ""))[:80] for it in items if it.get("u")]
            key = "；".join([u for u in users if u and u != "[压缩记忆]"][-5:])
            if not key:
                return None
            return {"u": "[压缩记忆]", "a": "此前聊过: " + key,
                    "t": time.time(), "compressed": True}
        except Exception:
            return None

    def mem_add(self, user, assistant):
        # v11: 多用户隔离——按用户存记忆
        # v15: 记忆去重——和上一条用户输入完全一样就不重复存
        uname = getattr(self, 'current_user', None) or 'default'
        mem_list = self.memory.setdefault(uname, [])
        # 检查重复：上一条的用户输入和当前一样就跳过
        if mem_list and mem_list[-1].get("u") == user:
            # 只更新助手回复，不新增一条
            mem_list[-1]["a"] = assistant
            mem_list[-1]["t"] = time.time()
            self.save_memory()
            return
        mem_list.append({"u": user, "a": assistant, "t": time.time()})
        cap = self.rule("记忆.每人上限", 200)
        if len(mem_list) > cap:
            # D6: 丢弃前先把最旧 10 条压缩成 1 条摘要，长程记忆不蒸发
            comp = self._compress_old(mem_list[:10])
            if comp:
                mem_list = [comp] + mem_list[10:]
            self.memory[uname] = mem_list[-cap:]
        self.save_memory()
        return

    def mem_recent(self, n=5):
        uname = getattr(self, 'current_user', None) or 'default'
        mem = self.memory.get(uname, [])
        return mem[-n:] if mem else []
