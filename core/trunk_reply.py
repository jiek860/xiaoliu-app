# -*- coding: utf-8 -*-
"""Trunk 聊天回复主流程和聊天状态。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class TrunkReplyMixin:
    _CHAT_ACTIVE_SEC = 25

    def get_stats(self):
        return self.stats

    def snapshot(self):
        return {"modules": list(self.modules.keys()), "lazy": list(self._lazy.keys())}

    def _chat_busy(self):
        """聊天中（含排队）或回复后120s内返回 True，后台闭环应让路，避免抢 Ollama"""
        if getattr(self, "_chat_in_progress", False):
            return True
        return time.time() < getattr(self, "_chat_active_until", 0)

    _TASK_WORDS = (
        "任务", "帮我完成", "帮我整理", "批量", "分步", "拆解", "自动处理",
        "检查并修复", "生成报告", "制定计划", "完整流程", "从头到尾",
        "整理一下", "分析一下", "对比一下", "批量处理",
    )

    def _should_auto_task(self, text):
        mode = str((self.config or {}).get("task_auto_mode", "auto")).lower()
        if mode == "off":
            return False
        t = str(text or "").strip()
        if mode == "always":
            return bool(t)
        if len(t) < 16:
            return False
        return any(w in t for w in self._TASK_WORDS)

    def reply(self, user_input, on_token=None, force_chat=False,
              cancel_token=None):
        self.last_task_result = None
        try:
            # P0-01: /model 热切换指令拦截
            t = user_input.strip()
            if t.startswith("/model "):
                name = t[7:].strip()
                llm = self.modules.get("llm")
                if llm and hasattr(llm, "switch_model"):
                    r = llm.switch_model(name)
                    if r.get("ok"):
                        return "✅ 已切换到模型: " + name
                    return "❌ 切换失败: " + str(r.get("msg", ""))

            if not force_chat and self._should_auto_task(t):
                try:
                    timeout = float((self.config or {}).get("task_auto_wait_sec", 45))
                except Exception:  # 静默是故意的 - 配置非法时用默认等待时间
                    timeout = 45
                tr = self.get_task_runtime().run_sync(t, timeout=timeout)
                self.last_task_result = dict(tr or {})
                ans = tr.get("结果") or tr.get("错误") or "任务已提交"
                if on_token:
                    try:
                        on_token(str(ans))
                    except Exception as e:  # 静默是故意的 - 流式回调失败不影响任务结果
                        _x6_swallowed(__name__, e, "best-effort fallback")
                if tr.get("ok"):
                    return str(ans)
                return "任务执行失败：%s（任务ID: %s）" % (
                    tr.get("错误", "未知错误"), tr.get("task_id", ""))

            self._chat_in_progress = True  # 聊天中（含排队期）：后台闭环持续让路
            self._chat_active_until = time.time() + self._CHAT_ACTIVE_SEC

            # 注入启用的技能提示词（自学习）
            skill_prompt = ""
            try:
                sr = self.modules.get("skill_registry") if hasattr(self, "modules") else None
                if sr is None:
                    # 尝试从 lazy 加载
                    try:
                        from core.skill_registry import SkillRegistry
                        sr = SkillRegistry(self)
                    except Exception:
                        sr = None
                if sr and hasattr(sr, "get_enabled_prompts"):
                    skill_prompt = sr.get_enabled_prompts()
            except Exception as e:
                _x6_swallowed(__name__, e, "skill inject failed")

            # 技能提示词走独立 system 消息，绝不能拼到用户输入前面：
            # 群聊角色/历史记忆会对用户输入做长度截断，拼前面会把用户原话挤掉。
            self._active_skill_prompt = skill_prompt
            try:
                return self._reply_inner(user_input, on_token=on_token,
                                         cancel_token=cancel_token)
            finally:
                self._active_skill_prompt = ""
        except Exception as e:
            # 错误入库（可在「设置 → 系统」里查看/清空）+ 日志，聊天只给友好提示
            self._log("回复异常: " + str(e)[:200])
            try:
                self.call("error_lib", "log", "reply", "reply", str(e))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            return "（抱歉，回复时出了点问题，详情已记入日志）"
        finally:
            # P0-1: 无论成功失败都复位，防止后台闭环永久让路
            self._chat_in_progress = False
            self._chat_active_until = time.time() + self._CHAT_ACTIVE_SEC

    def confirm_plan(self, plan_text, goal=""):
        """弹 GUI 对话框让用户确认/编辑计划（coder_pro 用）

        返回: (approved: bool, edited_plan: str)
        """
        # 先尝试弹 GUI 对话框
        try:
            from gui.plan_confirm_dialog import PlanConfirmDialog
            # 找主窗口
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                for w in app.topLevelWidgets():
                    if w.isVisible():
                        dlg = PlanConfirmDialog(plan_text, goal, parent=w)
                        dlg.exec_()
                        return dlg.is_approved(), dlg.get_edited_plan()
        except Exception:  # 静默是故意的：无 GUI 时降级命令行确认
            pass

        # 没有 GUI 就降级：命令行确认
        print("\n" + "="*60)
        print("目标:", goal)
        print("计划:")
        print(plan_text)
        print("="*60)
        ans = input("确认执行？(y/n): ").strip().lower()
        return ans == "y", plan_text

    def set_private_mode(self, on):
        """P1-21: 开启/关闭隐私模式（无痕会话）"""
        self._private_mode = bool(on)
        self._log("隐私模式: " + ("开启" if on else "关闭"))

    _PIPELINE_COOLDOWN_BASE = 60      # 首次失败后的冷却秒数

    _PIPELINE_COOLDOWN_MAX = 1800     # 冷却上限（30 分钟）

    def _pipeline_ready(self):
        """现在能不能走 pipeline：要么正常可用，要么冷却期已过可以再试一次"""
        if self._pipeline is None:
            return False
        if self._use_pipeline:
            return True
        return time.time() >= getattr(self, "_pipeline_retry_at", 0.0)

    def _pipeline_failed(self, err):
        """pipeline 出错：累计计数、按指数退避设置冷却、记错误库"""
        n = getattr(self, "_pipeline_fail_count", 0) + 1
        self._pipeline_fail_count = n
        cd = min(self._PIPELINE_COOLDOWN_BASE * (2 ** (n - 1)), self._PIPELINE_COOLDOWN_MAX)
        self._use_pipeline = False
        self._pipeline_retry_at = time.time() + cd
        self._legacy_fallback_count = getattr(self, "_legacy_fallback_count", 0) + 1
        self._log("Pipeline异常(连续第%d次，累计%d次)，降级走旧流程，%d 秒后重试: %s"
                  % (n, self._legacy_fallback_count, cd, str(err)[:110]))
        try:
            self.call("error_lib", "log", "pipeline", "reply", str(err))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    _FAIL_MARKS = ("（抱歉", "回复时出了点问题", "功能不可用",
                   "Pipeline 不可用", "服务不可用")

    def _looks_failed(self, answer):
        """判断这次回复其实是失败的（空串 / 明显的错误占位）"""
        try:
            a = "" if answer is None else str(answer).strip()
        except Exception:
            return True
        if not a:
            return True
        if len(a) > 60:          # 正常回答不会这么短就带失败特征
            return False
        return any(m in a for m in self._FAIL_MARKS)

    def _local_fallback_reply(self, user_input):
        """本地模型不可用时的端侧兜底

        local_fallback 这个模块登记了很久、全项目没人调用它。
        它做的就是这件事：Ollama 没起来时，至少回一句人话
        （"启动 Ollama 就能正常聊"），而不是让用户对着空气发呆。
        """
        try:
            if "local_fallback" not in self.modules:
                self.call("local_fallback", "__no__")
            fb = self.modules.get("local_fallback")
            if fb is not None and hasattr(fb, "reply"):
                t = fb.reply(user_input)
                if t:
                    self._log("模型不可用，已用端侧兜底回复")
                    return t
        except Exception as e:
            self._log("端侧兜底失败: %s" % str(e)[:60])
        return None

    def _reply_inner(self, user_input, on_token=None, cancel_token=None):
        """回复主流程 v2：优先 pipeline，出错先降级、冷却后自动重试"""
        answer = None
        if self._pipeline_ready():
            was_degraded = not self._use_pipeline
            try:
                answer = self._pipeline.run(user_input, on_token=on_token,
                                            cancel_token=cancel_token)
            except Exception as e:
                # 取消引起的异常不算 pipeline 故障，别让它进冷却
                if cancel_token is not None and cancel_token.is_cancelled():
                    return ""
                self._pipeline_failed(e)
            else:
                if was_degraded:
                    self._log("Pipeline 已恢复（此前连续失败 %d 次）"
                              % getattr(self, "_pipeline_fail_count", 0))
                # 成功即完全恢复，退避计数清零
                self._use_pipeline = True
                self._pipeline_fail_count = 0
                self._pipeline_retry_at = 0.0
        if answer is None:
            # 回退到旧流程
            # 回退到旧流程（实现在 core/pipeline/legacy_reply.py）
            from core.pipeline.legacy_reply import run as _legacy_reply
            answer = _legacy_reply(self, user_input, on_token=on_token,
                                   cancel_token=cancel_token)
        # 用户已停止：不启用端侧兜底话术（那不是用户要的回答）
        if cancel_token is not None and cancel_token.is_cancelled():
            return answer or ""
        # 全都失败（空回复 / 错误占位）→ 端侧兜底给一句人话
        if self._looks_failed(answer):
            fb = self._local_fallback_reply(user_input)
            if fb:
                return fb
        return answer
