# 贡献指南

## 新模块开发规范
1. 在 `modules/installed/` 下新建 `your_module.py`
2. 类签名必须是 `def __init__(self, trunk=None)`，并实现 `run()` 作为统一入口
3. **必须在 `core/lazy_config.py` 的 `LAZY_MAP` 里登记一行** ——
   它是**手写表**，不会自动扫描（早期文档写的"自动注册"是错的）
4. 改了 `modules/installed/` 之后必须走重签四步：
   `rebuild_modules_repo.py --apply` → `sign_modules.py` → `check_repo_sync.py`
   → `check_plugin_api.py`
5. 第三方插件必须声明清单 `api_version: "1.0"`，只能 import
   `core/plugin_api.py` 的 `PUBLIC_CORE_MODULES`；禁止依赖
   `core.trunk`、`core.data_schema`、`core.secret_store` 等私有实现，
   安装前会被静态检查拒绝。

## 代码规范
- 文件名小写下划线，类名大驼峰
- 不要硬编码绝对路径，统一用 `trunk.base`
- 不要吞异常，except 里至少写一行日志（`check_silent` 会数）
- 模块之间不要互相 import，全部走 `trunk.call()`

## 虚拟环境与打包

```powershell
# 三套环境一次建好
powershell -ExecutionPolicy Bypass -File scripts\setup_all_envs.ps1

# 只建开发环境 / 干净运行环境 / 打包环境
scripts\setup_dev_env.ps1
scripts\setup_runtime_env.ps1 -WithOptional
scripts\setup_build_env.ps1

# 检查
scripts\check_envs.ps1
```

- `.venv`：pytest / ruff / mypy / coverage
- `.runtime-venv`：只装核心运行依赖，可选依赖按需 `-WithOptional`
- `.build-venv`：核心依赖 + PyInstaller，不混入开发包
- 不要用系统 Python 直接做 PyInstaller 打包。

## 命令执行安全

所有命令入口必须经过 `core/command_policy.py`：

- 禁止引号外的 `& | > < ;` 等 shell 元字符；
- 首命令必须在白名单内；
- 参数优先用 argv 数组，`shell=False`；
- 应用启动先过白名单和真实路径校验；
- 关机/重启使用固定 argv；
- 沙箱字符串命令必须由代码 Agent 先经过 PermissionCenter 和用户确认；
- 审计记录命令摘要和哈希，不记录可能的密钥全文。

## 兼容性与数据迁移
- 支持 Windows 10/11 + Python 3.10/3.11/3.12；CI 矩阵见 `.github/workflows/compat-matrix.yml`。
- 新增/修改 WATCHED 数据文件时，必须在 `core/data_migrations.py` 增加逐级迁移函数，
  并补 `tests/test_data_migrations.py`；迁移前自动备份，坏行保留 `.bad_lines`。
- 兼容性细节和验收命令见 `docs/70_兼容性与数据迁移.md`。

## 改完自检
双击 `check.bat`（14 步：语法 / 测试 / 密钥 / 版本 / 预算 / 线程 / 插件仓 / 懒加载 / 静态检查 / Agent E2E / 文件长度 / 插件 API / 兼容性 / 数据迁移），
或单独跑 `py -3 -m pytest tests/ -q`。

## 禁止做的事
- 不要改 `LAZY_MAP` 里**已有**的键名（老配置会不兼容）
- 不要直接写 `data/` 下的数据库，用 `chat_store` / `vector_store` 接口
- 不要把 API Key 硬编码进代码；配置里敏感字段会自动 DPAPI 加密

## 2026-10-19 UI / 稳定性同步

- 已同步简单/高级模式、头像五项菜单、高级模式更多菜单、任务中心、左栏滚动与模块数量提示。
- 已同步自动补报误报修复和日志摘要最近启动过滤。
- 当前验证（2026-10-23）：1687 passed，2 skipped；按钮预算 184；质量门禁 81 warn / 0 error。

## 2026-10-20 兼容性与插件 API 同步

- 新增 Windows 2022/latest  Python 3.10/3.11/3.12 兼容矩阵。
- 数据迁移改为 v0v1v2 逐级执行，先备份、坏行保留、失败不覆盖。
- 插件清单新增 `api_version: "1.0"` 和 `first_party`，安装前检查 core 依赖边界。



## 启动相关改动的约定（2026-10-21）

1. `gui/app_pyqt.py` 的 `on_finished` 里**不允许**调用 `setCentralWidget`
   —— 会清空 `build_ui()` 装好的主界面（曾导致整屏白）。
2. 任何 `QFontDatabase` 访问前先判断 `QGuiApplication.instance()`。
3. 启动路径改动请同时跑：
   ```powershell
   py -3 -m pytest tests/test_boot_controller.py tests/test_font_and_dialogs.py tests/test_startup_speed.py -q
   ```
4. 提交前跑 `py -3 tools/sync_package.py`，保证打包源与开发目录一致。


---

## 新增门禁与约定（2026-10-22）

### 提交前必跑

```powershell
.venv\Scripts\python.exe -m ruff check core gui modules/installed
.venv\Scripts\python.exe tools/check_silent.py        # 静默异常棘轮
.venv\Scripts\python.exe tools/check_threads.py       # 子线程不得碰控件
.venv\Scripts\python.exe tools/check_file_sizes.py    # 单文件 <= 600 行
.venv\Scripts\python.exe tools/check_buttons.py       # 按钮预算 184
.venv\Scripts\python.exe tools/check_shapes.py        # 结构漂移
.venv\Scripts\python.exe -m pytest tests/ -q
```

### 三条容易被忽略的规则

**1. 子线程不能碰 Qt 控件**

```python
# 错误：崩溃或渲染错乱
threading.Thread(target=lambda: label.setText("x")).start()

# 正确：发信号回主线程
self.someSignal.emit("x")
```

**2. `threading.Timer` 必须设 daemon**

```python
timer = threading.Timer(1.0, fn)
timer.daemon = True        # 否则进程退出会挂住
timer.start()
```

**3. 弹窗不要放在可测逻辑里**

```python
# 错误：offscreen 测试会阻塞/崩溃
def start(self):
    if not goal:
        QMessageBox.information(...)   # 阻塞
        return

# 正确：校验与弹窗分离
def can_start(self) -> bool:
    return bool(self.goal)

def start(self):
    if not self.can_start():
        self.timeline.appendPlainText("请先描述要做什么")
        return
```

### 开窗必须走单例

```python
def mcp_dialog(self):
    return self._singleton_dialog("mcp_dialog", "gui.mcp_dialog", "MCPDialog")
```

否则连点按钮会开出多个窗口（实测 3 次 → 3 个窗口）。
