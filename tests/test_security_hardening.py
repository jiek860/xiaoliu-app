# -*- coding: utf-8 -*-
"""本轮安全加固的回归测试：默认拒绝、路径、签名、本地服务鉴权。"""
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from unittest import mock

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))


class _FakeTrunk:
    def __init__(self, base=None):
        self.base = base or tempfile.mkdtemp(prefix="x6sec_")
        self.config = {}
        self.modules = {}
        self.confirm_cb = None
        self._remote_tool_locked = False

    def rule(self, key, default=False):
        return default

    def call(self, mod, method, *a, **k):
        return {"ok": False, "error": "not implemented"}

    def _log(self, msg, level="INFO"):
        pass


def test_builtin_dangerous_tools_have_default_deny_policy():
    from modules.installed.tool_caller import ToolCaller
    from core import security_policy
    tc = ToolCaller(_FakeTrunk())
    for name in ("code_run", "fs_read", "fs_edit", "computer", "browser", "shell"):
        info = tc.tools[name]
        p = security_policy.classify(name, info)
        assert p["confirm"], "%s 没有强制确认" % name
    assert security_policy.classify("code_run", tc.tools["code_run"])["danger"]


def test_code_run_is_denied_when_danger_rule_off():
    from modules.installed.tool_caller import ToolCaller
    tc = ToolCaller(_FakeTrunk())
    tc.trunk.modules["code_runner"] = object()
    r = tc._dispatch(tc.tools["code_run"], {"code": "print(1)"}, "", "code_run")
    assert isinstance(r, dict) and r.get("ok") is False
    assert "规则" in str(r)


def test_fs_edit_requires_confirmation_when_no_ui():
    from modules.installed.tool_caller import ToolCaller
    tc = ToolCaller(_FakeTrunk())
    tc.trunk.rule = lambda key, default=False: True  # 规则开启，但没有确认界面
    r = tc._dispatch(tc.tools["fs_edit"],
                     {"spec": '{"path":"a.txt","old":"a","new":"b"}'},
                     "", "fs_edit")
    assert isinstance(r, dict) and r.get("ok") is False
    assert "取消" in str(r) or "确认" in str(r)


def test_safe_join_rejects_prefix_sibling_and_absolute_paths():
    from core.path_safety import safe_join
    root = tempfile.mkdtemp(prefix="x6root_")
    sibling = root + "_evil"
    os.makedirs(sibling, exist_ok=True)
    try:
        assert safe_join(root, "ok.txt")
        assert safe_join(root, "../evil.txt") is None
        assert safe_join(root, sibling + os.sep + "x.txt") is None
        assert safe_join(root, "C:\\Windows\\win.ini") is None
    finally:
        try:
            os.rmdir(sibling)
        except OSError:
            pass


def test_computer_controller_whitelist_rejects_prefix_sibling():
    from modules.installed.computer_controller import ComputerController
    root = tempfile.mkdtemp(prefix="x6cc_")
    sibling = root + "_evil"
    os.makedirs(sibling, exist_ok=True)
    try:
        cc = ComputerController(_FakeTrunk(root))
        assert cc._safe_path(os.path.join(root, "a.txt"))
        assert cc._safe_path(os.path.join(sibling, "a.txt")) is None
    finally:
        try:
            os.rmdir(sibling)
        except OSError:
            pass


def test_plugin_hash_only_is_not_trusted():
    from modules.installed.plugin_market import PluginMarket
    pm = PluginMarket(_FakeTrunk())
    raw = b"print(1)\n"
    res, why = pm._verify_meta(raw, {"sha256": hashlib.sha256(raw).hexdigest()})
    assert res is None, (res, why)
    assert "签名" in why


def test_plugin_download_rejects_path_traversal():
    from modules.installed.plugin_market import PluginMarket
    base = tempfile.mkdtemp(prefix="x6pm_")
    os.makedirs(os.path.join(base, "modules", "installed"))
    t = _FakeTrunk(base)
    t.config["online_repo_url"] = "https://example.invalid/repo"
    t.config["plugin_remote_install"] = True
    t.config["plugin_repo_allowlist"] = ["example.invalid"]
    pm = PluginMarket(t)
    payload = b"print('x')\n"
    pm._verify_meta = lambda data, meta: (True, "mocked")
    class R:
        def read(self):
            return payload
    with mock.patch("urllib.request.urlopen", return_value=R()):
        r = pm.download("../escaped.py",
                        {"sha256": hashlib.sha256(payload).hexdigest()})
    assert r.get("ok") is False
    assert not os.path.exists(os.path.join(base, "modules", "escaped.py"))


