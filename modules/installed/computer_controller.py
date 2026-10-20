# -*- coding: utf-8 -*-
from modules.base import BaseModule
from core.computer_file_tools import ComputerFileToolsMixin
from core.computer_window_tools import ComputerWindowToolsMixin

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

"""电脑操作 v12.0 - 完整本地电脑操控
能力：打开应用/窗口管理/鼠标键盘/截屏/剪贴板/系统信息/文件白名单+确认
      + 开发者文件工具（读带行号 / 搜内容 / 精确替换并备份）
安全：文件操作限白名单，删除/关机等危险操作弹窗确认，全部动作留日志
"""
import os, re, time, json, shutil, subprocess
from datetime import datetime

from core.path_safety import is_within


# ── 缺依赖时给用户的安装提示（统一走 core.error_text，别各写各的）──
# 为什么改：实测全项目 17 处 "pip install" 提示里**只有 1 处**带国内镜像，
# 其余都让用户直接跑 `pip install xxx` —— 那会走 PyPI 官方源，
# 国内经常慢到以为卡死。现在统一从这里出。
def _ih(pkg):
    try:
        from core.error_text import install_hint
        return install_hint(pkg)
    except Exception:
        return ("py -3 -m pip install --target optional_libs %s "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkg)


from core.computer_app_tools import ComputerAppToolsMixin
from core.computer_input_tools import ComputerInputToolsMixin
from core.computer_system_tools import ComputerSystemToolsMixin
from core.computer_command_parser import ComputerCommandParserMixin


class ComputerController(
    ComputerFileToolsMixin,
    ComputerWindowToolsMixin,
    ComputerAppToolsMixin,
    ComputerInputToolsMixin,
    ComputerSystemToolsMixin,
    ComputerCommandParserMixin,
    BaseModule,
):
    NAME = "computer_controller"

    VERSION = "1.0"

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        # v16修复: 插件装到 modules/installed 后 __file__ 上推两级会错位到 modules/，
        # 导致白名单根目录与日志路径错位；优先用躯干的项目根
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.log_dir = os.path.join(self.base, "data", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "computer_controller.log")
        self.whitelist = [
            self.base,

            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Documents"),
        ]
        # 允许用户在 config 里加白名单根目录，例如：
        #   "文件白名单": ["E:\\projects", "D:\\code"]
        # 不加的话 fs_read/fs_search 就只能读上面那四个根，用途很受限。
        try:
            for extra in (getattr(trunk, "config", {}) or {}).get("文件白名单", []) or []:
                if extra:
                    self.whitelist.append(os.path.expanduser(str(extra)))
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 常用软件表（名称 → 可执行/命令）
        self.known_apps = {
            "记事本": "notepad.exe", "notepad": "notepad.exe",
            "计算器": "calc.exe", "calculator": "calc.exe",
            "画图": "mspaint.exe", "mspaint": "mspaint.exe",
            "写字板": "write.exe", "wordpad": "write.exe",
            "命令提示符": "cmd.exe", "cmd": "cmd.exe", "命令行": "cmd.exe",
            "powershell": "powershell.exe",
            "任务管理器": "taskmgr.exe",
            "控制面板": "control.exe",
            "资源管理器": "explorer.exe", "此电脑": "explorer.exe",
            "设置": "ms-settings:",
            "截图工具": "snippingtool.exe", "截图": "snippingtool.exe",
            "浏览器": None,  # 运行时找默认浏览器
            "edge": None, "微软浏览器": None,
            "chrome": None, "谷歌浏览器": None,
            "steam": None,
            "qq": None, "微信": None,
            "word": None, "excel": None, "ppt": None, "wps": None,
        }

    def _log(self, action, detail="", ok=True, extra=""):
        try:
            line = "[%s] %s | 操作:%s | 详情:%s | 结果:%s %s" % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "✓" if ok else "✗", action, str(detail)[:120], "成功" if ok else "失败", extra)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except: pass  # 静默是故意的 - Agent 防御性回退，不阻塞主流程

    def _enabled(self):
        """电脑控制总开关（聊天触发开关，GUI面板不受影响）"""
        if self.trunk:
            cfg = getattr(self.trunk, "config", {}) or {}
            return bool(cfg.get("电脑控制", True))
        return True

    def _confirm(self, action, detail):
        """危险操作确认：没有确认界面时必须拒绝，不能默认放行。"""
        try:
            if self.trunk and self.trunk.rule("电脑控制.覆盖确认", True) is False:
                # 规则只允许跳过覆盖/写文件的重复确认；
                # 删除/关机/重启仍由调用方自己强制确认。
                pass
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        if not self.trunk or not getattr(self.trunk, "confirm_cb", None):
            return False
        try:
            return bool(self.trunk.confirm(action, detail))
        except Exception:
            return False

    def _check_path(self, path):
        """白名单检查：必须用 realpath + commonpath，不能使用字符串前缀。"""
        try:
            p = os.path.abspath(os.path.expanduser(str(path)))
            return any(is_within(w, p) for w in self.whitelist)
        except Exception:
            return False

    def _safe_path(self, path):
        """把用户给的文件路径限制在白名单内；相对路径落到项目 data 目录"""
        p = str(path or "").strip().strip('"').strip("'")
        if not p or "\x00" in p:
            return None
        p = os.path.expanduser(p)
        if not os.path.isabs(p):
            p = os.path.join(self.base, "data", p)
        p = os.path.abspath(p)
        return p if self._check_path(p) else None

    def _gui(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1
            return pyautogui
        except Exception as e:
            return e

    def _win(self):
        try:
            import win32gui, win32con, win32api
            return win32gui, win32con, win32api
        except Exception as e:
            return e

    def _virtual_screen_rect(self):
        """返回虚拟桌面坐标 (left, top, width, height)，支持多显示器。"""
        from core.screen_geometry import virtual_screen_rect
        fallback = (1920, 1080)
        gui = self._gui()
        if not isinstance(gui, Exception):
            fallback = tuple(gui.size())
        return virtual_screen_rect(fallback)

    def screen_info(self):
        """屏幕坐标信息，供 Agent 做截图/点击坐标换算。"""
        from core.screen_geometry import screen_info
        fallback = (1920, 1080)
        gui = self._gui()
        if not isinstance(gui, Exception):
            fallback = tuple(gui.size())
        return screen_info(fallback)

    def execute(self, action, kwargs):
        fn = getattr(self, action, None)
        if not fn:
            return False, "未知操作: " + action
        try:
            return fn(**kwargs)
        except Exception as e:
            return False, "执行失败: %s" % str(e)[:80]

    def try_handle(self, text):
        """聊天入口：能解析则执行并返回 (True, 结果文本)，否则 (False, None)"""
        if not self._enabled():
            return False, None
        parsed = self.parse(text)
        if not parsed:
            return False, None
        action, kwargs = parsed
        ok, result = self.execute(action, kwargs)
        if isinstance(result, dict):
            result = "\n".join("%s: %s" % (k, v) for k, v in result.items())
        return True, str(result)

    def run(self, action="", *args, **kwargs):
        """统一入口（工具调用/GUI 按钮）：传文本则解析执行，传 (action, kwargs) 则直接执行"""
        if isinstance(action, dict):
            kwargs = dict(action)
            action = kwargs.pop("action", "")
        if args:
            return self.try_handle(args[0])
        if action:
            if kwargs:
                return self.execute(action, kwargs)
            ok, r = self.try_handle(action)
            return r if ok else {"error": r}
        return self.status()
