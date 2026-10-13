# P7-ALGO-2 素材盘点摘要（可用 / 废弃 / 缺失）

> **编制**：技术审核 Agent（量化投资专家 + 算法专家角色）
> **日期**：2026-10-13
> **上游**：`docs/handoffs/2026-10-13-handoff-p7-algo2-design.md`
> **用途**：供 P7-ALGO-2《联合凯利与执行定价算法规格书》design debate 使用；最终并入规格书附录
> **文档性质**：中间设计材料（非最终规格书；最终规格书须经用户确认）

---

## 一、通读范围声明

已完成全量通读（按 Handoff §四 清单，无遗漏）：

- **9 份算法/交易文档**：判决书 P7-ALGO-VERDICT v0.2 ✅、凯利溯源卷宗 P7-ALGO-1 ✅、方案 v2.8 ✅、参数标定方案 v1.0 ✅、v1 旧策略（WEP v2.1）✅、legacy 标定说明 v1.0.0 ✅、legacy README_V1_ORIGINAL ✅、legacy baseline_sigma 优化提案 ✅、归档 README ✅
- **6 份关联 ADR**：ADR-0011 / 0012 / 0013 / 0014 / 0015 / 0018 ✅
- **归档交易代码**：src 现存 16 个源文件全部审读（risk 6、pricing 1 + `__init__`、simulation 8）；tests 现存 20 个中 bankroll 4 + execution 4 精读（源文件缺失模块的行为契约来源）；scripts 5 个结构扫描；`src/simulation/` 其余文件经类/函数签名扫描 + 关键模块精读
- **缺陷登记**：归档区 src/bankroll 与 src/execution 共 11 个源文件物理缺失（详见 §四.1）；本机目录为 Synology 同步副本、无 `.git`，git 历史不可用

---

## 二、可用素材（设计输入，进入规格书）

