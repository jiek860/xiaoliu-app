# -*- coding: utf-8 -*-
"""Main-process broker for isolated plugins.

The plugin worker never receives a trunk object. It can only ask the broker for
explicit capabilities. The broker validates the call against the normalized
manifest, consults PermissionCenter, performs the operation with bounded
resources, and writes an audit record.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from core.child_process import minimal_child_env
from core.path_safety import is_sensitive_path, safe_join_strict, safe_name
from core.safe_http import open_url, validate_http_url
from core.windows_job import WindowsJob


class PluginBrokerError(RuntimeError):
    pass


class PluginBroker:
    def __init__(self, base, plugin_name, plugin_path, capabilities,
                 trunk=None, confirm_cb=None, permission_center=None,
                 worker_path=None, timeout=30, max_output_bytes=256 * 1024):
        self.base = os.path.realpath(os.path.abspath(base))
        self.plugin_name = safe_name(plugin_name, "plugin")
        self.plugin_path = os.path.realpath(os.path.abspath(plugin_path))
        self.capabilities = capabilities or {}
        self.trunk = trunk
        self.confirm_cb = confirm_cb
        self.timeout = float(timeout or 30)
        self.max_output_bytes = int(max_output_bytes or 0)
        if permission_center is None:
            from core.permission_center import PermissionCenter
            permission_center = PermissionCenter(trunk)
        self.pc = permission_center
        self.worker_path = (os.path.realpath(os.path.abspath(worker_path))
                            if worker_path else os.path.join(
                                self.base, "core", "plugin_worker.py"))
        self.root = os.path.join(
            self.base, "data", "plugin_data", self.plugin_name)
        os.makedirs(self.root, exist_ok=True)
        self.proc = None
        self.job = None
        self._reader = None
        self._pending = {}
        self._lock = threading.RLock()
        self._write_lock = threading.RLock()
        self._id = 0
        self._alive = False
        self.last_error = ""
        # v2.1 N13：熔断与资源上限
        try:
            from core.plugin_limits import PluginLimits
            self.limits = PluginLimits()
        except Exception:
            self.limits = None
        # v2.1 N15：插件审计
        try:
            from core.plugin_audit import PluginAudit
            self.audit = PluginAudit(self.base)
        except Exception:
            self.audit = None
        self.version = ""
        self.session_id = ""

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if self._alive:
            return True
        worker = self.worker_path
        if not os.path.isfile(worker):
            self.last_error = "plugin_worker.py missing"
            return False
        if not os.path.isfile(self.plugin_path):
            self.last_error = "plugin file missing"
            return False
        env = minimal_child_env({"PYTHONPATH": self.base})
        kwargs = dict(
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, cwd=self.root, shell=False, env=env)
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(
                [sys.executable, worker, self.plugin_path], **kwargs)
        except Exception as exc:
            self.last_error = "worker start failed: %s" % str(exc)[:200]
            return False
        if os.name == "nt":
            self.job = WindowsJob(max_memory_mb=512, max_cpu_seconds=60,
                                  max_processes=8, kill_on_close=True)
            self.job.attach(self.proc.pid)
        self._alive = True
        self._reader = threading.Thread(
            target=self._reader_loop, daemon=True, name="plugin-worker-reader")
        self._reader.start()
        return True

    def stop(self):
        self._alive = False
        if self.job is not None:
            try:
                self.job.terminate()
            except Exception:  # 静默是故意的
                pass
            try:
                self.job.close()
            except Exception:  # 静默是故意的
                pass
            self.job = None
        p = self.proc
        self.proc = None
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except Exception:  # 静默是故意的
            pass
        if os.name == "nt" and p.pid:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:  # 静默是故意的
                pass
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:  # 静默是故意的
                pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.stop()
        return False

    # ------------------------------------------------------------ RPC
    def _send(self, payload):
        if self.proc is None or self.proc.stdin is None:
            raise PluginBrokerError("worker is not running")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._write_lock:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def _reader_loop(self):
        p = self.proc
        if p is None or p.stdout is None:
            return
        try:
            for line in p.stdout:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:  # 静默是故意的
                    continue
                if not isinstance(msg, dict):
                    continue
                rid = msg.get("id")
                with self._lock:
                    slot = self._pending.pop(rid, None)
                if slot is not None:
                    slot["result"] = msg.get("result")
                    slot["error"] = msg.get("error")
                    slot["event"].set()
                    continue
                method = msg.get("method")
                if method:
                    self._handle_worker_request(msg)
        except Exception as exc:
            self.last_error = "worker reader failed: %s" % str(exc)[:200]
        finally:
            self._alive = False
            with self._lock:
                slots = list(self._pending.values())
                self._pending.clear()
            for slot in slots:
                slot["error"] = {"message": "plugin worker exited"}
                slot["event"].set()

    def _audit_event(self, action, capability="", allowed=True, detail="",
                     extra=None):
        """写插件审计（v2.1 N15）。失败不影响主流程。"""
        audit = getattr(self, "audit", None)
        if audit is None:
            return None
        try:
            return audit.record(
                plugin=self.plugin_name, action=action,
                capability=capability, allowed=allowed, detail=detail,
                version=getattr(self, "version", ""),
                session_id=getattr(self, "session_id", ""),
                extra=extra)
        except Exception:  # 静默是故意的 - 审计失败不得阻断主流程（N15）
            return None

    def set_identity(self, version="", session_id=""):
        """由安装器/调度器注入版本与会话 id，用于审计字段。"""
        self.version = str(version or "")[:40]
        self.session_id = str(session_id or "")[:64]
        return {"ok": True}

    def call_plugin(self, args=None, timeout=None):
        # N13：熔断检查必须放在 start() **之前** —— 熔断状态下不该再尝试
        # 拉起 worker，否则真实原因会被"worker 启动失败"盖住。
        _limits = getattr(self, "limits", None)
        if _limits is not None:
            blocked = _limits.before_call()
            if blocked is not None:
                self._audit_event("call", "circuit", False,
                                  blocked["error"]["message"],
                                  {"code": blocked["error"]["code"]})
                raise PluginBrokerError(blocked["error"]["message"])
        if not self._alive and not self.start():
            raise PluginBrokerError(self.last_error or "worker is not running")
        with self._lock:
            self._id += 1
            rid = self._id
            slot = {"event": threading.Event()}
            self._pending[rid] = slot
        self._send({"jsonrpc": "2.0", "id": rid, "method": "plugin.run",
                    "params": {"args": list(args or [])}})
        if not slot["event"].wait(float(timeout or self.timeout)):
            with self._lock:
                self._pending.pop(rid, None)
            _limits = getattr(self, "limits", None)
            if _limits is not None:
                _limits.after_call(False, "timeout")
            self._audit_event("call", "run", False, "timeout")
            raise TimeoutError("plugin run timed out")
        if slot.get("error") is not None:
            err = slot["error"]
            msg = str(err.get("message") if isinstance(err, dict) else err)
            if _limits is not None:
                _limits.after_call(False, msg)
            self._audit_event("call", "run", False, msg[:200])
            raise PluginBrokerError(msg)
        if _limits is not None:
            _limits.after_call(True)
        self._audit_event("call", "run", True, "ok")
        return slot.get("result")

    # ------------------------------------------------------------ capability requests
    def _authorize(self, kind, **target):
        decision = self.pc.authorize_capability(
            self.plugin_name, self.capabilities, kind, **target)
        if decision.get("allow"):
            return
        if not decision.get("requires_confirm"):
            raise PermissionError(decision.get("reason") or "capability denied")
        if not self.confirm_cb:
            raise PermissionError(decision.get("reason") or "confirmation required")
        try:
            ok = bool(self.confirm_cb(
                "插件请求 %s 能力" % kind,
                "%s: %s" % (self.plugin_name, decision.get("reason", "")),
            ))
        except Exception:
            ok = False
        if not ok:
            raise PermissionError("user denied capability: %s" % kind)
        self.pc.approve("capability:%s:%s" % (self.plugin_name, kind),
                        scope="once", reason="用户确认插件能力")

    def _handle_worker_request(self, msg):
        rid = msg.get("id")
        method = str(msg.get("method") or "")
        params = msg.get("params") or {}
        try:
            result = self._dispatch(method, params)
            self._send({"jsonrpc": "2.0", "id": rid, "result": result})
        except Exception as exc:
            self._send({"jsonrpc": "2.0", "id": rid,
                        "error": {"message": str(exc)[:300],
                                  "type": type(exc).__name__}})

    def _dispatch(self, method, params):
        if method == "files.read":
            return self._read_file(params.get("path"),
                                   int(params.get("max_bytes") or 65536))
        if method == "files.write":
            return self._write_file(params.get("path"), params.get("text"),
                                    bool(params.get("append")))
        if method == "network.request":
            return self._network_request(params)
        if method == "process.run":
            return self._process_run(params)
        if method == "config.get_public":
            return self._config_get(params.get("key"))
        if method == "config.get_secret":
            return self._config_get_secret(params.get("name"))
        if method == "audit.record":
            return self._audit(str(params.get("event") or "")[:500])
        raise PermissionError("unknown broker method: %s" % method)

    def _target(self, path):
        target = safe_join_strict(self.root, path, reject_links=True)
        if not target:
            raise PermissionError("path escapes plugin root or crosses a link")
        if is_sensitive_path(target, self.base):
            raise PermissionError("sensitive path is forbidden")
        return target

    def _read_file(self, path, max_bytes):
        target = self._target(path)
        self._authorize("filesystem", plugin_root=self.root, path=target,
                        method="read")
        if not os.path.isfile(target):
            raise FileNotFoundError(path)
        with open(target, "rb") as f:
            data = f.read(max(1, int(max_bytes or 65536)) + 1)
        if len(data) > max_bytes:
            raise ValueError("file exceeds max_bytes")
        return data.decode("utf-8", "replace")

    def _write_file(self, path, text, append=False):
        target = self._target(path)
        self._authorize("filesystem", plugin_root=self.root, path=target,
                        method="write")
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)
        data = str(text or "").encode("utf-8")
        if len(data) > self.max_output_bytes:
            raise ValueError("write exceeds max_output_bytes")
        _limits = getattr(self, "limits", None)
        if _limits is not None:
            blocked = _limits.check_write(len(data))
            if blocked is not None:
                self._audit_event("capability", "filesystem", False,
                                  blocked["error"]["message"])
                raise PermissionError(blocked["error"]["message"])
        self._audit_event("capability", "filesystem", True,
                          "write:%s" % os.path.basename(target))
        mode = "ab" if append else "wb"
        with open(target, mode) as f:
            f.write(data)
        return {"ok": True, "bytes": len(data)}

    def _network_request(self, params):
        url = str(params.get("url") or "")
        method = str(params.get("method") or "GET").upper()
        if not validate_http_url(url):
            raise PermissionError("only http/https URLs are allowed")
        from urllib.parse import urlparse
        domain = (urlparse(url).hostname or "").lower()
        _limits = getattr(self, "limits", None)
        if _limits is not None:
            blocked = _limits.check_network()
            if blocked is not None:
                self._audit_event("capability", "network", False,
                                  blocked["error"]["message"])
                raise PermissionError(blocked["error"]["message"])
        self._authorize("network", domain=domain, method=method)
        self._audit_event("capability", "network", True,
                          "%s %s" % (method, domain))
        try:
            from core.net_guard import get_net_guard
            d = get_net_guard(self.trunk).check(
                url, module="plugin:" + self.plugin_name, purpose="plugin",
                method=method)
            if not d.get("allow"):
                raise PermissionError(d.get("reason") or "network denied")
        except PermissionError:
            raise
        data = params.get("body")
        if data is not None and not isinstance(data, (bytes, bytearray)):
            data = str(data).encode("utf-8")
        headers = {str(k): str(v) for k, v in (params.get("headers") or {}).items()}
        response = open_url(url, timeout=float(params.get("timeout") or 10),
                            headers=headers, data=data, method=method)
        raw = response.read(self.max_output_bytes + 1)
        if len(raw) > self.max_output_bytes:
            raise ValueError("network response exceeds max_output_bytes")
        return {"status": getattr(response, "status", 200),
                "body": raw.decode("utf-8", "replace")}

    def _process_run(self, params):
        argv = [str(x) for x in (params.get("argv") or [])]
        self._authorize("process", argv=argv)
        self._audit_event("capability", "process", True,
                          "run:%s" % " ".join(argv)[:120])
        job = None
        try:
            p = subprocess.Popen(
                argv, cwd=self.root, shell=False,
                env=minimal_child_env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               if os.name == "nt" else 0))
            if os.name == "nt":
                job = WindowsJob(max_memory_mb=256, max_cpu_seconds=30,
                                 max_processes=4, kill_on_close=True)
                job.attach(p.pid)
            out, _ = p.communicate(
                timeout=min(float(params.get("timeout") or 15), 120))
            if len(out.encode("utf-8", "replace")) > self.max_output_bytes:
                raise ValueError("process output exceeds max_output_bytes")
            return {"returncode": p.returncode, "output": out}
        finally:
            if job is not None:
                job.terminate()
                job.close()

    def _config_get(self, key):
        key = str(key or "")
        self._authorize("config", key=key)
        cfg = getattr(self.trunk, "config", {}) or {}
        value = cfg.get(key)
        self._audit_event("capability", "config", True,
                          "get_public:%s" % key)
        return value

    # 凭据读取：只有声明了 config.read_secrets 才允许（v2.1 S3/S7）
    SECRET_NAME_RE = None

    def _config_get_secret(self, name):
        """经 broker 代理读取凭据。

        - 必须声明 capabilities.config.read_secrets = true，否则拒绝；
        - 只允许读取 manifest 中 config.public_keys 之外的、宿主机密白名单内的键；
        - 返回值**不写审计原文**，审计只记录"读取了哪个名字"。
        """
        import re as _re
        cfg = (self.capabilities or {}).get("config") or {}
        if not cfg.get("read_secrets"):
            self._audit_event("capability", "config", False,
                              "get_secret refused: read_secrets not declared")
            raise PermissionError(
                "capabilities.config.read_secrets 未声明，禁止读取凭据")
        name = str(name or "").strip()
        if not _re.match(r"^[A-Za-z0-9_.-]{1,64}$", name):
            raise PermissionError("凭据名不合法")
        allowed = set(cfg.get("secret_names") or [])
        if allowed and name not in allowed:
            self._audit_event("capability", "config", False,
                              "get_secret refused: %s not in secret_names" % name)
            raise PermissionError("该凭据未在 secret_names 中声明: " + name)
        self._authorize("config", key="secret:" + name)
        store = getattr(self.trunk, "config", {}) or {}
        value = store.get(name)
        self._audit_event("capability", "config", True,
                          "get_secret:%s" % name)
        return value

    def _audit(self, event):
        """插件主动上报的审计事件（走 v2.1 N15 统一格式）。"""
        self._audit_event("plugin", "", True, event)
        try:
            from core.audit_log import AuditLog
            AuditLog(self.base).append({
                "subject": "plugin:" + self.plugin_name,
                "decision": "allow", "result": "audit",
                "reason": event[:300]})
        except Exception:  # 静默是故意的
            pass
        return {"ok": True}
