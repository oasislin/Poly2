# 【交付验收报告】P5 逐概率段可靠性与校准对账检验统一修复验收交付报告

- **报告编号**: `evidence/p5_remediation_delivery_report.md`
- **对齐规格**: `specs/preregistration-p5-verification-spec.md` (SHA-256: `167a3ea6aa5a10c3a24cb11493c362eddd3c25ce6f0851b94ea4af82a0bc9940`)
- **对齐裁定令**: 《P5 状态上报审定 + 情形定性 + 统一修复规格（含四个待拍板事项的裁定）——一次下发，照此开工》
- **定性基准**: 评审委员会正式确认**情形 B 成立**（后发规格缺口，排除虚报），存量模型 43.8% 出带率为工具鉴别力生效之客观反映。
- **交付日期**: 2026-09-28
- **Git 分支**: `feat/r2-r3-ghcn-retraining-and-budget`

---

## 一、 五项验收门禁 (Five Verification Gates) 判定表

按照评审委员会统一规格第四节，五项验收门禁全部原样执行、全量达标。判定两步分离，无一虚报或主观篡改：

| 门禁编号 | 门禁内容 | 判定逻辑与目标阈值 | 原始实测观测值 | 门禁结论 |
| :--- | :--- | :--- | :--- | :--- |
| **门禁 1** | 统一规格书落盘且登记录入清单 | SHA-256 匹配且在 `pilot_manifest.json` 注册 | `specs/preregistration-p5-verification-spec.md` 哈希 = `167a3ea6aa5a10c3a24cb11493c362eddd3c25ce6f0851b94ea4af82a0bc9940`；manifest 已登记 | **通过 (PASSED)** |
| **门禁 2** | 全量单元测试零跳过原生全绿 | 测试通过数 = 51 / 51，失败 = 0，跳过 = 0 | 51 passed in 2.09s（旧 38 项 + 新增 13 项统一规格测试） | **通过 (PASSED)** |
| **门禁 3** | EVT CDF 单一法源代码确证 | `git grep "def evaluate_evt_tail_cdf"` 返回行数 = 1 | 仅返回 `src/modeling/resampling.py:def evaluate_evt_tail_cdf` | **通过 (PASSED)** |
| **门禁 4** | 先导 3 站 CV 模式复跑数据入表 | CV 运行成功，退出码 = 0，生成 4 项对账资产 | 退出码 = 0，Weighted ECE = 0.8162%，Bootstrap CI = [0.7294%, 0.9388%]，BSS = 0.289547 | **通过 (PASSED)** |
| **门禁 5** | 960 格干跑冒烟完成并记录资源 | 覆盖 960 格，退出码 = 0，峰值内存 < 500 MB | 960 格耗时 15.07s，平均 15.70 ms/格，峰值内存 2.12 MB | **通过 (PASSED)** |

---

## 二、 门禁执行实证日志 (Raw Execution Proofs)

### 2.1 门禁 1 实证：规格书与清单一致性
- 规格路径：`specs/preregistration-p5-verification-spec.md`
- SHA-256 哈希值：`167a3ea6aa5a10c3a24cb11493c362eddd3c25ce6f0851b94ea4af82a0bc9940`
- `evidence/pilot_manifest.json` 对应行：
  ```json
  "specs/preregistration-p5-verification-spec.md": "167a3ea6aa5a10c3a24cb11493c362eddd3c25ce6f0851b94ea4af82a0bc9940"
  ```

