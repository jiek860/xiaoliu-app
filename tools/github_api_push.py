# -*- coding: utf-8 -*-
"""固定化的 GitHub 发布脚本（走 api.github.com，不依赖 git push）。

为什么不用 git push
-------------------
本机直连 github.com:443 经常被 RST，但 api.github.com 稳定可用。
以前的发布流程是临时脚本，每次都要重写；这里把它固化成工具：

    py -3 tools/github_api_push.py --message-file msg.txt \\
        --pr-title "batch 6: 工程加固" --wait-ci --merge

特性
----
* 只走 HTTPS api.github.com（拒绝其它主机）；
* 按文件**原始行尾风格**上传：直接读二进制，不做换行转换；
* 内容没变的文件复用远端 blob（不重复上传）；
* 支持删除文件（tree entry sha=null）；
* token 来源：GITHUB_TOKEN / GH_TOKEN 环境变量，或 Windows 凭据管理器；
  **日志、异常、命令回显里永远不打印 token**；
* --dry-run 只打印计划，不发写请求。

常用参数
--------
    --branch NAME         目标分支（默认 x6/auto-<时间戳>）
    --base NAME           基分支（默认 main）
    --message-file PATH   提交说明文件（UTF-8）
    --pr-title TITLE      创建 PR 的标题；不填则不建 PR
    --pr-body TEXT        PR 说明
    --wait-ci             轮询 check-runs 直到完成
    --merge               合并 PR（默认 squash）
    --dry-run             只展示将要上传的文件
    --files A B           只上传指定文件（默认取 git status 的改动）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.github_pr import GitHubClient, GitHubError, detect_repo

# 这些是本地运行产物/工具缓存，永远不该进仓库
EXCLUDE_PREFIXES = (
    ".trae/", ".venv/", ".git/", "__pycache__/", "data/", "dist/", "build/",
    "optional_libs/", "node_modules/", "logs/", "backups/",
)
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp")
EXCLUDE_NAMES = {
    "coverage.json", "_cov_tmp.json", ".coverage", "perf_baseline.local.json",
}


# ------------------------------------------------------------------ token
def _redact(text, token=""):
    text = str(text or "")
    if token:
        text = text.replace(token, "***")
    return text


def _win_credential_token(target_names=("git:https://github.com",
                                      "github.com")):
    """从 Windows 凭据管理器读取通用凭据（不落明文文件）。"""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes as wt

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wt.DWORD), ("Type", wt.DWORD),
                ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
                ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wt.LPWSTR), ("UserName", wt.LPWSTR),
            ]

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        CRED_TYPE_GENERIC = 1
        for target in target_names:
            ptr = ctypes.POINTER(CREDENTIAL)()
            ok = advapi.CredReadW(target, CRED_TYPE_GENERIC, 0,
                                  ctypes.byref(ptr))
            if not ok:
                continue
            try:
                cred = ptr.contents
                size = int(cred.CredentialBlobSize or 0)
                if size <= 0:
                    continue
                raw = ctypes.string_at(cred.CredentialBlob, size)
                for enc in ("utf-16-le", "utf-8", "latin-1"):
                    try:
                        value = raw.decode(enc).strip("\x00").strip()
                        if value:
                            return value
                    except UnicodeDecodeError:
                        continue
            finally:
                advapi.CredFree(ptr)
    except Exception:
        return ""
    return ""


def resolve_token():
    """环境变量优先，其次 Windows 凭据管理器，最后 git credential fill。"""
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "X6_GITHUB_TOKEN"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    value = _win_credential_token()
    if value:
        return value
    # git credential fill 在 Windows 上通常就是 manager-core（凭据管理器）
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (proc.stdout or "").splitlines():
            if line.startswith("password="):
                return line[len("password="):].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


# ------------------------------------------------------------------ 文件
def is_excluded(path):
    p = str(path or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p in EXCLUDE_NAMES:
        return True
    if p.endswith("/"):
        p = p.rstrip("/")
    for pre in EXCLUDE_PREFIXES:
        if p == pre.rstrip("/") or p.startswith(pre):
            return True
    return p.endswith(EXCLUDE_SUFFIXES)


def collect_changes(root, only=None):
    """返回 [(path, action)]；action = 'put' | 'delete'。

    使用 `git status --porcelain -z`，原样保留路径中的空格/中文。
    """
    only = [str(x).replace("\\", "/") for x in (only or [])]
    if only:
        out = []
        for rel in only:
            full = os.path.join(root, rel)
            out.append((rel, "put" if os.path.isfile(full) else "delete"))
        return [(p, a) for p, a in out if not is_excluded(p)]
    proc = subprocess.run(
        ["git", "status", "--porcelain", "-z"], cwd=root,
        capture_output=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    raw = proc.stdout or b""
    items = raw.split(b"\x00")
    changes, i = [], 0
    while i < len(items):
        rec = items[i]
        i += 1
        if not rec:
            continue
        text = rec.decode("utf-8", "replace")
        status, path = text[:2], text[3:]
        if status and status[0] in ("R", "C"):
            # -z 格式：新路径在本记录，旧路径在下一记录
            old = items[i].decode("utf-8", "replace") if i < len(items) else ""
            i += 1
            if old and not is_excluded(old):
                changes.append((old.replace("\\", "/"), "delete"))
            if not is_excluded(path):
                changes.append((path.replace("\\", "/"), "put"))
            continue
        if is_excluded(path):
            continue
        deleted = ("D" in status) or status == "AD"
        full = os.path.join(root, path.replace("/", os.sep))
        if not deleted and not os.path.isfile(full):
            continue          # 未跟踪目录 / 特殊文件不参与提交
        changes.append((path.replace("\\", "/"), "delete" if deleted else "put"))
    # 去重，删除优先放在前面
    seen, final = set(), []
    for path, action in changes:
        key = (path, action)
        if key in seen:
            continue
        seen.add(key)
        final.append((path, action))
    return final


def read_bytes(root, rel):
    with open(os.path.join(root, rel), "rb") as f:
        return f.read()


def line_ending_of(data):
    """判断文件原始行尾风格（只用于报告，上传始终用原始字节）。"""
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    if crlf and lf:
        return "mixed"
    return "crlf" if crlf else "lf"


def blob_sha(data):
    """git blob sha1 —— 和远端 tree 里的 sha 可直接比较。"""
    head = b"blob %d\x00" % len(data)
    return hashlib.sha1(head + data).hexdigest()


# ------------------------------------------------------------------ 上传
def remote_tree(client, tree_sha):
    data = client._request(
        "GET", "/repos/%s/git/trees/%s?recursive=1" % (client.repo, tree_sha))
    out = {}
    for item in data.get("tree") or []:
        if item.get("type") == "blob":
            out[str(item.get("path"))] = str(item.get("sha") or "")
    return out


def commit_worktree(client, files, message, base):
    """把工作区文件提交到新分支；内容未变的复用 blob。"""
    base_sha = client.ref_sha(base)
    if not base_sha:
        raise GitHubError("找不到基分支: " + base)
    base_tree = client.commit_tree(base_sha)
    remote = remote_tree(client, base_tree)

    entries, uploaded, reused, deleted = [], [], [], []
    for rel, action in files:
        if action == "delete":
            entries.append({"path": rel, "mode": "100644", "type": "blob",
                            "sha": None})
            deleted.append(rel)
            continue
        data = read_bytes(BASE_DIR, rel)
        sha = blob_sha(data)
        if remote.get(rel) == sha:
            reused.append(rel)
            continue
        blob = client._request(
            "POST", "/repos/%s/git/blobs" % client.repo,
            {"content": base64.b64encode(data).decode("ascii"),
             "encoding": "base64"})
        entries.append({"path": rel, "mode": "100644", "type": "blob",
                        "sha": blob.get("sha")})
        uploaded.append("%s (%s)" % (rel, line_ending_of(data)))

    if not entries:
        return {"ok": True, "changed": False, "base": base,
                "reused": reused, "deleted": [], "uploaded": []}

    tree = client._request(
        "POST", "/repos/%s/git/trees" % client.repo,
        {"base_tree": base_tree, "tree": entries})
    commit = client._request(
        "POST", "/repos/%s/git/commits" % client.repo,
        {"message": message, "tree": tree.get("sha"), "parents": [base_sha]})
    sha = commit.get("sha")
    if client.ref_sha(client.branch):
        client._request("PATCH", "/repos/%s/git/refs/heads/%s" % (
            client.repo, client.branch), {"sha": sha, "force": False})
    else:
        client.create_branch(client.branch, sha)
    return {"ok": True, "changed": True, "commit": sha, "base": base,
            "uploaded": uploaded, "reused": reused, "deleted": deleted}


def wait_ci_for_commit(client, sha, timeout=1800, interval=20):
    """对指定 commit 轮询 check-runs（不依赖 PR 是否已建）。"""
    deadline = time.time() + max(60, int(timeout))
    last = {"state": "pending", "checks": []}
    while time.time() < deadline:
        try:
            data = client._request(
                "GET", "/repos/%s/commits/%s/check-runs" % (client.repo, sha))
        except GitHubError as e:
            return {"state": "error", "checks": [], "error": str(e)[:200]}
        runs = data.get("check_runs") or []
        names, pending, failed = [], False, False
        for run in runs:
            names.append(str(run.get("name") or ""))
            if str(run.get("status") or "") != "completed":
                pending = True
            elif str(run.get("conclusion") or "") in (
                    "failure", "cancelled", "timed_out", "action_required"):
                failed = True
        last = {"state": ("failure" if failed else
                          "pending" if pending else "success"),
                "checks": names}
        if not runs:
            last = {"state": "pending", "checks": []}
        if last["state"] in ("success", "failure"):
            return last
        time.sleep(max(5, interval))
    return {"state": "timeout", "checks": last.get("checks") or []}


def _find_open_pr(client, head):
    try:
        prs = client._request(
            "GET", "/repos/%s/pulls?state=open&head=%s:%s" % (
                client.repo, client.repo.split("/")[0], head))
    except GitHubError:
        return None
    for pr in prs or []:
        if str((pr.get("head") or {}).get("ref") or "") == head:
            return pr
    return None


# ------------------------------------------------------------------ CLI
def build_parser():
    ap = argparse.ArgumentParser(description="GitHub 发布（api.github.com）")
    ap.add_argument("--branch", default="",
                    help="目标分支（默认 x6/auto-<时间戳>）")
    ap.add_argument("--base", default="main", help="基分支（默认 main）")
    ap.add_argument("--repo", default="", help="owner/repo（默认读 origin）")
    ap.add_argument("--message-file", default="", help="提交说明文件")
    ap.add_argument("--message", default="", help="提交说明（与 file 二选一）")
    ap.add_argument("--pr-title", default="", help="创建 PR 的标题")
    ap.add_argument("--pr-body", default="", help="PR 说明")
    ap.add_argument("--files", nargs="*", default=None,
                    help="只上传这些文件（默认取 git status）")
    ap.add_argument("--wait-ci", action="store_true", help="等待 CI 完成")
    ap.add_argument("--ci-timeout", type=int, default=1800)
    ap.add_argument("--merge", action="store_true", help="CI 通过后合并 PR")
    ap.add_argument("--merge-method", default="squash",
                    choices=("squash", "merge", "rebase"))
    ap.add_argument("--pr", type=int, default=0,
                    help="已有 PR 编号（--merge 时用）")
    ap.add_argument("--dry-run", action="store_true")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = BASE_DIR
    token = resolve_token()
    if not token and not args.dry_run:
        print("[X] 找不到 GitHub token：设置 GITHUB_TOKEN，"
              "或先在 Windows 凭据管理器登录 GitHub")
        return 2
    repo = args.repo or detect_repo(root)
    if not repo:
        print("[X] 无法识别 GitHub 仓库（git remote origin）")
        return 2
    branch = args.branch or "x6/auto-%d" % int(time.time())
    message = args.message
    if args.message_file:
        message = open(args.message_file, encoding="utf-8").read().strip()
    message = message or "chore: 小6工程加固"

    files = collect_changes(root, args.files)
    if not files:
        print("没有需要上传的改动。")
        return 0
    print("仓库: %s | 基分支: %s | 目标分支: %s" % (repo, args.base, branch))
    print("改动 %d 个文件：" % len(files))
    for rel, action in files:
        if action == "delete":
            print("  - 删除 %s" % rel)
        else:
            data = read_bytes(root, rel)
            print("  + 更新 %s（%s，%d 字节）" % (
                rel, line_ending_of(data), len(data)))
    if args.dry_run:
        print("[dry-run] 未发送任何写请求。")
        return 0

    client = GitHubClient(token=token, repo=repo)
    client.branch = branch  # 供 commit_worktree 判断分支是否已存在
    try:
        result = commit_worktree(client, files, message, args.base)
    except GitHubError as e:
        print("[X] 提交失败: " + _redact(e, token))
        return 1
    if not result.get("changed"):
        print("远端内容已是最新，无需提交（复用 blob %d 个）。"
              % len(result.get("reused") or []))
        return 0
    print("已提交: %s" % result.get("commit"))
    print("  上传 %d 个，复用 %d 个，删除 %d 个" % (
        len(result.get("uploaded") or []), len(result.get("reused") or []),
        len(result.get("deleted") or [])))

    pr = None
    if args.pr_title:
        try:
            pr = client.create_pr(branch, args.base, args.pr_title,
                                  args.pr_body)
            print("已创建 PR #%s %s" % (pr.get("number"), pr.get("url")))
        except GitHubError as e:
            existing = _find_open_pr(client, branch)
            if existing:
                pr = {"number": existing.get("number"),
                      "url": existing.get("html_url")}
                print("复用已存在的 PR #%s" % pr["number"])
            else:
                print("[X] 创建 PR 失败: " + _redact(e, token))
                return 1
    elif args.pr:
        pr = {"number": args.pr, "url": ""}

    if args.wait_ci:
        ci = wait_ci_for_commit(client, result.get("commit"),
                                timeout=args.ci_timeout)
        print("CI 状态: %s" % ci.get("state"))
        for name in ci.get("checks") or []:
            print("  - " + name)
        if ci.get("state") != "success":
            print("[X] CI 未通过，停止合并。")
            return 1
    if args.merge:
        number = args.pr or (pr or {}).get("number") or 0
        if not number:
            print("[X] 没有 PR 编号，无法合并。")
            return 1
        merged = client.merge_pr(number, method=args.merge_method)
        print("合并: %s %s" % (merged.get("ok"), merged.get("sha") or ""))
        return 0 if merged.get("ok") else 1
    return 0


if __name__ == "__main__":
    try:
        from _console import use_utf8_console
        use_utf8_console()
    except ImportError:
        pass
    sys.exit(main())
