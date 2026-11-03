# -*- coding: utf-8 -*-
"""P1-03: 操作录制回放（完整版）

2026-11-02 补的四件事
--------------------
1. **落盘走 ``data_path``**：原来自己拼 ``base/data/recordings``，测试把
   ``Trunk.data_dir`` 重定向到临时目录时，录制仍然写进用户真数据目录。
2. ``add_action`` 在没录制时原来返回 ``None`` —— 调用方无法区分
   "记上了" 和 "根本没在录"，动作就这么静默丢了。现在返回结构化结果。
3. ``stop()`` 空录制原来**先写文件再报错**，会把同名旧录制覆盖成空文件。
   现在先判空，不碰磁盘。
4. ``play()`` 单个动作失败原来一律吞掉，最后照样 ``{"ok": True}``。
   现在报 ``执行 / 失败 / 跳过``，看不出问题就等于没回放成功。

目录：``data/recordings/<名称>.json``（名称经 ``safe_name``，不允许路径分隔符）。
"""
import json
import os
import time
from datetime import datetime

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

from core.path_safety import safe_join, safe_name

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

# 回放支持的动作类型（其余类型只记不播，播时报"跳过"）
PLAYABLE = ("open_app", "type_text", "hotkey", "wait")
MAX_ACTIONS = 2000


