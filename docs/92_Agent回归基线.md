# Agent 回归基线（固定小样本）

日期：2026-10-25 22:13  
版本：v25.2.32  
样本：20 道  
通过：20（100.0%）

| # | 用例 | 结果 | 耗时(s) |
| --- | --- | --- | --- |
| 1 | path_1 | ✅ | 0.003 |
| 2 | path_escape | ✅ | 0.000 |
| 3 | net_private | ✅ | 0.121 |
| 4 | net_file | ✅ | 0.001 |
| 5 | net_cloud | ✅ | 0.028 |
| 6 | permission_lockdown | ✅ | 0.001 |
| 7 | workspace_1 | ✅ | 0.001 |
| 8 | parser_readme | ✅ | 0.003 |
| 9 | parser_missing | ✅ | 0.000 |
| 10 | redaction_secret | ✅ | 0.000 |
| 11 | untrusted_wrap | ✅ | 0.035 |
| 12 | patch_apply_rollback | ✅ | 0.044 |
| 13 | patch_reject_non_unique | ✅ | 0.004 |
| 14 | patch_reject_wrong_hash | ✅ | 0.007 |
| 15 | patch_dry_run_broken | ✅ | 0.035 |
| 16 | plan_simple_no_plan | ✅ | 0.001 |
| 17 | plan_complex_steps | ✅ | 0.000 |
| 18 | symbol_index_find | ✅ | 0.096 |
| 19 | tool_policy_read_allow | ✅ | 0.003 |
| 20 | tool_policy_untrusted_exec_deny | ✅ | 0.000 |

说明：这是**确定性回归基线**，不调用模型；用于每次改 Agent/补丁/权限逻辑后对比，不追求分数增长，只要求保持全绿。
