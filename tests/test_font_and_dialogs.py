# -*- coding: utf-8 -*-
"""Font bootstrap and startup-dialog serialization tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import font_bootstrap  # noqa: E402


def test_system_font_files_are_real_files():
    files = font_bootstrap.system_font_files()
    for p in files:
        assert os.path.isfile(p), p
    if sys.platform == "win32":
        assert files, "Windows 上应该能找到系统字体（否则界面会全白）"


def test_ensure_fonts_registers_and_reports(qapp):
    r = font_bootstrap.ensure_fonts(qapp)
    assert set(r) >= {"ok", "before", "after", "loaded", "families", "reason"}
    assert r["ok"] is True, r["reason"]
    assert r["after"] >= 1
    assert r["families"]


def test_ensure_fonts_second_call_is_noop(qapp):
    font_bootstrap.ensure_fonts(qapp)
    r = font_bootstrap.ensure_fonts(qapp)
    assert r["ok"] is True
    assert r["loaded"] == [], "已有字体时不该重复注册"


def test_status_reports_font_state(qapp):
    font_bootstrap.ensure_fonts(qapp)
    s = font_bootstrap.status()
    assert s["ok"] is True
    assert s["count"] >= 1
    assert s["platform"]


def test_ensure_fonts_survives_missing_qt(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("PyQt5.QtGui"):
            raise ImportError("no qt")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = font_bootstrap.ensure_fonts(None)
    assert r["ok"] is False
    assert "PyQt5" in r["reason"]


def test_show_onboarding_is_exported():
    """曾经被删掉的 show_onboarding 必须存在，否则启动日志一直报错。"""
    from gui.onboarding_wizard import needs_onboarding, show_onboarding
    assert callable(needs_onboarding)
    assert callable(show_onboarding)


def test_main_window_serializes_startup_dialogs():
    """启动引导必须是串行的：协议 -> 登录 -> 首次向导。"""
    src = open(os.path.join(BASE, "gui", "main_window.py"),
               encoding="utf-8").read()
    assert "_confirm_agreement" in src
    assert "_after_agreement_login" in src
    # 协议不能再在 __init__ 里同步 exec_
    init_end = src.index("def _do_login_flow")
    init_body = src[:init_end]
    assert "AgreementDialog(self.trunk, self)" not in init_body, \
        "__init__ 里还在同步弹协议框"


def test_login_dialog_does_not_double_prompt_agreement():
    src = open(os.path.join(BASE, "gui", "login_dialog.py"),
               encoding="utf-8").read()
    assert "_agreement_pending" in src, "登录框没有复用主窗口的协议状态"


def test_disabled_prompt_env_skips_all_modals(monkeypatch):
    monkeypatch.setenv("X6_DISABLE_LOGIN_PROMPT", "1")
    src = open(os.path.join(BASE, "gui", "main_window.py"),
               encoding="utf-8").read()
    assert 'os.environ.get("X6_DISABLE_LOGIN_PROMPT") == "1"' in src
    assert src.count("X6_DISABLE_LOGIN_PROMPT") >= 3


def test_status_without_qapp_does_not_crash():
    """没有 QApplication 时查字体必须安全返回，不能让进程崩掉。"""
    import subprocess
    code = (
        "import os,sys;"
        "sys.path.insert(0, r'%s');"
        "os.environ['QT_QPA_PLATFORM']='offscreen';"
        "from core import font_bootstrap;"
        "s=font_bootstrap.status();"
        "print('ok=', s.get('ok'), 'count=', s.get('count'));"
        "r=font_bootstrap.ensure_fonts(None);"
        "print('ensure_ok=', r.get('ok'), 'reason=', bool(r.get('reason')))"
    ) % BASE
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=120, cwd=BASE)
    assert r.returncode == 0, r.stderr[-400:]
    assert "ok= False" in r.stdout
    assert "ensure_ok= False" in r.stdout


def test_self_check_contains_font_check(qapp):
    """自检源码里必须有字体检查（有字体时打印 OK）。"""
    from core import font_bootstrap
    font_bootstrap.ensure_fonts(qapp)
    src = open(os.path.join(BASE, "core", "self_check.py"),
               encoding="utf-8").read()
    assert "font_bootstrap" in src
    assert "字体: OK" in src
    assert "Qt 没有可用字体" in src


def test_ensure_fonts_registers_when_qt_reports_zero(qapp, monkeypatch):
    """模拟"字体族为 0"的现场：必须走注册分支并最终 ok=True。"""
    from core import font_bootstrap

    real_db = font_bootstrap.ensure_fonts

    class FakeDB:
        def __init__(self):
            self.calls = 0

        def families(self):
            # 第一次报告 0，注册后返回真实字体族
            self.calls += 1
            if self.calls == 1:
                return []
            return ["Microsoft YaHei UI", "Segoe UI"]

        def addApplicationFont(self, path):
            return 0

    import PyQt5.QtGui as QtGui
    monkeypatch.setattr(QtGui, "QFontDatabase", FakeDB)
    r = font_bootstrap.ensure_fonts(qapp, min_families=1)
    assert r["before"] == 0
    assert r["after"] == 2
    assert r["ok"] is True
    assert r["loaded"], "应该记录注册过的字体文件"


def test_ensure_fonts_reports_failure_when_nothing_registrable(qapp, monkeypatch):
    from core import font_bootstrap

    class FakeDB:
        def families(self):
            return []

        def addApplicationFont(self, path):
            raise OSError("bad font")

    import PyQt5.QtGui as QtGui
    monkeypatch.setattr(QtGui, "QFontDatabase", FakeDB)
    r = font_bootstrap.ensure_fonts(qapp)
    assert r["ok"] is False
    assert "空白" in r["reason"]


def test_ensure_fonts_handles_db_failure(qapp, monkeypatch):
    from core import font_bootstrap

    class FakeDB:
        def __init__(self):
            raise RuntimeError("db broken")

    import PyQt5.QtGui as QtGui
    monkeypatch.setattr(QtGui, "QFontDatabase", FakeDB)
    r = font_bootstrap.ensure_fonts(qapp)
    assert r["ok"] is False
    assert "字体自愈失败" in r["reason"]


def test_status_reports_error_when_qt_fails(qapp, monkeypatch):
    from core import font_bootstrap

    class FakeDB:
        def families(self):
            raise RuntimeError("boom")

    import PyQt5.QtGui as QtGui
    monkeypatch.setattr(QtGui, "QFontDatabase", FakeDB)
    s = font_bootstrap.status()
    assert s["ok"] is False
    assert "boom" in s["error"]


def test_run_pyqt_calls_font_bootstrap_before_widgets():
    """字体修复必须在建窗口之前调用。"""
    src = open(os.path.join(BASE, "gui", "app_pyqt.py"),
               encoding="utf-8").read()
    i_font = src.index("font_bootstrap")
    i_window = src.index("JarvisWindow(")
    assert i_font < i_window, "字体自愈必须在创建主窗口之前"
    assert "ensure_fonts(app)" in src


def test_code_editor_line_numbers_use_valid_api():
    """只检查可执行代码；注释里提到旧写法是说明文字，不算违规。"""
    import ast
    path = os.path.join(BASE, "gui", "code_editor_widget.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "paint_line_numbers":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    calls.append(ast.unparse(sub.func))
    assert calls, "找不到 paint_line_numbers 里的调用"
    assert "self.viewport().contentOffset" not in calls, \
        "viewport 是 QWidget，没有 contentOffset（曾导致 paintEvent 崩溃）"
    assert any("self.contentOffset" in c for c in calls)
