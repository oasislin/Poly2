# 规格书：Active 10 站全量物理概率模型升级、方差校准与 2019 样本外终极验收 (Phase 2 Task 08)

> **规格版本**: v1.0.0 Engineering-Spec Final  
> **任务性质**: 核心物理概率模型全台站宇宙生产级推广与终极法定验收  
> **前置依赖**: 
> 1. Phase 1 先导站（KORD, KMIA, KSFO）FULL VALIDATION 终局闭环；
> 2. 统一校准数据集 `data/processed/calib-dataset-v2.0/`（2000–2018 训练窗，2019 OOS 评估集）；
> 3. 官方地面实测真值 `data/processed/truth_ghcn_daily/*.parquet`（NWS GHCN-Daily 官方源）；
> 4. 架构与算法依据：ADR-0015（物理方差底座）、ADR-0017（离散化半度连续性修正与加权 ECE 门禁）、D-3/D-6（防前瞻泄漏与冻结 $c_{\text{train}}$ 协议）、R-6（对流偏度修正）、R-7（极值 EVT 尾部校准）。

---

## 一、 问题背景与使命陈述 (Problem Statement & Mission)

在 Phase 1 的独立复算与审计中，工程组完成了对统计作弊（Case-B 泄漏、构造恒等式）的彻底铲除，并确立了外生冻结 $c_{\text{train}}$、因果滑动去偏窗口（`window=30`）、迈阿密 R-6 对流偏度修正、R-7 极值 EVT 厚尾校准，以及 ADR-0017 离散化加权 ECE 门禁体系。

然而，**上述所有千锤百炼打磨成型的最新科学修正公式与参数，目前仅在 3 个先导站（KORD, KMIA, KSFO）完成了闭环**。其余 7 个核心交易台站（`KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KAUS`）仍处于旧版未校准状态：
- 未在 2000–2018 历史训练窗拟合专属的外生 $c_{\text{train}}$ 与去偏参数；
- 未经过南部强对流与局地微地形的偏态（R-6）与极值厚尾（R-7）检验；
- 未曾通过 2019 年整年样本外 365 天严格的 ADR-0017 离散门禁验收。

**Task 08 的核心使命**：  
将先导站已完全验证成功的整套“物理模型升级与防泄漏校准体系”，**无损、全量、严格地扩展到全部 Active 10 交易台站**，为全部 10 个站点生成生产级参数资产，并在 2019 样本外完成终极法定结算与独立双向复算验证，使全台站宇宙正式晋升为 **`FULLY VALIDATED`**。

---

## 二、 核心技术契约与数学铁律 (Technical Contracts & Iron Rules)

### 1. 严格时间墙与外生性铁律 (No 2019 Lookahead)
- **训练数据范围**：严格限定于 **2000-01-01 至 2018-12-31**（扣除缺报后约 6,940 站·日/站）；
- **参数外生性**：所有滑动去偏窗口长度 $W$、方差膨胀系数 $c_{\text{train}}$、季节性 EMOS 参数 $(a, b, c, d)$、偏态参数与 EVT 阈值，**必须 100% 仅由 2000–2018 训练窗推导并冻结**；
- **严禁 Case-B 泄漏**：严禁在拟合上述参数时读取 2019 年残差方差或任何 2019 年气温数据。

### 2. 10 站全量参数拟合公式与离线冻结规范
对于每一个台站 $s \in \text{ACTIVE\_10\_STATIONS}$：
1. **因果滑动去偏状态推导**：
   采用训练窗离线检验确立的最优窗口 $W=30$ 天，计算因果滑动偏差均值：
   $$\mu_{\text{forecast}}(t) = \mu_{\text{raw}}(t) + \text{trailing\_bias}_{30}(t)$$
2. **外生方差膨胀系数 $c_{\text{train}}$**：
   $$c_{\text{train}}(s) = \sqrt{\frac{\text{Var}(r_{\text{train}}(s))}{\mathbb{E}[\sigma_{\text{raw}}^2(s)]}}$$
   其中残差 $r_{\text{train}} = y_{\text{train}} - \mu_{\text{forecast}}$。
3. **参数落盘与校验**：
   拟合结果统一固化写入 `evidence/active10_training_variance_factors.json`，并由 SHA-256 哈希锁定。

### 3. 局地气候特征定向校准 (R-6 偏态与 R-7 极值尾部)
1. **局地对流偏度诊断（针对南部及强对流台站：KMIA, KHOU, KAUS, KATL 等）**：
   检验午后雷暴对流引发的急剧降温负偏态（Negative Skewness），必要时装配 Johnson SU 偏度变换，防止冷端过信；
