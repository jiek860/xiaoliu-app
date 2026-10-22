# Agent 可控闭环落地方案与实施记录

版本：v1.0  
日期：2026-10-19  
状态：已实施并通过全量测试

## 1. 目标

把已有能力串成一条稳定、透明、可中断、可恢复的用户旅程：

```text
用户输入目标
  -> 自动路由（代码 / 电脑 / 对话）
  -> 计划或单步决策
  -> 执行
  -> 验证
  -> 失败重新观察 / 重新规划
  -> 过程可见、可暂停、可取消、可人工接管
  -> 完成后有结果、产物、diff/截图、测试报告
  -> 一键撤销
```

核心原则：

1. **一个入口**：普通用户只面对一个目标输入框；
2. **每一步有状态**：计划、观察、动作、验证、失败原因、下一步；
3. **每个动作可控制**：暂停、继续、取消、人工接管；
4. **每个改动可恢复**：代码 patch 和电脑文件操作都有回滚清单；
5. **权限统一**：代码 Agent、电脑 Agent 都经过 Agent 权限入口和审计；
6. **视觉结果可执行**：UIA/OCR/多模态候选统一带 element_id、rect、confidence；
7. **失败不是终点**：动态循环会重新观察并重新规划，而不是只重试旧动作。

---

## 2. 模块落点

| 模块 | 作用 |
|---|---|
| `core/agent_router.py` | 根据目标选择代码 / 电脑 / 对话 |
| `core/agent_orchestrator.py` | 统一编排执行域、事件、暂停取消、回滚 |
| `core/agent_permissions.py` | Agent 动作统一权限、确认、审计入口 |
| `core/action_schema.py` | 扩展动作、目标、验证条件 schema |
| `core/visual_grounding.py` | 统一 element_id / rect / confidence 输出 |
| `core/computer_agent.py` | 动态 Observe -> Plan -> Act -> Verify -> Replan |
| `core/code_agent.py` | 探索工具、自动测试探测、可中断命令、多操作 patch |
| `core/patch_engine.py` | update/create/delete/rename/write + 回滚 |
| `gui/agent_timeline.py` | 实时步骤时间线、截图、失败原因 |
| `gui/agent_journey_dialog.py` | 统一 Agent 旅程窗口 |
| `gui/code_agent_dialog.py` | 代码 Agent 暂停/取消/回滚/时间线 |
| `gui/computer_agent_dialog.py` | 电脑 Agent 动态执行/暂停/接管/回滚/时间线 |
| `modules/installed/browser.py` | DOM 感知：current_info/get_dom/exists/wait/press/upload |
| `modules/installed/computer_controller.py` | 前台窗口、虚拟桌面、多显示器、DPI、控件值、全屏截图 |

---

## 3. 原始问题逐项闭环

### 3.1 代码 Agent 默认测试命令 NameError

- 修复：`core/code_agent.py` 显式 `import sys`；
- 增强：自动探测 pytest / npm / cargo / go 测试命令；
- 无测试命令时返回 `skipped=True` 和明确原因，不再假装测试通过；
- 命令统一走可暂停、可取消、可超时的 `Popen` 执行器。

### 3.2 control_visible 误判

- 修复：只有 `ui_find()` 返回 `ok=True` 且找到控件数量大于 0 才算可见；
- 回归测试：`test_control_visible_failed_dict_is_not_success`。

### 3.3 视觉 grounding 未接入执行

- UIA / OCR 候系统一输出 `element_id + rect + confidence + source`；
- 规划器提示词直接携带候选 element_id、rect、confidence；
- 执行器优先按 element_id 查找，其次 UIA 名称，再次 rect 中心坐标；
- OCR 行若带 `@(x,y,w,h)` 会保留坐标；
- 截图后自动框选目标区域，供用户核对。

### 3.4 计算机 Agent 不是动态循环

- 新增 `run_goal_dynamic()`：
  - 每一步重新观察；
  - 单步规划；
  - 执行；
  - 验证；
  - 失败反馈给规划器；
  - 下一轮可以换定位方式或换动作；
