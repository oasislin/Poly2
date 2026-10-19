# P7-ALGO-2 算法描述文档（数学公式完备版，v0.6）

> **文档编号**：P7-ALGO-2-MATH  
> **版本**：v0.6（**已对齐市场特性契约 v1.0 + 外部审计修正与 τ_2D 阶梯补注 + 2026-10-19 套利轨废除修剪与 P0-2 严谨性注记**；待用户最终确认）  
> **配套**：《P7-ALGO-2 规格书》v0.6（本文件为其数学章节的完备展开）  
> **状态**：全部公式为结构定义；第二层涉及标定/sizing 的参数维持 `[F-2 LOCKED]` / `[待标定]`，不填实值；官方定案项（base=0.05、FAK、Data API v2、pUSD）与外部审计修正项已完成回填；套利三轨已废除，S6 降级为只读错价监控  
> **依据**：判决书 M-1~M-8、ADR-0011~0015/0018、Polymarket 市场特性契约 v1.0、外部专家审计报告（2026-10-14）、主导方审核意见 v1.0、DR-2026-1014-01~04、DR-2026-1019-01 裁决记录

---

## 1. 记号与输入

| 记号 | 含义 | 来源 |
| :--- | :--- | :--- |
| $K$ | 档位数（互斥完备市场，依站点温标划分为 11 档 2°F 或 1°C 离散区间） | 方案 v2.8 / DR-2026-1014-04 |
| $\hat p_i$ | 第 $i$ 档概率（EMOS 概率层输出，截断后，$\sum \hat p_i = 1$） | 概率层（F-2 管辖） |
| $q_i$ | 第 $i$ 档盘口 ask 价 | CLOB 盘口 |
| $q_{\text{eff}, i}$ | 第 $i$ 档含费率有效买入成本 | §2 |
| $N_i$ | 第 $i$ 档既有持仓（payout 沉没成本，只买不卖下为外生常数） | 四桶账务 |
| $W_{\text{free}}$ | 可自由资金（Free pUSD，backed by USDC） | 四桶账务 |
| $B_{\text{eff}}$ | 有效资金 $= \text{Free} + \text{Active}$（sizing 母数，Zombie/Disputed 以 0.0x 剔除） | ADR-0012 |
| $f_i$ | 第 $i$ 档拟投入金额（决策变量，$f_i \ge 0$） | 本规格 |
| $\text{base}$ | Polymarket 天气市场动态 Taker 费率系数（**0.05**） | 市场契约 v1.0（✅ 官方定案） |
| $\text{min\_edge}$ | 最小 Edge 门槛（结构保留，数值 `[待标定]`） | §2 |
| $\theta, \eta$ | 不确定集宽度参数 | M-1（`[F-2 LOCKED]`） |
| $\delta_\mu, \delta_\sigma$ | EMOS 参数（μ, σ）的不确定性尺度 | M-1（`[F-2 LOCKED]`） |
| $m_{\text{dutch}}$ | 套利安全边际 —— **[DEPRECATED]**（三轨废除） | DR-2026-1019-01 |
| $m_{\text{rehedge}}$ | 追单对冲允许贴水亏损上限 `max_rehedge_loss`（建议初值 2%） | P1-4（`[待标定]`） |
| $z_{\text{crit}}, z_{\text{cert}}$ | 无量纲标准化残差风控门限（参考基线 2.0 / 0.3） | DR-2026-1014-04（`[待标定]`） |
| $\text{eps}$ | 破产防御常数（$10^{-7}$，浮点层严格下界） | P0-3（✅ 架构参数） |

---

## 2. 定价：VWAP 深度穿透与动态费率

### 2.1 VWAP 深度穿透（S1，DR-2026-1014-01）

按 `min_edge` 达标穿透深度自动确定定价探针规模 $S_{\text{target}}$，根除"鸡生蛋"死锁：

$$S_{\text{target}} := \sum_{j: \text{edge}_j \ge \text{min\_edge}} s_j = \text{safe\_capacity\_at\_min\_edge}$$

