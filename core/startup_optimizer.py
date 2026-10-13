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
        """预编译所有pyc文件，加快二次启动

        两个坑都在这里修掉了（2026-10-13 审计 + 测试发现）：
          ① 编译失败的文件原来被静默跳过 —— 用户既不知道，下次启动也还是慢
          ② 更要紧的是 `doraise=False` **根本不抛异常**：它把 SyntaxError
             打到 stderr 就返回 None，于是 `except` 永远不触发，
             `count += 1` 反而**把编不过的文件也算成成功了**
             （测试实测：一个正常文件 + 一个语法错文件，返回 {'预编译文件': 2}）
        """
        count = 0
        failed = []                   # [(文件, 原因)]
        for d in ("core", "gui", "modules/installed"):
            for f in glob.glob(os.path.join(self.base, d, "*.py")):
                try:
                    # doraise=True 才会真的抛出来，改成 False 就又回到坑里了
                    py_compile.compile(f, doraise=True)
                    count += 1
                except Exception as e:
                    failed.append((os.path.basename(f),
                                   "%s: %s" % (type(e).__name__,
                                               str(e)[:60])))
        r = {"预编译文件": count}
        if failed:
            r["失败"] = len(failed)
            r["失败明细"] = ["%s（%s）" % (n, why) for n, why in failed[:8]]
            r["说明"] = ("有 %d 个文件没能预编译（上面列了前 8 个）—— "
                         "这些文件下次启动会现编译，稍微慢一点" % len(failed))
        return r

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
