# P8-STATION-SCOPE-AUDIT：站域口径三层只读对账与假盘站集裁定依据呈报（`2026-11-26` / 实查于 `2026-11-27`）

- **工单编号**：`P8-WO-20261126-EXEC19-STATION-SCOPE-AUDIT`（`PUSH-AUTO-OK` · 纯只读审计，零代码、零配置、零账本数据变更）
- **审计目的**：对账“假盘第一波 2 站（历史记忆） vs 现行产线 6 站（`P5 / P13 / P1`）vs `Active 10` 全集”三层客观事实；按语料门“覆盖 `>= 4` 站”及 `GATE-LIVE` `14 天 / >=30 站-日` 时钟呈报业主站集裁定依据，并在 `P3` 首笔成交开启前固化站集签字点。
- **范围边界声明**：本报告仅记录只读检索与实测结果，**不在本单修改任何规格正文、代码常量或 `P8-PARAMETER-LIFECYCLE-REGISTRY_v1.0.md`**；一切规格修订与 `STATION_UNIVERSE` 入册均列为提案候业主签署。

---

## §1 三层只读对账（逐字粘贴 + 精确路径与行号）

### 1.1 规格层全仓检索（8 部法定与历史文档逐字摘录）

| 文档与位置 | 原文逐字摘录 | 涉及站集/语义定位 | 备注 |
| :--- | :--- | :--- | :--- |
| [`Phase 1 执行文件 v5.9.2(细化版).md#L12`](../项目方案和执行文档/Phase%201%20执行文件：项目执行文件%20v5.9.2(细化版).md#L12) | `*   **模型总量**：20 模型/站 \times 2 站 = 40 组参数。` | 历史 Phase 1 `2 站`（`{ZSPD, KDEN}`） | 已被 `项目方案 v3.0 §0 L27` 声明彻底作废隔离 |
| [`docs/ROADMAP.md#L29-L30`](../ROADMAP.md#L29-L30) | `全美核心 Active 10 台站（KATL, KAUS, KDAL, KHOU, KLAX, KLGA, KMIA, KORD, KSEA, KSFO）的原始气象观测历史全部达到 78.55~96.72 年...` / `真正完成 20 折 Block-CV 独立选型与严格可靠度审计的仅有 KORD 与 KMIA 的 TMax（24/120 提前期格，即 2/10 站）；其余 8 站 TMax 覆盖率为 0%` | 模型审计范围 `Active 10` vs W2 先行 `2/10` 站 | 历史背景（后续 `data/models/manifest.json` 已全盘 1,200 模型） |
| [`docs/ROADMAP.md#L85-L86`](../ROADMAP.md#L85-L86) | `### 3.2 W2 —— Phase 2 双站短闭环` / `- **先锋阵容**：KORD（芝加哥奥黑尔）与 KMIA（迈阿密国际机场）双站，直接入役 P6 封卷之 24 时间格/96 季节格 TMax 资产；` | **W2 只读短闭环 `2 站`**（旧路线图） | 属 Phase 2 W2，非 `§3.4` 之 `T9 / S3-11` |
| [`项目方案 (v3.0).md#L47`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#L47) | `- **波次二（W2，主线）**：Phase 2 战术收窄为双站（KORD/KMIA）只读纸面盘短闭环，攻坚 Task 02（实况单调合流与特报截断）与 Task 04（2°F 离散映射与动态 EV 引擎）` | **W2 `2 站`**（承接 `ROADMAP §3.2`） | `§8.1 M1–M10` 后 α 架构未再限定 `2 站` |
| [`P8-ALGO-DEF-SPEC_20261108_v2.0.md#L45`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md#L45) | `- **生产法定契约生效台站**：**AUTHORIZED_STATIONS = ("KORD", "KMIA")**（**业主已裁决，首批上线范围**；CONF-02 选 A 已落地，仅该 2 站共 22 个有效提前量格位完成参数契约校验）。**其余 8 站保持「待正式定参后接入，严禁外推」**。` | **`CONF-02` 首批 2 站历史裁定（⚠️ 标红分叉）** | 2026-11-08 架构 `α` 前定下，后续 `T8` 与 6 站 `S2-01/S3-17` 并未显式废止本条 |
| [`P8-ALGO-DEF-SPEC_凹性与层数收口答复_20261108.md#L79`](P8-ALGO-DEF-SPEC_凹性与层数收口答复_20261108.md#L79) | `在首发试点仅上线 KORD 与 KMIA 2 个站时，由于 N = 2 < n_min，实施方实事求是地承认：在单轮瞬时发单场景下，两站打满亦无法耗尽日预算` | **首发 `2 站` 试点算术分析** | 同期 `L124` 写明 `坦承 2 站试点单轮不约束` |
| [`P8-KERNEL-CONSENSUS v1.1 §六 C L148-L152`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md#L148-L152) | `### C｜D-4 增补（假盘身份、真盘切换门与撮合规则 · 2026-11-17）`：`假盘与真盘采用完全同构的四元组及执行日志 schema，强标识 execution_mode = "PAPER" | "LIVE"` | **无站数限制条款** | `§六` 全文未设定假盘仅跑 2 站 |
| [`P8-T2-M7-LOGGING v1.3 §2.1 L42`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#L42) | ``| `station_id` | `str` | ✓ | ICAO 台站代码（必须属 Active 10） |`` | **`Active 10` 全集合法** | 未限定 2 站，亦未锁死 6 站 |
| [`P8-CAPITAL-CONFIG v1.1 §1 L13 / §1.5 L28`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#L13-L32) | `总资金池：$10,000（满部署语义 ≈ 10 站点总额度上限...）`；`D_deploy = min(P_tier / D_hold, 活跃站数 N × B)`；`按业主实际批准的活跃站数 N 与总资金池 P_tier 依上式计算` | **按活跃站数 $N$ 参数化** | 明确由业主批准活跃站数 $N$ |
| [`P8-D6-POLICY-CLOSURE v1.0 §三 L64`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#L64) | `冻结假盘连续运行 >= 14 个日历日（或覆盖 >= 30 个已结算站-日市场），且已录得 >= 20 笔经 P18 真实延迟帧撮合（capture_replay_mode="REPLAY_P13"）的模拟成交记录（FILLED 或 PARTIAL）` | **`GATE-LIVE` 14 日 / 30 站-日门** | 时钟周期与站数 $N$ 直接耦合 |
| [`P8-D6-POLICY-CLOSURE v1.0 §七 L122`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#L122) | `真盘切换首期（S3-12 通过后首月）按当期总部署配置下的默认站点全额执行（单站上限 $500 / 站... 如初期总部署先开 $2,000 覆盖 4 站）` | **真盘初期示例覆盖 `4 站`** | 不固定 2 站 |
| [`P8-D6-POLICY-CLOSURE v1.0 §八 L132`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#L132) | `离线录盘走簿：>= 200 次有效深度模拟切片覆盖至少 4 个站、连续 >= 72h 0.01 时代录盘` | **语料定标通用门槛：`>= 4 站`** | `S2-02` 与 `P8-PARAMETER-LIFECYCLE-REGISTRY §1` 均继承此 **`>= 4 站`** |
| [`P8-RECORDER-NO-SIDE-DESIGN v0.1 §1.1 L17`](P8-RECORDER-NO-SIDE-DESIGN_尾桶单侧与No侧双视角升级设计书_v0.1.md#L17) | `配置站表：configs/passive_book_recorder.example.yaml 更新为 6 站 ["KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA"]` | **录盘正式升级为 `6 站`** | 2026-11-21 批复落地 |
| [`P8-PROJECT-TASKS §2.2 S2-01 L56`](P8-PROJECT-TASKS_全量任务分解台账.md#L56) | `多日被动录盘建盘口基线（6 站 Yes+No 双侧 + 00:05Z 轮转 + single_side）` | **`S2-01 = 6 站 DONE`** | 六站与上游采集/录盘对齐 |
| [`P8-PROJECT-TASKS §2.3 S3-17 L85`](P8-PROJECT-TASKS_全量任务分解台账.md#L85) | `总装 6 站（KORD, KMIA, KLGA, KATL, KDAL, KSEA）GEFSFetcher.download_realtime(atmos.25) ...` | **`S3-17 = 6 站 DONE`** | `EXEC13` 批复后落地 |
| [`P8-PROJECT-TASKS §2.3 S3-11 L79`](P8-PROJECT-TASKS_全量任务分解台账.md#L79) | `model_hash 上线日冻结，execution_mode="PAPER" 消费 P13 实时录盘并注入真实延迟帧撮合，零 LIVE 发单` | **`S3-11 (T9)` 未限制站数** | 消费 `P13` 全盘（隐含承接 `S2-01` 6 站） |
| [`P8-PROJECT-TASKS §2.3 S3-15 L83`](P8-PROJECT-TASKS_全量任务分解台账.md#L83) 与 [`试单运行手册 §1 L17`](P8-S305B-TRIAL-RUNBOOK_试单运行手册草案_v0.1.md#L17) | `KMIA/KORD D+1 核心温区 YES（best_ask ∈ [0.25, 0.55]，禁 mid 锚定）` | **`S3-15` 真钱三探针试点仅 `KMIA/KORD` 2 站** | 系 **`S3-15` 真钱小额试单段**专用，非 `S3-11` 假盘 |

> **规格层核心发现**：
> 1. 仓库内 **存在三处历史“2 站（`KORD, KMIA`）/ `2 站`"条款**：① Phase 1 `{ZSPD, KDEN}`（已废）；② Phase 2 W2 `KORD/KMIA` 双站只读短闭环 + `CONF-02` [`AUTHORIZED_STATIONS = ("KORD", "KMIA")`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md#L45)（`2026-11-08`）；③ [`S3-15` 真钱三探针试单段](P8-S305B-TRIAL-RUNBOOK_试单运行手册草案_v0.1.md#L17)（`KMIA/KORD` 真钱 `$5` 上限测试）。
> 2. **不存在任何规定“`S3-11 (T9)` 假盘只跑 2 站”的现役 P8 条款**；相反，`S2-01`（录盘）、`S3-17`（实时 `P5`）、`P8-D6`（`>= 4 站` / `30 站-日`）与 `S3-11`（全盘消费 `P13`）天然指向 **6 站集**。同时，由于 `P8-ALGO-DEF-SPEC §1.1 L45`（`CONF-02`）从未发布废止或扩站修订注记，严格存在 **规格历史条款（`2 站`）与现役实践（`6 站`）之显式分叉**。

---

### 1.2 代码与配置层全仓检索（含站过滤核证）

| 文件与行号 | 逐字代码 / 配置常量 | 站数 | 用途与影响面 |
| :--- | :--- | :---: | :--- |
| [`configs/passive_book_recorder.example.yaml#L4-L10`](../../configs/passive_book_recorder.example.yaml#L4-L10) | `stations: [KORD, KMIA, KLGA, KATL, KDAL, KSEA]` | `6` | 现役 `PID 88755/90929` 实采配置 |
| [`src/data_acquisition/passive_book_recorder.py#L40-L48, L144, L165`](../../src/data_acquisition/passive_book_recorder.py#L40-L48) | `CITY_BY_STATION = {"KORD": "Chicago", "KLGA": "NYC", "KATL": "Atlanta", "KDAL": "Dallas", "KSEA": "Seattle", "KMIA": "Miami"}`; `stations: Tuple[str, ...] = ("KORD", "KMIA")` | `6` (fallback `2`) | 若 YAML 缺 `stations` 才回退 2 站；现役 YAML 覆盖为 6 站 |
| [`src/prediction/live_p5_producer.py#L61, L97`](../../src/prediction/live_p5_producer.py#L61) | `SUPPORTED_LIVE_STATIONS: Tuple[str, ...] = ("KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA")` | `6` | 现役 `PID 59745` 默认拉取站集 |
| [`scripts/run_live_p5_producer.py#L131, L152-L161`](../../scripts/run_live_p5_producer.py#L131) | `parser.add_argument("--stations", nargs="+", default=list(SUPPORTED_LIVE_STATIONS))` | `6` | `_resolve_station_targets` 仅校验 `close_utc > issue_ts`，无站过滤 |
| [`src/prediction/live_p5_producer.py#L549-L571`](../../src/prediction/live_p5_producer.py#L549-L571) | `def discover_p13_market_ladders(...): for env in loaded.envelopes: grouped.setdefault((env.station_id, env.target_date), set()).add(env.bin_label)` | **纯数据驱动** | **零站点白名单/过滤**：从 `P13` 全量信封动态发现 `(station_id, target_date)` 档梯 |
| [`scripts/run_s311_offline_scheduler.py#L120-L139`](../../scripts/run_s311_offline_scheduler.py#L120-L139) | `def discover_p13_schedule_targets(session_dir: Path): for env in loaded.envelopes: if env.payload.outcome != "YES": continue ...` | **纯数据驱动** | **零 `STATION_FILTER` / 零站子集截断**：只过滤 `outcome == "YES"`，扫遍会话内全站全市场 |
| [`src/decision/offline_scheduler.py#L164-L208`](../../src/decision/offline_scheduler.py#L164-L208) | `def _evaluate_tick_target(...): pairs = retriever.retrieve_decision_book_pairs(...)` | **无站过滤** | 对入参 `targets` 逐条执行评估，零站点裁剪 |
| [`src/audit/readonly_watchdog.py#L97`](../../src/audit/readonly_watchdog.py#L97) | `expected_stations: Tuple[str, ...] = ("KATL", "KDAL", "KLGA", "KMIA", "KORD", "KSEA")` | `6` | 巡检告警与 `M3` / `S2-01` 同构 6 站 |
| [`configs/policy_ledger.json#L23-L30`](../../configs/policy_ledger.json#L23-L30) | `"stations_covered": ["KATL", "KDAL", "KLGA", "KMIA", "KORD", "KSEA"]` | `6` | `EXEC15` 签发 `friction_median` 时 `S2-02` 实测覆盖 6 站 |
| [`src/data_processing/constants.py#L379-L406`](../../src/data_processing/constants.py#L379-L406) | `ACTIVE_11_STATIONS` (`11` 站含 `KBKF`); `ACTIVE_10_STATIONS = ("KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX", "KHOU", "KMIA", "KSFO", "KAUS")` | `10 / 11` | `discrete_bin_engine.py`, `constraint_enforcer.py`, `registry.py` 校验基准 |
| [`data/models/manifest.json`](../../data/models/manifest.json) | `model count: 1200`, `stations: ['KATL', 'KAUS', 'KDAL', 'KHOU', 'KLAX', 'KLGA', 'KMIA', 'KORD', 'KSEA', 'KSFO']`, `vars: ['Max', 'Min']` | `10` | 模型资产层覆盖全部 `Active 10` 站 × 双标的 (`1,200` 个模型) |
| ⚠️ **[标红]** [`src/contract/parameter_contract.py#L26-L28, L126-L128`](../../src/contract/parameter_contract.py#L26-L28) | `AUTHORIZED_STATIONS: Tuple[str, ...] = ("KORD", "KMIA")`, `TOTAL_AUTHORIZED_CELLS = 22`；`if station not in AUTHORIZED_STATIONS: raise ...` | **`2`（硬过滤！）** | 被 `param_table_converter/validator`, `version_watchdog` 与 2019 封跑脚本引用；**在 `live_p5_producer.py` / `offline_scheduler.py` 中均未被导入或调用** |
| ⚠️ **[历史残留]** [`configs/default.yaml#L6-L12`](../../configs/default.yaml#L6-L12) | `stations: [KLGA, KORD, KBKF, ZSPD]`, `suspended_stations: [KDEN]` | `4` | 旧 Phase 1.5 默认配置，未接入 P8 实盘/假盘链 |

- **全链路过滤逻辑核查结论**：对 `src/decision/`、`src/bankroll/`、`src/execution/`、`src/audit/`、`src/settlement/` 全目录检索 **`STATION_FILTER`、`AUTHORIZED_STATIONS`、`SUPPORTED_LIVE_STATIONS`、`ACTIVE_10` 命中数 = 0**（除 `readonly_watchdog.py#L97` 期望站表与 `bankroll/manager.py` 按单站累积亏损闸字典键外）。确认 **`S3-11` 离线调度器与决策链为 100% 纯 `P13` 数据驱动**，当前生产跑出的 6 站结果严格源自 `configs/passive_book_recorder.example.yaml` 录盘输入集，无任何隐藏代码滤波或白名单拦截。

---

### 1.3 实践层实时实测汇总（采样时刻：`2026-11-27T14:35+08:00`）

| 数据流 / 证据工件 | 站数与站集 | 精确分布与计数 |
| :--- | :---: | :--- |
| **`M3` 在采 `P13` 会话** (`rec-20261127T000501Z-04aca9`) | **`6` 站** | `targets = 198`（每站恰好 `33` 档），**`18` 组 `(station_id, target_date)`**（`KATL:3, KDAL:3, KLGA:3, KMIA:3, KORD:3, KSEA:3`，均覆盖 `2026-11-26, 2026-11-27, 2026-11-28`）；`discover_p13_market_ladders(active_only=True)` 返回完整 `18` 个连续阶梯（零失败）。历史 `11-21..26` 全 `18` 个已完成目录日分片均严格覆盖此 6 站（仅跨日残段缺个别已停盘日期）。 |
| **`M1/M2` `P5` 实时快照** (`data/live_p5/p5_live_20261126.jsonl`) | **`6` 站** | 累计 **`371` 条** `p17.v3`（覆盖 **`18` 个唯一 `(station_id, target_date)`**）：`{'KATL': 60, 'KDAL': 59, 'KLGA': 62, 'KMIA': 59, 'KORD': 59, 'KSEA': 72}`。 |
| **`M4/M7` `P1` 扫描与下单** (`data/audit_logs/PAPER/`) | **`6` 站** | **总扫描 `193,050` 条**（覆盖 `24` 组站-日市场，含 `11-25` 闭盘拒单）：<br>• `2026-11-26`：`116,028` 条 `p1`（`6` 站严格各 `19,338` 条），`ORDERED = 553`（`KATL:84, KDAL:93, KLGA:86, KMIA:76, KORD:68, KSEA:146`）；<br>• `2026-11-27`：`77,022` 条 `p1`（`6` 站严格各 `12,837` 条），`ORDERED = 278`（`KATL:57, KDAL:55, KLGA:43, KMIA:37, KORD:46, KSEA:40`）；<br>• 累计 `ORDERED = 831` 分布于全部 `6` 站（`{'KATL': 141, 'KDAL': 148, 'KLGA': 129, 'KMIA': 113, 'KORD': 114, 'KSEA': 186}`），无单一站点真空或垄断。 |
| **`M7` `P17` 审计消费** (`data/audit_logs/PAPER/`) | **`6` 站** | 累计 **`371` 条**（`11-26`: `224` 条；`11-27`: `147` 条），与 `data/live_p5/` 全量对齐，覆盖全 6 站。 |
| **`S2-02` 标定档案** (`configs/policy_ledger.json`) | **`6` 站** | `YES_ONLY` `9,387` 有效成交切片严格覆盖全 `6` 站（`median = 0.071645`）。 |

---

## §2 三列对照表与口径分歧标注

| 维度 | 规格层声明 | 代码与配置层现状 | 实践层运行事实 | 对账结论 / 分歧标注 |
| :--- | :--- | :--- | :--- | :--- |
| **旧 Phase 2 W2 / `CONF-02`** | `AUTHORIZED_STATIONS = ("KORD", "KMIA")`（`P8-ALGO-DEF-SPEC §1.1 L45`）；`ROADMAP §3.2` W2 `2` 站 | `src/contract/parameter_contract.py#L26` 写死 2 站（**未接入** `live_p5_producer` / `offline_scheduler`）；`manifest.json` 实际有 10 站 1,200 模型 | `PID 59745 / 60359` 在 `6` 站实产运行（`193,050` 条 `P1` 覆盖 6 站） | ⚠️ **`spec-practice divergence`**：`CONF-02`（2026-11-08）未随 `T8` 与 `S2-01/S3-17`（6 站）同步修订/废止 |
| **录盘与在线 `P5` (`S2-01 / S3-17`)** | `NO-SIDE-DESIGN §1.1`、`S2-01`、`S3-17` 均显式指定 `6` 站（`KORD, KMIA, KLGA, KATL, KDAL, KSEA`） | `passive_book_recorder.example.yaml` = 6 站；`SUPPORTED_LIVE_STATIONS` = 6 站；`readonly_watchdog` = 6 站（仅 recorder 无 yaml 兜底 = 2 站） | `rec-20261127T000501Z-04aca9` 与 `data/live_p5/` 全为 `6` 站 `18` 组站-日 | **一致（6 站）** |
| **假盘调度与执行 (`S3-11 / T9`)** | `S3-11 L79` / `KERNEL §六 C`：**无站数限制**（消费 `P13` 全录盘） | `discover_p13_schedule_targets` 纯数据驱动，**零站过滤** | 消费全 `6` 站 `198` YES tokens，`831` 笔 `ORDERED` 覆盖全 `6` 站 | **代码与实践一致；规格层“仅靠 `P13` 隐含继承 6 站，缺显式站集批文”** |
| **准入与校准门 (`S2-02 / S3-16 / GATE-LIVE`)** | `D6 §八`: 覆盖 **`>= 4` 站**；`D6 §三`: `>= 14` 天 **或** `>= 30` 站-日；`M7-LOGGING`: `Active 10` | `policy_ledger.json` 覆盖 `6` 站；`ece_evaluator.py` 按全量 `P17/P9` 评估无站裁剪 | `6` 站均具备 `S2-02` 实测滑点支撑与每日 `6` 站-日供给能力 | **一致且 6 站较 4 站门槛留有 +2 站冗余；若缩回 2 站则违反 `>= 4` 站门** |
| **真钱试单三探针 (`S3-15`)** | `试单手册 §1 L17` & `S3-15 L83`：仅 **`KMIA/KORD`**（2 站 `D+1` 核心区 `<= $5` 敞口） | 当前 `PAPER` 冻结态（`STANDING-DIRECTIVE-NOREAL-ORDER`） | 尚未触发（`0` 真钱单） | **语义区隔明确**：2 站仅属 `S3-15` 真钱 3 探针，**不可混淆作 `S3-11` 假盘上限** |

---

## §3 业主站集裁定依据呈报（本单不裁，候业主签字点）

### 3.a 维持当前 6 站方案（`KORD, KMIA, KLGA, KATL, KDAL, KSEA`）核心依据

1. **语料最小代表性门槛余量（`>= 4` 站硬约束）**：
   - `P8-D6 §八 L132` 与 `P8-PARAMETER-LIFECYCLE-REGISTRY §1` 均明确校准语料门槛要求**覆盖至少 `4` 个站**；现行 `6` 站提供 `+2` 站冗余度（即使单一站点因休眠/接口限流偶发缺测，仍稳稳满足 `>= 4` 站代表性）。
2. **与 `14` 天浸泡周期及 `30 / 60 / 200 / 300` 站-日时钟精准对齐**：
   - **假盘准入门（`P8-D6 §三 L64` `>= 30` 站-日）**：在 `6` 站并行下，每日可自然结算 **`6` 站-日/天**，`5` 天即可积满 `30` 站-日，在 `14` 日浸泡期内稳获 **`~84` 站-日**（不仅全覆盖 `30` 站-日最小门，且单轮 14 日即可超过 `S4-01` `60` 站-日成熟审查门槛！）；
   - **若退回 `2` 站**：每日仅 `2` 站-日，集满 `30` 站-日即需整 **`15` 天**（直接超出 `14` 日浸泡窗且 `0` 容错），集满 `60` 站-日需 **`30` 天**，`AUTO_BINNING_UPGRADE (200)` 需 **`100` 天**（vs 6 站 **`~33.3` 天**）。
3. **六站气候与盘口结构多样性实证（严格依据仓库受控元数据 [`STATION_METADATA`](../../src/data_processing/constants.py#L73-L226)、[`partitioner.py#L267-L305`](../../src/modeling/partitioner.py#L267-L305) 及 [`ROADMAP §3.3 L109-L112`](../ROADMAP.md#L109-L112)）**：

| 站代码 | 机场 / 城市 | 经纬度 & 海拔 (`STATION_METADATA`) | 时区 (`partitioner.py`) | `coastal_microclimate` | `microclimate_score` | `audit_status` / 原型归类 | 历史覆盖率 / 盘口流动性 |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- | :---: |
| **`KORD`** | Chicago O'Hare (`chicago`) | `41.97°N, -87.90°E, 205.0m` | `America/Chicago` (`Central`) | `False` | `98.0` | `ADMITTED_TIER_1` / 原型 1（`KORD` 原型） | `99.7%` / `$38,000` |
| **`KATL`** | Atlanta (`atlanta`) | `33.64°N, -84.43°E, 313.0m` | `America/New_York` (`Eastern`) | `False` | `95.0` | `ADMITTED_TIER_1` / 原型 3（阿巴拉契亚山麓冷池） | `99.7%` / `$25,000` |
| **`KDAL`** | Dallas Love Field (`dallas`) | `32.85°N, -96.85°E, 148.0m` | `America/Chicago` (`Central`) | `False` | `95.0` | `ADMITTED_TIER_1` | `99.1%` / `$22,000` |
| **`KLGA`** | LaGuardia (`nyc`) | `40.77°N, -73.87°E, 4.0m` | `America/New_York` (`Eastern`) | `True` | `82.0` | `ADMITTED_TIER_1` | `99.6%` / `$45,000` |
| **`KMIA`** | Miami Intl (`miami`) | `25.79°N, -80.29°E, 3.0m` | `America/New_York` (`Eastern`) | `True` | `75.0` | `ADMITTED_TIER_2` / 原型 2（`KMIA` 原型） | `99.5%` / `$65,000` |
| **`KSEA`** | Seattle-Tacoma (`seattle`) | `47.45°N, -122.31°E, 132.0m` | `America/Los_Angeles` (`Pacific`) | `True` | `85.0` | `ADMITTED_TIER_2` | `99.4%` / `$24,000` |

   - 六站天然构成 **`3` 内陆 (`coastal_microclimate=False`) + `3` 沿海 (`True`)**，跨 **`Eastern / Central / Pacific` 三大美国大陆时区**、纬度跨度 **`25.79°N–47.45°N`**、海拔 **`3.0m–313.0m`**，完整涵盖 `ROADMAP §3.3` 三大原型与全 `6` 站 `S2-02` 实测滑点先验；相比单靠 `KORD + KMIA` 2 站（`P8-ALGO-DEF-CORE §二 L69` 已自承“空间样本量 $K=2$ 无法估计全国模型方差分布”），6 站消除了单沿海/单内陆偏倚。
4. **`TMAX-only` 现状说明**：
   - 当前线上 `discover_p13_schedule_targets` 与 `live_p5_producer.py` 均仅扫描 `target_type = "TMAX"`（与 `P8-PROJECT-TASKS §1 M2`: `TMIN 维持现状至 W3` 一致），每日每站对应 `1` 个唯一当日结算标的，不存在 TMAX/TMIN 双倍站-日混淆。

---

### 3.b 选项对照表：修订规格采纳 6 站 vs 回归历史 2 站

| 对照维度 | 方案甲：**修订规格正式采纳 6 站**（`KORD, KMIA, KLGA, KATL, KDAL, KSEA`） | 方案乙：**强制回归 `2` 站**（仅 `KORD, KMIA`） |
| :--- | :--- | :--- |
| **语料门（`>= 4` 站）** | **原生满足并有 +2 站冗余**（`6 >= 4`），与 `S2-02` 实测 6 站 `friction_median`（`9,387` 切片）同源同集 | **违背 `>= 4` 站法定门槛**（`2 < 4`，永不达标，必须同步废除/重改 `D6 §八` 与 ECE 语料门；`S2-02` 6 站滑点与 2 站测试集出现口径失配） |
| **假盘 14 日浸泡时钟 & `30/60/200/300` 门** | `6` 站-日/天：`30` 站-日 **`≈ 5` 天**；`14` 天可积 **`~84` 站-日**（一次越过 `60` 成熟审查门）；`200` 升档 **`≈ 33.3` 天** | `2` 站-日/天：`30` 站-日需 **`15` 天**（卡死 14 日浸泡时钟，无断流容错）；`60` 站-日需 **`30` 天**；`200` 升档需 **`100` 天**；`300` 成熟区需 **`150` 天（~5 个月）** |
| **现有产线与数据连续性** | **`PID 88755/90929`、`59745`、`60359` 全线零停机延续**；已沉淀 `371` 条 `P5/P17`、`193,050` 条 `P1`（含 `831` `ORDERED`）全量有效 | 须修改 `passive_book_recorder.example.yaml`、`run_live_p5_producer`、过滤掉已采 `4` 站资产，`831` 笔 `ORDERED` 中 `603` 笔（`72.56%`：`KATL/KDAL/KLGA/KSEA`）作废或隔离 |
| **规格/文档需执行变更** | 经业主签发版本注记修订 [`P8-ALGO-DEF-SPEC §1.1 L45`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md#L45)（`CONF-02` `2` 站历史范围标注为“已由 `P8-S2-01/S3-17/T9` `6` 站集演进替代”；`S3-15` 真钱三探针仍维持 `KMIA/KORD` 2 站不动），并在台账 `S3-11` 显式写入假盘站集 | 需修改 `S2-01 / S3-17` 配置与下游采集策略（逆转已落地的 6 站设计），并下调/重写 `D6 §八` `>= 4 站` 规则 |
| **`S3-15` 真钱三探针兼容** | **互不冲突**：`S3-11` 假盘 6 站测分布/滑点/资金闸；`S3-15` 触发时仍按手册仅在 `KMIA/KORD` 2 站执行 `$5` 上限真钱 3 探针 | — |

---

### 3.c `STATION_UNIVERSE` 五要素登记提案（候 `EXEC18 C` 后独立工单入册，本单零写入）

> 按业主 `doctrine` 与本单第 `3.c` 条指令，仅在本节呈报 `STATION_UNIVERSE` 五要素条目草案，**严禁在本单直接写入 [`P8-PARAMETER-LIFECYCLE-REGISTRY_v1.0.md`](P8-PARAMETER-LIFECYCLE-REGISTRY_v1.0.md)**：

| 参数名称 | 初值 (`initial_value`) | 来源 (`provenance`) | 再标定触发条件 (`re_estimation_trigger`) | 再标定方法 (`re_estimation_method`) | 生效权限 (`authority`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`STATION_UNIVERSE`（假盘与在线 `P5/P13/P1` 活跃站集）** | **6 站** `("KORD", "KMIA", "KLGA", "KATL", "KDAL", "KSEA")`（`TMAX-only`，从 [`SUPPORTED_LIVE_STATIONS`](../../src/prediction/live_p5_producer.py#L61) 与 [`passive_book_recorder.example.yaml`](../../configs/passive_book_recorder.example.yaml#L4-L10) 对齐；全美合法母池 `ACTIVE_10_STATIONS`） | `S2-01`（6 站 `P13` 基线，`EXEC13 DONE`）、`S2-02`（6 站 `YES_ONLY=0.071645`，`EXEC15 DONE`）、`S3-17`（6 站 `P5`，`EXEC13 DONE`）、`P8-D6 §八`（`>= 4` 站与 `30` 站-日时钟对齐）；`S3-15` 真钱 3 探针维持独立子集 `("KMIA", "KORD")` | 下列任一发生时触发扩缩站复核：① 进入 **`W3` 横向扩展阶段**（按 `ROADMAP §3.3` 拟接入剩余 4 站：`KLAX, KHOU, KSFO, KAUS`）；② 单站在 `S4-01` 月度复检触发长期录盘断崖 / `P13 gap > 10%` 或 `$500` 硬亏损闸；③ Polymarket 官方下线/变更结算站或 `W3` 开放 `TMIN` | ① 扩站准入：核对目标站在 [`constants.py`](../../src/data_processing/constants.py) 元数据状态、WSS `<= 200 tokens/shard` 分片余量及 `S2-02` 重走簿滑点；② 缩站退回：单向收紧，保持剩余站数 `>= 4` 以不破坏 `ECE / D6` 语料代表性门 | **站集清单增删 = 业主显式签发**（须同步更新 `configs/passive_book_recorder.example.yaml`、`SUPPORTED_LIVE_STATIONS`、`readonly_watchdog.expected_stations` 与台账 `§1 M3`） |

---

## §4 审计门禁、无代码变更声明与待裁签字点

1. **纯只读零污染声明**：本次审计零创建、零修改任何 `src/`、`scripts/`、`tests/`、`configs/` 或 `P8-PARAMETER-LIFECYCLE-REGISTRY_v1.0.md` 与运行时 `data/` 文件；双冻结区、[`configs/policy_ledger.json`](../../configs/policy_ledger.json)、`S3-11`/`S3-16` 台账行及在产进程（`PID 88755/90929`、`59745`、`60359`）全程零触碰零重启。
2. **业主签字点（候在 `P3` 首笔真成交前拍板）**：
   - 请裁定是否批复 **§3.b 方案甲（维持 `6` 站全集跑 `S3-11` 假盘，修订历史 `CONF-02` `2` 站口径注记，并保留 `S3-15` 真钱试单段仅用 `KMIA/KORD`）** 并将 §3.c `STATION_UNIVERSE` 写入参数生命周期登记册；此裁决亦同步为 `EXEC18 A` 重启/旁路开启 `p3/p9` 浸泡计时铺平前置口径。
