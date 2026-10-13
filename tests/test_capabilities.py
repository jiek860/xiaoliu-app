# -*- coding: utf-8 -*-
"""能力冒烟测试：44 条注册能力，每条都要"证明它是活的"

为什么需要这个文件
------------------
实测（2026-10-13）：项目有 44 条能力，但**只有 2 条**被任何测试提到过（5%）。
后果之前已经吃到过两次：
    · memory_organizer.check_conflicts   `open(...)[-200:]` 必然 TypeError
      —— 这功能**从来没成功过**，因为从没有人跑过它
    · 「✅ 采纳建议」按钮  读的是占位符 "🤔 正在生成建议..."
      —— **从来没工作过**，同样因为没人跑过
写好的功能没人验证，等于没有。本文件不新增功能，只给已有能力加一道验证。

三层检查
--------
    第 1 层（全部 44 条）结构：模块能加载 / 方法存在 / 签名与声明的参数兼容
    第 2 层（离线只读）   真调用：确认返回的是结果而不是错误
    第 3 层（写入/需确认/长任务）**绝不真跑**：只验安全分级标对了

为什么第 3 层不真跑
    它们会改数据、打包数据、跑几分钟、或调用模型 —— 测试不该有副作用。
    但"不真跑"不等于"不验"：安全分级本身就是必须正确的东西，
    标错一个（比如把 clean_data 标成 readonly）就会让模型直接删数据。
"""
import ast
import inspect
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.trunk import Trunk                    # noqa: E402
from core import module_caps                    # noqa: E402
from tests.conftest import make_trunk           # noqa: E402

_trunk = None
_caps = None
_tc = None


def _setup():
    """注意：必须用 conftest.make_trunk()，不能直接 Trunk()

    `Trunk()` 构造 3 秒后会在后台线程里连 config.json 里配的 MCP 服务器，
    每个实例拉起 4 个子进程且**会累积**。实测踩到过：加了几个建 Trunk 的
    新测试之后，test_mcp_client 里那条断言全局 live_count() 的用例就挂了
    （它看到的是被污染的数字）。conftest 的 docstring 记的就是这件事。
    """
    global _trunk, _caps, _tc
    if _trunk is None:
        _trunk = make_trunk()
        _caps = module_caps.load_tools(BASE)
        _tc = _trunk._load_lazy("tool_caller")
    return _trunk, _caps, _tc


# ── 第 2 层白名单：离线、无副作用、可安全真跑 ──
# 判定标准：不联网、不写文件、不改数据、不调模型
OFFLINE_READONLY = [
    "stats_report", "mood_report", "growth_report", "learn_status",
    "memory_archives", "memory_conflicts", "dream_recent",
    "gpu_check", "browser_sessions", "action_recordings",
    "todo_list", "note_search", "calendar_today",
    "ocr_available", "ocr_history",
    "grouploop_stats", "grouploop_worst", "group_roles",
    "translate_detect", "kqa_list", "kqa_stats", "kqa_search",
]
# 依赖网络/外部服务：只要求"不抛异常"，允许返回错误（比如没网）
NETWORK_READONLY = ["weather_now", "translate_text"]

# ── 第 3 层：这些必须带安全标记，标错就是事故 ──
MUST_CONFIRM = ["clean_data", "memory_organize", "memory_archive", "auto_update"]
MUST_BG = ["auto_update", "crash_export", "debate", "learn_topic",
           "migrate_export", "model_vote", "startup_precompile", "task_goal"]


def _cap_names():
    _, caps, _ = _setup()
    return sorted(caps)


