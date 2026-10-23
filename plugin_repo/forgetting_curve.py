# -*- coding: utf-8 -*-
"""遗忘曲线 v2.0 - 间隔重复记忆 + 记忆提取 + 复习提醒 + 清空 + 统计"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, time
from core.safe import safe
from modules.base import BaseModule


class ForgettingCurve(BaseModule):
    NAME = "forgetting_curve"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.memory_path = os.path.join(self.base, "data", "forgetting.json")
        self.intervals = [1, 3, 7, 15, 30]  # 复习间隔（天）
        self._migrated = False
        self.memory = self._load()
        if self._migrated:
            self._save()

    def _load(self):
        if not os.path.exists(self.memory_path):
            return {}
        try:
            data = json.load(open(self.memory_path, encoding="utf-8"))
        except Exception as e:  # 静默是故意的：坏文件回退空记忆
            _x6_swallowed(__name__, e)
            return {}
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
        # 兼容旧版 forgetting.json：历史格式是 [{text,time,imp,review}, ...]
        if isinstance(data, list):
            out = {}
            now = time.time()
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or item.get("content")
                           or item.get("内容") or "").strip()
                if not text:
                    continue
                key = text
                if key in out:
                    key = "%s#%d" % (text, i)
                n = int(item.get("review") or item.get("学习次数") or 1)
                learned = float(item.get("time") or item.get("上次复习") or now)
                out[key] = {
                    "内容": text,
                    "学习次数": max(1, n),
                    "上次复习": learned,
                    "下次复习": learned + self.intervals[0] * 86400,
                }
            self._migrated = True
            return out
        return {}

    def _save(self):
        from core.safe import atomic_write_json
        try:
            atomic_write_json(self.memory_path, self.memory)
        except Exception as e:
            _x6_swallowed(__name__, e)

    @safe
    def remember(self, key, content):
        """记住一个信息"""
        if not isinstance(self.memory, dict):
            self.memory = {}
        self.memory[str(key)] = {
            "内容": content,
            "学习次数": 1,
            "上次复习": time.time(),
            "下次复习": time.time() + self.intervals[0] * 86400
        }
        self._save()
        return {"记住": key}

    @safe
    def recall(self, query):
        """提取记忆"""
        for key, val in self.memory.items():
            if query in key:
                return {"找到": key, "内容": val["内容"]}
        return {"没找到": query}

    @safe
    def due_review(self):
        """获取需要复习的记忆"""
        now = time.time()
        due = [k for k, v in self.memory.items()
               if isinstance(v, dict) and float(v.get("下次复习", 0) or 0) < now]
        return {"待复习": len(due), "项目": due}

    @safe
    def review(self, key):
        """复习一个记忆"""
        if key in self.memory:
            self.memory[key]["学习次数"] += 1
            n = self.memory[key]["学习次数"]
            interval = self.intervals[min(n, len(self.intervals)-1)] * 86400
            self.memory[key]["下次复习"] = time.time() + interval
            self._save()
            return {"已复习": key, "下次间隔": f"{interval//86400}天"}
        return {"错误": "记忆不存在"}

    @safe
    def forget(self, key):
        """删除一个记忆"""
        if key in self.memory:
            del self.memory[key]
            self._save()
            return {"已删除": key}
        return {"错误": "记忆不存在"}

    @safe
    def list_all(self):
        """列出所有记忆"""
        return {"记忆数": len(self.memory), "项目": list(self.memory.keys())}

    @safe
    def clear_all(self):
        """清空所有记忆"""
        self.memory = {}
        self._save()
        return {"ok": True}

    @safe
    def stats(self):
        """统计"""
        due = self.due_review()
        return {
            "总记忆数": len(self.memory),
            "待复习": due["待复习"],
            "间隔天数": self.intervals
        }

    def run(self, *args):
        return self.stats()

    @safe
    def get_memory_detail(self, key):
        """获取记忆详情"""
        if key in self.memory:
            return self.memory[key]
        return {"错误": "记忆不存在"}

    @safe
    def update_memory(self, key, content):
        """更新记忆内容"""
        if key in self.memory:
            self.memory[key]["内容"] = content
            self._save()
            return {"成功": True}
        return {"错误": "记忆不存在"}

    @safe
    def get_retention_rate(self):
        """记忆保持率"""
        total = len(self.memory)
        if total == 0:
            return {"保持率": "0%"}
        reviewed = sum(1 for v in self.memory.values() if v["学习次数"] > 1)
        rate = f"{reviewed/total*100:.1f}%"
        return {"保持率": rate}


