# -*- coding: utf-8 -*-
"""缺依赖时给用户的安装提示：必须带国内镜像

为什么会需要这个文件
--------------------
实测（2026-10-13）：全项目 17 处 "pip install" 提示里，**只有 1 处**
带国内镜像（`-i https://pypi.tuna.tsinghua.edu.cn/simple`），
其余 16 处都让用户直接跑 `pip install xxx`。

后果很实际：用户按提示跑 → 走 PyPI 官方源 → 国内经常慢到以为卡死
（实测官网直链下 Ollama 只有 0.05 MB/s；PyPI 大包同理）。
用户分不清"慢"和"卡住"，最后就是不装了、功能不用了。

统一入口在 core/error_text.py：
    install_cmd(pkg)    -> 一条能直接粘的命令（带 -i 国内源）
    install_hint(pkg)   -> 上面那条 + "不想用命令行就走图形界面"的替代路径

本文件守住"统一"这件事 —— 别再有人各写各的。
"""
import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import error_text as et                  # noqa: E402

MIRROR = "tuna.tsinghua.edu.cn"


# ── 统一入口的行为 ──
def test_install_cmd_has_mirror():
    cmd = et.install_cmd("pyautogui")
    assert MIRROR in cmd, "install_cmd 没带国内源：%s" % cmd
    assert "-i" in cmd, cmd
    assert "pyautogui" in cmd, cmd


def test_install_cmd_targets_project_dir_by_default():
    """默认装进项目的 optional_libs，不污染系统 Python

    （install_optional.bat 也是这个约定 —— 卸载程序时不给系统留一堆包。）
    """
    cmd = et.install_cmd("pyautogui")
    assert "--target" in cmd and "optional_libs" in cmd, cmd


def test_install_cmd_can_target_current_env():
    cmd = et.install_cmd("pyautogui", target=None)
    assert "--target" not in cmd, cmd
    assert MIRROR in cmd, cmd


def test_install_cmd_empty_package():
    assert et.install_cmd("") == ""
    assert et.install_cmd(None) == ""


def test_install_hint_gives_two_paths():
    """提示要给两条路：命令行（能粘）+ 图形界面（不碰命令行的人）"""
    h = et.install_hint("pyautogui")
    assert MIRROR in h, "提示里没有国内源：%s" % h
    assert "功能扩展组件" in h, "没给图形界面的替代路径：%s" % h


def test_missing_module_translation_has_mirror():
    """真跑一遍：ImportError 翻译出来的建议必须带国内源"""
    try:
        raise ImportError("No module named 'pyautogui'")
    except ImportError as e:
        what, todo = et.friendly(e)
    assert what, "没翻译出人话"
    assert todo, "没给下一步"
    assert MIRROR in todo, "翻译出来的建议不带国内源：%s" % todo


@pytest.mark.parametrize("pkg", ["pyautogui", "opencv-python",
                                 "faster-whisper", "playwright",
                                 "uiautomation", "edge-tts"])
def test_common_packages_all_get_mirror(pkg):
    """常用可选包逐个验一遍"""
    try:
        raise ImportError("No module named '%s'" % pkg)
    except ImportError as e:
        _what, todo = et.friendly(e)
    assert MIRROR in (todo or ""), "%s 的建议不带国内源：%s" % (pkg, todo)


# ── 全项目扫描：不许再有"不带源的裸 pip install 提示" ──
_ALLOW = (
    # 这些是"提到 pip"但不是在让用户执行安装命令，不算
    "requirements.txt",
    "requirements-optional.txt",
    "install_optional.bat",
)


def _scan_bare_pip_hints():
    """找出**面向用户的**、带 pip install 但没带国内源的地方

    ⚠️ 两个坑（都踩过）：
    ① **docstring 里的示例不算** —— core/error_text.py 的函数文档里
       举了 `todo = "装上它试试：pip install pyautogui"` 作例子，
       第一版把这两处报成了"没带国内源"，是误报。
       这里逐行跟踪三引号状态来跳过 docstring。
    ② **多行字符串要拼接后再判** —— 辅助函数写成
           return ("py -3 -m pip install --target optional_libs %s "
                   "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkg)
       镜像在**下一行**，只看单行会误报。
    """
    bad = []
    for root in ("core", "gui", "modules", "tools"):
        for r, ds, fs in os.walk(os.path.join(BASE, root)):
            ds[:] = [d for d in ds
                     if d not in ("__pycache__", "retired", "_deprecated")]
            for f in fs:
                if not f.endswith(".py"):
                    continue
                fp = os.path.join(r, f)
                lines = open(fp, encoding="utf-8",
                             errors="ignore").read().splitlines()
                in_doc = False
                for i, ln in enumerate(lines):
                    s = ln.strip()
                    # 跟踪 docstring 状态（粗略但够用：数三引号出现次数）
                    if s.count('"""') % 2 == 1 or s.count("'''") % 2 == 1:
                        was = in_doc
                        in_doc = not in_doc
                        if was or s.startswith(('"""', "'''")):
                            continue          # docstring 起止行本身不算
                    if in_doc:
                        continue
                    if "pip install" not in s:
                        continue
                    if s.startswith("#"):
                        continue
                    if any(a in s for a in _ALLOW):
                        continue
                    # 拼接后续 2 行一起判（多行字符串）
                    blob = " ".join(x.strip() for x in lines[i:i + 3])
                    if MIRROR in blob:
                        continue
                    if any(k in blob for k in ("_ih(", "install_cmd",
                                               "install_hint", "error_text")):
                        continue
                    bad.append((os.path.relpath(fp, BASE), i + 1, s[:70]))
    return bad


def test_no_bare_pip_install_hints():
    """**面向用户的 pip 提示必须带国内源**（或者走统一入口）

    这条是防回弹的：以前就是各写各的，于是 17 处里 16 处漏了镜像。
    """
    bad = _scan_bare_pip_hints()
    assert not bad, (
        "这些地方给了 pip install 但**没带国内源**（用户跑会走官方源，"
        "国内经常慢到以为卡死）：\n  %s\n"
        "改法：用 core.error_text 的 install_cmd()/install_hint()，"
        "或者自己把 -i https://pypi.tuna.tsinghua.edu.cn/simple 加上。"
        % "\n  ".join("%s:%d  %s" % b for b in bad))
