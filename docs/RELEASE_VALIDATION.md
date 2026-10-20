# 发布验证手册

## 1. 干净 Windows 10/11

在 Windows 10 22H2 和 Windows 11 当前版本 VM 上使用**非管理员测试账号**：

- 安装到含中文和空格的路径。
- 安装、首次启动、创建账号、配置模型、发送首条消息。
- 从上一发布版本升级，确认数据迁移、备份和回滚。
- 卸载，确认用户数据保留/删除策略符合隐私政策。
- 检查 UAC、防火墙提示、崩溃转储路径、日志目录权限。

## 2. 真实模型 E2E

- 启动真实 Ollama，拉取固定测试模型。
- 验证本地模型聊天、流式输出、模型切换、断线重连、错误提示。
- 云端模型使用独立测试账号和消费上限，验证超时、鉴权失败、限流。
- 日志中不得出现 API Key、Authorization、Cookie 或完整 webhook URL。

## 3. 8 小时长稳

记录并比较：

- RSS 内存峰值和增长趋势。
- 线程数、句柄数、子进程数。
- 工具调用错误率、MCP 重连次数。
- 审计记录数量与磁盘增长。
- 失败时保存诊断包并脱敏。

## 4. 产物与签名

- 只构建一次，上传 immutable artifact。
- 记录 `artifact-manifest.json` 和每个文件 SHA256。
- 使用 `tools/sign_artifact.ps1` 对最终构建产物签名。
- `tools/verify_artifact_manifest.py` 验证签名后产物。
- 对签名后的同一 hash 做启动冒烟、安装、E2E、长稳。
- 保存 Authenticode 验证输出、SBOM、license-report、pip-audit 报告。

## 5. 证据清单

发布记录至少包含：

- GitHub Actions run URL、commit SHA、required checks 结果。
- Windows build / portable artifact 名称和 hash。
- 干净 VM 安装、升级、卸载日志。
- 真实 Ollama/云端模型 E2E 日志。
- 8 小时长稳报告。
- Bandit triage、pip-audit、SBOM、license 报告。
- Authenticode 签名验证截图或命令输出。
