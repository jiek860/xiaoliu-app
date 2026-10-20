# -*- coding: utf-8 -*-
"""协议管理 v1.0 - 首次启动/版本更新时弹窗确认"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import json
from datetime import datetime

# 当前协议版本
PRIVACY_VERSION = "3.2"
TERMS_VERSION = "3.2"
AGREEMENT_VERSION = "3.2"


class Agreement:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or \
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = os.path.join(self.base, "data", "agreement.json")
        self.docs_dir = os.path.join(self.base, "docs")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        os.makedirs(self.docs_dir, exist_ok=True)
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return {}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def need_show(self):
        """是否需要弹窗"""
        if not self.data.get("agreed"):
            return True
        if self.data.get("version") != AGREEMENT_VERSION:
            return True
        if self.data.get("privacy_version") != PRIVACY_VERSION:
            return True
        if self.data.get("terms_version") != TERMS_VERSION:
            return True
        return False

    def agree(self, user="guest"):
        """用户同意"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history = self.data.get("history", [])
        history.append({
            "version": AGREEMENT_VERSION,
            "time": now,
            "action": "agree",
            "user": user,
        })
        self.data = {
            "agreed": True,
            "version": AGREEMENT_VERSION,
            "privacy_version": PRIVACY_VERSION,
            "terms_version": TERMS_VERSION,
            "time": now,
            "user": user,
            "history": history[-20:],
        }
        self._save()

    def disagree(self, user="guest"):
        """用户不同意"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history = self.data.get("history", [])
        history.append({
            "version": AGREEMENT_VERSION,
            "time": now,
            "action": "disagree",
            "user": user,
        })
        self.data["history"] = history[-20:]
        self._save()

    def get_status(self):
        """获取当前状态"""
        return {
            "需要弹窗": self.need_show(),
            "已同意": bool(self.data.get("agreed")),
            "当前协议版本": AGREEMENT_VERSION,
            "当前隐私版本": PRIVACY_VERSION,
            "当前用户协议版本": TERMS_VERSION,
            "上次同意时间": self.data.get("time", "从未"),
        }

    def _read_doc(self, name):
        """读协议文本：先找 docs/，再退回项目根目录

        为什么要回退：打包时（sync_package.py / make_share_zip.py）
        不一定带 docs/ 目录，但根目录的 隐私政策.txt / 用户协议.txt 会带。
        以前只认 docs/  结果打包版首次启动弹窗显示「（隐私政策文件未找到）」。
        """
        for p in (os.path.join(self.docs_dir, name),
                  os.path.join(self.base, name)):
            if os.path.exists(p):
                try:
                    return open(p, encoding="utf-8").read()
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
        return "（%s 未找到  请检查程序目录下是否有这个文件）" % name

    def read_privacy(self):
        """读隐私政策文本"""
        return self._read_doc("隐私政策.txt")

    def read_terms(self):
        """读用户协议文本"""
        return self._read_doc("用户协议.txt")

    def run(self):
        return self.get_status()