| # | 素材 | 可用内容 | 进入规格书的用途 |
| :--- | :--- | :--- | :--- |
| 1 | **判决书 v0.2** | M-1~M-8 判词（M-2 已裁、M-3~M-5 挂起、M-6 倾向废弃、M-7 废弃清单）；F-2 优先律（硬前置）；C 类三案台账对应 | 立法输入：每条机制处置（移植/保留/废弃/改造）以此为据；判词签署权归用户 |
| 2 | **凯利溯源卷宗 P7-ALGO-1** | v1 strategy.py Minimax 逐行摘录（不确定集构造、贪心投影、SLSQP 外层）；v2 退化事实；v1 config.yaml 参数现值全表（M-8 归档对象）；5 项未决事项 | 事实层：M-1 移植的代码形态依据；M-8"数值不继承"的对象清单；未决事项登记 |
| 3 | **方案 v2.8** | §1 核心目标（物理优势→USDC 复利）；§6 模块五（四桶资金、多项联合凯利增量对冲、IOC 保护价、两维阶梯风控）；§3.3 物理硬约束（p_i=0 乘法侧归零、禁预计算 ln(p)）；§4 ECE≤0.0100 门禁与挂旗治理；960 模型矩阵、2000–2018 训练窗、2019 盲测 | **算法目的提取源**（用户确认 v2.8 为现行最新版）；§6 即规格书目标函数的宪法出处 |
| 4 | **参数标定方案 v1.0** | 两步标定法（Brier σ → 反事实 sizing θ/η）；选择性偏差分析（决策时间戳池缺陷）；prob_cache 两阶段网格架构；诚实局限（3 天样本、方向正确性假设、时序分割）；Roadmap（时变 θ(t)、市场隐含 σ） | M-5 框架复用输入；F-2 挂锁后的标定设计基线；局限条目进入规格书"标定前置条件" |
| 5 | **ADR-0011** | 双源单调合流（IEM 主力 + WRH 影子）；TMAX/TMIN 对称截断；两维阶梯风控（15m 心跳 / 35m 硬熔断 / CancelAll）；截断单向永久锁定；迟滞恢复 | 执行层门禁宪法：φ=1.3 管辖源（M-7）；风控与截断联动接口 |
| 6 | **ADR-0012** | NWS WRH 唯一法定结算真值；四桶资金恒等式；双轨估值（sizing 0.0x 剔除 / NAV 90% 折价）；R_z 阶梯熔断（15%/30%/50%）；Decimal ROUND_HALF_UP 舍入 | bankroll 规格宪法；僵尸仓位双轨口径 |
| 7 | **ADR-0013** | 三道纯温门禁（气候极值域 / 正文-RMK 1.8°F / 单步 15°F）；迟到不投；三步 Fail-Closed 熔断；已成交持仓绝缘 | 截断层→执行层联动（M-6 覆盖性验证对象） |
| 8 | **ADR-0014** | 控制面/数据面分离；30s 自愈预算；预购双硬门禁（7min 新鲜度 + 连通）；本地硬关阀零发射定理；二元仲裁（INVALIDATED / SUSPENDED）；已成交绝缘 + 结算前 30min 逃生后门 | 执行前门禁宪法；异常→订单链路的全部门禁不等式来源 |
| 9 | **ADR-0015** | 方差公式 σ² = c² + d²·S_ens²（废除加法项）；σ_inst=0.9°F 物理底座；PIT KS / 加权 ECE≤3% 主门禁 | 概率层门禁（F-2 优先律的绿灯判定依据之一） |
| 10 | **ADR-0018** | 分层门禁（Screening 单折 vs Binding 池化）；20 折复合误杀 61.65% 实证；fold_04 单列终裁 | 概率层验收口径（F-2 绿灯的判定层级） |
| 11 | **v1 旧策略 WEP v2.1** | 动态费率数学（FeeRate=base·(1−p)、绝对费用对称 S·base·p(1−p)）；Dutch Book 判定式（Σ_taker_eff<0.98）；Reverse Lock-in；Noise Floor（Maker 3.5% / Taker 5.0%）；边界安全边际 | M-2/M-3 第一性原理素材：费率项与 Dutch Book 判定式的数学起点 |
| 12 | **legacy 标定说明 v1.0.0** | 稳健凯利公式形态 f* = clamp(θ·(p·b−(1−p))/b · e^(−η·StdDev), 0, f_max)；σ/θ/η 网格（36 组）；反事实决策点规则 | M-1/M-5 公式形态参照（v2 将改写为 EMOS 闭式 CDF 语境） |
| 13 | **legacy README_V1_ORIGINAL** | 契约优先架构；γ_ev 立方衰减、γ_σ 噪声缩水、增量调仓 worth-it 过滤、偏离度预警 | v1 机制全景（多数被 M-7 废弃，仅作考古） |
| 14 | **legacy baseline_sigma 提案** | 临近结算 baseline_sigma 线性衰减公式 Baseline(t) | v1 曾用机制；v2 由 EMOS σ(L) 承担（M-7），参照不继承 |
| 15 | **归档 README** | 归档定位（禁止 import）；例外保留清单；恢复指引（不原样回迁） | 重建边界：规格书基于归档代码审读，不做原样回迁 |

---

## 三、废弃 / 被裁决替代素材（不进入规格书本体，仅记录依据）

