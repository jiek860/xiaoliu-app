# -*- coding: utf-8 -*-
"""统一网络出站网关。

目标不是做系统防火墙，而是让程序自身的出站请求有统一策略、统一记录和
默认安全边界。系统级/子进程强制拦截由 Windows 防火墙桥接层负责。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import ipaddress
import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
import uuid

from core.audit_log import AuditLog

_DEFAULT_ALLOW = {
    "open.bigmodel.cn", "api.deepseek.com", "dashscope.aliyuncs.com",
    "api.moonshot.cn", "api.siliconflow.cn", "gitee.com", "github.com",
    "ollama.com", "cn.bing.com", "www.sogou.com", "html.duckduckgo.com",
    "api.github.com", "raw.githubusercontent.com", "huggingface.co", "hf-mirror.com",
    "open.feishu.cn", "qyapi.weixin.qq.com", "oapi.dingtalk.com",
    "gh-proxy.com", "ghproxy.net", "ghfast.top", "wttr.in",
}
_LOCAL_PURPOSES = {"local_model", "local_mcp", "local_health"}
_LOCAL_PORTS = {11434, 3742, 8899, 8765, 9000}


class NetGuard:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.dir = os.path.join(self.base, "data", "security")
        os.makedirs(self.dir, exist_ok=True)
        self.rules_path = os.path.join(self.dir, "network_rules.json")
        self.events_path = os.path.join(self.dir, "network_events.jsonl")
        self.audit = AuditLog(self.base)
        self._lock = threading.RLock()
        self.rules = self._load()
        self.events = []
        self._dns_cache = {}
        self._max_event_file = 5 * 1024 * 1024

    def _config(self):
        return getattr(self.trunk, "config", {}) or {}

    def _mode(self):
        try:
            return str(((self._config().get("security") or {})
                        .get("network_mode", "standard"))).lower()
        except Exception:
            return "standard"

    def _load(self):
        try:
            d = json.load(open(self.rules_path, encoding="utf-8"))
            return list(d.get("rules") or [])
        except Exception:
            return []

    def _save(self):
        try:
            tmp = self.rules_path + ".tmp"
            json.dump({"version": 1, "rules": self.rules},
                      open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            os.replace(tmp, self.rules_path)
            return True
        except Exception:
            return False

    def approve(self, domain, scope="once", expires=None):
        rec = {"id": "net_" + uuid.uuid4().hex[:10],
               "domain": str(domain).lower(), "scope": scope,
               "expires_at": float(expires or 0),
               "created_at": time.time()}
        if scope == "once":
            rec["_once"] = True
        self.rules.append(rec)
        if scope == "always":
            self._save()
        return {"ok": True, "rule": rec}

    def revoke(self, rule_id):
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.get("id") != rule_id]
        self._save()
        return len(self.rules) < before

    def _domain_allowed(self, host):
        host = (host or "").lower().rstrip(".")
        allowed = set(_DEFAULT_ALLOW)
        try:
            allowed.update(str(x).lower() for x in
                           ((self._config().get("security") or {})
                            .get("allow_domains", []) or []))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        for r in self.rules:
            exp = float(r.get("expires_at") or 0)
            if exp and exp <= time.time():
                continue
            d = str(r.get("domain") or "").lower().lstrip("*.")
            if not d:
                continue
            if host == d or host.endswith("." + d):
                if r.get("_once"):
                    try:
                        self.rules.remove(r)
                    except ValueError:
                        pass
                return True
        for d in allowed:
            d = str(d).lower().lstrip("*.")
            if host == d or host.endswith("." + d):
                return True
        return False

    def _trusted_lan_hosts(self):
        """用户在配置里显式信任的局域网主机（可带端口）。

        典型场景：程序跑在虚拟机里，Ollama 跑在**物理机**上，
        物理机在局域网里的地址是 192.168.x.x。回环白名单救不了这种，
        必须让用户显式声明"这台机器是我的"。
        """
        try:
            sec = (self._config().get("security") or {})
            items = sec.get("allow_lan_hosts") or []
            return {str(x).strip().lower().rstrip("/") for x in items if str(x).strip()}
        except Exception as e:  # 静默是故意的 - 配置读不到就当没有
            _x6_swallowed(__name__, e)
            return set()

    def _lan_cidrs(self):
        """用户声明允许的局域网网段（CIDR），如 192.168.0.0/16。

        与 allow_lan_hosts 的区别：
          · allow_lan_hosts  逐台主机（精确，推荐）
          · allow_lan_cidrs  整段放行（省事，但范围大）
        两者是**或**关系，任一命中即放行。
        """
        try:
            sec = (self._config().get("security") or {})
            return [str(x).strip() for x in (sec.get("allow_lan_cidrs") or [])
                    if str(x).strip()]
        except Exception as e:  # 静默是故意的 - 配置坏了当没有
            _x6_swallowed(__name__, e)
            return []

    def _in_lan_cidr(self, host):
        """host 是否落在用户声明的某个网段里。只接受私有网段。"""
        nets = self._lan_cidrs()
        if not nets:
            return False
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            # 域名解析后再判断（与 _resolves_private 同思路）
            try:
                ip = ipaddress.ip_address(socket.gethostbyname(host))
            except (OSError, ValueError):
                return False
        if not (ip.is_private and not ip.is_loopback):
            return False      # 只放行"局域网私有段"，公网 IP 不走这条路
        for spec in nets:
            try:
                if ip in ipaddress.ip_network(spec, strict=False):
                    return True
            except ValueError:
                continue
        return False

    def _is_trusted_lan(self, host, port):
        """host[:port] 是否落在允许的局域网范围内。

        规则优先级：
          1. allow_lan_cidrs 命中网段  -> 放行（任意端口）
          2. allow_lan_hosts 精确匹配  -> 按写法决定端口
             · "192.168.1.2"        -> 任意端口
             · "192.168.1.2:11434"  -> 仅该端口
        """
        host = (host or "").lower()
        if self._in_lan_cidr(host):
            return True
        trusted = self._trusted_lan_hosts()
        if not trusted:
            return False
        for item in trusted:
            if ":" in item and not item.count(":") > 1:      # IPv4:port
                h, _, p = item.partition(":")
                if h == host and str(port) == p:
                    return True
            elif item == host:
                return True
        return False

    def _local_allowed(self, host, port, purpose):
        if purpose not in _LOCAL_PURPOSES:
            return False
        # ① 回环地址
        if host in ("127.0.0.1", "localhost", "::1"):
            # 本地模型/MCP 端口可由用户配置；health 等只允许已知内置端口。
            if purpose in ("local_model", "local_mcp"):
                return True
            return not port or int(port) in _LOCAL_PORTS
        # ② 用户显式信任的局域网主机（虚拟机连物理机的场景）
        if purpose in ("local_model", "local_mcp", "local_health"):
            return self._is_trusted_lan(host, port)
        return False

    def check(self, url, *, module="unknown", purpose="network", method="GET"):
        parsed = urllib.parse.urlparse(str(url or ""))
        host = (parsed.hostname or "").lower()
        port = parsed.port
        record = {"module": str(module)[:80],
                  "purpose": str(purpose)[:80],
                  "domain": host,
                  "method": str(method)[:10],
                  "scheme": parsed.scheme}
        mode = self._mode()
        try:
            from core.permission_center import get_permission_center
            if get_permission_center(self.trunk).locked and not self._local_allowed(
                    host, port, purpose):
                return self._decision(False, "系统处于紧急锁定状态", record, "lockdown")
        except Exception as e:  # 静默是故意的 - 锁定状态读取失败时继续走正常策略
            _x6_swallowed(__name__, e, "best-effort fallback")
        if mode == "off":
            return self._decision(True, "网络策略关闭", record, "off")
        if parsed.scheme not in ("http", "https"):
            return self._decision(False, "不安全的URL协议", record, "scheme")
        if not host:
            return self._decision(False, "URL缺少主机名", record, "invalid")
        if self._local_allowed(host, port, purpose):
            return self._decision(True, "本地服务白名单", record, "local")
        # 字面 IP 直接判定
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return self._decision(False, "私有/回环/保留地址", record, "private_ip")
        except ValueError:
            # 域名解析后的实际 IP 也必须检查，防止 DNS rebinding 到内网。
            if self._resolves_private(host, port, parsed.scheme):
                return self._decision(False, "域名解析到私有/保留地址",
                                      record, "dns_private_ip")
        if host in ("169.254.169.254", "metadata.google.internal"):
            return self._decision(False, "云元数据地址", record, "metadata")
        if mode == "learning":
            return self._decision(True, "学习模式放行", record, "learning")
        if self._domain_allowed(host):
            return self._decision(True, "域名白名单", record, "allowlist")
        return self._decision(False, "域名不在允许列表", record, "not_allowlisted")

    def _resolves_private(self, host, port, scheme):
        """带缓存的 DNS 检查；解析失败不阻断离线/内网不可达场景。"""
        try:
            resolve = bool(((self._config().get("security") or {})
                            .get("resolve_dns", True)))
        except Exception:
            resolve = True
        if not resolve:
            return False
        now = time.time()
        cached = self._dns_cache.get(host)
        if cached and now - cached[0] < 300:
            return cached[1]
        try:
            infos = socket.getaddrinfo(
                host, port or (443 if scheme == "https" else 80),
                type=socket.SOCK_STREAM)
            bad = False
            for info in infos:
                try:
                    ip = ipaddress.ip_address(info[4][0].split("%")[0])
                    if (ip.is_private or ip.is_loopback or ip.is_link_local
                            or ip.is_reserved):
                        bad = True
                        break
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    continue
            self._dns_cache[host] = (now, bad)
            return bad
        except Exception:
            self._dns_cache[host] = (now, False)
            return False

    def _decision(self, allow, reason, record, rule):
        rec = dict(record)
        rec.update({"allow": allow, "reason": reason, "rule": rule,
                    "time": __import__("time").strftime("%Y-%m-%d %H:%M:%S")})
        with self._lock:
            self.events.append(rec)
            self.events = self.events[-500:]
            try:
                if (os.path.exists(self.events_path)
                        and os.path.getsize(self.events_path) > self._max_event_file):
                    os.replace(self.events_path, self.events_path + ".old")
                with open(self.events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        self.audit.append({"subject": "net:" + str(record.get("domain")),
                           "decision": "allow" if allow else "deny",
                           "module": record.get("module"),
                           "domain": record.get("domain"),
                           "purpose": record.get("purpose"),
                           "reason": reason})
        return rec

    def open(self, url, *, module="unknown", purpose="network", method="GET",
             data=None, headers=None, timeout=10, max_bytes=5 * 1024 * 1024):
        d = self.check(url, module=module, purpose=purpose, method=method)
        if not d.get("allow"):
            raise PermissionError(d.get("reason") or "网络请求被拒绝")
        req = urllib.request.Request(url, data=data, headers=headers or {},
                                     method=method)
        srv = self
        class _GuardRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                d2 = srv.check(newurl, module=module,
                               purpose=purpose, method="GET")
                if not d2.get("allow"):
                    raise PermissionError("重定向被拒绝: "
                                          + str(d2.get("reason")))
                return super().redirect_request(
                    req, fp, code, msg, headers, newurl)
        opener = urllib.request.build_opener(_GuardRedirect)
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError("响应体超过限制")
            return {"status": getattr(r, "status", 200),
                    "headers": dict(r.headers), "body": raw}

    def list_recent(self, limit=100):
        return self.events[-limit:]


_CACHE = {}


def get_net_guard(trunk):
    key = id(trunk) if trunk is not None else 0
    if key not in _CACHE:
        _CACHE[key] = NetGuard(trunk)
    return _CACHE[key]
