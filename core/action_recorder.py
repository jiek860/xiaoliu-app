# -*- coding: utf-8 -*-
"""P1-03: 操作录制回放"""
import os, json, time
from datetime import datetime


class ActionRecorder:
    """操作录制与回放"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.dir = os.path.join(self.base, "data", "recordings")
        os.makedirs(self.dir, exist_ok=True)
        self.recording = False
        self.actions = []
        self.current_name = ""

    def start(self, name):
        """开始录制"""
        self.recording = True
        self.actions = []
        self.current_name = name
        return {"ok": True, "msg": "开始录制: " + name}

    def add_action(self, action_type, **kwargs):
        """添加一个操作"""
        if not self.recording:
            return
        action = {"type": action_type, "time": time.time()}
        action.update(kwargs)
        self.actions.append(action)

    def stop(self):
        """停止录制"""
        self.recording = False
        if not self.actions:
            return {"ok": False, "msg": "没有录到操作"}
        path = os.path.join(self.dir, self.current_name + ".json")
        data = {
            "name": self.current_name,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "actions": self.actions,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"ok": True, "path": path, "count": len(self.actions)}

    def play(self, name, speed=1.0):
        """回放录制"""
        path = os.path.join(self.dir, name + ".json")
        if not os.path.exists(path):
            return {"ok": False, "error": "录制不存在"}
        data = json.load(open(path, encoding="utf-8"))
        cc = self.trunk.modules.get("computer_controller")
        if not cc:
            return {"ok": False, "error": "电脑控制模块未加载"}
        for a in data["actions"]:
            t = a.get("type")
            try:
                if t == "open_app":
                    cc.open_app(a.get("app", ""))
                elif t == "type_text":
                    cc.type_text(a.get("text", ""))
                elif t == "hotkey":
                    cc.hotkey(a.get("keys", ""))
                elif t == "wait":
                    time.sleep(a.get("seconds", 1) / speed)
            except Exception:
                pass
        return {"ok": True, "count": len(data["actions"])}

    def list_recordings(self):
        """列出所有录制"""
        return [f[:-5] for f in os.listdir(self.dir) if f.endswith(".json")]

    def run(self, *a):
        return {"录制数": len(self.list_recordings()), "录制中": self.recording}
