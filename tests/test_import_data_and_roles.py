# -*- coding: utf-8 -*-
"""S1 回归：导入数据只走安全迁移入口；群聊角色入口必须真的能打开。

第二轮体检（2026-11-02）确认的两个真问题：

1. ``gui/mixins/system_mixin.import_data`` 用 ``z.extractall(self.base)``，
   包里写一个 ``../core/evil.py`` 就能覆盖程序文件（zip slip），
   而提示文案只说"覆盖 data/"。
2. ``gui/roles_dialog.RolesDialog`` 写好了却没有任何入口：
   ``core/feature_registry`` 登记了 ``roles``（action="roles_dialog"），
   主窗口没有这个同名方法，``getattr`` 拿到 None 后被 ``callable()``
   挡掉 —— 「群聊角色」静默消失，不报错。
"""
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


class _Trunk:
    def __init__(self, base):
        self.base = base


def _owner(base):
    from gui.mixins.system_mixin import SystemMixin

    class Owner(SystemMixin):
        pass

    o = Owner()
    o.trunk = _Trunk(base)
    o.base = base
    return o


class _FakeMessageBox:
    Yes = 0x4000
    No = 0
    asked, info, warn = [], [], []

    @classmethod
    def question(cls, parent, title, text, *a, **k):
        cls.asked.append(text)
        return cls.Yes

    @classmethod
    def information(cls, parent, title, text, *a, **k):
        cls.info.append(text)

    @classmethod
    def warning(cls, parent, title, text, *a, **k):
        cls.warn.append(text)


def test_import_data_goes_through_safe_migration(monkeypatch, tmp_path):
    """覆盖现有数据要先确认，越界成员被拦下，正常成员照常恢复。"""
    import gui.mixins.system_mixin as mod

    base = str(tmp_path)
    os.makedirs(os.path.join(base, "data"), exist_ok=True)
    existing = os.path.join(base, "data", "config.json")
    with open(existing, "w", encoding="utf-8") as f:
        f.write('{"old": 1}')

    pkg = _zip(str(tmp_path / "pack.zip"), {
        "data/config.json": '{"new": 2}',
        "data/new_file.json": "{}",
        "../evil.txt": "pwned",
    })

    _FakeMessageBox.asked.clear()
    _FakeMessageBox.info.clear()
    _FakeMessageBox.warn.clear()
    monkeypatch.setattr(mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (pkg, "")))
    monkeypatch.setattr(mod, "QMessageBox", _FakeMessageBox)

    _owner(base).import_data()

    assert _FakeMessageBox.asked, "会覆盖现有文件时必须先让用户确认"
    assert "config.json" in _FakeMessageBox.asked[0]
    assert not _FakeMessageBox.warn, "确认+恢复成功后不该再弹失败"
    assert _FakeMessageBox.info and "已恢复" in _FakeMessageBox.info[-1]
    # 越界成员被安全规则拦下（报出来），但没写到程序外面
    assert "evil.txt" in _FakeMessageBox.info[-1]
    assert not os.path.exists(os.path.join(base, "evil.txt"))
    assert not os.path.exists(os.path.join(os.path.dirname(base), "evil.txt"))
    with open(existing, encoding="utf-8") as f:
        assert f.read().strip() == '{"new": 2}'


def test_import_data_cancel_writes_nothing(monkeypatch, tmp_path):
    """确认框选「否」时一个字节都不写。"""
    import gui.mixins.system_mixin as mod

    base = str(tmp_path)
    os.makedirs(os.path.join(base, "data"), exist_ok=True)
    existing = os.path.join(base, "data", "config.json")
    with open(existing, "w", encoding="utf-8") as f:
        f.write('{"old": 1}')
    pkg = _zip(str(tmp_path / "pack.zip"), {"data/config.json": '{"new": 2}'})

    class NoBox(_FakeMessageBox):
        @classmethod
        def question(cls, parent, title, text, *a, **k):
            cls.asked.append(text)
            return cls.No

    NoBox.asked.clear()
    monkeypatch.setattr(mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (pkg, "")))
    monkeypatch.setattr(mod, "QMessageBox", NoBox)

    _owner(base).import_data()
    with open(existing, encoding="utf-8") as f:
        assert f.read().strip() == '{"old": 1}', "选「否」还写了文件"


def test_import_data_no_longer_calls_extractall():
    """源码层兜底：这个入口不许再出现 extractall（旧实现就是它）。"""
    import gui.mixins.system_mixin as mod

    src = open(mod.__file__, encoding="utf-8").read()
    assert "extractall" not in src


def test_skill_loader_module_is_gone():
    """重复实现已删：能力由 core.skill_registry 统一提供。"""
    import importlib.util

    assert importlib.util.find_spec("core.skill_loader") is None
    from core.skill_registry import SkillRegistry
    assert hasattr(SkillRegistry, "install_from_file")
    assert hasattr(SkillRegistry, "export_to_file")


def test_roles_entry_is_wired():
    """注册表里的 roles 必须能在主窗口解析成可调用方法。"""
    from core.feature_registry import get_feature
    from gui.mixins.dialog_mixin import DialogMixin
    from gui.panel_registry import build_panel_commands

    feature = get_feature("roles")
    assert feature is not None
    assert feature.action == "roles_dialog"
    assert callable(getattr(DialogMixin, "roles_dialog", None))

    class Owner(DialogMixin):
        trunk = None
        base = "."

    assert build_panel_commands(Owner()).get("群聊角色") is not None
