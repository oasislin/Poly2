# P8-M10-BIZCHAIN-PROPOSAL：M10 业务决策链可视盘点、设计提案与实施排期提案（`v1.0`）

- **治理与派工编号**：`P8-M10-BIZCHAIN-PROPOSAL`｜派工单：**`P8-WO-20261123-M10-BIZCHAIN-DESIGN`**｜前置：`M10 v2`（`045291c`）
- **法定锚点**：[`项目方案 (v3.0) §8.1 M10 / §8.5`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#81-模块地图m1m10-十模块静态架构--2026-11-18-当前决策)、[`P8-T2-M7-LOGGING v1.1`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md)、[`P8-T4-M4M5-INTERFACE v1.0`](P8-T4-M4M5-INTERFACE_决策与执行接口规格.md)、[`P8-M10-DESIGN v1.0`](P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md)、[`P8-PROJECT-TASKS v2.6`](P8-PROJECT-TASKS_全量任务分解台账.md)
- **命名与准入依据（[`项目编号与命名规范 §6.5 / §9`](../项目编号与命名规范_20261021.md#6-现役衍生编号与文件--工单命名总表v11-新增)）**：依 `§6.5` `P<批次>-<THEME>_<中文主题>_v<X.Y>.md` 模板定名，经 `P8-WO-20261123-M10-BIZCHAIN-DESIGN` 准入并于 `P8-PROJECT-TASKS §1 M10 / §6` 挂载可达指针；**本轮仅产出盘点与提案文档，零代码修改**，实施单待业主批复排期后另发。

---

## §1 阶段 A：决策链五环节只读盘点（以 `HEAD 045291c` 实态为准）

### 1.1 五环节现状总览表

| 环节 | 盘点对象 | 现状三态 | 代码/规格事实锚点 | 关键结论与缺口摘要 |
| :---: | :--- | :---: | :--- | :--- |
| **①** | **决策时点天气** | **`落盘但不足`** | `P17`：[`forecast_distribution_engine.py#L314-L340`](../../src/prediction/forecast_distribution_engine.py#L314-L340)<br>`P12`：[`settlement_metar_stream.py#L293-L345`](../../src/data_acquisition/settlement_metar_stream.py#L293-L345)<br>`P9`：[`m9_settler.py#L131-L167`](../../src/settlement/m9_settler.py#L131-L167) | `P17` 落盘了推理时日内极值 `m_now_f / m_now_int_f`、先验 `prior_mu0 / prior_sigma0`、`gefs_lead_hours / tau_hours / is_bridge_active` 等；`P12` 仅落盘可用率/龄期无温度值且无 `P1` 外键；`P17` 缺当站最新瞬时实测温与 `obs_ts_utc` / 原始 METAR 摘录；且 **`P17.m_now_f`（决策前日内极值）与 `P9.settled_temp_f_exact/int`（次日法定终态结算温度）非同一字段**；当前 `M10` 未展示上述任何气象字段。 |
| **②** | **模型全档分布** | **`已落盘`**（未在前端展示） | `P17.bin_probs`：[`forecast_distribution_engine.py#L304,L338`](../../src/prediction/forecast_distribution_engine.py#L338)<br>规格：[`P8-T2-M7-LOGGING §2.3`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#L125-L128)<br>读取：[`p10_reader.py#L180-L206`](../../src/audit/p10_reader.py#L180-L206) | **`P17` 并非仅存点估计**：`bin_probs` 完整保存全档位离散概率列表（`bin_id / label / lower_int_f / upper_int_f / p_model / is_boundary_bin / is_dead_bin`）+ `prior_mu0 / prior_sigma0 / family / p_stay_phys / p_bin_stay / sigma_delta_sample`，**全档分布可完整回放**；当前仅 `M10` 未读取 `chain.p17_record["bin_probs"]` 渲染。 |
| **③** | **所选档概率与 `edge / net_ev`** | 所选档概率：**`落盘但不足`**<br>`net_ev / q_eff`：**`未落盘`**（统一用 `edge / net_ev`） | `edge_math`：[`edge_math.py#L56-L115`](../../src/pricing/edge_math.py#L56-L115)<br>`M4`：[`engine.py#L348-L390,L794-L806`](../../src/decision/engine.py#L794-L806)<br>规格：[`项目方案 v3.0 §8.5`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#L325-L347) | ① 所选 `bin_id` 概率需关联 `P1.forecast_id → P17.bin_probs[bin_id].p_model` 间接获取，`P1` 未直存；② 全仓检索 `docs/` 与 `src/` 确认现役后 α `v3.0` 与代码库统一采用含费相对边际优势 **`edge`（`P1.best_ask_edge`）与 `net_ev = p_model - q_eff`、`q_eff = price * (1 + fee_rate * (1 - price))`**，其中 `P1` 此前仅存 `best_ask_price`、`best_ask_edge`、`m_threshold`、`s_edge`，**未落盘 `selected_bin_p_model`、`fee_rate_applied`、`q_eff`、`net_ev`、`lambda_l`**（术语统一：全项目直接用 `edge / net_ev`）。 |
| **④** | **仓位公式** | **`落盘但不足`** | 公式锚点：[`P8-D6-POLICY-CLOSURE §1.3/§6`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md)、[`P8-CAPITAL-CONFIG §6/§1.5`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#L73-L81)、[`P8-T4-M4M5-INTERFACE §2.2`](P8-T4-M4M5-INTERFACE_决策与执行接口规格.md#L55-L85)<br>代码：[`engine.py#L709-L778`](../../src/decision/engine.py#L709-L778) | 公式 $G = B \cdot w(\tau) \cdot [s(\text{edge}) \cdot \lambda(L)]$ 与 $D = \max(0, \min(G - \text{held}, B_{\text{eff}}))$ 及其输出 `b_budget_usd / w_tau / s_edge / g_cap_usd / held_usd / headroom_d / target_slice_usd` 已入 `P1`，`P3` 含 `target_usd / filled_usd / fee_paid_usd`。在 `v2 1:N` 聚合口径下：**`G → D → target_slice_usd → sum(filled_usd)` 大体可区分，但缺 `lambda_l` 显式值、`b_eff_headroom_usd`、`pov_cap_usd` 与网关双闸裁剪/拒单归因（`reject_or_abort_reason`）**；且 `1:N` 重切片下不得用 `sum(P3.target_usd)`，须以 `P1.target_slice_usd` 作为理论发单基线。 |
| **⑤** | **CLOB 盘口与深浅修正** | 盘口帧：**`已落盘`**（需 `--p13-root`）<br>`LIVE` 深浅终注：**`未落盘 / 未实现`** | `P13`：[`passive_book_recorder.py#L205-L250`](../../src/data_acquisition/passive_book_recorder.py#L205-L250)<br>`M5`：[`executor.py`](../../src/execution/executor.py)<br>网关：[`clob_gateway.py#L991,L1306`](../../src/execution/clob_gateway.py#L991) | ① `P13` payload（`p13_book_stream_<station>.jsonl`）完整含 `asks` 全部卖档 `[[p, s], ...]`、`bids` / `bid_top10`、`best_bid`、`fee_rate`、`min_order_size_shares`、`single_side`，完全具备盘口深浅分析所需全部原始档位；仅当前 CLI 需传 `--p13-root` 才索引，且 `M10` 未展示档位明细；② **如实确认：当前 `PAPER` 链不存在 `LIVE` 网关级盘口动态修正终注逻辑**（仅 `M5 P2 plan_slice` 按静态 `PhiPolicy` 计算 `pov_cap`），真实 CLOB 深度滑点与动态修正属 **`S3-15` 冻结设计范畴**，本单严守红线不解冻。 |

### 1.2 环节③与环节④关键实态澄清注记

1. **关于 `edge / net_ev` 术语统一声明（已对齐 `2026-11-24` 业主指令）**：经全仓只读核验与业主确认，全项目统一直接使用代码语义 **`edge`（`best_ask_edge`）与 `net_ev`（及 `q_eff`、`fee_rate_applied`）**，不再另设抽象代号，确保捕获字段、规格文档与监控视图完全一致。
2. **关于 `P1` 关联与 `1:N` 口径下三段裁剪差值拆解**：
   - `理论门限 → M4/M6 裁剪` = `P1.g_cap_usd` → `P1.headroom_d`（受 `held_usd` 与 `B_eff` 制约）；
   - `M4/M6 额度 → P2 深度切片` = `P1.headroom_d` → `P1.target_slice_usd`（受盘口合格深度 `pov_cap` 与 `min_order_size` 制约）；
   - `P2 计划切片 → 网关/撮合实际成交` = `P1.target_slice_usd` → `sum(P3.filled_usd)`（含手费实支 `sum(P3.filled_usd + P3.fee_paid_usd)`；`REJECTED` / `CANCELLED_UNFILLED` 差额受 `clob_gateway` 双闸拒单或 IOC 流动性不足影响，当前 `_build_decision_rows` 尚未抽取 `reject_or_abort_reason`）。

---

## §2 阶段 B：业务决策链可视与余项演进设计提案（零代码）

### 2.1 上游决策时点捕获闭合方案（铁律：决策时点落盘，`M10` 绝不重算）

> **设计铁律**：所有决策链数值必须在 `M4 / M2` 决策当下写入 `M7` JSONL 并带 `record_sha256`；`M10` 只做只读聚合与字段关联，**严禁在 `M10` 渲染期重算 `edge` / `net_ev` / `G` / `D` / `pov_cap` 或反推气候分布**，确保审计与监控共享单一真相源。

建议采用 **`p1.v2` + `p17.v2` 向前兼容演进**（`p10_reader.py` 已天然兼容多 `schema_version` 字典字段，缺失新字段时回退渲染 `"LEGACY_N/A"`）：

1. **`P17` 扩展为 `schema_version = "p17.v2"`（决策输入气象补充）**：
   - 新增字段（来自 `M1` 喂桥同源观测上下文，保持与 `P9` 结算真值物理字段名严格隔离）：
     - `latest_obs_temp_f: Optional[float]`（推理当下最新一条合规观测瞬时温度 °F，区分于 `m_now_f` 日内极值）
     - `latest_obs_ts_utc: Optional[str]`（该最新观测 UTC 时戳）
     - `obs_source_mode: Optional[str]`（如 `AWC_ROUTINE_METAR`）
     - `gfs_prior_summary: Optional[Dict[str, Any]]`（如 `gfs_init_utc`, `gfs_completeness_ratio`；亦可挂载 `coverage_freshness_ok: bool`）
   - 已有全档 `bin_probs` 保持不变，直接复用。
2. **`P1` 扩展为 `schema_version = "p1.v2"`（环节③/④/⑤决策自解释字段）**：
   - `selected_bin_p_model: Optional[float]`（当次决策命中档位的 `p_model` 直录，免去跨流拼错风险）
   - `fee_rate_applied: Optional[float]`、`q_eff: Optional[float]`、`net_ev: Optional[float]`（与 `best_ask_edge`、`m_threshold`、`fee_rate_official_raw` 成套呈现 `edge / net_ev` 边际优势计算链）
   - `lambda_l: Optional[float]`、`b_eff_headroom_usd: Optional[float]`、`pov_cap_usd: Optional[float]`、`min_order_clipped: Optional[bool]`（实现 `G → D → target_slice_usd` 逐闸裁剪差值精确归因）
   - `gateway_reject_reason: Optional[str]`（或由 `M10` 从 `P3.reject_or_abort_reason` 与 `p3.gateway.v1 RISK_GATE_REJECTED` 直接抽取，无需 `P1` 改动即可获取成交裁剪原因）。
3. **向后兼容策略**：
   - `p10_reader.py` 沿用既有无状态 JSONL 读取逻辑，`p1.v1` / `p17.v1` 历史日志继续正常校验 `record_sha256` 与关联；`M10` 视图模型对新字段全部 `.get(...)`，旧记录显示 `"-"` 或 `"LEGACY_v1"`。

### 2.2 监控界面区块 3 升级方案（决策链卡 / 链式展开行）

在保留当前区块 1（常驻“风险参数面板”）、区块 2（`M7` 完整性与双哈希）基础上，将区块 3 升级为 **“每单决策链主表 + 只读 CSS `<details>` 链式卡片”**（纯 HTML5 `<details>/<summary>` 零 JS、零按钮/表单，继续 100% 通过 AST/HTML 只读门禁）：

```text
[区块 3 · 决策链卡片流 (每条 decision_id 一卡，按 scan_ts_utc 逆序)]
├─ 环节① 决策时点天气快照（来自 P17，显式标注非 P9 结算温度）
│    station / target_date / target_type / tau_hours / gefs_lead_hours / latest_obs_temp_f (@latest_obs_ts_utc)
│    日内极值 m_now_f (m_now_int_f) / 先验 (prior_mu0 ± prior_sigma0, family) / is_bridge_active
├─ 环节② 模型全档分布（来自 P17.bin_probs）
│    纯 CSS 横向概率条图（展示全档 label + p_model% + dead/boundary 标，**当前选中 bin_id 高亮**）
├─ 环节③ 所选档概率与边际评价（edge / net_ev 链，来自 P1）
│    selected_bin_p_model | best_ask_price | fee_rate → q_eff → net_ev → best_ask_edge vs m_threshold
│    挂参数出处：model_hash | config_hash | policy_version | scaler_policy_id
├─ 环节④ 仓位公式与三层裁剪对照（来自 P1 + P3 1:N 聚合）
│    公式参数：B (b_budget_usd) × w(τ) (w_tau) × [s(edge) (s_edge) × λ(L) (lambda_l)] = G (g_cap_usd)
│    逐级对比柱/数值：G (g_cap_usd) ─[held_usd / b_eff]→ D (headroom_d) ─[pov_cap]→ P2 切片 (target_slice_usd)
│    ─[网关双闸/IOC]→ 实际成交 sum(P3.filled_usd) + 手续费 sum(P3.fee_paid_usd) + terminal_status (attempt_count)
├─ 环节⑤ 盘口快照与 LIVE 修正预留槽位（来自 P13 + 预留）
│    PAPER 当前态：展示决策时点 P13 帧摘要（frame_seq / data_source / single_side / ask_top3 / bid_top3 / qual_depth_shares；未传 --p13-root 时标“P13 未挂载”）
│    LIVE 预留栏位：**`[预留 · 深度修正终注待 S3-15 LIVE 轨启用]`**（当前置灰只读占位）
└─ 结算回填关联（来自 M9 P9，显式区分于环节①）
     settlement_id | winning_bin_id | settled_temp_f_int | oracle_source | payout - cost_basis = realized_pnl_usd
```

### 2.3 既有缺口余项可得性与纳入建议（供业主批复）

| 既有待议视图 | 当前 `M7` 数据可得性实况 | 纳入建议与归属批次 |
| :--- | :--- | :--- |
| **1. 城市聚合卡** | **`完全可得`**：`P1 / P3 / P9 / P12 / P17 / P19` 全部原生携带 `station_id`；`M10` 无需改任何上游 schema，直接按 `station_id` 分组汇总扫描数、下单率、成交额、手续费、未平仓（已成交未结算 `P9`）与已实现 PnL 即可。 | **建议立即纳入下一轮 `M10 v2` 展示批**（零上游阻塞，纯粹视图聚合增强）。 |
| **2. 日盈亏曲线（含浮盈估算区分）** | **`部分可得（已实现盈亏可得 / 未实现市值缺）`**：已实现 PnL 可按 `P9`（`target_date` 或 `settled_ts_utc`）及 `P19` 时序净值（`free + locked + held` 需从 `P19` 或结算推算；注意 `P19` 当前仅在正常盈利释放时不单独写事件，且 `held_usd` 实时盯市估值需结合 `P13` 最新 `best_bid`）。 | **建议随 `M10 v2` 先上“按日已实现盈亏累计曲线（纯 SVG 静态折线，零 JS）”**；含未实现市值净值曲线留待 `P13` 盯市估值口径明确后在 `v3` 补齐。 |
| **3. 胜率 · 模型校准面板** | **`结算后可得，但依赖较多跨日样本`**：真值 `winning_bin_id` 与 `settled_temp_f_int` 已在 `P9`，预测概率在 `P17.bin_probs`，校准流已在 `P8`（[`p8_aggregator.py`](../../src/audit/p8_aggregator.py) 实现滑点中位、空转率、`sigma_delta` 分位、过期比）；但 `Brier / ECE / 胜率` 需要足够多已结算站-日样本才能统计稳定，当前单日/试单样本太少易误导。 | **建议与 `S3-08 / S2-02`（`11-26` 后实测复检）联动排期，归 `M10 v2.1 / M8` 月度复检可视化批**，前期仅展示基础“已结算胜/负笔数与平均预测命中概率”。 |

---

## §3 阶段 C：实施排期提案（本轮零代码，待业主批复后另开实施单）

### 3.1 总体依赖铁律与工时评估

- **硬依赖顺序**：**上游捕获（`P17 v2` / `P1 v2` + `M4` 传参透传）必须先于仪表盘 `M10 v2` 展示改造**，严禁反向在 `M10` 中伪造或重算缺失字段；阶段五中 `LIVE` 深度修正栏仅做只读预留占位，**严禁提前解冻 `S3-15`**。
- **与现有路线图并行与先后关系**：
  - 与 **`S2-07`（只读监测设计，当前 `READY`） / `S3-13`（自动化告警脚本，当前 `PLANNED`）**：文件改面完全独立（`S2-07/S3-13` 归 `M7/scripts/` 巡检与独立 `data/alerts/`；`M10` 业务链可视改 `M2/M4` 日志字段与 `src/ui/`），**可并行推进，零互斥**；后续 `M10 v2/v3` 只需预留只读挂载 `data/alerts/` 入口。
  - 与 **`S3-11`（`T9` 占位参数带延迟假盘冻结运行，当前 `PLANNED`，等 `S2-02 11-26` 填实 `friction_median` 后开跑）**：建议 **`Batch 1`（上游捕获扩展 `P1/P17`）在 `S3-11` 开跑前（即本周 `11-24 ~ 11-26`）先落盘**，确保 `S3-11 T9` 首轮假盘压测产出的 `M7` 日志即携带完整决策链字段；`Batch 2`（`M10 v2` 纯 SVG/HTML 决策链卡片 + 城市卡 + 日实现盈亏曲线）可紧随 `Batch 1` 或与 `S3-11` 同步交付验收。
  - 与 **`S3-15`（真钱试单段，冻结待业主“统一开通”）**：环节⑤ `LIVE` 深度修正列在 `M10 v2` 中先上灰置预留位，真正实值接入严格随 **`S3-15`** 触发解冻，本阶段不触及。

### 3.2 分批实施排期表（预估工时 & 建议落点）

| 批次 | 拟定范围与核心交付物 | 建议修改落点 | 预估工时 | 前置与排序建议 |
| :--- | :--- | :--- | :---: | :--- |
| **Batch 1（上游捕获先行）**<br>拟号：`S3-10b-CAPTURE` / `BIZCHAIN-EXEC3` | ① 统一使用代码语义 `edge / net_ev`；<br>② `P17 v2` 补 `obs_temp_f / obs_ts_utc / obs_source`（**须隔离于 `src/pricing/` 锁定区**）；<br>③ `P1 v2` 补 `selected_bin_p_model / fee_rate_applied / q_eff / net_ev / fee_rate_official_raw / lambda_l / b_eff_headroom_usd / pov_cap_usd / gate_result / reject_reason`；<br>④ 补强单测与 `P8-T2-M7-LOGGING` 规格升版（`§8.3` 同提交联动）。 | `src/prediction/`（非 `src/pricing/`）、`src/decision/engine.py`、`docs/audit/P8-T2-M7-LOGGING*`、相关单测 | **3–4 小时** | **最优先（`11-24 ~ 11-26`、`S3-11` 启动前完成）**；与 `S2-07` 并行。 |
| **Batch 2（`M10 v2` 决策链可视 + 城市卡 + 日实现盈亏）** | ① `_build_decision_rows` 抽取 `P17`（气象+全档 `bin_probs`）、`P1` 三级裁剪、网关 `reject_or_abort_reason`、可选 `P13` 盘口摘要；<br>② 静态 HTML 区块 3 升级为“主表 + CSS `<details>` 链式卡片”（含环节⑤ `LIVE` 预留槽）；<br>③ 增加城市聚合卡与纯静态 SVG 日实现盈亏曲线；<br>④ 保持零 JS / 零 CDN / AST 三禁全绿 + `p1.v1/p17.v1` 向后兼容测试。 | `src/ui/m10_view.py`、`scripts/render_m10_dashboard.py`、`tests/unit/ui/test_m10_s310_readonly_view.py`、`P8-M10-DESIGN` | **4–5 小时** | **强依赖 Batch 1 完成后启动**；可与 `S3-11` / `S3-13` 并行。 |
| **Batch 3（校准面板 + `LIVE` 深度修正接入）** | ① 接入 `P8` 校准指标与 `Brier/ECE` 分站命中视图；<br>② 随 `S3-15` 启用接入 `LIVE` 真实盘口深浅修正终注数据并开放环节⑤实值栏；<br>③ `S3-12` 前完成 `model_frozen` 只读注册表源重审。 | `src/ui/`、`src/audit/p8_aggregator.py`、`src/execution/`（仅届时经 `S3-15` 解冻授权单修改） | **3–4 小时** | **排期置后**：① 校准视图待 `S2-02 / S3-08` 复检期；② `LIVE` 修正栏待 `S3-15` 触发解冻。 |

> **本轮声明**：以上均属设计提案与排期评估，**本轮严格零代码改动**；待业主审阅确认 `edge / net_ev` 口径与批复各批次立项后，再按单另行实施。
