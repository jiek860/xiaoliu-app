# -*- coding: utf-8 -*-
"""微核躯干 v12.0
核心职责：
1. 模块注册与懒加载（_load_lazy）
2. 回复主流程（reply）：意图识别→检索→工具调用→LLM→闭环
3. 日志与崩溃兜底
4. 配置读取与保存
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, time, threading, sys, traceback
from datetime import datetime

from core.secret_store import decrypt_config, encrypt_config



from core.trunk_config import TrunkConfigMixin
from core.trunk_memory import TrunkMemoryMixin
from core.trunk_registry import TrunkRegistryMixin
from core.trunk_background import TrunkBackgroundMixin
from core.trunk_reply import TrunkReplyMixin



class Trunk(
    TrunkConfigMixin,
    TrunkMemoryMixin,
    TrunkRegistryMixin,
    TrunkBackgroundMixin,
    TrunkReplyMixin,
):
    """融合式躯干：核心能力直接内置，扩展模块注册调用"""

    def __init__(self):
        # 进程起点：给深度自检报启动耗时用（见 _deep_check）
        import time as _tstart
        self._process_start = _tstart.time()
        # 打包后（PyInstaller frozen）：可写数据放 exe 旁边，只读资源放 _MEIPASS
        if getattr(sys, 'frozen', False):
            self.base = os.path.dirname(sys.executable)
            self.res_base = getattr(sys, '_MEIPASS', self.base)
        else:
            self.base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.res_base = self.base
        self.data_dir = os.path.join(self.base, 'data')
        self.log_dir = os.path.join(self.data_dir, 'logs')
        self.kb_dir = os.path.join(self.data_dir, 'knowledge_docs')
        for d in [self.log_dir, self.kb_dir]:
            os.makedirs(d, exist_ok=True)

        self.log_path = os.path.join(self.log_dir, 'trunk.log')
        self.crash_path = os.path.join(self.log_dir, 'crashes.log')
        self.config_path = os.path.join(self.data_dir, 'config.json')
        # 数据格式迁移：先备份再迁移，失败不阻塞启动。
        try:
            from core import data_schema
            _mig = data_schema.migrate(self.base)
            if _mig.get("migrated"):
                self._log("数据迁移完成: %s" % str(_mig.get("migrated"))[:300])
            elif _mig.get("errors"):
                self._log("数据迁移有失败项: %s" % str(_mig.get("errors"))[:300])
        except Exception as e:
            self._log("数据迁移异常: " + str(e)[:120])
        # 注意：这里**不**自动装 sys.excepthook。
        # 原来在 __init__ 里直接 sys.excepthook = self._global_excepthook，
        # 后果是任何创建了 Trunk 的东西 —— 测试、脚本、tools/ 下的工具 ——
        # 一崩就往用户真实的 data/logs/crashes.log 里写，
        # 还会把深度自检的"今天N条崩溃"顶上去、白扣健康分（实际发生过：
        # 我自己的几个临时验证脚本写进去 3 条，健康分从 100 掉到 80）。
        # 需要的话由程序入口显式调 install_crash_hook()：
        # run.py / gui/app_pyqt.py 本来就各自装了钩子，run_server.py 调下面这个方法。
        self._owns_excepthook = False

        self.modules = {}
        self._lock = threading.Lock()
        self._last_use = {}
        self.stats = {"calls": 0, "errors": 0, "module_stats": {}}
        self._route_cache = {}
        # P2-5: 性能监控
        try:
            from core.perf import PerfMonitor
            self.perf = PerfMonitor()
        except Exception:
            self.perf = None
        # v12: 模块元信息（插件市场安装后写入）+ 已安装模块目录
        self.module_meta = {}
        self.modules_dir = os.path.join(self.base, "modules", "installed")
        os.makedirs(self.modules_dir, exist_ok=True)
        self.config = self._load_config()
        self.memory_path = os.path.join(self.data_dir, 'memory.json')
        self.current_user = None
        self.kb_index = os.path.join(self.kb_dir, '_index.json')
        self.memory = self._load_memory()
        self.kb_items = self._load_kb()

        # 懒加载映射表（从配置文件导入）
        from core.lazy_config import LAZY_MAP
        self._lazy = dict(LAZY_MAP)

        # 别名
        # 指向真身，老插件调 web_learner 仍然能用（proactive_learner 早已改名成
        # active_learning，直接删这条会让老插件静默失效）。
        # 下面那批 a->a 的自映射已删除：call() 里白查一次字典，行为完全一致。
        self._aliases = {
            "errors": "error_lib",
            "enhanced_memory": "vector_store",
            "file_reader": "file_upload",
            # "web_learner" 别名已移除：它指向的 active_learning 已退役
        # （全项目本来就没有地方调这个别名，留着只是历史包袱）。
            "auto_fixer": "error_lib",
            "llm_client": "llm",
        }

        self._register_core()
        # P0-4: 后台任务单线程队列，防止连续发消息起多个线程抢资源
        import queue as _q
        self._bg_queue = _q.Queue()
        self._bg_worker = threading.Thread(target=self._bg_loop, daemon=True)
        self._bg_worker.start()
        # 空闲任务队列：反思/记忆闭环要调模型，不能在用户连续聊天时插队。
        # 不能放在 _bg_loop 里 sleep —— 那是单线程队列，会把记忆入库一起堵住。
        self._idle_queue = _q.Queue()
        threading.Thread(target=self._idle_worker, daemon=True).start()
        threading.Thread(target=self._auto_unload_loop, daemon=True).start()
        # 后台服务丢线程，不阻塞 UI 启动
        threading.Thread(target=self._start_background, daemon=True).start()
        # 启动时自动备份一次（走 core/backup.py，带节流，见 _auto_backup）
        threading.Thread(target=self._auto_backup, daemon=True).start()
        # 性能优化：Ollama 预热 + 向量库预加载
        threading.Thread(target=self._warmup, daemon=True).start()
        # 尝试初始化 pipeline；初始化就失败的话只能一直走 legacy
        self._use_pipeline = True
        # pipeline 出错后的冷却重试状态（见 _reply_inner / _pipeline_failed）
        self._pipeline_fail_count = 0     # 连续失败次数，成功一次就清零
        self._pipeline_retry_at = 0.0     # 早于这个时间点不重试 pipeline
        try:
            from core.pipeline import ReplyPipeline
            self._pipeline = ReplyPipeline(self)
            self._log("Pipeline 初始化成功")
        except Exception as e:
            self._use_pipeline = False
            self._pipeline = None
            self._log(f"Pipeline 初始化失败，使用旧流程: {e}")
        # 后台自我改进组件（全try包裹，坏了不影响主程序）
        try:
            from core.config_healer import ConfigHealer
            fixes = ConfigHealer(self).check_and_heal()
            if fixes: self._log(f"配置自愈完成，修复{len(fixes)}项")
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            from core.module_health import ModuleHealth
            disabled = ModuleHealth(self).disabled_modules()
            if disabled: self._log(f"已自动禁用坏模块: {disabled}")
        except Exception as e:
            _x6_swallowed(__name__, e)
        self._log("躯干启动")
