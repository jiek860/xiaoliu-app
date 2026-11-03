# -*- coding: utf-8 -*-
"""懒加载来源校验（B0，2026-11-02）

为什么需要它
------------
core/lazy_config.py 的 LAZY_MAP 同时登记「插件市场插件」和「core 内置模块」。
以前 _load_lazy 两处目录都试，猜中哪个算哪个 —— 于是一个 core 模块文件丢了，
日志却写「模块未安装，请到插件市场下载」，把人指错方向；插件市场的
安装/卸载/签名流程也无法区分谁是真插件。

本守卫只做只读核对，四条硬规则：
  1. 每个 key 的文件必须在其登记来源目录存在（core → core/，installed → modules/installed/）；
  2. 登记为 core 的 key，不允许 modules/installed 下再有同名文件（防重复登记）；
  3. 同一文件名被多个 key 共用时，只允许 SAME_FILE_ALIASES 里声明的语义别名；
  4. SAME_FILE_ALIASES 的别名与目标都必须是已登记的 key。

退出码非 0 即失败，可直接挂进 pre-commit。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.lazy_config import (  # noqa: E402
    LAZY_MAP, SAME_FILE_ALIASES, source_of,
)


def _alias_group(name):
    """name 若属于某个声明的别名对，返回该对（集合）；否则 None"""
    for a, b in SAME_FILE_ALIASES.items():
        if name in (a, b):
            return {a, b}
    return None


def check():
    inst = os.path.join(BASE, "modules", "installed")
    core = os.path.join(BASE, "core")
    problems = []

    # 规则 1 + 2
    for key, val in LAZY_MAP.items():
        fname = val[0]
        src = source_of(key)
        home = core if src == "core" else inst
        if not os.path.exists(os.path.join(home, fname + ".py")):
            problems.append("%s 登记为 %s，但 %s/%s.py 不存在"
                            % (key, src, src, fname))
        if src == "core" and os.path.exists(os.path.join(inst, fname + ".py")):
            problems.append("%s 登记为 core，但 modules/installed/%s.py 也有同名文件（疑似重复）"
                            % (key, fname))

    # 规则 3：同一文件多 key 只允许声明的别名
    by_file = {}
    for key, val in LAZY_MAP.items():
        by_file.setdefault(val[0], []).append(key)
    for fname, keys in by_file.items():
        if len(keys) <= 1:
            continue
        if all(_alias_group(k) is not None for k in keys):
            continue
        problems.append("文件 %s.py 被多个 key 共用: %s（未在 SAME_FILE_ALIASES 声明）"
                        % (fname, keys))

    # 规则 4：别名两端都要是已登记 key
    for a, b in SAME_FILE_ALIASES.items():
        for k in (a, b):
            if k not in LAZY_MAP:
                problems.append("SAME_FILE_ALIASES 里的 %s 不在 LAZY_MAP" % k)

    return problems


def main():
    problems = check()
    n_core = sum(1 for k in LAZY_MAP if source_of(k) == "core")
    n_inst = len(LAZY_MAP) - n_core
    print("=" * 60)
    print("懒加载来源校验：共 %d 条（core %d / installed %d）"
          % (len(LAZY_MAP), n_core, n_inst))
    print("=" * 60)
    if problems:
        for p in problems:
            print("  [X] " + p)
        print("\n结果: 失败（%d 处）" % len(problems))
        return 1
    print("[OK] 全部命中登记来源，无重复登记、无未声明别名")
    return 0


if __name__ == "__main__":
    sys.exit(main())
