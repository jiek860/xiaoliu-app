# -*- coding: utf-8 -*-
"""GitHub PR 闭环：分支 -> 提交 -> PR -> CI -> 合并。

背景
----
本机 `git push` 到 github.com:443 经常被 RST，但 api.github.com 可用，
所以这里只用 REST API 写仓库（blob/tree/commit/ref/pull），不依赖 git push。

安全
----
* Token 来源：显式参数 > GITHUB_TOKEN/GH_TOKEN > git credential fill；
  **任何日志、异常、事件里都不出现 token**；
* 推送前经过 `authorize_agent_action`（权限中心 + 审计）；
* 只允许 HTTPS API 地址，避免把 token 发到任意主机。
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

API_BASE = "https://api.github.com"
_SSH_RE = re.compile(r"^git@([^:]+):(.+?)(?:\.git)?$")


class GitHubError(RuntimeError):
    pass


def parse_remote(url):
    """解析 owner/repo；支持 https 与 git@ 两种远程地址。"""
    url = str(url or "").strip()
    m = _SSH_RE.match(url)
    if m:
        return m.group(2).strip("/")
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def detect_repo(root):
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=root,
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        url = (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return parse_remote(url)


def credential_token(host="github.com"):
    """从系统凭据管理器取 token；失败返回空串（绝不打印内容）。"""
    try:
        p = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=%s\n\n" % host,
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in (p.stdout or "").splitlines():
        if line.startswith("password="):
            return line[len("password="):].strip()
    return ""


def resolve_token(token=None):
    return str(token or os.environ.get("GITHUB_TOKEN")
               or os.environ.get("GH_TOKEN") or credential_token() or "")


def _safe_host(base):
    return str(base or "").startswith("https://")


class GitHubClient:
    """最小 REST 客户端；transport 可注入，便于离线测试。"""

    def __init__(self, token=None, repo="", base=API_BASE, timeout=30,
                 transport=None, sleep=time.sleep):
        self.token = resolve_token(token)
        self.repo = str(repo or "").strip("/")
        self.base = str(base or API_BASE).rstrip("/")
        if not _safe_host(self.base):
            raise GitHubError("只允许 HTTPS GitHub API 地址")
        self.timeout = int(timeout or 30)
        self.transport = transport
        self.sleep = sleep
        self.calls = []

    # ---------------------------------------------------------- HTTP
    def _request(self, method, path, payload=None, raw=False):
        url = path if path.startswith("http") else self.base + path
        if not url.startswith("https://"):
            raise GitHubError("拒绝非 HTTPS 请求")
        if not self.token:
            raise GitHubError("缺少 GitHub Token")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": "token " + self.token,
            "User-Agent": "xiaoliu-code-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.calls.append({"method": method, "path": path})
        if callable(self.transport):
            return self.transport(method, url, headers, body)
        req = urllib.request.Request(url, data=body, method=method,
                                     headers=headers)
        try:
            # 安全：上面已强制 https:// 且只允许 api.github.com/HTTPS 主机
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # nosec B310
                data = r.read().decode("utf-8", "replace")
                return json.loads(data) if data.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            raise GitHubError("GitHub API %s %s -> %s %s" % (
                method, path, e.code, detail)) from None
        except urllib.error.URLError as e:
            raise GitHubError("GitHub API 连接失败: %s" % e.reason) from None

    # ---------------------------------------------------------- 读
    def default_branch(self):
        info = self._request("GET", "/repos/%s" % self.repo)
        return str(info.get("default_branch") or "main")

    def ref_sha(self, branch):
        try:
            info = self._request(
                "GET", "/repos/%s/git/ref/heads/%s" % (self.repo, branch))
        except GitHubError as e:
            if "404" in str(e):
                return ""      # 分支还不存在
            raise
        return str((info.get("object") or {}).get("sha") or "")

    def commit_sha(self, rev):
        return str(self._request(
            "GET", "/repos/%s/commits/%s" % (self.repo, rev)).get("sha") or "")

    def commit_tree(self, sha):
        return str((self._request(
            "GET", "/repos/%s/git/commits/%s" % (self.repo, sha))
            .get("tree") or {}).get("sha") or "")

    def pr_status(self, number):
        pr = self._request("GET", "/repos/%s/pulls/%d" % (self.repo, number))
        head = str((pr.get("head") or {}).get("sha") or "")
        checks = self._request(
            "GET", "/repos/%s/commits/%s/check-runs" % (self.repo, head))
        return aggregate_checks(checks.get("check_runs") or [],
                                state=str(pr.get("state") or ""))

    # ---------------------------------------------------------- 写
    def create_branch(self, branch, sha):
        return self._request(
            "POST", "/repos/%s/git/refs" % self.repo,
            {"ref": "refs/heads/" + branch, "sha": sha})

    def commit_files(self, branch, files, message, base=None):
        """一次提交多个文件；files = [(相对路径, 文本内容)]。"""
        base = base or self.default_branch()
        base_sha = self.ref_sha(base)
        if not base_sha:
            raise GitHubError("找不到基分支: " + base)
        tree_sha = self.commit_tree(base_sha)
        entries = []
        for rel, text in files:
            blob = self._request(
                "POST", "/repos/%s/git/blobs" % self.repo,
                {"content": base64.b64encode(
                    str(text).encode("utf-8")).decode("ascii"),
                 "encoding": "base64"})
            entries.append({"path": str(rel).replace("\\", "/"),
                            "mode": "100644", "type": "blob",
                            "sha": blob.get("sha")})
        tree = self._request(
            "POST", "/repos/%s/git/trees" % self.repo,
            {"base_tree": tree_sha, "tree": entries})
        commit = self._request(
            "POST", "/repos/%s/git/commits" % self.repo,
            {"message": str(message or "chore: xiaoliu code agent"),
             "tree": tree.get("sha"), "parents": [base_sha]})
        commit_sha = commit.get("sha")
        if self.ref_sha(branch):
            self._request("PATCH", "/repos/%s/git/refs/heads/%s" % (
                self.repo, branch), {"sha": commit_sha, "force": False})
        else:
            self.create_branch(branch, commit_sha)
        return {"ok": True, "branch": branch, "base": base,
                "commit": commit_sha, "files": [f[0] for f in files]}

    def create_pr(self, head, base, title, body=""):
        pr = self._request(
            "POST", "/repos/%s/pulls" % self.repo,
            {"head": head, "base": base, "title": title,
             "body": body or ""})
        return {"ok": True, "number": int(pr.get("number") or 0),
                "url": pr.get("html_url") or "", "state": pr.get("state")}

    def wait_ci(self, number, timeout=900, interval=15):
        deadline = time.time() + max(30, int(timeout or 900))
        last = {"state": "pending", "checks": []}
        while time.time() < deadline:
            last = self.pr_status(number)
            if last.get("state") in ("success", "failure"):
                return last
            self.sleep(max(1, int(interval or 15)))
        last = dict(last)
        last["state"] = "timeout"
        return last

    def merge_pr(self, number, method="merge"):
        r = self._request(
            "PUT", "/repos/%s/pulls/%d/merge" % (self.repo, number),
            {"merge_method": method})
        return {"ok": bool(r.get("merged")), "sha": r.get("sha") or "",
                "message": r.get("message") or ""}


def aggregate_checks(check_runs, state="open"):
    """把 check-runs 归并成 success / failure / pending。"""
    if str(state) == "closed":
        return {"state": "closed", "checks": []}
    names, pending, failed = [], False, False
    for c in check_runs or []:
        names.append(str(c.get("name") or ""))
        status = str(c.get("status") or "")
        conclusion = str(c.get("conclusion") or "")
        if status != "completed":
            pending = True
        elif conclusion in ("failure", "cancelled", "timed_out", "action_required"):
            failed = True
    if failed:
        result = "failure"
    elif pending:
        result = "pending"
    else:
        result = "success"
    return {"state": result, "checks": names}


def authorize_push(trunk, repo, branch, files):
    """推送前的统一权限门；没有权限中心时默认拒绝（fail-closed）。"""
    if trunk is None:
        return {"allow": False, "reason": "缺少 trunk，无法审计推送"}
    from core.agent_permissions import authorize_agent_action
    action = {
        "type": "network_push", "risk": "high",
        "args": {"repo": repo, "branch": branch,
                 "files": [str(f[0]) for f in files or []]},
        "reason": "代码 Agent 推送 GitHub 并创建 PR",
    }
    return authorize_agent_action(
        trunk, "code_agent", action,
        title="代码 Agent 推送 GitHub", detail="%s -> %s" % (repo, branch))


class PRFlow:
    """完整流程：分支 -> 提交 -> PR ->（可选）等 CI ->（可选）合并。"""

    def __init__(self, trunk, root, repo="", token=None, client=None,
                 event_cb=None):
        self.trunk = trunk
        self.root = os.path.abspath(root or ".")
        self.repo = repo or detect_repo(self.root)
        self.client = client or GitHubClient(
            token=token, repo=self.repo)
        self.event_cb = event_cb

    def _emit(self, event, data):
        if callable(self.event_cb):
            try:
                self.event_cb(event, data)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "pr flow event")

    @staticmethod
    def ci_feedback(result):
        """把 CI 结果整理成可回灌给 CodeAgent 的 `previous_error`。"""
        ci = (result or {}).get("ci") or {}
        names = "\n".join("- " + str(n) for n in ci.get("checks") or [])
        return "CI 状态: %s\n%s" % (ci.get("state") or "unknown", names)

    def run(self, files, *, title, body="", branch="", wait_ci=True,
            merge=False, timeout=900):
        if not self.repo:
            return {"ok": False, "error": "无法识别 GitHub 仓库（origin）"}
        branch = branch or "x6/code-%d" % int(time.time())
        gate = authorize_push(self.trunk, self.repo, branch, files)
        if not gate.get("allow"):
            return {"ok": False, "error": gate.get("reason"),
                    "permission": gate}
        self._emit("pr_start", {"step": "推送分支 " + branch})
        try:
            base = self.client.default_branch()
            committed = self.client.commit_files(
                branch, files, title, base=base)
            self._emit("pr_commit", {"step": "已提交 %d 个文件" % len(files),
                                     "commit": committed.get("commit")})
            pr = self.client.create_pr(branch, base, title, body)
            self._emit("pr_created", {"step": "已创建 PR #%s" % pr.get("number"),
                                      "url": pr.get("url")})
            result = {"ok": True, "branch": branch, "commit": committed,
                      "pr": pr}
            if wait_ci:
                ci = self.client.wait_ci(pr.get("number"), timeout=timeout)
                result["ci"] = ci
                self._emit("pr_ci", {"step": "CI: " + str(ci.get("state"))})
                if ci.get("state") != "success":
                    result["ok"] = False
                    result["error"] = "CI 未通过: " + str(ci.get("state"))
                    return result
            if merge:
                merged = self.client.merge_pr(pr.get("number"))
                result["merge"] = merged
                self._emit("pr_merged", {"step": "合并结果: %s" % merged.get("ok")})
                if not merged.get("ok"):
                    result["ok"] = False
                    result["error"] = merged.get("message") or "合并失败"
            return result
        except GitHubError as e:
            self._emit("pr_failed", {"step": "PR 失败", "error": str(e)[:300]})
            return {"ok": False, "error": str(e)}
