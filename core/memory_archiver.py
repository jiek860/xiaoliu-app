# -*- coding: utf-8 -*-
"""P2-08: 记忆压缩/归档 - 旧记忆自动压缩"""
import os, json, time
from datetime import datetime, timedelta


class MemoryArchiver:
    """旧记忆归档压缩"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.memory_path = os.path.join(self.base, "data", "memory_cards.jsonl")
        self.archive_dir = os.path.join(self.base, "data", "archive")
        os.makedirs(self.archive_dir, exist_ok=True)

    def archive_old(self, days=30):
        """归档超过N天的旧记忆"""
        if not os.path.exists(self.memory_path):
            return {"ok": False, "msg": "记忆文件不存在"}

        cutoff = datetime.now() - timedelta(days=days)
        old = []
        new = []
        for ln in open(self.memory_path, encoding="utf-8"):
            try:
                c = json.loads(ln.strip())
                date_str = c.get("date", "2026-01-01")
                date = datetime.strptime(date_str, "%Y-%m-%d")
                if date < cutoff:
                    old.append(c)
                else:
                    new.append(c)
            except Exception:
                new.append(c)

        if not old:
            return {"ok": True, "归档数": 0}

        # 保存归档
        archive_name = "archive_" + datetime.now().strftime("%Y%m") + ".jsonl"
        archive_path = os.path.join(self.archive_dir, archive_name)
        with open(archive_path, "a", encoding="utf-8") as f:
            for c in old:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # 重写主文件
        with open(self.memory_path, "w", encoding="utf-8") as f:
            for c in new:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        return {"ok": True, "归档数": len(old), "剩余": len(new)}

    def list_archives(self):
        """列出所有归档"""
        return [f for f in os.listdir(self.archive_dir) if f.endswith(".jsonl")]

    def run(self, *a):
        return {"归档文件": len(self.list_archives())}
