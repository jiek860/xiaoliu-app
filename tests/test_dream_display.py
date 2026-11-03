# -*- coding: utf-8 -*-
"""B4：dream_system（展示 / 导出 / 参数边界）

原来它只有能力表里的两个工具，界面上看不到任何东西；
B4 补了 ``to_markdown`` / ``export_md`` 并挂到「记忆 → 🌙 梦境」标签。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))


class _T:
    def __init__(self, base):
        self.base = str(base)


def _ds(tmp_path):
    from core.dream_system import DreamSystem
    (tmp_path / "data").mkdir(exist_ok=True)
    return DreamSystem(_T(tmp_path))


def test_markdown_when_no_dreams(tmp_path):
    md = _ds(tmp_path).to_markdown()
    assert "还没有做过梦" in md


def test_generate_then_markdown_contains_dream(tmp_path):
    ds = _ds(tmp_path)
    entry = ds.generate_dream()
    md = ds.to_markdown(5)
    assert "小6 的梦" in md
    assert entry["dream"][:10] in md


def test_export_md_writes_file(tmp_path):
    ds = _ds(tmp_path)
    ds.generate_dream()
    out = tmp_path / "dreams.md"
    r = ds.export_md(5, str(out))
    assert r["ok"] is True
    assert out.read_text(encoding="utf-8").startswith("# 小6 的梦")


def test_export_md_reports_write_failure(tmp_path):
    ds = _ds(tmp_path)
    # 用目录冒充文件，open 必然失败（模拟磁盘/权限问题）
    bad = tmp_path / "not_a_file"
    bad.mkdir()
    r = ds.export_md(5, str(bad))
    assert r["ok"] is False and "写梦境清单失败" in r["msg"]


def test_count_zero_does_not_return_whole_file(tmp_path):
    ds = _ds(tmp_path)
    for _ in range(3):
        ds.generate_dream()
    rows = ds.get_recent_dreams(0)          # 0 会被夹成 1，而不是 readlines()[-0:]
    assert len(rows) == 1, rows
    assert ds.get_recent_dreams("abc")      # 非数字用默认 10，不抛异常
    assert len(ds.get_recent_dreams(999)) <= 200


def test_bad_lines_reported_not_fatal(tmp_path):
    ds = _ds(tmp_path)
    with open(ds.path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"date": "2026-11-02", "dream": "好梦"},
                           ensure_ascii=False) + "\n")
        f.write("坏行\n")
    rows = ds.get_recent_dreams(10)
    assert any("读不出来" in str(r.get("说明", "")) for r in rows
               if isinstance(r, dict))
    assert ds.to_markdown(10).count("好梦") == 1


def test_run_makes_a_dream(tmp_path):
    r = _ds(tmp_path).run()
    assert r["梦数"] >= 1 and r["今天的梦"]
