# -*- coding: utf-8 -*-
"""P2-08: 记忆压缩/归档 - 旧记忆自动压缩（完整版）

职责
----
把 ``memory_cards.jsonl`` 里超过 N 天的旧记忆搬到 ``data/archive/*.jsonl``，
主文件只留新记忆，避免记忆库越跑越大、检索越来越慢。

三条硬约束
--------------
1. **坏行原样保留**：解析不了的行不代表该删（可能是别的版本写的），
   归档只搬"能确认是旧的"条目。
2. **写盘用临时文件 + os.replace**：中途崩不会把主库写坏。
3. **可恢复**：``restore()`` 把归档搬回来（按原文去重，可重复调用）。
"""
import json
import os
import time
from datetime import datetime, timedelta

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)


class MemoryArchiver:
    """旧记忆归档：手动归档 / 恢复 / 按周期自动触发"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.memory_path = data_path(trunk, "memory_cards.jsonl")
        self.archive_dir = data_path(trunk, "archive")
        try:
            os.makedirs(self.archive_dir, exist_ok=True)
        except OSError:
            # 目录建不出来时不让整个模块构造失败，归档时再报错
            pass

    @staticmethod
    def _days(days):
        try:
            return max(0, int(days))
        except (TypeError, ValueError):
            return 30

    def archive_old(self, days=30):
        """把超过 ``days`` 天的旧记忆移到归档文件。

        返回字段：
            ok       是否成功
            归档数   本次移走的条数
            剩余     主文件剩余条数
            坏行     解析失败但被原样保留的行数
        """
        days = self._days(days)
        if not os.path.exists(self.memory_path):
            return {"ok": False, "msg": "记忆文件不存在"}

        cutoff = datetime.now() - timedelta(days=days)
        old, keep, bad = [], [], 0
        try:
            with open(self.memory_path, encoding="utf-8") as f:
                for ln in f:
                    raw = ln.strip()
                    if not raw:
                        continue
                    try:
                        card = json.loads(raw)
                    except Exception:
                        # ⚠️ 原来的写法是 `new.append(c)`，而 json 解析失败时
                        # `c` 根本没赋值 —— 必然 NameError，整个归档直接崩。
                        # 现在把坏行当原文保留，计入 bad。
                        keep.append(raw)
                        bad += 1
                        continue
                    date_str = str(card.get("date") or "")
                    try:
                        date = datetime.strptime(date_str, "%Y-%m-%d")
                    except (TypeError, ValueError):
                        # 没有可用日期：按新记忆处理，不能因为缺字段就归档掉
                        keep.append(raw)
                        continue
                    if date < cutoff:
                        old.append(card)
                    else:
                        keep.append(raw)
        except Exception as e:
            return {"ok": False, "msg": "读取记忆失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}

        if not old:
            return {"ok": True, "归档数": 0, "剩余": len(keep), "坏行": bad}

        archive_name = "archive_" + datetime.now().strftime("%Y%m") + ".jsonl"
        archive_path = os.path.join(self.archive_dir, archive_name)
        tmp = self.memory_path + ".tmp"
        try:
            with open(archive_path, "a", encoding="utf-8") as f:
                for card in old:
                    f.write(json.dumps(card, ensure_ascii=False) + "\n")
            with open(tmp, "w", encoding="utf-8") as f:
                for raw in keep:
                    f.write(raw + "\n")
            os.replace(tmp, self.memory_path)
        except Exception as e:
            # 失败时清理半成品临时文件
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return {"ok": False, "msg": "写归档失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}

        r = {"ok": True, "归档数": len(old), "剩余": len(keep),
             "归档文件": archive_name}
        if bad:
            r["坏行"] = bad
        return r

    def list_archives(self):
        if not os.path.isdir(self.archive_dir):
            return []
        return sorted(name for name in os.listdir(self.archive_dir)
                      if name.endswith(".jsonl"))

    def restore(self, archive_name, remove=True):
        """把某个归档文件里的记忆搬回主库。

        ``remove=True`` 恢复成功后删除归档文件；``False`` 保留（便于二次核对）。
        按原文去重，重复恢复不会产生重复记忆。
        """
        if not archive_name:
            return {"ok": False, "msg": "没给归档文件名"}
        name = os.path.basename(str(archive_name))
        src = os.path.join(self.archive_dir, name)
        if not os.path.exists(src):
            return {"ok": False, "msg": "归档文件不存在: %s" % name}
        try:
            existing = set()
            if os.path.exists(self.memory_path):
                with open(self.memory_path, encoding="utf-8") as f:
                    existing = {ln.strip() for ln in f if ln.strip()}
            with open(src, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            restored = 0
            with open(self.memory_path, "a", encoding="utf-8") as f:
                for raw in lines:
                    if raw in existing:
                        continue
                    f.write(raw + "\n")
                    existing.add(raw)
                    restored += 1
            if remove:
                os.remove(src)
        except Exception as e:
            return {"ok": False, "msg": "恢复失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "恢复数": restored, "归档": name,
                "已删除归档": bool(remove)}

    def auto_archive_if_due(self, days=90, min_interval_days=7):
        """空闲时自动归档：只在距上次自动归档 ≥ ``min_interval_days`` 时做。

        阈值故意保守（默认 90 天、7 天一次）—— 自动动用户记忆这件事，
        宁可少做，不能做错。
        """
        marker = os.path.join(self.archive_dir, ".last_auto")
        try:
            with open(marker, encoding="utf-8") as f:
                last = float(f.read().strip())
        except (OSError, ValueError):
            last = 0.0
        now = time.time()
        interval = max(0, self._days(min_interval_days)) * 86400
        elapsed = now - last
        if last and elapsed < interval:
            return {"ok": True, "跳过": "未到自动归档周期",
                    "距下次(天)": round((interval - elapsed) / 86400, 1)}
        r = self.archive_old(days)
        if r.get("ok"):
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(str(now))
            except OSError:
                # 标记写不了不影响本次归档结果
                pass
        r["自动"] = True
        return r

    def run(self, *a):
        return {"归档文件": len(self.list_archives()),
                "归档目录": self.archive_dir}
