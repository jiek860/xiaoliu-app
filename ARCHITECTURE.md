# 小6智能体 · 架构速览（3 页）

> **这份是"骨架"，给新人 10 分钟读完用的。**
> 细节（939 行的全量说明、每个坑的来龙去脉）在
> `docs/00_产品架构与UI主文档.md` —— **遇到"为什么这么写"的问题去那里查。**

---

## 一、一句话架构

**微核 + 星型拓扑**：一个 `Trunk` 当总线，72 个模块挂在它周围，
**模块之间不许互相 import**，全部走 `trunk.call()`。

```
                    ┌─────────────┐
                    │    Trunk    │  core/trunk.py
                    │  （总线）    │  · 模块注册 / 懒加载
                    └──────┬──────┘  · 分发调用
          ┌────────────────┼────────────────┐
          │                │                │
      ┌───┴───┐       ┌────┴────┐      ┌────┴────┐
      │ core  │       │ modules │      │   gui   │
      │ 稳定核 │       │ 可替换插件│      │  PyQt5  │
      └───────┘       └─────────┘      └─────────┘
```

**唯一例外**：`plugin_market` → `core.plugin_signer.PluginSigner`（已记录在案）。

---

## 二、启动顺序

```
double-click 启动PyQt.bat
   └─ run.py                                    ← 入口
      ├─ ① core.crash_guard.enable()            ← 最先装（崩了才有现场）
      ├─ ② 把 libs/ 和 optional_libs/ 插进 sys.path
      ├─ ③ core.win_dll_fix.preload_msvc_runtime()
      │     ⚠️ 必须在 import Qt 之前 —— PyQt5 自带旧 MSVCP140.dll，
      │        会挡住 torch 的 c10.dll（WinError 1114）
      └─ ④ gui.app_pyqt.run_pyqt()
         └─ Trunk.__init__()
            ├─ 读 config（data/config.json，没有就用 config.default.json 生成）
            ├─ 按 LAZY_MAP 登记 72 个模块（**只是登记，不 import**）
            ├─ 起后台线程：_bg_loop / _idle_worker（无条件）
            └─ 3 秒后 _start_background()：定时任务 / MCP / 预热 / 自动备份
```

**懒加载**：72 个模块里常驻的只有 8 个，其余**第一次被调用时才 import**。
好处是启动快；代价是"某个模块有语法错"要等到用它才发现
（`tools/check_shapes.py` 就是防这个的）。

---

## 三、主聊天链路（数据流）

```
用户输入
  │
  ├─ gui/mixins/chat_mixin.py          界面层：拿到文字
  │
  └─ Trunk.reply(text)
       └─ core/pipeline/reply_pipeline.py     ← 主链路
          │
          ├─ ① context_builder     并行检索（三个都跑，取交集/并集）
          │     · vector_store    向量检索（Ollama 嵌入，失败降级关键词）
          │     · memory          记忆卡触发
          │     · knowledge_graph 知识图谱召回
          │
          ├─ ② prompt_assembler    拼提示词
          │     · personality.full_hint(用户原话)  ← 人格提示
          │     · 系统提示 + 历史对话 + 检索结果
          │     · tool_caller      **按上下文挑工具**（两级过滤，见下）
          │
          ├─ ③ llm_client          模型分发
          │     · 优先流式；失败自动降级非流式
          │     · 云端 / 本地 Ollama 同一套接口
          │
          └─ ④ 后处理
                · 群聊消息合并 / 代码块提取 / TTS 判断
  │
  └─ 后台队列（不阻塞回复）
       · 记忆沉淀 · 闭环学习 · 自动备份
```

### 工具是怎么挑出来的（两级过滤）

```
63 个工具全给模型 → 提示词爆炸、模型选错
所以：
  第一级  core/pipeline/context_builder._TOOL_HINTS
          按关键词粗筛（"看图" → 视觉相关那几个）
  第二级  core/tool_caller._candidates
          core/tool_presets.py 预设 + module_caps.shortlist 相似度精排
```
**改工具描述的时候注意**：这两级都用得上描述文本，写歪了工具就选不出来。

