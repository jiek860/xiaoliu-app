# -*- coding: utf-8 -*-
"""守卫：死模块 / 零引用函数只许降（把审计结果钉成基线）

为什么要把"审计"变成"门禁"
--------------------------
`tools/audit_dead_code.py` 是**报告**工具：它只打印"可疑清单"，退出码永远是 0。
2026-11-02 的 S3 把清单清到 0（可疑死模块 0 / 死函数 0 / 重复实现 0），
但报告工具不会拦住"下一次又加进来一个没人调用的函数" —— 那正是死代码长回来的方式。

所以这里做**棘轮**（同 `check_data_paths` / `check_silent` 的思路）：

    * 可疑死模块数、零引用函数数、完全重复实现组数，各自有基线；
    * 超基线 → 退出码 1，并把"新冒出来的那几个"直接点出来；
    * 确认要保留的（有意的公共入口）登在 `audit_dead_code.KEEP` 里，不算可疑，
      所以清理完基线是 **0/0/0** —— 任何新增都是真新增。

误报怎么办
----------
审计是**静态近似**（改名 / 反射 / 字符串拼装调用查不到）。真出现误报时两条路：

    1. 如果是"零引用但有意的公共入口" → 加进 `tools/audit_dead_code.py::KEEP`
       （带 why 一行说明），它就不再计入可疑；
    2. 如果是工具本身的漏扫（比如某个目录没被扫） → 修工具，不要调高基线。

`--update` 只用于"确认清单确实降下来了，把基线收紧"，不要用它放水。

用法
----
    py -3 tools\\check_dead_code.py            # 校验（门禁用）
    py -3 tools\\check_dead_code.py --update   # 清理后收紧基线
"""
import argparse
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(BASE, "tools", "dead_code_baseline.json")
TOOLS = os.path.dirname(os.path.abspath(__file__))

# 三类计数：基线键 -> 结果列表的键
KEYS = {
    "dead_modules": "可疑死模块（core/gui 里既没被 import、也没登记进 LAZY_MAP）",
    "dead_defs": "零引用函数/类（外部零引用，且本文件里除定义外再没出现）",
    "duplicates": "完全重复实现（跨文件 body 一模一样，≥6 条语句）",
}


def _audit():
    """跑一次审计（同一个进程内复用 audit_dead_code 的实现，不重复造轮子）

    结果缓存在模块级：`check()` 与 `main()` 都会要一份，而扫 790 个 .py 要 6 秒
    （测试里连调两次就是 12 秒，没必要）。
    """
    if "_cached" not in globals():
        if TOOLS not in sys.path:
            sys.path.insert(0, TOOLS)
        import audit_dead_code
        globals()["_cached"] = audit_dead_code.audit()
    return globals()["_cached"]


def load_baseline():
    try:
        with io.open(BASELINE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _describe(item):
    if "name" in item:        # 函数/类
        return "%s:%s %s %s" % (item.get("file"), item.get("line"),
                                item.get("kind", ""), item.get("name"))
    if "a" in item:           # 重复实现
        return "%s == %s" % (item.get("a"), item.get("b"))
    return str(item.get("file") or item)     # 死模块


def check(result=None):
    """返回错误列表（空 = 通过）"""
    r = result if result is not None else _audit()
    base = load_baseline()
    errs = []
    for key, why in KEYS.items():
        items = list(r.get(key) or [])
        cap = int(base.get(key) or 0)
        if len(items) <= cap:
            continue
        errs.append("%s：现 %d（基线 %d，涨了 %d）—— %s"
                    % (key, len(items), cap, len(items) - cap, why))
        for item in items[:10]:
            errs.append("    %s" % _describe(item))
        if len(items) > 10:
            errs.append("    …另有 %d 条，跑 py -3 tools/audit_dead_code.py --all"
                        % (len(items) - 10))
    if errs:
        errs.append("怎么处理：真没人用 → 删；零引用但有意的公共入口 → 登进 "
                    "tools/audit_dead_code.py::KEEP（写清 why）；工具漏扫 → 修工具。"
                    "不要调高基线放水。")
    return errs


def update(result=None):
    r = result if result is not None else _audit()
    data = {key: len(list(r.get(key) or [])) for key in KEYS}
    data["kept"] = len(list(r.get("kept_defs") or []))
    data["updated"] = "2026-11-02"
    data["why"] = ("可疑死代码基线（棘轮）：清理后只许降。新增一项就会让门禁失败，"
                   "确认要保留的登 KEEP。由 tools/audit_dead_code.py 的静态近似口径产出。")
    with io.open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("✅ 基线已更新：%s（已知保留 %d）"
          % (" / ".join("%s %d" % (k, data[k]) for k in KEYS), data["kept"]))
    return 0


def main():
    ap = argparse.ArgumentParser(description="死代码棘轮（可疑死模块/死函数只许降）")
    ap.add_argument("--update", action="store_true", help="把当前结果写成新基线")
    args = ap.parse_args()

    if args.update:
        return update()

    r = _audit()
    base = load_baseline()
    errs = check(r)
    print("=" * 74)
    print("死代码棘轮（静态近似：零引用 = 可疑，KEEP 里的不算）")
    print("=" * 74)
    for key in KEYS:
        now = len(list(r.get(key) or []))
        cap = int(base.get(key) or 0)
        print("  %-13s 现在 %3d / 基线 %3d  %s"
              % (key, now, cap, "✅" if now <= cap else "❌"))
    print("  已知保留（KEEP）       %3d（不计入可疑）" % len(r.get("kept_defs") or []))
    print("  扫描 .py 文件          %3d" % int(r.get("scanned") or 0))
    print("=" * 74)
    if errs:
        for e in errs:
            print(e)
        return 1
    print("死代码棘轮通过 ✅  没有新增可疑死代码")
    return 0


if __name__ == "__main__":
    sys.exit(main())
