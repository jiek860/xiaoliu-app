# -*- coding: utf-8 -*-
"""躯干自检与预热 —— 从 core/trunk.py 搬出来的

为什么搬：_deep_check 一个方法就 424 行，占 trunk.py 的 24%，而且它是纯诊断
（语法扫描 / 模块对账 / 目录层级 / Ollama 与云端连通性），不是内核职责。
内核该管注册、懒加载、分发、生命周期；自检报告属于运维，不该占微核篇幅。

trunk 那边保留同名委托方法，因为：
  · gui/system_dialog.py 直接调 trunk._deep_check()
  · 4 个测试用 mock.patch.object(Trunk, "_warmup_ollama") 打桩
"""
import os
import json
import time
from datetime import datetime


def warmup_ollama(trunk):
    """后台预热Ollama"""
    try:
        import requests
        url = trunk.config.get("ollama_url", "http://localhost:11434")
        requests.get(url + "/api/tags", timeout=2)
        trunk._log("Ollama预热完成")
    except Exception:
        pass


def check_ollama(trunk):
    try:
        import requests
        url = trunk.config.get("ollama_url", "http://localhost:11434")
        r = requests.get(url + "/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e)[:50]}


def check_cloud(trunk):
    try:
        import requests
        url = trunk.config.get("cloud_url", "")
        key = trunk.config.get("cloud_key", "")
        if not url or not key:
            return {"ok": False, "error": "未配置"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:50]}


def health_score(trunk):
    score = 100
    if not trunk._check_ollama()["ok"]:
        score -= 20
    if not trunk._check_cloud()["ok"]:
        score -= 10
    return score