---

## 四、一次调用的完整路径

```
trunk.call("browser", "open", url)
  │
  ├─ ① 找模块   modules 里没有 → _load_lazy("browser") → import
  ├─ ② 安全分级 core/tool_caller 分级：readonly / confirm / danger / bg
  │       danger 和 confirm 要用户点头
  ├─ ③ 真正调用 模块方法
  └─ ④ 出错时   core/error_text.describe() 翻译成人话 + 下一步
                 （缺依赖的话给带国内源的安装命令）
```

**例外**：`bg` 类工具（如"学个主题"）**不阻塞**，扔后台队列直接返回。

---

## UI 分层（2026-10-19 加入）

```
gui/build_ui.py
   activitybar  已移除（侧栏已有对话/任务/资料/设置，避免重复导航）
   topbar      品牌 / 模型状态 / 更多 / 头像
   sidebar     新建对话、导航、历史、模块按钮、高级入口（可滚动）
   main_tabs   顶部标签页：对话常驻，MCP/技能按需嵌入（gui/chrome.py）
   chat        ChatView + 首页三张引导卡（位于 main_tabs 的第一个标签页）
   composer    附件 + 聊天/任务切换 + 语音 + 发送
   statusbar   模式 / 引导 / 本地云端状态 / 模型名 / 今日 token（后两项在 gui/chrome.py）

gui/chrome.py              主区域标签页、状态栏元信息
gui/ui_mode.py             简单/高级模式状态（data/ui_state.json）
core/feature_registry.py   所有 UI 入口、分组、可见模式和按钮预算
gui/guidance.py            空状态 / 失败状态 / 权限状态的唯一下一步
gui/mixins/ui_mode_mixin.py 模式切换、头像/更多菜单、统一任务入口
gui/task_center_dialog.py  统一任务页面
```

原则：**功能不删，只分层**。简单模式首屏主操作入口 7 个；高级入口在高级模式更多菜单里全部可达。头像菜单固定 5 项，其余入口不与更多重复。

面板统一用 `_open_panel()` 挂成标签页，同一 key 只保留一个实例，关闭标签页后下次点击重建；侧栏与「更多」复用同一批 `_nav_*` / 对话框回调。


---

## 五、文件分工

| 目录 | 是什么 | 能改吗 |
|---|---|---|
| `core/` | 稳定核心：总线、管道、加密、存储、自检 | ⚠️ 改了要跑全量测试 |
| `modules/installed/` | **可替换插件**，43 个 | ✅ 随便加，不影响别人 |
| `modules_repo/` | 插件清单（RSA 签名，**独立 git 仓库**） | ⚠️ 改完要重签，见下 |
| `gui/` | PyQt5 界面 | ✅ |
| `tools/` | 8 个守卫 + 打包/同步工具 | ✅ |
| `tests/` | 932 个用例 | ✅ |

### ⚠️ 改 `modules/installed/` 后必须做这三步

```bash
set X6_KEY_VAULT=E:\xiao6-keys
py -3 tools/rebuild_modules_repo.py --apply   # 同步到 modules_repo
py -3 tools/sign_modules.py                   # 重新签名
py -3 tools/check_repo_sync.py                # 验证一致
```
**忘了会怎样**：`check_repo_sync` 会红，而且用户端装的插件还是旧的。

---

## 六、新人从哪儿读起

**这 10 个文件看完就懂 80%**（按顺序）：

| # | 文件 | 看什么 |
|---|---|---|
| 1 | `run.py` | 启动顺序（只有 130 行） |
| 2 | `core/trunk.py` | 微核：注册 / 懒加载 / call / reply |
| 3 | `core/lazy_config.py` | 72 个模块的登记表（LAZY_MAP） |
| 4 | `core/pipeline/reply_pipeline.py` | 主链路四步 |
| 5 | `core/pipeline/context_builder.py` | 检索 + 选工具 |
| 6 | `core/tool_caller.py` | 分发 + 安全分级 |
| 7 | `modules/base.py` | 插件协议（就 1 个基类） |
| 8 | `core/config.py` | 配置读写（原子写） |
| 9 | `core/safe.py` | 安全封装（原子写 / 错误记录） |
| 10 | `gui/app_pyqt.py` | 界面怎么起来的 |

