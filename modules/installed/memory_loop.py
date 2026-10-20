# -*- coding: utf-8 -*-
"""记忆闭环 v12.0 - 编排者：对话→记忆卡总结→遗忘曲线安排→到期复习→检索增强"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, time, json
from core.safe import safe
from modules.base import BaseModule


class MemoryPipeline(BaseModule):
    NAME = "memory_loop"
    VERSION = "1.0"
    """记忆闭环：只当指挥，具体活 trunk.call 给记忆卡/遗忘曲线/向量库/统一记忆"""

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.state_path = os.path.join(self.base, "data", "memory_loop.json")
        self.state = self._load()
        self.episodic_path = os.path.join(self.base, "data", "episodic_memory.json")
        self.episodic_mem = self._load_episodic()

    # ===== 情景记忆 =====
    SCENES = {
        "编程": ["代码", "python", "bug", "报错", "函数", "程序", "脚本", "api", "写一个",
                 "实现", "编程", "数据库", "爬虫", "模块", "接口", "语法"],
        "学习": ["学习", "教程", "怎么学", "资料", "知识", "训练", "课程", "文档", "主题"],
        "系统": ["日志", "设置", "重启", "闪退", "热更新", "配置", "模型", "启动", "版本", "检测"],
        "情感": ["心情", "难过", "开心", "烦", "累", "喜欢", "讨厌", "生气", "谢谢", "加油"],
        "闲聊": ["今天", "天气", "你好", "哈哈", "怎么样", "在吗", "早安", "晚安"],
    }

    def _scene(self, text):
        t = str(text or "")
        for sc, kws in self.SCENES.items():
            if any(k in t for k in kws):
                return sc
        return "日常"

    def _load_episodic(self):
        if os.path.exists(self.episodic_path):
            try:
                return json.load(open(self.episodic_path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return []

    def _save_episodic(self):
        try:
            json.dump(self.episodic_mem[-200:], open(self.episodic_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    @safe
    def remember_scene(self, user_text, answer):
        """情景记忆：记录 什么时候(时间戳) + 什么情景 + 聊了什么"""
        scene = self._scene(user_text)
        self.episodic_mem.append({
            "scene": scene,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": str(user_text)[:80],
            "answer": str(answer)[:120],
        })
        self._save_episodic()
        return scene

    def episodic(self, scene=None, hours=48, limit=3):
        """时间戳检索：按情景 + 时间窗口取最近记忆"""
        try:
            now = time.time()
            out = []
            for e in reversed(self.episodic_mem):
                try:
                    t = time.mktime(time.strptime(e.get("time", ""), "%Y-%m-%d %H:%M:%S"))
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    continue
                if now - t > hours * 3600:
                    continue
                if scene and e.get("scene") != scene:
                    continue
                out.append(e)
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []

    def recall(self, query, top_k=3, hours=48):
        """综合检索：向量相关 + 情景 + 时间戳，返回可注入prompt的上下文"""
        out = []
        # 向量检索
        try:
            for h in self.enhance(query, top_k):
                txt = h.get("text", "") if isinstance(h, dict) else str(h)
                if txt:
                    out.append({"type": "向量", "text": txt[:100]})
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        # 情景记忆（当前问题情景 + 时间窗口）
        scene = self._scene(query)
        for e in self.episodic(scene=scene, hours=hours, limit=2):
            out.append({"type": "情景", "scene": e.get("scene", ""),
                        "time": str(e.get("time", ""))[:16],
                        "text": e.get("text", "")[:80]})
        return out[:top_k]

    def _load(self):
        if os.path.exists(self.state_path):
            try:
                return json.load(open(self.state_path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return {"summarized": 0, "reviews": 0, "last": 0}

    def _save(self):
        try:
            json.dump(self.state, open(self.state_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _log(self, msg):
        if self.trunk:
            try:
                self.trunk._log(msg)
                return
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        print(msg)

    # ① 对话 → 记忆卡总结
    def summarize(self, user_text, answer):
        try:
            r = self.trunk.call("memory_cards", "maybe_summarize", user_text, answer)
            if isinstance(r, dict) and r.get("已总结"):
                self.state["summarized"] += 1
                self._save()
                return True
        except Exception as e:
            self._log("记忆卡失败: %s" % str(e)[:50])
        return False

    # ② 遗忘曲线安排
    def schedule(self, text, importance=0.5):
        try:
            self.trunk.call("forgetting_curve", "remember", text, importance)
            return True
        except Exception as e:
            self._log("遗忘曲线安排失败: %s" % str(e)[:50])
            return False

    # ③ 到期复习
    def do_review(self):
        """到期复习：遍历 forgetting_curve.due_review() 返回的 key 列表"""
        reviewed = 0
        try:
            due = self.trunk.call("forgetting_curve", "due_review")
            # 兼容三种返回：{"待复习":N,"项目":[...]} / [...] / 错误 dict
            if isinstance(due, dict) and "error" in due:
                due = None
            if isinstance(due, dict):
                keys = due.get("项目", []) or []
            elif isinstance(due, list):
                keys = due
            else:
                keys = []
            for key in keys[:5]:
                if not key:
                    continue
                try:
                    # review 接受 key（记忆的唯一标识）
                    self.trunk.call("forgetting_curve", "review", str(key))
                    # 复习后强化向量记忆
                    self.trunk.call("vector_store", "add", str(key), tag="复习")
                    reviewed += 1
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            if reviewed:
                self.state["reviews"] += reviewed
                self._save()
        except Exception as e:
            self._log("复习失败: %s" % str(e)[:50])
        return reviewed

    # ④ 检索增强（给 prompt 用）
    def enhance(self, query, top_k=3):
        try:
            r = self.trunk.call("vector_store", "search", query, top_k)
            if isinstance(r, list):
                return r
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return []

    def run(self, user_text="", answer="", query=""):
        """一轮记忆闭环"""
        self._log("▶ 记忆闭环开始")
        # 有对话就总结+安排+情景记忆
        if user_text and answer:
            s = self.summarize(user_text, answer)
            self._log("① 记忆卡总结: %s" % ("已总结" if s else "未触发"))
            self.schedule(user_text[:100])
            scene = self.remember_scene(user_text, answer)
            if scene:
                self._log("①+ 情景记忆[%s]: 已记录" % scene)
        # 到期复习
        rv = self.do_review()
        self._log("② 到期复习: %d 条" % rv)
        # 检索增强
        q = query or user_text or "最近学习"
        items = self.enhance(q)
        self._log("③ 检索增强: %d 条" % len(items))
        self._log("▶ 记忆闭环结束")
        return {
            "ok": True,
            "已总结": self.state["summarized"],
            "已复习": self.state["reviews"],
            "本次复习": rv,
            "检索增强": len(items),
            "情景记忆条数": len(self.episodic_mem),
            "最近情景": self.episodic(limit=3),
        }

    # ========== 新增：记忆压缩 + 记忆遗忘 + 记忆提取 + 记忆串联 ==========
    @staticmethod
    def _age_days(ts):
        """兼容字符串/float 两种时间戳，返回天数"""
        try:
            if isinstance(ts, str):
                import time as _t
                return (_t.time() - _t.mktime(_t.strptime(ts, "%Y-%m-%d %H:%M:%S"))) / 86400
            return (time.time() - float(ts)) / 86400
        except Exception:
            return 0.0

    def compress_old_memories(self, days=30):
        """记忆压缩：太久的事压缩成一句话"""
        old = [m for m in self.episodic_mem if self._age_days(m.get("time", 0)) > days]
        if not old:
            return {"压缩": "没有旧记忆需要压缩"}
        # 简单压缩：只保留日期和主题
        compressed = [{"日期": m.get("date", "?"), "主题": m.get("scene", "?")} for m in old]
        return {"压缩数": len(old), "压缩后": compressed[:5]}

    def forget_old_memories(self, days=90):
        """记忆遗忘：太久没提的事慢慢模糊"""
        before = len(self.episodic_mem)
        self.episodic_mem = [m for m in self.episodic_mem if self._age_days(m.get("time", 0)) < days]
        self._save_episodic()
        return {"遗忘前": before, "遗忘后": len(self.episodic_mem), "删除": before - len(self.episodic_mem)}

    def recall_from_month_ago(self, query):
        """记忆提取：能想起一个月前的事"""
        results = []
        for m in self.episodic_mem:
            if query in str(m):
                results.append(m)
        return {"查询": query, "找到": len(results), "结果": results[:5]}

    def link_memories(self, event):
        """记忆串联：'上次你说...后来怎么样了？'"""
        # 找相关的旧记忆
        related = []
        for m in self.episodic_mem[-20:]:
            if event in str(m):
                related.append(m)
        if len(related) >= 2:
            return {"串联": f"上次你说{related[0].get('scene', '?')}，后来{related[-1].get('scene', '?')}怎么样了？"}
        return {"串联": ""}



