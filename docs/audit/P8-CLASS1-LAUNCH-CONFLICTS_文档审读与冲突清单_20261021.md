# P8-CLASS1-LAUNCH-CONFLICTS · 第一类投注定价层文档审读与冲突清单

> **工单（B 线）**：`P8-CLASS1-LAUNCH`（治理批次 8）  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-02`  
> **编制角色**：开发组 Agent  
> **审读对象**：  
> 1. `P8-CLASS1-LAUNCH-PROPOSAL_第一类投注定价算法方案书_20261021.md`  
> 2. `docs/项目方案和执行文档/Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md`  
> 3. `docs/audit/P7-ALGO-VERDICT.md`（v1 遗产判决书）与 `P7-ALGO-2_裁决记录.md`  
> 4. `src/modeling/registry.py`（模型存储、元数据与 manifest）  
> 5. `scripts/evaluate_p4_2019_settlement.py`（结算与盲测评估脚本）  
> 6. `evidence/audit_v2/p4blind_v2r01_metrics.csv` 与 `p4blind_v2r01_comparison.csv`  
> **交付目的**：在进入 to-spec ②（grilling）与 ③（拆票）前，逐项排查边界、数据源与口径冲突，呈用户确认。

---

## 一、 冲突清单汇总表（逐条：覆盖 / 保留 / 待确认）

| 编号 | 冲突主题 | 冲突现状说明 | 涉及文件 / 规范 | 处置建议类别 | 推荐裁决方案概要 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **C-01** | **Task 边界与编号冲突 (G-4)** | 原方案书将联合凯利、定价探针、风控与纸面盘统称为「Task 04」，与 v2.1 既有 Task 04（2°F 映射+动态 EV，已完成）重名，且侵入已顺延的 Task 05/06 及未完成的 Task 07。 | `Phase 2 执行文件 v2.1` §4;<br>`P8-CLASS1-LAUNCH-PROPOSAL` §七 | **待用户裁定** | **按用户 U-2/U-4 裁定**：C-01 的“新建 Task 08”处置作废；先完成 Task 01~07 全量状态盘点与 close/废除/停止处置，新任务编号待裁决后再定。 |
| **C-02** | **方差比双重计权冲突 (G-1)** | 方案书 $S_{\text{conf}}$ 输入含 $x_s = \|s_{\text{oos}}-1\|$，而总折减又定义为 $\tau_{\text{conf}} = \psi(s_{\text{oos}}) \cdot S_{\text{conf}}$，同源信号发生乘法叠乘惩罚。 | `P8-CLASS1-LAUNCH-PROPOSAL` §2.2, §2.4 | **覆盖修订** | **信号正交化**：$\psi(s_{\text{oos}})$ 独占方差偏离维度，$S_{\text{conf}}$ 剔除 $x_s$，改由 ECE、覆盖率、PIT 方差三纯形态/可靠性特征组成，消灭双重惩罚。 |
| **C-03** | **欠自信双处理分工边界 (G-2)** | 方案书对 KMIA 欠自信同时采用 $\sigma_{\text{adj}}$ 外展（定价侧）与 $\psi$ 预算折减（配资侧），缺乏清晰的职责隔离。 | `P8-CLASS1-LAUNCH-PROPOSAL` §2.5 | **成文澄清** | **职责严格切分**：$\sigma_{\text{adj}}$ 专司「定价区间诚实性与防虚报 Edge」；$\psi$ 专司「下注资金风险敞口控制」。写入 ADR。 |
| **C-04** | **覆盖率数据源列名冲突 (G-3)** | 方案书提及 `x_cov` 取自盲测数据，但 `p4blind_v2r01_metrics.csv` 无覆盖率列；实际落盘于 `p4blind_v2r01_comparison.csv` 的 `v1_coverage_90` 列。 | `evidence/audit_v2/` 两 CSV;<br>`P8-CLASS1-LAUNCH-PROPOSAL` §2.2 | **覆盖修正** | **精确钉死数据源**：明确 $x_{\text{cov}}$ 唯一源自 `comparison.csv` 的 `v1_coverage_90` 列，门禁判定取 `v1_coverage_90_pass`。 |
| **C-05** | **预算压降确定性表述冲突 (G-5)** | 方案书写明“KMIA 预算压降至 40%~60%”，但软折减参数挂 `[F-2 LOCKED]`，定值表述违反 F-2 锁铁律。 | `P8-CLASS1-LAUNCH-PROPOSAL` §2.5, §五 | **成文澄清** | **勘误口径**：将“40%~60%”明确标注为「参考仿真工程预期（Heuristic Expectation）」，非生产承诺定值。 |
| **C-06** | **物理参数消费与解耦规范缺失 (G-6)** | 方案书仅强调 Q1/Q7，未建立物理模型全部输出参数（22 格 × 参数）向投注算法消费的正式契约，缺乏版本戳绑定。 | `src/modeling/registry.py`;<br>`CHK-02` §六 | **增补新建** | **建立参数消费契约 ADR**：逐参数定义消费/不消费；按 22 格独立组织；绑定模型 manifest SHA256 版本戳；明确过自信/欠自信处置边界。 |

---

## 二、 逐项冲突深度对账与论证

### 2.1 C-01 · Task 边界与编号对账（G-4 核心）

- **现役文档基线（《Phase 2 执行文件 v2.1》§4 任务矩阵）**：
  - `Task 01 模型重训与验收`：已完成并封盘（960 个生产模型）；
  - `Task 02 订单簿重建与动态价差`：W2 先锋攻坚；
  - `Task 03 异常处理与仲裁状态机`：标记为 `DEFERRED_TO_PRE_LIVE`；
  - `Task 04 概率映射与 EV 引擎`：现役树已包含 `discrete_bin_engine.py`、`truncated_probability_engine.py` 及配套 113 个单测，专注 2°F 档位离散概率计算；
  - `Task 05 资金管理与凯利分配`：标记为 `DEFERRED_TO_PRE_LIVE`；
  - `Task 06 保护价计算与订单路由`：标记为 `DEFERRED_TO_PRE_LIVE`；
  - `Task 07 风控联动与纸面盘验证`：包含两维风控与 48h 只读纸面盘模拟。
- **冲突所在**：
  原方案书将“第一类投注/定价落地”笼统命名为 `Task 04`。若强行使用 Task 04，将导致：① 与已经完成的 2°F 离散映射 Task 04 产生同名污染；② 违反《AGENTS.md》“已完成任务是冻结历史记录，内容永不改写”的硬性铁律。
- **推荐处置方案（按用户 U-2/U-4 裁定更新）**：
  原“新建 Task 08”处置方案已被用户裁决否决作废。
  当前法定前置门为：先对既有 Task 01~07 逐项完成状态盘点，并提交审核方复核与用户签署 close / 废除 / 停止裁决。新任务编号待用户对 Task 01~07 处置签署完成后再定，在此之前不立新编号。

---

### 2.2 C-02 · s_oos 双重计权对账（G-1）

- **冲突机理**：
  方案书中：
  $$S_{\text{conf}} = \exp\left( - \left( w_s \cdot (x_s/\sigma_s^*)^2 + w_{\text{ece}} \cdot (x_{\text{ece}}/\sigma_{\text{ece}}^*)^2 + \dots \right) \right)$$
  若将 $x_s = |s_{\text{oos}} - 1|$ 放入 $S_{\text{conf}}$，而最终预算折减乘数为：
  $$\tau_{\text{conf}} = \psi(s_{\text{oos}}) \cdot S_{\text{conf}}$$
  当 $s_{\text{oos}} = 1.30$ 时，$\psi$ 会压降（如降至 0.5），而 $S_{\text{conf}}$ 内部的 $x_s = 0.30$ 又使 $S_{\text{conf}}$ 压降（如降至 0.6），导致 $\tau_{\text{conf}} = 0.30$。这实际上对同一种物理缺陷（方差失真）进行了**两次乘法惩罚**。
- **推荐处置方案**：
  **维度正交化解耦**：
  1. $\psi(s_{\text{oos}})$ 独立承载**方差比失真（离散度偏离）**维度；
  2. $S_{\text{conf}}$ 剔除 $x_s$，仅聚合**纯可靠性与分布形状特征**：
     $$S_{\text{conf}} = \exp\left( - \left( w_{\text{ece}} \cdot \left(\frac{x_{\text{ece}}}{\sigma_{\text{ece}}^*}\right)^2 + w_{\text{cov}} \cdot \left(\frac{x_{\text{cov}}}{\sigma_{\text{cov}}^*}\right)^2 + w_{\text{pit}} \cdot \left(\frac{x_{\text{pit}}}{\sigma_{\text{pit}}^*}\right)^2 \right) \right)$$
  3. 彻底消除同源信号内部干涉，数理意义清晰。

---

### 2.3 C-03 · 欠自信双处理边界对账（G-2）

- **冲突机理**：
  针对 KMIA 欠自信（$s_{\text{oos}} \approx 1.28 \sim 1.36$），方案书同时提出了 $\sigma_{\text{adj}}$ 外展与 $\psi$ 折减，二者是否功能重叠？
- **对账结论**：
  二者作用于完全不同的数学环节，**不仅不重叠，而且构成防守纵深**：
  - **$\sigma_{\text{adj}} = \sqrt{s_{\text{oos}}} \cdot \sigma_{\text{eff}}$（定价层）**：
    作用对象是订单簿探针定价 $\bar{P}$ 与 M-1 稳健凯利的不确定集 $\mathcal{P}$。当模型欠自信时，真实温度波动更大，$\sigma_{\text{adj}}$ 迫使不确定集加宽，**压低计算出的边际优势（Edge）**，防止系统为虚假 Edge 报价；
  - **$\psi(s_{\text{oos}})$（资金层）**：
    作用对象是总预算上限 $C_{\max}$。即便在 $\sigma_{\text{adj}}$ 外展后依然存在正 EV 优势，由于该格历史方差稳定性较差，$\psi$ 依然会**限制总资金暴露上限**，防范系统性回撤；
  - **结论**：前者防虚假信号，后者控资金暴露，分工明确，写入 ADR-0019。

---

### 2.4 C-04 · 覆盖率数据源精确对账（G-3）

- **实测代码与数据资产审读**：
  查阅 `evidence/audit_v2/` 下的两份法定 CSV：
  1. `p4blind_v2r01_metrics.csv`（26 列）：
     列包含 `n, s_oos, rho1, neff, finf_lo, finf_hi, finf_in, fstd_lo, fstd_hi, fstd_in, ks_stat, ks_p, cvm_stat, cvm_p, reject_uniform, ece_2f, ece_7bin_v1, ece_bins10, ece_bins20, ece_range, pit_mean, pit_var, max_prob_dev, ece_eqfreq_q10, pit_hist_b01...b10`。**确实无覆盖率列**；
  2. `p4blind_v2r01_comparison.csv`（23 列）：
     包含 `v1_coverage_90` 与 `v1_coverage_90_pass` 列。
     实测值举例：
     - `KORD_18h`: `v1_coverage_90 = 0.909589`, `pass = True`
     - `KMIA_12h`: `v1_coverage_90 = 0.871233`, `pass = True`
     - 22 格全部在 G5 冻结带 $[0.83, 0.95]$ 内通过。
- **推荐处置方案**：
  在代码和规范中明确写入：
  $x_{\text{cov}}$ 的唯一权威读取字段为 `p4blind_v2r01_comparison.csv` 的 `v1_coverage_90` 列；其偏离度 $x_{\text{cov}} = |\text{v1\_coverage\_90} - 0.90|$；门禁校验布尔为 `v1_coverage_90_pass`。

---

### 2.5 C-05 · 预算压降表述勘误（G-5）

- **冲突机理**：
  方案书 §2.5 中“将该时间格下注预算 $C_{\max}$ 压降至 40%~60%”容易被误解为已给出生产定值，违反 F-2 锁约束。
- **推荐处置方案**：
  立即在方案书中补充修订说明：
  “40%~60% 仅为基于经验初值设定的启发式仿真预期（Heuristic Simulation Expectation），用于直观解释平滑折减的工程效果。该数值受 F-2 锁保护，非生产定值；正式定值将完全由纸面盘自产数据与两步标定法严密产出。”

---

### 2.6 C-06 · 物理参数消费契约与解耦对账（G-6）

- **审读输入**：
  - 物理模型层输出（未入 CSV）：
    - `mu_calib`：因果 30 天偏置校准后的均值；
    - `sig_eff = sig_raw * c_train`：含站×季方差膨胀因子的有效标准差；
    - 分布族与族参数：KORD（冬/春/秋 Johnson SU $(\gamma, \delta, \xi, \lambda)$，夏 Gaussian $\sigma$）；KMIA（四季 Johnson SU）；
    - 2°F 档位离散概率 $p_j$：`DiscreteBinEngine` 输出。
  - 模型存储元数据（`src/modeling/registry.py`）：
    - `data/models/emos/{station}/{variable}_{season}_{lead}h.json` 包含参数与训练诊断；
    - 模型文件具备 SHA256 校验和与 manifest 验证体系。
- **推荐处置方案**：
  制定完整的《物理模型参数向投注算法消费契约》，输出 **ADR-0019** 与《参数消费矩阵》（详见后续 Grilling 与 ADR 交付物）。

---

## 三、 请用户确认事项

开发组已完成上述 6 项冲突的深度审读，请用户对以下核心事项进行确认/指示：
1. **Task 编号与归属**：是否同意采用 **方案 A**（新建独立交付主工单 `Spec: Phase 2 Task 08 - 第一类投注定价算法与只读纸面盘落地`），避免破坏冻结的 Task 01~04 历史？
2. **冲突清单整体结论**：对 C-01 ~ C-06 的排查结果与推荐处置方案是否批准？

批准后，开发端将立即进入 Step 4.2（grilling 问答与 ADR 产出）！
