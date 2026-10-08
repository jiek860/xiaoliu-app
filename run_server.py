# -*- coding: utf-8 -*-
"""无GUI后台运行模式 - 24小时后台服务"""
import sys, os

# 与 run.py 保持一致：模型下载走镜像（可用 HF_ENDPOINT 覆盖）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 依赖目录与 run.py 保持一致：libs\ 核心库，optional_libs\ 可选功能库
_base_dir = os.path.dirname(os.path.abspath(__file__))
for _d in (os.path.join(_base_dir, "optional_libs"), os.path.join(_base_dir, "libs")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)
if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

# ⚠️ 必须在任何 Qt 导入之前：PyQt5 自带旧版 MSVCP140.dll，会挡住 torch 的 c10.dll
try:
    from core.win_dll_fix import preload_msvc_runtime
    preload_msvc_runtime()
except Exception:
    pass

os.chdir(_base_dir)

from core.trunk import Trunk

def main():
    print("=== 后台服务启动 ===")
    t = Trunk()
    print(f"模块: {len(t.modules)}核心 + {len(t._lazy)}懒加载")
    # 启动移动端 Web 服务（8765）
    try:
        mr = t._load_lazy('mobile_remote')
        if mr is None:
            print("移动端启动失败: 模块 mobile_remote 未登记或加载失败")
        else:
            print("移动端: " + str(mr.start()))
    except Exception as e:
        print("移动端启动失败: " + str(e))
    print("=== 24小时运行中 ===")
    print("按Ctrl+C停止")
    try:
        import time
        while True:
            time.sleep(60)
            try:
                t._log("心跳正常")
            except: pass
    except KeyboardInterrupt:
        print("\n=== 服务停止 ===")
        try:
            mr.stop()
        except Exception:
            pass

if __name__ == "__main__":
    main()
