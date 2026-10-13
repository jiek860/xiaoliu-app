# -*- coding: utf-8 -*-
"""🧰 实用工具 —— 把一批"登记了却没人调用"的后台模块接上入口

为什么做成一个统一窗口
----------------------
这些模块**不是对话框类**，而是一个个功能类（图片识别、记忆整理、数据清洗、
统计报表、一键迁移……），各有各的方法。给它们每个单独做一个窗口既啰嗦、
也没必要 —— 统一成一个"点一下、右边看结果"的面板更省事，也更好验证。

安全原则
--------
· 所有动作都在**后台线程**跑（BgWorker），界面不卡
· **会改数据的动作**（数据清洗 / 记忆整理 / 记忆归档）先弹确认
· 每个动作失败只报错，绝不影响别的按钮
· 只调用模块自己的公开方法，不碰任何内部状态
"""
import os

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit, QGroupBox, QScrollArea,
                             QWidget, QMessageBox, QInputDialog, QFileDialog, QLineEdit,
                             QGridLayout)

from gui.workers import BgWorker


def _fmt(r):
    """把模块返回值整理成可读文本"""
    if isinstance(r, dict):
        lines = []
        for k, v in r.items():
            s = str(v)
            if len(s) > 300:
                s = s[:300] + " …"
            lines.append("· %s: %s" % (k, s))
        return "\n".join(lines) if lines else "(空结果)"
    if isinstance(r, (list, tuple)):
        if not r:
            return "(空列表)"
        out = []
        for i, x in enumerate(r[:30]):
            out.append("%2d. %s" % (i + 1, str(x)[:200]))
        if len(r) > 30:
            out.append("… 共 %d 条" % len(r))
        return "\n".join(out)
    return str(r) if r is not None else "(无返回)"


