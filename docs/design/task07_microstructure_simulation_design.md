# Task 07 微观结构仿真与回测引擎重构设计方案

> **文档版本**: v1.0.0  
> **文档状态**: **已作废挂起（SUSPENDED & VOID）**  
> **状态说明**: 经架构裁决，物理模型当前阶段不以任何合成盘口做市商回测作为有效性证明。本任务全量挂起，系统工作重心全面转移至 Active 10 站物理模型全量生产升级（Phase 2 Task 08）。  
> **关联任务**: Phase 2 Task 07 (已停用)  
> **关联议题**: Issue #101, #102, #103  

---

## 一、历史盘口数据来源溯源与证据等级声明 (Data Provenance & Reality Boundary)

### 1.1 气象数据与盘口数据的物理不对称性
在量化回测与概率预测系统验证中，必须严格区分**物理气象数据**与**金融盘口数据**的真实性边界：
- **物理气象数据（真值与输入）**: 2000–2018 年训练集与 2019 年样本外盲测集（OOS）中的气温真值来自美国国家气象局（NWS）GHCN-Daily 官方地面台站实测数据（已通过 MADIS 多传感器交叉核验）；数值预报输入来自 NOAA GEFS v12 官方可溯源的历史再预报网格（Reforecast）。此部分物理数据为**客观存在的一手历史真值（Ground Truth）**。
- **预测市场盘口数据（对手方与流动性）**: Polymarket 预测平台上线于 2020 年，其每日结算的高频单站气温离散预测市场（Daily Temperature Bin Markets）实际于 2024–2026 年方形成具有连续中央限价订单簿（CLOB）的流动性盘口。**在 2019 年历史回测区间内，客观现实中不存在任何真实的 Polymarket 气温订单簿或历史撮合记录。**

### 1.2 证据等级评估与生成模式裁决
针对 2019 年历史回测缺乏一手真实盘口的客观现实，评估以下三种建模路径：

| 模式 | 方案描述 | 适用性与现实缺陷 | 证据等级裁定 |
| :--- | :--- | :--- | :--- |
| **模式 (a)**<br>真实历史重放 | 回放 2019 年 Polymarket 真实高频订单簿 (L2/L3 tick data)。 | **客观不可行**：2019 年 Polymarket 气象市场尚未建立，数据资产在物理现实中不存在。 | **N/A (物理不存在)** |
| **模式 (b)**<br>现代特征校准生成器 | 采集 2024–2026 年真实 Polymarket 气象合约 CLOB 盘口快照，提取价差分布、盘口厚度、逆向选择惩罚与挂单衰减率参数，驱动参数化做市商（Semi-synthetic Generator）。 | **推荐采用**：结合现代真实市场微观结构与 2019 真实物理气象预报，提供最具结构逼真度的仿真环境。必须声明属于“半合成”测试，并在敏感性分析中覆盖深度漂移。 | **Level 2 (半合成结构化仿真)** |
| **模式 (c)**<br>理论最劣界测算 | 忽略中间流动性，假设所有开仓均承受滑点上限，测算策略实现正收益的临界流动性阈值。 | **辅助约束**：作为防御性底线检验，验证策略在极度流动性挤压下的生存能力。 | **Level 3 (保守压力边界)** |

**方案裁决**：Task 07 重构正式确立以**模式 (b) 为基准模型**，并以**模式 (c) 作为极端压力门禁**。严禁将回测指标宣传为实盘业绩，回测结论仅用于检验“概率优势在经过合理微观摩擦过滤后是否具备可交易的统计超额”。

### 1.3 现代市场特征校准基准与压力测试矩阵
依据 2024–2026 年 Polymarket 气温市场观测到的 CLOB L2 快照，标定基准微观参数，并预注册跨参数敏感性测试矩阵：

```
                              [微观结构参数扰动网格]
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
     【稀薄流动性 (50%)】        【基准流动性 (100%)】       【充裕流动性 (200%)】
     Level 1: $75               Level 1: $150              Level 1: $300
     Spread: 5¢ ~ 8¢            Spread: 3¢ ~ 5¢            Spread: 2¢ ~ 3¢
     Decay: 快速衰减            Decay: 对数衰减            Decay: 线性衰减
```

