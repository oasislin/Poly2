# P8-ALGO-AUDIT-CHK-01：算法链路与 S_conf 独立性复核报告

> ⚠️ **历史快照（只读留档 · 2026-11-22 标定）**：本文档反映 **[2026-11-06 前-`α` 阶段《项目方案 v2.8》+ `ADR-0019` 链路之一次性独立审计产出]**，所审 `S_conf / x_ece / σ*` 链路已被 **`post-α` 架构**（[`项目方案 (v3.0) §8`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#8-模块地图与协议层总索引v30-后-α-十模块静态结构与-p1p19-契约--2026-11-18-当前决策) 与 [`P8-D6-POLICY-CLOSURE v1.0`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md)）整体取代，且不再承担日常活状态更新。依据《项目编号与命名规范 v1.1 §8.1》满足全部三项判据并冻结留档——**严禁回改原正文、严禁删除或移动路径**。当前实时权威状态与现行门限额制度请跳转：[`P8-PROJECT-TASKS_全量任务分解台账.md`](P8-PROJECT-TASKS_全量任务分解台账.md)、[`P8-D6-POLICY-CLOSURE v1.0`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) 与 [`P8-T4-M4M5-INTERFACE v1.1`](P8-T4-M4M5-INTERFACE_决策与执行接口规格.md)。

> **单据编号**：`P8-ALGO-AUDIT-CHK-01`  
> **父工单（B 线）**：`P8-ALGO-AUDIT`（全系统算法链路与风控独立性深度审计）  
> **工单性质**：**B 线独立审计 / 独立复核意见（只读复核与治理裁决，严禁改动业务代码）**  
> **审计对象**：算法设计本身（《项目方案 v2.8》、ADR-0019、P7-ALGO-2 规格书与执行代码链路）  
> **对应 A 线票**：**无（算法设计审计）**  
> **审计日期**：2026-11-06  
> **审计执行方**：系统独立审计组  

---

## 0. 独立性声明与审查背景

本复核单依据治理规范严格执行 B 线独立复核程序，旨在解决当前算法文档（《项目方案 (v2.8)》）、架构决策（ADR-0019）与底层代码实现（`src/modeling`、`src/prediction`、`src/pricing` 及缺失的 `src/bankroll`）之间存在的**严重断裂、口径冲突与重复惩罚**问题。

审计工作组遵循“原始观测不可篡改”与“实证必须附带工件引用”铁律，所有实证数字均由所附脚本 [`docs/audit/annex/CHK-01_repro/repro_chk01.py`](annex/CHK-01_repro/repro_chk01.py) 基于只读底层数据资产（SHA-256 见 §8）确定性复算产生。

---

## 1. 端到端链路连通表（10 处断点全景）

经对代码库 AST 语法树扫描、契约 JSON 字段比对与数据流追踪，端到端 10 处关键断点（B1~B10）判定结论如下：

| 编号 | 断点位置 | 规范设计意图 | 下游真实期待 | 实际代码现状 | 审计判定与后果分析 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **B1** | `src/modeling/gaussian_emos.py:65` | 方案 v2.8 / ADR-0015 规定方差 $\sigma^2 = c^2 + d^2 S_{\text{ens}}^2$ | 纯粹的条件预测方差，不含任何外部非均质加法项 | 实际代码保留 `clim_var` 加法项：$\sigma^2 = c^2 + d^2 S_{\text{ens}}^2 + \sigma^2_{\text{clim}}$ | **成立（严重断裂）**。直接导致预测方差虚高 3~4 倍，90% 覆盖率虚高至 98.60%，抹平盘口 Edge。 |
| **B2** | `src/prediction/**` 全包 | P4 重训全量引入 Johnson SU (JSU) 拟合厚尾 | 生产预测管线输出带 JSU 偏态参数的非高斯 CDF | 生产代码仅支持纯高斯推理，无任何 JSU 参数加载与计算逻辑 | **成立（严重断裂）**。物理重训成果无法在生产推理端生效，产生系统性形态漂移。 |
| **B3** | `src/prediction/static_predictor.py:123` | P4 重训强制引入 30 天滑动因果偏置 $b_{30}$ 修正均值 | 动态修正系统性偏差：$\mu_{\text{calib}} = \mu_{\text{raw}} + b_{30}$ | 生产代码直接使用 $\mu = a + b \cdot \bar{T}_{\text{ens}}$，完全遗漏 $b_{30}$ | **成立（严重断裂）**。导致生产均值预测滞后于季节性转换，MAE 劣化。 |
| **B4** | `data/contracts/physical_param_contract.json` | 契约向定价端提供完整物理校准基准 | 传递 $s_{\text{oos}}, n, p_k, \sigma_{\text{eff}}, \text{Cov}_{90}$ 等法定字段 | 契约缺失 $n, p_k$，且未内嵌当前运行时的 $\sigma_{\text{eff}}$ 基准 | **成立（数据断裂）**。下游无法重构有限样本标准误 $\sigma^*$，被迫硬编码常数。 |
| **B5** | `src/pricing/sigma_adj.py:81` | ADR-0019 §4 第一道防线：$\sigma_{\text{adj}} = \sqrt{\max(1, s_{\text{oos}})} \cdot \sigma$ | 定价层依据方差失真比平滑膨胀方差以抵御欠自信 | 生产管线零调用；且函数硬编码抛出 `F2LockNotReleasedError` | **成立（孤岛断裂）**。第一道防线物理未投入生产，欠自信风险敞口完全暴露。 |
| **B6** | 仓库根目录（缺少 `src/bankroll/`） | ADR-0019 §3 规定产出 $S_{\text{conf}}$ 与 $\tau_{\text{conf}}$ | 交易层将 $\tau_{\text{conf}}$ 并入预算上限 $C_{\max}$ | `src/bankroll/` 目录与代码物理不存在 | **成立（实现缺失）**。第二道防线与可信度调制完全悬空，无法执行。 |
| **B7** | `prediction_pipeline.py` vs `penetration_probe.py` | 预测管线算出 11 档离散概率并入库 SQLite | 将优势档概率 $\hat{p}_i$ 传入订单薄探针计算 EV 与 Edge | 管线存盘后直接退出，未调用探针 | **成立（链路断裂）**。定价最后一跳断裂，概率优势无法转化为订单薄穿透容量与交易信号。 |
| **B8** | 全仓检索（无 Kelly 代码） | 规格书 §3~§5 规划的稳健 Minimax Kelly 优化模型 | 求解各档最优下注金额 $f_i$（美元）并下达 FAK/IOC 订单 | 核心求解算法代码物理缺失 | **成立（实现缺失）**。无法完成从 Edge 到真实下单张数的数值换算。 |
| **B9** | `param_table_converter.py` | 契约 JSON 生成并落盘 | 下游消费时验证契约内容的完整性与防篡改 | 契约无内容自哈希校验字段，watchdog 仅校验 pkl 与 manifest | **成立（治理断裂）**。契约内数值若被篡改不会触发看门狗报警。 |
| **B10** | `parameter_contract.py` vs ADR-0019 §5 | 契约提供名义 90% 覆盖率 `v1_coverage_90` | $S_{\text{conf}}$ 消费覆盖率偏离 $x_{\text{cov}} = \|\text{Cov} - 0.9\|$ | ADR §5 承诺“宽带内过自信不罚”，但 $x_{\text{cov}}$ 对称绝对值对 $s<1$ 同号重罚 | **成立（逻辑冲突）**。KORD 36h/60h（$s=0.97/0.95$）覆盖率 91%~92%，在 $\sigma$ 端不罚，在 $S_{\text{conf}}$ 端被罚 $z=1.5\sigma$。 |

---

## 2. 三方对账表：22 格 × 三列深度对账与 D1 定值基准裁决

### 2.1 22 格 × 三列三方对账表
为彻底厘清物理重训产出、契约落盘与生产代码公式之间的方差口径，复核工作组基于 `2019_oos_p4_settlement_arrays.parquet`（全年逐日 365 条记录）、`data/contracts/physical_param_contract.json` 与 `src/modeling/gaussian_emos.py:65` 进行了逐格全量对账：

| 台站提前期格 (Cell) | 逐日均值 $\mathbb{E}[\sigma_{\text{calib}}]$ | 列 1: Parquet $s_{\text{oos}}$ | 列 2: 契约落盘 $s_{\text{oos}}$ | 列 3: 生产公式重算 $s_{\text{oos}}$ | 对照: raw EMOS $s_{\text{oos}}$ | 对账结论与绝对差异 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| **KMIA_12h_tmax** | 2.5782°F | 1.059687 | 1.059687 | 0.322285 | 1.323211 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_18h_tmax** | 1.7272°F | 1.159179 | 1.159179 | 0.180475 | 1.449059 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_24h_tmax** | 2.7975°F | 1.236250 | 1.236250 | 0.442594 | 1.533230 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_30h_tmax** | 2.5097°F | 1.363831 | 1.363831 | 0.404043 | 1.695327 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_36h_tmax** | 2.5385°F | 1.185000 | 1.185000 | 0.352536 | 1.479165 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_42h_tmax** | 1.8111°F | 1.255104 | 1.255104 | 0.212760 | 1.569183 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_48h_tmax** | 2.8022°F | 1.293564 | 1.293564 | 0.465431 | 1.605164 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_54h_tmax** | 2.5747°F | 1.284506 | 1.284506 | 0.400405 | 1.597423 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_60h_tmax** | 2.5653°F | 1.231480 | 1.231480 | 0.370505 | 1.538253 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_66h_tmax** | 1.9340°F | 1.183626 | 1.183626 | 0.229497 | 1.478451 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KMIA_72h_tmax** | 2.8286°F | 1.208182 | 1.208182 | 0.450604 | 1.497164 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_12h_tmax** | 6.6466°F | 0.888254 | 0.888254 | 0.282862 | 1.038057 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_18h_tmax** | 3.3023°F | 1.047818 | 1.047818 | 0.102340 | 1.223950 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_24h_tmax** | 7.5935°F | 1.193133 | 1.193133 | 0.459201 | 1.398906 | 列 1 与 列 2 恒等 ($\Delta = 2.22\text{e}-16$) |
| **KORD_30h_tmax** | 7.2839°F | 1.014575 | 1.014575 | 0.370220 | 1.189108 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_36h_tmax** | 6.9737°F | 0.833009 | 0.833009 | 0.286241 | 0.972288 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_42h_tmax** | 3.9506°F | 1.009950 | 1.009950 | 0.138043 | 1.176505 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_48h_tmax** | 7.8228°F | 1.105420 | 1.105420 | 0.444463 | 1.296636 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_54h_tmax** | 7.3748°F | 1.000051 | 1.000051 | 0.372114 | 1.171949 | 列 1 与 列 2 恒等 ($\Delta = 2.22\text{e}-16$) |
| **KORD_60h_tmax** | 7.0789°F | 0.817635 | 0.817635 | 0.286781 | 0.954572 | 列 1 与 列 2 恒等 ($\Delta = 0.00\text{e}+00$) |
| **KORD_66h_tmax** | 4.4340°F | 0.906868 | 0.906868 | 0.155049 | 1.057403 | 列 1 与 列 2 恒等 ($\Delta = 1.11\text{e}-16$) |
| **KORD_72h_tmax** | 7.8909°F | 1.078046 | 1.078046 | 0.440045 | 1.262556 | 列 1 与 列 2 恒等 ($\Delta = 2.22\text{e}-16$) |
| **全网格均值** | **4.3314°F** | **1.111817** | **1.111817** | **0.325816** | **1.341304** | **列 1 与 列 2 最大差 $\le 2.22\text{e}-16$** |

### 2.2 D1 定值基准裁决：必须以【契约 / Parquet 落盘列】为基准
在定案 D1 条款时，**必须且只能以【列 2（契约落盘 $s_{\text{oos}}$）/ 列 1（Parquet 序列）】为唯一法定基准**。理由如下（严格基于物理模型重训产出事实）：

1. **物理重训资产的法定契约事实**：
   在 Phase 2 Task 01 预注册规格书（[`specs/preregistration-p4-active10-retrain.md`](../../specs/preregistration-p4-active10-retrain.md) §1.3）与交付总报告（[`evidence/p4_retraining_execution_and_delivery_report.md`](../../evidence/p4_retraining_execution_and_delivery_report.md) §4）中，法定方差层被严密冻结为：
   $$\sigma_{\text{eff}} = c_{\text{train}} \cdot \sqrt{c^2 + d^2 S_{\text{ens}}^2}$$
   960 个生产模型 `.pkl` 与 `manifest.json` 均严格落盘了由 L-BFGS-B 多起点全局搜索拟合的 $c_{\text{train}}$ 参数（介于 $1.03 \sim 1.23$）。2019 样本外盲测脚本（[`scripts/evaluate_p4_2019_settlement.py:297`](../../scripts/evaluate_p4_2019_settlement.py)）正是以该 $\sigma_{\text{eff}}$ 作为 `sigma_calib` 进行结算落盘的。
2. **90% 覆盖率的物理客观性**：
   在基准列（列 1 / 列 2）下，22 格的名义 90% 区间覆盖率实测均值为 **88.74%**（非常接近名义 90% 水平，完美符合第一原理概率校准）。
3. **生产代码公式是历史遗留缺陷（Bug）**：
   列 3（按当前生产 `GaussianEMOS` 重算）的均值暴跌至 **0.3258**。这是因为早期代码在条件方差上粗暴累加了日历月气候总方差 $\sigma^2_{\text{clim}}$（$30 \sim 150^\circ\text{F}^2$），导致方差被人为放大 3~4 倍。若以列 3 为基准，等于承认并固化了工程 bug，彻底摧毁物理模型。因此，生产端必须对齐契约端，完成向上升级。

---

## 3. 契约 `v1_coverage_90`（88.74%）与重算 98.60% 的口径定性剖析

用户核心关切：“说明契约 `v1_coverage_90`（均值 88.74%）与它重算的 98.60% 是‘v1 覆盖率 vs v2 覆盖率’还是‘两套 $\sigma$’？”

复核工作组明确裁定：**此差异 100% 是“两套 $\sigma$ 的计算口径分裂”，与“v1 vs v2 覆盖率”毫无关系！**

### 3.1 事实依据与数据链溯源
1. **V1 与 V2 尺子的方差完全相同**：
   在 `evidence/audit_v2/p4blind_v2r01_comparison.csv` 中，列 `v1_s_oos` 与 `v2_s_oos` 在 22 格上**逐位恒等**（均值均为 1.111817）。V2 尺子升级（`P4-BLIND-AUDIT-V2R01`）仅改进了有效样本量 $N_{\text{eff}}$、CvM 均匀性检验与 2°F ECE，并未触动底层分布与 $\sigma$ 的定义。其记录的 `v1_coverage_90` 均值正是 **0.887358 (88.74%)**。
2. **两套 $\sigma$ 的根本对立**：
   - **口径 A（重训与契约真实落盘口径，88.74%）**：
     $\sigma_{\text{eff}} = c_{\text{train}} \cdot \sqrt{c^2 + d^2 S_{\text{ens}}^2}$。此时标准差均值为 **4.33°F**，2019 样本外 90% 覆盖率实测为 **88.74%**（高斯代理覆盖率均值为 **90.04%**）。
   - **口径 B（生产遗留代码 `GaussianEMOS:65` 粗暴加法项口径，98.60%）**：
     $\sigma^2_{\text{prod}} = c^2 + d^2 S_{\text{ens}}^2 + \sigma^2_{\text{clim}}$。由于叠加了日历气候总方差（芝加哥高达 $90 \sim 250^\circ\text{F}^2$），标准差均值被拉大至 **$10 \sim 15^\circ\text{F}$**。在这种极度虚胖的方差下，预测区间变得无比宽泛，观测值几乎 100% 落在其内，重算得出的 90% 覆盖率均值被虚假拉升至 **98.60%**（其中 5 个格子甚至出现 100.0% 盲覆盖）！

**裁决结论**：88.74% 是物理真实的有效覆盖率，98.60% 是生产代码错误添加气候加法项所产生的虚假产物。两者的差异本质是**物理重训有效 $\sigma$ 与生产遗留虚胖 $\sigma$ 之间的口径分裂**。

---

## 4. M1 ~ M8 逐条数学推导（四段式完整交付）

严格按照审查要求，M1~M8 逐条落实「假设 / 推导 / 结论 / 数值代入」四段式结构，演示假设显式标注：

### M1: 离散档客观概率 $p_k$ 重构与零假设偏倚基线 $b_{\text{ece}}$ 闭式推导

> ⚠️ **本节内容已失效/被取代（2026-11-22 标定）**：原用于连续 $S_{\text{conf}}$ 且未扣除有限样本零基线 $b_{\text{ece}}$ 之 $x_{\text{ece}}$ 离差惩罚，已被 `post-α` 离散月度 `P16 / P17` 池化 `ECE` 临界锚制度（`ECE_GREEN_ANCHOR <= 0.020` / `ECE_YELLOW_BAND (0.020, 0.040]` / `ECE_RED_ANCHOR > 0.040`）整体替换。现行权威：[`P8-D6-POLICY-CLOSURE v1.0 §1.2 & §4`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#四-ece-临界锚议程第-4-项) 与 [`项目方案 (v3.0) §8.1 M4/M8`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#81-模块地图m1m10-十模块静态架构--2026-11-18-当前决策)。原文按冻结规则保留，本标注为唯一合法编辑。

1. **假设**：
   在完美校准零假设下，日观测值 $y_t \sim F_t(x)$。对于 11 个离散档位，指示变量 $I_{k, t} = \mathbb{I}(y_t \in \text{Bin}_k) \sim \text{Bernoulli}(p_{k, t})$。时间轴平均无条件预测概率 $\bar{p}_k = \frac{1}{n} \sum_{t=1}^n p_{k, t}$。经验发生频率 $\hat{f}_k = \frac{1}{n}\sum_{t=1}^n I_{k, t}$。时间序列具有一阶自相关性，有效独立样本量记为 $N_{\text{eff}}$。
2. **推导**：
   依据中心极限定理，档位离差服从渐近正态分布：
   $$\hat{f}_k - \bar{p}_k \sim \mathcal{N}\left(0, \frac{\bar{p}_k (1 - \bar{p}_k)}{N_{\text{eff}}}\right)$$
   绝对离差 $|\hat{f}_k - \bar{p}_k|$ 服从折叠正态分布（Folded Normal Distribution，若 $X \sim \mathcal{N}(0, \sigma^2)$，则 $\mathbb{E}[|X|] = \sigma \sqrt{2/\pi}$）。
   无条件 11 档 ECE 定义为等权离差期望：
   $$\text{ECE} = \frac{1}{11} \sum_{k=0}^{10} |\hat{f}_k - \bar{p}_k|$$
   对其取零假设期望，得抽样偏倚基线闭式解析解：
   $$b_{\text{ece}} := \mathbb{E}_{\text{null}}[\text{ECE}] = \frac{1}{11} \sum_{k=0}^{10} \sqrt{\frac{2}{\pi}} \sqrt{\frac{\bar{p}_k (1 - \bar{p}_k)}{N_{\text{eff}}}}$$
3. **结论**：
   有限样本下，即使模型 100% 完美无偏，期望 ECE 绝不为 0，必然存在因离散抽样噪声引起的理论偏倚基线 $b_{\text{ece}} \in [0.00866, 0.01405]$。若在评分中不扣除 $b_{\text{ece}}$，将把纯抽样噪声误判为模型失调。
4. **数值代入**：
   以 `KORD_12h_tmax` 为例：$n = 365, N_{\text{eff}} = 328.2$。重构出的 11 档 $\bar{\mathbf{p}}$ 代入公式：
   $$b_{\text{ece}} = \frac{1}{11} \times 0.79788 \times \sum_{k=0}^{10} \sqrt{\frac{\bar{p}_k (1 - \bar{p}_k)}{328.2}} = \mathbf{0.01247}$$
   观测 ECE 值为 $0.01474$。若不扣偏倚，$z_{\text{raw}} = 0.01474 / 0.00286 = 5.15\sigma$（严重过罚）；扣除偏倚后净离差为 $|0.01474 - 0.01247| = 0.00227$，$z_{\text{adj}} = \mathbf{0.79\sigma}$（完全属于正常抽样波动）。全网格 22 格中，实测有 **12 / 22 格** 的观测 ECE 低于 $b_{\text{ece}}$！

---

### M2: 抽样标准差 $\sigma^*$ 的三种解析形式对比

> ⚠️ **本节内容已失效/被取代（2026-11-22 标定）**：原作为连续 $S_{\text{conf}}$ 标准化分母之 $\sigma^*_{\text{ece}} / \sigma^*_{\text{cov}} / \sigma^*_{\text{pit}}$（前-`α` 未定参数），已被 `post-α` 锚底幂函数时间骨架 $w(\tau)$ 与离散三态 `P16` 灯级乘子 $\lambda(L)$ 乘性结构、以及冻结残差分散度参数 `sigma_delta_frozen` 取代。现行权威：[`P8-EXECUTION-DESIGN v1.0 §2.1 & §3`](P8-EXECUTION-DESIGN_w与phi设计与决策记录_v1.0.md#三-当前裁决与驳回记录2026-11-17)、[`P8-D6-POLICY-CLOSURE v1.0 §1.3 & §6`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#六-黄灯半额精确定义与-yellow_multiplier-作用点议程第-6-项) 与 [`P8-T4-M4M5-INTERFACE v1.1 §3.4`](P8-T4-M4M5-INTERFACE_决策与执行接口规格.md#34-p6-executionpolicybundle-v10m8--m4--m5--m7--由-rc-正式成文)。原文按冻结规则保留，本标注为唯一合法编辑。

1. **假设**：
   - 形式 A（独立渐近折叠高斯）：假设 11 档绝对离差互相独立；
   - 形式 B（多项分布协方差纠偏）：考虑 $\sum_{k=0}^{10} \hat{f}_k = 1$ 的负协方差约束 $\text{Cov}(\hat{f}_i, \hat{f}_j) = -\frac{\bar{p}_i \bar{p}_j}{N_{\text{eff}}}$；
   - 形式 C（均匀分布经验上界）：假设 $p_k \approx 1/K$ 且忽略形态差异。
2. **推导**：
   折叠正态方差公式：$\text{Var}(|X|) = \left(1 - \frac{2}{\pi}\right) \sigma^2_X$。
   - 形式 A：
     $$\sigma^{*2}_{\text{ece}, A} = \text{Var}\left(\frac{1}{11} \sum_{k=0}^{10} |\hat{f}_k - \bar{p}_k|\right) = \frac{1 - 2/\pi}{121 N_{\text{eff}}} \sum_{k=0}^{10} \bar{p}_k (1 - \bar{p}_k)$$
   - 形式 B：
     利用 Geary 绝对值协方差近似 $\text{Cov}(|X_i|, |X_j|) \approx -\frac{2}{\pi} \frac{\bar{p}_i \bar{p}_j}{N_{\text{eff}}}$，引入负协方差交叉项求和：
     $$\sigma^{*2}_{\text{ece}, B} = \sigma^{*2}_{\text{ece}, A} - \frac{2/\pi}{121 N_{\text{eff}}} \sum_{i \ne j} \bar{p}_i \bar{p}_j = \sigma^{*2}_{\text{ece}, A} - \frac{2/\pi}{121 N_{\text{eff}}} (1 - \sum \bar{p}_k^2)$$
   - 形式 C：
     代入 $\bar{p}_k = 1/11$，得粗略常数：$\sigma^{*}_{\text{ece}, C} = \frac{\sqrt{1 - 2/\pi}}{\sqrt{11 N_{\text{eff}}}} \approx \frac{0.6028}{\sqrt{11 N_{\text{eff}}}}$。
3. **结论**：
   形式 A 闭式解数值极其稳健，且形式 B 的多项式修正仅使标准误微幅收缩约 3%~5%。形式 C 过于粗糙。推荐将形式 A 确立为法定计算式。
4. **数值代入**：
   以 `KORD_12h_tmax` ($N_{\text{eff}} = 328.2, \sum \bar{p}_k(1-\bar{p}_k) = 0.9021$) 为例：
   - 形式 A：$\sigma^*_{\text{ece}, A} = \sqrt{\frac{0.36338 \times 0.9021}{121 \times 328.2}} = \mathbf{0.002863}$
   - 形式 B：$\sigma^*_{\text{ece}, B} = \sqrt{8.25\text{e}-6 - 4.88\text{e}-7} = \mathbf{0.002786}$
   - 形式 C：$\sigma^*_{\text{ece}, C} = \frac{0.6028}{\sqrt{11 \times 328.2}} = \mathbf{0.01003}$
   实测必须采用形式 A 的 **$0.00286$**。

---

### M3: 零假设下无技能/零偏离时的 $S_{\text{conf}}$ 期望值推导

> ⚠️ **本节内容已失效/被取代（2026-11-22 标定）**：原 $S_{\text{conf}} = \exp(-\sum w_i Z_i^2)$ 在零偏离下理论期望 $\mathbb{E}[S] = 0.4648$ 的设计缺陷公式，已随前-`α` 连续 $S_{\text{conf}}$ 模块整体废除并由 `post-α` 门限额主公式 $G = B \cdot w(\tau) \cdot [s(\text{edge}) \cdot \lambda(L)]$（正常态 $\lambda(\text{GREEN})=1.0$、暂用恒等 `IdentityScaler` $s(\text{edge})=1.0$）取代（已于 `S3-06` 阶段一 `bff79e4` / 阶段二 `a861764` 落地）。现行权威：[`项目方案 (v3.0) §8.1 / §8.3.4`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#83-协议治理规则2026-11-18-当前决策)、[`P8-D6-POLICY-CLOSURE v1.0 §6`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#六-黄灯半额精确定义与-yellow_multiplier-作用点议程第-6-项) 与 [`test_m4_decision_engine.py`](../../tests/unit/decision/test_m4_decision_engine.py#L366-L386) 阶段二新基线。原文按冻结规则保留，本标注为唯一合法编辑。

1. **假设**：
   在零假设下，特征标准化残差 $Z_i = \frac{x_i - \mu_i}{\sigma^*_i} \sim \mathcal{N}(0, 1)$。三特征相互独立，权重等权 $w_i = 1/3$。
2. **推导**：
   - 方案 v2.8 原始公式：$S_{\text{conf}} = \exp\left(-\sum_{i=1}^3 w_i Z_i^2\right)$。
     其期望为三独立变量期望之积。利用高斯积分性质 $\mathbb{E}[e^{-t Z^2}] = (1 + 2t)^{-1/2}$（令 $t = 1/3$）：
     $$\mathbb{E}[S_{\text{conf}}] = \left( \frac{1}{\sqrt{1 + 2/3}} \right)^3 = \left(\sqrt{\frac{3}{5}}\right)^3 = (0.6)^{1.5} \approx \mathbf{0.464758}$$
   - 软死区改进公式：$S_{\text{conf}} = \exp\left(-\kappa \sum_{i=1}^2 w_i \text{softplus}(Z_i^2 - 1)\right)$（剔除 $x_{\text{cov}}$，两特征等权 $w_i = 0.5$）。
     通过一维数值数值积分求期望：
     $$\mathbb{E}[S_{\text{conf}}] = \left( \int_{-\infty}^\infty \exp\left(-0.3 \times 0.5 \ln(1 + e^{z^2 - 1})\right) \frac{1}{\sqrt{2\pi}} e^{-z^2/2} dz \right)^2 \approx \mathbf{0.83902}$$
3. **结论**：
   原版公式存在严重数学设计缺陷：**完全健康的零偏离模型在理论期望上直接被打 46 折！** 必须引入死区或平滑衰减，才能恢复“健康模型 0.80~0.85 期望分”的设计承诺。
4. **数值代入**：
   Monte Carlo 模拟（4000 轮抽样，seed=20260923）：
   - 原始公式实测模拟期望：$\mathbb{E}[S] = \mathbf{0.4646}$，中位数 $\mathbf{0.4552}$（与解析值 $0.4648$ 吻合）；
   - 软死区公式实测模拟期望：$\mathbb{E}[S] = \mathbf{0.8389}$，中位数 $\mathbf{0.8415}$（与解析值 $0.8390$ 吻合）。

---

### M4: Spearman 秩相关系数 $\rho(x_{\text{cov}})$ 的数学推导及并列秩敏感性分析
1. **假设**：
   样本量 $N = 22$。$x_i = |\text{v1\_coverage\_90}_i - 0.90|$，$y_i = s_{\text{oos}, i}$。数据集中存在完全相等的并列样本。
2. **推导**：
   Spearman 秩相关系数为排秩后的 Pearson 积矩：
   $$\rho = \frac{\sum_{i=1}^N (R(x_i) - \bar{R}_x)(R(y_i) - \bar{R}_y)}{\sqrt{\sum (R(x_i) - \bar{R}_x)^2 \sum (R(y_i) - \bar{R}_y)^2}}$$
   若存在并列值：
   - 平均秩算法（Average Tie-breaking）：并列第 $k$ 与 $k+1$ 位的样本平分名次，均赋值 $k + 0.5$。
   - 顺序秩算法（Ordinal Tie-breaking）：按输入原始顺序赋予连续整数秩 $k$ 和 $k+1$。
3. **结论**：
   两种算法的微小差异（$0.4672$ vs $0.4715$）100% 来源于并列秩的处理方式。无论哪种算法，$p$ 值均 $< 0.03$，统计实证上彻底推翻了 ADR-0019 宣称的“$x_{\text{cov}}$ 与 $s_{\text{oos}}$ 严格正交”。
4. **数值代入**：
   22 格数据中检测出 2 对并列值：
   - 并列对 1：`KORD_48h` 与 `KORD_54h`，值均为 $0.02876712$；
   - 并列对 2：`KMIA_36h` 与 `KMIA_42h`，值均为 $0.03186813$。
   代入实测：
   - `tie='average'`（scipy 默认）：$\rho = \mathbf{0.467232}$（四舍五入 **0.4672**）；
   - `tie='ordinal'`（连续整秩）：$\rho = \mathbf{0.471485}$（四舍五入 **0.4715**）。

---

### M5: 惩罚衰减函数数学形式对比（平滑 $\text{softplus}$ vs 硬截断 $\max(0, \cdot)$）
1. **假设**：
   自变量为二次标准化离差 $u = Z^2 - 1$。
2. **推导**：
   - 硬截断核：$g_1(u) = \max(0, u)$。
     一阶导数：$g'_1(u) = \mathbb{I}(u > 0)$。在临界点 $u = 0$ 处导数不连续，存在一阶跳跃（次梯度区间 $[0, 1]$）。下游参数敏感度产生梯度断裂。
   - 软死区核：$g_2(u) = \ln(1 + e^u)$。
     一阶导数：$g'_2(u) = \frac{e^u}{1 + e^u} = \sigma(u)$（标准 Sigmoid 函数），处处 $C^\infty$ 无穷阶光滑。
     渐近行为：
     当 $u \to -\infty$ 时，$g_2(u) \sim e^u \to 0$；
     当 $u = 0$ 时，$g_2(0) = \ln 2 \approx 0.6931$；
     当 $u \to +\infty$ 时，$g_2(u) \sim u$。
3. **结论**：
   Softplus 完美兼顾了死区对抽样噪声的压制和临界点的光滑可微性，杜绝了“微小扰动跨门槛导致额度悬崖下跌”的病态现象。
4. **数值代入**：
   当 $Z = 1.0$（即残差恰好处于 $1\sigma^*$ 门槛，演示假设值）：
   - 硬截断：$g_1(0) = 0.0 \implies \text{penalty} = \exp(0) = \mathbf{1.0000}$；
   - 软死区：$g_2(0) = 0.6931 \implies \text{penalty} = \exp(-0.3 \times 0.6931) = \mathbf{0.8122}$。

---

### M6: 特征相关性导致的重复惩罚量化推导
1. **假设**：
   模型发生方差失准，真实方差比为 $s_{\text{oos}}$。两道防线同时对同一失准现象反应。
2. **推导**：
   第一道防线方差调整：$\sigma_{\text{adj}} = \sqrt{s_{\text{oos}}} \cdot \sigma$。
   当 $s_{\text{oos}} > 1$（模型欠自信）时，第一道防线将预测方差拉大，导致峰值档位定价概率被稀释，交易净收益率下降：$\Delta \text{edge} \propto -(\sqrt{s} - 1)$。
   与此同时，90% 覆盖率受方差偏小拖累必然欠覆盖：
   $$1 - \text{Cov}_{90} \approx \Phi\left(-1.645 \sqrt{s_{\text{oos}}}\right)$$
   偏离量 $x_{\text{cov}} = |0.90 - \text{Cov}_{90}|$ 随之增大，导致第二道防线 $S_{\text{conf}}$ 再次扣分：$\Delta S_{\text{conf}} \propto -\frac{x_{\text{cov}}^2}{\sigma^{*2}}$。
   两层惩罚复合，总额度缩水幅度与失真呈四次方级别劣化。
3. **结论**：
   将 $x_{\text{cov}}$ 与 $s_{\text{oos}}$ 并存构成了对同源物理方差漂移的**双重非线性累加惩罚**。必须在 $S_{\text{conf}}$ 中彻底剥离 $x_{\text{cov}}$。
4. **数值代入**：
   以 `KMIA_30h_tmax` ($s_{\text{oos}} = 1.3638$) 为例：
   - 第一道防线：$\sigma$ 膨胀 $\sqrt{1.3638} = 1.1678$ 倍，定价概率从 $0.14$ 压低至 $0.12$（削减 14%）；
   - 第二道防线若计入 $x_{\text{cov}}$：实测覆盖率 84.89%，偏离 $0.0511$，$z_{\text{cov}} = 3.25\sigma$，导致 $S_{\text{conf}}$ 暴跌至 **0.35**。
   两层复合后总额度惨遭缩水至原值的 **28%**，属于典型的过度防御窒息交易。

---

### M7: 物理清零气候方差加法项对方差比 $s_{\text{oos}}$、覆盖率与 $z$ 的解析敏感度推导
1. **假设**：
   样本残差方差 $V_r = \text{Var}(y_{\text{obs}} - \mu_{\text{calib}})$。有效预报方差 $V_f = \mathbb{E}[\sigma_{\text{eff}}^2]$。气候方差加法项 $V_c = \sigma^2_{\text{clim}}$。
2. **推导**：
   生产代码错误添加 $V_c$ 时，方差比分母被严重抬高：
   $$s'_{\text{oos}} = \frac{V_r}{V_f + V_c} = s_{\text{oos}} \cdot \frac{1}{1 + V_c / V_f}$$
   芝加哥冬季气候方差 $V_c \approx 130 \ (^\circ\text{F})^2$，而条件 EMOS 方差 $V_f \approx 35 \ (^\circ\text{F})^2$，比值 $\frac{V_c}{V_f} \approx 3.7$。
   导致 $s'_{\text{oos}} \approx \frac{s_{\text{oos}}}{4.7} \approx 0.2 \sim 0.3$。
   同时，覆盖率判定区间被人工拉宽 $\sqrt{1 + 3.7} \approx 2.17$ 倍，导致原本在区间外的极端离差全部被包裹进区间，覆盖率暴增至 $98\% \sim 100\%$。
3. **结论**：
   代码中的气候加法项彻底摧毁了物理模型的方差辨识度，清零加法项是恢复统计科学性的唯一途径。
4. **数值代入**：
   以 `KORD_18h_tmax` 为例：
   - 加法项存在时（现状）：$s_{\text{oos}} = \mathbf{0.1023}$，90% 覆盖率高达 $\mathbf{100.0\%}$，$z_{\text{cov}} = \mathbf{6.37\sigma}$（门禁彻底被击穿）；
   - 清零加法项后（ADR-0015）：$s_{\text{oos}} = \mathbf{1.2240}$，90% 覆盖率恢复至 $\mathbf{88.77\%}$，$z_{\text{cov}} = \mathbf{0.79\sigma}$（完美达标）。

---

### M8: Golden Path 8 跳端到端定价与凯利配额确定性数值推导
1. **假设**：
   - 气象环境：`KORD_12h_tmax` (Winter, 2019-01-15)，$\bar{T}_{\text{ens}} = 31.0^\circ\text{F}, S^2_{\text{ens}} = 1.5 \ (^\circ\text{F})^2$；
   - 日内实况：$T_{\text{now}} = 26.0^\circ\text{F}$，距极值时间 $\Delta t = 6\text{h}$；
   - 盘口深度（演示假设挂单）：档位 $[36.0, 38.0]^\circ\text{F}$，最优卖单 $0.10$（500 份）、次优卖单 $0.11$（1000 份）；
   - 资金状态：$B_{\text{eff}} = 10,000\text{ pUSD}, W_{\text{free}} = 6,000\text{ pUSD}, \text{Active} = 2,500\text{ pUSD}$。
2. **推导**：
   - **第 1 跳（物理高斯分布）**：读取 `manifest.json` 中 `KORD_Winter_Max_lead12h.pkl`：$a=11.9896, b=0.8279, c=5.3884, d=1.7841$。
     $$\mu = 11.9896 + 0.8279 \times 31.0 = 37.6541^\circ\text{F}, \quad \sigma = \sqrt{5.3884^2 + 1.7841^2 \times 1.5} = 5.8146^\circ\text{F}$$
   - **第 2 跳（条件截断）**：截断点 $26.0^\circ\text{F}$，标准化分位数 $z = \frac{26.0 - 37.6541}{5.8146} = -2.0043$。
     $$\text{denom} = 1 - \Phi(-2.0043) = 1 - 0.0225 = \mathbf{0.9775}$$
   - **第 3 跳（离散映射）**：目标档位 $[36.0, 38.0]$ 概率：
     $$\hat{p}_0 = \frac{\Phi\left(\frac{38 - 37.6541}{5.8146}\right) - \Phi\left(\frac{36 - 37.6541}{5.8146}\right)}{0.9775} = \frac{\Phi(0.0595) - \Phi(-0.2845)}{0.9775} = \frac{0.1357}{0.9775} = \mathbf{0.1388}$$
   - **第 4 跳（第一道防线）**：契约 $s_{\text{oos}} = 0.888254 < 1.0$，膨胀因子为 $1.0$。
     $$\sigma_{\text{adj}} = \sqrt{\max(1.0, 0.888254)} \times 5.8146 = 5.8146^\circ\text{F} \implies \hat{p}' = \mathbf{0.1388}$$
   - **第 5 跳（穿透探针与动态费率）**：穿透 1500 份挂单，纯盘口均价 $\bar{P} = \frac{0.10 \times 500 + 0.11 \times 1000}{1500} = 0.106667$。
     $$q_{\text{eff}} = \bar{P} [1 + 0.05(1 - \bar{P})] = 0.106667 \times [1 + 0.05 \times 0.893333] = \mathbf{0.111431}$$
     $$\text{net\_ev} = 0.1388 - 0.111431 = 0.027369, \quad \text{edge} = \frac{0.027369}{0.111431} = \mathbf{+24.58\%}$$
   - **第 6 跳（第二道防线可信度）**：$z_{\text{ece}} = 0.7937, z_{\text{pit}} = 0.9494$。
     $$\text{penalty} = 0.3 \times [0.5 \times \text{softplus}(0.7937^2 - 1) + 0.5 \times \text{softplus}(0.9494^2 - 1)] = 0.1755$$
     $$S_{\text{conf}} = \exp(-0.1755) = 0.83902, \quad \psi(0.888) = 1.0 \implies \tau_{\text{conf}} = \mathbf{0.83902}$$
   - **第 7 跳（预算上限前置压缩）**：
     $$C_{\text{base}} = \min(0.10 \times 10000, 0.70 \times 10000 - 2500, 6000) = \mathbf{1000.00\text{ pUSD}}$$
     $$C_{\max} = \tau_{\text{conf}} \times 1.0 \times 1.0 \times 1000.00 = \mathbf{839.02\text{ pUSD}}$$
   - **第 8 跳（稳健凯利求解与最终下单）**：
     $$f^*_{\text{half}} = \frac{0.5 \times (0.1388 - 0.111431)}{1 - 0.111431} = 1.5413\% \implies f_{\text{raw}} = 154.13\text{ pUSD} \le C_{\max}$$
     $$\text{Shares} = \left\lfloor \frac{154.13}{0.106667} \right\rfloor = \mathbf{1444\text{ 份}}, \quad \text{Order Amount} = 1444 \times 0.106667 = \mathbf{\$154.03}$$
3. **结论**：
   全链路 8 跳数学闭环无缝贯通，各跳变量名严格承接，最终下单金额精确到 0.01 美元。
4. **数值代入**：
   最终下单金额为 **\$154.03**（买入 1444 份合约）。

---

## 5. 三个 $x$ 的完整口径定义与实测范围

| 符号 | 完整定义式 | 量纲 | 来源文件与行号 | 实测 22 格取值范围 |
| :-- | :-- | :-- | :-- | :-- |
| **$x_{\text{ece}}$** | $x_{\text{ece}} := \text{ECE}_{2^\circ\text{F}} = \frac{1}{11} \sum_{k=0}^{10} \|\hat{f}_k - \bar{p}_k\|$ | 无量纲概率离差 | `evidence/audit_v2/p4blind_v2r01_metrics.csv:1` (列 `ece_2f`) | `[0.00709, 0.01961]` (均值 0.01188) |
| **$x_{\text{cov}}$** | $x_{\text{cov}} := \|\text{Coverage}_{90} - 0.90\|$ | 无量纲覆盖率偏离 | `data/contracts/physical_param_contract.json` (列 `v1_coverage_90`) | `[0.00083, 0.04088]` (均值 0.02877) |
| **$x_{\text{pit}}$** | $x_{\text{pit}} := \text{Var}(U) = \frac{1}{n-1} \sum_{t=1}^n (u_t - \bar{u})^2$ | 无量纲方差 (理论值 1/12) | `evidence/audit_v2/p4blind_v2r01_metrics.csv:1` (列 `pit_var`) | `[0.07842, 0.08915]` (均值 0.08412) |

---

## 6. 判定结论与最小可行定义

> ⚠️ **本节内容已失效/被取代（2026-11-22 标定）**：本单针对前-`α` 链路的「需修正后可用」总判定（含 `J1 σ* 无定义`、`J2 x_ece 缺零基线校正`、`J3 E[S]=0.4648` 三项技术发现及 `B6 src/bankroll/ 缺失`）**均已全面销项并被现行 `post-α` 架构取代**：① `S_conf` 旧法源经 `P7-ALGO-2` 与 [`P8-D6-POLICY-CLOSURE v1.0`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) 合龙裁决废止，三项 `S_conf` 缺陷随 [`项目方案 (v3.0) §8`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#8-模块地图与协议层总索引v30-后-α-十模块静态结构与-p1p19-契约--2026-11-18-当前决策) 与 [`P8-D6-POLICY-CLOSURE §1.2/§1.3/§4/§6`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) 落地（$G = B \cdot w(\tau) \cdot [s(\text{edge}) \cdot \lambda(L)]$ + 离散 `P16 ECE` 锚）全面消解；② `src/bankroll/`（`M6`）及 `M4 λ(L)` 亦已于 `S3-06`（`bff79e4` + `a861764`）正式交付 [`src/bankroll/`](../../src/bankroll/__init__.py)。现行权威：[`P7-ALGO-2_裁决记录.md`](P7-ALGO-2_裁决记录.md)、[`P8-D6-POLICY-CLOSURE v1.0`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) 与 [`P8-PROJECT-TASKS v1.5`](P8-PROJECT-TASKS_全量任务分解台账.md)。原文按冻结规则保留，本标注为唯一合法编辑。

### 6.1 审计判定：**需修正后可用**
- **判据 J1（三 $\sigma^*$ 存在性）**：文档/代码均未定义数值与公式 $\to$ **不通过**；
- **判据 J2（零假设偏倚校准）**：未扣除 $b_{\text{ece}}$，导致健康模型 $z$ 虚高 $\to$ **不通过**；
- **判据 J3（零偏离期望）**：现行公式 $\mathbb{E}[S_{\text{conf}}] = 0.4648 \ll 0.75$ $\to$ **不通过**；
- **判据 J4（平滑可微性）**：单调性与连续性满足 $\to$ **通过**；
- **判据 J5（参数与契约绑定）**：契约缺 $n$ 与 $p_k$ $\to$ **不通过**；
- **判据 J6（下游执行链路）**：`src/bankroll/` 物理缺失 $\to$ **不通过**。

### 6.2 最小可行修正定义（可施工、无缺陷）
$$S_{\text{conf}} = \exp\left( -\kappa \left[ w_{\text{ece}} \cdot \text{softplus}\left(\frac{(x_{\text{ece}} - b_{\text{ece}})^2}{\sigma^{*2}_{\text{ece}}} - 1\right) + w_{\text{pit}} \cdot \text{softplus}\left(\frac{(x_{\text{pit}} - 1/12)^2}{\sigma^{*2}_{\text{pit}}} - 1\right) \right] \right)$$
- $\text{softplus}(x) = \ln(1 + e^x)$；
- $w = (0.5, 0.5)$（剔除共线的 $x_{\text{cov}}$，方差失真独占交由 $\psi(s_{\text{oos}})$ 惩罚）；
- $\kappa = 0.3$（F-2 锁定，标定后注入）；
- 完美校准下，期望得分稳定在 **0.80 ~ 0.85** 区间，彻底解除 54% 误杀。

---

## 7. 事实 / 推断 / 未找到证据 三栏归位

| 事实（读码或执行命令直接观测之客观结果） | 推断（基于客观事实的数理外推） | 未找到证据（代码与文档中物理缺失项） |
| :-- | :-- | :-- |
| `src/bankroll/` 目录物理不存在；全仓除说明字符串外无 $S_{\text{conf}}$、$\psi$、Kelly 实现代码 | 现行 $S_{\text{conf}}$ 若直接落码，将随机腰斩 54% 的健康模型下注额度 | 未找到 `σ*_ece / cov / pit` 的法定数学定义式或标定数值 |
| 生产代码 `gaussian_emos.py:65` 仍包含 `clim_var` 加法项，与方案 v2.8 / ADR-0015 冲突 | 生产代码若继续保留气候加法项，盘口 Edge 将完全被虚胖方差抹平 | 未找到 `ψ(s_oos)` 的参数值、标定记录或代码工程实现 |
| 契约中 `v1_coverage_90` 读自 V1 CSV，V2 脚本自身从未重算过覆盖率 | 契约中的校准参数描述的是含 $b30$ 与 JSU 的分布，与纯高斯生产推理存在稳态漂移 | 未找到生产管线从离散概率到 `compute_probe` 的调用接线 |
| `p_k` 虽未落盘，但可从 parquet 结算数组与 JSU 参数无损重构并可验证 | $x_{\text{cov}}$ 与 $s_{\text{oos}}$ 确定性共线，现行两道防线存在严重的双重惩罚 | 未找到 `fractional_multiplier` 的生产取值逻辑与参数配置文件 |
| 22 格中有 12 格实测 ECE 低于有限样本抽样偏倚基线 $b_{\text{ece}}$ | 只要扣除 $b_{\text{ece}}$ 并引入软死区，零假设期望即可恢复至 0.80~0.85 | 未找到契约自身的内容自哈希校验字段 |

---

## 8. 附录：复现工件、校验和与复现命令

### 8.1 核心数据资产 SHA-256 校验和（逐字原样）
```text
3225362fa0e15f4a9907929f8ffe7d882e7c33d1254697d3e4ab9921bf470e70  data/processed/audit_arrays/2019_oos_p4_settlement_arrays.parquet
3ed2350d49e88e1f48131a386b299ea3d1cbe0f54bcbb68078bdb1bd3bb7936f  evidence/p4_2019_settlement_statistics.csv
246397fdeff31384c1703d8ce3fa049028cb6d44254c23997261c6bb276ee8a5  evidence/p4_active10_climate_calibration.json
ae615945bc35a72fb9f9c2de04f26033637ad080f7cf70fc66b514065ccb611a  evidence/audit_v2/p4blind_v2r01_metrics.csv
572cc7cb8f033ddda8317d0e6b729ea8dc041cb085e1e1f0be3ffb022da6af21  evidence/audit_v2/p4blind_v2r01_comparison.csv
315e21e7347e322c79bcbd781987831ecdb151bdc939fa9c11f45dfd48c0608c  data/contracts/physical_param_contract.json
8bb364e26b8228a50372cfbcd7b0f7a5378b083b99bcb648c727d5e8c4de98eb  data/models/manifest.json
245de325b2788983bbdcb5620d0dc5c5036857c6f0fa5553722c4d3f27880a08  data/processed/climate_floor/KORD_climate_floor.parquet
1744f0b3dc4957360c93b247f267b6177b025bd249309b4b10e0b179bc24a106  data/processed/climate_floor/KMIA_climate_floor.parquet
```

### 8.2 独立复现命令
```bash
python3 docs/audit/annex/CHK-01_repro/repro_chk01.py
```
该命令执行耗时约 6 秒，将原样重现本文第 2、3、4 节中全部实测数值、相关系数、对账表与 Golden Path 8 跳输出。
