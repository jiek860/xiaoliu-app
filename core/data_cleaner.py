# -*- coding: utf-8 -*-
"""v26-6.1: 数据去重与清洗（完整版）

三条安全线（2026-11-02 补）
--------------------------
1. **先干跑**：``clean_all(dry_run=True)`` 只统计「会删多少」，一个字都不写。
2. **写前备份**：真要清时默认先把要动的文件拷到
   ``data/cleaning_backup/<时间戳>/``，``restore_backup()`` 可整份回滚。
3. **坏行原样保留**：原来 ``clean_cards`` 读的时候跳过解析失败的行，
   写回却是全量覆盖 —— 那几行就被**永久删掉**了（和
   ``memory_organizer`` 修的是同一类问题）。现在坏行原样写回。

能力表里的 ``clean_data`` 默认仍然是「真的清」（会弹确认框）；
要看影响就先调 ``preview()``（= 干跑）。
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)


class DataCleaner:
    """一键清洗所有数据：聊天 / 记忆 / 图谱"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.db_path = data_path(trunk, "chats.db")
        self.cards_path = data_path(trunk, "memory_cards.jsonl")
        self.graph_path = data_path(trunk, "graph.json")
        self.backup_root = data_path(trunk, "cleaning_backup")

    # ------------------------------------------------------------------
    @staticmethod
    def _flag(value, default=False):
        """把模型/界面传来的开关值转成 bool。

        LLM 传的可能是 JSON 的 ``true``，也可能是字符串 ``"true"/"false"``，
        直接 ``bool("false")`` 会得到 True —— 那样「干跑」就成了「真删」。
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on", "是", "干跑", "只预览"):
            return True
        if text in ("0", "false", "no", "off", "否", "不"):
            return False
        return default

    # ------------------------------------------------------------------
    # 备份 / 回滚
    # ------------------------------------------------------------------
    def list_backups(self):
        """列出已有备份（新的在前）"""
        if not os.path.isdir(self.backup_root):
            return []
        out = []
        for name in sorted(os.listdir(self.backup_root), reverse=True):
            folder = os.path.join(self.backup_root, name)
            if not os.path.isdir(folder):
                continue
            manifest = {}
            try:
                with open(os.path.join(folder, "manifest.json"),
                          encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                manifest = {}
            files = [n for n in os.listdir(folder) if n != "manifest.json"]
            out.append({"名称": name, "时间": manifest.get("时间", ""),
                        "文件": sorted(files),
                        "说明": manifest.get("说明", "")})
        return out

    def _backup(self, paths, label=""):
        """把要动的文件拷进时间戳目录；返回备份名（失败抛异常给调用方）"""
        existing = [p for p in paths if p and os.path.exists(p)]
        if not existing:
            return ""
        name = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(self.backup_root, name)
        os.makedirs(folder, exist_ok=True)   # 同秒重复调用时合并进同一份
        copied = []
        for p in existing:
            dst = os.path.join(folder, os.path.basename(p))
            shutil.copy2(p, dst)
            copied.append(os.path.basename(p))
        manifest = {"时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "说明": label, "文件": copied}
        tmp = os.path.join(folder, "manifest.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(folder, "manifest.json"))
        return name

    def restore_backup(self, name="latest"):
        """把某份备份拷回原位。

        ``name="latest"`` 取最新一份。只覆盖备份里有的文件，
        备份后新产生的数据（比如新聊天）不受影响。
        """
        backups = self.list_backups()
        if not backups:
            return {"ok": False, "msg": "没有可用备份"}
        if name in ("", "latest", None):
            name = backups[0]["名称"]
        folder = os.path.join(self.backup_root, str(name))
        if not os.path.isdir(folder):
            return {"ok": False, "msg": "备份不存在: %s" % name}
        restored = []
        try:
            for fname in os.listdir(folder):
                if fname == "manifest.json" or fname.endswith(".tmp"):
                    continue
                src = os.path.join(folder, fname)
                dst = {
                    "chats.db": self.db_path,
                    "memory_cards.jsonl": self.cards_path,
                    "graph.json": self.graph_path,
                }.get(fname)
                if not dst:
                    continue
                shutil.copy2(src, dst)
                restored.append(fname)
        except Exception as e:
            return {"ok": False, "msg": "回滚失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "备份": str(name), "已恢复": restored}

    # ------------------------------------------------------------------
    # 聊天记录
    # ------------------------------------------------------------------
    def _plan_chats(self):
        """算「哪些消息是连续重复」；返回 (删除 id 列表, 总行数, 错误)"""
        if not os.path.exists(self.db_path):
            return None, 0, "无数据库"
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cols = [r[1] for r in
                        conn.execute("PRAGMA table_info(messages)").fetchall()]
                if not cols:
                    return None, 0, "没有 messages 表"
                if "ts" in cols:
                    sql = ("SELECT id, username, session_id, role, text "
                           "FROM messages ORDER BY ts")
                else:
                    sql = ("SELECT id, username, session_id, role, text "
                           "FROM messages ORDER BY id")
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()
        except Exception as e:
            return None, 0, "读 chats.db 失败：%s: %s" % (type(e).__name__,
                                                      str(e)[:60])
        doomed, last_key = [], None
        for row in rows:
            key = (row[1], row[2], row[3], row[4])
            if key == last_key:
                doomed.append(row[0])
            else:
                last_key = key
        return doomed, len(rows), ""

    def clean_chats(self, dry_run=False, backup=True):
        """聊天记录去重：删除完全相同的**连续**消息"""
        dry_run = self._flag(dry_run)
        backup = self._flag(backup, True)
        doomed, total, err = self._plan_chats()
        if doomed is None:
            return {"状态": err or "无数据库"}
        plan = {"删除重复": len(doomed), "剩余": total - len(doomed),
                "干跑": bool(dry_run)}
        if dry_run or not doomed:
            return plan
        backup_name = ""
        if backup:
            try:
                backup_name = self._backup([self.db_path], "聊天记录去重")
            except Exception as e:
                return {"ok": False, "msg": "备份失败，未做修改：%s: %s"
                                           % (type(e).__name__, str(e)[:60])}
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.executemany("DELETE FROM messages WHERE id=?",
                                 [(i, ) for i in doomed])
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            return {"ok": False, "msg": "删除失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        plan["ok"] = True
        if backup_name:
            plan["备份"] = backup_name
        return plan

    # ------------------------------------------------------------------
    # 记忆卡
    # ------------------------------------------------------------------
    def clean_cards(self, dry_run=False, backup=True):
        """记忆卡去重：相似度 > 0.8 的合并（坏行原样保留）"""
        dry_run = self._flag(dry_run)
        backup = self._flag(backup, True)
        if not os.path.exists(self.cards_path):
            return {"状态": "无记忆卡"}
        cards, bad_lines, total_lines = [], [], 0
        try:
            with open(self.cards_path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    total_lines += 1
                    try:
                        cards.append(json.loads(line))
                    except Exception:
                        bad_lines.append(line.rstrip("\n"))
        except Exception as e:
            return {"ok": False, "msg": "读记忆卡失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}

        keep, deleted = [], 0
        for c in cards:
            facts = "".join(c.get("facts", [])) if isinstance(c, dict) else ""
            s1 = set(facts)
            dup = False
            for k in keep:
                s2 = set("".join(k.get("facts", [])) if isinstance(k, dict) else "")
                if s1 and s2:
                    sim = len(s1 & s2) / len(s1 | s2)
                    if sim > 0.8:
                        dup = True
                        deleted += 1
                        break
            if not dup:
                keep.append(c)

        r = {"原始": total_lines, "保留": len(keep), "删除": deleted,
             "干跑": bool(dry_run)}
        if bad_lines:
            r["无法解析"] = len(bad_lines)
            r["说明"] = "有 %d 行没法解析，已**原样保留**" % len(bad_lines)
        if dry_run or not deleted:
            return r
        backup_name = ""
        if backup:
            try:
                backup_name = self._backup([self.cards_path], "记忆卡去重")
            except Exception as e:
                return {"ok": False, "msg": "备份失败，未做修改：%s: %s"
                                           % (type(e).__name__, str(e)[:60])}
        try:
            tmp = self.cards_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for c in keep:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")
                # 坏行原样写回 —— 不删（解析不了不等于没用）
                for raw in bad_lines:
                    f.write(raw + "\n")
            os.replace(tmp, self.cards_path)
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return {"ok": False, "msg": "写回失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        r["ok"] = True
        if backup_name:
            r["备份"] = backup_name
        return r

    # ------------------------------------------------------------------
    # 知识图谱
    # ------------------------------------------------------------------
    def clean_graph(self, dry_run=False, backup=True):
        """知识图谱去重：删除完全相同的三元组"""
        dry_run = self._flag(dry_run)
        backup = self._flag(backup, True)
        if not os.path.exists(self.graph_path):
            return {"状态": "无图谱"}
        try:
            with open(self.graph_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {"ok": False, "msg": "读图谱失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        if isinstance(data, dict):
            tris = data.get("三元组") or []
        elif isinstance(data, list):
            tris = data
        else:
            return {"ok": False, "msg": "graph.json 格式不对"}
        if not isinstance(tris, list):
            return {"ok": False, "msg": "三元组列表格式不对"}

        seen, keep = set(), []
        for t in tris:
            if not isinstance(t, dict) or not all(
                    key in t for key in ("s", "p", "o")):
                # 缺字段的条目**不参与去重**，原样留着 ——
                # 原来会按 (None,None,None) 归成一条，等于把不同条目并掉
                keep.append(t)
                continue
            key = (t.get("s"), t.get("p"), t.get("o"))
            if key in seen:
                continue
            seen.add(key)
            keep.append(t)
        deleted = len(tris) - len(keep)
        r = {"原始": len(tris), "保留": len(keep), "删除": deleted,
             "干跑": bool(dry_run)}
        if dry_run or not deleted:
            return r
        backup_name = ""
        if backup:
            try:
                backup_name = self._backup([self.graph_path], "图谱去重")
            except Exception as e:
                return {"ok": False, "msg": "备份失败，未做修改：%s: %s"
                                           % (type(e).__name__, str(e)[:60])}
        try:
            tmp = self.graph_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"三元组": keep} if isinstance(data, dict) else keep,
                          f, ensure_ascii=False)
            os.replace(tmp, self.graph_path)
        except Exception as e:
            return {"ok": False, "msg": "写回失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        r["ok"] = True
        if backup_name:
            r["备份"] = backup_name
        return r

    # ------------------------------------------------------------------
    def clean_all(self, dry_run=False, backup=True):
        """四类清洗一起做。

        ``dry_run=True`` 只报「会删多少」；``backup=True``（默认）
        先整份备份，之后可用 ``restore_backup()`` 回滚。
        """
        dry_run = self._flag(dry_run)
        backup = self._flag(backup, True)
        r = {
            "干跑": bool(dry_run),
            "聊天记录": self.clean_chats(dry_run=True, backup=False),
            "记忆卡": self.clean_cards(dry_run=True, backup=False),
            "知识图谱": self.clean_graph(dry_run=True, backup=False),
        }
        if dry_run:
            r["说明"] = "干跑：只统计，没有改动任何文件"
            return r

        backup_name = ""
        if backup:
            try:
                backup_name = self._backup(
                    [self.db_path, self.cards_path, self.graph_path], "清洗全部")
            except Exception as e:
                r["ok"] = False
                r["msg"] = ("备份失败，未做修改：%s: %s"
                            % (type(e).__name__, str(e)[:60]))
                return r

        r["聊天记录"] = self.clean_chats(dry_run=False, backup=False)
        r["记忆卡"] = self.clean_cards(dry_run=False, backup=False)
        r["知识图谱"] = self.clean_graph(dry_run=False, backup=False)
        failures = [name for name, item in r.items()
                    if isinstance(item, dict) and item.get("ok") is False]
        r["ok"] = not failures
        if backup_name:
            r["备份"] = backup_name
        if failures:
            r["msg"] = "部分清洗失败：%s（可用 restore_backup 回滚）" % "、".join(
                failures)
        return r

    def preview(self):
        """干跑：只看会删多少，不动任何文件"""
        return self.clean_all(dry_run=True, backup=False)

    def run(self, *a):
        return self.clean_all()
