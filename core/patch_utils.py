# -*- coding: utf-8 -*-
"""差分更新 v1.0 - 纯Python实现（difflib文本差分）
适合py文件更新，不需要第三方库
"""
import os
import json
import difflib


def make_patch(old_text, new_text):
    """生成两个文本的diff补丁（unified diff格式）"""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile='old', tofile='new',
        n=3
    )
    return ''.join(diff)


def apply_patch(old_text, patch_text):
    """把补丁应用到旧文本上，返回新文本
    简化版：只支持unified diff的简单场景
    """
    # 如果补丁为空，直接返回旧文本
    if not patch_text.strip():
        return old_text

    old_lines = old_text.splitlines(keepends=True)
    result = []
    patch_lines = patch_text.splitlines(keepends=True)

    # 跳过diff头（--- +++ 两行）
    i = 0
    while i < len(patch_lines) and not patch_lines[i].startswith('@@'):
        i += 1

    old_idx = 0
    while i < len(patch_lines):
        line = patch_lines[i]
        if line.startswith('@@'):
            # 解析 @@ -old_start,old_count +new_start,new_count @@
            parts = line.split(' ')
            old_part = parts[1]  # -1,7
            old_start = int(old_part.split(',')[0][1:])  # 1
            # 把前面的行复制过来
            while old_idx < old_start - 1:
                result.append(old_lines[old_idx])
                old_idx += 1
            i += 1
        elif line.startswith('-'):
            # 删除行
            old_idx += 1
            i += 1
        elif line.startswith('+'):
            # 新增行
            result.append(line[1:])
            i += 1
        elif line.startswith(' '):
            # 相同行
            result.append(line[1:])
            old_idx += 1
            i += 1
        elif line.startswith('\\'):
            # "\ No newline at end of file"
            i += 1
        else:
            i += 1

    # 把剩下的旧行复制过来
    while old_idx < len(old_lines):
        result.append(old_lines[old_idx])
        old_idx += 1

    return ''.join(result)


def make_file_patch(old_path, new_path):
    """生成两个文件的补丁"""
    with open(old_path, 'r', encoding='utf-8') as f:
        old_text = f.read()
    with open(new_path, 'r', encoding='utf-8') as f:
        new_text = f.read()
    return make_patch(old_text, new_text)


def apply_file_patch(old_path, patch_text, output_path=None):
    """把补丁应用到旧文件"""
    with open(old_path, 'r', encoding='utf-8') as f:
        old_text = f.read()
    new_text = apply_patch(old_text, patch_text)
    if output_path is None:
        output_path = old_path
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(new_text)
    return output_path


# 测试
if __name__ == '__main__':
    old = """def hello():
    print('hello world')
    return 1
"""
    new = """def hello():
    print('hello world v2')
    print('new line')
    return 2
"""
    patch = make_patch(old, new)
    print("=== 补丁 ===")
    print(patch)
    patched = apply_patch(old, patch)
    print("=== 打补丁后 ===")
    print(patched)
    print("=== 是否一致 ===")
    print(patched == new)
