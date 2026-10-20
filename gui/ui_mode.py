# -*- coding: utf-8 -*-
"""简单 / 高级 UI 模式管理。

状态存 data/ui_state.json，和业务配置分开：
  * 业务配置（模型、网络、任务预算）是用户资产；
  * UI 状态（模式、引导是否看过）是可丢失的界面偏好。
这样即使用户重置 config，也不会把已经看过教程重新弹一遍。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Dict, Optional

from core.feature_registry import ADVANCED, MODES, SIMPLE

STATE_FILE = "ui_state.json"
_LOCK = threading.RLock()

DEFAULT_UI_STATE: Dict = {
    "ui_mode": SIMPLE,
    "ui_mode_ever_switched": False,
    "show_advanced_entries": False,
    "guidance": {"completed": [], "seen": [], "last_event": ""},
    "appearance": {
        "theme": "system",
        "accent": "blue",
        "font_size": 14,
        "density": "comfortable",
        "code_font": "Consolas",
    },
    "window": {"geometry_b64": "", "maximized": False},
    "updated_at": 0,
}


def normalize_mode(mode: Optional[str]) -> str:
    m = str(mode or "").strip().lower()
    return ADVANCED if m in ("advanced", "高级", "高级模式") else SIMPLE


def _state_path(base: str) -> str:
    return os.path.join(base or ".", "data", STATE_FILE)


def _merge_state(raw) -> Dict:
    out = json.loads(json.dumps(DEFAULT_UI_STATE))
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if k in ("guidance", "appearance", "window"):
            g = v if isinstance(v, dict) else {}
            out.setdefault(k, {}).update(g)
        else:
            out[k] = v
    out["ui_mode"] = normalize_mode(out.get("ui_mode"))
    out["ui_mode_ever_switched"] = bool(out.get("ui_mode_ever_switched"))
    out["show_advanced_entries"] = bool(out.get("show_advanced_entries"))
    if not isinstance(out.get("guidance"), dict):
        out["guidance"] = {"completed": [], "seen": [], "last_event": ""}
    for k in ("completed", "seen"):
        if not isinstance(out["guidance"].get(k), list):
            out["guidance"][k] = []
    return out


def load_ui_state(base: str) -> Dict:
    path = _state_path(base)
    with _LOCK:
        try:
            with open(path, encoding="utf-8") as f:
                return _merge_state(json.load(f))
        except Exception:  # 静默是故意的
            return json.loads(json.dumps(DEFAULT_UI_STATE))


def save_ui_state(base: str, state: Dict) -> Dict:
    path = _state_path(base)
    data = _merge_state(state)
    data["updated_at"] = __import__("time").time()
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    return data


def get_ui_mode(base: str, config: Optional[Dict] = None) -> str:
    """读取模式；state 文件优先，其次兼容旧配置。"""
    state = load_ui_state(base)
    if os.path.exists(_state_path(base)):
        return normalize_mode(state.get("ui_mode"))
    if isinstance(config, dict) and config.get("ui_mode"):
        return normalize_mode(config.get("ui_mode"))
    return SIMPLE


def set_ui_mode(base: str, mode: str, config: Optional[Dict] = None,
                save_config=None, switched: bool = True) -> Dict:
    mode = normalize_mode(mode)
    state = load_ui_state(base)
    state["ui_mode"] = mode
    if switched:
        state["ui_mode_ever_switched"] = True
    state["show_advanced_entries"] = mode == ADVANCED
    state["updated_at"] = __import__("time").time()
    state = save_ui_state(base, state)
    if isinstance(config, dict):
        config["ui_mode"] = mode
        config["ui_mode_ever_switched"] = state["ui_mode_ever_switched"]
        config["show_advanced_entries"] = state["show_advanced_entries"]
        if callable(save_config):
            try:
                save_config()
            except Exception:  # 静默是故意的
                pass
    return state


class UIModeManager:
    """主窗口使用的薄封装；不依赖 Qt，方便单元测试。"""

    def __init__(self, base: str, config: Optional[Dict] = None, save_config=None):
        self.base = base
        self.config = config if isinstance(config, dict) else {}
        self.save_config = save_config
        self._state = load_ui_state(base)
        # 兼容：首次引入时把旧 config 里的模式迁到 state
        if not os.path.exists(_state_path(base)) and self.config.get("ui_mode"):
            self._state["ui_mode"] = normalize_mode(self.config.get("ui_mode"))
            save_ui_state(base, self._state)
        self._mode = get_ui_mode(base, self.config)

    @property
    def state(self) -> Dict:
        return json.loads(json.dumps(self._state))

    @property
    def mode(self) -> str:
        return self._mode

    def is_simple(self) -> bool:
        return self._mode == SIMPLE

    def is_advanced(self) -> bool:
        return self._mode == ADVANCED

    def set_mode(self, mode: str, switched: bool = True) -> str:
        self._state = set_ui_mode(
            self.base, mode, self.config, self.save_config, switched=switched)
        self._mode = self._state["ui_mode"]
        return self._mode

    def toggle(self) -> str:
        return self.set_mode(ADVANCED if self.is_simple() else SIMPLE)

    def mark_switched(self) -> None:
        self._state["ui_mode_ever_switched"] = True
        self._state = save_ui_state(self.base, self._state)
