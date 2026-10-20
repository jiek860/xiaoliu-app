# -*- coding: utf-8 -*-
"""电脑控制：截图、系统信息、命令执行和危险操作。"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime
from core import command_policy

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerSystemToolsMixin:
    def screenshot(self, save_path=None, region=None, window_title=None):
        try:
            from PIL import ImageGrab
            if not save_path:
                save_path = os.path.join(self.base, "data", "screenshot_%s.png" % datetime.now().strftime("%Y%m%d_%H%M%S"))
            if window_title:
                g, _, _ = self._win()
                if not isinstance(g, Exception):
                    hwnd = self._find_window(window_title)
                    if hwnd:
                        try:
                            g.SetForegroundWindow(hwnd)
                        except: pass  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                        time.sleep(0.3)
                        from win32gui import GetWindowRect
                        left, top, right, bottom = GetWindowRect(hwnd)
                        region = (left, top, right, bottom)
            if region:
                if isinstance(region, str):
                    xy = self._parse_xy(region)
                    if xy:
                        region = (0, 0, xy[0], xy[1])
                img = ImageGrab.grab(bbox=tuple(int(v) for v in region), all_screens=True)
            else:
                try:
                    img = ImageGrab.grab(all_screens=True)
                except TypeError:
                    img = ImageGrab.grab()
            img.save(save_path)
            self._log("screenshot", save_path)
            return True, "已截屏: " + save_path
        except Exception as e:
            return False, "截屏失败: %s" % str(e)[:60]

    def system_info(self):
        info = {}
        try:
            import psutil
            v = psutil.virtual_memory()
            info["内存"] = "已用 %d%% (%.1f/%.1f GB)" % (v.percent, v.used / 2**30, v.total / 2**30)
            info["CPU"] = "%d%%" % psutil.cpu_percent(interval=0.3)
            d = psutil.disk_usage(os.path.abspath(os.sep))
            info["磁盘"] = "已用 %d%% (剩 %.1f GB)" % (d.percent, d.free / 2**30)
            try:
                b = psutil.sensors_battery()
                if b:
                    info["电池"] = "%d%%%s" % (b.percent, "（充电中）" if b.power_plugged else "（未充电）")
            except: pass  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
        except Exception as e:
            info["错误"] = str(e)[:60]
        try:
            import platform
            info["系统"] = platform.system() + " " + platform.release()
        except: pass  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
        return True, info

    def _audit_command(self, subject, command, decision, result, reason=""):
        try:
            from core.permission_center import get_permission_center
            pc = get_permission_center(self.trunk)
            pc.audit.append({
                "subject": subject,
                "decision": decision,
                "result": result,
                "reason": str(reason)[:200],
                "command_preview": command_policy.command_preview(command),
                "command_hash": command_policy.command_hash(command),
            })
        except Exception as e:  # 静默是故意的 - 审计失败不改变执行结果
            _x6_swallowed(__name__, e, "write command audit")

    def _authorize_shell(self, command):
        """命令执行统一经过权限中心；无界面时 fail-closed。"""
        if self.trunk is None:
            return False, "没有运行上下文"
        try:
            from core.permission_center import get_permission_center
            pc = get_permission_center(self.trunk)
            info = {"risk": "exec", "readonly": False, "confirm": True,
                    "danger": True, "danger_rule": "电脑控制.允许命令"}
            decision = pc.authorize(
                "computer.shell", info=info,
                args={"command": str(command)})
        except Exception as e:
            return False, "权限中心异常: %s" % str(e)[:100]
        if decision.get("allow"):
            self._audit_command("computer.shell", command, "allow",
                                "authorized", decision.get("reason", ""))
            return True, ""
        if not decision.get("requires_confirm"):
            self._audit_command("computer.shell", command, "deny",
                                "blocked", decision.get("reason", ""))
            return False, decision.get("reason", "命令被拒绝")
        if not getattr(self.trunk, "confirm_cb", None):
            self._audit_command("computer.shell", command, "deny",
                                "no_ui", "没有可用确认界面")
            return False, "当前没有可用的确认界面，拒绝执行命令"
        if not self._confirm("执行命令", str(command)[:200]):
            self._audit_command("computer.shell", command, "deny",
                                "cancelled", "用户取消")
            return False, "已取消"
        try:
            pc.approve("computer.shell", scope="once", reason="命令执行确认")
        except Exception as e:  # 静默是故意的 - 单次授权失败时仍已确认，可继续本次
            _x6_swallowed(__name__, e, "approve once command")
        self._audit_command("computer.shell", command, "allow",
                            "user_confirmed", "命令执行确认")
        return True, ""

    def shutdown(self, delay=30):
        if not self._danger_enabled("关机"):
            self._log("关机", "功能已禁用(规则引擎)", True)
            return False, "关机功能已禁用（可在规则引擎开启 电脑控制.允许关机）"
        try:
            delay = max(0, min(int(delay), 600))
        except (TypeError, ValueError):
            return False, "关机延时必须是 0-600 秒"
        if not self._confirm("关机", "系统将在 %d 秒后关机（执行 shutdown /s）" % delay):
            return False, "已取消关机"
        argv = ["shutdown", "/s", "/t", str(delay)]
        try:
            subprocess.Popen(argv, shell=False, close_fds=True)
            self._log("shutdown", "delay=%d" % delay, True, "已确认")
            self._audit_command("computer.shutdown", " ".join(argv),
                                "allow", "confirmed", "用户确认关机")
            return True, "已安排 %d 秒后关机（可运行 shutdown /a 取消）" % delay
        except Exception as e:
            self._audit_command("computer.shutdown", " ".join(argv),
                                "deny", "failed", str(e)[:120])
            return False, str(e)[:60]

    def restart(self, delay=30):
        if not self._danger_enabled("重启"):
            self._log("重启", "功能已禁用(规则引擎)", True)
            return False, "重启功能已禁用（可在规则引擎开启 电脑控制.允许关机）"
        try:
            delay = max(0, min(int(delay), 600))
        except (TypeError, ValueError):
            return False, "重启延时必须是 0-600 秒"
        if not self._confirm("重启", "系统将在 %d 秒后重启（执行 shutdown /r）" % delay):
            return False, "已取消重启"
        argv = ["shutdown", "/r", "/t", str(delay)]
        try:
            subprocess.Popen(argv, shell=False, close_fds=True)
            self._log("restart", "delay=%d" % delay, True, "已确认")
            self._audit_command("computer.restart", " ".join(argv),
                                "allow", "confirmed", "用户确认重启")
            return True, "已安排 %d 秒后重启（可运行 shutdown /a 取消）" % delay
        except Exception as e:
            self._audit_command("computer.restart", " ".join(argv),
                                "deny", "failed", str(e)[:120])
            return False, str(e)[:60]

    def cancel_shutdown(self):
        argv = ["shutdown", "/a"]
        try:
            subprocess.Popen(argv, shell=False, close_fds=True)
            self._log("cancel_shutdown", "", True)
            self._audit_command("computer.cancel_shutdown", " ".join(argv),
                                "allow", "confirmed", "取消关机计划")
            return True, "已取消关机/重启计划"
        except Exception as e:
            self._audit_command("computer.cancel_shutdown", " ".join(argv),
                                "deny", "failed", str(e)[:120])
            return False, str(e)[:60]

    def status(self):
        return {
            "白名单目录数": len(self.whitelist),
            "总开关(聊天触发)": "开" if self._enabled() else "关",
            "能力": "打开应用/窗口管理/鼠标键盘/截屏/剪贴板/系统信息/文件管理",
            "日志": self.log_path,
        }

    _SHELL_ALLOW = (
        # —— 只读/查询类 ——
        "dir", "type", "where", "tasklist", "whoami", "hostname", "ver",
        "ipconfig", "systeminfo", "tree", "findstr", "more", "fc",
        "python", "py", "git", "pip", "node", "npm", "pytest", "ruff",
        "ffmpeg", "curl", "ping", "nslookup", "netstat", "wmic", "reg",
    )

    _SHELL_META = ("&&", "||", "|", ";", ">", "<", "&", "`", "$(", "%(", "\n", "\r")

    def _shell_enabled(self):
        """命令执行总开关（规则引擎，默认关闭）"""
        try:
            if self.trunk:
                return bool(self.trunk.rule("电脑控制.允许命令", False))
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        return False

    def shell(self, cmd):
        """执行一条白名单内的命令。

        默认关闭。要开启：data/rules/rules.json 里把
        「电脑控制.允许命令」的 value 改成 true（或在规则界面里开）。
        执行前依次经过：元字符检查 -> 命令白名单 -> 权限中心 -> 用户确认 -> 审计。
        """
        c = str(cmd or "").strip()
        if not c:
            return {"ok": False, "错误": "没给命令"}
        if not self._shell_enabled():
            return {"ok": False,
                    "错误": "命令执行已禁用（规则引擎：电脑控制.允许命令 = false）",
                    "怎么开": "data/rules/rules.json 里把该规则 value 设为 true"}
        ok, reason, _token = command_policy.check_command(
            c, allowed=set(self._SHELL_ALLOW))
        if not ok:
            self._audit_command("computer.shell", c, "deny", "policy_rejected",
                                reason)
            return {"ok": False, "错误": reason,
                    "白名单": list(self._SHELL_ALLOW)}
        allowed, why = self._authorize_shell(c)
        if not allowed:
            return {"ok": False, "错误": why}
        t0 = time.time()
        try:
            r = subprocess.run(
                command_policy.build_exec_argv(c)[0],
                shell=False, capture_output=True, text=True,
                timeout=60, cwd=self.base, encoding="utf-8",
                errors="replace")
        except subprocess.TimeoutExpired:
            self._log("shell", "%s -> 超时" % c[:80], True)
            self._audit_command("computer.shell", c, "allow", "timeout",
                                "命令超时")
            return {"ok": False, "错误": "命令超过 60 秒未结束，已放弃"}
        except Exception as e:
            self._log("shell", "%s -> %s" % (c[:80], str(e)[:40]), True)
            self._audit_command("computer.shell", c, "allow", "failed",
                                str(e)[:120])
            return {"ok": False, "错误": str(e)[:80]}
        out = ((r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else ""))[:4000]
        self._log("shell", "%s -> exit=%s" % (c[:80], r.returncode), True,
                  "确认执行" if r.returncode == 0 else "非零退出")
        self._audit_command("computer.shell", c, "allow", "finished",
                            "exit=%s" % r.returncode)
        return {"ok": r.returncode == 0, "命令": c, "退出码": r.returncode,
                "耗时": round(time.time() - t0, 2), "输出": out}

    def _danger_enabled(self, action):
        """关机/重启默认禁用，规则引擎可开启（电脑控制.允许关机）"""
        try:
            if self.trunk:
                return bool(self.trunk.rule("电脑控制.允许关机", False))
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        return False

    def status_line(self):
        return "电脑控制 v11.0 已就绪 | 白名单目录: %d | 日志: %s" % (len(self.whitelist), self.log_path)

    def get_action_history(self, count=10):
        """操作记录：记录做了什么，能撤销"""
        try:
            with open(self.log_path, encoding="utf-8") as f:
                lines = f.readlines()
            return {"最近操作": [l.strip()[:80] for l in lines[-count:]]}
        except:
            return {"操作记录": "无"}

    def safety_check(self, action):
        """安全边界：防止AI误删文件/误操作"""
        # 原来这张表里有 "shutdown" 和 "reboot"，但重启的方法是 restart ——
        # "reboot" in "restart" 是 False，于是 restart 一直被漏判成"不危险"。
        dangerous = ["delete", "remove", "format", "shutdown", "reboot",
                     "restart", "rmtree"]
        for d in dangerous:
            if d in str(action).lower():
                return {"危险": True, "操作": action, "提示": "这个操作很危险，需要确认"}
        return {"危险": False}

    def vision_understand(self, screenshot_path):
        """视觉理解：截图后让AI看懂屏幕内容再操作"""
        multimodal = self.trunk.modules.get("multimodal")
        if not multimodal:
            return {"错误": "多模态模块未加载"}
        return multimodal.describe_image(screenshot_path)
