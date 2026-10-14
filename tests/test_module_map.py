# -*- coding: utf-8 -*-
"""模块星图的调用边扫描的回归保护（core/module_map._real_calls）

补这笔欠账的原因
----------------
"五种调用形态"的扫描是 v25.2.1 加的关键逻辑，当时只用**临时脚本**验过，
**没留下永久测试** —— 和 tool_presets 一样是我的欠账。

为什么这个扫描值得钉住
----------------------
它原来只认 trunk.call("字面量","字面量")，于是**一批正在跑的模块**
在图上看不到任何调用者、像孤儿。实测被误判过的：
    agent_coder / agent_analyst / agent_planner / empathy /
    plugin_signer / stt
"静态扫不到"会让人以为那些模块坏了或没用了。

五种形态
    ① 字面量      trunk.call("mod", "meth")
    ② 映射表驱动   AGENTS = {"代码": "agent_coder"}; trunk.call(AGENTS[k], ...)
    ③ 直接 import  from core.plugin_signer import PluginSigner
    ④ 别名         stt / voice 指向同一文件 -> 两个键都记边
    ⑤ 注册表驱动   tool_caller 按能力声明里的 mod 分发

⚠️ 关键：**不造假边**。
    smart_router 有一张 8 条的意图->模块映射表，但它**自己不调用**
    （core/trunk.py 只消费 意图=="task" 这一个分支，从没读过 r["模块"]），
    所以不该给它加边。这条克制反而挖出了 empathy 实际到不了的真问题。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

import core.module_map as mm                        # noqa: E402
from tests.conftest import make_trunk               # noqa: E402


@pytest.fixture(scope="module")
def built():
    t = make_trunk()
    return mm.build(t)


def _who(calls, target):
    return sorted({c[0] for c in calls if c[1] == target})


def test_edges_have_valid_endpoints(built):
    """边的两个端点都必须是真实节点 —— 否则查看器会静默丢掉它们"""
    valid = {m["name"] for m in built["modules"]}
    bad = [c for c in built["calls"]
           if c[0] not in valid or c[1] not in valid]
    assert not bad, "有悬空边：%s" % bad[:3]


def test_scan_finds_a_meaningful_number_of_edges(built):
    """边数不能少得离谱（扫描失效时最容易表现为"一条都没有"）"""
    assert len(built["calls"]) >= 20, \
        "只扫到 %d 条边，扫描可能失效了" % len(built["calls"])


# ── ① 字面量 + ② 映射表驱动 ──
def test_mapping_table_driven_calls_are_found(built):
    """task_loop 的 AGENTS 字典 + trunk.call(ag, ...) -> 要能扫到"""
    calls = built["calls"]
    for tgt in ("agent_coder", "agent_analyst", "agent_planner"):
        assert "task_loop" in _who(calls, tgt), \
            "映射表驱动的调用没扫到：task_loop -> %s" % tgt


# ── ③ 直接 import ──
def test_direct_import_is_found(built):
    """plugin_market 直接 from core.plugin_signer import —— 绕过 trunk.call"""
    calls = built["calls"]
    assert "plugin_market" in _who(calls, "plugin_signer"), \
        "直接 import 没扫到：plugin_market -> plugin_signer"


# ── ⑤ 注册表驱动 ──
def test_registry_driven_edges_from_tool_caller(built):
    """tool_caller 按能力声明里的 mod 分发 —— 声明本身就是一条边

    ⚠️ 不能断言"tool_caller 的出边**全部**来自注册表" ——
    它还有内置工具表那条路（browser / code_runner / vector_store …），
    那条路的方法名是变量，标成"按表分发"。第一版就是这么写错的。
    """
    out = [c for c in built["calls"] if c[0] == "tool_caller"]
    assert len(out) >= 20, "tool_caller 只有 %d 条出边" % len(out)

    reg = [c for c in out if "按能力声明" in c[2]]
    assert len(reg) >= 25, "注册表驱动的边只有 %d 条" % len(reg)

    # 另一条路（内置工具表）也要标出来源，不能留 "?" 这种没信息的东西
    assert not any(c[2] == "?" for c in out), \
        "还有标成 '?' 的边，图上看不出是怎么调的"
    table = [c for c in out if "按表分发" in c[2]]
    assert table, "内置工具表那条路没被识别出来"
    for c in table:
        assert c[1] in ("browser", "code_runner", "computer_controller",
                        "deep_search", "file_upload", "knowledge_graph",
                        "mcp_server", "task_planner", "vector_store"), \
            "按表分发的目标出乎意料：%s" % c[1]


# ── ⚠️ 不造假边 ──
def test_smart_router_does_not_fabricate_edges(built):
    """smart_router 只声明映射、自己不调用 -> 不该有出边

    它那张 8 条的表算完就被丢掉了（trunk 只消费 意图=="task"）。
    给它加边会把"实际到不了"的模块画成"有人在用"。
    """
    out = [c for c in built["calls"] if c[0] == "smart_router"]
    assert not out, "smart_router 只声明不调用，不该有边：%s" % out[:3]


def test_probe_idiom_is_not_an_edge(built):
    """`call(模块, "__no__")` 是懒加载探针惯用法，不是真调用"""
    bad = [c for c in built["calls"] if "__no__" in c[2]]
    assert not bad, "探针被当成调用了：%s" % bad[:3]


def test_self_calls_are_excluded(built):
    """模块调自己不算边（会把图弄乱）"""
    selfs = [c for c in built["calls"] if c[0] == c[1]]
    assert not selfs, "有自环边：%s" % selfs[:3]


def test_build_shape_is_stable(built):
    """build() 的返回结构是对外契约（模块星图页面按它渲染）"""
    assert set(built) == {"modules", "links", "calls"}, set(built)
    assert isinstance(built["modules"], list) and built["modules"]
    assert isinstance(built["links"], list)
    assert isinstance(built["calls"], list)
    for m in built["modules"][:5]:
        assert set(m) >= {"name", "cn", "desc", "group", "loaded"}, m


def test_every_module_is_a_node(built):
    """登记表里的模块都要出现在节点里（否则边会被丢掉）"""
    from core.lazy_config import LAZY_MAP
    names = {m["name"] for m in built["modules"]}
    missing = [k for k in LAZY_MAP if k not in names]
    assert not missing, "这些登记模块没有节点：%s" % missing[:5]