| # | 机制 | 处置依据 |
| :--- | :--- | :--- |
| 1 | 阶梯投注表 1U/3U/6U/10U | M-7：代码从未实现，纯文档遗留 |
| 2 | 四阶段时间策略 Phase Ⅰ~Ⅳ | M-7：代码无状态机 |
| 3 | Sigmoid 时间衰减（k=0.30, tc=24h） | M-7：由 EMOS σ(L) 承担 |
| 4 | φ=1.3 决战 Edge 放大 | M-7：废弃；临盘管辖归 ADR-0011 两维风控 |
| 5 | CHSM 蒙特卡洛（ρ=0.85） | M-6：倾向废弃，等 ADR-0013 截断层覆盖性验证后落笔 |
| 6 | 胜率向市场收缩 Shrinkage（C-1） | M-4：废弃（已解锁） |
| 7 | 气候方差加法项 σ²_clim | ADR-0015：废除（违背校准不等式） |
| 8 | BH 多重假设检验条款 | ADR-0015：废除 |
| 9 | Wunderground 结算职责 | ADR-0012：解除，物理隔离 |
| 10 | 名义极值前 2h 切源状态机 | ADR-0011：废除 |
| 11 | 陈旧 45min 硬编码阈值 + 降级放大 σ×1.3 | ADR-0011：废除（改为 15m/35m 两维） |
| 12 | v1 三层资金池（Deployed/Hedge/Reserve） | 卷宗 2.2：v2 已改四桶状态机 |
| 13 | v1 全部金融参数数值直接继承 | M-8：禁止，任何数值须走两步标定或 v2 宪法推导 |
| 14 | Wunderground 抓取、DEHO、华氏 floor 取整 | M-7：已死组件 |

---

## 四、缺失 / 缺口（重大，须在规格书中显式声明）

### 4.1 【重大】归档区 bankroll / execution 源文件物理缺失

- **事实**：`docs/archive/trading_modules/src/bankroll/` 与 `src/execution/` 目录存在但**为空**。归档 README 声称归档 src 共 27 个文件，物理实存 16 个（risk 6 + pricing 2 + simulation 8），**缺 11 个**：
  - `bankroll/`：`bankroll_manager.py`、`multinomial_kelly.py`、`risk_limiter.py`、`zombie_evaluator.py`、`__init__.py`
  - `execution/`：`clob_client.py`、`execution_engine.py`、`models.py`、`order_router.py`、`residual_risk.py`、`__init__.py`
- **佐证**：全项目 Glob 无 `multinomial_kelly.py` / `execution_engine.py` 任何副本；tests 8 个存在；本机无 `.git`（Synology 同步副本），git 历史不可用。
- **影响**：上述 5 个模块正是 P7-ALGO-2 的核心对象（多项凯利优化器、四桶资金、风险限制器、僵尸估值、执行引擎、订单路由、CLOB 客户端、保护价、残差风险）。规格书只能基于 **tests 行为契约 + 判决书/卷宗代码摘录 + paper_engine 调用关系** 反推接口与语义，**无法逐行审读源实现**。
- **处置建议**：① 从真实 git 仓库（或用户 Mac 侧原仓库）恢复 11 个源文件补入归档区后，再做逐行审读；② 若不可行，规格书以 tests 契约为**最低接口约束**重建定义，并在规格书中显式标注"接口自契约反推，未经源码逐行核验"。
- **补充**：`src/pricing/paper_evaluation_engine.py` 与 `w3_offline_replay_analyzer.py` 仅存 `__pycache__` 编译痕迹（.pyc），源文件不在归档区且不在 README 归档清单内——W2 纸面盘评估链路（真实 EMOS + 动态截断 + 体检门禁串联）的现役实现不可得，规格书验证层设计只能参照归档的 `paper_engine.py`（旧版事件驱动仿真）。

### 4.2 v1 核心策略代码库外未检入

- `strategy.py`、`calibrator.py`、`config/config.yaml`、`scratch/calibrate_financial_params.py` 完整实现保存在外部目录（`Polymarket天气套利/`），本仓库零检入。判决书与卷宗含关键逐行摘录，但**完整实现不可得**。规格书不依赖其全文，仅引用已摘录公式与事实。

### 4.3 M-2 对外核实待办

- base=0.0125 与 Maker 返佣 0.20 的**现行有效性**需对外核实一次（Polymarket 现行费率规则是否仍与 2026-07 时点一致）后 M-2 才闭环。规格书费率模块以 `q = p·[1+base·(1−p)]` 为已裁公式，参数标注"待核实"。