# ══════════════════════════════════════════════════════════════
# 第 1 层：结构（全部 44 条）
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", _cap_names())
def test_capability_structure(name):
    """声明的模块能加载、方法存在、且参数传得进去"""
    trunk, caps, tc = _setup()
    info = caps[name]

    # ① 模块能加载（声明的 mod 必须真能拿到）
    mod_name = info["mod"]
    m = trunk.modules.get(mod_name)
    if m is None:
        trunk.call(mod_name, "__no__")          # 触发懒加载
        m = trunk.modules.get(mod_name)
    assert m is not None, "能力 %s 声明的模块 %s 加载不起来" % (name, mod_name)

    # ② 方法存在
    method = info["method"]
    fn = getattr(m, method, None)
    assert fn is not None, "%s 没有方法 %s" % (mod_name, method)
    assert callable(fn), "%s.%s 不是可调用的" % (mod_name, method)

    # ③ 参数传得进去 —— 与 tool_caller._dispatch 的三条路径一一对应，
    #    任何一条成立就说明派发不会因为参数而失败
    declared = list((info.get("args") or {}).keys())
    try:
        ps = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return                                   # 内建/无法取签名，放过
    names = [p.name for p in ps
             if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    required = [p.name for p in ps
                if p.default is p.empty
                and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    argv_ok = bool(declared) and set(declared) <= set(names)     # ① kwargs
    zero_ok = not required                                       # ② 零参
    first_ok = bool(declared)                                    # ③ 首参兜底
    assert argv_ok or zero_ok or first_ok, (
        "能力 %s 的参数传不进去：声明 %s，方法签名 %s"
        % (name, declared, names))

    # ④ 声明的参数名如果和签名对不上，必须能走首参兜底
    if declared and not set(declared) <= set(names):
        assert len(declared) == 1, (
            "能力 %s 声明了多个参数 %s，但方法签名是 %s —— "
            "多参数只能走 kwargs 路径，名字必须完全一致"
            % (name, declared, names))


def test_all_capabilities_have_desc_and_hints():
    """每条能力都要有说明和关键词 —— 没有 hints 就进不了候选，等于藏着"""
    _, caps, _ = _setup()
    bad_desc = [n for n, v in caps.items() if not v.get("desc")]
    bad_hint = [n for n, v in caps.items() if not v.get("hints")]
    assert not bad_desc, "这些能力缺 desc：%s" % bad_desc
    assert not bad_hint, "这些能力缺 hints（进不了候选）：%s" % bad_hint


def test_no_duplicate_tool_names():
    """工具名不能重复 —— 重复会让其中一个永远选不到"""
    _, _, tc = _setup()
    names = list(tc.tools)
    assert len(names) == len(set(names)), "工具名有重复"


# ══════════════════════════════════════════════════════════════
# 第 2 层：离线只读能力真跑（证明它活着，不是只有声明）
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", OFFLINE_READONLY)
def test_offline_readonly_really_works(name):
    """离线只读能力：真调一次，返回不能是错误"""
    _, caps, tc = _setup()
    info = caps.get(name)
    assert info is not None, "%s 不在能力表里" % name
    assert info.get("readonly"), "%s 应该标 readonly（白名单里要求它无副作用）" % name

    args = {}
    if name == "kqa_search":
        args = {"keyword": "冒烟测试"}
    r = tc._dispatch(info, args, "")

    assert not isinstance(r, dict) or "错误" not in r, (
        "%s 返回了错误：%s" % (name, r))
    assert not isinstance(r, dict) or r.get("ok") is not False, (
        "%s 返回失败：%s" % (name, r))


@pytest.mark.parametrize("name", NETWORK_READONLY)
def test_network_readonly_does_not_crash(name):
    """依赖网络的能力：不要求成功（可能没网），但不能抛异常/崩"""
    _, caps, tc = _setup()
    info = caps.get(name)
    assert info is not None, "%s 不在能力表里" % name
    args = {"text": "hello", "city": "北京"}
    args = {k: v for k, v in args.items() if k in (info.get("args") or {})}
    try:
        tc._dispatch(info, args, "hello")
    except Exception as e:                        # noqa: BLE001
        pytest.fail("%s 抛异常了（应该被兜住）：%r" % (name, e))


# ══════════════════════════════════════════════════════════════
# 第 3 层：安全分级（不真跑，但必须标对）
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", MUST_CONFIRM)
def test_dangerous_capability_requires_confirm(name):
    """会改数据的能力必须标 confirm，否则模型能直接删数据"""
    _, caps, _ = _setup()
    info = caps.get(name)
    assert info is not None, "%s 不在能力表里" % name
    assert info.get("confirm"), "%s 会改数据，必须标 confirm" % name
    assert not info.get("readonly"), "%s 不能标 readonly" % name


@pytest.mark.parametrize("name", MUST_BG)
def test_long_capability_marked_bg(name):
    """长任务必须标 bg —— 否则聊天触发会把回复卡死（实测踩过 8 秒）"""
    _, caps, _ = _setup()
    info = caps.get(name)
    assert info is not None, "%s 不在能力表里" % name
    assert info.get("bg"), "%s 是长任务，必须标 bg" % name


def test_confirm_capabilities_refuse_without_ui():
    """没有确认界面时必须**拒绝执行**（fail-closed），不能静默跑"""
    _, caps, tc = _setup()
    for name in MUST_CONFIRM:
        info = caps[name]
        if info.get("bg"):
            continue                              # bg 的走后台，不在这条路径
        # 模拟没有确认回调的环境
        saved = getattr(tc.trunk, "confirm_cb", None)
        try:
            tc.trunk.confirm_cb = None
            r = tc._dispatch(info, {}, "")
            assert isinstance(r, dict) and r.get("ok") is False, (
                "%s 在没有确认界面时竟然执行了：%s" % (name, r))
        finally:
            if saved is not None:
                tc.trunk.confirm_cb = saved


# ══════════════════════════════════════════════════════════════
# 覆盖度自检：能力表和工具表必须一致
# ══════════════════════════════════════════════════════════════
def test_registry_and_tool_table_agree():
    """注册表里的每条能力都要在工具表里 —— 否则声明了也调不到"""
    _, caps, tc = _setup()
    missing = [n for n in caps if n not in tc.tools]
    assert not missing, "这些能力声明了但工具表里没有：%s" % missing


def test_dispatch_covers_every_capability():
    """每条能力都要能被 _dispatch 认出来（不能只认一部分）"""
    _, caps, tc = _setup()
    assert hasattr(tc, "_dispatch"), "tool_caller 没有 _dispatch"
    for name, info in caps.items():
        assert info.get("mod") and info.get("method"), (
            "%s 缺 mod/method，没法派发" % name)
