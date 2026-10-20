# -*- coding: utf-8 -*-
"""路径安全工具。

所有接收用户/模型给出的路径并准备读写文件的代码，都必须走这里。
不要再用 `path.startswith(root)` 判断：`E:\\xiaoliu_evil` 也会匹配
`E:\\xiaoliu`，这是实测过的绕过。
"""
import os
import re


_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def is_within(root, path):
    """path 是否真的位于 root 内部（含 root 本身）。"""
    try:
        root_n = _norm(root)
        path_n = _norm(path)
        return os.path.commonpath([root_n, path_n]) == root_n
    except (TypeError, ValueError, OSError):
        return False


def safe_join(root, user_path, must_exist=False):
    """把 user_path 安全地拼到 root 下。

    返回规范化绝对路径；非法时返回 None。
    拒绝：空值、NUL、绝对路径、Windows 盘符、UNC、`..` 组件。
    """
    if user_path is None:
        return None
    try:
        raw = str(user_path)
    except Exception:
        return None
    if not raw or "\x00" in raw:
        return None
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None
    # 统一成当前平台分隔符后再判断绝对路径
    probe = raw.replace("/", os.sep).replace("\\", os.sep)
    if os.path.isabs(probe) or _DRIVE_RE.match(probe) or probe.startswith("\\\\"):
        return None
    parts = [p for p in probe.split(os.sep) if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    target = os.path.abspath(os.path.join(os.path.abspath(root), *parts))
    if not is_within(root, target):
        return None
    if must_exist and not os.path.exists(target):
        return None
    return target


def safe_name(name, default="untitled", max_len=80):
    """把用户可控的名字变成单级文件名，不允许路径分隔符。"""
    s = str(name or "").strip()
    s = os.path.basename(s.replace("\\", "/"))
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = s.strip(" .")
    if not s:
        s = default
    return s[:max_len]


def contained_relpath(root, path):
    """返回 path 相对 root 的安全路径；越界返回 None。"""
    if not is_within(root, path):
        return None
    return os.path.relpath(_norm(path), _norm(root))

_SENSITIVE_RELATIVE_PREFIXES = (
    "data/config.json",
    "data/security",
    "data/browsers",
    "data/cookies",
    "data/credentials",
    "core/激活公钥.pem",
    "core/公钥.pem",
    "users",
    "appdata",
    "browser profiles",
    "browser_profiles",
)
_SENSITIVE_SUFFIXES = (".key", ".pem", ".pfx", ".p12")
_SENSITIVE_WORDS = ("私钥", "private_key", "id_rsa", "id_ed25519",
                    "credentials", "cookie")


def has_reparse_point(path):
    """True for symlinks, Windows junctions and other reparse points."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if os.path.islink(path):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse)


def path_has_reparse_component(root, path):
    root = os.path.realpath(os.path.abspath(root))
    target = os.path.realpath(os.path.abspath(path))
    try:
        rel = os.path.relpath(target, root)
    except ValueError:
        return True
    if rel.startswith(".."):
        return True
    current = root
    if has_reparse_point(current):
        return True
    for part in rel.split(os.sep):
        if part in ("", "."):
            continue
        current = os.path.join(current, part)
        if has_reparse_point(current):
            return True
    return False


def safe_join_strict(root, user_path, must_exist=False, reject_links=True):
    """safe_join plus reparse-point rejection for untrusted plugins."""
    target = safe_join(root, user_path, must_exist=must_exist)
    if target is None:
        return None
    if reject_links and path_has_reparse_component(root, target):
        return None
    return target


def is_sensitive_path(path, base=None):
    """Reject paths that must never be exposed to models/plugins."""
    try:
        p = os.path.realpath(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError, OSError):
        return True
    rel = p
    base = base or os.getcwd()
    try:
        rel = os.path.relpath(p, os.path.realpath(os.path.abspath(base)))
    except ValueError:
        rel = p
    rel = rel.replace("\\", "/").lower()
    if rel.startswith("../"):
        # Also catch the common sensitive suffix when the caller passed an
        # absolute path outside its own base.
        suffix = "/" + rel.lstrip("./")
        if any(suffix.endswith(x) or ("/" + x + "/") in suffix
               for x in _SENSITIVE_RELATIVE_PREFIXES):
            return True
    if any(rel == x or rel.startswith(x + "/") for x in _SENSITIVE_RELATIVE_PREFIXES):
        return True
    if any(rel.endswith(x) for x in _SENSITIVE_SUFFIXES):
        return True
    if any(x in rel for x in _SENSITIVE_WORDS):
        return True
    # Credential-bearing directories inside a user profile. Do not reject the
    # whole home directory: the user may legitimately ask the file tool to read
    # an ordinary document there.
    low_path = p.replace("\\", "/").lower()
    for marker in ("/.ssh/", "/.aws/", "/.azure/",
                   "/appdata/roaming/microsoft/credentials/",
                   "/appdata/local/google/chrome/", "/mozilla/firefox/",
                   "/cookies/", "/credentials/", "/browser profiles/"):
        if marker in low_path:
            return True
    return False