class ModuleToolsDialog(QDialog):
    """实用工具面板：左边按分组列动作，右边看结果"""

    # (分组, 按钮文字, 模块名, 方法名, 说明, 是否需要先确认, 输入提示)
    ACTIONS = [
        ("📷 图片与硬件", "🔍 检测 OCR 可用性", "image_ocr", "available",
         "看看图片文字识别能不能用（需要可选组件）", False, None),
        ("📷 图片与硬件", "🖼 识别图片文字", "image_ocr", "recognize",
         "选一张图片，把里面的文字提取出来", False, "file"),
        ("📷 图片与硬件", "📜 OCR 历史", "image_ocr", "get_history",
         "以前识别过的图片", False, None),
        ("📷 图片与硬件", "🎮 GPU 检测", "gpu_detector", "detect",
         "看看这台机器有没有可用的 GPU", False, None),

        ("🧠 记忆", "🗂 查记忆冲突", "memory_organizer", "check_conflicts",
         "检查记忆卡之间有没有互相矛盾（只读）", False, None),
        ("🧠 记忆", "🧹 记忆自动整理", "memory_organizer", "auto_organize",
         "合并重复的记忆卡（会改写 memory_cards.jsonl）", True, None),
        ("🧠 记忆", "🗜 归档旧记忆", "memory_archiver", "archive_old",
         "把 30 天前的旧记忆压缩归档", True, None),
        ("🧠 记忆", "📦 归档列表", "memory_archiver", "list_archives",
         "看已经归档了哪些", False, None),
        ("🧠 记忆", "🔐 记忆加密导出", "memory_crypto", "export_encrypted",
         "把记忆加密成一个文件（要设密码，别忘了）", False, "password"),

        ("📊 报告", "📊 统计报表", "stats_report", "generate",
         "最近 7 天的使用统计", False, None),
        ("📊 报告", "😊 心情日报", "mood_report", "report",
         "最近 7 天的情绪统计", False, None),
        ("📊 报告", "📈 成长报告", "growth_report", "report",
         "人格成长情况", False, None),
        ("📊 报告", "🌙 生成一个梦", "dream_system", "generate_dream",
         "让它做一个梦（纯娱乐）", False, None),
        ("📊 报告", "🌙 最近的梦", "dream_system", "get_recent_dreams",
         "以前生成的梦", False, None),

        ("🧹 数据", "🧽 数据清洗", "data_cleaner", "clean_all",
         "删掉完全重复的聊天记录 + 合并重复记忆（会改数据！）", True, None),

        ("📦 导出与迁移", "📦 一键迁移导出", "migration", "export",
         "把整份数据打包，换电脑时用", False, "savezip"),
        ("📦 导出与迁移", "🎭 导出人格包", "personality_market", "export_personality",
         "把当前 AI 人格导出成一个小包，可以分享", False, "savezip"),
        ("📦 导出与迁移", "📤 导出崩溃日志包", "crash_export", "export",
         "打包日志+配置+系统信息（密钥自动脱敏）", False, "savezip"),

        ("🌐 浏览器与录制", "🌐 浏览器会话列表", "browser_session", "list",
         "保存过哪些网站的登录状态", False, None),
        ("🌐 浏览器与录制", "📋 录制列表", "action_recorder", "list_recordings",
         "录过哪些操作", False, None),

        ("👥 群聊与多智能体", "👥 群聊角色", "group_parallel", "list_roles",
         "当前有哪些群聊角色", False, None),
        ("👥 群聊与多智能体", "💬 让它们辩论", "group_debate", "debate",
         "给个话题，多个角色来回辩", False, "topic"),
        ("👥 群聊与多智能体", "🗳 多模型投票", "model_vote", "chat_vote",
         "给个问题，多个模型各答一遍再投票", False, "message"),
        ("👥 群聊与多智能体", "📊 群聊闭环统计", "group_loop", "stats",
         "群聊的历史统计", False, None),
    ]

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self._worker = None
        self.setWindowTitle("🧰 实用工具")
        self.resize(860, 640)
        self._build()

    # ---------------- 界面 ----------------
    def _build(self):
        root = QHBoxLayout(self)

        # 左：搜索框 + 分组按钮（可滚动）
        # 40 多个按钮平铺着找太费劲，加个过滤框：按名称或说明实时筛，
        # 整组都被筛掉时连分组标题一起隐藏。
        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 搜索功能…（按名称或说明过滤，回车直接执行唯一匹配）")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_only_match)
        left.addWidget(self.search)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(340)
        host = QWidget()
        lv = QVBoxLayout(host)
        groups = {}
        self._groups = []            # [(分组框, [(按钮, 名称, 说明)])] 供过滤用
        for gname, label, mod, meth, desc, need_confirm, ask in self.ACTIONS:
            if gname not in groups:
                box = QGroupBox(gname)
                gl = QGridLayout(box)
                gl.setContentsMargins(8, 14, 8, 8)
                gl.setSpacing(6)
                groups[gname] = gl
                lv.addWidget(box)
                self._groups.append((box, []))
            gl = groups[gname]
            b = QPushButton(label)
            b.setMinimumHeight(32)
            # 必须自己覆写内边距：全局样式表给所有 QPushButton 加了 padding:10px
            # （上下共 20px），32px 高的按钮就只剩 10px 放字，13px 的文字会被压掉。
            # app 里其它小按钮（model_btn / editor_btn / voice_btn）都是这么处理的。
            b.setStyleSheet("padding: 2px 8px;")
            b.setToolTip(desc)
            b.clicked.connect(
                lambda _c=False, l=label, m=mod, me=meth, d=desc,
                nc=need_confirm, a=ask: self._do(l, m, me, d, nc, a))
            gl.addWidget(b, gl.count() // 1, 0)
            for _box, items in self._groups:
                if _box.title() == gname:
                    items.append((b, label, desc))
                    break
        lv.addStretch(1)
        left_scroll.setWidget(host)
        left.addWidget(left_scroll, stretch=1)
        root.addLayout(left)

    def _filter(self, text=""):
        """按名称/说明过滤按钮；某组一个都不剩就整组隐藏"""
        q = (text or "").strip().lower()
        for box, items in getattr(self, "_groups", []):
            shown = 0
            for b, label, desc in items:
                hit = (not q) or (q in label.lower()) or (q in str(desc or "").lower())
                b.setVisible(hit)
                shown += 1 if hit else 0
            box.setVisible(shown > 0)

    def _visible_buttons(self):
        out = []
        for _box, items in getattr(self, "_groups", []):
            for b, _l, _d in items:
                if b.isVisible():
                    out.append(b)
        return out

    def _run_only_match(self):
        """回车：只剩一个匹配时直接执行它，省一次点击"""
        bs = self._visible_buttons()
        if len(bs) == 1:
            bs[0].click()

        # 右：结果
        right = QVBoxLayout()
        right.addWidget(QLabel("运行结果："))
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(
            "font-family:Consolas,'Microsoft YaHei';font-size:13px;")
        self.out.setPlainText(
            "点左边的按钮运行。\n\n"
            "· 这些功能原先只是登记了但没人调用，现在都接上了入口\n"
            "· 所有动作在后台跑，界面不会卡\n"
            "· 会改数据的动作（记忆整理 / 归档 / 数据清洗）会先问你一遍")
        right.addWidget(self.out, stretch=1)
        root.addLayout(right, stretch=1)

    # ---------------- 动作 ----------------
    def _need_arg(self, ask, label):
        """需要输入的，先问用户；返回 (要不要继续, 额外参数)"""
        if not ask:
            return True, []
        if ask == "file":
            p, _ = QFileDialog.getOpenFileName(
                self, label, "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)")
            return (bool(p), [p])
        if ask == "savezip":
            p, _ = QFileDialog.getSaveFileName(
                self, label, os.path.join(os.path.expanduser("~"), "Desktop",
                                          "小6导出.zip"),
                "压缩包 (*.zip)")
            return (bool(p), [p])
        if ask == "topic":
            t, ok = QInputDialog.getText(self, label, "辩论话题：")
            return (bool(ok and t.strip()), [t.strip()] if t.strip() else [])
        if ask == "message":
            t, ok = QInputDialog.getMultiLineText(self, label, "要投票的问题：")
            return (bool(ok and t.strip()), [t.strip()] if t.strip() else [])
        if ask == "password":
            p, ok = QInputDialog.getText(self, label, "设置一个密码（用于加密）：",
                                         QLineEdit.Password)
            if not (ok and p):
                return False, []
            out, ok2 = QFileDialog.getSaveFileName(
                self, label, os.path.join(os.path.expanduser("~"), "Desktop",
                                          "小6记忆加密.bin"), "加密文件 (*.bin)")
            return (bool(ok2 and out), [out, p] if ok2 and out else [])
        return True, []

    def _do(self, label, mod, meth, desc, need_confirm, ask):
        if need_confirm:
            r = QMessageBox.question(
                self, "确认", "%s\n\n%s\n\n确定要做吗？" % (label, desc),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                self.out.setPlainText("已取消：%s" % label)
                return
        ok, extra = self._need_arg(ask, label)
        if not ok:
            self.out.setPlainText("已取消：%s" % label)
            return

        self.out.setPlainText("▶ %s 运行中…（后台执行，界面不卡）" % label)

        def _work():
            # 确保模块已加载（懒加载走 trunk.call 的探测惯用法）
            self.trunk.call(mod, "__no__")
            m = self.trunk.modules.get(mod)
            if m is None or not hasattr(m, meth):
                return "❌ 模块 %s 没有方法 %s（可能没装上）" % (mod, meth)
            fn = getattr(m, meth)
            if extra:
                return fn(*extra)
            # 先不给参数试；方法有必填参数时，按常见默认值再试几次
            # （get_history(count) / generate(period) / report(days) 这类）
            for args in ((), (7,), (30,), (20,)):
                try:
                    return fn(*args)
                except TypeError:
                    continue
            return "❌ %s.%s 的参数对不上，需要手动调用" % (mod, meth)

        w = BgWorker(_work)
        w.done.connect(lambda r: self.out.setPlainText(
            "%s\n\n%s" % (label, _fmt(r))))
        self._worker = w
        w.start()


def show_module_tools(trunk, parent=None):
    d = ModuleToolsDialog(trunk, parent)
    d.exec_()
    return d
