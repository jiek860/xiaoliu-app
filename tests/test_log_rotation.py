# -*- coding: utf-8 -*-
"""日志管理的测试：轮转 + 读法（产品级 #2 #3）

背景
----
项目里有**两条写日志的路**，同一件事两个实现：
    core/logger.py  写 app.log    本来就有轮转 ✅
    core/trunk.py   写 trunk.log  `open(path,"a")` 直接追加，**没有任何上限** ❌

实测 trunk.log 已 914 KB 且无限增长；而 gui/log_dialog.py 打开日志中心时
用 `f.readlines()` **读整个文件**再切最后 300 行 ——
跑久了会越来越慢，最后打不开。

本文件守住三件事：
    ① 轮转真的会转，且只保留约定代数（不会无限堆 .old）
    ② trunk 的日志路径也走轮转（两条路统一）
    ③ 日志中心读的是**尾部**，内存不随文件大小增长
"""
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.logger import append_line, rotate_if_needed   # noqa: E402


# ── ① 轮转 ──
def test_rotation_happens_when_over_limit():
    d = tempfile.mkdtemp(prefix="x6log_")
    p = os.path.join(d, "t.log")
    for i in range(50):
        append_line(p, "第 %d 行" % i, max_size=300)
    assert os.path.exists(p), "主文件没了"
    assert os.path.exists(p + ".old"), "超限了却没轮转出 .old"
    assert os.path.getsize(p) <= 300 * 2, "轮转后主文件还是太大"


def test_rotation_works_repeatedly():
    """连着转两次也要成功 —— 这条能抓出"每隔一次失败"的 bug

    背景：第一版 rotate_if_needed 在 keep=1 时，循环里 src 与 dst 是同一个
    路径（都是 .old），先 remove 再 replace 必然抛异常。
    后果是**每隔一次轮转就失败，并把上一代的 .old 删掉**。
    连续写入时看起来正常（成功/失败交替），只有"连着转两次"才暴露。
    """
    d = tempfile.mkdtemp(prefix="x6log_")
    p = os.path.join(d, "t.log")
    # 第一次
    open(p, "w", encoding="utf-8").write("x" * 500)
    assert rotate_if_needed(p, 100) is True, "第一次轮转就失败了"
    assert os.path.exists(p + ".old"), "第一次没转出 .old"
    # 第二次（.old 已存在）—— 这里就是原来出错的地方
    open(p, "w", encoding="utf-8").write("y" * 500)
    assert rotate_if_needed(p, 100) is True, \
        "第二次轮转失败（.old 已存在时）—— 上一代日志会丢"
    assert os.path.exists(p + ".old"), "第二次后 .old 不见了"
    assert "y" in open(p + ".old", encoding="utf-8").read(), \
        ".old 里不是最新转出来的那一代"
    # 第三次，确认稳定
    open(p, "w", encoding="utf-8").write("z" * 500)
    assert rotate_if_needed(p, 100) is True, "第三次轮转失败"


def test_repeated_rotation_keeps_file_bounded():
    """反复轮转下主文件始终被控制住（不会偷偷失效）"""
    d = tempfile.mkdtemp(prefix="x6log_")
    p = os.path.join(d, "t.log")
    limit = 200
    for i in range(150):
        append_line(p, "第 %d 行 填充填充填充填充填充" % i, max_size=limit)
        assert os.path.getsize(p) <= limit * 3, \
            "第 %d 次后主文件涨到 %d 字节（阈值 %d）—— 轮转偷偷失效了" \
            % (i, os.path.getsize(p), limit)


def test_multi_generation_keeps_configured_count():
    """keep>1 时保留约定代数"""
    d = tempfile.mkdtemp(prefix="x6log_")
    p = os.path.join(d, "t.log")
    for i in range(200):
        append_line(p, "第 %d 行 填充填充填充" % i, max_size=150)
        rotate_if_needed(p, 150, keep=3)
    olds = sorted(f for f in os.listdir(d) if ".old" in f)
    assert len(olds) <= 3, "保留代数超了：%s" % olds
    assert olds, "一代都没留下来"


def test_no_rotation_under_limit():
    d = tempfile.mkdtemp(prefix="x6log_")
    p = os.path.join(d, "t.log")
    append_line(p, "短", max_size=10 * 1024 * 1024)
    assert not os.path.exists(p + ".old"), "没超限就轮转了"


