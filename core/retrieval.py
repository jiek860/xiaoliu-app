# -*- coding: utf-8 -*-
"""混合检索：关键词 BM25 + 可选向量检索 + 简单重排。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import math
import os
import re
from collections import Counter


def _tokens(text):
    s = str(text or "").lower()
    # 中文按 2 字滑窗 + 英文/数字词
    words = re.findall(r"[a-z0-9_]{2,}", s)
    zh = re.findall(r"[\u4e00-\u9fff]", s)
    grams = ["".join(zh[i:i + 2]) for i in range(max(0, len(zh) - 1))]
    return words + zh + grams


class HybridRetriever:
    def __init__(self, base=None, vector_store=None):
        self.base = base or "."
        self.vector_store = vector_store
        self.docs = []
        self.path = os.path.join(self.base, "data", "retrieval_index.json")
        self._cache = None
        self._load()

    def _load(self):
        try:
            self.docs = list(json.load(open(self.path, encoding="utf-8")))
        except Exception:
            self.docs = []

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            json.dump(self.docs[-5000:], open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def add(self, text, *, doc_id="", source="", page=None, metadata=None):
        rec = {"id": doc_id or "doc_%d" % len(self.docs),
               "text": str(text or ""),
               "source": source,
               "page": page,
               "metadata": metadata or {}}
        self.docs.append(rec)
        self._cache = None
        self._save()
        return rec

    def add_many(self, items):
        """批量写入：只重建一次索引、只写一次盘。"""
        added = []
        for item in items or []:
            rec = {"id": item.get("id") or "doc_%d" % len(self.docs),
                   "text": str(item.get("text", "")),
                   "source": item.get("source", ""),
                   "page": item.get("page"),
                   "metadata": item.get("metadata") or {}}
            self.docs.append(rec)
            added.append(rec)
        if added:
            self._cache = None
            self._save()
        return added

    def clear(self):
        self.docs = []
        self._cache = None
        self._save()

    def delete_source(self, source):
        before = len(self.docs)
        self.docs = [d for d in self.docs if d.get("source") != source]
        if len(self.docs) != before:
            self._cache = None
            self._save()
            return True
        return False

    def stats(self):
        return {"docs": len(self.docs)}

    def _build_index(self):
        if self._cache is not None:
            return self._cache
        toks = [_tokens(d.get("text", "")) for d in self.docs]
        avg = sum(len(t) for t in toks) / max(1, len(toks))
        df = Counter()
        for t in toks:
            for w in set(t):
                df[w] += 1
        self._cache = (toks, avg, df, len(toks))
        return self._cache

    def _bm25(self, query, k1=1.5, b=0.75):
        if not self.docs:
            return []
        toks, avg, df, n = self._build_index()
        q = _tokens(query)
        scores = []
        for d, t in zip(self.docs, toks, strict=False):
            tf = Counter(t)
            score = 0.0
            for w in q:
                if not tf.get(w):
                    continue
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                denom = tf[w] + k1 * (1 - b + b * len(t) / max(avg, 1))
                score += idf * tf[w] * (k1 + 1) / denom
            if score:
                scores.append((score, d))
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores

    def search(self, query, top_k=5, source=None):
        """BM25 + 向量结果做 RRF 融合，再做轻量词面重排。"""
        combined = {}
        bm = self._bm25(query)
        for rank, (_score, d) in enumerate(bm[:top_k * 3]):
            if source and d.get("source") != source:
                continue
            key = d.get("id") or d.get("text", "")[:80]
            item = combined.setdefault(key, {
                "text": d.get("text", "")[:800],
                "source": d.get("source", ""),
                "page": d.get("page"), "id": key,
                "score": 0.0})
            item["score"] += 1.0 / (60 + rank + 1)
        if self.vector_store and hasattr(self.vector_store, "search"):
            try:
                for rank, r in enumerate(self.vector_store.search(query, top_k=top_k * 2) or []):
                    key = r.get("id") or r.get("text", "")[:80]
                    if source and str(r.get("tag", "")) != source:
                        continue
                    item = combined.setdefault(key, {
                        "text": str(r.get("text", ""))[:800],
                        "source": r.get("tag", "vector"),
                        "page": None, "id": key, "score": 0.0})
                    item["score"] += 1.0 / (60 + rank + 1)
            except Exception as e:  # 静默是故意的 - 向量检索失败时保留 BM25 结果
                _x6_swallowed(__name__, e, "best-effort fallback")
        q_tokens = set(_tokens(query))
        out = []
        for item in combined.values():
            overlap = len(q_tokens & set(_tokens(item.get("text", ""))))
            item["lexical_overlap"] = overlap
            item["score"] = round(float(item["score"]) + overlap * 0.001, 6)
            out.append(item)
        out.sort(key=lambda x: (x["score"], x.get("lexical_overlap", 0)),
                 reverse=True)
        return out[:top_k]
