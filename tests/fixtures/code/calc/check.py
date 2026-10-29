# -*- coding: utf-8 -*-
import sys

from calc import average

try:
    if average([1, 2]) != 1.5:
        print("失败：average([1, 2]) 应为 1.5")
        sys.exit(1)
    if average([]) != 0:
        print("失败：average([]) 应为 0")
        sys.exit(1)
except ZeroDivisionError:
    print("失败：average([]) 抛了 ZeroDivisionError")
    sys.exit(1)
print("ok")
