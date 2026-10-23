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
                             QMessageBox, QWizard, QPushButton, QComboBox,
                             QLineEdit)
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
        for attr in ("chat", "input", "trunk", "base", "activity_btn",
                     "theme_manager", "window_state"):
            assert hasattr(w, attr), "主窗口缺 %s" % attr
        assert w.windowTitle(), "主窗口标题是空的"
        assert len(w.findChildren(QWidget)) > 10, "主窗口里控件太少，装配不完整"
        # Ctrl+K 快捷键（v25.2.0 加的，漏了 import 就会静默失效）
        assert hasattr(w, "_cmd_shortcut"), "Ctrl+K 快捷键没装上"

        # 所有主界面按钮：必须有可读文字，且真的接了点击处理。
        # 空文字 / 未接线按钮在截图里往往看不出来，用户点了才发现没反应。
        from PyQt5.QtWidgets import QPushButton as _QPushButton
        buttons = w.findChildren(_QPushButton)
        assert len(buttons) >= 18, "主界面按钮少得反常：%d" % len(buttons)
        empty = [b.objectName() or b.toolTip() for b in buttons
                 if not (b.text() or "").strip()]
        assert not empty, "存在无文字按钮：%s" % empty
        unwired = [(b.text() or "").strip() for b in buttons
                   if b.receivers(b.clicked) < 1]
        assert not unwired, "存在没有点击处理的按钮：%s" % unwired

        # 命令面板 / 设置窗口共用入口表：每一项都必须真实可调用，
        # 不能出现 None 导致设置页按钮被静默置灰。
        commands = w._panel_commands()
        dead = [name for name, fn in commands.items() if not callable(fn)]
        assert not dead, "命令面板/设置缺少入口：%s" % dead
    finally:
        try:
            w.close()
        except Exception:
            pass


# ======================================================================
# 以下从 tests/test_onboarding_layout.py 并入
# （那个文件在全量跑时会间歇性崩溃，见它原来的说明；
#   这些用例本身没问题，只是需要一个稳定的执行位置）
# ======================================================================


# 输入框窄于这个宽度就算不可用（文字会被截断）
MIN_OK = 100

_ONB_FIELDS = [
    ("本地地址", "ed_ollama"), ("本地模型", "ed_local_model"),
    ("服务商", "cb_provider"), ("云端地址", "ed_cloud_url"),
    ("云端模型", "ed_cloud_model"), ("云端Key", "ed_cloud_key"),
]

_ONB_LABELS = ("lbl_local_status", "lbl_local_howto", "lbl_provider_tip", "lbl_dl")

import os
import sys


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")



# 阈值：低于这个宽度就属于"文字会被截断、没法核对"的不可用状态
MIN_OK = 100

_ONB_FIELDS = [("本地地址", "ed_ollama"), ("本地模型", "ed_local_model"),
          ("云端地址", "ed_cloud_url"), ("云端模型", "ed_cloud_model"),
          ("云端Key", "ed_cloud_key")]

_w = None


