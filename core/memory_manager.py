# -*- coding: utf-8 -*-
"""记忆管理：查看、编辑、删除、遗忘、来源和置信度。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import time
import uuid


class MemoryManager:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "memory_cards.jsonl")
        self.archive_dir = os.path.join(self.base, "data", "memory_archive")
        self.tombstone_path = os.path.join(self.base, "data", "memory_tombstones.jsonl")
        os.makedirs(self.archive_dir, exist_ok=True)

    def _load(self):
        out = []
        if not os.path.exists(self.path):
            return out
        for i, ln in enumerate(open(self.path, encoding="utf-8"), 1):
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
                if isinstance(d, dict):
                    d.setdefault("id", "mem_%d" % i)
                    out.append(d)
            except Exception as e:
                _x6_swallowed(__name__, e)
                continue
        return out

    def _save(self, rows):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)

    @staticmethod
    def _expired(rec, now=None):
        exp = float(rec.get("expires_at") or 0)
        return bool(exp and exp <= (now or time.time()))

    def list(self, limit=200):
        now = time.time()
        return [r for r in self._load() if not self._expired(r, now)][-limit:]

    @staticmethod
    def _normalize(text):
        return " ".join(str(text or "").lower().split())

    @staticmethod
    def _similar(a, b):
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio()

    def _find_duplicate(self, rows, text, threshold=0.9, now=None):
        """在已有记忆里找最相近的一条（B3 去重）。"""
        norm = self._normalize(text)
        best, best_score = None, 0.0
        for r in rows:
            if self._expired(r, now):
                continue
            other = self._normalize(r.get("text", ""))
            score = 1.0 if norm == other else self._similar(norm, other)
            if score > best_score:
                best, best_score = r, score
        if best is not None and best_score >= float(threshold):
            return best
        return None

    def add(self, text, *, source="", confidence=1.0, tags=None,
            expires_at=None, dedup=True, dedup_threshold=0.9):
        """加一条记忆；B3 默认先去重，命中则合并（加权）而不新增。"""
        text = str(text)
        rows = self._load()
        if dedup:
            dup = self._find_duplicate(rows, text, dedup_threshold)
            if dup is not None:
                dup["confidence"] = min(
                    1.0, float(dup.get("confidence", 1.0)) + 0.1)
                if source and not dup.get("source"):
                    dup["source"] = str(source)
                for t in (tags or []):
                    if t not in (dup.get("tags") or []):
                        dup.setdefault("tags", []).append(t)
                dup["updated_at"] = time.time()
                dup["last_seen"] = time.time()
                self._save(rows)
                return dict(dup, merged=True)
        rec = {"id": "mem_" + uuid.uuid4().hex[:10], "text": text,
               "source": str(source), "confidence": float(confidence),
               "tags": list(tags or []), "created_at": time.time(),
               "last_seen": time.time(), "status": "active",
               "expires_at": float(expires_at or 0)}
        rows.append(rec)
        self._save(rows)
        return rec

    @staticmethod
    def _decay_factor(rec, now=None, half_life_days=30):
        last = float(rec.get("last_seen") or rec.get("updated_at")
                     or rec.get("created_at") or 0)
        if not last:
            return 1.0
        age = max(0.0, float(now if now is not None else time.time()) - last)
        hl = max(1.0, float(half_life_days)) * 86400.0
        return 0.5 ** (age / hl)

    def effective_confidence(self, rec, now=None, half_life_days=30):
        """随时间衰减后的有效置信度（不改存储值，只做展示/排序）。"""
        base = float(rec.get("confidence") or 0)
        return round(base * self._decay_factor(rec, now, half_life_days), 3)

    def decay(self, half_life_days=30, now=None, verify_below=0.3):
        """重算每条记忆的有效置信度与状态（active / verify）。"""
        rows = self._load()
        now = now or time.time()
        changed = 0
        for r in rows:
            if self._expired(r, now):
                continue
            eff = self.effective_confidence(r, now, half_life_days)
            r["effective_confidence"] = eff
            r["status"] = "verify" if eff < float(verify_below) else "active"
            changed += 1
        if changed:
            self._save(rows)
        return {"ok": True, "updated": changed}

    def edit(self, memory_id, text=None, confidence=None, tags=None):
        rows = self._load()
        for r in rows:
            if r.get("id") == memory_id:
                if text is not None:
                    r["text"] = str(text)
                if confidence is not None:
                    r["confidence"] = float(confidence)
                if tags is not None:
                    r["tags"] = list(tags)
                r["updated_at"] = time.time()
                self._save(rows)
                return {"ok": True, "memory": r}
        return {"ok": False, "error": "记忆不存在"}

    def forget(self, memory_id, archive=True):
        rows = self._load()
        found = None
        keep = []
        for r in rows:
            if r.get("id") == memory_id:
                found = r
            else:
                keep.append(r)
        if not found:
            return {"ok": False, "error": "记忆不存在"}
        if archive:
            p = os.path.join(self.archive_dir,
                             time.strftime("%Y%m%d") + ".jsonl")
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"forgot_at": time.time(),
                                    "memory": found},
                                   ensure_ascii=False) + "\n")
        try:
            with open(self.tombstone_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"id": memory_id,
                                    "forgot_at": time.time()},
                                   ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback
        self._save(keep)
        return {"ok": True, "forgotten": memory_id}

    def purge_expired(self):
        rows = self._load()
        now = time.time()
        keep = [r for r in rows if not self._expired(r, now)]
        removed = len(rows) - len(keep)
        if removed:
            self._save(keep)
        return {"ok": True, "removed": removed}

    def search(self, query, limit=20):
        q = str(query or "").lower()
        now = time.time()
        return [r for r in self._load()
                if not self._expired(r, now)
                and q in str(r.get("text", "")).lower()][-limit:]
