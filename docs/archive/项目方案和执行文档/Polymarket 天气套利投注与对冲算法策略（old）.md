---
created: 2026-06-12 11:58:31
updated: 2026-06-13 19:19:40
title: Polymarket 天气套利投注与对冲算法策略
version: 2.1
---

# Polymarket 天气套利投注与对冲算法策略 (v2.1)

> **适用范围**: Polymarket 上所有开通的最高温/最低温盘口
> **策略代号**: Weather Edge Portfolio (WEP)
> **最新更新**: 针对 Polymarket 动态费率机制（Taker 成交费率与绝对费用的数学关系，Maker 免税/返佣）进行精确修正与重构。

---

## 目录

1. [策略目标与市场特征分析](#1-策略目标与市场特征分析)
2. [资金池设计与边界估算](#2-资金池设计与边界估算)
3. [核心数学框架与概率估计](#3-核心数学框架与概率估计)
4. [考虑 Polymarket 费率的期望与 Edge 模型](#4-考虑-polymarket-费率的期望与-edge-模型)
5. [投注量计算与阶梯边缘投注法](#5-投注量计算与阶梯边缘投注法)
6. [综合投注：必胜套利与风险对冲](#6-综合投注必胜套利与风险对冲)
7. [多次投注：动态仓位管理与风控墙](#7-多次投注动态仓位管理与风控墙)
8. [时间维度对冲与实况集成策略](#8-时间维度对冲与实况集成策略)
9. [附录：策略参数汇总表](#9-附录策略参数汇总表)

---

## 1. 策略目标与市场特征分析

### 1.1 策略目标
在 Polymarket 天气温度盘口上进行系统性概率套利：
- **物理概率与价格偏差（Edge）**：使用 ICON 40-member 集合预报模型计算的真实气象概率，与市场隐含概率进行对比，寻找定价偏差并下注。
- **分散投资**：覆盖全球 30+ 城市、最高/最低温盘口，通过跨市场分散化降低单一城市预报失准的特异性风险。
- **动态风控与对冲**：结合 Polymarket 互斥档位特性（Dutch Book）和气温日变化周期（DTC），进行时间维度和空间维度的风险对冲。

### 1.2 市场结构与交易成本特征
Polymarket 的交易机制和费率结构具有以下核心特征：

| 特征维度         | 规则与典型值                                                                     | 对策略的影响与应对                                                                                                                           |
| :----------- | :------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------- |
| **单市场档位数**   | 11 个互斥区间（YES 代币）                                                           | 结算时有且仅有一个 YES 为 $1.00，其余归零。可进行组合投注。                                                                                                 |
| **Maker 费率** | **0% 费率** + **20%~25% 返佣 (Rebate)**                                        | **最优执行通道**。在阶段 I 和 II 尽量以限价单（Limit Order）做 Maker 挂单，降低摩擦成本并获取额外收益。                                                                  |
| **Taker 费率** | **动态费率**，公式为：<br>$\text{FeeRate}_{taker} = \text{BaseRate} \times (1 - p)$ | **对便宜代币收取最高费率**。当买入资产单价 $p \to 0$ 时，从实际成交金额中收取的费率最高（接近 $\text{BaseRate}$）；当单价 $p \to 1$ 时，费率归零。期望计算（EV）和 Dutch Book 判定必须将此动态扣减纳入模型。 |
| **结算来源**     | Weather Underground (整数截断)                                                 | 严格遵循结算源的取整规则，避免因边界效应导致概率估计错误。                                                                                                       |
| **盘口更新频率**   | 分钟级                                                                        | 非高频套利，每 5-15 分钟轮询一次即可满足建仓与对冲需求。                                                                                                     |

---

## 2. 资金池设计与边界估算

本策略采用**三层资金隔离架构**：
- **总钱包 (Wallet)**：存放总 USDC 资产。
- **策略虚拟本金 (Allocated Capital, $C$)**：分配给天气套利策略的额度，初始设为 $C_0 = 10,000$ USDC。
- **明细配置**：
  1. **活跃部署资金 (Deployed Capital, 70%)**：用于常规天气套利的投注建仓（最高 $7,000$ USDC）。
  2. **对冲预备金 (Hedge Reserve, 20%)**：用于 Phase III 决战时刻的紧急实况对冲与 Dutch Book 锁利（$2,000$ USDC）。
  3. **保留缓冲金 (Reserve Buffer, 10%)**：流动性缓冲，应对大额结算延迟（$1,000$ USDC）。

### 资金池边界估算
- **安全下限 ($C_{min} = 4,000$ USDC)**：若低于此值，单城市单档位分配的最小筹码将受限，无法在 30+ 城市间进行有效分散，组合方差会显著增大。
- **流动性上限 ($C_{max} = 20,000$ USDC)**：Polymarket 天气盘口单档位日均 Bid 深度多在 $100 - $1,000 USDC 之间。本金超过 $20,000 USDC 将面临严重的滑点和无法完全成交的流动性瓶颈。

---

## 3. 核心数学框架与概率估计

### 3.1 集合预报蒙特卡洛法
系统使用 **ICON Seamless 40-member 集合预报**计算真实概率。
对于任一档位 $R_i$（温度区间为 $C_i$），真实概率的蒙特卡洛估计值为：

$$\hat{P}(R_i) = \frac{1}{M} \sum_{j=1}^{M} \mathbb{1}\left[T_j^{*} \in C_i\right]$$

其中：
- $M = 40$ （集合成员数）。
- $T_j^{*}$ 为第 $j$ 个集合成员预测的目标日期气温极值（最高温取 $\max$，最低温取 $\min$）。
- $\mathbb{1}[\cdot]$ 是示性函数。温度值须按结算源精度进行取整。

### 3.2 边界安全边际调整 (Boundary Safety Margin)
当预报温度集中分布在档位临界点附近时，微小的偏差会导致取整后概率产生剧烈跳跃。为此引入边界安全调整因子：

$$\hat{P}_{adj}(R_i) = \hat{P}(R_i) \times (1 - \lambda \cdot \rho_{boundary})$$

- $\rho_{boundary}$：预测温度距档位边界 $\le 0.3^\circ\text{C}$ 的成员比例。
- $\lambda = 0.5$：安全边际系数。
- 此调整能有效平滑边界概率，防止模型在临界点过度自信。

### 3.3 预报时效衰减
集合预报的准确度随天数增加而衰减。引入时效衰减因子 $\alpha(d)$ 对原始 Edge 进行平滑：

$$\text{Edge}_{raw} = \hat{P}_{adj}(R_i) - p_{market}$$
$$\text{Edge}_{effective} = \text{Edge}_{raw} \times \alpha(d)$$

- $D+1$ 天 (次日结算)：$\alpha = 1.0$
- $D+2$ 天 (后日结算)：$\alpha = 0.75$
- $D+3$ 天及以上：$\alpha = 0.50$ (不建议大额建仓)

---

## 4. 考虑 Polymarket 费率的期望与 Edge 模型

在引入 Polymarket 官方费率后，单笔投注的数学期望和实际交易成本必须区分为 **Maker 执行** 和 **Taker 执行** 两种模式。

### 4.1 Polymarket 费率与绝对费用计算

我们需要明确区分**成交费率 (Fee Rate)** 与**绝对费用 (Absolute Fee)** 两个不同的概念：

#### 1) Taker 成交费率 (Fee Rate)
这是从实际成交金额（即 USDC 支付额）中收取的比例。Polymarket 的 Taker 费率是根据盘口价格 $p$（即所购买资产的隐含概率）进行动态反算的：
- **买入价格为 $p$ 的 YES 代币**：
  $$\text{FeeRate}_{YES} = \text{feeRate} \times (1 - p)$$
  - 当 $p \to 0$（买入极便宜的 YES 代币）时，费率最高，无限接近于基础费率 $\text{feeRate}$。
  - 当 $p \to 1$（买入极昂贵的 YES 代币）时，费率最低，趋近于 0。
- **买入价格为 $q = 1-p$ 的 NO 代币**：
  $$\text{FeeRate}_{NO} = \text{feeRate} \times (1 - q) = \text{feeRate} \times p$$
  - 当 $q \to 0$（即 $p \to 1$，买入极便宜的 NO 代币）时，费率最高，无限接近于基础费率 $\text{feeRate}$。
  - 当 $q \to 1$（即 $p \to 0$，买入极昂贵的 NO 代币）时，费率最低，趋近于 0。

#### 2) Taker 绝对费用 (Absolute Fee)
绝对费用指交易实际扣除的 USDC 金额。它是实际成交额（$\text{Shares} \times \text{Price}$）与成交费率的乘积：
- **买入 $S$ 份 YES 代币（单价 $p$）**：
  $$\text{Fee}_{YES} = S \times p \times \text{FeeRate}_{YES} = S \times p \times \text{feeRate}(1 - p) = S \times \text{feeRate} \times p(1 - p)$$
- **买入 $S$ 份 NO 代币（单价 $1-p$）**：
  $$\text{Fee}_{NO} = S \times (1 - p) \times \text{FeeRate}_{NO} = S \times (1 - p) \times \text{feeRate} \cdot p = S \times \text{feeRate} \times p(1 - p)$$

因此，无论买 YES 还是 NO，绝对费用在数学上都是完全对称的，公式均为 $S \times \text{feeRate} \times p(1 - p)$：
- 当 $p = 0.5$（单价为 $0.5$）时，绝对费用达到峰值 $0.25 \times \text{feeRate} \times S$；
- 当 $p \to 0$ 或 $p \to 1$ 时，绝对费用均趋于 0。

> [!NOTE]
> 成交费率 $\text{FeeRate}$ 反映的是资金的费率摩擦，而绝对费用 $\text{Fee}$ 反映的是持仓规模下的总成本损耗。在买入价格极低的资产时（如 $p = 0.05$），虽然绝对费用极低，但其成交费率高达 $95\% \times \text{feeRate}$，这一点在期望计算中需要被精确考量。

### 4.2 期望价值 (EV) 修正公式
设真实物理概率为 $\hat{P}$，市场买入价格为 $p$，投注数量为 $S$：

#### 1) Taker 吃单模式 (Market Order)
Taker 交易需即时扣除动态手续费，其实际有效买入成本被抬升：

$$p_{taker\_eff} = p \times (1 + \text{FeeRate}_{taker}) = p + \text{feeRate} \times p(1 - p)$$

单股数学期望 $\text{EV}_{taker}$ 和实际 Edge 修正为：

$$\text{Edge}_{taker} = \hat{P}_{adj} - p - \text{feeRate} \times p(1 - p)$$
$$\text{EV}_{taker} = S \times \text{Edge}_{taker} = S \times \left( \hat{P}_{adj} - p - \text{feeRate} \times p(1 - p) \right)$$

> [!WARNING]
> 当市场价格处于 $0.3 - 0.7$ 的高不确定区间时，绝对费用损耗最大；而当市场价格接近 $0$ 时，虽然绝对费用低，但单笔成交金额的费率摩擦最高。在执行 Taker 扫单时，必须将此摩擦成本扣减，否则会把微弱的正期望变为负期望。

#### 2) Maker 挂单模式 (Limit Order)
Maker 交易无手续费，且获得返佣（Rebate，设定返佣率为 $\beta$，通常为 Taker 费率的 20%~25%）：

$$p_{maker\_eff} = p - \beta \times \text{feeRate} \times p(1 - p)$$
$$\text{Edge}_{maker} = \hat{P}_{adj} - p + \beta \times \text{feeRate} \times p(1 - p)$$
$$\text{EV}_{maker} = S \times \text{Edge}_{maker} = S \times \left( \hat{P}_{adj} - p + \beta \times \text{feeRate} \times p(1 - p) \right)$$

### 4.3 费率对期望的影响对比示例
假设某天气档位：$\hat{P}_{adj} = 0.55$，市场价格 $p = 0.50$，基础费率 $\text{feeRate} = 1.5\%$，返佣率 $\beta = 20\%$，买入 $S = 1000$ 股：
- **无费率理想状态**：$\text{Edge} = 5\%$，$\text{EV} = +50$ USDC。
- **Maker 挂单执行**：
  $$\text{Edge}_{maker} = 0.55 - 0.50 + 0.20 \times 0.015 \times 0.5 \times (1-0.5) = 5.075\%$$
  $$\text{EV}_{maker} = +50.75 \text{ USDC}$$
- **Taker 吃单执行**：
  $$\text{Edge}_{taker} = 0.55 - 0.50 - 0.015 \times 0.5 \times (1-0.5) = 4.625\%$$
  $$\text{EV}_{taker} = +46.25 \text{ USDC}$$

---

## 5. 投注量计算与双阶段凸优化凯利求解器

系统已弃用传统的阶梯投注法，升级为基于数值计算的**双阶段双边 YES/NO 多结局凸优化凯利求解器**，利用 `scipy.optimize.minimize` (SLSQP 算法) 在严格的预算约束下求解最优资金分配。

### 5.1 动态 Noise Floor (噪声区下限)
由于 Maker 与 Taker 存在成本差异，设置不同的噪声死区：
- **Maker 噪声死区**：$\text{NoiseFloor}_{maker} = 3.5\%$ (主要覆盖预报的标准误差与买卖价差)。
- **Taker 噪声死区**：$\text{NoiseFloor}_{taker} = 5.0\%$ (额外覆盖动态手续费损耗)。

### 5.2 阶梯投注表
设定本金 $C = 10,000$ USDC，基础投注单元 $U = C \times 0.5\% = 50$ USDC。下注额取决于执行模式下的有效 Edge：

| 有效 Edge 区间 | 下注级别 | 投入比例 (占 C) | 投入金额 (USDC) |
| :--- | :--- | :--- | :--- |
| $\text{Edge} < \text{NoiseFloor}$ | 噪声区 (死区) | 0% | $0 |
| $\text{NoiseFloor} \le \text{Edge} < 10\%$ | 试探级别 (1U) | 0.5% | $50 |
| $10\% \le \text{Edge} < 20\%$ | 优势级别 (3U) | 1.5% | $150 |
| $20\% \le \text{Edge} < 35\%$ | 确信级别 (6U) | 3.0% | $300 |
| $\text{Edge} \ge 35\%$ | 极度确信级别 (10U) | 5.0% | $500 |

### 5.3 最小交易约束与风控 Shares 化
- **最小下注额**：$\text{Min\_Bet} = 5$ USDC。若计算出的下注金额低于此值则不执行。
- **风控核心单位 (Shares 化)**：Polymarket 风险暴露由持有代币数（Shares）决定，因为低价代币具有极高杠杆。
  $$\text{Max\_Net\_Shares}_{single} = C \times 10\% = 1,000 \text{ 份}$$
  即单档位持有的最大净 Shares 数量不得超过 1,000 份。

---

## 6. 综合投注：必胜套利与风险对冲

### 6.1 考虑 Taker 费率的 Dutch Book 必胜套利
Dutch Book 的核心是在同一天气盘口的所有互斥档位上各买入 1 份 YES，总成本低于结算回收的 $1.00，实现无风险套利。
但在实际操作中，如果使用 Taker 模式吃单，必须将动态绝对费用计入总成本：

$$\text{Total Cost}_{taker} = \sum_{i=1}^{N} \left( p_i + \text{feeRate} \times p_i(1 - p_i) \right)$$

#### 1) Taker Dutch Book 获利条件
$$\Sigma_{taker\_eff} = \sum_{i=1}^{N} p_i + \text{feeRate} \times \sum_{i=1}^{N} p_i(1 - p_i) < 1.00$$
若满足此条件，则可即时使用 Market Order 扫单，锁定无风险利润。

#### 2) Maker Dutch Book 获利条件
$$\Sigma_{maker\_eff} = \sum_{i=1}^{N} p_i - \beta \times \text{feeRate} \times \sum_{i=1}^{N} p_i(1 - p_i) < 1.00$$
Maker 套利要求更宽松，且有返佣支持。策略应优先尝试在所有档位以限价单挂单建仓。

> [!IMPORTANT]
> **Dutch Book 执行算法**：
> 1. 每轮扫描计算 $\Sigma_{taker\_eff}$ 和 $\Sigma_{maker\_eff}$。
> 2. 设置套利最小利润安全边界 $\alpha_{db\_margin} = 2.0\%$。
> 3. 若 $\Sigma_{taker\_eff} < 0.98$，立即执行 Taker 扫单；若 $\Sigma_{maker\_eff} < 0.98$ 且盘口深度稳定，以限价单挂单套利。

### 6.2 反向锁利对冲 (Reverse Lock-in Hedge)
当持有的 YES 代币大幅升值，且结算概率发生漂移时，可通过买入相同 Shares 数量的 NO 代币或相邻档位的 YES 来锁定收益。
设以均价 $\bar{p}_{YES}$ 持有 $S$ 份 YES，当前 NO 代币 Taker 价格为 $p_{NO}$：
$$\text{锁利判定式 (Taker)}: \bar{p}_{YES} + p_{NO} + \text{feeRate} \times p_{NO}(1 - p_{NO}) < 1.00$$
若公式成立，买入 $S$ 份 NO 即可锁定无风险净利润：
$$\text{Locked Profit} = S \times \left( 1.00 - \bar{p}_{YES} - p_{NO} - \text{feeRate} \times p_{NO}(1 - p_{NO}) \right)$$

### 6.3 跨档位对冲 (Adjacent Bucket Hedge)
天气预报的温度不确定性呈连续正态分布。为降低胜率方差，采用“核心-卫星”配置：
- **核心档位**：购买概率最高的 $R_i$。
- **卫星档位**：以较小仓位（如 1U 或限价单）购买相邻的 $R_{i-1}$ 和 $R_{i+1}$，确保当气温微偏时仍能收回大部分本金。

---

## 7. 多次投注：动态仓位管理与风控墙

系统每 5 分钟轮询一次。每轮计算最新有效 Edge，并与现有持仓对比，决定是否加仓、持有或平仓。

### 7.1 风控三条件墙 (Risk Gates)
任何一笔买入指令（Maker 挂单或 Taker 吃单）在执行前必须同时通过以下三道风控关卡：

1. **单边净持仓数量硬顶 (Net Shares Limit)**：
   $$|S_{YES,i} - S_{NO,i}| \le C \times 10\% = 1,000 \text{ 份}$$
2. **单市场总资金占用硬顶 (Capital Lock Limit)**：
   $$\text{Cost}_{YES\_total} + \text{Cost}_{NO\_total} \le C \times 15\% = 1,500 \text{ USDC}$$
   *(对冲买单不受此限，直到 Shares 达到 1:1 配平)*
3. **组合级别总敞口上限 (Portfolio Exposure Limit)**：
   $$\sum_{m} \sum_{i} |S_{m,i}^{YES} - S_{m,i}^{NO}| \times p_{m,i} \le C \times 70\% = 7,000 \text{ USDC}$$

### 7.2 动态调仓与翻转防抖 (Hysteresis Band)
为了防止价格在临界点震荡导致高频调仓（吃单费率损耗），引入**翻转防抖机制**：
- **常规加仓**：有效 Edge 跨越到更高阶梯时，追加下注至该阶梯对应的总仓位。
- **平仓/减仓**：当有效 Edge 跌落至对应执行模式的 $\text{NoiseFloor}$ 以下时，触发逐步减仓。
- **方向翻转** (如 YES 仓平仓并反向买 NO)：
  - **触发条件**：相反方向的 $\text{Edge}_{effective}$ **连续 3 轮轮询** 均大于 $15\%$，且原方向 $\text{Edge} < -5\%$。
  - **执行顺序**：**先减仓（平仓），后建仓**。严禁同时持有大量双向净敞口。

---

## 8. 时间维度对冲与实况集成策略

气温变化的极值通常出现在特定的时间段，而预报数据更新存在滞后。因此必须引入基于当地时间的**四阶段执行策略**。

### 8.1 四阶段时间策略定义

#### 阶段 Ⅰ：远期侦察 (结算前 > 24h)
- **特征**：预报不确定性大，盘口流动性差，价差大。
- **策略**：**严控 Taker 吃单**。仅在有效 $\text{Edge} > 15\%$ 时，以 **Maker 限价单** 挂单试探建仓（最大投入限额的 30%），规避手续费并赚取返佣。

#### 阶段 Ⅱ：标准作战 (结算前 12h ~ 24h)
- **特征**：最新集合预报数据（06z/12z）已发布，概率估计置信度提高。
- **策略**：标准执行。根据计算的 $\text{Edge}_{maker}$ 挂单，若价差极小且 Edge 充足，可少量使用 Taker 吃单。允许建仓至上限的 70%。

#### 阶段 Ⅲ：决战时刻 (结算前 6h 内至结算)
- **特征**：气温开始向极值逼近（最高温极值窗口：当地时间 11:00-18:00；最低温极值窗口：当地时间 02:00-08:00）。
- **策略**：**实况温度驱动（Live-Data Trigger）** 与 **Taker 决战**。
  - 接入实况气象 API（如 Open-Meteo Realtime API）。
  - **实况突破触发**：若当日已测得的实况温度已经超越了某些低温档位，则这些档位的 YES 概率降为 0%，高于实况温度的档位概率大增。立即使用 **Taker 吃单** 扫货被低估的 YES，或者买入已死档位的 NO（如有盘口）。
  - **EV 信心增强**：此时预报误差极低，可将 $\text{Edge}_{effective}$ 乘以信心系数 $\phi = 1.3$（等效于降低噪声阈值），以 Taker 快速扫单。

#### 阶段 Ⅳ：收割与退出 (极值已确定)
- **特征**：极值窗口已过，气温开始回落或回升，当日极值已成定局。
- **策略**：**全面锁利与残值清理**。
  - 启动高频 Dutch Book 扫描，寻找未反应过来的滞后盘口。
  - 对有利润持仓执行 Reverse Lock-in 锁定 100% 收益。
  - 对概率降为 0% 的残余持仓，如有买盘（如 $0.001 - $0.005），折价平仓以回收流动性。

---

## 9. 附录：策略参数汇总表

| 参数变量名 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `allocated_capital` | 10,000 USDC | 策略虚拟本金 ($C$) |
| `base_unit` | 50 USDC | 基础投注单元 ($U = C \cdot 0.5\%$) |
| `base_fee_rate` ($\gamma$) | 1.5% (150 bps) | Polymarket Taker 基础费率 |
| `maker_rebate_rate` ($\beta$) | 20.0% | Maker 返佣比例 (占 Taker 费的百分比) |
| `noise_floor_maker` | 3.5% | Maker 挂单模式下的 Edge 噪声下限 |
| `noise_floor_taker` | 5.0% | Taker 吃单模式下的 Edge 噪声下限 |
| `max_net_shares` | 1,000 份 | 单档位最大净持仓股数限制 |
| `max_capital_lock` | 1,500 USDC | 单市场最大资金锁定限制 |
| `max_portfolio_exposure`| 7,000 USDC | 投资组合总风险敞口限制 |
| `min_bet_usdc` | 5.0 USDC | 最小下注和调仓金额限制 |
| `min_dutch_book_margin` | 2.0% | Dutch Book 套利最小安全利润率 |
| `boundary_buffer` | 0.3°C | 边界平滑温差区间 |
| `reversal_consecutive_rounds`| 3 轮 | 仓位翻转所需的连续轮数 |
| `reversal_edge_threshold`| 15.0% | 翻转动作触发的 Edge 阈值 |
| `lead_d1_alpha` | 1.00 | D+1 日期衰减因子 |
| `lead_d2_alpha` | 0.75 | D+2 日期衰减因子 |
| `lead_d3_alpha` | 0.50 | D+3 日期衰减因子 |
| `phase_3_edge_boost` ($\phi$) | 1.30 | Phase III 决战阶段 Edge 放大系数 |