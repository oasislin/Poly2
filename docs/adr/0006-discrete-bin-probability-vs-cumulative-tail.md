# ADR 0006: 离散区间全概率映射与严禁累积尾部单向交易原则

## 状态
已通过（Active / Core Trading Rule）

## 背景与问题陈述
在 Polymarket 温度市场量化预测与交易系统中，动态截断层（`DynamicCorrector`）输出的是条件截断连续概率分布 $F_{post}(x) = P(X \le x \mid \text{Obs})$，并能快速计算累积单侧尾部概率（如 $P(X \ge L \mid X \ge T_{now})$）。

然而，Polymarket 的真实盘口合约**并不是单一的连续阈值赌注**，而是由一组**互斥的离散温度区间（Mutually Exclusive Discrete Bins）**组成（例如上海最高温盘口划分为：`<32°C`, `[32.0, 32.9]`, `[33.0, 33.9]`, `[34.0, 34.9]`, `[35.0, 35.9]`, `≥36.0°C`）。

若在系统设计或策略开发中，错误地将累积尾部概率 $P(X \ge L)$ 直接与某个具体区间档位（如 `[35.0, 35.9]`）的盘口价格进行比对并计算 Edge / EV，将导致灾难性的逻辑错误与资金亏损。

## 致命错误逻辑与机理剖析

### 错误示例
假设日内实况达到 $T_{now} = 34.8^\circ\text{C}$，动态截断层算出累积尾部概率 $P(X \ge 35^\circ\text{C} \mid X \ge 34.8^\circ\text{C}) = 85\%$。
盘口档位 `[35.0, 35.9]` 的当前挂单价格为 $0.35$ 美元。

- **错误认知**：误以为发现巨大 Edge（$85\% - 35\% = +50\%$），进而重仓买入 `[35.0, 35.9]`。
- **事实真相**：这 $85\%$ 的累积概率是后续**所有** $\ge 35^\circ\text{C}$ 区间的概率总和：
  $$ P(X \ge 35) = P(35.0 \le X \le 35.9) + P(X \ge 36.0) = P(\text{Bin}_4) + P(\text{Bin}_5) $$
  若其中极高温档位 $\ge 36.0^\circ\text{C}$（$\text{Bin}_5$）分流了 $55\%$，则目标档位 `[35.0, 35.9]`（$\text{Bin}_4$）的实际区间概率仅有：
  $$ P(35.0 \le X \le 35.9) = 85\% - 55\% = 30\% $$
- **实际后果**：以 $0.35$ 美元买入真实胜率仅 $30\%$ 的合约，产生 **$-5\%$ 的负期望（Negative EV）**，不仅毫无优势，反而直接招致确定性亏损！

## 决策与系统核心铁律

1. **严禁累积尾部单向交易（Strict Prohibition on Cumulative Tail Trading）**：
   - 累积尾部概率 $P(X \ge L)$ 或 $P(X \le L)$ 仅作为数学中间量，**严禁直接用于生成单档位交易信号或计算单档 Edge**。
   - 唯一的特例是盘口中最右侧或最左侧的单向半开无限区间（如 `≥36.0°C` 或 `<32.0°C`），因其自身就是一个完整的 Bin。

2. **必须强制经过 `BinConverter` 离散化映射**：
   - 任何量化下单与持仓决策，必须以具体离散区间的区间积分概率为唯一依据：
     $$ P(\text{Bin}_k) = P(\text{low}_k \le X \le \text{high}_k) = F_{post}(\text{high}_k) - F_{post}(\text{low}_k) $$
   - 必须通过 $\pm 0.5^\circ$ 连续性修正，且全市场所有互斥 Bins 的概率和严格归一化为 1.0（$\sum_{k} P(\text{Bin}_k) = 1.0$）。

3. **Phase 2 多项联合凯利优化器（Multi-Bin Joint Kelly）输入规范**：
   - Phase 2 的仓位计算必须以全部 Bins 的离散概率向量 $\mathbf{p} = [p_1, p_2, \dots, p_K]$ 和市场价格向量 $\mathbf{\pi} = [\pi_1, \pi_2, \dots, \pi_K]$ 作为联合输入。
   - 优化器在评估每个档位的 EV 时，必须严格遵循 $EV_k = p_k / \pi_k - 1$（或对应赔率公式），确保每一笔资金分配都建立在互斥离散档位的真实边缘优势之上。

4. **架构不变量（Pipeline Invariant）**：
   预测到交易执行的严格单向数据流必须恒成立：
   $$ \text{Continuous EMOS} \to \text{Dynamic Truncation} \to \text{Physical Constraints} \to \mathbf{BinConverter (Discrete Bins)} \to \text{Kelly Sizing} \to \text{Execution} $$
