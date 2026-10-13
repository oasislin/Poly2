# P7-ALGO-2 算法描述文档（数学公式完备版，主导方初稿）

> **文档编号**：P7-ALGO-2-MATH  
> **版本**：v0.2（主导方初稿；**待开发端挑战审阅**，未定稿——2026-10-13）  
> **配套**：《P7-ALGO-2 规格书》v0.2（本文件为其数学章节的完备展开）  
> **状态**：全部公式为结构定义；所有涉及标定/sizing 的参数 `[F-2 LOCKED]` / `[待标定]` / `[待核实]`，不填实值  
> **依据**：判决书 M-1~M-8、卷宗 §4（v1 公式摘录）、ADR-0011~0015/0018、归档代码契约（ev_engine / risk_limiter / order_router / paper_engine / tests）、Debate 冻结共识

---

## 1. 记号与输入

| 记号 | 含义 | 来源 |
| :--- | :--- | :--- |
| $K$ | 档位数（互斥完备市场，如 11 档 2°F 离散区间） | 方案 v2.8 |
| $\hat p_i$ | 第 $i$ 档概率（EMOS 概率层输出，截断后，$\sum \hat p_i = 1$） | 概率层（F-2 管辖） |
| $q_i$ | 第 $i$ 档盘口 ask 价 | CLOB 盘口 |
| $q_{\text{eff}, i}$ | 第 $i$ 档含费率有效买入成本 | §2 |
| $N_i$ | 第 $i$ 档既有持仓（payout 沉没成本，只买不卖下为外生常数） | 四桶账务 |
| $W_{\text{free}}$ | 可自由资金（Free USDC） | 四桶账务 |
| $B_{\text{eff}}$ | 有效资金 $= \text{Free} + \text{Active}$（sizing 母数，Zombie/Disputed 以 0.0x 剔除） | ADR-0012 |
| $f_i$ | 第 $i$ 档拟投入金额（决策变量，$f_i \ge 0$） | 本规格 |
| $\text{base}$ | Polymarket 动态费率基础值（v1 现值 0.0125） | M-2（`[待核实]`） |
| $\text{min\_edge}$ | 最小 Edge 门槛（结构保留，数值 `[待标定]`） | §2 |
| $\theta, \eta$ | 不确定集宽度参数 | M-1（`[F-2 LOCKED]`） |
| $\delta_\mu, \delta_\sigma$ | EMOS 参数（μ, σ）的不确定性尺度 | M-1（`[F-2 LOCKED]`） |
| $m_{\text{dutch}}$ | 套利安全边际（v1 现值 2%，**不继承**） | M-3（`[待标定]`） |

---

## 2. 定价：VWAP 深度穿透与动态费率

### 2.1 VWAP 深度穿透（S1）

按目标规模 $S_{\text{target}}$ 累计 ask 档（价格升序 $j=1,2,\dots$）：

$$S = \sum_{j} s_j \quad \text{（累计至 } \min(S_{\text{target}}, \text{盘口总深度})\text{）}$$

$$\bar P = \frac{\sum_j p_j \cdot s_j}{\sum_j s_j} \quad \text{（纯盘口加权均价）}$$

- 对齐归档 `ev_engine.calculate_effective_price` 契约；深度不足时按可成交部分计。

### 2.2 动态费率折算（M-2 已裁；Debate 约束 1 冻结）

**时序铁律：先穿透得纯盘口均价 $\bar P$，再统一施加费率，严禁逐层非线性迭代。**

$$q_{\text{eff}} = \bar P \cdot \left[1 + \text{base}\cdot(1 - \bar P)\right]$$

- 等价于 v1 `strategy.py:691` 已裁公式 $q = p\cdot[1+\text{base}\cdot(1-p)]$（卷宗 4.2）；
- 边缘情形：$\bar P \to 0$ 时绝对费用小但费率摩擦高，EV 判定保留 edge 的费率敏感性（不得因绝对费用小忽略）；
- 参数：$\text{base}=0.0125$ `[待核实]`（M-2 闭环项）；Maker 返佣 $\beta=0.20$ 的判定式见 §9。

