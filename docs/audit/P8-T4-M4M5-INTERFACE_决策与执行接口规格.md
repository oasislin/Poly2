# P8-T4-M4M5-INTERFACE：决策引擎（`M4`）与执行器（`M5`）接口规格及 `P2/P5/P6/P7/P8/P14` 协议正文（`v1.2` · `2026-11-28 已对齐 P2 陡峭尾档预冻结约束与 P18 静息盘口回退`）

> **版本标注（`2026-11-22` `P8-WO-20261123-S306-STAGE2-EXEC` · 已对齐 `S3-06` 阶段二 / `D-6` 合龙）**：物理路径保持 `_v1.0.md` 引用不变；既有 `§1–§3.4` 历史正文保留不重写，新增 **`§3.5 P14 v1.0` 正式协议正文**，并同步注记 `§3.4` `_compute_policy_config_hash v2` 纳入 `yellow_multiplier`。
>
> **版本标注（`2026-11-28` · 已对齐 `P2 v1.2` 陡峭尾档预冻结感知走簿与 `P18 v1.1` 连续假盘静息回退）**：既有历史正文全部保留不重写；`§2.2` 追加 **`P2 v1.2`** 预冻结感知深度切片与预计实花下限双校验修订注记，`§2.3` 追加 **`P18 v1.1`** 可选静息盘口回退与帧级虚拟深度扣减修订注记（代码落点 [`src/execution/executor.py`](../../src/execution/executor.py)）；同日按业主指令移除物理文件名 `_v1.0` 后缀，版本号统一在正文首部维护。

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
3. **空卖盘与跨盘倒挂前置阻断（`D3` + `P4 v1.1` 单侧盘口守卫）**：若 `P4.ask_book is None`（`P4.single_side == "bid_only"`，尾桶无卖单）或 `P4.best_bid is not None and P4.ask_book.levels[0][0] <= P4.best_bid`，强制阻断本次机会评估并写入 `P1`（`decision_outcome="BLOCKED_NO_BOOK_DEPTH"`，`best_ask_price=None`），严禁将 `None` 或倒挂盘口传入 `edge_math` 或 `M5`。
4. **含费 `edge` 与相对门槛判定（裁定 `A2` + `B5`）**：
   - 仅当 `P4.ask_book is not None` 时调用唯一事实源 [`src/pricing/edge_math.py`](../../src/pricing/edge_math.py) 之 `evaluate_book_edges(ask_book=P4.ask_book, p_model=bin_p, m=P6.risk_gate.m_threshold, fee_rate=P4.fee_rate)`；
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

### 2.2 `P2 plan_slice` 正式协议签名与切片算法（`M4 → M5` · `v1.1` · `2026-11-21` 对齐 `Decimal` 域）

```python
@dataclass(frozen=True)
class SlicePlan:
    should_submit: bool
    target_usd: Decimal
    target_shares: Decimal
    limit_price: Decimal
    est_vwap: Decimal
    qual_depth_shares: Decimal
    order_type: Literal["IOC_FAK"]
    abort_reason: Optional[str] = None
    leg_allocations: Tuple[PlannedLegSlice, ...] = ()


def plan_slice(
    d_headroom_usd: Decimal | float,
    ask_book_frame: MarketBookSnapshot | MergedYesAskView,   # 同帧 P4 v1.1 或双侧合并视图
    p_model: float,
    m_threshold: float,
    phi_policy: PhiPolicy,
) -> SlicePlan:
    ...
```

