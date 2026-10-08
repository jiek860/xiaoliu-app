# -*- coding: utf-8 -*-
"""生命周期混入：关闭清理、事件过滤、确认弹窗"""
import os
import json
import threading
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import QMessageBox


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
            except Exception:
                pass
            for sig in ("done", "token", "result"):
                try:
                    s = getattr(w, sig, None)
                    if s is not None:
                        s.disconnect()
                except Exception:
                    pass

    def closeEvent(self, e):
        threading.Thread(target=self._flush_pending_embeddings, daemon=True).start()
        try:
            self._safe_stop_workers()
        except Exception:
            pass
        e.accept()

    def _flush_pending_embeddings(self):
        try:
            import requests
            dp = os.path.join(self.base, "data", "vectors.json")
            ep = os.path.join(self.base, "data", "embeddings.json")
            if not (os.path.exists(dp) and os.path.exists(ep)):
                return
            data = json.load(open(dp, encoding="utf-8"))
            emb = json.load(open(ep, encoding="utf-8"))
            need = len(data) - len(emb)
            if need <= 0:
                return
            url = self.trunk.config.get("ollama_url", "http://localhost:11434")
            for i in range(len(emb), len(data)):
                text = data[i].get("text", "")[:500]
                r = requests.post(
                    url + "/api/embeddings",
                    json={"model": "nomic-embed-text", "prompt": text},
                    timeout=2,
                )
                v = r.json().get("embedding", [])
                if v:
                    emb[str(i)] = v
            json.dump(emb, open(ep, "w", encoding="utf-8"))
        except Exception as ex:
            try:
                self.trunk._log(f"关程序补嵌入失败: {ex}")
            except Exception:
                pass

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

    def _ask_confirm(self, action, detail):
        r = QMessageBox.question(
            self, "确认操作",
            f"要执行这个操作吗？\n\n操作: {action}\n详情: {detail}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        self._confirm_result["ok"] = (r == QMessageBox.Yes)
        self._confirm_evt.set()
