# -*- coding: utf-8 -*-
"""躯干的后台维护循环：启动备份 + 空闲模块卸载。

为什么单列成一个文件（2026-10-28）
---------------------------------
`core/trunk_background.py` 已经到 634 行，撞上"文件长度"门禁（新文件 600 行必须拆）。
这段代码和"线程启停 / 队列消息"是两件事：它只负责**隔一段时间做一次杂务**
（备份一次、把 5 分钟没用过的模块卸掉），拆出来两边都更好读。

两个入口都接受 host（Trunk 实例），用到的字段与拆分前完全一致：
`_log` / `modules` / `_lazy` / `_last_use` / `_stopped()` / `_wait()` /
`_AUTO_BACKUP_MIN_GAP_H`。测试仍然通过 `Trunk._auto_backup()` 等薄包装调用。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import sys
import time


def auto_backup(host):
    """启动时自动备份一次 —— 走真正的备份系统（core/backup.py）

    和历史的关系
    ------------
    原来这里是自己拷几个关键文件到 data/backup_MMDD_HHMM、留最近 2 份。
    但项目里本来就有 core/backup.py：增量、排除 datasets/cache/logs、
    写 backups/、还支持加密导出和恢复。两套并存的问题不只是重复：
      · 产物分散在两个地方（data/backup_* 和 backups/backup_*），
        要恢复时不知道该看哪个
      · 自检的"📦 备份"数的是旧的 data/backup_*，真正的 backups/ 反而没数
      · 旧那套的排除规则是手写的文件清单，容易和实际存储漂移
        （历史上就漏备过 memory.json / graph.json / chats.db）
    现在融合成一条：启动时触发真正的备份，产物统一进 backups/。

    另加节流：距上次备份不足 _AUTO_BACKUP_MIN_GAP_H 小时就跳过。

    节流做两层（2026-10-27）：
      ① 这里先快速看一眼最近一份（省掉建 Backup 的开销）
      ② 真正的判断在 Backup.backup_now(force=False, min_gap_h=...) 的**锁内** ——
         两个线程同时进来时，第二个能看到第一个刚落盘的备份，
         不会再出现同一秒两份（backup_..._211951 / _211951_2）。
    测试/CI 里设环境变量 X6_NO_AUTO_BACKUP=1 可直接关掉（它会写真实磁盘）。
    """
    # 测试/CI 短路：conftest 默认设了，单测里造 Trunk 不会写真实备份
    if str(os.environ.get("X6_NO_AUTO_BACKUP", "")).strip().lower() \
            not in ("", "0", "false", "no"):
        return
    try:
        from core.backup import Backup
        bk = Backup(host)
        last = bk._last_backup_path()
        if last and backup_is_recent(host, last):
            return
        r = bk.backup_now(force=False,
                          min_gap_h=host._AUTO_BACKUP_MIN_GAP_H) or {}
        if r.get("跳过"):
            return
        if r.get("成功"):
            host._log("启动备份完成: %s（%s）"
                      % (r.get("备份到"), "增量" if r.get("增量") else "全量"))
        else:
            host._log("启动备份未完成: %s" % str(r.get("错误"))[:60])
    except Exception as e:
        host._log("启动备份失败: %s" % str(e)[:60])


def backup_is_recent(host, path):
    """最近的备份是否还在节流窗口内"""
    try:
        age_h = (time.time() - os.path.getmtime(path)) / 3600.0
        return age_h < host._AUTO_BACKUP_MIN_GAP_H
    except Exception as e:
        _x6_swallowed(__name__, e, "backup mtime")
        return False


def auto_unload_loop(host):
    """每 30 秒看一眼：哪些模块 5 分钟没用过就卸掉，把内存还回去

    常驻白名单：核心 + 后台服务（定时任务/热更新/学习闭环等带独立线程的模块不可卸载，
    否则 stop() 会停掉服务线程。
    """
    import gc
    core = {"llm", "vector_store", "auth", "backup", "knowledge_graph",
            "rules_engine",
            "scheduler", "hot_reload", "error_lib",
            "learning_loop", "memory_loop"}
    while not host._stopped():
        if host._wait(30):       # 可被 stop_background 立刻打断（不用干等 30 秒）
            break
        try:
            now = time.time()
            to_unload = []
            for name in list(host.modules.keys()):
                if name in core:
                    continue
                last = host._last_use.get(name, 0)
                if last and now - last > 300:  # P0-1: 5分钟才卸载，避免反复懒加载拖慢
                    to_unload.append(name)
            for name in to_unload:
                try:
                    mod = host.modules.get(name)
                    for m in ["stop", "close", "shutdown", "cleanup"]:
                        fn = getattr(mod, m, None)
                        if fn:
                            try:
                                fn()
                            except Exception as e:
                                host._log("异常: " + str(e)[:80])
                    del host.modules[name]
                    if name in host._lazy:
                        mod_path = "core." + host._lazy[name][0]
                        if mod_path in sys.modules:
                            try:
                                del sys.modules[mod_path]
                            except Exception as e:
                                host._log("异常: " + str(e)[:80])
                    gc.collect()
                    host._log("真卸载模块: %s" % name)
                except Exception as e:
                    host._log("卸载%s失败: %s" % (name, str(e)[:50]))
        except Exception as e:
            host._log("自动卸载线程出错: %s" % str(e)[:50])
