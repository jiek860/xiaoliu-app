# -*- coding: utf-8 -*-
"""P2-19: 知识图谱SQLite存储后端"""
import os, sqlite3


class GraphDB:
    """三元组SQLite存储"""
    def __init__(self, trunk=None):
        # 兼容两种调用：
        #   1) 微核协议 —— 传 trunk（core/lazy_config.py 登记的就是这种）
        #   2) 直接传项目根路径字符串（旧调用方式）
        # 历史 bug：原来参数名叫 base 且必填，_load_lazy 调 cls(trunk) 时
        # 会把 Trunk 对象当路径用，导致 graph_db 永远加载失败。
        if isinstance(trunk, (str, bytes, os.PathLike)):
            self.trunk = None
            base = os.fspath(trunk)
        else:
            self.trunk = trunk
            base = getattr(trunk, "base", None) or os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))
        self.base = base
        self.db_path = os.path.join(base, "data", "graph.db")
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        c = self._conn()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS triples(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                predicate TEXT,
                object TEXT,
                time REAL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_subj ON triples(subject)")
            c.commit()
        finally:
            c.close()

    def add(self, s, p, o):
        import time
        c = self._conn()
        try:
            c.execute("INSERT INTO triples(subject, predicate, object, time) VALUES(?,?,?,?)",
                      (s, p, o, time.time()))
            c.commit()
        finally:
            c.close()

    def query_by_subject(self, subject):
        c = self._conn()
        try:
            rows = c.execute("SELECT * FROM triples WHERE subject=?", (subject,)).fetchall()
            return [{"主体": r["subject"], "关系": r["predicate"], "客体": r["object"]} for r in rows]
        finally:
            c.close()

    def all_triples(self):
        c = self._conn()
        try:
            rows = c.execute("SELECT * FROM triples").fetchall()
            return [{"主体": r["subject"], "关系": r["predicate"], "客体": r["object"]} for r in rows]
        finally:
            c.close()

    def count(self):
        c = self._conn()
        try:
            return c.execute("SELECT COUNT(*) as cnt FROM triples").fetchone()["cnt"]
        finally:
            c.close()

    def run(self, *a):
        """模块统一入口（微核协议）"""
        try:
            return {"三元组数": self.count(), "数据库": self.db_path}
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}
