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
- 当前验证（2026-10-20 第二阶段后）：1292 passed，2 skipped；总覆盖率约 60.36%。

## 2026-10-20 兼容性与插件 API 同步

- 新增 Windows 2022/latest  Python 3.10/3.11/3.12 兼容矩阵。
- 数据迁移改为 v0v1v2 逐级执行，先备份、坏行保留、失败不覆盖。
- 插件清单新增 `api_version: "1.0"` 和 `first_party`，安装前检查 core 依赖边界。