### 4.4 F-2 概率层绿灯未亮

- 概率层 ECE/CRPSS 门禁未绿灯（含 ADR-0015 / ADR-0018 口径）。规格书结构可写，**凯利标定与 sizing 调优挂锁**（F-2 优先律）。

---

## 五、归档代码审读结果：模块清单与契约

> 标注 **[源缺失]** 的模块接口由 tests 契约 + paper_engine/execution_engine 调用关系反推。

### 5.1 bankroll（4 模块，源缺失）

| 模块 | 职责 | 关键接口 / 契约 |
| :--- | :--- | :--- |
| `multinomial_kelly.py` **[源缺失]** | 多项凯利 SLSQP 点估计增量对冲求解 | `MultinomialKellyOptimizer.optimize(probabilities, prices, w_free, max_allocable, existing_payouts=None)` → `KellyAllocationResult(success, optimal_allocations, total_allocation)`；正 EV 分配 / 负 EV 归零 / 概率翻转自然转向（不市价抛旧仓）/ 非法输入 fail-closed 归零 |
| `bankroll_manager.py` **[源缺失]** | 四桶资金状态机 + Decimal 6 位截断 | `Total = Free + Active + Zombie + Disputed`；`lock_funds / unlock_funds / withdraw / settle_position(original_locked, payout) / transfer_to_zombie / transfer_to_disputed / get_effective_bankroll()`（Free+Active，0.0x 剔除） |
| `risk_limiter.py` **[源缺失]** | 仓位硬门禁限制器 | `RiskLimiter(RiskLimiterConfig(fractional_multiplier, single_market_cap_ratio=0.10, global_utilization_cap_ratio=0.70)).apply_limits(market_id, raw_allocations, current_market_exposure, bankroll_manager, liquidity_tier)` → `RiskLimitResult(is_approved, total_approved, approved_allocations, is_throttled, throttle_reason)`；单市场 10% 硬顶按比例缩水、全局 70%、僵尸分级折价（WARNING 0.5x / HALT 0.0x / SAFE_MODE 0.0x）、Free 不足截断 |
| `zombie_evaluator.py` **[源缺失]** | 僵尸仓位双轨估值 + 流动性分级断路器 | `ZombieEvaluator(bankroll_manager, ZombieEvaluatorConfig(grace_period_hours=12.0, zombie_haircut=0.10, tier_haircut_threshold=0.15, tier_halt_threshold=0.30, tier_safe_mode_threshold=0.50))`；`register_position / evaluate_positions / calculate_financial_nav / evaluate_liquidity_tier`；R_z≤15% HEALTHY(1.0x) / ≤30% WARNING(0.5x) / ≤50% HALT(0.0x) / >50% SAFE_MODE(0.0x) |

### 5.2 execution（5 模块，源缺失）

