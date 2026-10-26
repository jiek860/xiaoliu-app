# -*- coding: utf-8 -*-
"""Skills 管理对话框：列出所有技能，启用/禁用/删除"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QListWidgetItem,
                             QMessageBox, QMenu, QInputDialog)
from PyQt5.QtCore import Qt

from gui.feedback_states import make_action_links


class SkillsDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("📚 技能管理")
        self.resize(700, 500)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("所有技能（点击勾选 = 启用）："))

        self.list = QListWidget()
        self.list.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        more = QPushButton("更多操作")
        more.clicked.connect(self._show_actions)
        row.addWidget(more)
        # 导入 / 导出 / 关闭都是低频入口 → 链接，只留「更多操作」一个按钮
        row.addWidget(make_action_links([
            ("导入", self._import_skill),
            ("导出", self._export_skill),
            ("关闭", self.close),
        ]))
        row.addStretch(1)
        row.addWidget(QLabel("Esc 关闭"))
        lay.addLayout(row)

    def _show_actions(self):
        """低频操作收进菜单，避免一排按钮把界面撑满。"""
        menu = QMenu(self)
        menu.addAction("刷新", self._refresh)
        menu.addAction("从市场安装", self._install_market_skill)
        menu.addAction("确认选中", self._confirm_skill)
        menu.addAction("拒绝选中", self._reject_skill)
        menu.addAction("删除选中", self._delete_selected)
        anchor = self.sender() or self
        menu.exec_(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _get_registry(self):
        from core.skill_registry import SkillRegistry
        return SkillRegistry(self.trunk)

    def _refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        try:
            reg = self._get_registry()
            skills = reg.list_all()
            for s in skills:
                src_tag = {"zip": "📦", "captured": "✅", "pending": "⏳"}.get(s["source"], "?")
                it = QListWidgetItem("%s %s [%s]" % (src_tag, s["name"], s["source"]))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if s["enabled"] else Qt.Unchecked)
                it.setData(Qt.UserRole, s["name"])
                self.list.addItem(it)
        except Exception as e:
            _x6_swallowed(__name__, e)
        finally:
            self.list.blockSignals(False)

    def _on_item_changed(self, item):
        name = item.data(Qt.UserRole)
        if not name:
            return
        try:
            reg = self._get_registry()
            if item.checkState() == Qt.Checked:
                reg.enable(name)
            else:
                reg.disable(name)
        except Exception as e:
            _x6_swallowed(__name__, e)

    def _import_skill(self):
        """导入 .x6skill 包"""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择 .x6skill 文件", "", "Skill 包 (*.x6skill)")
        if not path:
            return
        try:
            reg = self._get_registry()
            r = reg.install_from_file(path)
            if r.get("ok"):
                QMessageBox.information(self, "成功", "导入成功: " + r.get("name", ""))
                self._refresh()
            else:
                QMessageBox.warning(self, "失败", r.get("error", "未知错误"))
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e)[:200])

    def _export_skill(self):
        """导出选中的技能为 .x6skill 包"""
        it = self.list.currentItem()
        if not it:
            QMessageBox.information(self, "提示", "请先选一个技能")
            return
        name = it.data(Qt.UserRole)
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "保存技能包", name + ".x6skill", "Skill 包 (*.x6skill)")
        if not path:
            return
        try:
            reg = self._get_registry()
            r = reg.export_to_file(name, path)
            if r.get("ok"):
                QMessageBox.information(self, "成功", "导出成功: " + path)
            else:
                QMessageBox.warning(self, "失败", r.get("error", "未知错误"))
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e)[:200])

    def _install_market_skill(self):
        """从本地/远程技能目录选择一个技能安装。"""
        try:
            from core.skills_market import fetch_remote_catalog, download_skill
            catalog = fetch_remote_catalog()
            if not catalog.get("ok"):
                QMessageBox.warning(self, "技能市场", catalog.get("error", "目录不可用"))
                return
            items = catalog.get("skills") or []
            labels = ["%s — %s" % (s.get("title") or s.get("name"),
                                   s.get("desc") or "") for s in items]
            if not labels:
                QMessageBox.information(self, "技能市场", "目录里没有技能")
                return
            label, ok = QInputDialog.getItem(
                self, "技能市场", "选择要安装的技能：", labels, 0, False)
            if not ok:
                return
            item = items[labels.index(label)]
            result = download_skill(item["name"])
            if not result.get("ok"):
                QMessageBox.warning(self, "安装失败", result.get("error", "下载失败"))
                return
            reg = self._get_registry()
            r = reg.install_from_file(result["zip_path"])
            try:
                import os
                if result.get("zip_path"):
                    os.remove(result["zip_path"])
            except OSError:  # 静默是故意的：临时包清理失败不影响已完成的安装
                pass
            if r.get("ok"):
                QMessageBox.information(self, "成功", "已安装: " + item["name"])
                self._refresh()
            else:
                QMessageBox.warning(self, "安装失败", r.get("error", "未知错误"))
        except Exception as e:
            QMessageBox.warning(self, "技能市场", str(e)[:200])

    def _confirm_skill(self):
        """确认选中的待确认技能"""
        it = self.list.currentItem()
        if not it:
            QMessageBox.information(self, "提示", "请先选一个待确认的技能")
            return
        name = it.data(Qt.UserRole)
        try:
            sc = self.trunk.modules.get("skill_capture") if self.trunk else None
            if sc is None and self.trunk is not None:
                try:
                    sc = self.trunk._load_lazy("skill_capture")
                except Exception:
                    sc = None
            if sc and hasattr(sc, "confirm_skill"):
                r = sc.confirm_skill(name)
                if r.get("已确认"):
                    QMessageBox.information(self, "成功", "已确认: " + name)
                    self._refresh()
                else:
                    QMessageBox.warning(self, "失败", r.get("错误", "未知错误"))
            else:
                QMessageBox.warning(self, "失败", "skill_capture 未加载")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e)[:200])

    def _reject_skill(self):
        """拒绝选中的待确认技能"""
        it = self.list.currentItem()
        if not it:
            QMessageBox.information(self, "提示", "请先选一个待确认的技能")
            return
        name = it.data(Qt.UserRole)
        try:
            sc = self.trunk.modules.get("skill_capture") if self.trunk else None
            if sc is None and self.trunk is not None:
                try:
                    sc = self.trunk._load_lazy("skill_capture")
                except Exception:
                    sc = None
            if sc and hasattr(sc, "reject_skill"):
                r = sc.reject_skill(name)
                if r.get("已拒绝"):
                    QMessageBox.information(self, "成功", "已拒绝: " + name)
                    self._refresh()
                else:
                    QMessageBox.warning(self, "失败", r.get("错误", "未知错误"))
            else:
                QMessageBox.warning(self, "失败", "skill_capture 未加载")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e)[:200])

    def _delete_selected(self):
        it = self.list.currentItem()
        if not it:
            return
        name = it.data(Qt.UserRole)
        if QMessageBox.question(self, "确认", "删除技能「%s」？" % name,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            reg = self._get_registry()
            reg.delete(name)
            self._refresh()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e)[:100])
