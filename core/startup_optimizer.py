# -*- coding: utf-8 -*-
"""v26-5.4: 启动速度优化（完整版）

做什么
------
把 ``core`` / ``gui`` / ``modules/installed`` 下的 ``.py`` 预编译成 ``.pyc``，
第二次启动就不用再现场编译。

两个坑（2026-10-13 审计 + 测试发现，这里都已修掉）
--------------------------------------------------
① ``doraise=False`` **根本不抛异常**：它把 SyntaxError 打到 stderr 就返回
   ``None``，于是 ``except`` 永远不触发，``count += 1`` 反而**把编不过的
   文件也算成成功了**（测试实测：1 个正常 + 1 个语法错，返回 ``{'预编译文件': 2}``）。
   现在用 ``doraise=True``。
② 编不过的文件原来被静默跳过 —— 用户既不知道，下次启动也还是慢。
   现在失败**计数 + 明细**一起返回，并落盘到 ``data/precompile_failures.json``，
   下次启动/自检能顺着文件把坏文件找出来。

目录扫描（2026-11-02 补）
-------------------------
``base`` 不对（测试临时目录、绿色版挪过位置）时原来一个字也不报，返回
``{'预编译文件': 0}``，看着像"没文件要编"而不是"路径错了"。现在返回
``说明: 没找到可预编译的目录（base 不对？）`` 并把实际扫过的目录列出来。
"""
import glob
import json
import os
import py_compile
import time

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)


try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

SCAN_DIRS = ("core", "gui", "modules/installed")


class StartupOptimizer:
    """启动优化：预编译 + 启动画面"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.t0 = time.time()
        self.last_failures = []

    # ------------------------------------------------------------------
    def _save_failures(self, failed):
        """把编译失败明细落到 ``data/precompile_failures.json``。

        落盘失败**不能**让 precompile 整个失败：返回值里已经有一份明细，
        文件只是给下次启动/自检看的备份。
        """
        if not failed:
            return None
        path = data_path(self.trunk, "precompile_failures.json")
        rows = [{"文件": name, "原因": why} for name, why in failed]
        payload = {"时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "失败数": len(rows), "失败明细": rows}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return path
        except Exception as e:
            _x6_swallowed(__name__, e, "precompile failures save")
            return None

    def precompile(self, dirs=None):
        """预编译 ``dirs``（默认 SCAN_DIRS）下的 .py，返回结构化结果。

        返回：
            {"预编译文件": n, "扫描目录": [...]}
            可选 "失败": m、"失败明细": [...]、"失败明细文件": 路径 | "落盘失败"
            可选 "说明"（失败 / 没找到目录 / 没有可编译文件）
        """
        names = SCAN_DIRS if dirs is None else tuple(dirs)
        scanned, count, failed = [], 0, []
        for name in names:
            folder = os.path.join(self.base, name)
            if not os.path.isdir(folder):
                continue
            scanned.append(name)
            for path in sorted(glob.glob(os.path.join(folder, "*.py"))):
                try:
                    # doraise=True 才会真的抛出来，改回 False 就又回到坑①
                    py_compile.compile(path, doraise=True)
                    count += 1
                except Exception as e:
                    failed.append((os.path.basename(path),
                                   "%s: %s" % (type(e).__name__,
                                               str(e)[:60])))
        self.last_failures = failed

        r = {"预编译文件": count, "扫描目录": scanned}
        if not scanned:
            r["说明"] = "没找到可预编译的目录（base 不对？）：%s" % str(self.base)
            return r
        if failed:
            r["失败"] = len(failed)
            r["失败明细"] = ["%s（%s）" % (n, why) for n, why in failed[:8]]
            saved = self._save_failures(failed)
            r["失败明细文件"] = saved or "落盘失败"
            r["说明"] = ("有 %d 个文件没能预编译（上面列了前 8 个）—— "
                         "这些文件下次启动会现编译，稍微慢一点" % len(failed))
        elif count == 0:
            r["说明"] = "目录里没有 .py 文件可预编译"
        return r

    # ------------------------------------------------------------------
    def elapsed(self):
        """启动耗时（秒）"""
        return round(time.time() - self.t0, 2)

    def show_splash(self):
        """显示启动画面（在 app_pyqt 里调用）"""
        from PyQt5.QtWidgets import QSplashScreen
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
        r = {"启动耗时": self.elapsed()}
        r.update(self.precompile())
        return r
