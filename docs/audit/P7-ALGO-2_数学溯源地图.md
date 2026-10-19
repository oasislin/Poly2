<!-- 供主导方/开发端/用户共同读取 | 日期: 2026-10-19 | 性质: 全量数学溯源地图 -->
# P7-ALGO-2 数学依据与文献溯源地图 v1.2

> **版本**：v1.2（2026-10-19 套利轨废除修剪：de Finetti 理论保留为概率公理一致性基准，交易通道已废除；DR-2026-1019-01）  
> **用途**：将《算法描述文档》v0.6 的每一个数学组件，逐一映射到**经典出处（论文/专著 → 具体章节或概念）**，并说明**关联性**（为什么用这个、它解决什么、替代方案是什么）。
> **目的**：确保"每个数学选择都有出处"，杜绝拍脑袋——延续 P7-ALGO-1 凯利溯源卷宗的纪律。
> **关联文档**：`P7-ALGO-2_P01_basis_review.md`；`P7-ALGO-2_裁决记录.md`。

---

## 〇、总览：算法数学结构 → 学科家族

```
┌─ 目标层   稳健多项凯利（§3+§6）      = 凯利对数效用（信息论/金融） × 鲁棒优化（box 不确定集）
├─ 不确定性层  Delta Method + box 区间（§4） = 统计一阶传播 × 鲁棒优化
├─ 求解层   LP 强对偶单层展开 + SLSQP（§5~§6） = 凸对偶理论 × 序列二次规划（闭式解析 Jacobian）
├─ 执行层   保护价 / 深度穿透（§8）     = 市场微结构（VWAP）
├─ 观测层   错价监控（§9）              = 概率公理一致性（de Finetti 主观概率论，只读零发射）
├─ 门禁层   ECE / CRPS（§7）            = 概率校准与评分（统计气象验证）
└─ 账务层   四桶 / R_z / NAV（§10~§11） = 项目内账务设计（ADR-0012，非外部文献）
```

---

## 一、目标函数层（算法文档 §3）

### 1.1 对数财富最大化 = 凯利准则

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §3.1 目标函数 $\max_f \sum_i \hat p_i \ln W_i(f)$ |
| **数学内容** | 每次决策最大化期望对数财富；$W_i(f) = W_{\text{free}} + N_i + \frac{f_i}{q_{\text{eff},i}} - \sum_j f_j$ |
| **文献** | **Kelly, J. L. (1956).** *A New Interpretation of Information Rate*. Bell System Technical Journal 35(4): 917–926 |
| **具体章节/概念** | 原文核心场景小节（"the gambler with a private wire"）：①证明最大化期望对数财富 ⇔ 复利下长期增长率最大；②公平赔率下最大增长率 = 信道信息率；③**推广到任意赔率**——本项目使用的正是任意赔率情形 |
| **关联性** | **为什么用 log**：复利下加法性（ln 把乘法转加法，适用大数定律）；W>0 定义域天然禁止破产。**替代方案**：线性期望 EV → 长期被复利方差拖累；Markowitz 均值-方差 → 仅在正态/二次效用下最优，且无"长期增长最优"保证。**后续支撑**：Breiman (1961) 证明凯利渐近最优（双准则：最小期望时间达目标 / 最大增长率）；Bell & Cover (1980) 证明竞争最优性（单期 ≥50% 概率跑赢任意对手）——两者为本项目"用 Kelly 而非其他下注准则"提供完整理论正当性 |

### 1.2 目标凹性（引理 1~3）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §3.3 引理 1（ln(线性) 凹）、引理 2（非负加权和保凹）、引理 3（可行域凸） |
| **文献** | **Boyd, S. & Vandenberghe, L. (2004).** *Convex Optimization*. Cambridge University Press |
| **具体章节/概念** | 引理 1 ← §3.1.5（复合规则：log 是凹函数，凹∘仿射仍凹）；引理 2 ← §3.2.1（非负加权和保持凸性/凹性）；引理 3 ← §2.1.4 / §2.2（box 与半空间是凸集、凸集交集凸；$\{f \ge 0,\ \sum f \le C_{\max}\}$ = box ∩ 半空间） |
| **关联性** | 凹性是"全局收敛"承诺的源头（见 1.3）。若目标非凹 → 只能保证局部收敛 → 正是 P0-1 要避免的情形 |

