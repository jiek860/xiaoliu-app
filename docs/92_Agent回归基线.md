# Agent 回归基线（固定小样本）

> **文档分类**：评测与基线（Agent 回归、SWE-bench、评测基线）
> **状态**：合订本（2026-10-30 合并，原零散文件已并入本文）
> **合并来源**：93_SWE_bench_Verified_评测方案.md、94_SWE_bench_Verified_正式跑记录.md、94b_SWE_bench_第二批记录.md、95_SWE_bench_环境准备.md、104_评测基线_2026-10-29.md
> **维护要求**：新内容先判断归属，属于本类的追加到文末对应章节，不再新建同级 md/txt（详见 docs/109 第十三节）。

日期：2026-10-26 22:17
版本：v25.2.33
样本：20 道
通过：20（100.0%）

| # | 用例 | 结果 | 耗时(s) |
| --- | --- | --- | --- |
| 1 | path_1 | ✅ | 0.002 |
| 2 | path_escape | ✅ | 0.000 |
| 3 | net_private | ✅ | 0.092 |
| 4 | net_file | ✅ | 0.006 |
| 5 | net_cloud | ✅ | 0.029 |
| 6 | permission_lockdown | ✅ | 0.000 |
| 7 | workspace_1 | ✅ | 0.001 |
| 8 | parser_readme | ✅ | 0.002 |
| 9 | parser_missing | ✅ | 0.000 |
| 10 | redaction_secret | ✅ | 0.001 |
| 11 | untrusted_wrap | ✅ | 0.129 |
| 12 | patch_apply_rollback | ✅ | 0.066 |
| 13 | patch_reject_non_unique | ✅ | 0.008 |
| 14 | patch_reject_wrong_hash | ✅ | 0.002 |
| 15 | patch_dry_run_broken | ✅ | 0.015 |
| 16 | plan_simple_no_plan | ✅ | 0.000 |
| 17 | plan_complex_steps | ✅ | 0.000 |
| 18 | symbol_index_find | ✅ | 0.023 |
| 19 | tool_policy_read_allow | ✅ | 0.004 |
| 20 | tool_policy_untrusted_exec_deny | ✅ | 0.000 |

说明：这是**确定性回归基线**，不调用模型；用于每次改 Agent/补丁/权限逻辑后对比，不追求分数增长，只要求保持全绿。

---

## 附录：SWE-bench Verified 评测方案

> 原文件 `docs/93_SWE_bench_Verified_评测方案.md`，2026-10-30 合并入本文。

# SWE-bench Verified 公开评测方案（B7 试跑 / B11 正式跑）

更新日期：2026-10-26
适用版本：v25.2.32（B7 / B11 批次）
驱动脚本：`tools/swebench_verified.py`
生成入口：`tools/x6_code_cli.py`（无头代码 Agent，只产出 patch）

## 一、为什么换成公开评测

原来只有自家 20 道题（`tests/eval/cases.json`），它能证明"程序没崩、链路能跑"，
但**不能证明"能把真实仓库里的 bug 修好"**——题目是我们自己出的，别人无法复现，
也没法和同类产品横向比。

SWE-bench Verified 是 OpenAI 发布的 500 题人工复核子集，每题都带：
真实仓库 + `base_commit` + 真实 issue 文本 + `FAIL_TO_PASS` / `PASS_TO_PASS` 用例。
判分由官方 harness 在容器里跑测试得出，**不接受截图、不接受"看起来修好了"**。

对本项目的要求正好对齐：评测只吃 `model_patch`（git diff），而
`tools/x6_code_cli.py` 的定位就是"只生成 patch、不落盘、不跑测试"。

## 二、指标与口径

| 项目 | 口径 |
|---|---|
| 主指标 | `resolve_rate = 修好题数 / 总题数`（官方 harness 输出） |
| 判定 | 该题 `FAIL_TO_PASS` 全部通过 **且** `PASS_TO_PASS` 无回归 |
| 空 patch | 记为未修好（仍然写进 predictions，不重跑、不删题） |
| 重跑 | 同一 `run_id` 不覆盖；重跑要换 `--run-id`，历史结果都留 |
| 每轮预算 | 每题最多 6 轮工具调用（`--max-rounds 6`），与默认策略一致 |

## 三、两步跑法

> 数据集已经落到本仓库：`data/swebench/swebench_verified.jsonl`（500 题），
> 下面的命令直接用它，不再依赖 `data/swe_verified.jsonl`。

### 1. 试跑 10 题（B7）

