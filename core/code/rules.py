# -*- coding: utf-8 -*-
"""项目约定摘要（批次 45.5）：从规则文件里抽“能照做”的短句。

来源：``x6.rules.md`` / ``AGENTS.md`` / ``CONTRIBUTING.md`` / ``coding_rules.md``
以及 ``docs`` 下文件名含“规则/规范/约定/convention/style”的 Markdown，
最多 8 个，避免把整套文档塞进提示。

只保留三类行：标题、列表项、含“必须/不要/禁止/一律/命名/测试/风格”的句子；
结果按文件 mtime+size 做签名缓存（``data/code_rules_cache.json``），
文件没变就不重复扫描。
"""
from __future__ import annotations

import hashlib
import json
import os
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

CANDIDATES = ("x6.rules.md", "AGENTS.md", "CONTRIBUTING.md",
              "coding_rules.md")
_KEYWORDS = ("规则", "规范", "约定", "convention", "style")
_KEEP = ("必须", "不要", "禁止", "一律", "命名", "测试", "风格", "统一",
         "只用", "不能")
MAX_FILES = 8


def _docs(root):
    docs = os.path.join(str(root or "."), "docs")
    found = []
    if not os.path.isdir(docs):
        return found
    try:
        names = sorted(os.listdir(docs))
    except OSError:
        return found
    for name in names:
        low = name.lower()
        if name.endswith(".md") and any(k in low for k in _KEYWORDS):
            found.append("docs/" + name)
    return found[:MAX_FILES]


def candidates(root):
    files = [name for name in CANDIDATES
             if os.path.isfile(os.path.join(str(root or "."), name))]
    files.extend(_docs(root))
    return files[:MAX_FILES]


def extract(text, max_chars=1200):
    """按行筛选：标题 / 列表项 / 含强约束词的句子；去重后限长。"""
    picked, seen = [], set()
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line in seen:
            continue
        keep = (line.startswith("#") or line.startswith(("- ", "* "))
                or bool(re.match(r"^\d+[.)]\s", line))
                or any(word in line for word in _KEEP))
        if not keep:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if not line:
                continue
            picked.append("## " + line)
        else:
            picked.append(line[:160])
        seen.add(line)
        if sum(len(x) + 1 for x in picked) >= int(max_chars):
            break
    out = "\n".join(picked)
    return out[:int(max_chars)]


def _signature(root, files):
    digest = hashlib.sha1()
    for rel in files:
        path = os.path.join(str(root or "."), rel.replace("/", os.sep))
        try:
            stat = os.stat(path)
            digest.update(("%s:%s:%s;" % (rel, int(stat.st_mtime),
                                          stat.st_size)).encode())
        except OSError:
            digest.update(("%s:missing;" % rel).encode())
    return digest.hexdigest()[:16]


def _cache_path(root):
    return os.path.join(str(root or "."), "data", "code_rules_cache.json")


def summary(root, max_chars=1200, use_cache=True):
    """返回项目约定摘要；没有规则文件时返回空串。"""
    root = str(root or ".")
    files = candidates(root)
    if not files:
        return ""
    signature = _signature(root, files)
    cache_path = _cache_path(root)
    if use_cache:
        try:
            with open(cache_path, encoding="utf-8") as fp:
                cached = json.load(fp)
            if cached.get("signature") == signature:
                return str(cached.get("text") or "")
        except (OSError, ValueError, TypeError) as e:
            _x6_swallowed(__name__, e, "read cache")
    parts = []
    for rel in files:
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)),
                      encoding="utf-8", errors="replace") as fp:
                text = fp.read(20000)
        except OSError:
            continue
        block = extract(text, max_chars // max(1, len(files)))
        if block:
            parts.append("## 来源：%s\n%s" % (rel, block))
    result = "\n".join(parts)[:int(max_chars)]
    if use_cache and result:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            tmp = cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump({"signature": signature, "text": result}, fp,
                          ensure_ascii=False)
            os.replace(tmp, cache_path)
        except OSError as e:
            _x6_swallowed(__name__, e, "write cache")
    return result
