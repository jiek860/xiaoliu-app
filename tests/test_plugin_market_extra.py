# -*- coding: utf-8 -*-
"""PluginMarket：扫描、验签材料、安装、下载、回滚和外部插件检查。"""
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.plugin_market import PluginMarket  # noqa: E402


PLUGIN_SRC = '''from modules.base import BaseModule

class Notes(BaseModule):
    NAME = "notes"
    def run(self, *a):
        return {"ok": True}
'''


class _NG:
    def check(self, *_a, **_k):
        return {"allow": True}


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {
            "allow_unsigned_plugins": True,
            "allow_inprocess_plugins": True,
            "plugin_remote_install": True,
            "plugin_repo_allowlist": ["example.test"],
            "online_repo_url": "https://example.test/repo",
        }
        self.modules = {}
        self.loaded = []

    def _log(self, *_a, **_k):
        return None

    def _load_lazy(self, name):
        self.loaded.append(name)
        return None


def _market(tmp_path):
    trunk = _Trunk(tmp_path)
    pm = PluginMarket(trunk)
    os.makedirs(pm.installed_dir, exist_ok=True)
    os.makedirs(pm.repo_dir, exist_ok=True)
    os.makedirs(os.path.join(tmp_path, "core"), exist_ok=True)
    (tmp_path / "core" / "lazy_config.py").write_text(
        'LAZY_MAP = {\n    "notes": ("notes", "Notes", "笔记"),\n}\n',
        encoding="utf-8")
    return pm


