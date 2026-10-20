# 第二阶段：产品竞争力落地

## 状态说明

- 已落地代码 + 测试
- 已有底座，仍需 UI/业务接线
- 需要外部环境/证书/真实账号验收

## 1. 模型接入

`core/llm_providers.py` 已支持 OpenAI、Anthropic、Gemini、OpenRouter、Azure OpenAI、LM Studio、llama.cpp、vLLM。`core/llm_cloud.py` 已支持 `cloud_provider` 走 provider adapter；默认留空时保持原有 OpenAI-compatible 路径。

## 2. 能力探测与路由

`core/model_router.py` 提供静态能力矩阵 + provider 默认能力 + 运行时 override，按 tool calling、JSON、vision、context window 路由，本地失败自动转云端，未知模型保守降级，并返回 fallback chain。`LLMClient.route_request()` 已接入。

## 3. RAG

`core/rag_pipeline.py` 提供增量文件清单、页码/offset/chunk 引用定位、ACL roles、混合检索、RRF 融合、轻量 rerank 和原子写入。`KnowledgeQnA` 已接入 ingest/search；CLI 为 `python tools/rag_admin.py`。

## 4. GUI Agent

已有 `computer_agent` 的 Observe -> Plan -> Act -> Verify -> Replan 主链。本阶段补充 `core/gui_agent_quality.py`：UIA/OCR/视觉双通道定位、动作后验证、有界重试、失败修复计划、DPI/多显示器坐标转换、中文/多行/IME 输入 paste 策略。

## 5. 插件市场产品化

`core/plugin_registry.py` 提供 SemVer、宿主/API 兼容检查、官方/签名/未签名信任等级、更新选择、blocked 版本区分和安装账本。UI 已展示发布者、信任等级、版本、签名、API、能力和风险。`docs/examples/plugins/hello_plugin.py` 提供受限 SDK 示例。

## 6. 多用户/团队版

`core/team_policy.py` 提供 owner/admin/editor/viewer/auditor 角色、权限、用户隔离、集中配置覆盖、脱敏审计导出。CLI 为 `python tools/team_admin.py`。

## 验收命令

    python -m pytest tests/test_llm_providers.py tests/test_llm_cloud_provider.py tests/test_model_router.py tests/test_rag_pipeline.py tests/test_gui_agent_quality.py tests/test_plugin_registry.py tests/test_team_policy.py -q

## 仍需接线

- 设置页已增加 provider 选择器；Azure deployment 使用 cloud_model 字段，API version 仍建议增加独立输入
- 管理端增加团队/角色/集中配置页面
- 插件市场增加检查更新/更新/回滚按钮
- RAG 管理页增加文档、ACL、引用预览
- GUI Agent 将修复计划接入 computer_agent 的 trace UI

## 发布前 P0

- 干净 Windows 10/11 安装/升级/卸载
- 真实 Ollama + 云端模型 E2E
- 8 小时长稳
- Authenticode 签名
- PyQt5 许可证决策

## 非环境类收尾（已完成）

- RAG 管理窗口：导入文件/目录、ACL 角色、检索引用、删除来源。
- 团队管理窗口：用户表、角色设置、集中配置、审计导出。
- 插件市场：检查更新后可直接应用兼容更新，自动保留回滚副本；单插件可回滚。
- 电脑 Agent 窗口：展示重试修复计划和动作验证原因。
- 设置页：模型服务商选择器。
- 命令面板可通过「RAG管理」「团队管理」「多用户」打开对应窗口。

## 新增非环境能力

- 云端模型配置拆成独立窗口：服务商、模型/Azure deployment、API 地址、Key、Azure API version、静态能力预览。
- 新增「模型用量与成本」窗口：7 天调用、Token、估算成本、P50/P95 延迟和按模型统计。
- 新增模型价格估算表，未配置价格的模型显示 $0，不会伪造费用。
- 命令面板可打开「用量成本」「模型用量」。

## 打包体积优化

- PyInstaller 不再重复打包 `gui/` 和 `core/` 源码树，只保留运行时会编辑的 `core/lazy_config.py`。
- 排除未使用的 Qt WebEngine/QML/Quick/SQL/Test/XML 等模块。
- 本地构建：文件数 643 -> 370，产物 151.0MB -> 148.6MB，启动冒烟和 missing-module 分类通过。


## 2026-10-20 文档同步

本文件、README/README_EN、ARCHITECTURE、docs/00/10/20/50/70/80、
CHANGELOG、FAQ.txt、使用说明-小白版.txt、模型教程.txt、检测手册.txt、
部署步骤.md、开发者须知-密钥与发版.md、gui/tutorial_dialog.py 已同步。
打包源通过 `tools/sync_package.py` 更新。

## 2026-10-20 启动提速（秒开界面 + 看门狗同时启动）

### 问题

实测（offscreen，本机 Windows 11 / Python 3.12）：

    QApplication 就绪        118 ms
    骨架未拆分时窗口显示    2501 ms
    其中 Trunk.__init__     约 1850 ms
      ├─ 核心模块注册        约 530~700 ms（其中 llm_client 导入 306 ms）
      ├─ vector_store 初始化  约 120 ms
      └─ 模块星图 AST 遍历    约 300~1100 ms

### 改法

1. 新增 `core/startup.py`：纯 stdlib 的启动打点（mark / report / log_summary），
   每个阶段写入 `data/logs/trunk.log` 的一行 `[启动耗时] …`。
2. `run.py` 打点顺序：进程启动 → 依赖路径 → MSVC 预载 → **看门狗拉起** → GUI 导入。
   看门狗（`core/crash_watchdog.spawn`）在主线程还没进 Qt 之前就已经是独立进程，
   所以界面再慢，它也已经跑起来了。
3. `gui/main_window.py` 支持 `boot_signal=False`：只建窗口骨架（标题/图标/样式/占位页）
   立刻显示，`trunk` 置 None 等后台补。
4. 新增 `gui/boot_controller.py`：`QTimer` 把 Trunk 创建排到事件循环之后，
   完成/失败都通过信号回到 GUI 线程；失败自动重试一次，仍失败弹窗说明。
5. `core/trunk_registry.py`：模块星图导出改后台线程（纯展示用途）。
6. `core/llm_client.py`：新增 `defer_warmup=True` 与幂等的 `start_background_workers()`；
   Trunk 启动完成后延迟 1 秒再补启 LLM 看门狗和模型预热，避免和首帧抢 CPU。
7. 可用 `X6_BLOCKING_BOOT=1` 退回"全部就绪才显示"的旧行为（排查用）。

### 结果

| 指标 | 优化前 | 优化后 |
|---|---:|---:|
| 界面可见 | 2501 ms | **155~197 ms** |
| 全功能就绪 | 2510 ms | 约 990~1220 ms |
| 看门狗 | Qt 之后（约 2.5 s） | 进程启动后约 0.3 s，独立进程 |
| 全量测试 | — | 1298 passed / 2 skipped |
| 覆盖率 | — | 约 60.2% |

### 验收

    python -m pytest tests/test_startup_speed.py tests/test_gui_smoke.py tests/test_trunk_facade.py -q
    python run.py        # 看 trunk.log 里的 [启动耗时] 一行

新增测试：`tests/test_startup_speed.py`（打点单调性、看门狗快启、骨架不建 Trunk）。
