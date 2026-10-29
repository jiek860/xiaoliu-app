# -*- coding: utf-8 -*-
import sys

from game import Snake

s = Snake()
s.eat()
if s.status()["score"] != 10:
    print("失败：吃到食物后分数应为 10，实际 %s" % s.status())
    sys.exit(1)
s.eat()
if s.status()["length"] != 5:
    print("失败：长度应为 5，实际 %s" % s.status())
    sys.exit(1)
print("ok")
