# -*- coding: utf-8 -*-
"""聊天混入：发送、接收、流式渲染、主动搭话"""
import time
from PyQt5.QtCore import Qt
from gui.workers import StreamWorker

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class ChatMixin:
    """聊天相关方法"""
    def send(self):
        # [v2 修复] 加空输入提示 + 登录检查 + 异常保护
        text = self.input.toPlainText().strip()
        if not text:
            try:
                self.input.setFocus()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
            return

        # 上一条还在回复时不要并行发：两个 Worker 同时往同一个视图写字，
        # 内容会交错。给一句可执行的提示（Esc 可停），而不是静默丢弃。
        try:
            w = getattr(self, "worker", None)
            if w is not None and w.isRunning():
                self.chat.append_system("上一条还在回复，按 Esc 停止后再发送")
                self.input.setFocus()
                return
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        
        # [任务模式] 输入框已切到任务时，统一走任务运行时
        try:
            if self._composer_is_task():
                self.last_user_msg = time.time()
                return self._send_task(text)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

        # 检查登录状态
        try:
            if not self.account.current_username():
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, "未登录",
                    "请先登录已激活的账号再发送消息")
                return
        # 静默是故意的：这只是个便利提示（问用户要不要装组件）——
        # 它出任何问题都不该影响聊天本身
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        
        # 统一 Agent 路由：明确的代码/电脑任务先建议进入工作台。
        try:
            from core.agent_router import route_goal
            route = route_goal(
                text, has_code_root=bool(getattr(self, "base", None)))
            if route.get("kind") in ("code", "computer") and \
                    float(route.get("confidence") or 0) >= 0.65:
                from PyQt5.QtWidgets import QMessageBox
                label = "代码 Agent" if route["kind"] == "code" else "电脑 Agent"
                r = QMessageBox.question(
                    self, "检测到可执行的 Agent 任务",
                    "这看起来适合交给「%s」。\n\n%s\n\n"
                    "要打开工作台执行吗？\n"
                    "（AI 面板在编辑器下方，可暂停、人工接管、审批 diff、一键撤销）"
                    % (label, route.get("reason", "")),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if r == QMessageBox.Yes:
                    d = self.agent_journey_dialog(text)
                    if d is not None:
                        self.input.clear()
                        return
        except Exception as e:  # 静默是故意的 - 路由失败不影响普通聊天
            _x6_swallowed(__name__, e, "best-effort fallback")

        # 复杂请求自动提示：一键切到任务模式，而不是让用户自己猜
        force_chat = False
        try:
            if self.trunk._should_auto_task(text):
                from PyQt5.QtWidgets import QMessageBox
                r = QMessageBox.question(
                    self, "检测到复杂任务",
                    "这看起来是一个需要多步执行的任务。\n\n"
                    "要切换到任务模式，显示计划、步骤和结果吗？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if r == QMessageBox.Yes:
                    self._set_composer_mode("task")
                    self.last_user_msg = time.time()
                    return self._send_task(text)
                force_chat = True
        except Exception:  # 静默是故意的
            force_chat = False

        self.last_user_msg = time.time()
        try:
            self.chat.append_user(text)
            self.input.clear()
            anchor = self.chat.append_thinking()
            self._chat_anchor = anchor
            # 流式重绘状态：首帧立即出，之后按时间节流，避免每来一个字都重排。
            self._stream_buf = []
            self._stream_rendered_at = 0.0
            self._stream_rendered_len = 0
            self._stream_rendered_once = False
            # 新一条开始：清掉上一条的停止标记，否则这一条会被当成已停止
            self._stop_requested = False
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("send 前置步骤失败: %s" % e)
            return
        
        try:
            self.account.save_line("u", text)
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().warn("保存用户消息失败: %s" % e)
        
        try:
            self.worker = StreamWorker(self.trunk, text, force_chat=force_chat)
            self.worker.token.connect(self._on_token)
            self.worker.done.connect(self._on_reply)
            self.worker.start()
            try:
                self.trunk._log("[GUI] 发送消息: %s" % text[:30])
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("启动 Worker 失败: %s" % e)
            try:
                if self._chat_anchor is not None:
                    self.chat.remove_from_anchor(self._chat_anchor)
                    self._chat_anchor = None
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

    _STREAM_RENDER_INTERVAL = 0.12

    def _on_token(self, t):
        # Esc 之后可能还有已排队的 token 信号：直接丢掉，不能把半条内容
        # 追加到"已停止生成"提示后面。
        if getattr(self, "_stop_requested", False):
            return
        # 用户往上翻历史时不要抢滚动条；贴底时才自动跟随。
        try:
            stick = self.chat.at_bottom()
        except Exception:  # 静默是故意的
            stick = True
        try:
            self._stream_buf = getattr(self, "_stream_buf", []) + [str(t)]
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        renderer = getattr(self.chat, "stream_render", None)
        if callable(renderer):
            self._stream_tick(renderer)
        else:
            # 没有流式重绘能力时退回"直接追加"（测试替身/旧视图）。
            cur = self.chat.textCursor()
            cur.movePosition(cur.End)
            cur.insertText(t)
            self.chat.setTextCursor(cur)
        if stick:
            try:
                self.chat.scroll_to_bottom()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

    def _stream_tick(self, renderer):
        """按节流间隔把缓冲内容整体重绘成气泡，首帧立即出。"""
        now = time.monotonic()
        text = "".join(getattr(self, "_stream_buf", []) or [])
        first = not getattr(self, "_stream_rendered_once", False)
        grown = len(text) - int(getattr(self, "_stream_rendered_len", 0))
        if not first and now - float(getattr(self, "_stream_rendered_at", 0)) \
                < self._STREAM_RENDER_INTERVAL and grown < 120:
            return
        try:
            self._chat_anchor = renderer(
                getattr(self, "_chat_anchor", None), text, self.ai_name)
            self._stream_rendered_at = now
            self._stream_rendered_len = len(text)
            self._stream_rendered_once = True
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def stop_reply(self):
        """Esc：停止当前回复（保留已收到的部分内容）"""
        w = getattr(self, "worker", None)
        if w is None or not w.isRunning():
            return False
        try:
            w.stop()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 断开信号，避免后台线程跑完后把完整结果盖到"已停止"的界面上。
        for sig, slot in ((w.token, self._on_token), (w.done, self._on_reply)):
            try:
                sig.disconnect(slot)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        self._stop_requested = True
        partial = "".join(getattr(self, "_stream_buf", []) or [])
        self._stream_buf = []
        self._stream_rendered_once = False
        try:
            anchor = getattr(self, "_chat_anchor", None)
            if anchor is not None:
                self.chat.remove_from_anchor(anchor)
                self._chat_anchor = None
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            partial_text = partial.strip()
            if partial_text:
                # 已收到的部分按 Markdown 渲染，并写进会话历史 ——
                # 原来停止后既不保存也不排版，切换会话这半条回复就没了。
                try:
                    self.chat.render_reply(partial_text,
                                           fallback_name=self.ai_name)
                except Exception:  # 静默是故意的
                    self.chat.append_plain(self.ai_name, partial_text)
                try:
                    self.account.save_line("a", partial_text)
                except Exception as e:  # 静默是故意的
                    _x6_swallowed(__name__, e, "save stopped partial reply")
            self.chat.append_system("已停止生成（已保留当前内容）")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 线程还在后台收尾，留引用防止 QThread 被回收时崩溃。
        try:
            self._zombie_workers = getattr(self, "_zombie_workers", []) + [w]
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        self.worker = None
        try:
            self.input.setFocus()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return True

    def _on_reply(self, a):
        if getattr(self, "_stop_requested", False):
            self._stop_requested = False
            return
        self._stream_buf = []
        self._stream_rendered_once = False
        try:
            anchor = getattr(self, "_chat_anchor", None)
            if anchor is not None:
                self.chat.remove_from_anchor(anchor)
                self._chat_anchor = None
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("移除思考块失败: %s" % e)
        
        try:
            self.account.save_line("a", a)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        
        try:
            tts = str(a)
            segs = self.chat.split_group(tts)
            if segs:
                d6 = dict(segs).get("小6")
                if d6:
                    tts = d6
            # 只有自动朗读开关开着才播报
            if tts.strip() and self.trunk.config.get("auto_tts", False):
                self.speech.speak_async(tts.strip())
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        
        try:
            self.chat.render_reply(a, fallback_name=self.ai_name)
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("渲染回复失败: %s" % e)
            self.chat.append("回复渲染失败: " + str(e)[:100])

        # 第一次聊天完成 + 自动任务结果卡片
        try:
            self._mark_guide_event("first_chat")
            self._handle_last_task_result()
            self._update_empty_state()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

        # 权限 / 网络 / 工具不存在等失败，给一条唯一下一步
        try:
            low = str(a or "").lower()
            triggers = ("权限", "拒绝", "网络被拒绝", "工具不存在", "not found")
            if any(k in low for k in triggers):
                guide = self.guidance.for_error(str(a))
                self.chat.append_guidance_card(
                    guide.get("title"), guide.get("message"),
                    "guidance://" + guide.get("action"),
                    guide.get("action_label"))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

        # 回复里如果出现了"缺依赖"，弹一个"要不要现在装"的框
        # （改之前只留一句让用户自己复制命令的文字，很多人到这就放弃了，
        #   那个功能就白做了）
        self._maybe_offer_install(a)

    def _maybe_offer_install(self, reply_text):
        """回复里提示了"缺某个组件"时，问用户要不要现在就装

        ⚠️ 三条约束，都是为了别让它变成骚扰：
          ① 同一个包**只问一次**（问过就记在 self._dep_asked 里）
          ② 用户选过"不再问我这个组件"就永久跳过（存进 config）
          ③ 任何异常都吞掉 —— 这只是个便利提示，不该影响聊天
        """
        try:
            from core.error_text import missing_package
            pkg = missing_package(reply_text)
            if not pkg:
                return
            asked = getattr(self, "_dep_asked", None)
            if asked is None:
                asked = set(self.trunk.config.get("dep_never_ask", []) or [])
                self._dep_asked = asked
            if pkg in asked:
                return
            asked.add(pkg)

            from gui.dep_dialog import show_dep_dialog
            choice = show_dep_dialog(self, pkg, feature="刚才那个功能",
                                     base=getattr(self.trunk, "base", None))
            if choice == "never":
                try:
                    cur = list(self.trunk.config.get("dep_never_ask", []) or [])
                    if pkg not in cur:
                        cur.append(pkg)
                        self.trunk.config["dep_never_ask"] = cur
                        self.trunk.save_config()
                # 静默是故意的：记"不再问"失败只是下次可能再问一遍，
                # 不该因此打断聊天
                except Exception as e:  # 静默是故意的
                    _x6_swallowed(__name__, e, "best-effort fallback")
            if choice == "installed":
                self.chat.append(
                    "<div style='color:#16a34a'>✅ 组件装好了，"
                    "再试一次刚才那个功能就行。</div>")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    # ---------------- 对话编辑 / 重新生成 / 分支 ----------------
    def _last_exchange(self):
        store = self.account.chat_store
        user = store.last_message(self.account.username, self.account.session,
                                  role="u")
        assistant = store.last_message(self.account.username,
                                       self.account.session, role="a")
        return user, assistant

    def _delete_last_exchange(self):
        store = self.account.chat_store
        user, assistant = self._last_exchange()
        if assistant:
            store.delete_message_by_id(assistant["id"])
        if user:
            store.delete_message_by_id(user["id"])
        return user

    def edit_last_user_message(self):
        """把上一条用户消息放回输入框，重新编辑后发送。"""
        user = self._delete_last_exchange()
        if not user:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "编辑消息", "当前会话还没有可编辑的用户消息")
            return
        try:
            self.chat.clear()
            self.chat.load_history(
                self.account.load_history(limit=50))
            self.input.setPlainText(user.get("text", ""))
            self.input.setFocus()
            self._update_empty_state()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def regenerate_last_reply(self):
        """删除上一轮问答后重新发送同一条用户消息。"""
        user = self._delete_last_exchange()
        if not user:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "重新生成", "当前会话还没有可重新生成的问答")
            return
        try:
            self.chat.clear()
            self.chat.load_history(self.account.load_history(limit=50))
            self.input.setPlainText(user.get("text", ""))
            self.send()
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("重新生成失败: %s" % e)

    def branch_current_conversation(self):
        """把当前会话复制到一个新分支并切换过去。"""
        try:
            old_sid = self.account.session
            new_sid = self.account.chat_store.branch_session(
                self.account.username, old_sid)
            self.account.switch_session(new_sid)
            self.chat.clear()
            self.chat.load_history(self.account.load_history(limit=50))
            self._refresh_session_list()
            self._update_empty_state()
            try:
                self.statusBar().showMessage(
                    "已创建对话分支：%s" % new_sid, 4000)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "创建分支", str(e)[:120])

    def _persona_opening(self):
        try:
            pers = self.trunk.modules.get("personality") or \
                   self.trunk._load_lazy("personality")
            if not pers:
                return
            line = pers.proactive_lines() or pers.dream()
            if line:
                self.chat.append(
                    f'<b style="color:#1a1a2e">{self.ai_name}:</b><br>{line}<br>'
                )
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _check_proactive(self):
        try:
            if time.time() - self.last_user_msg < 15 * 60:
                return
            pers = self.trunk.modules.get("personality")
            if not pers:
                return
            line = pers.proactive_lines()
            if line:
                self.chat.append(
                    f'<b style="color:#1a1a2e">{self.ai_name}:</b><br>{line}<br>'
                )
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")


    def _on_session_clicked(self, item):
        """点击会话列表切换会话"""
        try:
            sid = item.data(Qt.UserRole) or item.text()
            self.account.switch_session(sid)
            self.chat.clear()
            msgs = self.account.load_history(limit=50)
            self.chat.load_history(msgs)
        except Exception as e:  # 静默是故意的
            self.chat.append(f"<span style='color:#c00'>切换会话失败: {e}</span>")

    def _refresh_session_list(self):
        """刷新会话列表"""
        try:
            self.session_list.clear()
            sessions = self.account.list_sessions()
            if not sessions:
                from PyQt5.QtWidgets import QListWidgetItem
                it = QListWidgetItem("💬 默认对话")
                it.setData(Qt.UserRole, "default")
                self.session_list.addItem(it)
                return
            for s in sessions:
                sid = s.get("session_id", "default")
                cnt = s.get("count", 0)
                from PyQt5.QtWidgets import QListWidgetItem
                it = QListWidgetItem(f"💬 {sid} ({cnt})")
                it.setData(Qt.UserRole, sid)
                self.session_list.addItem(it)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")