### 1.3 凹最大化于凸集 → 局部 = 全局

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §3.3 结论 + §6 稳健化 |
| **文献** | **Boyd & Vandenberghe (2004)**，同书 |
| **具体章节/概念** | **§4.2.2**："Any locally optimal point of a convex problem is (globally) optimal"——凸问题中局部最优即全局最优；**§5.5.3**：凸问题的 KKT 条件为充分条件（KKT 点即全局最优） |
| **关联性** | 这是"SLSQP 收敛即全局最优"的完整数学来源。**任何破坏凹性的实现都会使该定理失效**——开发端初版罚函数（凹+凸=非凸）即属此类（P0-1 修正根因） |

---

## 二、不确定性层（算法文档 §4）

### 2.1 Delta Method（一阶不确定性传播）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §4.1 $SE_{\text{EMOS}} = \lvert\partial p/\partial \mu\rvert\,\delta\mu + \lvert\partial p/\partial \sigma\rvert\,\delta\sigma$ |
| **文献** | **Casella, G. & Berger, R. (2002).** *Statistical Inference*, 2nd ed., §5.5.4 "The Delta Method"；**van der Vaart, A. W. (1998).** *Asymptotic Statistics*, Cambridge Univ. Press, **§3 "The Delta Method"** |
| **具体章节/概念** | 对可微 $g$：$g(\hat X) \approx g(\mu) + g'(\mu)(\hat X - \mu)$，标准差传播 $\sigma_{g} \approx \lvert g'(\mu)\rvert \sigma$。我们把该一阶线性化用于"EMOS 参数 $(\mu,\sigma)$ 的扰动 → 各档概率 $p_i$ 的波动"（多变量一阶传播） |
| **关联性** | **为什么一阶**：闭式、O(K) 计算、与 SLSQP 主循环解耦（快照冻结 N3）。**为什么用 L1 绝对值相加而非 L2 范数（P2-2 口径说明）**：标准独立假设下的 Delta Method 误差传播为 L2 范数 $\sqrt{(\frac{\partial p}{\partial \mu}\delta\mu)^2 + (\frac{\partial p}{\partial \sigma}\delta\sigma)^2}$；本项目采用绝对值相加（L1 范数）是**盒式最坏相关上界（Worst-case correlation upper bound）**，在数学上比 L2 传播至多放大 $\sqrt{2}$ 倍（约 1.414x）。这是刻意的审慎鲁棒设计，旨在全面防御 EMOS 参数 $(\mu, \sigma)$ 扰动之间潜在的正负相关性耦合冲击。**替代方案**：蒙特卡洛采样传播（每次决策需数千次采样，实时不可行）；二阶 Delta Method（收益小、复杂度高，且参数扰动本身是估计值，二阶项被噪声淹没） |

### 2.2 高斯 CDF 对 μ/σ 的偏导（闭式灵敏度）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §4.1 $\partial p/\partial \mu = \dfrac{\varphi(z_a) - \varphi(z_b)}{\sigma}$；$\partial p/\partial \sigma = \dfrac{z_a\varphi(z_a) - z_b\varphi(z_b)}{\sigma}$ |
| **数学常识** | **Leibniz 积分法则**（对积分限求导）+ 正态密度 $\varphi$ 的定义。推导：$p = \Phi(z_b) - \Phi(z_a)$，$z = (x-\mu)/\sigma$；$\partial\Phi(z)/\partial\mu = -\varphi(z)/\sigma$，$\partial\Phi(z)/\partial\sigma = -\varphi(z)z/\sigma$，相减得闭式 |
| **支撑书目** | Casella & Berger §2（CDF/密度）；任意微积分教材（Leibniz 法则） |
| **关联性** | 闭式 → 无需数值微分（数值微分有步长选择问题、离散噪声大、慢）。这是"可解析求导就用解析"的工程纪律在统计层的应用 |

