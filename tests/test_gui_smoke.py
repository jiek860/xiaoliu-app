# -*- coding: utf-8 -*-
"""GUI 冒烟测试：32 个界面类，每个都要"能构造出来"

为什么需要这个文件
------------------
界面是用户 100% 的接触面，但它是最容易在重构中**悄悄坏掉**的地方 ——
改一个 import、重命名一个控件，程序照样启动（主窗口能开），
只有点到那个窗口才崩。这一轮我自己就犯过两次：
    · gui/system_dialog.py 撤按钮后留下死 import（QLineEdit / QTextEdit）
    · gui/main_window.py   加 Ctrl+K 时漏了 Qt / QShortcut 的 import

已有的覆盖与本文档的分工（实测过，别重复）：
    tests/test_ui_responsiveness.py   测 9 个对话框**打开得快不快**
                                      （走主窗口方法，所以类名不出现在那里）
    本文件                            测 **32 个类能不能构造出来**
                                      （直接 import + 构造，抓 import/属性错误）

两类互补：那边防"界面卡"，这边防"界面坏"。

设计取舍
--------
· 只验"构造"不验"交互" —— 无头环境点不了按钮，假装测交互只会得到假信号
· 每个类都关掉，避免残留窗口影响后续用例
· QThread 子类**只构造不启动**（start() 会真的跑任务）
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (QApplication, QWidget, QDialog, QMainWindow,  # noqa: E402
                             QMessageBox, QWizard)
from PyQt5.QtCore import QThread, QObject  # noqa: E402
from PyQt5.QtGui import QTextDocument  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from tests.conftest import make_trunk  # noqa: E402


@pytest.fixture(scope="module")
def trunk():
    """屏蔽后台的 Trunk（见 conftest：裸 Trunk 会连 MCP 拉起子进程）"""
    return make_trunk()


@pytest.fixture(scope="module", autouse=True)
def _quiet_boxes():
    """桩掉会阻塞/弹窗的东西 —— 无头环境弹窗会挂住

    exec_ 必须桩掉：这些 show_xxx_dialog 结尾是 `d.exec_()`（模态，
    等用户关窗口）。有的是通过 _dlg 工厂建的，有的是**自己 new 一个
    QDialog** 再 exec_ —— 所以连 QDialog.exec_ 一起桩。
    实测不桩的话 12 个里有 8 个挂死（现象是"卡住不退"，不是报错）。
    （tests/test_ui_responsiveness.py 对 QWizard.exec_ 也是这么处理的。）

    顺便**记录**哪些窗口走到了 exec_ —— 这是"界面真的搭完了"的最硬证据，
    而且对两种写法（走工厂 / 自建窗口）都成立。
    """
    saved = (QMessageBox.information, QMessageBox.warning,
             QMessageBox.critical, QMessageBox.question)
    saved_exec = QDialog.exec_

    def _recording_exec(self):
        _EXEC_LOG.append(self)
        return 0

    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.critical = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QWizard.exec_ = _recording_exec
    QDialog.exec_ = _recording_exec
    yield
    (QMessageBox.information, QMessageBox.warning,
     QMessageBox.critical, QMessageBox.question) = saved
    QDialog.exec_ = saved_exec


_EXEC_LOG = []          # 走到 exec_ 的窗口（= 界面搭完并"显示"了）


class _Acct:
    """HistoryDialog 要一个 account 对象"""
    def load_history(self, limit=50):
        return []

    def current_username(self):
        return "tester"


# (标签, 模块, 类名, 构造方式)
#   构造方式用 lambda，因为各个类签名不一样（有的要 trunk+parent，
#   有的只要 parent，线程类只要一个参数）
DIALOGS = [
    ("同意条款", "gui.agreement_dialog", "AgreementDialog", lambda t: (t, None)),
    ("机器人", "gui.bot_dialog", "BotDialog", lambda t: (t, None)),
    ("命令面板", "gui.command_palette", "CommandPalette",
     lambda t: (t, {"设置": lambda: None}, None)),
    ("反馈", "gui.feedback_dialog", "FeedbackDialog", lambda t: (t, None)),
    ("历史记录", "gui.history_dialog", "HistoryDialog",
     lambda t: (t, _Acct(), None)),
    ("MCP", "gui.mcp_dialog", "MCPDialog", lambda t: (t, None)),
    ("记忆可视化", "gui.memory_view_dialog", "MemoryViewDialog",
     lambda t: (t, None)),
    ("手机远程", "gui.mobile_dialog", "MobileDialog", lambda t: (t, None)),
    ("模型管理", "gui.model_manager_dialog", "ModelManagerDialog",
     lambda t: (t, None)),
    ("搜索聊天", "gui.search_dialog", "SearchDialog", lambda t: (t, None)),
    ("数据统计", "gui.stats_dialog", "StatsDialog", lambda t: (t, None)),
    ("日历待办", "gui.tools_dialog", "ToolsDialog", lambda t: (t, None)),
    ("检查更新", "gui.update_dialog", "UpdateDialog", lambda t: (t, None)),
    ("语音对话", "gui.voice_chat_dialog", "VoiceChatDialog", lambda t: (t, None)),
    ("代码编辑器", "gui.code_editor_dialog", "CodeEditorDialog",
     lambda t: (t, None)),
    ("首次设置向导", "gui.onboarding_wizard", "OnboardingWizard",
     lambda t: (t, None)),
]

WIDGETS = [
    ("桌宠", "gui.desktop_pet", "DesktopPet", lambda t: (t, None)),
    ("聊天视图", "gui.chat_view", "ChatView", lambda t: (None, BASE)),
    ("代码编辑部件", "gui.code_editor_dialog", "CodeEditWidget",
     lambda t: (None,)),
]

OBJECTS = [
    ("插件在线信号", "gui.plugin_dialog", "_OnlineSignals", lambda t: ()),
    ("语音中继", "gui.mixins.voice_mixin", "_VoiceRelay", lambda t: ()),
]

THREADS = [
    ("后台工人", "gui.workers", "BgWorker", lambda t: (lambda: None,)),
    ("学习闭环工人", "gui.workers", "LearnWorker", lambda t: (t,)),
    ("流式工人", "gui.workers", "StreamWorker", lambda t: (t, "hi")),
    ("语音合成工人", "gui.workers", "TTSWorker", lambda t: (t, "hi")),
    ("任务闭环工人", "gui.workers", "TaskWorker", lambda t: (t, "目标")),
    ("语音对话工人", "gui.voice_chat_dialog", "VoiceChatWorker", lambda t: (t,)),
    ("模型下载工人", "gui.model_manager_dialog", "PullWorker",
     lambda t: ("http://127.0.0.1:1", "测试模型")),
    ("更新下载线程", "gui.update_dialog", "UpdateThread",
     lambda t: (None, [], None)),
]

# ── 函数式对话框 ──
# 本项目大量界面是 show_xxx_dialog() 函数而不是类，类名不出现在任何地方 ——
# 所以"用类名搜索测试源码"那种覆盖率统计**量不到它们**（我第一版就被这个骗了，
# 报了个"3%"的错误数字）。这里按真实签名一个个补上。
#
# 其中 6 个（设置/电脑控制/系统/插件/日志/向导）已经被
# tests/test_ui_responsiveness.py 通过主窗口方法打开过（它测的是**耗时**），
# 这里补的是**构造**这一层；剩下 7 个此前完全没被碰过。
# 调用时都要 dlg / parent 这类工厂参数，用最小的桩替代。
FUNC_DIALOGS = [
    ("命令面板", "gui.command_palette", "show_command_palette",
     lambda t, p, dlg: (t, {"设置": lambda: None}, p)),
    ("可选组件", "gui.components_dialog", "show_components_dialog",
     lambda t, p, dlg: (p, BASE, lambda *a, **k: None)),
    ("知识图谱", "gui.graph_dialog", "show_graph_dialog",
     lambda t, p, dlg: (p, dlg, t)),
    ("知识库", "gui.kb_dialog", "show_kb_dialog",
     lambda t, p, dlg: (p, dlg, t, lambda: None)),
    ("登录", "gui.login_dialog", "show_login_dialog",
     lambda t, p, dlg: (p, t, BASE, lambda *a, **k: None)),
    ("引导教程", "gui.tutorial_dialog", "show_tutorial_dialog",
     lambda t, p, dlg: (p,)),
    ("实用工具（薄壳）", "gui.module_tools_dialog", "show_module_tools",
     lambda t, p, dlg: (t, p)),
    # 下面这些 test_ui_responsiveness 已测过耗时，这里补构造
    ("设置", "gui.settings_dialog", "show_settings_dialog",
     lambda t, p, dlg: (p, dlg, t, BASE, "小6", None, None, None, None, None,
                        {})),
    ("电脑控制", "gui.computer_dialog", "show_computer_dialog",
     lambda t, p, dlg: (p, dlg, t, None, None, None)),
    # "系统"（show_system_dialog）**故意不放这里**：它的签名是 (self)，
    # 要一个完整主窗口（用 self.trunk / self._bg_call / self.statusMessage…），
    # 不是能单独构造的对话框。它已经被 tests/test_ui_responsiveness.py
    # 通过 win.sys_dialog() 覆盖了，这里重复只会得到一个假的失败。
    ("插件市场", "gui.plugin_dialog", "show_plugin_dialog",
     lambda t, p, dlg: (p, dlg, t, lambda: None, lambda: None)),
    ("日志中心", "gui.log_dialog", "show_log_dialog",
     lambda t, p, dlg: (p, dlg, BASE, lambda *a, **k: None)),
]


class _DlgFactory:
    """替代主窗口的 _dlg 工厂：返回 (dialog, layout)

    真身是 gui/mixins/dialog_dialog 里的 _dlg，签名 (title, w, h)。
    这里给一个真 QDialog + QVBoxLayout，让各对话框照常搭界面。

    ⚠️ 关键：必须把 exec_() 换成不阻塞的桩。
       这些 show_xxx_dialog 结尾都是 `d.exec_()`（模态，等用户关窗口），
       用真 exec_ 的话测试会**永远挂住** —— 实测 12 个里有 8 个挂死，
       而且现象是"卡住不退"，不是报错（我第一次跑就把命令挂到超时了）。
       记一下 exec_ 被调用过，这本身就是"界面真的搭完了"的证据。

    ⚠️ 踩过的坑：**不要去 patch QDialog.show**。
       我一开始为了识别"非模态界面"（命令面板 / 实用工具用 d.show()）
       也把 show 换成了记录器，再用赋值恢复 —— 结果
       `TypeError: show(self): first argument of unbound method must have
       type 'QWidget'` 污染了**后面所有**用到 show 的测试
       （test_ui_responsiveness 直接挂了 6 个）。
       原因：show 是从 QWidget **继承**来的，赋值会在 QDialog 上造一个副本，
       PyQt 处理不了。改用**返回值**识别非模态界面，不碰 show。
    """
    def __init__(self):
        self.made = []
        self.exec_called = 0

    def __call__(self, title="", w=600, h=400):
        from PyQt5.QtWidgets import QVBoxLayout
        d = QDialog()
        d.setWindowTitle(title or "测试")
        d.resize(w, h)
        lay = QVBoxLayout(d)

        def _fake_exec():
            self.exec_called += 1
            return 0                      # 立刻返回，不阻塞

        try:
            d.exec_ = _fake_exec          # PyQt 实例上盖掉 exec_
        except Exception:
            pass
        self.made.append(d)
        return d, lay

    def close_all(self):
        for d in self.made:
            try:
                d.close()
                d.deleteLater()
            except Exception:
                pass
        self.made = []


def _build(mod, cls_name, args_fn, t):
    import importlib
    m = importlib.import_module(mod)
    cls = getattr(m, cls_name)
    return cls(*args_fn(t))


# ══════════════════════════════════════════════════════════════
# 对话框 / 窗口：要能构造、有标题、有内容、能关
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,mod,cls,args", DIALOGS,
                         ids=[d[0] for d in DIALOGS])
def test_dialog_constructs(label, mod, cls, args, trunk):
    w = None
    try:
        w = _build(mod, cls, args, trunk)
        assert isinstance(w, (QDialog, QMainWindow, QWidget)), \
            "%s 不是窗口部件：%r" % (label, type(w))
        # 有标题（忘了 setWindowTitle 的话用户看到的是空白标题栏）
        title = w.windowTitle() if hasattr(w, "windowTitle") else ""
        assert title, "%s 的窗口标题是空的" % label
        # 有内容（构造出个空壳说明布局没搭起来）
        kids = w.findChildren(QWidget)
        assert len(kids) >= 1, "%s 里一个子控件都没有（布局没搭起来？）" % label
    finally:
        if w is not None:
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass


@pytest.mark.parametrize("label,mod,cls,args", WIDGETS,
                         ids=[w[0] for w in WIDGETS])
def test_widget_constructs(label, mod, cls, args, trunk):
    w = None
    try:
        w = _build(mod, cls, args, trunk)
        assert isinstance(w, QWidget), "%s 不是部件" % label
    finally:
        if w is not None:
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
# 线程类：只构造，**不 start()**（start 会真跑任务）
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,mod,cls,args", THREADS,
                         ids=[t[0] for t in THREADS])
def test_worker_constructs_without_starting(label, mod, cls, args, trunk):
    w = _build(mod, cls, args, trunk)
    assert isinstance(w, QThread), "%s 不是 QThread" % label
    assert not w.isRunning(), "%s 构造时就跑起来了（不该）" % label


@pytest.mark.parametrize("label,mod,cls,args", OBJECTS,
                         ids=[o[0] for o in OBJECTS])
def test_qobject_helper_constructs(label, mod, cls, args, trunk):
    w = _build(mod, cls, args, trunk)
    assert isinstance(w, QObject), "%s 不是 QObject" % label


# ══════════════════════════════════════════════════════════════
# 函数式对话框：调一次 show_xxx_dialog，界面要真搭起来
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,mod,fn,args", FUNC_DIALOGS,
                         ids=[f[0] for f in FUNC_DIALOGS])
def test_function_dialog_builds(label, mod, fn, args, trunk):
    """函数式对话框：调一次，界面要真的搭起来并"显示"

    判据是 **有没有窗口走到 exec_()**，而不是"有没有用我给的工厂"。
    为什么：这一批写法不统一 ——
        show_graph_dialog / show_settings_dialog … 用传进来的 dlg 工厂
        show_command_palette / show_tutorial_dialog … 自己 new QDialog
    第一版我断言"工厂必须被用到"，结果 7 个"失败"里有 5 个是**我的判据
    不适用**（它们自己建窗口），不是程序坏了。改成记录 exec_ 就对两种
    写法都成立，而且更本质：走到 exec_ 说明界面搭完并进入了显示阶段。
    """
    import importlib
    fac = _DlgFactory()
    del _EXEC_LOG[:]
    try:
        f = getattr(importlib.import_module(mod), fn)
        ret = f(*args(trunk, None, fac))
        # 三种"界面真的搭起来了"的证据，命中任一条即可：
        #   ① 用了传进去的 dlg 工厂（图形/设置/日志…）
        #   ② 有窗口走到 exec_()（自己 new QDialog 的那些）
        #   ③ 函数**返回**了一个窗口（非模态的那些，如命令面板 —— 它 d.show()
        #      之后把 d 返回了。故意不去 patch QDialog.show，见 _DlgFactory 说明）
        cands = list(fac.made) + list(_EXEC_LOG)
        if isinstance(ret, QWidget):
            cands.append(ret)
        assert cands, (
            "%s 既没用 dlg 工厂、也没有窗口走到 exec_()、也没返回窗口 —— "
            "是不是中途 return 了（import 缺失/签名变了都会这样）？" % label)
        w = cands[-1]
        assert w.windowTitle(), "%s 的窗口标题是空的" % label
        assert len(w.findChildren(QWidget)) >= 1, \
            "%s 里一个子控件都没有（布局没搭起来？）" % label
    finally:
        fac.close_all()
        del _EXEC_LOG[:]


# ══════════════════════════════════════════════════════════════
# 高亮器：要传一个文档
# ══════════════════════════════════════════════════════════════
def test_syntax_highlighter_constructs():
    from gui.code_editor_dialog import _PyHighlighter
    doc = QTextDocument()
    h = _PyHighlighter(doc)
    assert h is not None
    doc.setPlainText("def f():\n    return 1\n")     # 触发一次高亮


def test_code_editor_line_number_area():
    from gui.code_editor_dialog import CodeEditWidget, _LineNumberArea
    ed = CodeEditWidget(None)
    try:
        area = _LineNumberArea(ed)
        assert area is not None
    finally:
        ed.close()


# ══════════════════════════════════════════════════════════════
# 主窗口：整体装配（最重的一个）
# ══════════════════════════════════════════════════════════════
def test_main_window_assembles():
    """主窗口能装配出来，且关键控件都在

    这是最值钱的一条 —— 主窗口装配失败 = 程序打不开。
    注意要屏蔽后台：JarvisWindow 内部会建 Trunk，
    裸建的话 3 秒后它会去连 MCP（见 conftest 的说明）。
    """
    import unittest.mock as mock
    from core.trunk import Trunk
    from tests.conftest import _BACKGROUND
    patchers = [mock.patch.object(Trunk, n, lambda self: None)
                for n in _BACKGROUND]
    for p in patchers:
        p.start()
    try:
        from gui.main_window import JarvisWindow
        w = JarvisWindow()
    finally:
        for p in patchers:
            p.stop()
    try:
        # 关键控件必须存在 —— 少了任何一个，主界面就是残的
        for attr in ("chat", "input", "trunk", "base"):
            assert hasattr(w, attr), "主窗口缺 %s" % attr
        assert w.windowTitle(), "主窗口标题是空的"
        assert len(w.findChildren(QWidget)) > 10, "主窗口里控件太少，装配不完整"
        # Ctrl+K 快捷键（v25.2.0 加的，漏了 import 就会静默失效）
        assert hasattr(w, "_cmd_shortcut"), "Ctrl+K 快捷键没装上"
    finally:
        try:
            w.close()
        except Exception:
            pass
