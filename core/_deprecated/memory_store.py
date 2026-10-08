# -*- coding: utf-8 -*-
"""记忆卡SQLite存储，替代JSONL，支持快速查询和去重"""
import os, json, sqlite3, time, threading
from core.paths import BASE
class MemoryStore:
    def __init__(self, base=None):
        self.base = base or BASE
        self.db_path = os.path.join(self.base, "data", "memory_cards.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init()
    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c
    def _init(self):
        c = self._conn()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, ts REAL, facts TEXT, feelings TEXT,
                follow_up TEXT, trigger TEXT, facts_hash TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON cards(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hash ON cards(facts_hash)")
            c.commit()
        finally:
            c.close()
    def add(self, card):
        facts = card.get("facts", []) or []
        facts_text = "|".join(facts)
        facts_hash = str(hash(facts_text))
        if self.is_dup(facts_hash):
            return False
        c = self._conn()
        try:
            c.execute("INSERT INTO cards(date, ts, facts, feelings, follow_up, trigger, facts_hash) VALUES(?,?,?,?,?,?,?)",
                (card.get("date", ""), card.get("time", time.time()),
                 json.dumps(facts, ensure_ascii=False), card.get("feelings", ""),
                 card.get("follow_up") or "", card.get("trigger", ""), facts_hash))
            c.commit()
            return True
        finally:
            c.close()
    def is_dup(self, facts_hash):
        c = self._conn()
        try:
            row = c.execute("SELECT 1 FROM cards WHERE facts_hash=? ORDER BY id DESC LIMIT 1", (facts_hash,)).fetchone()
            return row is not None
        finally:
            c.close()
    def recent(self, n=20):
        c = self._conn()
        try:
            rows = c.execute("SELECT * FROM cards ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        finally:
            c.close()
        out = []
        for r in reversed(rows):
            try: facts = json.loads(r["facts"] or "[]")
            except: facts = []
            out.append({"date": r["date"], "time": r["ts"], "facts": facts,
                        "feelings": r["feelings"], "follow_up": r["follow_up"] or None,
                        "trigger": r["trigger"]})
        return out
    def stats(self):
        c = self._conn()
        try: n = c.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        finally: c.close()
        return {"记忆卡总数": n}
    def migrate_from_jsonl(self, jsonl_path):
        if not os.path.exists(jsonl_path): return 0
        n = 0
        try:
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try: card = json.loads(line)
                    except: continue
                    if self.add(card): n +=1
        except: pass
        try: os.replace(jsonl_path, jsonl_path + ".migrated")
        except: pass
        return n
