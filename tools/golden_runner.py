# -*- coding: utf-8 -*-
"""Golden Set 离线评测运行器（第 1 批：评测标尺）。

为什么要有它
------------
"聊天更拟人 / AI 写代码更准"这类目标，仅凭手感无法判断有没有变好。
这里用**完全离线**的确定性用例给出分数：不调模型、不联网、不碰 Qt，
因此在 CI 和本地 `pytest` 里都能稳定复现。

两类指标
--------
* 聊天：记忆命中率（检索召回）、引用准确率（结果带来源）、
  指代消解准确率、回复风格通过率；
* 代码：代码一次通过率（patch 应用 → 跑 fixture 自带 check.py）。

用法
----
    py -3 tools/golden_runner.py                 # 跑聊天 + 代码，打印分数
    py -3 tools/golden_runner.py --domain chat
    py -3 tools/golden_runner.py --json          # 机器可读
    py -3 tools/golden_runner.py --update-baseline   # 把当前分数写成基线

门禁（tests/test_golden_*.py）读 baseline.json：分数不得低于基线 - 容差。
新增用例后分数下降是**有意暴露的差距**，当批修好后再 `--update-baseline`。
"""
from __future__ import annotations

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
sys.path.insert(0, os.path.join(BASE, "tools"))

GOLDEN_DIR = os.path.join(BASE, "tests", "golden")
BASELINE_PATH = os.path.join(GOLDEN_DIR, "baseline.json")
FILES = {"chat": "chat_cases.json", "code": "code_cases.json"}
DOMAINS = ("chat", "code")
TOLERANCE = 0.02          # 允许的分数抖动（用例改动的正常波动）


def load_cases(domain):
    path = os.path.join(GOLDEN_DIR, FILES[domain])
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------- 聊天用例

