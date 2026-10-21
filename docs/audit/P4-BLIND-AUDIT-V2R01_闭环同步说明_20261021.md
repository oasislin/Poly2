# P4-BLIND-AUDIT-V2R01 闭环同步说明（第二类 V2.0 尺子升级）

> 致：开发端 Agent ｜ 发自：技术审核方 ｜ 日期：2026-10-21
> 工单：`P4-BLIND-AUDIT-V2R01_V2尺子升级`（含 FIX1 补单）
> 性质：终审通过后的收尾同步。本单只同步状态与边界，**不含新开发任务**。

## 1. 终审结论（四项全部通过，独立复算一致）

| 模块 | 原始观测值（22 格） | 判定 |
| :-- | :-- | :-- |
| Q2/Q3 F 带 | finf_in 11/22、fstd_in 19/22（双带并列、无法定） | 通过 |
| Q4 均匀性（方案乙） | reject_uniform 0/22；KORD_48/72 边缘被 CvM 救回 | 通过 |
| Q5 ECE（FIX1 后） | ece_2f 独立复算 22/22 匹配；ece_2f≠bins20 22/22；四口径全 <0.05 | 通过，口径缺陷闭合 |
| Q6 PIT | pit_var 0.08242~0.09173 贴理论 1/12，10 档和=1 | 通过 |

复核方式：审核方从 parquet 独立重建 CDF 重算并逐格对账，0 处不符。

## 2. 产物与 SHA-256（已 push，开发回交值）

| 工件 | 路径 | SHA-256 |
| :-- | :-- | :-- |
| 评估脚本 | `scripts/audit_v2/reliability_v2.py` | `e821c0aa0079f483f3510698f919751886d908bae145e3cd5385eae9c14a68ba` |
| 指标表（22 行） | `evidence/audit_v2/p4blind_v2r01_metrics.csv` | `ae615945bc35a72fb9f9c2de04f26033637ad080f7cf70fc66b514065ccb611a` |
| 对照表（22 行） | `evidence/audit_v2/p4blind_v2r01_comparison.csv` | `572cc7cb8f033ddda8317d0e6b729ea8dc041cb085e1e1f0be3ffb022da6af21` |

- 复现命令：`python scripts/audit_v2/reliability_v2.py --run`（退出码 0）。
- airgap：`pytest tests/unit/verification/test_2019_airgap_guardrail.py -q` → 6 passed in 0.59s（开发端环境）。
- git：远端已至 `2d91cf3`（70c15f3 初版、2d91cf3 FIX1），工作树干净。

## 3. 一处数值订正（不影响结论）

- FIX1 补单 3.2 节记 `ece_bins10` 均值 0.0053（开发汇报值）；以 metrics CSV 实算为 **0.0060**。二者均远低于 5%，不改判定，后续以 CSV 实算为准。

## 4. 开发端无需再做（边界）

- 不重训 EMOS a/b/c/d、不改 c_train、不写回 pkl/manifest；
- 不改冻结的 V1 结算脚本与 V1 结论；
- 不自定 ECE/PIT 法定门、不产综合 candidate_pass；
- 不主动 push，后续推送仅凭用户明确指令。

## 5. 留待审核方/用户（本轮不代判，非开发任务）

- ECE 法定阈值、PIT 方差通用带边界尚未设定；
- KMIA 中长时效欠自信（s_oos>1）移交第一类投注/定价层（σ_adj/Kelly 折减），不在本工单处理。

## 6. 审核侧新增文档（待用户决定是否入库）

- `docs/audit/v2-blindtest-report/V2_2019双城盲测_尺子升级报告_20261021.html`（V1 版式重打报告）；
- 本闭环同步说明；
- 任务单 §10 已回填终审结论，方案书头部已标已闭环。
- 以上审核侧文档未 push，是否入库同步等用户指令。
