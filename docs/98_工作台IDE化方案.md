# 工作台 IDE 化方案（VS Code 风格）

> 目标：把当前「VS Code 骨架」补齐到可用的 IDE 工作台，同时守住项目约束：
> 按钮总数不超过 60、单文件不超过 600 行、不为了像 VS Code 而堆假按钮。

> **落地状态（批次 29）**：P0 / P1 / P2 已全部实施，验证记录见
> `docs/20` 批次 29。实施中的三处偏差已回写到本文：
> ① Git 标记用 `ForegroundRole` 给文件名上色（不改图标）；
> ② 右键菜单用 `QMenu.addAction`（`addAction` 不是 `QAction(...)` 创建点，
>   按钮守卫统计的是后者）；
> ③ AI 会话持久化复用已有的 `data/code_jobs/queue.json`，不另建
>   `ai_sessions.json`，避免两份历史。

## 1. 现状与差距

已具备：活动栏、资源管理器、编辑器标签/工具条、面包屑、底部输出、右侧 AI、
状态栏文件/编码/行列。

| 差距 | 影响 | 处理批次 |
|---|---|---|
| 活动栏只有 3 个入口，emoji 图标不统一 | 找不到搜索/Git/扩展 | P0 |
| 没有顶部命令中心 | 高频动作只能找鼠标 | P0 |
| 状态栏缺分支/错误数/语言模式 | 不像 IDE 状态栏 | P0 |
| 右侧 AI 没有历史列表 | 只能看当前时间线 | P0 |
| 左侧没有搜索/Git 视图 | 搜索与提交前检查要另开窗口 | P0 |
| 面包屑在标签上方 | 与 VS Code 顺序相反 | P1 |
| 没有编辑器分屏/minimap | 大文件/对照编辑不便 | P1 |
| 输出只有一块黑框，没有「问题/终端」页签 | 无法在 IDE 内跑命令/看诊断 | P1 |
| 文件树没有 Git 状态标记/右键新建重命名 | 资源管理器不完整 | P2 |
| AI 历史不持久化、不是标准 Secondary Side Bar | 重启后丢会话 | P2 |

## 2. P0：侧栏与命令入口（本批完成）

### 2.1 活动栏

- 六个入口，全部真实动作：
  1. `explorer` 资源管理器：切换到文件树
  2. `search` 搜索：切换到工作区内容搜索视图
  3. `scm` 源代码管理：切换到 Git 改动视图
  4. `run` 运行：运行当前文件
  5. `extensions` 扩展：打开插件市场
  6. `ai` AI：展开并聚焦右侧 AI 面板
- 图标改为 `QPainter` 画的单色线性图标（灰/选中蓝），不再用 emoji。
- 活动栏仍是 `QListWidget`，不新增按钮创建点。

### 2.2 左侧视图栈

- 在现有资源管理器位置插入 `QStackedWidget`：
  - 页 0：原资源管理器（不动文件树和顶部文件图标）
  - 页 1：搜索视图（输入框 + 结果列表，Enter 搜索、双击跳行）
  - 页 2：源代码管理（分支 + `git status --porcelain` 改动列表、双击打开）
- 搜索优先用 `rg`，没有则用 Python 遍历文本文件；最多 100 条，忽略
  `.git/node_modules/.venv/modules_repo` 等目录。
- 视图文件独立到 `gui/ide_sidebar.py`，避免 `workbench_dialog.py` 超 600 行。
- 挂载顺序有坑：`QSplitter.replaceWidget(0, host)` 会让被替换的旧控件停在
  “显式隐藏”状态，即使再 `insertWidget` 收进栈也不显示，侧栏被压成 0 宽。
  正确顺序是「先把资源管理器 `insertWidget(0, ...)` 收养进栈 → 再
  `splitter.insertWidget(0, host)` → 最后显式 `show()`」，并给 host
  `setMinimumWidth(200)`、`splitter.setStretchFactor(0, 0)`；
  `test_workbench.test_sidebar_not_collapsed` 守住这条回归。

### 2.3 顶部命令中心

- 顶栏中间加 `QLineEdit`（不是按钮），支持：
  - 命令：新建文件、打开文件、保存、另存为、运行、搜索、源代码管理、
    资源管理器、输出、插件市场、AI 面板、全屏
  - 非命令文本：按文件名在工作区找第一个匹配并打开
