# -*- coding: utf-8 -*-
"""v26-3.2: 记忆自动整理 完整版"""
import os, json, time, re
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
        """一键整理记忆卡

        ⚠️ 这里原来有个**数据丢失**问题（2026-10-13 修）：
            读的时候 `except: pass` 跳过解析失败的行，
            写回却是 `open(path, "w")` **全量覆盖** ——
            于是那几行被**永久删除**，而且返回值里的
            "原始: len(cards)" 报的是**解析成功的条数**（不是文件行数），
            所以返回 {"原始": 5, "保留": 5} 看起来"一条没丢"，
            实际文件里可能有 8 行。

        现在的原则：**坏行原样保留**。解析不了不代表该删 ——
        可能是格式略有问题的有效数据，也可能是别的版本写的。
        宁可留着让人看见，也不能静默抹掉用户的记忆。
        """
        if not os.path.exists(self.cards_path):
            return {"状态": "无记忆卡"}
        cards = []
        bad_lines = []                 # 解析失败的行，原样留着
        total_lines = 0
        with open(self.cards_path, encoding="utf-8") as f:
            for i, ln in enumerate(f, 1):
                if not ln.strip():
                    continue
                total_lines += 1
                try:
                    cards.append(json.loads(ln))
                except Exception as e:
                    bad_lines.append((i, ln.rstrip("\n"),
                                      "%s: %s" % (type(e).__name__,
                                                  str(e)[:60])))

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

        # 4. 写回主文件（先写临时文件再替换，中途崩不会毁掉原文件）
        tmp = self.cards_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for c in active:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
            # 坏行原样保留 —— 不删
            for _ln, raw, _why in bad_lines:
                f.write(raw + "\n")
        os.replace(tmp, self.cards_path)

        r = {
            "原始": total_lines,            # 文件里实际的行数（不是解析成功的数）
            "保留": len(active),
            "合并": merged,
            "归档": len(archived),
        }
        if bad_lines:
            r["无法解析"] = len(bad_lines)
            r["无法解析明细"] = ["第 %d 行（%s）" % (n, why)
                                 for n, _raw, why in bad_lines[:5]]
            r["提示"] = ("有 %d 行没法解析，已**原样保留**在文件里"
                         "（不影响本次整理，但值得看看是不是哪里写坏了）"
                         % len(bad_lines))
        return r

    def check_conflicts(self):
        """检测冲突记忆（同话题不同结论）

        只读：不改记忆卡。每条冲突带上两边的行号与「哪条更新」，
        记忆页照着行号让用户选保留哪一条（``resolve_conflict`` 才写盘）。
        """
        if not os.path.exists(self.cards_path):
            return {"冲突数": 0}
        # 原来写的是 open(...)[-200:] —— 文件对象**不支持切片**，
        # 必然抛 TypeError: '_io.TextIOWrapper' object is not subscriptable，
        # 也就是这个功能从来没成功过一次。作者本意是"读最后 200 行"。
        try:
            with open(self.cards_path, encoding="utf-8") as f:
                all_lines = f.read().splitlines()
        except Exception as e:
            return {"冲突数": 0, "错误": str(e)[:60]}
        start = max(0, len(all_lines) - 200)
        skipped = 0
        rows = []          # [(文件行号(1 起), 卡)]
        for offset, ln in enumerate(all_lines[start:]):
            try:
                card = json.loads(ln)
            except Exception:
                # 跳过个别坏行是对的（一行坏了不该让整个检测读不出来），
                # 但**要报出跳过数** —— 否则"没有冲突"和"全被跳过没检测"分不清
                skipped += 1
                continue
            if isinstance(card, dict):
                rows.append((start + offset + 1, card))
            else:
                skipped += 1
        conflicts = []
        for i, (line1, c1) in enumerate(rows):
            for line2, c2 in rows[i+1:]:
                for a in self._pref_statements(c1):
                    for b in self._pref_statements(c2):
                        if a == b or not self._pref_conflict(a, b):
                            continue
                        newer, older = self._newer_line(
                            (line1, c1), (line2, c2))
                        conflicts.append({
                            "fact1": a, "fact2": b,
                            "line1": line1, "line2": line2,
                            "newer_line": newer, "older_line": older,
                        })
        r = {"冲突数": len(conflicts), "冲突": conflicts[:10]}
        if skipped:
            r["跳过"] = skipped
            r["说明"] = ("有 %d 行记忆卡读不出来已跳过 —— "
                         "本次检测没覆盖这些行" % skipped)
        return r

    @staticmethod
    def _pref_statements(card):
        """一张卡里的偏好句（兼容旧卡「偏好:」事实与 v2 的 preference 卡）。"""
        out = []
        for fact in (card.get("facts") or []):
            fact = str(fact or "").strip()
            if fact.startswith("偏好:"):
                out.append(fact[len("偏好:"):].strip())
        text = str(card.get("text") or "").strip()
        if text:
            for part in re.split(r"[；;]", text):
                part = part.strip()
                if part.startswith("偏好:"):
                    out.append(part[len("偏好:"):].strip())
                elif str(card.get("type") or "") == "preference":
                    out.append(part)
        return [p for p in out if p]

    @staticmethod
    def _pref_conflict(a, b):
        """两句偏好是否冲突：优先用记忆 v2 的同一套规则，失败退回旧前缀比较。"""
        try:
            from core.chat.memory_v2 import same_topic_conflict
            return bool(same_topic_conflict(
                {"type": "preference", "text": str(a)},
                {"type": "preference", "text": str(b)}))
        except Exception:
            return str(a)[:5] == str(b)[:5]

    @staticmethod
    def _newer_line(one, two):
        """比较两条记忆卡的时间，返回 (较新行号, 较早行号)。

        没有时间字段时按文件顺序：后写的算更新（旧卡没带 time 很常见）。
        """
        def _ts(pair):
            line, card = pair
            for key in ("time", "created_at", "updated_at"):
                try:
                    return float(card.get(key))
                except (TypeError, ValueError):
                    continue
            return float(line)
        return ((one[0], two[0]) if _ts(one) >= _ts(two)
                else (two[0], one[0]))

    def resolve_conflict(self, conflict, keep="new"):
        """按用户选择删掉冲突里的一条（批次 O2）。

        keep="new" 保留较新的记忆、删较早那条；``keep="old"`` 反过来。
        只删指定行，其余行与坏行原样保留；写前再核对这行确实是那条偏好，
        避免行号变化后误删别的记忆。
        """
        drop = (conflict or {}).get("older_line" if keep == "new"
                                    else "newer_line")
        try:
            drop = int(drop)
        except (TypeError, ValueError):
            return {"ok": False, "error": "这条冲突没有行号，请重新检查"}
        try:
            with open(self.cards_path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception as e:
            return {"ok": False, "error": "记忆卡读不了：%s" % str(e)[:60]}
        if not 1 <= drop <= len(lines):
            return {"ok": False, "error": "行号已变化，请重新检查冲突"}
        expected = str((conflict or {}).get(
            "fact1" if drop == conflict.get("line1") else "fact2") or "")
        try:
            card = json.loads(lines[drop - 1])
        except Exception:
            card = None
        if not isinstance(card, dict):
            return {"ok": False, "error": "这一行不是有效记忆卡，请重新检查"}
        facts = [str(f) for f in (card.get("facts") or [])]
        text = str(card.get("text") or "")
        if expected and expected not in facts and expected not in text:
            return {"ok": False, "error": "这条记忆已经变了，请重新检查冲突"}
        tmp = self.cards_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for index, ln in enumerate(lines, 1):
                    if index == drop:
                        continue
                    f.write(ln + "\n")
            os.replace(tmp, self.cards_path)
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return {"ok": False, "error": "写回失败：%s" % str(e)[:60]}
        return {"ok": True, "删除": drop}

    def run(self, *a):
        return self.auto_organize()
