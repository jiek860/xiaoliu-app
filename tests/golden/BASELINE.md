# Golden Set 基线（第 1 批交付）

> 记录时间：2026-11-01
> 口径：完全离线（不调模型、不联网、不碰 Qt），`pytest` 与本地命令结果一致。

## 初始分数（第 1 批交付时）

| 域 | 通过/总数 | pass_rate | 关键指标 |
|---|---|---|---|
| 聊天 | 8/10 | 0.8000 | memory_hit_rate 1.0000、citation_accuracy 1.0000、referent_accuracy 0.5000、style_pass_rate 1.0000 |
| 代码 | 5/5 | 1.0000 | code_pass_rate 1.0000 |

聊天域未通过的 2 条是**有意暴露的已知差距**（不是测试写错）：

- `ref_001`：`给它加个参数校验` → 话题被抽成 `password`，而不是 `login.py`
  （`core/chat/topic_index.topic_of` 取"最长的英文 token"，对代码场景不准）；
- `ref_002`：`继续` → 话题抽成 `才会越玩越有成就`（取了整句，未按语义收窄）。

## 现状（第 4 批交付时，已 `--update-baseline`）

| 域 | 通过/总数 | pass_rate | 关键指标 |
|---|---|---|---|
| 聊天 | 10/10 | 1.0000 | memory_hit_rate 1.0000、citation_accuracy 1.0000、**referent_accuracy 1.0000**、style_pass_rate 1.0000 |
| 代码 | 5/5 | 1.0000 | code_pass_rate 1.0000 |

第 4 批的修法（对应上面两条差距）：

- `topic_index.topic_of` 改为**先取第一句人话**（`first_sentence`），取不到才退到最长关键词；
- `referent.last_topic` 改为**优先用户原话**（助手那句"好的，已经给你写好了"不再当指代对象）。

## 工程基线（第 1 批开工时）

| 项 | 结果 |
|---|---|
| `py -3 -m pytest -q` | 3116 passed / 4 skipped |
| `check_buttons` | 创建点 60/60、表行 0/0 ✅ |
| `check_file_sizes` | 通过（警告不阻塞） |
| `check_silent` | 0 处（基线 0） ✅ |
| `check_shapes` | 全部通过（清单 48 条契约完好） |
| `check_version` | v25.5.0 ✅ |

## 用例扩充节奏

| 批次 | 聊天用例 | 代码用例 |
|---|---|---|
| 第 1 批（已完成） | 10 | 5 |
| 第 2~5 批 | → 50 | 5 |
| 第 6~8 批 | 50 | → 30 |
| 第 9 批 | 全量 + 6 项守卫 | 全量 |
