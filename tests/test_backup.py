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
