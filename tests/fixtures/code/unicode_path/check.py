# -*- coding: utf-8 -*-
import os
import sys
import tempfile

from io_util import write_text

root = tempfile.mkdtemp(prefix="x6_unicode_")
path = os.path.join(root, "中文文件.txt")
try:
    write_text(path, "你好，小6")
    with open(path, encoding="utf-8") as fp:
        text = fp.read()
    if text != "你好，小6":
        print("失败：读回内容不一致 %r" % text)
        sys.exit(1)
except UnicodeDecodeError:
    print("失败：用 UTF-8 读回时解码失败（写入编码不是 UTF-8）")
    sys.exit(1)
print("ok")
