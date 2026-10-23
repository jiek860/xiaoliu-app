# -*- coding: utf-8 -*-
"""向量存储 v6.0 - SQLite存储 + numpy内存检索
P0-3大改：数据存SQLite，内存里保留numpy矩阵做快速检索
优势：
- add只插一行，不用全量写JSON
- 启动快，数据大了也不卡
- 原子写，不会损坏
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import time
import math
import re
import sqlite3
import threading
import requests


class VectorStore:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(self.base, r"data\vectors.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 内存数据
        self.data = []
        self._emb_mat = None  # numpy矩阵
        self._qemb_cache = {}
        self.query_cache = {}
        self._cache_timer = time.time()
        self._lock = threading.Lock()
        self._last_embed = 0.0
        # ⚠️ 这一行原来**漏了**，后果很严重（2026-10-14 补）：
        #    `_embed()` 的**成功路径**里有 `if self._embed_retry_at != 0:`
        #    （用于"恢复了就提示一下"），但 __init__ 从没初始化它
        #    -> 第一次嵌入必然抛 AttributeError
        #    -> 被自己的 except 当成"嵌入失败"
        #    -> 设下 300 秒冷却
        #    **结果：每次启动后 5 分钟内语义检索完全不可用，
        #      一直静默走关键词降级。**
        #    冷却判断那处用的是 getattr(..., 0) 兜住了，成功路径没有 ——
        #    所以这个 bug 只在"嵌入真的能用"时才暴露，很难碰到。
        self._embed_retry_at = 0

        # 规则引擎参数
        try:
            self.half_life = self.trunk.rule("向量.半衰期天", 60)
            self.max_items = self.trunk.rule("向量.容量上限", 2000)
            self.keep_items = self.trunk.rule("向量.截断数", 1000)
            self.cache_max = self.trunk.rule("缓存.上限", 200)
            self.embed_gap = self.trunk.rule("嵌入.节流秒", 0.2)
        except Exception:
            self.half_life = 60
            self.max_items = 2000
            self.keep_items = 1000
            self.cache_max = 200
            self.embed_gap = 0.2

        # P0-11: Chroma可选加速
        self._use_chroma = False
        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(
                path=os.path.join(self.base, "data", "chroma"))
            self._collection = self._chroma_client.get_or_create_collection("memories")
            self._use_chroma = True
            if trunk:
                trunk._log("向量库: Chroma 加速已启用")
        except Exception:
            self._use_chroma = False

        # 初始化SQLite
        # ⚠️ 顺序不能反：先验文件是否可用，再建表。
        #    `_conn()` 里的 PRAGMA 在坏文件上自己就抛，所以
        #    "先连接、抛了再补救"是走不通的（补救时还是要连接）。
        self._ensure_db_ok()
        self._init_db()
        # 从SQLite加载所有数据到内存
        self._load_from_db()

    def _conn(self):
        """SQLite连接"""
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _ensure_db_ok(self):
        """开库**之前**先验这个文件是不是可用的 SQLite；坏了就挪走重建

        ⚠️ 为什么必须在开库前做（2026-10-14）：
            `_conn()` 里那句 `PRAGMA journal_mode=WAL` 在损坏文件上
            **自己就会抛** `DatabaseError`。所以"先连接、抛了再补救"
            这条路走不通 —— 补救的时候还是要 `_conn()`，还是抛。
            实测踩到：加了 except 之后**依然崩**，因为恢复路径里
            重新 `_conn()` 又抛了一次。

            vectors.db 是**长期积累**的文件，被强杀/断电/磁盘问题时真会坏。
            坏了就打不开程序，而用户**完全猜不到**是向量库的问题。

        取舍：宁可丢掉向量库（记忆的"索引"），也要让程序能起来 ——
        记忆正文在 memory.json，那个另有保护。
        坏文件改名留证，不直接删（万一还能人工抢救）。
        """
        if not os.path.exists(self.db_path):
            return
        try:
            c = sqlite3.connect(self.db_path, timeout=5)
            try:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("SELECT count(*) FROM sqlite_master")
            finally:
                c.close()
            return                                  # 是好的
        # 静默是故意的：这里"坏"是**预期内**的分支 ——
        # 判断依据是紧接着的改名/重建动作，不需要额外报错
        except sqlite3.DatabaseError:
            pass
        except Exception:
            return
        bad = self.db_path + ".corrupt"
        try:
            if os.path.exists(bad):
                os.remove(bad)
            os.replace(self.db_path, bad)
            note = "已改名为 %s 并重建" % os.path.basename(bad)
        except Exception:
            # 静默是故意的：改名失败（文件被占用）就退到"直接删"，
            # 下面那一层会处理；两层都失败才放弃（放弃也是静默返回，
            # 因为"修不了坏库"不该拦住程序启动 —— 见本函数开头的取舍）
            try:
                os.remove(self.db_path)
                note = "已删除并重建"
            except Exception:
                # 静默是故意的：同上 —— 连删都删不掉就放弃修复。
                # 接下来 _init_db() 会照常尝试，真起不来时错误会从那里冒出来，
                # 比在这里吞掉更容易定位
                return
        try:
            if self.trunk:
                self.trunk._log("向量库损坏，%s（记忆正文在 memory.json，"
                                "不受影响）" % note)
        # 静默是故意的：连"记一条日志"都失败就没别的办法了，
        # 而这件事本身不影响修复结果（库已经改名/删掉了）
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _init_db(self):
        """初始化表

        （损坏处理已挪到 `_ensure_db_ok()` —— 那必须在**开库前**做，
          原因见那个函数的说明。）
        """
        c = self._conn()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS vectors(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                tag TEXT,
                time REAL,
                hits INTEGER DEFAULT 0,
                embedding BLOB
            )""")
            c.commit()
        finally:
            c.close()

    def _load_from_db(self):
        """从SQLite加载所有数据到内存

        ⚠️ 整体兜住 DatabaseError（2026-10-14 补）：`_init_db()` 那边
        已经能"改名重建"坏库了，但**这里也会开库** —— 如果重建也失败
        （磁盘满、目录只读），异常会从这儿再抛出去，程序照样起不来。
        栽在最后一步最不值：前面已经做对了"宁可丢向量库也要能启动"，
        不能因为读回内存这一下前功尽弃。

        读不出来就当空库 —— 记忆的正文在 memory.json，那个另有保护。
        """
        import numpy as np
        try:
            c = self._conn()
        except sqlite3.DatabaseError:
            self.data = []
            self._emb_mat = None
            return
        try:
            rows = c.execute("SELECT * FROM vectors ORDER BY id DESC LIMIT ?",
                           (self.max_items,)).fetchall()
            rows = list(reversed(rows))  # 按时间正序
            emb_list = []
            self.data = []
            dim = 0          # 第一条合法向量的维度，后续必须一致
            skipped = 0      # 维度不符 / 损坏而被跳过的条数
            for r in rows:
                # 反序列化 embedding。
                # ⚠️ 必须校验长度一致：np.frombuffer 只要求字节数是 4 的倍数，
                #    所以一条被截断/损坏的记录会得到一个"短向量"，
                #    混进 emb_list 后 np.array() 会报
                #    "inhomogeneous shape" 把整个库读崩。
                #    这里遇到长度异常/空向量就跳过该条。
                #    data 和 emb_mat 必须同步 append，否则后面按索引检索会错位。
                raw = r["embedding"]
                if not raw:
                    skipped += 1
                    continue
                if not isinstance(raw, (bytes, bytearray)) or len(raw) % 4:
                    skipped += 1
                    continue
                emb = np.frombuffer(raw, dtype=np.float32).tolist()
                if not emb or (dim and len(emb) != dim):
                    skipped += 1
                    continue
                dim = len(emb)
                emb_list.append(emb)
                self.data.append({
                    "text": r["text"],
                    "tag": r["tag"],
                    "time": r["time"],
                    "hits": r["hits"],
                })
            if skipped and self.trunk:
                try:
                    self.trunk._log(
                        "向量库有 %d 条记录向量维度异常，已跳过（不影响其他数据）"
                        % skipped)
                except Exception as e:  # 静默是故意的 - 日志失败不能影响加载
                    _x6_swallowed(__name__, e)
            if emb_list:
                self._emb_mat = np.array(emb_list, dtype=np.float32)
        except sqlite3.DatabaseError as e:
            # 读的过程中坏了（建表成功但内容是垃圾）—— 当空库
            self.data = []
            self._emb_mat = None
            try:
                if self.trunk:
                    self.trunk._log("向量库读取失败（%s），本次按空库启动"
                                    % str(e)[:50])
            # 静默是故意的：连"记一条日志"都失败就没别的办法了。
            # 关键动作（把 data/_emb_mat 置空）已经在上面做完了，
            # 所以这里吞掉不影响"按空库启动"这个结果
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")
        finally:
            c.close()
        # ===== P1-06步骤1：向量库一致性检查（只加不改） =====
        try:
            if self._emb_mat is None:
                if self.data:
                    self.trunk._log("向量库异常：data有%d条但emb_mat为空，已清空data" % len(self.data))
                    self.data = []
            else:
                n_mat = len(self._emb_mat)
                n_data = len(self.data)
                if n_mat != n_data:
                    n = min(n_mat, n_data)
                    self._emb_mat = self._emb_mat[:n]
                    self.data = self.data[:n]
                    self.trunk._log("向量库不一致：矩阵%d条，数据%d条，已截断到%d条" % (n_mat, n_data, n))
                else:
                    self.trunk._log("向量库一致：%d条" % n_data)
        except Exception as e:
            try:
                self.trunk._log("向量库一致性检查失败：%s" % str(e)[:80])
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass

    # 嵌入失败后的冷却秒数。
    # 为什么要这个：嵌入服务（Ollama）挂掉时，每次检索都要白等一个 timeout
    # 才走到关键词降级 —— 实测一轮回复里 memory_loop.recall 会调 3 次，
    # 3 × 15 秒 = 45 秒纯等待，而模型生成本身只要 8 秒。
    # 失败一次就冷却一段时间，期间直接走关键词降级，结果照样能用。
    _EMBED_COOLDOWN = 300
    _EMBED_TIMEOUT = 5

    def _embed(self, text):
        """真神经网络嵌入（nomic-embed-text）——节流防Ollama被打爆"""
        # 冷却期内直接放弃，别再白等一个 timeout
        if time.time() < getattr(self, "_embed_retry_at", 0):
            return []
        now = time.time()
        gap = self.embed_gap
        wait = gap - (now - self._last_embed)
        if wait > 0:
            time.sleep(wait)
        self._last_embed = time.time()
        try:
            import core.llm_client as _lc
            with _lc.get_ollama_lock():
                url = (self.trunk.config.get("ollama_url", "http://localhost:11434")
                       if self.trunk else "http://localhost:11434")
                r = requests.post(url + "/api/embeddings",
                    json={"model": "nomic-embed-text", "prompt": text[:500]},
                    timeout=self._EMBED_TIMEOUT)
                emb = r.json().get("embedding", [])
                if emb:
                    if self._embed_retry_at != 0:
                        try: self.trunk._set_status("✅ 向量检索已恢复")
                        except Exception as e:
                            _x6_swallowed(__name__, e)
                    self._embed_retry_at = 0        # 成功：解除冷却
                return emb
        except Exception as e:
            # 失败 → 进入冷却，这期间检索直接走关键词降级
            self._embed_retry_at = time.time() + self._EMBED_COOLDOWN
            try:
                self.trunk._log("嵌入失败（%ds 内不再重试，检索走关键词降级）: %s"
                                % (self._EMBED_COOLDOWN, str(e)[:60]))
                try: self.trunk._set_status("⚠ 向量检索暂不可用，已切关键词模式")
                except Exception as e:
                    _x6_swallowed(__name__, e)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            return []

    def add(self, text, tag=""):
        """添加向量，嵌入移出锁"""
        emb = self._embed(text)
        if not emb:
            return {"ok": False, "reason": "embed_failed"}
        with self._lock:
            return self._add_locked(text, tag, emb)

    def _add_locked(self, text, tag, emb):
        import numpy as np
        # 1. 内存加
        self.data.append({
            "text": text, "tag": tag,
            "time": time.time(), "hits": 0
        })
        # 2. 矩阵加
        if self._emb_mat is not None:
            try:
                self._emb_mat = np.vstack([self._emb_mat, emb])
            except Exception:
                self._emb_mat = np.array([emb], dtype=np.float32)
        else:
            self._emb_mat = np.array([emb], dtype=np.float32)
        # 3. SQLite插一行
        c = self._conn()
        try:
            emb_blob = np.array(emb, dtype=np.float32).tobytes()
            c.execute("INSERT INTO vectors(text, tag, time, hits, embedding) VALUES(?,?,?,?,?)",
                     (text, tag, time.time(), 0, emb_blob))
            c.commit()
        finally:
            c.close()

        # P0-11: 同步到Chroma
        if self._use_chroma:
            try:
                self._collection.add(
                    embeddings=[emb],
                    documents=[text],
                    metadatas=[{"tag": tag, "time": time.time()}],
                    ids=["v_" + str(int(time.time() * 1000))]
                )
            except Exception as e:
                # 这里原来是一句 pass（2026-10-13 按"用户路径"审计时改的）。
                #
                # 判定：**数据不会丢** —— 上面 SQLite 那条是真持久化，
                # 而 Chroma 只是可选的二级索引。所以不该当成致命错误。
                #
                # 但完全静默是错的：Chroma 同步一直失败的话，
                # **向量检索会悄悄退化成关键词检索**，用户只觉得"搜得不准了"，
                # 完全不知道是索引坏了。
                # 所以：记一次日志（不刷屏）+ 首次失败时状态栏提示一次。
                if not getattr(self, "_chroma_warned", False):
                    self._chroma_warned = True
                    try:
                        self.trunk._log("Chroma 同步失败（数据已存 SQLite，"
                                        "只影响向量索引；后续同类失败不再重复记）: %s"
                                        % str(e)[:70], "WARN")
                    # 静默是故意的：这是"报告失败的手段本身失败了"，
                    # 报不出去也没别的办法，再套一层只会无限递归
                    except Exception as e:
                        _x6_swallowed(__name__, e, "best-effort fallback")
                    try:
                        self.trunk._set_status(
                            "⚠ 向量索引同步失败，搜索可能变弱（数据本身没丢）")
                    # 静默是故意的：同上 —— 状态栏设置失败无处可报
                    except Exception as e:
                        _x6_swallowed(__name__, e, "best-effort fallback")

        # 4. 截断
        if len(self.data) > self.max_items:
            self._trim_old()
        return {"ok": True}

    def _trim_old(self):
        """截断旧数据"""
        import numpy as np
        keep = self.keep_items
        self.data = self.data[-keep:]
        self._emb_mat = self._emb_mat[-keep:]
        # SQLite删旧数据
        c = self._conn()
        try:
            c.execute("DELETE FROM vectors WHERE id NOT IN (SELECT id FROM vectors ORDER BY id DESC LIMIT ?)",
                     (keep,))
            c.commit()
        finally:
            c.close()

    def _cosine(self, a, b):
        dot = sum(x*y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x*x for x in a)) or 1
        nb = math.sqrt(sum(x*x for x in b)) or 1
        return dot / (na * nb)

    def search(self, query, top_k=None):
        if top_k is None:
            try:
                top_k = self.trunk.rule("检索.top_k", 5)
            except Exception:
                top_k = 5
        with self._lock:
            return self._search_locked(query, top_k)

    def _search_locked(self, query, top_k=5):
        if not self.data:
            return []
        # 缓存清理
        if time.time() - self._cache_timer > 300:
            self._qemb_cache = dict(list(self._qemb_cache.items())[-50:])
            self.query_cache = dict(list(self.query_cache.items())[-50:])
            self._cache_timer = time.time()
        # 查询缓存
        if query in self.query_cache:
            return self.query_cache[query]
        q_emb = self._qemb_cache.get(query)
        if not q_emb:
            q_emb = self._embed(query)
            if q_emb:
                self._qemb_cache[query] = q_emb
        if not q_emb:
            # 嵌入失败：关键词降级
            words = [w for w in re.split(r"[\s\W]+", query) if len(w) >= 2]
            scored = []
            for item in self.data:
                # ⚠️ `or ""` 不能省：data 是从 SQLite 读回来的，
                #    text 列可能是 NULL（`{"text": None}`）。
                #    原来直接 `w in item.get("text", "")` —— get 的默认值
                #    只在**键不存在**时生效，键存在但值是 None 时照样返回 None，
                #    于是 `"x" in None` -> TypeError -> **整个检索崩掉**。
                #    一份长期积累的库里出现几行脏数据是很正常的事，
                #    不能因此让"回忆"这个功能整个不可用。
                _text = item.get("text") or ""
                s = sum(1 for w in words if w in _text)
                if s:
                    scored.append((s, item))
            scored.sort(key=lambda x: -x[0])
            if not scored:
                return [{"text": (x.get("text") or ""), "score": 0}
                        for x in self.data[:top_k]]
            return [{"text": (s.get("text") or ""), "score": round(sc, 3)}
                    for sc, s in scored[:top_k]]
        # numpy矩阵检索
        scored = []
        now = time.time()
        if self._emb_mat is not None and len(self._emb_mat) == len(self.data):
            try:
                import numpy as np
                q = np.asarray(q_emb, dtype=np.float32)
                qn = np.linalg.norm(q) or 1.0
                qn_vec = q / qn
                norms = np.linalg.norm(self._emb_mat, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                mat_norm = self._emb_mat / norms
                sims = mat_norm @ qn_vec
                ages = np.array([(now - it.get("time", now))/86400 for it in self.data], dtype=np.float32)
                sims = sims * np.exp(-ages/60)
                top_idx = np.argsort(-sims)[:top_k]
                for i in top_idx:
                    scored.append((float(sims[i]), self.data[int(i)]))
            except Exception:
                scored = []
        if not scored:
            for i, item in enumerate(self.data):
                if self._emb_mat is not None and i < len(self._emb_mat):
                    emb = self._emb_mat[i].tolist()
                else:
                    continue
                score = self._cosine(q_emb, emb)
                age = (now - item.get("time", now))/86400
                score *= math.exp(-age/60)
                scored.append((score, item))
            scored.sort(key=lambda x: -x[0])
        result = [{"text": s["text"], "score": round(sc, 3)} for sc, s in scored[:top_k]]
        self.query_cache[query] = result
        return result

    def save(self):
        """SQLite自动提交，不需要手动save"""
        return True

    def list_all(self):
        return self.data[-100:]

    def run(self, q=""):
        if q:
            return {"结果": self.search(q)}
        return {"记忆数": len(self.data), "嵌入模型": "nomic-embed-text"}
