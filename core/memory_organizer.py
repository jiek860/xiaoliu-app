# -*- coding: utf-8 -*-
"""v26-3.2: 记忆自动整理 完整版"""
import os, json, time
from datetime import datetime


class MemoryOrganizer:
    """自动去重/合并/归档/冲突检测"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.cards_path = os.path.join(self.base, "data", "memory_cards.jsonl")
        self.archive_dir = os.path.join(self.base, "data", "archive")
        os.makedirs(self.archive_dir, exist_ok=True)

    def auto_organize(self):
        """一键整理记忆卡"""
        if not os.path.exists(self.cards_path):
            return {"状态": "无记忆卡"}
        cards = []
        for ln in open(self.cards_path, encoding="utf-8"):
            try:
                cards.append(json.loads(ln))
            except Exception:
                pass

        # 1. 去重：相似度>0.7合并
        keep = []
        merged = 0
        for c in cards:
            facts = "".join(c.get("facts", []))
            s1 = set(facts)
            dup = False
            for k in keep:
                s2 = set("".join(k.get("facts", [])))
                if s1 and s2:
                    sim = len(s1 & s2) / len(s1 | s2)
                    if sim > 0.7:
                        # 合并事实
                        for f in c.get("facts", []):
                            if f not in k.get("facts", []):
                                k.setdefault("facts", []).append(f)
                        dup = True
                        merged += 1
                        break
            if not dup:
                keep.append(c)

        # 2. 归档30天前的
        cutoff = time.time() - 30 * 86400
        active = []
        archived = []
        for c in keep:
            if c.get("time", 0) < cutoff:
                archived.append(c)
            else:
                active.append(c)

        # 3. 归档文件
        if archived:
            arch_path = os.path.join(self.archive_dir, "memory_%s.jsonl" % datetime.now().strftime("%Y%m"))
            with open(arch_path, "a", encoding="utf-8") as f:
                for c in archived:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # 4. 写回主文件
        with open(self.cards_path, "w", encoding="utf-8") as f:
            for c in active:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        return {
            "原始": len(cards),
            "保留": len(active),
            "合并": merged,
            "归档": len(archived),
        }

    def check_conflicts(self):
        """检测冲突记忆（同话题不同结论）"""
        if not os.path.exists(self.cards_path):
            return {"冲突数": 0}
        cards = []
        for ln in open(self.cards_path, encoding="utf-8")[-200:]:
            try:
                cards.append(json.loads(ln))
            except Exception:
                pass
        conflicts = []
        for i, c1 in enumerate(cards):
            for c2 in cards[i+1:]:
                f1 = c1.get("facts", [])
                f2 = c2.get("facts", [])
                for a in f1:
                    for b in f2:
                        if a.startswith("偏好:") and b.startswith("偏好:") and a != b:
                            subj1 = a[3:8]
                            subj2 = b[3:8]
                            if subj1 == subj2:
                                conflicts.append({"fact1": a, "fact2": b})
        return {"冲突数": len(conflicts), "冲突": conflicts[:10]}

    def run(self, *a):
        return self.auto_organize()
