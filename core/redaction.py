# -*- coding: utf-8 -*-
"""Central secret redaction for logs, audit records and diagnostics."""
from __future__ import annotations

import json
import re

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token|"
    r"secret|password|passwd|credential|cookie|authorization|private[_-]?key)",
    re.I)

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"), "sk-***"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "gh***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "github_pat_***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.I), r"\1***"),
    (re.compile(r"((?:api[_-]?key|token|secret|password|passwd|cookie)=)[^&\s\"']+",
                re.I), r"\1***"),
    (re.compile(r"([?&](?:key|token|secret|password)=)[^&\s]+", re.I), r"\1***"),
    (re.compile(r"(/hook/)[A-Za-z0-9\-]{8,}"), r"\1***"),
]

_MASK = "***REDACTED***"


def redact_text(value, limit=1000):
    text = str(value if value is not None else "")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    if limit and len(text) > limit:
        text = text[:limit] + "...[truncated]"
    return text


def redact_mapping(value, *, _depth=0):
    if _depth > 8:
        return "[depth-limit]"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                out[key] = _MASK
            else:
                out[key] = redact_mapping(item, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_mapping(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def safe_json(value, **kwargs):
    return json.dumps(redact_mapping(value), ensure_ascii=False, **kwargs)
