# 小6智能体  产品体验与 Agent 能力提升方案

版本：v1.0  
日期：2026-10-19  
状态：本轮范围已闭环；macOS / Linux 适配层按需求不做  
适用范围：GUI 使用体验、代码 Agent、电脑操控 Agent、任务运行时、可观测性与工程化

---

## 实施进度（2026-10-19）

已完成的基础里程碑：

- Sprint 1 基础完成：
  - `core/agent_harness.py`：RunRegistry、统一错误信封、任务活动同步。
  - `core/task_runtime.py` 状态事件接入活动注册表。
  - `gui/activity_center_dialog.py`：运行中活动中心。
  - 状态栏运行中 N入口，点击打开活动中心。
  - 聊天、任务闭环、学习闭环、TTS、后台 BgWorker、后台后处理均接入活动注册表。
  - MCP stdio 子进程连接/断开也进入活动中心，并预导入传输层避免并发 import 崩溃。
- Sprint 2 基础完成：
  - `gui/theme_manager.py`：主题、字号、密度持久化。
  - `gui/window_state.py`：窗口位置、大小、最大化状态持久化。
  - 设置窗口增加主题和界面密度选项，以及设置搜索。
  - 设置项补充影响说明、主题/密度即时预览、命令面板快捷键配置。
  - `gui/feedback_states.py`：Loading / Empty / ErrorCard 统一组件。
- Sprint 3 基础完成：
  - `core/workspace_index.py`：文件、Python 符号、import、测试关联索引。
  - `core/patch_engine.py`：多文件 patch 校验、diff、应用、备份、回滚。
  - `trunk.get_workspace_index()` 懒加载入口。
- Sprint 4 基本完成：
  - `core/code_agent.py`：项目上下文 -> patch -> 审批 -> 应用 -> 测试 -> 回修 -> 回滚。
  - `gui/diff_dialog.py`：文件/hunk 勾选、diff 预览、应用选中修改。
  - `gui/code_agent_dialog.py`：代码 Agent 界面、测试命令、失败后继续修复。
  - 代码编辑器 AI 修复改为先显示 unified diff，用户批准后才替换。
  - 编辑器右键支持撤销上次 AI 修改；保存后增量更新项目索引。
  - Git 工作区状态记录和 dirty diff 备份。
  - 测试/lint 命令执行、失败定位解析和失败后继续修复。
  - v25.2.28：`core/code_plan.py` 复杂任务先出结构化计划，用户确认后才进入 patch 审批；拒绝零落盘。
  - v25.2.28：`agent._llm_chat()` 接入 `CancelToken`，Esc 在单次模型生成期间立即生效。
- 对话体验补齐：
  - 右键编辑上一条消息
  - 重新生成上一条回复
  - 从当前对话创建分支
- Sprint 5 基础完成：
  - `core/action_schema.py`：类型化电脑动作和验证条件。
  - `core/computer_agent.py`：Observe -> Act -> Verify -> Retry harness。
  - `core/visual_grounding.py`：UIA 元素解析与目标打分。
  - `core/action_recorder.py`：动作录制、保存和回放。
  - 支持 screenshot_diff 视觉变化验证。
  - 融合 UIA + OCR + 多模态描述进行元素 grounding。
  - LLM 自动生成跨应用电脑任务计划，并在 GUI 中确认执行。

已完成（原「尚未完成」清单，2026-10-25 核对）：

- 活动中心对非任务后台作业的全面接入（v25.2.30）。
- 设置搜索和统一 Loading/Empty/Error 组件（`gui/feedback_states.py`）。
- 聊天/命令入口直接生成多文件 patch 并进入审批。
- 自动测试运行器、lint、失败自动回修。
- 项目测试运行器、自动回修、Git 状态保护。
- 截图元素 grounding、视觉验证和跨应用电脑任务（`core/visual_grounding.py`、`core/computer_agent.py`）。
- 操作录制回放（`core/action_recorder.py`）。

仍未完成 / 明确不做：

- 跨平台适配层（macOS / Linux）：按需求不做。
- 覆盖率门槛继续棘轮、Agent 回归基线常态化：见下方「工程加固（批次 6）」。

