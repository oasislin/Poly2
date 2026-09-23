# Polymarket 气象概率量化系统修复轮工件索引表 (Evidence Index)

- **当前版本**: v3.0 (依据《修复轮指令 v3》D-1 ~ D-6 归正建立)
- **唯一法定结算凭据**: [`recompute_settlement_report.md`](recompute_settlement_report.md)
- **校验和清单文件**: [`pilot_manifest.json`](pilot_manifest.json)

---

## 阶段索引导航

### 一、R-1 单位与舍入约定核查 (已验收闭环)
- [`r1_unit_and_rounding_audit.txt`](r1_unit_and_rounding_audit.txt): R-1 逐行对照与排除性执行记录。

### 二、P 系列：真值数据资产建设 (已验收闭环)
- [`p1_decision_summary.md`](p1_decision_summary.md): GHCN-Daily 全量采集决策与断点声明。
- [`p1_download_metrics.csv`](p1_download_metrics.csv) & [`p1_bulk_download_log.csv`](p1_bulk_download_log.csv): 2000–2019 三站下载指标与日志。
- [`p2_qc_summary.md`](p2_qc_summary.md): 质检分析与 KSFO 2018 年 20 天物理缺报确认报告。
- [`p3_truth_manifest.json`](p3_truth_manifest.json): GHCN-Daily 原始工件哈希清单。

### 三、R-2 ~ R-5：偏差消解与门禁重标定
- [`recompute_settlement_report.md`](recompute_settlement_report.md): **【全项目唯一法定结算表】**（无 2019 前瞻泄漏，冻结 $c_{\text{train}}$ 版）。
- [`r2_r3_diagnosis_and_budget_report.md`](r2_r3_diagnosis_and_budget_report.md): 切靶消解预算、厚尾分析与冷偏差诊断报告。
- [`r2_target_switch_budget.csv`](r2_target_switch_budget.csv): **[REFERENCE ONLY]** 探针辅助测算表（已废除 `final_` 列名）。
- [`r4_ece_definition_audit.md`](r4_ece_definition_audit.md): ECE 算法实现一致性审计报告。
- [`r4_gate_calibration_protocol.md`](r4_gate_calibration_protocol.md): 新门禁阈值数理溯源与标定协议。
- [`pit_histograms.svg`](pit_histograms.svg) & [`reliability_diagrams.svg`](reliability_diagrams.svg): 矢量可视化图表。

### 四、D 系列：底层数据解耦披露与第三方独立复算 (指令 v3 核心)
- **D-1 审计数组与独立复算**:
  - `data/processed/audit_arrays/2000_2018_training_arrays.parquet` (20,820 行训练数组)
  - `data/processed/audit_arrays/2019_oos_evaluation_arrays.parquet` (1,095 行 OOS 评估数组)
  - [`../scripts/standalone_recompute_evaluation.py`](../scripts/standalone_recompute_evaluation.py): 零私有依赖独立复算脚本。
  - [`recomputed_statistics.csv`](recomputed_statistics.csv): 独立复算输出的机器可读统计值。
- **D-2 法定结算表唯一性**:
  - 确立 [`recompute_settlement_report.md`](recompute_settlement_report.md) 为唯一法定标准。
- **D-3 数字冲突对账与状态映射**:
  - [`d3_conflict_reconciliation.md`](d3_conflict_reconciliation.md): 跨文件数字冲突根因剖析与训练窗外生性声明。
- **D-4 SPECI 分解表断点重制**:
  - [`r2_speci_all_hourly_yearly_breakdown.csv`](r2_speci_all_hourly_yearly_breakdown.csv) & [`r2_speci_yearly_pivot.csv`](r2_speci_yearly_pivot.csv): 标注 2000-2015 归档断点边界声明。
- **D-5 ECE 统计规范与门禁仲裁**:
  - [`../docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md`](../docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md): 彻底纠正“中心档 ECE = 尖锐度”错误，确立 7 档位加权 ECE 为法定主门禁 ②。
- **D-6 防泄漏架构与代码变更留痕**:
  - [`../scripts/fit_training_variance_factors.py`](../scripts/fit_training_variance_factors.py): 训练窗方差拟合脚本。
  - [`training_variance_factors.json`](training_variance_factors.json): 2000–2018 拟合并冻结的 $c_{\text{train}}$。
  - [`d6_code_change_audit_trail.md`](d6_code_change_audit_trail.md): 变更留痕、代码 Diff 与 SHA256 清单。
