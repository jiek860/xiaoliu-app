# -*- coding: utf-8 -*-
"""插件依赖解析与隔离策略（功能深化二期 · D1 插件市场 / F1 插件运行时）。

两块纯逻辑：

* **依赖解析**：安装插件前算出缺哪些依赖（按 manifest.dependencies），
  交给安装器提示/补装。
* **隔离策略**：判断一个插件是否该进子进程沙箱（高风险 / 执行系统命令 /
  联网 / 写删文件），供运行时决定隔离方式。

不联网、不 import 插件本身，只读 manifest，测试友好。
"""
from __future__ import annotations

import re

_VERSION_RE = re.compile(r"[vV]?\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?")

# 触发"进沙箱"的能力关键字（大小写不敏感，做包含匹配）
_RISKY_CAPS = ("exec", "shell", "subprocess", "network", "http", "socket",
               "file_write", "write_file", "delete", "remove", "system",
               "command")
_RISKY_RISK = ("high", "danger", "dangerous", "高危", "危险")


def parse_version(v):
    """'v1.2.3' / '1.2' / '1' -> (1,2,3)；解析不出按 (0,0,0)。"""
    m = _VERSION_RE.match(str(v or "").strip())
    if not m:
        return (0, 0, 0)
    parts = [int(x) if x is not None else 0 for x in m.groups()]
    return tuple(parts)


def newer(remote, local):
    """远端版本是否比本地严格更新。"""
    return parse_version(remote) > parse_version(local)


def _dep_name(d):
    if isinstance(d, str):
        return d.strip()
    if isinstance(d, dict):
        return str(d.get("name") or d.get("id") or "").strip()
    return ""


def missing_deps(manifest, is_installed):
    """manifest.dependencies 里尚未安装的依赖名列表。

    ``is_installed`` 是 ``name -> bool`` 的回调（避免本模块依赖全局注册表）。
    """
    deps = (manifest or {}).get("dependencies") or []
    out = []
    for d in deps:
        name = _dep_name(d)
        if name and not is_installed(name):
            out.append(name)
    return out


def should_isolate(manifest):
    """高风险/危险能力 -> True（建议进子进程沙箱）。"""
    manifest = manifest or {}
    if str(manifest.get("risk") or "").strip().lower() in _RISKY_RISK:
        return True
    caps = [str(c).lower() for c in (manifest.get("capabilities") or [])]
    return any(any(k in c for k in _RISKY_CAPS) for c in caps)