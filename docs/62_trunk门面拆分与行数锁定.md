# core/trunk.py 门面拆分与行数锁定

日期：2026-10-19  
状态：已完成并通过全量回归

## 拆分前

```text
core/trunk.py    1268 行
职责：启动、配置、日志、备份、模块注册、懒加载、记忆、知识库、
      后台任务、回复主流程、聊天状态、资源回收、关闭流程
```

## 拆分后

| 文件 | 行数 | 职责 |
|---|---:|---|
| `core/trunk.py` | 151 | 组合根、`__init__`、公共门面 |
| `core/trunk_config.py` | 166 | 配置、日志、崩溃钩子、规则 |
| `core/trunk_memory.py` | 116 | 记忆与知识库 |
| `core/trunk_registry.py` | 289 | 模块注册、懒加载、`call`、运行时入口 |
| `core/trunk_background.py` | 439 | 预热、备份、后台队列、卸载、关闭 |
| `core/trunk_reply.py` | 196 | 聊天回复、聊天状态、流水线状态 |

## 锁定机制

1. `tools/check_file_sizes.py` 增加单独预算：
   - `core/trunk.py` 上限 220 行；
   - 所有 `trunk_*` 拆分模块分别有上限；
   - 其他生产文件仍受 1300 行总上限约束。
2. 新增 `tests/test_trunk_facade.py`：
   - 强制 `core/trunk.py` <= 220 行；
   - 强制 Trunk 类里只允许 `__init__`；
   - 公共 API 丢失会直接测试失败。
3. `check.bat` 和 CI 都会执行文件长度守卫。

## 兼容性

- `Trunk.reply()`
- `Trunk.call()`
- `Trunk._load_lazy()`
- `Trunk._deep_check()`
- `Trunk._warmup()`
- `Trunk.save_config()`
- `Trunk.mem_add()`
- `Trunk.get_task_runtime()`
- `Trunk.validate_lazy_imports()`

全部通过继承保持原方法名和签名，现有测试无需改调用方。

## 验证

```text
pytest: 1052 passed / 2 skipped
Ruff: All checks passed
Mypy: 13 个关键模块通过
Agent E2E: 13 passed
懒加载: 66/66 通过
文件长度: core/trunk.py 151 行 / 上限 220
插件仓库: 42/42 一致且验签通过
```


## 文件长度策略升级（2026-10-19）

- 默认文件上限：**600 行**。
- 新增/未登记文件超过 600 行直接失败。
- 存量超标文件迁移期冻结在当前行数，只允许下降，不允许上涨。
- `core/trunk.py` 独立上限：**220 行**。
- 存量清单：`tools/file_size_baseline.json`。


## 分层文件长度策略

| 类型 | 目标区间 | 说明 |
|---|---:|---|
| 普通文件 | 200～400 | 建议目标 |
| 核心复杂模块 | 300～450 | 建议目标 |
| 门面文件 | 100～250 | 如 `core/trunk.py` |
| 警告线 | 500 | 打印警告，不阻塞开发 |
| 新文件硬上限 | 600 | 超过直接失败 |
| 禁止新增区 | 800+ | 冻结当前行数，只能拆分或降行数 |

存量超标文件记录在 `tools/file_size_baseline.json`，只允许下降。
