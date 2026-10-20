# -*- coding: utf-8 -*-
"""生命周期混入：关闭清理、事件过滤、确认弹窗"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import QMessageBox, QCheckBox


class LifecycleMixin:
    """生命周期相关方法"""
    def _safe_stop_workers(self):
        for name in ("worker", "_task_worker", "_learn_worker",
                     "_au_worker", "_tts_worker", "_bg_worker"):
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                if w.isRunning():
                    w.requestInterruption()
                    w.wait(200)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            for sig in ("done", "token", "result"):
                try:
                    s = getattr(w, sig, None)
                    if s is not None:
                        s.disconnect()
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

    def closeEvent(self, e):
        try:
            if getattr(self, "window_state", None) is not None:
                self.window_state.save(self)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            self._safe_stop_workers()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        e.accept()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "input", None):
            if event.type() == QEvent.KeyPress:
                if event.key() in (16777220, 16777221):    # Enter / Return
                    if not (event.modifiers() & Qt.ShiftModifier):
                        try:
                            self.send()
                        except Exception as e:
                            from core.logger import get_logger
                            get_logger().error("Enter 触发 send 失败: %s" % e)
                        return True
                if event.modifiers() & Qt.ControlModifier and event.key() == 76:
                    self.chat.clear()
                    return True
            elif event.type() == QEvent.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Drop:
                for url in event.mimeData().urls():
                    fp = url.toLocalFile()
                    if fp and os.path.isfile(fp):
                        self._dropped_file = fp
                        self.input.setPlaceholderText(
                            "已选文件: " + os.path.basename(fp) + "，输入内容后发送"
                        )
                        break
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def _confirm_wait(self, action, detail):
        self._confirm_evt.clear()
        self._confirm_result["ok"] = False
        self.confirmRequested.emit(action, detail)
        self._confirm_evt.wait(120)
        return self._confirm_result.get("ok", False)

    def _confirm_scope_wait(self, action, detail):
        self._confirm_evt.clear()
        self._confirm_result["ok"] = False
        self._confirm_result["scope"] = None
        self.confirmScopeRequested.emit(action, detail)
        self._confirm_evt.wait(120)
        return self._confirm_result.get("scope")

    def _ask_confirm_scope(self, action, detail):
        box = QMessageBox(self)
        box.setWindowTitle("确认操作")
        box.setIcon(QMessageBox.Question)
        box.setText("要执行这个操作吗？")
        box.setInformativeText("操作: %s\n详情: %s" % (action, detail))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        cb = QCheckBox("本次运行内不再询问同类操作")
        box.setCheckBox(cb)
        permanent = box.addButton("永久允许", QMessageBox.AcceptRole)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is permanent:
            scope = "always"
        elif clicked == box.button(QMessageBox.Yes):
            scope = "session" if cb.isChecked() else "once"
        else:
            scope = None
        self._confirm_result["ok"] = scope is not None
        self._confirm_result["scope"] = scope
        self._confirm_evt.set()

    def _ask_confirm(self, action, detail):
        r = QMessageBox.question(
            self, "确认操作",
            f"要执行这个操作吗？\n\n操作: {action}\n详情: {detail}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        self._confirm_result["ok"] = (r == QMessageBox.Yes)
        self._confirm_evt.set()
