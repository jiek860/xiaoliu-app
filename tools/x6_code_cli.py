# -*- coding: utf-8 -*-
"""x6 无头代码 Agent CLI —— 只生成 patch，不落盘、不跑测试、不碰 GUI。

用途
----
SWE-bench 这类公开评测只接受 `model_patch`（git diff），不接受截图或
GUI 操作。这个入口把 `CodeAgent` 包成命令行：
    仓库 + 任务描述 -> patch JSON + git diff

它不修改目标仓库，也不会写 trace 到目标仓库，方便在评测容器里反复跑。

用法
----
    py -3 tools\\x6_code_cli.py --check
    py -3 tools\\x6_code_cli.py --repo <仓库> --task "修复登录超时" --out result.json
    py -3 tools\\x6_code_cli.py --repo <仓库> --task-file task.txt --instance-id django__django-12345
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

X6_ROOT = Path(__file__).resolve().parent.parent
if str(X6_ROOT) not in sys.path:
    sys.path.insert(0, str(X6_ROOT))


class HeadlessTrunk:
    """CodeAgent 需要的最小运行上下文：配置、LLM、仓库根。"""

    def __init__(self, base, config=None, llm=None, allow_headless_agent=False):
        self.base = str(base)
        self.config = dict(config or {})
        self.modules = {"llm": llm} if llm else {}
        self.allow_headless_agent = bool(allow_headless_agent)
        self.confirm_cb = None

    def _log(self, *_args, **_kwargs):
        return None

    def save_config(self):
        return None

    def rule(self, *_args, default=None, **_kwargs):
        return default


def _model_info(llm):
    cfg = getattr(llm, "config", {}) or {}
    return {
        "mode": str(cfg.get("model_mode") or "本地路由"),
        "provider": str(cfg.get("cloud_provider") or ""),
        "cloud_model": str(cfg.get("cloud_model") or ""),
        "local_model": str(cfg.get("local_model") or ""),
    }


def _is_git_repo(path):
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def check(repo=None, config_path=None):
    """环境自检：缺什么直接说，不实例化模型、不发网络请求。"""
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    add("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    git = shutil.which("git")
    add("git", bool(git), git or "未安装 git")

    try:
        from core.code_agent import CodeAgent  # noqa: F401
        from core.llm_client import LLMClient  # noqa: F401
        add("核心模块", True, "core.code_agent / core.llm_client")
    except Exception as exc:
        add("核心模块", False, str(exc)[:200])

    cfg_file = Path(config_path or (X6_ROOT / "data" / "config.json"))
    add("配置文件", cfg_file.is_file(), str(cfg_file))
    if cfg_file.is_file():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
            add("模型配置", True, "模式=%s / provider=%s / 模型=%s"
                % (cfg.get("model_mode") or "本地路由",
                   cfg.get("cloud_provider") or "-",
                   cfg.get("cloud_model") or cfg.get("local_model") or "-"))
        except Exception as exc:
            add("模型配置", False, "配置不是合法 JSON: %s" % str(exc)[:160])

    if repo:
        path = Path(repo)
        add("仓库目录", path.is_dir(), str(path))
        git_ok = path.is_dir() and _is_git_repo(path)
        add("Git 仓库", git_ok,
            "是" if git_ok else "SWE-bench 需要 git checkout")

    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def print_check(result):
    print("x6 无头代码 CLI 环境检查")
    for item in result.get("checks") or []:
        mark = "✅" if item.get("ok") else "❌"
        print("  %s %s：%s" % (mark, item.get("name"), item.get("detail")))
    if result.get("ok"):
        print("结论：可以运行")
    else:
        failed = [x["name"] for x in result.get("checks") or [] if not x.get("ok")]
        print("结论：缺少 %d 项（%s）" % (len(failed), "、".join(failed)))


def _git_diff(root, patch):
    """把结构化 patch 转成 `git apply` 能吃的 diff。"""
    from core.patch_engine import unified_diff

    root = os.path.abspath(root)
    parts = []
    for fp in patch.get("files") or []:
        rel = str(fp.get("path") or "").replace("\\", "/").lstrip("/")
        op = str(fp.get("op") or "update").lower()
        new_rel = str(fp.get("new_path") or fp.get("to") or "") \
            .replace("\\", "/").lstrip("/")
        target = new_rel or rel
        header = "diff --git a/%s b/%s\n" % (rel, target)
        exists = os.path.isfile(os.path.join(root, rel.replace("/", os.sep)))
        if op in ("create", "write") and not exists:
            header += "new file mode 100644\n"
        elif op == "delete":
            header += "deleted file mode 100644\n"
        elif op == "rename":
            header += ("similarity index 100%%\nrename from %s\nrename to %s\n"
                       % (rel, new_rel))
        body = unified_diff(root, {"files": [fp]})
        parts.append(header + body)
    return "".join(parts)


def generate(repo, task, *, llm=None, max_rounds=6, two_role=None,
             instance_id="", verbose=False):
    """生成 patch；不落盘、不运行测试。

    返回 dict，包含 `model_patch`（git diff）与 `patch`（结构化补丁）。
    失败时抛异常，由 CLI 统一转成 `ok:false`。
    """
    from core.code_agent import CodeAgent
    from core.patch_engine import PatchError, dry_run_patch

    repo = os.path.abspath(repo)
    if not os.path.isdir(repo):
        raise ValueError("仓库不存在: " + repo)
    task = str(task or "").strip()
    if not task:
        raise ValueError("任务描述为空")

    if llm is None:
        from core.llm_client import LLMClient
        llm = LLMClient(trunk=None, defer_warmup=True)

    rounds = max(1, min(15, int(max_rounds or 6)))
    trunk = HeadlessTrunk(
        base=X6_ROOT,
        config={"code_agent": {
            "two_role": True if two_role is None else bool(two_role),
        }},
        llm=llm,
    )

    def _event(name, data):
        if verbose:
            print("[event] %s %s" % (name, (data or {}).get("step", "")),
                  file=sys.stderr)

    agent = CodeAgent(trunk, root=repo, event_cb=_event)
    # 评测仓库不该出现 x6 自己的 trace 文件。
    agent._append_trace = lambda payload: None

    started = time.time()
    context = agent.build_context(task)
    patch = agent.propose_patch(
        task, context, max_tool_rounds=rounds, two_role=two_role)
    if not isinstance(patch, dict) or not patch.get("files"):
        raise PatchError("模型返回了空 patch")

    dry = dry_run_patch(repo, patch)
    if not dry.get("ok"):
        raise PatchError("补丁预演失败: " + "；".join(
            str(x) for x in (dry.get("errors") or [])))

    diff = _git_diff(repo, patch)
    if not diff.strip():
        raise PatchError("补丁没有产生任何 diff")

    return {
        "ok": True,
        "instance_id": str(instance_id or ""),
        "repo": repo,
        "task_hash": hashlib.sha1(task.encode("utf-8", "replace")).hexdigest()[:16],
        "version": _version(),
        "model": _model_info(llm),
        "max_rounds": rounds,
        "two_role": True if two_role is None else bool(two_role),
        "context_files": list(context.get("files") or []),
        "patch": patch,
        "model_patch": diff,
        "elapsed": round(time.time() - started, 2),
    }


def _version():
    try:
        from core.version import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def _load_task(args):
    if args.task_file:
        return Path(args.task_file).read_text(encoding="utf-8-sig").strip()
    return str(args.task or "").strip()


def _write_json(path, data):
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="x6 无头代码 Agent（只生成 patch）")
    parser.add_argument("--check", action="store_true", help="环境自检")
    parser.add_argument("--repo", help="目标仓库")
    parser.add_argument("--task", help="任务描述")
    parser.add_argument("--task-file", help="从文件读取任务描述")
    parser.add_argument("--out", help="结果 JSON 输出路径")
    parser.add_argument("--instance-id", default="", help="评测实例 id")
    parser.add_argument("--max-rounds", type=int, default=6,
                        help="模型探索/生成工具轮数（1~15，默认 6）")
    parser.add_argument("--single-role", action="store_true",
                        help="关闭双角色，使用单角色循环")
    parser.add_argument("--two-role", action="store_true",
                        help="强制双角色（探索 Agent + 修改 Agent）")
    parser.add_argument("--verbose", action="store_true", help="事件打印到 stderr")
    args = parser.parse_args(argv)

    if args.single_role and args.two_role:
        parser.error("--single-role 与 --two-role 不能同时使用")

    if args.check:
        result = check(args.repo)
        print_check(result)
        return 0 if result["ok"] else 1

    if not args.repo:
        parser.error("需要 --repo（或用 --check 只做环境自检）")
    task = _load_task(args)
    if not task:
        parser.error("需要 --task 或 --task-file")

    two_role = None
    if args.single_role:
        two_role = False
    elif args.two_role:
        two_role = True

    try:
        result = generate(
            args.repo, task, max_rounds=args.max_rounds, two_role=two_role,
            instance_id=args.instance_id, verbose=args.verbose)
    except Exception as exc:
        result = {
            "ok": False,
            "instance_id": str(args.instance_id or ""),
            "repo": os.path.abspath(args.repo),
            "error": str(exc)[:4000],
            "model_patch": "",
            "version": _version(),
        }

    if args.out:
        _write_json(args.out, result)
        if result.get("ok"):
            diff_len = len(result.get("model_patch") or "")
            print("✅ 已生成补丁：%d 个文件 / %d 字符 / %.2fs -> %s"
                  % (len(result.get("patch", {}).get("files") or []),
                     diff_len, result.get("elapsed", 0), args.out))
        else:
            print("❌ 生成失败：%s" % result.get("error"))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    from _console import use_utf8_console

    use_utf8_console()
    sys.exit(main())
