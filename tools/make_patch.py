# -*- coding: utf-8 -*-
"""差分补丁生成脚本
用法: python tools/make_patch.py 旧文件 新文件 输出补丁.diff
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.patch_utils import make_file_patch


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: python tools/make_patch.py 旧文件 新文件 输出补丁.diff")
        sys.exit(1)
    old_path, new_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    patch = make_file_patch(old_path, new_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(patch)
    print("✅ 补丁已生成:", out_path)
    print("大小:", len(patch), "字节")