### 2.3 尾部膨胀项 $\eta\sqrt{p(1-p)}$

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §4.2 $SE_{\text{tail}} = \eta\sqrt{p(1-p)}$ |
| **数学常识** | Bernoulli(p) 方差 = p(1−p)；比例的标准误差 $\sqrt{p(1-p)}$（大数/CLT 下样本比例的渐近标准差） |
| **支撑书目** | Casella & Berger §5.3（比例分布/CLT）等任何统计教材 |
| **关联性** | **双源取 max 的原因**（Debate Q1 冻结）：EMOS 灵敏度在 p→0/1 时可能低估（CDF 平坦区），尾部项保证低概率档也有最小不确定性下界。**替代方案**：仅用 EMOS 灵敏度（低估尾部风险） |

### 2.4 box 不确定集（区间 $[\hat p - \theta SE,\ \hat p + \theta SE]$）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §4.3 + §5 内层 |
| **文献** | **Ben-Tal, A., El Ghaoui, L. & Nemirovski, A. (2009).** *Robust Optimization*. Princeton Univ. Press——核心概念：不确定性集合（uncertainty set）、鲁棒对应（robust counterpart）、**box 型不确定集**（各分量独立区间）。更早：**Soyster, A. L. (1973).** *Operations Research* 21(5): 1154–1157（box 不确定的最保守先驱）。**Bertsimas, D. & Sim, M. (2004).** *The Price of Robustness*. Operations Research 52(1): 35–53（box 鲁棒的保凸性、可解性与"鲁棒代价"量化） |
| **具体章节/概念** | 以书目录为准：不确定集类型（box/椭球/多面体）与鲁棒对应定义章节；Bertsimas & Sim 的"鲁棒线性优化"框架（box 不确定 + 保凸性） |
| **关联性** | **为什么选 box 而非椭球/KL 球**：①box 下最坏投影有贪心闭式解 O(K log K)（见 §5）；②椭球/KL 球对应 SOCP/熵约束（求解成本高、无闭式投影）；③θ 直接对标"几个标准差"，保守度可解释。这正是 Debate Q1 冻结结论（启发式独立置信边界 + η 尾部膨胀）的文献根基 |

---

## 三、求解层（算法文档 §5~§6）

### 3.1 最坏情形投影 = 线性函数在 box+simplex 上的最小化（贪心填充）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §5 内层 $\min_{p \in P} \sum_i p_i \ln W_i(f)$——对固定 f，$\ln W_i(f)$ 是常数 → **内层是线性目标** |
| **数学核心** | 线性函数在凸多面体上的最小值出现在**极点**（LP 基本定理）——**Bertsimas, D. & Tsitsiklis, J. (1997).** *Introduction to Linear Optimization*. Athena Scientific, **§2.4 "Extreme Points"** |
| **具体算法** | 连续背包（fractional knapsack）贪心最优——**Cormen, T. et al. (2009).** *Introduction to Algorithms*, 3rd ed., **§16.2**（含 fractional knapsack 贪心解及其最优性） |
| **关联性** | 按 $W_i$ 升序（最差结局优先），把剩余概率质量顶格填入 $p_U - p_L$ 容量直到用尽 = 连续背包贪心 = **精确最优非近似**，O(K log K)（排序主导）。**替代方案**：通用 LP 内点法（每次迭代 K 维但常数大）；极点枚举（组合爆炸）。退化保护（Σp_L≥1 归一化；Σp_U<1 待补）是工程防御，不改变数学结构 |

