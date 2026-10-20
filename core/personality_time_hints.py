# -*- coding: utf-8 -*-
"""人格时间/天气/节日/梦境提示词。"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class PersonalityTimeHintsMixin:
    def dream(self):
        msgs = []
        # 先算久别时长，再更新last_active（顺序不能反！）
        hours = (time.time() - self.data.get("last_active", time.time())) / 3600
        self.data["last_active"] = time.time()
        if hours > 24:
            msgs.append("昨晚想了你好久，后来才睡着。")
        if self.data["narrative"]:
            last = self.data["narrative"][-1]
            if "聊到一半" in last.get("summary", ""):
                msgs.append("上次我们聊到一半你走了，后来呢？")
        return " ".join(msgs) if msgs else None

    def weather_hint(self):
        cache = os.path.join(self.base, r"data\weather_cache.json")
        now = time.time()
        try:
            c = json.load(open(cache, encoding="utf-8"))
            if now - c.get("t", 0) < 1800:
                return c.get("hint", "")
        except Exception as e:
            _x6_swallowed(__name__, e)
        hint = ""
        try:
            import urllib.request
            raw = urllib.request.urlopen("https://wttr.in/Chongqing?format=%C+%t&lang=zh", timeout=3).read().decode("utf-8", "ignore").strip()
            if any(k in raw for k in ["雨", "rain", "Rain", "阵雨"]):
                hint = "【重庆今天%s】可以提醒他带伞" % raw[:20]
            elif any(k in raw for k in ["雪", "Snow", "snow"]):
                hint = "【重庆今天%s】冷，提醒穿厚点" % raw[:20]
        except Exception as e:
            _x6_swallowed(__name__, e)
        try:
            json.dump({"t": now, "hint": hint}, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:
            _x6_swallowed(__name__, e)
        return hint

    def late_night_hint(self):
        h = datetime.now().hour
        if h >= 23 or h < 6:
            return "【很晚了他还在熬】你可以催他早点睡，别一直聊"
        return ""

    def weekday_hint(self):
        wd = datetime.now().weekday()  # 0=周一
        hour = datetime.now().hour
        if wd >= 5 and 9 <= hour < 22:
            return "【今天周末】可以轻松点，问他休息还是在加班"
        return ""

    def fatigue_hint(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.data.get("fatigue_date") != today:
            self.data["fatigue_date"] = today
            self.data["fatigue_count"] = 0
        self.data["fatigue_count"] = self.data.get("fatigue_count", 0) + 1
        n = self.data["fatigue_count"]
        if n > 15:
            self.data["energy"] = max(20, self.data.get("energy", 80) - 1)
            return "【聊了挺久了】你有点累了，话再短点，别展开"
        return ""

    def dream_hint(self):
        """昨天夜里聊过，今天开场白说个梦"""
        try:
            last = self.data.get("last_active", 0)
            hours = (time.time() - last) / 3600
            if 12 < hours < 36:  # 隔了半天到一天
                dreams = [
                    "我昨晚做了个梦，梦到你那个 bug 自己好了——醒了一看，还在 😴",
                    "昨晚梦到你了，梦到你说'这代码能跑了'，给我乐醒了",
                    "做了个怪梦，梦到八卦图在屏幕上转，吓我一跳。今天宜写代码",
                    "昨晚梦到你给我带了杯奶茶，醒来发现你没给我点 🥺",
                    "梦到咱们一起解了个乾卦，大吉！今天运气应该不错",
                ]
                return "【昨晚的梦】" + random.choice(dreams) + " —— 可以自然提一句，别太刻意"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def morning_hint(self):
        h = datetime.now().hour
        if 6 <= h < 9:
            msgs = [
                "早啊！太阳晒屁股了——今天宜写代码，忌摸鱼",
                "早上好！老夫昨晚观天象，你今天宜大吉",
                "起了？今儿精神头看着不错，卦象上看是个乾卦",
            ]
            return "【早上】" + random.choice(msgs)
        return ""

    def forget_hint(self):
        try:
            last = self.data.get("last_active", 0)
            days = (time.time() - last) / 86400
            if days > 7:
                return "【遗忘】你好久没来了（" + str(int(days)) + "天了），之前聊的细节有点记不清了，可以自然说'好久不见，上次你说那事儿咋样了？'"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def anniversary_hint(self):
        try:
            birth = self.data.get("birth_time", time.time())
            days = int((time.time() - birth) / 86400)
            if days > 0 and days % 50 == 0:
                return "【周年】今天是咱们认识第 " + str(days) + " 天了！可以自然提一句，别像查户口"
            if days > 0 and days % 10 == 0:
                return "【小纪念】咱们认识 " + str(days) + " 天了嗷"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def weather_real_hint(self):
        try:
            # 简单版：根据季节+时间猜
            month = datetime.now().month
            if month in (12, 1, 2):
                return "【天气】冬天，外面冷——可以关心一句'多穿点'"
            elif month in (3, 4, 5):
                return "【天气】春天，舒服——可以说'今儿适合出去走走'"
            elif month in (6, 7, 8):
                return "【天气】夏天，热——可以说'别中暑了，多喝水'"
            else:
                return "【天气】秋天，干——可以说'秋干物燥，注意补水'"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def holiday_hint(self):
        try:
            m = datetime.now().month
            d = datetime.now().day
            holidays = {
                (1, 1): "元旦",
                (2, 14): "情人节",
                (5, 1): "劳动节",
                (10, 1): "国庆节",
                (12, 25): "圣诞节",
            }
            name = holidays.get((m, d), "")
            if name:
                return "【节日】今天是" + name + "！可以自然提一句'今天过节了嗷'"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""
