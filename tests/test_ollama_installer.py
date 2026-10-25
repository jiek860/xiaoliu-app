# -*- coding: utf-8 -*-
"""core/ollama_installer.py 的同名测试：探源、下载、校验、启动安装。

网络全部用假响应替换，不下载真实安装包。
"""
import hashlib
import os
import sys

import pytest

from core import ollama_installer as oi


class FakeResp:
    def __init__(self, chunks, headers=None):
        self.chunks = list(chunks)
        self.headers = headers or {}

    def read(self, n=None):
        return self.chunks.pop(0) if self.chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeTime:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        self.now += 1.0
        return self.now


class _AllowGuard:
    def check(self, url, **kw):
        return {"allow": True}


@pytest.fixture(autouse=True)
def _allow_network(monkeypatch):
    monkeypatch.setattr("core.net_guard.get_net_guard",
                        lambda *a, **k: _AllowGuard())


def test_probe_accepts_mz_executable(monkeypatch):
    monkeypatch.setattr(oi, "safe_open_url", lambda req, timeout=10: FakeResp(
        [b"MZ" + b"\0" * 100],
        {"Content-Range": "bytes 0-1023/1509000000"}))
    r = oi.probe("https://example.com/a.exe")
    assert r["ok"] is True
    assert r["MB"] > 0


def test_probe_rejects_html_page(monkeypatch):
    monkeypatch.setattr(oi, "safe_open_url", lambda req, timeout=10: FakeResp(
        [b"<!DOCTYPE html>"]))
    assert oi.probe("https://example.com/a.exe")["ok"] is False


def test_probe_reports_network_denied(monkeypatch):
    class Deny:
        def check(self, url, **kw):
            return {"allow": False, "reason": "黑名单"}

    monkeypatch.setattr("core.net_guard.get_net_guard",
                        lambda *a, **k: Deny())
    r = oi.probe("https://example.com/a.exe")
    assert r["ok"] is False and "网络策略拒绝" in r["错误"]


def test_pick_best_returns_first_available(monkeypatch):
    seen = []

    def fake_probe(url, timeout=10):
        seen.append(url)
        return {"ok": True, "MB": 1.0}

    monkeypatch.setattr(oi, "probe", fake_probe)
    r = oi.pick_best()
    assert r and r["url"] == oi.SOURCES[0]["url"]
    assert len(seen) == 1


def test_pick_best_reports_progress_and_none(monkeypatch):
    notes = []
    monkeypatch.setattr(oi, "probe", lambda url, timeout=10: {"ok": False})
    assert oi.pick_best(progress=notes.append) is None
    assert len(notes) == len(oi.SOURCES)


def test_download_writes_file_and_progress(tmp_path, monkeypatch):
    dest = str(tmp_path / "OllamaSetup.exe")
    monkeypatch.setattr(oi, "safe_open_url", lambda req, timeout=30: FakeResp(
        [b"a" * 10, b"b" * 10], {"Content-Length": "20"}))
    monkeypatch.setattr(oi, "time", FakeTime())
    seen = []
    r = oi.download("https://example.com/x.exe", dest=dest,
                    progress=lambda *a: seen.append(a))
    assert r["ok"] is True and r["字节"] == 20
    assert open(dest, "rb").read() == b"a" * 10 + b"b" * 10
    assert seen and seen[0][1] == 20
    assert not os.path.exists(dest + ".part")


def test_download_cancel_before_connect(tmp_path):
    r = oi.download("https://example.com/x.exe",
                    dest=str(tmp_path / "x.exe"), should_stop=lambda: True)
    assert r == {"取消": True}
    assert not os.path.exists(str(tmp_path / "x.exe"))


def test_download_interrupt_cleans_partial(tmp_path, monkeypatch):
    dest = str(tmp_path / "x.exe")
    monkeypatch.setattr(oi, "safe_open_url", lambda req, timeout=30: FakeResp(
        [b"a" * 10, b"b" * 10]))
    state = {"n": 0}

    def should_stop():
        state["n"] += 1
        return state["n"] > 1

    r = oi.download("https://example.com/x.exe", dest=dest,
                    should_stop=should_stop)
    assert r["ok"] is False and r["取消"] is True
    assert not os.path.exists(dest + ".part")


def test_download_network_error_cleans_partial(tmp_path, monkeypatch):
    def boom(req, timeout=30):
        raise OSError("断网")

    monkeypatch.setattr(oi, "safe_open_url", boom)
    dest = str(tmp_path / "x.exe")
    r = oi.download("https://example.com/x.exe", dest=dest)
    assert r["ok"] is False and "OSError" in r["错误"]
    assert not os.path.exists(dest + ".part")


def test_verify_sha256(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    good = hashlib.sha256(b"abc").hexdigest()
    assert oi.verify_sha256(str(p), "") is None
    assert oi.verify_sha256(str(p), good) is True
    assert oi.verify_sha256(str(p), good.upper()) is True
    assert oi.verify_sha256(str(p), "0" * 64) is False


def test_run_installer_missing_file(tmp_path):
    r = oi.run_installer(str(tmp_path / "nope.exe"))
    assert r["ok"] is False and "不存在" in r["错误"]


def test_run_installer_rejects_tiny_file(tmp_path):
    p = tmp_path / "small.exe"
    p.write_bytes(b"MZ" + b"\0" * 100)
    r = oi.run_installer(str(p))
    assert r["ok"] is False and "太小" in r["错误"]


def test_run_installer_rejects_sha_mismatch(tmp_path):
    p = tmp_path / "big.exe"
    p.write_bytes(b"MZ" + b"\0" * (1024 * 1024 + 8))
    r = oi.run_installer(str(p), expected_sha256="0" * 64)
    assert r["ok"] is False and "SHA256" in r["错误"]


def test_run_installer_rejects_bad_signature(tmp_path, monkeypatch):
    p = tmp_path / "big.exe"
    p.write_bytes(b"MZ" + b"\0" * (1024 * 1024 + 8))
    monkeypatch.setattr(oi, "verify_authenticode",
                        lambda path, hint="Ollama": (False, "STATUS:NotSigned"))
    r = oi.run_installer(str(p))
    assert r["ok"] is False and "签名校验失败" in r["错误"]


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="os.startfile 仅 Windows")
def test_run_installer_starts_wizard(tmp_path, monkeypatch):
    p = tmp_path / "big.exe"
    p.write_bytes(b"MZ" + b"\0" * (1024 * 1024 + 8))
    monkeypatch.setattr(oi, "verify_authenticode",
                        lambda path, hint="Ollama": (True, "Ollama Inc."))
    started = []
    monkeypatch.setattr(os, "startfile", lambda path: started.append(path),
                        raising=False)
    r = oi.run_installer(str(p))
    assert r["ok"] is True and started == [str(p)]


def test_detect_installed_via_path(monkeypatch):
    monkeypatch.setattr(oi.shutil, "which", lambda name: "C:/ollama.exe")
    assert oi.detect_installed() == {"已装": True, "来源": "PATH"}


def test_detect_installed_absent(monkeypatch):
    monkeypatch.setattr(oi.shutil, "which", lambda name: None)
    monkeypatch.setattr(oi.os.path, "exists", lambda p: False)
    assert oi.detect_installed() == {"已装": False, "来源": ""}


def test_default_path_is_installer_name():
    assert oi.default_path().endswith("OllamaSetup.exe")
