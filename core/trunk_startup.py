# -*- coding: utf-8 -*-
"""躯干的延迟启动编排：编译自检 → 定时任务 → 热更新 → 模块服务 → MCP → 内存清理。

为什么单列成一个文件（2026-10-28）
---------------------------------
从 `core/trunk_background.py` 拆出来的（那个文件已到 634 行，撞"文件长度"门禁）。
这里全是"启动 3 秒后在后台把各个服务拉起来"的编排，与线程启停、队列消息无关。

入口 `start_background(host)` 用到的字段与拆分前完全一致：
`_wait()` / `_log()` / `call()` / `_load_lazy()` / `config` / `base` / `modules`。
测试仍然通过 `Trunk._start_background()` 薄包装调用。
"""
import threading


def start_background(host):
    """P2-4: 延迟3秒启动后台服务，不阻塞UI"""
    if host._wait(3):            # 还没起服务就被要求退出（关窗/测试收尾）
        return
    try:
        from core.lazy_health import compile_lazy_sources
        _lh = compile_lazy_sources(host.base)
        if not _lh.get("ok"):
            host._log("懒加载语法自检失败: %s" % str(
                _lh.get("errors", [])[:3])[:300])
        else:
            host._log("懒加载语法自检通过: %d 个模块" % _lh.get("checked", 0))
    except Exception as e:
        host._log("懒加载语法自检异常: " + str(e)[:120])
    # 定时任务（内部会启动连续学习线程）
    try:
        host.call("scheduler", "start")
        host._log("定时任务已启动")
    except Exception as e:
        host._log("定时任务启动失败: %s" % str(e)[:60])
    # 热更新检测（每5分钟自动扫 .py 变化）
    try:
        hr = host._load_lazy("hot_reload")
        if hr and hasattr(hr, "auto_reload"):
            hr.auto_reload()
            host._log("热更新已启动")
    except Exception as e:
        host._log("热更新启动失败: %s" % str(e)[:60])
    # 模块服务器（本机插件仓库，127.0.0.1:8899）
    # 配置成远程地址时只连远程、不拉起本地服务（见 部署步骤.md 第五节）
    try:
        cfg_url = str(host.config.get("module_server", "") or "")
        if (not cfg_url) or ("127.0.0.1" in cfg_url) or ("localhost" in cfg_url):
            from core.module_server import ModuleServer
            if getattr(host, "_module_server", None) is None:
                host._module_server = ModuleServer(host)
                host._log(str(host._module_server.start())[:70])
        else:
            host._log("模块服务器: 配置为远程地址 %s，不拉起本地服务" % cfg_url[:40])
    except Exception as e:
        host._log("模块服务器启动失败: %s" % str(e)[:60])
    # MCP 服务端 + 客户端
    # 服务端是内嵌的本地工具服务：把 chat / search / run_code / backup
    # 包成 HTTP 接口（127.0.0.1:3742），供客户端那条「本地工具」配置连。
    # 原来这里只调了 ms.run()（返回工具清单，什么也不启动），
    # start_http() 全项目没有调用点，所以那个服务从来没起来过。
    try:
        ms = host._load_lazy("mcp_server")
        if ms and hasattr(ms, "start_http"):
            host._log("本地工具服务: %s" % str(ms.start_http())[:80])
    except Exception as e:
        host._log("本地工具服务启动失败: %s" % str(e)[:60])
    try:
        mc = host._load_lazy("mcp_client")
        if mc:
            r = mc.run()
            host._log("MCP客户端: %d个工具" % r.get("可用工具数", r.get("工具数", 0)))
    except Exception as e:
        host._log("MCP客户端: %s" % str(e)[:40])
    # Ollama 后台预热
    threading.Thread(target=host._warmup_ollama, daemon=True).start()
    # 定期内存清理：memory_optimizer 登记了很久没人调用
    # （它只做 gc.collect() + 收窄内部历史缓存，不动任何数据，放后台安全）
    try:
        host.call("memory_optimizer", "__no__")
        mo = host.modules.get("memory_optimizer")
        if mo is not None and hasattr(mo, "start_periodic"):
            r = mo.start_periodic(1800)
            host._log("内存优化: %s" % str(r.get("状态", "已启动")))
    except Exception as e:
        host._log("内存优化启动失败: %s" % str(e)[:60])