- `Ctrl+Shift+P` 聚焦命令中心；`QCompleter` 提示命令名。
- 不做传统 `QMenuBar`：菜单项是 `QAction`，会直接突破 60 按钮预算；
  命令中心先覆盖高频动作，P2 再评估用非 QAction 的菜单实现。

### 2.4 状态栏

- 增加：Git 分支、错误数（当前文件语法错误）、语言模式。
- 顺序：`就绪/消息`（左）｜`⎇ 分支` · `行 x, 列 y` · `⚠ n` ·
  `语言` · `相对路径 · UTF-8 · LF`（右）。
- 语法错误由 `CodeEditWidget` 的 `ast.parse` 结果发信号；非 `.py` 文件不误报。

### 2.5 AI 历史

- 现有任务队列列表改成「会话历史（最近 20 条，双击载入/续跑）」，
  高度从 64 调到 100；双击行为复用 `_resume_item`。
- 本批只做内存历史，重启持久化放 P2。

## 3. P1：编辑器骨架

1. **面包屑顺序**：用 `QTabBar + QStackedWidget` 替换 `QTabWidget`，
   布局改成「标签栏 → 面包屑 → 编辑区」；保留现有对外 API
   （`addTab/removeTab/widget/count/currentWidget/...`）避免大改调用方。
2. **编辑器分屏**：同屏两个 `CodeEditWidget`，共享当前文件；`Ctrl+\` 分屏，
   关闭分屏回到单栏。不做任意多组分屏，控制复杂度。
3. **minimap**：在编辑器右侧画文档缩略图，点击/拖动定位；先只支持当前文件，
   不做语法着色，避免性能问题。
4. **底部面板页签**：`输出 / 问题 / 终端`：
   - 输出：现有 `self.output`
   - 问题：收集语法错误，双击跳行
   - 终端：`QProcess` 跑一次性命令，支持 `cd` 与清屏，不做完整 PTY
5. 验收：`test_workbench` 覆盖标签顺序、分屏开关、minimap 尺寸、三个页签。

## 4. P2：资源管理器与 AI 会话

1. 文件树 Git 状态标记：`git status --porcelain` 映射成文件名颜色
   （`ForegroundRole`，M 琥珀 / A 绿 / D 红 / ? 灰 / R 紫），
   不改图标、不改排序、不改根目录逻辑。实现：`gui/ide_explorer.GitFileModel`。
   必须带 `-c core.quotePath=false`：否则中文路径被转义成
   `"docs/\344\270\255..."`，既对不上文件树路径（不着色），SCM 列表也会乱码。
2. 右键菜单：新建文件/文件夹、重命名、删除、在资源管理器中显示。
   用 `QMenu.addAction` 注册（不新建 QAction 实例，按钮预算不变）。
   实现：`gui/ide_explorer.ExplorerMenuMixin`。
3. AI 会话持久化：复用现有 `data/code_jobs/queue.json`（原子写入、最多 100 条），
   面板里的「会话历史」就是它的最近 20 条视图，双击载入/从断点续跑。
4. 标准 Secondary Side Bar：AI 面板装进 `QDockWidget`（右侧默认停靠，
   `DockWidgetMovable | Floatable | Closable`），「⛶ 弹出」= `setFloating(True)`；
   不再用 splitter 第三栏 + 占位控件模拟。

## 5. 验收与约束

- 每批都必须通过：`test_workbench`、`test_gui_smoke`、`check_buttons`
  （60/60）、`check_shapes`、`py_compile`。
- 搜索/SCM 面板不创建按钮；只用 `QLineEdit/QListWidget/QLabel` 链接。
- 新增 `gui/ide_sidebar.py` 后，功能冻结基线需要 `--force` 重锁一次
  `gui_files`，按钮总数仍为 60；在 `docs/20` 记录原因。
- 不改 `QFileSystemModel` 的文件树根目录逻辑；搜索/SCM 只读，不写文件。
- P0 完成后，工作台应能完成「搜索 → 打开 → 修改 → 运行 → 看 Git 改动」
  全流程，不需要离开工作台。
