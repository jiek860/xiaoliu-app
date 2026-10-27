# SWE-bench Verified 判分环境准备（v25.2.33）

更新日期：2026-10-27
目标：让 `swebench.harness.run_evaluation` 能真正跑出官方 resolve@1。
结论先说：**Python 侧已经齐了**，剩下三件事——一次管理员提权、配国内镜像加速、
把镜像数据放到 E 盘。三者缺一，装了 Docker 也跑不出分。

## 一、现状（2026-10-27 实测）

| 项目 | 状态 | 证据 / 位置 |
|---|---|---|
| Python | ✅ 3.12.10 | `.swebench-venv\Scripts\python.exe` |
| git | ✅ 2.47.0 | `E:\Git\cmd\git.exe` |
| `swebench` 包 | ✅ 5.0.2 | 独立虚拟环境 `e:\xiaoliu\.swebench-venv`（不污染主环境） |
| 官方 harness CLI | ✅ 可调 | `--help` 列出 `--modal` 等全部参数 |
| `docker` / `modal` Python 包 | ✅ 7.2.0 / 1.6.2 | 判分用 `docker`，云端路线用 `modal` |
| 数据集缓存 | ✅ 500 题 | HF 缓存已有 `datasets--SWE-bench--SWE-bench_Verified` |
| 本地 jsonl | ✅ | `data/swebench/swebench_verified.jsonl` |
| 环境自检 | ⚠️ 只红 Docker | `tools\swebench_verified.py --check` 现覆盖 Docker daemon、镜像加速、磁盘 |
| Docker | ❌ 未安装 | 无 `docker` 命令；`C:\Program Files\Docker` 不存在 |
| WSL2 | ❌ 未安装 | `wsl --status` 提示可运行 `wsl --install` |
| 虚拟化 | ✅ 已开启 | `HyperVisorPresent=True`（可用 Hyper-V 后端） |
| 管理员权限 | ❌ 当前会话未提权 | `IsInRole(Administrator)=False`，但 `whoami /groups` 显示 `BUILTIN\Administrators` 为 `Group used for deny only` → **账号本身在管理员组，弹一次 UAC 即可** |
| Docker Hub 直连 | ❌ 不通 | `registry-1.docker.io`、`auth.docker.io` 的 443 均失败 |
| 国内加速器 | ✅ 4 个可用 | `docker.1ms.run`、`hub.rat.dev`、`docker.xuanyuan.me`、`docker.nju.edu.cn`（`/v2/` 返回 401/403 = 注册表活着）；`dockerproxy.com`、`docker.mirrors.ustc.edu.cn`、`hub-mirror.c.163.com`、`swr.cn-north-1.myhuaweicloud.com` 均不通 |
| 磁盘 | ⚠️ C 盘吃紧 | C 剩 10.0 GB / E 剩 63.8 GB → Docker Desktop 本体装 C，镜像数据必须指到 E |

> 关键结论：这台机器的 Docker Hub 是完全不通的。以前只写"装 Docker"是不够的，
> **不配 `registry-mirrors` 就拉不到 `python:3.11` 这类基础镜像**，harness 会在
> 构建阶段就失败。

## 二、为什么用独立 venv

`swebench` 会带进 `datasets`、`docker`、`modal` 等一串依赖，主环境里
`datasets` 已经是 5.0.1（产品自己的 RAG/评测也在用）。直接全局装可能把它们
升级到不兼容版本，把产品测试弄红。所以：

```
e:\xiaoliu\.swebench-venv\          ← 只给评测用
e:\xiaoliu\                        ← 产品环境保持不变
```

## 三、装环境（只需提权一次）

### 3.0 一键脚本：`tools\setup_swebench_docker.ps1`

脚本只做需要管理员的三件事，**不重启、不自动跑评测**：

1. `dism` 打开 `Microsoft-Windows-Subsystem-Linux` + `VirtualMachinePlatform`
2. `winget install -e --id Docker.DockerDesktop`
3. 把 4 个可用加速器写进 `C:\ProgramData\Docker\config\daemon.json`

