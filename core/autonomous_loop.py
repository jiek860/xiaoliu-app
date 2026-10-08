# -*- coding: utf-8 -*-
"""v26-2.1: 自主循环引擎 完整版"""
import os, json, time, threading
from datetime import datetime


class AutonomousLoop:
    """小6自己做事的引擎，等级0-5"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.state_path = os.path.join(self.base, "data", "autonomous.json")
        self.state = self._load()
        self._running = False
        self._thread = None

    def _load(self):
        if os.path.exists(self.state_path):
            try:
                return json.load(open(self.state_path, encoding="utf-8"))
            except Exception:
                pass
        return {
            "level": 0,
            "last_run": 0,
            "history": [],
            "pending_proposals": [],
        }

    def _save(self):
        try:
            tmp = self.state_path + ".tmp"
            json.dump(self.state, open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            os.replace(tmp, self.state_path)
        except Exception:
            pass

    def set_level(self, level):
        self.state["level"] = max(0, min(5, int(level)))
        self._save()
        return {"ok": True, "level": self.state["level"]}

    def get_level(self):
        return self.state["level"]

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                time.sleep(3600)  # 每小时检查一次
                self._tick()
            except Exception as e:
                if self.trunk:
                    self.trunk._log("自主循环异常: " + str(e)[:80])

    def _tick(self):
        """每次tick按等级做事"""
        level = self.state["level"]
        if level == 0:
            return
        now = time.time()
        if now - self.state["last_run"] < 14400:  # 至少4小时一次
            return
        self.state["last_run"] = now
        self._save()

        # 1. 检查崩溃日志
        crash_log = os.path.join(self.base, "data", "logs", "crashes.log")
        crash_count = 0
        if os.path.exists(crash_log):
            today = datetime.now().strftime("%Y-%m-%d")
            try:
                crash_count = sum(1 for ln in open(crash_log, encoding="utf-8", errors="replace") if today in ln)
            except Exception:
                pass

        # 2. 检查模块健康
        missing = []
        if self.trunk:
            for name in ("llm", "vector_store", "knowledge_graph"):
                if name not in self.trunk.modules:
                    missing.append(name)

        # 3. 按等级汇报
        msg_parts = []
        if crash_count:
            msg_parts.append("今天有%d条崩溃" % crash_count)
        if missing:
            msg_parts.append("未加载模块: %s" % ", ".join(missing))

        if msg_parts:
            self._report("；".join(msg_parts))

        # 等级>=2 生成提议
        if level >= 2 and missing:
            for m in missing:
                self._propose("加载模块 " + m, "load:" + m)

    def _report(self, msg):
        if self.trunk:
            self.trunk._log("[自主] " + msg)
            try:
                self.trunk.publish("autonomous_report", {"msg": msg})
            except Exception:
                pass
        self.state["history"].append({"time": time.strftime("%Y-%m-%d %H:%M"), "msg": msg})
        self.state["history"] = self.state["history"][-50:]
        self._save()

    def _propose(self, title, action):
        """生成待确认提议"""
        p = {"time": time.strftime("%Y-%m-%d %H:%M"), "title": title, "action": action}
        self.state["pending_proposals"].append(p)
        self.state["pending_proposals"] = self.state["pending_proposals"][-10:]
        self._save()
        if self.trunk:
            try:
                self.trunk.publish("autonomous_proposal", p)
            except Exception:
                pass

    def accept_proposal(self, idx):
        """接受提议"""
        try:
            p = self.state["pending_proposals"][idx]
        except Exception:
            return {"错误": "提议不存在"}
        action = p["action"]
        try:
            if action.startswith("load:"):
                self.trunk._load_lazy(action[5:])
            self.state["pending_proposals"].pop(idx)
            self._save()
            return {"ok": True}
        except Exception as e:
            return {"错误": str(e)[:80]}

    def list_proposals(self):
        return self.state["pending_proposals"]

    def stop(self):
        self._running = False

    def status(self):
        return {
            "等级": self.state["level"],
            "上次运行": self.state["last_run"],
            "待确认提议": len(self.state["pending_proposals"]),
            "历史条数": len(self.state["history"]),
        }

    def run(self, *a):
        return self.status()
