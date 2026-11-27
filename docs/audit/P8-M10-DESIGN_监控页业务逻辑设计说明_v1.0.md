# P8-M10-DESIGN：M10 监控页业务逻辑设计说明（`v1.0`）

- **版本状态注记**：`v1.0`（`2026-11-24` 初建；`2026-11-27` 已对齐 `Batch 2b` 浅色股票终端 UI 改版与懒加载多维筛选；`2026-11-28` 补齐 `/decision` 独立详情页、卡片 1/4 双口径防误导展示及 `_derive_model_hash` 现行实态对齐；历史 `§1–§8` 原文保持冻结不回改）
- **治理与任务编号**：`P8-M10-DESIGN`｜对应交付任务：**`S3-10`**（`M10` 前台管理界面 `v1`）｜派工单：**`P8-WO-20261123-M10-DOC-DESIGN-v2`**
- **法定锚点**：[`项目方案 (v3.0) §8.1 M10`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#81-模块地图m1m10-十模块静态架构--2026-11-18-当前决策)、[`P8-T2-M7-LOGGING v1.1 §2.2/§2.7/§3.2`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#32-p10m7--m10-前台只读视图兼容约束与正式查询契约v11--s2-04-正文冻结)、[`P8-PROJECT-TASKS v2.5 §2 S3-10`](P8-PROJECT-TASKS_全量任务分解台账.md)
- **命名与新建文档准入依据（[`项目编号与命名规范 v1.1 §6.5 / §9`](../项目编号与命名规范_20261021.md#6-现役衍生编号与文件--工单命名总表v11-新增)）**：
  1. 文件名按 `§6.5` 治理/架构/设计文档模板 `docs/audit/P<批次>-<THEME>_<中文主题>_v<X.Y>.md` 定名（批次 `P8`、主题短码 `M10-DESIGN`、版本号 `v1.0`）；
  2. 按 `§9` 文件增殖判据核验：全仓此前无独立承载 `M10 v1` 聚合口径、派生状态机、HTML 安全防线及缺陷修复审计的文档，若强行塞入 `P8-T2-M7-LOGGING`（协议规格）或 `P8-PROJECT-TASKS`（任务台账）将导致协议定义与前台视图设计混杂；经业主直接指令及 `P8-WO-20261123-M10-DOC-DESIGN-v2` 批复准入，并在 `P8-PROJECT-TASKS §1 M10`、`§2 S3-10` 与 `§6` 建立可达指针；
  3. **代码事实基准**：本文档全部规则、阈值、函数名与测试名严格对齐阶段一修复后仓库 `HEAD` 代码实态（[`src/ui/m10_view.py`](../../src/ui/m10_view.py)、[`scripts/render_m10_dashboard.py`](../../scripts/render_m10_dashboard.py)、[`src/audit/p10_reader.py`](../../src/audit/p10_reader.py)、[`tests/unit/ui/test_m10_s310_readonly_view.py`](../../tests/unit/ui/test_m10_s310_readonly_view.py)）。

---

## §1 数据流全景与五区块界面映射

`M10 v1` 严格遵循 **“零独立业务数据库、零反向写回 `M7` / `recordings`、静态离线纯展示”** 架构铁律，完整数据流如下：

```text
只读输入源                                  M7 只读聚合层                  M10 视图模型层                       静态 HTML 五区块
─────────────────────────────────────────  ────────────────────────────   ────────────────────────────────   ──────────────────────────────────
data/audit_logs/<PAPER|LIVE>/<YYYY-MM-DD>/
  ├── p1_scan_decisions.jsonl      ──┐
  ├── p3_execution_attempts.jsonl  ──┤
  ├── p9_settlement_truths.jsonl   ──┼─▶ query_p10_session_view() ──▶ P10SessionView
  ├── p12_weather_coverage.jsonl   ──┤     (SHA-256 校验 / 尾行跳过 /      │
  ├── p17_forecast_snapshots.jsonl ──┤      joined_chains P1↔P17/P13/P3)   ▼
  └── p19_capital_events.jsonl     ──┘                                 build_m10_dashboard_model() ──▶ render_m10_dashboard_html()
                                                                           │                             ├── Banner: PAPER 灰 / LIVE 红
[可选] data/market_recordings/.../p13_*.jsonl ─▶ _index_p13_frames() ──────┤                             ├── 区块1: 常驻只读“风险参数面板”
                                                                           │                             ├── 区块2: M7 完整性/双哈希/PnL 汇总
configs/clob_gateway.yaml ───▶ load_gateway_safety_config() ───────────────┤                             ├── 区块3: 投决全链路表 (P1→P17/P13/P3)
                                                                           │                             ├── 区块4: M9 官方结算与盈亏对账表
daily_ledger_path JSON ──────▶ _read_daily_used_readonly() ────────────────┘                             └── 区块5: M6 资金账本事件表 (P19)
```

### 1.1 视图模型 `M10DashboardModel` 与页面五区块映射

[`M10DashboardModel`](../../src/ui/m10_view.py#L32-L53) 为不可变 `@dataclass(frozen=True)`，各字段与 [`render_m10_dashboard_html`](../../src/ui/m10_view.py#L328-L521) 区块对应关系如下：

1. **顶部模式横幅 + 区块 1（常驻全只读“风险参数面板”）**：消费 `model.risk_panel`（[`GatewayRiskPanelSnapshot`](../../src/execution/clob_gateway.py)），展示 `execution_mode`（`mode-banner-paper` / `mode-banner-live`）、`max_single_order_usd`、`max_daily_cumulative_usd`、`daily_used_usd`、`daily_remaining_usd`、`circuit_open` + `consecutive_failures`、`light_status`、`model_hash` + `model_frozen`、`safety_config_sha256`。（`2026-11-28 Batch 2b 实态对齐`：在卡片 4 UI 展示层中，若 `PAPER` 态下网关日账本缺失/`$0` 而存在 `P3` 模拟成交，则以模拟成交额对照 `\$250` 上限渲染并在超限时亮出 `超试单日限`、副行标注 `网关账本 $0 · P18 未走 CLOB 网关`；底层 `risk_panel.daily_used_usd` 字段仍严格保持读取网关日账本的原始口径不变；多模型指纹统一于卡片 4 收起显示计数及最新 10 位哈希、完整列表置底部抽屉。）
2. **区块 2（`M7 Audit Integrity, Dual Hashes & PnL Summary`）**：消费 `render_status`、`settlement_status`、`tail_status`、`valid_lines`、`corrupt_count`、`partial_tail_count`、`missing_forecast_fk_count`、`policy_overdue_count`、`total_filled_usd`、`total_fee_paid_usd`、`total_realized_pnl_usd`、`config_hashes`、`model_hashes`。
3. **区块 3（`Decision-to-Execution Trace (P1 -> P17 / P13 / P3)`）**：消费 `model.decision_rows`，逐条展示 16 列投决到成交与网关阶段全过程。
4. **区块 4（`M9 Official Settlement & M6/P15 Reconciliation`）**：消费 `model.settlement_rows` 与 `model.settlement_status`，展示 `M9 P9` 中奖档位、真值源与含费盈亏对账结果；无 `P9` 时保持降级占位提示。
5. **区块 5（`M6 Capital Ledger Events (P19)`）**：消费 `model.p19_rows`（直接引用 `view.p19_events`），按行展示灯级应用、预冻结、成交转换、站损/回撤门禁及变动后余额。

---

## §2 全部派生规则与计算口径

### 2.1 日额度派生（[`_read_daily_used_readonly`](../../src/ui/m10_view.py#L65-L74)）

1. 先决定对账 UTC 日期 `ledger_day`：优先取显式入参 `utc_date`；未传时若传入 `date_range` 则取 `date_range[1]`；均未传则取 `datetime.now(timezone.utc).date()`。
2. 只读读取 `safety.daily_ledger_path`（JSON 字典 `{YYYY-MM-DD: str_decimal}`）：若文件不存在、JSON 解析异常或非 `dict`，回退为 `Decimal("0")`。
3. 计算当日额度：
   - `daily_used_usd = Decimal(raw.get(ledger_day.isoformat(), "0"))`
   - `daily_remaining_usd = max(Decimal("0"), safety.max_daily_cumulative_usd - daily_used_usd)`
4. **`2026-11-28 Batch 2b` 双口径防误导展示注记**：`risk_panel.daily_used_usd` 严格保持从网关日账本文件读取的原始口径；在页面卡片 4 渲染层，当 `PAPER` 态网关账本缺失或为 `$0` 而同期存在 `P3` 模拟成交时，页面额外以模拟成交累计额对照 `\$250` 上限（超限显示 `超试单日限` 提示），并在副行明示 `网关账本 $0 · P18 未走 CLOB 网关`，防止误判假盘无耗用。

### 2.2 熔断事件重放状态机（[`_derive_circuit_status`](../../src/ui/m10_view.py#L77-L96)）

初始状态 `(circuit_open=False, consecutive_failures=0)`，按 `view.p3_events` 顺序扫描 `schema_version == "p3.gateway.v1"` 网关事件：

| `stage` | `details.action` | 状态转移 |
| :--- | :--- | :--- |
| `CIRCUIT_BREAKER` | `"TRIPPED"` | `circuit_open = True`；`consecutive_failures = int(details.get("consecutive_failures", consecutive_failures or 5))` |
| `CIRCUIT_BREAKER` | `"MANUAL_RESET"` | `circuit_open = False`；`consecutive_failures = 0` |
| `EXCEPTION` | — | `consecutive_failures += 1` |
| `CLOB_SUCCESS` | — | `consecutive_failures = 0` |

### 2.3 三色信号灯优先级链（[`_derive_light_status`](../../src/ui/m10_view.py#L99-L109)）

1. **第一优先级（`M6 / P19` 资金侧落盘应用事件）**：顺序遍历 `view.p19_events`，取最后一条满足 `event_type == "LIGHT_LEVEL_APPLIED"` 且 `light_status` 非空事件的 `light_status`。
2. **第二优先级（`M4 / P1` 决策侧快照标签）**：若 `P19` 未命中，顺序遍历 `view.p1_events`，取最后一条 `light_status` 非空记录。
3. **空值回退**：两处均无时返回 `None`，HTML 页面中以 `"UNSET"` 展示。

### 2.4 `model_hash` 与 `model_frozen` 口径（含 `LIVE` 前重审注记）

1. `model_hash` 推导（[`_derive_model_hash`](../../src/ui/m10_view.py#L112-L121)）：显式参数 `model_hash` 优先；否则逆序取最新 `view.p1_events` 的 `model_hash`；再否则逆序取最新 `view.p17_snapshots` 的 `model_hash`；均无返回 `None`。（**`2026-11-28 Batch 2b` 现行修正**：兼容 `IncrementalAuditCache` 倒序缓存场景，改按最大 `scan_ts_utc` / `issue_ts_utc` 确定最新记录提取 `model_hash`；同时针对 `live_p5_producer.py` 多站多提前量产生多个冻结模型指纹的实态，卡片 4 在存在多个哈希时收起展示「`多模型指纹共 N 个 (最新 <10位>… · 默认 FROZEN)`」，完整指纹列表统一置于底部审计抽屉。）
2. **`model_frozen` 调用侧声明语义（重要诚实口径）**：
   - `M10 v1` **当前不从 `M7` JSONL 自动读取或反推模型冻结状态**（`P1`/`P17` 协议本身不携带 `model_frozen` 布尔字段），完全由调用侧显式声明：
     - 库接口 `build_m10_dashboard_model`：传入 `risk_panel_override` 时直接沿用 `risk_panel_override.model_frozen`；否则直接写入形参 `model_frozen: bool = True`。
     - CLI `scripts/render_m10_dashboard.py`：由开关 `--model-unfrozen` 控制 `model_frozen=not args.model_unfrozen`（默认 `FROZEN`，传入 `--model-unfrozen` 时渲染 `UNFROZEN`）。
   - **`LIVE` 上线前强制重审注记**：上述调用侧显式传入语义适用于 `S3-10 / S3-11` `PAPER` 试运行；**在 `S3-12 GATE-LIVE` 切真盘前，必须重审 `model_frozen` 推导口径**（例如由 `M8`/模型注册表持久化冻结清单并作为只读输入接入，避免人为漏传 `--model-unfrozen` 造成假阳性 `FROZEN` 展示）。

### 2.5 `P1 → P3` `1:N` 聚合与终态收敛规则（[`_build_decision_rows`](../../src/ui/m10_view.py#L148-L202) & [`_resolve_consolidated_terminal_status`](../../src/ui/m10_view.py#L124-L145)）

遵循 `P8-T2-M7-LOGGING §2.2`（`P1` 与 `P3` 通过 `decision_id` 成 `1:N` 关联），对每条 `DecisionJoinChain` 执行：

1. **流分离**：遍历 `chain.p3_records`，`schema_version == "p3.gateway.v1"` 的记录提取 `stage` 并按序拼接为 `gateway_stages`（` -> ` 分隔，空则 `"-"`）；其余记录归入 `attempt_recs`（`p3.v1 ExecutionAttemptLog`）。
2. **数值累加（`Decimal` 精确求和）**：
   - `filled_shares = sum(_to_decimal(a.get("filled_shares")) for a in attempt_recs)`
   - `filled_usd = sum(_to_decimal(a.get("filled_usd")) for a in attempt_recs)`
   - `fee_paid_usd = sum(_to_decimal(a.get("fee_paid_usd")) for a in attempt_recs)`
   - `attempt_count = len(attempt_recs)`
3. **决策级终态收敛（`_resolve_consolidated_terminal_status`）**：
   - 先按 `(final_ts_utc or submit_ts_utc, 原始索引)` 稳定排序 `attempt_recs`；
   - `0` 条尝试 → `"-"`；`1` 条尝试 → 直接取该条 `terminal_status`；
   - `>= 2` 条尝试（设末条状态为 `last_status`）：
     - `last_status == "FILLED"` → `"FILLED"`（如首片 `PARTIAL`、重切片补足后末片 `FILLED`）；
     - `total_filled_shares > 0`（如首片 `PARTIAL`、次片 `CANCELLED_UNFILLED` 或 `REJECTED`）→ `"PARTIAL"`（避免以末片未成状态掩盖实际已成持仓）；
     - 其余零成交场景 → 取 `last_status`。
4. **外键与元数据提取**：抽取 `session_id`、`station_id`、`target_date`、`target_type`、`market_id` 供下游 `P9` 精确绑定；`book_frame_ref` 直接读自 `P1.book_frame_ref`。

### 2.6 `P9` 结算绑定、盈亏对账公式与跨 UTC 日界关联理由（[`_build_settlement_rows`](../../src/ui/m10_view.py#L219-L287)）

1. **跨 UTC 日界关联设计及理由**：
   - 站点目标日 `D`（如 `KORD 2026-11-23`）的法定日终锁窗在当地次日凌晨（对应 UTC `2026-11-24T06:00Z` 以后），因此 `M9` 结算真值 `p9_settlement_truths.jsonl` 必然落盘在 **`D+1` 的 UTC 分片目录**下；同时 `P3 ExecutionAttemptLog` 与 `P19 CapitalEventLog` 结构本身不含 `target_date` 键。
   - 故 [`build_m10_dashboard_model`](../../src/ui/m10_view.py#L298-L320) 仅将 `utc_date` 用于读取当日日账本（`ledger_day`），而向 `P10Query` 传入 `date_range=date_range` 与 `target_date=None`，避免将目录扫描收窄至单日或误过滤无 `target_date` 字段的 `P3/P19` 流，保障 `D` 日投决链与 `D+1` UTC 凌晨 `P9` 结算同屏闭合。
2. **按 `P9.settlement_id` 构成要素精确绑定（[`_matches_p9_settlement_scope`](../../src/ui/m10_view.py#L205-L216)）**：
   - 依 `P8-T2-M7-LOGGING §2.7`，`P9.settlement_id` 由 `(session_id, station_id, target_date, target_type, market_id)` 五元组确定性 `uuid5` 生成；
   - `_build_settlement_rows` 先对非空 `settlement_id` 去重（幂等保护），再以**五要素全等 + `filled_shares > 0`** 精确匹配 `decision_rows`，彻底隔离同站同日不同 `market_id`、`TMAX` vs `TMIN` 及不同会话的成交记录。
3. **盈亏对账公式**：
   - `payout_usd = sum(r["filled_shares"] for r in matched_decisions if r["bin_id"] == winning_bin_id)`（二元市场赢档每份兑付 `$1`）
   - `cost_basis_usd = sum(r["filled_usd"] + r["fee_paid_usd"] for r in matched_decisions)`（对齐 `S3-14 P14` 含费实花成本基）
   - 若 `matched_decisions` 非空：`realized_pnl_usd = payout_usd - cost_basis_usd`
   - 否则若存在 `p15_by_ref.get(settlement_id)` 且 `station_realized_pnl_usd` 非空：回退取该值；再否则 `Decimal("0")`
   - `reconciled = bool(matched_decisions) or (p15 is not None)`
   - `total_realized_pnl_usd = sum(row["realized_pnl_usd"] for row in settlement_rows)`

---

## §3 三个状态机与降级阈值

全部三个状态机由 [`query_p10_session_view`](../../src/audit/p10_reader.py#L218-L255) 判定并由 `build_m10_dashboard_model` 原样透传：

| 状态机 | 枚举值 | 精确触发条件与判定优先级 |
| :--- | :--- | :--- |
| **`render_status`** | `"DEGRADED_CORRUPT_LINES"`<br>`"NO_AUDIT_RECORDS"`<br>`"OK"` | **优先级 1**：全扫描目录下 6 条流任意存在 **`>= 1` 条损坏行**（`bool(corrupt)`，已 `\n` 结尾但 JSON 解析失败或 `record_sha256` 校验失败，在 `_matches_query` 过滤前汇总）→ `DEGRADED_CORRUPT_LINES`；<br>**优先级 2**：无坏行，且模式目录缺失 / 日目录列表为空 / 过滤后 `matched_valid == 0` → `NO_AUDIT_RECORDS`；<br>**优先级 3**：无坏行且 `matched_valid > 0` → `OK`。 |
| **`tail_status`** | `"CONCURRENT_TAIL_SKIPPED"`<br>`"NONE"` | 扫描 6 条流时，任一文件末行**不以 `\n` 结尾**即计入 `partial_tail_skipped_lines`；当总数 `> 0` 时置为 `"CONCURRENT_TAIL_SKIPPED"`，否则 `"NONE"`（不导致 `render_status` 降级）。 |
| **`settlement_status`** | `"READY"`<br>`"PENDING_P9"` | 当过滤后 `by_stream.get("p9")` 非空（`>= 1` 条已验证 `P9` 记录）→ `"READY"`；否则 → `"PENDING_P9"`（仅降级结算表占位提示，不影响其余 4 个区块展示）。 |

---

## §4 三层只读安全防线

1. **静态 AST 与源码写入禁令（`src/ui/*.py`）**：
   - 禁止导入数据库或交易客户端库：`sqlite3`、`sqlalchemy`、`psycopg`、`py_clob_client`；
   - 源码全文禁止出现 `.write(`、`.unlink(`、`.mkdir(`、`open(..., "w")`、`open(..., "a")`，由 [`test_m10_ast_zero_database_zero_write_and_cli_render`](../../tests/unit/ui/test_m10_s310_readonly_view.py) 每次 CI 静态 AST 强制校验。
2. **HTML 零交互 / 零外部依赖 / 按态互斥横幅禁令（`2026-11-27` 依业主路线 2 裁决增补本地实时轮询特例）**：
   - 离线导出 HTML（[`scripts/render_m10_dashboard.py`](../../scripts/render_m10_dashboard.py)）及实时页暂停态（`refresh=0`）仍严格禁止 `<form`、`<button`、`<input`、`<select`、`<textarea`、`<script`、`fetch(`、`xmlhttprequest`、`cdn.`；
   - 仅当本地只读服务（[`scripts/serve_m10_live.py`](../../scripts/serve_m10_live.py)）处于自动刷新态（`refresh > 0`）时，允许内联唯一标有 `data-m10-live-poll="1"` 的同源只读微脚本（`fetch(window.location.href, { cache: "no-store" })`），用于只更新 `#m10-live-root` 数据并保留所有 `<details[id]>` 展开状态与滚动条位置；仍严禁外链脚本、`cdn.`、表单输入或任何写请求方法。
   - 所有动态字段统一经 `html.escape(..., quote=True)` 转义；
   - `render_m10_dashboard_html` 仅内联当前 `execution_mode` 对应的横幅 CSS（`PAPER` 态仅生成 `.mode-banner-paper` 且绝对不含 `mode-banner-live`；`LIVE` 态仅生成 `.mode-banner-live`）。
3. **CLI 输出路径隔离守卫（[`scripts/render_m10_dashboard.py#L54-L57`](../../scripts/render_m10_dashboard.py#L54-L57)）**：
   - 解析 `audit_root.resolve()` 与 `output.resolve()`，若 `out_resolved == audit_resolved` 或 `audit_resolved in out_resolved.parents`，立即抛 `ValueError` 中止写盘，物理杜绝渲染输出污染 `M7` 审计日志目录。

---

## §5 边界情形汇总

| 边界情形 | 代码实态处理机制 |
| :--- | :--- |
| **同 `(station, target_date)` 多笔 `P9`** | `_matches_p9_settlement_scope` 按 `(session_id, station_id, target_date, target_type, market_id)` 五要素精确绑定，并对重复 `settlement_id` 去重，杜绝跨市场/跨标的/重复记录的盈亏双算。 |
| **单决策 `1:N` 多次部分成交/拆单** | `_build_decision_rows` 累加全部 `p3.v1` 尝试的 `filled_shares / filled_usd / fee_paid_usd`，并经 `_resolve_consolidated_terminal_status` 给出合并终态（`PARTIAL+FILLED→FILLED`，`PARTIAL+CANCELLED→PARTIAL`）。 |
| **损坏行（坏 JSON / SHA-256 不匹配）** | 仅对已 `\n` 结尾行判定，隔离入 `corrupt_lines` 计入 `corrupt_count` 并置 `render_status="DEGRADED_CORRUPT_LINES"`，其余合法行仍正常渲染不中断。 |
| **并发未换行尾行** | `read_verified_jsonl_file` 跳过无 `\n` 结尾行并计入 `partial_tail_skipped_lines`（`tail_status="CONCURRENT_TAIL_SKIPPED"`），无锁并发安全、不计入损坏行。 |
| **空目录 / `M7` 或日账本文件缺失** | `query_p10_session_view` 返回 `NO_AUDIT_RECORDS + NONE + PENDING_P9`；`_read_daily_used_readonly` 返回 `0`；HTML 正常渲染空表提示及风险参数面板。 |
| **`P1.forecast_id` 断链** | 非 `"MISSING*"` 开头的 `forecast_id` 在 `p17` 中未命中时递增 `missing_forecast_fk_count`；显式 `"MISSING*"` 缺测占位符按规则豁免不计入缺失。 |

---

## §6 管控席八问（`Q1–Q8`）逐项代码实态答复

### 6.1 Q1：`DEGRADED_CORRUPT_LINES` 的触发阈值
- **代码实态**：触发阈值为 **`>= 1` 条损坏行**（`bool(corrupt)` 为真）。[`read_verified_jsonl_file`](../../src/audit/p10_reader.py#L89-L114) 对任何以 `\n` 结尾的完整行执行 `json.loads` 与 `verify_record_sha256_line`，任一失败即记入 `CorruptLineRecord`（`JSON_ERROR:...` 或 `SHA256_MISMATCH`）。[`_read_all_mode_streams`](../../src/audit/p10_reader.py#L147-L161) 在 `_matches_query` 过滤**之前**收集扫描范围内 6 条流的全部坏行，故即使损坏行落在当前筛选站外或有效匹配为 `0`，[`query_p10_session_view`](../../src/audit/p10_reader.py#L233-L237) 仍优先返回 `"DEGRADED_CORRUPT_LINES"`；[`build_m10_dashboard_model`](../../src/ui/m10_view.py#L363-L378) 原样透传 `render_status` 与 `corrupt_count`。
- **对应函数与测试**：函数 `read_verified_jsonl_file`、`_read_all_mode_streams`、`query_p10_session_view`、`build_m10_dashboard_model`；测试 [`test_p10_reader_degradation_filter_empty_tail_and_corrupt_quarantine`](../../tests/unit/audit/test_m7_audit_and_replay.py#L144-L173)。

### 6.2 Q2：`tail_status=CONCURRENT_TAIL_SKIPPED` 的确切语义、触发条件，及与 `corrupt_count` 的分工
- **代码实态**：
  1. 触发条件：[`read_verified_jsonl_file`](../../src/audit/p10_reader.py#L99-L101) 检测 `if not raw.endswith("\n")`，将尚未写完换行符的并发半行跳过并累加 `partial_tail_skipped_lines`；[`query_p10_session_view`](../../src/audit/p10_reader.py#L238) 在 `tail_cnt > 0` 时将 `tail_status` 置为 `"CONCURRENT_TAIL_SKIPPED"`（否则 `"NONE"`），`build_m10_dashboard_model` 透传 `tail_status` 与 `partial_tail_count` 至区块 2。
  2. 分工边界：`tail_status / partial_tail_count` 专管**无 `\n` 结尾**的正常并发追加尾行（无锁读取、不降级 `render_status`）；`corrupt_count / DEGRADED_CORRUPT_LINES` 专管**已有 `\n` 结尾**但 JSON 或 SHA-256 异常的已落地损坏行。
- **对应函数与测试**：函数 `read_verified_jsonl_file`、`query_p10_session_view`、`build_m10_dashboard_model`、`render_m10_dashboard_html`；测试 [`test_p10_reader_degradation_filter_empty_tail_and_corrupt_quarantine`](../../tests/unit/audit/test_m7_audit_and_replay.py#L144-L173)。

### 6.3 Q3：`missing_forecast_fk_count` 的判定规则
- **代码实态**：在 [`_build_join_chains`](../../src/audit/p10_reader.py#L180-L206) 中，先用当前匹配的 `p17` 记录构建 `fc_by_id = {r.get("forecast_id"): r ...}`，再逐条检查 `p1` 的 `fc_id = r1.get("forecast_id")`；**当且仅当** `isinstance(fc_id, str) and not fc_id.startswith("MISSING") and fc_by_id.get(fc_id) is None` 时递增 `missing_fk`（即显式 `"MISSING*"` 占位符豁免，非占位符却丢失 `P17` 快照则计数）。`build_m10_dashboard_model` 原样透传至 `missing_forecast_fk_count` 并在 HTML 区块 2 渲染。
- **对应函数与测试**：函数 `_build_join_chains`、`query_p10_session_view`、`build_m10_dashboard_model`；测试 [`test_m10_missing_forecast_fk_count_positive`](../../tests/unit/ui/test_m10_s310_readonly_view.py)（直接断言 `fc-missing-p17` 计 `1` 而 `"MISSING_FORECAST"` 豁免且页面显示 `1`）及 [`test_m10_full_chain_settlement_reconcile_and_paper_risk_panel`](../../tests/unit/ui/test_m10_s310_readonly_view.py#L83-L233)（归零路径）。

### 6.4 Q4：`model_frozen`（`FROZEN`/`UNFROZEN`）的推导来源与规则
- **代码实态**：**当前不从 `M7` JSONL 自动推导**，完全由调用侧显式声明：① [`build_m10_dashboard_model`](../../src/ui/m10_view.py#L290-L343) 传 `risk_panel_override` 时沿用其 `model_frozen`，否则采用形参 `model_frozen: bool = True`；② [`scripts/render_m10_dashboard.py`](../../scripts/render_m10_dashboard.py#L46-L50,L69) 由命令行参数 `--model-unfrozen` 决定 `model_frozen=not args.model_unfrozen`（默认 `FROZEN`，传 `--model-unfrozen` 渲染 `UNFROZEN`）。注：进入 `S3-12 LIVE` 前须重审接入只读冻结清单源。
- **对应函数与测试**：函数 `build_m10_dashboard_model`、`render_m10_dashboard_html`、`scripts/render_m10_dashboard.py:main`；测试 [`test_m10_full_chain_settlement_reconcile_and_paper_risk_panel`](../../tests/unit/ui/test_m10_s310_readonly_view.py#L219) 及 [`test_m10_live_mode_red_banner_circuit_open_and_empty_degraded_safety`](../../tests/unit/ui/test_m10_s310_readonly_view.py#L252)。

### 6.5 Q5：`p12`/`p13` 在页面中的角色与呈现位置
- **代码实态**：
  1. `p12`（`p12_weather_coverage.jsonl`）：在 `query_p10_session_view` 中完成扫描与 SHA-256 校验，**直接贡献** `valid_lines`、`corrupt_lines`、`partial_tail_skipped_lines` 与 `render_status/tail_status`，原样保留于 `view.p12_ledgers`；**在当前 `v1` HTML 页面中未单独开辟 `P12` 列表表格**，仅通过区块 2 完整性计数器与状态指标体现。
  2. `p13`（`p13_book_stream_<station>.jsonl`）：当传入 `p13_root` 时，[`_index_p13_frames`](../../src/audit/p10_reader.py#L164-L177) 按 `(session_id, token_id, frame_seq)` 建索引（不计入 `M7` `valid_lines`/`corrupt_lines`），[`_lookup_p13_for_p1`](../../src/audit/p10_reader.py#L209-L215) 命中后挂入 `chain.p13_record`，[`_build_decision_rows`](../../src/ui/m10_view.py#L170-L172) 写入 `book_frame_ref`（直接取 `P1.book_frame_ref`）与 `p13_ref_present`；**在 HTML 区块 3 表格中呈现 `book_frame` 列（`book_frame_ref` 帧号）**，当前 `v1` 未展开盘口档位明细亦未单列 `p13_ref_present`。
- **对应函数与测试**：函数 `_read_all_mode_streams`、`_index_p13_frames`、`_lookup_p13_for_p1`、`_build_decision_rows`、`render_m10_dashboard_html`；测试 [`test_p10_reader_degradation_filter_empty_tail_and_corrupt_quarantine`](../../tests/unit/audit/test_m7_audit_and_replay.py#L144-L173)、[`test_p13_reader_handles_partial_tail_and_probes_gap_abort`](../../tests/unit/audit/test_m7_audit_and_replay.py#L176-L203)、[`test_m10_full_chain_settlement_reconcile_and_paper_risk_panel`](../../tests/unit/ui/test_m10_s310_readonly_view.py#L83-L233)。

### 6.6 Q6：同 `(station, target_date)` 多笔 `P9` / 单决策多次部分成交回环时 `settlement_rows` 的匹配与聚合规则
- **代码实态（阶段一修复后）**：
  1. **单决策 `1:N` 多次部分成交/拆单**：[`_build_decision_rows`](../../src/ui/m10_view.py#L148-L202) 收集全部非 `p3.gateway.v1` 尝试入 `attempt_recs`，对 `filled_shares`、`filled_usd`、`fee_paid_usd` 执行 `Decimal` 求和累加，记录 `attempt_count`，并通过 [`_resolve_consolidated_terminal_status`](../../src/ui/m10_view.py#L124-L145) 按时间序收敛决策级终态（`PARTIAL+FILLED→FILLED`；`PARTIAL+CANCELLED_UNFILLED→PARTIAL`）。
  2. **同 `(station, target_date)` 多笔 `P9`**：[`_build_settlement_rows`](../../src/ui/m10_view.py#L219-L287) 先按非空 `settlement_id` 去重防重算，再经 [`_matches_p9_settlement_scope`](../../src/ui/m10_view.py#L205-L216) 以 `P9.settlement_id` 全部五项构成键 **`(session_id, station_id, target_date, target_type, market_id)` + `filled_shares > 0`** 精确绑定 `decision_rows`；对匹配集计算 `payout_usd - cost_basis_usd`（赢档按 `bin_id == winning_bin_id` 计 `$1/share`，成本含 `fee_paid_usd`），无成交匹配时回退匹配 `P19 related_ref_id`，消除跨 `P9` 重复计入 `total_realized_pnl_usd`。
- **对应函数与测试**：函数 `_resolve_consolidated_terminal_status`、`_build_decision_rows`、`_matches_p9_settlement_scope`、`_build_settlement_rows`；测试 [`test_m10_single_decision_multiple_partial_p3_attempts_aggregated`](../../tests/unit/ui/test_m10_s310_readonly_view.py) 与 [`test_m10_multiple_p9_same_station_date_bound_by_market_session_type_no_double_count`](../../tests/unit/ui/test_m10_s310_readonly_view.py)。

### 6.7 Q7：`decision_rows` 中 `gateway_stages` / `book_frame` / `terminal` 的取数口径
- **代码实态（[`_build_decision_rows`](../../src/ui/m10_view.py#L148-L202)）**：
  - `gateway_stages`：按 `chain.p3_records` 原始顺序收集所有 `schema_version == "p3.gateway.v1"` 且 `stage` 非空事件的 `stage` 字段，以 `" -> "` 拼接；无网关事件则为 `"-"`。
  - `book_frame`（键名 `book_frame_ref`）：直接读取 `p1.get("book_frame_ref")`，不依赖是否传入 `p13_root` 或命中 `p13_record`，为 `None` 时 HTML 渲染 `"-"`。
  - `terminal`（键名 `terminal_status`）：经 `_resolve_consolidated_terminal_status` 汇总同 `decision_id` 下全部非 `p3.gateway.v1` 记录（详见 §2.5 / Q6），无尝试记录时返回 `"-"`。
- **对应函数与测试**：函数 `_build_decision_rows`、`_resolve_consolidated_terminal_status`、`render_m10_dashboard_html`；测试 [`test_m10_full_chain_settlement_reconcile_and_paper_risk_panel`](../../tests/unit/ui/test_m10_s310_readonly_view.py#L83-L233)（验证 `PRE_SIGN_SNAPSHOT -> HTTP_RESPONSE` / `1` / `FILLED`）及 [`test_m10_single_decision_multiple_partial_p3_attempts_aggregated`](../../tests/unit/ui/test_m10_s310_readonly_view.py)。

### 6.8 Q8：页面生成与刷新机制，以及与 `S2-07` 监测 / `S3-13` 告警的衔接关系
- **代码实态**：
  1. **生成与刷新机制**：[`scripts/render_m10_dashboard.py`](../../scripts/render_m10_dashboard.py) 为**一次性按需离线 CLI 静态生成**，无后台常驻 Web 服务、无定时自刷新守护、HTML 无任何 JS/轮询请求；由运维人员或上游调度命令按需执行产出静态报告至 `--output`（强制校验不得落入 `--audit-root`）。
  2. **与 `S2-07` / `S3-13` 的衔接关系**：`S2-07`（只读巡检口径设计，`READY`）与 `S3-13`（四类 `watchdog` 自动化实现，`PLANNED`）当前均尚未与 `M10 v1` 代码发生直接调用耦合；三者共同受 [`P8-T2-M7-LOGGING §3.2`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#32-p10m7--m10-前台只读视图兼容约束与正式查询契约v11--s2-04-正文冻结) 只读零写回与物理隔离铁律约束（告警输出至独立目录如 `data/alerts/`，绝不写回 `data/audit_logs/` 或 `data/market_recordings/`）。后续 `S3-13` 落地后，既可定时触发 `render_m10_dashboard.py` 刷新静态面板，也可由 `M10` 后续版本只读消费独立 `data/alerts/` 摘要。
- **对应函数与测试**：函数 `scripts/render_m10_dashboard.py:main`、`render_m10_dashboard_html`；测试 [`test_m10_ast_zero_database_zero_write_and_cli_render`](../../tests/unit/ui/test_m10_s310_readonly_view.py#L279-L319)。

---

## §7 已知历史缺陷与修复记录（`P8-WO-20261123-M10-DOC-DESIGN-v2` 阶段一闭环）

在执行文档单 `P8-WO-20261123-M10-DOC-DESIGN` 初版核查时，开发侧主动触发停工申报并上报以下实态缺口，随后依 `P8-WO-20261123-M10-DOC-DESIGN-v2` 阶段一授权修复闭环：

1. **历史缺陷 1（已修复）**：初版（`2de3059`）`_build_decision_rows` 循环内用 `attempt_rec = p3` 覆盖 `1:N` `P3` 尝试记录，导致单决策多次部分成交/重切片丢账。已修复为累加求和 `filled_shares / filled_usd / fee_paid_usd` 并引入 `_resolve_consolidated_terminal_status`，新增专测 `test_m10_single_decision_multiple_partial_p3_attempts_aggregated` 验证通过。
2. **历史缺陷 2（已修复）**：初版（`2de3059`）`_build_settlement_rows` 仅按 `(station_id, target_date)` 匹配成交记录，未带 `market_id / target_type / session_id`，同站同日多笔 `P9` 会重复计入 `total_realized_pnl_usd`。已修复为按 `P9.settlement_id` 全部五项构成键 `_matches_p9_settlement_scope` 绑定并按 `settlement_id` 去重，新增专测 `test_m10_multiple_p9_same_station_date_bound_by_market_session_type_no_double_count` 验证通过。
3. **测试覆盖补齐（已闭合）**：针对初版 `Q3` `missing_forecast_fk_count > 0` 缺少直接 UI 层断链测试的缺口，新增专测 `test_m10_missing_forecast_fk_count_positive` 覆盖 `"fc-missing-p17"` 计数与 `"MISSING_FORECAST"` 豁免。
4. **现存口径观察项（非缺陷，保留记档待后续迭代审视）**：
   - `model_frozen` 调用侧声明语义需在 `S3-12 LIVE` 前重审接入只读冻结源（见 §2.4）；
   - HTML 区块 4 表头 `p15_reconciled`（`#L499`）实际渲染字段 `reconciled`（反映存在 `matched_decisions` 成交匹配或 `P19` 关联事件）；
   - 当未传 `risk_panel_override` 时，`build_m10_dashboard_model` 未强制校验入参 `execution_mode == safety.execution_mode`，日常经 CLI 读取同一 YAML 或测试显式匹配即可保持一致。

---

## §8 `Batch 2a` 业务视图增量规则（决策链卡片、城市→日期二级聚合卡与静态 SVG 累计盈亏曲线）

> 本节记录依 `P8-WO-20261123-M10-BIZCHAIN-EXEC1`、`P8-WO-20261123-M10-BIZCHAIN-EXEC2` 与 `P8-WO-20261124-M10-BIZCHAIN-EXEC3` 合入的只读展示增量与上游捕获衔接，全部计算均保持“仅展示与严格求和、绝不重算上游预测/`edge`/`net_ev`、零 JS / 零 CDN”。

1. **区块 3 六段式决策链卡片（[`_render_decision_chain_card`](../../src/ui/m10_view.py)）**：纯 CSS `<details class="chain-card">` 逐单展示 ① 决策时点天气（`p17.v2`: `obs_temp_f / obs_ts_utc / obs_source`）、② `P17.bin_probs` 全档条与命中档高亮、③ 所选档概率与 `edge / net_ev` 指标（`p1.v2`: `selected_bin_p_model / best_ask_edge / net_ev / q_eff / fee_rate_applied`，附 `fee_rate_official_raw`）、④ `G -> D -> target_slice_usd -> sum(filled_usd)` 三段精确 `Decimal` 差（`p1.v2`: `lambda_l / b_eff_headroom_usd / pov_cap_usd / gate_result / reject_reason`）、⑤ `P13` 盘口快照与 `LIVE` 置灰预留槽、⑥ `P9` 结算回填；缺失上游字段（如历史 `p1.v1/p17.v1`）统一显示 `"未落盘"`。
2. **城市 -> 日期独立盘口二级聚合卡（[`_build_city_date_aggregations`](../../src/ui/m10_view.py) / [`_render_city_aggregation_cards`](../../src/ui/m10_view.py)）**：
   - **第一级 `<details class="city-card">`** 按 `station_id` 汇总：累计投入(含费) `sum(filled_usd + fee_paid_usd)`、累计已结算盈亏 `sum(realized_pnl_usd)`、未结算敞口 `sum(PENDING_P9 投入)`、已结算单数/胜场；
   - **第二级 `<details class="market-day-card">`** 按 `M7 §2.7` 五要素 `(session_id, station_id, target_date, target_type, market_id)` 独立核算每个盘口（同日存在多 `market_id/target_type` 时拆分子行并标注 `同日多盘口独立核算`；扫描未成交零仓位盘口标示 `空盘口（有决策未成交）`）；严格恪守“每日/每盘口独立”铁律，城市层禁止跨盘口概率平均、胜率加权或收益摊平。
3. **按结算日累计已实现盈亏曲线（[`_build_daily_cumulative_pnl_series`](../../src/ui/m10_view.py) / [`_render_daily_pnl_svg`](../../src/ui/m10_view.py)）**：按 `settled_ts_utc[:10]`（缺失时回退 `target_date`）汇总每日 `realized_pnl_usd` 并按日历时序累加绘制静态 `<svg class="pnl-svg">` 折线与节点圆标；无结算日如实留空不插值补点，全未结算时不生成伪零线；对应专测集 [`tests/unit/ui/test_m10_s310_readonly_view.py`](../../tests/unit/ui/test_m10_s310_readonly_view.py) 共 13 项全绿。
4. **历史记录占位语义注记（`pre-p1.v2 / pre-p17.v2`）**：`2026-11-24` 之前生成的历史 `p1.v1 / p17.v1` 记录因决策时点未持久化 `obs_temp_f / net_ev / lambda_l` 等增量字段，在区块 3 决策链卡片中永久显示 `"未落盘"` 占位符（依 `fail-honest` 原则永不事后伪造回填，防看卡歧义）。

---

## §9 `Batch 2b` 浅色股票终端交互改版与按时间窗懒加载（`2026-11-27` 已对齐）

> 本节记录按业主审定方案落盘的前端交互与性能升级，全部严格恪守零 JS / 零表单 / 零写回 / 不重算不修改原始观测值及新增/修改函数 `< 50` 行红线。

1. **模块化只读渲染拆分**：新增 [`m10_formatting.py`](../../src/ui/m10_formatting.py)（`STATION_METADATA` 站点中文名与 IANA 时区双显转换、人话状态翻译、心跳与 `watchdog` 新鲜度判别）、[`m10_theme.py`](../../src/ui/m10_theme.py)（浅色金融看板 CSS 与浅色静态 `<svg>` 累计盈亏曲线）、[`m10_cards.py`](../../src/ui/m10_cards.py)（顶部心跳条、4 格资产/盈亏/漏斗/风控 KPI、统一《最近成交与委托订单一览》主表、默认折叠的城市持仓榜、可折叠交易故事卡、底部折叠审计抽屉）。实时服务主页面顺序为：**顶部状态与 4 格 KPI（卡片 1 同时明示「扣减未结算持仓后的参考可用余额」与「`P19` 最新落盘余额」并在差额 `> $0.01` 时标注上游重启未继承持仓提醒） → 筛选条 → 《最近成交与委托订单一览》（附一句话原因，点击 `查看详情 ↗` 以新窗口只读打开 `/decision?id=<decision_id>` 独立 6 步因果全链路页，消除主页卡片重复堆叠） → 《分城市持仓与独立盘口》 → 《累计已实现盈亏走势 (SVG)》 → 《一致性核验》与审计抽屉**；离线 CLI 导出维持单文件自包含内嵌卡片。
2. **按时间窗懒加载与跨日外键保障（[`m10_live_cache.py`](../../src/ui/m10_live_cache.py)）**：
   - `IncrementalAuditCache.refresh(target_dates=..., extra_streams=...)` 支持只读加载当前筛选周期（`period=today` 默认 / `week` / `month` / `year` / `all` 或指定 UTC 日）覆盖目录，避免长周期积累后冷启动全量解压历史 `.jsonl.gz`；
   - 自动附带读取 `d_start - 1` 的轻量 `p17`（修复跨 UTC `00:00Z` 凌晨 `P1→P17` 外键断链误报）、`d_end + 1` 的 `p9`（保障跨日结算对账）及最新日 `p19`（展示最新账户可用/冻结余额）；
   - 通过 `p1_dim_outcomes` 按 `(station_id, target_type, outcome)` 在读取阶段预聚合扫描计数，彻底解耦全量 KPI/城市汇总与底部卡片分页 `limit`，且 `action=p3` 默认视图将 `FILLED/PARTIAL` 订单置顶展示。
3. **纯 `<a>` 多维筛选、真分页与双时区切换（[`serve_m10_live.py`](../../scripts/serve_m10_live.py) / [`render_m10_dashboard.py`](../../scripts/render_m10_dashboard.py)）**：支持 `period`（今日/近7日/本月/本年/全部）、`station`（全部/6 站）、`target_type`（全部/`TMAX`/`TMIN`）、`action`（有下单尝试[成交置顶]/仅已成交/有信号动作/全部扫描）、`tz`（北京+站点双显/仅北京/优先站点当地）、`page`（`首页/上一页/页码/下一页/末页`，同时联动《最近成交订单一览》与《委托单与决策原因流水》）、`limit`（每页条数）与 `refresh` 纯超链接切换；城市持仓内部优先展示有成交/待结算/已结算盘口，空盘口沉底；6 步因果核验时间轴（`m10_consistency.py`）升级为支持双时区的横向步骤卡。
4. **实时 `P13` 盘口快照按需增量索引（[`m10_p13_cache.py`](../../src/ui/m10_p13_cache.py)）**：`serve_m10_live.py` 默认只读挂载 `data/market_recordings/`（可通过 `--p13-root` 覆盖），仅对当前匹配窗口内出现的 `(session_id, station_id)` 增量读取 `p13_book_stream_<station>.jsonl(.gz)`（跳过未换行并发尾行并校验 SHA-256，只保留顶三档与关键元数据），在毫秒级增量开销下完整点亮时间轴 `② P13 盘口帧` 时间戳与格子 ⑤ 盘口快照。
5. **首页去重主表、`/decision` 独立详情页与双口径防误导展示（`2026-11-28` 实态对齐）**：
   - 实时首页将原成交表与流水卡片合并为一张带「一句话原因」的分页主表（[`render_unified_orders_table`](../../src/ui/m10_cards.py)），点击单笔条目以新标签页只读打开 `GET /decision?id=<decision_id>` 独立 6 步因果详情页（[`render_decision_detail_html`](../../src/ui/m10_view.py) / [`render_live_decision_detail_html`](../../src/ui/m10_live_cache.py)）；
   - 卡片 1 同时明示「参考可用余额（含费持仓扣除推算）」与「`P19` 最新 `free_usd_after`」，差额 `> $0.01` 时标注上游重启未继承持仓提醒；卡片 4 在 `PAPER` 网关账本为空/`$0` 且存在 `P3` 模拟成交时明示模拟单日耗用与 `超试单日限` 告警及 `网关账本 $0 · P18 未走 CLOB 网关` 副行；局部同源轮询严格按 `§4.2` 仅限实时服务 `refresh > 0` 内联唯一 `data-m10-live-poll="1"` 脚本且保留 `<details[id]>` 展开态与滚动条位置。

---

## §10 本地回环实时刷新服务、`.jsonl.gz` 归档兼容与 5 项一致性核验（`2026-11-28` 已对齐）

> 本节补录 `2026-11-27/28` 与存储优化、`P10` 压缩读取兼容及跨模块机械对账相关的增量实现，严格遵守只读零写回与原始观测值原样呈现铁律。

1. **本地回环只读实时刷新服务（[`scripts/serve_m10_live.py`](../../scripts/serve_m10_live.py) & [`src/ui/m10_live_cache.py`](../../src/ui/m10_live_cache.py)）**：
   - 仅绑定回环地址 `127.0.0.1:8765`，HTTP 层严格放行 `GET` / `HEAD` 并对所有写方法返回 `405`；页面维持零 JS / 零表单，使用 `<meta http-equiv="refresh">` 自动刷新与纯 `<a>` 超链接切换视图参数；
   - `IncrementalAuditCache` 按字节偏移增量读取活跃日流，避免每次 HTTP 请求重复全量重扫历史文件（实测基准：`cold_get_ms = 7883.0`、`warm_get_ms = 16.1`）。
2. **`.jsonl.gz` 透明兼容、历史日志原子归档与 `P1` 噪声节流**：
   - [`src/audit/p10_reader.py`](../../src/audit/p10_reader.py) 新增 `_resolve_stream_file` 与 `_open_jsonl_readonly`，无缝只读读取 `.jsonl` 与归档后的 `.jsonl.gz` 审计流；
   - [`scripts/archive_audit_logs.py`](../../scripts/archive_audit_logs.py) 对历史日期目录（严格跳过 `dir_date >= today_utc` 当日目录）执行原子 `.jsonl.gz` 压缩，并校验解压 SHA-256 一致后再移除原始 `.jsonl`（`data/audit_logs/PAPER/2026-11-26/` 实测由 `171,448,217 bytes` 压缩至 `15,427,747 bytes`，占原体积 `9.0%`）；
   - [`src/decision/offline_scheduler.py`](../../src/decision/offline_scheduler.py) 与 [`scripts/run_s311_offline_scheduler.py`](../../scripts/run_s311_offline_scheduler.py) 引入 `_P1NoDepthThrottle`（`--p1-no-depth-heartbeat-sec 900`），100% 完整保留 `ORDERED`、`SKIP_EDGE_BELOW_M`、`BLOCKED_BELOW_MIN_ORDER` 等有动作/决策结果日志，仅将重复的 `BLOCKED_NO_BOOK_DEPTH` 收敛为「状态变化立即写 + 每 15 分钟心跳写」；
   - 分页窗口一致性修复：[`src/ui/m10_live_cache.py`](../../src/ui/m10_live_cache.py) 新增 `_filter_p3_for_window`，修正默认 `limit=50` 分页窗口裁剪后产生假阳性 `orphan_p3=112` 的视图误报。
3. **5 项机械式跨模块一致性核验与 6 步因果时间轴（[`src/ui/m10_consistency.py`](../../src/ui/m10_consistency.py) & [`src/ui/m10_view.py`](../../src/ui/m10_view.py)）**：
   - 机械核验 5 项跨流不变量并原样展示布尔与数值偏差：`Order Check`（最小份数与预计实花）、`Forecast FK & Dual Hash`（`P1 -> P17` 外键及 `model_hash / config_hash`）、`P1↔P3 Alignment`（`ORDERED` 与执行尝试对齐）、`P3↔P19 Conservation`（资金三桶零残差守恒）与 `P9↔PnL Reconciliation`（官方结算与已实现净盈亏对齐）；
   - 决策链卡片内嵌 6 步因果时间轴（预报 → `P13` 盘口帧 → `P1` 决策 → `P14 FREEZE` → `P3` 撮合终态 → `P9` 结算），专测 [`tests/unit/ui/test_m10_live_server_and_consistency.py`](../../tests/unit/ui/test_m10_live_server_and_consistency.py) 与 [`tests/unit/decision/test_p1_noise_throttle_and_archive.py`](../../tests/unit/decision/test_p1_noise_throttle_and_archive.py) 全绿通过。