$$S = \sum_{j} s_j \quad \text{（累计至 } \min(S_{\text{target}}, \text{盘口总深度})\text{）}$$

$$\bar P = \frac{\sum_j p_j \cdot s_j}{\sum_j s_j} \quad \text{（达标深度纯盘口加权均价）}$$

- 定价加权均价 $\bar P$ 在达标深度内具有保守单调性，实际任意规模成交均价必定 $\le \bar P$；
- 穿透逻辑与 S4 执行路由的 $\text{safe\_capacity}$ 共享算法核心，杜绝两处口径漂移。

### 2.2 动态费率折算（M-2 已裁；市场特性契约 v1.0 回填）

**时序铁律：先穿透得纯盘口均价 $\bar P$，再统一施加费率，严禁逐层非线性迭代。**

$$q_{\text{eff}} = \bar P \cdot \left[1 + 0.05 \cdot (1 - \bar P)\right]$$

- 官方公式依据：$fee = C \times 0.05 \times \bar P(1 - \bar P)$，每份名义溢价率 $\text{fee\_rate} = 0.05(1 - \bar P)$；有效买入成本 $q_{\text{eff}} = \bar P(1 + \text{fee\_rate})$；
- 边缘情形：$\bar P \to 0$ 时绝对费用小但费率摩擦高，EV 判定保留 edge 的费率敏感性（极端价位不抹费率，坚持最坏情况防御）；
- 参数状态：$\text{base} = 0.05$ 已闭环（✅ 官方定案回填）；Maker 暂不建模（用户裁决挂起）。

### 2.3 EV 与 Edge（S1 交易信号）

$$\text{net\_ev}_i = \hat p_i - q_{\text{eff}, i}$$

$$\text{edge}_i = \frac{\text{net\_ev}_i}{q_{\text{eff}, i}} = \frac{\hat p_i - q_{\text{eff}, i}}{q_{\text{eff}, i}}$$

**可交易判定**：$\text{tradable}_i = \big(\text{edge}_i \ge \text{min\_edge}\big) \wedge \big(\text{治理旗放行}\big)$

- 治理（用户裁决 A）：带旗资产 $\text{tradable}_i = \text{False}$（只观测、不交易，直至拔旗）；FAILSAFE 只读；
- $\text{min\_edge}$：结构保留（覆盖 Noise Floor 语义：v1 已归档不继承，数值 `[待标定]`）。

---

## 3. 凯利目标函数（多项增量对冲与预算前置）

### 3.1 结局财富与 W_free 基底设计意图（P2-3 批注）

第 $i$ 档胜出时的结局财富（买入 $f_i / q_{\text{eff}, i}$ 股，总投入 $\sum_j f_j$，既有持仓 $N_i$ 为沉没成本）：

$$W_i(f) = W_{\text{free}} + N_i + \frac{f_i}{q_{\text{eff}, i}} - \sum_{j=1}^{K} f_j$$

> **架构批注（W_free 基底的刻意设计）**：
> 结局财富基底明确采用当前自由流动资金 $W_{\text{free}}$（而非有效总资产 $B_{\text{eff}}$）。这是审慎风控的刻意**内生动态降杠杆机制**：当已有较多持仓被占用锁定（$W_{\text{free}}$ 降低）时，对数效用函数自然对每一笔新风险暴露施加更严苛的边际惩罚，迫使优化器自动收缩后续开仓规模，坚决防范资金链断裂。

### 3.2 预算上限与风控调制前置化（DR-2026-1014-02 / DR-2026-1014-03）

风控调制系数（$\tau_z$ 僵尸率调制、$\tau_{\text{2D}}$ 阶梯温差调制）前置并入预算上限公式：

$$C_{\max} := \tau_z \cdot \tau_{\text{2D}} \cdot \min\left(0.10 \cdot B_{\text{eff}},\; 0.70 \cdot B_{\text{eff}} - \text{Active\_locked},\; W_{\text{free}}\right)$$

