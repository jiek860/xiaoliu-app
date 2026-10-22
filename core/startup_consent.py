# -*- coding: utf-8 -*-
"""启动期确认的"只问一次"机制（2026-10-22）。

要解决的问题
------------
每次启动程序都会弹一串确认框：

    协议确认 -> 登录 -> 首次引导 -> MCP 服务器确认 -> 插件能力确认 ...

用户点过"同意/永久允许"后，重启又全部重来。

设计边界（很重要）
------------------
本模块**只管启动期的安全确认**，不管运行期的用户操作：
    可以记住：协议同意、登录态、首次引导、MCP 命令信任、插件能力授权
    绝不记住：覆盖文件、删除文件、关机/重启、执行 shell 命令
    -- 这些每次都必须问，因为它们直接毁数据。

为什么登录态不进这个文件
------------------------
登录凭据属于敏感数据，必须放在 data/users/ 下并受 DPAPI 保护
（见 core/auth.py），不能和普通的"确认标记"混在一个 JSON 里。
本模块只记录"用户已经同意过哪些启动期提示"。
"""
from __future__ import annotations

import json
import os
import threading

STATE_FILE = os.path.join("data", "startup_consent.json")
SCHEMA_VERSION = 1

# 可以一次性记住的启动期确认项
CONSENT_ITEMS = (
    "agreement",        # 用户协议 + 隐私政策
    "onboarding",       # 首次配置引导
    "mcp_trust",        # MCP 启动命令信任（实际数据在 mcp_trust.json）
    "plugin_caps",      # 插件能力授权
)

# 明确**不记住**的项（写在这里是为了让后来者知道这是刻意的）
ALWAYS_ASK = (
    "覆盖文件", "删除文件", "覆盖目标文件", "关机", "重启",
    "执行命令", "自动更新部署", "按控件名点击",
)

_lock = threading.RLock()


def _path(base):
    return os.path.join(str(base or "."), STATE_FILE)


def load(base):
    try:
        with open(_path(base), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data.get("consents") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def save(base, consents):
    """原子写入。失败返回 (False, 原因)，绝不假装成功。"""
    path = _path(base)
    tmp = path + ".tmp"
    with _lock:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"schema_version": SCHEMA_VERSION,
                           "consents": consents or {},
                           "always_ask": list(ALWAYS_ASK)},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True, ""
        except OSError as e:
            return False, "写入启动确认记录失败: %s" % str(e)[:120]


def is_granted(base, item):
    """某一项启动确认是否已经同意过。"""
    return bool((load(base) or {}).get(str(item)))


def grant(base, item, detail=""):
    """记录某项已同意。返回 (ok, 原因)。"""
    import time
    with _lock:
        data = load(base)
        data[str(item)] = {"granted": True,
                           "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "detail": str(detail)[:200]}
        return save(base, data)


def revoke(base, item=None):
    """撤销某一项（或全部）。用于"我想重新被问一次"。"""
    with _lock:
        if item is None:
            return save(base, {})
        data = load(base)
        data.pop(str(item), None)
        return save(base, data)


def summary(base):
    """返回 {"granted": [...], "pending": [...], "always_ask": [...]}"""
    data = load(base)
    granted = [k for k in CONSENT_ITEMS if (data.get(k) or {}).get("granted")]
    return {"granted": granted,
            "pending": [k for k in CONSENT_ITEMS if k not in granted],
            "always_ask": list(ALWAYS_ASK)}


def should_ask(base, item):
    """启动期是否还需要问。ALWAYS_ASK 里的项永远返回 True。"""
    if str(item) in ALWAYS_ASK:
        return True
    return not is_granted(base, item)