选题固定、覆盖 6 个仓库（Django / SymPy / Sphinx / pytest / Matplotlib / astropy）：

```powershell
py -3 tools/swebench_verified.py --plan --out data/swebench_pilot_plan.json
py -3 tools/swebench_verified.py --check
py -3 tools/swebench_verified.py --dataset data/swebench/swebench_verified.jsonl `
    --limit 10 --workdir data/swe_work --out data/swebench_pilot_predictions.jsonl `
    --report docs/93b_SWE_bench试跑记录.md
```

脚本会校验这 10 个 id **确实在数据集里**，缺一个就报错退出——不允许"少跑几题当跑完了"。
本轮修正后真实清单（原来有 4 个 id 抄错了）：

```
django__django-10880      django__django-11099      django__django-11133
sympy__sympy-20154        sympy__sympy-20590        sphinx-doc__sphinx-8721
sphinx-doc__sphinx-11445  pytest-dev__pytest-7490   matplotlib__matplotlib-20676
astropy__astropy-12907
```

### 2. 正式 50 题（B11）

```powershell
py -3 tools/swebench_verified.py --final --dataset data/swebench/swebench_verified.jsonl `
    --out data/swebench_final_plan.json
py -3 tools/swebench_verified.py --dataset data/swebench/swebench_verified.jsonl `
    --ids (Get-Content data/swebench_final_plan.json | ConvertFrom-Json).ids -join "," `
    --out data/swebench_final_predictions.jsonl
py -3 tools/swebench_verified.py --predictions data/swebench_final_predictions.jsonl `
    --run-harness --run-id x6-v25.2.32-final
```

取样规则写死：`instance_id` 升序 → 排除试跑 10 题 → 固定种子 `20261123` 的
`random.sample(50)`。同样的数据集必然得到同一份清单，别人可以复核我们没挑题。
正式清单已生成：`data/swebench_final_plan.json`（seed 20261123，50 题）。

### 2.1 网络说明（本机实测）

`github.com` 直连 `git clone` 会被重置（`Recv failure: Connection was reset`）。
`tools/swebench_verified.py` 的 `mirror_url()` 默认走 `https://ghfast.top/` 前缀，
直连失败自动重试镜像；设置环境变量 `X6_GIT_MIRROR=`（空字符串）可关闭。
HuggingFace 直连不可达，下载数据集要用 `HF_ENDPOINT=https://hf-mirror.com` 且
`HF_HUB_DISABLE_XET=1`。

### 3. 判分

由官方 harness 完成，不在本仓库里自造：

```powershell
py -3 -m swebench.harness.run_evaluation `
    --predictions_path data/swebench_final_predictions.jsonl `
    --dataset_name SWE-bench/SWE-bench_Verified --split test `
    --max_workers 4 --run_id x6-v25.2.32-final