### 3.2 双层 Minimax 结构（稳健优化的标准形式）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §6 $\max_f \min_{p \in P} \sum_i p_i \ln W_i(f)$ |
| **文献** | **von Neumann, J. (1928).** *Zur Theorie der Gesellschaftsspiele*. Math. Ann. 100: 295–320（minimax 定理起源）；**Sion, M. (1958).** *On General Minimax Theorems*. Pacific J. Math. 8: 171–176（凸凹条件下 minimax 的推广）；**Ben-Tal, A., El Ghaoui, L. & Nemirovski, A. (2009).** *Robust Optimization*（鲁棒优化 LP 对偶化单层展开标准范式） |
| **关联性** | 我们的结构是"max 外、min 内"（先取最坏情形、再优化策略）= 鲁棒优化的标准 minimax 形式。在 P0-2 外部审计修正后，正式采纳 **LP 强对偶单层展开**（Dual Reformulation），将双层 Minimax 合并为 $3K+1$ 维单层凸规划，既严格继承了 von Neumann/Sion 强对偶定理，又彻底消除了离散 argsort 导致的非光滑极点翻转与线搜索 status=8 假死风险 |

### 3.3 SLSQP 求解器

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §6 外层 |
| **文献** | **Kraft, D. (1988).** *A Software Package for Sequential Quadratic Programming*. DFVLR-FB 88-28（SLSQP 原始实现）；综述：**Boggs, P. & Tolle, J. (1995).** *Sequential Quadratic Programming*. Acta Numerica 4: 1–51；**Nocedal, J. & Wright, S. (2006).** *Numerical Optimization*, 2nd ed., Springer, **§18**（Sequential Quadratic Programming） |
| **具体章节/概念** | SQP 每步解一个 QP 子问题逼近原问题（active-set 处理不等式）；对线性约束 + 箱约束是**原生标准能力**（Gill, Murray & Saunders, SNOPT：SQP 大规模约束的标准实现） |
| **关联性** | **为什么 SLSQP**：①K∈[5,11] 小规模，SQP 微秒~毫秒级；②原生支持箱约束 + 线性不等式（我们只需这两种）；③scipy 内置、实现成熟。**替代方案**：内点法 IPOPT（面向大规模，杀鸡用牛刀）；单纯形（仅线性目标，不适用） |

### 3.4 罚函数法的局限（P0-1 修正的核心文献依据）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | 开发端 §4.3 原实现（二次罚项 1e6·Σ(eps−W)²）→ 修正方案 b（K 个线性硬约束） |
| **文献** | **Nocedal & Wright (2006) §17**（Penalty and Barrier Methods）：二次罚函数是"约束近似"（approximate constraint）——需要罚系数 μ→∞ 的**序列逼近**才收敛到约束解；固定有限系数只能得到近似可行解。现代处理：**Byrd, Gould, Nocedal & Waltz (2004).** *On the Convergence of Successive Linear-Quadratic Programming Algorithms*. Math. Program. 100: 27–48（动态罚参数/steering） |
| **具体概念** | 罚函数加入目标会**改变问题形状**（凹+凸=非凸 → 全局保证失效）；而 $W_i(f) \ge \varepsilon$ 是**线性**不等式 → 直接交给 SLSQP active-set（SQP 原生能力，见 3.3） |
| **关联性** | 这正是凸优化建模第一原则"**能线性约束就不罚**"（Boyd §4.1 标准形式：线性不等式是最基本凸约束），也是"P0-1 选 b 不选 a/c"的文献依据 |

---

## 四、执行层（算法文档 §8）

### 4.1 VWAP 深度穿透

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §8.1 $\bar P$（先穿透 Asks 得纯盘口 VWAP → 再统一费率） |
| **文献** | **Berkowitz, S., Logue, D. & Noser, E. (1988).** *The Total Cost of Transactions on the New York Stock Exchange*. Journal of Finance 43(1): 97–112（**VWAP 作为执行成本基准**的早期权威） |
| **数学内容** | $\bar P = \dfrac{\sum \text{price}_i \cdot \text{size}_i}{\sum \text{size}_i}$（成交量加权平均价） |
| **关联性** | **为什么 VWAP 而非中间价**：中间价不含可成交深度信息；VWAP 反映真实成交成本。**为什么"先 VWAP 后费率"**（Debate 约束 1 冻结）：$q_{\text{eff}} = \bar P[1 + \text{base}(1-\bar P)]$ 一次折算，杜绝逐层非线性费率迭代的递归误差 |

