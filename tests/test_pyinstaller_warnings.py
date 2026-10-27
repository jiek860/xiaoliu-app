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


# 2026-10-27：运行时锁文件补 openpyxl / python-pptx / xlsxwriter / lxml 后，
# `Windows Build` 的 `Check missing-module classification` 一次性列出这 14 个名字。
# 逐条确认都不影响运行：格式化/解析类是可选项（缺了只影响对应格式的读写），
# cython 只是编译期工具，annotationlib 是 3.13+ 才有的标准库，
# urllib.urlencode/urlopen 是 Python2 写法。这里锁住分类，防止再次变红。
BATCH25_MISSING_MODULES = [
    "BeautifulSoup", "annotationlib", "bs4", "cssselect", "cython",
    "cython.cimports", "defusedxml", "defusedxml.ElementTree", "html5lib",
    "html5lib.treebuilders", "lxml_html_clean", "openpyxl.tests",
    "urllib.urlencode", "urllib.urlopen",
]


def test_batch25_new_missing_modules_are_all_classified():
    text = "\n".join("missing module named %s" % n
                     for n in BATCH25_MISSING_MODULES)
    names = extract_missing(text)
    assert names == sorted(BATCH25_MISSING_MODULES)
    cats, unknown = classify(names)
    assert not unknown
    assert "BeautifulSoup" in cats["optional_python_packages"]
    assert "bs4" in cats["optional_python_packages"]
    assert "html5lib" in cats["optional_python_packages"]
    assert "lxml_html_clean" in cats["optional_python_packages"]
    assert "openpyxl.tests" in cats["optional_python_packages"]
    assert "urllib.urlencode" in cats["python2_legacy"]
    assert "urllib.urlopen" in cats["python2_legacy"]
    assert "cython" in cats["build_time_only"]
    assert "cython.cimports" in cats["build_time_only"]
    assert "annotationlib" in cats["newer_python_stdlib"]


# 2026-10-27 追加：exe 依赖集补 pypdf==6.21.3 后，同一道门禁又列出 8 个名字。
# 全部是 pypdf 的可选后端（pycryptodome 加密 / 阿拉伯文整形 / fontTools 字体），
# 以及 Pillow 已在锁里、pypdf 延迟导入 `from PIL import Image` 产生的一条提示。
PYPDF_MISSING_MODULES = [
    "Crypto", "Crypto.Cipher", "Crypto.Util", "PIL.Image", "arabic_reshaper",
    "bidi", "fontTools", "fontTools.ttLib",
]


def test_pypdf_missing_modules_are_all_classified():
    text = "\n".join("missing module named %s" % n
                     for n in PYPDF_MISSING_MODULES)
    names = extract_missing(text)
    assert names == sorted(PYPDF_MISSING_MODULES)
    cats, unknown = classify(names)
    assert not unknown
    for name in PYPDF_MISSING_MODULES:
        assert name in cats["optional_python_packages"]