```

## 四、本轮实测状态（诚实记录）

### 已交付

| 项目 | 状态 | 证据 |
|---|---|---|
| 评测驱动 | ✅ 完成 | `tools/swebench_verified.py`（check / plan / final / run / harness） |
| 数据集 | ✅ 已落盘 | `data/swebench/swebench_verified.jsonl`（500 题） |
| 试跑清单 | ✅ 完成 | `data/swebench_pilot_plan.json`（10 题，真实 id） |
| 正式清单 | ✅ 完成 | `data/swebench_final_plan.json`（50 题，seed 20261123） |
| 端到端实跑 | ✅ 跑通链路 | clone（含镜像重试）→ Agent → predictions 落盘 |
| patch 生成 | ❌ 0 / 3 | 4B 本地模型三次都返回空 patch（详见 `docs/94`） |
| 离线可验逻辑 | ✅ 通过 | `tests/test_x6_code_cli.py`：清单/解析/缺 id 报错/空 patch 记账/仓库失败记账/50 题取样可复现/镜像重写 |
| 生成入口 | ✅ 已有 | `tools/x6_code_cli.py`（B2），只产出 patch |

### 阻塞项（实测）

| 检查 | 结果 | 说明 |
|---|---|---|
| Python 3.12.10 / git | ✅ | 具备 clone + checkout 条件 |
| 无头 CLI / 核心模块 | ✅ | `core.code_agent`、`core.llm_client` 可导入 |
| 模型可用性 | ❌ | 云端 `open.bigmodel.cn` → **HTTP 401**（Key 失效）；本机 Ollama 可达但 4B 模型产不出 patch |
| `swebench` 包 | ✅ 已装 | 独立 venv `e:\xiaoliu\.swebench-venv`（5.0.2），不污染产品环境；见 `docs/95` |
| Docker | ❌ | 未安装；官方 harness 需要容器（管理员 + 重启），步骤见 `docs/95` |
| 数据集 | ✅ | 已通过 hf-mirror + `HF_HUB_DISABLE_XET=1` 下载并导出 |
| GitHub clone | ✅（走镜像） | 直连被重置，`ghfast.top` 可用，脚本自动重试 |

结论：**本轮没有真实分数**。3 次端到端试跑（pytest / sympy / sphinx 各 1 题）都把
"修改 Agent 未返回有效 patch" 如实记成 error，合计 0 / 3；官方判分又缺 Docker +
`swebench` 包。把这种 0% 当成绩发布是造假，所以本版本只交付"可复现的评测装置 +
诚实的空 patch 记录"，不发布 resolve 率。

### 解除阻塞需要什么（任选一条模型路）

1. 云端：`设置 → 模型 → 云端` 换一个有效 Key，点「测试云端 Key」看到 ✅；
   建议用 DeepSeek / 智谱 / 硅基流动（国内直连）。
2. 本地：本机 Ollama 已能连通，但 4B 量化模型改不动真实仓库；
   换成 `qwen2.5-coder:7b` 或更大，向导里点「下载模型」。

然后补齐评测环境：

```powershell
py -3 -m pip install swebench          # 判分
# Docker Desktop 安装并启动
# 数据集导出
py -3 -c "from datasets import load_dataset; ds=load_dataset('SWE-bench/SWE-bench_Verified', split='test'); ds.to_json('data/swe_verified.jsonl')"
```

再按第三节的命令跑；`--check` 全绿才开跑。

## 五、成本与时间预估（试跑 10 题）

| 项目 | 粗估 |
|---|---|
| 每题上下文 | 仓库按需读取，单题 3~8 万 token（6 轮工具调用） |
| 每题耗时 | 本地 7B 约 8~20 分钟；云端约 2~5 分钟 |
| 判分 | 每题一个容器，10 题约 20~40 分钟（4 并发） |
| 网络 | 首次 clone 每题 100~400MB（`--filter=blob:none` 已尽量小） |

正式 50 题的 token 成本约为试跑的 5 倍，判分时间约 1.5~3 小时。

## 六、和自家 20 题的关系

| 评测 | 用途 | 频率 |
|---|---|---|
| `tools/run_eval.py` + `docs/92_Agent回归基线.md` | 链路回归（不调模型，秒级） | 每次改 Agent/补丁逻辑 |
| SWE-bench Verified 10 题 | 能力摸底（调模型） | 每次发版前 |
| SWE-bench Verified 50 题 | 对外可复现成绩 | 每个冻结版一次 |

两者不互相替代：前者保证"没把东西改坏"，后者回答"到底能不能修真实 bug"。

---

## 附录：SWE-bench Verified 正式跑记录

> 原文件 `docs/94_SWE_bench_Verified_正式跑记录.md`，2026-10-30 合并入本文。

# SWE-bench Verified 正式评测记录（v25.2.32 冻结版）

更新日期：2026-10-26
驱动脚本：`tools/swebench_verified.py`
生成入口：`tools/x6_code_cli.py`（只产出 patch，不落盘、不跑测试）
判分入口：官方 `swebench.harness.run_evaluation`

## 一、本轮结论（先看这里）

**没有产出可判分的分数。** 试跑 3 题全部是 `error`（修改 Agent 未返回有效 patch），
即 `0 / 3`。这不是"跑输了"，而是**模型侧拿不出 patch**——本机可用模型是
`xiao6-qwen3.5-4b`（4B 量化），在 6 轮工具调用预算内一直返回"没有可应用的修改"。

按事先约定的口径：空 patch 记为未修好、如实写进 predictions、不重跑刷分、不删题。
所以本轮对外口径是：

| 项目 | 结果 |
|---|---|
| 官方判分 resolve@1 | **未产生**（无 Docker / 无 `swebench` 包） |
| patch 生成率 | **0 / 3**（3 题都返回空 patch） |
| 可复现性 | ✅ 取样清单、镜像、命令、预测文件全部留档 |

## 二、数据集是怎么来的（可复核）

| 步骤 | 做法 |
|---|---|
| 数据源 | HuggingFace `SWE-bench/SWE-bench_Verified`（test split，500 题） |
| 下载 | `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1`（直连 huggingface.co 不可达；不关 Xet 会 401） |
| 落盘 | `data/swebench/dataset/data/test-00000-of-00001.parquet`（约 6.3 MB，500 行） |
| 导出 | `data/swebench/swebench_verified.jsonl`（每行含 `instance_id` / `repo` / `base_commit` / `problem_statement` / `FAIL_TO_PASS` / `PASS_TO_PASS`） |

复现命令：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HF_HUB_DISABLE_XET = "1"
py -3 -c "from datasets import load_dataset; ds = load_dataset('SWE-bench/SWE-bench_Verified', split='test'); ds.to_json('data/swebench/swebench_verified.jsonl', orient='records', lines=True)"
```