def test_plugin_market_scan_and_metadata(tmp_path):
    pm = _market(tmp_path)
    repo_file = tmp_path / "modules_repo" / "notes.py"
    repo_file.write_text(PLUGIN_SRC + "\n# " + "x" * 2000, encoding="utf-8")
    manifest = [{"name": "notes", "title": "笔记", "file": "notes.py",
                 "cls": "Notes", "sha256": hashlib.sha256(
                     repo_file.read_bytes()).hexdigest(),
                 "signature": "", "api_version": "1.0",
                 "first_party": False}]
    (tmp_path / "modules_repo" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert pm._file_size(str(repo_file)) >= 1
    assert "BaseModule" in pm._doc_of(str(repo_file)) or pm._doc_of(str(repo_file)) == ""
    meta = pm._repo_meta("notes.py")
    assert meta["name"] == "notes"
    assert pm._read_repo_file("notes.py") == str(repo_file)
    assert pm._allow_unsigned() is True
    mods = pm.list_all()
    assert isinstance(mods, list)


def test_plugin_verify_and_install_unsigned_allowed(tmp_path):
    pm = _market(tmp_path)
    raw = PLUGIN_SRC.encode("utf-8")
    repo_file = tmp_path / "modules_repo" / "notes.py"
    repo_file.write_bytes(raw)
    meta = {"file": "notes.py", "sha256": hashlib.sha256(raw).hexdigest(),
            "signature": "", "api_version": "1.0", "first_party": False}
    (tmp_path / "modules_repo" / "manifest.json").write_text(
        json.dumps([meta]), encoding="utf-8")
    res, why = pm._verify_meta(raw, meta)
    assert res is None and "sha256" in why
    r = pm.install("notes")
    assert r["ok"] is True, r
    assert (tmp_path / "modules" / "installed" / "notes.py").exists()
    assert "notes" in pm.trunk.loaded


def test_plugin_download_and_list_online(tmp_path, monkeypatch):
    pm = _market(tmp_path)
    raw = PLUGIN_SRC.encode("utf-8")
    meta = {"file": "newnote.py", "sha256": hashlib.sha256(raw).hexdigest(),
            "signature": "test-signature", "api_version": "1.0",
            "first_party": False}

    class Resp:
        def __init__(self, data):
            self.data = data

        def read(self):
            return self.data

    def fake_urlopen(url, timeout=0):
        if "manifest.json" in url:
            return Resp(json.dumps([meta]).encode("utf-8"))
        return Resp(raw)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("core.net_guard.get_net_guard", lambda _t: _NG())
    monkeypatch.setattr(pm, "_verify_meta", lambda *_a, **_k: (True, "mocked"))
    online = pm.list_online()
    assert online and online[0]["file"] == "newnote.py"
    r = pm.download("newnote.py", meta)
    assert r["ok"] is True, r
    assert (tmp_path / "modules" / "installed" / "newnote.py").exists()


def test_plugin_rollback_and_governance(tmp_path):
    pm = _market(tmp_path)
    os.makedirs(pm.installed_dir, exist_ok=True)
    (tmp_path / "modules" / "installed" / "notes.py").write_text("old", encoding="utf-8")
    (tmp_path / "data" / "plugin_backups").mkdir(parents=True, exist_ok=True)
    backup = tmp_path / "data" / "plugin_backups" / "notes.py"
    backup.write_text(PLUGIN_SRC, encoding="utf-8")
    r = pm.rollback_module("notes")
    assert r["ok"] is True
    assert "notes" in pm.trunk.loaded
    assert "历史" in pm.governance_report()


def test_plugin_install_file_rejects_and_accepts(tmp_path):
    pm = _market(tmp_path)
    assert pm.install_file(str(tmp_path / "missing.py"))["ok"] is False
    bad = tmp_path / "bad.py"
    bad.write_text("print('no class')\n", encoding="utf-8")
    assert pm.install_file(str(bad))["ok"] is False
    good = tmp_path / "myplugin.py"
    good.write_text(PLUGIN_SRC.replace("Notes", "MyPlugin"), encoding="utf-8")
    r = pm.install_file(str(good))
    assert r["ok"] is True, r
    assert "myplugin" in pm.trunk.loaded
    assert "myplugin" in (tmp_path / "core" / "lazy_config.py").read_text(encoding="utf-8")

def test_plugin_download_falls_back_to_second_signed_source(tmp_path, monkeypatch):
    pm = _market(tmp_path)
    pm.trunk.config["online_repo_url"] = ""
    pm.trunk.config["plugin_repo_urls"] = [
        "https://one.example/repo",
        "https://two.example/repo",
    ]
    pm.trunk.config["plugin_repo_allowlist"] = ["one.example", "two.example"]
    raw_good = PLUGIN_SRC.encode("utf-8")
    meta = {"file": "notes.py", "signature": "signed",
            "sha256": hashlib.sha256(raw_good).hexdigest(),
            "api_version": "1.0", "first_party": False}

    class _Resp:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data

    def fake_open(url, timeout=0):
        if "one.example" in str(url):
            return _Resp(b"tampered")
        return _Resp(raw_good)

    monkeypatch.setattr("modules.installed.plugin_market_online.safe_open_url", fake_open)
    monkeypatch.setattr("core.net_guard.get_net_guard", lambda _t: _NG())
    monkeypatch.setattr(pm, "_verify_meta", lambda data, _meta: (
        (True, "ok") if data == raw_good else (False, "bad signature")))
    r = pm.download("notes.py", meta)
    assert r["ok"] is True, r
    assert (tmp_path / "modules" / "installed" / "notes.py").read_bytes() == raw_good


def test_plugin_market_check_updates(tmp_path, monkeypatch):
    pm = _market(tmp_path)
    online = [{"file": "notes.py", "name": "notes", "version": "1.2.0",
               "api_version": "1.0", "signature": "s", "first_party": True,
               "capabilities": {}}]
    monkeypatch.setattr(pm, "list_online", lambda: online)
    monkeypatch.setattr(pm, "_repo_meta", lambda _f: {"version": "1.0.0"})
    r = pm.check_updates()
    assert r["ok"] is True
    assert r["updates"] and r["updates"][0]["latest"]["version"] == "1.2.0"


def test_apply_update_backs_up_and_records_ledger(tmp_path, monkeypatch):
    from core.plugin_installer import apply_update
    from core.plugin_registry import InstallLedger
    pm = _market(tmp_path)
    installed = tmp_path / "modules" / "installed"
    installed.mkdir(parents=True, exist_ok=True)
    (installed / "notes.py").write_text("old", encoding="utf-8")
    def fake_download(filename, meta):
        (installed / filename).write_text("new", encoding="utf-8")
        return {"ok": True, "msg": "downloaded"}
    monkeypatch.setattr(pm, "download", fake_download)
    r = apply_update(pm, {"name": "notes", "file": "notes.py", "version": "1.2.0"})
    assert r["ok"] is True
    assert r["backup"] and (tmp_path / "data" / "plugin_backups" / "notes.py").exists()
    assert "notes" in pm.trunk.loaded
    assert InstallLedger(str(tmp_path)).latest("notes")["version"] == "1.2.0"
