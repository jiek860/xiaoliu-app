# -*- coding: utf-8 -*-
"""本地模型管理 - 列出/下载/删除Ollama模型"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QProgressBar
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from gui.feedback_states import make_action_links


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
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            self.done.emit(True, "")
        except Exception as e:
            self.done.emit(False, str(e)[:80])


class ModelManagerDialog(QDialog):
    """本地模型管理对话框"""
    # 子线程取完数据后用它把结果送回 GUI 线程 —— Qt 不允许在子线程碰控件
    modelsReady = pyqtSignal(object, str)

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("本地模型管理")
        self.setMinimumSize(640, 520)
        self._build_ui()
        # 异步刷新：requests.get 有 5 秒超时，直接在 __init__ 里调会让对话框
        # 弹出来是僵的。但子线程只能取数据，控件更新必须回到 GUI 线程做。
        self.modelsReady.connect(self._apply_models)
        self.msg.setText("正在加载模型列表...")
        self._refresh_async()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("📦 本地模型管理（Ollama）")
        title.setStyleSheet("font-size:16px;font-weight:bold;padding:6px;")
        layout.addWidget(title)

        self.model_summary = QLabel("硬件与路由信息加载中")
        self.model_summary.setWordWrap(True)
        self.model_summary.setStyleSheet(
            "background:#f7f9fc;border:1px solid #e2e8f0;border-radius:6px;"
            "padding:8px;color:#334155;")
        layout.addWidget(self.model_summary)
        try:
            from core.model_registry import ModelRegistry
            reg = ModelRegistry(self.trunk)
            hw = reg.hardware_profile()
            route = reg.route_plan()
            self.model_summary.setText(
                "内存：%s GB　GPU：%s\n推荐模型：%s\n路由模式：%s　回退链：%s"
                % (hw.get("ram_gb", "?"),
                   " / ".join(hw.get("gpu", [])) or "未检测到 NVIDIA GPU",
                   "、".join(hw.get("recommended", [])[:5]) or "无",
                   route.get("mode", ""),
                   "  ".join([x for x in route.get("fallback", []) if x])))
        except Exception as e:  # 静默是故意的 - 概览失败不影响模型列表
            self.model_summary.setText("模型概览加载失败: " + str(e)[:80])

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
        # 「删除选中」是破坏性低频动作 → 链接（带确认框）
        row.addWidget(make_action_links([("删除选中", self._delete)]))
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

    def _fetch_models(self):
        """只取数据，不碰任何 Qt 控件 —— 所以可以在子线程里跑。

        返回 (models, err)：models 是 [(名字, 大小GB), ...]，err 非空表示失败。
        """
        try:
            import requests
            url = self._base_url().rstrip("/") + "/api/tags"
            r = requests.get(url, timeout=5)
            out = []
            for m in r.json().get("models", []):
                out.append((m.get("name", "?"),
                            m.get("size", 0) / 1024 / 1024 / 1024))
            return out, ""
        except Exception as e:
            return [], "Ollama 未启动或无法连接: " + str(e)[:60]

    def _apply_models(self, models, err):
        """更新控件 —— 只能在 GUI 线程调用（子线程通过 modelsReady 信号进来）"""
        self.list_w.clear()
        if err:
            self.msg.setText("❌ " + err)
            return
        for name, size in models:
            item = QListWidgetItem("%s  (%.2f GB)" % (name, size))
            item.setData(Qt.UserRole, name)
            self.list_w.addItem(item)
        self.msg.setText("共 %d 个模型" % len(models))

    def _refresh(self):
        """同步刷新（主线程用：删完 / 下完模型之后）"""
        models, err = self._fetch_models()
        self._apply_models(models, err)

    def _refresh_async(self):
        """异步刷新（打开对话框时用，避免卡 5 秒）"""
        import threading

        def work():
            models, err = self._fetch_models()      # 子线程：只取数据
            self.modelsReady.emit(models, err)      # 信号排队回 GUI 线程

        threading.Thread(target=work, daemon=True).start()

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
