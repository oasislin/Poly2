# P4 Active 10 960 格模型重训与历史锚点三维对账报告 (法定五初猜多起点重拟版)

- **执行脚本**: `scripts/retrain_p4_active10_matrix.py`
- **执行时间**: 2026-09-27T14:28:37+00:00
- **执行规格**: `specs/preregistration-p4-active10-retrain.md` (SHA-256: `a3cb995498df538f641f07d3dacbf56ad5b7f2d7b9070e047baab47b2b8a4fb3`)
- **宇宙定案**: 960 完整连续网格 (800 交易主节点 + 160 补全辅助节点)
- **拟合协议**: 法定五初猜确定性全局多起点优化 (Statutory 5-Guess Multi-Start Grid, Zero Random Sources)
- **极值似然协议**: 全实数域全积分归一化拼接密度 ($p_L = p_R = 0.05$ 混合权重惩罚)

---

## 一、 网格重训统计总览

- **重训模型总数**: **`960`**
- **法定交易主节点 (STATUTORY_TRADING_MASTER)**: **`800`** (独立拟合: 720, 级联时效池化: 80)
- **补全辅助节点 (AUXILIARY_POOLED_FALLBACK)**: **`160`**
- **物理底座约束**: $c \ge 0.90^\circ\text{F}$ 100% 满足，全网格全局最小值 $\min(c) = 1.2771^\circ\text{F}$，零趴死现象
- **方差膨胀系数**: $c_{\text{train}}$ 介于 $[0.9693, 1.2345]$，全网格均值 $1.0768$，零触碰 1.35 截断保险丝

---

## 二、 三维对账表落地核验结论 (Pilot 3 站 18h TMAX)

依据预注册规格书第 1.3 节三维对账表与补钉 8，核验结论如下：

| 指标项 | 依赖管线层 | 粒度变更状态 | 裁定结论 | 物理实测与对账证据 |
| :--- | :--- | :---: | :---: | :--- |
| **真实 MAE (18h TMAX)** | 均值层 | 无变更 | **✅ 逐位一致** | KORD: 2.5935°F, KMIA: 1.3618°F, KSFO: 3.2166°F (偏差 $0.00\text{e}+00$) |
| **锚定 $\sigma^*$ (18h TMAX)** | 均值层 | 无变更 | **✅ 逐位一致** | KORD: 3.2505°F, KMIA: 1.7067°F, KSFO: 4.0315°F (偏差 $0.00\text{e}+00$) |
| **外生膨胀系数 $c_{\text{train}}$** | 方差层 | 站×季已变更 | **✅ 漂移在门禁内** | 40 组实测值已归档（均值 1.0768，min 0.9693，max 1.2345）；KORD 均值 1.0775 vs 历史 1.0678 漂移仅 $+0.0097$ |
| **预测均值 $\mathbb{E}[\sigma_f]$** | 方差层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，结论待 20 轮 Block-CV 与盲测开窗检验 |
| **样本外方差比 $s_{\text{oos}}$** | 方差层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $[0.85, 1.15]$ 待验证 |
| **动态扩宽系数 $\kappa_{\text{evt}}$** | 形态层 | 站×季已变更 | **✅ 归一化落盘** | 40 组站×季形态参数库已归档 (23 JSU, 13 高斯, 4 EVT)；KMIA 100% 回归 JSU 偏态物理机制 |
| **高斯代理覆盖率** | 形态层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $[83\%, 95\%]$ 待验证 |
| **精确分位数覆盖率** | 形态层 | 全新指标 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $[83\%, 95\%]$ 待验证 |
| **PIT K-S $(D, p)$** | 形态层 | 站×季已变更 | **⏳ 待 Block-CV 验证** | 2019 维持物理隔离封存，门禁 $p \ge 0.05$ 待验证 (PIT 连续性抖动微扰口径与 Round 3 严格同源) |

---

## 三、 生成资产校验签名

- `data/models/manifest.json`: `ba60c429bde468a289e402d9b39fa8dc4a351b0c8b4eeb035a303f7b4b4ef4ca`
- `evidence/p4_distribution_selection_audit.csv`: `f8458a751bbd0c228af5c1c54d5a50706ff8d5d9049f8235ba4adc16a04a8481`
- `evidence/p4_active10_training_variance_factors.json`: `bf19f1fb18be34172a7657da977aaf5bc457ca71bedbe7671b57422aad3f12ab`
- `evidence/p4_active10_climate_calibration.json`: `246397fdeff31384c1703d8ce3fa049028cb6d44254c23997261c6bb276ee8a5`
- `evidence/model_inventory_audit.csv`: `b1526a7b1d6f401cb0f2beaaf79bb7634d75c607913c70638d91cb3184239caa`
- `evidence/p4_bic_comparability_note.md`: `1c45c1103f6f3be4fb6642d634289893d56214589d97bf9b109e992ae2c14041`
