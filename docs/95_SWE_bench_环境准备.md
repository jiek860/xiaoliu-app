# SWE-bench Verified 判分环境准备（v25.2.32）

更新日期：2026-10-26
目标：让 `swebench.harness.run_evaluation` 能真正跑出官方 resolve@1。
结论先说：**Python 侧已经装好，只差 Docker**。当前会话没有管理员权限，
Docker Desktop 的安装需要在管理员 PowerShell 里执行一次并重启。

## 一、现状（实测）

| 项目 | 状态 | 证据 / 位置 |
|---|---|---|
| Python | ✅ 3.12.10 | `py -3 --version` |
| git | ✅ 2.47.0 | `git --version` |
| `swebench` 包 | ✅ 5.0.2 | 独立虚拟环境 `e:\xiaoliu\.swebench-venv`（不污染主环境） |
| 官方 harness CLI | ✅ 可调 | `e:\xiaoliu\.swebench-venv\Scripts\python.exe -m swebench.harness.run_evaluation --help` |
| 数据集缓存 | ✅ 500 题 | 已用 `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1` 预热到 HuggingFace 缓存 |
| 本地 jsonl | ✅ | `data/swebench/swebench_verified.jsonl` |
| 环境自检 | ✅ 除 Docker 外全绿 | `e:\xiaoliu\.swebench-venv\Scripts\python.exe tools\swebench_verified.py --check --dataset data\swebench\swebench_verified.jsonl` |
| Docker | ❌ 未安装 | `docker --version` 找不到命令；官方 harness 直接报 `DockerException` |
| WSL2 | ❌ 未安装 | `wsl --status` 提示可运行 `wsl --install` |
| 虚拟化 | ✅ 已开启 | `HyperVisorPresent=True`（Hyper-V 已存在，Docker Desktop 可用 Hyper-V 后端） |
| 管理员权限 | ❌ 当前会话是普通用户 | `IsInRole(Administrator)=False` |
| 磁盘 | ⚠️ E 盘剩余 67.4 GB | 官方镜像按实例构建，50 题可能不够，建议先跑 10 题 |

## 二、为什么用独立 venv

`swebench` 会带进 `datasets`、`docker`、`modal` 等一串依赖，主环境里
`datasets` 已经是 5.0.1（产品自己的 RAG/评测也在用）。直接全局装可能把它们
升级到不兼容版本，把产品测试弄红。所以：

```
e:\xiaoliu\.swebench-venv\          ← 只给评测用
E:\xiaoliu\                      ← 产品环境保持不变
```

## 三、把 Docker 装上（需要管理员，一次性）

1. 以**管理员身份**打开 PowerShell。
2. 装 WSL2（本机 Hyper-V 已在，装 WSL 仍是最省事的路径；装完要重启）：

   ```powershell
   wsl --install
   ```

3. 重启后装 Docker Desktop：

   ```powershell
   winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
   ```

4. 启动 Docker Desktop，等托盘图标变绿，然后在普通 PowerShell 里验证：

   ```powershell
   docker --version
   docker run --rm hello-world
   ```

> 如果不想用 WSL2：Docker Desktop 设置里选 **Hyper-V 后端**（本机已具备），
> 效果一样，官方 harness 只要求"能连上 Docker daemon"。

## 四、装完 Docker 后怎么判分

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HF_HUB_DISABLE_XET = "1"

# 先用 1 题验证环境（几分钟到十几分钟，第一次要构建镜像）
e:\xiaoliu\.swebench-venv\Scripts\python.exe -m swebench.harness.run_evaluation `
    -d SWE-bench/SWE-bench_Verified -s test `
    -p data\swe_pilot_one_predictions.jsonl `
    -i pytest-dev__pytest-7490 `
    -id x6-v25.2.32-smoke --max_workers 1 -t 1800

# 再跑正式 50 题（先确认磁盘；镜像会占很多空间）
e:\xiaoliu\.swebench-venv\Scripts\python.exe -m swebench.harness.run_evaluation `
    -d SWE-bench/SWE-bench_Verified -s test `
    -p data\swebench_final_predictions.jsonl `
    -id x6-v25.2.32-final --max_workers 2 -t 1800
```

报告输出在 `logs/run_evaluation/<run_id>/`；`report.json` 里的
`resolved_instances` / `total_instances` 才是可以对外说的官方分数。

## 五、现在没有 Docker 时能做什么

- **能**：生成 patch、落 predictions、检查清单与取样、核对镜像重试逻辑
  （`tools/swebench_verified.py --run`）。
- **不能**：官方判分、不能对外说 resolve 率。
- 本轮实跑 3 题的 patch 生成结果见 `docs/94`：0 / 3，原因是模型侧产不出 patch，
  和 Docker 无关；即使装了 Docker，也要先解决模型问题才有分数。

## 六、装完后的自检清单

```text
[ ] docker run --rm hello-world 成功
[ ] e:\xiaoliu\.swebench-venv\Scripts\python.exe -c "import swebench; print(swebench.__file__)"
[ ] tools\swebench_verified.py --check --dataset data\swebench\swebench_verified.jsonl 全绿
[ ] 1 题 smoke 跑通，report.json 有 resolved_instances 字段
[ ] 磁盘剩余 ≥ 50 GB 再跑 50 题
```

## 七、如果要彻底绕开 Docker（可选）

`swebench` 支持 `--modal true` 走 Modal 云沙箱：需要注册 Modal、拿到
`MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`，并把 50 题的镜像交给云端构建。
优点是不吃本机磁盘；缺点是要付费额度，且结果仍由官方 harness 产出。
本地没有 Docker 又不想装 WSL 时，这是唯一还算正规的路。
