# -*- coding: utf-8 -*-
"""插件市场模块层回归测试（离线，不需要网络）

守住的坑：core/lazy_config.py 的 LAZY_MAP 自 v3.0 起值是 **3 元组**
(文件, 类名, 中文名)。plugin_market.list_all() 原来写成

    for name, (f, cls) in LAZY_MAP.items():

只解 2 个，必然抛 "too many values to unpack (expected 2)"，
导致整个插件市场扫描失败（界面显示"❌ 扫描失败"）。
这个 bug 从初始版本一直存在，因为没人给这条路径写过测试。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.lazy_config import LAZY_MAP  # noqa: E402


class _Shim:
    """假 trunk：PluginMarket 只要 base/config/_log"""
    base = BASE
    config = {}

    def _log(self, m):
        pass


@pytest.fixture
def pm():
    from modules.installed.plugin_market import PluginMarket
    return PluginMarket(_Shim())


def test_lazy_map_shape_is_3_tuple():
    """前提：LAZY_MAP 的值是 3 元组。变了就该来改这里的测试和调用方。"""
    bad = [k for k, v in LAZY_MAP.items()
           if not (isinstance(v, (list, tuple)) and len(v) >= 3)]
    assert not bad, "LAZY_MAP 里这些键的值不是 3 元组: %s" % bad[:5]


def test_list_all_does_not_raise(pm):
    """核心回归：能扫完，不抛 too many values to unpack"""
    mods = pm.list_all()
    assert isinstance(mods, list)
    assert mods, "扫描结果不该为空"


def test_list_all_entries_have_required_keys(pm):
    need = {"name", "file", "cls", "installed", "active", "desc", "size", "icon"}
    for m in pm.list_all():
        missing = need - set(m)
        assert not missing, "%s 缺少字段 %s" % (m.get("name"), missing)
        assert m["file"], "%s 的 file 为空" % m.get("name")


def test_list_all_has_no_duplicate_files(pm):
    """stt / voice 这类别名指向同一文件，只应出现一次"""
    files = [m["file"] for m in pm.list_all()]
    dup = sorted({f for f in files if files.count(f) > 1})
    assert not dup, "同一个文件出现多次: %s" % dup


def test_stats_matches_list_all(pm):
    """统计数字必须和实际扫描结果对得上（否则界面上卡片数与状态栏会矛盾）"""
    mods = pm.list_all()
    st = pm.stats()
    assert st["模块总数"] == len(mods)
    assert st["已安装"] == sum(1 for m in mods if m["installed"])
    assert st["可安装"] == sum(1 for m in mods if not m["installed"])
    assert st["已安装"] + st["可安装"] == st["模块总数"]
    assert st["总大小KB"] >= 0


def test_run_returns_stats(pm):
    """trunk.call('plugin_market','run') 走的就是 stats()"""
    assert pm.run() == pm.stats()
