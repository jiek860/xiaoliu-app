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
