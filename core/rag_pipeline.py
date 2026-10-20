# -*- coding: utf-8 -*-
"""Incremental, permission-aware RAG pipeline.

This is the product-level knowledge layer on top of the existing document
parser / retrieval primitives. It adds:
  * incremental file manifests (unchanged files are not re-indexed);
  * page/offset citations;
  * per-chunk ACL roles;
  * hybrid retrieval + lightweight reranking;
  * atomic index writes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import Counter

from core.document_parser import chunk_text, parse
from core.path_safety import safe_name


def _tokens(text):
    s = str(text or "").lower()
    words = re.findall(r"[a-z0-9_]{2,}", s)
    zh = re.findall(r"[\u4e00-\u9fff]", s)
    grams = ["".join(zh[i:i + 2]) for i in range(max(0, len(zh) - 1))]
    return words + zh + grams


class KnowledgeBase:
    def __init__(self, base, namespace="default", vector_store=None):
        self.base = os.path.realpath(os.path.abspath(base))
        self.namespace = safe_name(namespace or "default", "default")
        self.dir = os.path.join(self.base, "data", "rag", self.namespace)
        os.makedirs(self.dir, exist_ok=True)
        self.index_path = os.path.join(self.dir, "chunks.json")
        self.manifest_path = os.path.join(self.dir, "manifest.json")
        self.vector_store = vector_store
        self._chunks = self._load_json(self.index_path, [])
        self._manifest = self._load_json(self.manifest_path, {})

    @staticmethod
    def _load_json(path, default):
        try:
            data = json.load(open(path, encoding="utf-8-sig"))
            return data if isinstance(data, type(default)) else default
        except Exception:
            return default

    @staticmethod
    def _atomic_json(path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    @staticmethod
    def _file_hash(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def ingest_file(self, path, *, acl_roles=None, force=False):
        path = os.path.realpath(os.path.abspath(str(path or "")))
        if not os.path.isfile(path):
            return {"ok": False, "error": "file not found"}
        try:
            st = os.stat(path)
            digest = self._file_hash(path)
        except OSError as exc:
            return {"ok": False, "error": str(exc)[:120]}
        rel = os.path.relpath(path, self.base).replace("\\", "/")
        old = self._manifest.get(rel) or {}
        if not force and old.get("sha256") == digest:
            return {"ok": True, "skipped": True, "source": rel,
                    "chunks": int(old.get("chunks") or 0)}
        parsed = parse(path)
        if not parsed.get("ok"):
            return {"ok": False, "error": parsed.get("error"), "source": rel}
        roles = sorted({str(x) for x in (acl_roles or []) if str(x)})
        chunks = []
        text = str(parsed.get("text") or "")
        # Page-aware PDF text is stored separately by document_parser.
        pages = (parsed.get("metadata") or {}).get("pages") or []
        if pages:
            for page in pages:
                for c in chunk_text(page.get("text") or "", chunk_size=700,
                                    overlap=100):
                    chunks.append({"text": c["text"], "page": page.get("page"),
                                   "offset": c.get("offset", 0)})
        else:
            for c in chunk_text(text, chunk_size=700, overlap=100):
                chunks.append({"text": c["text"], "page": None,
                               "offset": c.get("offset", 0)})
        self.delete_source(rel, save=False)
        now = time.time()
        for idx, c in enumerate(chunks):
            rec = {
                "id": "%s#%d" % (hashlib.sha256(rel.encode("utf-8")).hexdigest()[:12], idx),
                "text": c["text"], "source": rel, "page": c.get("page"),
                "offset": c.get("offset", 0), "acl_roles": roles,
                "metadata": {"file_sha256": digest, "title": os.path.basename(path),
                             "indexed_at": now},
            }
            self._chunks.append(rec)
        self._manifest[rel] = {"sha256": digest, "size": st.st_size,
                               "mtime": st.st_mtime, "chunks": len(chunks),
                               "acl_roles": roles, "indexed_at": now}
        self._save()
        return {"ok": True, "source": rel, "chunks": len(chunks),
                "skipped": False}

    def ingest_directory(self, directory, *, acl_roles=None, force=False,
                         extensions=None):
        allowed = set(extensions or (".txt", ".md", ".pdf", ".docx", ".xlsx",
                                     ".xlsm", ".pptx", ".html", ".htm", ".csv",
                                     ".json", ".yaml", ".yml"))
        out = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() not in allowed:
                    continue
                r = self.ingest_file(os.path.join(root, name), acl_roles=acl_roles,
                                     force=force)
                out.append(r)
        return {"ok": all(x.get("ok") for x in out), "files": len(out),
                "results": out}

    def delete_source(self, source, *, save=True):
        before = len(self._chunks)
        self._chunks = [c for c in self._chunks if c.get("source") != source]
        self._manifest.pop(source, None)
        if save:
            self._save()
        return len(self._chunks) != before

    @staticmethod
    def _allowed(chunk, role):
        roles = chunk.get("acl_roles") or []
        return not roles or (role and role in roles)

    @staticmethod
    def _lexical_scores(query, chunks):
        q = _tokens(query)
        if not chunks or not q:
            return {}
        toks = [_tokens(c.get("text", "")) for c in chunks]
        avg = sum(len(t) for t in toks) / max(1, len(toks))
        df = Counter()
        for t in toks:
            for w in set(t):
                df[w] += 1
        n = len(toks)
        out = {}
        for chunk, t in zip(chunks, toks, strict=False):
            tf = Counter(t)
            score = 0.0
            for w in q:
                if not tf.get(w):
                    continue
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                denom = tf[w] + 1.5 * (1 - 0.75 + 0.75 * len(t) / max(avg, 1))
                score += idf * tf[w] * 2.5 / denom
            if score:
                out[chunk.get("id")] = score
        return out

    def search(self, query, *, top_k=5, role="viewer", rerank=True):
        chunks = [c for c in self._chunks if self._allowed(c, role)]
        lex = self._lexical_scores(query, chunks)
        fused = {cid: {"rrf": 1.0 / (61 + rank), "lex": score}
                 for rank, (cid, score) in enumerate(
                     sorted(lex.items(), key=lambda x: x[1], reverse=True)[:top_k * 4])}
        if self.vector_store and hasattr(self.vector_store, "search"):
            try:
                for rank, hit in enumerate(self.vector_store.search(query, top_k=top_k * 3) or []):
                    cid = hit.get("id") or ""
                    if cid and any(c.get("id") == cid for c in chunks):
                        rec = fused.setdefault(cid, {"rrf": 0.0, "lex": 0.0})
                        rec["rrf"] += 1.0 / (61 + rank)
            except Exception:  # 静默是故意的
                pass
        by_id = {c.get("id"): c for c in chunks}
        results = []
        q_norm = str(query or "").lower().strip()
        q_terms = set(_tokens(query))
        for cid, scores in fused.items():
            chunk = by_id.get(cid)
            if not chunk:
                continue
            text = str(chunk.get("text") or "")
            overlap = len(q_terms & set(_tokens(text)))
            phrase = 1.0 if q_norm and q_norm in text.lower() else 0.0
            final = scores["rrf"] * 100 + scores["lex"] + overlap * 0.01 + phrase
            results.append({
                "chunk_id": cid, "text": text, "source": chunk.get("source"),
                "page": chunk.get("page"), "offset": chunk.get("offset", 0),
                "score": round(final if rerank else scores["rrf"], 6),
                "citation": self.citation(chunk), "metadata": chunk.get("metadata") or {},
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max(1, int(top_k))]

    @staticmethod
    def citation(chunk):
        source = str(chunk.get("source") or "")
        page = chunk.get("page")
        offset = int(chunk.get("offset") or 0)
        loc = source
        if page is not None:
            loc += "#page=%s" % page
        if offset:
            loc += "&offset=%d" % offset
        return loc

    def stats(self):
        sources = {c.get("source") for c in self._chunks if c.get("source")}
        return {"namespace": self.namespace, "sources": len(sources),
                "chunks": len(self._chunks),
                "manifest_files": len(self._manifest)}

    def _save(self):
        self._atomic_json(self.index_path, self._chunks[-20000:])
        self._atomic_json(self.manifest_path, self._manifest)
