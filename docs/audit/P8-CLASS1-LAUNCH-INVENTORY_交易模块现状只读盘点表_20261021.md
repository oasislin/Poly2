# P8-CLASS1-LAUNCH-INVENTORY · 交易与风控模块现状只读盘点表

> **工单（B 线）**：`P8-CLASS1-LAUNCH`（治理批次 8）  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-01`  
> **编制角色**：开发组 Agent  
> **基准代码库状态**：`main` @ `f187881`（原基线 `e421ac8` 已完成 handoff 与核验单提交；工作树无未跟踪代码；未 push）  
> **盘点性质**：只读静态盘点，严禁把归档模块 import 进现役路径，严禁凭假设推断。

---

## 一、 盘点背景与主树状态确认（Step 0 回执）

### 1.1 主树实际状态实测
在 `main` 树上实测执行 `ls -la src/bankroll src/execution src/risk 2>&1`，原始观测值：
- `src/bankroll`: No such file or directory
- `src/execution`: No such file or directory
- `src/risk`: 仅存在 `__init__.py` 与 `stream_watchdog.py`（及 `__pycache__`）

**两步判定**：
- 原始观测值：主树不存在 `src/bankroll/`、`src/execution/`，`src/risk/` 中除 `stream_watchdog.py` 外无任何交易风控模块；
- 判定阈值：与 R-16 方案 B（DECISION_LEDGER §五 R-16；`R16_TRADING_MODULE_ARCHIVE_BRIEF.md`）要求一致；
- 结论：**通过**（完全符合 R-16 归档状态，无任何冲突，盘点对象转入隔离归档区）。

### 1.2 测试运行状态实测
1. **现役测试**：
   - 执行：`python3 -m pytest tests/unit/prediction tests/unit/risk -q`
   - 结果：`113 passed in 2.33s`（退出码 0，全绿）。
2. **归档测试**：
   - 执行：`python3 -m pytest docs/archive/trading_modules/tests/ -q --collect-only`
   - 结果：20 个测试模块因引用的 `src.bankroll` / `src.execution` / `src.pricing` / `src.simulation` 已归档，收集期报 `ModuleNotFoundError`（退出码 2）。
   - 结论：符合物理归档隔离设计，归档资产未污染现役运行时。

---

## 二、 归档资产逐模块盘点表（Step 1 交付）

### 2.1 资金与配资模块（`docs/archive/trading_modules/src/bankroll/`）

| 模块路径 | 关键类 / 函数签名 | 核心功能 | 内部与外部依赖 | 配套测试路径与状态 | 重建/复用建议（待 P7-ALGO-2） |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `bankroll_manager.py` | `BankrollManager`: <br>• `get_balance(bucket)`<br>• `get_effective_bankroll()`<br>• `lock_funds(...)`<br>• `unlock_funds(...)`<br>• `settle_position(...)`<br>• `get_utilization_ratio()`<br>`to_usdc_decimal(val)` | 管理 Free / Active / Zombie / Disputed 四桶资金，核算可运作资金与全局资金利用率 | `decimal.Decimal`, `dataclasses`, `threading`, `logging` | `tests/bankroll/test_bankroll_manager.py`<br>(类: `TestBankrollManager`，13 个测试点；归档中) | **核心复用**：四桶资金划分和资金守恒机制是 v2 宪法基础；需按 DR-2026-1014-03 明确 $B_{\text{eff}}=\text{Free}+\text{Active}$。 |
| `multinomial_kelly.py` | `MultinomialKellyOptimizer`: <br>• `optimize(probs, prices, bankroll, ...)`<br>`MultinomialKellyConfig`<br>`KellyAllocationResult` | 多项凯利优化器，基于 SLSQP 求解互斥多档位的最优下注份额 $f^*$，最大化对数增长率期望 | `scipy.optimize.minimize`, `numpy`, `dataclasses`, `logging` | `tests/bankroll/test_multinomial_kelly.py`<br>(类: `TestMultinomialKellyOptimizer`，7 个测试点；归档中) | **结构重构**：当前为点估计多项凯利。按判决书 M-1 改为基于 EMOS 闭式 CDF 的稳健凯利结构，$\theta/\eta$ 标定挂 F-2 锁；折剪并入 $C_{\max}$（DR-2026-1014-02）。 |
| `risk_limiter.py` | `RiskLimiter`: <br>• `apply_limits(allocations, bankroll_manager, ...)`<br>`RiskLimiterConfig`<br>`RiskLimitResult` | 实施单市场硬顶（10% $B_{\text{eff}}$）、单档位硬顶（2.5% $B_{\text{eff}}$）与全局利用率上限（70%）门禁 | `src.bankroll.bankroll_manager`, `src.bankroll.zombie_evaluator`, `decimal.Decimal` | `tests/bankroll/test_risk_limiter.py`<br>(类: `TestRiskLimiter`，6 个测试点；归档中) | **调整对账**：按 DR-2026-1014-02，风控折剪前置并入 S2 预算公式，本模块转化为纯布尔放行与硬顶截断。 |
| `zombie_evaluator.py` | `ZombieEvaluator`: <br>• `register_position(...)`<br>• `get_zombie_trigger_utc(...)`<br>• `evaluate_positions(...)`<br>• `evaluate_liquidity_tier(...)` | 跟踪持仓时效，在结算日后 T+2 日上午自动触发僵尸资金标记并划转至 Zombie 桶 | `zoneinfo.ZoneInfo`, `src.bankroll.bankroll_manager`, `src.data_processing.constants` | `tests/bankroll/test_zombie_evaluator.py`<br>(类: `TestZombieEvaluator`，5 个测试点；归档中) | **完全复用**：时区感知与资金隔离逻辑完整健壮，重建时直接吸纳入资金管辖。 |

---

### 2.2 交易执行模块（`docs/archive/trading_modules/src/execution/`）

| 模块路径 | 关键类 / 函数签名 | 核心功能 | 内部与外部依赖 | 配套测试路径与状态 | 重建/复用建议（待 P7-ALGO-2） |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `models.py` | `CLOBOrder`, `FillEvent`, `OrderStatus`, `OrderType`, `OrderSide`, `MarketOrderForbiddenError` | CLOB 交易数据结构，强制采用 IOC 限价单，严防市价单穿透 | `decimal.Decimal`, `dataclasses`, `uuid`, `src.data_processing.constants` | `tests/execution/test_clob_models_client.py`<br>(类: `TestCLOBModels`，8 个测试点；归档中) | **完全复用**：全链路 Decimal 与枚举定义完备，天然支持只买不卖与 IOC。 |
| `clob_client.py` | `CLOBClientInterface`<br>`CLOBSigner`: `sign_order(...)`<br>`MockCLOBClient`: <br>• `set_orderbook(...)`<br>• `place_order(...)`<br>• `get_orderbook(...)` | CLOB 交互抽象接口、EIP-712 签名器及离线测试 Mock 客户端 | `hashlib`, `src.execution.models`, `src.pricing.ev_engine` | `tests/execution/test_clob_models_client.py`<br>(类: `TestCLOBSigner`, `TestMockCLOBClient`；归档中) | **按需复用**：`MockCLOBClient` 可作为纸面盘与单元测试核心构件；真实 CLOB 连接留待生产配置。 |
| `order_router.py` | `OrderRouter`: <br>• `route_allocations(...)`<br>`calculate_protection_price(model_prob, asks, min_edge)` | 逐档计算滑点保护价 $\bar{P}$ 与有效成本，生成保护价 IOC 指令 | `src.execution.clob_client`, `src.execution.models`, `src.pricing.ev_engine`, `src.bankroll.bankroll_manager` | `tests/execution/test_order_router.py`<br>(类: `TestProtectionPriceCalculation`, `TestOrderRouter`；归档中) | **对账复用**：按 DR-2026-1014-01，S1 定价探针规模由 min_edge 达标深度确定，与本模块算法自洽。 |
| `residual_risk.py` | `ResidualRiskEvaluator`<br>`ResidualRiskStateMachine`: <br>• `handle_execution_result(...)`<br>• `_attempt_rehedge(...)`<br>• `_execute_hard_stop_loss(...)` | 处理 IOC 部分成交后的残差风险，包含补单、反向对冲与硬止损状态机 | `src.execution.order_router`, `src.execution.clob_client`, `src.bankroll.bankroll_manager` | `tests/execution/test_residual_risk.py`<br>(类: `TestResidualRiskEvaluator`, `TestResidualRiskStateMachine`；归档中) | **精简复用**：只买不卖原则下，移除对冲/卖出逻辑，按 P7-ALGO-2 残差场景聚焦补单与预算释放。 |
| `execution_engine.py` | `CLOBExecutionEngine`: <br>• `execute_strategy(...)`<br>• `emergency_cancel_all()` | 串联风控门禁、配资求解、订单路由与残差处理的总执行引擎 | 依赖 bankroll/execution/risk 各子模块 | `tests/execution/test_execution_engine.py`<br>(类: `TestCLOBExecutionEngine`；归档中) | **流水线重构**：作为 S1→S5 执行流水线骨架重新整合。 |

---

### 2.3 风控仲裁模块（`docs/archive/trading_modules/src/risk/`）

| 模块路径 | 关键类 / 函数签名 | 核心功能 | 内部与外部依赖 | 配套测试路径与状态 | 重建/复用建议（待 P7-ALGO-2） |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `central_arbiter.py` | `CentralExceptionArbiter`: <br>• `is_station_tradable(...)`<br>• `check_calendar_rollover(...)`<br>• `handle_incident(...)` | 站点生命周期状态机、跨日冻结、观测流断流仲裁 | `src.risk.incident_protocol`, `src.data_processing.constants`, `zoneinfo` | `tests/risk/test_central_arbiter.py`<br>(类: `TestCentralArbiter`；归档中) | **核心复用**：跨日自然日历滚动与交易准入仲裁是统一中枢核心。 |
| `emergency_control.py` | `EmergencyFileSentinel`: <br>• `create_sentinel(...)`<br>• `remove_sentinel(...)`<br>• `is_emergency_halt()` | 基于文件系统的“紧急拔网线”物理熔断机制（分站点/全局） | `pathlib.Path`, `src.data_processing.constants` | `tests/risk/test_emergency_control.py`<br>(类: `TestEmergencyControl`；归档中) | **完全复用**：非侵入式最高优先级硬熔断机制。 |
| `cli.py` | `run_cli()` | 紧急拔网线命令行运维工具 | `argparse`, `src.risk.emergency_control` | 手工运维验证（无独立单元测试） | 运维辅助保留。 |
| `incident_protocol.py` | `IncidentProtocolManager`: <br>• `report_incident(...)`<br>• `resolve_incident(...)` | 事故分级响应（INFO/WARNING/CRITICAL/FATAL）与降级记录 | `dataclasses`, `enum`, `logging` | `tests/risk/test_incident_protocol.py`<br>(类: `TestIncidentProtocol`；归档中) | 保留为日志审计与告警事件总线。 |
| `pre_buy_gate.py` | `PreBuyGate`: <br>• `evaluate_all_gates(...)`<br>`GateCheckResult` | 下单前门禁体系（流动性、点差、气象突变、风控状态等） | 依赖 bankroll/execution/pricing/risk | `tests/risk/test_pre_buy_gate.py`<br>(类: `TestPreBuyGate`；归档中) | **改版为 S3 纯布尔门禁**：按 DR-2026-1014-02，门禁只做布尔放行，不作物料乘法折剪。 |
| `two_dimensional_risk.py`| `TwoDimensionalRiskController`: <br>• `evaluate_regime(delta_t, t_remaining)` | 基于时效剩余 $T_{\text{rem}}$ 与残差 $\Delta T$ 的两维阶梯风控 | `dataclasses`, `decimal.Decimal`, `enum` | `tests/execution/test_execution_engine.py`<br>(类: `TestTwoDimensionalRiskController`；归档中) | **按 DR-2026-1014-04 改造**：残差阈值改为标准化残差 $z = \|\Delta T\| / \sigma_{\text{EMOS}}$，消解温标差异。 |

---

### 2.4 定价与仿真模块（`docs/archive/trading_modules/src/{pricing,simulation}/`）

| 模块路径 | 关键类 / 函数签名 | 核心功能 | 内部与外部依赖 | 配套测试路径与状态 | 重建/复用建议（待 P7-ALGO-2） |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ev_engine.py` | `DynamicEVEngine`: <br>• `calculate_effective_price(...)`<br>• `evaluate_bin(...)`<br>`OrderBookSnapshot` | 计入 Polymarket 动态费率公式 $q = p[1+\text{base}\cdot(1-p)]$ 的真实预期价值（EV）计算 | `dataclasses`, `logging`, `typing` | `tests/pricing/test_ev_engine.py`<br>(类: `TestDynamicEVEngine`；归档中) | **核心复用**：判决书 M-2 已追认动态费率修复，是 S1 盘口定价基石。 |
| `backtest_engine.py` | `HistoricalBacktestEngine`: <br>• `run_backtest(...)` | 历史回测撮合引擎，驱动历史天气与仿真做市盘口 | 依赖 modeling/prediction/simulation 各模块 | `tests/simulation/test_historical_backtest.py` | 历史验证引擎，重建后作为离线策略评估器。 |
| `clock.py` | `SimulationClock`: <br>• `now()`, `advance()`, `set_time()` | 可插拔仿真时钟，支持快进与步进 | `datetime`, `enum`, `logging` | `tests/simulation/test_sim_models_clock.py` | 完全复用：纸面盘时间控制基础设施。 |
| `market_maker.py` | `SyntheticMarketMaker`: <br>• `generate_market_order_books(...)` | 生成符合真实盘口微观结构（点差、深度）的仿真 OrderBook | `numpy`, `scipy.special`, `ev_engine` | `tests/simulation/test_synthetic_market_maker.py` | 完全复用：纸面盘环境下的做市盘口模拟。 |
| `metrics.py` | `SimulationMetricsCalculator`: <br>• `compute_max_drawdown(...)`<br>• `compute_sharpe_ratio(...)`<br>• `verify_capital_conservation()` | 回测/纸面盘指标评估与资金守恒机械校验 | `math`, `decimal.Decimal`, `bankroll_manager` | `tests/simulation/test_sim_metrics.py` | 完全复用：资金守恒布尔校验直接作为审计验收项。 |
| `models.py` | `SimulatedOrderBook`, `PaperPosition`, `PaperTradeRecord` | 仿真订单簿、纸面持仓与交易记录 | `execution.models`, `ev_engine` | `tests/simulation/test_sim_models_clock.py` | 完全复用：纸面盘轻量数据结构。 |
| `paper_engine.py` | `PaperTradingSimulator`: <br>• `on_weather_observation(...)`<br>• `evaluate_and_execute(...)`<br>• `settle_market(...)` | 纸面盘事件驱动总控（观测驱动 $\to$ 定价 $\to$ 凯利 $\to$ 撮合 $\to$ 结算） | 串联 bankroll/execution/risk/simulation | `tests/simulation/test_paper_engine.py` | **第一类落地的纸面盘载体**：在此装配重构后的 S1~S5 流程。 |
| `settlement_sim.py` | `SettlementSimulator`: <br>• `settle_market(...)` | 市场到期结算模拟器，按温度命中划转盈亏 | `bankroll_manager`, `execution.models` | `tests/simulation/test_paper_engine.py`<br>(测试类: `TestSettlementSimulator`) | 完全复用：结算损益与胜负划转。 |

