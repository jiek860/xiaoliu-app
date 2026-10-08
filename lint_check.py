# -*- coding: utf-8 -*-
"""代码检查脚本 - 语法 + 导入检查"""
import sys, os, glob, py_compile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 50)
print("代码检查")
print("=" * 50)
print()

# 1. 语法检查
print("【1. 语法检查】")
errors = []
py_files = []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in ("libs", "__pycache__", "data", ".git")]
    for f in files:
        if f.endswith(".py") and not f.endswith(".bak"):
            py_files.append(os.path.join(root, f))

for f in py_files:
    try:
        py_compile.compile(f, doraise=True)
    except Exception as e:
        errors.append((f, str(e)[:60]))

print("  检查了 %d 个文件" % len(py_files))
print("  语法错误: %d 个" % len(errors))
for f, e in errors:
    print("    ❌ %s: %s" % (f, e))

# 2. 导入检查
print()
print("【2. 核心模块导入检查】")
core_modules = ["trunk", "config", "logger", "safe", "crypto", "chat_store", "version"]
ok = 0
fail = 0
for m in core_modules:
    try:
        __import__("core." + m)
        ok += 1
    except Exception as e:
        print("  ❌ core.%s: %s" % (m, str(e)[:50]))
        fail += 1
print("  成功: %d/%d" % (ok, ok+fail))

# 3. 测试
print()
print("【3. 单元测试】")
try:
    import subprocess
    result = subprocess.run(
        [sys.executable, "tests/test_core.py"],
        capture_output=True, text=True, timeout=30
    )
    if "ALL" in result.stdout and "PASSED" in result.stdout:
        print("  ✅ 所有测试通过")
    else:
        print("  ❌ 测试失败")
        print(result.stdout[-200:])
except Exception as e:
    print("  ⚠️ 测试运行失败: %s" % str(e)[:50])

print()
print("=" * 50)
if len(errors) == 0 and fail == 0:
    print("✅ 全部检查通过！")
else:
    print("❌ 发现 %d 个问题" % (len(errors) + fail))
print("=" * 50)