## 三、取样规则（写死，防止挑题）

- 试跑 10 题：`data/swebench_pilot_plan.json`，覆盖 6 个仓库，id 必须真实存在于数据集中
  （脚本缺一个就报错退出；另有一条测试专门守这个）。
- 正式 50 题：`data/swebench_final_plan.json`，规则是
  `instance_id` 升序 → 排除试跑 10 题 → `random.Random(20261123).sample(50)`。
  同样的数据集 + 同样的种子必然得到同一份清单，任何人都能复核。

试跑 10 题（真实 id）：

```
django__django-10880      django__django-11099      django__django-11133
sympy__sympy-20154        sympy__sympy-20590        sphinx-doc__sphinx-8721
sphinx-doc__sphinx-11445  pytest-dev__pytest-7490   matplotlib__matplotlib-20676
astropy__astropy-12907
```

## 四、实跑做了什么、结果如何

环境：Windows 10 / Python 3.12.10 / 本地 Ollama（`http://192.168.1.2:11434`）
可用模型：`xiao6-qwen3.5-4b:latest`、`qwen3.5:4b`、`qwen2.5-coder-1.5b-cn`
生成命令（临时把 `model_mode` 切到本地路由，跑完原样还原）：

```powershell
py -3 tools/swebench_verified.py --dataset data/swebench/swebench_verified.jsonl ^
    --ids pytest-dev__pytest-7490 --workdir data/swe_work ^
    --out data/swe_pilot_one_predictions.jsonl ^
    --report docs/92_Agent回归基线.md
```

| 批次 | 实例 | 结果 | 说明 |
|---|---|---|---|
| 1 | `pytest-dev__pytest-7490` | error | 修改 Agent 未返回有效 patch |
| 2 | `sympy__sympy-20154` | error | 同上 |
| 2 | `sphinx-doc__sphinx-8721` | error | 同上 |

`data/swe_pilot_one_predictions.jsonl`、`data/swe_pilot_two_predictions.jsonl`
里都是空 `model_patch`——这是模型的真实产出，没有手工补。
第二批的原始输出另存一份 `docs/94b_SWE_bench_第二批记录.md`。

> 收尾时已删除 `data/swe_work/`（3 个真实仓库 clone，约 52 MB）。原因有两个：
> 一是里面含 Sphinx 测试用的 `tests/certs/cert.pem`，会被"项目里不得有私钥"
> 的守卫拦下；二是不该把第三方仓库塞进产品仓库。重跑时脚本会重新 clone。

## 五、三处硬阻塞（Key 已恢复，另两处仍在）

| 阻塞 | 现状 | 解除步骤 |
|---|---|---|
| 模型产不出 patch | 4B 量化模型在 4~6 轮内不改文件；换更大模型才有意义 | 云端换有效 Key（DeepSeek / 智谱 / 硅基流动），或本机装 `qwen2.5-coder:7b` 以上 |
| 云端 Key 401 | ✅ **2026-10-27 复核已恢复**：配置里存的是 DPAPI 密文（`dpapi:v1:`），解密后为 49 字符明文（智谱 `<id>.<secret>` 格式），`test_cloud` 与 `glm-4v-flash` 直连均返回 **HTTP 200**。10-26 那次 401 是旧 Key 失效；另查到一个会复现同样 401 的坑：把密文当 `Bearer` 发出去 | 设置 → 模型 → 「云端模型 / 服务商」对话框里新增「🔌 测试云端连通」：用输入框当前值真打一次请求，当场显示 ✅ / ❌ + HTTP 码，不必先保存 |
| 官方判分环境 | ⚠️ `swebench` 已装（独立 venv `e:\xiaoliu\.swebench-venv`，5.0.2），**Docker 仍未装**；且本机 Docker Hub 不通、C 盘仅剩 10 GB | 提权后跑 `tools\setup_swebench_docker.ps1`（开 WSL + 装 Docker Desktop + 写国内镜像加速），再把磁盘镜像位置指到 E 盘；详见 `docs/95` |

