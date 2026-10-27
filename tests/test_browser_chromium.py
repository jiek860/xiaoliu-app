# -*- coding: utf-8 -*-
"""浏览器内核（Chromium）按需下载的提示（#7：再省 705 MB）

背景
----
data/browsers 里是 playwright 的 chromium，实测 705.6 MB
（chromium-1243 431.9 MB + chromium_headless_shell-1243 + ffmpeg + winldd）。

它**本来就不该随程序分发** —— 对方需要浏览器功能时再下就行。
但以前"没装"时的表现很差：用户看到的是 playwright 原始报错被截到 80 字，

    Executable doesn't exist at ...\\data\\browsers\\chromium-1243\\chrome-w

既看不出是"浏览器没下载"，也不知道该怎么办。

本文件守住：缺内核时给的是**能照着做的提示**，而不是原始报错。
"""
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import make_trunk               # noqa: E402


@pytest.fixture(scope="module")
def browser_cls():
    from modules.installed.browser import Browser
    return Browser


def _with_base(browser_cls, base):
    b = browser_cls.__new__(browser_cls)
    b.base = base
    b._page = None
    b._pw = None
    b._browser = None
    b.history = []
    return b


def test_info_when_missing_says_how_to_install(browser_cls):
    """缺内核时必须给出**可照做的命令**"""
    b = _with_base(browser_cls, tempfile.mkdtemp(prefix="x6nobrowser_"))
    info = b.chromium_info()
    assert info["已装"] is False
    assert "playwright install chromium" in info["怎么装"]
    # 要说明"这是正常的"，否则用户以为程序坏了
    assert "正常" in info["说明"], info["说明"]
    assert "第一次" in info["说明"], "没说明是首次使用时才需要"


def test_info_when_missing_mentions_the_path_pitfall(browser_cls):
    """必须提示 PLAYWRIGHT_BROWSERS_PATH 这个坑

    这是这个模块历史上真正翻过车的地方：装到了默认目录
    （%LOCALAPPDATA%\\ms-playwright），运行时却去 data/browsers 找，
    于是报 "Executable doesn't exist"。
    """
    b = _with_base(browser_cls, tempfile.mkdtemp(prefix="x6nobrowser_"))
    info = b.chromium_info()
    blob = str(info)
    assert "PLAYWRIGHT_BROWSERS_PATH" in blob, "没提环境变量这个坑"
    assert "ms-playwright" in blob, "没说明装错地方会去哪"


def test_info_when_installed_reports_size(browser_cls):
    """装了的时候要报出实际体积（用户想知道这 700 MB 花在哪）

    ⚠️ 夹具要写**够大**：_size() 故意把 MB 四舍五入到 1 位小数
    （真实场景是几百 MB，1 位足够）。第一版只写了 2 KB，
    0.00195 MB 被舍成 0.0，测试挂了 —— 是我的测试写错，不是函数错。
    """
    d = tempfile.mkdtemp(prefix="x6hasbrowser_")
    cr = os.path.join(d, "data", "browsers", "chromium-9999")
    os.makedirs(cr)
    with open(os.path.join(cr, "chrome.exe"), "wb") as f:
        f.write(b"x" * (3 * 1024 * 1024))          # 3 MB，够过舍入
    b = _with_base(browser_cls, d)
    info = b.chromium_info()
    assert info["已装"] is True
    assert info["文件数"] == 1
    assert info["MB"] == pytest.approx(3.0, rel=0.05), info


def test_headless_shell_dir_does_not_count_as_installed(browser_cls):
    """只有 headless_shell 而没有 chromium 时，不算"已装"

    两者是不同用途的二进制；只认 headless_shell 会导致
    非 headless 模式下启动失败。
    """
    d = tempfile.mkdtemp(prefix="x6hlonly_")
    os.makedirs(os.path.join(d, "data", "browsers",
                             "chromium_headless_shell-9999"))
    b = _with_base(browser_cls, d)
    assert b.chromium_info()["已装"] is False


def test_open_gives_actionable_message_not_raw_playwright_error(browser_cls):
    """open() 缺内核时给的必须是"先运行：…"，不是 playwright 原始报错"""
    b = _with_base(browser_cls, tempfile.mkdtemp(prefix="x6nobrowser_"))
    r = b.open("https://example.com")
    assert isinstance(r, dict)
    from core.plugin_errors import error_of
    msg = str((error_of(r) or {}).get("message", ""))
    assert msg, "没给错误信息"
    assert "playwright install chromium" in msg, \
        "没给出安装命令：%s" % msg
    assert "Executable doesn't exist" not in msg, \
        "还在甩 playwright 的原始报错：%s" % msg


def test_command_survives_the_80_char_truncation(browser_cls):
    """⚠️ 命令必须**完整**活过 80 字截断

    open() 里是 `str(e)[:80]`。第一版的提示写成
    "浏览器内核没下载（约 700 MB（含 headless shell 与 ffmpeg））。装法：py -3 -m
     playwright install chromium"，79 个字正好把命令切掉，
    用户看到一个装不了的半截命令。
    修法：把命令放最前面。
    """
    b = _with_base(browser_cls, tempfile.mkdtemp(prefix="x6nobrowser_"))
    from core.plugin_errors import error_of
    msg = str((error_of(b.open("https://example.com")) or {}).get("message", ""))
    assert len(msg) <= 80 or "playwright install chromium" in msg[:80], \
        "命令落在 80 字之外，会被截断：%s" % msg
    assert "playwright install chromium" in msg


def test_real_project_has_chromium_or_says_so(browser_cls):
    """真实项目上跑一遍 —— 两种结果都合法，但都要能说清"""
    t = make_trunk()
    b = t._load_lazy("browser")
    info = b.chromium_info()
    assert isinstance(info, dict)
    assert "已装" in info
    if info["已装"]:
        assert info["MB"] > 0
    else:
        assert info["怎么装"]