### 2.3 EV 与 Edge（S1 交易信号）

$$\text{net\_ev}_i = \hat p_i - q_{\text{eff}, i}$$

$$\text{edge}_i = \frac{\text{net\_ev}_i}{q_{\text{eff}, i}} = \frac{\hat p_i - q_{\text{eff}, i}}{q_{\text{eff}, i}}$$

**可交易判定**：$\text{tradable}_i = \big(\text{edge}_i \ge \text{min\_edge}\big) \wedge \big(\text{治理旗放行}\big)$

- 治理（用户裁决 A）：带旗资产 $\text{tradable}_i = \text{False}$（只观测、不交易，直至拔旗）；FAILSAFE 只读；
- $\text{min\_edge}$：结构保留（覆盖 Noise Floor 语义：v1 Maker 3.5% / Taker 5.0% 已归档不继承，数值 `[待标定]`）。

---

## 3. 凯利目标函数（多项增量对冲，v2 基线 + N_i 注入）

### 3.1 结局财富

第 $i$ 档胜出时的结局财富（买入 $f_i / q_{\text{eff}, i}$ 股，总投入 $\sum_j f_j$，既有持仓 $N_i$ 为沉没成本）：

$$W_i(f) = W_{\text{free}} + N_i + \frac{f_i}{q_{\text{eff}, i}} - \sum_{j=1}^{K} f_j$$

### 3.2 目标函数与约束

$$\max_{f} \; G(f) = \sum_{i=1}^{K} \hat p_i \cdot \ln W_i(f)$$

$$\text{s.t.} \quad f_i \ge 0 \quad \forall i \quad \text{（只买不卖）}$$

$$\sum_i f_i \le C_{\max} := \min\left(0.10 \cdot B_{\text{eff}},\; 0.70 \cdot B_{\text{eff}} - \text{Active\_locked},\; W_{\text{free}}\right)$$

$$W_i(f) > 0 \quad \forall i \quad \text{（对数定义域；若不可行则 fail-closed 全零）}$$

- 对齐归档 `multinomial_kelly.py` 契约：正 EV 档分配、负 EV 归零、概率翻转自然转向（新钱解决）、非法输入 fail-closed 归零；
- $q_{\text{eff}}$ 在**决策快照内冻结**（按预估规模），不对 SLSQP 迭代重算（N3 决策快照冻结）。

### 3.3 凹性与收敛性（回应开发端质询：N_i 注入后是否仍凸且收敛）

**引理 1（凹性）**：$\ln\big(W_{\text{free}} + N_i + \frac{f_i}{q_{\text{eff},i}} - \sum_j f_j\big)$ 是 $f$ 的凹函数（线性函数之对数）。

**引理 2（保凹性）**：非负加权和保凹——$G(f) = \sum_i \hat p_i \ln W_i(f)$ 是凹函数。

**引理 3（可行域凸性）**：$\{f \ge 0,\; \sum f \le C_{\max}\}$ 为凸集（box + 单形约束）。

**结论**：$\max_f G(f)$ 为**凹最大化于凸集**——SLSQP 收敛到全局最优；既有持仓 $N_i$ 仅平移 $W_i(f)$ 的常数项（$W_{\text{free}} + N_i$），**不改变凹性结构**，收敛性保持。该论证同样适用于稳健化目标（§6，因 min 保凹）。

---

## 4. 稳健化：不确定集构造（M-1 改造；Debate Q1 冻结）

### 4.1 双源区间宽度（Delta Method + η 尾部膨胀，取 max）

$$\text{SE}_i = \max\left(\text{SE}_{\text{EMOS}, i},\; \eta\sqrt{\hat p_i(1 - \hat p_i)}\right)$$