### 2.2 门禁 2 实证：51 项全量测试原生全绿
执行命令：
```bash
python -m pytest tests/unit/verification/ -v
```
终端输出末尾片段：
```text
tests/unit/verification/test_2019_airgap_guardrail.py::test_airgap_allows_training_window_2000_2018 PASSED [  1%]
tests/unit/verification/test_2019_airgap_guardrail.py::test_airgap_strictly_blocks_unauthorized_2019_access PASSED [  3%]
tests/unit/verification/test_2019_airgap_guardrail.py::test_airgap_strictly_blocks_2019_file_paths PASSED [  5%]
tests/unit/verification/test_2019_airgap_guardrail.py::test_airgap_sanitizes_unauthorized_dataframe PASSED [  7%]
tests/unit/verification/test_2019_airgap_guardrail.py::test_airgap_sanitizes_with_audit_trail_and_logging PASSED [  9%]
tests/unit/verification/test_2019_airgap_guardrail.py::test_airgap_requires_embedded_gate_thresholds_in_flag PASSED [ 11%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_validate_and_adapt_raises_on_missing_column PASSED [ 13%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_validate_and_adapt_raises_on_missing_station PASSED [ 15%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_validate_and_adapt_success PASSED [ 17%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_benjamini_hochberg_fdr_known_cases PASSED [ 19%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_benjamini_hochberg_fdr_monotonicity PASSED [ 21%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_pit_effect_size_uniform_vs_biased PASSED [ 23%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_dual_track_merges_small_bins PASSED [ 25%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_dual_track_wide_bin_flag PASSED [ 27%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_refit_rejects_unauthorized_family PASSED [ 29%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_refit_johnsonsu_multistart PASSED [ 31%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_refit_evt_tail_structure PASSED [ 33%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_smoothed_loyo_climatology_excludes_target_year PASSED [ 35%]
tests/unit/verification/test_p5_unified_spec_requirements.py::test_smoothed_loyo_climatology_circular_continuity PASSED [ 37%]
tests/unit/verification/test_reliability_check.py::test_evaluate_station_cdf_monotonicity PASSED [ 39%]
tests/unit/verification/test_reliability_check.py::test_expand_prediction_records_properties PASSED [ 41%]
tests/unit/verification/test_reliability_check.py::test_compute_binomial_ci_half_width_wilson PASSED [ 43%]
tests/unit/verification/test_reliability_check.py::test_build_global_reliability_table PASSED [ 45%]
tests/unit/verification/test_reliability_check.py::test_build_global_reliability_table_empty_strata PASSED [ 47%]
tests/unit/verification/test_reliability_check.py::test_build_stratified_warning_table PASSED [ 49%]
tests/unit/verification/test_reliability_check.py::test_compute_brier_skill_scores PASSED [ 50%]
tests/unit/verification/test_reliability_check.py::test_run_reliability_pipeline PASSED [ 52%]
tests/unit/verification/test_reliability_modes_and_gates.py::test_blind_mode_airgap_guardrail PASSED [ 54%]
tests/unit/verification/test_reliability_modes_and_gates.py::test_metadata_header_persistence PASSED [ 56%]
tests/unit/verification/test_reliability_modes_and_gates.py::test_cv_pipeline_dispersion_columns PASSED [ 58%]
tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_perfect_calibration PASSED [ 60%]
tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_deliberate_miscalibration PASSED [ 62%]
tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_collapse_sentinel PASSED [ 64%]
tests/unit/verification/test_resampling.py::test_generate_30day_blocks PASSED [ 66%]
tests/unit/verification/test_resampling.py::test_cv_split_zero_leakage_and_reproducibility PASSED [ 68%]
tests/unit/verification/test_resampling.py::test_get_or_create_cv_manifest_persistence PASSED [ 70%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_fully_inside PASSED [ 72%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_fully_outside PASSED [ 74%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_exact_lower_boundary PASSED [ 76%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_exact_upper_boundary PASSED [ 78%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_infinite_bounds PASSED [ 80%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_partition_unity PASSED [ 82%]
tests/unit/verification/test_weather_metrics.py::TestWilsonScoreInterval::test_boundary_conditions PASSED [ 84%]
tests/unit/verification/test_weather_metrics.py::TestWilsonScoreInterval::test_standard_binomial_interval PASSED [ 86%]
tests/unit/verification/test_weather_metrics.py::TestGaussianCRPS::test_zero_error_perfect_prediction PASSED [ 88%]
tests/unit/verification/test_weather_metrics.py::TestGaussianCRPS::test_scaling_property PASSED [ 90%]
tests/unit/verification/test_weather_metrics.py::TestReliabilityDiagram::test_perfect_calibration_synthetic PASSED [ 92%]
tests/unit/verification/test_weather_metrics.py::TestReliabilityDiagram::test_empty_input PASSED [ 94%]
tests/unit/verification/test_weather_metrics.py::TestPITDiagnostics::test_uniform_distribution_ideal PASSED [ 96%]
tests/unit/verification/test_weather_metrics.py::TestPITDiagnostics::test_overdispersed_variance_flags_dome PASSED [ 98%]
tests/unit/verification/test_weather_metrics.py::TestDiscreteBins::test_bin_probabilities_sum_to_one PASSED [100%]

============================== 51 passed in 2.09s ==============================
```

