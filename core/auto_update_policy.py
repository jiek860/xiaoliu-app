# -*- coding: utf-8 -*-
"""自动更新：版本比较、自升级和签名策略。"""
from __future__ import annotations

import os
import re
import sys
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class AutoUpdatePolicyMixin:
    def _allow_self_upgrade(self):
        """「自主.升级」规则，默认开（等于改动前的无条件执行）"""
        try:
            if self.trunk:
                return bool(self.trunk.rule("自主.升级", True))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return True

    @staticmethod
    def _version_tuple(v):
        """'v25.1.6' -> (25, 1, 6)，用于版本比较"""
        out = []
        for seg in str(v).lstrip("vV").split("."):
            m = re.match(r"\d+", seg)
            out.append(int(m.group()) if m else 0)
        return tuple(out)

    def _allow_unsigned_update(self):
        try:
            return bool(self.trunk and self.trunk.config.get("allow_unsigned_update", False))
        except Exception:
            return False

    def _log(self, msg):
        if not self.trunk:
            print(msg)
            return
        try:
            self.trunk._log(msg)
        except Exception:
            print(msg)
