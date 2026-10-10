# -*- coding: utf-8 -*-
"""回归测试：备份要跳过 datasets 等目录，且恢复不能删掉没备份的东西

背景：data 目录实测 37.9MB，其中 datasets(训练资料) 就占 35.5MB，
      而且 data/backup_* 本身也是备份 —— 不跳过会"备份套备份"越滚越大。
      真正需要备份的状态只有 2.2MB。

同时注意：一旦备份不再包含 datasets，restore 就绝不能先 rmtree 整个 data，
      否则 35MB 训练资料会被不可逆地删掉。这条测试就是防这个。
"""
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.backup import Backup  # noqa: E402


class FakeTrunk:
    def __init__(self, base):
        self.base = base
        self.config = {}


def _make_fake_project():
    """搭一个假项目：data 下有要备份的状态，也有该跳过的 datasets/旧备份/缓存"""
    root = tempfile.mkdtemp(prefix="bk_")
    data = os.path.join(root, "data")
    os.makedirs(data, exist_ok=True)
    # 要备份的
    open(os.path.join(data, "config.json"), "w", encoding="utf-8").write("{}")
    open(os.path.join(data, "memory.json"), "w", encoding="utf-8").write("{}")
    os.makedirs(os.path.join(data, "knowledge_docs"), exist_ok=True)
    open(os.path.join(data, "knowledge_docs", "a.md"), "w", encoding="utf-8").write("x")
    # 不该备份的
    os.makedirs(os.path.join(data, "datasets", "小6训练资料"), exist_ok=True)
    open(os.path.join(data, "datasets", "小6训练资料", "big.jsonl"),
         "w", encoding="utf-8").write("x" * 5000)
    os.makedirs(os.path.join(data, "backup_0101_0101"), exist_ok=True)
    open(os.path.join(data, "backup_0101_0101", "config.json"), "w", encoding="utf-8").write("{}")
    os.makedirs(os.path.join(data, "cache"), exist_ok=True)
    open(os.path.join(data, "cache", "c.bin"), "w", encoding="utf-8").write("x")
    os.makedirs(os.path.join(data, "logs"), exist_ok=True)
    open(os.path.join(data, "logs", "trunk.log"), "w", encoding="utf-8").write("x")
    os.makedirs(os.path.join(data, "recordings"), exist_ok=True)
    open(os.path.join(data, "recordings", "r.wav"), "w", encoding="utf-8").write("x")
    return root


def _rels(path):
    out = set()
    for r, _, fs in os.walk(path):
        for f in fs:
            out.add(os.path.relpath(os.path.join(r, f), path).replace("\\", "/"))
    return out


