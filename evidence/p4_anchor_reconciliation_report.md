# P4 Active 10 960 格模型重训与历史锚点三维对账报告

- **执行脚本**: `scripts/retrain_p4_active10_matrix.py`
- **执行时间**: 2026-09-24T04:03:50.232242+00:00
- **执行规格**: `specs/preregistration-p4-active10-retrain.md` (SHA: `b607cc60...e9247`)
- **宇宙定案**: 960 完整连续网格 (800 交易主节点 + 160 补全辅助节点)

---

## 一、 网格重训统计总览

- **重训模型总数**: **`960`**
- **法定交易主节点 (STATUTORY_TRADING_MASTER)**: **`800`** (独立拟合: 720, 级联池化: 80)
- **补全辅助节点 (AUXILIARY_POOLED_FALLBACK)**: **`160`**
- **物理底座约束**: $c \ge 0.90^\circ\text{F}$ 100% 满足，无方差坍缩

---

## 二、 三维对账表落地核验结论 (Pilot 3 站 18h TMAX)

依据预注册规格书第 1.3 节三维对账表，核验结论如下：

| 指标项 | 依赖管线层 | 粒度变更状态 | 裁定结论 | 物理实测与对账证据 |
| :--- | :--- | :---: | :---: | :--- |
| **真实 MAE (18h TMAX)** | 均值层 | 无变更 | **✅ 逐位一致** | KORD: 2.5935°F, KMIA: 1.3618°F, KSFO: 3.2166°F (偏差 $0.00\text{e}+00$) |
| **锚定 $\sigma^*$ (18h TMAX)** | 均值层 | 无变更 | **✅ 逐位一致** | KORD: 3.2505°F, KMIA: 1.7067°F, KSFO: 4.0315°F (偏差 $0.00\text{e}+00$) |
| **外生膨胀系数 $c_{\text{train}}$** | 方差层 | 站×季已变更 | **✅ 参数落盘** | 40 组实测值已归档（均值 1.3283，min 0.9592，max 1.3500） |
| **预测均值 $\mathbb{E}[\sigma_f]$** | 方差层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，结论待 20 轮 Block-CV 与盲测开窗检验 |
| **样本外方差比 $s_{\text{oos}}$** | 方差层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $[0.85, 1.15]$ 待验证 |
| **动态扩宽系数 $\kappa_{\text{evt}}$** | 形态层 | 站×季已变更 | **✅ 参数落盘** | 40 组站×季形态参数库已归档 (28 EVT, 7 高斯, 5 JSU) |
| **高斯代理覆盖率** | 形态层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $[83\%, 95\%]$ 待验证 |
| **精确分位数覆盖率** | 形态层 | 全新指标 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $[83\%, 95\%]$ 待验证 |
| **PIT K-S $(D, p)$** | 形态层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $p \ge 0.05$ 待验证 (PIT 抖动口径同源) |

---

## 三、 生成资产校验签名

- `data/models/manifest.json`: `4bbf1e7b891c3a9b6ef224b5e5c24c45be91bbaf5b8f3aa2d756668e85bc76d8`
- `evidence/p4_distribution_selection_audit.csv`: `2f2607895259c50429949b920fb72a8ea509c3f476019304431224134d873719`
- `evidence/p4_active10_training_variance_factors.json`: `e7245c9b7465526dbd02ec1b73121f18ea54e70a846ac7919b7992034378e64f`
- `evidence/p4_active10_climate_calibration.json`: `8c904c28f7dc134decaad8bea358dd098d5f72b1090f7f543f833f8067bebe70`
- `evidence/model_inventory_audit.csv`: `3bbf7a6f66425b9e949d630cd9c978d613ed11960c74862329011afb5461f025`
