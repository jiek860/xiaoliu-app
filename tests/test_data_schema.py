# -*- coding: utf-8 -*-
"""数据文件版本登记的测试（产品级 #5）

背景
----
这一轮修的两个真问题，根子都是**格式假设 + 没有版本校验**：
    · memory_organizer.auto_organize 假定每行都是合法 JSON，
      解析失败就跳过、写回却全量覆盖 -> 坏行被永久删除
    · startup_optimizer.precompile   假定 py_compile 会抛异常（它不会）

数据文件有 45 个，逐个版本化是过度设计。这里只守两件最值钱的：
    ① **降级保护**：数据是更新版本写的 -> 要警告，不能按旧格式静默误读
    ② 登记表本身坏了/被改 -> 不能把程序搞崩，也不能误报

本文件守住这些。
"""
import json
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import data_schema as ds            # noqa: E402


def _mkbase():
    d = tempfile.mkdtemp(prefix="x6schema_")
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    return d


def _write(base, name, content="{}"):
    p = os.path.join(base, "data", name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


# ── ① 基本流程 ──
def test_no_registry_is_reported_not_crashed():
    base = _mkbase()
    r = ds.check(base)
    assert r["ok"] is True, "没有登记表不该算错（首次运行就是这样）"
    assert r["unknown"], "应当提示还没有登记表"


def test_stamp_then_check_is_clean():
    base = _mkbase()
    for n in ("memory_cards.jsonl", "config.json"):
        _write(base, n)
    ds.stamp_all(base)
    r = ds.check(base)
    assert r["ok"] is True, r
    assert not r["warning"], r
    assert len(r["info"]) == 2, r


def test_unstamped_file_is_unknown_not_warning():
    """新加的、没登记的文件只算"未登记"，不该谎报成格式问题"""
    base = _mkbase()
    _write(base, "memory_cards.jsonl")
    ds.stamp_all(base)
    _write(base, "personality.json")          # 后加的，没登记
    r = ds.check(base)
    assert r["ok"] is True, r
    assert any("personality.json" in u for u in r["unknown"]), r


# ── ② 降级保护（最要紧的）──
def test_newer_data_is_a_warning():
    base = _mkbase()
    _write(base, "memory_cards.jsonl")
    ds.stamp_all(base)
    # 模拟"这份数据是更新版本的程序写的"
    d = ds.load(base)
    d["files"]["memory_cards.jsonl"] = ds.WATCHED["memory_cards.jsonl"] + 1
    ds.save(base, d)
    r = ds.check(base)
    assert r["ok"] is False, "数据比程序新却没报警"
    assert any("更新版本" in w for w in r["warning"]), r
    assert any("先别改它" in w for w in r["warning"]), \
        "警告里要明确告诉用户别动它"


def test_newer_registry_itself_is_a_warning():
    base = _mkbase()
    _write(base, "config.json")
    ds.stamp_all(base)
    d = ds.load(base)
    d["data_schema"] = ds.DATA_SCHEMA + 5
    ds.save(base, d)
    r = ds.check(base)
    assert r["ok"] is False
    assert any("登记表是更新版本" in w for w in r["warning"]), r


def test_older_data_is_a_warning():
    base = _mkbase()
    _write(base, "config.json")
    ds.stamp_all(base)
    d = ds.load(base)
    d["files"]["config.json"] = 0
    ds.save(base, d)
    r = ds.check(base)
    assert r["ok"] is False
    assert any("需要迁移" in w for w in r["warning"]), r


# ── ③ 健壮性 ──
def test_broken_registry_does_not_crash():
    base = _mkbase()
    with open(os.path.join(base, "data", "_schema.json"), "w",
              encoding="utf-8") as f:
        f.write("{这不是 JSON")
    r = ds.check(base)          # 不该抛
    assert isinstance(r, dict)
    assert ds.load(base) == {}, "坏登记表应被当作空表"


def test_registry_is_atomic_write():
    base = _mkbase()
    _write(base, "config.json")
    ds.stamp(base, "config.json")
    assert not os.path.exists(os.path.join(base, "data", "_schema.json.tmp")), \
        "留下了 .tmp"


def test_stamp_returns_false_on_bad_path():
    assert ds.stamp("Z:\\不存在的盘\\x", "config.json") is False


def test_describe_is_one_line():
    base = _mkbase()
    _write(base, "config.json")
    ds.stamp_all(base)
    s = ds.describe(base)
    assert "\n" not in s, "摘要应当是一行"
    assert "正常" in s, s


# ── ④ 真实项目上跑一遍（确认已经登记好、不误报）──
def test_real_project_registry_is_healthy():
    r = ds.check(BASE)
    assert not r["warning"], "真实项目上报出了警告：%s" % r["warning"]
    assert r["info"], "真实项目还没有登记表"
