# -*- coding: utf-8 -*-
"""本地模型管理 - 列出/下载/删除Ollama模型"""
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QProgressBar
from PyQt5.QtCore import Qt, QThread, pyqtSignal


class PullWorker(QThread):
    """后台下载模型"""
    progress = pyqtSignal(str, int, int)
    done = pyqtSignal(bool, str)

    def __init__(self, base_url, name):
        super().__init__()
        self.base_url = base_url
        self.name = name

    def run(self):
        import requests, json
        try:
            url = self.base_url.rstrip("/") + "/api/pull"
            r = requests.post(url, json={"name": self.name}, stream=True, timeout=3600)
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    self.progress.emit(
                        d.get("status", ""),
                        d.get("completed", 0),
                        d.get("total", 0)
                    )
                    if d.get("status") == "success":
                        self.done.emit(True, "")
                        return
                except Exception:
                    pass
            self.done.emit(True, "")
        except Exception as e:
            self.done.emit(False, str(e)[:80])


class ModelManagerDialog(QDialog):
    """本地模型管理对话框"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("本地模型管理")
        self.setMinimumSize(640, 520)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("📦 本地模型管理（Ollama）")
        title.setStyleSheet("font-size:16px;font-weight:bold;padding:6px;")
        layout.addWidget(title)

        # 模型列表
        layout.addWidget(QLabel("已安装模型:"))
        self.list_w = QListWidget()
        layout.addWidget(self.list_w, stretch=1)

        # 下载行
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入模型名，如 qwen2.5:7b")
        row.addWidget(self.input)
        btn_pull = QPushButton("下载")
        btn_pull.clicked.connect(self._pull)
        row.addWidget(btn_pull)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_del)
        layout.addLayout(row)

        # 进度条
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

        # 状态
        self.msg = QLabel("")
        layout.addWidget(self.msg)

    def _base_url(self):
        cfg = getattr(self.trunk, "config", {}) or {}
        return cfg.get("ollama_url", "http://localhost:11434")

    def _refresh(self):
        """刷新模型列表"""
        self.list_w.clear()
        try:
            import requests
            url = self._base_url().rstrip("/") + "/api/tags"
            r = requests.get(url, timeout=5)
            models = r.json().get("models", [])
            for m in models:
                name = m.get("name", "?")
                size = m.get("size", 0) / 1024 / 1024 / 1024
                item = QListWidgetItem("%s  (%.2f GB)" % (name, size))
                item.setData(Qt.UserRole, name)
                self.list_w.addItem(item)
            self.msg.setText("共 %d 个模型" % len(models))
        except Exception as e:
            self.msg.setText("❌ Ollama 未启动或无法连接: " + str(e)[:60])

    def _pull(self):
        name = self.input.text().strip()
        if not name:
            QMessageBox.information(self, "提示", "请输入模型名")
            return
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.msg.setText("下载中: " + name)
        self.worker = PullWorker(self._base_url(), name)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_progress(self, status, completed, total):
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(completed / total * 100))
        self.msg.setText("下载中: " + status)

    def _on_done(self, ok, err):
        self.bar.setVisible(False)
        if ok:
            self.msg.setText("✅ 下载完成")
        else:
            self.msg.setText("❌ 下载失败: " + err)
        self._refresh()

    def _delete(self):
        item = self.list_w.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        if QMessageBox.question(
            self, "确认删除", "确定删除模型 " + name + " ?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            import requests
            url = self._base_url().rstrip("/") + "/api/delete"
            r = requests.delete(url, json={"name": name}, timeout=10)
            if r.status_code == 200:
                self.msg.setText("✅ 已删除 " + name)
            else:
                self.msg.setText("❌ 删除失败")
        except Exception as e:
            self.msg.setText("❌ 删除失败: " + str(e)[:60])
        self._refresh()
