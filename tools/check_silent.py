# -*- coding: utf-8 -*-
"""静默失败棘轮 —— 冻结存量，拦住新增

为什么用棘轮而不是"全修掉"
--------------------------
实测全项目有 500+ 处 `except Exception: pass`。**存量不能批量改** ——
大部分是合理的最尽力路径（可选组件缺失、探测失败、清理时忽略错误），
批量改的风险远大于收益，而且会把"本来就不该报"的地方变成噪声。

但**新增**必须被拦住：静默失败是这一类 bug 的来源 ——
这一轮修的两个真问题都是它：
    · memory_organizer.auto_organize  读时跳过坏行 + 写时全量覆盖
      -> 坏行被永久删除，而返回值还报"一条没丢"
    · startup_optimizer.precompile    py_compile(doraise=False) 不抛异常，
      把编不过的文件也算成成功
所以：存量冻结（有数字），新增要说明理由。

怎么标"这里是故意的"
--------------------
在这处 except 的上方或同行写一句说明即可（两种写法都认）：
    # 静默是故意的：没有 N 卡属于正常结果，不是错误
    except Exception:
        pass
或
    except Exception:  # 静默是故意的
        pass
判定时会检查 except 节点往上 6 行内有没有 "故意" / "noqa: silent"。
（已按此标记：gpu_detector.detect、crash_export 写提示文件。）

用法
----
    py -3 tools\\check_silent.py            # 检查（超基线返回 1）
    py -3 tools\\check_silent.py --rebase   # 把当前数量写成新基线
    py -3 tools\\check_silent.py -v         # 列出每处位置
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import argparse
import ast
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(BASE, "tools", "silent_baseline.json")

SKIP_DIRS = {"__pycache__", "libs", "optional_libs", ".git", "backups",
             "staging", "dist", "build", "data", "modules_repo", "retired",
             "_deprecated", "_trash"}
# 扫描范围：这几层是"用户会碰到"的代码
SCAN_DIRS = ("core", "gui", "modules", "run.py", "tools", "scripts")

MARKERS = ("故意", "noqa: silent", "noqa:silent", "有意")
LOOKBACK = 6          # 往上找标记的行数


def _is_silent(handler):
    """except 体是不是"什么都不做"（pass / continue / return None / return）"""
    body = [n for n in handler.body if not isinstance(n, ast.Expr)
            or not isinstance(n.value, ast.Constant)]   # 忽略纯字符串（docstring）
    if not body:
        return True
    first = body[0]
    if isinstance(first, ast.Pass):
        return True
    if isinstance(first, ast.Continue):
        return True
    if isinstance(first, ast.Return):
        return first.value is None
    return False


def _has_marker(lines, handler):
    """往上 LOOKBACK 行里有没有"这是故意的"标记"""
    lo = max(0, handler.lineno - 1 - LOOKBACK)
    hi = min(len(lines), (getattr(handler, "end_lineno", handler.lineno) or
                          handler.lineno))
    text = "\n".join(lines[lo:hi])
    return any(m in text for m in MARKERS)


def scan(base=BASE):
    """返回 {相对路径: [行号...]}（只含"宽泛 + 静默 + 没标记"的）"""
    out = {}
    for target in SCAN_DIRS:
        p = os.path.join(base, target)
        files = []
        if os.path.isfile(p):
            files = [p]
        else:
            for r, ds, fs in os.walk(p):
                ds[:] = [d for d in ds if d not in SKIP_DIRS]
                files += [os.path.join(r, f) for f in fs if f.endswith(".py")]
        for fp in files:
            try:
                src = open(fp, encoding="utf-8-sig", errors="ignore").read()
                tree = ast.parse(src)
            except Exception as e:
                _x6_swallowed(__name__, e)
                continue
            lines = src.splitlines()
            hits = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                # 只算宽泛捕获（具体类型如 ImportError/OSError 属于合理兜底）
                if node.type is None:
                    broad = True
                elif isinstance(node.type, ast.Name):
                    broad = node.type.id in ("Exception", "BaseException")
                else:
                    broad = False
                if not broad:
                    continue
                if not _is_silent(node):
                    continue
                if _has_marker(lines, node):
                    continue
                hits.append(node.lineno)
            if hits:
                rel = os.path.relpath(fp, base).replace("\\", "/")
                out[rel] = sorted(hits)
    return out


def main():
    ap = argparse.ArgumentParser(description="静默失败棘轮")
    ap.add_argument("--rebase", action="store_true", help="把当前数量写成新基线")
    ap.add_argument("-v", "--verbose", action="store_true", help="列出每处位置")
    args = ap.parse_args()

    now = scan()
    total = sum(len(v) for v in now.values())

    if args.rebase:
        # per_file 存**数量**（不是行号列表）—— 存列表的话下面比较时
        # 会变成 int > list，直接 TypeError（写的时候踩过）
        json.dump({"_说明": "静默失败存量基线（棘轮）。新增应当先说明理由，"
                            "确属故意的在这处 except 上方写『静默是故意的：…』"
                            "或行尾加 # 静默是故意的。",
                   "total": total,
                   "per_file": {k: len(v) for k, v in now.items()}},
                  open(BASELINE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("  基线已更新：%d 处，%d 个文件" % (total, len(now)))
        return 0

    try:
        b = json.load(open(BASELINE, encoding="utf-8"))
    except Exception:
        print("[X] 读不到基线 %s —— 先跑一次 --rebase" % BASELINE)
        return 1

    b_total = int(b.get("total", 0))
    b_per = b.get("per_file", {}) or {}

    print("=" * 74)
    print("静默失败棘轮（宽泛捕获 + 什么都不做 + 没标记）")
    print("=" * 74)
    print("  现在 %d 处 / 基线 %d 处   %s"
          % (total, b_total, "✅" if total <= b_total else "❌ 超 %d" % (total - b_total)))
    print("  （具体异常类型不算 —— ImportError / OSError 这类属于合理兜底）")

    over = []
    for rel, hits in sorted(now.items()):
        cap = b_per.get(rel)
        if cap is None:
            over.append("%s 新增 %d 处" % (rel, len(hits)))
            print("  %-52s %3d /   -  ❌ 新增" % (rel, len(hits)))
        elif len(hits) > cap:
            over.append("%s 从 %d 涨到 %d" % (rel, cap, len(hits)))
            print("  %-52s %3d / %3d  ❌ 涨了" % (rel, len(hits), cap))
        elif args.verbose:
            print("  %-52s %3d / %3d" % (rel, len(hits), cap))

    print("=" * 74)
    if over or total > b_total:
        print("超基线：")
        for o in over:
            print("   · %s" % o)
        print()
        print("怎么处理：")
        print("  · 确实该报的 —— 把它改成记日志 / 返回错误，别静默吞")
        print("  · 确实该忍的 —— 在这处 except 上方写一行说明：")
        print("        # 静默是故意的：<为什么这不是错误>")
        print("    或者行尾加 # 静默是故意的")
        print("  · 都不适用 —— 跑一次 py -3 tools\\check_silent.py --rebase")
        print("    并说明为什么这次放开")
        return 1
    print("静默失败棘轮通过 ✅  存量 %d 处，没有新增" % total)
    return 0


if __name__ == "__main__":
    from _console import use_utf8_console
    use_utf8_console()
    sys.exit(main())
