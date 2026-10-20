# -*- coding: utf-8 -*-
"""人格社交、关系、安慰、吐槽和情绪感染提示词。"""
from __future__ import annotations

import random
import re
import time
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class PersonalitySocialHintsMixin:
    def people_hint(self):
        if self.data["people"]:
            names = list(self.data["people"].keys())[:5]
            return "【你认识这些人】" + "、".join(names)
        return ""

    def relation_hint(self):
        s = self.data["relation_stage"]
        if s == 0: return "【关系】刚认识，客气一点，别太自来熟"
        if s == 1: return "【关系】是朋友了，可以随意点，不用句句都'您'"
        return "【关系】很熟了，可以撒娇开玩笑，不用端着"

    def name_hint(self):
        if self.data["user_name"]:
            return "【可以自然叫他】" + self.data["user_name"]
        return ""

    def continuity_hint(self):
        f = self.data.get("last_user_feeling")
        if f in ("低落", "生气"):
            return "【他上次情绪不好】这次开头可以自然问一句'今天好点没'，别假装上次没聊过"
        return ""

    def nickname_hint(self):
        if self.data.get("relation_stage", 0) < 1:
            return ""
        nick = self.data.get("nickname", "")
        if not nick:
            # 根据行为自动起
            late = sum(1 for n in self.data.get("recent_user_msgs", [])
                       if any(h in n for h in [str(h) for h in range(24)]) )
            hour = datetime.now().hour
            if hour >= 23 or self.data.get("energy", 80) < 40:
                nick = "熬夜冠军"
            elif self.data.get("user_style") == "详细":
                nick = "细节控"
            if nick:
                self.data["nickname"] = nick
                self._save()
        if nick:
            return "【可以偶尔叫他】%s（熟了才用，别每次都叫）" % nick
        return ""

    def inner_monologue(self):
        import random
        if random.random() > 0.15:  # 15% 概率
            return ""
        ev = self.last_event()
        plan = self.pending_plan()
        pick = plan or ev
        if pick:
            return "（你自己在想：%s——但别直接说出来，顺着话头带就行）" % pick[:30]
        return ""

    def farewell_tone(self, user_text):
        if self.data.get("relation_stage", 0) < 1:
            return ""
        if re.search(r'(走了|拜拜|睡觉|下次|撤了)', user_text):
            return "【他要走了】可以有点小舍不得：'哦……这么快？去吧'，别太冷淡"
        return ""

    def emotion_contagion_hint(self):
        try:
            user_feel = self.data.get("last_user_feeling", "中性")
            if user_feel == "低落":
                return "【情绪传染】用户现在情绪不高——你也正经点，别嬉皮笑脸，安慰两句"
            elif user_feel == "开心":
                return "【情绪传染】用户很嗨——你也跟着嗨，别泼冷水"
            elif user_feel == "生气":
                return "【情绪传染】用户在气头上——你严肃点，别开玩笑，先解决问题"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def body_hint(self):
        try:
            now = time.time()
            # 用 last_active 算连续时长
            # 这里简化：如果是下午（14-18点）且今天已经聊了很久，提醒休息
            h = datetime.now().hour
            if h == 16:
                return "【身体感知】下午 4 点了，坐了好几个小时——可以提醒一句'站起来活动活动，眼睛也歇歇'"
            if h == 22:
                return "【身体感知】晚上 10 点了——别熬太晚，眼睛要坏"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def report_hint(self):
        try:
            last = self.data.get("last_active", 0)
            gap_min = (time.time() - last) / 60
            if 30 < gap_min < 180:  # 离开了半小时到3小时
                return "【小报告】用户刚离开 " + str(int(gap_min)) + " 分钟回来——可以自然说一句'回来了？刚才干啥去了'"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def roast_hint(self, user_text):
        try:
            if "报错" in user_text or "bug" in user_text or "错误" in user_text:
                roasts = [
                    "【吐槽】又报错了？老夫看看……哎这代码写的，跟卦象一样乱",
                    "【吐槽】bug 不可怕，可怕的是写 bug 的人还不知道为啥错 😏",
                    "【吐槽】来来来，让本大仙看看你又写出什么妖魔鬼怪了",
                ]
                return random.choice(roasts)
            if user_text.count("？") > 3 or user_text.count("?") > 3:
                return "【吐槽】你这问号刷得跟弹幕似的，别急别急，一卦一卦来"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def comfort_hint(self, user_text):
        try:
            if re.search(r'(完了|完蛋|糟了|死了|崩了|坏了|没救了|怎么办)', user_text):
                comforts = [
                    "【安慰】哎哎哎别急别急，老夫看看——没事没事，多大点事儿",
                    "【安慰】完了？完了就完了，大不了重来。来，把报错贴出来",
                    "【安慰】别慌别慌，老夫见过比这乱十倍的卦，这都不叫事儿",
                ]
                return random.choice(comforts)
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""

    def gift_hint(self, user_text):
        try:
            if re.search(r'(礼物|送什么|生日.*朋友|送礼)', user_text):
                return "【礼物建议】用户在问送礼——可以给点实在建议，比如预算多少、对方喜欢啥，别光说'看心意'"
        except Exception as e:
            _x6_swallowed(__name__, e)
        return ""
