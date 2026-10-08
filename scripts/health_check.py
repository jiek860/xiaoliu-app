# -*- coding: utf-8 -*-
"""小6智能体一键健康检查脚本
用法：双击运行，或在命令行执行 python scripts/health_check.py
"""
import os, sys, compileall

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    print("="*50)
    print("小6智能体 健康检查")
    print("="*50)
    ok = True

    # 1. 语法检查
    print("\n[1/4] 语法检查...")
    for d in ["core", "gui", "modules/installed", "modules_repo", "tools", "scripts"]:
        full = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d)
        if not os.path.isdir(full):
            continue
        r = compileall.compile_dir(full, quiet=1)
        if r:
            print(f"  ✅ {d} 语法正确")
        else:
            print(f"  ❌ {d} 存在语法错误")
            ok = False

    # 2. 核心模块导入检查
    print("\n[2/4] 核心模块导入检查...")
    mods = ["core.trunk", "core.llm_client", "core.config", "gui.main_window", "gui.chat_view"]
    for m in mods:
        try:
            __import__(m)
            print(f"  ✅ {m}")
        except Exception as e:
            print(f"  ❌ {m}: {str(e)[:60]}")
            ok = False

    # 3. 配置文件检查
    print("\n[3/4] 配置文件检查...")
    cfg_path = os.path.join("data", "config.json")
    if os.path.exists(cfg_path):
        import json
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                json.load(f)
            print("  ✅ config.json 格式正确")
        except Exception as e:
            print(f"  ❌ config.json 损坏: {e}")
            ok = False
    else:
        print("  ⚠️ config.json 不存在")

    # 4. 崩溃日志检查
    print("\n[4/4] 最近崩溃检查...")
    crash_log = os.path.join("data", "logs", "gui_crashes.log")
    if os.path.exists(crash_log):
        with open(crash_log, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            if len(lines) > 0:
                print(f"  ⚠️ 最近有{len(lines)}条崩溃记录，最近一条: {lines[-1].strip()[:80]}")
            else:
                print("  ✅ 无崩溃记录")
    else:
        print("  ✅ 无崩溃历史")

    print("\n" + "="*50)
    if ok:
        print("✅ 健康检查通过，程序状态正常")
    else:
        print("❌ 健康检查发现问题，请根据上面提示修复")
    print("="*50)
    input("按回车退出...")

if __name__ == "__main__":
    main()
