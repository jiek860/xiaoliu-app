# -*- coding: utf-8 -*-
"""崩溃转储配置工具（WER LocalDumps / procdump）

为什么要有这个文件
------------------
`core/crash_guard.py` 用 faulthandler 抓到了**Python 层**栈，但它有硬局限：

    **看不到原生子帧** —— numpy / Qt / torch 的 C 层调用它看不见。

如果那次 access violation 是崩在 `c10.dll` 里某个偏移，
faulthandler 只能告诉你"崩在哪个 Python 函数调的"。
要定位那种，必须拿**进程级 dump**。

本文件守住三件事：
    ① 命令拼对（`-e 1` 那种会被正常异常刷爆的参数不能默认开）
    ② 权限判断对（WER 要管理员，procdump 不要）
    ③ 隐私提醒在（dump 含进程内存，可能有聊天内容和 Key）
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "tools"))

import setup_crash_dumps as scd                    # noqa: E402


# ══════════════════════════════════════════════════════════════
# ① procdump 命令行 —— **拼错了就等于白配**
# ══════════════════════════════════════════════════════════════
def _cmd(**kw):
    ok, cmd, note = scd.procdump_watch(**kw)
    return ok, cmd, note


def test_watch_returns_three_values():
    """⚠️ 必须返回**三个**值

    第一版写成 `return True, (" ".join(cmd), "说明…")` ——
    多了一层括号，调用方 `cmd, note = rest` 只拿到 1 个，
    直接 `ValueError: not enough values to unpack`。
    这条钉住返回值的形状。
    """
    r = scd.procdump_watch(wait=True)
    assert isinstance(r, tuple) and len(r) == 3, \
        "procdump_watch 必须返回 (ok, cmd, note)，实际 %r" % (r,)


def test_default_does_not_use_first_chance():
    """⚠️ 默认**不能**用 `-e 1`（首次异常就抓）

    那会**每个异常都抓** —— 而 Python 内部大量用异常做流程控制
    （StopIteration / KeyError 试探 / ImportError 探测…），
    结果是几秒钟就被正常异常刷爆，D 盘直接满。

    而且真正的崩溃（access violation 杀掉进程）一定是**未处理**异常，
    `-e` 就够。
    """
    ok, cmd, _ = _cmd(wait=True)
    assert ok, cmd
    assert "-e 1" not in cmd, \
        "默认用了 -e 1 —— 会被正常异常刷爆：%s" % cmd
    assert " -e " in cmd or cmd.endswith(" -e"), "没有 -e（抓不到异常）：%s" % cmd


def test_first_chance_requires_filter():
    """真要用 `-e 1` 时必须带过滤器（否则同上）"""
    ok, cmd, _ = _cmd(wait=True, first_chance=True)
    assert ok, cmd
    assert "-e 1" in cmd
    assert "-f" in cmd, "用了 -e 1 却没加 -f 过滤器：%s" % cmd


def test_no_empty_filter_argument():
    """⚠️ 不能出现空的 `-f ` —— 参数解析会错位

    第一版拼出过 `... -e 1 -f  -n 5 ...`（-f 后面空一格），
    procdump 会把 `-n` 当成过滤表达式。
    """
    for fc in (False, True):
        ok, cmd, _ = _cmd(wait=True, first_chance=fc)
        assert "-f  " not in cmd, "有空 -f：%s" % cmd
        assert not cmd.endswith("-f"), "命令以 -f 结尾：%s" % cmd


def test_uses_full_dump():
    """要用 `-ma`（完整 dump）

    迷你 dump 只有栈，看不到堆内存 —— 而 C 层内存错误的现场
    恰恰在堆里。配了迷你等于白配。
    """
    ok, cmd, _ = _cmd(wait=True)
    assert "-ma" in cmd, "没用完整 dump（-ma）：%s" % cmd


def test_dump_dir_is_under_project():
    """dump 存到项目下 —— 不散落到系统目录（也方便一起打包发给开发者）"""
    ok, cmd, note = _cmd(wait=True)
    assert "data" in cmd.lower() and "dump" in cmd.lower(), cmd


def test_accepteula_present():
    """必须带 -accepteula，否则首次运行会弹许可对话框卡住"""
    ok, cmd, _ = _cmd(wait=True)
    assert "-accepteula" in cmd, cmd


def test_privacy_warning_in_note():
    """⚠️ 说明里必须提醒"dump 含内存"

    dump 是进程内存快照 —— 里面**有聊天记录、API Key、记忆内容**。
    用户可能随手就发给别人了，必须提醒。
    """
    for w in (True, False):
        ok, _cmd_s, note = _cmd(wait=w)
        assert "内存" in note, "没提醒 dump 含内存：%s" % note
        assert "Key" in note or "聊天" in note, \
            "没说明具体风险（聊天/Key）：%s" % note


def test_wait_mode_explains_order():
    """-w 模式要讲清"先开监视、再开程序"的顺序

    顺序反了 procdump 会等不到进程 —— 用户会以为工具坏了。
    """
    ok, _cmd_s, note = _cmd(wait=True)
    assert "然后" in note or "再" in note, "没说清先后顺序：%s" % note


# ══════════════════════════════════════════════════════════════
# ② 权限判断
# ══════════════════════════════════════════════════════════════
def test_is_admin_returns_bool():
    assert isinstance(scd.is_admin(), bool)


def test_wer_explains_admin_requirement_when_not_admin():
    """不是管理员时，要给**能照着做**的提示，不是干巴巴一句"需要管理员"

    WER 写的是 HKLM（系统级），必须提权 —— 但用户未必知道怎么提。
    """
    if scd.is_admin():
        pytest.skip("当前就是管理员")
    ok, msg = scd.wer_enable()
    assert ok is False
    assert "管理员" in msg, msg
    # 要给出"怎么做"
    assert ("右键" in msg or "终端" in msg or "procdump" in msg), \
        "只说了需要管理员，没给替代做法：%s" % msg


# ══════════════════════════════════════════════════════════════
# ③ 状态读取不能抛
# ══════════════════════════════════════════════════════════════
def test_wer_status_never_raises():
    st = scd.wer_status()
    assert isinstance(st, dict)


def test_procdump_status_never_raises():
    s = scd.procdump_status()
    assert isinstance(s, str)


def test_wer_key_targets_local_dumps():
    """注册表路径要对 —— 写错地方等于没配"""
    assert "Windows Error Reporting" in scd.WER_KEY
    assert "LocalDumps" in scd.WER_KEY
    assert scd.WER_KEY.startswith("HKLM"), \
        "WER 本地转储在 HKLM 下（HKCU 不生效）"


def test_dump_type_defaults_to_full():
    """默认 dump_type=2（完整）

    type 1 是迷你 —— 那次崩溃是 C 层内存错误，迷你往往看不出所以然。
    """
    import inspect
    sig = inspect.signature(scd.wer_enable)
    assert sig.parameters["dump_type"].default == 2, \
        "WER 默认不是完整 dump —— C 层崩溃会看不清"


def test_dump_count_is_bounded():
    """dump 个位数要有上限 —— 每个几十到几百 MB，无限存会撑爆盘"""
    import inspect
    sig = inspect.signature(scd.wer_enable)
    n = sig.parameters["count"].default
    assert 1 <= n <= 50, "dump 保留个数 %s 不合理" % n


def test_procdump_urls_are_official():
    """下载地址必须是微软官方 —— 别从第三方拉可执行文件"""
    for u in scd.PROCDUMP_URLS:
        assert "sysinternals" in u.lower(), \
            "procdump 下载地址不是官方：%s" % u
