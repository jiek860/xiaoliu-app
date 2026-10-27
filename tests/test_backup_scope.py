# -*- coding: utf-8 -*-
"""备份不能把"能重新下载的大东西"备进去

为什么要有这个文件
------------------
实测（2026-10-14）：`backups/` 堆到 **1421 MB**，两份，隔 12 分钟。
去看每份的内容 —— **708.3 MB 里 705.6 MB 是 Chromium 内核**
（`data/browsers` 的 .pak / .hyb / .dll）。

    EXCLUDE_DIRS 里有 browser_sessions（小），**没有 browsers**（705.6 MB）

原始注释写的是"实测 data 目录 37.9MB，其中只有 2.2MB 是真正需要备份的
状态" —— **那句话写的时候 `data/browsers` 还不存在**，
是浏览器功能加进来之后才把它漏进备份范围的。

判断标准：**能重新下载/重新生成的东西不进备份。**
用户真正怕丢的是记忆、聊天、配置、人格 —— 那些加起来才 2.7 MB。

本文件守住这条线。
"""
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.backup import Backup                     # noqa: E402

# 这些目录体积大、且**能重新得到**，不该进备份
BIG_AND_REGENERABLE = [
    ("browsers", "Chromium 内核 705.6 MB，playwright install 能重下"),
    ("datasets", "数据集，能重新导入"),
    ("cache", "缓存"),
    ("logs", "日志（有轮转）"),
    ("recordings", "录音"),
    ("uploads", "上传的临时文件"),
    ("browser_sessions", "浏览器会话"),
    ("staging", "打包/下载中间产物"),
    # 2026-10-27 补：backups/ 实测 979.5 MB，大头是 swe_work 里的 .git pack
    ("swebench", "SWE 评测产物，能重跑"),
    ("swe_work", "SWE 工作区（含 .git pack），能重新 clone"),
]


@pytest.mark.parametrize("name,why", BIG_AND_REGENERABLE,
                         ids=[n for n, _ in BIG_AND_REGENERABLE])
def test_big_regenerable_dirs_are_excluded(name, why):
    """大而可再生的目录必须在排除名单里"""
    assert name in Backup.EXCLUDE_DIRS, (
        "`%s` 没被排除 —— %s。\n"
        "后果实测过：备份从 2.7 MB 涨到 708 MB（膨胀 262 倍），"
        "backups/ 一天堆到 1.4 GB。" % (name, why))


def test_backups_and_their_zips_are_excluded():
    """备份自己不能被备份（否则越滚越大）"""
    for n in ("backups", "plugin_backups", "pathfix_backup",
              "config_backup"):
        assert n in Backup.EXCLUDE_DIRS, n


def test_skip_dir_matches_exclude_dirs():
    """_skip_dir() 的判断要和 EXCLUDE_DIRS 一致"""
    b = Backup.__new__(Backup)
    for n in Backup.EXCLUDE_DIRS:
        assert b._skip_dir(n), "EXCLUDE_DIRS 里有 %s 但 _skip_dir 说不用跳" % n
    assert b._skip_dir("backup_20260101_000000"), "旧备份目录没被跳过"
    assert not b._skip_dir("memory"), "普通目录不该被跳过"


def test_small_user_state_is_not_excluded():
    """**该备的必须还在** —— 别为了瘦身把用户数据也排掉了

    这条是反过来的保险：上一版修的是"排除太多"，这一版得防"排除过头"。
    """
    MUST_BACKUP = ["users", "rules", "skills", "tasks", "knowledge",
                   "learning", "knowledge_docs", "group_mem"]
    for n in MUST_BACKUP:
        assert n not in Backup.EXCLUDE_DIRS, \
            "%s 是用户状态，不该被排除在备份之外" % n


def test_real_folder_backup_is_small():
    """真实项目上跑一次备份，体积必须是**MB 级**，不是几百 MB

    这条是端到端的：直接对 E:\\xiaoliu 的 data 备一次，看多大。
    （不写进项目目录，用临时目录做目的地。）
    """
    data_dir = os.path.join(BASE, "data")
    if not os.path.isdir(data_dir):
        pytest.skip("没有 data 目录")

    # 算一下"如果排除名单对，备份应该多大"
    should = 0
    for r, ds, fs in os.walk(data_dir):
        ds[:] = [d for d in ds
                 if d not in Backup.EXCLUDE_DIRS
                 and not d.startswith("backup_")]
        for f in fs:
            try:
                should += os.path.getsize(os.path.join(r, f))
            except Exception:
                pass
    mb = should / 1048576
    assert mb < 50, (
        "按当前排除名单，备份会有 %.1f MB —— 太大了。\n"
        "多半是又有什么大东西漏进了 data/ 而没进 EXCLUDE_DIRS。\n"
        "判断标准：能重新下载/重新生成的不进备份。" % mb)


def test_browsers_is_the_big_one():
    """把"元凶"钉住：data/browsers 确实很大，所以它的排除不是可选项

    （如果哪天 browsers 没了或变小了，这条会失败，提醒重新评估
      —— 那是好事，说明前提变了。）
    """
    p = os.path.join(BASE, "data", "browsers")
    if not os.path.isdir(p):
        pytest.skip("本机没有 data/browsers")
    s = sum(os.path.getsize(os.path.join(r, f))
            for r, _d, fs in os.walk(p) for f in fs)
    assert s > 100 * 1048576, (
        "data/browsers 只有 %.1f MB —— 和当初（705.6 MB）差太多，"
        "重新评估一下它还要不要排除" % (s / 1048576))
