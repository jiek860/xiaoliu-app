# -*- coding: utf-8 -*-
"""崩溃现场捕获（faulthandler）

为什么要有这个文件
------------------
2026-10-13 跑全量测试时出现过一次 **access violation**：
进程直接死（退出码 3221225477），之后连跑 4 次全过、单独跑 5 次全过。
**没复现、没现场、没定位** —— 只能在 CHANGELOG 里如实记一句"没查出来"。

关键点：**`sys.excepthook` 抓不到 C 层崩溃。**
它只能接住 Python 层没处理的异常；access violation 是 C 层内存错误，
进程当场死，解释器根本没机会跑到 excepthook。

faulthandler 是 Python 自带的，把 dump 做在信号/异常处理层，
能在进程死之前把所有线程的栈写进文件。

本文件守住三件事：
    ① 程序启动时**真的装上了**（而且是在 import Qt 之前）
    ② 测试套件也装了（那次崩溃就出在测试里）
    ③ 没有 faulthandler 时程序**照常能启动**（它是保护措施，不是功能）
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))

from core import crash_guard                       # noqa: E402


@pytest.fixture(autouse=True)
def _restore_session_enable():
    """每条测试跑完，把"会话级开启"恢复回来

    ⚠️ 为什么需要这个：本文件里有好几条用例要调 `reset_for_test()`
    （测"未开启"状态、测重复 enable），而那是**改全局状态**的 ——
    它会把 conftest 在会话开始时装好的捕获一起清掉。

    不恢复的话：`test_this_session_actually_enabled_it` 会假失败，
    **而且更糟的是后面真崩了就没有现场了** —— 那正是这个功能存在的意义。

    （这条是测试自己发现的：第一次跑就红在这，
      一开始还以为是 conftest 没生效。）
    """
    yield
    # 恢复：重新 enable 到默认位置
    crash_guard.enable()


# ══════════════════════════════════════════════════════════════
# ① 基本行为
# ══════════════════════════════════════════════════════════════
def test_enable_creates_log(tmp_path):
    crash_guard.reset_for_test()
    p = str(tmp_path / "fh.log")
    got = crash_guard.enable(p)
    assert got == p, "enable() 没返回日志路径"
    assert os.path.exists(p), "没建出日志文件"
    crash_guard.reset_for_test()


def test_enable_writes_start_marker(tmp_path):
    """每次启动要写一行分隔 —— 否则多次崩溃的栈混在一起分不清"""
    crash_guard.reset_for_test()
    p = str(tmp_path / "fh2.log")
    crash_guard.enable(p)
    crash_guard.reset_for_test()

    crash_guard.enable(p)                      # 第二次启动
    crash_guard.reset_for_test()

    s = open(p, encoding="utf-8").read()
    assert s.count("启动 ") == 2, "两次启动没写两行标记：%r" % s[:300]
    assert "pid=" in s and "python=" in s, s[:200]


def test_enable_is_idempotent(tmp_path):
    """重复 enable 不该重复装（也不该报错）"""
    crash_guard.reset_for_test()
    p = str(tmp_path / "fh3.log")
    a = crash_guard.enable(p)
    b = crash_guard.enable(p)
    assert a == b
    crash_guard.reset_for_test()


def test_enable_uses_default_path():
    """不给路径时，默认写到 data/logs/faulthandler.log"""
    crash_guard.reset_for_test()
    got = crash_guard.enable()
    crash_guard.reset_for_test()
    assert got, "没返回默认路径"
    assert got.replace("\\", "/").endswith("data/logs/faulthandler.log"), got


def test_enable_never_raises_on_bad_path():
    """⚠️ 崩溃捕获**自己**坏掉不许拦住程序启动

    它是保护措施，不是功能。装不上就退化成"和以前一样没有现场"，
    但不能因为装不上它就打不开程序。
    """
    crash_guard.reset_for_test()
    # 拿一个不可能的路径（Windows 上非法字符）
    got = crash_guard.enable("Z:\\不存在的盘\\没有这个目录\\x.log")
    crash_guard.reset_for_test()
    assert got == "", "坏路径竟然成功了？"
    # 关键：没抛异常


# ══════════════════════════════════════════════════════════════
# ② 手动 dump（卡死时用）
# ══════════════════════════════════════════════════════════════
def test_dump_now_writes_thread_stacks(tmp_path):
    """`dump_now()` 要真的写出栈 —— 卡死往往比崩溃更难查"""
    p = str(tmp_path / "dump.log")
    got = crash_guard.dump_now("测试用：界面卡住", log_path=p)
    assert got == p
    s = open(p, encoding="utf-8").read()
    assert "手动 dump" in s, s[:300]
    assert "界面卡住" in s, "没记录原因"
    assert "Traceback" in s or "File \"" in s, "没写出栈：%s" % s[:400]
    assert "线程数" in s, "没记线程数（那次崩溃和线程数有关）"


def test_dump_now_never_raises():
    crash_guard.reset_for_test()
    got = crash_guard.dump_now("没有日志路径时")
    crash_guard.reset_for_test()
    assert isinstance(got, str)               # 给个路径或空串都行，别抛


# ══════════════════════════════════════════════════════════════
# ③ 状态与读取
# ══════════════════════════════════════════════════════════════
def test_status_reports_on_and_off(tmp_path):
    crash_guard.reset_for_test()
    off = crash_guard.status()
    assert off["已开启"] is False
    assert "未开启" in off["说明"]

    crash_guard.enable(str(tmp_path / "s.log"))
    on = crash_guard.status()
    assert on["已开启"] is True
    assert "会自动" in on["说明"]
    assert on["线程数"] >= 1
    crash_guard.reset_for_test()


def test_recent_crashes_reads_tail(tmp_path):
    p = str(tmp_path / "tail.log")
    crash_guard.reset_for_test()
    crash_guard.enable(p)
    crash_guard.dump_now("第一件事", log_path=p)
    crash_guard.reset_for_test()

    s = crash_guard.recent_crashes(lines=200, log_path=p)
    assert "第一件事" in s, s[:200]


def test_recent_crashes_missing_file_is_empty():
    assert crash_guard.recent_crashes(
        log_path=r"Z:\没有这个文件\x.log") == ""


# ══════════════════════════════════════════════════════════════
# ④ 接线检查 —— 这才是重点
# ══════════════════════════════════════════════════════════════
def test_run_py_enables_it_before_qt():
    """⚠️ `run.py` 必须在**任何 Qt 导入之前**装上它

    装晚了就覆盖不到"导入阶段就崩"的情况 —— 而 Qt 导入阶段
    恰恰是最容易出 DLL 冲突的地方（项目文档里记着
    `先 import PyQt5 再 import torch 会 WinError 1114 / c10.dll`）。
    """
    src = open(os.path.join(BASE, "run.py"), encoding="utf-8").read()
    i_guard = src.find("crash_guard")
    assert i_guard > 0, "run.py 里没装崩溃捕获"
    for lib in ("PyQt5", "from gui", "from core.win_dll_fix"):
        i = src.find(lib)
        if i > 0:
            assert i_guard < i, \
                "crash_guard 在 %s 之后才装 —— 装晚了" % lib


def test_tests_also_enable_it():
    """测试套件也要装 —— 那次 access violation 就出在全量测试里

    pytest 自己的报告抓不到 C 层崩溃（进程直接死，teardown 都跑不到）。
    """
    src = open(os.path.join(BASE, "tests", "conftest.py"),
               encoding="utf-8").read()
    assert "crash_guard" in src, \
        "conftest 没装崩溃捕获 —— 测试再崩还是没有现场"


def test_this_session_actually_enabled_it():
    """本次测试会话应该已经装上了（conftest 生效的证明）"""
    st = crash_guard.status()
    assert st["已开启"], \
        "conftest 里的 enable() 没生效 —— 测试崩了不会有现场"
    assert st["日志"], "没有日志路径"


def test_wer_hint_is_present():
    """要留下"怎么拿原生帧"的说明

    ⚠️ faulthandler 只能 dump **Python 层**栈，
    **看不到 numpy/Qt/torch 的原生子帧**。
    只靠它定位不了 DLL 级别的崩溃 —— 得配合 WER dump / procdump。
    这个局限必须写在代码里，否则下次有人拿到栈会以为信息够了。
    """
    assert "procdump" in crash_guard.WER_HINT
    assert "LocalDumps" in crash_guard.WER_HINT
    assert "原生" in crash_guard.WER_HINT or "C 层" in crash_guard.WER_HINT
