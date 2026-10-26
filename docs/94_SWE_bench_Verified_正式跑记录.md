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
    --report docs/94_SWE_bench_Verified_正式跑记录.md
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

## 五、三项硬阻塞（解除办法都写清楚）

| 阻塞 | 现状 | 解除步骤 |
|---|---|---|
| 模型产不出 patch | 4B 量化模型在 4~6 轮内不改文件；换更大模型才有意义 | 云端换有效 Key（DeepSeek / 智谱 / 硅基流动），或本机装 `qwen2.5-coder:7b` 以上 |
| 云端 Key 失效 | `https://open.bigmodel.cn/api/paas/v4/chat/completions` → **HTTP 401** | 设置 → 模型 → 云端，换 Key 后点「测试云端 Key」看到 ✅ |
| 官方判分环境缺失 | 未装 `swebench` 包、未装 Docker | `py -3 -m pip install swebench` + 安装并启动 Docker Desktop |

判分命令（环境齐了以后直接跑；本轮没有跑，所以没有分数）：

```powershell
py -3 -m swebench.harness.run_evaluation ^
    --predictions_path data/swebench_final_predictions.jsonl ^
    --dataset_name SWE-bench/SWE-bench_Verified --split test ^
    --max_workers 4 --run_id x6-v25.2.32-final
```

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