def test_backup_skips_datasets_and_old_backups():
    root = _make_fake_project()
    try:
        bk = Backup(FakeTrunk(root))
        r = bk.backup_now()
        assert r.get("成功"), r
        dest = os.path.join(bk.backup_dir, r["备份到"])
        got = _rels(dest)

        # 该备份的在
        assert "config.json" in got
        assert "memory.json" in got
        assert "knowledge_docs/a.md" in got
        # 不该备份的不在
        assert not any(p.startswith("datasets/") for p in got), got
        assert not any(p.startswith("backup_") for p in got), got
        assert not any(p.startswith("cache/") for p in got), got
        assert not any(p.startswith("logs/") for p in got), got
        assert not any(p.startswith("recordings/") for p in got), got
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_incremental_backup_also_skips():
    """第二次走增量分支，同样不能把 datasets 带进来"""
    root = _make_fake_project()
    try:
        bk = Backup(FakeTrunk(root))
        bk.backup_now()                      # 第一次：全量
        r2 = bk.backup_now()                 # 第二次：增量
        assert r2.get("增量") is True, r2
        dest = os.path.join(bk.backup_dir, r2["备份到"])
        got = _rels(dest)
        assert not any(p.startswith("datasets/") for p in got), got
        assert not any(p.startswith("backup_") for p in got), got
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_every_backup_is_a_complete_snapshot():
    """每份备份都必须是**完整快照**，不是"只有变化的那些文件"

    这条是数据安全的关键。原来的增量只复制比上次新的文件，于是第二份
    备份里只有变化的那些 —— 配上 _cleanup(keep=2)，全量的第一份很快被删掉，
    此后每份都残缺：拿它恢复到空目录会得到不完整的数据
    （实测新备份里连 config.json 都没有）。

    现在改为：变了的复制，没变的从上一份硬链接过来。
    """
    root = _make_fake_project()
    try:
        bk = Backup(FakeTrunk(root))
        bk.backup_now()
        set1 = _rels(os.path.join(bk.backup_dir, bk._last_backup_path()
                                  and os.path.basename(bk._last_backup_path())))
        # 只改动一个文件，其余保持原样
        with open(os.path.join(root, "data", "memory.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"changed": true}')
        time.sleep(1.1)                      # 避开同秒撞名
        r2 = bk.backup_now()
        dest2 = os.path.join(bk.backup_dir, r2["备份到"])
        got2 = _rels(dest2)

        # 第二份里必须**所有**该备份的文件都在，不能只有 memory.json
        assert len(set1) >= 3, "假项目的文件太少，测不出问题: %s" % sorted(set1)
        assert got2 == set1, (
            "第二份快照的文件集合和第一份不一致 —— 缺: %s，多: %s"
            % (sorted(set1 - got2), sorted(got2 - set1)))
        assert "config.json" in got2, "第二份快照缺 config.json"
        # 改动过的那个文件内容应当是新的
        assert "changed" in open(os.path.join(dest2, "memory.json"),
                                 encoding="utf-8").read()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_snapshot_reuses_unchanged_files_by_hardlink():
    """未变的文件用硬链接复用，不额外占空间；且删掉旧份不影响新份"""
    root = _make_fake_project()
    try:
        bk = Backup(FakeTrunk(root))
        bk.backup_now()
        time.sleep(1.1)
        r2 = bk.backup_now()
        d1 = os.path.join(bk.backup_dir, sorted(
            [d for d in os.listdir(bk.backup_dir) if d.startswith("backup_")])[0])
        d2 = os.path.join(bk.backup_dir, r2["备份到"])

        # 找一个没变过的文件，两边的 inode 应当相同（硬链接）
        same = 0
        for rel in ("config.json", "graph.json"):
            p1, p2 = os.path.join(d1, rel), os.path.join(d2, rel)
            if os.path.exists(p1) and os.path.exists(p2):
                if os.stat(p1).st_ino == os.stat(p2).st_ino:
                    same += 1
        assert same > 0, "未变的文件没有用硬链接复用"

        # 关键：硬链接不会因为旧份被删而丢数据
        content = open(os.path.join(d2, "config.json"), "rb").read()
        shutil.rmtree(d1, ignore_errors=True)
        assert os.path.exists(os.path.join(d2, "config.json")), \
            "删掉旧备份后新备份的文件没了（硬链接语义不对）"
        assert open(os.path.join(d2, "config.json"), "rb").read() == content
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_two_backups_in_same_second_do_not_collide():
    """同一秒内连做两次不能撞名、更不能互相覆盖"""
    root = _make_fake_project()
    try:
        bk = Backup(FakeTrunk(root))
        r1 = bk.backup_now()
        r2 = bk.backup_now()
        assert r1["备份到"] != r2["备份到"], "两份备份用了同一个名字，会互相覆盖"
        assert os.path.isdir(os.path.join(bk.backup_dir, r1["备份到"]))
        assert os.path.isdir(os.path.join(bk.backup_dir, r2["备份到"]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_restore_does_not_delete_unbacked_dirs():
    """恢复后，没进备份的 datasets / recordings 必须还在（防不可逆数据丢失）"""
    root = _make_fake_project()
    try:
        bk = Backup(FakeTrunk(root))
        r = bk.backup_now()
        name = r["备份到"]

        # 备份后又产生了新东西，同时 datasets 还在
        data = os.path.join(root, "data")
        open(os.path.join(data, "memory.json"), "w", encoding="utf-8").write('{"new":1}')

        rr = bk.restore(name)
        assert rr.get("成功"), rr

        # datasets / recordings 不能被删掉
        assert os.path.isdir(os.path.join(data, "datasets", "小6训练资料"))
        assert os.path.isfile(os.path.join(data, "recordings", "r.wav"))
        # 备份里的内容应当覆盖回来
        assert open(os.path.join(data, "memory.json"), encoding="utf-8").read() == "{}"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_export_filters_excluded_dirs():
    """导出 zip 也要排除 datasets（否则异地备份里塞 35MB 训练资料）"""
    import zipfile
    root = _make_fake_project()
    try:
        bk = Backup(FakeTrunk(root))
        out = os.path.join(root, "out")
        os.makedirs(out, exist_ok=True)
        r = bk.export(dest_dir=out, password="test123")
        assert r.get("成功"), r
        zp = r["导出到"]
        with zipfile.ZipFile(zp) as z:
            names = [n.replace("\\", "/") for n in z.namelist()]
        assert any(n.endswith("data/config.json") for n in names), names
        assert not any("datasets/" in n for n in names), names
    finally:
        shutil.rmtree(root, ignore_errors=True)