| 模块 | 职责 | 关键接口 / 契约 |
| :--- | :--- | :--- |
| `models.py` **[源缺失]** | CLOB 订单模型 + 校验 | `CLOBOrder.create_buy_ioc(...)`；**MARKET 单严格禁止**（`MarketOrderForbiddenError`）；Decimal 精度钳制（price 4 位、size 6 位 ROUND_DOWN）；station 必须属 ACTIVE_10；`OrderType(IOC/GTC/MARKET)`、`OrderSide`、`OrderStatus`、`FillEvent`、`OrderPlacementResult` |
| `clob_client.py` **[源缺失]** | CLOB 客户端接口（Mock 撮合） | `CLOBSigner`（确定性签名 65 字节 hex）、`CLOBClientInterface`、`MockCLOBClient`（`set_orderbook / get_orderbook / place_order` VWAP 撮合、`cancel_all_orders(station_id)`） |
| `execution_engine.py` **[源缺失]** | 执行编排（两维风控 + IOC 路由 + 残差） | `CLOBExecutionEngine(clob_client, bankroll_manager, arbiter, hard_valve, risk_controller, min_edge).execute_strategy(station_id, market_id, allocations, model_probs, bin_labels, t_remain_hours, current_temp_f, bin_centers)` → `EngineExecutionResult(executed, blocked_reason, risk_regime, committed_cost, orders)`；SUSPENDED 阻断；CRITICAL 0.2x 折仓 |
| `order_router.py` **[源缺失]** | EV 零点保护价 + IOC 限价路由 | `calculate_protection_price(model_prob, asks, min_edge)` → `ProtectionPriceResult(is_tradable, protection_price, safe_capacity)`；遍历 ask 档锁定**最后一个正 EV 档**为保护价，safe_capacity=累计正 EV 深度；`OrderRouter.route_allocations(...)` 生成 IOC，未成交解锁资金 |
| `residual_risk.py` **[源缺失]** | 非原子单残差评估 + 愈合状态机 | `ResidualRiskEvaluator.evaluate(station_id, market_id, fills, model_probs, total_cost)` → `is_exposed, expected_pnl, max_loss`；`ResidualRiskStateMachine`（CLEAN / RESOLVED_BALANCED / LIQUIDATED；rehedge 或止损） |

### 5.3 pricing（ev_engine.py 在档，已精读）

| 模块 | 职责 | 关键公式 / 契约 |
| :--- | :--- | :--- |
| `ev_engine.py` | 动态微观 EV 引擎 + 盘口深度穿透 | `DynamicEVEngine.evaluate_bin(snapshot, model_probability, target_size, is_failsafe, is_flagged)`：`net_ev = p_model·(1−fee_rate) − p_eff`；`edge = net_ev / p_eff`；VWAP 深度穿透（`calculate_effective_price`）；`EVConfig(min_reprice_edge=0.03, fee_rate=0.0)`；FAILSAFE 只读降级、FLAGGED 0.5x 缩仓；`OrderBookLevel/OrderBookSnapshot/EVTradeSignal` |

### 5.4 risk（6 模块在档，已精读）

| 模块 | 职责 | 关键契约 |
| :--- | :--- | :--- |
| `two_dimensional_risk.py` | 两维阶梯风控（ADR-0011） | `evaluate_regime(t_remain_hours, delta_temp_f)`：CRITICAL（T_rem<1.0h 且 ΔT>3.0°F → 0.20x，禁反向=False）；CERTAIN（T_rem<0.5h 且 ΔT≤0.5°F → 1.00x，禁反向=True）；NORMAL（1.00x） |
| `pre_buy_gate.py` | 预购门 + 本地硬阀 + 持仓绝缘（ADR-0014） | `PreBuyGateKeeper.verify_pre_buy(intent, latest_observation_time, data_stream_connected, gateway_connected, current_wall_time)`：连通门 → ACTIVE 门 → 7min 新鲜度门；`LocalHardValve`（零发射定理，close→cancel_all 联动）；`PositionInsulationPolicy`（异常态禁市价抛售；结算前 30min 转逃生后门） |
| `central_arbiter.py` | 中央异常仲裁 + 台站生命周期（ADR-0014） | `StationLifeCycleState(ACTIVE/SUSPENDED/INVALIDATED/EMERGENCY_HALT)`；二元仲裁（CORRUPTED/SANITY_BREACH/COR_CONFLICT→INVALIDATED 至 EoD；DEGRADED/DATA_STALENESS/EXCHANGE_DOWN/RETRY_BUDGET_EXHAUSTED→SUSPENDED，超 3 次衰变 INVALIDATED）；冷却 + 3 连续健康帧恢复；30s 重试预算升级；当地午夜自动复位 |
| `incident_protocol.py` | 统一 Incident 契约 + 事件总线 | `IncidentSubsystem(INGESTION/TRUNCATION/PRICING/EXECUTION/SETTLEMENT)`、`IncidentSeverity(DEGRADED/CORRUPTED/PANIC)`、`IncidentReasonCode(SANITY_BREACH/DATA_STALENESS/COR_CONFLICT/EXCHANGE_DOWN/MANUAL_EMERGENCY_STOP/RETRY_BUDGET_EXHAUSTED)`；`IncidentReport.create / from_dict / to_dict`；`IncidentBus`（subscribe/publish/history） |
| `emergency_control.py` | 本地拔网线哨兵 | `EmergencyFileSentinel`：`EMERGENCY_STOP_<STATION>` 文件探测（create/remove/list/check）→ 单站/全局硬停机 |
| `cli.py` | 命令行入口 | `run_cli(args)` |

