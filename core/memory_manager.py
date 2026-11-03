# -*- coding: utf-8 -*-
"""记忆管理：查看、编辑、删除、遗忘、来源和置信度。

第 4 批深度①起加"分层记忆"：每条记忆带一个 ``layer``
（``work`` 工作 / ``episodic`` 情景 / ``semantic`` 语义），
存储仍是同一个 ``data/memory_cards.jsonl``（老卡片不迁移、只补字段），
但读取可以按层分开（``list(layer=...)`` / ``search(layer=...)`` / ``recall``）。
分层的好处：回复时先召回"语义 + 情景"（长期有用），
当前任务相关的临时上下文（工作记忆）用更小的预算、更短的时效。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import time
import uuid
from core.data_paths import data_path

try:
    from core.chat.memory_v2 import LAYERS, infer_layer, infer_type
except Exception:  # pragma: no cover - 记忆 v2 不可用时退化成单层
    LAYERS = ("work", "episodic", "semantic")

    def infer_layer(text, ctype=""):
        return "semantic"

    def infer_type(text):
        return "fact"

LAYER_NAMES = {"work": "工作记忆", "episodic": "情景记忆", "semantic": "语义记忆"}


class MemoryManager:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = data_path(self, "memory_cards.jsonl")
        self.archive_dir = data_path(self, "memory_archive")
        self.tombstone_path = data_path(self, "memory_tombstones.jsonl")
        os.makedirs(self.archive_dir, exist_ok=True)

    @staticmethod
    def _layer_of(rec):
        """记忆所属层：老卡片没写 layer 的按文本/类型推断。"""
        layer = str((rec or {}).get("layer") or "")
        if layer in LAYERS:
            return layer
        return infer_layer(str((rec or {}).get("text") or ""),
                           str((rec or {}).get("type") or ""))

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
                    d.setdefault("layer", self._layer_of(d))
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

    def list(self, limit=200, layer=None):
        now = time.time()
        rows = [r for r in self._load() if not self._expired(r, now)]
        if layer in LAYERS:
            rows = [r for r in rows if self._layer_of(r) == layer]
        return rows[-limit:]

    def layers(self):
        """分层统计（工作/情景/语义各多少条、各自最新的几条）。"""
        now = time.time()
        rows = [r for r in self._load() if not self._expired(r, now)]
        out = {}
        for name in LAYERS:
            bucket = [r for r in rows if self._layer_of(r) == name]
            out[name] = {"名称": LAYER_NAMES.get(name, name),
                         "条数": len(bucket),
                         "最新": [str(r.get("text") or "")[:40]
                                  for r in bucket[-3:]]}
        out["合计"] = len(rows)
        return out

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
            expires_at=None, dedup=True, dedup_threshold=0.9, layer=None):
        """加一条记忆；B3 默认先去重，命中则合并（加权）而不新增。

        ``layer`` 显式给定时按"只升不降"合并（work < episodic < semantic）。
        """
        text = str(text)
        rows = self._load()
        if dedup:
            dup = self._find_duplicate(rows, text, dedup_threshold)
            if dup is not None:
                dup["confidence"] = min(
                    1.0, float(dup.get("confidence", 1.0)) + 0.1)
                if source and not dup.get("source"):
                    dup["source"] = str(source)
                if layer in LAYERS and \
                        LAYERS.index(layer) > LAYERS.index(self._layer_of(dup)):
                    dup["layer"] = layer
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
               "expires_at": float(expires_at or 0),
               "layer": layer if layer in LAYERS
               else infer_layer(text, infer_type(text))}
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

    def search(self, query, limit=20, layer=None):
        q = str(query or "").lower()
        now = time.time()
        rows = [r for r in self._load()
                if not self._expired(r, now)
                and q in str(r.get("text", "")).lower()]
        if layer in LAYERS:
            rows = [r for r in rows if self._layer_of(r) == layer]
        return rows[-limit:]

    @staticmethod
    def _relevance(query, text):
        try:
            from core.chat.memory_v2 import relevance
            return float(relevance(query, text))
        except Exception:
            q = str(query or "").lower()
            return 1.0 if q and q in str(text or "").lower() else 0.0

    def recall(self, query, limit=5, layers=None, now=None):
        """分层召回（第 4 批深度①）：默认只要"语义 + 情景"两层。

        排序 = 相关度 × 有效置信度（含时间衰减）。工作记忆默认不参与，
        因为它是"这次会话的临时上下文"，长期回答用不上，只会白占预算。
        """
        now = now or time.time()
        want = tuple(layers) if layers else ("semantic", "episodic")
        scored = []
        for rec in self._load():
            if self._expired(rec, now) or self._layer_of(rec) not in want:
                continue
            rel = self._relevance(query, rec.get("text", ""))
            if rel <= 0:
                continue
            score = rel * float(self.effective_confidence(rec, now))
            scored.append((score, rec))
        scored.sort(key=lambda item: -item[0])
        return [rec for _score, rec in scored[:max(0, int(limit or 0))]]
