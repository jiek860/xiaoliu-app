# -*- coding: utf-8 -*-
"""打包源同步工具：不能把隐私/开发文件带进去

为什么要有这个文件
------------------
打包流程是「开发目录 -> 复制一份干净的 -> 对那份打包」。
"复制一份干净的"这一步**每次改完代码都要重做**，
忘了就会把旧代码打进安装包 —— 而且**装出来照样能跑**，
只是行为是旧的，很难发现。

比"忘同步"更严重的是**把不该带的带进去**：
    data/config.json   你的 API Key、邮箱授权码、企微 Webhook
    data/chats.db      你和它的全部聊天记录
    data/memory.json   它的长期记忆
那些一旦进了安装包、发出去，就是**隐私事故**。

本文件守住这条底线。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "tools"))

import sync_package as sp                          # noqa: E402


# ── 绝对不能同步的东西 ──
FORBIDDEN = ["data", "backups", "optional_libs", "tests", "tools",
             "scripts", "staging", ".git", ".githooks", "dist", "build",
             "logs", "docs"]


@pytest.mark.parametrize("name", FORBIDDEN)
def test_forbidden_dirs_are_not_in_sync_list(name):
    """这些目录**一个都不许**进同步清单"""
    assert name not in sp.DIRS, "%s 被列进同步目录了 —— 会带进安装包" % name
    assert name not in sp.FILES, "%s 被列进同步文件了" % name
    assert name in sp.FORBIDDEN, \
        "%s 不在 FORBIDDEN 里 —— 同步后的安全检查就查不出它" % name


def test_sync_list_is_minimal():
    """同步清单要够小 —— 安装包里每多一个文件，用户就多一分困惑"""
    assert set(sp.DIRS) == {"core", "gui", "modules", "modules_repo", "libs"}, \
        "同步目录清单变了：%s" % sp.DIRS
    for name in ("CHANGELOG.md", "docs", "README.md"):
        assert name not in sp.FILES, \
            "%s 是开发文档，不该进安装包" % name
        assert name not in sp.OPTIONAL_FILES, \
            "%s 在 OPTIONAL_FILES 里 —— 会跟着进安装包" % name


def test_skip_covers_dev_junk():
    """__pycache__ / retired / .git 这些不该被复制"""
    for n in ("__pycache__", "retired", ".git", ".githooks",
              ".pytest_cache", ".ruff_cache"):
        assert n in sp.SKIP, "%s 没被排除" % n


def test_config_default_has_no_real_key():
    """`config.default.json` 是**脱敏版**，里面不许有填好的 Key

    这条是整套打包流程里最要紧的一条：config.default.json 会被打进
    安装包，如果里面带着你的 API Key，那每个装了这个包的人都有你的 Key。
    """
    p = os.path.join(BASE, "config.default.json")
    if not os.path.exists(p):
        pytest.skip("没有 config.default.json")
    import re
    s = open(p, encoding="utf-8", errors="ignore").read()
    hits = [(k, v) for k, v in re.findall(
        r'"(cloud_key|email_pass|webhook|api_key|cloud_url)"\s*:\s*"([^"]*)"',
        s, re.I) if v.strip()]
    # cloud_url 填了不算问题（那只是个接口地址，不是密钥）
    hits = [(k, v) for k, v in hits if k.lower() != "cloud_url"]
    assert not hits, (
        "config.default.json 里有填好的敏感字段：%s\n"
        "这个文件会被打进安装包 —— 等于把你的 Key 发给每个装机的人。"
        % [k for k, _ in hits])


def test_check_safety_catches_leaked_data(tmp_path):
    """`check_safety()` 要真的能查出问题（不是走过场）"""
    d = tmp_path / "fake_pkg"
    (d / "data").mkdir(parents=True)
    problems = sp.check_safety(str(d))
    assert problems, "data/ 混进来了，check_safety 却没报"

    d2 = tmp_path / "clean"
    d2.mkdir()
    assert not sp.check_safety(str(d2)), "干净的目录被误报"


def test_check_safety_catches_key_in_config(tmp_path):
    d = tmp_path / "pkg2"
    d.mkdir()
    (d / "config.default.json").write_text(
        '{"cloud_key": "sk-真key", "model_mode": "云端模型"}',
        encoding="utf-8")
    problems = sp.check_safety(str(d))
    assert problems, "配置里有真 Key，check_safety 却没报"


def test_plan_detects_differences(tmp_path):
    """`plan()` 要能算出"要新增什么"（不能永远返回空）"""
    d = tmp_path / "empty"
    d.mkdir()
    add, upd, dele = sp.plan(str(d))
    assert add, "对着一个空目录说'没有要新增的' —— plan 坏了"
    assert any("run.py" in a for a in add), "没算到 run.py 要新增"


def test_real_package_folder_is_clean():
    """真实打包目录（如果存在）必须是干净的"""
    dst = sp.DEFAULT_DST
    if not os.path.isdir(dst):
        pytest.skip("还没有打包目录")
    for n in FORBIDDEN:
        assert not os.path.exists(os.path.join(dst, n)), \
            "打包目录 %s 里混进了 %s" % (dst, n)
    assert not sp.check_safety(dst), sp.check_safety(dst)


# ══════════════════════════════════════════════════════════════
# 嵌套 .git —— 踩过的坑
# ══════════════════════════════════════════════════════════════
# 实测（2026-10-14）：打包源里残留着 `modules_repo\.git`
# （461 文件 / 1.79 MB），里面有**私有 gitee 仓库地址**。
# 没有凭据泄漏（git 默认不把 token 写进 config），
# 但仓库地址 + git 历史（objects/ 里可能有已删文件）都不该跟着安装包发出去。
#
# 它是怎么进去的：早先用 `robocopy /MIR` 手动同步，
# **只排除了 __pycache__、没排除 .git**。
#
# 为什么正式工具也没清掉它（两个原因叠加）：
#   ① 复制用 copytree(dirs_exist_ok=True) —— **只增不删**
#   ② "要删除"清单靠 plan() 比出来，而 plan() 的 walk() 会**跳过** .git
#      → .git 永远不出现在清单里 → 永远清不掉
#   ③ 更糟的是：`if not (...): return 0` 提前返回，
#      **清理那一步永远跑不到**（第二版才发现的）

def test_skip_covers_git():
    assert ".git" in sp.SKIP, \
        ".git 不在 SKIP 里 —— 嵌套的 git 仓库会被复制进安装包"


def test_copytree_actually_skips_nested_git(tmp_path):
    """`ignore_patterns(SKIP)` 对**嵌套**的 .git 有效吗

    这条实测过：有效（560 -> 49 文件）。但必须钉住 ——
    哪天有人把 SKIP 换成别的写法，这里会立刻发现。
    """
    import shutil
    src = tmp_path / "src"
    (src / "sub" / ".git" / "objects").mkdir(parents=True)
    (src / "sub" / ".git" / "config").write_text("url = secret",
                                                 encoding="utf-8")
    (src / "sub" / "a.py").write_text("x = 1", encoding="utf-8")

    dst = tmp_path / "dst"
    shutil.copytree(str(src), str(dst),
                    ignore=shutil.ignore_patterns(*sp.SKIP))
    assert (dst / "sub" / "a.py").exists(), "正常文件被误排"
    assert not (dst / "sub" / ".git").exists(), \
        "嵌套 .git 被复制过去了"


def test_purge_removes_stuff_already_there(tmp_path):
    """`purge_forbidden()` 要能清掉**已经存在**的 .git

    这条是关键：copytree 只增不删，plan() 又比不出 .git，
    所以必须有一个"无条件扫一遍"的清理步骤。
    """
    d = tmp_path / "pkg"
    (d / "modules_repo" / ".git" / "objects").mkdir(parents=True)
    (d / "modules_repo" / ".git" / "config").write_text("url = secret",
                                                        encoding="utf-8")
    (d / "core" / "__pycache__").mkdir(parents=True)
    (d / "core" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (d / "core" / "keep.py").write_text("x = 1", encoding="utf-8")

    removed, failed = sp.purge_forbidden(str(d))
    assert removed, "什么都没清掉 —— purge_forbidden 没生效"
    assert not failed, "有没删掉的：%s" % failed
    assert not (d / "modules_repo" / ".git").exists(), ".git 还在"
    assert not (d / "core" / "__pycache__").exists(), "__pycache__ 还在"
    assert (d / "core" / "keep.py").exists(), "正常文件被误删了！"


def test_purge_removes_readonly_files(tmp_path):
    """⚠️ **只读文件也必须删得掉**（这是最难发现的一个坑）

    git 的 `objects/` 里是**只读文件**。Windows 上 `shutil.rmtree`
    删不掉只读文件，而 `ignore_errors=True` 会**把失败吞掉** ——
    于是函数"成功返回"、调用方以为清干净了，实际 433 个对象文件还在。

    实测踩到：同步报告"清掉了 modules_repo/.git"，可它一直在，
    连跑两次都这么说。是 `test_real_package_has_no_nested_git`
    才把它揪出来的。
    """
    import stat
    d = tmp_path / "pkg2"
    ro = d / "modules_repo" / ".git" / "objects"
    ro.mkdir(parents=True)
    f = ro / "abc123"
    f.write_bytes(b"\x00" * 64)
    os.chmod(str(f), stat.S_IREAD)          # 设成只读

    removed, failed = sp.purge_forbidden(str(d))
    assert not failed, "只读文件没删掉（就是踩过的那个坑）：%s" % failed
    assert not (d / "modules_repo" / ".git").exists(), \
        ".git 还在 —— 只读文件挡住了删除"


def test_purge_reports_failure_instead_of_pretending(tmp_path):
    """删不掉时要**如实报出来**，不能假装成功

    （第一版 `ignore_errors=True` 就是假装成功的那种写法。）
    """
    d = tmp_path / "pkg3"
    (d / "core").mkdir(parents=True)
    removed, failed = sp.purge_forbidden(str(d))
    assert not removed and not failed, "干净目录不该报任何东西"
    # 返回值必须是**两个**列表 —— 只返回"删掉的"就没法报告失败
    assert isinstance(removed, list) and isinstance(failed, list)


def test_purge_is_reachable_even_when_in_sync(tmp_path):
    """⚠️ **"已经一致"时也必须跑到清理那一步**

    第二版踩的坑：清理写在 `if not (add or upd or dele): return 0`
    **之后**，于是目标里残留 .git 时，同步说"已经一致，不用动" ——
    清理永远跑不到。

    这条用源码检查（真跑一次要动真实目录，不适合放进测试套件）：
    `purge_forbidden` 的调用必须在提前 return 的**前面**。
    """
    src = open(os.path.join(BASE, "tools", "sync_package.py"),
               encoding="utf-8").read()
    i_purge = src.find("purge_forbidden(dst)")
    i_early = src.find("已经一致，不用动")
    assert i_purge > 0, "找不到 purge_forbidden 的调用"
    assert i_early > 0, "找不到提前返回那一段"
    assert i_purge < i_early, (
        "purge 在提前 return 之后 —— 目标里残留 .git 时清理跑不到。\n"
        "（这正是第二版的 bug：同步说'已经一致，不用动'，"
        "而 .git 一直留着）")

    # 还要确认"有没有残留"参与了提前返回的判断
    assert "stash" in src, \
        "没把'目标里已有的不该有的东西'算进差异 —— 会提前返回"


def test_real_package_has_no_nested_git():
    """真实打包目录里不许有**任何层级**的 .git"""
    dst = sp.DEFAULT_DST
    if not os.path.isdir(dst):
        pytest.skip("还没有打包目录")
    bad = []
    for r, ds, _fs in os.walk(dst):
        for d in ds:
            if d in (".git", ".githooks", "__pycache__", ".pytest_cache",
                     ".ruff_cache"):
                bad.append(os.path.relpath(os.path.join(r, d), dst))
    assert not bad, "打包目录里有不该有的目录（会跟着安装包发出去）：%s" % bad