def _score_retrieval(case):
    """记忆/知识库检索：命中期望片段 + 来源可追溯。"""
    from core.retrieval import HybridRetriever

    tmp = tempfile.mkdtemp(prefix="x6_golden_ret_")
    try:
        retriever = HybridRetriever(base=tmp)
        retriever.add_many(case.get("corpus") or [])
        hits = retriever.search(case.get("query", ""),
                                top_k=int(case.get("top_k", 3)))
        texts = [str(h.get("text", "")) for h in hits]
        sources = [str(h.get("source", "")) for h in hits]
        expect = case.get("expect") or {}
        issues = []
        if expect.get("empty"):
            if hits:
                issues.append("不该命中却召回了 %d 条" % len(hits))
        else:
            joined = "\n".join(texts)
            for word in expect.get("must_include") or []:
                if word not in joined:
                    issues.append("未召回：%s" % word)
            want_src = str(expect.get("source") or "")
            if want_src and want_src not in sources:
                issues.append("来源不对：期望 %s，实际 %s"
                              % (want_src, "、".join(sources) or "无"))
        return {"ok": not issues, "issues": issues,
                "hits": len(hits),
                "cited": sum(1 for s in sources if s)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _score_referent(case):
    """指代消解：该补全就补全，没依据时不编造。"""
    from core.chat import referent

    got = referent.resolve(case.get("input", ""),
                          case.get("messages") or [])
    expect = case.get("expect") or {}
    issues = []
    if "changed" in expect and bool(got.get("changed")) != bool(expect["changed"]):
        issues.append("changed 期望 %s，实际 %s"
                      % (expect["changed"], got.get("changed")))
    want = str(expect.get("topic_contains") or "")
    if want and want not in str(got.get("topic") or "") \
            and want not in str(got.get("text") or ""):
        issues.append("话题未补全到「%s」（实际：%s）"
                      % (want, got.get("topic") or got.get("text")))
    return {"ok": not issues, "issues": issues}


def _score_reply(case):
    """回复风格：用固定答案验证风格口径（长度 / 禁语 / 要点）。"""
    import eval_metrics

    result = eval_metrics.eval_chat(case.get("answer", ""),
                                    case.get("expect") or {})
    return {"ok": bool(result.get("ok")), "issues": list(result.get("issues") or []),
            "hits": 0, "cited": 0}


_CHAT_SCORERS = {
    "retrieval": _score_retrieval,
    "referent": _score_referent,
    "reply": _score_reply,
}


def score_chat_case(case):
    kind = str(case.get("kind") or "retrieval")
    scorer = _CHAT_SCORERS.get(kind)
    if scorer is None:
        return {"id": case.get("id"), "ok": False, "kind": kind,
                "issues": ["未知用例类型: " + kind], "hits": 0, "cited": 0}
    try:
        row = scorer(case)
    except Exception as e:
        row = {"ok": False, "issues": ["执行异常: %s" % str(e)[:120]],
               "hits": 0, "cited": 0}
    row.update({"id": case.get("id"), "kind": kind,
                "desc": case.get("desc", "")})
    return row


# ---------------------------------------------------------------- 代码用例

def _copy_fixture(src, dst):
    def ignore(_d, names):
        return [n for n in names if n == "__pycache__"]
    shutil.copytree(src, dst, ignore=ignore)


def score_code_case(case):
    """把 fixture 拷到临时目录 → 应用 patch → 跑 check.py。"""
    from core.patch_engine import apply_patch

    fixture = os.path.join(BASE, case.get("fixture", ""))
    if not os.path.isdir(fixture):
        return {"id": case.get("id"), "ok": False,
                "issues": ["fixture 不存在: " + case.get("fixture", "")]}
    tmp = tempfile.mkdtemp(prefix="x6_golden_code_")
    work = os.path.join(tmp, os.path.basename(fixture.rstrip("/")))
    try:
        _copy_fixture(fixture, work)
        try:
            apply_patch(work, case.get("patch") or {})
        except Exception as e:
            return {"id": case.get("id"), "ok": False,
                    "issues": ["patch 应用失败: %s" % str(e)[:160]]}
        check = case.get("check") or "check.py"
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                [sys.executable, check], cwd=work, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=60,
                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return {"id": case.get("id"), "ok": False, "issues": ["check.py 超时"]}
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0 and "ok" in out
        issues = [] if ok else ["check.py 未通过（返回码 %d）：%s"
                                % (proc.returncode, out.strip()[:160])]
        return {"id": case.get("id"), "ok": ok, "issues": issues}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 汇总

def _rate(passed, total):
    return round(float(passed) / float(total), 4) if total else 0.0


def run_domain(domain):
    cases = load_cases(domain)
    scorer = score_chat_case if domain == "chat" else score_code_case
    rows = [scorer(c) for c in cases]
    total = len(rows)
    passed = sum(1 for r in rows if r.get("ok"))
    metrics = {"pass_rate": _rate(passed, total)}
    if domain == "chat":
        by_kind = {"retrieval": [0, 0], "referent": [0, 0], "reply": [0, 0]}
        hits = cited = 0
        for row in rows:
            bucket = by_kind.setdefault(row.get("kind"), [0, 0])
            bucket[0] += 1
            if row.get("ok"):
                bucket[1] += 1
            hits += int(row.get("hits") or 0)
            cited += int(row.get("cited") or 0)
        metrics["memory_hit_rate"] = _rate(by_kind["retrieval"][1],
                                           by_kind["retrieval"][0])
        metrics["referent_accuracy"] = _rate(by_kind["referent"][1],
                                             by_kind["referent"][0])
        metrics["style_pass_rate"] = _rate(by_kind["reply"][1], by_kind["reply"][0])
        metrics["citation_accuracy"] = _rate(cited, hits)
    else:
        metrics["code_pass_rate"] = metrics["pass_rate"]
    return {"domain": domain, "total": total, "passed": passed,
            "metrics": metrics, "cases": rows}


def run_all(domains=DOMAINS):
    return {d: run_domain(d) for d in domains}


def load_baseline():
    try:
        with open(BASELINE_PATH, encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_baseline(result):
    payload = {"updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    for domain, row in result.items():
        payload[domain] = {"total": row["total"], "passed": row["passed"],
                           "metrics": row["metrics"]}
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    with open(BASELINE_PATH, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
    return BASELINE_PATH


def regressions(domain, result, baseline=None, tolerance=TOLERANCE):
    """返回相对基线下降的指标列表（空列表 = 通过）。"""
    baseline = load_baseline() if baseline is None else baseline
    base = (baseline or {}).get(domain) or {}
    if not base:
        return []
    out = []
    base_metrics = base.get("metrics") or {}
    for key, value in (result.get("metrics") or {}).items():
        old = base_metrics.get(key)
        if old is None:
            continue
        if float(value) + float(tolerance) < float(old):
            out.append("%s 从 %.4f 降到 %.4f" % (key, float(old), float(value)))
    return out


# ---------------------------------------------------------------- 命令行

def _print_human(result):
    for domain, row in result.items():
        print("=" * 60)
        print("%s：%d/%d 通过（pass_rate=%.4f）"
              % (domain, row["passed"], row["total"],
                 row["metrics"].get("pass_rate", 0.0)))
        for key, value in sorted(row["metrics"].items()):
            if key != "pass_rate":
                print("  %-20s %.4f" % (key, value))
        bad = [r for r in row["cases"] if not r.get("ok")]
        for r in bad:
            print("  [X] %s %s" % (r.get("id"), "；".join(r.get("issues") or [])))
    print("=" * 60)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Golden Set 离线评测")
    ap.add_argument("--domain", default="all", choices=("all",) + DOMAINS)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--update-baseline", action="store_true",
                    help="把当前分数写成基线")
    args = ap.parse_args(argv)
    domains = DOMAINS if args.domain == "all" else (args.domain,)
    result = run_all(domains)
    if args.update_baseline:
        merged = load_baseline()
        for domain, row in result.items():
            merged[domain] = {"total": row["total"], "passed": row["passed"],
                              "metrics": row["metrics"]}
        merged["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        with open(BASELINE_PATH, "w", encoding="utf-8") as fp:
            json.dump(merged, fp, ensure_ascii=False, indent=2, sort_keys=True)
        print("基线已更新: %s" % os.path.relpath(BASELINE_PATH, BASE))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(result)
    failed = [d for d, row in result.items() if row["passed"] < row["total"]]
    if failed:
        print("未通过用例：%s（用例本身失败不代表回归，见 baseline 说明）"
              % "、".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
