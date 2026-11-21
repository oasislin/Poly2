# P8-RECORDER-NO-SIDE-DESIGN：尾桶单侧盘口修复与 `No` 侧双视角升级设计书（`v0.1`）

- **关联任务单**：`S2-01`（`M3` 被动录盘）、`S2-02`（`D-A1` 滑点）、`S2-03`（`D-6` 标定）、`S3-04 / S3-05`（`M4 / M5`）、`C3`（`P4 → P13 / P18 / M7` 同提交联动）
- **法定锚点**：
  - [`项目方案 (v3.0) §8.2–§8.4`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#82-协议清单p1p19-十九条--2026-11-18-当前决策)（含 `C3` 协议联动铁律）
  - [`P8-T2-M7-LOGGING v1.0 §2.6 & §4`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#26-p13-marketbookrecordenvelopem3--m7--s1-05-与-c3-锚点)
  - [`P8-T4-M4M5-INTERFACE v1.0 §1.2, §2.2–2.3`](P8-T4-M4M5-INTERFACE_决策与执行接口规格_v1.0.md#22-p2-plan_slice-正式协议签名与切片算法m4--m5--v11--2026-11-21-对齐-decimal-域)
  - [`P8-T8-ALGO4-DESIGN v0.3 §3–§4`](P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md#4-s3-05--m5-执行器ρedge-引-p2全程-decimal-与-p18-保守撮合)
- **文件增殖判据核验（[`AGENTS.md`](../../AGENTS.md)）**：本批工作同时覆盖已落地之 `M3` 采集器 `P4 v1.1 / P13` 协议修正（工单 1–4）与经 `2026-11-21` 开工批复落地之 `M4/M5` `No` 侧跨视图升级暨 `D-6` 合并视图输入（工单 5）。既不可将 `No` 侧跨视图工程规格混入 [`P8-T8-ALGO4-DESIGN v0.3`](P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md)，亦不适合由单边日志规格 [`P8-T2-M7-LOGGING`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md) 承载执行撮合与 `split/merge` 经济等价设计，故按判据合规单独立档。
- **边界声明（已对齐 `2026-11-21` 工单 5 实施批）**：**`§1–§2` 对应已落盘之 `M3` 采集与协议守卫口径；`§3` 对应经批复并已于 `src/execution/`、`src/decision/` 落地桩验证之 `M4/M5` 与 `DualSideBookPair` 实现（`LIVE` 实盘交叉拆分仍由 `enable_cross_side_split_routing=False` 门控）；全程严守 `F-2` 锁定区（`src/pricing/penetration_probe.py` / `src/pricing/edge_math.py`）零修改。**

---

## §1 已落地采集升级总览（工单 1–4 工程定案）

### 1.1 站表与实盘发现过滤修正（工单 1 & 4）
- **配置站表**：[`configs/passive_book_recorder.example.yaml`](../../configs/passive_book_recorder.example.yaml) 更新为 6 站 `["KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA"]`，其余 `endpoints` / `recording` / `field_mapping` 保持原貌。
- **遗留 slug 污染修复**：`2026-11-21` 实测 Gamma `/public-search?q=Highest+temperature+in+NYC` 仍返回 3 条未关闭十月/十一月初历史测试事件（`polyv2-highest-temperature-atomic-in-nyc-on-october-27-2026`、`november-4`、`november-5`），原 `discover_active_temperature_markets` 按 `endDate` 升序截取前 3 条导致完全漏掉实时市场。本次已加精确 `highest-temperature-in-{city_slug}-on-` 前缀过滤，剔除陈旧实验盘。

### 1.2 每日 `00:05Z` 优雅重启与 `stop_event` 信号响应修复（工单 2）
- **`run_passive_book_recorder.py` / `run_ws_loop` 阻塞核查结论**：
  - 原 [`scripts/run_passive_book_recorder.py#L64-L76`](../../scripts/run_passive_book_recorder.py#L64-L76) 已将 `SIGINT` / `SIGTERM` 绑定至 `stop_event.set()`，并在 `finally` 调用 `recorder.flush_and_close()`。
  - **原实现阻滞点**：[`passive_book_recorder.py`](../../src/data_acquisition/passive_book_recorder.py) `run_ws_loop` 内 `await asyncio.wait_for(ws.recv(), timeout=25.0)` 与 `await asyncio.sleep(delay)` 未并发监听 `stop_event.wait()`，导致平静盘面下 `SIGTERM` 最多滞留 `25s` 并误触发 `WS_HEARTBEAT_TIMEOUT` + 全量 REST 补拉后才退出。
  - **修正**：新增 `_recv_or_stop()`（`asyncio.wait({ws.recv(), stop_event.wait()}, FIRST_COMPLETED)`）与 `_sleep_or_stop()`；一旦 `stop_event.set()` 立即取消未决 `recv` 退出循环、`0` 误标 gap，紧接执行 `recorder.flush_and_close()` 排空异步 JSONL 写入队列。
- **定时轮转与运维巡检 CLI**：新增 [`scripts/run_passive_book_recorder_daily.py`](../../scripts/run_passive_book_recorder_daily.py)（维护 `latest_session.json` 指针并每日 UTC `00:05:00Z` 优雅重启换会 `rec-<YYYYMMDDTHHMMSSZ>-<hex>`），配套只读运维状态报告脚本 [`scripts/record_status.py`](../../scripts/record_status.py) 巡检活动会话、站台 token 覆盖、单侧占比、`fee_rate` 溯源、断流 gap 与未换行 trailing 残行计数。

### 1.3 `No` 侧双 token 订阅与 WSS 单连接容量实测分片方案（工单 4）
- **元数据扩展**：`MarketSubscriptionMeta` 新增 `outcome: Literal["YES", "NO"] = "YES"`；`discover_active_temperature_markets` 从 Gamma 市场同时提取 `clobTokenIds[0..1]` 与 `outcomes`（`YES` + `NO`），双双注入 `self._meta_by_token`；`P4 MarketBookSnapshot` 同步序列化 `"outcome": "YES" | "NO"`，确保离线读取 `P13` JSONL 无需反查线上 Gamma。
- **Polymarket CLOB WSS 容量实测结果（`2026-11-21` 实连 `wss://ws-subscriptions-clob.polymarket.com/ws/market`）**：
  - 官方文档（`docs.polymarket.com`）未声明全局 CLOB 单连接硬性 `assets_ids` 上限（注：Polymarket US 网关文档限制 `100` markets/subscription），社区广泛报告大数组单连存在“PING/PONG 正常但停止推流（silent freeze）”。
  - **实测基准**：
    - 目标 6 站实时 `Yes+No` 全集（`336 tokens` / `27,144 B`）：单连接 `14.42s` 内收全 **`336/336`** 独立资产（`726` 条消息、`340` 条 `book` 帧、`errors=[]`）；
    - 全球活跃天盘抽样 `420 tokens`（`34,069 B`）：单连获 **`332`** 独立资产（与 `210+210` 双分片合计 `170+162=332` 一致，首帧时延单连 `2.912s` vs 分片 `2.441s / 2.796s`）；
    - `600 tokens`（`48,665 B`）：单连收 **`488`** 资产、`errors=[]`；
    - **`850 tokens`（`68,930 B` > `64 KiB`）：单连零报错但返回 `book_frames=0, unique=0`（实证存在 `~64 KiB / ~600–850 tokens` 静默丢订阅悬崖）**。
- **拆连接工程方案**：
  - `RecorderConfig.max_tokens_per_ws` 默认 **`200`**（远低于实测 `~64 KiB` 静默悬崖 3–4× 安全裕度），`partition_token_shards()` 将 `token_ids` 确定性切片为 `ceil(N / 200)` 个分片（400 tokens → **2 条并发 WS 连接 × 200 tokens**，每条 ~16 KB）。
  - `run_ws_loop` 在 `len(shards) > 1` 时并发运行 `_run_ws_shard(shard_index, ...)`；REST 兜底（`poll_rest_fallback_once(token_ids=shard)`）与断线 gap 状态（`_shard_pending_gaps[shard_index]`）均按分片强隔离，禁止甲分片重连污染乙分片 `gap_detected` 标志。

---

## §2 尾桶单侧盘口修复与 `P4 v1.1 / P13 / M5` 对齐定案（工单 3）

### 2.1 对照 `P13` Schema 口径定案：选用 `payload.single_side`，严禁复用 `gap_reason`
- **对照依据**：[`P8-T2-M7-LOGGING v1.0 §2.6`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#L148-L149) 定义 `gap_detected: bool` / `gap_reason: Optional[str]` 专用于**传输与采集连续性缺失**；[`P8-T4-M4M5-INTERFACE v1.0 §2.3`](P8-T4-M4M5-INTERFACE_决策与执行接口规格_v1.0.md#L90) 规定 `P18` 回放窗口 `(decision_seq_id, F*.seq_id]` 内**只要存在任意 `gap_detected == True` 帧即强制熔断拒单 `PAPER_MATCH_ABORTED_GAP`**。
- **实盘反证**：`2026-11-21` 在盘统计显示 `KLGA / KATL / KSEA / KDAL` 等正常盘面中约 4–10 个档位常态为 `bids=[]`（`ask_only`）、尾端 1 个档位常态为 `asks=[]`（`bid_only`）。若将单侧状态写入 `gap_reason` 并置 `gap_detected=True`，等同将正常流动盘面污染为“录盘断流”，导致 `P18` 假盘撮合大面积误熔断。
- **正式口径**：
  1. `P13` 信封层 `gap_detected / gap_reason` **严格维持纯粹传输/采集缺口语义**；
  2. `P4 MarketBookSnapshot v1.1`（即 `P13.payload`）新增 **`single_side: Optional[Literal["bid_only", "ask_only"]]`** 并将 `ask_book` 放宽为 **`Optional[AskBook]`**（锁定文件 [`src/pricing/penetration_probe.py#L51`](../../src/pricing/penetration_probe.py#L51) `AskBook` 保持 100% 零修改，仅外部不再强求非空包裹）：
     - 双边均有档：`ask_book = AskBook(...)`, `bid_book = BidBook(...)`, `single_side = None`；
     - 仅有卖盘（`bids=[]`）：`ask_book = AskBook(...)`, `bid_book = None`, `single_side = "ask_only"`, `gap_detected = False`；
     - 仅有买盘（`asks=[]`，典型尾桶 `YES` 无卖单或近归零/近归壹档）：`ask_book = None`, `bid_book = BidBook(...)`, `single_side = "bid_only"`, `gap_detected = False`；
     - **双边全空**（`asks=[]` 且 `bids=[]`）：继续抛 `ValueError` 并由 `record_raw_book_frame` 记 `INVALID_OR_EMPTY_BOOK` 缺口。

### 2.2 `M4`、`M5` 切片与 `P18` 撮合守卫对齐规则
1. **`M4` 前置守卫（单侧 `YES` 基线模式）**：
   - 在调用 [`src/pricing/edge_math.py`](../../src/pricing/edge_math.py) 前强制检查：`if p4.ask_book is None or p4.single_side == "bid_only"` → **禁止向 `evaluate_book_edges` 传入 `None`**，直接产出 `P1 (decision_outcome="BLOCKED_NO_BOOK_DEPTH", best_ask_price=None, best_ask_edge=None)`；
   - 跨盘倒挂检测（`D3`）改写为仅当双边皆在场时检验：`if p4.ask_book is not None and p4.best_bid is not None and p4.ask_book.levels[0][0] <= p4.best_bid`（避免 `ask_only` 且 `best_bid is None` 误判）。
2. **`M5 PovSlicer (P2)` 守卫**：
   - 入口先验 `if ask_book_frame.ask_book is None or ask_book_frame.single_side == "bid_only"` → 返回 `SlicePlan(should_submit=False, target_usd=0, ..., abort_reason="NO_ASK_DEPTH")`。
3. **`M5 P18 ReplayMatcher` 守卫（区分“真实无卖盘”与“录盘缺口”）**：
   - `R1/R2/R3` 校验命中目标帧 $F^*$（无缺口、`gap_detected=False`）后，若发现 $F^*.\text{payload}.\text{ask\_book} \text{ is None}$（`single_side == "bid_only"`）：
     - 单侧买 `YES` 模式**不得标记 `PAPER_MATCH_ABORTED_GAP`**，应诚实归因正常无流动性不成交：**`terminal_status = "CANCELLED_UNFILLED"`、`reject_or_abort_reason = "NO_ASK_DEPTH"`**，并经 `P14` 全额解冻预冻结现金 `C_freeze`；
     - 若后续启用 `§3` `No` 侧跨视图撮合，则可尝试路由至配对 `NO` 侧 `BidBook` 按 `split/merge` 合成卖盘深，仍无深度方判 `CANCELLED_UNFILLED`。

---

## §3 工单 5 实施对齐：`M4 / M5` `No` 侧解析、`split / merge` 跨视图撮合与 `D-6` 合并视图输入

### 3.1 `M4 / M5` 编码批桩数据路径：`Yes + No` 双侧帧解析与因果配对
1. **双侧帧索引结构（只读 `P13` 解析层）**：
   - 离线解析器按 `(station_id, target_date, bin_label, market_id)` 建双槽索引 `DualSideBookPair(yes_frame: Optional[MarketBookSnapshot], no_frame: Optional[MarketBookSnapshot])`，依据 `P4.outcome`（`"YES"` | `"NO"`）路由入槽；
   - 因果配对时刻 $t_{\text{scan}}$（或撮合到达时刻 $t_{\text{arrive}}$）：各自取满足 `recv_ts_utc <= t_ref` 且未超出 `max_book_staleness_sec` 的最新合法无缺口帧；
   - 定义可选双侧时差门限 `pair_max_skew_sec`：当双侧同时在场且 `abs(yes_ts - no_ts) > pair_max_skew_sec` 时，不强行合成过期腿（退化为较新鲜且满足单一时效门限的可用腿，并在审计日志标注 `skew_fallback`），禁止把半小时前的陈旧 `No` 挂单与当前 `Yes` 挂单混拼出虚假套利/深度。

### 3.2 `M5` 撮合器跨视图成交与 `split / merge` 经济等价规则
设同一档位（`condition_id`）包含互补二元结果合约 $\text{YES}$ 与 $\text{NO}$，在 `Decimal` 精确域执行如下等价变换：

1. **买 `YES` 的两条经济等价执行路径（建仓主方向）**：
   - **直接吃卖盘（`YES_ASK`）**：买方命中 $\text{YES}$ `AskBook` 档 $(p_a, s_a)$；
   - **拆合卖出等效路径（`NO_BID_SPLIT_SELL`：`buy Yes @ p ↔ sell No @ 1 − p`）**：依据 CTF `split` 恒等式（$1\text{ USDC} \equiv 1\text{ YES} + 1\text{ NO}$），从 $\text{NO}$ `BidBook` 取买盘档位 $(p_{b,\text{NO}}, s_{b,\text{NO}})$——对应隐含卖出 $1\text{ NO}$ 得现金 $p_{b,\text{NO}}$、铸币净成本等价于以**等效 `YES` 卖价**买入：
     $$p_{\text{imp, YES}} = 1 - p_{b,\text{NO}}, \qquad s_{\text{imp, YES}} = s_{b,\text{NO}}$$
2. **卖 `YES` / 减仓平盘对称路径（预留归并，当前 `v1` 不主动卖出）**：
   - 卖 $\text{YES}$ 于 $p$ 经济等价于通过 **`merge`** 路径买入 $\text{NO}$ 于 $1 - p$（命中 $\text{NO}$ `AskBook` 后 $1\text{ YES} + 1\text{ NO} \xrightarrow{\text{CTF merge}} 1\text{ USDC}$）。
3. **费用函数在 $p \leftrightarrow 1 - p$ 下的精确代数对称性**：
   - 依 [`FACT-001`](P8-FACTS-LEDGER_静态事实档案_v0.1.md#L15) 与 [`edge_math.py#L65`](../../src/pricing/edge_math.py#L65)，Taker 费用公式为 $\text{fee}(C, p) = C \cdot r_{\text{fee}} \cdot p(1 - p)$。令 $p_{\text{imp}} = 1 - p_{b,\text{NO}}$，有：
     $$p_{b,\text{NO}}(1 - p_{b,\text{NO}}) \equiv (1 - p_{\text{imp}}) \cdot p_{\text{imp}} = p_{\text{imp}}(1 - p_{\text{imp}})$$
   - 因此在不计链上 `splitPosition` 额外 gas 且未出现跨腿 5 位小数舍入尾差前，通过 `NO` 买盘隐含获取 `YES` 的有效含费成本 `q_eff` 与直接买入 `YES` 于 $p_{\text{imp}}$ **严格相等**：
     $$q_{\text{eff}}^{\text{NO-bid}} = (1 - p_{b,\text{NO}}) + r_{\text{fee}} \cdot p_{b,\text{NO}}(1 - p_{b,\text{NO}}) = p_{\text{imp}} \big[1 + r_{\text{fee}}(1 - p_{\text{imp}})\big]$$
4. **合成统一 `AskBook(YES)` 视图与跨视图倒挂守卫（零改 `F-2`）**：
   - 对每一档 $(p_{b,\text{NO}}, s_{b,\text{NO}}) \in \text{no\_frame.bid\_book}$，计算 `p_imp_dec = Decimal("1") - Decimal(str(p_bid_no))`（仅保留 $0 < p_{\text{imp}} < 1$ 且按帧 `tick_size` 验证精度）；
   - 将 `{ (p_a, s_a, "YES_ASK") } ∪ { (p_imp, s_bid_no, "NO_BID_SPLIT_SELL") }` 按价格升序聚合并去重同价位深度，形成合并纯深度清单与**分腿溯源映射**：
     - 纯深度 `AskBook(levels=...)` 直接喂给未修改的 `edge_math.evaluate_book_edges`；
     - **跨视图套利/倒挂前置守卫（扩展 `D3`）**：当 $\text{best\_ask}_{\text{YES}} + \text{best\_ask}_{\text{NO}} \le 1 - \epsilon$ 或 $\text{best\_bid}_{\text{YES}} + \text{best\_bid}_{\text{NO}} \ge 1 + \epsilon$ 或直接腿本身 `best_ask <= best_bid` 时，标定级报警或按配置拦截异常快照；而在正常盘面下，若出现 $1 - \text{best\_bid}_{\text{NO}} < \text{best\_ask}_{\text{YES}}$（`No` 侧出价对应隐含卖价更优），合并视图优先吃掉更优档位。
   - **执行层 & `P18` 落地硬边界标注（待实现批核对）**：
     - Polymarket 实盘 `LIVE` 网关中，CLOB 仅在发单合约内置撮合引擎对 `BUY YES @ p` 与原生互补 **`BUY NO @ 1-p`**（而非 `SELL NO` 吃 `Bid(NO)`）；若主动吃 `Bid(NO)` 需前置持有 `NO`（即先链上 `NegRiskAdapter.splitPosition` 铸币后再 `SELL NO`），该两步在 Polygon 链上具有异步确认时延与 gas，无法与单笔 CLOB `IOC_FAK` 原子同构！因此设计明确区分：
       - **假盘/回放理想化撮合与 `D-6` 经济可成交视图**：`M5` 与 `P18` 按 `YES_ASK ∪ NO_BID_SPLIT_SELL` 经济等价合并吃深并分腿记录 `execution_leg`（用于量化“若打通 `No` 侧互补流动性，盘口等效深度与滑点可改善多少”）；
       - **实盘路由门控**：`LIVE` 执行器仅在配置显式启用 `enable_cross_side_split_routing=True` 并接入原子预拆分库存/原生互补订单类型时方可发单，默认 `False` 时实盘仅走 `YES_ASK`，`NO_BID_SPLIT_SELL` 仅作镜像影子对照流记录于 `P3`。
     - `P18` 间隙守卫扩展：回放撮合若实际消耗了 `NO` 侧档位，必须同步检验 `NO` token 在 `(submit_ts, arrive_ts]` 内无 `gap_detected=True` 且未触发 `max_silent_gap_sec`，任意使用到之 token 遇 gap 一律 `PAPER_MATCH_ABORTED_GAP`。

### 3.3 `D-6` 标定输入升级：`Yes + No` 双侧盘口合并视图
- **`S2-02`（`D-A1 friction_median`）与 `S2-03`（`D-6` 门槛 / `s(edge)` / `yellow_multiplier`）标定输入规范**：
  1. 标定数据集同时产出两列平行统计口径：
     - `YES_ONLY` 基线视图：仅使用 `P4(outcome="YES").ask_book`；
     - **`DUAL_MERGED` 主研究视图**：对每个 `(station_id, target_date, bin_label)` 使用 §3.2 合成之 `Ask(YES) ∪ (1 - Bid(NO))` 合并盘口，特别是回填 `YES` 侧为 `single_side="bid_only"` 但 `NO` 侧存在 `Bid(NO)` 的尾档流动性；
  2. 记录关键指标对照：`qualified_depth_gain_ratio`（双侧相比单侧新增合格股数比）、`wing_bin_ask_availability_pct`（尾桶有价档位覆盖率）、`friction_median_yes_only` vs `friction_median_dual_merged`，以及 `YES_ASK` vs `1 - Bid(NO)` 价差偏离分布（验证 CLOB 补集定价紧度）；
  3. 仅待本设计文档获用户书面回签批准后，再另开独立实现工单更新 `M4`、`M5`、`P18` 与 `D-6` 标定脚本代码。