@pytest.fixture(scope="module")
def wiz():
    """**整个模块只建一次**向导，用完销毁

    ⚠️ 为什么必须是 module 作用域（这里是崩溃的真凶）
    ------------------------------------------------
    曾经写成 scope="function" —— 20 个用例就建 20 个向导。
    而每个向导都配一个 `make_trunk()` 造的 Trunk，**而 make_trunk 并不屏蔽
    Trunk.__init__ 里无条件启动的 `_bg_loop` / `_idle_worker` 两个后台线程**。
    20 个用例 = 20 个 Trunk = **40 个后台线程**。

    后果：全量跑时间歇性踩到 **Windows fatal exception: access violation**
    （退出码 0xC0000005 / 3221225477），而且：
        · 单独跑本文件也崩（合并进来之后）
        · 二分定位到它是**累积**效应：前缀 18 个文件时没事，
          加到第 19 个（test_mcp_stdio.py）就开始崩
    线程数暴涨正是"累积"的来源。

    改成 module 作用域后：1 个 Trunk / 2 个线程，量级降回正常。
    """
    global _w
    import gui.onboarding_wizard as ow
    import core.model_setup as _ms
    mp = pytest.MonkeyPatch()
    mp.setattr(_ms, "probe_ollama",
               lambda *a, **k: {"reachable": False, "models": [],
                                "error": "offline-test"})
    orig = ow.OnboardingWizard._refresh_local_status
    # 把"异步"强制走同步分支 —— 不起探测线程
    ow.OnboardingWizard._refresh_local_status = (
        lambda self, async_=True: orig(self, async_=False))
    try:
        _w = ow.OnboardingWizard(make_trunk())
        _w.resize(760, 640)
        _w.show()
        _app.processEvents()
        for i in range(_w.pageIds().__len__()):
            if "模型" in (_w.page(i).title() or ""):
                _w.setStartId(i)
                break
        _w.restart()
        _app.processEvents()
        yield _w
    finally:
        ow.OnboardingWizard._refresh_local_status = orig
        try:
            _w.close()
            _w.deleteLater()
        except Exception:
            pass
        _w = None
        mp.undo()
        for _ in range(6):
            _app.processEvents()


@pytest.fixture(scope="module")
def wiz():
    """建一次向导，并**切到第 2 页（模型配置）**

    ⚠️ 两个坑，都踩过：
    ① 不切页的话第 2 页的控件根本没被布局，测得的位置全是默认值 ——
       第一版 y 坐标两边都是 39，看着像"在同一行"，其实只是没布局。
    ② **必须把异步探测改成同步**：向导 `_prefill()` 会起一个
       `onboarding-probe` 线程去 urllib 请求 Ollama。测试跑完时这个
       daemon 线程可能还在跑，解释器拆除阶段撞上它 -> 整个 pytest
       进程硬崩（Windows fatal exception: access violation，
       退出码 0xC0000005，连是哪个用例都打不出来）。
       实测就是这么挂的：跑到 63% 直接没输出。
    """
    global _w
    if _w is None:
        import gui.onboarding_wizard as ow
        import core.model_setup as _ms
        mp = pytest.MonkeyPatch()
        mp.setattr(_ms, "probe_ollama",
                   lambda *a, **k: {"reachable": False, "models": [],
                                    "error": "offline-test"})
        orig = ow.OnboardingWizard._refresh_local_status
        # 把"异步"强制走同步分支 —— 不起线程，也就没有拆除期崩溃
        ow.OnboardingWizard._refresh_local_status = (
            lambda self, async_=True: orig(self, async_=False))
        try:
            _w = ow.OnboardingWizard(make_trunk())
            _w.resize(760, 640)
            _w.show()
            _app.processEvents()
            for i in range(_w.pageIds().__len__()):
                if "模型" in (_w.page(i).title() or ""):
                    _w.setStartId(i)
                    break
            _w.restart()
            _app.processEvents()
            _app.processEvents()
        finally:
            ow.OnboardingWizard._refresh_local_status = orig
            mp.undo()
    return _w


def test_we_are_on_the_model_page(wiz):
    """先确认测的确实是那一页 —— 否则下面全是假通过"""
    assert "模型" in (wiz.currentPage().title() or ""), \
        "没切到模型配置页，测的是：%s" % wiz.currentPage().title()


@pytest.mark.parametrize("size", [(660, 520), (760, 560), (900, 640)])
def test_fields_are_wide_enough(wiz, size):
    """每个输入框在任何窗口尺寸下都不能被压成条

    这条就是抓用户截图里那个问题。
    """
    wiz.resize(*size)
    _app.processEvents()
    narrow = []
    for label, attr in _ONB_FIELDS:
        w = getattr(wiz, attr).width()
        if w < MIN_OK:
            narrow.append("%s 只有 %d px" % (label, w))
    assert not narrow, (
        "窗口 %dx%d 时这些输入框被压扁了（文字会被截断）：%s\n"
        "改法：别把多个可拉伸输入框塞进同一行 —— 拆成各占一行，"
        "并给每个设 setMinimumWidth。"
        % (size[0], size[1], "；".join(narrow)))


