# 规格书：Polymarket 盘口定价映射、区间积分与动态 EV 引擎 (Phase 2 Task 04)

- **Spec Issue**: [#76](https://github.com/oasislin/Poly2/issues/76) (Spec: Phase 2 Task 04 - Polymarket 盘口定价映射、区间积分与动态 EV 引擎)
- **Tickets**:
  - `Phase 2 Task 04 - Ticket 01`: [#77](https://github.com/oasislin/Poly2/issues/77) (Frontier)
  - `Phase 2 Task 04 - Ticket 02`: [#78](https://github.com/oasislin/Poly2/issues/78)
  - `Phase 2 Task 04 - Ticket 03`: [#79](https://github.com/oasislin/Poly2/issues/79) (Frontier)
  - `Phase 2 Task 04 - Ticket 04`: [#80](https://github.com/oasislin/Poly2/issues/80)
  - `Phase 2 Task 04 - Ticket 05`: [#81](https://github.com/oasislin/Poly2/issues/81)

---

## 问题陈述 (Problem Statement)

在 Polymarket 二元期权温度预测市场中，标的合约是由一系列互斥且完备的离散温度档位构成的。模型端（Phase 2 Task 01 产出的 EMOS 模型）输出的是连续的高斯物理分布参数 $(\mu, \sigma)$，而交易端需要对具体的离散档位合约进行定价下注。

原有系统在概率映射与期望收益（EV）计算上存在四个严重的结构性缺陷：
1. **台站宇宙脱节与浮点下溢隐患**：旧版 `BinConverter` 硬编码了历史旧站（如已退役或隔离的 KDEN/ZSPD），未对 Active 10 站（全部为华氏度 1°F 档位）建立原生适配；且旧积分计算未强制采用 `scipy.special.ndtr`，在分布尾部容易产生数值下溢与舍入失真；
2. **实况截断未联动重正化**：当 Task 02 产生的日内实测极值（$T_{max\_so\_far}$ 或 $T_{min\_so\_far}$）推进时，物理上已被超越的死档虽然应置 0，但现有代码缺少对剩余活档概率的条件概率重正化（Simplex Re-normalization），导致概率和 $< 1.0$，扭曲真实胜率；
3. **临界舍入悬案（PENDING-01）**：Polymarket 官方基于 NWS 整数华氏度结算。当真实极值落在临界值（如 $74.50^\circ\text{F}$）时，Python 原生 `round()` 的银行家舍入（四舍六入五成双）会导致偶数向下舍入，产生错档致命亏损；且缺乏临界预警沙盘；
4. **缺乏订单簿微观深度与动态费率 EV 引擎**：盘口定价不能仅停留在“中间价（Mid-price）”，必须穿透订单簿的 Ask/Bid 深度，结合 Polymarket 费率模型（Taker/Maker 费用）计算真实的净期望收益（Net EV）与有效边缘（Edge），否则极易因未计交易摩擦而买入负 EV 陷阱。

---

## 解决方案 (Solution)

严格依据已裁决的 `ADR-0012`（法定结算真值源与舍入闭环）及《Phase 2 执行文件 v2.0》§1、§2、§6 规范，在 `src/prediction/` 与 `src/pricing/` 架构全新一代定价与动态 EV 引擎：

1. **Active 10 站高精 ndtr 离散区间积分转换器 (`DiscreteBinEngine`)**：
   - 严格适配 Active 10 交易宇宙（全部基于 1°F 整数温度档位：$\le T_{min}$, $T_1$, $T_2$, $\dots$, $\ge T_{max}$）；
   - 目标区间 $[B_i, B_{i+1})$ 的模型预测概率必须采用 `scipy.special.ndtr`：
     $$p_{\text{model}}(i) = \Phi\left(\frac{B_{i+1} - \mu}{\sigma}\right) - \Phi\left(\frac{B_i - \mu}{\sigma}\right)$$
   - 半度连续性修正（Half-Degree Continuity Correction）：整数 $T^\circ\text{F}$ 档位对应的物理积分区间为 $[T - 0.5, T + 0.5)^\circ\text{F}$；
   - 保证全空间概率单纯形约束：$\sum_{i} p_i = 1.000000$（容差 $\le 10^{-6}$）。
2. **极值单调截断与条件单纯形重正化 (`TruncatedProbabilityEngine`)**：
   - 接入 Task 02 单调合流极值：
     - 最高温 TMAX：若实测已达 $T_{obs}$，则所有满足 $T + 0.5 \le T_{obs}$ 的档位，其结算概率永久归零：$p_{\text{model}}(i) \equiv 0.0$；
     - 最低温 TMIN：若实测已达 $T_{obs}$，则所有满足 $T - 0.5 \ge T_{obs}$ 的档位，其结算概率永久归零：$p_{\text{model}}(i) \equiv 0.0$；
   - 条件重正化：将剩余存活档位的概率和按单纯形归一化：$p'_k = \frac{p_k}{\sum_{j \in \text{Alive}} p_j}$，保证概率乘法侧严格归一。
3. **法定 NWS WRH 算术四舍五入 (Half-Up) 与临界哨兵 (`SettlementRoundingSimulator`)**：
   - 强制使用 Python `decimal` 模块的 `ROUND_HALF_UP` 算术四舍五入复刻 NWS 官方结算真值；
   - 设立临界哨兵（Borderline Sentinel）：日内极值落在任一整数的 $[X.45, X.55]^\circ\text{F}$ 闭区间内时，自动打上 `BORDERLINE_CRITICAL` 标签，并输出向上进位与向下舍去的双向预期沙盘。
4. **订单簿深度穿透与动态 EV 引擎 (`DynamicEVEngine`)**：
   - 输入：当前盘口订单簿快照（Bids / Asks 深度档位：价格与可用量）与模型重正化胜率 $p_i$；
   - 注入动态费率策略：考虑 Polymarket 费率 $f$（Taker/Maker 差异）；
   - 计算穿透加权成本 $P_{\text{eff}}$ 与净期望收益：
     $$\text{EV} = p_i \cdot (1.0 - f) - P_{\text{eff}}, \quad \text{Edge} = \frac{\text{EV}}{P_{\text{eff}}}$$
   - 过滤生成正期望收益交易信号（`EVTradeSignal`），仅当 $\text{Edge} \ge \text{min\_reprice\_edge}$ 时允许触发开仓意图。

---

## 用户故事 (User Stories)

1. 作为量化研究员，我希望连续高斯分布 $(\mu, \sigma)$ 能够通过高精 `ndtr` 积分映射到 Active 10 站的 1°F 离散温度档位上，以便消除数值下溢与近似误差。
2. 作为风控主管，我希望日内实测极值突破某个档位时，该死档的概率不可逆归零，且剩余存活档位自动按条件概率重正化，以便模型概率始终反映最新的物理现实。
3. 作为结算工程师，我希望结算规则严格遵从 NWS WRH 的算术四舍五入（Half-Up），杜绝 Python 默认银行家舍入导致的错档爆仓。
4. 作为交易员，我希望在温度接近 .50°F 临界点时系统发出 Borderline 预警并输出进位与舍去双向情景沙盘，以便提前掌控结算歧义风险。
5. 作为执行算法工程师，我希望 EV 计算引擎能够穿透订单簿流动性深度，结合真实手续费计算净收益与 Edge，以便坚决不向下发负 EV 或被深度滑点击穿的订单。
6. 作为系统测试人员，我希望通过完整的端到端集成测试套件断言概率归一、死档归零、Half-Up 舍入与深度加权 EV 计算的数学正确性。

---

## 实现决策 (Implementation Decisions)

- **核心接口与分层设计**：
  - `src/prediction/discrete_bin_engine.py`：实现高精 `ndtr` 区间积分，生成 Active 10 站标准化 1°F 档位列表；
  - `src/prediction/truncated_probability_engine.py`：实现吸收合流极值的死档置零与单纯形条件概率重正化；
  - `src/settlement/rounding_simulator.py`：实现 Decimal `ROUND_HALF_UP` 算术四舍五入与 `BorderlineSentinel` 双向沙盘；
  - `src/pricing/ev_engine.py`：实现包含订单簿深度穿透与费率模型在内的 `DynamicEVEngine`，输出 `EVTradeSignal`。
- **交易宇宙锁定**：
  - 严格限定在 `ACTIVE_10_STATIONS`（`KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS`）。
- **零魔法数与配置受控**：
  - 在 `configs/default.yaml` 中新增/规范 `pricing` 与 `ev_engine` 配置节（`min_reprice_edge: 0.03`, `taker_fee_rate: 0.0`, `borderline_tolerance: 0.05` 等）。

---

## 测试决策 (Testing Decisions)

- **单元与组件测试**：
  - `test_discrete_bin_engine.py`: 验证 ndtr 尾部极端积分稳定性、区间互斥完备性与和为 1.0；
  - `test_truncated_probability_engine.py`: 验证 TMAX/TMIN 极值注入后死档严格为 0.0、存活档位单纯形和为 1.0；
  - `test_rounding_simulator.py`: 验证 .49°F 舍去、.50°F 进位、.51°F 进位，断言与 Python 原生 round 的差异；
  - `test_ev_engine.py`: 验证薄盘口深度加权成本、费率扣减、+EV 筛选与阈值过滤。
- **集成与验收测试**：
  - `tests/integration/test_pricing_ev_pipeline.py`: 从 $(\mu, \sigma)$ 到实况极值截断，再到订单簿注入与 EVTradeSignal 生成的全链路端到端闭环验证；
- **网络与冒烟硬性纪律**：
  - 持续保证真实 GEFS 网络冒烟绿灯：
    `RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`。

---

## 范围外声明 (Out of Scope)

- 四桶资金状态机与联合凯利仓位最优化（属于 Task 05 范畴）；
- CLOB 订单签名、IOC 限价单路由与非原子成交残局处理（属于 Task 06 范畴）。

---

## 任务垂直切片拆分 (Tickets Breakdown)

1. **`Phase 2 Task 04 - Ticket 01: feat(pricing): 高精 ndtr 连续分布向 Active 10 站离散区间积分转换器`**
   - **内容**：实现 `DiscreteBinEngine`，使用 `scipy.special.ndtr` 进行半度连续性高斯累积分布区间积分，原生适配 Active 10 站 1°F 整数档位，输出归一化离散概率分布；
   - **依赖**：无（Frontier）。

2. **`Phase 2 Task 04 - Ticket 02: feat(truncation): 极值单调截断概率归零与单纯形条件重正化引擎`**
   - **内容**：实现 `TruncatedProbabilityEngine`，对接合流极值（$T_{max\_so\_far}$, $T_{min\_so\_far}$），死档概率不可逆强制归零，存活档位执行条件概率单纯形归一化；
   - **依赖**：Blocked by `Ticket 01`。

3. **`Phase 2 Task 04 - Ticket 03: feat(settlement): 法定 NWS WRH 算术四舍五入 (Half-Up) 与临界哨兵沙盘`**
   - **内容**：实现 `SettlementRoundingSimulator`，使用 `decimal.Decimal` 与 `ROUND_HALF_UP` 复刻官方结算真值，实现 $[X.45, X.55]$ 临界哨兵预警与双向情景沙盘；
   - **依赖**：无（可独立推进或并行）。

4. **`Phase 2 Task 04 - Ticket 04: feat(ev): 订单簿深度穿透加权与微观结构动态 EV 计算引擎`**
   - **内容**：实现 `DynamicEVEngine`，穿透订单簿挂单深度计算买入加权成本，注入 Polymarket 费率模型，计算净 EV 与 Edge，输出标准化 `EVTradeSignal`；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 02`。

5. **`Phase 2 Task 04 - Ticket 05: test(acceptance): 盘口定价与 EV 全链路端到端集成测试套件`**
   - **内容**：实现全链路集成测试，覆盖从参数输入、极值截断、四舍五入检验到深度 EV 信号生成的全流程，确保网络冒烟全绿；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 02`, `Ticket 03`, `Ticket 04`。