def test_backup_delete_rejects_path_traversal():
    from core.backup import Backup
    base = tempfile.mkdtemp(prefix="x6bk_")
    os.makedirs(os.path.join(base, "backups"))
    victim = os.path.join(base, "victim")
    os.makedirs(victim)
    try:
        b = Backup(_FakeTrunk(base))
        r = b.delete_backup("../victim")
        assert not r.get("成功")
        assert os.path.isdir(victim)
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


def test_bot_server_requires_token():
    from core.bot_server import BotServer
    b = BotServer(_FakeTrunk())
    r = b.start(port=0)
    assert r.get("成功"), r
    port = b.server.server_address[1]
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d/wecom" % port,
            data=b'{"text":{"content":"hi"}}',
            headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=3)
        assert ei.value.code == 401
    finally:
        b.stop()


def test_auth_login_revalidates_license_not_just_local_boolean():
    from core.auth import Auth
    base = tempfile.mkdtemp(prefix="x6auth_")
    os.makedirs(os.path.join(base, "data", "users"))
    with open(os.path.join(base, "data", "users", "users.json"),
              "w", encoding="utf-8") as f:
        json.dump({"u": {"activated": True, "code": "X6AI-FAKE"}}, f)
    a = Auth(_FakeTrunk(base))
    r = a.login("u")
    assert r.get("ok") is False
    assert "授权" in r.get("msg", "") or "激活" in r.get("msg", "")


def test_memory_crypto_v2_uses_salt_and_aead():
    from core.memory_crypto import MemoryCrypto
    base = tempfile.mkdtemp(prefix="x6mc_")
    os.makedirs(os.path.join(base, "data"))
    with open(os.path.join(base, "data", "memory_cards.jsonl"), "w",
              encoding="utf-8") as f:
        f.write('{"facts":["秘密"]}\n')
    out = os.path.join(base, "m.bin")
    mc = MemoryCrypto(_FakeTrunk(base))
    r = mc.export_encrypted(out, "pw")
    assert r.get("ok"), r
    raw = open(out, "rb").read()
    assert raw.startswith(b"X6MEM2")
    assert b"\xe7\xa7\x98\xe5\xaf\x86" not in raw
    bad = mc.import_encrypted(out, "wrong")
    assert bad.get("ok") is False


def test_backup_export_never_silently_writes_plaintext():
    from core.backup import Backup
    base = tempfile.mkdtemp(prefix="x6bkx_")
    os.makedirs(os.path.join(base, "data"))
    with open(os.path.join(base, "data", "config.json"), "w",
              encoding="utf-8") as f:
        f.write('{"x":1}')
    out = os.path.join(base, "out")
    os.makedirs(out)
    bk = Backup(_FakeTrunk(base))
    r = bk.export(dest_dir=out, password="pw")
    assert r.get("成功"), r
    assert r.get("加密") != "无(未找到7-Zip)"
    raw = open(r["导出到"], "rb").read()
    if "7-Zip" in str(r.get("加密") or ""):
        import zipfile
        with zipfile.ZipFile(r["导出到"]) as z:
            infos = z.infolist()
            assert infos and all(i.flag_bits & 0x1 for i in infos), "7-Zip ZIP 必须逐项加密"
    else:
        assert not raw.startswith(b"PK"), "加密失败时不能落成明文 zip"


def test_ollama_installer_requires_valid_signature():
    from core import ollama_installer as oi
    base = tempfile.mkdtemp(prefix="x6oi_")
    p = os.path.join(base, "fake.exe")
    with open(p, "wb") as f:
        f.write(b"MZ" + b"x" * (1024 * 1024))
    with mock.patch.object(oi, "verify_authenticode",
                           return_value=(False, "bad signature")):
        r = oi.run_installer(p)
    assert r.get("ok") is False
    assert "签名" in r.get("错误", "")
