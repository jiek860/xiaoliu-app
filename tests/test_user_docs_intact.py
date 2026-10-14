# -*- coding: utf-8 -*-
"""用户文档必须一直在 —— 不许被任何工具/测试删掉

为什么加这个
------------
2026-10-14 出过一次：`小6工程化风险解决方案.txt`（用户给的方案文档）
**从磁盘上消失了**。是从 git 里 `checkout` 回来的（17164 字节完好）。

排查了所有带删除操作的代码：
    core/backup.py:264        只删 backups/ 下的旧备份目录
    tools/sync_package.py     只删**目标目录**（E:\\xiao6-package）里的东西
    tools/measure_coverage.py 只删自己生成的临时 json
都没发现能删到项目根目录的路径 —— **也就是说，至今没定位到原因。**

所以这条守卫的意义是：
    **下次再发生，会立刻红，而不是等到用户发现自己的文档没了。**

⚠️ 没定位到原因不等于没风险。这几个文档是用户自己写的/给的，
   丢了就是丢了（git 里有的能找回，没提交过的找不回）。
"""
import os

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 这些是**用户的东西**，任何工具都不该动
USER_DOCS = [
    "小6工程化风险解决方案.txt",
    "小6智能体最新架构与功能说明.txt",
    "使用说明-小白版.txt",
    "使用说明.txt",
    "检测手册.txt",
    "安装教程.txt",
    "模型教程.txt",
    "激活教程.txt",
    "FAQ.txt",
    "小6小传.txt",
    "开发者须知-密钥与发版.md",
    "README.md",
    "CHANGELOG.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
]

# 这些是程序跑起来要的，同样不能在
RUNTIME_FILES = [
    "run.py", "app.ico", "config.default.json",
    "requirements.txt", "requirements-optional.txt", "启动PyQt.bat",
]


@pytest.mark.parametrize("name", USER_DOCS, ids=USER_DOCS)
def test_user_doc_exists(name):
    p = os.path.join(BASE, name)
    assert os.path.exists(p), (
        "**用户文档不见了：%s**\n"
        "如果是误删，先从 git 找回：\n"
        "    git checkout HEAD -- \"%s\"\n"
        "这个文件不该被任何工具/测试删除。" % (name, name))
    assert os.path.getsize(p) > 0, "%s 是空文件 —— 被截断了？" % name


@pytest.mark.parametrize("name", RUNTIME_FILES, ids=RUNTIME_FILES)
def test_runtime_file_exists(name):
    p = os.path.join(BASE, name)
    assert os.path.exists(p), "程序运行必需的文件不见了：%s" % name


def test_docs_are_not_accidentally_gitignored():
    """⚠️ 文档不能被 .gitignore 排除

    如果被排除了，**删掉就找不回来了** —— 从 git 恢复的前提是它在 git 里。
    （这次能恢复，正是因为它没被排除。）
    """
    gi = os.path.join(BASE, ".gitignore")
    if not os.path.exists(gi):
        pytest.skip("没有 .gitignore")
    import subprocess
    for name in USER_DOCS:
        p = os.path.join(BASE, name)
        if not os.path.exists(p):
            continue
        r = subprocess.run(["git", "check-ignore", "-q", name],
                           cwd=BASE, capture_output=True)
        assert r.returncode != 0, (
            "%s 被 .gitignore 排除了 —— 删了就找不回来" % name)


def test_no_tool_deletes_at_project_root():
    """静态检查：tools/ 里不许有"对项目根目录动手"的删除

    这条是防回弹的 —— 现在没有，不等于以后不会被加进来。
    """
    import ast
    import re
    bad = []
    for r, ds, fs in os.walk(os.path.join(BASE, "tools")):
        ds[:] = [d for d in ds if d != "__pycache__"]
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(r, f)
            src = open(p, encoding="utf-8", errors="ignore").read()
            for i, ln in enumerate(src.splitlines(), 1):
                s = ln.strip()
                if s.startswith("#"):
                    continue
                # 删/移 的目标直接写成 BASE / "." 这种根路径 -> 危险
                if re.search(r"(rmtree|remove|unlink)\(\s*(BASE|base|\"\.\"|'\.')\s*[,)]", s):
                    bad.append((os.path.relpath(p, BASE), i, s[:70]))
    assert not bad, (
        "tools/ 里有对项目根目录的删除操作（会删到用户文档）：\n  %s"
        % "\n  ".join("%s:%d  %s" % b for b in bad))


def test_backup_cleanup_stays_inside_backups_dir():
    """`backup._cleanup()` 只准删 backups/ 里的东西

    它是全项目唯一一个真的 `shutil.rmtree` —— 如果哪天路径算错，
    删的可能是别处。这条钉住它的作用范围。
    """
    src = open(os.path.join(BASE, "core", "backup.py"),
               encoding="utf-8").read()
    i = src.find("def _cleanup")
    assert i > 0, "找不到 _cleanup"
    body = src[i:i + 900]
    assert "backup_dir" in body, \
        "_cleanup 里没看到 backup_dir —— 它删的可能不是备份目录"
    assert "os.listdir" in body, \
        "_cleanup 的删除目标不是 listdir(backup_dir) 来的？"