- **前置优势**：SLSQP 在压缩后的预算内全局优化，自动集中资金于最优势档位，彻底规避后置乘法导致的零碎小单团灭；
- **分母统一（DR-2026-1014-03）**：全局 70% 约束统一以有效资金母数 $B_{\text{eff}}$ 为分母，Zombie / Disputed 分子分母坚决全剔除。

---

## 4. 稳健化：不确定集构造（M-1 改造；Debate Q1 冻结）

### 4.1 双源区间宽度（Delta Method + η 尾部膨胀，取 max）

$$\text{SE}_i = \max\left(\text{SE}_{\text{EMOS}, i},\; \eta\sqrt{\hat p_i(1 - \hat p_i)}\right)$$

$$\text{SE}_{\text{EMOS}, i} = \left|\frac{\partial p_i}{\partial \mu}\right| \delta_\mu + \left|\frac{\partial p_i}{\partial \sigma}\right| \delta_\sigma$$

**高斯族闭式灵敏度**（双参数 CDF，$z_a = (a_i-\mu)/\sigma$，$z_b = (b_i-\mu)/\sigma$）：

$$\frac{\partial p_i}{\partial \mu} = \frac{\varphi(z_a) - \varphi(z_b)}{\sigma}, \qquad \frac{\partial p_i}{\partial \sigma} = \frac{z_a\,\varphi(z_a) - z_b\,\varphi(z_b)}{\sigma}$$

> **口径批注（L1 盒式最坏相关上界，P2-2）**：
> 此处绝对值之和（L1 范数）构成关于 $(\mu, \sigma)$ 扰动的最坏相关上界（Worst-case correlation upper bound），比独立假设下的 L2 范数放大至多 $\sqrt{2}$ 倍，旨在审慎抵御气象预测均值与方差耦合偏差的最坏情况冲击。

### 4.2 区间与冻结

$$p_{L,i} = \max\left(0,\; \hat p_i - \theta \cdot \text{SE}_i\right), \qquad p_{U,i} = \min\left(1,\; \hat p_i + \theta \cdot \text{SE}_i\right)$$

- $\text{SE}_i, p_{L,i}, p_{U,i}$ 在决策快照内固定，不进 SLSQP 迭代重算；参数维持 `[F-2 LOCKED]`。

---

## 5. 稳健 Minimax：LP 强对偶单层展开（P0-2 外部审计修正）

### 5.1 内层最坏概率极小化的对偶化推导

内层极小化问题为：

$$\min_{p \in \mathcal{P}} \; \sum_{i=1}^{K} p_i \ln W_i(f) \quad \text{s.t.} \quad \sum_{i=1}^K p_i = 1, \quad p_i \ge p_{L,i}, \quad -p_i \ge -p_{U,i}$$

引入对偶变量：
- $\lambda \in \mathbb{R}$ 对应等式约束 $\sum p_i = 1$；
- $\alpha_i \ge 0$ 对应下界约束 $p_i \ge p_{L,i}$；
- $\beta_i \ge 0$ 对应上界约束 $p_i \le p_{U,i}$。

拉格朗日函数：
$$L(p, \lambda, \alpha, \beta) = \lambda + \sum_{i=1}^K \alpha_i p_{L,i} - \sum_{i=1}^K \beta_i p_{U,i} + \sum_{i=1}^K p_i \big(\ln W_i(f) - \lambda - \alpha_i + \beta_i\big)$$

对 $p$ 求极小，有限值的充要条件为对偶约束 $\ln W_i(f) - \lambda - \alpha_i + \beta_i \ge 0$。根据线性规划强对偶定理，内层原问题与对偶问题极值严格相等、对偶间隙恒为 0：

$$\min_{p \in \mathcal{P}} \sum_{i=1}^K p_i \ln W_i(f) = \max_{\substack{\lambda \in \mathbb{R}, \\ \alpha \ge 0, \beta \ge 0 \\ \lambda + \alpha_i - \beta_i \le \ln W_i(f)}} \left( \lambda + \sum_{i=1}^K \alpha_i p_{L,i} - \sum_{i=1}^K \beta_i p_{U,i} \right)$$

### 5.2 单层连续可微规划问题定义（3K + 1 维变量）

