# -*- coding: utf-8 -*-
"""小6智能助手 - 启动入口"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

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

# 看门狗模式：只等主进程退出并补发日志，不加载 Qt
if __name__ == "__main__" and "--watchdog" in sys.argv:
    try:
        from core.crash_watchdog import main as _watchdog_main
        sys.exit(_watchdog_main(sys.argv))
    except Exception:
        sys.exit(0)

# ⚠️ 必须在任何 Qt 导入之前：PyQt5 自带旧版 MSVCP140.dll，会挡住 torch 的 c10.dll
# （WinError 1114）。详见 core/win_dll_fix.py
try:
    from core.win_dll_fix import preload_msvc_runtime
    preload_msvc_runtime()
except Exception as e:
    _x6_swallowed(__name__, e)
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
        except Exception as e:
            _x6_swallowed(__name__, e)
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
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _crash_hook


def _resolve_startup(startup):
    """拿到计时器；传进来的优先，没有就 import 一个（失败返回 None）。"""
    if startup is not None:
        return startup
    try:
        from core import startup as mod
        return mod
    except Exception as e:  # 静默是故意的 - 计时器坏了不该挡住启动
        _x6_swallowed(__name__, e, "best-effort fallback")
        return None


def _make_boot_callbacks(window, startup):
    """构造 BootController 用的两个回调（进度 / 完成）。

    抽成独立函数是为了能单测：真跑 run_pyqt 会进 app.exec_()，测试里起不来事件循环。
    """
    def on_progress(text):
        try:
            window.statusBar().showMessage(text, 5000)
            ph = getattr(window, "_boot_placeholder", None)
            if ph is not None:
                ph.setText(text)
        except Exception as e:  # 静默是故意的 - 状态栏/占位页缺失不影响启动
            _x6_swallowed(__name__, e, "best-effort fallback")

    def on_finished(ok, message):
        try:
            ph = getattr(window, "_boot_placeholder", None)
            if ph is not None:
                ph.deleteLater()
                window._boot_placeholder = None
                window.setCentralWidget(None)
        except Exception as e:  # 静默是故意的 - 占位页已销毁就跳过
            _x6_swallowed(__name__, e, "best-effort fallback")
        if startup is not None:
            startup.mark("启动完成" if ok else "启动失败")
            try:
                print(startup.log_summary(getattr(window, "trunk", None)))
            except Exception as e:  # 静默是故意的 - 日志失败不影响启动
                _x6_swallowed(__name__, e, "best-effort fallback")
        if not ok:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(window, "启动失败",
                                 "核心模块没有加载成功：\n" + str(message)[:400])
        else:
            try:
                window.statusBar().showMessage("已就绪", 3000)
            except Exception as e:  # 静默是故意的 - 没有状态栏就算了
                _x6_swallowed(__name__, e, "best-effort fallback")

    return on_progress, on_finished


def run_pyqt(startup=None):
    """入口：DPI + 高DPI图标 + 主窗口

    顺序说明（决定"能不能秒开"）：
      ① QApplication 最先建 —— 越早建，Windows 越早显示窗口框架
      ② 看门狗/自动上报在 Qt 之前就已经由 run.py 拉起（幂等）
      ③ JarvisWindow 内部把 Trunk 初始化和后台服务继续往后排
    """
    startup = _resolve_startup(startup)
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("小6智能助手")
    if startup is not None:
        startup.mark("QApplication 就绪")

    # 崩溃 / 闪退自动上报（直接双击本文件启动时也生效；start 是幂等的）
    try:
        from core import auto_report
        auto_report.start(_base)
        if startup is not None:
            startup.mark("自动上报就绪")
    except Exception as e:
        print("自动上报初始化失败: %s" % str(e)[:80])
    from gui.main_window import JarvisWindow
    if startup is not None:
        startup.mark("主窗口模块导入")

    # 秒开策略：boot_signal=False 时窗口只建"空骨架"立刻显示，
    # 真正的 Trunk 初始化交给 BootController 在事件循环之后跑。
    # 环境变量 X6_BLOCKING_BOOT=1 可退回"全部就绪才显示"的旧行为（排查用）。
    blocking = os.environ.get("X6_BLOCKING_BOOT") == "1"
    w = JarvisWindow(startup=startup, boot_signal=blocking)
    if startup is not None:
        startup.mark("主窗口构造完成")
    w.show()
    if startup is not None:
        startup.mark("界面已显示")

    if not blocking:
        from gui.boot_controller import BootController
        boot = BootController(w, startup=startup)
        w._boot_controller = boot
        on_progress, on_finished = _make_boot_callbacks(w, startup)
        boot.progress.connect(on_progress)
        boot.finished.connect(on_finished)
        boot.start(delay_ms=0)
    else:
        if startup is not None:
            try:
                print(startup.log_summary(getattr(w, "trunk", None)))
            except Exception as e:  # 静默是故意的 - 日志失败不影响启动
                _x6_swallowed(__name__, e, "best-effort fallback")
    sys.exit(app.exec_())


if __name__ == "__main__":
    run_pyqt()