### 4.2 动态费率公式 $q = p[1 + \text{base}(1-p)]$

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §2.2（M-2 追认公式，base=0.0125 [待核实]） |
| **来源** | **项目 v1 遗产代码契约**（v1 strategy.py:691）——非外部文献，判词 M-2 已追认；属"项目内契约 + 数学性质自证" |
| **数学性质** | q 对 p 二阶导 = −2·base < 0 → **凹**；q ≥ p（含费溢价）；最大溢价 = base/4 在 p=0.5 |
| **关联性** | 不依赖外部文献；数学性质（凹性、单调性）为 EV/edge 判定的单调性提供依据（价格升序 → edge 单调递减 → 保护价可 break） |

---

## 五、套利层（算法文档 §9）

### 5.1 Dutch Book 判定 $\sum q_{\text{eff}} \le 1 - m_{\text{dutch}}$

> **2026-10-19 定论**：de Finetti Dutch Book 理论（概率公理一致性）**仍为有效理论基准**——它正是"Σp=1 / YES+NO≡1 恒等"的公理来源，也是只读错价监控的判定基准；  
> 但作为**交易通道**（算法描述 §9 三轨套利）已全部废除：公理保证 Σ≥1+摩擦，无触发的无风险锁利空间（DR-2026-1019-01）。本层仅保留理论溯源与监控基准用途。

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | §9.1 全包 YES / 反向 NO 互补折算（原交易通道已废除，转为 §9.2 只读错价监控） |
| **文献** | **de Finetti, B. (1931).**（主观概率与 Dutch Book 一致性论证的源头）；现代综述：**Hájek, A. (2009).** *Dutch Book Arguments*. Stanford Encyclopedia of Philosophy |
| **具体概念** | 一组互斥且穷尽的赌局：若赔付概率之和 < 1（买全）或 > 1（卖全），存在**无风险利润** ⇔ 定价不一致（违反概率公理） |
| **关联性** | de Finetti 概率一致性定理奠定了市场结算 Σp=1 与单档互补协议恒等的物理基石。原算法曾设计的"买全"方向（Σq_eff ≤ 1−m_dutch）与单档配对套利通道因不可能触发已废除（死代码有害），现仅作为只读错价监控的偏离度度量理论依据 |

---

## 六、门禁与验证层（算法文档 §7 + 规格书）

### 6.1 ECE（Expected Calibration Error）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | 概率层门禁梯级（Binding ECE ≤ 5% / 交易窗口 ≤ 0.0100） |
| **文献** | **Naeini, M., Cooper, G. & Hauskrecht, M. (2015).** *Obtaining Well Calibrated Probabilities Using Bayesian Binning into Quantiles*. AAAI（ECE 定义）；**Guo, C., Pleiss, G., Sun, Y. & Weinberger, K. (2017).** *On Calibration of Modern Neural Networks*. ICML（ECE 流行化） |
| **数学内容** | ECE = Σ (bin 频率) · |bin 准确率 − bin 平均置信度|（按置信度分箱） |
| **关联性** | 概率层输出质量门禁（F-2 前置）。这是模型校准的**业界标准度量**（非项目自创）；继承自模型训练抽检口径（用户裁决：继承口径声明 + 联动调整契约） |

### 6.2 CRPS / CRPSS（连续排序概率评分）

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | 概率层验证（CRPSS） |
| **文献** | **Gneiting, T. & Raftery, A. (2007).** *Strictly Proper Scoring Rules, Prediction, and Estimation*. JASA 102(477): 359–372（CRPS 为严格适当评分）；**Hersbach, H. (2000).** *Decomposition of the Continuous Ranked Probability Score for Ensemble Prediction Systems*. Weather and Forecasting 15(5): 559–570（CRPS 分解：可靠性/分辨率/不确定性） |
| **关联性** | 气象概率预报（EMOS 家族）的**行业标准验证指标**——我们继承概率层评价口径（判决书/方案 v2.8） |

