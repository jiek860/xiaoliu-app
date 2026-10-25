# -*- coding: utf-8 -*-
"""后台任务 / 模块按钮 / 可选组件安装相关方法。

从 gui/mixins/dialog_mixin.py 原样搬出（该文件接近 600 行上限）。
只搬代码不改行为：方法名与逻辑逐行一致，由 DialogMixin 继承。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os

from PyQt5.QtWidgets import QMessageBox, QInputDialog, QFileDialog

from gui.workers import TaskWorker, LearnWorker, BgWorker


class BackgroundTaskMixin:
    """后台任务启动、模块按钮分发、可选组件安装。"""

    def _bg_call(self, result, fn, label="处理"):
        result.setPlainText("▶ %s中，请稍候（后台执行，界面不卡）..." % label)
        w = BgWorker(fn)
        w.done.connect(lambda r: result.setPlainText(str(r)))
        self._bg_worker = w
        w.start()

    def _run_task_goal(self, result):
        goal, ok = QInputDialog.getText(
            self, "任务闭环",
            "输入要完成的目标（如：帮我写一个计算器脚本）:",
        )
        if not ok or not goal.strip():
            result.setPlainText("已取消")
            return
        result.setPlainText("▶ 任务闭环开始（拆步→子智能体执行→沙盒验证→评分），请稍候...")
        def fmt(r):
            if not isinstance(r, dict):
                return "返回异常: %s" % r
            lines = []
            if r.get("ok"):
                lines.append("✔ 任务完成")
                lines.append("步骤数: %d | 评分: %s" % (r.get("步骤数", 0), r.get("评分", "?")))
                for it in (r.get("明细") or [])[:5]:
                    lines.append("- %s | %s | %s" % (
                        it.get("步骤", "")[:25], it.get("agent", "?"), it.get("验证", "")[:20]))
            else:
                lines.append("✖ 未完成: %s" % r.get("原因", "未知"))
            return "\n".join(lines)
        self._task_worker = TaskWorker(self.trunk, goal.strip())
        self._task_worker.done.connect(lambda r: result.setPlainText(fmt(r)))
        self._task_worker.start()

    def _run_learn_one(self, result):
        result.setPlainText("▶ 学习闭环开始（搜索→提炼→入库），请稍候...")
        def fmt(r):
            if not isinstance(r, dict):
                return "返回异常: %s" % r
            lines = []
            if r.get("ok"):
                lines.append("✔ 学习完成")
                lines.append("方向: %s" % r.get("方向", ""))
                lines.append("主题: %s" % r.get("主题", ""))
                lines.append("入库: %d 条" % r.get("入库条数", 0))
                lines.append("累计轮次: %s" % r.get("累计轮次", 0))
            else:
                lines.append("✖ 未完成: %s" % r.get("原因", "未知"))
            return "\n".join(lines)
        self._learn_worker = LearnWorker(self.trunk)
        self._learn_worker.done.connect(lambda r: result.setPlainText(fmt(r)))
        self._learn_worker.start()

    def _export_backup_ui(self, result):
        dest = QFileDialog.getExistingDirectory(self, "选择导出目录（网盘/移动盘）")
        if not dest:
            result.setPlainText("已取消")
            return
        self._bg_call(result, lambda: self.trunk.call("backup", "export", dest), "导出备份")

    def _run_auto_update_ui(self, result):
        result.setPlainText("▶ 自更新闭环开始（取问题→建议→编程小匠→沙盒→确认→部署），请稍候...")
        def _fn():
            au = self.trunk.modules.get("auto_updater")
            if not au:
                self.trunk.call("auto_updater", "run")
                au = self.trunk.modules.get("auto_updater")
            if not au:
                return {"ok": False, "原因": "auto_updater 加载失败"}
            return au.run_auto_update()
        def fmt(r):
            if not isinstance(r, dict):
                return "返回异常: %s" % r
            lines = list(r.get("日志") or [])
            if r.get("ok"):
                lines.append("✔ 闭环完成 | 目标: %s | 备份: %s" % (
                    r.get("目标", ""), os.path.basename(r.get("备份", "?"))))
            else:
                lines.append("✖ 未完成: %s" % r.get("原因", "未知"))
            return "\n".join(lines)
        w = BgWorker(_fn)
        w.done.connect(lambda r: result.setPlainText(fmt(r) if isinstance(r, dict) else str(r)))
        self._au_worker = w
        w.start()

    def _module_button_clicked(self, module, action):
        if action.startswith("gui:"):
            fn = getattr(self, action[4:], None)
            if fn:
                fn()
                return
            QMessageBox.information(self, "模块按钮", "本地面板未找到: " + action)
            return
        r = self.trunk.call(module, action)
        if isinstance(r, dict):
            if r.get("ok") == False:
                err = r.get("error") or r.get("原因") or r.get("msg") or "未知错误"
                txt = f"「{module}」运行失败：\n{err[:200]}"
            else:
                txt = "\n".join("%s: %s" % (k, v) for k, v in r.items())
        else:
            txt = str(r)
        QMessageBox.information(self, module, txt[:2000])

    def _install_component(self, mod, pipname, status_label, btn):
        import sys as _sys
        btn.setEnabled(False)
        btn.setText("下载中…")
        opt_dir = os.path.join(self.base, "optional_libs")
        try:
            from pip._internal.cli.main import main as pip_main
            rc = pip_main([
                "install", "--quiet", "--disable-pip-version-check",
                "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                "--target", opt_dir, pipname,
            ])
            if rc == 0:
                if opt_dir not in _sys.path:
                    _sys.path.insert(0, opt_dir)
                for m in list(_sys.modules.keys()):
                    if m == mod or m.startswith(mod + "."):
                        del _sys.modules[m]
                try:
                    __import__(mod)
                    status_label.setText("✅ 已装")
                    status_label.setStyleSheet("color:green;")
                    btn.setText("已安装")
                except ImportError as e:
                    status_label.setText("⚠ 装完但 import 失败: " + str(e)[:50])
            else:
                status_label.setText("⚠ 安装失败(code=%d)" % rc)
                btn.setText("重试")
        except Exception as e:
            status_label.setText("⚠ " + str(e)[:80])
            btn.setText("重试")
        finally:
            btn.setEnabled(True)
