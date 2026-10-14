# -*- coding: utf-8 -*-
"""聊天混入：发送、接收、流式渲染、主动搭话"""
import time
from PyQt5.QtCore import Qt
from gui.workers import StreamWorker


class ChatMixin:
    """聊天相关方法"""
    def send(self):
        # [v2 修复] 加空输入提示 + 登录检查 + 异常保护
        text = self.input.toPlainText().strip()
        if not text:
            try:
                self.input.setFocus()
            except Exception:
                pass
            return
        
        # 检查登录状态
        try:
            if not self.account.current_username():
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, "未登录",
                    "请先登录已激活的账号再发送消息")
                return
        # 静默是故意的：这只是个便利提示（问用户要不要装组件）——
        # 它出任何问题都不该影响聊天本身
        except Exception:
            pass
        
        self.last_user_msg = time.time()
        try:
            self.chat.append_user(text)
            self.input.clear()
            anchor = self.chat.append_thinking()
            self._chat_anchor = anchor
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("send 前置步骤失败: %s" % e)
            return
        
        try:
            self.account.save_line("u", text)
        except Exception as e:
            from core.logger import get_logger
            get_logger().warn("保存用户消息失败: %s" % e)
        
        try:
            self.worker = StreamWorker(self.trunk, text)
            self.worker.token.connect(self._on_token)
            self.worker.done.connect(self._on_reply)
            self.worker.start()
            try:
                self.trunk._log("[GUI] 发送消息: %s" % text[:30])
            except Exception:
                pass
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("启动 Worker 失败: %s" % e)
            try:
                if self._chat_anchor is not None:
                    self.chat.remove_from_anchor(self._chat_anchor)
                    self._chat_anchor = None
            except Exception:
                pass

    def _on_token(self, t):
        cur = self.chat.textCursor()
        cur.movePosition(cur.End)
        cur.insertText(t)
        self.chat.setTextCursor(cur)

    def _on_reply(self, a):
        try:
            anchor = getattr(self, "_chat_anchor", None)
            if anchor is not None:
                self.chat.remove_from_anchor(anchor)
                self._chat_anchor = None
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("移除思考块失败: %s" % e)
        
        try:
            self.account.save_line("a", a)
        except Exception:
            pass
        
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
        except Exception:
            pass
        
        try:
            self.chat.render_reply(a, fallback_name=self.ai_name)
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("渲染回复失败: %s" % e)
            self.chat.append("回复渲染失败: " + str(e)[:100])

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
                except Exception:
                    pass
            if choice == "installed":
                self.chat.append(
                    "<div style='color:#16a34a'>✅ 组件装好了，"
                    "再试一次刚才那个功能就行。</div>")
        except Exception:
            pass

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
        except Exception:
            pass

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
        except Exception:
            pass


    def _on_session_clicked(self, item):
        """点击会话列表切换会话"""
        try:
            sid = item.data(Qt.UserRole) or item.text()
            self.account.switch_session(sid)
            self.chat.clear()
            msgs = self.account.load_history(limit=50)
            self.chat.load_history(msgs)
        except Exception as e:
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
        except Exception:
            pass