---

### 2.5 现役树模块（`src/risk/`, `src/prediction/`）

| 模块路径 | 关键类 / 函数签名 | 核心功能 | 现役测试路径与状态 | 关系与衔接要求 |
| :--- | :--- | :--- | :--- | :--- |
| `src/risk/stream_watchdog.py` | `StreamRiskWatchdog`: <br>• `record_packet(...)`<br>• `evaluate()`<br>`RiskLevel`, `RiskStatus` | 监测实时观测流延迟与心跳，维护流级风险状态 | `tests/unit/risk/test_stream_watchdog.py`<br>(4 passed in 0.01s) | **现役保留模块**：作为数据管道输入侧的健康度指标输入，连接到统一中枢。 |
| `src/prediction/discrete_bin_engine.py` | `DiscreteBinEngine`: <br>• `generate_2deg_adsorbed_bins(...)`<br>• `calculate_2deg_bin_probabilities(...)`<br>`settle_half_up(val)` | 将连续分布（如 Johnson SU / Gaussian）精确积分吸附到 Polymarket 2°F 互斥离散档位 | `tests/unit/prediction/test_discrete_bin_engine.py`<br>`test_discrete_bin_engine_2deg.py`<br>(全绿) | **第一类概率输入基石**：提供每个离散档位的模型胜率估计 $p_j$；Q7 双轨在此明确区分输出。 |
| `src/prediction/truncated_probability_engine.py` | `TruncatedProbabilityEngine`: <br>• `apply_truncation(...)`<br>`TruncationResult` | 根据日内已发生实况实施单调截断（温度不可逆上升/下降），动态重估各档位条件概率 | `tests/unit/prediction/test_truncated_probability_engine.py`<br>(4 passed in 0.01s) | **日内动态修正输入**：替代 v1 CHSM 的实况动态重定价核心引擎。 |

