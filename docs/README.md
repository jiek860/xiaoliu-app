# docs 文档索引

更新日期：2026-10-23（全程序检测、按钮验收与提交前复核同步）
适用版本：v25.2.23

## 一、主文档（优先阅读）

| 文档 | 用途 | 维护要求 |
|---|---|---|
| `00_产品架构与UI主文档.md` | 当前架构、功能全貌、UI 简单/高级模式、任务入口 | 架构或 UI 行为变化时更新 |
| `10_开发流程与工程手册.md` | 开发流程、目录结构、发版检查、工程风险和处置 | 开发流程/打包/风险变化时更新 |
| `20_优化路线与实施记录.md` | 四阶段路线、深化方向、已落地实施记录、性能可靠性变更 | 阶段方案或实施结果变化时更新 |
| `30_模块规则与API参考.md` | 模块/规则/能力全景与开发者 API 参考 | API、能力或规则变化时更新；文档一致性测试会检查能力数 |
| `40_安全加固与权限说明.md` | 安全修复清单与边界说明 | 安全相关改动后更新 |
| `50_产品体验与Agent能力提升方案.md` | 使用体验、代码 Agent、电脑操作 Harness、路线图和验收指标 | 方案调整或阶段完成后更新 |
| `70_兼容性与数据迁移.md` | Windows/Python 兼容矩阵、v0→v1→v2 数据迁移、插件 API v1.0 边界与验收命令 | 兼容性、数据版本或插件 API 变化时更新 |
| `80_程序质量检测报告_2026-10-20.md` | 全量检测结果、覆盖率、安全扫描、打包实测、问题优先级与发布结论 | 每次发布前复核 |
| `81_全程序检测与UI按钮验收报告_2026-10-22.md` | 本轮全程序/模块链接/按钮文字与接线/文档同步/打包源验收结果 | 每次全量验收后更新 |
| `92_开源对标更新版_2026-10-23.md` | 第二阶段能力与开源 Agent 的对比、差距和后续方向 | 对标结论变化时更新 |
| `PRODUCT_PHASE2.md` | 第二阶段模型/RAG/GUI Agent/插件/团队能力、状态、验收命令 | 能力或状态变化时更新 |
| `PLUGIN_SDK.md` | 隔离插件 SDK、能力声明、信任等级、版本兼容和发布流程 | 插件 API 或安全边界变化时更新 |
| `PLUGIN_STANDARD.md` | **插件标准 v2.1**（分级/审计/熔断/密钥校验，含模块级标准对照与质量门禁） | 插件标准变化时更新 |
| `MODULE_STANDARD.md` | 《模块级程序标准 v1.0》原文（外部通用标准对照基线） | 外部标准更新时同步 |
| `SECURITY_ARCHITECTURE.md` | 权限、网络、沙箱、MCP、插件、Prompt 注入防线 | 安全边界变化时更新 |
| `CI_RELEASE_GATES.md` | CI 必需检查、分支保护、发布门禁 | workflow/门禁变化时更新 |
| `RELEASE_VALIDATION.md` | 发布验收清单和证据记录 | 发版流程变化时更新 |
| `examples/plugins/` | 隔离插件 SDK 示例 | 插件 SDK 变化时更新 |

## 二、运行时文件

| 文档 | 用途 | 维护要求 |
|---|---|---|
| `用户协议.txt` | 运行时协议弹窗读取；根目录还有一份打包回退副本 | 改动需同步根目录并升级 `core/agreement.py` 版本 |
| `隐私政策.txt` | 运行时隐私政策弹窗读取；根目录还有一份打包回退副本 | 改动需同步根目录并升级 `core/agreement.py` 版本 |
| `模块星图.html` | GUI「模块星图」直接打开的页面，运行时读取 `data/modules_map.js` | 不要删；页面结构变化需同步 `core/module_map.py` |
| `使用说明-小白版.txt` | 唯一完整用户手册 | 用户可见功能变化时更新；旧短版已删除 |

## 三、已删除的历史文档

以下文档属于历史方案、阶段性报告或已被现行文档替代，已删除：