将内外层两个 $\max$ 合并，消灭所有极点折角，形成单层规划：

$$\max_{f, \lambda, \alpha, \beta} \; H(f, \lambda, \alpha, \beta) := \lambda + \sum_{i=1}^K \alpha_i p_{L,i} - \sum_{i=1}^K \beta_i p_{U,i}$$

**约束条件**：
1. **耦合约束（$K$ 个）**：$g_i(f, \lambda, \alpha, \beta) := \ln W_i(f) - \lambda - \alpha_i + \beta_i \ge 0 \quad (\forall i \in \{1,\dots,K\})$
2. **预算上限约束（1 个）**：$C_{\max} - \sum_{j=1}^K f_j \ge 0$
3. **破产硬约束（$K$ 个）**：$W_i(f) - \text{eps} \ge 0 \quad (\forall i \in \{1,\dots,K\})$
4. **决策变量盒约束**：$0 \le f_i \le C_{\max}, \quad \alpha_i \ge 0, \quad \beta_i \ge 0, \quad \lambda \in \mathbb{R}$

### 5.3 闭式解析 Jacobian 偏导数

为确保 SLSQP 求解器达到极致数值稳定性，提供精确闭式 Jacobian：
- 目标函数关于变量 $(f, \lambda, \alpha, \beta)$ 的梯度：
  $$\nabla_f H = \mathbf{0}_K, \quad \nabla_\lambda H = 1, \quad \nabla_\alpha H = p_L, \quad \nabla_\beta H = -p_U$$
- 耦合约束 $g_i$ 关于变量的梯度：
  $$\frac{\partial g_i}{\partial f_j} = \frac{1}{W_i(f)} \cdot \left(\frac{\delta_{ij}}{q_{\text{eff},i}} - 1\right), \quad \frac{\partial g_i}{\partial \lambda} = -1, \quad \frac{\partial g_i}{\partial \alpha_j} = -\delta_{ij}, \quad \frac{\partial g_i}{\partial \beta_j} = \delta_{ij}$$

---

## 6. 凹性与收敛性证明（引理 1~3，P0-2 改写）

**引理 1（LP 强对偶等价性）**：对于任意满足 $p_L \le p_U$ 且可行域非空的快照不确定集 $\mathcal{P}$，内层最坏概率极小化问题强对偶成立，原 Minimax 问题与单层对偶问题解集与极值完全等价。

**引理 2（目标与可行域凸性）**：单层规划目标函数 $H$ 为线性函数（无限光滑 $C^\infty$）；耦合函数 $g_i$ 是仿射函数与对数函数的复合，为凹函数（一般情形非严格凹：存在线性方向时凹性退化）；其水平集 $\{ (f,\lambda,\alpha,\beta) \mid g_i \ge 0 \}$ 是闭凸集；预算与破产约束均为线性半空间，交集为闭凸集。

**引理 3（全局收敛与假死根除）**：线性目标在闭凸集上的极值问题不存在任何非光滑折角或局部伪极值；SLSQP 在给定解析 Jacobian 下保证收敛至 KKT 点，即全局最优解，彻底消除了 argsort 导致的 line search status=8 假死。**注**：凹性保证全局最优，但线性目标的最优解集可能非唯一（凸面）；数值 SLSQP 不保证 100% 收敛——**G7 Fail-Closed 兜底保留为第二道物理防线**（对偶化负责常态收敛率，Fail-Closed 负责退化兜底，二者互补）。

---

## 7. 风控门禁不等式（S3，全部下沉为纯布尔判定）

