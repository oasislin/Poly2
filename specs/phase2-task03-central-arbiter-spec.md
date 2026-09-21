# 规格书：控制面统一异常仲裁中枢与台站级安全挂起协议 (Phase 2 Task 03)

- **Spec Issue**: [#70](https://github.com/oasislin/Poly2/issues/70) (Spec: Phase 2 Task 03 - 控制面统一异常仲裁中枢与台站级安全挂起协议)
- **Tickets**:
  - `Phase 2 Task 03 - Ticket 01`: [#71](https://github.com/oasislin/Poly2/issues/71) (Frontier)
  - `Phase 2 Task 03 - Ticket 02`: [#72](https://github.com/oasislin/Poly2/issues/72)
  - `Phase 2 Task 03 - Ticket 03`: [#73](https://github.com/oasislin/Poly2/issues/73)
  - `Phase 2 Task 03 - Ticket 04`: [#74](https://github.com/oasislin/Poly2/issues/74)
  - `Phase 2 Task 03 - Ticket 05`: [#75](https://github.com/oasislin/Poly2/issues/75)

---

## 问题陈述 (Problem Statement)

在 Polymarket 温度量化交易系统工程中，各业务子模块（数据接入、极值截断、定价模型、资金仓位、订单执行）若各自编写局部兜底逻辑（如静默吞异常、盲目重试、私自下线或降级），将导致系统在实盘极端行情下发生严重的状态分裂（Split-Brain）、假死以及隐性穿仓。

现有系统架构在控制面统一协调和资本安全防御上存在以下四大隐患与结构性痛点：
1. **异常标准碎片化与缺乏全局中枢**：子模块缺乏统一标准的 Incident 契约语言，各模块报错字段和级别不一致，导致上层无法形成确定性的系统级应急响应；
2. **数据面与控制面边界模糊**：底层公网单次网络抖动若无度退避重试，会阻塞主交易循环；反之若缺乏统一预算控制，微小扰动频繁触发全站停机，破坏交易连续性；
3. **买单前盲盒下注风险**：如果策略引擎在向网关下发订单的最后 1 秒缺乏对“数据物理新鲜度（$\le 7.0$ 分钟）”与“网络确证连通性”的强制内存同步校验，极易在外部断流或心跳陈旧时向已改变的盘口错误下注，遭受对手盘掠夺；
4. **缺乏本地物理硬关阀与生产级拔网线机制**：在外部网络拥堵或交易所接口异常时，如果仅依赖远端 `cancel_all`，一旦 API 超时或丢包，本地仍可能错误继续发射订单；同时缺乏黑天鹅现场一键硬件级断电/拔网线的运维防御通道。

---

## 解决方案 (Solution)

严格依据已裁决落地的 `ADR-0014`（统一异常仲裁中枢与台站级安全挂起协议）与《Phase 2 执行文件 v2.0》，在 `src/risk/` 架构统一控制面核心：

1. **统一 Incident 契约标准 (Standard Incident Contract)**：
   - 确立全系统各子模块向中枢上报事件的标准契约（标准 7 字段）：
     - `incident_id`: 全局唯一跟踪编码（UUID/ULID）；
     - `timestamp_utc`: 物理发生时刻（ISO 8601 UTC）；
     - `station_id`: 影响实体（限定 Active 10 交易站点或 `GLOBAL`）；
     - `subsystem`: 报告源组件（`INGESTION`, `TRUNCATION`, `PRICING`, `EXECUTION`, `SETTLEMENT`）；
     - `severity`: 严重等级（`DEGRADED`, `CORRUPTED`, `PANIC`）；
     - `reason_code`: 受控原因代码（`SANITY_BREACH`, `DATA_STALENESS`, `COR_CONFLICT`, `EXCHANGE_DOWN`, `MANUAL_EMERGENCY_STOP`）；
     - `evidence_snapshot`: 只读上下文快照（原始报文、异常堆栈或诊断摘要）。
2. **数据面与控制面分离与 30s 自愈预算衰竭 (Separation & Retry Budget)**：
   - 数据面技术瞬态（底层 HTTP 抖动、重连、Nonce 冲突）：允许就地退避重试，但耗时预算严格限制在 $\le 30\text{s}$ 内；
   - 若 30 秒预算衰竭或检测到破坏性异常，强制立即升格为 `IncidentReport` 移交控制面中枢。
3. **二元定性仲裁机制 (Dual-Categorization Arbitration)**：
   - **物理不可信 $\rightarrow$ 标的当日直接作废 (`INVALIDATED`)**：
     - 触发根因：气象数据底层真实性破坏（如 COR 修正极值冲突、单步跳温 $>15.0^\circ\text{F}$）；
     - 裁决动作：彻底剥夺该站点今日交易资格，置为 `INVALIDATED`，直至本地次日 00:00:00 物理复位前坚决禁止复活。
   - **外部通信受阻 $\rightarrow$ 标的暂时安全挂起 (`SUSPENDED`)**：
     - 触发根因：传感器物理真实性完好，仅外部公网超时、交易所断流或到达心跳超限（$>15\text{min}$）；
     - 裁决动作：标的置为 `SUSPENDED` 进入观察队列，受反振荡滞后恢复锁（Hysteresis Lock）保护（需强制冷却静默期 + 连续 3 帧健康发报探针）；
     - 衰变规则：一日内累计挂起满 3 次，强制单向衰变为当日作废（`INVALIDATED`）。
4. **买单前“新鲜度 + 连通性”双硬门禁与本地硬关阀 (Pre-Buy Gate & Local Zero-Emission)**：
   - **Pre-Buy Gate Check**：策略下发买单前强制内存同步检验：
     ① 气温观测物理新鲜度：$\Delta t_{\text{age}} \le 7.0\text{ 分钟}$；
     ② 网络连通与中枢状态：数据源与交易网关确证连通且台站为 `ACTIVE`；
     - 任一不满足直接打回意图（`REJECTED_STALE_DATA` / `REJECTED_STATION_SUSPENDED`），本地绝对静默，绝不盲盒开仓。
   - **本地硬关阀 (Local Hard Valve Shutdown)**：
     - 异常触发 0ms 内，本地内存发射阀瞬间锁死，物理切断买单字节发射；
     - 并发向远端发送 `cancel_all`（Best-Effort Cancel）；
     - **已成交持仓绝缘**：严禁向订单簿发送自动市价平仓单，安全绝缘持有至结算；到期前 30 分钟预留交割日特别后门通道（Settlement Grace Escape Hatch）。
5. **本地拔网线 CLI 与硬件级阻断触发器 (Emergency Kill-Switch & Sentinel)**：
   - 文件哨兵监听：检测到根目录 `EMERGENCY_STOP_<STATION>` 或 `EMERGENCY_STOP_ALL` 标记文件时，0ms 触发硬件级物理阻断；
   - 提供专用运维 CLI 工具，支持一键熔断单站、挂起恢复探针查询与全站紧急关停。

---

## 用户故事 (User Stories)

1. 作为量化系统架构师，我希望所有业务组件使用统一的 Incident 契约格式向中枢上报异常，以便消除异常碎片化带来的系统不可观测性。
2. 作为风控经理，我希望底层网络重试严格限制在 30 秒预算内，超时立即升格至控制面中枢，以便防止子模块陷入死循环阻塞交易。
3. 作为交易员，我希望当台站发生物理撕裂（跳温 $>15^\circ\text{F}$ 或 COR 极值冲突）时，中枢能够将其定性为当日作废（`INVALIDATED`）且当日禁止复活，以便绝对避免向虚假物理状态下单。
4. 作为交易算法工程师，我希望策略引擎在发出买单的瞬间强制经过纯内存同步双门禁，数据龄期超过 7.0 分钟或网络未连通时绝对零发射，以便根绝盲盒下注。
5. 作为资管风控官，我希望在触发严重异常时本地内存发射阀 0ms 瞬间关闭，远端执行 Best-Effort Cancel，而已成交持仓坚决不自动市价踩踏抛售，以便杜绝在稀薄流动性下的恐慌穿仓。
6. 作为运维工程师，我希望能在服务器根目录下创建 `EMERGENCY_STOP_<STATION>` 标记文件或执行 CLI 命令，立即在单站拔网线，以便在极端突发情况下具备最高优先级的物理控制权。
7. 作为质检工程师，我希望通过完整的 Test-Scenario E 验收套件验证自愈超时升级、二元仲裁作废、买单前双门禁拦截、滞后恢复锁与紧急拔网线，以便确保控制面资本防线万无一失。

---

## 实现决策 (Implementation Decisions)

- **核心接口与分层设计**：
  - `src/risk/incident_protocol.py`：定义全系统统一 Incident 契约标准（`IncidentReport`, `IncidentSeverity`, `IncidentSubsystem`, `IncidentReasonCode` 等）；
  - `src/risk/central_arbiter.py`：实现控制面唯一中枢 `CentralExceptionArbiter`，统管 Active 10 站的生命周期状态（`ACTIVE`, `SUSPENDED`, `INVALIDATED`, `EMERGENCY_HALT`），执行二元仲裁与 30s 自愈超时升格；
  - `src/risk/pre_buy_gate.py`：实现买单前纯内存同步双硬门禁 `PreBuyGateKeeper` 与本地硬关阀控制器 `LocalHardValve`；
  - `src/risk/emergency_control.py`：实现文件哨兵 `EmergencyFileSentinel` 与运维控制工具 `EmergencyKillSwitch`；
  - `src/risk/cli.py`：提供命令行紧急拔网线与台站状态查询接口。
- **与 Task 02 模块的无缝衔接**：
  - 对接 `src/prediction/temperature_sanitizer.py`：将跳温拦截与物理撕裂转换为 `IncidentReport(subsystem=TRUNCATION, severity=CORRUPTED, reason_code=SANITY_BREACH)` 提交给中枢；
  - 对接 `src/risk/stream_watchdog.py`：将 15m 到达心跳超时与 35m 物理龄期超限统一接入中枢的 `SUSPENDED` 挂起与冷却管理。
- **Active 10 交易宇宙与配置持久化**：
  - 严格限定于 `KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS`；
  - 在 `config/default.yaml` 中新增对齐 ADR-0014 的 `arbiter` 配置节（包含自愈预算 30s、新鲜度门禁 7.0m、挂起最大次数 3 次等常量）。

---

## 测试决策 (Testing Decisions)

- **单元与组件测试**：
  - `test_incident_protocol.py`：测试 IncidentReport 标准 7 字段序列化、不可变契约与受控枚举校验；
  - `test_central_arbiter.py`：测试台站状态机生命周期跃迁（ACTIVE $\to$ SUSPENDED $\to$ INVALIDATED）、二元定性仲裁逻辑、反振荡滞后恢复锁（Hysteresis Lock）及日内 3 次挂起单向衰变；
  - `test_pre_buy_gate.py`：测试买单前 $\Delta t_{\text{age}} \le 7.0\text{min}$ 门禁、网络未确证连通打回、本地硬关阀阻断与已成交持仓绝缘持有逻辑；
  - `test_emergency_control.py`：测试 `EMERGENCY_STOP_<STATION>` 标记文件侦测、CLI 紧急阻断与恢复解除。
- **集成与验收测试 (Test-Scenario E)**：
  - `tests/integration/test_scenario_e_arbiter_fail_closed.py`：
    - E1: 数据面重试超时超 30s 自动升格为 Incident，0ms 触发 CancelAll 并锁死开仓，已成交持仓绝缘；
    - E2: 物理破门禁（单步跳温 20°F 或 COR 极值倒退冲突）触发二元仲裁定性为 `INVALIDATED`，直至次日 00:00:00 LT 物理复位前严禁复活；
    - E3: 买单前物理龄期 7.5min 注入，断言被 PreBuyGate 纯内存同步拦截打回，本地绝对零发射；
    - E4: 通信恢复注入 3 帧连续健康发报，断言成功从 `SUSPENDED` 解锁回 `ACTIVE`；单日第 4 次触发挂起断言直接单向衰变为 `INVALIDATED`；
    - E5: 根目录注入 `EMERGENCY_STOP_KORD` 文件，断言 0ms 单站硬件级物理切断与开仓硬关阀。
- **网络与冒烟硬性纪律**：
  - 维持真实 GEFS 外部契约网络冒烟绿灯：
    `RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`。

---

## 范围外声明 (Out of Scope)

- 概率向 Polymarket 盘口区间积分映射 (ndtr) 与 EV 动态计算（属于 Task 04 范畴）；
- 四桶资金分配与增量凯利计算（属于 Task 05 范畴）；
- CLOB 交易签名、REST/WSS 订单路由与成交撮合状态机（属于 Task 06 范畴）。

---

## 任务垂直切片拆分 (Tickets Breakdown)

1. **`Phase 2 Task 03 - Ticket 01: feat(core): 统一 Incident 契约标准、枚举体系与事件总线总管`**
   - **内容**：实现 `src/risk/incident_protocol.py`，落地 ADR-0014 §3 法定 7 字段（`incident_id`, `timestamp_utc`, `station_id`, `subsystem`, `severity`, `reason_code`, `evidence_snapshot`），建立标准事件结构与广播分发接缝；
   - **依赖**：无（Frontier）。

2. **`Phase 2 Task 03 - Ticket 02: feat(arbiter): 控制面 CentralExceptionArbiter 状态机与二元仲裁定性引擎`**
   - **内容**：实现 `src/risk/central_arbiter.py`，管理 Active 10 站生命周期状态（ACTIVE, SUSPENDED, INVALIDATED, EMERGENCY_HALT），落实二元仲裁准则（物理破坏 $\to$ INVALIDATED 至 EoD，通信受阻 $\to$ SUSPENDED 滞后恢复，日内 3 次挂起衰变至 INVALIDATED），集成 30s 自愈超时升格机制；
   - **依赖**：Blocked by `Ticket 01`。

3. **`Phase 2 Task 03 - Ticket 03: feat(risk): 买单前双连通硬门禁、本地零发射硬关阀与挂起协议`**
   - **内容**：实现 `src/risk/pre_buy_gate.py`，落地买单前强制内存同步双校验（数据新鲜度 $\Delta t_{\text{age}} \le 7.0$ min + 网络确证连通），实现本地硬关阀控制器（LocalHardValve），确立 0ms 关阀与已成交持仓绝缘持有原则（到期前 30min 留特别后门）；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 02`。

4. **`Phase 2 Task 03 - Ticket 04: feat(emergency): 根目录紧急制动触发器与拔网线运维 CLI`**
   - **内容**：实现 `src/risk/emergency_control.py` 与 `src/risk/cli.py`，监听项目根目录 `EMERGENCY_STOP_<STATION>` 与 `EMERGENCY_STOP_ALL` 文件哨兵，提供 CLI 命令行一键阻断与状态查询，与 CentralExceptionArbiter 联动实现单站/全站硬件级断电；
   - **依赖**：Blocked by `Ticket 02`。

5. **`Phase 2 Task 03 - Ticket 05: test(acceptance): 统一异常中枢端到端全链路与 Test-Scenario E 验收门禁`**
   - **内容**：实现端到端全链路集成测试，全量覆盖 Test-Scenario E1~E5 验收门禁（30s 超时升级、物理破门禁作废、买单前新鲜度打回、连续 3 帧滞后恢复与衰变、文件哨兵紧急拔网线），确保持续满足 GEFS 真实网络冒烟绿灯；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 02`, `Ticket 03`, `Ticket 04`。
