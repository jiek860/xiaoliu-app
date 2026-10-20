# -*- coding: utf-8 -*-
"""HTTP(S)-only URL opener.

All application HTTP requests should pass through NetGuard first. This module
adds the second, mandatory boundary: only http/https URLs with a hostname may
reach urllib. Keeping the actual urlopen call in one audited place also makes
the Bandit B310 allow-list reviewable instead of scattered across the tree.
"""
from __future__ import annotations

import urllib.parse
import urllib.request


def validate_http_url(url):
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except (TypeError, ValueError):
        return False
    return (parsed.scheme.lower() in ("http", "https")
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password)


def open_url(url, *, timeout=10, headers=None, data=None, method=None):
    """Open an HTTP(S) URL or Request after strict scheme/host validation."""
    if isinstance(url, urllib.request.Request):
        req = url
        target = req.full_url
    else:
        target = str(url)
        req = urllib.request.Request(
            target, data=data, headers=headers or {}, method=method)
    if not validate_http_url(target):
        raise ValueError("only http/https URLs with a hostname are allowed")
    # Keep the plain-string call path when no custom request is needed. This
    # preserves compatibility with callers/tests that patch urlopen directly.
    open_target = req if (isinstance(url, urllib.request.Request)
                          or headers or data is not None or method) else target
    # validate_http_url() above restricts this to http/https URLs.
    return urllib.request.urlopen(open_target, timeout=timeout)  # nosec B310
