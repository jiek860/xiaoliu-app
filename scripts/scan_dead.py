# -*- coding: utf-8 -*-
"""死代码扫描脚本：生成报告，不删任何文件"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.lazy_config import LAZY_MAP
REPORT = os.path.join(BASE, "data", "dead_code_report.txt")
SCAN_DIRS = ["core", "gui", "modules", "installed"]
all_text = ""
for d in SCAN_DIRS:
    p = os.path.join(BASE, d)
    if not os.path.isdir(p):
        continue
    for root, _, files in os.walk(p):
        for f in files:
            if f.endswith(".py"):
                try:
                    all_text += open(os.path.join(root, f), encoding="utf-8", errors="ignore").read()
                except Exception:
                    pass
lines = ["=== 死代码扫描报告 ===", "", "模块名 | 有trunk.call引用 | 疑似死代码"]
for name in LAZY_MAP.keys():
    has_call = ('trunk.call("%s"' % name) in all_text
    suspect = "是" if not has_call else "否"
    lines.append("%s | %s | %s" % (name, has_call, suspect))
with open(REPORT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("扫描完成，报告已写入: " + REPORT)
