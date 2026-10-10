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

## 二、 封盘门禁九项检查表 (The 9 Sealing Gates)

| 序号 | 门禁检查项 | 当前状态 | 状态确认文件路径 | 判定依据与核验口径 |
| :---: | :--- | :---: | :--- | :--- |
| **01** | **阶段 1 三条件**<br>(候选集取证 / 逐日预测表哈希门禁 / 断点续跑) | **✓ 已完成**<br>(Passed) | • [`tests/unit/modeling/test_p6_zero_drift_gate.py`](../tests/unit/modeling/test_p6_zero_drift_gate.py)<br>• [`evidence/p4_audit_reliability_v13b_lineage.json`](../evidence/p4_audit_reliability_v13b_lineage.json)<br>• [`scripts/run_p6_fullgrid_tmax.py`](../scripts/run_p6_fullgrid_tmax.py) | 候选分布族确证 (Gaussian / Johnson SU / EVT Hybrid)；13,740 逐日样本血统 SHA256 逐位一致；断点续跑机制落盘。 |
| **02** | **P6-EVT-GUARD + P6-EVT-FIX 闭环**<br>(代码缺陷修补与存量资产解禁) | **✓ 已完成**<br>(Released) | • [`evidence/evt_path_validation_report.md`](../evidence/evt_path_validation_report.md)<br>• [`evidence/p6_evt_fix_remediation_report.md`](../evidence/p6_evt_fix_remediation_report.md)<br>• [`tests/unit/verification/test_evt_path_validation.py`](../tests/unit/verification/test_evt_path_validation.py)<br>• [`EVIDENCE_INDEX.md`](../EVIDENCE_INDEX.md) (P6-EVT-G1, P6-EVT-F1) | 落地 Scheme B 条件高斯重标截断，10 项扩展契约测试 100% 全绿；KATL/KDAL/KLAX/KSFO 四格全域积分恢复精确 1.00000000，边界跳跃清零，解除隔离放行。 |
| **03** | **92 格跑数 + 逐格 KS 诊断**<br>(双城全网格 20 折 Block-CV) | **✓ 已完成**<br>(Passed) | • [`evidence/fullgrid_tmax/PROGRESS.json`](../evidence/fullgrid_tmax/PROGRESS.json)<br>• [`evidence/p6_fullgrid_96cells_summary.json`](../evidence/p6_fullgrid_96cells_summary.json)<br>• [`evidence/fullgrid_tmax/`](../evidence/fullgrid_tmax/) (逐格 summary 与 parquet) | 目标 96 季节格（24 时间格）100% 跑数完毕。KORD 12 格全部放行（11 高斯 + 1 JSU）；KMIA 12 格全部放行（1 EVT + 1 混合 JSU/EVT + 10 JSU）。24 格中 23 格加权 ECE $\le 0.0100$ 达标（达标率 95.83%），1 格（KMIA_12h 0.0183）挂旗入账（触发器计数 1/2，未达 2 格立项门槛）。 |
| **04** | **KORD 12h~36h KS≈0 反差专项解释**<br>(超额峰度与近时效离散反差) | **📌 已挂账**<br>(Booked) | • [`evidence/p6_heavytail_diag_report.md`](../evidence/p6_heavytail_diag_report.md)<br>• [`evidence/p6_heavytail_diag_results.json`](../evidence/p6_heavytail_diag_results.json)<br>• [`STATUS.md`](../STATUS.md) (KORD 42h 厚尾归因拆层记录) | 四件套机制诊断证实残差厚尾由极少数孤立失准日主导；事实层（超额峰度增长）与假说层严格拆层，已在对账表与封盘文档统一收口。 |
| **05** | **KMIA 数据覆盖取证**<br>(迈阿密站址与对流机制升级放行前置) | **✓ 已完成**<br>(Released) | • [`evidence/p6_window_forensic_report.md`](../evidence/p6_window_forensic_report.md)<br>• [`evidence/kmia_12h_gate_report.md`](../evidence/kmia_12h_gate_report.md)<br>• [`evidence/kmia_36h_split_audit_report.md`](../evidence/kmia_36h_split_audit_report.md) | 78.72 物理年（口径 A）与 19.00 训练日历年（口径 B）双录通过立法解释；Airgap 严格隔离；对流昼夜谐波与正午峰度周期确证，J2 门槛受控修订入册。 |
| **06** | **全量回归基线零变更证明**<br>(970 项历史测试无退化) | **✓ 已完成**<br>(Passed) | • 执行命令：`pytest tests/ -q`<br>• [`tests/unit/modeling/test_p6_zero_drift_gate.py`](../tests/unit/modeling/test_p6_zero_drift_gate.py) | 960 passed, 10 skipped, 0 failed；KORD 18h TMax 关键审计指标逐位无漂移（加权 ECE 0.0029，KS p 0.46915，偏度 0.0471，峰度 0.0667）。 |
| **07** | **封盘文档条款落盘**<br>(EVT 完整叙事 / 厚尾拆层 / 昼夜谐波 / 已知限制 / 池化 6h 审计) | **✓ 已完成**<br>(Passed) | • [`evidence/p6_tmax_methodology_closure.md`](../evidence/p6_tmax_methodology_closure.md)<br>• [`evidence/p6_tmax_methodology_closure.json`](../evidence/p6_tmax_methodology_closure.json)<br>• [`evidence/p6_pool6h_audit_report.md`](../evidence/p6_pool6h_audit_report.md) | 24 格数据与 6h 池化回退层 100% 闭环收口。封盘法定报告完整包含两段式家族选择披露、昼夜谐波与正午周期统一解释、A1 残差相位分解对照表（4.2 节谐波外推证据）、24 格唯一事实层对账表、三层真相注、方法论注记 4（AC-3 衰减缺口与实况硬截断兜底）、已知限制与后向研发议题扩项（P6-POOL-PHASE 并入 TMax 衰减缺口评估）。 |
| **08** | **尾单：P6-CALM-OUTLIER**<br>(平静日极端失准事前指纹与 Regime 模型) | **✓ 已完成**<br>(Passed) | • [`STATUS.md`](../STATUS.md) (待办事项)<br>• [`EVIDENCE_INDEX.md`](../EVIDENCE_INDEX.md) (条目 P6-CALM-1)<br>• [`evidence/p6_calm_outlier_precheck_report.md`](../evidence/p6_calm_outlier_precheck_report.md) | 尾单法定重新呈报闭环；确证稀疏极端日支配厚尾与平静日特征；呈报 5 元组实证、清晨中性相位（sigma_ens < 0.50°F）与 2°F 整度判定几何边界伪影证据；作为封盘已知限制入档，登记封盘后研究议题。 |
| **09** | **出域同步状态**<br>(远端 main 与本地账本一致性) | **✓ 已完成**<br>(Passed) | • [`docs/SYNC_POLICY.md`](SYNC_POLICY.md)<br>• [`evidence/p7_sync_bridge_audit.md`](../evidence/p7_sync_bridge_audit.md)<br>• PR #128 合流提交 (`4824edb`) | 172 采样文件本地↔远端 100% 一致 (0 mismatch)；主干 PR #128 经委员会核准合入；建立 Git LFS 分层存储与“未验收不出域、验收必出域”法定机制，封盘证据链具备外部审计完备性。 |

---

## 三、 三处固定锚点与两份关键规格路径速查

1. **三处固定状态锚点**：
   - 锚点 ①：[`STATUS.md`](../STATUS.md) —— 项目最高状态入口（登记阶段、活跃工作流、红线、P6-CALM-OUTLIER 防删挂账）。
   - 锚点 ②：[`EVIDENCE_INDEX.md`](../EVIDENCE_INDEX.md) —— 法定工件证据索引表（登记各工单报告路径与 SHA256 签名）。
   - 锚点 ③：[`evidence/fullgrid_tmax/PROGRESS.json`](../evidence/fullgrid_tmax/PROGRESS.json) —— 92 格运算状态机动态断点库（逐格胜出模型、指标与 backlog 挂账）。

2. **两份关键规格与交接协议**：
   - 规格书：[`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md)（冻结 EVT 门槛原文 $|\text{Skew}| > 0.40$ 与 $\text{Kurt}_{\text{excess}} > 1.0$）。
   - 交接书：[`evidence/handoff_p6_tmax_fullgrid.md`](../evidence/handoff_p6_tmax_fullgrid.md)（阶段 1 三条件、零漂移门禁、升级触发条件）。
