# Phase 2 开工前准备：交接文档（Step 3 特报语义与高频截断执行层裁决）

> **文档版本**：v1.0  
> **生成时间**：2026-09-20  
> **前置任务状态**：
> - Phase 1.5 全部结项：Commit `73d24cd`，Tag `phase1.5-final` ✅
> - `calib-dataset-v2.0` 生产级数据集发布（528 文件全门禁通过）✅
> - **Step 1 已闭环**：`ADR-0011` 正式落定（双源单调合流架构、TMAX-TMIN 对称截断、15m 丢心跳撤挂单/35m 物理龄期两维阶梯风控，彻底废除跨源切换）✅
> - **Step 2 已闭环**：`ADR-0012` 正式落定（法定结算真值源确立为 NWS WRH、彻底下线 Wunderground、四桶资金双轨制会计模型、Decimal 算术四舍五入闭环 PENDING-01）✅
> - **交易站点宇宙固化**：Active 10 活跃高频交易站（`KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS`；`KBKF` 忽略不纳入交易，`KDCA` 彻底下线隔离）✅
> **下游目标**：推进《项目方案 (v2.6)》§8.1 / §8.2 三项开工前 ADR 裁决之 **Step 3：特报语义与高频截断执行层裁决（拟开立 ADR-0013）**

---

## 1. 任务背景与核心使命

根据《项目方案 (v2.6)》§8.1 / §8.2 与《Phase 2 执行文件 v1.3》§5.2 / §9，Phase 2 开工前必须完成三项阻塞级 ADR 对齐。
当前 Step 1（`ADR-0011`）与 Step 2（`ADR-0012`）均已正式闭环。**当前第三步：特报语义与高频截断执行层裁决**：

1. **历史背景与现状**：
   - 在 Phase 1.5 Task 03 清障期间，基于芝加哥 2026-08-31 强雷暴实证，已出具 `ADR-0009`，确立了特报（SPECI）具有完全合法的结算效力，并在数据管道中保留全量报文（`report_type=["1", "2"]`）；
   - 但在《Phase 2 执行文件 v1.3》的高频实盘执行层面，**尚未将特报语义深度整合进交易与风控引擎**。
2. **核心待裁决任务（ADR-0013 范围）**：
   - **截断层注入时效**：实盘物理原报流接收到突发 SPECI 时，`DynamicCorrector` 是立即毫秒级触发单调硬截断（Lower/Upper Bound Clamping），还是需要防抖缓冲以防瞬时传感器毛刺？
   - **对流天气方差膨胀（$\sigma_{\text{speci}}$）**：雷暴锋面过境伴随急剧气温骤升骤降（如短时升温 3~4°F），联合多项凯利优化器在临界区间边缘如何防止过度拟合重仓？是否需要根据特报标记（如 `TSRA`、`SQ`、急剧气压涌浪）动态引入不确定性膨胀因子？
   - **近邻时间戳保序**：当 ASOS 突发 SPECI 与常规整点 METAR 极其接近（例如 13:50 SPECI 与 13:51 METAR）时，时序状态机的防乱序与防回退守卫契约；
   - **形成正式决策文档**：顺延领号开立 **`ADR-0013`**，完成 Phase 2 开工前阻塞清单的最后一项拼图。

---

## 2. 需重点读取的上下文与证据文件

1. **项目方案与执行规范**：
   - `docs/项目方案和执行文档/项目方案 (v2.6)：Polymarket 温度市场量化投注系统.md`（重点关注 §5、§8.1、§8.2、§9）
   - `docs/项目方案和执行文档/Phase 2 执行文件 v1.3：盘口定价、套利与执行引擎.md`（重点排查截断层与执行引擎）
2. **前序 ADR 决议**：
   - `docs/adr/ADR-0009：芝加哥 08-31 特报（SPECI）结算语义裁决与截断层规则.md`（特报法定地位基石）
   - `docs/adr/ADR-0011：双源单调合流架构、TMAX-TMIN对称截断与两维阶梯风控裁决.md`（合流截断与两维风控）
   - `docs/adr/ADR-0012：法定结算真值源（NWS WRH）、僵尸仓位双轨估值与舍入闭环裁决.md`（结算真值与双轨会计）
3. **状态与元数据**：
   - `STATUS.md`
   - `src/data_processing/constants.py`（Active 10 站六要素受控元数据）

---

## 3. 新 Session 快速启动指令

在新开启的对话窗口中，直接复制以下指令发送给 Agent：

```text
我们已经圆满完成 Phase 2 开工前 ADR 裁决之 Step 1（ADR-0011 双源单调合流与两维风控）与 Step 2（ADR-0012 法定结算源 NWS WRH、僵尸仓位双轨估值与舍入闭环）。
请读取 docs/reports/phase2-handover-step3.md，正式开始推进 Phase 2 开工前准备三项 ADR 裁决之最后一步——Step 3：特报语义与高频截断执行层裁决（拟开立 ADR-0013）。

请严格遵从项目核心纪律：
1. 先输出详细的分析方案与 ADR 提案草案供我审阅讨论，在我明确确认前严禁编写或修改任何代码；
2. 严格基于 Active 10 活跃高频交易站点宇宙（KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS；KBKF 忽略不纳入交易，KDCA 彻底退役下线）；
3. 严格遵循六要素受控词表，严禁自由发挥非受控词汇；
4. 若涉及任何测试，必须维持每步真实网络冒烟绿灯：RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q。
```