def test_minimum_width_is_set_as_defense(wiz):
    """输入框要设最小宽度（防"窗口被拖窄"时的第二层保护）

    为什么要单独测这个：拆成两行之后，正常尺寸下输入框本来就占满整行，
    所以 `setMinimumWidth` 在当前窗口尺寸范围内**测不出差别** ——
    负向测试把这几行删掉，660~900 的用例全都照样通过（这是真的，
    不是测试写得不好；它就是一层冗余防御）。

    但它管的是真实场景里会遇到的两种窄：
        · 用户把窗口拖到很小
        · 系统字体放大，导致布局需求变宽
    没有它，输入框会退化成没法核对的一条。

    这条**只读属性**，不改窗口（第一版我在这里折腾 resize/setFixedWidth，
    结果把控件状态搞乱，基线自己就挂了）。
    """
    for label, attr in _ONB_FIELDS:
        w = getattr(wiz, attr).minimumWidth()
        assert w >= MIN_OK, (
            "%s 的最小宽度是 %d px（应 >= %d）—— 窗口拖窄时它会退化成条。\n"
            "改法：给每个输入框加 setMinimumWidth(240)。"
            % (label, w, MIN_OK))


def test_local_row_is_split_not_crowded(wiz):
    """本地那行不能又是"4 个控件挤一行"

    结构检查（比逐尺寸量宽度更早发现问题）：地址和模型必须**各占一行**，
    也就是它们的 y 坐标不能相同。
    """
    y_addr = wiz.ed_ollama.mapTo(wiz, wiz.ed_ollama.rect().topLeft()).y()
    y_model = wiz.ed_local_model.mapTo(wiz, wiz.ed_local_model.rect().topLeft()).y()
    assert y_addr != y_model, \
        "地址和模型还在同一行（y 都是 %d）—— 窄窗口下必然被压" % y_addr


def test_cloud_model_and_key_are_on_separate_rows(wiz):
    """云端的模型和 Key 也要各占一行"""
    y_m = wiz.ed_cloud_model.mapTo(wiz, wiz.ed_cloud_model.rect().topLeft()).y()
    y_k = wiz.ed_cloud_key.mapTo(wiz, wiz.ed_cloud_key.rect().topLeft()).y()
    assert y_m != y_k, "云端模型和 Key 还在同一行（y 都是 %d）" % y_m


def test_local_model_is_a_editable_combobox(wiz):
    """模型框要是可编辑下拉框 —— 检测到就自动列出来，不用手打

    手打模型名错一个字符，表现就是"发消息没反应"，用户很难自己查出来。
    同类程序的做法是检测到模型后自动刷进下拉框。
    """
    assert isinstance(wiz.ed_local_model, QComboBox), \
        "模型框不是下拉框（用户只能手打模型名）"
    assert wiz.ed_local_model.isEditable(), \
        "下拉框不可编辑 —— 自己训的模型名就填不进去了"


def test_detected_models_are_filled_in(wiz):
    """检测到 Ollama 里的模型后，要自动出现在下拉框里"""
    from core import model_setup
    url = wiz.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA
    info = model_setup.probe_ollama(url, timeout=3)
    if not info.get("reachable") or not info.get("models"):
        pytest.skip("本机 Ollama 没在跑或没有模型，跳过")
    wiz._apply_local_status(info, url)
    _app.processEvents()
    got = [wiz.ed_local_model.itemText(i)
           for i in range(wiz.ed_local_model.count())]
    missing = [m for m in info["models"] if m not in got]
    assert not missing, "检测到的模型没进下拉框：%s" % missing