**敏感性压力测试矩阵参数定义**：
1. **盘口深度乘数 ($\kappa_{\text{depth}}$)**：
   - 稀薄深度（Thin Market）: $\kappa_{\text{depth}} = 0.5$（Level 1 深度 \$75，Level 2 \$125，Level 3 \$200）；
   - 基准深度（Baseline）: $\kappa_{\text{depth}} = 1.0$（Level 1 深度 \$150，Level 2 \$250，Level 3 \$400）；
   - 充裕深度（Deep Market）: $\kappa_{\text{depth}} = 2.0$（Level 1 深度 \$300，Level 2 \$500，Level 3 \$800）。
2. **买卖价差跨度 ($S_{\text{spread}}$)**：
   - 紧价差: $S \in [0.02, 0.04]$（2¢ ~ 4¢）；
   - 基准价差: $S \in [0.03, 0.05]$（3¢ ~ 5¢）；
   - 宽价差: $S \in [0.05, 0.08]$（5¢ ~ 8¢）。
3. **逆向选择惩罚系数 ($\alpha_{\text{adv}}$)**：
   - 当外部订单持续单向吃单时，做市商报价向吃单方向动态推挤 1¢ ~ 3¢，抑制做市商无底线倾销白菜价。

---

## 二、四大旧病灶剖析与机制彻底废除对照 (Pathology Autopsy & Abolition)

在前期运行的原型回测引擎中，曾产生“年化夏普 13.06、最大回撤 0.09%、总收益 +1517%”的荒谬指标。经严格技术审计，该虚假业绩源于四个系统性结构病灶。新设计必须在数学与机制上彻底废除旧逻辑。

### 2.1 四大病灶机制与重构对照表

| 病灶维度 | 旧回测引擎缺陷机制 (`src/simulation`) | Task 07 重构规范方案 (`src/simulation_v2`) |
| :--- | :--- | :--- |
| **病灶 1**<br>档位内生绑定偏差<br>*(Bin Center Bias)* | `center_f = int(round(mu))`：由我方 EMOS 预测均值决定市场的 7 个档位。导致档位始终贴合我方分布中心，完全回避了我方大幅误判时“档位不在中心”的边缘截断风险。 | **外生规则固定档位**：合约档位严格在 00:00 UTC 依据外生公开预报（未经校准的早间 GEFS 集合平均四舍五入整数）或固定整数网格设立，开盘后静态冻结，绝对不得引用回测策略的任何内部状态。 |
| **病灶 2**<br>做市商无脑倾销<br>*(Naive Dumping MM)* | 做市商仅依据 raw GEFS 静态高斯积分挂出无脑报价，在策略具有 20%~30% EV 的边缘档位以 0.03 美元恒定挂出 150 股，且无库存风险控制和价差走阔。 | **真实订单簿消耗（Walk the Book）+ 逆向选择保护**：引入有限深度分层阶梯（L1/L2/L3），单笔订单穿透深度时按加权边际价格成交；做市商引入库存偏斜与逆向选择价差拓宽。 |
| **病灶 3**<br>独立二元独立假定<br>*(Independent Bin Fallacy)* | 在单一市场买入多个档位时，未考虑互斥合约的联合约束；部分档位缺失挂单时缺少优雅退化机制；分数凯利固定取 $\lambda = 0.25$ 缺乏数理依据。 | **7 档互斥分类凯利（Categorical Kelly）凸优化**：在概率单纯形与互斥收益曲面上联合求解；若某档位缺失报价，强制约束 $f_k = 0$ 退化至子空间求解；$\lambda$ 由历史 ECE 误差外生约束。 |
| **病灶 4**<br>日频 100% 摩擦清算<br>*(Zero-Lockup Reinvestment)* | 当天 18h lead 投注，当天 24:00 全额结算回 Free USDC；10 个台站分散独立平滑，导致资金每日无摩擦复利，抹平一切跨日波动，伪造回撤 0.09%。 | **UMA 结算延迟与在途资金锁闭队列**：强制执行 24h~72h 争议挑战期（T+1 到 T+3）；未完成争议裁决前资金绝对锁闭在 Settlement-Pending 队列，不得用于再次建仓。 |