> 注意：本清单曾长期保留"自动测试、lint、失败回修、多文件 patch、diff 审批、回滚未完成"的旧结论，
> 与代码实际状态不符。以上述核对结果为准，后续规划不要重复立项。


## 0. 结论先行

小6当前不是功能不足，而是能力已经存在，但还没有形成成熟产品应有的闭环。

三个最关键的差距：

1. **使用感受**：任务过程不够透明，失败恢复不够统一，长任务和后台活动不可见，对话缺少编辑、重试和分支。
2. **代码能力**：编辑器目前是可用编辑器，AI 改代码还是生成完整文件并替换，没有形成项目理解 -> 多文件 patch -> diff 审批 -> 测试回修 -> 回滚的闭环。
3. **电脑操控**：动作能力齐全，但缺少感知 -> 规划 -> 执行 -> 验证 -> 重试/回滚的视觉 Agent 闭环。

本方案的目标不是简单增加按钮，而是把现有能力统一到一套可观测、可恢复、可审计的 Agent Harness 中。

目标形态：

```text
用户目标
  -> 计划
  -> 工具/模型执行
  -> 结果验证
  -> 失败诊断
  -> 自动重试或请求用户
  -> 结果交付
  -> 可回放、可撤销、可继续
```

---

## 1. 设计原则

### 1.1 一个 Agent Harness，多个执行域

聊天、任务、代码、电脑操控不要各自维护一套状态机。以现有 `core/task_runtime.py` 为基础，扩展为统一执行 harness，代码修改和电脑操作都作为 harness 的一类执行域。

### 1.2 每一步必须有状态、原因和验证条件

每个步骤至少记录：

- 做什么
- 为什么做
- 用了哪个工具或模型
- 开始/结束时间
- 消耗的 token、费用和时间
- 结果摘要
- 验证条件
- 失败原因
- 可执行的下一步
- 是否可回滚

### 1.3 失败不是终点，而是一个结构化状态

统一错误信封：

```json
{
  "ok": false,
  "code": "NETWORK_DENIED",
  "title": "网络被拒绝",
  "message": "这次请求被安全策略拦截",
  "cause": "目标域名不在允许列表中",
  "next_action": {
    "id": "open_security_network_events",
    "label": "查看安全中心网络事件"
  },
  "technical_detail": "...",
  "task_id": "task_..."
}
```

UI 只展示 title、message、next_action；技术细节折叠。

### 1.4 UI 不等待，状态主动推送

所有长任务、模型调用、工具调用、文件修改、测试执行都在后台运行。主线程只负责渲染状态和接收事件。

### 1.5 安全边界内自动化

- 低风险动作自动执行并记录。
- 中风险动作展示预览并确认。
- 高风险动作必须二次确认，默认 fail-closed。
- 所有动作有审计记录，代码修改有备份，电脑操作有回滚依据。

### 1.6 向 DeepSeek Harness 类 Agent 框架靠拢

本方案中向 DeepSeek Harness 靠拢定义为以下工程原则，不依赖某个特定产品的内部实现：

- 工具 schema 化，而不是自由文本解析
- Observation -> Plan -> Act -> Verify -> Reflect 循环
- 明确的执行状态机和 checkpoint
- 上下文压缩与长期记忆分层
- 工具调用、权限、沙箱、审计统一入口
- 任务可回放、可恢复、可中断
- 每个动作都有验证和失败恢复策略
- 计划器、执行器、验证器职责分离
- 预算、超时、重试和幂等控制

---

## 2. 总体目标架构

```text
GUI
   聊天视图
   任务中心
   运行中活动中心（新增）
   代码工作区
   电脑操作查看器
   diff 审批窗口（新增）
   设置 / 主题 / 窗口状态

Agent Harness
   Goal / Plan
   Step State Machine
   Tool Registry
   Permission / Policy
   Context Manager
   Executor
   Verifier
   Recovery Manager
   Trace / Event Bus
   Artifact Store

执行域
   Chat
   Code Workspace
   Computer Use
   File / Shell
   Knowledge / Retrieval
   Background Jobs
```

