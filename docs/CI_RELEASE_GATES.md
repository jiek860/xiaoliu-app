# CI / 发布门禁

## 必需检查（Branch protection required checks）

在 GitHub 仓库设置中把以下检查设为 required status checks，并启用：

- Require a pull request before merging
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Do not allow bypassing the above settings

稳定检查名：

| Check | Workflow | 说明 |
|---|---|---|
| `static` | `.github/workflows/test.yml` | Ruff、Mypy、文件长度、workflow 供应链策略 |
| `test` | `.github/workflows/test.yml` | 全量测试、覆盖率、E2E、守卡 |
| `ci-required` | `.github/workflows/test.yml` | static + test 汇总 |
| `compat-required` | `.github/workflows/compat-matrix.yml` | Windows / Python 3.10-3.12 矩阵 |
| `windows-build-required` | `.github/workflows/build-windows.yml` | PyInstaller 构建、产物 hash 清单 |
| `portable-required` | `.github/workflows/build-portable.yml` | Windows/Linux/macOS 便携包 |
| `security-required` | `.github/workflows/security.yml` | secret scan、Bandit triage、pip-audit、license、SBOM（Dependabot + pip-audit 作为依赖审查门禁） |
| `codeql-analyze` | `.github/workflows/codeql.yml` | CodeQL 静态分析 |

如果矩阵检查需要单独配置，也可同时要求：

- `windows-2022 / Python 3.10`
- `windows-2022 / Python 3.11`
- `windows-2022 / Python 3.12`
- `windows-latest / Python 3.10`
- `windows-latest / Python 3.11`
- `windows-latest / Python 3.12`

## 配置命令

先在本地安装并登录 GitHub CLI：

```powershell
gh auth login
```

然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/configure_branch_protection.ps1
```

脚本使用 GitHub REST API 设置 required checks。仓库管理员权限是必需的。

## 发布证据要求

每次 release candidate 必须保留：

- 三个核心 workflow 的 run URL、commit SHA、结果；
- required checks 截图或 API 结果；
- `xiao6-windows-build` artifact 的 `artifact-manifest.json`；
- 最终签名产物的 SHA256、Authenticode 签名结果；
- 覆盖率报告、Bandit 报告、pip-audit 报告、CycloneDX SBOM；
- 干净 Windows 10/11 VM 的安装、升级、启动、卸载记录；
- 真实 Ollama + 云端模型 E2E 日志（密钥必须脱敏）；
- 8 小时长稳报告（内存、线程、句柄、子进程、错误率）。

## 产物原则

1. 只构建一次。
2. 构建产物上传为 immutable artifact。
3. 下载 artifact 后签名。
4. 对签名后的同一 hash 做安装、启动冒烟、E2E。
5. 发布该签名产物，不重新构建。

任何无法提供证据的门禁，一律视为 red。