---

## 六点五、兼容性、迁移与插件 API（2026-10-20）

```
支持矩阵        Windows 10/11  Python 3.10/3.11/3.12
CI              .github/workflows/compat-matrix.yml（2 个 Windows runner  3 个 Python）
环境检查        tools/check_runtime_compat.py
数据版本        data/_schema.json + core/data_schema.py
数据迁移        core/data_migrations.py: v0 -> v1 -> v2，逐级执行
迁移安全        先备份 -> 原子写 -> 坏行 .bad_lines -> 失败不覆盖
插件 API        core/plugin_api.py: PLUGIN_API_VERSION = "1.0"
插件边界        manifest.api_version + AST 静态检查；私有 core 模块禁止
```

启动时 `Trunk` 会调用 `data_schema.migrate()`；迁移报告写入运行日志。
插件市场在验签之后、落盘/加载之前调用 `validate_plugin_manifest()`，
失败直接拒绝安装。兼容性细节见 `docs/70_兼容性与数据迁移.md`。

---

## 七、几条**不能违反**的规矩（都有守卫盯着）

| 规矩 | 为什么 | 谁在盯 |
|---|---|---|
| 模块之间不许互相 import | 一旦成网，就没法单独替换任何一个 | `check_shapes`（星型拓扑） |
| 子线程不许碰 Qt 控件 | 会**随机崩溃**，而且不在崩溃点报错 | `check_threads` |
| 静默 except 要写理由 | 354 处存量冻结，只许减不许增 | `check_silent` |
| 后台工作线程不许被异常杀死 | 死了没人知道，表现为"它突然不理我了" | 测试（AST 检查） |
| 大而可再生的东西不进备份 | 曾把 705 MB 浏览器内核当用户数据备份 | `test_backup_scope` |
| 用户文档不许被工具删 | 出过一次，原因至今没定位到 | `test_user_docs_intact` |
| 版本号单一来源 | 三处（version.py / CHANGELOG / 说明.txt）必须一致 | `check_version` |
| 按钮有预算 | 逼你想"这个按钮『说一句』替代不了吗" | `check_buttons` |

---

## 八、出问题时先看哪儿

| 现象 | 先看 |
|---|---|
| 崩了 / 卡死 | `data/logs/faulthandler.log`（全部线程的 Python 栈） |
| 崩在 DLL 里（faulthandler 看不出） | 跑 `崩溃转储配置.bat`，拿进程 dump 用 WinDbg |
| 某个功能没反应 | `data/logs/trunk.log`；看 `trunk.call` 返回的 `error` |
| 它"记不住事" | `data/vectors.db` + `core/vector_store.py`（嵌入降级了？） |
| 它"今天没性格" | `data/personality.json` 有没有坏；`full_hint` 有没有抛 |
| 测试随机崩 | 先数线程（`Trunk.__init__` 那两个线程是无条件起的） |

---

## 九、工程化现状（数据说话）

```
生产代码    30,000+ 行（core 86 文件 / gui 47 / modules 44）
测试        971 passed / 2 skipped（共 973 个用例），60 个 test_*.py
守卫        7 个 check_*.py + pre_commit_check.py（git hook 已装）
插件签名    43 条 RSA
覆盖率      41.7%（v25.2.15 实测基线；之后补了 300+ 用例，请跑 `py -3 tools/measure_coverage.py` 重测）
分发        201.4 MB（打包源，含 PyQt5 142 MB）
```

**算覆盖率**：`py -3 tools/measure_coverage.py`
**发版前**：跑 `check.bat`（7 步）
**打包**：`同步打包目录.bat` → 加固打包.exe → 安装包生成器.exe


---