| # | 门禁 | 不等式 / 判定 | 来源 |
| :--- | :--- | :--- | :--- |
| G1 | 单市场硬顶 | $\sum_i f_i \le 0.10 \cdot B_{\text{eff}}$ | ADR-0012 |
| G2 | 全局利用率 | $\big(\text{Active\_locked} + \sum_i f_i\big) \big/ B_{\text{eff}} \le 0.70$（分母统一 $B_{\text{eff}}$） | DR-2026-1014-03 |
| G3 | 僵尸熔断放行 | $\tau_z > 0$（当 $R_z > 30\%$ 时 $\tau_z = 0$ 触发阻断） | DR-2026-1014-02 |
| G4 | 两维残差风控 | $z = \frac{|T_{\text{obs}} - \hat\mu|}{\hat\sigma}$；$\tau_{\text{2D}} \in \{1.0, 0.20, 0\}$（阶梯映射见 §7.1）；门禁布尔放行条件为 $\tau_{\text{2D}} > 0$ 且方向合规 | DR-2026-1014-04 |
| G5 | 带旗治理 | $\text{governance\_flag is None}$（带旗只观测禁投） | 方案 A |
| G6 | 预购与元数据 | $\Delta_{\text{age}} \le 7\text{min} \wedge \text{数据连通} \wedge \text{网关连通} \wedge \text{元数据完备} \wedge \text{ACTIVE} \wedge \text{阀开}$ | ADR-0014 |
| G7 | 求解器收敛 | $\text{solver\_success} \wedge \neg\text{NaN} \wedge \forall i: W_i(f) \ge \text{eps}$ 全部成立才放行 | 约束 2 |

**联合总放行判定**：$\text{ALL\_SYSTEMS\_PASS} = \text{G6} \wedge \text{G5} \wedge \text{G7} \wedge \text{G1} \wedge \text{G2} \wedge \text{G3} \wedge \text{G4}$。

### 7.1 $\tau_{\text{2D}}$ 阶梯映射规则（结构式，数值挂锁）

风控调制系数 $\tau_{\text{2D}}$ 前置并入 S2 联合凯利预算上限公式 $C_{\max}$，具体映射规则如下：

| 档位 | 触发条件（结构） | $\tau_{\text{2D}}$ 取值 | 业务与风控语义 |
| :--- | :--- | :---: | :--- |
| **正常档** | 非以下各档 | **1.0** | 全额预算分配（前置并入 $C_{\max}$） |
| **CRITICAL 缩放档** | $z_{\text{cert}} < z \le z_{\text{crit\_scale}} \wedge t_{\text{rem}} \le 60\text{m}$ | **0.20** | 承接原 ADR-0011 "临盘 1h 且温差大" 的 0.20x 预算折剪，防范模型尾部失真 |
| **CERTAIN 方向限制** | $z \le z_{\text{cert}}$（预测高度确定） | 正向 **1.0** / 反向 **0** | 承接原 "CERTAIN 禁反向投机"：与预测温差同向档位正常放行，逆向反开档位一票否决 |
| **极端阻断档** | $z > z_{\text{crit\_scale}} \wedge t_{\text{rem}} \le 15\text{m}$ | **0** | 临近关盘且严重偏离预测，全额阻断（$C_{\max}=0$），触发 G4 布尔拦截 |

> **换算对照基线与挂锁说明**：
> - 阈值 $z_{\text{cert}}$（参考基线 0.3）、$z_{\text{crit\_scale}}$（参考基线 2.0）均标注为 **`[待标定]`**，F-2 绿灯后经两步标定定稿，严禁填入虚假实值；
> - 原 ADR-0011 华氏度绝对阈值（$0.5^\circ\text{F} / 3.0^\circ\text{F}$）保留为**换算对照基线**（当典型台站 $\sigma \approx 1.5^\circ\text{F}$ 时，$z = 0.5 / 1.5 \approx 0.33$，$z = 3.0 / 1.5 = 2.0$），仅作审计追溯对照，运行时严格以无量纲 $z$ 为准；
> - **CERTAIN 口径演进说明**：原 v0.3 CERTAIN 判定需 $t_{\text{rem}} < 0.5\text{h} \wedge \Delta T \le 0.5^\circ\text{F}$ 双条件；新口径统一以无量纲标准化残差 $z \le z_{\text{cert}}$ 判定（时间条件已吸收进 $z$ 判定，当预测高度确定时全时段严禁逆势投机，禁反向适用范围扩大至全时段，属更保守的防御方向，避免误读为 bug）；
> - **结构不变更**：$\tau_{\text{2D}}$ 前置并入 $C_{\max}$ 与 S3 门禁纯布尔判定保持不变：只要 $\tau_{\text{2D}} > 0$（含 0.20 档与 CERTAIN 正向档）即为布尔放行；极端阻断档或 CERTAIN 逆向档则判定为阻断。

