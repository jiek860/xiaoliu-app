# -*- coding: utf-8 -*-
"""电脑操作录制与回放。"""
from __future__ import annotations

import json
import os
import time
import uuid


class ComputerRecorder:
    def __init__(self, base):
        self.base = base
        self.dir = os.path.join(base, "data", "computer_recordings")
        os.makedirs(self.dir, exist_ok=True)
        self._actions = []
        self._started_at = 0
        self._name = ""

    def start(self, name=""):
        self._actions = []
        self._started_at = time.time()
        self._name = name or ("recording_" + time.strftime("%Y%m%d_%H%M%S"))
        return self._name

    def record(self, action):
        self._actions.append(dict(action))
        return len(self._actions)

    def stop(self):
        name = self._name or ("recording_" + time.strftime("%Y%m%d_%H%M%S"))
        payload = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "started_at": self._started_at or time.time(),
            "finished_at": time.time(),
            "actions": list(self._actions),
        }
        path = os.path.join(self.dir, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def list_recordings(self):
        out = []
        for fn in sorted(os.listdir(self.dir)):
            if fn.endswith(".json"):
                out.append(os.path.join(self.dir, fn))
        return out

    def load(self, path_or_name):
        p = path_or_name
        if not os.path.isabs(p):
            p = os.path.join(self.dir, path_or_name)
            if not p.endswith(".json"):
                p += ".json"
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def replay(self, agent, path_or_name, title=""):
        rec = self.load(path_or_name)
        actions = rec.get("actions") or []
        return agent.run_actions(actions, title=title or rec.get("name", "回放"))