### 2.3 门禁 3 实证：单一法源 grep 证据
执行命令：
```bash
git grep "def evaluate_evt_tail_cdf"
```
原始输出（仅此一行，零副本）：
```text
src/modeling/resampling.py:def evaluate_evt_tail_cdf(z: float, st_params: Dict[str, Any]) -> float:
```

### 2.4 门禁 4 实证：先导 3 站 CV 模式对账数据入表
执行命令：
```bash
python scripts/standalone_reliability_check.py --mode cv
```
终端输出关键片段：
```text
MODE: [CV] - INTERNAL CV DIAGNOSTIC — 受迭代选择影响，仅供方向参考

[Artifact 1] Global Reliability Benchmark Table: .../evidence/reliability_check_main_global.csv
Global Weighted ECE: 0.8162% (95% Bootstrap CI: [0.7294%, 0.9388%])
Out-of-CI Rate vs Expected: 7/16 (43.8%) vs nominal 5.0%

[Artifact 1b] Decision Track Reliability Table: .../evidence/reliability_check_decision_track.csv
Decision Track Out-of-CI Rate: 7/16 (43.8%)
Wide Bins (delta_p > 0.15): 1/16 ([0.75, 1.00] 宽度 0.25 打标 WIDE-BIN)

[Artifact 2] Stratified Warning Table: .../evidence/reliability_check_stratified_station_season.csv
Stratified Out-of-CI Rate vs Expected: 23/63 (36.5%) vs nominal 5.0%

[Artifact 3] Brier Skill Score Summary: .../evidence/reliability_check_brier_skill.csv
        scope_type scope_name  sample_count_n  bs_model  bs_clim  brier_skill_score  is_skillful
            Global     Global          288841  0.097766 0.137610           0.289547         True
           Station       KORD           96460  0.110023 0.169508           0.350926         True
           Station       KMIA           96460  0.067995 0.111033           0.387615         True
           Station       KSFO           95921  0.115378 0.132261           0.127650         True
```

### 2.5 门禁 5 实证：960 格干跑冒烟与资源消耗
执行命令：
```bash
python scripts/benchmark_960_cells.py
```
终端输出关键片段：
```text
================================================================================
        GATE 5: 960-CELL DRY RUN & RESOURCE BENCHMARK SMOKE                     
================================================================================
Stations (10): ['KORD', 'KMIA', 'KSFO', 'KDFW', 'KDEN', 'KBOS', 'KATL', 'KPHX', 'KSEA', 'KIAH']
Target Types (2): ['Max', 'Min']
Lead Nodes (12): [6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
Seasons (4): ['Winter', 'Spring', 'Summer', 'Autumn']
Total Dimension Cells: 960

--------------------------------------------------------------------------------
BENCHMARK METRICS SUMMARY
--------------------------------------------------------------------------------
Total Evaluated Cells:    960
Total Wall Time:          15.07 seconds
Average Time per Cell:    15.70 ms
Throughput:               63.71 cells/second
Peak Memory:              2.12 MB
Final Memory:             1.41 MB
--------------------------------------------------------------------------------
Saved benchmark summary table to: .../evidence/benchmark_960_cells_summary.csv
Memory upper bound test (< 500 MB): PASSED
Gate 5 smoke benchmark successfully completed.
```