def test_selected_model_survives_refresh(wiz):
    """已经选好的模型，重新检测后不能被冲掉

    （每次刷新都把用户的选择重置成第一项，是很烦人的体验。）
    """
    if wiz.ed_local_model.count() < 2:
        pytest.skip("候选不足 2 个，跳过")
    target = wiz.ed_local_model.itemText(1)
    wiz.ed_local_model.setCurrentText(target)
    from core import model_setup
    info = model_setup.probe_ollama(
        wiz.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA, timeout=3)
    if not info.get("reachable"):
        pytest.skip("Ollama 没在跑")
    wiz._apply_local_status(info, info.get("url", ""))
    assert wiz.ed_local_model.currentText() == target, \
        "重新检测把用户选的模型冲掉了"


def test_missing_ollama_gives_actionable_steps(wiz):
    """连不上 Ollama 时，要给**能照着做**的步骤

    两步都已经改成程序内一键完成了（对标同类程序）：
      · 装 Ollama：点按钮下载，不用自己开浏览器找
      · 下模型：点按钮拉取，不用自己开命令行跑 `ollama run xxx`
        （那一步要求用户会开 cmd、会粘命令、看着黑窗口、
          还得自己判断什么时候算下完 —— 同样劝退）
    这条守着"每一步都得说清点哪、多大、装完回哪一步"。
    """
    wiz._apply_local_status(
        {"reachable": False, "models": [], "error": "测试"}, "http://x")
    _app.processEvents()
    txt = wiz.lbl_local_howto.text()
    assert "下载 Ollama" in txt or "一键下载" in txt, \
        "没告诉用户装 Ollama 要点哪：%s" % txt[:80]
    assert "立即安装" in txt, "没说下完怎么装"
    assert "重新检测" in txt, "没说装完回哪一步"
    assert "下载模型" in txt, \
        "没说模型怎么下（现在是程序内一键，不该再让用户开命令行）：%s" % txt[:80]
    assert "1509" in txt, "没说明安装包多大"
    assert "2GB" in txt or "进度" in txt, "没说明模型多大/要等多久"
    # 官网兜底链接还是要留着（一键下载失败时用户得有出路）
    assert "ollama.com" in txt, "没留手动下载的兜底链接"


def test_status_label_has_no_truncation_marker(wiz):
    """状态栏文字里不该出现被截断的省略号残影（那种"看起来就是坏的"）"""
    wiz._apply_local_status(
        {"reachable": False, "models": [], "error": "x"}, "http://localhost")
    txt = wiz.lbl_local_status.text()
    assert "http://localhost" in txt, \
        "连不上时没把地址说出来（用户没法核对填的对不对）：%s" % txt


# ══════════════════════════════════════════════════════════════
# 窗口尺寸必须按内容算 —— 用户截图报的"内容被裁 + 滚动条"
# ══════════════════════════════════════════════════════════════
# 原来写的是 setMinimumSize(660, 520)，一个**手写的猜测值**。
# 实测「配置模型」页内容需要 620x628、外壳另占 22x99，
# 所以窗口至少要 642x727 —— 520 的高度差了 207px。
# 后果：内容被裁 → 底部横向滚动条 + 右侧纵向滚动条 → 文字截断。

_ONB_LABELS = ("lbl_local_status", "lbl_local_howto", "lbl_provider_tip", "lbl_dl")


def _problems(w):
    """当前尺寸下有什么问题：滚动条 / 太窄的输入框 / 被切的文字"""
    from PyQt5.QtWidgets import QScrollArea
    for _ in range(3):
        _app.processEvents()
    bars = []
    for s in w.findChildren(QScrollArea):
        if s.verticalScrollBar().maximum() > 0:
            bars.append("纵向滚动条")
        if s.horizontalScrollBar().maximum() > 0:
            bars.append("横向滚动条")
    narrow = ["%s=%dpx" % (n, getattr(w, at).width()) for n, at in _ONB_FIELDS
              if getattr(w, at).width() < MIN_OK]
    cut = []
    for n in _ONB_LABELS:
        lb = getattr(w, n, None)
        if lb is None or not lb.text():
            continue
        # ⚠️ 自动换行的 QLabel 必须用 heightForWidth(实际宽度) 判断有没有被切。
        #    sizeHint().height() 给的是"首选宽度下的高度"，会**误报**
        #    （第一版就用它误报了 lbl_provider_tip，白排查一轮）。
        hfw = lb.heightForWidth(lb.width()) if lb.wordWrap() else 0
        need = hfw if hfw > 0 else lb.sizeHint().height()
        if need > lb.height() + 2:
            cut.append("%s(要%dpx 只有%dpx)" % (n, need, lb.height()))
    return bars, narrow, cut


