# -*- coding: utf-8 -*-
"""Trunk 配置、日志、崩溃钩子和规则读取。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime

from core.secret_store import decrypt_config, encrypt_config

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class TrunkConfigMixin:
    def install_crash_hook(self):
        """把未捕获异常写进 data/logs/crashes.log（由程序入口显式调用）

        只在真跑程序时装 —— 见 __init__ 里的说明，
        别让测试/工具把自己的崩溃写进用户的日志。
        """
        sys.excepthook = self._global_excepthook
        self._owns_excepthook = True
        return True

    def _global_excepthook(self, exc_type, exc_value, exc_tb):
        try:
            with open(self.crash_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] 崩溃: {exc_type.__name__}: {exc_value}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
                f.write("\n")
        except Exception as e:
            self._log("异常: " + str(e)[:80])
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _set_status(self, text):
        """更新 UI 状态栏"""
        if hasattr(self, 'status_cb') and self.status_cb:
            try: self.status_cb(text)
            except Exception as e:
                _x6_swallowed(__name__, e)

    def _warn_user(self, text, detail=None):
        """用户能看见的告警：状态栏一行 + 日志一行。

        后处理（记忆沉淀 / 技能捕获 / 后台整理）出错原来只进日志，界面上完全无感，
        用户只会觉得"它怎么好像没记住"。这类"坏了但不报错"的降级要留个痕迹。
        """
        try:
            self._set_status("⚠ " + text)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        self._log(text + ((": " + str(detail)[:80]) if detail else ""), "WARN")

    def _log(self, msg: str, level: str = "INFO") -> None:
        line = "[%s][%s] %s" % (datetime.now().strftime("%H:%M:%S"), level, msg)
        if level in ("WARN", "ERROR"):
            print(line)
        # 走带轮转的公共写入（core.logger.append_line）。
        #
        # 原来这里是 `with open(self.log_path, "a") as f: f.write(...)` ——
        # 直接追加，**没有任何大小上限**。实测 trunk.log 已经 914 KB 且一直长，
        # 而 gui/log_dialog.py 打开日志中心时是 `f.readlines()` 读整个文件 ——
        # 跑久了会越来越慢，最后打不开。
        # 项目里两条日志路（app.log 有轮转、trunk.log 没有），这次统一。
        try:
            from core.logger import append_line
            append_line(self.log_path, line)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _warn(self, msg): self._log(msg, "WARN")

    def _error(self, msg): self._log(msg, "ERROR")

    def _debug(self, msg): self._log(msg, "DEBUG")

    def _load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                return decrypt_config(json.load(open(self.config_path, "r", encoding="utf-8")))
            except Exception as e:
                self._log("异常: " + str(e)[:80])
        # 首次运行：以脱敏模板 config.default.json 为底生成一份可用的 config.json。
        # 发布包只带模板（不含任何密钥），开发机上那份带密钥的 data/config.json 不打包。
        for tpl in (os.path.join(self.base, "config.default.json"),
                    os.path.join(self.res_base, "config.default.json"),
                    os.path.join(self.res_base, "data", "config.default.json")):
            try:
                if not os.path.exists(tpl):
                    continue
                d = json.load(open(tpl, "r", encoding="utf-8"))
                if isinstance(d, dict) and d:
                    # 模板里的通知默认凭据是应用级密文；写入本机配置前
                    # 还原成明文，再交给 DPAPI 加密。
                    d = decrypt_config(d)
                    _enc, _n = encrypt_config(d)
                    with open(self.config_path, "w", encoding="utf-8") as f:
                        json.dump(_enc, f, ensure_ascii=False, indent=2)
                    self._log("已从模板 config.default.json 生成首次配置")
                    return d
            except Exception as e:
                self._log("读取配置模板失败: " + str(e)[:60])
        return {"model_mode": "本地路由", "local_model": "xiao6-7b:latest",
                "small_model": "xiao6-7b:latest",
                "cloud_model": "qwen-turbo"}

    def save_config(self) -> None:
        """原子写 + 读回校验：先写临时文件再替换；写后立即读回验证；失败保留旧配置"""
        import os as _os
        tmp = self.config_path + ".tmp"
        try:
            _enc, _n = encrypt_config(self.config)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_enc, f, ensure_ascii=False, indent=2)
            # 读回校验
            with open(tmp, encoding="utf-8") as f:
                _back = json.load(f)
            if not isinstance(_back, dict):
                raise ValueError("配置校验失败：不是字典")
            _os.replace(tmp, self.config_path)  # 原子替换
            self._log("配置已保存并校验通过")
            return True
        except Exception as e:
            self._log("配置校验失败，保留旧配置: " + str(e)[:60])
            try:
                if _os.path.exists(tmp):
                    _os.remove(tmp)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            return False

    def confirm(self, action, detail):
        """危险操作确认：GUI 可注册 confirm_cb（弹窗）。

        安全原则是 fail-closed：没有确认界面、回调异常或回调返回空值，
        都必须按用户未同意处理。无界面后台模式不能静默执行危险操作。
        """
        cb = getattr(self, "confirm_cb", None)
        if not cb:
            return False
        try:
            return bool(cb(action, detail))
        except Exception:
            return False

    def rule(self, key, default=None):
        """从规则引擎读参数；规则引擎异常时回退 config/默认（不崩）"""
        try:
            re_ = self.modules.get("rules_engine")
            if re_ is not None:
                return re_.get(key, default)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return default