## 十、安全与任务运行时（v25.2.23）

新增核心模块：

| 模块 | 作用 |
|---|---|
| `core/permission_center.py` | 统一工具权限、once/session/always 规则、紧急锁定 |
| `core/net_guard.py` | 出站网络策略：私有 IP / 回环 / 元数据地址 / file:// 拦截 |
| `core/sandbox.py` | 进程级代码执行沙箱：临时目录、环境清理、超时杀进程树 |
| `core/audit_log.py` | 结构化审计日志与脱敏导出 |
| `core/task_runtime.py` | 持久化任务状态机：暂停、取消、恢复、失败重试 |
| `core/trace.py` | 任务、工具、网络事件时间线 |
| `core/diff_review.py` | 文件修改 unified diff |
| `core/document_parser.py` | PDF/Word/Excel/PPT/Markdown/HTML 解析 |
| `core/retrieval.py` | BM25 + 向量混合检索 |
| `core/memory_manager.py` | 记忆编辑、遗忘、来源和置信度 |
| `core/workspace.py` | 工作区目录隔离 |
| `core/model_registry.py` | 模型登记和健康检查 |
| `core/usage_tracker.py` | token/耗时/费用统计 |
| `core/plugin_governance.py` | 插件权限估计、信任等级、安装历史 |

新增界面：

- `gui/security_center_dialog.py`
- `gui/task_center_dialog.py`

新增数据目录：

```text
data/security/       权限、网络规则、审计、网络事件
data/task_runtime/   任务状态
data/traces/         trace
data/usage/          用量统计
data/workspaces/     工作区
data/certs/mobile/   手机端 HTTPS 证书
```

发布前验证：

```powershell
py -3 -m pytest -q
py -3 tools/run_eval.py
py -3 tools/make_sbom.py
```


## 十一、第二阶段新增模块（2026-10-20）

| 文件 | 职责 |
|---|---|
| `core/llm_providers.py` | 8 类模型服务商请求/响应适配 |
| `core/model_router.py` | 能力矩阵与本地/云端路由 |
| `core/rag_pipeline.py` | 增量 RAG、ACL、引用、混合检索、rerank |
| `core/gui_agent_quality.py` | 双通道定位、验证、修复、DPI/IME |
| `core/plugin_registry.py` | 插件 SemVer、兼容、信任等级、更新选择 |
| `core/plugin_installer.py` | 更新前备份、热加载、安装账本 |
| `core/team_policy.py` | RBAC、用户隔离、集中配置、审计 |
| `core/model_pricing.py` | Token 价格估算 |
| `gui/cloud_provider_dialog.py` | 模型服务商配置 |
| `gui/rag_dialog.py` | RAG 管理窗口 |
| `gui/team_dialog.py` | 团队管理窗口 |
| `gui/usage_dialog.py` | 用量成本窗口 |
| `gui/panel_registry.py` | 命令面板/设置共享入口表 |

入口统一从 `gui/panel_registry.py` 注册，命令面板 Ctrl+K 可打开
「RAG管理」「团队管理」「用量成本」「模型用量」。


## 十二、启动链路（2026-10-20 秒开改造）

```
run.py
  ├─ core/startup.mark("进程启动")
  ├─ sys.path: 项目根 / libs / optional_libs
  ├─ win_dll_fix.preload_msvc_runtime()
  ├─ auto_report.start()  -> crash_watchdog.spawn()   ← 独立进程，先跑
  └─ gui.app_pyqt.run_pyqt(startup)
       ├─ QApplication（约 70~120ms）
       ├─ core.font_bootstrap.ensure_fonts(app)   ← 字体为 0 时注册系统字体
       │     （否则 Qt 会把每个字画成空白 —— 表现为"界面全白"）
       ├─ JarvisWindow(boot_signal=False) 只建骨架 -> show()（约 160~200ms 可见）
       └─ BootController（QTimer 后置）
            ├─ Trunk() 核心模块并行注册
            ├─ 模块星图导出丢后台线程
            ├─ _init_from_trunk() 补挂 UI/账号/定时器
            │     └─ build_ui() → setCentralWidget(central)  ← 主界面在这里装好
            └─ 1 秒后补启 LLM 看门狗与模型预热
```