新增或改造模块建议：

| 模块 | 作用 |
|---|---|
| `core/agent_harness.py` | 统一任务执行循环、步骤状态、验证和恢复 |
| `core/action_schema.py` | 工具和电脑操作的类型化 schema |
| `core/workspace_index.py` | 项目文件、符号、import、测试索引 |
| `core/patch_engine.py` | 多文件 patch 生成、校验、应用和回滚 |
| `core/computer_agent.py` | 截图 + UIA + OCR 的感知/规划/执行/验证 |
| `core/verifier.py` | 退出码、测试、文件状态、截图差异等验证器 |
| `core/artifact_store.py` | 输出文件、截图、diff、测试报告、回放记录 |
| `gui/activity_center_dialog.py` | 统一运行中任务/后台活动面板 |
| `gui/diff_dialog.py` | 文件级和 hunk 级 diff 审批 |
| `gui/theme_manager.py` | 主题、字号、密度、强调色 |
| `gui/window_state.py` | 窗口布局、分栏和位置记忆 |
| `gui/error_presenter.py` | 统一错误卡片和下一步渲染 |

---

## 3. 使用感受提升方案

### 3.1 统一运行中活动中心

#### 目标

用户随时知道：

- 后台在跑什么
- 任务是否还在运行
- 是否在等权限
- 是否在消耗 token 或费用
- 是哪个任务/窗口/文件引起的
- 关闭窗口后任务是否继续
- 如何暂停、取消、继续

#### UI

新增 `gui/activity_center_dialog.py`，可以从以下位置打开：

- 状态栏运行中 N按钮
- 任务中心
- 头像菜单
- 命令面板
- 任务卡片

列表字段：

```text
状态 | 任务名 | 当前步骤 | 已耗时 | 预算 | 等待事项 | 操作
```

操作：

- 查看详情
- 暂停 / 继续
- 取消
- 打开任务中心
- 查看日志 / trace
- 授权 / 拒绝（等待权限时）
- 结束全部后台

#### 技术

- 由 harness 维护全局 `RunRegistry`
- 每个 run 注册 `run_id`、`task_id`、`kind`、`status`、`owner`
- UI 通过事件订阅刷新，不轮询整张表
- 窗口关闭时按配置选择：继续后台运行 / 询问 / 中止

#### 验收

- 所有活跃任务在 500ms 内出现在活动中心
- 任何任务都能从活动中心取消
- 关闭主窗口后可选择后台继续或停止
- 活动中心不阻塞 UI 线程

---

### 3.2 任务时间线升级

#### 每个步骤显示

- 标题
- 目的：为什么执行这一步
- 工具：tool name、model name
- 时间：开始、结束、耗时
- 状态：pending/running/waiting_approval/verifying/done/failed/cancelled
- 结果摘要
- 验证结果
- token / cost
- 错误和下一步
- 产物：文件、diff、截图、日志、测试报告

#### UI 展示

任务详情采用计划 + 时间线双视图：

```text
目标
 步骤 1  完成  2.1s
 步骤 2  完成  8.4s
 步骤 3  验证中
 步骤 4  等待确认
```

点击步骤展开：

```text
为什么做
使用了什么工具
输入参数摘要
输出摘要
验证结果
失败原因
可执行下一步
```

#### 验收

- 每个步骤有非空目的说明
- 每个失败步骤有唯一下一步
- 任务完成后有结果摘要和产物链接
- 任务中断后恢复不需要用户重复描述目标

---

### 3.3 统一错误恢复协议

#### 统一错误分类

| code | 用户文案 | 唯一下一步 |
|---|---|---|
| MODEL_NOT_CONFIGURED | 模型还没配置好 | 去设置模型 |
| PERMISSION_DENIED | 权限被拒绝 | 重新授权 / 去安全中心 |
| NETWORK_DENIED | 网络被拒绝 | 查看安全中心网络事件 |
| TOOL_NOT_FOUND | 工具不存在 | 去插件市场 |
| TASK_TIMEOUT | 任务超时 | 增加预算 / 继续任务 |
| TASK_FAILED | 任务失败 | 重试失败步骤 |
| FILE_CONFLICT | 文件已被修改 | 查看 diff / 重新生成 |
| TEST_FAILED | 测试未通过 | 查看失败测试 / 自动修复 |
| MODEL_ERROR | 模型调用失败 | 切换模型 / 重试 |