---

## 三、 盘点结论与对新算法开发的架构映射

1. **资产状态结论**：
   - 现役代码库与测试（113 passed）保持了极佳的洁净度与模块独立性；
   - 归档交易资产具备完整的四桶资金账务、IOC 保护价路由、做市商仿真与资金守恒审计底座；
   - 历史缺陷（如 M-4 的 Sigmoid 市场价收缩、M-1 缺失 Minimax、未统一残差标准化、后置多重折剪）已被裁决令彻底判决与纠正，不存在隐蔽的历史债务外溢风险。
2. **Q1 / Q7 接入点明确**：
   - **Q1（连续可信度得分与仓位折减）**：
     - 上游输入：`DiscreteBinEngine` 与盲测/评估指标（方差比 $s_{\text{oos}}$、档级加权 ECE、覆盖率、PIT 方差）；
     - 接入位置：S2 预算上限计算公式 $C_{\max}$，作为唯一折剪点（DR-2026-1014-02），严禁后置多重折剪，严禁做胜率收缩；
     - KMIA 欠自信格处置：在 $\sigma_{\text{adj}}$ 与 Kelly 侧收缩预算，不重训模型。
   - **Q7（覆盖率双轨分工）**：
     - `exact`（经验 5/95 分位）下沉至结算核验与事后质检（`tests/` 与评估脚本）；
     - `gaussian_proxy`（$\mu \pm 1.64485\cdot\sigma_{\text{eff}}$）用于实时定价与不确定集定义；
     - 二者与门禁带 G5 严禁混用。
