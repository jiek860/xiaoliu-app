# -*- coding: utf-8 -*-
"""便携包构建：--out 相对路径和内容边界。"""
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools import build_portable  # noqa: E402


def test_relative_out_path_builds_zip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = build_portable.build_zip("portable.zip")
    assert os.path.isabs(out)
    assert out == str(tmp_path / "portable.zip")
    assert zipfile.is_zipfile(out)


def test_portable_zip_has_no_private_runtime_dirs(tmp_path):
    out = build_portable.build_zip(str(tmp_path / "portable.zip"))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "run.py" in names
    assert "使用说明-小白版.txt" in names
    assert any(n.startswith("modules_repo/") for n in names)
    forbidden = [n for n in names
                 if n.startswith(("data/", "tests/", "tools/", "backups/",
                                  "staging/"))
                 or "__pycache__" in n]
    assert not forbidden


def test_out_directory_appends_default_name(tmp_path):
    out = build_portable.build_zip(str(tmp_path))
    assert out.endswith(".zip")
    assert os.path.dirname(out) == str(tmp_path)
    assert zipfile.is_zipfile(out)