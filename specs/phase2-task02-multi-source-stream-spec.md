# 规格书：多源实况合流、特报高频截断与两维阶梯风控引擎 (Phase 2 Task 02)

- **Spec Issue**: [#64](https://github.com/oasislin/Poly2/issues/64) (Spec: Phase 2 Task 02 - 多源实况合流、特报高频截断与两维阶梯风控引擎)
- **Tickets**:
  - `Phase 2 Task 02 - Ticket 01`: [#65](https://github.com/oasislin/Poly2/issues/65) (Frontier)
  - `Phase 2 Task 02 - Ticket 02`: [#66](https://github.com/oasislin/Poly2/issues/66)
  - `Phase 2 Task 02 - Ticket 03`: [#67](https://github.com/oasislin/Poly2/issues/67)
  - `Phase 2 Task 02 - Ticket 04`: [#68](https://github.com/oasislin/Poly2/issues/68)
  - `Phase 2 Task 02 - Ticket 05`: [#69](https://github.com/oasislin/Poly2/issues/69)

---

## 问题陈述 (Problem Statement)

在 Polymarket 温度二元期权预测市场中，当真实物理气温推进时，任何已被实测超越的温度档位（对于最高温 TMAX，实测已达 $T_{obs}$ 则所有 $< T_{obs}$ 的区间；对于最低温 TMIN，实测已达 $T_{obs}$ 则所有 $> T_{obs}$ 的区间）在物理上已绝对不可能成为最终结算极值，其结算概率应被不可逆地归零。

然而，现有系统在实况接入与动态截断上存在四个严重的结构性缺陷：
1. **历史切换窗倒挂与脏数据污染**：旧版规范设计了“名义极值前 2h 切换至实况源”的硬切换逻辑，不仅因切换网络抖动带来状态机震荡，而且原方案依赖的 Wunderground 爬虫数据因存在严重系统性偏差已被 `ADR-0007` 物理隔离废弃；
2. **截断层下线自毁防线**：旧版降级策略在数据发生超时陈旧（`DATA_STALENESS`）时，错误地执行“截断层自动下线、$\sigma$ 放大 1.3 倍”，导致已被物理淘汰的死档重新获得虚高的模型概率，诱发向死档下注穿仓的毁灭性风险；
3. **特报（SPECI）接入与纯温门禁缺失**：突发强对流、雷暴阵雨等恶劣天气往往伴随剧烈的气温骤升骤降，但旧系统未建立特报流的毫秒级解析与纯温本征门禁，缺乏跳温异常时的 Fail-Closed 快速阻断；
4. **风控时延量纲脱节**：旧版 45 分钟单一超时阈值过于粗放，相当于容忍连续丢失 8~9 报，在长达 45 分钟的盲盒期内极易遭受盘口知情交易者的逆向选择抢跑打击。

---

## 解决方案 (Solution)

严格依据已裁决的 `ADR-0011`（双源单调合流与两维阶梯风控）与 `ADR-0013`（特报高频截断与异常安全阻断），在 `src/prediction/` 与 `src/risk/` 搭建全新的**多源实况单调合流与特报截断引擎**：
1. **双源单调合流架构 (Dual-Active Monotonic Driver)**：
   - 以 IEM ASOS 实时原报流（包含 Routine METAR 与 SPECI 特报，0.1°C RMK T 组精度）作为全天候主力物理驱动源；
   - 以 NWS WRH 官方时序表作为异步影子对齐源；
   - 彻底废除 2h 跨源切换，全天候执行单调更新算子：$T_{max\_so\_far} = \max(T_{IEM}, T_{NWS})$，$T_{min\_so\_far} = \min(T_{IEM}, T_{NWS})$。
2. **三道纯温本征门禁 (Pure-Temperature Sanity Gates)**：
   - 门禁 1（绝对气候极值域）：$T_{dry} \in [-40.0^\circ\text{F}, 135.0^\circ\text{F}]$；
   - 门禁 2（正文与 RMK T 组交叉检验）：$|\Delta T_{body-rmk}| \le 1.8^\circ\text{F}$；
   - 门禁 3（单步跳变硬门禁）：5 分钟单步跳变 $|\Delta T_{5min}| \le 15.0^\circ\text{F}$（对齐 ADR-0010 物理上限）。
3. **迟到不投原则 (Missed Window Principle)**：
   - 报文到达时间延迟超过 15 分钟，或物理时间戳晚到/乱序，坚决丢弃，绝不触发重新定价与新开仓订单。
4. **单站安全熔断阻断 (Fail-Closed Circuit Breaker)**：
   - 发现物理跳温破门禁或不可确证异常时，立即向统一异常中枢（ADR-0014）上报 `PHYSICAL_TEAR` Incident，0ms 撤销该台站全部排队未成交挂单，当日锁定 `STATION_BLOCKED`（已成交持仓绝缘持有至结算）。
5. **两维阶梯风控防线与迟滞恢复 (Tiered Risk Watchdog & Hysteresis)**：
   - 第一道防线：到达心跳超时（> 15 分钟），立即下发 CancelAll 撤销排队未成交挂单，禁止开新仓；
   - 第二道防线：绝对物理龄期超限（> 35 分钟），触发 `DATA_STALENESS` 进入 `SAFE_MODE` 交易熔断；
   - 迟滞恢复：连续 3 帧（至少 15 分钟）持续健康发报且物理龄期 $< 20$ 分钟方可解除限制。
6. **截断约束永久锁定法则**：
   - 物理极值事实单向不可逆，数据断流失明期截断门禁永久锁定，绝不下线。

---

## 用户故事 (User Stories)

1. 作为量化交易员，我希望系统能够实时流式解析 IEM METAR 与 SPECI 特报的高精 RMK 气温，以便日内气温一旦突破档位边界能毫秒级截断死档。
2. 作为风控经理，我希望系统实施三道纯温本征门禁，严格剔除负数乱码、跳字或传感器短路，以便劣质数据绝不污染极值状态机。
3. 作为架构师，我希望最高温（TMAX）与最低温（TMIN）在数学与工程上完全平权对称，TMAX 单向锁死下界，TMIN 单向封顶上界，以便两种市场的截断逻辑具备一致性。
4. 作为交易算法工程师，我希望报文到达延迟超过 15 分钟的迟到帧直接丢弃，绝不反向触发模型定价与开仓，以便消除信息过时后的逆向选择风险。
5. 作为风控主管，我希望数据断流超过 15 分钟时系统毫秒级撤销订单簿上所有未成交的挂单（CancelAll），以便在盲盒期不被知情交易者打劫。
6. 作为交易系统操作员，我希望已成交的仓位在任何异常熔断时坚决不市价踩踏平仓，安全持有至结算，以便杜绝恐慌自残穿仓。
7. 作为量化开发人员，我希望截断层维护的日内极值在数据断流失明期永久锁定且绝不下线，以便死档区间概率始终保持为 0.0。
8. 作为系统工程师，我希望站点在经历心跳断流后必须满足“连续 3 帧（至少 15 分钟）稳定发报且物理龄期 < 20 分钟”方可解除挂单封锁，以便杜绝网络边缘抖动引发的高频频繁震荡。
9. 作为质检工程师，我希望系统提供完整的 Test-Scenario D 验收套件，覆盖迟到丢弃、正文与 RMK 交叉纠偏、异常跳温 20°F 阻断与 Fail-Closed 断言。

---

## 实现决策 (Implementation Decisions)

- **核心接口与分层设计**：
  - 数据接入层：`src/data_acquisition/observation_stream.py`，实现多源（IEM METAR/SPECI、NWS WRH）流式接入契约与 UTC 物理时间戳标准化；
  - 纯温校验层：`src/prediction/temperature_sanitizer.py`，封装纯温三道门禁（极值域、交叉检验、单步 15°F 跳变）与迟到丢弃逻辑；
  - 单调合流层：`src/prediction/monotonic_confluence.py`，维护每个台站在本地时区自然日（00:00:00 ~ 23:59:59）内的单调极值状态机（$T_{max\_so\_far}$, $T_{min\_so\_far}$）；
  - 风控监控层：`src/risk/stream_watchdog.py`，维护台站的到达心跳计时器、物理龄期计时器、两维阶梯风控状态机与 3 帧迟滞恢复看门狗；
  - 截断适配层：升级 `src/prediction/dynamic_corrector.py`，对接合流极值状态，保证截断门禁单向永久锁定。
- **配置持久化规范**：
  在 `config/default.yaml` 中新增对齐 ADR-0011 与 ADR-0013 的受控配置节 `stream_confluence` 与 `truncation_rules`。
- **严格遵循受控词表与 Active 10 交易宇宙**：
  仅针对 `KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS` 维护状态机，严格基于 `src/data_processing/constants.py` 的受控元数据。

---

## 测试决策 (Testing Decisions)

- **单元与组件测试**：
  - 门禁契约单测：测试正负温解码、RMK T 组高精解析、超出 $[-40, 135]^\circ\text{F}$ 拦截、正文与 RMK 差值 $>1.8^\circ\text{F}$ 拦截、单步跳变 $>15.0^\circ\text{F}$ 拦截；
  - 单调累积单测：注入乱序、较小值、较大值，断言 TMAX 只增不减，TMIN 只减不增；
  - 迟到丢弃单测：注入时间戳倒退报文，断言状态机不更新且不发交易事件；
  - 两维风控单测：Mock 时间流逝，测试 15m 触发 CancelAll、35m 触发 SAFE_MODE、连续 3 帧恢复健康。
- **集成与验收测试 (Test-Scenario D)**：
  - D1: 迟到 METAR 原报丢弃负断言；
  - D2: 正文整度与 RMK 0.1°C 偏差交叉纠偏正断言；
  - D3: 异常跳温 20°F 触发 Fail-Closed 安全阻断与单站锁定断言。
- **网络与冒烟硬性纪律**：
  保持每步真实网络冒烟绿灯：`RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`。

---

## 范围外声明 (Out of Scope)

- 控制面统一异常仲裁中枢跨模块全局编排与 Incident 广播分发（属于 Task 03 范畴）；
- 概率向 Polymarket 盘口区间积分映射 (ndtr) 与 EV 动态计算（属于 Task 04 范畴）；
- 四桶资金状态机与联合凯利仓位优化计算（属于 Task 05 范畴）；
- CLOB 交易签名、REST/WSS 订单路由与成交撮合状态机（属于 Task 06 范畴）。

---

## 任务垂直切片拆分 (Tickets Breakdown)

1. **`Phase 2 Task 02 - Ticket 01: feat(ingestion): 观测数据流接入适配器与 IEM/NWS 双源报文解析器`**
   - **内容**：实现 `ObservationStreamAdapter`，集成 IEM METAR/SPECI 报文与 NWS WRH 观测流解析，提取纯气温（支持正文整度与 RMK T 组高精解码），统一输出标准化 `ObservationPacket`（含 UTC 时间戳、台站 ID、正文温、RMK 温）；
   - **依赖**：无（Frontier）。

2. **`Phase 2 Task 02 - Ticket 02: feat(truncation): 三道纯温本征门禁与物理跳温安全阻断器`**
   - **内容**：实现 `TemperatureSanitizer`，校验门禁 1（绝对域）、门禁 2（正文-RMK 交叉检验）、门禁 3（单步 15°F 跳变），实现迟到报文丢弃与物理撕裂异常上报触发器；
   - **依赖**：Blocked by `Ticket 01`。

3. **`Phase 2 Task 02 - Ticket 03: feat(pipeline): 双源单调合流状态机与日历日极值跟踪器`**
   - **内容**：实现 `MonotonicConfluenceEngine`，管理 Active 10 站本地自然日内的极值推进（TMAX 只增不减，TMIN 只减不增），自然日午夜原子翻转，升级 `DynamicCorrector` 保证截断门禁单向永久锁定；
   - **依赖**：Blocked by `Ticket 02`。

4. **`Phase 2 Task 02 - Ticket 04: feat(risk): 15m到达心跳与35m物理龄期两维阶梯风控监控器`**
   - **内容**：实现 `StreamRiskWatchdog`，监控台站到达心跳（15m 触发 CancelAll 挂单撤销）与绝对物理龄期（35m 触发 SAFE_MODE 熔断），实现连续 3 帧健康发报迟滞恢复；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 03`。

5. **`Phase 2 Task 02 - Ticket 05: test(acceptance): 多源合流端到端集成与 Test-Scenario D 验收套件`**
   - **内容**：编写端到端管道集成测试，全量覆盖 Test-Scenario D1（迟到丢弃）、D2（正文/RMK 对齐纠偏）、D3（异常跳温 20°F 阻断与 Fail-Closed），确保网络冒烟全绿；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 02`, `Ticket 03`, `Ticket 04`。