### ⚠️ 启动收尾的两条铁律（都是踩过的坑）

1. **`on_finished` 里禁止调用 `setCentralWidget`。**
   骨架页只是占位 QLabel；`build_ui()` 已经装好主界面，再调
   `setCentralWidget(None)` 会把整张界面拆掉，表现为
   "标题栏还在、状态栏还在、中间全白"。
   正确做法：`ph.setParent(None)` + `ph.deleteLater()`。
   守卫：`tests/test_font_and_dialogs.py` 与 `tests/test_boot_controller.py` 里的 AST 断言。

2. **没有 `QApplication` 时不能碰 `QFontDatabase`。**
   否则 Qt 报 "Must construct a QGuiApplication before accessing
   QFontDatabase"，随后进程 0xC0000409 硬退出。
   统一走 `core/font_bootstrap._gui_app()` 判断。

### 白屏的两类现场（排查时先分类）

| 现象 | 含义 | 处理 |
|---|---|---|
| 状态栏有字、中间空白 | 主界面被清空（代码 bug） | 检查 `on_finished` 是否动了 centralWidget |
| 连按钮文字都是空白块 | Qt 字体族为 0 | `core/font_bootstrap.ensure_fonts()` 是否执行 |
| 一直停在"正在启动…" | BootController 未完成 | 看日志"启动失败"，检查 `_init_from_trunk` 异常 |

调试：`trunk.log` 里搜 `[启动耗时]`；想恢复"全部就绪才显示"设
`X6_BLOCKING_BOOT=1`。


## 十三、插件标准 v1.0（2026-10-21）

插件不是"能跑就算"，必须满足 8 条标准（全文见 `docs/PLUGIN_STANDARD.md`）：

| 编号 | 标准 | 强制点 |
|---|---|---|
| S1 | 清单必填字段齐全 | 安装/下载前 |
| S2 | `api_version=1.0` | `manifest_api_version()` |
| S3 | `capabilities` 5 段齐全 | `validate_capabilities()` |
| S4 | 只能用公共 core 模块 | AST 静态检查 |
| S5 | sha256 + RSA 签名 | 验签后才落盘 |
| S6 | 文件名/路径越界防护 | `safe_plugin_filename` |
| S7 | 运行时经 broker 授权 | 每次能力调用 |
| S8 | 风险/信任等级展示 | 插件市场 UI |

当前合规：48/48 声明能力、48/48 已签名、0 个 legacy。
契约测试 `tests/test_plugin_standard.py` 防止标准被悄悄放宽。

---

## 工作台架构（2026-10-22）

### 分层

```text
┌─────────────────────────────────────────────────────┐
│ gui/workbench_dialog.py                             │
│   WorkbenchWindow（QMainWindow）                     │
│     ├─ QSplitter(H)  左文件树 | 右内容               │
│     └─ QSplitter(V)  上编辑器 | 下 AgentDock         │
├─────────────────────────────────────────────────────┤
│ 复用组件                                             │
│   gui/code_editor_dialog.py  （编辑器，已内嵌）       │
│   gui/diff_dialog.py         （diff 审批）           │
│   gui/agent_timeline.py      （步骤时间线）           │
├─────────────────────────────────────────────────────┤
│ 能力层（未改动）                                      │
│   core/agent_orchestrator.py  路由 + 调度             │
│   core/code_agent.py          代码改动                │
│   core/computer_agent.py      电脑操作                │
└─────────────────────────────────────────────────────┘
```

### 代码 Agent 能力层（2026-10-24）

