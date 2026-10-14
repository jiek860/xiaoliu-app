# -*- coding: utf-8 -*-
"""测试自身的卫生检查 —— 防止"建 Trunk 不屏蔽后台"这个坑第三次咬人

为什么要有这个文件
------------------
`Trunk()` 构造 3 秒后会在后台线程里连 config.json 里配的 MCP 服务器，
**每个实例拉起 4 个子进程且会累积**，还会占端口、连 Ollama。

这个坑已经踩过两次：
    第一次  tests/conftest.py 的 docstring 里记着 ——
            "一条断言 live_count() 的用例被后台拉起的 MCP 连接搞挂"
    第二次  加能力冒烟测试时又踩 ——
            新测试里建了几个裸 Trunk，test_mcp_client 里那条全局
            live_count() 断言就失败了（它看到的是被污染的数字）

**光写文档拦不住**（我读了 conftest 还是踩了），所以这里做机器检查：
每个 `Trunk()` 调用点，要么用 conftest.make_trunk()，要么在构造前
自己 mock 掉那几个后台入口。
"""
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(BASE, "tests")

# 构造前必须屏蔽掉的后台入口（与 conftest._BACKGROUND 一致）
BACKGROUND = ("_start_background", "_warmup", "_auto_unload_loop",
              "_warmup_ollama")
# 这些名字出现就说明不是"裸" Trunk
SAFE_CALL = ("make_trunk", "quiet_trunk")


def _test_files():
    for f in sorted(os.listdir(TESTS)):
        if f.startswith("test_") and f.endswith(".py"):
            yield os.path.join(TESTS, f)


def test_no_bare_trunk_in_tests():
    """测试里不许出现没有屏蔽后台的裸 Trunk()

    用 AST 找**真实的调用点**，不靠行文本匹配 ——
    第一版用正则，结果把本文件 docstring 里解释这个坑的那句话也当成了调用
    （自己抓自己）。注释和文档字符串里的 Trunk() 不该算数。
    """
    import ast
    problems = []
    unparsed = []
    for p in _test_files():
        # 用 utf-8-sig 读：PowerShell 的 Set-Content -Encoding UTF8 会写 BOM，
        # 带 BOM 时 ast.parse 直接失败 —— 第一版就是在这里静默 continue 了，
        # 结果一个真带裸 Trunk 的探针文件被**跳过**、没被抓到（负向测试发现的）。
        src = open(p, encoding="utf-8-sig", errors="ignore").read()
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            # 不能静默跳过 —— 跳过就等于这道检查对那个文件失效
            unparsed.append("%s: %s" % (os.path.basename(p), e))
            continue
        for node in ast.walk(tree):
            # 只认 Trunk() 这种无参调用，且不在注释/字符串里（AST 天然排除）
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "Trunk"
                    and not node.args and not node.keywords):
                continue
            i = node.lineno - 1
            window = "\n".join(lines[max(0, i - 8):i + 1])
            if any(s in window for s in SAFE_CALL):
                continue
            if all(b in window for b in ("_start_background", "_warmup")):
                continue
            problems.append("%s:%d  %s" % (os.path.basename(p), node.lineno,
                                           lines[i].strip()[:60]))
    assert not unparsed, "这些测试文件解析不了，检查对它们失效：%s" % unparsed
    assert not problems, (
        "发现没屏蔽后台的裸 Trunk()：\n  %s\n"
        "改法：用 tests/conftest.py 的 make_trunk()（或 quiet_trunk fixture），"
        "否则它 3 秒后会连 MCP，拉起子进程并污染其它用例的全局计数。"
        % "\n  ".join(problems))


def test_conftest_still_patches_all_background_entries():
    """conftest 的屏蔽清单不能缩水 —— 少一个就又漏一条路"""
    src = open(os.path.join(TESTS, "conftest.py"), encoding="utf-8").read()
    missing = [b for b in BACKGROUND if b not in src]
    assert not missing, "conftest 没屏蔽这些后台入口：%s" % missing


def test_new_test_files_use_the_helper():
    """本仓库约定：新测试文件用 make_trunk / quiet_trunk

    ⚠️ 判断"有没有建真 Trunk"必须用**正则**，不能用 `"Trunk()" in src`。
    踩过的坑（2026-10-14）：`tests/test_realtime_engine.py` 里定义了
    `class FakeTrunk`，用的时候写 `FakeTrunk()` —— 那里面**含有**
    子串 `Trunk()`，于是被误报成"建了真 Trunk 却没走 make_trunk"。

    真的 `Trunk()` 前面不该有字母/下划线（`FakeTrunk()` / `MyTrunk()`
    这类假件不算）。
    """
    import re
    # \b 在 FakeTrunk() 上也成立（d 和 T 之间不是词边界），所以用负向断言
    REAL_TRUNK = re.compile(r"(?<![A-Za-z_])Trunk\s*\(\s*\)")
    for p in _test_files():
        name = os.path.basename(p)
        if name in ("conftest.py", "test_test_hygiene.py"):
            continue
        src = open(p, encoding="utf-8", errors="ignore").read()
        if not REAL_TRUNK.search(src):
            continue
        ok = any(s in src for s in SAFE_CALL) or \
            ("_start_background" in src and "_warmup" in src)
        assert ok, "%s 建了 Trunk 但没走 make_trunk / 没屏蔽后台" % name