---

## 8. 执行定价与离散量化管道（S4：保护价 + FAK）

### 8.1 保护价计算与含费量化时序（P0-3 修正）

遍历 ask 档 $j$（价格升序），锁定最后一个满足 Edge 阈值的档位：

$$P_{\text{protect}, i} = \text{最后一个满足 } \text{edge}_j \ge \text{min\_edge} \text{ 的 ask 价}, \qquad \text{safe\_capacity}_i = \sum_{\text{达标档}} s_j$$

**从连续资金到离散订单的执行管道时序（顺序严格锁定）**：
1. 资金精度收口：$f_{\text{dec}} = \text{quantize}(f_i^*, \text{Decimal}("0.000001"), \text{ROUND\_DOWN})$；
2. 保护价穿透：计算 $P_{\text{protect}}$ 与 $\text{safe\_capacity}$；
3. 价格量化：$P_{\text{limit}} = \text{quantize\_to\_tick}(P_{\text{protect}}, \text{tick\_size}, \text{ROUND\_DOWN})$；
4. **含费折算原始份额与深度截断（P0-3）**：
   $$S_{\text{raw}} = \min\left( \frac{f_{\text{dec}}}{q_{\text{eff}}(P_{\text{limit}})},\; \text{safe\_capacity} \right)$$
   $$S_{\text{order}} = \text{quantize\_to\_lot}(S_{\text{raw}}, \text{lot\_size}, \text{ROUND\_DOWN})$$
5. 最小订单门禁：若 $S_{\text{order}} < \text{minimum\_order\_size}$，标记 `SKIPPED_BELOW_MINIMUM_ORDER_SIZE` 并退出；
6. **含费足额预冻结资金（P0-3）**：$\text{lock\_funds}(S_{\text{order}} \times q_{\text{eff}}(P_{\text{limit}}))$；
7. 订单类型：统一使用 **FAK 限价单**（Fill-and-Kill），**严禁市价单**。

### 8.2 残差愈合与追单贴水上限（P1-4）

- 30s 内限价补单重对冲；允许最大追单贴水亏损 $\text{rehedge\_loss} \le m_{\text{rehedge}} = 0.02$（`[待标定]`）；
- 超时或亏损击穿阈值 $\Rightarrow$ 触发 `STOP_LOSS_TRIGGERED` / `LIQUIDATED` 紧急止损。

---

## 9. 套利轨废除与只读错价监控（S6：观测面，2026-10-19 定论）

### 9.1 三轨废除（公理 + 机制 + 实证三重依据）

- **轨 A（全包 YES）— 公理性不可能**：互斥穷尽市场结算公理 Σp=1；盘口总和被套利均衡钉在 ≥1+摩擦（开普敦实测 ΣAsk(YES)=1.0170>1），含 0.05 费率后更 >1，恒不满足 `Σq_eff(Ask(YES_i)) ≤ 1−m_dutch`；
- **轨 B（全包 NO）— 镜像冗余**：每档互补协议锁定（split/merge 固定 $1/对，1 YES+1 NO≡1 pUSD）下 ΣAsk(YES)+ΣAsk(NO)≡K，"ΣNO≤K−1−m" ⟺ "ΣYES≥1+m"，与轨 A 为同一约束的代数镜像，不增加独立信息；
- **轨 C（单档配对）— 机制性恒等**：YES+NO≡1 自铸造（split）即成立，Ask(YES_i)+Ask(NO_i)≥1+spread；<1 窗口被套利机器人 split+merge 秒级闭合。

**判定**：三轨全部废除（死代码有害：永不触发的判定逻辑只承担误触发 bug 风险，轨 B 错误不等式即实盘教训）。原"套利前置 S6 最高优先级"（Q2 裁决）作废，见 DR-2026-1019-01。

