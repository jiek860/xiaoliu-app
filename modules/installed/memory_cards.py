# -*- coding: utf-8 -*-
"""
import os记忆卡系统 v2（规则级）：对话后按规则触发→分类提取→去重→时间衰减检索，喂回 prompt
升级：触发规则（轮数/强信号/话题切换/情绪）、分类标签、Jaccard 去重、时间衰减 hint
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json, os, time, re, threading
from datetime import datetime
from core.safe import safe
from modules.base import BaseModule

CARDS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "memory_cards.jsonl")


class MemoryCards(BaseModule):
    NAME = "memory_cards"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.rounds = 0
        self._last_text = ""
        self._lock = threading.Lock()
        self._hint_history = []  # D3: 最近注入过的卡文本（去重用，最多留 3 批）
        # ---------- 规则配置（规则级，可调） ----------
        self.RULES = {
            "min_rounds": self._rule("记忆卡.min_rounds", 5),          # 最少几轮强制总结
            "recall_days": self._rule("记忆卡.recall_days", 7),       # hint 只带几天内的新记忆
            "max_hint_cards": self._rule("记忆卡.max_hint_cards", 3), # hint 最多带几张卡
            "max_facts": self._rule("记忆卡.max_facts", 3),           # 每张卡最多带几条事实
            "dup_threshold": self._rule("记忆卡.dup_threshold", 0.55),# Jaccard 相似度超过即视为重复
            "topic_words": self._rule("记忆卡.topic_words", 3),       # 话题切换：共同关键词 ≤ 3 判定为切换
        }
        # 强记忆信号：命中立即触发总结（不只等轮数）
        self.SIGNAL_PAT = re.compile(
            r"(我喜欢|我爱|我讨厌|我不喜欢|我的|我要|我想|我打算|我准备|我计划|"
            r"我决定|我买了|我住|我工作|我是|我爸妈|我家|我公司|我儿子|我女儿|"
            r"别忘了|记住|提醒我|下次|以后|重要|生日|考试|目标)"
        )
        # 情绪信号：命中立即触发
        self.EMOTION_PAT = re.compile(r"(高兴|开心|难过|伤心|烦|累|焦虑|紧张|兴奋|生气|委屈|失望)")
        # 话题关键词（用于话题切换检测）
        self.TOPIC_KW = re.compile(
            r"(编程|代码|Python|工作|学习|考试|健身|减肥|吃饭|旅行|游戏|电影|"
            r"音乐|买房|买车|孩子|父母|对象|朋友|钱|工资|项目|论文|跑步|睡觉|"
            r"天气|公园|散步|爬山|宠物|猫|狗|生病|医院|搬家|上班|周末|假期)"
        )

    # ---------- 存取 ----------
    @safe
    def _load_recent(self, n=20):
        if not os.path.exists(CARDS_PATH):
            return []
        lines = open(CARDS_PATH, encoding="utf-8").readlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]

    def _save_card(self, card):
        with open(CARDS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

    # ---------- 触发规则 ----------
    def _should_trigger(self, user_text):
        """规则级触发：轮数 / 强信号 / 话题切换 / 情绪，任一命中即总结"""
        if self.rounds % self.RULES["min_rounds"] == 0:
            return "轮数"
        if self.SIGNAL_PAT.search(user_text):
            return "强信号"
        if self.EMOTION_PAT.search(user_text):
            return "情绪"
        # 话题切换：与上一轮共同话题词太少
        cur = set(self.TOPIC_KW.findall(user_text))
        last = set(self.TOPIC_KW.findall(self._last_text))
        if cur and last and len(cur & last) <= self.RULES["topic_words"]:
            return "话题切换"
        return None

    def _rule(self, key, default):
        """从规则引擎读参数（引擎没注册时用默认，不崩）"""
        try:
            if self.trunk:
                return self.trunk.rule(key, default)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return default

    def maybe_summarize(self, user_text, answer):
        """对话后调用：规则判断是否该总结（线程安全）"""
        with self._lock:
            return self._maybe_summarize_locked(user_text, answer)

    def _maybe_summarize_locked(self, user_text, answer):
        self.rounds += 1
        trigger = self._should_trigger(user_text)
        if not trigger:
            self._last_text = user_text
            return {"触发": False, "卡": None}
        llm = self.trunk.modules.get("llm") if self.trunk else None
        card = None
        if llm:
            card = self._llm_card(user_text, answer, trigger)
        if not card:
            card = self._rule_card(user_text, trigger)
        if card:
            if self._is_dup(card):
                self._last_text = user_text
                return {"触发": True, "卡": card, "重复": True}
            card["trigger"] = trigger
            self._save_card(card)
            self._log("记忆卡[%s]: %s" % (trigger, "、".join(card.get("facts", [])[:2])))
        self._last_text = user_text
        return {"触发": trigger is not None, "卡": card}

    # ---------- LLM 提取（分类标签） ----------
    def _llm_card(self, user_text, answer, trigger):
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return None
        try:
            prompt = """把下面这段对话总结成小6对用户的记忆卡。只输出JSON：
{"facts": ["每条事实不超过20字，标注类型：偏好/计划/事实/情感/关系，如\"偏好:喜欢Python\""],
 "feelings": "他当时的情绪（一个词）",
 "follow_up": "以后可以主动问的事，没有就null"}