#### UI 组件

新增统一错误卡片：

```text
标题
一句人话解释
唯一下一步按钮
[技术细节] 折叠
```

同一个组件用于聊天、任务中心、代码编辑器和电脑操作。

#### 验收

- 主导航上不出现原始 traceback
- 所有失败状态有一个 primary action
- 技术细节可展开、可复制、可脱敏导出
- 错误 code 可被测试和日志检索

---

### 3.4 对话编辑、重试和分支

#### 能力

- 编辑上一条用户消息
- 从某条消息重新生成
- 换模型重新生成
- 会话分支
- 重新生成时保留原回答作为分支
- 消息引用
- 文件引用
- 代码行引用
- 回答中的来源引用和可点击定位
- 长回答折叠/展开

#### 数据模型

```json
{
  "session_id": "s_...",
  "message_id": "m_...",
  "parent_id": "m_prev",
  "branch_id": "b_...",
  "role": "user",
  "content": "...",
  "attachments": [],
  "refs": [
    {"type": "file", "path": "gui/build_ui.py", "lines": "120-180"}
  ]
}
```

#### 验收

- 编辑消息后能重新生成
- 原分支不丢失
- 消息引用可定位到文件和行
- 附件可预览、删除、重新排序

---

### 3.5 设置、主题与窗口布局记忆

#### 设置搜索

- 搜索框匹配设置项名称、说明和当前值
- 搜索结果直接定位到对应控件
- 支持最近修改项

#### 设置项说明

每项显示：

- 当前值
- 默认值
- 影响范围
- 是否需要重启

#### 主题

新增 `gui/theme_manager.py`：

```json
{
  "appearance": {
    "theme": "system",
    "accent": "blue",
    "font_size": 14,
    "density": "comfortable",
    "radius": "medium",
    "code_font": "Consolas"
  }
}
```

支持：

- 跟随系统 / 浅色 / 深色
- 强调色
- 字号
- 密度
- 圆角
- 代码字体
- 高对比度模式

#### 窗口布局记忆

新增 `gui/window_state.py`：

```json
{
  "window": {
    "geometry": [100, 80, 1280, 820],
    "maximized": false,
    "sidebar_width": 230,
    "main_splitter": [320, 960],
    "editor_splitter": [280, 820],
    "task_splitter": [300, 940],
    "last_page": "chat"
  }
}
```

实现要求：

- 写入 `data/ui_state.json`
- 防抖保存，避免拖动时频繁写盘
- 启动时校验窗口是否仍在可见屏幕内
- 多显示器拔插后自动回退到主屏
- 提供恢复默认布局按钮
- 主题、字号、密度、窗口状态分别可重置

#### 验收

- 重启后窗口位置、大小、分栏宽度恢复
- 窗口在屏幕外时自动回到可见区域
- 主题切换即时生效
- 设置搜索能定位到目标项

---

### 3.6 统一加载、空状态、失败状态组件

建立统一组件：

- `LoadingBlock`
- `EmptyState`
- `ErrorCard`
- `PermissionCard`
- `TaskResultCard`
- `ArtifactList`
- `ProgressRing / ProgressBar`

要求：

- 所有长操作都有 loading 和取消
- 所有空页面都有下一步
- 所有失败都使用统一错误卡片
- 所有任务结果都有产物、查看任务和下一步

---

### 3.7 通知与免打扰

- 任务完成通知
- 等待授权通知
- 失败通知
- 长任务进度通知
- 免打扰时间段
- 按任务类型静音
- 通知点击后定位到活动中心或任务详情

---

## 4. 代码 Agent 提升方案

### 4.1 目标

把当前编辑器 + AI 修复升级为：

```text
项目理解
  -> 相关文件定位
  -> 多文件修改计划
  -> patch 生成
  -> diff 审批
  -> 应用修改
  -> 运行测试 / lint / 编译
  -> 失败定位并自动回修
  -> 结果报告
  -> 一键回滚
```