```text
core/code_roles.py        探索 Agent（只读工具 -> report）
                          修改 Agent（report + patch）
core/code_agent_policy.py 轮次上限（默认 12，1~15）+ 终止条件
core/symbol_parser.py     Python AST / JS-TS tree-sitter（可选）/ 正则降级
core/patch_engine.py      dry_run_patch（整批预演）+ 写盘失败整批回滚
core/code_task_queue.py   data/code_jobs/queue.json：队列 + 断点续跑
core/github_pr.py         REST：blob/tree/commit/ref/PR/check-runs/merge
gui/inline_diff.py        编辑器内联 diff：跳转 + 应用/撤销（QLabel 链接）
```

流程：`工作台 AI 面板 -> CodeTaskQueue -> AgentOrchestrator -> CodeAgent`
- 每轮：探索（AST 符号索引）→ 修改 Agent 出 patch → dry-run → 审批 →
  应用 → tests/lint → `evaluate_round`；
- `evaluate_round` 只在"全绿 / 连续两轮同指纹 / 轮次用尽"时停止，
  并把 `stop_reason` 写回队列与时间线；
- PR 流程走 `api.github.com`（`git push` 到 github.com:443 会被 RST），
  Token 只来自参数/环境/凭据管理器，不进入日志或异常文本。

### 关键设计决策

| 决策 | 理由 |
|---|---|
| 不用功能页签 | 用户要求同屏可见；页签会隐藏上下文 |
| 编辑器复用而非重写 | 语法高亮、jedi 补全、多文件标签已验证 |
| AgentDock 委托 orchestrator | 与旧"Agent 旅程"共用同一能力层，无重复实现 |
| 接入方式 | 旧入口（`open_code_editor` / `agent_journey_dialog` / `code_agent_dialog`）全部转发到 `open_workbench()` |
| 按钮精简 | 收起→Ctrl+J，全屏→F11；只保留"开始/暂停/取消/弹出"这类必须即时点击的动作 |

### 启动确认架构

```text
core/startup_consent.py    启动期确认记录（可记住项 + 永不记住项）
core/mcp_trust.py          MCP 命令信任（按命令哈希）
core/auth.py               session.json（只存账号名，启动重新验签）
```

`ALWAYS_ASK` 里列出的操作（覆盖/删除文件、关机、执行命令等）
即便被写入记录也会被 `should_ask()` 强制返回 True。


---

## 入口注册表（2026-10-22）

`core/feature_registry.py` 是**所有主界面入口的唯一真相源**，
`gui/build_ui.py` 只按它渲染，不自己写第二套可见性规则。

### 单入口原则

编辑能力合并后只保留一个 Feature：

```python
Feature("workbench", "工作台", "🧰", "工具", (ADVANCED,), 140,
        False, "编辑器 + AI 面板同屏…", "editor_btn", "open_workbench")
```

历史 id（`code_editor` / `agent_journey` / `code_agent`）通过
`ALIASES` 映射到 `workbench`，保证旧调用不失效。

### 为什么保留别名而不是直接删

| 使用方 | 影响 |
|---|---|
| 命令面板全文搜索 | 用户仍可能搜到旧词 |
| 历史文档/教程 | 引用旧名 |
| 测试/脚本 | 按旧 id 断言 |

删别名会造成"入口消失"式回归，因此保留转发。

---

## v3.1 增量架构（2026-10-23）

- **技能层**：`core/skill_registry.py` 统一扫描 zip / captured / pending；`core/skills_market.py` 负责目录、下载和 sha256 校验；`core/skills_catalog.json` + `skills_repo/` 随包分发。
- **注入层**：`core/trunk_reply.py` 将启用技能作为独立 system 消息注入，不再拼接 user_input，避免群聊 300 字截断时丢掉用户原话。
- **浏览器层**：`web_agent` 先取可交互元素 DOM 摘要，再用 VLM 截图描述补足；动作失败返回 ok=False。
- **Web 控制台**：`api_server` 使用 localhost + 临时 token；任务创建/查询接真实 TaskRuntime；WebSocket 依赖 `websockets`，缺失时明确降级。
- **按钮精简**：侧栏高级入口只保留任务中心/命令面板，其余收进右上角「更多」；技能管理只保留导入/导出/更多/关闭，低频动作进菜单。
