# -*- coding: utf-8 -*-
"""聊天记录 SQLite（多会话版）v2.0
升级：搜索、统计、导出、会话重命名、删除会话
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import time
import sqlite3


class ChatStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init()

    def _conn(self):
        """P1-4: 开启WAL模式，提升读写性能"""
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    def _init(self):
        c = self._conn()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                session_id TEXT DEFAULT 'default',
                role TEXT,
                text TEXT,
                ts REAL
            )""")
            # 迁移老表：加 session_id 列
            try:
                c.execute("SELECT session_id FROM messages LIMIT 1")
            except:
                c.execute("ALTER TABLE messages ADD COLUMN session_id TEXT DEFAULT 'default'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_session ON messages(username, session_id, ts)")
            # P1-4: FTS5全文索引
            try:
                c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                             USING fts5(username, session_id, role, text,
                                        content='messages', content_rowid='id')""")
                c.execute("""CREATE TRIGGER IF NOT EXISTS messages_ai
                             AFTER INSERT ON messages BEGIN
                             INSERT INTO messages_fts(rowid, username, session_id, role, text)
                             VALUES (new.id, new.username, new.session_id, new.role, new.text);
                             END""")
                c.execute("""CREATE TRIGGER IF NOT EXISTS messages_ad
                             AFTER DELETE ON messages BEGIN
                             INSERT INTO messages_fts(messages_fts, rowid, username, session_id, role, text)
                             VALUES('delete', old.id, old.username, old.session_id, old.role, old.text);
                             END""")
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass  # FTS5不可用时回退LIKE
            c.commit()
        finally:
            c.close()

    def append(self, username, role, text, session_id="default"):
        """P1-4: 显式关闭连接，防止连接泄漏"""
        c = self._conn()
        try:
            c.execute("INSERT INTO messages(username, session_id, role, text, ts) VALUES(?,?,?,?,?)",
                      (username, session_id, role, text, time.time()))
            c.commit()
        finally:
            c.close()

    def edit_message(self, username, session_id, ts, new_text):
        """P1-15: 编辑某条消息"""
        c = self._conn()
        try:
            c.execute("UPDATE messages SET text=? WHERE username=? AND session_id=? AND ts=?",
                      (new_text, username, session_id, ts))
            c.commit()
            return True
        finally:
            c.close()

    def delete_message(self, username, session_id, ts):
        """P1-15: 删除某条消息"""
        c = self._conn()
        try:
            c.execute("DELETE FROM messages WHERE username=? AND session_id=? AND ts=?",
                      (username, session_id, ts))
            c.commit()
            return True
        finally:
            c.close()

    def load(self, username, session_id="default", limit=50):
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, text, ts FROM messages WHERE username=? AND session_id=? ORDER BY ts DESC LIMIT ?",
                (username, session_id, limit)).fetchall()
        return [{"role": r["role"], "text": r["text"], "ts": r["ts"]} for r in reversed(rows)]

    def last_message(self, username, session_id="default", role=None):
        """返回最近一条消息（可按 role 过滤）。"""
        c = self._conn()
        try:
            if role:
                row = c.execute(
                    "SELECT id, role, text, ts FROM messages "
                    "WHERE username=? AND session_id=? AND role=? "
                    "ORDER BY ts DESC, id DESC LIMIT 1",
                    (username, session_id, role)).fetchone()
            else:
                row = c.execute(
                    "SELECT id, role, text, ts FROM messages "
                    "WHERE username=? AND session_id=? "
                    "ORDER BY ts DESC, id DESC LIMIT 1",
                    (username, session_id)).fetchone()
            return dict(row) if row else None
        finally:
            c.close()

    def delete_message_by_id(self, message_id):
        c = self._conn()
        try:
            c.execute("DELETE FROM messages WHERE id=?", (int(message_id),))
            c.commit()
            return True
        finally:
            c.close()

    def delete_last_message(self, username, session_id="default", role=None):
        msg = self.last_message(username, session_id, role=role)
        if not msg:
            return False
        return self.delete_message_by_id(msg["id"])

    def branch_session(self, username, source_session, upto_ts=None):
        """从当前会话复制到新会话，形成对话分支。"""
        new_sid = self.new_session(username)
        c = self._conn()
        try:
            if upto_ts is None:
                rows = c.execute(
                    "SELECT role, text, ts FROM messages "
                    "WHERE username=? AND session_id=? ORDER BY ts, id",
                    (username, source_session)).fetchall()
            else:
                rows = c.execute(
                    "SELECT role, text, ts FROM messages "
                    "WHERE username=? AND session_id=? AND ts<=? "
                    "ORDER BY ts, id",
                    (username, source_session, float(upto_ts))).fetchall()
            for r in rows:
                c.execute(
                    "INSERT INTO messages(username, session_id, role, text, ts) "
                    "VALUES(?,?,?,?,?)",
                    (username, new_sid, r["role"], r["text"], r["ts"]))
            c.commit()
            return new_sid
        finally:
            c.close()

    def list_sessions(self, username):
        """列出所有会话（按最后时间倒序）"""
        with self._conn() as c:
            rows = c.execute(
                "SELECT session_id, MAX(ts) as last_ts, COUNT(*) as cnt FROM messages WHERE username=? GROUP BY session_id ORDER BY last_ts DESC",
                (username,)).fetchall()
        return [{"session_id": r["session_id"], "last_ts": r["last_ts"], "count": r["cnt"]} for r in rows]

    def new_session(self, username):
        """BUG-17: 用uuid防止同秒重复"""
        import uuid
        sid = "s" + uuid.uuid4().hex[:12]
        return sid

    def rename_session(self, username, old_id, new_name):
        """重命名会话"""
        with self._conn() as c:
            c.execute("UPDATE messages SET session_id=? WHERE username=? AND session_id=?",
                      (new_name, username, old_id))

    def delete_session(self, username, session_id):
        """删除会话"""
        with self._conn() as c:
            c.execute("DELETE FROM messages WHERE username=? AND session_id=?", (username, session_id))

    def clear(self, username, session_id=None):
        with self._conn() as c:
            if session_id:
                c.execute("DELETE FROM messages WHERE username=? AND session_id=?", (username, session_id))
            else:
                c.execute("DELETE FROM messages WHERE username=?", (username,))

    def count(self, username=None):
        with self._conn() as c:
            if username:
                return c.execute("SELECT COUNT(*) FROM messages WHERE username=?", (username,)).fetchone()[0]
            return c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def search(self, username, keyword):
        """P1-4: 优先用FTS5全文搜索，失败回退LIKE"""
        c = self._conn()
        try:
            try:
                rows = c.execute(
                    """SELECT m.session_id, m.role, m.text, m.ts
                       FROM messages_fts f
                       JOIN messages m ON m.id = f.rowid
                       WHERE f.username=? AND f.text MATCH ?
                       ORDER BY m.ts DESC LIMIT 20""",
                    (username, keyword)).fetchall()
                return [{"session_id": r["session_id"], "role": r["role"], "text": r["text"], "ts": r["ts"]} for r in rows]
            except Exception:
                # FTS5不可用，回退LIKE
                rows = c.execute(
                    "SELECT session_id, role, text, ts FROM messages WHERE username=? AND text LIKE ? ORDER BY ts DESC LIMIT 20",
                    (username, f"%{keyword}%")).fetchall()
                return [{"session_id": r["session_id"], "role": r["role"], "text": r["text"], "ts": r["ts"]} for r in rows]
        finally:
            c.close()

    def stats(self, username):
        """统计"""
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM messages WHERE username=?", (username,)).fetchone()[0]
            sessions = c.execute("SELECT COUNT(DISTINCT session_id) FROM messages WHERE username=?", (username,)).fetchone()[0]
        return {"总消息数": total, "会话数": sessions}

    def export(self, username, session_id=None):
        """导出聊天记录"""
        with self._conn() as c:
            if session_id:
                rows = c.execute("SELECT role, text, ts FROM messages WHERE username=? AND session_id=? ORDER BY ts",
                                (username, session_id)).fetchall()
            else:
                rows = c.execute("SELECT session_id, role, text, ts FROM messages WHERE username=? ORDER BY ts",
                                (username,)).fetchall()
        return [dict(r) for r in rows]
