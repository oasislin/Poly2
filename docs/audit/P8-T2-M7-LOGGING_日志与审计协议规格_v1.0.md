# P8-T2-M7-LOGGING：日志与审计模块（`M7`）协议本体及落盘规范（`v1.0` · `2026-11-18 当前决策`）

- **任务单与治理编号**：`S1-03`（`T2` · 切片 1 阶段 0 文档交付）｜归属模块：**`M7`（日志审计）**
- **法定锚点**：[`P8-KERNEL-CONSENSUS v1.1 §六 E/F`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md)、[`项目方案 (v3.0) §8.1 / §8.2 / §8.3`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#8-模块地图与协议层总索引v30-后-α-十模块静态结构与-p1p19-契约--2026-11-18-当前决策)
- **文件增殖判据核验（[`AGENTS.md`](../../AGENTS.md)）**：全仓此前不存在承载 `M7` JSONL 六条流完整字段字典、目录分片规范及 `P10` 只读渲染兼容约定的独立支撑文档；若强制塞入 [`P8-KERNEL-CONSENSUS`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md) 或 [`P8-CAPITAL-CONFIG`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md) 将导致战略共识/资金配置与数据工程 schema 职责混杂，故按判据合规新建本支撑文档。
- **版本与表述纪律**：**`v1.0`（`2026-11-18` 当前决策 / 首期选择；月度复检可替换）**；本文件仅确立 `M7` 日志 schema、校验和与目录结构契约，不预先编写 `M10` 前台代码，不触碰 `src/pricing/` 锁定文件。

---

## 一、 `M7` 核心架构与防污染设计约束

1. **单一只读事实底座**：
   - `M7` 对生产/假盘运行时提供**异步只写追加（Append-Only JSONL）**接口，严禁同步阻塞下游下单路径；
   - `M7` 对校准复检（`M8` 经 **`P8`**）、假盘撮合回放（`M5` 经 **`P18`**）及前台只读界面（`M10` 经 **`P10`**）提供**严格只读**访问——严禁任何生产逻辑反向消费 `M7` 日志在线改参（防污染第一条）。
2. **四元组 + 气象/盘口双旁路全景**：
   - 决策核心四元组：**`P1 ScanDecisionEvent`**（`M4 → M7`）+ **`P3 ExecutionAttemptLog`**（`M5 → M7`）+ **`P17 ForecastSnapshotLog`**（`M2 → M7`）+ **`P19 CapitalEventLog`**（`M6 → M7`）；
   - 输入保障旁路：**`P12 CoverageLedgerLog`**（`M1 → M7`）+ **`P13 MarketBookRecordEnvelope`**（`M3 → M7`）。
3. **身份隔离与双哈希溯源（`§六 E.2`）**：
   - 全部 6 条流均强制携带 `session_id: str` 与 `execution_mode: Literal["PAPER", "LIVE"]`（仅 `P13` 允许单独的 `capture_mode = "PASSIVE_RECORD"`），严禁假盘记录混入真盘绩效统计；
   - 四元组与 `P12` 强制同时打点 **`model_hash`**（预测模型本体指纹，假盘上线日冻结）与 **`config_hash`**（`P6` 执行策略包指纹），实现任意单笔决策到模型版本与政策版本的可重现追溯。
4. **单行完整性校验（`record_sha256`）**：
   - 每条 JSONL 记录末尾携带 `record_sha256: str`（64 位十六进制 lowercase SHA256），计算输入为**去除 `record_sha256` 键后按键名字典序序列化之紧凑 UTF-8 JSON 字符串（`separators=(",", ":")`, `ensure_ascii=False`）**；写入方计算并写入，离线审计/回放/前端聚合端校验并统计损坏行（严禁静默吞并坏行）。

---

## 二、 `M7` 六条 JSONL 流协议正文（`v1.0` · `2026-11-18`）

### 2.1 `P1 ScanDecisionEvent`（`M4 → M7`）

- **语义**：双钟（信息钟 `INFO_CLOCK` / 价格钟 `PRICE_CLOCK`）每次扫描对单个 `(station_id, target_date, bin_id)` 档位产生**恰好一条**事件记录——**无论是否下单均落盘**，为 `D-1` 盈利性检验与分时段空转率计算保留完整负样本池。
- **字段契约**：

| 字段名 | 类型 | 必填 | 说明与约束 |
| :--- | :--- | :---: | :--- |
| `schema_version` | `str` | ✓ | 固定 `"p1.v1"` |
| `decision_id` | `str` | ✓ | 全局唯一 UUIDv7 / ULID（`P3` 之外键锚） |
| `session_id` | `str` | ✓ | 运行会话唯一 ID |
| `execution_mode` | `Literal["PAPER", "LIVE"]` | ✓ | 强隔离标识 |
| `scan_clock` | `Literal["INFO_CLOCK", "PRICE_CLOCK"]` | ✓ | 触发该次扫描的时钟源 |
| `scan_ts_utc` | `str` (ISO-8601 UTC) | ✓ | 决策计算时刻 UTC |
| `station_id` | `str` | ✓ | ICAO 台站代码（必须属 Active 10） |
| `target_date` | `str` (`YYYY-MM-DD`) | ✓ | 站点当地目标气象日历日 |
| `target_type` | `Literal["TMAX", "TMIN"]` | ✓ | 极值标的极性 |
| `bin_id` | `str` | ✓ | 温度档位标识（如 `"58-59F"`） |
| `token_id` | `str` | ✓ | Polymarket YES outcome `token_id` |
| `market_id` | `str` | ✓ | Gamma 市场 ID |
| `model_hash` | `str` | ✓ | `M2` 预测本体冻结指纹 |
| `config_hash` | `str` | ✓ | `P6` 政策包指纹 |
| `policy_version` | `str` | ✓ | `P6.policy_version` |
| `policy_overdue` | `bool` | ✓ | 透传 `P6.is_overdue` 状态（`B6` 催办标） |
| `forecast_id` | `str` | ✓ | **外键指向 `P17`**，零冗余搬运全档分布数组 |
| `book_frame_ref` | `int` | ✓ | **`N2` 外键指向 `P4.frame_seq`**（盘口侧精确重放闭合键） |
| `best_ask_price` | `Optional[float]` | ✗ | 当帧卖一价；无卖盘时 `None` |
| `best_ask_edge` | `Optional[float]` | ✗ | 由 `edge_math.evaluate_book_edges` 产出（相对无量纲）；无卖盘 `None` |
| `m_threshold` | `float` | ✓ | `P6.RiskGatePolicy.m_threshold`（含费相对门限） |
| `tau_hours` | `float` | ✓ | `(T_settle_close_utc - scan_ts_utc) / 3600`（`>= 0.0`） |
| `b_budget_usd` | `float` | ✓ | 派生单市场日预算（来自 `P6.WPolicy.b_budget_usd`） |
| `w_tau` | `float` | ✓ | `w(tau)` 时间骨架输出 `[w0, 1.0]` |
| `s_edge` | `float` | ✓ | `s(edge)` 机会缩放输出 `[0.0, 1.0]` |
| `g_cap_usd` | `float` | ✓ | `b_budget_usd * w_tau * s_edge` |
| `held_usd` | `float` | ✓ | 经 `P7` 查询之当前已持仓市值 + 冻结中敞口 |
| `headroom_d` | `float` | ✓ | 可用增仓差额 `D`（受 `g_cap_usd - held_usd` 及 `M6` `B_eff` 兜底制约） |
| `decision_outcome` | 枚举（见下） | ✓ | **互斥五枚举** |
| `target_slice_usd` | `float` | ✓ | 当 `ORDERED` 时为 `P2` 计划切片额（`> 0`）；否则恒 `0.0` |
| `record_sha256` | `str` | ✓ | 整行完整性摘要 |

- **`decision_outcome` 互斥五枚举与空转率计算式**：
  - `"ORDERED"`：所有门槛通过，向 `M5` 下发 `P2 plan_slice`；
  - `"IDLE_BUDGET_EXHAUSTED"`：`best_ask_edge >= m_threshold`，但额度差额 `headroom_d <= 0` 或被 `M6` 站限/刹车阻断；
  - `"BLOCKED_BELOW_MIN_ORDER"`：`best_ask_edge >= m_threshold` 且 `headroom_d > 0`，但折算可下股数 `< min_order_size_shares` 或低于 `min_notional_usd`；
  - `"BLOCKED_NO_BOOK_DEPTH"`：`ask_book` 为空、`best_ask <= best_bid` 倒挂异常或无可用合格深度；
  - `"SKIP_EDGE_BELOW_M"`：`best_ask_edge < m_threshold`（含负 `edge`）。
  - **离线分时段空转率指标**：
    $$\text{IdleRate}(\tau\text{-bin}) = \frac{\text{count}(\text{outcome} = \texttt{IDLE\_BUDGET\_EXHAUSTED})}{\text{count}(\text{outcome} \in \{\texttt{ORDERED},\; \texttt{IDLE\_BUDGET\_EXHAUSTED},\; \texttt{BLOCKED\_BELOW\_MIN\_ORDER},\; \texttt{BLOCKED\_NO\_BOOK\_DEPTH}\})}$$

---

### 2.2 `P3 ExecutionAttemptLog`（`M5 → M7`）

- **语义**：记录每笔经 `P2 plan_slice` 发往假盘撮合器（`P18`）或实盘 CLOB 网关的下单尝试及终态，与 `P1` 通过 `decision_id` 成 **`1:N`** 关联（单次决策超额重切片/多单拆分可对应多条 `attempt_id`）。
- **核心字段与相对滑点定义（`N3` 对齐裁定 `B5`）**：

| 字段名 | 类型 | 必填 | 说明与约束 |
| :--- | :--- | :---: | :--- |
| `schema_version` | `str` | ✓ | 固定 `"p3.v1"` |
| `attempt_id` | `str` | ✓ | 本次发单尝试唯一 ID |
| `decision_id` | `str` | ✓ | 关联 `P1.decision_id` |
| `idempotency_key` | `str` | ✓ | 发单防重幂等键 |
| `session_id` | `str` | ✓ | 运行会话 ID |
| `execution_mode` | `Literal["PAPER", "LIVE"]` | ✓ | 强隔离标识 |
| `capture_replay_mode` | `Literal["NONE", "REPLAY_P13"]` | ✓ | 假盘是否由 `P13/P18` 延迟撮合 |
| `replay_source_seq_id` | `Optional[int]` | ✗ | 假盘成交匹配所命中之 `P13.seq_id` |
| `latency_injected_ms` | `Optional[int]` | ✗ | 假盘注入延迟毫秒数（实盘置 `None`） |
| `station_id` / `market_id` / `token_id` | `str` | ✓ | 目标市场身份 |
| `model_hash` / `config_hash` | `str` | ✓ | 双哈希溯源 |
| `decision_ts_utc` | `str` (ISO-8601 UTC) | ✓ | `M4` 决策快照时刻 |
| `decision_best_ask` | `float` | ✓ | 决策瞬间基准卖一价（来自 `P4`） |
| `decision_est_vwap` | `float` | ✓ | 决策瞬间沿 `AskBook` 预估吃深均价 |
| `decision_qual_depth_shares` | `float` | ✓ | 决策瞬间 `edge_j >= m` 总合格深度 |
| `order_type` | `Literal["IOC_FAK"]` | ✓ | 首期唯一允许单型（禁市价） |
| `limit_price` | `float` | ✓ | 保护限价（按 `tick_size` 向下对齐） |
| `target_shares` / `target_usd` | `float` | ✓ | 本次下单目标份额与名义额 |
| `submit_ts_utc` / `final_ts_utc` | `str` (ISO-8601 UTC) | ✓ | 发送时刻与终态确认时刻 |
| `terminal_status` | 枚举 | ✓ | `"FILLED" \| "PARTIAL" \| "CANCELLED_UNFILLED" \| "REJECTED" \| "PAPER_MATCH_ABORTED_GAP"` |
| `reject_or_abort_reason` | `Optional[str]` | ✗ | 拒单原报错误码或 `P18` gap 原因 |
| `filled_shares` / `filled_usd` | `float` | ✓ | 实际成交份额与成交美元成本 |
| `actual_avg_fill_price` | `Optional[float]` | ✗ | 无成交时 `None` |
| `fee_paid_usd` | `float` | ✓ | 实际/模拟扣除 taker 费用（无成交 `0.0`） |
| `fill_rate` | `float` | ✓ | `filled_shares / target_shares`（`∈ [0.0, 1.0]`） |
| **`slippage_vs_best_ask`** | `Optional[float]` | ✗ | **相对无量纲比例（`N3`）**：`(actual_avg_fill_price - decision_best_ask) / decision_best_ask`（未成交 `None`）；**直接作为 `RiskGatePolicy.friction_median` 校准输入** |
| **`slippage_vs_est_vwap`** | `Optional[float]` | ✗ | **相对无量纲比例**：`(actual_avg_fill_price - decision_est_vwap) / decision_est_vwap` |
| `record_sha256` | `str` | ✓ | 整行完整性摘要 |

---

### 2.3 `P17 ForecastSnapshotLog`（`M2 → M7`）

- **语义**：每次预测引擎推理（每站 × 每目标日 × 每次信息钟/触发更新）异步持久化一条 **`P5 ForecastDistributionSnapshot` 全量记录**；既是 `P1.forecast_id` 的外键宿主机，也是 **`P8` 校准样本流的唯一合法源头**（严禁 `M2` 旁路直写 `M8`）。
- **核心字段**：完整包含 `P5` 字段（`forecast_id`, `issue_ts_utc`, `station_id`, `target_date`, `target_type`, `gefs_lead_hours`, `tau_hours`, `settle_close_utc`, `model_hash`, `prior_mu0`, `prior_sigma0`, `family`, `m_now_f`, `is_bridge_active`, `p_stay`, `bin_probs` 列表、`sigma_delta_sample`），附加 `schema_version="p17.v1"`, `session_id`, `execution_mode`, `config_hash`, `record_sha256`。

---

### 2.4 `P19 CapitalEventLog`（`M6 → M7` · `N1` 新增）

- **语义**：记录 `M6` 资金与本地实时风控模块产生的一切资金变更与闸门状态跳变事件（填补 `M6` 此前唯一无落盘审计边的缺口）。
- **核心字段**：
  - `schema_version="p19.v1"`, `event_id: str`, `event_ts_utc: str`, `session_id: str`, `execution_mode: Literal["PAPER", "LIVE"]`, `station_id: Optional[str]`；
  - `event_type: Literal["FREEZE", "UNFREEZE", "FILL_SETTLE_CONVERSION", "STATION_LOSS_GATE_TRIP", "ACCOUNT_DRAWDOWN_BRAKE_TRIP", "LIGHT_LEVEL_APPLIED", "TIER_STEP_UP", "POLICY_OVERDUE_MARK", "GATE_LIVE_SWITCH"]`；
  - `light_status: Optional[str]`, `tier_pool_usd: Optional[float]`, `free_usd_after: float`, `active_locked_usd_after: float`, `station_realized_pnl_usd: Optional[float]`, `policy_version: str`, `config_hash: str`, `is_overdue: bool`, `related_ref_id: Optional[str]`（关联 `attempt_id` / `decision_id` / `P16 event_id`）, `reason: str`, `record_sha256: str`。

---

### 2.5 `P12` 气象 `CoverageLedgerLog`（`M1 → M7`）

- **语义**：一级审计制品，与每次模型/观测拉取同步落盘，杜绝静默缺测或陈旧 METAR 观测混入在线推导或事后评估。
- **核心字段**：`schema_version="p12.v1"`, `run_ts_utc`, `session_id`, `execution_mode`, `station_id`, `target_date`, `gfs_init_utc`, `gfs_available: bool`, `gfs_completeness_ratio: float`, `metar_source_mode`, `metar_obs_count_window: int`, `latest_obs_utc: Optional[str]`, `physical_age_sec: Optional[float]`, `dispatch_age_sec: Optional[float]`, `freshness_ok: bool`, `gap_flags: list[str]`, `model_hash`, `config_hash`, `record_sha256`。

---

### 2.6 `P13 MarketBookRecordEnvelope`（`M3 → M7` · `S1-05` 与 `C3` 锚点）

- **语义**：以标准信封包装 **`P4 MarketBookSnapshot`** 完整载荷（**严禁平铺复制第二套价格深度字段**），同一文件同时服务 **`M7` 审计沉淀** 与 **`P18` 假盘延迟回放撮合器**（双消费者铁律）。
- **信封外层与嵌套载荷契约**：
  - `schema_version: str`（固定 `"p13.v1"`）
  - `seq_id: int`（本次录制运行进程内严格单调递增，从 `1` 起步，每次断流或重启由 `session_id` + `seq_id` 唯一标识）
  - `session_id: str`
  - `capture_mode: Literal["PASSIVE_RECORD", "LIVE_STREAM", "PAPER_SHADOW"]`
  - `gap_detected: bool`（心跳超时、WS 断连重连期间或 REST 补拉探测到缺失窗口时置 `True`）
  - `gap_reason: Optional[str]`（如 `"WS_HEARTBEAT_TIMEOUT"`, `"WS_RECONNECT"`, `"REST_POLL_ERROR"`；无缺口时 `None`）
  - `recorded_ts_utc: str` (ISO-8601 UTC)
  - **`payload: dict`**（严格映射 [`P4 MarketBookSnapshot v1.0-rc`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#a1-p4-marketbooksnapshot-v10-rcm3--m4--m5--m7)：`token_id`, `market_id`, `condition_id`, `snapshot_ts_utc`, `recv_ts_utc`, `frame_seq`, `data_source`, `tick_size`, `min_order_size_shares`, `min_notional_usd`, `fee_rate`, `fee_rate_provenance`, `neg_risk`, `best_bid`, `asks`, `bids`, `bid_top10`，外层可附带 `station_id` / `target_date` / `bin_label` 只读路由标签）
  - `record_sha256: str`

---

## 三、 落盘目录结构与 `P10` (`M10`) 只读渲染兼容设计

### 3.1 目录分层契约（本地存储默认布局，切片 2 起按需配置路径前缀）

```text
data/
├── audit_logs/
│   └── <execution_mode>/                  # "PAPER" 或 "LIVE"，物理文件夹强隔离
│       └── <YYYY-MM-DD>/                  # 按 UTC 事件日分片，控制单文件体积
│           ├── p1_scan_decisions.jsonl
│           ├── p3_execution_attempts.jsonl
│           ├── p12_weather_coverage.jsonl
│           ├── p17_forecast_snapshots.jsonl
│           └── p19_capital_events.jsonl
└── market_recordings/
    └── <capture_mode>/                    # "PASSIVE_RECORD" | "PAPER_SHADOW" | "LIVE_STREAM"
        └── <YYYY-MM-DD>/
            └── <session_id>/
                └── p13_book_stream_<station_id>.jsonl
```

### 3.2 `P10`（`M7 → M10` 前台只读视图）兼容约束

1. **零独立数据库**：依据 [`项目方案 v3.0 §8.1`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#81-模块地图m1m10-十模块静态架构--2026-11-18-当前决策) 架构铁律，`M10` 不建立 SQLite/Postgres 业务状态库，所有视图（决策链路穿透、挂单/成交滑点审计、资金曲线、盘口回放检查）一律从 `data/audit_logs/` 与 `data/market_recordings/` 只读读取聚合；
2. **统一联结键**：全部流共享 `(execution_mode, session_id, station_id, target_date)`；跨表钻取通过 `P1.decision_id == P3.decision_id`、`P1.forecast_id == P17.forecast_id`、`P1.book_frame_ref == P13.payload.frame_seq`（同 `(session_id, token_id)`）及 `P19.related_ref_id` 完成；
3. **尾部并发读安全**：读取器按逐行扫描，若遇未以 `\n` 结尾的末尾未写完行直接跳过或忽略当行，并通过 `record_sha256` 标记损坏率面板；
4. **结算视图延迟兼容**：在 `P9`（`M9 → M7/M8`）待 `ADR` 裁决后落盘之前，`M10` 结算对账面板显式降级为 `"PENDING_P9"` 状态，不影响决策/执行/资金视图渲染。

---

## 四、 `P4` 升版联动核对注记（`C3` 协议治理执行）

本文件已确立 `P13` 信封（`§2.6`）与 `M7` 审计目录约定；后续任何对 `P4 MarketBookSnapshot` 字段集或语义的升版，必须同步核查本文档 **`§2.6 payload` 映射**、`M3` 序列化器及 `M5` **`P18` 回放撮合解析器**。
