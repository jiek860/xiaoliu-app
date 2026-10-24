# -*- coding: utf-8 -*-
"""GitHub PR 闭环测试：REST 流程、CI 归并、权限与地址解析（全离线）。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.github_pr import (  # noqa: E402
    GitHubClient, GitHubError, PRFlow, aggregate_checks, parse_remote,
)


def test_parse_remote_variants():
    assert parse_remote("https://github.com/jiek860/xiaoliu-app.git") == \
        "jiek860/xiaoliu-app"
    assert parse_remote("git@github.com:jiek860/xiaoliu-app.git") == \
        "jiek860/xiaoliu-app"
    assert parse_remote("https://example.com/a/b") == ""


def test_aggregate_checks():
    ok = [{"name": "tests", "status": "completed", "conclusion": "success"}]
    assert aggregate_checks(ok)["state"] == "success"
    assert aggregate_checks(ok + [
        {"name": "ci", "status": "in_progress", "conclusion": None}
    ])["state"] == "pending"
    assert aggregate_checks(ok + [
        {"name": "ci", "status": "completed", "conclusion": "failure"}
    ])["state"] == "failure"


class _Transport:
    def __init__(self):
        self.calls = []
        self.seen_auth = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        self.seen_auth.append(headers.get("Authorization", ""))
        path = url.replace("https://api.github.com", "")
        if path == "/repos/o/r" and method == "GET":
            return {"default_branch": "main"}
        if path == "/repos/o/r/git/ref/heads/main":
            return {"object": {"sha": "base"}}
        if path == "/repos/o/r/git/commits/base":
            return {"tree": {"sha": "tree0"}}
        if path.startswith("/repos/o/r/git/blobs"):
            return {"sha": "blob%d" % len(self.calls)}
        if path == "/repos/o/r/git/trees":
            return {"sha": "tree1"}
        if path == "/repos/o/r/git/commits" and method == "POST":
            return {"sha": "commit1"}
        if path == "/repos/o/r/git/ref/heads/x6/code-1":
            return {}          # 分支还不存在
        if path == "/repos/o/r/git/refs":
            return {"ref": "refs/heads/x6/code-1"}
        if path == "/repos/o/r/pulls":
            return {"number": 7, "html_url": "https://x/pr/7", "state": "open"}
        if path == "/repos/o/r/pulls/7":
            return {"state": "open", "head": {"sha": "commit1"}}
        if path == "/repos/o/r/commits/commit1/check-runs":
            return {"check_runs": [
                {"name": "tests", "status": "completed",
                 "conclusion": "success"}]}
        if path == "/repos/o/r/pulls/7/merge":
            return {"merged": True, "sha": "mergedsha"}
        raise AssertionError("未预期的请求: %s %s" % (method, path))


class _Trunk:
    allow_headless_agent = True
    config = {}
    base = "."

    def __init__(self):
        self.modules = {}


def test_client_commit_pr_merge_flow():
    t = _Transport()
    c = GitHubClient(token="secret-token", repo="o/r", transport=t,
                     sleep=lambda s: None)
    d = c.commit_files("x6/code-1", [("a.py", "x = 1\n")], "msg")
    assert d["commit"] == "commit1" and d["base"] == "main"
    pr = c.create_pr("x6/code-1", "main", "title")
    assert pr["number"] == 7
    ci = c.pr_status(7)
    assert ci["state"] == "success"
    assert c.merge_pr(7)["ok"] is True
    assert all(h == "token secret-token" for h in t.seen_auth)
    methods = [m for m, _u in t.calls]
    assert "PATCH" not in methods  # 新分支走 POST refs


def test_pr_flow_with_permission_and_ci():
    t = _Transport()
    c = GitHubClient(token="t", repo="o/r", transport=t, sleep=lambda s: None)
    events = []
    flow = PRFlow(_Trunk(), ".", repo="o/r", client=c,
                  event_cb=lambda e, d: events.append(e))
    r = flow.run([("a.py", "x")], title="PR", branch="x6/code-1",
                 wait_ci=True, merge=True)
    assert r["ok"] is True
    assert r["ci"]["state"] == "success"
    assert r["merge"]["ok"] is True
    assert "pr_created" in events and "pr_merged" in events
    assert PRFlow.ci_feedback(r).startswith("CI 状态: success")


def test_pr_flow_denied_without_trunk():
    t = _Transport()
    c = GitHubClient(token="t", repo="o/r", transport=t)
    r = PRFlow(None, ".", repo="o/r", client=c).run(
        [("a.py", "x")], title="x", branch="x6/code-1")
    assert r["ok"] is False and "审计" in r["error"]


def test_client_requires_https_and_token(monkeypatch):
    import core.github_pr as g
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(g, "credential_token", lambda *a, **k: "")
    try:
        GitHubClient(token="t", repo="o/r", base="http://api.github.com")
    except GitHubError as e:
        assert "HTTPS" in str(e)
    else:
        raise AssertionError("应该拒绝非 HTTPS")
    c = GitHubClient(token="", repo="o/r")
    try:
        c.default_branch()
    except GitHubError as e:
        assert "Token" in str(e)
    else:
        raise AssertionError("缺少 token 时应失败")