- `plan_next()` 增加 done 判断、历史、反馈和最新屏幕候选；
- 旧 `run_goal()` 保留兼容，GUI 新路径使用动态循环。

### 3.5 Patch 不能新建/删除/重命名

- `patch_engine` 增加 `op`：
  - `update`：hunk 修改；
  - `create`：创建新文件；
  - `write`：整文件写入；
  - `delete`：删除；
  - `rename`：重命名；
- 支持顺序操作模拟：create/rename 之后可以继续 update；
- 回滚清单记录 existed / backup / new_path，可逆恢复；
- 空白差异做受限模糊匹配，仍拒绝歧义匹配。

### 3.6 暂停/取消/接管

- `CodeAgent` 与 `ComputerAgent` 都有：
  - `cancel()`；
  - `pause()`；
  - `resume()`；
  - 可中断等待和可杀死子进程；
- 代码 Agent 命令执行使用 `Popen`，取消/超时会终止进程树；
- 电脑 Agent 每一步之间检查取消/暂停；
- GUI 提供暂停、继续、取消、人工接管按钮；
- 关闭窗口时提示会取消任务，并等待线程退出。

### 3.7 一键回滚没有入口

- 代码 Agent 弹窗新增「一键撤销」，调用 `rollback_all()`；
- 电脑 Agent 弹窗新增「一键撤销」，调用 `rollback_run()`；
- 统一 Agent 旅程窗口也有「一键撤销」；
- 电脑文件操作记录备份：write/edit/delete/copy/move；
- 支持动作自带 `rollback` 的 hotkey/press_key 回退。

### 3.8 入口割裂

- 新增统一 Agent 旅程窗口，一个输入框自动路由；
- 普通聊天输入明确代码/电脑任务时，会提示进入 Agent 旅程；
- 命令面板和更多菜单增加「Agent 旅程」入口；
- 高级模式仍保留代码 Agent / 电脑 Agent 独立入口。

### 3.9 过程不透明

- 新增统一 `AgentTimeline`：
  - 状态；
  - 百分比；
  - 步骤列表；
  - 工具结果；
  - 验证原因；
  - 失败原因；
  - 截图预览；
- RunRegistry 每个步骤更新 current_step / progress；
- Agent 事件同时写入 `data/agent_runs/*/events.jsonl`。

### 3.10 审批模型不统一

- 新增 `core/agent_permissions.py`；
- 代码 Agent 和电脑 Agent 都调用同一入口；
- 支持 once / session / always；
- 上层已有 diff 审批时使用 `already_approved=True`，避免重复确认；
- 所有允许/拒绝结果写入审计日志。

### 3.11 浏览器仍像普通窗口

- Browser 增加：
  - `current_info()`；
  - `get_dom()`；
  - `exists()`；
  - `wait_for_selector()`；
  - `press()`；
  - `upload_file()`；
- Action schema 增加 browser_* 动作；
- 电脑 Agent 规划器要求浏览器任务优先 selector，像素点击作为兜底。

### 3.12 验证器不可靠

- 实现 `text_changed`；
- 实现 `element_value`；
- 实现 `url_contains`；
- 实现 `file_contains`；
- screenshot_diff 改为 PIL 像素差异比例 + 阈值；
- control_visible 修复误判；
- 验证支持短轮询等待，而不是执行后立刻判断。

### 3.13 多显示器 / 高 DPI

- `computer_controller` 新增 `screen_info()`；
- 使用 Win32 虚拟桌面 metrics 计算多显示器坐标；
- 截图使用 `all_screens=True`；
- 鼠标坐标按虚拟桌面边界 clamp；
- 截图标注时按虚拟桌面 left/top 换算。

### 3.14 代码 Agent 项目理解浅

- 上下文从最近文件 + 首段文本升级为：
  - 关键词命中；
  - AST 符号；
  - import / 测试关联；
  - 当前打开文件；
  - 最近修改文件；
  - 命中行附近代码片段；
  - 用户选中文本；
  - 文件符号大纲；
- 总上下文预算仍是可控的，避免一次性塞爆模型。

