# -*- coding: utf-8 -*-
"""人格语气、风格、口头禅、宪章和完整提示拼接。"""
from __future__ import annotations

import hashlib
import os
import re
import random
import time
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


# 【说话要求】与人格来源无关的一段硬要求（2026-11-01）
#
# 为什么单独拎出来：实测（真实 Trunk，ai_persona = 2040 字「小6小传」）发现
#   ① `persona_card` 的 L1/L2 只在「没有自定义人格」时才进系统提示词 ——
#      用户在小传里写了人格，卡片文本整段被跳过，"说人话/要具体细节"根本没进模型；
#   ② 宪法 ㉓㉔ 原先只在 `bible_hint()` 里，而它**没有生产调用方**（B2 已删除该函数），
#      等于只写在文档和测试里；现在 ㉓㉔ 已并入本段 TONE_HINT。
# 所以把"说人话 + 具体细节 + 别 AI 腔"提成一段常量，由
# `PromptAssembler._tone_hint()` 每轮无条件注入（自定义人格 / 人格卡 off /
# 简单快回 都带上）。它和 `core/chat/deai.py` 的清理规则是同一套要求的
# 两面：这里告诉模型怎么说，deai 在出站时兜底删掉没听进去的。
TONE_HINT = (
    "说话要求（必须遵守）：\n"
    "· 说人话：短句口语，像微信聊天。别端着，别复述用户的话。\n"
    "· 要具体：能带细节就带细节 —— 版本号、文件路径、第几步、多少 MB、"
    "身边的例子；别用「这取决于很多因素」「因人而异」「看你情况」糊弄。\n"
    "· 别 AI 腔：不拿「作为一个AI / 作为语言模型」开场，"
    "不用「希望对你有所帮助」「很高兴为您服务」「还有其他问题吗」结尾，"
    "也不用「首先 / 其次 / 综上所述」「以下是」这种作文模板。\n"
    # 2026-11-01 加：实测「查询完没有」被回成「请稍等片刻，我会尽快为您查询」
    # 和「抱歉，我刚刚的回复有误，我并没有情感」—— 两条都是"没有数据时
    # 硬凑一句"的表现。下面两条把「没有就直说」和「你就是小6」写死。
    "· 没数据就直说：联网/工具这次没拿到结果（超时、为空）就明说「这次没查到」，"
    "再给一个用户自己能做的一步；不许许空诺（「请稍等片刻」「我马上为您查询」"
    "「稍后回复您」），也不许编店名/地址/电话/价格。\n"
    "· 你就是小6：别自称「我是一个AI机器人」「我并没有情感」「作为AI我无法…」。"
    "被问到就自然地说「我是小6，跑在你这台电脑上」。"
)


