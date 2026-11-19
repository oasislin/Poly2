# P8-T4-M4M5-INTERFACE：决策引擎（`M4`）与执行器（`M5`）接口规格及 `P2/P5/P6/P7/P8` 协议正文（`v1.0` · `2026-11-18 当前决策`）

- **任务单与治理编号**：`S1-04`（`T4` · 切片 1 阶段 0 接口规格与纯函数交付）｜归属模块：**`M4`（决策引擎）/ `M5`（执行器）**，联动 `M2 / M6 / M7 / M8`
- **法定锚点**：
  - [`P8-CAPITAL-CONFIG v1.0`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md)
  - [`P8-EXECUTION-DESIGN v1.0`](P8-EXECUTION-DESIGN_w与phi设计与决策记录_v1.0.md)
  - [`项目方案 (v3.0) §8.1 / §8.2 / §8.3 / §8.4 / §8.5`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#8-模块地图与协议层总索引v30-后-α-十模块静态结构与-p1p19-契约--2026-11-18-当前决策)
- **文件增殖判据核验（[`AGENTS.md`](../../AGENTS.md)）**：`P8-CAPITAL-CONFIG` 承载三层资金制度与参数账本，`P8-EXECUTION-DESIGN` 承载 `w/φ` 选型理由；全仓此前尚无承载 `M4/M5` 模块接口、`P7` 额度查询、`P8` 校准流及 `P5/P6 v1.0` 正文契约的独立工程规格文档，故按判据合规新建本文件。
- **版本与表述纪律**：**`v1.0`（`2026-11-18` 当前决策 / 首期选择；月度复检可替换；数据充分时形态让位于数据）**；严格不动 `F-2 LOCKED`（`penetration_probe.py` / `sigma_adj.py` / `coverage_dual_track.py`）。

---

## 一、 `M4` 决策引擎工程接口规格

### 1.1 职责边界（严守 `项目方案 v3.0 §8.1`）

- **只消费上游输出，绝不反向越界**：`M4` 消费 **`P5 ForecastDistributionSnapshot`**（来自 `M2`）、**`P4 MarketBookSnapshot`**（来自 `M3`）、**`P6 ExecutionPolicyBundle`**（来自 `M8`）、**`P7 QuotaSnapshot`**（来自 `M6`）及 **`P16` 灯级事件订阅**（来自 `M8`），禁止回耦 `M2` 内部先验/条件桥数学实现，禁止接触钱包私钥与网关发单客户端。
- **`P16` 订阅消费声明（裁定 `A1`）**：`M4` 在初始化阶段注册 `P16` 订阅回调槽（接收月度定级与月中降档事件并转发状态标签至 `P1`），**但关于 `s(edge)` 中间形态及 `yellow_multiplier` 精确作用点，留归 `D-6` 下一桌议程拍板（本规格不预设 `D-6` 未决消费语义）**。

### 1.2 双钟扫描流水线与门限额决策签名

1. **双钟调度入口（数据前预设形状见 `P8-CAPITAL-CONFIG §7`）**：
   - **信息钟（`INFO_CLOCK`）**：由 `M2` 预报轮次/日内收敛节奏触发（占位阶梯 `6h / 3h / 1h / 15–30min`）；
   - **价格钟（`PRICE_CLOCK`）**：独立以 `30–60min` 节拍主动扫描目标站点活跃市场盘口；
   - 两钟共用同一决策纯函数，严格落实 **“时间只调门、不开门”**。
2. **`w(tau)` 纯函数接口（`B2` 锚底幂函数，`w` 严格留于 `M4` 内部、不传给 `M5`）**：
   ```python
   def compute_w_tau(tau_hours: float, policy: WPolicy) -> float:
       """Compute bounded anchor power schedule w(tau) in [policy.w0, 1.0]."""
       tau_clamped = min(max(tau_hours, 0.0), policy.tau_max_h)
       progress = 1.0 - (tau_clamped / policy.tau_max_h)
       return policy.w0 + (1.0 - policy.w0) * (progress ** policy.p)
   ```
3. **跨盘倒挂前置阻断（`D3`）**：若 `P4.best_bid is not None` 且 `P4.ask_book.best_price <= P4.best_bid`，强制阻断本次机会评估并写入 `P1`（`decision_outcome="BLOCKED_NO_BOOK_DEPTH"`），严禁带倒挂盘口进入 `edge_math` 或 `M5`。
4. **含费 `edge` 与相对门槛判定（裁定 `A2` + `B5`）**：
   - 调用唯一事实源 [`src/pricing/edge_math.py`](../../src/pricing/edge_math.py) 之 `evaluate_book_edges(ask_book=P4.ask_book, p_model=bin_p, m=P6.risk_gate.m_threshold, fee_rate=P4.fee_rate)`；
   - **量纲强一致性（`B5`）**：`edge = (p_model - q_eff) / q_eff`（相对无量纲比例，仅扣 taker fee、不含 extra spread）与派生只读 `m_threshold = max(k0_threshold_coef * sigma_delta_frozen.value + friction_median, m_floor)` 同属**无量纲相对收益率尺度**，由单测 [`test_edge_math.py`](../../tests/unit/pricing/test_edge_math.py) 强检验。
5. **门限额 $G$ 与增仓差额 $D$**：
   - `g_cap_usd = P6.w_policy.b_budget_usd * w_tau * s_edge`（当 `best_ask_edge < m_threshold` 时 `s_edge = 0.0`）；
   - 向 `M6` 发起 `P7` 查询得到 `QuotaSnapshot`，计算 `headroom_d = max(0.0, min(g_cap_usd - quota.market_held_usd, quota.b_eff_headroom_usd))`；
   - 若 `headroom_d > 0` 且满足 `min_order_size_shares / min_notional_usd`，输出 `P1 (decision_outcome="ORDERED")` 并下发 **`P2 plan_slice`** 至 `M5`；否则按互斥五枚举写 `P1` 负样本日志，**永不抛异常中断扫描循环**。
   - **超门不加不减条款（`CAPITAL-CONFIG §6.4`）**：若 `g_cap_usd <= quota.market_held_usd`，`headroom_d = 0.0`（写 `IDLE_BUDGET_EXHAUSTED` 或跳过），严禁产生卖出减仓指令（`v1` 不做主动退出）。

---

## 二、 `M5` 执行器工程接口规格

### 2.1 职责边界（严守 `项目方案 v3.0 §8.1 / §8.2 P2`）

- `M5` 消费 **`P2 plan_slice`** 与 `P4.tick_size / min_order_size_shares / min_notional_usd / neg_risk` 元数据，向 **`M6` 经 `P14`** 请求买侧 `C_freeze` 现金预冻结，向网关（`LIVE`）或 `P18` 延迟回放撮合器（`PAPER`）提交限价 `IOC_FAK` 单，并将结果经 **`P14`** 回环更新 `M6` 及经 **`P3 ExecutionAttemptLog`** 写入 `M7`。
- **`w` 严禁进入 `M5`**；`M5` 只看见剩余可执行目标美元额 `D` 与 `PhiPolicy`。

### 2.2 `P2 plan_slice` 正式协议签名与切片算法（`M4 → M5` · `v1.0`）

```python
@dataclass(frozen=True)
class SlicePlan:
    should_submit: bool
    target_usd: float
    target_shares: float
    limit_price: float
    est_vwap: float
    qual_depth_shares: float
    order_type: Literal["IOC_FAK"]
    abort_reason: Optional[str]


def plan_slice(
    d_headroom_usd: float,
    ask_book_frame: MarketBookSnapshot,   # 同帧 P4 快照
    p_model: float,
    m_threshold: float,
    phi_policy: PhiPolicy,
) -> SlicePlan:
    ...
```

- **算法流程（Edge 感知 POV，`φ = C`）**：
  1. 调用 `edge_math.evaluate_book_edges(ask_book_frame.ask_book, p_model, m_threshold, fee_rate=ask_book_frame.fee_rate)`；
  2. 对每档 `lvl` $\in \text{qualified\_levels}$ 计算参与率 $\rho(\text{edge}_j) = \text{clip}(\rho_0 + k_{\text{slope}} \cdot (\text{edge}_j - m_{\text{threshold}}),\; \rho_{\min},\; \rho_{\max})$，累计加权可执行深度上限 `pov_cap_usd = sum(rho_j * lvl.size * lvl.price)`；
  3. 确定 `target_usd = min(d_headroom_usd, pov_cap_usd)`，保护限价 `limit_price` 取合格档位内覆盖 `target_usd` 所需最差档价按 `ask_book_frame.tick_size` 对齐，`target_shares = round_down(target_usd / limit_price, decimals=2)`；
  4. **双约束校验**：核验 `target_shares >= ask_book_frame.min_order_size_shares`（`5.0 shares`）及（若非空）`target_usd >= ask_book_frame.min_notional_usd`，不达标则返回 `should_submit=False, abort_reason="BELOW_MIN_ORDER"`。

### 2.3 `LIVE` 与 `PAPER`（`P18` 延迟撮合）双轨路由规则

- **`LIVE` 路由**：通过 `P14` 冻结 `C_freeze = target_shares * limit_price * (1 + max_fee_buffer)` 后，按 `ask_book_frame.neg_risk` 选择 NegRisk CTF EIP-712 域签名下发 `FAK` 限价单；成交后 `P14` 确认实花含费美元解冻余款，并写 `P3`。
- **`PAPER` 延迟撮合（`P18` · `M7 → M5`）**：
  - 记录下单发出时间 `submit_ts_utc`，注入延迟 `latency_ms`（占位延迟参数随假盘会话配置，基于 `T3` / 实测网关时延分布）；
  - 向 `M7` 只读查询 `(token_id=ask_book_frame.token_id, after_ts=submit_ts_utc + latency_ms)` 对应的 **`P13` 录制流下一真实帧**；
  - 若命中帧 `gap_detected == True` 或缺失可匹配帧：**立即终止本笔模拟撮合**，回传 **`PAPER_MATCH_ABORTED_GAP`** 写入 `P3` 并通知 `P14` 解冻预冻结额；**严禁回退使用决策瞬间快照零延迟成交，严禁旁路直读 `live WS` 流**。

### 2.4 `S1-06` 费率消费与回放口径隔离规则（`P4 / P18` · `2026-11-19` 当前决策）

- **回放 / 离线评估 / 假盘录盘撮合路径（消费 `P13 / P18` 录盘数据）**：凡消费录盘帧的路径（含 `P18` 假盘撮合、`M4/M5` 历史盘口回放、`T3` 走簿分析及 `P3` 滑点归因），计算含费 `edge` 与模拟撮合手续费时，**`fee_rate` 一律严格取所消费帧自带的 `P4.fee_rate`（即录盘时点之真实历史费率）**，严禁跨越 `2026-11-20T23:59Z` 变费断点用今日实时费率去覆写历史录盘帧；并按 [`P8-FACTS-LEDGER v0.3 §2.1`](P8-FACTS-LEDGER_静态事实档案_v0.1.md#21-2026-11-19-s1-06-变费复核与-费率时代标记规则当前决策) 标注 `fee_era`（跨断点不混采）。
- **实盘实时下单路径（`LIVE`）**：取运行时 **Gamma `/markets` `feeSchedule.rate`**（`D1` 权威源，`API_RUNTIME`；字段缺失时退回 `FACT-001` 并如实标注 `fee_rate_provenance="FACT-001"`）。

---

## 三、 本批正式确立协议正文（`P7`、`P8`、`P5 v1.0`、`P6 v1.0`）

### 3.1 `P7` 额度查询 / 占用协议（`M6 → M4` · `v1.0`）

```python
@dataclass(frozen=True)
class QuotaQuery:
    station_id: str
    market_id: str
    token_id: str
    policy_version: str


@dataclass(frozen=True)
class QuotaSnapshot:
    station_id: str
    market_id: str
    free_usd: float
    station_active_locked_usd: float
    market_held_usd: float
    station_cap_usd: float                  # 当前 $500/站
    station_realized_loss_usd: float
    station_loss_gate_tripped: bool         # M6 本地亏损闸（不进 P16）
    account_drawdown_brake_tripped: bool    # M6 本地 25% 回撤硬刹车（不进 P16）
    b_eff_headroom_usd: float               # 扣除超并发占仓与站限后的实时剩余可用额度（N8 兜底）
    blocked_reason: Optional[str]
```

- **超并发兜底语义（`N8`）**：当实盘挂牌并发日数超出 `RiskGatePolicy.concurrent_days` 规划假设时，即使单市场 `$G$` 算出正差额，**`M4` 对 `D` 取 `min(G - market_held_usd, b_eff_headroom_usd)`**，由 `M6` 持仓侧站限 `$500` 实时封顶，两层不冲突。

---

### 3.2 `P8` 校准样本流协议（`M7 → M8` · `v1.0`）

- **唯一流向固化**：`M2 → M7 (P17) → M8` 离线聚合 + `M5 → M7 (P3) → M8` + `M9 → M8 (P9)`，**严禁 `M2` 任何代码路径旁路直写 `M8` 参数账本或校准库**。
- **契约对象**：
  - `CalibrationAggregateBatch(window_start_utc, window_end_utc, execution_mode_filter="PAPER"|"LIVE", model_hash, config_hash, n_forecast_samples, sigma_delta_quantiles, empirical_slippage_vs_best_ask_median, n_slippage_fills, idle_rate_by_tau, policy_overdue_ratio)`；
  - 仅由 `M8` 月度复检离线例程批量生成参数替换建议，须人工签发后方写入下一期 `P6 ExecutionPolicyBundle`（测量自动、换版人工、月度节奏）。

---

### 3.3 `P5 ForecastDistributionSnapshot v1.0`（`M2 → M4 / M7` · 由 `rc` 正式成文）

- **结构字段**：
  - 路由与溯源：`forecast_id: str`, `issue_ts_utc: datetime`, `station_id: str`, `target_date: date`, `target_type: Literal["TMAX", "TMIN"]`, `gefs_lead_hours: int`, `tau_hours: float`, `settle_close_utc: datetime`, `model_hash: str`；
  - 先验与桥状态：`prior_mu0: float`, `prior_sigma0: float`, `family: str`, `m_now_f: Optional[float]`, `is_bridge_active: bool`, `p_stay: Optional[float]`；
  - 输出向量与样本：`bin_probs: tuple[BinProb, ...]`（`BinProb(bin_id, label, lower_f, upper_f, p_model)`）、`sigma_delta_sample: float`（仅经 `P17` 落盘供 `P8` 月度离线校准）。
- **四条硬不变量（`Q-B1` · 已入 [`test_edge_math.py`](../../tests/unit/pricing/test_edge_math.py) `N7` 随机参数测试清单）**：
  1. 概率单纯形完备：$\sum_k p_{\text{model}, k} = 1.0$（浮点容差 $\le 10^{-5}$）且每项 $\in [0.0, 1.0]$；
  2. 边界点质量域：`p_stay is None` 当且仅当 `is_bridge_active == False`；当 `is_bridge_active == True` 时 $0.0 \le p_{\text{stay}} \le 1.0$；
  3. 极性敏感死档清零：`TMAX` 全部 $k < j$（$U_k \le m_{\text{now}}$）恒有 `p_model == 0.0`；`TMIN` 对称全部 $k > j$（$L_k \ge m_{\text{now}}$）恒有 `p_model == 0.0`；
  4. **点质量包含律**：边界档 $j$ 恒满足 **`bin_probs[j].p_model >= p_stay`**（非叠加重复计入）；若落入开放极值档（`U_{K-1}=+inf` / `L_0=-inf`），则 `p_stay == 1.0` 且该档 `p_model == 1.0`。
- **三态合法矩阵（`Q-B2`）**：`is_bridge_active=True` $\implies$ `m_now_f != None`；`False` & `None`（开盘前/断流降级）合法；`False` & `m_now_f != None`（预热维持先验）合法但必有 `p_stay=None` 且不强行清零死档。
- **`tau_hours` 与 `T_settle_close_utc` 晚绑定与 `S1-02 G-15` 对齐说明**：
  - 接口显式接收 `settle_close_utc: datetime`（与 `gefs_lead_hours` 完全分离，绝不混用），天然支持按站点动态注入与晚绑定；
  - 结合 `S1-02 T1 G-15` 与 **`S1-06`（`2026-11-19`）** 裁决闭环（[`P8-KERNEL-CONSENSUS §七`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md#七-s1-06-g-15-裁决事实增补max-恒等式定义域论证与-t8-m1-规格输入2026-11-19-当前决策)），`T_settle_close_utc` 正式锚定为 `(target_date + 1d) 00:00:00 Station Local (tz=ZoneInfo(station.tz)) → UTC`（含 DST；不取 Gamma `endDate=12:00Z`），且 **`P5` 四条不变量与死档清零定义域严格限定为“`M_now` 来自常规 `METAR` 结算同构流（$\mathcal{O}_{\text{settle}}(D, t) \subseteq \mathcal{O}_{\text{settle}}(D)$）”**，具体 `M1 / M9` 代码切换于 `T8` 落实。
- **`T8` 现役代码改造接口映射（延续 `P5 rc` 诚实披露）**：`T8` 阶段 `M2` 改造须补齐 `TruncatedDistribution.cdf()` 对 `mu_r_result` 的消费以落实点质量包含律，并按 `G-15` 核定之整数格点与 `.5` 正无穷进位口径重构 [`DiscreteBinEngine`](../../src/prediction/discrete_bin_engine.py) 边界映射。

---

### 3.4 `P6 ExecutionPolicyBundle v1.0`（`M8 → M4 / M5 / M7` · 由 `rc` 正式成文）

- **顶层元数据**：`policy_version: str`, `config_hash: str`, `signed_at_utc: datetime`, `is_overdue: bool`。
- **`WPolicy` (`@dataclass(frozen=True)`)**：
  - `w0_intent: float`, `min_order_usd_eff: float`, `p: float`（默认占位 `1.5`, 要求 `>= 1.0`）, `tau_max_h: float`（`> 0`）, `provenance: str`, **派生只读 `b_budget_usd = station_cap_usd / concurrent_days`** 与 **`w0 = max(min_order_usd_eff / b_budget_usd, w0_intent)`**；
  - **工厂构造铁律（`B4`）**：`b_budget_usd` 与 `w0` 一律在 `build_execution_policy_bundle()` 工厂构造期派生并在 `__post_init__` 强校验 `0 < w0 <= 1.0` 且 `w0 * b_budget_usd >= min_order_usd_eff`；`concurrent_days` 任何变化视为参数账本换版、须重新签发 bundle 并刷新 `config_hash`，严禁 `M4/M5` 运行循环内自行重算。
- **`PhiPolicy` (`@dataclass(frozen=True)`)**：
  - `rho_0: float`, `k_slope: float`（首期占位 `0.0`）, `rho_min: float`, `rho_max: float`, `order_type: Literal["IOC_FAK"] = "IOC_FAK"`, `provenance: str`；不变量 `0 < rho_min <= rho_0 <= rho_max <= 1.0` 且 `k_slope >= 0.0`。
- **`RiskGatePolicy` (`@dataclass(frozen=True)`)**：
  - `k0_threshold_coef: float`（首期占位 `2.0`）；
  - `sigma_delta_frozen: SigmaDeltaFrozen(value: float, provenance: str, freeze_cycle_id: str)`（`N4`；仅月度人工签发替换，严禁运行期在线浮动；首期无实盘样本时置离线先验残差离散度占位值并注明 provenance）；
  - **`friction_median: Optional[float]`**（**裁定 `B5` 阻塞门**：定义 ≡ 相对单位 `median(slippage_vs_best_ask)`，**不含 spread**；初始值必须源自 **切片 2 `T3` 录盘走簿模拟典型切片吃深滑点中位数**，后续首次月度复检以假盘 `P3` 实测滑点中位数替换；**在 `D-A1` 实测未填入之前，`friction_median` 保持 `None` 占位且工厂签发强制阻塞假盘/实盘正式上线运行**）；
  - `m_floor: float`（绝对下限护栏，防极低残差分散期放行噪声微单）；
  - `station_cap_usd: float = 500.0`, `concurrent_days: int = 2`, `yellow_multiplier: float`（保留并标 `"待 D-6 作用点"`，按裁定 `A1`）；
  - **派生只读属性 `m_threshold`**（`B5`）：当 `friction_median` 已填入合法非负值时，`m_threshold = max(k0_threshold_coef * sigma_delta_frozen.value + friction_median, m_floor)`；`light_status` 已从 `P6` 移除（走 `P16`）。
- **`is_overdue=True` 强制消费语义（`B6`）**：维持旧冻结参数继续运行、`M7`（`P1/P3/P19`）写入 `policy_overdue=True` 标、经参数账本通道催办；严禁降级、半额或停机。