### 4.2 项目索引

新增 `core/workspace_index.py`。

索引内容：

- 文件树
- 文件语言、大小、修改时间
- Python AST：类、函数、变量、import
- import 依赖图
- 调用关系
- 测试文件关联
- 项目运行命令
- 代码风格配置
- 最近修改文件

索引存储建议：

```text
data/workspace_index/{workspace_id}/
  files.json
  symbols.json
  deps.json
  tests.json
  meta.json
```

更新策略：

- 启动时增量扫描
- 文件保存后局部更新
- 大批量修改后后台重建
- 索引损坏时自动重建

### 4.3 多文件 Patch Engine

新增 `core/patch_engine.py`。

Patch 格式：

```json
{
  "patch_id": "p_...",
  "goal": "修复设置窗口保存失败",
  "files": [
    {
      "path": "gui/settings_dialog.py",
      "base_hash": "sha256...",
      "hunks": [
        {
          "old_start": 120,
          "old_lines": ["..."],
          "new_lines": ["..."],
          "reason": "修复 None 引用"
        }
      ]
    }
  ],
  "risk": "medium",
  "tests": ["pytest tests/test_settings_entries.py -q"]
}
```

安全要求：

- 应用前检查 base_hash
- 每个 hunk 必须能唯一匹配
- 冲突时拒绝应用，不覆盖用户修改
- 自动备份原文件
- 支持文件级和 hunk 级接受/拒绝
- 支持一键撤销本次 patch

### 4.4 Diff 审批窗口

新增 `gui/diff_dialog.py`。

功能：

- 文件列表和变更统计
- 文件级接受 / 拒绝
- hunk 级接受 / 拒绝
- 风险等级
- 修改原因
- 影响文件
- 测试计划
- 应用后自动执行验证

### 4.5 测试与自动回修

流程：

1. 应用 patch
2. 运行配置好的测试/lint/编译命令
3. 解析失败输出
4. 将失败文件、traceback、测试用例反馈给模型
5. 生成下一轮 patch
6. 最多重试 N 次
7. 失败后将工作区恢复到 patch 前状态，并给出下一步

测试命令来源：

- 项目配置
- `pyproject.toml`
- `pytest.ini`
- 用户设置
- 自动探测

### 4.6 代码工作区运行环境

在现有 `gui/code_editor_dialog.py` 基础上增加：

- 项目虚拟环境选择
- 工作目录
- 环境变量
- 内置终端
- 当前文件运行
- 项目任务运行
- 端口/服务检测
- 长进程管理
- 运行历史

短期不追求完整 IDE，但需要具备代码 Agent 可执行验证的最小运行环境。

### 4.7 Git 与回滚

- 显示当前分支和 dirty 状态
- patch 应用前检查工作区是否干净
- 支持生成临时分支或 stash
- 支持撤销本次 Agent 修改
- 支持查看 patch 对应的 commit/diff
- 冲突时停止，不自动覆盖

### 4.8 验收指标

- 能定位并修改至少 2 个相关文件
- 所有修改先展示 diff
- 支持按文件/按 hunk 接受
- 应用后自动跑测试
- 测试失败能自动产生第二轮 patch
- 任何一次 Agent 修改都能一键回滚
- 修改过程有完整 trace 和测试报告

---

## 5. 电脑操控 Agent 方案：向 DeepSeek Harness 类执行框架靠拢

### 5.1 核心循环

```text
Observe
  -> 截图
  -> 可访问性树 UIA
  -> OCR / 视觉理解
  -> 当前窗口和屏幕状态

Plan
  -> 目标拆解
  -> 选择应用/窗口
  -> 选择控件或坐标
  -> 预估风险和验证方式

Act
  -> 点击 / 输入 / 快捷键 / 滚动 / 文件操作
  -> 每次只做一个可验证动作

Verify
  -> 再截图
  -> 检查窗口标题、控件状态、文本变化、文件变化
  -> 判断成功 / 失败 / 需要重试

Reflect
  -> 更新世界状态
  -> 失败时分析原因
  -> 重试、回退或请求用户
```