---

## 三、7 档互斥分类凯利优化模型形式化推导 (Categorical Kelly Optimization)

气象预测市场的每一个标的（如 KORD 当日最高温）由 $K=7$ 个严格互斥且完备的离散温度区间组成（$\sum_{k=1}^K \mathbb{I}_{\{k=y\}} = 1$）。策略在同一标的内可同时持有多个档位以形成复合分布头寸。

### 3.1 收益结构与对数财富增长目标函数
设初始可用资本为 $W_{\text{free}}$，我们在 $K$ 个档位上分别配置的资金比例为 $f = (f_1, f_2, \dots, f_K)^T$，其中 $f_k \ge 0$ 为投入档位 $k$ 的资金占总可用资本的比例。  
对于档位 $k$，市场卖一档（Best Ask）执行价格为 $q_k \in (0, 1)$。若买入金额为 $f_k W_{\text{free}}$，则获得的合约份数为：
$$
N_k = \frac{f_k W_{\text{free}}}{q_k}
$$
各档位严格互斥，最终有且仅有一个档位 $j \in \{1, \dots, K\}$ 发生结算（赔付 \$1.00，其余档位赔付 \$0.00）。  
因此，当真实气温落在档位 $j$ 时，清算后的总财富为：
$$
W(j) = W_{\text{free}} \left( 1 - \sum_{k=1}^K f_k \right) + N_j = W_{\text{free}} \left( 1 - \sum_{k=1}^K f_k + \frac{f_j}{q_j} \right)
$$
财富增长倍率为：
$$
R(j; f) = 1 + \left( \frac{1}{q_j} - 1 \right) f_j - \sum_{k \ne j} f_k = 1 + \frac{f_j}{q_j} - \sum_{k=1}^K f_k
$$
我方经 EMOS 及极端物理截断校准后的主观概率向量为 $p = (p_1, p_2, \dots, p_K)^T$，满足 $p_k \ge 0$ 且 $\sum_{k=1}^K p_k = 1$。  
凯利准则要求最大化期望对数财富增长率 $G(f)$：
$$
\max_{f} G(f) = \sum_{j=1}^K p_j \ln \left( 1 + \frac{f_j}{q_j} - \sum_{k=1}^K f_k \right)
$$

### 3.2 约束条件与凸性证明
优化问题受以下线性约束限制：
1. **非负杠杆约束**: $f_k \ge 0, \quad \forall k \in \{1, \dots, K\}$
2. **总预算不透支约束**: $\sum_{k=1}^K f_k \le f_{\max} \le 1.0$（其中 $f_{\max}$ 为单市场最高资金敞口，如 0.20）
3. **破产安全约束**: 对任意 $j \in \{1, \dots, K\}$，财富必须严格为正：
   $$
   1 + \frac{f_j}{q_j} - \sum_{k=1}^K f_k > 0
   $$

**凸性证明**：
目标函数中的项 $u_j(f) = 1 + \frac{f_j}{q_j} - \sum_{k=1}^K f_k$ 是关于向量 $f$ 的仿射变换（Affine Function）。  
由于标量函数 $h(u) = \ln(u)$ 在其定义域 $\mathbb{R}_{++}$ 上是严格凹函数，且非负权重 $p_j \ge 0$ 下的严格凹函数之和仍为严格凹函数。  
因此，$G(f)$ 在凸集 $\mathcal{F} = \{ f \in \mathbb{R}^K \mid f_k \ge 0, \sum f_k \le f_{\max}, u_j(f) > 0 \}$ 上是**严格凹函数**（Strictly Concave）。  
最小化 $-G(f)$ 属于标准凸优化问题，存在唯一的全局最优解 $f^*$，不存在任何局部伪极小值。