### 9.2 S6 只读错价监控（保留，零发射）

- **观测对象**：① 单档互补偏离 `Ask(YES_i)+Ask(NO_i) − 1`；② 跨档总和偏离 `ΣAsk(YES_i) − 1`；
- **频率**：低频轮询（60s）或行情事件驱动；
- **输出**：偏离度时序 + 超阈值告警日志（仅人工/审计消费）；
- **硬约束**：不触发任何下单、不产生仓位、不进入交易管线（零发射定理）；
- **用途**：市场健康度信号（流动性断裂/撮合异常度量），并入风控观测 M 层。

---

## 10. 概率层门禁：ECE 梯级判定

$$\text{F-2 绿灯} = \begin{cases}
\text{GREEN（完全解锁标定）} & \text{Binding ECE} \le 0.05 \wedge \text{交易窗口 ECE} \le 0.0100 \\
\text{YELLOW（带旗，按方案 A 禁投只观测）} & \text{Binding ECE} \le 0.05 \wedge \text{交易窗口 ECE} > 0.0100 \\
\text{RED（全线熔断）} & \text{Binding ECE} > 0.05
\end{cases}$$

---

## 11. 结算与账务（S5/S7：四桶恒等与双轨估值）

$$\text{Total} = \text{Free} + \text{Active} + \text{Zombie} + \text{Disputed} \quad \text{（全链路 pUSD 6 位 Decimal ROUND\_DOWN）}$$

$$B_{\text{eff}} = \text{Free} + \text{Active} \quad \text{（sizing 母数，Zombie/Disputed 0.0x 剔除）}$$

- 12h 触发僵尸判定；结算复刻器严格按 NWS WRH 整度结合 Decimal `ROUND_HALF_UP` 算术舍入闭环（ADR-0012）；
- 距离名义关盘剩余小时 $t_{\text{remain}}$ 严格锚定台站当地时区 23:59:59（依 `station_tz` 解析）。

---

## 12. 参数挂锁与运行端点映射汇总

| 参数 / 接口 | 当前值 / 状态 | 来源 / 解锁依据 |
| :--- | :---: | :--- |
| base（Weather Taker 费率系数） | **0.05** | ✅ 官方定案（市场契约 v1.0 回填；docs.polymarket.com/trading/fees） |
| Maker 返佣 | 暂不建模 | ✅ 用户裁决（暂不做 maker，挂起备查 25%） |
| 历史数据 API | **Data API v2** | ✅ 官方定案（端点 `data-api.polymarket.com/v2`，token_id + cursor 分页） |
| 官方 SDK 基础 | **py-sdk（polymarket-client）** | ✅ 官方定案（替代废弃 py-clob-client） |
| eps（破产防御常数） | **1e-7** | ✅ 架构参数（浮点层严格下界） |
| $\theta, \eta, \delta_\mu, \delta_\sigma$ | `[F-2 LOCKED]` | 概率层 GREEN + 两步标定 Step 1（纸面盘自产数据） |
| $m_{\text{dutch}}$（套利安全边际） | **[DEPRECATED]**（三轨废除，2026-10-19） | DR-2026-1019-01 |
| $m_{\text{rehedge}}$（残差追单贴水上限） | 建议初值 0.02 | 仅 S4 凯利执行部分成交/单档失败场景（非套利），P1-4（`[待标定]`） |
| $z_{\text{crit}}, z_{\text{cert}}$（残差门限） | 参考基线 2.0 / 0.3 | DR-2026-1014-04（`[待标定]`） |
| $\text{min\_edge}$（Noise Floor） | `[待标定]` | 结构保留，数值走标定或宪法推导 |
| 10%/70%/7min/15m/35m/12h/R_z | 宪法级 | 架构硬规则，不标定（ADR-0011~0014） |
| fractional_multiplier | 配置默认（0.5） | F-2 解锁后 Step 1 复核 |

---

*本文档为 v0.6 对齐稿；第二层 `[F-2 LOCKED]` / `[待标定]` 项在解锁前绝不填入虚假实值。最终版须经用户确认。*

