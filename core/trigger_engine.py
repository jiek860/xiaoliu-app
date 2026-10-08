# -*- coding: utf-8 -*-
"""P1-04: 事件触发器 - 文件变化/时间触发动作"""
import os, json, time, threading
from datetime import datetime


class TriggerEngine:
    """事件触发引擎"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "triggers.json")
        self.triggers = self._load()
        self._running = False
        self._thread = None
        self._watchers = {}

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        return {"triggers": []}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.triggers, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def add(self, name, ttype, **kwargs):
        """添加触发器"""
        tid = "t_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        t = {"id": tid, "name": name, "type": ttype, "enabled": True}
        t.update(kwargs)
        self.triggers["triggers"].append(t)
        self._save()
        return tid

    def remove(self, tid):
        """删除触发器"""
        self.triggers["triggers"] = [t for t in self.triggers["triggers"] if t["id"] != tid]
        self._save()

    def start(self):
        """启动后台监听"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        """后台循环检测"""
        while self._running:
            try:
                for t in self.triggers["triggers"]:
                    if not t.get("enabled"):
                        continue
                    if t["type"] == "file_change":
                        self._check_file(t)
                    elif t["type"] == "time":
                        self._check_time(t)
            except Exception:
                pass
            time.sleep(10)

    def _check_file(self, t):
        """检测文件变化"""
        path = t.get("path")
        if not path or not os.path.isdir(path):
            return
        key = "file:" + t["id"]
        if key not in self._watchers:
            self._watchers[key] = set(os.listdir(path))
            return
        now = set(os.listdir(path))
        new = now - self._watchers[key]
        if new:
            self._fire(t, "新文件: " + ", ".join(list(new)[:3]))
        self._watchers[key] = now

    def _check_time(self, t):
        """检测时间触发"""
        now = datetime.now().strftime("%H:%M")
        if t.get("at") == now and t.get("last_fired") != now:
            self._fire(t, "到达时间 " + now)
            t["last_fired"] = now
            self._save()

    def _fire(self, t, detail):
        """触发动作"""
        action = t.get("action", "notify")
        if action == "notify":
            if self.trunk:
                self.trunk._log("触发器[%s]: %s" % (t["name"], detail))
        elif action == "run":
            cmd = t.get("action_args", {}).get("cmd", "")
            if cmd and self.trunk:
                self.trunk.call("code_runner", "run", cmd)

    def stop(self):
        self._running = False

    def run(self, *a):
        return {"触发器数": len(self.triggers["triggers"]), "运行中": self._running}