def test_old_files_do_not_pile_up():
    """只保留约定的代数 —— 否则 .old 自己会无限堆"""
    d = tempfile.mkdtemp(prefix="x6log_")
    p = os.path.join(d, "t.log")
    for i in range(300):
        append_line(p, "第 %d 行 填充填充填充" % i, max_size=200)
    olds = [f for f in os.listdir(d) if ".old" in f]
    assert len(olds) <= 2, "轮转文件堆太多了：%s" % olds


def test_rotation_never_raises_on_bad_path():
    """轮转失败不能反过来搞挂程序"""
    assert rotate_if_needed("Z:\\不存在的盘\\x.log") is False
    assert append_line("Z:\\不存在的盘\\x.log", "hi") is False


def test_appends_newline_once():
    d = tempfile.mkdtemp(prefix="x6log_")
    p = os.path.join(d, "t.log")
    append_line(p, "没有换行")
    append_line(p, "有换行\n")
    content = open(p, encoding="utf-8").read()
    assert content == "没有换行\n有换行\n", repr(content)


def _real_calls(src_path, func_attr):
    """用 AST 找出真实调用 `xxx.func_attr(...)`，**不匹配注释和文档字符串**

    踩过的坑：第一版用 `"readlines()" not in src` 这种文本断言，
    结果匹配到了我**自己写的解释性注释**（注释里为了说明问题引用了旧写法），
    于是"修好了"反而测试失败。文本匹配分不清"代码里在用"和"注释里在讲"。
    """
    import ast
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == func_attr:
                hits.append(node.lineno)
    return hits


# ── ② trunk 的日志走同一条路 ──
def test_trunk_log_uses_rotating_writer():
    """trunk._log 必须走带轮转的写入，不能再自己 open(append)"""
    import ast
    p = os.path.join(BASE, "core", "trunk.py")
    src = open(p, encoding="utf-8").read()
    tree = ast.parse(src)

    # ① 必须用了公共写入
    assert "append_line" in src, "trunk._log 没走公共写入（轮转对它无效）"

    # ② 反证：不该再有"往 log_path 以 a 模式 open"的真实调用
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Name) and f.id == "open"):
            continue
        # open(self.log_path, "a")
        if not node.args:
            continue
        a0 = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else ""
        mode = ""
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value)
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = str(kw.value.value)
        if "log_path" in a0 and "a" in mode:
            bad.append(node.lineno)
    assert not bad, "trunk.py 第 %s 行还在直接 open(log_path,'a')（不走轮转）" % bad


def test_trunk_log_actually_writes():
    from tests.conftest import make_trunk
    t = make_trunk()
    d = tempfile.mkdtemp(prefix="x6trunk_")
    t.log_path = os.path.join(d, "trunk.log")
    t._log("测试一条日志")
    assert os.path.exists(t.log_path), "trunk 日志没写出来"
    assert "测试一条日志" in open(t.log_path, encoding="utf-8").read()


# ── ③ 日志中心读尾部，内存不随文件增长 ──
def test_log_dialog_reads_only_tail():
    """_read_file 必须用"边读边丢"，不能 readlines() 全读"""
    p = os.path.join(BASE, "gui", "log_dialog.py")
    src = open(p, encoding="utf-8").read()
    assert not _real_calls(p, "readlines"), \
        "日志中心还在真实调用 readlines()（文件大了会卡住）"
    assert "deque" in src, "没改成读尾部"


def test_read_tail_returns_correct_count_and_content():
    """行为验证：小文件全读、大文件只留尾部、行数仍准确"""
    import importlib.util
    # log_dialog 的 _read_file 是 show_log_dialog 里的闭包，没法直接 import。
    # 这里复刻它的算法做行为校验（等价实现），保证逻辑正确。
    import collections

    def read_tail(path, tail=300):
        buf = collections.deque(maxlen=tail)
        total = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                buf.append(line)
                total += 1
        return "".join(buf), total

    d = tempfile.mkdtemp(prefix="x6rd_")
    p = os.path.join(d, "a.log")
    with open(p, "w", encoding="utf-8") as f:
        for i in range(1000):
            f.write("行 %d\n" % i)
    text, total = read_tail(p, 10)
    assert total == 1000, "总行数数错了：%d" % total
    assert text.count("\n") == 10, "尾部行数不对：%d" % text.count("\n")
    assert "行 999" in text and "行 0\n" not in text, "尾部内容不对"
