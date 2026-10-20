# -*- coding: utf-8 -*-
"""电脑文件工具：白名单、读写、搜索、精确替换与备份。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.computer_controller import ComputerController  # noqa: E402


class _FakeTrunk:
    def __init__(self, base):
        self.base = base
        self.config = {"电脑控制": True, "文件白名单": []}
        self.confirm_cb = None
        self.modules = {}


def _controller(tmp_path):
    c = ComputerController(_FakeTrunk(str(tmp_path)))
    c._confirm = lambda *a, **k: True
    return c


def test_safe_path_allows_project_and_blocks_escape(tmp_path):
    c = _controller(tmp_path)
    inside = tmp_path / "a.txt"
    outside = tmp_path.parent / "outside.txt"
    assert c._safe_path(str(inside)) == str(inside)
    assert c._safe_path(str(outside)) is None


def test_file_create_read_search_edit_and_backup(tmp_path):
    c = _controller(tmp_path)
    f = tmp_path / "notes.txt"
    ok, msg = c.create_file(str(f), "alpha\nbeta\n")
    assert ok, msg
    r = c.read_text(str(f))
    assert r["ok"] and "alpha" in r["内容"] and r["总行数"] == 2
    s = c.search_text("beta", str(tmp_path))
    assert s["ok"] and s["命中数"] >= 1
    e = c.edit_text({"path": str(f), "old": "beta", "new": "gamma"})
    assert e["ok"], e
    assert "gamma" in f.read_text(encoding="utf-8")
    assert os.path.exists(e["备份"])


def test_edit_requires_unique_old_text(tmp_path):
    c = _controller(tmp_path)
    f = tmp_path / "dup.txt"
    f.write_text("x\nx\n", encoding="utf-8")
    r = c.edit_text({"path": str(f), "old": "x", "new": "y"})
    assert r["ok"] is False
    assert "不唯一" in r["错误"]


def test_delete_and_copy_require_confirm_and_stay_in_whitelist(tmp_path):
    c = _controller(tmp_path)
    src = tmp_path / "src.txt"
    src.write_text("data", encoding="utf-8")
    assert c.copy_file(str(src), str(tmp_path / "dst.txt"))[0] is True
    assert (tmp_path / "dst.txt").read_text(encoding="utf-8") == "data"
    assert c.delete_file(str(tmp_path / "dst.txt"))[0] is True
    assert not (tmp_path / "dst.txt").exists()
    assert c.create_file(str(tmp_path.parent / "bad.txt"), "x")[0] is False