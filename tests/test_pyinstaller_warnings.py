# -*- coding: utf-8 -*-
"""PyInstaller warning 分类器：已知噪声放行，未知缺失必须报警。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.check_pyinstaller_warnings import (  # noqa: E402
    classify, extract_missing,
)


def test_extract_and_classify_known_noise():
    text = """
    missing module named numpy._core.add
    missing module named yaml
    missing module named pwd
    missing module named multiprocessing.TimeoutError
    """
    names = extract_missing(text)
    cats, unknown = classify(names)
    assert not unknown
    assert "numpy_internal_reflection" in cats
    assert "optional_python_packages" in cats
    assert "unix_or_platform" in cats


def test_unknown_missing_module_is_not_hidden():
    names = extract_missing("missing module named my_required_runtime_dep")
    _cats, unknown = classify(names)
    assert unknown == ["my_required_runtime_dep"]