- **算法流程（Edge 感知 POV，`φ = C`，`v1.1 Decimal` 精确域）**：
  0. **单侧无卖盘与倒挂前置守卫（`P4 v1.1` 对齐）**：若目标视图 `inverted_cross` 或 `ask_book is None`（`single_side == "bid_only"` 且无配对 `Bid(NO)` 互补深度），立即返回 `should_submit=False, abort_reason="INVERTED_BOOK" | "NO_ASK_DEPTH"`，不得向 `edge_math` 传 `None`；
  1. 调用 `edge_math.evaluate_book_edges(ask_book, p_model, m_threshold, fee_rate=...)`；
  2. 对每档 `lvl` $\in \text{qualified\_levels}$ 在 `Decimal` 精确上下文中计算参与率 $\rho(\text{edge}_j) = \text{clip}(\rho_0 + k_{\text{slope}} \cdot (\text{edge}_j - m_{\text{threshold}}),\; \rho_{\min},\; \rho_{\max})$，累计加权可执行深度上限 `pov_cap_usd = sum(rho_j * lvl.size * lvl.price)`（同步记录 `YES_ASK` / `NO_BID_SPLIT_SELL` 分腿配置）；
  3. 确定 `target_usd = min(d_headroom_usd, pov_cap_usd)`，保护限价 `limit_price` 取合格档位最差档价按 `tick_size` 向下整数倍对齐（`Decimal` 整除对齐消除浮点漂移），`target_shares = (target_usd / limit_price).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)`，`effective_target_usd = target_shares * limit_price`；
  4. **双约束校验**：在 `Decimal` 域核验 `target_shares >= min_order_size_shares`（`5.0 shares`）及（若非空）`effective_target_usd >= min_notional_usd`，不达标则返回 `should_submit=False, abort_reason="BELOW_MIN_ORDER"`。

- **2026-11-28 修订注记（`P2 v1.2` · 陡峭尾档预冻结感知走簿与预计实花下限双校验，[`src/execution/executor.py`](../../src/execution/executor.py)）**：
  - **问题根因**：在 `KDAL 7338470`（`D=$6.312`）实测中暴露出陡峭尾档切片失真——原 `_allocate_pov_legs` 沿合格卖档一路上探至高价档位（`$0.001 -> $0.20`），抬高 `limit_price=$0.20`，随后旧版 `plan_slice` 抛弃累计 `tot_sh` 而直接按 `target_usd / limit_price` 计算 `target_shares = $6.312 / $0.20 = 31.56 shares`，导致实际只买入低价卖档成交 `$0.03156`（`200x` 失真），同时以虚高的 `effective_target_usd = $6.312` 绕过了 `min_notional_usd = $1.0` 下限校验。
  - **预冻结感知走簿（`_allocate_pov_legs`）**：逐档累加合格卖盘深度时，在每个价位 `p` 先核算按最高限价预冻结预算可容纳的增量上限 `escrow_room_shares = (d_usd_dec / p) - total_shares`；若 `escrow_room_shares <= 0` 则立即停止继续向上爬档；否则截断当前档取量 `take_sh = min(take_sh, escrow_room_shares)` 并在吃满预冻结容量后终止，确保 `limit_price` 不再被陡峭尾档虚高拉升。
  - **份额守恒与双下限校验（`plan_slice`）**：保留实际走簿累计份额 `tot_sh`，取 `target_shares = min(tot_sh, d_usd_dec / limit_dec).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)`；并对 `min_notional_usd` 执行**双口径强校验**——`effective_target_usd = target_shares * limit_price` **与** `est_expected_usd = target_shares * est_vwap` 必须**同时** `>= min_notional_usd`，否则返回 `should_submit=False, abort_reason="BELOW_MIN_ORDER"`，杜绝 `$0.03` 等尘埃单穿透发单门槛。
  - **Edge / VWAP 与预算门不变量**：走簿涉及的每一档均已单独满足 `lvl.edge >= m_threshold`，因此累计平均成交价严格满足 `est_vwap <= limit_price` 且组合 `edge(est_vwap) >= m_threshold`；同时 `target_shares * limit_price <= D` 保证 `M6` 预冻结资金 `C_freeze` 严格不越 `G` 上限。

### 2.3 `LIVE` 与 `PAPER`（`P18` 延迟撮合）双轨路由规则

