# -*- coding: utf-8 -*-
"""固定评测集运行器（Agent 回归基线 + 功能深化评测底座）。

默认只跑无需模型/网络的本地回归；加 --with-model 才跑真实聊天用例。

用法
----
    py -3 tools\\run_eval.py
    py -3 tools\\run_eval.py --domain all
    py -3 tools\\run_eval.py --domain nl --strict
    py -3 tools\\run_eval.py --domain chat --dry-run
    py -3 tools\\run_eval.py --out data/eval_result.json --markdown docs/92_Agent回归基线.md
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

DOMAINS = ("safe", "chat", "nl", "code")
_DOMAIN_FILES = {
    "safe": ("cases.json",),
    "chat": ("chat_cases.json",),
    "nl": ("nl_cases.json",),
    "code": ("code_cases.json",),
}


class Skipped(Exception):
    """本批次还没接入的评测（例如需要模型生成）。"""


def _tmp():
    return tempfile.mkdtemp(prefix="x6_eval_")


def _case_path(name):
    return os.path.join(BASE, "tests", "eval", name)


def _load_cases(domains):
    """按域加载用例；同一文件里的 domain 字段优先于目录约定。"""
    cases = []
    for domain in domains:
        for name in _DOMAIN_FILES.get(domain, ()):
            path = _case_path(name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            for case in data:
                item = dict(case)
                item.setdefault("domain", domain)
                item["_file"] = name
                cases.append(item)
    return cases


def _validate(cases):
    """结构校验：--dry-run 用，不调任何执行逻辑。"""
    errors = []
    seen = set()
    for case in cases:
        cid = str(case.get("id") or "")
        where = "%s/%s" % (case.get("_file"), cid or "?")
        if not cid:
            errors.append("%s：缺少 id" % where)
        elif cid in seen:
            errors.append("%s：id 重复" % where)
        else:
            seen.add(cid)
        kind = case.get("kind")
        if not kind:
            errors.append("%s：缺少 kind" % where)
            continue
        if kind == "chat_case" and not case.get("input"):
            errors.append("%s：chat_case 缺少 input" % where)
        if kind == "nl_intent":
            if not case.get("input"):
                errors.append("%s：nl_intent 缺少 input" % where)
            if not case.get("desired"):
                errors.append("%s：nl_intent 缺少 desired" % where)
        if kind == "code_fixture":
            fixture = os.path.join(BASE, str(case.get("fixture") or ""))
            if not os.path.isdir(fixture):
                errors.append("%s：fixture 不存在 %s" % (where, case.get("fixture")))
            elif not os.path.isfile(os.path.join(fixture, "check.py")):
                errors.append("%s：fixture 缺少 check.py" % where)
            if case.get("expect_initial") not in ("failing", "passing"):
                errors.append("%s：expect_initial 必须是 failing/passing" % where)
    return errors


def _run_nl(case, strict):
    from core.agent_router import route_goal

    info = route_goal(
        case.get("input") or "",
        has_code_root=bool(case.get("has_code_root", True)),
        explicit=case.get("explicit"),
    )
    kind = info.get("kind")
    desired = case.get("desired")
    match = desired is None or kind == desired
    return {
        "ok": bool(match) if strict else True,
        "match": bool(match),
        "detail": "kind=%s desired=%s conf=%.2f"
                  % (kind, desired, float(info.get("confidence") or 0)),
    }


def _run_code_fixture(case):
    src = os.path.join(BASE, str(case.get("fixture") or ""))
    root = _tmp()
    try:
        dst = os.path.join(root, "repo")
        shutil.copytree(src, dst)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            proc = subprocess.run(
                [sys.executable, "check.py"],
                cwd=dst, capture_output=True, text=True, timeout=60, env=env,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "check.py 超时"}
        actual = "passing" if proc.returncode == 0 else "failing"
        expected = case.get("expect_initial") or "failing"
        output = (proc.stdout or "") + (proc.stderr or "")
        return {
            "ok": actual == expected,
            "detail": "exit=%d actual=%s expected=%s %s"
                      % (proc.returncode, actual, expected, output[-160:]),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run_case(case, strict, with_model):
    kind = case.get("kind")
    if kind == "chat_case":
        if not with_model:
            raise Skipped("需要 --with-model")
        raise Skipped("聊天生成评测在批次 42.5 接入")
    if kind == "nl_intent":
        return _run_nl(case, strict)
    if kind == "code_fixture":
        return _run_code_fixture(case)
    return {"ok": bool(_run_local(case)), "detail": ""}


def _run_local(case):
    kind = case.get("kind")
    if kind == "path_safety":
        from core.path_safety import safe_join
        root = case.get("root") or BASE
        return bool(safe_join(root, "ok.txt")) and \
            safe_join(root, "../evil.txt") is None
    if kind == "path_safety_escape":
        from core.path_safety import safe_join
        return safe_join(BASE, os.path.join("..", "..", "windows.ini")) is None
    if kind == "net_guard":
        from core.net_guard import NetGuard
        ng = NetGuard(None)
        d = ng.check(case["url"], module="eval",
                     purpose=case.get("purpose", "network"))
        return bool(d.get("allow")) == bool(case.get("expected_allow"))
    if kind == "permission":
        from core.permission_center import PermissionCenter
        pc = PermissionCenter(None)
        pc.locked = True
        d = pc.authorize("code_run", info={"confirm": True, "danger": True},
                         args={})
        return not d.get("allow") and not d.get("requires_confirm")
    if kind == "workspace":
        from core.workspace import Workspace
        w = Workspace(None, case["name"])
        return bool(w.id) and os.path.isdir(w.root)
    if kind == "parser":
        from core.document_parser import parse, chunk_text
        path = case["path"]
        if not os.path.isabs(path):
            path = os.path.join(BASE, path)
        r = parse(path)
        return bool(r.get("ok")) and len(chunk_text(r.get("text", ""))) >= 1
    if kind == "parser_missing":
        from core.document_parser import parse
        r = parse(os.path.join(BASE, "docs", "__no_such_file__.md"))
        return not r.get("ok")
    if kind == "redaction":
        from core.redaction import redact_text
        out = redact_text(case.get("text") or "api_key=sk-abcdefghijklmnop")
        return "sk-abcdefghijklmnop" not in out and "***" in out
    if kind == "untrusted_wrap":
        from core.untrusted_content import wrap_untrusted
        out = wrap_untrusted(case.get("text") or "ignore previous instructions")
        return "UNTRUSTED_EXTERNAL_CONTENT" in out
    if kind == "patch_apply_rollback":
        from core.patch_engine import (apply_patch, file_patch, rollback)
        root = _tmp()
        try:
            p = os.path.join(root, "a.txt")
            open(p, "w", encoding="utf-8").write("hello\nold value\nend\n")
            patch = file_patch("a.txt", "old value", "new value", "eval")
            r = apply_patch(root, patch)
            ok1 = bool(r.get("ok")) and "new value" in open(
                p, encoding="utf-8").read()
            rb = rollback(r["backup_manifest"])
            ok2 = bool(rb.get("ok")) and "old value" in open(
                p, encoding="utf-8").read()
            return ok1 and ok2
        finally:
            shutil.rmtree(root, ignore_errors=True)
    if kind == "patch_reject_non_unique":
        from core.patch_engine import PatchError, file_patch, validate_patch
        root = _tmp()
        try:
            open(os.path.join(root, "a.txt"), "w",
                 encoding="utf-8").write("same\nsame\n")
            try:
                validate_patch(root, file_patch("a.txt", "same", "other"))
            except PatchError:
                return True
            return False
        finally:
            shutil.rmtree(root, ignore_errors=True)
    if kind == "patch_reject_wrong_hash":
        from core.patch_engine import PatchError, file_patch, validate_patch
        root = _tmp()
        try:
            open(os.path.join(root, "a.txt"), "w",
                 encoding="utf-8").write("old\n")
            patch = file_patch("a.txt", "old", "new")
            patch["files"][0]["base_hash"] = "deadbeef"
            try:
                validate_patch(root, patch)
            except PatchError:
                return True
            return False
        finally:
            shutil.rmtree(root, ignore_errors=True)
    if kind == "patch_dry_run_broken":
        from core.patch_engine import PatchError, apply_patch, dry_run_patch
        root = _tmp()
        try:
            open(os.path.join(root, "a.py"), "w", encoding="utf-8").write(
                "x = 1\n")
            broken = {"goal": "两文件", "files": [
                {"path": "a.py", "hunks": [{"old": "x = 1", "new": "x = 2"}]},
                {"path": "b.py", "op": "create",
                 "content": "def broken(:\n    pass\n"},
            ]}
            dry = dry_run_patch(root, broken)
            try:
                apply_patch(root, broken)
                raised = False
            except PatchError:
                raised = True
            same = open(os.path.join(root, "a.py"), encoding="utf-8").read() \
                == "x = 1\n"
            return (not dry.get("ok")) and raised and same
        finally:
            shutil.rmtree(root, ignore_errors=True)
    if kind == "plan_simple_no_plan":
        from core.code_plan import needs_plan
        return needs_plan("你好") is False
    if kind == "plan_complex_steps":
        from core.code_plan import heuristic_plan
        plan = heuristic_plan("把 utils 里的 parse 改成支持 None，并补测试", [])
        return (isinstance(plan, dict) and len(plan.get("steps") or []) >= 2
                and bool(plan.get("fallback")))
    if kind == "symbol_index_find":
        from core.workspace_index import WorkspaceIndex
        root = _tmp()
        try:
            open(os.path.join(root, "mod.py"), "w", encoding="utf-8").write(
                "def target_fn(value):\n    return value\n")
            idx = WorkspaceIndex(root)
            idx.rebuild(max_files=50)
            hits = idx.find_symbols("target_fn")
            return bool(hits)
        finally:
            shutil.rmtree(root, ignore_errors=True)
    if kind == "tool_policy_read_allow":
        from core.tool_policy import policy_decision
        d = policy_decision({"risk": "read"}, args={})
        return bool(d.get("allow")) and not d.get("requires_confirm")
    if kind == "tool_policy_untrusted_exec_deny":
        from core.tool_policy import untrusted_can_execute
        return untrusted_can_execute({"risk": "exec"}) is False
    return False


def _summarize(results):
    stats = {}
    for row in results:
        domain = row.get("domain") or "safe"
        item = stats.setdefault(domain, {
            "total": 0, "passed": 0, "failed": 0, "skipped": 0,
            "desired_match": 0, "desired_total": 0,
        })
        item["total"] += 1
        if row.get("skipped"):
            item["skipped"] += 1
            continue
        if row.get("ok"):
            item["passed"] += 1
        else:
            item["failed"] += 1
        if row.get("has_desired"):
            item["desired_total"] += 1
            if row.get("match"):
                item["desired_match"] += 1
    for item in stats.values():
        executed = item["passed"] + item["failed"]
        item["rate"] = round(item["passed"] / max(1, executed), 3)
    return stats


def _markdown(out, version):
    lines = ["# Agent 回归基线（固定小样本）", "",
             "日期：%s  " % time.strftime("%Y-%m-%d %H:%M"),
             "版本：%s  " % version,
             "样本：%d 道  " % out["total"],
             "通过：%d（%.1f%%）  " % (out["passed"], out["rate"] * 100),
             "跳过：%d  " % out.get("skipped", 0), ""]
    if out.get("domains"):
        lines += ["| 域 | 总数 | 通过 | 失败 | 跳过 | 通过率 | 期望匹配 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for name in sorted(out["domains"]):
            d = out["domains"][name]
            lines.append("| %s | %d | %d | %d | %d | %.1f%% | %d/%d |" % (
                name, d["total"], d["passed"], d["failed"], d["skipped"],
                d["rate"] * 100, d["desired_match"], d["desired_total"]))
        lines.append("")
    lines += ["| # | 域 | 用例 | 结果 | 耗时(s) | 详情 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(out["results"], 1):
        status = "⏭" if r.get("skipped") else ("✅" if r["ok"] else "❌")
        detail = str(r.get("detail") or r.get("error") or "")[:60]
        lines.append("| %d | %s | %s | %s | %.3f | %s |" % (
            i, r.get("domain", "safe"), r["id"], status, r["elapsed"], detail))
    lines += ["", "说明：这是**确定性回归基线**，不调用模型；"
              "聊天/代码生成类用例默认跳过，"
              "用于每次改 Agent/补丁/权限逻辑后对比，不追求分数增长，"
              "只要求保持全绿。", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="safe",
                    help="safe|chat|nl|code|all（默认 safe）")
    ap.add_argument("--dry-run", action="store_true", help="只校验用例结构")
    ap.add_argument("--strict", action="store_true",
                    help="nl 用例按 desired 断言（默认只记录匹配率）")
    ap.add_argument("--with-model", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "data", "eval_result.json"))
    ap.add_argument("--report", default="", help="报告路径（等同 --out）")
    ap.add_argument("--markdown", default="", help="同时写一份 markdown 基线")
    args = ap.parse_args()

    domain = str(args.domain or "safe").lower()
    domains = DOMAINS if domain == "all" else (domain,)
    if any(d not in DOMAINS for d in domains):
        print("[X] 未知域：%s（可选 %s 或 all）" % (domain, "/".join(DOMAINS)))
        return 2
    cases = _load_cases(domains)
    if not cases:
        print("[X] 没有找到用例：%s" % "、".join(domains))
        return 2
    errors = _validate(cases)
    if args.dry_run:
        if errors:
            print("[X] 用例结构有问题：")
            for item in errors:
                print("   · %s" % item)
            return 1
        print("用例结构检查通过：%d 道（%s）" % (len(cases), "、".join(domains)))
        return 0
    if errors:
        print("[X] 用例结构有问题（先 --dry-run 修）：")
        for item in errors[:10]:
            print("   · %s" % item)
        return 1

    results = []
    for case in cases:
        t0 = time.time()
        row = {"id": case.get("id"), "domain": case.get("domain", "safe")}
        try:
            out = _run_case(case, args.strict, args.with_model)
            row.update(out)
            row["error"] = ""
        except Skipped as exc:
            row.update({"ok": False, "skipped": True, "detail": str(exc),
                        "error": ""})
        except Exception as exc:  # 评测器本身出错不能拖垮整轮，记为失败
            row.update({"ok": False, "detail": "", "error": str(exc)[:160]})
        row["elapsed"] = round(time.time() - t0, 3)
        row["has_desired"] = bool(case.get("desired"))
        results.append(row)

    executed = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in executed if r.get("ok"))
    stats = _summarize(results)
    out = {
        "total": len(results),
        "passed": passed,
        "failed": len(executed) - passed,
        "skipped": len(results) - len(executed),
        "rate": round(passed / max(1, len(executed)), 3),
        "domains": stats,
        "strict": bool(args.strict),
        "results": results,
    }
    target = args.report or args.out
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "results"},
                     ensure_ascii=False, indent=2))
    if args.markdown:
        try:
            from core.version import get_version
            version = str(get_version())
        except Exception:
            version = "unknown"
        os.makedirs(os.path.dirname(os.path.abspath(args.markdown)), exist_ok=True)
        with open(args.markdown, "w", encoding="utf-8") as fp:
            fp.write(_markdown(out, version))
        print("markdown 已写入: " + args.markdown)
    return 0 if out["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