$$\text{SE}_{\text{EMOS}, i} = \left|\frac{\partial p_i}{\partial \mu}\right| \delta_\mu + \left|\frac{\partial p_i}{\partial \sigma}\right| \delta_\sigma$$

**高斯族闭式灵敏度**（双参数 CDF，$z_a = (a_i-\mu)/\sigma$，$z_b = (b_i-\mu)/\sigma$，$\varphi$ 为标准正态密度）：

$$p_i = \Phi(z_b) - \Phi(z_a)$$

$$\frac{\partial p_i}{\partial \mu} = \frac{\varphi(z_a) - \varphi(z_b)}{\sigma}$$

$$\frac{\partial p_i}{\partial \sigma} = \frac{z_a\,\varphi(z_a) - z_b\,\varphi(z_b)}{\sigma}$$

（JSU / EVT-Hybrid 族同法解析，规格书标注公式族，推导随实现落地——开放项 2。）

### 4.2 区间与冻结

$$p_{L,i} = \max\left(0,\; \hat p_i - \theta \cdot \text{SE}_i\right), \qquad p_{U,i} = \min\left(1,\; \hat p_i + \theta \cdot \text{SE}_i\right)$$

- **快照冻结**：$\text{SE}_i, p_{L,i}, p_{U,i}$ 在决策快照内固定，不进 SLSQP 迭代重算（保贪心投影 $O(K\log K)$ 与收敛性——Debate Q1 冻结）；
- **可行性条件**：$\sum_i p_{L,i} \le 1 \le \sum_i p_{U,i}$（否则退化处理，fail-closed 或归一化，规格书开放项）；
- 参数：$\theta, \eta, \delta_\mu, \delta_\sigma$ 全部 `[F-2 LOCKED]`（v1 θ=1.5/η=0.15 仅归档不继承）。

---

## 5. 稳健 Minimax：内层贪心最坏情况投影（M-1；O(K log K)）

固定 $f$（外层迭代），求解最坏分布：

$$\min_{p \in \mathcal{P}} \; \sum_{i=1}^{K} p_i \ln W_i(f), \qquad \mathcal{P} = \left\{p : p_{L,i} \le p_i \le p_{U,i},\; \sum p_i = 1\right\}$$

**精确解（非近似）**：目标对 $p$ 线性，box + 单形约束下极值点在极点——按 $\ln W_i$（等价 $W_i$）**升序**，将概率质量优先分配给财富最差结局：

1. 排序：$\pi = \text{argsort}(W_i)$（升序，$O(K\log K)$）；
2. 从最差档开始：$p_{\pi(k)}^* = \min\big(p_{U,\pi(k)},\; 1 - \sum_{\text{已分配}}\big)$，直到 $\sum p^* = 1$；
3. 其余档 $p^* = 0$（若 $p_{L}$ 强制下限使 $\sum p_L > 1$，触发可行性退化分支）。

- 对齐 v1 `project_worst_case_probabilities` 结构（卷宗 4.1）；
- **精确性**：线性规划在 box+simplex 上的最优解由贪心排序给出，非启发式近似。

---

## 6. 稳健 Minimax：外层 SLSQP（M-1）

$$\max_{f \in \mathcal{F}} \; \min_{p \in \mathcal{P}} \; \sum_{i=1}^{K} p_i \ln W_i(f)$$

$$\mathcal{F} = \left\{f \ge 0,\; \sum f \le C_{\max},\; W_i(f) > 0\right\}$$

- 内层 min 保凹（凹函数逐点下确界仍凹），外层仍为凹最大化 → SLSQP 全局收敛（引理 1~3 推广）；
- **Fail-Closed（Debate 约束 2 冻结）**：
  - 预设 `maxiter = 200`、`ftol = 1e-9`；
  - `res.success == False` 或结果含 NaN → **100% 回退全零向量**（不分配资金）；
  - NaN/脏解防御覆盖**输入**（p̂ 含 NaN/越界）与**输出**（f* 含 NaN）两方向；
  - 连续 $N$ 次失败 → 联动 ADR-0014 上报（台站降级/人工介入），不止静默归零。

