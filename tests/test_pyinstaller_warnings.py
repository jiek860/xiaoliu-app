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


def test_tree_sitter_languages_is_optional():
    """tree_sitter_languages 是可选项，必须归到 optional 而不是未分类。

    它是 `core/symbol_parser.py` 里的 try-import：没装就退回正则解析，
    JS/TS 符号质量下降但功能不缺失。2026-10-25 起 `Windows Build` 一直红在
    这一条上（PyInstaller 把它列为 missing module），所以写条测试锁住分类。
    """
    names = extract_missing("missing module named tree_sitter_languages")
    cats, unknown = classify(names)
    assert not unknown
    assert "tree_sitter_languages" in cats["optional_python_packages"]