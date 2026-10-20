# -*- coding: utf-8 -*-
"""固定评测集运行器。

默认只跑无需模型/网络的本地回归；加 --with-model 才跑真实聊天用例。
"""
import argparse
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _cases():
    p = os.path.join(BASE, "tests", "eval", "cases.json")
    return json.load(open(p, encoding="utf-8"))


def _run_local(case):
    kind = case.get("kind")
    if kind == "path_safety":
        from core.path_safety import safe_join
        return bool(safe_join(case["root"], "ok.txt")) and \
            safe_join(case["root"], "../evil.txt") is None
    if kind == "net_guard":
        from core.net_guard import NetGuard
        ng = NetGuard(None)
        d = ng.check(case["url"], module="eval", purpose=case.get("purpose", "network"))
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
        return w.id and os.path.isdir(w.root)
    if kind == "parser":
        from core.document_parser import parse, chunk_text
        r = parse(case["path"])
        return r.get("ok") and len(chunk_text(r.get("text", ""))) >= 1
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-model", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "data", "eval_result.json"))
    args = ap.parse_args()
    cases = _cases()
    results = []
    for c in cases:
        if c.get("kind") == "model" and not args.with_model:
            continue
        t0 = time.time()
        try:
            ok = _run_local(c)
            err = ""
        except Exception as e:
            ok, err = False, str(e)[:160]
        results.append({"id": c.get("id"), "ok": bool(ok),
                        "elapsed": round(time.time() - t0, 3),
                        "error": err})
    passed = sum(1 for r in results if r["ok"])
    out = {"total": len(results), "passed": passed,
           "rate": round(passed / max(1, len(results)), 3),
           "results": results}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