---

## 7. 风控门禁不等式（S3，全部下沉为布尔判定）

| # | 门禁 | 不等式 / 判定 | 来源 |
| :--- | :--- | :--- | :--- |
| G1 | 单市场硬顶 | $\sum_i f_i \le 0.10 \cdot B_{\text{eff}}$（超限按比例缩水） | ADR-0012 / risk_limiter 契约 |
| G2 | 全局利用率 | $\big(\text{Active\_locked} + \sum_i f_i\big) \big/ \text{Total} \le 0.70$ | ADR-0012 / risk_limiter 契约 |
| G3 | 僵尸分级折剪 | $\tau_z \in \{1.0,\;0.5,\;0.0,\;0.0\}$ 对应 R_z ≤ 15% / ≤ 30% / ≤ 50% / > 50% | ADR-0012 / zombie_evaluator 契约 |
| G4 | 两维风控 | CRITICAL：$T_{\text{rem}}<1\text{h} \wedge \Delta T > 3^\circ\text{F}$ → 0.20x；CERTAIN：$T_{\text{rem}}<0.5\text{h} \wedge \Delta T \le 0.5^\circ\text{F}$ → 禁反向投机；否则 1.00x | ADR-0011 / two_dimensional_risk 契约 |
| G5 | 带旗治理（用户裁决 A） | $\text{FLAGGED} \Rightarrow \text{tradable} = \text{False}$（只观测）；$\text{FAILSAFE} \Rightarrow$ 只读 | 方案 v2.8 §4 / R-19 |
| G6 | 预购门 | $\Delta_{\text{age}} \le 7\text{min} \wedge \text{数据连通} \wedge \text{网关连通} \wedge \text{ACTIVE} \wedge \text{阀开}$ | ADR-0014 / pre_buy_gate 契约 |
| G7 | 求解器 Fail-Closed | $\text{success} \wedge \neg\text{NaN} \wedge W_i(f)>0$ 全部成立才放行 | Debate 约束 2 |

**批准分配**：$x_{\text{approved}} = \tau_z \cdot \tau_{\text{2D}} \cdot f^*$（G3×G4 调制；G5 为前置禁投；G1/G2/G6/G7 为硬门禁，不调制只放行/阻断）。**折剪点唯一化**：调制全在 S3，无第二折剪点（带旗禁投使治理折剪不存在）。

---

## 8. 执行定价（S4：保护价 + IOC）

### 8.1 保护价（EV 零点）

遍历 ask 档 $j$（价格升序），对第 $i$ 档目标：

$$\text{edge}_j = \frac{\hat p_i - q_{\text{eff}, j}}{q_{\text{eff}, j}} \ge \text{min\_edge} \quad \text{（$q_{\text{eff}, j}$ 按 §2.2 折算）}$$

$$P_{\text{protect}, i} = \text{最后一个达标档的 ask 价}, \qquad \text{safe\_capacity}_i = \sum_{\text{达标档}} s_j$$

- 对齐归档 `order_router.calculate_protection_price` 契约；
- IOC 限价单，**严禁市价单**（`MarketOrderForbiddenError`，归档 models.py 契约）。

### 8.2 残差愈合（非原子成交）

- 部分成交 → 30s 内限价再对冲（rehedge）；超时或亏损击穿 → 硬止损移交人工 / 保持持有至结算；
- 状态机：CLEAN / RESOLVED_BALANCED / LIQUIDATED（归档 residual_risk 契约）。

---

## 9. 套利通道（S6：独立旁路，Debate Q2 + 主导方补充冻结）

### 9.1 判定式（含费率，M-3）

**全包 YES**：$\sum_{i=1}^{K} q_{\text{eff}, i} \le 1 - m_{\text{dutch}}$