class ActionRecorder:
    """操作录制与回放"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.dir = data_path(trunk, "recordings")
        self.recording = False
        self.actions = []
        self.current_name = ""

    # ------------------------------------------------------------------
    def _ensure_dir(self):
        """确保录制目录存在；返回错误说明（"" 表示没问题）"""
        try:
            os.makedirs(self.dir, exist_ok=True)
            return ""
        except Exception as e:
            _x6_swallowed(__name__, e, "recordings dir")
            return "建不出录制目录：%s: %s" % (type(e).__name__, str(e)[:60])

    def _path(self, name):
        """名称 → 安全文件路径；名字非法返回 None"""
        clean = safe_name(name, default="")
        if not clean:
            return None
        return safe_join(self.dir, clean + ".json")

    def start(self, name=None):
        """开始录制。已在录制 / 名字非法 / 同名已存在都会明确拒绝。"""
        if self.recording:
            return {"ok": False,
                    "msg": "已经在录制「%s」，先 stop() 再开新的"
                           % (self.current_name or "未命名")}
        if not name:
            name = "录制_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._path(name)
        if not path:
            return {"ok": False, "msg": "录制名非法（不能带路径分隔符）"}
        if os.path.exists(path):
            return {"ok": False, "msg": "同名录制已存在，换个名字或先删掉",
                    "文件": path}
        err = self._ensure_dir()
        if err:
            return {"ok": False, "msg": err}

        self.recording = True
        self.actions = []
        self.current_name = safe_name(name)
        return {"ok": True, "msg": "开始录制: " + self.current_name,
                "名称": self.current_name}

    def add_action(self, action_type, **kwargs):
        """记一个操作；没在录制时明确失败（原来返回 None，动作会静默丢）"""
        if not self.recording:
            return {"ok": False, "msg": "没有在录制，动作没记上"}
        if not str(action_type or "").strip():
            return {"ok": False, "msg": "动作类型不能为空"}
        action = {"type": str(action_type).strip(), "time": round(time.time(), 3)}
        action.update(kwargs)
        self.actions.append(action)
        if len(self.actions) > MAX_ACTIONS:
            self.actions = self.actions[-MAX_ACTIONS:]
        return {"ok": True, "动作数": len(self.actions),
                "支持回放": action["type"] in PLAYABLE}

    def stop(self):
        """停止录制并落盘（空录制不落盘，避免覆盖同名旧录制）"""
        if not self.recording:
            return {"ok": False, "msg": "没有在录制"}
        self.recording = False
        name, actions = self.current_name, self.actions
        if not actions:
            self.actions = []
            self.current_name = ""
            return {"ok": False, "msg": "没有录到操作，未生成录制文件",
                    "动作数": 0}

        path = self._path(name)
        if not path:
            return {"ok": False, "msg": "录制名非法", "动作数": len(actions)}
        err = self._ensure_dir()
        if err:
            return {"ok": False, "msg": err, "动作数": len(actions)}
        data = {"name": name,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "actions": actions}
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            _x6_swallowed(__name__, e, "recording save")
            return {"ok": False,
                    "msg": "写录制失败：%s: %s" % (type(e).__name__, str(e)[:60]),
                    "动作数": len(actions)}

        self.actions = []
        self.current_name = ""
        return {"ok": True, "path": path, "文件": path,
                "count": len(actions), "动作数": len(actions), "名称": name}

    # ------------------------------------------------------------------
    def get_recording(self, name):
        """读一份录制（不播放），供界面/导出用"""
        path = self._path(name)
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "录制不存在或名称非法"}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {"ok": False, "error": "录制文件读不出来：%s: %s"
                                          % (type(e).__name__, str(e)[:60])}
        if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
            return {"ok": False, "error": "录制文件格式不对（缺 actions 列表）"}
        return {"ok": True, "录制": data, "动作数": len(data["actions"])}

    def play(self, name, speed=1.0):
        """回放录制；逐条报执行/失败/跳过，不再"全吞掉还报成功"。"""
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            speed = 1.0
        speed = max(0.1, min(10.0, speed))       # speed=0 会除零

        got = self.get_recording(name)
        if not got.get("ok"):
            return {"ok": False, "error": got.get("error")}
        actions = got["录制"]["actions"]

        cc = (getattr(self.trunk, "modules", None) or {}).get(
            "computer_controller") if self.trunk is not None else None
        if not cc:
            return {"ok": False, "error": "电脑控制模块未加载", "总数": len(actions)}

        done, failed, skipped, details = 0, 0, 0, []
        for a in actions:
            if not isinstance(a, dict):
                skipped += 1
                continue
            kind = str(a.get("type") or "")
            try:
                if kind == "open_app":
                    cc.open_app(a.get("app", ""))
                elif kind == "type_text":
                    cc.type_text(a.get("text", ""))
                elif kind == "hotkey":
                    cc.hotkey(a.get("keys", ""))
                elif kind == "wait":
                    seconds = a.get("seconds", 1)
                    seconds = float(seconds) if isinstance(seconds, (int, float)) \
                        else 1.0
                    time.sleep(max(0.0, seconds) / speed)
                else:
                    skipped += 1          # 这类动作当初就没被支持
                    details.append("跳过未知动作：%s" % (kind or "空"))
                    continue
                done += 1
            except Exception as e:
                _x6_swallowed(__name__, e, "replay action")
                failed += 1
                details.append("%s 失败：%s: %s"
                               % (kind, type(e).__name__, str(e)[:60]))

        r = {"ok": failed == 0, "总数": len(actions), "执行": done,
             "失败": failed, "跳过": skipped}
        if details:
            r["明细"] = details[:5]
            r["说明"] = ("%d 条没执行成功（上面列了前 5 条）"
                         % (failed + skipped))
        return r

    # ------------------------------------------------------------------
    def list_recordings(self):
        """列出所有录制名（排序、跳过隐藏文件与临时文件）"""
        try:
            names = [f[:-5] for f in os.listdir(self.dir)
                     if f.endswith(".json") and not f.startswith(".")]
        except Exception as e:
            _x6_swallowed(__name__, e, "list recordings")
            return []
        return sorted(names)

    def delete(self, name):
        path = self._path(name)
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "不存在或名称非法"}
        try:
            os.unlink(path)
        except Exception as e:
            _x6_swallowed(__name__, e, "delete recording")
            return {"ok": False, "error": "删不掉：%s" % str(e)[:60]}
        return {"ok": True, "名称": safe_name(name)}

    def to_markdown(self):
        """录制清单（给人看的入口）"""
        lines = ["# 操作录制\n"]
        names = self.list_recordings()
        if not names:
            lines.append("- 还没有录制（说「开始录制」就能记）\n")
            return "\n".join(lines) + "\n"
        for name in names:
            got = self.get_recording(name)
            if got.get("ok"):
                info = got["录制"]
                lines.append("- %s：%s 个动作（创建于 %s）"
                             % (name, len(info.get("actions") or []),
                                info.get("created", "未知时间")))
            else:
                lines.append("- %s：读不出来（%s）"
                             % (name, got.get("error", "")))
        return "\n".join(lines) + "\n"

    def export_md(self, path=None):
        """把录制清单写成 md（默认 data/recordings.md）"""
        path = path or data_path(self.trunk, "recordings.md")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self.to_markdown())
            os.replace(tmp, path)
        except Exception as e:
            _x6_swallowed(__name__, e, "export recordings md")
            return {"ok": False, "错误": "写不出去：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "文件": path, "录制数": len(self.list_recordings())}

    def run(self, *a):
        return {"录制数": len(self.list_recordings()), "录制中": self.recording,
                "当前": self.current_name, "已记动作": len(self.actions)}
