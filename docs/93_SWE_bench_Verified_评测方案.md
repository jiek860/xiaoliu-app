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
