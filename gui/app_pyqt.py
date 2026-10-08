# -*- coding: utf-8 -*-
"""小6智能助手 - 启动入口"""
import sys
import os
import traceback

# 与 run.py 保持一致：语音模型下载走镜像（huggingface_hub 在 import 时读 HF_ENDPOINT，
# 所以必须放在任何相关导入之前）。自己设过的 HF_ENDPOINT 优先。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 依赖目录（与 run.py 保持一致，保证直接双击本文件启动也找得到）：
#   libs/           核心随包库（numpy / requests 等）
#   optional_libs/  可选功能库（torch / cv2 / whisper，按需安装）
# 插入顺序反过来做，最终 sys.path 为 [项目根, libs, optional_libs, ...]，
# 这样 import core.* 一定走项目代码，核心库也优先于可选库。
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_base, "optional_libs"), os.path.join(_base, "libs")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)
if _base not in sys.path:
    sys.path.insert(0, _base)

# ⚠️ 必须在任何 Qt 导入之前：PyQt5 自带旧版 MSVCP140.dll，会挡住 torch 的 c10.dll
# （WinError 1114）。详见 core/win_dll_fix.py
try:
    from core.win_dll_fix import preload_msvc_runtime
    preload_msvc_runtime()
except Exception:
    pass

# ===== 核心依赖检查（缺依赖时给人话提示，不抛一堆traceback） =====
import importlib.util as _ilu
_REQUIRED = {
    "PyQt5": "PyQt5",
    "requests": "requests",
    "numpy": "numpy",
    "cryptography": "cryptography",
    "psutil": "psutil",
}
def _check_deps():
    missing = []
    for mod, pkg in _REQUIRED.items():
        try:
            if _ilu.find_spec(mod) is None:
                missing.append(pkg)
        except (ImportError, ValueError):
            missing.append(pkg)
    if missing:
        msg = (
            "\n========================================\n"
            "  小6智能体 启动失败：缺少核心依赖\n"
            "========================================\n\n"
            "缺少的包：\n  " + "\n  ".join(missing) + "\n\n"
            "请双击项目根目录的 install.bat 自动安装，或在命令行执行：\n\n"
            "  pip install -r requirements.txt\n\n"
            "如果pip很慢，用清华镜像：\n\n"
            "  pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple\n\n"
            "按回车键退出...\n"
        )
        print(msg)
        try:
            input()
        except Exception:
            pass
        sys.exit(1)
_check_deps()
# ===== 依赖检查结束 =====


def _crash_hook(exc_type, exc_value, exc_tb):
    try:
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "logs",
        )
        os.makedirs(log_dir, exist_ok=True)
        from datetime import datetime
        with open(os.path.join(log_dir, "gui_crashes.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] GUI崩溃: {exc_type.__name__}: {exc_value}\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
            f.write("\n")
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _crash_hook


def run_pyqt():
    """入口：DPI + 高DPI图标 + 主窗口"""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("小6智能助手")
    from gui.main_window import JarvisWindow
    w = JarvisWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    run_pyqt()