### 5.2 感知层

新增统一感知结果：

```json
{
  "screen": {
    "size": [1920, 1080],
    "scale": 1.25,
    "active_window": "记事本",
    "monitor": 0
  },
  "accessibility": {
    "windows": [],
    "controls": [
      {
        "id": "uia_17",
        "name": "保存",
        "type": "ButtonControl",
        "rect": [100, 200, 80, 30],
        "enabled": true
      }
    ]
  },
  "vision": {
    "text_blocks": [],
    "detected_buttons": [],
    "description": "当前窗口是..."
  }
}
```

感知优先级：

1. UIA 控件树
2. 浏览器 DOM/可访问性信息（后续）
3. OCR / 视觉模型
4. 原始坐标兜底

### 5.3 动作 schema

所有电脑动作用类型化 schema 表达：

```json
{
  "action_id": "act_...",
  "type": "click|type|hotkey|scroll|open_app|activate_window|read_file|write_file|shell",
  "target": {
    "kind": "uia|vision|coordinate|window|path",
    "id": "uia_17",
    "text": "保存",
    "rect": [100, 200, 80, 30]
  },
  "args": {},
  "risk": "low|medium|high",
  "verify": {
    "type": "window_title|control_visible|text_changed|file_exists|exit_code|screenshot_diff",
    "expected": "..."
  },
  "rollback": {
    "type": "none|restore_file|hotkey|screenshot_restore"
  }
}
```

### 5.4 计划器 / 执行器 / 验证器分离

- **Planner**：只产出计划，不直接操作电脑。
- **Executor**：只执行经过 schema 校验的动作。
- **Verifier**：只检查执行结果，不修改状态。
- **Recovery Manager**：失败后选择重试、回退或请求用户。

这样可以避免模型边想边乱点。

### 5.5 视觉 grounding

目标元素定位采用多源融合：

- UIA name/type 精确匹配
- 控件文本模糊匹配
- OCR 文本 + 位置匹配
- 截图视觉模型候选
- 坐标置信度打分

输出：

```json
{
  "candidate_id": "uia_17",
  "confidence": 0.92,
  "source": "uia+ocr",
  "risk": "low"
}
```

置信度低于阈值时：

- 请求用户确认
- 或先放大/滚动/聚焦窗口重新感知

### 5.6 动作后验证

每个动作都带验证条件：

| 动作 | 验证 |
|---|---|
| 点击按钮 | 目标窗口标题/控件状态变化 |
| 输入文本 | 目标输入框内容包含输入内容 |
| 打开应用 | 窗口出现 |
| 保存文件 | 文件 mtime/size 变化 |
| 命令执行 | exit code + 输出 |
| 页面导航 | URL/标题/可见文本变化 |
| 截图操作 | 截图哈希/区域差异 |

验证失败后：

1. 重新截图
2. 重新定位目标
3. 重试 1-2 次
4. 仍失败则停止并给出下一步

### 5.7 回滚与审计

- 文件修改前备份
- 高风险操作前保存快照
- 每个动作记录前后截图
- 记录动作 schema、参数、耗时、结果
- 支持按任务查看操作回放
- 支持撤销文件操作
- 系统级操作不可逆时，在执行前明确说明

### 5.8 跨应用工作流

用一个统一的任务模型表示跨应用步骤：

```json
{
  "goal": "把浏览器查到的内容整理到 Excel",
  "steps": [
    {"app": "chrome", "action": "search", "verify": "结果页出现"},
    {"app": "chrome", "action": "extract_text", "verify": "文本非空"},
    {"app": "excel", "action": "write_rows", "verify": "文件已保存"},
    {"app": "excel", "action": "screenshot", "verify": "表格可见"}
  ]
}
```

要求：

- 每一步有验证条件
- 应用切换有窗口激活确认
- 失败时可回退到上一步
- 支持录制、参数化和重放

### 5.9 命令执行权限

保留现有安全边界，但提供可操作的权限流程：