### 3.3 部分档位无报价（Ask 缺失）的退化处理
在真实市场或稀薄流动性切片中，极端档位常出现无挂单（Ask 缺失或流动性深度为 0）的现象。  
设有效报价档位集合为 $\mathcal{A} \subset \{1, \dots, K\}$，无报价档位集合为 $\mathcal{M} = \{1, \dots, K\} \setminus \mathcal{A}$。  
对于 $m \in \mathcal{M}$，无法进行买入建仓，强制施加硬性等式约束：
$$
f_m = 0, \quad \forall m \in \mathcal{M}
$$
此时，优化变量降维为 $|\mathcal{A}|$ 维向量 $f_{\mathcal{A}}$。  
若真实气温落在无报价档位 $m \in \mathcal{M}$，策略无法在该档位获得赔付，$N_m = 0$，此时财富增长倍率为：
$$
R(m; f_{\mathcal{A}}) = 1 - \sum_{k \in \mathcal{A}} f_k
$$
此时的目标函数自然分解为两部分：
$$
\max_{f_{\mathcal{A}}} G(f_{\mathcal{A}}) = \sum_{j \in \mathcal{A}} p_j \ln \left( 1 + \frac{f_j}{q_j} - \sum_{k \in \mathcal{A}} f_k \right) + \left( \sum_{m \in \mathcal{M}} p_m \right) \ln \left( 1 - \sum_{k \in \mathcal{A}} f_k \right)
$$
**数学结论**：  
无报价档位的存在会产生概率惩罚项 $P(\mathcal{M}) = \sum_{m \in \mathcal{M}} p_m$。当不可买入档位的总主观概率 $P(\mathcal{M})$ 较大时，后项的负斜率将对总敞口 $\sum_{k \in \mathcal{A}} f_k$ 施加极其严厉的惩罚，自发压缩可投注档位的配比，防止由于漏保极端档位而引发的毁灭性亏损。

### 3.4 外生分数凯利系数约束 ($\lambda$-Fractional Kelly)
全额凯利（Full Kelly, $\lambda = 1.0$）在物理概率完全精确时具有长期几何增长率最优性，但对分布参数误差极其敏感，易导致剧烈波动与深幅回撤。  
本系统严禁在回测阶段事后内生寻找最优 $\lambda$，必须通过**2000–2018 训练期可验证的外部指标进行外生约束**：

$$
\lambda^* = \lambda_0 \times \max \left( 0.20, \; 1.0 - \gamma \cdot \text{ECE}_{\text{train}} \right) \times \min \left( 1.0, \; \frac{1.0}{\max(1.0, s_{\text{oos}})} \right)
$$

其中：
- $\lambda_0 = 0.25$（基准 Quarter-Kelly）；
- $\text{ECE}_{\text{train}}$ 为 Phase 1 冻结的训练期预期校准误差（三站平均 $\approx 0.035$）；
- $\gamma = 5.0$ 为校准惩罚敏度系数；
- $s_{\text{oos}}$ 为方差比保护因子。
计算得到稳健的外生缩放区间锁定为 $\lambda^* \in [0.20, 0.25]$。最终执行资金向量为：
$$
f_{\text{exec}} = \lambda^* \cdot f^*
$$

---

## 四、UMA 结算延迟与待结算资金锁闭队列模型 (UMA Settlement Lockup Engine)

### 4.1 结算生命周期与争议挑战期
真实 Polymarket 气温市场的结算依赖去中心化预言机（UMA Optimistic Oracle）。结算并非即时发生，必须经历完整的状态流转：

```
 [T 日 18:00 UTC] ──> 执行建仓
        │
        ▼
 [T+1 日 00:00 UTC] ──> 合约到期，锁定交易
        │
        ▼
 [T+1 日 06:00 UTC] ──> NWS GSOD 官方数据发布，提出结算提议 (Propose)
        │
        ├────── UMA 争议挑战窗口 (Challenge Window, 24h ~ 72h)
        ▼
 [T+2 ~ T+4 日] ────> 挑战期结束无异议 / DVM 投票裁决通过 ──> 资金释放到 Free
```

### 4.2 资金账户四状态机形式化定义
废除将资金视为单一自由流动池的简化模型，强制将总资产（Total Equity）划分为四类互斥账户：

