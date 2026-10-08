# -*- coding: utf-8 -*-
"""v26-5.4: 启动速度优化 完整版"""
import os, py_compile, glob, time


class StartupOptimizer:
    """启动优化：预编译+启动画面"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.t0 = time.time()

    def precompile(self):
        """预编译所有pyc文件，加快二次启动"""
        count = 0
        for d in ("core", "gui", "modules/installed"):
            for f in glob.glob(os.path.join(self.base, d, "*.py")):
                try:
                    py_compile.compile(f, doraise=False)
                    count += 1
                except Exception:
                    pass
        return {"预编译文件": count}

    def elapsed(self):
        """启动耗时"""
        return round(time.time() - self.t0, 2)

    def show_splash(self):
        """显示启动画面（在app_pyqt里调用）"""
        from PyQt5.QtWidgets import QSplashScreen, QLabel
        from PyQt5.QtGui import QPixmap, QFont
        from PyQt5.QtCore import Qt
        pix = QPixmap(400, 200)
        pix.fill(Qt.white)
        splash = QSplashScreen(pix)
        splash.showMessage("小6智能体 启动中...", Qt.AlignCenter, Qt.black)
        font = QFont("Microsoft YaHei", 14)
        splash.setFont(font)
        splash.show()
        return splash

    def run(self, *a):
        return {"启动耗时": self.elapsed(), **self.precompile()}