### 5.5 simulation（8 模块在档）

| 模块 | 职责 | 关键契约 |
| :--- | :--- | :--- |
| `paper_engine.py` | 纸面盘事件驱动全链路仿真 | `PaperTradingSimulator.evaluate_and_execute(station_id, market_id, model_probs, bin_labels, bin_centers, t_remain_hours, current_temp_f)`：7 步闭环（Arbiter 预检 → 取盘口 best_ask → 提取旧持仓 payout → 多项凯利 → RiskLimiter → 执行引擎 → 记账）；`PaperSimulationConfig(fractional_multiplier=0.5 半凯利, single_market_cap_ratio=0.10, global_utilization_cap_ratio=0.70, min_edge=0.02, auto_rehedge=True)`；零非物理订单定理（p≤0 或价≥1 强制归零） |
| `backtest_engine.py` | 历史对抗回测 | `HistoricalBacktestEngine.run_backtest(...)` → `BacktestReport`（含 `DailyPerformanceRecord`）；2019 独立盲测年（卷宗/方案 v2.8 语境） |
| `market_maker.py` | 合成做市（naive 对手盘） | `SyntheticMarketMaker.compute_naive_probabilities(bins, ensemble_mean, ensemble_variance, observed_temp_f)`：未校准高斯（min_naive_std=2.5°F，日内 nudge w=0.3）；`generate_order_book`：3 层深度（150/250/400 股），半价差 2.5 分（总价差 3~8 分） |
| `settlement_sim.py` | 结算模拟（12h 僵尸 + 逾期） | `SettlementSimulator(bankroll_manager).settle_market(market_id, winning_bin_index, positions) / handle_overdue_market` |
| `clock.py` | 仿真时钟 | `SimulationClock(mode)`：`now / advance / set_time` |
| `metrics.py` | 仿真指标 | `SimulationMetricsCalculator`：`compute_max_drawdown / compute_sharpe_ratio / verify_capital_conservation / generate_report` |
| `models.py` | 仿真数据模型 | `PaperPosition / PaperTradeRecord / SimulationEvent / SimulatedOrderBook`（`simulate_buy_ioc`） |

### 5.6 scripts（5 个，运行入口）

`run_paper_trading.py`（PaperRunnerConfig + run_simulation）、`run_historical_backtest.py`、`run_p7_w2_shortloop_paper_simulation.py`（含断裂引用，仅考古）、`run_p7_w2b_48h_observation.py`（48h 观测实验 + ObservationMetrics）、`audit_p7_w2_shortloop.py`（六门禁 C1~C6 审计 + Markdown 报告）。

---

## 六、关键公式契约摘录（规格书数学章节的既有锚点）