- **`LIVE` 路由**：通过 `P14` 冻结 `C_freeze = target_shares * limit_price * (1 + max_fee_buffer)` 后，按 `ask_book_frame.neg_risk` 选择 NegRisk CTF EIP-712 域签名下发 `FAK` 限价单；成交后 `P14` 确认实花含费美元解冻余款，并写 `P3`。
- **`PAPER` 延迟撮合（`P18` · `M7 → M5`）**：
  - 记录下单发出时间 `submit_ts_utc`，注入延迟 `latency_ms`（占位延迟参数随假盘会话配置，基于 `T3` / 实测网关时延分布）；
  - 向 `M7` 只读查询 `(token_id=ask_book_frame.token_id, after_ts=submit_ts_utc + latency_ms)` 对应的 **`P13` 录制流下一真实帧**；
  - 若命中帧 `gap_detected == True` 或缺失可匹配帧：**立即终止本笔模拟撮合**，回传 **`PAPER_MATCH_ABORTED_GAP`** 写入 `P3` 并通知 `P14` 解冻预冻结额；**严禁回退使用决策瞬间快照零延迟成交，严禁旁路直读 `live WS` 流**；
  - 若命中帧 `gap_detected == False` 但 `ask_book is None`（`single_side == "bid_only"`）：诚实判正常无卖盘深度未成交，置 **`terminal_status = "CANCELLED_UNFILLED"`**、**`reject_or_abort_reason = "NO_ASK_DEPTH"`** 并经 `P14` 解冻 `C_freeze`（不得误报 `PAPER_MATCH_ABORTED_GAP`；双侧 `No` 跨视图撮合扩展设计见 [`P8-RECORDER-NO-SIDE-DESIGN v0.1 §3`](P8-RECORDER-NO-SIDE-DESIGN_尾桶单侧与No侧双视角升级设计书_v0.1.md#3-工单-5-纯设计m4--m5-no-侧解析split--merge-跨视图撮合与-d-6-合并视图输入不下代码)，待回签后落代码）。
  - **2026-11-28 修订注记（`P18 v1.1` · 连续假盘静息盘口回退与帧级虚拟深度扣减，[`src/execution/executor.py`](../../src/execution/executor.py)）**：
    - `ReplayMatcher.__init__(..., allow_resting_book_fallback: bool = False)` 新增可选参数；**默认 `False`**，保持离线静态回放对 `R1` 无后继帧的既有严格拒单契约；
    - 当连续假盘守望模式显式开启 `allow_resting_book_fallback=True` 时：① **严格保留真断流守卫**：命中帧或 `(decision_seq_id, F*.seq_id]` 窗口任一 `gap_detected == True` 时仍强制立即中止（`R2_HIT_GAP` / `R2_GAP_IN_WINDOW`）；② **静息盘口回退**：若 `t_arrive` 之后盘口因行情静默尚未产生新增量帧，允许安全回退至 `t_arrive` 前最新无缺口真实录盘帧（`prior_clean`），并置 `final_ts = max(t_arrive, raw_final_ts)` 防止回填时间戳倒挂；③ **帧级虚拟深度扣减**：按 `(token_id, frame_seq, raw_price)` 持久化维护 `_consumed_shares` 账本，同一静态盘口帧的某档深度被模拟单吃尽后，后续命中同一帧的请求不再重复吃同一流动性，耗尽时返回 `RESTING_BOOK_DEPTH_EXHAUSTED` 并解冻余款。
    - **2026-11-28 补充（`PAPER` 独立双限额门控）**：`S3-11` 连续假盘经 [`PaperSafetyGate`](../../src/execution/paper_safety_gate.py) 在 `P14` 预冻结前与 `P18` 撮合前同步执行 `configs/clob_gateway.yaml` 单笔（`\$25`）与**单站单盘口日**（`\$250`，按 `station_id|target_date` 独立计数，非本地自然日）硬门控（账本隔离落盘至 `data/gateway/paper_daily_usage.json`），超限直接返回 `P3` `REJECTED`（`SAFETY_GATE_SINGLE_ORDER_EXCEEDED` / `SAFETY_GATE_DAILY_LIMIT_EXCEEDED`）。

### 2.4 `S1-06` 费率消费与回放口径隔离规则（`P4 / P18` · `2026-11-19` 当前决策）

- **回放 / 离线评估 / 假盘录盘撮合路径（消费 `P13 / P18` 录盘数据）**：凡消费录盘帧的路径（含 `P18` 假盘撮合、`M4/M5` 历史盘口回放、`T3` 走簿分析及 `P3` 滑点归因），计算含费 `edge` 与模拟撮合手续费时，**`fee_rate` 一律严格取所消费帧自带的 `P4.fee_rate`（即录盘时点之真实历史费率）**，严禁跨越 `2026-11-20T23:59Z` 变费断点用今日实时费率去覆写历史录盘帧；并按 [`P8-FACTS-LEDGER v0.3 §2.1`](P8-FACTS-LEDGER_静态事实档案_v0.1.md#21-2026-11-19-s1-06-变费复核与-费率时代标记规则当前决策) 标注 `fee_era`（跨断点不混采）。
- **实盘实时下单路径（`LIVE`）**：取运行时 **Gamma `/markets` `feeSchedule.rate`**（`D1` 权威源，`API_RUNTIME`；字段缺失时退回 `FACT-001` 并如实标注 `fee_rate_provenance="FACT-001"`）。

### 2.5 编码批精度与跨侧容差补充规格（`2026-11-21` · `P8-WO-20261121-M4M5-RECTIFY §1.4` 补录）

1. **`cross_arb_eps` 跨视图套利容差（[`orderbook_views.py`](../../src/execution/orderbook_views.py)）**：
   - **默认值与选择依据**：`build_merged_yes_ask_view(..., cross_arb_eps=Decimal("0.0001"))` 将跨侧负价差判定阈值设为 `1e-4`（即 `raw_all[0].implied_yes_price < best_bid_eff - Decimal("0.0001")` 始判 `CROSS_VIEW_INVERTED_SPREAD`）。Polymarket 活跃温度盘最小行情 `tick_size` 为 `0.01` 或 `0.001`；当市场恰好处于 `ask_YES + ask_NO == 1.0` 无套利零和平衡点时（例如 `ask_YES = 0.40`, `ask_NO = 0.60 → 1 - ask_NO = 0.40`），原无容差 `<=` 判别会将其误杀为跨视图倒挂。选取小于最小 `0.001` 跳价十倍的 `0.0001`，既彻底消除等价平衡点及 `float → Decimal` 边界量化误差导致的误报，又不放松真实跨盘套利穿越（≥ `0.001` 一跳即时触发拦截）。
   - **单边内盘零容差区分**：单腿内部盘口倒挂校验（`YES_INTRA_BOOK_INVERTED`: `yes_ask <= yes_best_bid`；`NO_INTRA_BOOK_INVERTED`: `no_ask <= no_best_bid`）**严格维持 `<=` 零容差**，绝不引入 `cross_arb_eps`，保持对 `D3` 单侧盘口完整性的硬阻断。
2. **`_to_exec_decimal` 数值转换规则与下游 12 位守卫（[`executor.py`](../../src/execution/executor.py)）**：
   - **转换规则**：`_to_exec_decimal(value, *, name)` 委托 [`to_guarded_decimal`](../../src/utils/decimal_guard.py) 执行十进制语义转换——底层使用 Python **`str(value)` 十进制序列化** 构造 `Decimal`（运行于 `EXACT_DECIMAL_CONTEXT_PREC=64` 上下文，绝不直接调用带二进制 IEEE-754 尾数噪声的 `Decimal(float)`）；针对上层 Python 浮点算术不可避免产生的 15–17 位尾数伪影（如 `0.1 + 0.2 -> 0.30000000000000004`，17 位有效数字），仅对 `isinstance(value, float)` 入口操作数放宽 `max_sig_digits=18`。
   - **下游 12 位结构守卫不变性**：对一切显式 `Decimal` 或 `str` 输入，`_to_exec_decimal` 继续强制 `max_sig_digits=12`；且所有下游核算/收费/对齐函数（`to_guarded_decimal`、`compute_taker_fee_usd_raw`、`align_price_down_to_tick`、`build_merged_yes_ask_view` 等）继续严格执行 `DEFAULT_MAX_OPERAND_SIG_DIGITS = 12` 抛出 `DecimalOperandBoundsError`。

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

### 3.3 `P5 ForecastDistributionSnapshot v1.1`（`M2 → M4 / M7` · `2026-11-19` `S3-02 / T8 v0.3` 联动升版）

> **升版说明（`v1.0 → v1.1` · `2026-11-19`）**：依据 `S3-02` 结算同构整数刻度裁决及 `T8 v0.3` 评审令：① 废弃 `.5°F` 边界，改为闭整数端点；② 严禁单字段双语义，将原 `p_stay` 拆分为全档同义之物理点质量 **`p_stay_phys`** 与档内锁定概率 **`p_bin_stay`**；③ 明确 `M4` 最新 `issue_ts_utc` 胜出消费规则、超龄降级与 `M2/M4` 双龄分段职责。

- **结构字段**：
  - 路由与溯源：`forecast_id: str`, `issue_ts_utc: datetime`, `station_id: str`, `target_date: date`, `target_type: Literal["TMAX", "TMIN"]`, `gefs_lead_hours: int`, `tau_hours: float`, `settle_close_utc: datetime`, `model_hash: str`；
  - 结算口径与桥状态：`prior_mu0: float`, `prior_sigma0: float`, `family: str`, `m_now_f: Optional[float]`, `m_now_int_f: Optional[int]`（$\lfloor m_{\text{now}} + 0.5 \rfloor$）, `oracle_compliant: bool`, `upstream_obs_fresh: bool`（`M2` 侧校验之 `M1→M2` 观测新鲜度）, `is_bridge_active: bool`, **`p_stay_phys: Optional[float]`**（物理极值不创新高/低 Dirac 原子质量，全档统一定义不截顶）, **`p_bin_stay: Optional[float]`**（归属当前极值所在离散档位之锁定留存概率）；
  - 输出向量与样本：`bin_probs: tuple[BinProb, ...]`（`BinProb(bin_id, label, lower_int_f: Optional[int], upper_int_f: Optional[int], p_model: float)`，`None` 表示开区间尾端 $-\infty / +\infty$，**严禁再出现 `.5°F` 边界字段**）、`sigma_delta_sample: float`（仅经 `P17` 落盘供 `P8` 月度离线校准）。
- **四条硬不变量（`Q-B1` · 已入 [`test_edge_math.py`](../../tests/unit/pricing/test_edge_math.py) `N7` 随机参数测试清单，随 `T8` 升级至 `v1.1` 双字段校验）**：
  1. 概率单纯形完备（依赖连贯档梯守卫）：$\sum_k p_{\text{model}, k} = 1.0$（浮点容差 $\le 10^{-5}$）且每项 $\in [0.0, 1.0]$；
  2. 双原子字段正交域（禁用单字段双语义）：`p_stay_phys is None` 当且仅当 `p_bin_stay is None` 当且仅当 `is_bridge_active == False`；当 `is_bridge_active == True` 时必有 $0.0 \le p_{\text{stay\_phys}} \le 1.0$ 且 $0.0 \le p_{\text{bin\_stay}} \le 1.0$；
  3. 极性敏感死档清零（全整数域）：设 $m_{\text{now}}^{\text{int}} = \lfloor m_{\text{now}} + 0.5 \rfloor$，`TMAX` 全部 `upper_int_f is not None and upper_int_f < m_now_int` 之档恒有 `p_model == 0.0`；`TMIN` 对称全部 `lower_int_f is not None and lower_int_f > m_now_int` 之档恒有 `p_model == 0.0`；
  4. **点质量与档内锁定双包含律**：含 $m_{\text{now}}^{\text{int}}$ 之边界档 $j$ 恒满足 **`bin_probs[j].p_model == p_bin_stay >= p_stay_phys`**（`p_stay_phys` 为全档同义物理原子成分、`p_bin_stay` 为档内留存概率，二者均内包于 `p_model` 绝不重复叠加）；当落入开放尾档（`TMAX` `upper_int_f is None` / `TMIN` `lower_int_f is None`）时，**`p_bin_stay == 1.0` 且 `bin_probs[j].p_model == 1.0`**，而 **`p_stay_phys` 继续保持其未截顶物理原子概率 $\Phi(-\mu_R/\sigma_{\text{rem}})$**。
- **`M4` 消费、`issue_ts` 胜出与双龄分段规则（`2026-11-19` `v1.1` 新增）**：
  - **最新 `issue_ts_utc` 胜出，严禁回替**：`M4` 对同 `(station_id, target_date, target_type)` 取 `issue_ts_utc <= scan_ts_utc` 的最新一条 `P5` 快照；若该最新快照不满足 `oracle_compliant` 或超龄，**严禁回退消费更早的历史 `P5` 快照**；
  - **超龄走降级枚举**：若 `scan_ts_utc - P5.issue_ts_utc > forecast_age_limit_sec`（可配置参数，附 `provenance`），`M4` 停止按该过期预测新开仓并记入降级/阻塞事件状态；
  - **双龄职责分段（各管一段）**：`M2` 专属负责签发前校验 **`M1 → M2` 观测数据新鲜度**（`P11` `physical_age / dispatch_age`）并写入 `upstream_obs_fresh`（超限时置 `is_bridge_active=False` 退先验）；`M4` 专属负责决策瞬间校验 **`M2 → M4` 预测签发龄（`scan_ts_utc - P5.issue_ts_utc`）与 `M3 → M4` 盘口龄（`scan_ts_utc - P4.recv_ts_utc`）**。
- **三态合法矩阵（`Q-B2`）**：`is_bridge_active=True` $\implies$ `m_now_f != None and m_now_int_f != None and oracle_compliant`；`False` & `None`（开盘前/断流降级）合法；`False` & `m_now_f != None`（预热维持先验）合法但必有 `p_stay_phys=None, p_bin_stay=None` 且不强行清零死档。
- **`tau_hours` 与 `T_settle_close_utc` 晚绑定与 `S1-02 G-15` 对齐说明**：
  - 接口显式接收 `settle_close_utc: datetime`（与 `gefs_lead_hours` 完全分离，绝不混用），天然支持按站点动态注入与晚绑定；
  - 结合 `S1-02 T1 G-15` 与 **`S1-06`（`2026-11-19`）** 裁决闭环（[`P8-KERNEL-CONSENSUS §七`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md#七-s1-06-g-15-裁决事实增补max-恒等式定义域论证与-t8-m1-规格输入2026-11-19-当前决策)），`T_settle_close_utc` 正式锚定为 `(target_date + 1d) 00:00:00 Station Local (tz=ZoneInfo(station.tz)) → UTC`（含 DST；不取 Gamma `endDate=12:00Z`），且 **`P5` 四条不变量与死档清零定义域严格限定为“`M_now` 来自常规 `METAR` 结算同构流（$\mathcal{O}_{\text{settle}}(D, t) \subseteq \mathcal{O}_{\text{settle}}(D)$）”**，具体 `M1 / M9` 代码切换于 `T8` 落实。
- **`T8` 现役代码改造接口映射（对齐 [`P8-T8-ALGO4-DESIGN v0.3`](P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md)）**：`T8` 阶段 `M2` 改造须补齐 `TruncatedDistribution` 对 `MuRHook` 的核一致 Hurdle/点质量导出（产出 `p_stay_phys` 与 `p_bin_stay`），并重构 [`DiscreteBinEngine`](../../src/prediction/discrete_bin_engine.py) 为纯整数闭合区间与连贯档梯守卫。

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
- **`config_hash v2` 升版注记（`2026-11-22` `S3-06` 阶段二）**：`_compute_policy_config_hash` 已按业主裁决正式纳入 `yellow_multiplier`；修改 `yellow_multiplier` 须换版 `policy_version` 并重算 `config_hash`。

---

### 3.5 `P14` 现金预冻结 / 成交回环协议（`M5 ↔ M6` · `v1.0` · `2026-11-22` `S3-06` 阶段二正式成文）

- **归属与实操模块**：协议正文常驻本节（联动 [`src/bankroll/`](../../src/bankroll/) 与 `M5` 执行器）；同步刷新 [`项目方案 (v3.0) §8.2 P14`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#82-协议清单p1p19-十九条--2026-11-18-当前决策)（`§8.3` 同提交闭合）。
- **核心契约数据结构（内部 `Decimal` 域，面向 `P7/P19` 边界转 `float`）**：

```python
@dataclass(frozen=True)
class FreezeRequest:
    decision_id: str
    idempotency_key: str        # 幂等去重键（非空）
    station_id: str
    market_id: str
    token_id: str
    target_freeze_usd: Decimal  # 必须 > 0
    requested_ts_utc: datetime


@dataclass(frozen=True)
class FreezeReceipt:
    accepted: bool
    decision_id: str
    idempotency_key: str
    frozen_usd: Decimal
    blocked_reason: Optional[str]
    recorded_ts_utc: datetime
    deduplicated: bool = False


@dataclass(frozen=True)
class FillSettleLoopback:
    decision_id: str
    attempt_id: str             # 幂等回环键
    station_id: str
    market_id: str
    filled_usd: Decimal         # >= 0 且 <= frozen_usd
    terminal_status: Literal[
        "FILLED", "PARTIAL", "CANCELLED_UNFILLED", "REJECTED", "PAPER_MATCH_ABORTED_GAP"
    ]
    settled_ts_utc: datetime
    reject_or_abort_reason: Optional[str] = None
```

- **Fail-Closed 阻断与优先级规则**：
  1. 幂等校验：`FreezeRequest.idempotency_key` 命中缓存时直接返回原 `FreezeReceipt(deduplicated=True)`，不重复扣款亦不重复写 `P19`；`FillSettleLoopback.attempt_id` 同样幂等去重；
  2. 闸门优先级：**`ACCOUNT_DRAWDOWN_BRAKE_TRIPPED` > `STATION_LOSS_GATE_TRIPPED` > `P16_RED_LIGHT_BLOCKED` > `INSUFFICIENT_FREE_USD / STATION_CAP_EXCEEDED`**；任一触发即整体拒绝（`accepted=False, frozen_usd=Decimal("0")`），严禁部分冻结，且遵守 [`P8-CAPITAL-CONFIG §6.4`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#64-超门不自动平仓原则) 不主动平掉既已持仓（`held_by_market`）；
  3. 仅作为 `M6` 本地风控数据源与预冻结通道，**`-$500/站` 亏损闸与 `25%` 账户回撤硬刹车仅消费 `P14/P15` 回报在 `M6` 本地触发并记入 `P19`，绝不向 `P16` 反向广播**。
- **三桶严格资金守恒式与 `FILL_SETTLE_CONVERSION` 语义澄清（`修正 1`）**：
  - `M6`（[`BankrollAccountManager`](../../src/bankroll/manager.py)）采用 `Decimal` 三桶记账：`free_usd`（自由现金）、`active_locked_usd`（`Σ frozen_by_decision`，待 IOC 回环冻结额）、`held_total_usd`（`Σ held_by_market`，`FILL_SETTLE_CONVERSION` 转化留存持仓成本基）；全程满足零漂移恒等式：
    `free_usd + active_locked_usd + Σ held_by_market == tier_pool_usd + Σ realized_pnl_by_station`（`conservation_residual_usd == Decimal("0")`）；
  - 与离线 `S3-05` 回放桩 [`replay_engine._ReplayAccountTracker`](../../src/audit/replay_engine.py#L88-L109) 之口径差异注记：离线回放追踪器未单设 `held_by_market` 桶，故其 `apply_settlement_conversion` 仅将未成交余款退回 `free_usd` 而把成交成本留置于 `active_locked_usd`；生产级 `M6` 显式拆分 `active_locked_usd` 与 `held_by_market`，使 `P7 QuotaSnapshot` 可精确分列 `station_active_locked_usd` 与 `market_held_usd` 并同步满足三桶守恒。
- **`25%` 账户回撤激活双路径（`P8-CAPITAL-CONFIG §4 L40-45` · `修正 4`）**：`tier_pool_usd <= $2,000` 期 `drawdown_brake_enabled=False`（仅计算并可查回撤指标，不阻塞下单；`-$500/站` 亏损闸自始生效）；当 **首次触发 `TIER_STEP_UP`（`+$1,000`）之日** 或 **进入满部署（`$10,000`）之日**，自动激活 `drawdown_brake_enabled=True`。
