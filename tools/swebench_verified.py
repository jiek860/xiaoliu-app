# -*- coding: utf-8 -*-
"""SWE-bench Verified 公开评测驱动（B7 试跑 10 题 / B11 正式 50 题）。

为什么用公开评测
----------------
自家 20 道题测出来的是"能跑"，不是"能修"。SWE-bench Verified 是 OpenAI
发布的 500 题人工复核子集：每题有真实仓库、base_commit、problem_statement、
FAIL_TO_PASS / PASS_TO_PASS 测试用例，别人能拿同样的题目复现同一个分数。

这个脚本只做三件事
------------------
    1. 把官方数据集里的实例整理成本机能跑的清单（--plan / --dataset）
    2. 逐题：clone@base_commit -> 调 x6 无头 CLI 生成 patch -> 写 predictions
    3. 交给官方 harness 判分（--run-harness，需要 Docker）

不做的事：不修改题库、不挑题重跑、不把"patch 为空"算成通过。

依赖（缺哪样会直说，不会假装跑过）
----------------------------------
    · git              clone / checkout base_commit
    · 数据集           datasets 或 huggingface-cli 下 SWE-bench_Verified
    · 模型 Key         云端 Key 或本地 Ollama（见 tools/x6_code_cli.py --check）
    · Docker           只有 --run-harness 判分需要

用法
----
    py -3 tools\\swebench_verified.py --check
    py -3 tools\\swebench_verified.py --plan --out data/swebench_pilot_plan.json
    py -3 tools\\swebench_verified.py --dataset data/swe_verified.jsonl \
        --limit 10 --workdir data/swe_work --out data/swebench_pilot.json
    py -3 tools\\swebench_verified.py --predictions data/swe_predictions.jsonl \
        --run-harness --run-id x6-pilot-1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

CLI = BASE / "tools" / "x6_code_cli.py"

# 试跑用的 10 题（覆盖 Django / SymPy / Sphinx / pytest / Matplotlib / astropy）。
# 具体实例必须存在于官方 Verified 子集里：脚本会把不在数据集里的 id 挑出来报错，
# 不会静默跳过（否则"少跑几题"会被看成"跑完了"）。
PILOT_IDS = [
    "django__django-10880",
    "django__django-11099",
    "django__django-11133",
    "sympy__sympy-20154",
    "sympy__sympy-20590",
    "sphinx-doc__sphinx-8721",
    "sphinx-doc__sphinx-11445",
    "pytest-dev__pytest-7490",
    "matplotlib__matplotlib-20676",
    "astropy__astropy-12907",
]

DATASET_HINT = (
    "数据集自查：\n"
    "  py -3 -c \"from datasets import load_dataset;"
    " ds=load_dataset('SWE-bench/SWE-bench_Verified', split='test');"
    " print(ds.num_rows)\"\n"
    "  # 或：huggingface-cli download SWE-bench/SWE-bench_Verified "
    "--repo-type dataset\n"
    "  # 然后导出成 jsonl（字段：instance_id/repo/base_commit/"
    "problem_statement/FAIL_TO_PASS/PASS_TO_PASS）"
)


# --------------------------------------------------------------- 数据与清单
def read_instances(path):
    """读数据集：支持 .jsonl / .json（list 或 {"instances": [...]}）。

    只保留评测必需的字段；缺字段的实例直接判为不可用（不猜）。
    """
    p = Path(path)
    if not p.is_file():
        raise SystemExit("数据集不存在：%s\n%s" % (p, DATASET_HINT))
    text = p.read_text(encoding="utf-8-sig")
    rows = []
    if p.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    else:
        data = json.loads(text)
        rows = data.get("instances", []) if isinstance(data, dict) else data
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "instance_id": str(r.get("instance_id") or ""),
            "repo": str(r.get("repo") or ""),
            "base_commit": str(r.get("base_commit") or ""),
            "problem_statement": str(r.get("problem_statement") or ""),
            "FAIL_TO_PASS": _as_list(r.get("FAIL_TO_PASS")),
            "PASS_TO_PASS": _as_list(r.get("PASS_TO_PASS")),
        })
    return out


def _as_list(v):
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        try:
            got = json.loads(v)
            return [str(x) for x in got] if isinstance(got, list) else [v]
        except Exception:
            return [v] if v else []
    return []


def pick_instances(instances, ids=None, limit=0):
    """按 id 顺序挑题；id 不在数据集里要报错（缺题不能当跑过）。"""
    by_id = {i["instance_id"]: i for i in instances}
    want = list(ids or PILOT_IDS)
    missing = [x for x in want if x not in by_id]
    if missing:
        raise SystemExit(
            "这些实例不在数据集里（可能 id 写错或数据集版本不同）：\n  %s\n%s"
            % ("\n  ".join(missing), DATASET_HINT))
    picked = [by_id[x] for x in want]
    if limit and limit > 0:
        picked = picked[:int(limit)]
    return picked


def plan(ids=None):
    """离线也能产出的清单：跑哪几题、每题的仓库与判分口径。"""
    return {
        "benchmark": "SWE-bench Verified",
        "model": "x6 CodeAgent（tools/x6_code_cli.py）",
        "ids": list(ids or PILOT_IDS),
        "count": len(ids or PILOT_IDS),
        "metric": "resolve_rate = 修好题数 / 总题数（官方 harness 口径）",
        "notes": [
            "patch 为空按未修好计，不重跑、不挑题",
            "每题单独 clone@base_commit，不共享工作区",
            "FAIL_TO_PASS 全绿且 PASS_TO_PASS 不回归才算 resolve",
        ],
        "dataset": DATASET_HINT,
    }


def sample_final(instances, count=50, seed=20261123):
    """B11 的正式 50 题取样：可复现（固定种子）、排除已试跑的 10 题。"""
    import random

    pool = sorted(i["instance_id"] for i in instances
                  if i["instance_id"] and i["instance_id"] not in PILOT_IDS)
    if len(pool) <= count:
        return pool
    return sorted(random.Random(int(seed)).sample(pool, int(count)))


# ------------------------------------------------------------------ 环境自检
def check(dataset=None, workdir=None):
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    add("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    git = shutil.which("git")
    add("git", bool(git), git or "未安装 git（clone/checkout 需要）")
    add("无头 CLI", CLI.is_file(), str(CLI))
    try:
        from tools import x6_code_cli
        r = x6_code_cli.check()
        bad = [c["name"] for c in r.get("checks") or [] if not c["ok"]]
        add("模型与核心模块", bool(r.get("ok")),
            "缺：" + "、".join(bad) if bad else "已就绪")
    except Exception as exc:
        add("模型与核心模块", False, str(exc)[:160])
    try:
        import swebench  # noqa: F401
        add("swebench", True, "可调官方 harness")
    except Exception:
        from core.error_text import install_cmd
        add("swebench", False, "未安装（判分需要）：\n    "
            + install_cmd("swebench", target=None))
    docker = shutil.which("docker")
    add("Docker", bool(docker), docker or "判分需要 Docker（生成 patch 不需要）")
    if dataset:
        add("数据集", Path(dataset).is_file(), str(dataset))
    else:
        add("数据集", False, "未指定 --dataset\n" + DATASET_HINT)
    if workdir:
        add("工作区", bool(Path(workdir).parent.exists())
            or Path(workdir).exists(), str(workdir))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def print_check(result):
    print("SWE-bench Verified 评测环境检查")
    for item in result.get("checks") or []:
        print("  %s %s：%s" % ("✅" if item.get("ok") else "❌",
                              item.get("name"), item.get("detail")))
    failed = [c["name"] for c in result.get("checks") or [] if not c["ok"]]
    print("结论：%s" % ("可以运行" if result.get("ok")
                     else "缺少 %d 项（%s）" % (len(failed), "、".join(failed))))


# ------------------------------------------------------------------ 逐题生成
def mirror_url(url, prefix=None):
    """把 GitHub 地址套上镜像前缀。

    实测（2026-10 这台机器）：github.com 的 TCP 能连上，但 git clone 直接被
    重置（Recv failure: Connection was reset）；gh-proxy.com / ghfast.top 可用。
    所以直连失败后自动重试镜像，而不是把"拉不下来"直接当失败。
    可用 X6_GIT_MIRROR 覆盖；设为空字符串则只用直连。
    """
    if prefix is None:
        prefix = os.environ.get("X6_GIT_MIRROR", "https://ghfast.top/")
    prefix = str(prefix or "").strip()
    if not prefix or not url.startswith("https://github.com/"):
        return url
    return prefix.rstrip("/") + "/" + url


def _git(args, timeout):
    return subprocess.run(["git"] + args, capture_output=True, text=True,
                          timeout=timeout)


def clone_at(repo, base_commit, dest, timeout=1800):
    """clone 并 checkout 到 base_commit；失败抛异常（不静默降级）。

    头条原则：**不把"没克隆成功"当成"这题模型没做出来"**。
    直连失败会再试一次镜像；两次都失败才抛，消息里带两次的 stderr。
    """
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = "https://github.com/%s.git" % repo
    targets = [url]
    mirrored = mirror_url(url)
    if mirrored != url:
        targets.append(mirrored)
    errors = []
    for target in targets:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            r = _git(["clone", "--filter=blob:none", "--no-checkout",
                      target, str(dest)], timeout)
        except subprocess.TimeoutExpired:
            errors.append("clone 超时: %s" % target)
            continue
        if r.returncode != 0:
            errors.append(str(r.stderr or "")[-400:])
            continue
        try:
            c = _git(["-C", str(dest), "checkout", base_commit], 600)
        except subprocess.TimeoutExpired:
            c = None
            errors.append("checkout 超时: %s" % base_commit)
        if c is not None and c.returncode == 0:
            return dest
        if c is not None:
            errors.append(str(c.stderr or "")[-400:])
    raise RuntimeError("仓库拉不下来（直连与镜像都失败）：" + " | ".join(errors)[-800:])


def generate_patch(inst, repo_dir, out_json, timeout=3600, max_rounds=6):
    """调无头 CLI 生成 patch，返回 (patch, error)。"""
    task_file = Path(out_json).with_suffix(".task.txt")
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(inst.get("problem_statement") or "", encoding="utf-8")
    cmd = [sys.executable, str(CLI), "--repo", str(repo_dir),
           "--task-file", str(task_file),
           "--instance-id", inst["instance_id"],
           "--max-rounds", str(max_rounds), "--out", str(out_json)]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", "生成超时（%ds）" % timeout
    elapsed = round(time.time() - started, 1)
    if not Path(out_json).is_file():
        return "", "CLI 没有输出结果文件：%s" % (proc.stderr or "")[-300:]
    try:
        data = json.loads(Path(out_json).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return "", "结果文件不是 JSON：%s" % str(exc)[:200]
    if not data.get("ok"):
        return "", str(data.get("error") or "生成失败")[:500]
    patch = str(data.get("model_patch") or "")
    if not patch.strip():
        return "", "patch 为空"
    data["elapsed_cli"] = elapsed
    return patch, ""


def run_predictions(instances, workdir, out_json, timeout=3600,
                    max_rounds=6, log=print):
    """逐题跑一遍，返回 (predictions 列表, 每题状态)。"""
    rows, records = [], []
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for inst in instances:
        iid = inst["instance_id"]
        rec = {"instance_id": iid, "repo": inst["repo"],
               "base_commit": inst["base_commit"], "status": ""}
        repo_dir = workdir / iid.replace("/", "_")
        out_one = workdir / ("%s.result.json" % iid.replace("/", "_"))
        try:
            clone_at(inst["repo"], inst["base_commit"], repo_dir)
        except Exception as exc:
            rec["status"] = "repo_error"
            rec["error"] = str(exc)[:300]
            records.append(rec)
            log("  ✗ %s：仓库拉不下来（%s）" % (iid, rec["error"][:80]))
            continue
        patch, err = generate_patch(inst, repo_dir, out_one,
                                    timeout=timeout, max_rounds=max_rounds)
        if patch:
            rec["status"] = "predicted"
            rec["patch_bytes"] = len(patch)
            rows.append({
                "instance_id": iid,
                "model_name_or_path": "x6-agent",
                "model_patch": patch,
            })
            log("  ✓ %s：patch %d 字符" % (iid, len(patch)))
        else:
            rec["status"] = "empty_patch" if err == "patch 为空" else "error"
            rec["error"] = err
            # 官方口径：没给 patch 就是没修好，仍然写进 predictions。
            rows.append({"instance_id": iid, "model_name_or_path": "x6-agent",
                         "model_patch": ""})
            log("  ✗ %s：%s" % (iid, err[:100]))
        records.append(rec)
    write_predictions(rows, out_json)
    return rows, records


def write_predictions(rows, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({
                "instance_id": r["instance_id"],
                "model_name_or_path": r["model_name_or_path"],
                "model_patch": r["model_patch"],
            }, ensure_ascii=False) + "\n")
    return p


def run_harness(predictions, run_id, timeout=7200):
    """调官方 harness 判分（需要 Docker + swebench）。"""
    cmd = [sys.executable, "-m", "swebench.harness.run_evaluation",
           "--predictions_path", str(predictions),
           "--max_workers", "4",
           "--run_id", str(run_id),
           "--dataset_name", "SWE-bench/SWE-bench_Verified",
           "--split", "test"]
    print(">>> " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    report = {"run_id": run_id, "cmd": cmd, "returncode": proc.returncode,
              "stdout": (proc.stdout or "")[-4000:],
              "stderr": (proc.stderr or "")[-2000:]}
    return report


# --------------------------------------------------------------------- 报告
def write_report(records, path, extra=None):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ok = [r for r in records if r.get("status") == "predicted"]
    lines = ["# SWE-bench Verified 试跑记录", "",
             "| 实例 | 状态 | 说明 |", "|---|---|---|"]
    for r in records:
        lines.append("| %s | %s | %s |"
                     % (r.get("instance_id"), r.get("status"),
                        (r.get("error") or "")[:80]))
    lines += ["", "生成成功 %d / %d 题。判分口径以官方 harness 输出为准。"
              % (len(ok), len(records)), ""]
    if extra:
        for k, v in extra.items():
            lines.append("- %s：%s" % (k, v))
            lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# --------------------------------------------------------------------- 入口
def main(argv=None):
    ap = argparse.ArgumentParser(description="SWE-bench Verified 评测驱动")
    ap.add_argument("--check", action="store_true", help="环境自检")
    ap.add_argument("--plan", action="store_true", help="只输出试跑清单")
    ap.add_argument("--final", action="store_true",
                    help="输出正式 50 题取样清单（需 --dataset）")
    ap.add_argument("--sample-count", type=int, default=50)
    ap.add_argument("--dataset", help="数据集 jsonl/json")
    ap.add_argument("--ids", help="逗号分隔的实例 id（默认 10 题试跑集）")
    ap.add_argument("--limit", type=int, default=0, help="最多跑几题")
    ap.add_argument("--workdir", default="data/swe_work", help="工作目录")
    ap.add_argument("--out", help="结果 JSON（predictions）")
    ap.add_argument("--report", help="Markdown 记录")
    ap.add_argument("--predictions", help="已有 predictions，直接判分")
    ap.add_argument("--run-harness", action="store_true", help="调官方 harness")
    ap.add_argument("--run-id", default="x6-pilot", help="判分 run_id")
    ap.add_argument("--max-rounds", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=3600, help="每题超时秒数")
    args = ap.parse_args(argv)

    if args.check:
        print_check(check(args.dataset, args.workdir))
        return 0

    if args.plan:
        ids = [x.strip() for x in (args.ids or "").split(",") if x.strip()]
        data = plan(ids or None)
        if args.out:
            _write_json(args.out, data)
            print("✅ 试跑清单：%d 题 -> %s" % (data["count"], args.out))
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if args.final:
        if not args.dataset:
            ap.error("--final 需要 --dataset（先看看有哪些实例）")
        instances = read_instances(args.dataset)
        ids = sample_final(instances, args.sample_count)
        data = {"benchmark": "SWE-bench Verified", "count": len(ids),
                "ids": ids, "seed": 20261123,
                "note": "固定种子 random.sample，已排除试跑 10 题；只跑一次，不挑题。"}
        if args.out:
            _write_json(args.out, data)
            print("✅ 正式取样 %d 题 -> %s" % (len(ids), args.out))
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if args.run_harness:
        if not args.predictions:
            ap.error("--run-harness 需要 --predictions")
        report = run_harness(args.predictions, args.run_id)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(
                "# SWE-bench 判分输出\n\n```\n%s\n```\n"
                % report.get("stdout", ""), encoding="utf-8")
        print(report.get("stdout", "") or report.get("stderr", ""))
        return 0 if report.get("returncode") == 0 else 1

    if not args.dataset:
        ap.error("需要 --dataset（或先用 --check 看缺什么）")
    instances = read_instances(args.dataset)
    if not instances:
        raise SystemExit("数据集是空的：%s" % args.dataset)
    ids = [x.strip() for x in (args.ids or "").split(",") if x.strip()]
    picked = pick_instances(instances, ids or None, args.limit)
    out = args.out or str(Path(args.workdir) / "predictions.jsonl")
    rows, records = run_predictions(picked, args.workdir, out,
                                    timeout=args.timeout,
                                    max_rounds=args.max_rounds)
    if args.report:
        write_report(records, args.report,
                     {"predictions": out, "model": "x6-agent"})
    print("生成 %d 条 predictions -> %s" % (len(rows), out))
    return 0


def _write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
