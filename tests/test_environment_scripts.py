# -*- coding: utf-8 -*-
"""开发/运行/打包三套虚拟环境脚本必须存在且分离依赖。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _read(name):
    return open(os.path.join(BASE, "scripts", name), encoding="utf-8-sig").read()


def test_env_setup_scripts_exist_and_are_documented():
    all_script = _read("setup_all_envs.ps1")
    for name in ("setup_dev_env.ps1", "setup_runtime_env.ps1",
                 "setup_build_env.ps1", "check_envs.ps1"):
        assert os.path.exists(os.path.join(BASE, "scripts", name))
        assert name in all_script


def test_dev_runtime_build_have_different_dependency_sets():
    dev = _read("setup_dev_env.ps1")
    runtime = _read("setup_runtime_env.ps1")
    build = _read("setup_build_env.ps1")
    assert "requirements-dev.txt" in dev
    assert "requirements.txt" in dev
    assert "requirements.txt" in runtime
    assert "requirements-optional.txt" in runtime
    assert "pyinstaller" in build.lower()
    assert "requirements-dev.txt" not in runtime
    assert "requirements-dev.txt" not in build

def test_optional_env_probe_has_structured_result():
    from tools.check_optional_env import probe
    # 只为结构断言，不在 pytest 进程里加载 onnxruntime/OpenCV 等原生 DLL；
    # 真正的可选依赖探测由 .runtime-venv 的 check_optional_env.py 执行。
    r = probe(import_modules=False)
    assert set(r) >= {"ok", "missing", "checked", "chromium_dirs",
                      "voice_backend"}
    assert isinstance(r["missing"], list)
    assert r["checked"] >= 10
