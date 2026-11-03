# -*- coding: utf-8 -*-
"""B5：startup_optimizer / gpu_detector

守住三件事
----------
1. 预编译**编不过的文件要报出来**，并且明细要落盘（``data/precompile_failures.json``）。
2. ``base`` 不对（没有可扫目录）要说明「路径不对」，不能返回 0 让人觉得"没事"。
3. 显卡检测：结构化状态 + 缓存，且**任何情况都不抛异常**
   （自检/工具调用不该因为显卡把链路带崩）。
"""
import json
import os
import sys
import tempfile
import types

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))


class _T:
    def __init__(self, base):
        self.base = str(base)


@pytest.fixture()
def tmp_base():
    return tempfile.mkdtemp(prefix="x6su_")


def _make_dirs(base, names):
    for name in names:
        os.makedirs(os.path.join(base, name), exist_ok=True)


def _write(base, rel, text):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ══════════════════════════════════════════════════════════════
# startup_optimizer
# ══════════════════════════════════════════════════════════════
def test_precompile_reports_and_persists_failures(tmp_base):
    from core.startup_optimizer import StartupOptimizer
    _make_dirs(tmp_base, ("core", "gui", "modules/installed"))
    _write(tmp_base, "core/ok.py", "x = 1\n")
    _write(tmp_base, "core/bad.py", "def broken(:\n")

    so = StartupOptimizer(_T(tmp_base))
    r = so.precompile()

    assert r["预编译文件"] == 1, r          # 编不过的不能算成功
    assert r["失败"] == 1, r
    assert "bad.py" in str(r["失败明细"])
    assert r["扫描目录"] == ["core", "gui", "modules/installed"]

    path = r.get("失败明细文件")
    assert path and os.path.exists(path), r
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["失败数"] == 1
    assert saved["失败明细"][0]["文件"] == "bad.py"
    assert so.last_failures and so.last_failures[0][0] == "bad.py"


def test_precompile_wrong_base_says_so(tmp_base):
    from core.startup_optimizer import StartupOptimizer
    r = StartupOptimizer(_T(tmp_base)).precompile()
    assert r["预编译文件"] == 0
    assert r["扫描目录"] == []
    assert "base 不对" in r["说明"], r


def test_precompile_respects_dirs_argument(tmp_base):
    from core.startup_optimizer import StartupOptimizer
    _make_dirs(tmp_base, ("core", "gui"))
    _write(tmp_base, "core/a.py", "a = 1\n")
    _write(tmp_base, "gui/b.py", "b = 1\n")

    r = StartupOptimizer(_T(tmp_base)).precompile(dirs=("core",))
    assert r["扫描目录"] == ["core"]
    assert r["预编译文件"] == 1


def test_precompile_empty_dir_is_explained(tmp_base):
    from core.startup_optimizer import StartupOptimizer
    _make_dirs(tmp_base, ("core",))
    r = StartupOptimizer(_T(tmp_base)).precompile()
    assert r["预编译文件"] == 0
    assert "没有 .py" in r["说明"], r


def test_precompile_failure_save_never_raises(tmp_base):
    """落盘失败（data 目录被占成文件）也不能让 precompile 崩掉"""
    from core.startup_optimizer import StartupOptimizer
    _make_dirs(tmp_base, ("core",))
    _write(tmp_base, "core/bad.py", "def broken(:\n")
    os.makedirs(os.path.join(tmp_base, "data"), exist_ok=True)
    # 用一个目录冒充 json 文件，open 会失败
    os.makedirs(os.path.join(tmp_base, "data",
                             "precompile_failures.json"), exist_ok=True)

    r = StartupOptimizer(_T(tmp_base)).precompile()
    assert r["失败"] == 1
    assert r["失败明细文件"] == "落盘失败"


def test_run_includes_elapsed(tmp_base):
    from core.startup_optimizer import StartupOptimizer
    _make_dirs(tmp_base, ("core",))
    _write(tmp_base, "core/a.py", "a = 1\n")
    r = StartupOptimizer(_T(tmp_base)).run()
    assert "启动耗时" in r
    assert r["预编译文件"] == 1


# ══════════════════════════════════════════════════════════════
# gpu_detector
# ══════════════════════════════════════════════════════════════
def _gpu(monkeypatch, system="Windows"):
    import core.gpu_detector as mod
    monkeypatch.setattr(mod.platform, "system", lambda: system)
    return mod.GPUDetector(None)


def test_gpu_detect_never_raises_and_keeps_nvidia_key(monkeypatch):
    gpu = _gpu(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda _n: None)

    def _boom(*a, **k):
        raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr("subprocess.run", _boom)

    info = gpu.detect()
    assert isinstance(info, dict)
    assert "NVIDIA" in info
    assert info["NVIDIA"] is False
    assert info["状态"] == "无显卡"
    assert info["推荐后端"] == "CPU"


def test_gpu_detect_parses_nvidia_smi(monkeypatch):
    gpu = _gpu(monkeypatch)
    fake = types.SimpleNamespace(
        returncode=0, stdout="NVIDIA GeForce RTX 4090, 24564 MiB".encode(),
        stderr=b"")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake)

    info = gpu.detect()
    assert info["NVIDIA"] is True
    assert info["GPU型号"] == "NVIDIA GeForce RTX 4090"
    assert "24564" in info["显存"]
    assert info["推荐后端"] == "CUDA"
    assert info["状态"] == "ok"
    assert "RTX" in gpu.summary()


def test_gpu_detect_nonzero_exit_is_detect_failure(monkeypatch):
    gpu = _gpu(monkeypatch)
    fake = types.SimpleNamespace(returncode=2, stdout=b"",
                                 stderr="未找到命令".encode())
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake)
    info = gpu.detect()
    assert info["状态"] == "检测失败"
    assert info["NVIDIA"] is False
    assert "检测失败" in gpu.summary()


def test_gpu_detect_timeout_is_detect_failure(monkeypatch):
    import subprocess
    gpu = _gpu(monkeypatch)

    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired("nvidia-smi", 5)
    monkeypatch.setattr("subprocess.run", _timeout)
    info = gpu.detect()
    assert info["状态"] == "检测失败"
    assert "超时" in info["说明"]


def test_gpu_detect_cached_until_refresh(monkeypatch):
    gpu = _gpu(monkeypatch)
    calls = {"n": 0}

    def _once():
        calls["n"] += 1
        return {"NVIDIA": False, "GPU型号": "未知", "显存": "未知",
                "推荐后端": "CPU", "状态": "无显卡"}
    monkeypatch.setattr(gpu, "_detect_once", _once)

    gpu.detect()
    cached = gpu.detect()
    assert calls["n"] == 1
    assert cached["缓存"] is True
    gpu.detect(refresh=True)
    assert calls["n"] == 2


def test_gpu_unsupported_platform_is_explained(monkeypatch):
    gpu = _gpu(monkeypatch, system="Darwin")
    info = gpu.detect()
    assert info["状态"] == "无显卡"
    assert "不做 GPU 检测" in info["说明"]
    assert info["推荐后端"] == "CPU"
