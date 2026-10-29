# -*- coding: utf-8 -*-
"""Lightweight performance baseline and regression gate.

The measurements are deliberately coarse and stable enough for CI trend checks:
import/startup probes, source/package size and process RSS. Hosted runners are
noisy, so the gate uses a 20% regression allowance and a median of three runs.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT = BASE / "perf_baseline.json"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _probe(code):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    times = []
    for _ in range(3):
        started = time.perf_counter()
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(BASE),
                              capture_output=True, text=True, timeout=120, env=env)
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or "")[-300:]}
        times.append((time.perf_counter() - started) * 1000.0)
    return {"ok": True, "ms_median": round(statistics.median(times), 2),
            "samples_ms": [round(x, 2) for x in times]}


def _cold_start_probe():
    """冷启动近似：导入启动链路（Qt/主窗口/LLM 客户端），不含构造实例。"""
    return _probe(
        "import time; t=time.perf_counter();"
        " import core.trunk, core.llm_client, core.llm_cloud;"
        " import gui.build_ui, gui.main_window;"
        " print((time.perf_counter()-t)*1000)")


def _first_token_probe():
    """首 token 的**本机解析管线**耗时（不含网络与模型生成）。

    为什么这样量：CI 里没有模型和外部网络，直接测真实首 token 会变成
    "网络是否可达"的测试。这里固定一串 OpenAI SSE 数据，量从收到第一块
    数据到解析出 token 的耗时；网络/模型延迟由手工压测记录，不放进 CI。
    """
    try:
        from core.llm_providers import parse_stream_chunk
        payload = ('{"choices":[{"delta":{"content":"你"}}]}')
        samples = []
        for _ in range(50):
            started = time.perf_counter()
            token = parse_stream_chunk("openai", payload)
            samples.append((time.perf_counter() - started) * 1000.0)
        return {"ok": bool(token), "ms_median": round(statistics.median(samples), 4),
                "samples_ms": [round(x, 4) for x in samples[:5]]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def _index_probe(mode):
    """49.2：索引刷新/检索耗时（临时 30 个文件，隔离 data 目录）。"""
    setup = (
        "import os, tempfile, time;"
        "from core.code.index_v2 import CodeIndexV2;"
        "base=tempfile.mkdtemp(prefix='x6_idx_'); root=os.path.join(base,'proj');"
        "os.makedirs(root);"
        "[open(os.path.join(root,'m%d.py'%i),'w',encoding='utf-8')"
        ".write('def f%d(x):\\n    return x+%d\\n'%(i,i)) for i in range(30)];"
    )
    if mode == "refresh":
        body = ("idx=CodeIndexV2(base, root);"
                "t=time.perf_counter(); st=idx.refresh(root);"
                "print((time.perf_counter()-t)*1000)")
    else:
        body = ("idx=CodeIndexV2(base, root); idx.refresh(root);"
                "t=time.perf_counter();"
                "[idx.search('f%d x'%i, top_k=10) for i in range(30)];"
                "print((time.perf_counter()-t)*1000/30)")
    return _probe(setup + body)


def _retrieval_probe():
    """49.2：200 篇文档的检索耗时（纯本地，不加载向量模型）。"""
    return _probe(
        "import tempfile, time;"
        "from core.retrieval import HybridRetriever;"
        "base=tempfile.mkdtemp(prefix='x6_rtr_'); r=HybridRetriever(base);"
        "r.add_many([{'text':'第%d篇 关于索引、检索、上下文的说明'%i,'source':'s'} "
        "for i in range(200)]);"
        "t=time.perf_counter();"
        "[r.search('检索 上下文', top_k=5) for _ in range(50)];"
        "print((time.perf_counter()-t)*1000/50)")


def _context_probe():
    """49.2：上下文裁剪耗时（100 条消息、超预算触发裁剪）。"""
    return _probe(
        "import time;"
        "from core.context_budget import trim_messages;"
        "msgs=[{'role':'user','content':'第%d条 这是一段用来触发预算裁剪的对话内容'%i}"
        " for i in range(100)];"
        "t=time.perf_counter();"
        "[trim_messages(msgs, 2000, 200) for _ in range(100)];"
        "print((time.perf_counter()-t)*1000/100)")


def _memory_probe():
    """49.2：记忆召回耗时（200 张卡、50 次召回）。"""
    return _probe(
        "import tempfile, time;"
        "from core.chat.memory_v2 import MemoryV2, make_card, append_cards;"
        "base=tempfile.mkdtemp(prefix='x6_mem_'); m=MemoryV2(base);"
        "append_cards(m.path, [make_card('我喜欢第%d种咖啡'%i) for i in range(200)]);"
        "t=time.perf_counter();"
        "[m.recall('咖啡', limit=5) for _ in range(50)];"
        "print((time.perf_counter()-t)*1000/50)")


def _tree_size(path):
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def measure():
    metrics = {
        "cold_start_ms": _cold_start_probe(),
        "first_token_ms": _first_token_probe(),
        "import_core_modules": _probe(
            "import time; t=time.perf_counter(); import core.permission_center,"
            " core.net_guard, core.plugin_api, core.tool_policy;"
            " print((time.perf_counter()-t)*1000)"),
        "import_gui_build_ui": _probe(
            "import time; t=time.perf_counter(); import gui.build_ui;"
            " print((time.perf_counter()-t)*1000)"),
        "code_index_refresh_ms": _index_probe("refresh"),
        "code_index_search_ms": _index_probe("search"),
        "retrieval_search_ms": _retrieval_probe(),
        "memory_recall_ms": _memory_probe(),
        "context_trim_ms": _context_probe(),
        "artifact_bytes": _tree_size(BASE / "dist"),
        "source_bytes": _tree_size(BASE / "core") + _tree_size(BASE / "gui") +
                        _tree_size(BASE / "modules" / "installed"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        import psutil
        metrics["process_rss_mb"] = round(
            psutil.Process().memory_info().rss / 1048576.0, 2)
    except Exception:
        metrics["process_rss_mb"] = 0
    return metrics


def compare(current, baseline, tolerance=0.20):
    failures = []
    checks = {
        "cold_start_ms": "ms_median",
        "first_token_ms": "ms_median",
        "import_core_modules": "ms_median",
        "import_gui_build_ui": "ms_median",
        "code_index_refresh_ms": "ms_median",
        "code_index_search_ms": "ms_median",
        "retrieval_search_ms": "ms_median",
        "memory_recall_ms": "ms_median",
        "context_trim_ms": "ms_median",
        "source_bytes": None,
        "artifact_bytes": None,
    }
    for metric, field in checks.items():
        old = baseline.get(metric)
        cur = current.get(metric)
        if metric == "artifact_bytes" and not cur:
            continue
        if isinstance(old, dict):
            old = old.get(field)
        if isinstance(cur, dict):
            cur = cur.get(field)
        if not old or not cur:
            continue
        limit = float(old) * (1.0 + tolerance)
        if float(cur) > limit:
            failures.append("%s regressed: %.2f > %.2f (baseline %.2f)"
                            % (metric, float(cur), limit, float(old)))
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--baseline", default=str(DEFAULT))
    parser.add_argument("--tolerance", type=float, default=0.20)
    parser.add_argument("--warn-only", action="store_true",
                        help="超过阈值只报警，返回 0（先观察一轮）")
    parser.add_argument("--json-out", default="",
                        help="把本次实测写到指定 json（CI artifact 用）")
    args = parser.parse_args(argv)
    current = measure()
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    path = Path(args.baseline)
    if args.write or not path.exists():
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print("Perf baseline written:", path)
        return 0
    if args.check:
        try:
            baseline = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print("Cannot read baseline:", exc)
            return 2
        failures = compare(current, baseline, tolerance=args.tolerance)
        if failures:
            print("Performance gate %s:" % ("warning" if args.warn_only else "failed"))
            for failure in failures:
                print(" -", failure)
            return 0 if args.warn_only else 1
        print("Performance gate passed.")
    print(json.dumps(current, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