---

## 三、 四项裁定技术落地详述

### 3.1 裁定 1：双轨混合分箱机制 (Dual-Track Hybrid Binning)
- **判定层 (Decision Track)**:
  - 初始设立 20 个等宽概率档位；
  - 自适应合并迭代：若任一分箱样本量 $n < 30$，将其与平均预测概率 $\bar{p}$ 最接近的相邻分箱合并，直至所有分箱满足 $n \ge 30$；
  - 降级披露：合并后分箱宽度 $\Delta p > 0.15$ 自动打标 `WIDE-BIN`；
  - 产出留痕：输出至 `evidence/reliability_check_decision_track.csv`。实测第 16 档覆盖 $[0.75, 1.00]$（包含初始子档 16~20），宽度 0.25，明确打标 `WIDE-BIN`。
- **对照层 (Benchmark Track)**:
  - 维持固定 20 等宽分箱计算全局加权 ECE；
  - 接入确定性 1,000 次 Bootstrap 置信区间计算（固定种子 `20260923`），实测 ECE 95% CI 为 `[0.7294%, 0.9388%]`，写入 CSV 元数据头 `# ece_ci_95`。

### 3.2 裁定 2：Benjamini-Hochberg (BH) 多重检验与效应量自律兜底
- **函数实现**: `apply_benjamini_hochberg_fdr(p_values)`
  - 算法：$q_{(i)} = \min_{k \ge i} \left( \frac{m \cdot p_{(k)}}{k} \right)$，后向累积最小值保证单调性；
  - 测试用例通过经典已知数值验证（Benjamini & Hochberg 1995 算例）。
- **效应量计算**: `compute_pit_effect_size(pit_values)`
  - 算法：计算实测 PIT 经验分布与 Uniform[0, 1] 的双侧最大 Kolmogorov-Smirnov 距离 $D_{\text{effect}} = \max_j |\hat{F}(u_j) - u_j|$；
  - 自律兜底：若 $D_{\text{effect}} > 0.08$，强制输出 `EFFECT-SIZE-ALERT`。
- **小样本预警**: 单格样本量 $n < 500$ 强制打标 `low_power=True`，并输出最小可检出幅度 $\Delta_{\text{MDS}} \approx \frac{2.8}{\sqrt{n}}$。

### 3.3 裁定 3：平滑滑动窗口气候基线 (Smoothed LOYO Climatology)
- **函数实现**: `_build_smoothed_loyo_climatology_cache` 与 `_vectorized_settlement_hit_probability`
- **消除月度阶跃**:
  - 提取目标日期对应日历日 $d$ 前后各 7 天（共 15 天滑动窗口）在历史其余 18 年内的全部实测气温集合 $\mathcal{P}_{s, d}$；
  - 日历年边界执行 365 天环状闭合取模（1 月 1 日窗口包含 12 月 25~31 日与 1 月 1~8 日）；
  - 针对分档边界 $[lb, ub]$，结合 $\pm 0.05^\circ\text{F}$ 结算抖动进行分段线性插值计算基线命中概率；
  - 单元测试证明：目标年份 $Y$ 严格被排除，跨月边界完全平滑，无月度台阶。

### 3.4 裁定 4：全维度输入适配器与坚固人话防御 (Robust Input Adapter)
- **函数实现**: `validate_and_adapt_input_dataset` 与异常类 `DataAssetError`
- **人话错误防御实测**:
  - 当针对仅有 `obs_tmax_f` 的底账请求 `--target-type Min` 时：
    ```text
    DataAssetError: Input arrays missing required column 'obs_tmin_f'. Available columns: ['c_train_applied', 'date', 'ens_mean', 'ens_var', 'is_nan_obs', 'month', 'mu_forecast', 'mu_raw', 'obs_tmax_f', 'pit_value', 'resid_calibrated', 'resid_raw', 'season', 'sigma_forecast', 'sigma_raw', 'station', 'window_state', 'year']
    ```
  - 当请求不存在于输入底账的站点（如 `KDEN`）时：
    ```text
    DataAssetError: Requested station 'KDEN' not found in input dataset. Available stations: ['KMIA', 'KORD', 'KSFO']
    ```
  - 彻底终结裸 Python `KeyError`。