1. **动态费率（M-2 已裁）**：有效成本 `q = p·[1 + base·(1−p)]`，base=0.0125（参数对外核实待办）。
2. **v2 净 EV（ev_engine 在档）**：`net_ev = p_model·(1 − fee_rate) − p_eff`，`edge = net_ev / p_eff`；fee_rate 现为 0.0（卷宗未决事项 2：低价档负 EV 隐患，规格书须纳入动态费率）。
3. **v1 稳健凯利 Minimax（M-1 移植对象）**：不确定集 `p_L = max(0, p − θ·se)`、`p_U = min(1, p + θ·se)`，`se_model = η·√(p(1−p))`；贪心投影最小化 `Σ p_k·ln(W_k)`；外层 SLSQP。v2 移植须改：se 来源 = EMOS 闭式 CDF 分布参数。
4. **多项凯利增量对冲（v2 在役契约）**：SLSQP 最大化对数财富增量，旧持仓 `existing_payouts` 外生注入，`max_allocable` 约束，只买不卖。
5. **保护价（order_router 契约）**：锁定最后一个 `edge ≥ min_edge` 的 ask 档价格为 IOC 保护价；`safe_capacity` = 累计正 EV 档深度。
6. **两维风控（ADR-0011 / two_dimensional_risk）**：CRITICAL `T_rem<1h ∧ ΔT>3°F → 0.20x`；CERTAIN `T_rem<0.5h ∧ ΔT≤0.5°F → 禁反向投机`。
7. **预购门（ADR-0014 / pre_buy_gate）**：`Δage ≤ 7min` + 数据/网关连通 + 台站 ACTIVE + 本地阀开。
8. **僵尸双轨（ADR-0012 / zombie_evaluator）**：12h 触发；sizing 母数 0.0x；NAV 90% 折价；R_z 15/30/50 阶梯。
9. **四桶与硬顶（ADR-0012 / risk_limiter）**：`Bankroll_eff = Free + Active`；单市场 10%；全局利用率 70%。
10. **概率层门禁（ADR-0015/0018）**：Binding 池化 `ECE ≤ 0.05`（方案 v2.8 交易窗口加权 `ECE ≤ 0.0100` 为更高口径，两者层级不同须在规格书澄清）、Wilson ≥90%、KS ≤0.08、BSS>0。

---

## 七、对 P7-ALGO-2 设计的输入映射（盘点结论）

| 规格书章节 | 设计输入 | 挂锁 / 前置 |
| :--- | :--- | :--- |
| 算法目的 | 方案 v2.8 §1 + §6（宪法级描述）；ADR-0011~0014 架构 | — |
| Kelly 公式形态（M-1） | 判决书 M-1 判词 + 卷宗 4.1 Minimax 摘录 + legacy 公式形态；**不确定集 std_errors 改为 EMOS 闭式 CDF 参数派生** | θ/η 不继承（挂 F-2 锁）；标定须走两步标定法（M-5 框架） |
| 费率模型（M-2） | `q = p·[1+base·(1−p)]` 已裁；Maker 返佣 0.20 | base/返佣对外核实待办（M-2 闭环项） |
| Dutch Book + 豁免（M-3） | v1 WEP §6 判定式 + ADR-0014 中枢登记 + 四桶账务 | C-2 挂起=方案语境解锁；现实盘口深度约束（微观结构报告 $300~2500/档） |
| sizing / 风险限制（F-2 管辖） | risk_limiter / zombie_evaluator 契约；ADR-0012 双轨 | **标定与 sizing 调优挂 F-2 锁（概率层绿灯前不得开工）** |
| 执行定价（保护价 / IOC） | order_router / execution_engine 契约；ADR-0014 预购门；ADR-0011 两维风控 | 动态费率并入 EV 判定（卷宗未决事项 2 修复方向） |
| 门禁不等式 | ADR-0015/0018 概率门禁 + 方案 v2.8 ECE≤0.0100 + 预购门不等式 + 两维风控不等式 | F-2 绿灯判定口径需在规格书显式定义（分层：Screening/Binding/交易窗口） |
| 验证机制 | paper_engine（半凯利 0.5、2% min_edge）/ backtest_engine / market_maker naive 对手盘 | 标定数据须等纸面盘自产（M-5）；2019 盲测年 Airgap |

**盘点声明**：本摘要全部条目基于上表通读范围的客观事实；§四.1 缺失登记为归档物理现状（空目录 + 无副本 + 无 git），建议处置方案（恢复源文件 / 契约反推标注）需用户或开发端 Agent 确认后执行。