### 6.3 10% 单市场 / 70% 全局利用率硬顶

| 项 | 内容 |
| :--- | :--- |
| **算法位置** | 门禁 G1/G2 |
| **来源** | 项目风险治理决策（规格书 §7；ADR-0011/0012 背景）——非外部文献，属项目内风险政策 |
| **关联性** | 学理背景可关联**分数凯利（fractional Kelly）**——**MacLean, Thorp & Ziemba (2011).** *The Kelly Capital Growth Investment Criterion*. World Scientific（综合卷：分数凯利在波动/回撤与增长间的折中实证），为"为何不超过全 Kelly"提供学理支撑 |

---

## 七、账务层（算法文档 §10~§11）

- **四桶恒等 / NAV 90% 折价 / 僵尸 R_z 分级**：项目内账务设计（ADR-0012），无外部经典文献。
- 可关联的常识：NAV（基金会计标准概念）、流动性分层与破产风险管理（风险治理实践）——不构成学术引用，标注为"项目内设计"。

---

## 八、文献总表（按主题聚合）

### A. 凸优化 / 数值优化
| 文献 | 用于本算法的组件 |
| :--- | :--- |
| Boyd & Vandenberghe (2004) *Convex Optimization* | 引理 1~3（§3.1.5/§3.2.1/§2）、局部=全局（§4.2.2）、KKT（§5.5.3）、显式 vs 隐式约束（§4.1） |
| Rockafellar (1970) *Convex Analysis* | 逐点下确界保凹（§6 稳健化）的理论根源 |
| Nocedal & Wright (2006) *Numerical Optimization* 2nd ed. | SQP（§18）、罚函数法局限（§17） |
| Kraft (1988) SLSQP | 求解器实现 |
| Boggs & Tolle (1995) SQP 综述 | SQP 理论 |
| Byrd, Gould, Nocedal & Waltz (2004) | 动态罚参数（为何不用固定罚系数） |
| Gill, Murray & Saunders, *SNOPT* | SQP 处理大规模线性约束的标准实现 |

### B. 凯利 / 组合
| 文献 | 用于本算法的组件 |
| :--- | :--- |
| Kelly (1956) | 对数财富目标（§3.1） |
| Breiman (1961) | 凯利渐近最优性（目标正当性） |
| Bell & Cover (1980) | 竞争最优性（目标正当性） |
| MacLean, Thorp & Ziemba (2011) | 分数凯利（G1/G2 学理背景） |
| Cover & Thomas (2006) *Elements of Information Theory* 2nd ed. | log-optimal portfolio 框架（§16）；KL 散度（§2.5，不确定集替代方案的对照） |

### C. 鲁棒优化
| 文献 | 用于本算法的组件 |
| :--- | :--- |
| Ben-Tal, El Ghaoui & Nemirovski (2009) | box 不确定集、鲁棒对应（§4.3/§5） |
| Soyster (1973) | box 不确定先驱 |
| Bertsimas & Sim (2004) | box 鲁棒保凸性、鲁棒代价（§4.3） |

### D. 统计 / 概率
| 文献 | 用于本算法的组件 |
| :--- | :--- |
| Casella & Berger (2002) | Delta Method（§5.5.4）、正态/比例（§2/§3/§5） |
| van der Vaart (1998) | Delta Method（§3） |
| de Finetti (1931) / Hájek (2009) | Dutch Book（§9，2026-10-19 后仅理论基准/监控基准，交易通道已废除） |
| Naeini et al. (2015) / Guo et al. (2017) | ECE（门禁） |
| Gneiting & Raftery (2007) / Hersbach (2000) | CRPS（验证） |