$$
W_{\text{total}}(t) = W_{\text{free}}(t) + W_{\text{locked}}(t) + W_{\text{pending}}(t) + W_{\text{settled}}(t)
$$

1. **自由可用资本 ($W_{\text{free}}$)**: 当前未被占用、可立即投入新交易的 USDC 余额；
2. **挂单冻结资本 ($W_{\text{locked}}$)**: 已提交限价单但尚未成交的冻结资金；
3. **在途待结算资本 ($W_{\text{pending}}$)**: 已经成交持有、等待 UMA 预言机裁决的沉淀资金：
   $$
   W_{\text{pending}}(t) = \sum_{pos \in \mathcal{P}_{\text{active}}} \text{Cost}(pos)
   $$
4. **应收已结算资本 ($W_{\text{settled}}$)**: 预言机已出具裁决但尚未执行链上提款（Redeem）的利润/本金。

### 4.3 待结算锁闭队列（Settlement Lockup Queue）算法
引入离散事件队列维护在途资金。每一笔建仓生成一个具有到期时序的记录：

```python
@dataclass(frozen=True)
class SettlementLockupItem:
    market_id: str
    station_id: str
    entry_date: str          # T
    settlement_eligible_date: str  # T + 1 (NWS 真实发布日)
    funds_release_date: str        # T + 1 + challenge_hours (T+2 到 T+4)
    committed_capital: Decimal     # 占用的 USDC 本金
    payout_if_won: Decimal         # 命中时的总返还
    is_winner: bool                # 依据真实 NWS 判定的胜负
```

**流动性挤压约束（Liquidity Crunch Guard）**：  
在任何交易日 $T$，策略可用于配置所有 10 个台站的总预算上限严格受限于当前可用资金：
$$
\text{Budget}_{\max}(T) = \min \left( W_{\text{free}}(T) \times 0.40, \; W_{\text{total}}(T) \times 0.20 \right)
$$
当连续出现多日气象预报高不确定性或恶劣天气引发集中下注时，$W_{\text{pending}}$ 显著上升，$W_{\text{free}}$ 自发萎缩。新模型能够精确复现真实世界中“因前期资金未结算而错失后续机会”或“连续错判导致流动性耗尽”的真实金融回撤特征。

---

## 五、限价订单簿深度消耗与滑点模型 (Walk the Book Execution)

### 5.1 有限深度分层结构
废除旧模型中以单一最优 Ask 价格无限吃单的假设。做市商在每个档位提供 3 档（L1, L2, L3）离散限价挂单：

$$
\mathcal{OB}_k = \left\{ (P_{k, 1}, Q_{k, 1}), \; (P_{k, 2}, Q_{k, 2}), \; (P_{k, 3}, Q_{k, 3}) \right\}
$$

- $P_{k, 1} = P_{\text{mid}, k} + \frac{1}{2} S_k$（L1 价格）
- $P_{k, 2} = P_{k, 1} + \delta_{\text{spread}, 2}$（L2 价格，走阔 2¢）
- $P_{k, 3} = P_{k, 2} + \delta_{\text{spread}, 3}$（L3 价格，走阔 3¢）

### 5.2 撮合消耗与边际成本积分
当凯利优化器决定在档位 $k$ 下注预算 $B_k$ 时，撮合引擎执行“遍历订单簿”（Walk the Book）逻辑：

$$
B_k = \sum_{l=1}^L \Delta B_{k, l}, \quad \text{其中 } \Delta B_{k, l} = \min \left( B_k - \sum_{m=1}^{l-1} \Delta B_{k, m}, \; P_{k, l} \cdot Q_{k, l} \right)
$$

获得的实际合约份额为：
$$
N_k = \sum_{l=1}^L \frac{\Delta B_{k, l}}{P_{k, l}}
$$
有效平均执行价格为：
$$
\bar{P}_k = \frac{B_k}{N_k} \ge P_{k, 1}
$$
若预算 $B_k$ 超过 L3 总挂单容量，超出部分**自动拒单（Kill or Fill Partial）**，严禁以假想无限流动性成交。此举彻底杜绝在小众极端档位上投入巨资产生虚假利润的可能。

