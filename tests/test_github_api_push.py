# -*- coding: utf-8 -*-
"""发布脚本 tools/github_api_push.py 的单元测试。

不联网：只测可独立验证的纯函数与 dry-run 流程。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from tools import github_api_push as push  # noqa: E402


def test_blob_sha_matches_git(tmp_path):
    """本地算的 blob sha 必须和 git hash-object 一致（否则复用判断会错）。"""
    p = tmp_path / "a.txt"
    data = "hello\nworld\n".encode("utf-8")
    p.write_bytes(data)
    expect = subprocess.run(
        ["git", "hash-object", str(p)], capture_output=True, text=True,
        encoding="utf-8").stdout.strip()
    assert push.blob_sha(data) == expect


def test_line_ending_of_detects_styles():
    assert push.line_ending_of(b"a\nb\n") == "lf"
    assert push.line_ending_of(b"a\r\nb\r\n") == "crlf"
    assert push.line_ending_of(b"a\r\nb\n") == "mixed"


def test_is_excluded_skips_local_artifacts():
    assert push.is_excluded(".trae/")
    assert push.is_excluded(".trae/foo.md")
    assert push.is_excluded("data/eval_result.json")
    assert push.is_excluded("core/__pycache__/x.pyc")
    assert push.is_excluded("coverage.json")
    assert not push.is_excluded("core/github_pr.py")
    assert not push.is_excluded("docs/92_Agent回归基线.md")


def test_collect_changes_uses_git_status(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    (tmp_path / "a.txt").write_text("new\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "junk.json").write_text("{}", encoding="utf-8")
    changes = dict(push.collect_changes(str(tmp_path)))
    assert changes.get("a.txt") == "put"
    assert "data/junk.json" not in changes


class FakeClient:
    repo = "o/r"

    def __init__(self, branch="b"):
        self.branch = branch
        self.posts = []

    def ref_sha(self, name):
        return {"main": "main-sha", "b": "branch-sha"}.get(name, "")

    def commit_tree(self, sha):
        return "tree-" + sha

    def create_branch(self, name, sha):
        self.posts.append(("CREATE", name, sha))

    def _request(self, method, path, payload=None):
        self.posts.append((method, path, payload))
        if "/git/blobs" in path:
            return {"sha": "blob-new"}
        if path.endswith("/git/trees"):
            return {"sha": "tree-new"}
        if path.endswith("/git/commits"):
            return {"sha": "commit-new"}
        return {}


def test_commit_worktree_bases_on_existing_branch(tmp_path, monkeypatch):
    """第二次推送应基于分支最新提交，才能快进更新同一个 PR。"""
    (tmp_path / "a.txt").write_text("new\n", encoding="utf-8")
    monkeypatch.setattr(push, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(push, "remote_tree", lambda client, tree: {})
    client = FakeClient()
    result = push.commit_worktree(client, [("a.txt", "put")], "msg", "main")
    assert result["changed"] is True
    commit = [p for p in client.posts if p[1].endswith("/git/commits")][0][2]
    assert commit["parents"] == ["branch-sha"]
    tree = [p for p in client.posts if p[1].endswith("/git/trees")][0][2]
    assert tree["base_tree"] == "tree-branch-sha"


def test_commit_worktree_falls_back_to_main_for_new_branch(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("new\n", encoding="utf-8")
    monkeypatch.setattr(push, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(push, "remote_tree", lambda client, tree: {})
    client = FakeClient(branch="brand-new")
    push.commit_worktree(client, [("a.txt", "put")], "msg", "main")
    commit = [p for p in client.posts if p[1].endswith("/git/commits")][0][2]
    assert commit["parents"] == ["main-sha"]


def test_dry_run_prints_plan_and_returns_zero(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "remote", "add", "origin",
                    "https://github.com/o/r.git"], cwd=str(tmp_path), check=True)
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(push, "BASE_DIR", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert push.main(["--dry-run"]) == 0