- 按任务授予临时命令权限
- 展示完整命令、工作目录和影响
- 在沙箱内执行
- 超时、输出上限、环境变量清理
- 危险命令单独确认
- 完整审计和回放

### 5.10 跨平台适配层

新增抽象接口：

```python
class ComputerAdapter:
    def observe(self): ...
    def find(self, target): ...
    def act(self, action): ...
    def verify(self, condition): ...
    def screenshot(self): ...
```

首个实现：Windows UIA + Win32。后续可增加 macOS Accessibility、Linux AT-SPI。

---

## 6. 技术实施路线

### Sprint 1：统一状态与活动中心（1 周）

- `core/agent_harness.py` 基础状态机
- 统一 RunRegistry
- `gui/activity_center_dialog.py`
- 任务事件、步骤时间线扩展
- 统一错误信封和错误卡片

验收：

- 所有任务/工具调用在活动中心可见
- 失败任务有唯一下一步
- 主线程无阻塞

### Sprint 2：主题、窗口状态与设置体验（1 周）

- `gui/theme_manager.py`
- `gui/window_state.py`
- 设置搜索
- 设置项说明
- 统一 Loading / Empty / Error 组件

验收：

- 重启恢复窗口和主题
- 多显示器异常自动回退
- 设置搜索命中后可定位控件

### Sprint 3：代码项目索引与 patch 引擎（2 周）

- `core/workspace_index.py`
- `core/patch_engine.py`
- `core/verifier.py`
- 多文件 patch 数据结构
- 文件备份和回滚

验收：

- 能基于项目索引定位相关文件
- patch 必须通过唯一匹配校验
- 支持一键回滚

### Sprint 4：代码 Agent 闭环（2 周）

- `gui/diff_dialog.py`
- hunk 审批
- 测试/lint 执行
- 失败反馈和自动回修
- 代码工作区终端和运行环境

验收：

- 多文件修改 -> diff -> 应用 -> 测试闭环
- 测试失败能触发回修
- 所有修改可撤销

### Sprint 5：电脑操控感知与验证（2 周）

- `core/action_schema.py`
- `core/computer_agent.py`
- UIA + OCR + 截图感知
- 动作后验证
- 重试和恢复
- 操作日志和截图证据

验收：

- 至少 3 个跨应用场景可完成任务
- 动作失败能自动重试或停止
- 全程有 trace 和回放

### Sprint 6：录制回放、跨应用和打磨（2 周）

- 操作录制
- 参数化重放
- 多应用任务
- 性能优化
- 全量测试和打包

---

## 7. 验收指标

### 使用体验

- 任务开始到首个状态反馈 < 300ms
- 任务状态刷新 < 500ms
- 任意任务可从活动中心取消
- 100% 失败状态只有一个主 next action
- 重启后窗口和主题恢复
- 设置搜索可定位设置项

### 代码 Agent

- 多文件 patch 成功率 >= 90%
- diff 应用前冲突检测覆盖率 100%
- 测试失败自动回修成功率 >= 60%
- 一键回滚成功率 100%
- 代码修改无静默覆盖

### 电脑 Agent

- 单步动作验证覆盖率 100%
- 低风险 UI 操作成功率 >= 85%
- 失败后重试或停止率 100%
- 所有操作可回放
- 高风险动作全部经过确认

### 可观测性

- 每个任务有 trace_id
- 每个步骤有开始/结束/结果
- 每个失败有 code、cause、next_action
- 日志摘要可脱敏导出

---

## 8. 测试策略

- 单元测试：schema、状态机、patch 校验、错误映射
- 集成测试：任务中心、活动中心、diff 审批、权限流程
- GUI 烟雾测试：所有新增窗口可构造
- 端到端测试：代码修改闭环、电脑操作闭环
- 故障注入：超时、权限拒绝、网络失败、文件冲突、模型失败
- 回放测试：同一 trace 可复现任务状态

---

## 9. 风险与边界

