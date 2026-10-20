# -*- coding: utf-8 -*-
"""Isolated plugin broker/worker tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_broker import PluginBroker  # noqa: E402
from core.plugin_capabilities import validate_capabilities  # noqa: E402
from core.permission_center import PermissionCenter  # noqa: E402


PLUGIN = '''
class Demo:
    def run(self, ctx):
        ctx.files.write("outbox/result.txt", "hello from worker")
        return ctx.files.read("outbox/result.txt")
'''


class Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {"theme": "dark", "api_key": "secret-value"}


def _caps():
    return validate_capabilities({
        "name": "demo",
        "capabilities": {
            "filesystem": {
                "read": ["data/plugin_data/demo/outbox"],
                "write": ["data/plugin_data/demo/outbox"],
            },
            "config": {"public_keys": ["theme"]},
        },
    })["capabilities"]


def test_worker_executes_through_broker(tmp_path):
    plugin = tmp_path / "demo.py"
    plugin.write_text(PLUGIN, encoding="utf-8")
    trunk = Trunk(tmp_path)
    pc = PermissionCenter(trunk)
    broker = PluginBroker(
        tmp_path, "demo", str(plugin), _caps(), trunk=trunk,
        permission_center=pc, confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))
    try:
        assert broker.start()
        assert broker.call_plugin() == "hello from worker"
        assert (tmp_path / "data" / "plugin_data" / "demo" /
                "outbox" / "result.txt").read_text(encoding="utf-8") == "hello from worker"
    finally:
        broker.stop()


def test_worker_rejects_unauthorized_path(tmp_path):
    plugin = tmp_path / "demo.py"
    plugin.write_text('''
class Demo:
    def run(self, ctx):
        return ctx.files.read("../../secret.txt")
''', encoding="utf-8")
    trunk = Trunk(tmp_path)
    broker = PluginBroker(
        tmp_path, "demo", str(plugin), _caps(), trunk=trunk,
        permission_center=PermissionCenter(trunk),
        confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))
    try:
        assert broker.start()
        try:
            broker.call_plugin()
            assert False, "path escape should fail"
        except Exception as exc:
            assert "escape" in str(exc).lower() or "permission" in str(exc).lower()
    finally:
        broker.stop()


def test_worker_blocks_dangerous_import(tmp_path):
    plugin = tmp_path / "demo.py"
    plugin.write_text('''
import subprocess
class Demo:
    def run(self, ctx):
        return subprocess.call(["cmd", "/c", "whoami"])
''', encoding="utf-8")
    trunk = Trunk(tmp_path)
    broker = PluginBroker(
        tmp_path, "demo", str(plugin), _caps(), trunk=trunk,
        permission_center=PermissionCenter(trunk),
        confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))
    try:
        assert broker.start()
        try:
            broker.call_plugin()
            assert False, "sandbox import should fail"
        except Exception as exc:
            assert "not allowed" in str(exc).lower() or "import" in str(exc).lower()
    finally:
        broker.stop()


def test_config_secret_is_denied(tmp_path):
    plugin = tmp_path / "demo.py"
    plugin.write_text('''
class Demo:
    def run(self, ctx):
        return ctx.config.get_public("api_key")
''', encoding="utf-8")
    trunk = Trunk(tmp_path)
    broker = PluginBroker(
        tmp_path, "demo", str(plugin), _caps(), trunk=trunk,
        permission_center=PermissionCenter(trunk),
        confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))
    try:
        assert broker.start()
        try:
            broker.call_plugin()
            assert False, "secret config should be denied"
        except Exception as exc:
            assert "secret" in str(exc).lower() or "denied" in str(exc).lower()
    finally:
        broker.stop()


def _caps_with(extra):
    base = {
        "name": "demo",
        "capabilities": {
            "filesystem": {
                "read": ["data/plugin_data/demo/outbox"],
                "write": ["data/plugin_data/demo/outbox"],
            },
            "config": {"public_keys": ["theme"]},
        },
    }
    base["capabilities"].update(extra)
    return validate_capabilities(base)["capabilities"]


def test_broker_config_audit_and_unknown_method(tmp_path):
    trunk = Trunk(tmp_path)
    broker = PluginBroker(
        tmp_path, "demo", str(tmp_path / "missing.py"), _caps(), trunk=trunk,
        permission_center=PermissionCenter(trunk), confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))
    assert broker._dispatch("config.get_public", {"key": "theme"}) == "dark"
    assert broker._dispatch("audit.record", {"event": "hello"})["ok"] is True
    try:
        broker._dispatch("unknown.method", {})
        assert False
    except PermissionError:
        pass


def test_broker_denies_process_without_capability(tmp_path):
    trunk = Trunk(tmp_path)
    broker = PluginBroker(
        tmp_path, "demo", str(tmp_path / "missing.py"), _caps(), trunk=trunk,
        permission_center=PermissionCenter(trunk), confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))
    try:
        broker._dispatch("process.run", {"argv": [sys.executable, "-c", "print(1)"]})
        assert False
    except PermissionError as exc:
        assert "process" in str(exc).lower()


def test_broker_network_request_checks_domain_and_method(tmp_path, monkeypatch):
    trunk = Trunk(tmp_path)
    caps = _caps_with({"network": {"enabled": True, "domains": ["example.com"],
                                    "methods": ["GET"]}})
    broker = PluginBroker(
        tmp_path, "demo", str(tmp_path / "missing.py"), caps, trunk=trunk,
        permission_center=PermissionCenter(trunk), confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))

    class Guard:
        def check(self, *_a, **_k):
            return {"allow": True}

    class Resp:
        status = 200
        def read(self, _n):
            return b"ok"

    monkeypatch.setattr("core.net_guard.get_net_guard", lambda _t: Guard())
    monkeypatch.setattr("core.plugin_broker.open_url", lambda *_a, **_k: Resp())
    out = broker._dispatch("network.request",
                           {"url": "https://example.com/x", "method": "GET"})
    assert out["status"] == 200 and out["body"] == "ok"
    try:
        broker._dispatch("network.request",
                         {"url": "https://evil.test/x", "method": "GET"})
        assert False
    except PermissionError:
        pass


def test_broker_process_run_with_fixed_argv(tmp_path):
    trunk = Trunk(tmp_path)
    argv = [sys.executable, "-c", "print(42)"]
    caps = _caps_with({"process": {"enabled": True, "allow_argv": [argv]}})
    broker = PluginBroker(
        tmp_path, "demo", str(tmp_path / "missing.py"), caps, trunk=trunk,
        permission_center=PermissionCenter(trunk), confirm_cb=lambda *_a: True,
        worker_path=os.path.join(BASE, "core", "plugin_worker.py"))
    out = broker._dispatch("process.run", {"argv": argv, "timeout": 10})
    assert out["returncode"] == 0
    assert "42" in out["output"]