---

## 六、预注册与可复现性三项铁律 (Pre-registration & Iron Rules)

为防止任何事后过拟合（Data Snooping）与选择性汇报，Task 07 重构制定以下三项硬性工程门禁：

### 6.1 铁律一：真实财务指标完整同表呈现（严禁报喜不报忧）
任何测试报告必须在同一张汇总表中完整输出以下全部指标，绝对不得隐瞒亏损指标：
1. **净年化夏普比率（Annualized Sharpe）**: 预期合理区间 $[1.0, 2.5]$。若 $\text{Sharpe} > 3.5$，直接触发风控警报并判定为模型异常；
2. **最大回撤（Maximum Drawdown, MDD）**: 必须体现 UMA 锁闭与连败期的真实回撤，严禁出现 $< 1.0\%$ 的假象；
3. **真实亏损日分布（Losing Days Ratio）**: 真实量化策略通常伴随 35%~50% 的亏损日比例，必须如实公布日盈亏分布直方图；
4. **破产概率（Probability of Ruin）**: 在整个 2019 样本外测试期内必须恒等于 0；
5. **利润因子（Profit Factor）**: 总盈利 / 总亏损，预期健康区间在 $[1.2, 2.0]$。

### 6.2 铁律二：敏感性压力测试矩阵预先冻结
在运行 2019 样本外测试前，以下 3 组敏感性测试场景的参数网格必须硬编码冻结于配置文件中：

```json
{
  "scenarios": {
    "thin_liquidity": {
      "depth_multiplier": 0.5,
      "spread_markup": 0.03,
      "mdd_limit_pct": 0.25,
      "min_sharpe": 0.80
    },
    "baseline_liquidity": {
      "depth_multiplier": 1.0,
      "spread_markup": 0.00,
      "mdd_limit_pct": 0.15,
      "min_sharpe": 1.20
    },
    "stressed_worst_case": {
      "depth_multiplier": 0.3,
      "spread_markup": 0.05,
      "mdd_limit_pct": 0.35,
      "min_sharpe": 0.40
    }
  }
}
```
**门禁要求**：策略在“最差流动性压力情景（Stressed Worst-Case）”下必须仍然维持资本正增长且破产概率为 0，方可被认定为具备生产可用性。

### 6.3 铁律三：零容忍学术受控文风
所有设计文档、测试日志、代码注释与呈报总结中，严格遵循客观、量化、严谨的专业标准：
- **禁用形容词清单**：“大圆满”、“终局”、“突破性”、“决胜”、“基石”、“印钞机”、“完美无瑕”；
- **规范用词标准**：使用“符合统计显著性门禁”、“在预设置信区间内通过核验”、“经验微观结构校准”、“有限样本估计噪声”等受控学术词汇。

---

## 七、实施落地规划与里程碑 (Milestones & Next Steps)

本设计方案提交评审委员会审议。审议通过后，按以下切片进行代码实现：

1. **Ticket 07-1 (外生档位与订单簿重构)**:
   - 移除 `center_f = int(round(mu))`；
   - 依据早间 00:00 UTC 原始集合预报建立外生 7 档位网格；
   - 实现包含 L1/L2/L3 深度消耗与逆向选择保护的 `RealisticMarketMaker`。
2. **Ticket 07-2 (分类互斥凯利优化器加固)**:
   - 实现支持无报价档位自动降维退化的 `CategoricalKellyOptimizer`；
   - 接入 Phase 1 冻结 ECE 误差的外生分数凯利系数约束。
3. **Ticket 07-3 (UMA 争议锁闭队列与资金状态机)**:
   - 重写 `BankrollManager`，实现 4 状态资金模型；
   - 建立 24h~72h 延迟清算队列。
4. **Ticket 07-4 (敏感性压力测试与 2019 样本外全量运行)**:
   - 执行 3 组敏感性测试矩阵；
   - 输出包含真实回撤与亏损日分布的完整报表。
