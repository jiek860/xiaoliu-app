# -*- coding: utf-8 -*-
"""安装脚本必须明确 Python 支持范围并实际校验版本。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _text():
    return open(os.path.join(BASE, "install.bat"), encoding="utf-8").read()


def test_install_bat_states_supported_python_versions():
    s = _text()
    assert "Python 3.10 / 3.11 / 3.12" in s
    assert "3.13 尚未验证" in s
    assert "3.9 及以下不支持" in s


def test_install_bat_prefers_supported_launchers_and_checks_version():
    s = _text()
    assert "for %%V in (3.12 3.11 3.10)" in s
    assert "sys.version_info[:2]" in s
    assert "tools\\check_runtime_compat.py --allow-server" in s