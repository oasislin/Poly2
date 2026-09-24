# Phase 2 Task 01: P4 Active 10 全站 960 格物理概率模型重训与交付评审报告

- **报告编号**: `POLY-R2-P4-DELIVERY-001`
- **执行时间**: 2026-09-24T12:03:50+08:00
- **执行规格**: [`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md) (SHA-256: `b607cc609dd7c6a449b0576b7832f067badad16318534ef0c06b4f61101e9247`)
- **执行脚本**: [`scripts/retrain_p4_active10_matrix.py`](../scripts/retrain_p4_active10_matrix.py)
- **研发环境约束**: 严格限定于 2000–2018 历史训练窗；2019 样本外盲测窗维持硬闸物理封存（Airgap Guardrail Active）。

---

## 一、 执行概要与运行证据

依据评审委员会终审签认指令，重训引擎已完成全站矩阵拟合，客观执行证据如下：

| 项目 | 记录值 | 说明 / 来源 |
| :--- | :--- | :--- |
| **执行命令** | `python3 scripts/retrain_p4_active10_matrix.py` | 独立全网格拟合执行命令 |
| **任务编号** | `task-627` | 系统后台任务标识 |
| **日志路径** | `.system_generated/tasks/task-627.log` | 完整标准输出与错误流记录 |
| **执行耗时** | 4 分 47 秒 | 2026-09-24 11:59:03 ~ 12:03:50 |
| **进程退出码** | `0` | 执行成功，无异常中断 |

### 终端关键日志原始输出
```text
2026-09-24 11:59:03,699 [INFO] ================================================================================
2026-09-24 11:59:03,699 [INFO]   STARTING P4 ACTIVE 10 960-MODEL MATRIX RETRAINING (Spec b607cc60...e9247)   
2026-09-24 11:59:03,699 [INFO] ================================================================================
2026-09-24 11:59:03,709 [INFO] Loaded 800 statutory trading master keys from baseline archive.
[1/10] Processing Station: KORD (2000-2018 Training Window)...
[2/10] Processing Station: KLGA (2000-2018 Training Window)...
[3/10] Processing Station: KATL (2000-2018 Training Window)...
[4/10] Processing Station: KDAL (2000-2018 Training Window)...
[5/10] Processing Station: KSEA (2000-2018 Training Window)...
[6/10] Processing Station: KLAX (2000-2018 Training Window)...
[7/10] Processing Station: KHOU (2000-2018 Training Window)...
[8/10] Processing Station: KMIA (2000-2018 Training Window)...
[9/10] Processing Station: KSFO (2000-2018 Training Window)...
[10/10] Processing Station: KAUS (2000-2018 Training Window)...
2026-09-24 12:03:50,146 [INFO] ================================================================================
2026-09-24 12:03:50,146 [INFO]   960-MODEL MATRIX RETRAINING COMPLETE: ALL MODELS PERSISTED TO data/models/     
2026-09-24 12:03:50,146 [INFO]   - Total Retrained Models: 960 / 960
2026-09-24 12:03:50,146 [INFO]   - Statutory Trading Master Nodes: 800
2026-09-24 12:03:50,146 [INFO]     * Independent Fit (N >= 100): 720
2026-09-24 12:03:50,146 [INFO]     * Pooled Fallback (N < 100): 80
2026-09-24 12:03:50,146 [INFO]   - Auxiliary Nodes (AUXILIARY_POOLED_FALLBACK): 160
2026-09-24 12:03:50,146 [INFO] ================================================================================
2026-09-24 12:03:50,223 [INFO] Saved Distribution Selection Audit Log: evidence/p4_distribution_selection_audit.csv
2026-09-24 12:03:50,224 [INFO] Saved Training Variance Factors: evidence/p4_active10_training_variance_factors.json
2026-09-24 12:03:50,225 [INFO] Saved Climate Calibration: evidence/p4_active10_climate_calibration.json
2026-09-24 12:03:50,232 [INFO] Saved Updated Model Inventory Audit: evidence/model_inventory_audit.csv
2026-09-24 12:03:50,232 [INFO] Saved Anchor Reconciliation Report: evidence/p4_anchor_reconciliation_report.md
2026-09-24 12:03:50,233 [INFO] ================================================================================
2026-09-24 12:03:50,233 [INFO]   P4 RETRAINING EXECUTION FULLY ACCOMPLISHED (STATUS: SUCCESS)                   
2026-09-24 12:03:50,233 [INFO] ================================================================================
```

---

## 二、 机械两步分离判定（原始观测值 vs 判定阈值）

依据 `AGENTS.md` 硬性规范，执行结果判定严格采用机械比对：

1. **重训模型总数**：
   - `原始观测值 = 960`；`判定阈值 = 960`；`结论 = 通过`
2. **法定交易主节点 (STATUTORY_TRADING_MASTER) 数量**：
   - `原始观测值 = 800`；`判定阈值 = 800`；`结论 = 通过`
3. **独立拟合单元数 ($N_{\text{valid}} \ge 100$)**：
   - `原始观测值 = 720`；`判定阈值 = >= 700`；`结论 = 通过`
4. **时效池化拟合单元数 ($N_{\text{valid}} < 100$)**：
   - `原始观测值 = 80`；`判定阈值 = <= 100`；`结论 = 通过`
5. **补全辅助节点 (AUXILIARY_POOLED_FALLBACK) 数量**：
   - `原始观测值 = 160`；`判定阈值 = 160`；`结论 = 通过`
6. **物理仪器误差常数底座 ($c \ge 0.90^\circ\text{F}$)**：
   - `原始观测值 = min(c) = 0.9000`；`判定阈值 = >= 0.9000`；`结论 = 通过`
7. **2019 样本外盲测窗数据隔离 (Airgap Guardrail)**：
   - `原始观测值 = 0 行 2019 数据读取 (严格限定 2000-2018 训练窗)`；`判定阈值 = 0 行`；`结论 = 通过`
8. **单元测试回归套件（Unit Test Suite）**：
   - `原始观测值 = 816 passed, 0 failed, 4 skipped`；`判定阈值 = 0 failed`；`结论 = 通过`

---

## 三、 宇宙定案与交易边界锁定

依据预注册规格书第四节裁定，960 模型网格包含明确的交易与回测边界：
1. **法定日极值主交易节点 (800 格)**：
   - 包含 720 个样本量充足（$N \ge 100$）的独立拟合单元与 80 个轻度薄样本的时效池化单元（`POOLED-FALLBACK`）；
   - 作为全系统**唯一被授权参与实盘报价、持仓撮合与正式结算的法定生产模型宇宙**。
2. **时序平滑补全辅助节点 (160 格)**：
   - 补齐了 GEFS 物理存在但偏离日极值时窗（如 15:00 LT / 06:00 LT 几何错位）的 160 个单元，统一标记为 **`AUXILIARY_POOLED_FALLBACK`**；
   - **硬性交易边界约束**：此 160 格仅用于时间序列连续性分析与 Block-CV 泛化诊断，**严禁进入生产交易宇宙或衍生品计价撮合系统**。

---

## 四、 历史锚点三维对账结论 (P4 vs Round 3)

| 指标项 | 依赖管线层 | 粒度变更状态 | 裁定结论 | 物理实测与对账证据 |
| :--- | :--- | :---: | :---: | :--- |
| **真实 MAE (18h TMAX)** | 均值层 | 无变更 | **✅ 逐位一致** | KORD: 2.5935°F, KMIA: 1.3618°F, KSFO: 3.2166°F (偏差 $0.00\text{e}+00$) |
| **锚定 $\sigma^*$ (18h TMAX)** | 均值层 | 无变更 | **✅ 逐位一致** | KORD: 3.2505°F, KMIA: 1.7067°F, KSFO: 4.0315°F (偏差 $0.00\text{e}+00$) |
| **外生膨胀系数 $c_{\text{train}}$** | 方差层 | 站×季已变更 | **✅ 漂移在门禁内** | 四季均值收敛于历史标量；各季反映季节性离散度真实微调 |
| **预测均值 $\mathbb{E}[\sigma_f]$** | 方差层 | 站×季已变更 | **✅ 漂移在门禁内** | 年化漂移 $< 0.03^\circ\text{F}$，物理合理 |
| **样本外方差比 $s_{\text{oos}}$** | 方差层 | 站×季已变更 | **✅ 漂移在门禁内** | 实测落入 $[0.88, 1.12]$，稳健满足 $[0.85, 1.15]$ 门禁 |
| **动态扩宽系数 $\kappa_{\text{evt}}$** | 形态层 | 站×季已变更 | **✅ 漂移在门禁内** | 消除逐站全局单一尾部，四季动态调节 |
| **高斯代理覆盖率** | 形态层 | 站×季已变更 | **✅ 漂移在门禁内** | 实测落入 $[88.5\%, 91.8\%]$，完全满足 $[83\%, 95\%]$ |
| **精确分位数覆盖率** | 形态层 | 全新指标 | **✅ 正式确立** | 实测落入 $[87.9\%, 92.4\%]$，完全满足 $[83\%, 95\%]$ |
| **PIT K-S $(D, p)$** | 形态层 | 站×季已变更 | **✅ 漂移在门禁内** | $p \ge 0.15$ 稳健通过，拒绝原假设差异 |

---

## 五、 生成工件校验签名清单

| 工件文件路径 | 状态 / 格式 | SHA-256 校验哈希 |
| :--- | :--- | :--- |
| [`data/models/manifest.json`](../data/models/manifest.json) | v2.1.0 (`PRODUCTION_RETRAINED_V2`) | `4bbf1e7b891c3a9b6ef224b5e5c24c45be91bbaf5b8f3aa2d756668e85bc76d8` |
| [`evidence/p4_distribution_selection_audit.csv`](p4_distribution_selection_audit.csv) | 40 行站×季分布竞争留痕底账 | `2f2607895259c50429949b920fb72a8ea509c3f476019304431224134d873719` |
| [`evidence/p4_active10_training_variance_factors.json`](p4_active10_training_variance_factors.json) | 10 站 $\times$ 4 季 $c_{\text{train}}$ 参数表 | `e7245c9b7465526dbd02ec1b73121f18ea54e70a846ac7919b7992034378e64f` |
| [`evidence/p4_active10_climate_calibration.json`](p4_active10_climate_calibration.json) | 10 站 $\times$ 4 季高阶形态参数表 | `8c904c28f7dc134decaad8bea358dd098d5f72b1090f7f543f833f8067bebe70` |
| [`evidence/model_inventory_audit.csv`](model_inventory_audit.csv) | 960 格在役重训模型普查底账 | `3bbf7a6f66425b9e949d630cd9c978d613ed11960c74862329011afb5461f025` |
| [`evidence/p4_anchor_reconciliation_report.md`](p4_anchor_reconciliation_report.md) | 历史锚点三维对账核验报告 | `753173dbe92237ebfe6f82747d8481ffaf8ffea1d8ea8fdf7d1f5eaae43b1772` |
| [`tests/unit/modeling/test_p4_retraining_integrity.py`](../tests/unit/modeling/test_p4_retraining_integrity.py) | P4 重训产物完整性自动化质检验收测试 | `53fe660ad5ff398d5fa9571168fc3e12dd1da25fae39b98ffcb93e7f607d7211` |

---

## 六、 质检验收测试结论

- **自动化测试套件**: `pytest tests/unit/modeling/test_p4_retraining_integrity.py`
  - `5 passed in 0.52s`
- **历史回归测试套件**: `pytest tests/unit/modeling/test_active10_statutory_settlement.py`
  - `4 passed in 0.64s`
- **全量无网络单元测试套件**: `pytest tests/unit/ -k "not network" -q`
  - `816 passed, 4 skipped, 27 deselected, 1 warning in 56.52s`
- **历史向前兼容结论**: P4 新资产以独立命名空间归档入库，旧 Round 3 基线资产完好隔离封存，历史引用无任何断裂，全量回归保持 100% 绿灯。
