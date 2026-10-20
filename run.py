# -*- coding: utf-8 -*-
"""小6智能体 - 启动入口"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import sys, os

# 看门狗模式（--watchdog <pid>）必须**最先**处理：
# 它只等主进程退出并补发日志，不加载 Qt / Trunk，也不装 crash_guard
# （否则两个进程会同时往 faulthandler.log 里写）。
_wd_flag = ("--watchdog" in sys.argv)
if __name__ == "__main__" and _wd_flag:
    _wd_base = os.path.dirname(os.path.abspath(__file__))
    if _wd_base not in sys.path:
        sys.path.insert(0, _wd_base)
    try:
        from core.crash_watchdog import main as _watchdog_main
        sys.exit(_watchdog_main(sys.argv))
    except Exception:
        sys.exit(0)

# ⚠️ 崩溃捕获要**第一个装**，必须在任何 Qt / 重型库之前。
# 原因：2026-10-13 出现过一次 access violation —— 进程直接死，
# **没现场、没定位**，只能在 CHANGELOG 里记一句"没查出来"。
#
# 为什么 sys.excepthook 不够（run.py 下面那个 _install_excepthook）：
#   它只能接住 **Python 层**没处理的异常；
#   access violation 是 **C 层**内存错误，进程当场死，
#   解释器根本没机会跑到 excepthook。
# faulthandler 把 dump 做在信号/异常处理层，能在死之前
# 把**所有线程**的 Python 栈写进文件。
#
# 放在模块顶层（而不是 main 里）是为了也覆盖"导入阶段就崩"的情况。
try:
    from core.crash_guard import enable as _enable_crash_guard
    _enable_crash_guard()
# 静默是故意的：崩溃捕获是**保护措施**，不是功能。
# 它自己装不上（缺模块/没权限建目录）就退化成"和以前一样没有现场"，
# 但**绝不能因为它而打不开程序**。crash_guard.enable() 内部也做了同样取舍。
except Exception:
    pass

# 依赖目录：
#   libs/           核心随包库（numpy / requests 等），必须有
#   optional_libs/  可选功能库（torch / cv2 / faster-whisper 等），按需安装；
#                   缺失时语音识别与图片理解不可用，其余功能不受影响
# 插入顺序反过来做，最终 sys.path 为 [项目根, libs, optional_libs, ...]
_base_dir = os.path.dirname(os.path.abspath(__file__))
for _d in (os.path.join(_base_dir, "optional_libs"), os.path.join(_base_dir, "libs")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)
if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

# ⚠️ 必须在任何 Qt 导入之前：PyQt5 自带旧版 MSVCP140.dll，会挡住 torch 的 c10.dll
# （WinError 1114）。详见 core/win_dll_fix.py
try:
    from core.win_dll_fix import preload_msvc_runtime
    preload_msvc_runtime()
except Exception as e:
    _x6_swallowed(__name__, e)
    pass

# HuggingFace 直连在部分网络下会超时（实测本机直连不通、镜像可达）。
# 语音识别首次使用要从 HF 下载模型，而 huggingface_hub 是在 import 时读取
# HF_ENDPOINT 的，所以必须在这里、在导入任何模块之前设好。
# 用 setdefault：你自己设过的 HF_ENDPOINT 永远优先。
# 想强制走官方源就设 HF_ENDPOINT=https://huggingface.co
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def _has_missing_deps():
    """返回缺失的依赖包列表（空列表=全部就绪）"""
    missing = []
    try:
        import PyQt5
    except ImportError:
        missing.append("PyQt5")
    try:
        import cryptography
    except ImportError:
        missing.append("cryptography")
    return missing


def _install_excepthook():
    """安装全局异常钩子"""
    def hook(exctype, value, tb):
        import traceback
        from datetime import datetime
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "crashes.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now()}] 崩溃: {exctype.__name__}: {value}\n")
            traceback.print_tb(tb, file=f)
        traceback.print_exception(exctype, value, tb)
    sys.excepthook = hook


def _validate_config():
    """校验配置"""
    try:
        from core.config import validate_config, load_config
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "config.json")
        cfg = load_config(cfg_path)
        result = validate_config(cfg)
        if not result.get("有效", True):
            print("配置校验警告: %s" % ", ".join(result.get("错误", [])))
    except Exception as e:
        print("配置校验失败: %s" % str(e)[:60])


if __name__ == "__main__":
    _missing = _has_missing_deps()
    if _missing:
        print("缺少依赖: " + ", ".join(_missing))
        sys.exit(1)
    _install_excepthook()
    _validate_config()

    # 崩溃 / 闪退自动上报：Python 层异常当场发；原生崩溃下次启动补发
    try:
        from core import auto_report
        auto_report.start(os.path.dirname(os.path.abspath(__file__)))
    except Exception as e:
        print("自动上报初始化失败: %s" % str(e)[:80])

    # Ollama预热 + 向量库预热：后台加载模型，提速
    import threading, urllib.request
    def warmup():
        try:
            # Ollama预热
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
            # 向量库预热：加载embedding模型
            try:
                import json
                req = urllib.request.Request(
                    "http://localhost:11434/api/embeddings",
                    data=json.dumps({"model": "nomic-embed-text", "prompt": "预热"}).encode(),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(req, timeout=5)
                print("向量库预热完成")
            except Exception as e:
                _x6_swallowed(__name__, e)
        except Exception as e:
            _x6_swallowed(__name__, e)
    threading.Thread(target=warmup, daemon=True).start()

    # 退出时清理资源（**必须注册在 run_pyqt 之前**：
    # run_pyqt 里 sys.exit 一抛，后面这段就永远执行不到 
    # 原来那份 atexit 其实一直是死代码）
    import atexit
    def _cleanup():
        try:
            # LGT-10: 真正调用trunk.shutdown()，向量库/记忆落盘
            import sys
            trunk = getattr(sys.modules.get("gui.main_window"), "_trunk", None)
            if trunk and hasattr(trunk, "shutdown"):
                trunk.shutdown()
            print("小6已退出，资源已清理")
        except Exception as e:
            _x6_swallowed(__name__, e)
    atexit.register(_cleanup)


    from gui.app_pyqt import run_pyqt
    run_pyqt()
    
