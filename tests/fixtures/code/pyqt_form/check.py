# -*- coding: utf-8 -*-
import sys

from form import Form

called = []
form = Form()
form.handler = lambda: called.append(1)
form.submit()
if not called:
    print("失败：提交时没有调用 handler")
    sys.exit(1)
if form.saved != 1:
    print("失败：saved 应为 1，实际 %s" % form.saved)
    sys.exit(1)
print("ok")