### 3.15 一次性 patch，不是探索 Agent

- 模型可返回探索工具调用：
  - read_file；
  - grep；
  - list_files；
  - find_symbols；
  - run_command；
- 工具结果回填给模型，再进行下一轮；
- 达到最大探索轮数后明确失败，不无限循环。

### 3.16 测试/lint/工程环境

- 自动探测 pytest / npm / cargo / go；
- lint 探测 ruff / npm lint / cargo clippy / gofmt；
- 测试和 lint 均走统一命令执行器；
- 支持超时、取消、输出上限、退出码。

### 3.17 安装与首次体验

本轮优先修复进入 Agent 后能不能看懂、停下、撤销的核心体验。安装包体积与浏览器内核仍采用延迟下载策略，不在本轮强行移除 PyQt5 或 Chromium；它们属于分发优化，不阻塞 Agent 闭环。

---

## 3.18 按钮预算说明

本轮新增的暂停、继续、取消、人工接管、一键撤销、审批入口，属于
执行中必须立即触达的安全控制，不能只用一句自然语言替代：
用户需要在不打断 Agent 的情况下立刻停止或接管。因此按钮预算按
安全控制需求上调，并在 `tools/button_budget.json` 中记录新基线。

## 4. 用户旅程验收

### 代码任务

1. 输入修复 xxx 并补测试；
2. 自动路由到代码 Agent；
3. 收集项目上下文；
4. 模型可先 grep/read_file 再生成 patch；
5. 显示 diff，可按文件/hunk 批准；
6. 应用修改；
7. 自动运行测试与 lint；
8. 失败自动带失败输出进行下一轮；
9. 用户可暂停、取消；
10. 完成后可一键撤销。

### 电脑任务

1. 输入打开浏览器搜索天气并保存到记事本；
2. 自动路由到电脑 Agent；
3. 每一步观察屏幕；
4. 绑定 UIA element_id / OCR rect / browser selector；
5. 动作审批；
6. 执行并验证；
7. 失败重新观察并重新规划；
8. 全过程有时间线、截图和目标框；
9. 用户可暂停、人工接管、取消；
10. 文件改动可一键撤销。

---

## 5. 验证命令

```powershell
py -3 -m pytest -q
py -3 tools/run_eval.py
```

本机结果：

- 全量 pytest：1026 passed / 2 skipped；
- 新增 Agent 闭环测试：10 passed；
- Agent 相关专项：19 passed。

## 6. 后续建议

1. 增加真实 E2E 任务集，而不是只依赖单元测试；
2. 对 grounding 增加坐标标定与点击命中率统计；
3. 将浏览器 DOM 与 UIA 的候选统一成同一套 Accessibility 树；
4. 将代码 Agent 接入编辑器当前文件/选区/诊断；
5. 做安装包的最小运行版 / 完整版双分发，降低首次下载成本。


---

## 闭环的 UI 承载（2026-10-22）

Agent 闭环（计划 → 执行 → 审批 → 回滚）现在有统一的可视化承载：

```text
gui/workbench_dialog.AgentDock
  ├─ goal        目标输入
  ├─ start/pause/cancel   执行控制
  ├─ timeline    实时步骤（事件流）
  └─ _approve()  diff / 电脑动作审批（DiffReviewDialog）
```

底层仍是 `core/agent_orchestrator.AgentOrchestrator`：

```text
route(goal) → code / computer / chat
  code     → CodeAgent（patch 审批）
  computer → ComputerAgent（动作审批）
```

### 关键约束

| 约束 | 原因 |
|---|---|
| 审批回调 fail-closed | diff 打不开时必须拒绝，不能默认放行 |
| 不阻塞 UI 线程 | 事件通过 `event_cb` 回主线程追加到 timeline |
| 暂停 / 取消 可随时触发 | 长任务必须能立刻停手 |

### 测试

```powershell
py -3 -m pytest tests/test_workbench.py -q    # 26 passed
```

覆盖：正常完成、失败结果、异常、暂停/继续、取消、文件上下文传递。