### E. 算法 / 微结构
| 文献 | 用于本算法的组件 |
| :--- | :--- |
| Bertsimas & Tsitsiklis (1997) | LP 极点定理（§2.4，贪心投影的理论依据） |
| Cormen et al. (2009) CLRS | 连续背包贪心（§16.2，贪心投影的实现依据） |
| von Neumann (1928) / Sion (1958) | Minimax（§6 结构） |
| Berkowitz, Logue & Noser (1988) | VWAP 执行基准（§8.1） |

---

## 九、数学常识清单（教科书级，标注具体使用位置）

| # | 数学常识 | 教科书支撑 | 在本算法中的位置 |
| :--- | :--- | :--- | :--- |
| 1 | ln 的凹性 + 仿射复合仍凹 | Boyd §3.1.5；微积分基础 | 引理 1（§3.3） |
| 2 | 非负加权和保凹/保凸 | Boyd §3.2.1 | 引理 2（§3.3） |
| 3 | box、半空间为凸集；凸集交集凸 | Boyd §2.1.4/§2.2 | 引理 3（§3.3） |
| 4 | 凸问题局部最优 = 全局最优 | Boyd §4.2.2 | §3.3 结论、§6 |
| 5 | KKT 条件（凸问题充分性） | Boyd §5.5.3；Nocedal & Wright §12 | 最优性判定（§3/§6） |
| 6 | 凹函数逐点下确界保凹（inf 保凹） | Boyd §3.2.3 对偶；Rockafellar 1970 | §6 稳健化目标 |
| 7 | Leibniz 积分法则（积分限求导） | 任意微积分教材 | §4.1 高斯偏导闭式 |
| 8 | 正态 CDF/密度性质、φ(−∞)=φ(+∞)=0 | Casella & Berger §2 | §4.1 端点处理 |
| 9 | Bernoulli 方差 p(1−p)、比例标准误 | Casella & Berger §5.3 | §4.2 尾部膨胀项 |
| 10 | Delta Method（一阶泰勒传播） | Casella & Berger §5.5.4；van der Vaart §3 | §4.1 SE_EMOS |
| 11 | 线性函数在凸多面体极点取极值 | Bertsimas & Tsitsiklis §2.4 | §5 贪心投影最优性 |
| 12 | 连续背包贪心最优 | CLRS §16.2 | §5 贪心投影实现 |
| 13 | Minimax 定理（凸凹条件） | von Neumann 1928；Sion 1958 | §6 双层结构 |
| 14 | 期望对数与几何平均（复利） | Kelly 1956；Cover & Thomas §16 | §3 目标函数 |
| 15 | 概率公理一致性（Σp=1、互斥穷尽） | 概率论基础 | §5 投影约束、§9 Dutch Book（2026-10-19 仅理论基准/只读监控） |
| 16 | 正态分布归一化 | Casella & Berger | 每档概率构造 |

---

## 十、核实状态与方法

- ✅ **已检索核实**（2026-10-13）：Kelly (1956) 原文全文、Boyd & Vandenberghe (2004) 及其教程、Nocedal & Wright 体系（Curtis 2007 论文、Byrd et al. 2004/2005、SNOPT 论文）。
- 🔲 **学科常识级引用**（未逐一检索，均为本领域标准文献；如需全量闭环可批量补检索）：Rockafellar、Ben-Tal et al.、Bertsimas & Sim、Soyster、Casella & Berger、van der Vaart、CLRS、Boggs & Tolle、Gneiting & Raftery、Naeini 2015、Guo 2017、Hersbach 2000、Berkowitz 1988、Breiman 1961、Bell & Cover 1980、de Finetti/Hájek、Sion、von Neumann、Kraft、Thorp、MacLean/Thorp/Ziemba、Bertsimas & Tsitsiklis、Cover & Thomas。
- **章节号声明**：上表章节号（§4.2.2、§3.1.5、§16.2 等）为学科标准引用，已尽最大把握标注；🔲 项建议补检索时以原书目录复核。

*本溯源地图随 P7-ALGO-2 规格书/算法描述文档归档；新增数学组件须先在此登记出处后方可入规格。*