2. **极值理论厚尾校准（EVT / GPD）**：
   针对夏季内陆高温站点（KDAL, KAUS, KSFO 极端焚风），拟合超额极值广义帕累托分布（GPD），动态修正尾部预测方差，确保高斯分布不低估尾部风险。

### 4. 2019 样本外 ADR-0017 离散化评估契约
在 2019 年 365 天样本外（总计 3,650 站·日），严格按照 ADR-0017 执行积分与检验：
1. **1°F 档位半度连续性修正积分**：
   $$P(\text{Bin } [k-0.5, k+0.5)) = \Phi\left(\frac{k+0.5 - \mu}{\sigma_f}\right) - \Phi\left(\frac{k-0.5 - \mu}{\sigma_f}\right)$$
2. **随机化 PIT 抖动**：
   对离散温度真值施加 $U(-0.05, 0.05)^\circ\text{F}$ 随机抖动（锁定随机种子 `seed=42`），消除经验阶梯离散伪影；
3. **有限样本双向 Kolmogorov-Smirnov 检验**：
   计算实测 $D$ 统计量并由精确有限样本互补累积函数反解 $p$ 值：
   $$p = \text{kstwo.sf}(D, 365)$$

---

## 三、 六大终极法定验收门禁 (Final Acceptance Gates)

全部 10 个台站在 2019 年样本外单次盲测中，必须全员通过以下六项法定门禁：

| 门禁项 | 统计指标名称 | 门禁阈值区间 | 物理与统计意义 |
| :---: | :--- | :---: | :--- |
| **主门禁 ①** | 随机化 PIT K-S 拟合检验 $p$ 值 | **$p \ge 0.05$** | 拒绝模型与真实分布不一致的原假设（分布形态完全吻合） |
| **主门禁 ②** | 7 档位离散加权 ECE | **$\le 3.0\%$** | 概率可靠性与校准误差控制在预测市场交易阈值内 |
| **主门禁 ③** | 样本外方差比 $s_{\text{oos}}$ | **$[0.85, 1.15]$** | 预测弥散度与实际残差离散度达到物理守恒，无过度自信 |
| **双向检验 ①**| 样本外 PIT 均值 | **$[0.46, 0.54]$** | 全年概率积分无系统性偏高或偏低（无全局冷/热偏差） |
| **双向检验 ②**| 90% 名义置信区间覆盖率 | **$[83\%, 95\%]$** | 真实温度落入 90% 预测带的比例符合二项分布置信区间 |
| **均值层纯净性**| 真实 MAE 跨版本一致性 | **保持报表精度恒定** | 证明方差与尾部校准仅作用于 $\sigma$ 层，绝不篡改均值 $\mu$ 层 |

---

## 四、 任务垂直切片与工件规划 (Tickets & Deliverables)

- **Spec 主 Issue**: `Spec: Phase 2 Task 08 - Active 10 站全量物理概率模型升级、方差校准与 2019 样本外终极验收`
- **切片 Tickets**:
  1. **Ticket 01**: `Phase 2 Task 08 - Ticket 01: feat(modeling): 扩展训练窗拟合引擎至 Active 10 站并冻结 c_train 与 window`
     - 扩展 `scripts/fit_training_variance_factors.py`，全量计算 Active 10 站并产出 `evidence/active10_training_variance_factors.json`。
  2. **Ticket 02**: `Phase 2 Task 08 - Ticket 02: feat(calibration): 推进 10 站局地气候偏态(R-6)与极值理论厚尾(R-7)参数化`
     - 产出针对其余 7 站的局地气候校准参数 `evidence/active10_climate_calibration.json`。
  3. **Ticket 03**: `Phase 2 Task 08 - Ticket 03: feat(evaluation): 实施 10 站 2019 样本外盲测推演并生成 Parquet 审计底账`
     - 运行 10 站 2019 年推演，生成只读底账 `data/processed/audit_arrays/2019_oos_active10_arrays.parquet`。
  4. **Ticket 04**: `Phase 2 Task 08 - Ticket 04: test(gates): 全量落实现代 ADR-0017 离散化门禁与六重统计指标核验`
     - 产出机器可读的统计表 `evidence/active10_recomputed_statistics.csv`，断言六大门禁全绿。
  5. **Ticket 05**: `Phase 2 Task 08 - Ticket 05: docs(settlement): 交付 Active 10 站唯一法定结算表、独立复算脚本与哈希清单`
     - 产出法定报告 `evidence/active10_settlement_report.md`、零依赖复算脚本 `scripts/standalone_recompute_active10.py`，并刷新 `evidence/active10_manifest.json`。