运行方式（未提权时会自动弹 UAC 重新拉起自己）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File e:\xiaoliu\tools\setup_swebench_docker.ps1
```

可选参数：

| 参数 | 用途 |
|---|---|
| `-SkipWsl` | WSL/虚拟机平台已开过，跳过 DISM |
| `-SkipDocker` | Docker 已装，只补镜像加速 |
| `-Reboot` | 跑完直接重启（默认不重启，自己选时机） |

### 3.1 手动路径（不想用脚本时）

```powershell
# 管理员 PowerShell
wsl --install
# 重启后
winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
# 启动 Docker Desktop，托盘变绿后
docker --version
docker run --rm hello-world
```

### 3.2 镜像加速（不配就白装）

`C:\ProgramData\Docker\config\daemon.json`（改完要重启 Docker Desktop）：

```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://hub.rat.dev",
    "https://docker.xuanyuan.me",
    "https://docker.nju.edu.cn"
  ]
}
```

验证：`docker pull python:3.11-slim` 能下完，就说明加速器生效。

### 3.3 磁盘：C 盘只有 10 GB

- Docker Desktop 本体装在 C（约 2~3 GB，装完 C 会更紧）。
- 镜像/容器数据必须改到 E：Docker Desktop → **Settings → Resources → Advanced**
  → Disk image location → `E:\Docker\data`。
- 官方镜像按实例构建，10 题建议 ≥ 20 GB，50 题建议 ≥ 50 GB；E 盘 63.8 GB
  只够跑 10~20 题，50 题要么清盘、要么走 Modal。

## 四、装完 Docker 后怎么判分

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HF_HUB_DISABLE_XET = "1"

# 先用 1 题验证环境（第一次要构建镜像，几分钟到十几分钟）
e:\xiaoliu\.swebench-venv\Scripts\python.exe -m swebench.harness.run_evaluation `
    -d SWE-bench/SWE-bench_Verified -s test `
    -p data\swe_pilot_one_predictions.jsonl `
    -i pytest-dev__pytest-7490 `
    -id x6-v25.2.33-smoke --max_workers 1 -t 1800

# 再跑正式 50 题（先确认磁盘；镜像会占很多空间）
e:\xiaoliu\.swebench-venv\Scripts\python.exe -m swebench.harness.run_evaluation `
    -d SWE-bench/SWE-bench_Verified -s test `
    -p data\swebench_final_predictions.jsonl `
    -id x6-v25.2.33-final --max_workers 2 -t 1800
```

报告输出在 `logs/run_evaluation/<run_id>/`；`report.json` 里的
`resolved_instances` / `total_instances` 才是可以对外说的官方分数。

## 五、现在没有 Docker 时能做什么

```powershell
e:\xiaoliu\.swebench-venv\Scripts\python.exe tools\swebench_verified.py --check `
    --dataset data\swebench\swebench_verified.jsonl
```

自检现在会分开报四项（缺哪项一目了然）：

| 检查项 | 判定 |
|---|---|
| Docker | `docker info` 能否拿到 daemon 版本（CLI 在但 daemon 没起也算红） |
| 镜像加速 | Docker Hub 或至少一个加速器的 443 能连 |
| 磁盘 | 项目所在盘剩余 ≥ 20 GB |
| 数据集 / 工作区 / swebench | 与以前一致 |

- **能**：生成 patch、落 predictions、检查清单与取样、核对镜像重试逻辑
  （`tools/swebench_verified.py --run`）。
- **不能**：官方判分、不能对外说 resolve 率。
- 本轮实跑 3 题的 patch 生成结果见 `docs/94`：0 / 3，原因是模型侧产不出 patch，
  和 Docker 无关；即使装了 Docker，也要先解决模型问题才有分数。

## 六、装完后的自检清单

```text
[ ] docker run --rm hello-world 成功
[ ] docker pull python:3.11-slim 能下完（镜像加速生效）
[ ] Docker Desktop 的 Disk image location 已指到 E:\Docker\data
[ ] e:\xiaoliu\.swebench-venv\Scripts\python.exe -c "import swebench; print(swebench.__file__)"
[ ] tools\swebench_verified.py --check --dataset data\swebench\swebench_verified.jsonl 全绿
[ ] 1 题 smoke 跑通，report.json 有 resolved_instances 字段
[ ] 磁盘剩余 ≥ 50 GB 再跑 50 题
```

## 七、要彻底绕开 Docker：`--modal true`（云沙箱）

`swebench` 支持 `--modal`，本机 venv 里 `modal 1.6.2` 已装好，只差账号：

1. 注册 Modal，拿 `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`；
2. 设环境变量后按官方 harness 跑：

```powershell
$env:MODAL_TOKEN_ID = "..."
$env:MODAL_TOKEN_SECRET = "..."
e:\xiaoliu\.swebench-venv\Scripts\python.exe -m swebench.harness.run_evaluation `
    -d SWE-bench/SWE-bench_Verified -s test `
    -p data\swebench_final_predictions.jsonl `
    -id x6-v25.2.33-modal --modal true --max_workers 2
```

优点：不吃本机磁盘、不依赖本机 Docker；缺点：要付费额度，且镜像构建在云端，
第一次仍要等较久。结果由官方 harness 产出，可对外。
