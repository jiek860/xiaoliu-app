# -*- coding: utf-8 -*-
"""局域网可信主机配置（虚拟机连物理机的大模型）。

场景
----
程序跑在虚拟机里，Ollama 跑在物理机上，物理机地址是 192.168.x.x。
网络守卫默认拒绝所有私有地址，所以必须在设置里**显式**声明
"这台机器是我的"，否则本地模型永远连不上。

为什么单独成模块
----------------
gui/settings_dialog.py 已接近 600 行上限，这块是独立的配置逻辑，
拆出来更好测也更好复用（命令行/设置界面都能调）。
"""
from __future__ import annotations

import urllib.parse


def entry_of(url):
    """从 URL 提取 "host[:port]" 形式的白名单项。"""
    try:
        p = urllib.parse.urlparse(str(url or ""))
    except ValueError:
        return ""
    host = (p.hostname or "").strip()
    if not host:
        return ""
    return host + (":%d" % p.port if p.port else "")


def current_hosts(trunk):
    try:
        sec = (getattr(trunk, "config", {}) or {}).get("security") or {}
        return [str(x) for x in (sec.get("allow_lan_hosts") or []) if str(x).strip()]
    except Exception:  # 静默是故意的 - 配置异常按空处理
        return []


def trust_host(trunk, url=None):
    """把 url（默认取 ollama_url）的主机加入信任。返回 (ok, 消息)。

    写配置失败必须返回 False，不能假装成功 —— 否则用户以为信任了，
    下次还是连不上，会以为程序坏了。
    """
    cfg = getattr(trunk, "config", None)
    if cfg is None:
        return False, "配置不可用"
    raw = url or cfg.get("ollama_url") or "http://localhost:11434"
    entry = entry_of(raw)
    if not entry:
        return False, "URL 里没有主机名: %s" % str(raw)[:80]
    hosts = current_hosts(trunk)
    if entry in hosts:
        return True, "%s 已在信任列表中" % entry
    hosts.append(entry)
    try:
        sec = cfg.setdefault("security", {})
        sec["allow_lan_hosts"] = hosts
        save = getattr(trunk, "save_config", None)
        if callable(save):
            result = save()
            # save_config 返回 False 表示写盘失败
            if result is False:
                return False, "写入配置失败，请检查 data/config.json 是否可写"
        return True, "已把 %s 加入局域网信任列表" % entry
    except Exception as e:  # 静默是故意的 - 要把原因告诉用户
        return False, "保存失败: %s" % str(e)[:120]


def revoke_host(trunk, entry):
    cfg = getattr(trunk, "config", None) or {}
    hosts = [h for h in current_hosts(trunk) if h != entry]
    try:
        cfg.setdefault("security", {})["allow_lan_hosts"] = hosts
        save = getattr(trunk, "save_config", None)
        if callable(save):
            save()
        return True, "已移除 %s" % entry
    except Exception as e:  # 静默是故意的
        return False, "保存失败: %s" % str(e)[:120]


def describe(trunk):
    """给界面用的一行摘要。"""
    hosts = current_hosts(trunk)
    if not hosts:
        return "未信任任何局域网主机（虚拟机连物理机时需要添加）"
    return "已信任: " + ", ".join(hosts)