判分命令（环境齐了以后直接跑；本轮没有跑，所以没有分数）：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HF_HUB_DISABLE_XET = "1"
e:\xiaoliu\.swebench-venv\Scripts\python.exe -m swebench.harness.run_evaluation `
    -d SWE-bench/SWE-bench_Verified -s test `
    -p data\swebench_final_predictions.jsonl `
    -id x6-v25.2.33-final --max_workers 2 -t 1800
```

环境细节与 Docker 安装步骤见 `docs/95_SWE_bench_环境准备.md`。

## 六、为跑通评测补的工程（本轮真实产出）

| 改动 | 原因 |
|---|---|
| `mirror_url()` + `_git()` + clone 直连失败自动重试 `ghfast.top` | `github.com` 直连 `git clone` 被重置（`Recv failure: Connection was reset`），不加重试一题都跑不起来 |
| 修正 `PILOT_IDS` 为数据集里真实存在的 id | 原清单是抄来的，4 个 id 根本不在 Verified 里；现在有测试守着 |
| `--plan` / `--final` 清单落盘 + 固定种子 | 让别人能复核"没挑题" |
| 空 patch 也写进 predictions | 不删失败样本，避免"只报好题" |

## 七、怎么看待这轮结果

- 工程链路是通的：数据集 → 固定取样 → clone（含镜像重试）→ Agent 生成 patch → predictions 落盘，端到端跑过。
- 分数是不通的：缺一个能真正改代码的模型、缺 Docker 判分环境。
- 因此本版本**不发布 SWE-bench 分数**，只发布"可复现的评测装置 + 诚实的 0/3 patch 生成记录"。
  等模型和判分环境补齐，按第五节命令重跑即可得到官方 resolve 率。

---

## 附录：SWE-bench 第二批记录

> 原文件 `docs/94b_SWE_bench_第二批记录.md`，2026-10-30 合并入本文。

# SWE-bench Verified 试跑记录

| 实例 | 状态 | 说明 |
|---|---|---|
| sympy__sympy-20154 | error | 修改 Agent 未返回有效 patch |
| sphinx-doc__sphinx-8721 | error | 修改 Agent 未返回有效 patch |

生成成功 0 / 2 题。判分口径以官方 harness 输出为准。

- predictions：e:\xiaoliu\data\swe_pilot_two_predictions.jsonl

- model：x6-agent

---

## 附录：SWE-bench 环境准备

> 原文件 `docs/95_SWE_bench_环境准备.md`，2026-10-30 合并入本文。

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

---

## 附录：评测基线（2026-10-29）

> 原文件 `docs/104_评测基线_2026-10-29.md`，2026-10-30 合并入本文。

# Agent 回归基线（固定小样本）

日期：2026-10-29 17:03  
版本：v25.2.36  
样本：140 道  
通过：80（100.0%）  
跳过：60  

| 域 | 总数 | 通过 | 失败 | 跳过 | 通过率 | 期望匹配 |
| --- | --- | --- | --- | --- | --- | --- |
| chat | 60 | 0 | 0 | 60 | 0.0% | 0/0 |
| code | 20 | 20 | 0 | 0 | 100.0% | 0/0 |
| nl | 40 | 40 | 0 | 0 | 100.0% | 32/40 |
| safe | 20 | 20 | 0 | 0 | 100.0% | 0/0 |