**反向 NO 锁利**（买入 NO 组合与单档 YES 之间）：按对应互补价格折算后同样式判定。

- $m_{\text{dutch}}$：**新参数，不继承 v1 2%**（用户裁决），`[待标定]`；
- Taker 与 Maker 两套判定式分别落位（Maker 返佣 $\beta=0.20$ 按 v1 §4.2 结构，参数 `[待核实]`）。

### 9.2 资金与优先级

$$\text{套利预算} \le \min\big(W_{\text{free}},\; C_{\text{total}} - \text{Active\_locked}\big)$$

$$\text{且} \le \text{盘口现实可成交深度（M-3 拷问 3 约束）}$$

- **豁免**：$C_{\text{loc}}$（10% 单市场）；**不豁免**：70% 全局利用率（主导方补充 N2）；
- 占用计入 Active Locked；执行后剩余 Free 与最新持仓注入 S2 凯利增量对冲；
- 必须向 ADR-0014 中枢登记 `IncidentEvent(SUB_ARBITRAGE, DUTCH_BOOK_DISPATCH)`（禁止静默穿仓）。

---

## 10. 概率层门禁：ECE 梯级判定（Q6 冻结 + 用户确认继承声明）

$$\text{F-2 绿灯} = \begin{cases}
\text{GREEN（完全解锁标定）} & \text{Binding ECE} \le 0.05 \wedge \text{交易窗口 ECE} \le 0.0100 \\
\text{YELLOW（带旗，按 A 禁投只观测）} & \text{Binding ECE} \le 0.05 \wedge \text{交易窗口 ECE} > 0.0100 \\
\text{RED（全线熔断）} & \text{Binding ECE} > 0.05
\end{cases}$$

- **口径继承声明**：两口径继承自模型训练/抽检时设定的阈值（ADR-0018 Binding ≤5% + 方案 v2.8 交易窗口加权 ≤0.0100），交易层只消费判定结果，不产生、不修正概率（P1）；
- **联动调整契约**：版本更新时概率层与交易层协同调整口径（两侧确认、留痕、回灌门禁）；
- RED 联动 ADR-0014 fail-closed（全线熔断/只读）。

---

## 11. 结算与账务（S5/S7：四桶恒等与双轨估值）

$$\text{Total} = \text{Free} + \text{Active} + \text{Zombie} + \text{Disputed} \quad \text{（恒等式，全链路 Decimal 6 位 ROUND\_DOWN）}$$

$$B_{\text{eff}} = \text{Free} + \text{Active} \quad \text{（sizing 母数）}$$

$$\text{NAV} = \sum_i \left(N_i \cdot 0.90 \right) \quad \text{（僵尸双轨估值，sizing 母数 0.0x）}$$

- 12h 触发僵尸判定；结算按 NWS WRH 复刻；舍入闭环（ADR-0012）。

---

## 12. 参数挂锁汇总

| 参数 | 状态 | 解锁路径 |
| :--- | :--- | :--- |
| $\theta, \eta, \delta_\mu, \delta_\sigma$ | `[F-2 LOCKED]` | 概率层 GREEN + 两步标定 Step 1（纸面盘自产数据） |
| $m_{\text{dutch}}$ | `[待标定]`（不继承） | 宪法推导 / 两步标定复核 |
| $\text{min\_edge}$（Noise Floor） | `[待标定]` | 同上 |
| $\text{base}, \beta$ | `[待核实]` | M-2 对外核实一次后闭环 |
| 10%/70%/7min/0.2x/12h/R_z | 宪法级 | 不标定（ADR 来源） |
| fractional_multiplier | 配置默认（0.5） | F-2 解锁后 Step 1 复核 |

---

*本文件全部公式为结构定义；`[F-2 LOCKED]` / `[待标定]` / `[待核实]` 项在解锁/核实前不填实值。最终版须经用户确认。*