对话：
用户: %s
小6: %s
JSON:""" % (user_text[:200], answer[:200])
            raw = llm.chat([{"role": "user", "content": prompt}])
            m = re.search(r'\{[^{}]*"facts"[^{}]*\}', raw, re.DOTALL)
            if m:
                card = json.loads(m.group())
                card["date"] = datetime.now().strftime("%Y-%m-%d")
                card["time"] = time.time()
                return card
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return None

    # ---------- 规则提取（分类 + 多类型） ----------
    def _rule_card(self, user_text, trigger):
        facts = []
        if re.search(r"(我要|我打算|我准备|我计划|我想).{1,30}(学|做|去|考|买|写)", user_text):
            facts.append("计划:" + re.search(r"(我要|我打算|我准备|我计划|我想).{1,30}", user_text).group(0)[:25])
        if re.search(r"(我喜欢|我爱|我讨厌|我不喜欢).{1,25}", user_text):
            facts.append("偏好:" + re.search(r"(我喜欢|我爱|我讨厌|我不喜欢).{1,25}", user_text).group(0)[:25])
        if re.search(r"(我买了|我住|我工作|我是|我家|我公司).{1,25}", user_text):
            facts.append("事实:" + re.search(r"(我买了|我住|我工作|我是|我家|我公司).{1,25}", user_text).group(0)[:25])
        if re.search(r"(高兴|开心|难过|烦|累|焦虑)", user_text):
            facts.append("情感:用户情绪波动")
        if not facts:
            facts.append("事实:" + user_text[:25])
        return {"date": datetime.now().strftime("%Y-%m-%d"),
                "facts": facts[:self.RULES["max_facts"]],
                "feelings": "中性", "follow_up": None, "time": time.time()}

    # ---------- 去重规则 ----------
    def _is_dup(self, card):
        recent = self._load_recent(10)
        if not recent:
            return False
        new = set("".join(card.get("facts", [])))
        for old in recent:
            oldf = set("".join(old.get("facts", [])))
            if not new or not oldf:
                continue
            j = len(new & oldf) / max(len(new), len(oldf))
            if j >= self.RULES["dup_threshold"]:
                return True
        return False

    # ---------- 检索规则（时间衰减 hint） ----------
    def hint(self):
        """取最近记忆卡：7天内优先 + 有 follow_up/偏好/计划 的高价值优先"""
        cards = self._load_recent(20)
        if not cards:
            return ""
        now = time.time()
        DAY = 86400
        scored = []
        for c in cards:
            if not c.get("facts"):
                continue
            age = now - c.get("time", 0)
            recency = 1.0 if age <= self.RULES["recall_days"] * DAY else max(0.0, 1 - (age - self.RULES["recall_days"] * DAY) / (30 * DAY))
            value = 1.0
            joined = "".join(c.get("facts", []))
            if any(k in joined for k in ("偏好", "计划", "follow")):
                value += 0.5
            if c.get("follow_up"):
                value += 0.5
            scored.append((recency * value, c))
        scored.sort(key=lambda x: -x[0])
        lines = []
        for _, c in scored[:self.RULES["max_hint_cards"]]:
            facts = "、".join(c.get("facts", [])[:self.RULES["max_facts"]])
            # D3: 与最近注入过的卡去重（Jaccard > 0.55 跳过，避免每轮重复喂同一张）
            if facts and self._dup_with_history(facts):
                continue
            if facts:
                lines.append(facts)
        if not lines:
            return ""
        # 记录本次注入，供下次去重
        self._hint_history.append(" ".join(lines))
        self._hint_history = self._hint_history[-3:]
        return "【小6记得这些事】" + "；".join(lines[:3]) + " ——聊到相关话题自然带出来，别像查户口"

    def _dup_with_history(self, facts):
        """D3: 与最近注入过的卡文本算 Jaccard，重复返回 True"""
        if not self._hint_history:
            return False
        a = set(facts)
        for h in self._hint_history:
            b = set(h)
            if not a or not b:
                continue
            inter = len(a & b)
            union = len(a | b)
            if union and inter / union > self.RULES["dup_threshold"]:
                return True
        return False

    def _log(self, msg):
        try:
            if self.trunk:
                self.trunk._log(msg)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def stats(self):
        cards = self._load_recent(50)
        return {"记忆卡总数": len(cards),
                "最新": cards[-1].get("date", "?") if cards else "无"}

    def run(self, *a):
        return self.stats()

    # ========== 新增：记忆分类 + 记忆重要性 + 记忆搜索 + 记忆关联 ==========
    def classify_card(self, facts):
        """记忆分类：工作/生活/朋友"""
        work_kw = ["工作", "项目", "老板", "同事", "代码", "编程", "会议", "上班"]
        life_kw = ["吃饭", "睡觉", "天气", "散步", "健身", "游戏", "电影", "音乐"]
        friend_kw = ["朋友", "张三", "李四", "王", "聚会", "聊天"]

        text = " ".join(facts)
        if any(k in text for k in work_kw):
            return "工作"
        elif any(k in text for k in life_kw):
            return "生活"
        elif any(k in text for k in friend_kw):
            return "朋友"
        return "其他"

    def set_importance(self, card, level=3):
        """记忆重要性：1低/3中/5高"""
        card["重要性"] = level
        return card

    def search_cards(self, keyword):
        """记忆搜索：能搜'上周说的那个事'"""
        cards = self._load_recent(50)
        found = []
        for c in cards:
            facts = c.get("facts", [])
            for f in facts:
                if keyword in f:
                    found.append({"日期": c.get("date", "?"), "内容": f})
                    break
        return {"找到": len(found), "结果": found}

    def recall_related(self, person_name):
        """记忆关联：提到'张三'自动想起他说过的话"""
        cards = self._load_recent(50)
        related = []
        for c in cards:
            facts = c.get("facts", [])
            for f in facts:
                if person_name in f:
                    related.append(f)
        return {"人物": person_name, "相关记忆": related}
