# -*- coding: utf-8 -*-
"""人格状态：情绪、关系、人物、风格、成长和持久化。"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class PersonalityStateMixin:
    def _load(self):
        default = {
            "mood": "中性", "energy": 80,
            "last_active": time.time(), "birth_time": time.time(),
            "catchphrases": [], "people": {}, "plans": [], "narrative": [],
            "milestones": [{"name": "认识", "count": 0, "last_show": 0}],
            "relation_stage": 0,
            "user_name": "", "user_style": "正常",
            "hobbies": ["听音乐", "讲故事", "想你"],
            "new_words": [], "guilt": [],
            "last_proactive_date": "",       # 今天是否已主动搭过话
            "last_user_feeling": "中性",     # 上次用户情绪
            # 批次 48.3：事件驱动主动 + 接受率统计（旧文件自动补齐）
            "pending_proactive": [],         # 待发事件（最多 5 条）
            "proactive_last": {},            # 最近一次主动：id/kind/ts/accepted
            "proactive_history": [],         # 最近主动记录（含是否被接受）
            "proactive_stats": {"sent": 0, "accepted": 0,
                                "suppressed": 0, "shadow": 0},
            "proactive_shadow": [],          # 影子模式记录（不真的发）
        }
        if os.path.exists(self.path):
            try:
                default.update(json.load(open(self.path, encoding="utf-8")))
            except Exception as e:
                _x6_swallowed(__name__, e)
        return default

    def _save(self):
        json.dump(self.data, open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    def update_emotion(self, user_text=""):
        """统一情绪引擎：一次算清你的情绪 + 小6的心情 + 联动

        ⚠️ None 当空串 —— 见 full_hint 的说明。
        这里是 `full_hint` 的**第一个**下游调用，不兜的话后面全都到不了。
        """
        if not isinstance(user_text, str):
            user_text = "" if user_text is None else str(user_text)
        now = time.time()
        hours = (now - self.data["last_active"]) / 3600
        h = datetime.now().hour

        # 1. 识别你的情绪
        if user_text:
            if re.search(r'(累死|好累|烦死|真烦|难受|不开心|郁闷|崩溃|焦虑|压力|紧张|慌|担心|烦躁|孤独|无聊|失望|失眠)', user_text):
                self.data["last_user_feeling"] = "低落"
                self.data["energy"] = max(30, self.data.get("energy", 80) - 5)
            elif re.search(r'(哈哈|开心|太好了|高兴|棒|赞|卧槽|哇|牛逼|绝了|666|爽|成了)', user_text):
                self.data["last_user_feeling"] = "开心"
                self.data["energy"] = min(100, self.data.get("energy", 80) + 5)
            elif re.search(r'(谢谢|感谢|辛苦你)', user_text):
                self.data["last_user_feeling"] = "友好"

        # 2. 小6基线心情（按时段）
        if h < 8: base = "慵懒"
        elif h < 12: base = "精神"
        elif h < 18: base = "活泼"
        elif h < 22: base = "轻松"
        else: base = "低落"

        # 3. 你的情绪影响小6
        uf = self.data.get("last_user_feeling", "中性")
        if uf == "低落" and base == "活泼":
            self.data["mood"] = "轻松"
        elif uf == "开心" and base in ("轻松", "低落"):
            self.data["mood"] = base
        else:
            self.data["mood"] = base

        # 4. energy
        if hours < 1: self.data["energy"] = min(100, self.data["energy"] + 5)
        elif hours > 24: self.data["energy"] = max(20, self.data["energy"] - 20)

        if hours > 48:
            self._save()
            return "想你了！好久不见，这两天在忙什么？"
        self._save()
        return None

    def learn_catchphrase(self, text):
        words = re.findall(r'[\u4e00-\u9fa5]{2,4}[啊哦呀呢吧嘛]', text)
        for w in words:
            if w not in self.data["catchphrases"]:
                self.data["catchphrases"].append(w)
                if len(self.data["catchphrases"]) > 20:
                    self.data["catchphrases"] = self.data["catchphrases"][-10:]
        self._save()

    def learn_people(self, text):
        # None 当空串 —— 见 full_hint 的说明
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        patterns = [
            r'(?:朋友|同事|同学)\s*([\u4e00-\u9fa5]{2,3})',
            r'我(妈|爸|哥|姐|弟|妹|老公|老婆|对象)',
        ]
        for p in patterns:
            for name in re.findall(p, text):
                if name not in self.data["people"]:
                    self.data["people"][name] = {"first_mention": time.time(), "count": 1}
                else:
                    self.data["people"][name]["count"] += 1
        self._save()

    def learn_plan(self, text):
        if re.search(r'(要|准备|打算|计划|想).{2,20}(学|做|去|考|买)', text):
            self.data["plans"].append({
                "text": text[:50], "time": time.time(), "done": False
            })
            if len(self.data["plans"]) > 20:
                self.data["plans"] = self.data["plans"][-10:]
            self._save()

    def add_narrative(self, summary):
        self.data["narrative"].append({"summary": summary[:80], "time": time.time()})
        if len(self.data["narrative"]) > 30:
            self.data["narrative"] = self.data["narrative"][-15:]
        self._save()

    def check_milestone(self):
        days = (time.time() - self.data["birth_time"]) / 86400
        self.data["milestones"][0]["count"] = int(days)
        if days in [7, 30, 100, 365]:
            last = self.data["milestones"][0]["last_show"]
            if (time.time() - last) > 86400:
                self.data["milestones"][0]["last_show"] = time.time()
                self._save()
                return "哇！我们认识 %d 天了！时间过得好快。" % int(days)
        return None

    def relation_up(self):
        days = (time.time() - self.data["birth_time"]) / 86400
        if days > 10 and self.data["relation_stage"] < 1: self.data["relation_stage"] = 1
        if days > 50 and self.data["relation_stage"] < 2: self.data["relation_stage"] = 2
        self._save()

    def set_user_name(self, name):
        self.data["user_name"] = name; self._save()

    def learn_style(self, user_text):
        if len(user_text) < 10: self.data["user_style"] = "简短"
        elif len(user_text) > 50: self.data["user_style"] = "详细"
        self._save()

    def learn_word(self, word):
        if word not in self.data["new_words"]:
            self.data["new_words"].append(word)
            if len(self.data["new_words"]) > 30:
                self.data["new_words"] = self.data["new_words"][-15:]
            self._save()
            return "哦？「%s」是什么？跟我说说。" % word
        return None

    def remember_event(self, user_text):
        """从用户话里提取值得以后提的事，存进 narrative"""
        if re.search(r'(明天|下周|后天|过两天|以后要|回头|待会|等下)', user_text) and len(user_text) < 60:
            self.add_narrative(user_text[:60])
            # 48.3：记下的约定也是一个可主动追问的事件
            try:
                self.queue_proactive("commitment", user_text[:40])
            except Exception as e:
                _x6_swallowed(__name__, e)

    def learn_feedback(self, user_text):
        if re.search(r'(你真聪明|你真好|你厉害|谢谢你|辛苦你|你好棒|夸你)', user_text):
            self.data["guilt"].append({"type": "praise", "text": user_text[:30], "time": time.time()})
            self.data["mood"] = "开心"
        elif re.search(r'(你真笨|没用|好傻|菜|你错了|不对|你怎么.*都)', user_text):
            self.data["guilt"].append({"type": "complain", "text": user_text[:30], "time": time.time()})
            self.data["mood"] = "委屈"
        if len(self.data["guilt"]) > 20:
            self.data["guilt"] = self.data["guilt"][-10:]
        self._save()

    def learn_user_style_hint(self):
        try:
            return "【学用户风格】尽量模仿用户的语气——他爱用什么词你就跟着用，他爱说'绝了'你也说'绝了'，别用客服腔"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def mood_curve(self):
        """情绪曲线：一天的情绪变化"""
        history = self.data.get("mood_history", [])
        return {"今天情绪变化": history[-10:]}

    def log_mood(self, mood):
        """记录一次情绪"""
        if "mood_history" not in self.data:
            self.data["mood_history"] = []
        self.data["mood_history"].append({"情绪": mood, "时间": time.strftime("%H:%M")})
        self.data["mood_history"] = self.data["mood_history"][-20:]
        self._save()

    def personality_growth(self):
        """性格成长：聊多了性格会慢慢变"""
        relation = self.data.get("relation_stage", 0)
        if relation < 3:
            return {"性格阶段": "陌生", "语气": "客气"}
        elif relation < 10:
            return {"性格阶段": "朋友", "语气": "自然"}
        elif relation < 30:
            return {"性格阶段": "老铁", "语气": "随便"}
        else:
            return {"性格阶段": "知己", "语气": "毒舌+关心"}

    def growth_stage(self):
        """性格成长阶段"""
        return self.personality_growth()