- `升级报告_20260923.md`
- `电脑操控补全方案.md`
- `能力架构最优方案.md`
- `规则对比与优化清单.md`
- `自主规则_未启用.md`
- `可落地优化方案.md`
- `安全加固方案.md`
- `小6程序架构全景图.html`
- `API.md`（内容已合并到 `30_模块规则与API参考.md`）
- 根目录 `使用说明.txt`（内容已合并到 `使用说明-小白版.txt`，旧短版已删除）
- `全模块规则体系.md`（内容已合并到 `30_模块规则与API参考.md`）
- `安全加固实施记录.md`（内容已合并到 `40_安全加固与权限说明.md`）
- `UI简化与导航方案.md`（内容已合并到 `00_产品架构与UI主文档.md`）
- `开发流程与目录结构梳理.md`（内容已合并到 `10_开发流程与工程手册.md`）
- `四阶段可落地优化方案.md`（内容已合并到 `20_优化路线与实施记录.md`）
- `四阶段实施记录.md`（内容已合并到 `20_优化路线与实施记录.md`）
- `现有功能深化优化方案.md`（内容已合并到 `20_优化路线与实施记录.md`）
- `深度优化记录.md`（内容已合并到 `20_优化路线与实施记录.md`）
- 根目录 `小6智能体最新架构与功能说明.txt`（内容已合并到 `00_产品架构与UI主文档.md`）
- 根目录 `小6工程化落地-执行手册.txt`（内容已合并到 `10_开发流程与工程手册.md`）
- 根目录 `小6工程化风险解决方案.txt`（内容已合并到 `10_开发流程与工程手册.md`）

## 四、维护规则

1. 运行时必须读取的文件不能删：
   - `docs/用户协议.txt`
   - `docs/隐私政策.txt`
   - `docs/模块星图.html`
2. 修改协议文本必须同步：
   - 根目录 `用户协议.txt` / `隐私政策.txt`
   - `core/agreement.py` 里的版本号
3. 新增核心模块或架构变化时同步：
   - `ARCHITECTURE.md`
   - `docs/00_产品架构与UI主文档.md`
   - `docs/30_模块规则与API参考.md`
4. 新增能力或规则时同步：
   - `docs/30_模块规则与API参考.md`
   - `tests/test_docs_consistency.py` 会检查能力数
5. 兼容性/数据/插件 API 变化时同步：
   - `docs/70_兼容性与数据迁移.md`
   - `使用说明-小白版.txt`
   - `gui/tutorial_dialog.py` / `gui/onboarding_wizard.py`
6. 启动/界面相关改动后追加：
   ```powershell
   py -3 -m pytest tests/test_boot_controller.py tests/test_font_and_dialogs.py tests/test_startup_speed.py -q
   ```
7. 发布前运行：
   ```powershell
   py -3 -m pytest tests/test_docs_consistency.py tests/test_user_docs_intact.py -q
   py -3 tools/check_version.py
   py -3 tools/check_plugin_repo.py
   py -3 tools/check_plugin_api.py
   py -3 tools/check_diff_coverage.py --coverage coverage.json --base origin/main
   py -3 tools/sync_package.py --dry-run
   py -3 tools/sync_package.py
   ```
8. 文档/教程同步范围：
   - 根目录 `README.md` / `README_EN.md` / `ARCHITECTURE.md` / `CHANGELOG.md`
   - 用户文档 `使用说明-小白版.txt` / `FAQ.txt` / `模型教程.txt` /
     `检测手册.txt` / `部署步骤.md` / `开发者须知-密钥与发版.md`
   - 程序内教程 `gui/tutorial_dialog.py` / `gui/onboarding_wizard.py`
   - `docs/00/10/20/30/50/70/80` 与 `docs/PRODUCT_PHASE2.md` / `docs/PLUGIN_SDK.md`
   - 打包源由 `tools/sync_package.py` 同步到 `E:\xiao6-package`


## 五、Agent 闭环方案

- `60_Agent闭环落地方案.md`：统一 Agent 路由、实时时间线、暂停/取消/人工接管、动态重规划、patch 全操作、一键回滚、权限与审计、验收记录。

- `61_18项质量硬化记录.md`：安全、沙箱、线程、资源清理、增量索引、E2E 和静态检查的 18 项硬化记录。

- `62_trunk门面拆分与行数锁定.md`：Trunk 拆分结果、公共 API 兼容和 220 行预算锁定。

- `63_11个存量超标文件拆分完成.md`：11 个 600+ 行文件的拆分结果和兼容性记录。

---

## 2026-10-22 新增文档条目

| 主题 | 位置 | 说明 |
|---|---|---|
| 工作台（三窗口融合） | `00_产品架构与UI主文档.md` 末尾 | 布局、入口兼容、按钮精简记录 |
| 启动期确认门禁 | `10_开发流程与工程手册.md` 末尾 | 新增功能如何登记确认项 |
| 新增模块 API | `30_模块规则与API参考.md` 末尾 | startup_consent / mcp_trust / auth / workbench |
| 信任模型 | `40_安全加固与权限说明.md` 末尾 | 三层分离、恢复登录校验、哈希信任 |
| 新增数据文件 | `70_兼容性与数据迁移.md` 末尾 | 三个新 JSON 的作用与损坏容错 |
| 全程序检测与按钮验收 | `81_全程序检测与UI按钮验收报告_2026-10-22.md` | 1687 passed / 2 skipped；184 按钮预算；48 插件验签；质量门禁 81 warn / 0 error |
