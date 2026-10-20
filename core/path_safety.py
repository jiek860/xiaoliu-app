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