def test_window_size_is_computed_from_content(wiz):
    """窗口最小尺寸必须**按内容算出来**，不能是手写的猜测值"""
    wiz.resize(900, 900)
    _app.processEvents()
    need_w = need_h = 0
    for i in range(wiz.pageIds().__len__()):
        sh = wiz.page(i).sizeHint()
        need_w = max(need_w, sh.width())
        need_h = max(need_h, sh.height())
    mn = wiz.minimumSize()
    assert mn.width() >= need_w, \
        "最小宽 %d 小于内容需要 %d —— 必然出现横向滚动条" % (mn.width(), need_w)
    assert mn.height() >= need_h, \
        "最小高 %d 小于内容需要 %d —— 文字会被裁掉" % (mn.height(), need_h)


@pytest.mark.parametrize("state", ["连上且有模型", "没装Ollama", "没模型",
                                   "下载中", "下完"])
def test_no_clipping_in_every_state(wiz, state):
    """**每种状态下**、缩到最小尺寸，都不能有滚动条/窄框/被切的文字

    这条是抓用户截图那个问题的正主：状态一变文字长短就变，
    窗口不跟着调整就会被裁。
    """
    if state == "连上且有模型":
        wiz._apply_local_status({"reachable": True,
                                 "models": ["a:1b", "b:2b"], "url": "x"}, "x")
    elif state == "没装Ollama":
        wiz._apply_local_status({"reachable": False, "models": [],
                                 "error": "t"}, "http://localhost:11434")
    elif state == "没模型":
        wiz._apply_local_status({"reachable": True, "models": [],
                                 "url": "x"}, "x")
    elif state == "下载中":
        wiz._on_pull_progress("正在下载…", 320.0, 1509.0, 21, 18.2)
    elif state == "下完":
        wiz._on_dl_done({"ok": True, "MB": 1509, "源": "gh-proxy.com",
                         "耗时秒": 84})

    wiz.resize(wiz.minimumSize())
    bars, narrow, cut = _problems(wiz)
    assert not bars, "「%s」状态下出现滚动条：%s" % (state, bars)
    assert not narrow, "「%s」状态下输入框太窄：%s" % (state, narrow)
    assert not cut, "「%s」状态下文字被裁：%s" % (state, cut)


def test_growing_text_resizes_the_window(wiz):
    """说明文字从一句变成四步时，窗口要跟着变高

    （不跟着变的话，新加的那几行直接看不见 —— 而这四步正是
      "没装 Ollama 怎么办"的全部指引。）
    """
    wiz._apply_local_status({"reachable": True,
                             "models": ["a:1b"], "url": "x"}, "x")
    wiz.resize(wiz.minimumSize())
    _app.processEvents()
    short_min = wiz.minimumSize().height()

    wiz._apply_local_status({"reachable": False, "models": [],
                             "error": "t"}, "http://localhost:11434")
    wiz.resize(wiz.minimumSize())
    _app.processEvents()
    tall_min = wiz.minimumSize().height()

    assert tall_min > short_min, \
        "四步说明比一句话长，最小高度却没变（%d -> %d）—— 新加的行会被裁" \
        % (short_min, tall_min)


def test_window_never_shrinks_back(wiz):
    """用户拉大过窗口后，一次文字更新不该把它缩回去"""
    wiz.resize(1000, 950)
    _app.processEvents()
    before = (wiz.width(), wiz.height())
    wiz._apply_local_status({"reachable": True, "models": ["a:1b"],
                             "url": "x"}, "x")
    _app.processEvents()
    after = (wiz.width(), wiz.height())
    assert after[0] >= before[0] and after[1] >= before[1], \
        "窗口被缩回去了：%s -> %s" % (before, after)
