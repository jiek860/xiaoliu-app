# -*- coding: utf-8 -*-
import sys

import a

if a.VALUE != 1:
    print("失败：a.VALUE 应为 1，实际 %s" % a.VALUE)
    sys.exit(1)
if a.run() != 2:
    print("失败：a.run() 应为 2，实际 %s" % a.run())
    sys.exit(1)
print("ok")
