# -*- coding: utf-8 -*-
"""coder_pro 单元测试"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.installed.coder_pro import CoderPro


def test_tools_declared():
    assert len(CoderPro.TOOLS) == 1
    t = CoderPro.TOOLS[0]
    assert t["name"] == "coder_task"
    assert t["danger"] is True
    assert t["confirm"] is True
    assert "hints" in t


def test_safe_root():
    cp = CoderPro()
    root = cp._safe_root()
    assert os.path.isdir(root)


def test_safe_root_nonexistent():
    cp = CoderPro()
    root = cp._safe_root("nonexistent_dir_xyz")
    # safe_join 不会报错，只是返回路径
    assert "nonexistent_dir_xyz" in root


def test_git_snapshot_no_repo():
    cp = CoderPro()
    tmp = tempfile.mkdtemp()
    try:
        r = cp._git_snapshot(tmp)
        assert "snapshot" in r
        assert r["auto_commit"] is False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_task_nonexistent_dir():
    cp = CoderPro()
    r = cp.run_task("test goal", "/nonexistent/path/xyz")
    assert r["ok"] is False
    assert "目录不存在" in r["error"]


if __name__ == "__main__":
    test_tools_declared()
    test_safe_root()
    test_safe_root_nonexistent()
    test_git_snapshot_no_repo()
    test_run_task_nonexistent_dir()
    print("All coder_pro tests passed!")
