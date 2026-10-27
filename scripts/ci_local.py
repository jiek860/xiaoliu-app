# -*- coding: utf-8 -*-
"""本地定时 CI（P2-12）：不依赖 GitHub，跑完整门禁并把结果落到 docs。

为什么不用 GitHub Actions
------------------------
本机 `github.com:443` 直连被 RST，Actions 的触发/回看都不稳。等网络可用再上云端，
这里先做「本地定时脚本 + 结果落 docs」：定时任务只管触发，门禁和记录都在本地。

用法
----
    py -3 scripts\\ci_local.py              # 全套（含 pytest，约 5~6 分钟）
    py -3 scripts\\ci_local.py --quick      # 跳过 pytest 与类型检查
    py -3 scripts\\ci_local.py --no-record  # 只打印，不写 docs

结果写入 `docs/96_本地CI运行记录.md`（表格追加一行，失败项会带原因）。

退出码：0 全过；1 有失败项。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(BASE, "docs", "96_本地CI运行记录.md")
PY = sys.executable or "py"

# (名称, 命令参数, 是否可被 --quick 跳过)
CHECKS = [
    ("语法编译", ["-m", "compileall", "-q", "core", "gui", "modules",
                  "modules_repo", "tools", "scripts"], False),
    ("版本号", ["tools/check_version.py"], False),
    ("按钮清单", ["tools/check_buttons.py"], False),
    ("工具清单", ["tools/check_tools.py"], False),
    ("线程生命周期", ["tools/check_threads.py"], False),
    ("静默异常", ["tools/check_silent.py"], False),
    ("依赖形状", ["tools/check_shapes.py"], False),
    ("文件长度", ["tools/check_file_sizes.py"], False),
    ("插件仓库一致", ["tools/check_repo_sync.py"], False),
    ("插件质量", ["tools/check_plugin_quality.py"], False),
    ("插件安全", ["tools/check_plugin_security.py"], False),
    ("插件签名", ["tools/verify_signature.py", "--all"], False),
    ("类型与风格", ["tools/check_types.py"], True),
    ("全量测试", None, True),
]

TIMEOUT = 900
PYTEST_CHUNKS = 3


def _env():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.pop("PYTHONPATH", None)
    return env


def run_check(argv):
    """返回 (ok, 秒, 失败摘要)"""
    t0 = time.time()
    try:
        r = subprocess.run([PY] + argv, cwd=BASE, env=_env(),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, "超时（%d 秒）" % TIMEOUT
    except Exception as e:
        return False, time.time() - t0, str(e)[:120]
    dt = time.time() - t0
    if r.returncode == 0:
        return True, dt, ""
    lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    tail = " | ".join(x.strip() for x in lines[-4:] if x.strip())[:220]
    return False, dt, tail or ("退出码 %d" % r.returncode)


def _test_files():
    root = os.path.join(BASE, "tests")
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.startswith("test_") and name.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dirpath, name), BASE))
    return sorted(out)


def run_pytest_chunked():
    """分段跑全量测试。

    为什么分段：一次跑 2100+ 用例时本机偶发 `MemoryError` / 进程级崩溃
    （0xC0000409），不是用例失败却会让整条 CI 记成红。拆成几段后内存能
    及时归还，失败也能定位到具体是哪一段。
    """
    files = _test_files()
    if not files:
        return False, 0.0, "tests/ 下没找到 test_*.py"
    size = (len(files) + PYTEST_CHUNKS - 1) // PYTEST_CHUNKS
    t0 = time.time()
    for start in range(0, len(files), size):
        part = files[start:start + size]
        ok, _dt, why = run_check(["-m", "pytest"] + part + ["-q"])
        if not ok:
            return False, time.time() - t0, "第 %d 段：%s" % (
                start // size + 1, why)
    return True, time.time() - t0, ""


def _write_record(rows, passed, total, dt):
    """往 docs/96_本地CI运行记录.md 追加一行（没有就建表头）"""
    head = ("# 本地定时 CI 运行记录\n\n"
            "> 由 `scripts/ci_local.py` 自动追加。GitHub Actions 等网络可用后以云端为准，\n"
            "> 这里只解决「现在全靠手动跑门禁」的问题。\n\n"
            "| 时间 | 结果 | 通过/总数 | 耗时 | 失败项 |\n"
            "|---|---|---|---|---|\n")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    bad = [r[0] for r in rows if not r[1]]
    cells = ["%s" % stamp,
             "✅ 全过" if not bad else "❌ 有失败",
             "%d/%d" % (passed, total),
             "%.0f 秒" % dt,
             "—" if not bad else "、".join(bad)]
    line = "| " + " | ".join(cells) + " |\n"
    try:
        if not os.path.exists(RECORD):
            os.makedirs(os.path.dirname(RECORD), exist_ok=True)
            with open(RECORD, "w", encoding="utf-8", newline="") as f:
                f.write(head)
        with open(RECORD, "a", encoding="utf-8", newline="") as f:
            f.write(line)
        return True
    except OSError as e:
        print("[!] 写记录失败: %s" % str(e)[:80])
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="本地定时 CI（门禁 + 落 docs）")
    ap.add_argument("--quick", action="store_true", help="跳过 pytest 与类型检查")
    ap.add_argument("--no-record", action="store_true", help="不写 docs 记录")
    args = ap.parse_args(argv)

    todo = [c for c in CHECKS if not (args.quick and c[2])]
    print("=" * 66)
    print("本地 CI · %s · %d 项%s"
          % (time.strftime("%Y-%m-%d %H:%M"), len(todo),
             "（快速模式）" if args.quick else ""))
    print("=" * 66)

    rows = []
    t_all = time.time()
    for name, argv_, _skip in todo:
        if argv_ is None:                       # 全量测试：分段跑
            ok, dt, why = run_pytest_chunked()
        else:
            ok, dt, why = run_check(argv_)
        rows.append((name, ok, dt, why))
        print("%s %-14s %6.1f 秒 %s"
              % ("✅" if ok else "❌", name, dt, "" if ok else why[:120]))

    total = len(rows)
    passed = sum(1 for r in rows if r[1])
    dt_all = time.time() - t_all
    print("-" * 66)
    print("结果 %d/%d 通过 · %.1f 秒" % (passed, total, dt_all))
    if passed != total:
        print("失败项: %s" % "、".join(r[0] for r in rows if not r[1]))
    if not args.no_record:
        _write_record(rows, passed, total, dt_all)
        print("记录已写入: %s" % os.path.relpath(RECORD, BASE))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