1. **视觉定位不稳定**：UIA 优先，OCR/视觉兜底，低置信度请求确认。
2. **模型误操作**：所有副作用动作有 schema、权限、审计和回滚。
3. **多文件 patch 冲突**：base_hash 校验，冲突拒绝，不强制覆盖。
4. **上下文过长**：项目索引检索 + 摘要 + 分阶段上下文。
5. **后台任务失控**：预算、超时、取消、活动中心和全局停止。
6. **跨平台成本高**：先 Windows 做好，再抽象适配层。
7. **功能过多导致 UI 再次膨胀**：所有新入口遵守 feature registry 和按钮预算，默认折叠。

---

## 10. 不建议现在做

- 一开始就做完整 IDE、调试器和所有语言 LSP
- 一开始就做全平台电脑控制
- 无确认的全自动文件覆盖
- 无验证的纯视觉点击
- 让模型自由生成 shell 并直接执行
- 把所有运行状态塞进聊天消息里

---

## 11. 一句话目标

让小6从能聊天、能点按钮、能改当前文件升级为：

> **能理解项目、能安全改多文件、能跑测试回修；能看屏幕、能执行动作、能验证结果；所有过程可看见、可暂停、可恢复、可回滚。**

---

## 最终完成状态（2026-10-19）

本轮方案内、除明确排除的 macOS / Linux 适配层外，均已完成：

- Agent Harness 与活动中心
- MCP 子进程活动登记
- 设置搜索、说明、即时预览、快捷键
- 主题与窗口布局记忆
- 统一 Loading / Empty / ErrorCard
- 聊天编辑 / 重新生成 / 分支
- 代码 Agent：索引、patch、diff 审批、测试、lint、失败定位、继续修复、回滚
- 电脑 Agent：动作 schema、UIA+OCR+多模态 grounding、验证、重试、录制回放、LLM 跨应用计划
- 文档更新
- 打包目录同步

当前验证基线：

- 1026 passed，2 skipped
- 按钮预算 136/136
- 静默失败检查 339/372
- 打包源：E:\xiao6-package，4470 个文件，201.8 MB

不在范围：

- macOS / Linux 适配层


## 2026-10-20 第二阶段完成项

- 模型服务商配置与能力预览。
- RAG 管理窗口（导入、ACL、引用、删除）。
- 团队管理窗口（角色、集中配置、审计）。
- 用量成本窗口。
- 插件检查更新/更新/回滚。
- 电脑 Agent 修复计划可视化。
- 命令面板统一注册表 `gui/panel_registry.py`。

下一阶段重点：真实 GUI 交互回归、插件市场评分/审核/变更日志、
企业 SSO、多设备同步和跨平台基础能力。


## 2026-10-21 首屏体验修复

- 首屏 0.2 秒出现窗口骨架，用户不再盯着空白桌面等 2.5 秒。
- 骨架期显示"正在启动…"占位提示，装配完成自动替换为主界面。
- 修复装配完成后界面被清空（白屏）与字体缺失（空白方块）两类问题。
- 启动引导串行：协议 → 登录 → 首次配置向导，一次只弹一个框。
- 深度自检新增字体检查，用户可自助判断白屏类型。


---

## 实施进展：工作台融合（2026-10-22 已落地）

原方案中「统一 Agent 入口」已实现为**工作台**：

```text
+--------------+----------------------------------+
| 文件树        | 编辑器（多文件标签）               |
|              +----------------------------------+
|              | 🤖 AI 面板（AgentDock）           |
+--------------+----------------------------------+
| 运行输出                                          |
+--------------------------------------------------+
```

| 设计点 | 落地 |
|---|---|
| 无功能页签 | ✅ 不存在"编辑器页/旅程页/Agent页"切换 |
| AI 在下方 | ✅ 垂直 splitter，可拖动 |
| 全屏独立窗口 | ✅ F11 + 「⛶ 弹出」把 AI 面板独立出去 |
| 单一入口 | ✅ 菜单只保留「</> 代码编辑器」 |
| 文件上下文共享 | ✅ `editor_open_files()` 交给 Agent |

价值：以前改完 AI 代码想手动调，必须关窗重开（文件/目录/选中片段全丢）；
现在直接在上方编辑器改，切回下方 AI 继续。

代码：`gui/workbench_dialog.py`（`WorkbenchWindow` + `AgentDock`）。
