# 方法论封盘门禁总清单 (Sealing Gate Checklist)

> **目标任务**：Phase 6 双城 (KORD / KMIA) TMax 全网格验证与方法论封盘 (P6-2)  
> **单一入口**：本文件为封盘门禁法定全局总对账单。下次会话启动时，只需输入下方标准召回指令即可恢复全部上下文。  
> **前置规格与交接协议**：
> 1. 预注册规格书（冻结 EVT 门槛原文）：[`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md)
> 2. 双城主线交接协议（零漂移门禁与升级路径）：[`evidence/handoff_p6_tmax_fullgrid.md`](../evidence/handoff_p6_tmax_fullgrid.md)

---

## 一、 快速恢复指令（下次回来只需输入这一句话）

> **“读 STATUS.md 和 docs/SEALING_GATE.md，报告封盘门禁当前完成到哪一项、下一项是什么、有没有阻塞。”**

---

## 二、 封盘门禁八项检查表 (The 8 Sealing Gates)

| 序号 | 门禁检查项 | 当前状态 | 状态确认文件路径 | 判定依据与核验口径 |
| :---: | :--- | :---: | :--- | :--- |
| **01** | **阶段 1 三条件**<br>(候选集取证 / 逐日预测表哈希门禁 / 断点续跑) | **✓ 已完成**<br>(Passed) | • [`tests/unit/modeling/test_p6_zero_drift_gate.py`](../tests/unit/modeling/test_p6_zero_drift_gate.py)<br>• [`evidence/p4_audit_reliability_v13b_lineage.json`](../evidence/p4_audit_reliability_v13b_lineage.json)<br>• [`scripts/run_p6_fullgrid_tmax.py`](../scripts/run_p6_fullgrid_tmax.py) | 候选分布族确证 (Gaussian / Johnson SU / EVT Hybrid)；13,740 逐日样本血统 SHA256 逐位一致；断点续跑机制落盘。 |
| **02** | **P6-EVT-GUARD + P6-EVT-FIX 闭环**<br>(代码缺陷修补与存量资产解禁) | **✓ 已完成**<br>(Released) | • [`evidence/evt_path_validation_report.md`](../evidence/evt_path_validation_report.md)<br>• [`evidence/p6_evt_fix_remediation_report.md`](../evidence/p6_evt_fix_remediation_report.md)<br>• [`tests/unit/verification/test_evt_path_validation.py`](../tests/unit/verification/test_evt_path_validation.py)<br>• [`EVIDENCE_INDEX.md`](../EVIDENCE_INDEX.md) (P6-EVT-G1, P6-EVT-F1) | 落地 Scheme B 条件高斯重标截断，10 项扩展契约测试 100% 全绿；KATL/KDAL/KLAX/KSFO 四格全域积分恢复精确 1.00000000，边界跳跃清零，解除隔离放行。 |
| **03** | **92 格跑数 + 逐格 KS 诊断**<br>(双城全网格 20 折 Block-CV) | **⏸ 进行中 (冻结)**<br>(Triggered Frozen) | • [`evidence/fullgrid_tmax/PROGRESS.json`](../evidence/fullgrid_tmax/PROGRESS.json)<br>• [`evidence/fullgrid_tmax/`](../evidence/fullgrid_tmax/) (逐格 summary 与 parquet) | 目标 96 格（复用 KORD 18h 四季，实际新增 92 格）。KORD 11 格已跑完；KMIA 12h 触发 `winner_family == "evt_hybrid"`，依据 handoff 第七条进入待裁决升级冻结。 |
| **04** | **KORD 12h~36h KS≈0 反差专项解释**<br>(超额峰度与近时效离散反差) | **📌 已挂账**<br>(Booked) | • [`evidence/p6_heavytail_diag_report.md`](../evidence/p6_heavytail_diag_report.md)<br>• [`evidence/p6_heavytail_diag_results.json`](../evidence/p6_heavytail_diag_results.json)<br>• [`STATUS.md`](../STATUS.md) (KORD 42h 厚尾归因拆层记录) | 四件套机制诊断证实残差厚尾由极少数孤立失准日主导；事实层（超额峰度增长）与假说层严格拆层，待封盘法定文档统一收口。 |
| **05** | **KMIA 数据覆盖取证**<br>(迈阿密站址与对流机制升级放行前置) | **⚠️ 放行前置**<br>(Escalation Prerequisite) | • [`evidence/handoff_p6_tmax_fullgrid.md`](../evidence/handoff_p6_tmax_fullgrid.md) (第七条升级路径第一款)<br>• [`evidence/fullgrid_tmax/PROGRESS.json`](../evidence/fullgrid_tmax/PROGRESS.json) (KMIA_12h 节点指标) | KMIA 12h 胜出 EVT Hybrid 触发红线。需排查 GHCN-Daily 观测历史是否存在数据争议，并向委员会呈报海陆风午后对流机制判定，获批后方可放行。 |
| **06** | **全量回归基线零变更证明**<br>(970 项历史测试无退化) | **✓ 已完成**<br>(Passed) | • 执行命令：`pytest tests/ -q`<br>• [`tests/unit/modeling/test_p6_zero_drift_gate.py`](../tests/unit/modeling/test_p6_zero_drift_gate.py) | 960 passed, 10 skipped, 0 failed；KORD 18h TMax 关键审计指标逐位无漂移（加权 ECE 0.0029，KS p 0.46915，偏度 0.0471，峰度 0.0667）。 |
| **07** | **封盘文档条款落盘**<br>(EVT 完整叙事 / 厚尾拆层 / 已知限制) | **📝 待编制**<br>(Pending Full-Grid) | • `evidence/p6_tmax_methodology_closure.md` (待落盘)<br>• `evidence/p6_tmax_methodology_closure.json` (待落盘) | 待 92 格跑数与升级项闭环后编制。条款必须包含：Scheme B EVT 叙事、厚尾拆层措辞、以及已知限制（显式回填 P6-CALM-OUTLIER 结案结论）。 |
| **08** | **尾单：P6-CALM-OUTLIER**<br>(平静日极端失准事前指纹与 Regime 模型) | **📌 已法定登记**<br>(Backlog Anti-Deletion) | • [`STATUS.md`](../STATUS.md) (待办事项第 15-20 行)<br>• [`EVIDENCE_INDEX.md`](../EVIDENCE_INDEX.md) (条目 P6-CALM-1)<br>• [`evidence/fullgrid_tmax/PROGRESS.json`](../evidence/fullgrid_tmax/PROGRESS.json) (backlog 字段) | 最高防删条款生效：完成 92 格主线后、封盘签署前，必须作为独立议题重新呈上委员会。全程只读生产工件，禁止引入剔除/补偿生产补丁。 |

---

## 三、 三处固定锚点与两份关键规格路径速查

1. **三处固定状态锚点**：
   - 锚点 ①：[`STATUS.md`](../STATUS.md) —— 项目最高状态入口（登记阶段、活跃工作流、红线、P6-CALM-OUTLIER 防删挂账）。
   - 锚点 ②：[`EVIDENCE_INDEX.md`](../EVIDENCE_INDEX.md) —— 法定工件证据索引表（登记各工单报告路径与 SHA256 签名）。
   - 锚点 ③：[`evidence/fullgrid_tmax/PROGRESS.json`](../evidence/fullgrid_tmax/PROGRESS.json) —— 92 格运算状态机动态断点库（逐格胜出模型、指标与 backlog 挂账）。

2. **两份关键规格与交接协议**：
   - 规格书：[`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md)（冻结 EVT 门槛原文 $|\text{Skew}| > 0.40$ 与 $\text{Kurt}_{\text{excess}} > 1.0$）。
   - 交接书：[`evidence/handoff_p6_tmax_fullgrid.md`](../evidence/handoff_p6_tmax_fullgrid.md)（阶段 1 三条件、零漂移门禁、升级触发条件）。
