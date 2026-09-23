# 规格书：风控联动贯通、全套注入测试统一验收与纸面盘仿真运行器 (Phase 2 Task 07)

> [!CAUTION]
> **CRITICAL NOTICE (Review Audit R5)**:
> Metrics fixed at commit `67d668b`. All pre-existing metric-dependent conclusions, Sharpe claims (>2.0), and 2019 backtest results in this spec are **VOID pending `--recompute`** with verified statistical closure metrics.
> Furthermore, current paper trading simulator is strictly defined as **Synthetic Opponent Simulation** (using theoretical mathematical pricing). True microsecond order book replay is officially **deferred until genuine L2/L3 order book dataset asset ingestion**.

- **Spec Issue**: [#94](https://github.com/oasislin/Poly2/issues/94) (Spec: Phase 2 Task 07 - 风控联动贯通、全套注入测试统一验收与纸面盘仿真运行器)
- **Tickets**:
  - `Phase 2 Task 07 - Ticket 01`: [#95](https://github.com/oasislin/Poly2/issues/95) (`feat(simulation): 纸面盘事件模型、时钟推进器与仿真账户基石`)
  - `Phase 2 Task 07 - Ticket 02`: [#96](https://github.com/oasislin/Poly2/issues/96) (`feat(simulation): 纸面盘全链路编排引擎与结算收益核算器`)
  - `Phase 2 Task 07 - Ticket 03`: [#97](https://github.com/oasislin/Poly2/issues/97) (`feat(metrics): 仿真交易度量器、夏普比率与资金守恒监控`)
  - `Phase 2 Task 07 - Ticket 04`: [#98](https://github.com/oasislin/Poly2/issues/98) (`test(acceptance): 全套注入测试（Test-Scenario A~E）统一验收门禁与端到端串联`)
  - `Phase 2 Task 07 - Ticket 05`: [#99](https://github.com/oasislin/Poly2/issues/99) (`feat(runner): Active 10 站 48h 纸面盘仿真运行器 CLI 与全量验证`)

---

## 一、 问题陈述与目标 (Problem Statement & Goals)

Polymarket 温度市场量化预测系统在完成数据源单调合流（Task 02）、统一仲裁中枢（Task 03）、动态 EV 定价（Task 04）、联合凯利增量分配（Task 05）以及 IOC 保护价执行引擎（Task 06）等各个模块的独立研发与切片测试后，进入 Phase 2 的**终局验收与实战模拟落地（Task 07）**阶段。
系统面临的核心工程与数学挑战包括：
1. **全套注入测试（Test-Scenario A ~ E）的统一集成断言**：
   各 Scenario 此前分布在独立测试文件中，缺少一个端到端一体化门禁套件来证明：在真实复合场景中，多模块并存时不会发生状态踩踏、死锁或契约撕裂；
2. **实战纸面盘（Paper Trading）全生命周期闭环**：
   系统需要一个轻量、精确、事件驱动的仿真系统（`PaperTradingSimulator`），在 48 小时多站并发运行中，将数据合流、心跳异常检测、两维阶梯风控、EV定价、联合凯利、IOC 限价单发单撮合、非原子残局自愈与真值结算串联成闭环；
3. **严格风控指标与零非物理下单门禁**：
   必须建立严格的度量器（`SimulationMetricsCalculator`），对 48h 运行窗口统计净值曲线（NAV）、最大回撤（MDD）与模拟资金夏普比率（Sharpe Ratio > 2.0），并严格执行：
   - 零非物理下单（零概率截断档位禁止发单）；
   - 零滑点穿仓与四桶资金 Decimal 守恒无缝衔接。

---

## 二、 核心架构规范与数学契约 (Architectural Contracts)

### 1. 全套注入测试统一套件契约
- **Test-Scenario A**：冷锋过境概率突变，旧持仓外生隔离与增量凯利前向对冲；单市场 10% 顶限幅；
- **Test-Scenario B**：CLOB 薄盘口深度击穿防御，IOC 限价单自动截断，实际成交均价期望收益 $\overline{\text{EV}} > 0$；残局状态机对冲/止损；
- **Test-Scenario C**：12h 超期未结算仓位移入 Zombie Margin，双轨估值（Sizing 0.0x vs NAV 0.90x），Decimal 定点数截断零撕裂；
- **Test-Scenario D**：METAR 迟到报丢弃、正文与 RMK 气温单调纠偏、跳温 20°F 安全阻断；
- **Test-Scenario E**：统一仲裁中心心跳超时（>30s）0ms 撤单与持仓绝缘。

### 2. 纸面盘事件驱动仿真引擎 (`PaperTradingSimulator`)
- **双模仿真时钟 (`SimulationClock`)**：
  - 支持回放模式（虚拟时间戳手动步进，加速回测）与实时模式（基于系统真实时间戳运行）；
- **全生命周期闭环**：
  1. `on_market_data(station_id, market_id, order_book)`：更新仿真订单簿深度；
  2. `on_weather_observation(station_id, observation)`：单调合流检查与仲裁中枢心跳刷新；
  3. `on_prediction_update(station_id, model_probs, bin_centers)`：气温截断层应用，重算 EV 与各档位增量凯利配比；
  4. `evaluate_and_execute(station_id, market_id, t_remain_hours, current_temp_f)`：两维阶梯风控审查，发单至 CLOB 模拟撮合，四桶资金扣减；
  5. `on_settlement(market_id, actual_temp_f)`：根据结算真值裁定中奖档位，兑付本息，超期 12h 触发 Zombie 转轨。

### 3. 指标核算器与守恒定理 (`SimulationMetricsCalculator`)
- **夏普比率计算**：
  $$\text{Sharpe} = \frac{\mu - r_f}{\sigma + \epsilon} \cdot \sqrt{N}$$
  其中 $\epsilon = 10^{-7}$，当 $\sigma < 10^{-7}$ 时，若均值收益 $>0$ 返回平滑年化夏普，收益为 0 返回 0.0，杜绝除零崩溃。
- **资金守恒恒等式**：
  $$\text{Free USDC} + \text{Active Locked} + \text{Zombie Margin} + \text{Disputed Margin} = \text{Initial Deposit} + \text{Cumulative Realized PnL}$$
- **零非物理下单断言**：
  若某档位在模型截断中概率为 0.0（或低于截断阈值），系统绝不下发针对该档位的买单。

---

## 三、 垂直切片与落地计划 (5 阶段 Tickets)

- **Ticket 01 (`#95`)**: `feat(simulation): 纸面盘事件模型、时钟推进器与仿真账户基石`
  - 产出：`src/simulation/models.py`, `src/simulation/clock.py`
  - 测试：`tests/unit/simulation/test_sim_models_clock.py`
- **Ticket 02 (`#96`)**: `feat(simulation): 纸面盘全链路编排引擎与结算收益核算器`
  - 产出：`src/simulation/paper_engine.py`, `src/simulation/settlement_sim.py`
  - 测试：`tests/unit/simulation/test_paper_engine.py`
- **Ticket 03 (`#97`)**: `feat(metrics): 仿真交易度量器、夏普比率与资金守恒监控`
  - 产出：`src/simulation/metrics.py`
  - 测试：`tests/unit/simulation/test_sim_metrics.py`
- **Ticket 04 (`#98`)**: `test(acceptance): 全套注入测试（Test-Scenario A~E）统一验收门禁与端到端串联`
  - 产出：`tests/integration/test_full_suite_scenarios_a_to_e.py`
- **Ticket 05 (`#99`)**: `feat(runner): Active 10 站 48h 纸面盘仿真运行器 CLI 与全量验证`
  - 产出：`scripts/run_paper_trading.py`, `tests/unit/simulation/test_paper_runner.py`
  - 交付：`data/reports/paper_trading_48h_report.json`

---

## 四、 验收标准与交付门禁 (Acceptance Gates)
1. **统一验收测试 CI 100% 绿灯**：`test_full_suite_scenarios_a_to_e.py` 全通过；
2. **全库回归无损**：`pytest tests/` 800+ 用例全绿；
3. **真实网络冒烟绿灯**：GEFS AWS 真实拉取单条 GRIB 报文通过；
4. **Active 10 站 48h 纸面盘验证**：
   - 零非物理下单；
   - 零滑点穿仓；
   - 模拟资金夏普比率 $> 2.0$；
   - 最大回撤（MDD）$< 15\%$。

---

## Addendum 1: 已对齐 v5.9.2 / 纸面盘工程冒烟与多月量化回测双轨解耦规范 (Issue #100)

### 1. 背景与缺陷归正
在对 Task 07 交付物进行算法 Review 时，发现原 `scripts/run_paper_trading.py` 中存在合成测试打桩（Mock 气温正弦波、写死 65% 概率、盘口 0.40 美元送钱），导致 100% 胜率及年化夏普比率 18.78 的数学失真。为维护量化金融严肃性与科学公信力，实施双轨架构解耦：

### 2. 双轨架构体系 (Dual-Track Architecture)
- **轨一 (Tier 1 - 工程端到端冒烟门禁)**：
  - 专职脚本：`scripts/run_paper_trading.py`
  - 验证目标：48h 多站时钟推进、零非物理下单、四桶 Decimal 资金守恒、异常注入中枢熔断阻断 100%；
  - 门禁断言：坚决剔除非法夏普断言，确立工程稳定性门禁（`zero_non_physical_orders_violated == 0`，`capital_conservation_passed == True`，`final_nav > 0`）；
  - 报告类型：`evaluation_type: "engineering_smoke"`，产出 `data/reports/paper_trading_48h_report.json`。
- **轨二 (Tier 2 - 高保真样本外量化回测门禁)**：
  - 专职模块与脚本：`src/simulation/market_maker.py`, `src/simulation/backtest_engine.py`, `scripts/run_historical_backtest.py`
  - 数据基础：直接驱动 `calib-dataset-v2.0` 2019 年 365 天样本外真实气象数据（覆盖 Active 10 站全天候环境）；
  - 生产模型与截断：动态加载 `data/models/emos/` 200 组生产级高斯 EMOS 模型及 `ConstraintEnforcer` / `TruncatedProbabilityEngine`；
  - 对抗性合成做市商 (`SyntheticMarketMaker`)：以原始未校准 GEFS 集合均值与离散度定价（无 EMOS 纠偏、无物理截断），挂出 Polymarket 真实点差（3~8 美分）与有限深度（100~500 股），坚决杜绝无脑送钱；
  - 真正金融度量：基于日独立收盘结算收益率序列，以 $\sqrt{365}$ 计算年化夏普比率、最大回撤（MDD）、真实胜率与盈亏比；
  - 报告交付：`evaluation_type: "quantitative_backtest"`，产出独立权威报告 `data/reports/historical_backtest_2019_report.json`。

### 3. 修复 Tickets 归档
- **Issue #101 (Fix-01)**: `feat(simulation): 实现对抗性合成做市商模块 (SyntheticMarketMaker)` [CLOSED]
- **Issue #102 (Fix-02)**: `feat(simulation): 实现 2019 合成对抗做市商回测引擎 (HistoricalBacktestEngine, 原高保真称号作废)` [CLOSED]
- **Issue #103 (Fix-03)**: `feat(simulation): 开发全新量化回测 CLI 并完成 2019 全年日结算金融夏普核算` [CLOSED]
- **Issue #104 (Fix-04)**: `refactor(simulation): 重构 48h 纸面盘工程冒烟与更新规范留痕 (Addendum 1 & STATUS)` [CLOSED]