| # | 域 | 用例 | 结果 | 耗时(s) | 详情 |
| --- | --- | --- | --- | --- | --- |
| 1 | safe | path_1 | ✅ | 0.004 |  |
| 2 | safe | path_escape | ✅ | 0.000 |  |
| 3 | safe | net_private | ✅ | 0.075 |  |
| 4 | safe | net_file | ✅ | 0.000 |  |
| 5 | safe | net_cloud | ✅ | 0.014 |  |
| 6 | safe | permission_lockdown | ✅ | 0.000 |  |
| 7 | safe | workspace_1 | ✅ | 0.000 |  |
| 8 | safe | parser_readme | ✅ | 0.002 |  |
| 9 | safe | parser_missing | ✅ | 0.000 |  |
| 10 | safe | redaction_secret | ✅ | 0.000 |  |
| 11 | safe | untrusted_wrap | ✅ | 0.015 |  |
| 12 | safe | patch_apply_rollback | ✅ | 0.033 |  |
| 13 | safe | patch_reject_non_unique | ✅ | 0.004 |  |
| 14 | safe | patch_reject_wrong_hash | ✅ | 0.003 |  |
| 15 | safe | patch_dry_run_broken | ✅ | 0.015 |  |
| 16 | safe | plan_simple_no_plan | ✅ | 0.000 |  |
| 17 | safe | plan_complex_steps | ✅ | 0.000 |  |
| 18 | safe | symbol_index_find | ✅ | 0.011 |  |
| 19 | safe | tool_policy_read_allow | ✅ | 0.001 |  |
| 20 | safe | tool_policy_untrusted_exec_deny | ✅ | 0.000 |  |
| 21 | chat | chat_001 | ⏭ | 0.000 | 需要 --with-model |
| 22 | chat | chat_002 | ⏭ | 0.000 | 需要 --with-model |
| 23 | chat | chat_003 | ⏭ | 0.000 | 需要 --with-model |
| 24 | chat | chat_004 | ⏭ | 0.000 | 需要 --with-model |
| 25 | chat | chat_005 | ⏭ | 0.000 | 需要 --with-model |
| 26 | chat | chat_006 | ⏭ | 0.000 | 需要 --with-model |
| 27 | chat | chat_007 | ⏭ | 0.000 | 需要 --with-model |
| 28 | chat | chat_008 | ⏭ | 0.000 | 需要 --with-model |
| 29 | chat | chat_009 | ⏭ | 0.000 | 需要 --with-model |
| 30 | chat | chat_010 | ⏭ | 0.000 | 需要 --with-model |
| 31 | chat | chat_011 | ⏭ | 0.000 | 需要 --with-model |
| 32 | chat | chat_012 | ⏭ | 0.000 | 需要 --with-model |
| 33 | chat | chat_013 | ⏭ | 0.000 | 需要 --with-model |
| 34 | chat | chat_014 | ⏭ | 0.000 | 需要 --with-model |
| 35 | chat | chat_015 | ⏭ | 0.000 | 需要 --with-model |
| 36 | chat | chat_016 | ⏭ | 0.000 | 需要 --with-model |
| 37 | chat | chat_017 | ⏭ | 0.000 | 需要 --with-model |
| 38 | chat | chat_018 | ⏭ | 0.000 | 需要 --with-model |
| 39 | chat | chat_019 | ⏭ | 0.000 | 需要 --with-model |
| 40 | chat | chat_020 | ⏭ | 0.000 | 需要 --with-model |
| 41 | chat | chat_021 | ⏭ | 0.000 | 需要 --with-model |
| 42 | chat | chat_022 | ⏭ | 0.000 | 需要 --with-model |
| 43 | chat | chat_023 | ⏭ | 0.000 | 需要 --with-model |
| 44 | chat | chat_024 | ⏭ | 0.000 | 需要 --with-model |
| 45 | chat | chat_025 | ⏭ | 0.000 | 需要 --with-model |
| 46 | chat | chat_026 | ⏭ | 0.000 | 需要 --with-model |
| 47 | chat | chat_027 | ⏭ | 0.000 | 需要 --with-model |
| 48 | chat | chat_028 | ⏭ | 0.000 | 需要 --with-model |
| 49 | chat | chat_029 | ⏭ | 0.000 | 需要 --with-model |
| 50 | chat | chat_030 | ⏭ | 0.000 | 需要 --with-model |
| 51 | chat | chat_031 | ⏭ | 0.000 | 需要 --with-model |
| 52 | chat | chat_032 | ⏭ | 0.000 | 需要 --with-model |
| 53 | chat | chat_033 | ⏭ | 0.000 | 需要 --with-model |
| 54 | chat | chat_034 | ⏭ | 0.000 | 需要 --with-model |
| 55 | chat | chat_035 | ⏭ | 0.000 | 需要 --with-model |
| 56 | chat | chat_036 | ⏭ | 0.000 | 需要 --with-model |
| 57 | chat | chat_037 | ⏭ | 0.000 | 需要 --with-model |
| 58 | chat | chat_038 | ⏭ | 0.000 | 需要 --with-model |
| 59 | chat | chat_039 | ⏭ | 0.000 | 需要 --with-model |
| 60 | chat | chat_040 | ⏭ | 0.000 | 需要 --with-model |
| 61 | chat | chat_041 | ⏭ | 0.000 | 需要 --with-model |
| 62 | chat | chat_042 | ⏭ | 0.000 | 需要 --with-model |
| 63 | chat | chat_043 | ⏭ | 0.000 | 需要 --with-model |
| 64 | chat | chat_044 | ⏭ | 0.000 | 需要 --with-model |
| 65 | chat | chat_045 | ⏭ | 0.000 | 需要 --with-model |
| 66 | chat | chat_046 | ⏭ | 0.000 | 需要 --with-model |
| 67 | chat | chat_047 | ⏭ | 0.000 | 需要 --with-model |
| 68 | chat | chat_048 | ⏭ | 0.000 | 需要 --with-model |
| 69 | chat | chat_049 | ⏭ | 0.000 | 需要 --with-model |
| 70 | chat | chat_050 | ⏭ | 0.000 | 需要 --with-model |
| 71 | chat | chat_051 | ⏭ | 0.000 | 需要 --with-model |
| 72 | chat | chat_052 | ⏭ | 0.000 | 需要 --with-model |
| 73 | chat | chat_053 | ⏭ | 0.000 | 需要 --with-model |
| 74 | chat | chat_054 | ⏭ | 0.000 | 需要 --with-model |
| 75 | chat | chat_055 | ⏭ | 0.000 | 需要 --with-model |
| 76 | chat | chat_056 | ⏭ | 0.000 | 需要 --with-model |
| 77 | chat | chat_057 | ⏭ | 0.000 | 需要 --with-model |
| 78 | chat | chat_058 | ⏭ | 0.000 | 需要 --with-model |
| 79 | chat | chat_059 | ⏭ | 0.000 | 需要 --with-model |
| 80 | chat | chat_060 | ⏭ | 0.000 | 需要 --with-model |
| 81 | nl | nl_001 | ✅ | 0.001 | kind=code desired=code conf=1.00 |
| 82 | nl | nl_002 | ✅ | 0.000 | kind=code desired=code conf=1.00 |
| 83 | nl | nl_003 | ✅ | 0.000 | kind=code desired=code conf=1.00 |
| 84 | nl | nl_004 | ✅ | 0.000 | kind=code desired=code conf=0.83 |
| 85 | nl | nl_005 | ✅ | 0.000 | kind=code desired=code conf=0.50 |
| 86 | nl | nl_006 | ✅ | 0.000 | kind=chat desired=code conf=0.67 |
| 87 | nl | nl_007 | ✅ | 0.000 | kind=code desired=code conf=1.00 |
| 88 | nl | nl_008 | ✅ | 0.000 | kind=code desired=code conf=0.80 |
| 89 | nl | nl_009 | ✅ | 0.000 | kind=chat desired=code conf=0.35 |
| 90 | nl | nl_010 | ✅ | 0.000 | kind=code desired=code conf=1.00 |
| 91 | nl | nl_011 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 92 | nl | nl_012 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 93 | nl | nl_013 | ✅ | 0.000 | kind=chat desired=computer conf=0.35 |
| 94 | nl | nl_014 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 95 | nl | nl_015 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 96 | nl | nl_016 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 97 | nl | nl_017 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 98 | nl | nl_018 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 99 | nl | nl_019 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 100 | nl | nl_020 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 101 | nl | nl_021 | ✅ | 0.000 | kind=chat desired=chat conf=1.00 |
| 102 | nl | nl_022 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 103 | nl | nl_023 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 104 | nl | nl_024 | ✅ | 0.000 | kind=chat desired=chat conf=1.00 |
| 105 | nl | nl_025 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 106 | nl | nl_026 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 107 | nl | nl_027 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 108 | nl | nl_028 | ✅ | 0.000 | kind=chat desired=chat conf=1.00 |
| 109 | nl | nl_029 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 110 | nl | nl_030 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 111 | nl | nl_031 | ✅ | 0.000 | kind=chat desired=chat conf=1.00 |
| 112 | nl | nl_032 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 113 | nl | nl_033 | ✅ | 0.000 | kind=code desired=code conf=1.00 |
| 114 | nl | nl_034 | ✅ | 0.000 | kind=code desired=computer conf=1.00 |
| 115 | nl | nl_035 | ✅ | 0.000 | kind=chat desired=chat conf=0.35 |
| 116 | nl | nl_036 | ✅ | 0.000 | kind=chat desired=code conf=0.35 |
| 117 | nl | nl_037 | ✅ | 0.000 | kind=chat desired=code conf=0.35 |
| 118 | nl | nl_038 | ✅ | 0.000 | kind=computer desired=computer conf=1.00 |
| 119 | nl | nl_039 | ✅ | 0.000 | kind=chat desired=code conf=0.35 |
| 120 | nl | nl_040 | ✅ | 0.000 | kind=computer desired=code conf=1.00 |
| 121 | code | code_001 | ✅ | 0.051 | exit=1 actual=failing expected=failing 失败：吃到食物后分数应为 10，实际 {' |
| 122 | code | code_002 | ✅ | 0.049 | exit=1 actual=failing expected=failing 失败：吃到食物后分数应为 10，实际 {' |
| 123 | code | code_003 | ✅ | 0.057 | exit=1 actual=failing expected=failing 失败：吃到食物后分数应为 10，实际 {' |
| 124 | code | code_004 | ✅ | 0.057 | exit=1 actual=failing expected=failing 失败：吃到食物后分数应为 10，实际 {' |
| 125 | code | code_005 | ✅ | 0.050 | exit=1 actual=failing expected=failing 失败：提交时没有调用 handler
 |
| 126 | code | code_006 | ✅ | 0.046 | exit=1 actual=failing expected=failing 失败：提交时没有调用 handler
 |
| 127 | code | code_007 | ✅ | 0.053 | exit=1 actual=failing expected=failing 失败：提交时没有调用 handler
 |
| 128 | code | code_008 | ✅ | 0.054 | exit=1 actual=failing expected=failing 失败：提交时没有调用 handler
 |
| 129 | code | code_009 | ✅ | 0.051 | exit=1 actual=failing expected=failing 失败：average([]) 抛了 Zer |
| 130 | code | code_010 | ✅ | 0.045 | exit=1 actual=failing expected=failing 失败：average([]) 抛了 Zer |
| 131 | code | code_011 | ✅ | 0.046 | exit=1 actual=failing expected=failing 失败：average([]) 抛了 Zer |
| 132 | code | code_012 | ✅ | 0.046 | exit=1 actual=failing expected=failing 失败：average([]) 抛了 Zer |
| 133 | code | code_013 | ✅ | 0.053 | exit=1 actual=failing expected=failing ot import name 'VALUE |
| 134 | code | code_014 | ✅ | 0.050 | exit=1 actual=failing expected=failing ot import name 'VALUE |
| 135 | code | code_015 | ✅ | 0.046 | exit=1 actual=failing expected=failing ot import name 'VALUE |
| 136 | code | code_016 | ✅ | 0.064 | exit=1 actual=failing expected=failing ot import name 'VALUE |
| 137 | code | code_017 | ✅ | 0.102 | exit=1 actual=failing expected=failing 失败：用 UTF-8 读回时解码失败（写入 |
| 138 | code | code_018 | ✅ | 0.098 | exit=1 actual=failing expected=failing 失败：用 UTF-8 读回时解码失败（写入 |
| 139 | code | code_019 | ✅ | 0.083 | exit=1 actual=failing expected=failing 失败：用 UTF-8 读回时解码失败（写入 |
| 140 | code | code_020 | ✅ | 0.085 | exit=1 actual=failing expected=failing 失败：用 UTF-8 读回时解码失败（写入 |

说明：这是**确定性回归基线**，不调用模型；聊天/代码生成类用例默认跳过，用于每次改 Agent/补丁/权限逻辑后对比，不追求分数增长，只要求保持全绿。

## 批次 41 基线解读（2026-10-29）

- **safe 20/20**：原有安全/工具链回归保持全绿，没有因为评测底座改造而回退。
- **nl 32/40（80.0%）**：现有三词表路由与「期望意图」的一致率。这是批次 44 要抬到 ≥92% 的**起点**，不是终态；未命中 8 条正是「打开 README」「把日志里的错误提取出来」这类跨域表达。
- **code 20/20**：5 个 fixture 的**初始健康度**全部符合预期（故意失败），说明 fixture 可复现、可迁移；真正的修复成功率（pass@1）在批次 46 用 Agent 跑，届时新增 `code_agent_*` 用例。
- **chat 60 条全部跳过**：本批只建用例与指标函数，真实生成评测在批次 42.5 接入（`--with-model`）。因此「拟人度/重复率」这一列当前不可比，需等 42.3/42.5 产出。

**复现命令**：

```powershell
py -3 tools/run_eval.py --domain all --report data/eval/report_20261029.json
py -3 tools/run_eval.py --domain nl      # 只看工作台 NL
py -3 tools/run_eval.py --domain code     # 只跑 fixtures
py -3 tools/run_eval.py --domain chat --with-model   # 批次 42.5 之后
```

**口径提醒**：nl 默认是「快照 + 匹配率」，不算失败；加 `--strict` 才会因不匹配而红。这样在批次 44 之前不会因为已知差距把 CI 卡死。