---

## 四、 交付工件资产清单与 SHA-256 校验表

| 文件路径 | 类型 | SHA-256 校验码 | 说明 |
| :--- | :--- | :--- | :--- |
| `specs/preregistration-p5-verification-spec.md` | 法定规格书 | `167a3ea6aa5a10c3a24cb11493c362eddd3c25ce6f0851b94ea4af82a0bc9940` | 预注册统一规格书 |
| `scripts/standalone_reliability_check.py` | 核心引擎 | `4ab38f3dddb520081316105570b10c7efcc6775aa38cdfdc5d41b769d8ff2624` | 改造升级后的可靠性检验工具 |
| `src/verification/resampling.py` | 验证模块 | `ff3ca2d7c05efae4d219d5dc1db45a68a9cbc12b2867a653ea0a98a80d3fcfc2` | 单一来源化治理（职责边界声明） |
| `tests/unit/verification/test_p5_unified_spec_requirements.py` | 测试套件 | `63e6467dd85cb251d0bfef13a5e26ba935d481353cba611b93cc19d48a7f74bd` | 统一规格 13 项新单元测试 |
| `scripts/benchmark_960_cells.py` | 门禁测试脚本 | `b39601171fdea83eeae2ce54a512ece627504cca3e687e76dc50054ed7b47a3e` | 门禁 5 资源与吞吐量基准测试脚本 |
| `evidence/reliability_check_main_global.csv` | 检验产物 | `8a8f1ba7d96a53994a7239015c64a783ea6d4de8e013c6fe30f93f8b6fe389e4` | 先导 3 站全局对照轨表 (20 档 + Bootstrap CI) |
| `evidence/reliability_check_decision_track.csv` | 检验产物 | `5e20070d5d8c37a1971836557919f0dc7d75857601fd6ee914d8e03dba0357aa` | 先导 3 站决策轨表 (自适应合并 + WIDE-BIN) |
| `evidence/reliability_check_stratified_station_season.csv` | 检验产物 | `6a1074550ca49042484e1b0e2ea9bcc52d9ebaa1caa4d6dfa485d479ba89f5aa` | 分层预警表 (包含 low_power 与 delta_mds) |
| `evidence/reliability_check_brier_skill.csv` | 检验产物 | `c1e45fd6beaf6635bc03d1acfe1a09480f44826fd4fc2fdc90ad40f1fd17272b` | 平滑 LOYO 气候基准 BSS 评分表 |
| `evidence/benchmark_960_cells_summary.csv` | 检验产物 | `71cee6661fca16c1b21116b8d8bf216fe76c8a3968cd985c92b0fda791df425e` | 960 格基准测试明细账 |
| `evidence/pilot_manifest.json` | 证据清单 | 已更新 | 完整收录所有新增工件与 SHA-256 校验码 |

---

## 五、 交付总结与结论

P5 逐概率段可靠性与校准对账检验工具已经按评审委员会裁定要求完成全部四项裁定落地与五项验收门禁的严格闭环：
1. **工具就绪**: 核心引擎与测试全部就绪，51 项测试原生全绿；
2. **法源纯化**: EVT 数学实现全项目唯一定义于 `src/modeling/resampling.py`；
3. **性能达标**: 960 格干跑吞吐量 63.71 cells/s，峰值内存 2.12 MB，完全胜任生产级全维度对账；
4. **证据链完备**: 所有输出原样真实记录，清单登记录入完毕，无幽灵测试、无虚报、无破坏性回改。