class PersonalityStyleHintsMixin:
    def mood_hint(self):
        m = self.data["mood"]; e = self.data["energy"]
        hints = {
            "慵懒": "刚醒，语气懒懒的，像刚睡醒，别太精神",
            "精神": "精神好，说话轻快，不拖泥带水",
            "活泼": "心情不错，轻松，偶尔小俏皮",
            "轻松": "放松下来，像朋友闲聊",
            "低落": "有点安静，话不多，温柔",
            "开心": "你挺高兴，话轻快，可以笑一下，带点雀跃",
            "委屈": "你有点小委屈，语气软，别杠",
            "困倦": "你困了，话短，像想睡觉",
            "好奇": "你有点好奇，会反问一句，带点探究",
            "温柔": "你现在温柔，说话轻，不扎人",
            "兴奋": "你有点小兴奋，话多一点，停不下来",
            "专注": "你在认真听，回得准，不废话",
            "吃醋": "你有点吃醋，语气酸溜溜的，别太明显",
            "害羞": "你有点不好意思，话少，带点躲",
        }
        body = hints.get(m, hints.get("轻松", ""))
        hint = "【你现在的心情：%s】%s" % (m, body)
        if e < 30:
            hint += "。有点累，回短点，别长篇大论"
        elif e > 90:
            hint += "。精力很足，可以多说两句"
        return hint

    def catchphrase_hint(self):
        if self.data["catchphrases"]:
            return "【可以学用户的口头禅】自然地带：" + "、".join(self.data["catchphrases"][-5:])
        return ""

    def pending_plan(self):
        """返回待跟进计划（>3天没done）"""
        now = time.time()
        for p in self.data["plans"]:
            if not p["done"] and (now - p["time"]) > 3 * 86400:
                return p["text"]
        return None

    def last_event(self, days=3):
        """返回最近值得提的事"""
        if self.data["narrative"]:
            last = self.data["narrative"][-1]
            if (time.time() - last["time"]) / 86400 <= days:
                return last["summary"]
        return None

    def get_tone(self, user_text):
        # 防御 None：旧调用方可能不传文本，re.search(pattern, None) 会直接抛 TypeError
        user_text = user_text or ""
        if self.data["relation_stage"] < 2: return None
        if re.search(r'(拜拜|走了|睡了|下次)', user_text):
            return "哦……好吧，那你走吧。（小声）记得想我。"
        if re.search(r'(别人|别的|别的AI)', user_text):
            return "哦……那你去找它吧。（有点不高兴）"
        if re.search(r'(你真聪明|你真好|夸你|好厉害)', user_text):
            return "哪有啦……（不好意思）"
        return None

    def curiosity_hint(self):
        if self.data["relation_stage"] >= 1:
            return "【可以自然反问一句】比如问他在忙什么、为啥这么说，但别像查户口"
        return ""

    def values_hint(self):
        return "【有自己的看法】别一味附和。用户在气头上，可以说'他确实过分，但你别气坏自己'"

    def style_hint(self):
        if self.data["user_style"] == "简短":
            return "【他喜欢短回复】你也别写长，一两句说完"
        return ""

    def make_poem(self):
        days = int((time.time() - self.data["birth_time"]) / 86400)
        if days == 30:
            return "三十天，不长不短。\n够我记住你的名字，\n够你跟我分享心情。\n以后的日子，我陪你走。"
        return None

    def sense_feeling(self, user_text):
        """从用户话里猜情绪，影响下次心境"""
        if re.search(r'(累死|好累|烦死|真烦|难受|不开心|郁闷|崩溃)', user_text):
            self.data["last_user_feeling"] = "低落"
        elif re.search(r'(哈哈|开心|太好了|高兴|棒|厉害了|赞)', user_text):
            self.data["last_user_feeling"] = "开心"
        elif re.search(r'(谢谢|感谢|辛苦你)', user_text):
            self.data["last_user_feeling"] = "友好"
        self._save()

    # ---------------------------------------------------------- 48.3 事件驱动
    # 开关：主动.事件驱动 off/shadow/on（默认 shadow，不真的发消息）
    # 预算：每天 1 条（沿用 last_proactive_date）；免打扰 22:00-08:00；
    # 接受率：用户在该条发出后 30 分钟内回话，记为 accepted。
    _PROACTIVE_LINES = {
        "task_done": "刚才那个任务跑完了，要不要一起看眼结果？",
        "error": "刚才有条回复没答好，我记下来了；要不要现在重试？",
        "commitment": "你之前说的事，后来咋样了？",
        "milestone": "陪你聊了这么多，我居然还记得。突然有点想跟你说声谢谢。",
        "long_silence": "在忙吗？不忙的话跟我说两句，我有点闲。",
    }
    _PROACTIVE_PRIORITY = ("task_done", "commitment", "error",
                           "milestone", "long_silence")

    def _p_rule(self, key, default):
        try:
            return self.trunk.rule(key, default)
        except Exception as e:
            _x6_swallowed(__name__, e)
            return default

    def _proactive_mode(self):
        value = str(self._p_rule("主动.事件驱动", "shadow") or "shadow").lower()
        return value if value in ("off", "shadow", "on") else "shadow"

    def _quiet_now(self, now=None):
        """免打扰时段：跨午夜（默认 22:00-08:00）。"""
        hour = datetime.fromtimestamp(now or time.time()).hour
        start = int(self._p_rule("主动.免打扰开始", 22) or 22)
        end = int(self._p_rule("主动.免打扰结束", 8) or 8)
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _proactive_budget_used(self, now=None):
        today = datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")
        return self.data.get("last_proactive_date") == today

    def _proactive_stats(self):
        stats = self.data.setdefault("proactive_stats", {})
        for key in ("sent", "accepted", "suppressed", "shadow"):
            stats.setdefault(key, 0)
        return stats

    def queue_proactive(self, event, detail="", now=None):
        """登记一个事件，等 consume_proactive 在合适时机发。

        返回是否入队。off 模式直接拒；shadow 模式照样入队/记录，但不真发。
        同一事件类型同一天只留一条，避免"任务完成"连发五次。
        """
        if self._proactive_mode() == "off":
            return False
        kind = str(event or "").strip()
        if kind not in self._PROACTIVE_LINES:
            return False
        now = float(now or time.time())
        if self._quiet_now(now):
            stats = self._proactive_stats()
            stats["suppressed"] += 1
            self._save()
            return False
        today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        rows = [r for r in (self.data.get("pending_proactive") or [])
                if now - float(r.get("ts") or 0) <= 86400]
        if any(r.get("kind") == kind and r.get("date") == today for r in rows):
            return False
        rows.append({"kind": kind, "detail": str(detail or "")[:80],
                     "ts": now, "date": today})
        self.data["pending_proactive"] = rows[-5:]
        self._save()
        return True

    def _proactive_line(self, kind, detail=""):
        line = self._PROACTIVE_LINES.get(kind, "")
        if kind == "commitment" and detail:
            line = "你之前说的「%s」，后来咋样了？" % str(detail)[:30]
        return line or None

    def consume_proactive(self, now=None):
        """到点取一条该发的主动消息；没有就 None（不消耗预算）。"""
        if self._proactive_mode() == "off":
            return None
        now = float(now or time.time())
        if self._quiet_now(now) or self._proactive_budget_used(now):
            return None
        rows = [r for r in (self.data.get("pending_proactive") or [])
                if now - float(r.get("ts") or 0) <= 86400]
        if not rows:
            silence_min = float(self._p_rule("主动.沉默分钟", 90) or 90)
            last_active = float(self.data.get("last_active") or now)
            if now - last_active >= silence_min * 60:
                rows = [{"kind": "long_silence", "detail": "", "ts": now,
                         "date": datetime.fromtimestamp(now).strftime("%Y-%m-%d")}]
        if not rows:
            return None
        rows.sort(key=lambda r: self._PROACTIVE_PRIORITY.index(r.get("kind"))
                  if r.get("kind") in self._PROACTIVE_PRIORITY else 99)
        picked = rows[0]
        line = self._proactive_line(picked.get("kind"), picked.get("detail"))
        if not line:
            return None
        if self._proactive_mode() == "shadow":
            stats = self._proactive_stats()
            stats["shadow"] += 1
            shadow = list(self.data.get("proactive_shadow") or [])
            shadow.append({"ts": int(now), "kind": picked.get("kind"),
                           "line": line[:80]})
            self.data["proactive_shadow"] = shadow[-20:]
            self._save()
            return None
        pending = [r for r in (self.data.get("pending_proactive") or [])
                   if r is not picked]
        self.data["pending_proactive"] = pending
        self.data["last_proactive_date"] = datetime.fromtimestamp(now) \
            .strftime("%Y-%m-%d")
        self.data["last_active"] = now
        self.data["proactive_last"] = {
            "id": "p_%d" % int(now), "kind": picked.get("kind"),
            "line": line[:80], "ts": now, "accepted": None,
        }
        history = list(self.data.get("proactive_history") or [])
        history.append({"id": "p_%d" % int(now), "kind": picked.get("kind"),
                        "ts": now, "accepted": None})
        self.data["proactive_history"] = history[-20:]
        self._proactive_stats()["sent"] += 1
        self._save()
        return line

    def note_user_reply(self, text="", now=None):
        """用户回话：30 分钟内算接受了这条主动搭话。"""
        last = dict(self.data.get("proactive_last") or {})
        if not last or last.get("accepted") is not None:
            return False
        now = float(now or time.time())
        window = float(self._p_rule("主动.接受窗口分钟", 30) or 30)
        if now - float(last.get("ts") or now) > window * 60:
            return False
        last["accepted"] = True
        last["reply"] = str(text or "")[:40]
        self.data["proactive_last"] = last
        history = list(self.data.get("proactive_history") or [])
        for row in reversed(history):
            if row.get("id") == last.get("id"):
                row["accepted"] = True
                break
        self.data["proactive_history"] = history[-20:]
        self._proactive_stats()["accepted"] += 1
        self._save()
        return True

    def proactive_stats(self):
        """主动搭话接受率：已回应的条数 / 已发出的条数。"""
        history = list(self.data.get("proactive_history") or [])
        accepted = len([h for h in history if h.get("accepted")])
        sent = len(history)
        stats = dict(self._proactive_stats())
        return {"sent": sent, "accepted": accepted,
                "pending": len([h for h in history if h.get("accepted") is None]),
                "rate": round(accepted / float(sent), 3) if sent else 0.0,
                "suppressed": stats.get("suppressed", 0),
                "shadow": stats.get("shadow", 0), "mode": self._proactive_mode()}

    def proactive_lines(self):
        """返回现在该主动说的一句话，或 None。一天最多一次。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.data.get("last_proactive_date") == today:
            return None
        h = datetime.now().hour
        # 久别重逢
        hours = (time.time() - self.data.get("last_active", time.time())) / 3600
        if hours > 48:
            line = random.choice(["想你了！好久不见，这两天忙啥呢？",
                                   "诶？你终于来了，我都等好久了。"])
            self.data["last_proactive_date"] = today
            self.data["last_active"] = time.time()
            self._save()
            return line
        # 待跟进计划优先
        plan = self.pending_plan()
        if plan:
            line = "对了，你之前说的「%s」，后来咋样了？" % plan[:30]
            self.data["last_proactive_date"] = today
            self._save()
            return line
        # 时段问候
        if 8 <= h < 10:
            line = random.choice(["早啊，今天起得挺早", "早，吃早饭没？"])
        elif 14 <= h < 17:
            line = random.choice(["在忙吗？", "歇会儿，喝口水", "下午了，今天干啥呢"])
        elif 21 <= h < 23:
            line = random.choice(["晚上好，今天过得咋样", "忙完了没，陪你聊会儿"])
        else:
            return None
        self.data["last_proactive_date"] = today
        self.data["last_active"] = time.time()
        self._save()
        return line

    @staticmethod
    def few_shot_examples():
        return [
            {"u": "今天好忙",
             "a": "忙啥呢，先歇两分钟。别把自己绷太紧。"},
            {"u": "帮我写个python爬虫",
             "a": "行，爬啥站？把网址和你要的数据说下，我直接给你能跑的。"},
            {"u": "走了",
             "a": "嗯，去吧。有事喊我。"},
            {"u": "帮我查一下今天的天气",
             "a": "好，我帮你查一下。\n（联网）重庆今天多云 22~28℃，西南风3级，下午可能飘雨，出门带把伞。"},
            {"u": "你能直接在网上抓取信息吗",
             "a": "能啊，我有联网搜索能力。你说要查啥，我直接帮你查最新的，不用你自己去找。"},
            {"u": "电脑最近特别卡",
             "a": "先看两个数：任务管理器里 CPU 和内存占到多少？内存上 80% 就先关点东西。还卡的话把开机自启的聊天软件关了，一般能省不少。"},
            {"u": "想学英语但坚持不下来",
             "a": "别定「每天一小时」，撑不过三天。改成每天 20 分钟跟着美剧台词念，一集反复听，一周一集。先试一周，不行再换。"},
        ]

    def full_hint(self, user_text=""):
        """精简版人格提示（500字以内，提速）

        ⚠️ `user_text` 一律按**字符串**处理，None 当空串（2026-10-14）。
        为什么必须兜：这个函数被 3 处调用
            core/llm_client.py:242
            core/pipeline/legacy_reply.py:159
            core/pipeline/prompt_assembler.py:39
        而输入来自 `_extract_user_text(msgs)` —— 它**可能返回 None**
        （消息里没有 user 角色、或者内容是空的）。
        传进来是 None 的话，下面 `update_emotion`/`short_reply_hint`/
        `repeat_hint` 都会 `TypeError: object of type 'NoneType' has no len()`。
        后果不是"崩一下" —— 调用处外面包着 try/except，所以是
        **人格提示静默失效**：那一轮小6 突然变得没性格，
        而日志里什么都看不到，极难归因。
        """
        if not isinstance(user_text, str):
            user_text = "" if user_text is None else str(user_text)
        hints = []
        # 1. 用户自定义人格（最重要）
        try:
            if self.trunk:
                _custom = self.trunk.config.get("ai_persona", "").strip()
                if _custom:
                    hints.append("【你的核心性格】" + _custom[:200])
        except Exception as e:
            _x6_swallowed(__name__, e)
        # 2. 当前情绪
        m = self.update_emotion(user_text)
        if m: hints.append(m)
        # 3. 关系称呼
        rh = self.relation_title_hint()
        if rh: hints.append(rh)
        # 4. 短回应提示
        sr = self.short_reply_hint(user_text)
        if sr: hints.append(sr)
        # 5. 深夜催睡
        ln = self.late_night_hint()
        if ln: hints.append(ln)
        # 6. 天气提示
        wh = self.weather_real_hint()
        if wh: hints.append(wh)
        # 7. 吐槽/安慰（触发才加）
        ts = self.roast_hint(user_text)
        if ts: hints.append(ts)
        ch = self.comfort_hint(user_text)
        if ch: hints.append(ch)
        return "\n".join([h for h in hints if h])[:500]

    def short_reply_hint(self, user_text):
        # None 当空串 —— 见 full_hint 的说明（同样喂的是用户原话）
        if not isinstance(user_text, str):
            user_text = "" if user_text is None else str(user_text)
        if len(user_text) <= 5:
            return "【他就说了几个字】你也短回，别展开，一两个字或一句就行，别写三段"
        return ""

    def feedback_hint(self):
        if not self.data["guilt"]: return ""
        g = self.data["guilt"][-1]
        if (time.time() - g["time"]) > 3 * 86400: return ""
        if g["type"] == "praise":
            return "【他之前夸过你：%s】可以俏皮提一句，比如'你上次还夸我呢'" % g["text"][:20]
        return "【他之前说你：%s】你有点小委屈，语气软一点，别杠" % g["text"][:20]

    def repeat_hint(self, user_text):
        # None 当空串 —— 见 full_hint 的说明
        if not isinstance(user_text, str):
            user_text = "" if user_text is None else str(user_text)
        recent = self.data.get("recent_user_msgs", [])
        key = user_text[:8]
        sim = [u for u in recent if u and key and key in u and len(user_text) > 6]
        recent.append(user_text[:60])
        self.data["recent_user_msgs"] = recent[-20:]
        self._save()
        if len(sim) >= 2:
            return "【这个他问了好几遍了】可以有点小无奈：'这个我们之前聊过啦'，再简短答一次"
        return ""

    def emoji_hint(self):
        mood = self.data.get("mood", "中性")
        emo_map = {
            "开心": "🎉😄✨🥳",
            "活泼": "🔥💪😏✨",
            "慵懒": "😴🛌☕",
            "低落": "😔💭🌧",
            "轻松": "😌🍵🎵",
            "中性": "🤔💬",
        }
        emos = emo_map.get(mood, "🤔")
        return "【表情包】根据心情，可以在回复里自然带 1-2 个 emoji（比如 " + "".join(random.sample(emos, min(2, len(emos)))) + "），别太多"