def deep_check(trunk):
    """深度自检报告 v2：11 项检查（含目录层级/星型拓扑/结构契约）"""
    import py_compile, re as _re
    import glob as _g          # 提前导入，确保全程可用
    results = []
    errors = []
    def log(m):
        results.append(m)

    log("=== 深度自检报告 v2 ===")
    log("时间: %s" % datetime.now().strftime("%H:%M:%S"))
    _who = ""
    try:
        _r = trunk.call("auth", "whoami")
        if isinstance(_r, dict):
            _who = str(_r.get("user", ""))
    except Exception:
        pass
    log("账号: %s" % (_who if _who else "未登录(游客)"))
    log("")

    # 1. 语法检查（全程序目录，非仅 core）
    ok = fail = 0
    bad = []
    for root, _, files in os.walk(trunk.base):
        if any(x in root for x in ("backups", "staging", "dist", ".git", "node_modules")):
            continue
        for f in files:
            if f.endswith(".py") and not f.startswith("_"):
                try:
                    py_compile.compile(os.path.join(root, f), doraise=True)
                    ok += 1
                except Exception:
                    fail += 1
                    if len(bad) < 2:
                        bad.append(os.path.relpath(os.path.join(root, f), trunk.base))
    log("📁 语法: %d通过 %d失败 %s" % (ok, fail, ("❌" + str(bad)) if bad else "✓"))
    if fail:
        errors.append("语法失败%d个: %s" % (fail, bad))

    # 2. 核心模块
    miss = [n for n in ("llm", "vector_store", "knowledge_graph", "auth", "backup")
            if n not in trunk.modules]
    log("🧩 核心模块: %s" % ("✓ 5个全在" if not miss else "❌缺 " + str(miss)))
    if miss:
        errors.append("核心模块缺失: " + str(miss))

    # 3. 懒加载模块对账（登记表 ↔ 文件 ↔ 类名）
    #    两处必须和 _load_lazy 的真实规则一致，否则全是误报：
    #      a) 登记表直接用内存里的 trunk._lazy，不要再去正则解析源码 ——
    #         原来那种扫 '": (' 的写法只认得出缩进不整齐的行，90 条里只认出 12 条
    #      b) 文件查找要先 modules/installed，找不到再回退 core/（_load_lazy 就是这么做的）
    try:
        lazy = getattr(trunk, "_lazy", {}) or {}
        lmiss = []
        for k, v in lazy.items():
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                f, c = v[0], v[1]
            elif isinstance(v, (list, tuple)) and v:
                f, c = v[0], ""
            else:
                f, c = str(v), ""
            fp = os.path.join(trunk.modules_dir, f + ".py")
            if not os.path.exists(fp):
                fp = os.path.join(trunk.base, "core", f + ".py")
            if not os.path.exists(fp):
                lmiss.append(k + "(文件)")
            elif c:
                try:
                    if not _re.search(r"class\s+" + _re.escape(c) + r"\b",
                                      open(fp, encoding="utf-8").read()):
                        lmiss.append(k + "(类名)")
                except Exception:
                    pass
        log("🧩 懒加载模块: %d条 %s" % (len(lazy), "✓ 全对齐" if not lmiss else "❌" + str(lmiss[:3])))
        if lmiss:
            errors.append("懒加载对账失败: " + str(lmiss[:3]))
    except Exception as e:
        log("🧩 懒加载模块: ❌ %s" % str(e)[:40])
        errors.append("懒加载对账失败: %s" % str(e)[:40])

    # 4. Ollama
    o = trunk._check_ollama()
    log("🤖 Ollama: %s" % ("✅ %d个模型" % len(o["models"]) if o["ok"] else "❌ " + o["error"]))
    if not o["ok"]:
        errors.append("Ollama: " + o["error"])

    # 5. 云端
    c = trunk._check_cloud()
    log("☁️ 云端: %s" % ("✅ 已配置" if c["ok"] else "❌ " + c["error"]))
    if not c["ok"]:
        errors.append("云端: " + c["error"])

    # 6. 错误库状态
    #    这里原来叫「自愈闭环」，检的是 self_heal 模块在不在。
    #    那个模块已删除（名字叫自愈、实际只标记不改代码），
    #    现在只报错误库自己还有多少条未修复。
    try:
        n = 0
        try:
            r = trunk.call("error_lib", "list")
            n = (r or {}).get("未修复", 0)
        except Exception:
            pass
        log("🩹 错误库: 未修复错误 %d 条%s" % (n, " ⚠" if n else " ✓"))
        if n:
            errors.append("有%d条未修复错误" % n)
    except Exception as e:
        log("🩹 错误库: ❌ %s" % str(e)[:40])

    # 7. 向量/嵌入对齐
    #    向量库已迁到 SQLite + numpy 矩阵：条目在 .data，向量在 ._emb_mat。
    #    原来读的 .embeddings 属性早就不存在了，getattr 默认 {} 恒为 0，
    #    所以不管实际对不对齐都报"差N"—— 纯误报。
    try:
        vs = trunk.modules.get("vector_store")
        nv = len(getattr(vs, "data", None) or [])
        ne = len(getattr(vs, "embeddings", None) or {})
        if not ne:
            mat = getattr(vs, "_emb_mat", None)
            try:
                ne = int(mat.shape[0]) if mat is not None else 0
            except Exception:
                ne = 0
        ok7 = nv == ne
        log("🧮 向量/嵌入: %d/%d %s" % (nv, ne, "✓ 对齐" if ok7 else "❌差%d" % (nv - ne)))
        if not ok7:
            errors.append("向量嵌入不对齐(差%d)" % (nv - ne))
        # P2-8: 自我评估统计
        try:
            _refl = trunk.modules.get("self_reflect") or trunk._load_lazy("self_reflect")
            if _refl and hasattr(_refl, "stats"):
                _st = _refl.stats()
                _avg = _st.get("平均分")
                try:
                    _avg_f = float(_avg)
                except Exception:
                    _avg_f = 0.0
                log("🏷 自我评估: 平均 %.2f · %d 次" % (
                    _avg_f, _st.get("总反思次数", _st.get("历史数", 0))))
        except Exception:
            pass
    except Exception as e:
        log("🧮 向量/嵌入: ❌ %s" % str(e)[:40])

    # 8. 数据文件完整性
    #    vectors.json / embeddings.json 是旧版遗留，现已迁到 SQLite（vectors.db），
    #    检查它们必然报"损坏"—— 纯误报。SQLite 库用 quick_check 验完整性。
    dmiss = []
    for fn in ("config.json", "graph.json", "memory.json"):
        try:
            json.load(open(os.path.join(trunk.data_dir, fn), encoding="utf-8"))
        except Exception:
            dmiss.append(fn)
    for fn in ("vectors.db", "chats.db"):
        p = os.path.join(trunk.data_dir, fn)
        if not os.path.exists(p):
            continue                      # 首次运行还没建，不算错
        try:
            import sqlite3
            con = sqlite3.connect(p)
            con.execute("PRAGMA quick_check").fetchone()
            con.close()
        except Exception:
            dmiss.append(fn + "(损坏)")
    log("🗂 数据文件: %s" % ("✓ 全部可读" if not dmiss else "❌ " + str(dmiss)))
    if dmiss:
        errors.append("数据文件损坏: " + str(dmiss))

    # 9. 崩溃日志（当天新增）
    try:
        n9 = 0
        if os.path.exists(trunk.crash_path):
            today = datetime.now().strftime("%Y-%m-%d")
            n9 = sum(1 for ln in open(trunk.crash_path, encoding="utf-8", errors="replace") if today in ln)
        log("📜 崩溃日志: 今天 %d 条 %s" % (n9, "✓" if n9 == 0 else "⚠"))
        if n9:
            errors.append("今天%d条崩溃" % n9)
    except Exception as e:
        log("📜 崩溃日志: ❌ %s" % str(e)[:40])

    # 11. 层级检查（目录层级 / 模块分层 / 星型拓扑 / 方法入口）
    try:
        _lv_err = []
        # 11.1 目录层级
        _need = ["core", "gui", "modules", "modules_repo", "data", "backups", "staging"]
        _miss = [d for d in _need if not os.path.isdir(os.path.join(trunk.base, d))]
        log("📁 目录层级: %s %s" % ("✓ 7个关键目录齐全" if not _miss else "❌缺", _miss or ""))
        if _miss:
            _lv_err.append("目录缺失: " + str(_miss))
        # 11.2 模块分层注册
        _core_n = len([n for n in ("llm", "vector_store", "knowledge_graph", "auth", "backup", "rules_engine")
                       if n in trunk.modules])
        _bg_n = len([n for n in ("scheduler", "hot_reload", "mobile_remote") if n in trunk.modules])
        _lazy_n = len(getattr(trunk, "_lazy", {}) or {})
        log("🗂 模块分层: 核心%d/6 · 后台%d/3 · 懒加载%d · 当前已加载%d" % (_core_n, _bg_n, _lazy_n, len(trunk.modules)))
        if _core_n < 6:
            _lv_err.append("核心模块不足(%d/6)" % _core_n)
        # 11.3 星型拓扑：modules 内模块不应互相 import（只准 import core/标准库）
        _viol = []
        _mi = os.path.join(trunk.base, "modules", "installed")
        if os.path.isdir(_mi):
            _fs = [f for f in os.listdir(_mi) if f.endswith(".py")]
            for _f in _fs:
                try:
                    _src = open(os.path.join(_mi, _f), encoding="utf-8").read()
                    for _o in _fs:
                        if _o == _f:
                            continue
                        _bn = _o[:-3]
                        if _bn in ("__init__", "config"):
                            continue
                        # 只认"真的导入了这个兄弟模块"：
                        #     from modules.installed.<名> import ...
                        #     import <名> / from <名> import ...
                        # 原来写的是 import\s+.*<名>，只要文件名出现在任意 import 行的
                        # 后半段就报违规，于是 from core.realtime.tts import TTS
                        # 被误判成 realtime_chat.py→tts.py —— 那其实是在导入 core，完全合规。
                        _pat = (r"modules\.installed\." + _re.escape(_bn) + r"\b"
                                r"|^\s*(?:from|import)\s+" + _re.escape(_bn) + r"\b")
                        if _re.search(_pat, _src, _re.M):
                            _viol.append("%s→%s" % (_f, _o))
                except Exception:
                    pass
        log("🕸 星型拓扑: %s" % ("✓ 模块间无互相 import" if not _viol else "⚠ " + str(_viol[:4])))
        if _viol:
            _lv_err.append("模块互相import: " + str(_viol[:3]))
        # 11.4 方法入口层级：抽查懒加载前 12 个模块是否有 run/reply
        _mm = []
        _lazy_d = getattr(trunk, "_lazy", {}) or {}
        for _k, _v in list(_lazy_d.items())[:12]:
            _f = _v[0] if isinstance(_v, (list, tuple)) else str(_v)
            _fp = os.path.join(trunk.modules_dir, _f + ".py")
            if os.path.exists(_fp):
                _s2 = open(_fp, encoding="utf-8").read()
                if "def run" not in _s2 and "def reply" not in _s2:
                    _mm.append(_k)
        log("🔧 方法入口: %s" % ("✓ 抽查12个模块均有 run/reply" if not _mm else "⚠无run: " + str(_mm[:3])))
        if _mm:
            _lv_err.append("模块缺run入口: " + str(_mm[:3]))
        if _lv_err:
            errors.extend(_lv_err)
    except Exception as e:
        log("🗂 层级检查: ❌ %s" % str(e)[:40])

    # 9.5 新增检测项
    try:
        import psutil
        mem=psutil.virtual_memory()
        log("💾 内存: 已用%d%% 可用%dMB"%(mem.percent,mem.available//1048576))
    except Exception: log("💾 内存: psutil未装")
    # 启动耗时：接上 startup_optimizer（它登记了很久没人调用）。
    # 只报数，不做任何"优化动作"——它的 precompile() 会在启动时
    # 编译整个项目，放到这里会把启动拖慢好几秒，不调。
    try:
        import time as _tb
        _el = _tb.time() - getattr(trunk, "_process_start", _tb.time())
        log("⏱ 启动耗时: %.1f秒（进程起到现在）" % _el)
    except Exception: pass
    try:
        # os.statvfs 是 Unix 专用 API，Windows 上根本没有这个函数，
        # 原来被 except 吞掉，这行从来没打印过。
        import psutil
        _du = psutil.disk_usage(trunk.base)
        log("💽 磁盘: 可用%dGB / 共%dGB" % (_du.free // 1073741824, _du.total // 1073741824))
    except Exception:
        pass
    try:
        kg = trunk.modules.get("knowledge_graph")
        if kg:
            n_triples = len(getattr(kg, "data", {}).get("三元组", []))
            log("🧠 知识图谱: %d三元组" % n_triples)
    except Exception:
        pass
    try:
        # 数真正的备份系统（core/backup.py 写 backups/，名字形如 backup_20261010_204104）。
        # 原来数的是 data/backup_* —— 那是已删除的"简单文件拷贝"式备份留下的目录，
        # 真正的 backups/ 反而没被数到。
        import glob
        _b = [d for d in glob.glob(os.path.join(trunk.base, "backups", "backup_*"))
              if os.path.isdir(d)]
        _latest = ""
        if _b:
            _latest = "（最近 %s）" % os.path.basename(sorted(_b)[-1])[7:15]
        log("📦 备份: %d个%s" % (len(_b), _latest))
    except Exception: pass
    try:
        mc=trunk.modules.get("mcp_client")
        if mc:
            r = mc.run() or {}
            # stats() 返回的键是 服务器数 / 工具数，
            # 原来读的是"已连接服务器"/"总服务器" —— 两个都不存在，
            # 于是永远显示 0/0（实际 5 个服务器 37 个工具），
            # 又是那种"键名对不上、又不报错"的静默 bug。
            log("🔌 MCP: %d 个服务器 · %d 个工具" % (
                r.get("服务器数", 0), r.get("工具数", 0)))
            if r.get("连接失败"):
                log("   （%d 个服务器连不上）" % len(r["连接失败"]))
        else:
            log("🔌 MCP: 未加载")
    except Exception: pass
    try:
        t0=time.time(); llm=trunk.modules.get("llm")
        if llm:
            llm.chat("你好"); dt=time.time()-t0
            log("⚡ LLM响应: %.1f秒"%dt)
            if dt>10: errors.append("LLM慢%.1fs"%dt)
    except Exception as e: log("⚡ LLM响应: %s"%str(e)[:40])

    # 9.6 完整体检新增
    try:
        hard=0
        for py in _g.glob(os.path.join(trunk.base,"core","*.py"))+_g.glob(os.path.join(trunk.base,"gui","*.py")):
            for line in open(py,encoding="utf-8",errors="ignore"):
                if trunk.base.replace("\\", "\\\\") in line and "trunk.base" not in line: hard+=1
        log("🔗 硬编码路径: %d处 %s"%(hard,"⚠" if hard>10 else "✓"))
        if hard>20: errors.append("硬编码%d处"%hard)
    except Exception: pass
    try:
        cfg=trunk.config; need=["local_model","ollama_url"]
        miss=[k for k in need if not cfg.get(k)]
        log("⚙️ 配置: %s"%("✓ 关键项齐" if not miss else "❌缺"+str(miss)))
        if miss: errors.append("配置缺"+str(miss))
    except Exception: pass
    try:
        logf=os.path.join(trunk.base,"data","logs","app.log"); leak=0
        if os.path.exists(logf):
            for line in open(logf,encoding="utf-8",errors="ignore"):
                if "sk-" in line or "api_key" in line.lower(): leak+=1
        log("🔒 密钥泄漏: %d处 %s"%(leak,"⚠" if leak else "✓"))
    except Exception: pass
    try:
        boot=getattr(trunk,"_boot_time",None)
        if boot: log("🚀 启动耗时: %.1f秒"%(time.time()-boot))
    except Exception: pass
    try:
        # 聊天记录在 chats.db 的 messages 表（SQLite），
        # 旧的 chat_history.jsonl 早已不用，所以这里一直显示 0 条。
        cf = os.path.join(trunk.base, "data", "chats.db")
        n = 0
        if os.path.exists(cf):
            import sqlite3
            con = sqlite3.connect(cf)
            try:
                n = con.execute("select count(*) from messages").fetchone()[0]
            except Exception:
                n = 0
            con.close()
        log("💬 聊天记录: %d条" % n)
    except Exception: pass
    # 层级检测 + 链接检测
    try:
        loaded=list(trunk.modules.keys())
        lazy=list(trunk._lazy.keys())
        never=[m for m in lazy if m not in loaded]
        log("🔗 链接: 已加载%d · 未触发%d"%(len(loaded),len(never)))
        if never: log("   未触发模块: %s"%(", ".join(never[:8])))
    except Exception: pass
    try:
        # 真正的"死模块"检测：模块名在**全项目源码**里除了登记表自己，
        # 一处都没出现过 —— 那就说明没有任何代码路径能用到它。
        #
        # 原来这里只找 trunk.call("名字") 这一种直接引用，而且把"当前没加载"
        # 也算进去，于是按需加载/定时调用的模块全被误报成孤儿
        # （实测报 50 个，其实都是能用的），这行提示因此失去意义。
        # 现在按"名字有没有在别处出现过"判断：出现过就算可达（宁可漏报不误报）。
        import re as _re
        _dirs = ("core", "gui", "modules", "tests", "tools", "scripts")
        _srcs = []
        for _d in _dirs:
            _root = os.path.join(trunk.base, _d)
            for _r, _ds, _fs in os.walk(_root):
                _ds[:] = [x for x in _ds if x not in ("__pycache__", "_deprecated")]
                for _f in _fs:
                    if _f.endswith(".py"):
                        _srcs.append(os.path.join(_r, _f))
        _IGNORE = {os.path.join(trunk.base, "core", "lazy_config.py")}
        dead = []
        for _name, _tup in trunk._lazy.items():
            _own = {os.path.join(trunk.base, "modules", "installed", _tup[0] + ".py"),
                    os.path.join(trunk.base, "core", _tup[0] + ".py")}
            _pat = _re.compile(r"\b" + _re.escape(_name) + r"\b")
            _hit = False
            for _p in _srcs:
                if _p in _own or _p in _IGNORE or os.sep + "modules_repo" + os.sep in _p:
                    continue
                try:
                    if _pat.search(open(_p, encoding="utf-8", errors="ignore").read()):
                        _hit = True
                        break
                except Exception:
                    continue
            if not _hit:
                dead.append(_name)
        if dead:
            log("👻 死模块: %d个（登记了但全项目没有调用点）" % len(dead))
            log("   这些模块装了也不会被用到，建议接上入口或从登记表摘掉。")
            log("   %s%s" % (", ".join(dead[:10]), " …" if len(dead) > 10 else ""))
            # 死模块算真问题：它让"模块 N 个"这个数字虚高，
            # 也让插件市场把它们当成可用功能推给用户。
            errors.append("有%d个登记模块没有任何调用点" % len(dead))
        else:
            log("👻 死模块: ✓ 登记的模块都有调用点")
    except Exception:
        pass


            # 10. 健康分（基于以上错误数）
    hs = max(100 - 20 * len(errors), 0)
    log("💯 健康分: %d" % hs)
    log("")
    if errors:
        log("⚠ 发现 %d 类问题：" % len(errors))
        for e in errors:
            log("   · " + e)
    else:
        log("✔ 全部 11 项检查通过")
    report = "\n".join(results)

    # 这里原来会联动 self_heal（自愈闭环：LLM分析→沙盒验证→弹窗确认→应用）。
    # 那个模块已删除 —— 它并不改代码，只是把错误标记成已处理，
    # 却会顺带弹一次确认窗。标记与清理现在由错误库自己做，
    # 定时任务每 4 小时跑一次（见 modules/installed/scheduler.py）。
    return report
