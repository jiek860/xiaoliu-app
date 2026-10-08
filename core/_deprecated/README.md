# 已废弃的 core 模块

这里的东西**全项目从未被 import 过**，是历史遗留或重构后没人清理的。
2026-10-08 从 core/ 移到这里，没有删除 —— 需要时改改就能用。

| 文件 | 为什么废弃 |
|---|---|
| base_module.py | 与 modules/base.py 的 BaseModule 重复，后者才是模块基类 |
| boot_check.py | 启动自检逻辑已并入 core/trunk.py（躯干启动时直接打日志） |
| bootstrap.py | 统一 sys.path 的辅助函数，run.py / gui/app_pyqt.py 已各自处理 |
| feedback_learner.py | 无任何调用方 |
| health_check.py | 注释写着"从 trunk.py 拆出来"，但 trunk 并未调用它；
脚本版在 scripts/health_check.py，那个是在用的 |
| memory_store.py | 无任何调用方（记忆实际走 core/vector_store.py 与 data/memory.json） |
| registry.py | 早期模块注册器，已被 trunk 内置的 _load_lazy 取代 |
| theme_manager.py | 无任何调用方（主题在 gui/style.py） |
| update_stats.py | 无任何调用方 |
