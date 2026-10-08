# -*- coding: utf-8 -*-
"""逐个真实加载 core/lazy_config.py 里登记的每个模块

比语法检查更进一步：能抓住「类存在、但构造函数签名与微核协议不匹配」这类
只有真正加载时才会暴露的问题（历史案例：core/graph_db.py 参数是路径而不是 trunk，
_load_lazy 永远返回 None，日志里只有一行 '加载xxx失败'）。

用法：
    python scripts/check_modules.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

# 这些模块加载时会占用音频设备/端口，单独跳过（本机没设备时必失败）
SKIP = {"voice", "stt"}


def main():
    from core.trunk import Trunk
    from core.lazy_config import LAZY_MAP

    print("=" * 52)
    print("懒加载模块实际加载检查")
    print("=" * 52)

    t = Trunk()
    keys = sorted(k for k in LAZY_MAP if k not in SKIP)
    ok, bad = 0, []
    for k in keys:
        try:
            m = t._load_lazy(k)
        except Exception as e:
            m = None
            bad.append((k, "%s: %s" % (type(e).__name__, str(e)[:60])))
            continue
        if m is None:
            bad.append((k, "加载返回 None（看 data/logs/trunk.log 里的『加载%s失败』）" % k))
        else:
            ok += 1

    print("\n加载成功: %d/%d" % (ok, len(keys)))
    for k, why in bad:
        print("  [X] %-24s %s" % (k, why))
    if bad:
        print("\n提示：注册了但加载不了的模块，等于用户点开就报错，应当修掉或从 LAZY_MAP 摘除。")
        return 1
    print("\n[OK] 所有登记模块都能正常加载")
    return 0


if __name__ == "__main__":
    sys.exit(main())
