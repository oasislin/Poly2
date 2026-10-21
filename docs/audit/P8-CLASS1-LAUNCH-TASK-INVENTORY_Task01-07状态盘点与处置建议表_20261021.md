# P8-CLASS1-LAUNCH-TASK-INVENTORY · Phase 2 既有 Task 01~07 状态全量盘点与处置定稿表

> **工单（B 线）**：`P8-CLASS1-LAUNCH`（治理批次 8）  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-04` / `CHK-05` / `CHK-07`（定稿）  
> **编制角色**：开发组 Agent  
> **依据文件**：《Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md》§4 任务矩阵、用户裁决 U-6~U-10（CHK-06/07）  
> **定稿性质**：本表为 Phase 2 任务树法定清理与收口定稿单。经技术审核复核与用户逐条签署（U-6~U-10），Task 01~07 历史处置正式定稿，新第一类任务正式以 **`Phase 2 Task 08`** 立项。

---

## 一、 逐项两步判定纪律说明

依据《AGENTS.md》硬性铁律：
- **原始观测值**：以当前代码库、测试执行真实输出、数据文件实际落盘统计及历史决议台账原样记录；
- **判定阈值**：以《Phase 2 执行文件 v2.1》各任务交付验收标准与波次二（W2）收窄口径为准；
- **结论**：由机械比对得出，严禁主观加工；
- **处置状态**：严格区分 **收窄口径 Close（封盘）**、**Close（封盘）**、**停止/顺延**、**收口 Close（移交未完成部分）**、**废除（Superseded）**、**终止（Reset）**。

---

## 二、 Task 01~07 逐项状态盘点与处置定稿表

### Task 01 · 模型重训与验收

| 检查维度 | 盘点事实与证据（原始观测值） |
| :--- | :--- |
| **定义原文** | 在 `calib-dataset-v2.0` 上全量重训 Active 10 站 960 个生产模型矩阵，通过 P5/P6 审计体系验收。960 个生产模型落盘 `data/models/`；KORD/KMIA 双城 24 时间格完成审计封卷（气象门禁 ECE $\le 5.0\%$；ECE $\le 0.0100$ 与挂旗治理属交易侧内部口径）。 |
| **现役代码/资产（实测）** | 1. **落盘数量实测（P-2 修正）**：`data/models/` 顶层实测包含 **1200** 个 `.pkl` 模型文件（`manifest.json` 包含 1200 个模型哈希），`data/models/archive_legacy_20260920/` 包含 800 个历史模型，合计 2000 个；规格基准 960 个（10 站 × 2 标的 × 4 季 × 12 lead）全部包含在内，额外 240 个为 6h 池化回退层及密集时效插值模型；<br>2. 统一推理门面：`src/modeling/registry.py` 完整实现；<br>3. 盲测体检封盘：2019 独立盲测 V2.0 尺子升级终审四项全部通过（`70c15f3` + `2d91cf3` + `e421ac8`）；<br>4. 审计覆盖范围实测：依据 `SEALING_GATE` 与 `ROADMAP`，P5/P6 20 折 Block-CV 审计已 100% 覆盖双城 TMax 24 时间格（96 季节格）；其余 8 站 TMax 与全量 10 站 TMin（480 格）审计覆盖率为 0%。 |
| **测试证据（P-3 补齐）** | 执行命令：`python3 -m pytest tests/unit/modeling/test_registry.py -q`<br>原始输出末尾：`tests/unit/modeling/test_registry.py .......... [100%]`<br>`============================== 10 passed in 1.44s ==============================`<br>判定阈值：10 个用例全部 Pass；退出码 = 0；结论 = 通过。 |
| **两步判定** | - 原始观测值：顶层 1200 模型落盘（含 960 生产全矩阵）+ 双城 TMax 24 时间格 P5/P6 审计封盘 + V2R01 尺子终审闭环；其余 8 站 TMax 与 10 站 TMin 审计未跑；<br>- 判定阈值：按波次二（W2）双站只读纸面盘闭环收窄口径；<br>- 状态判定：**已完成双城 TMax 审计封盘，余量顺延未来横向训练**。 |
| **处置定稿（U-6 裁决）** | **收窄口径 Close（封盘冻结）**。<br>定稿口径（P-1 修正）：当前以两城（KORD/KMIA）继续完成第一类投注定价与纸面盘全流程闭环；**其余 8 站 TMax 与 10 站 TMin 的审计余量明确标注为「留作未来横向训练回归」**，不视为永久搁置，后续波次按需扩域回归。本阶段不再重训模型、不改参数。 |

---

### Task 02 · 多源合流与特报引擎

| 检查维度 | 盘点事实与证据（原始观测值） |
| :--- | :--- |
| **定义原文** | 搭建实况观测接入管道，实现 METAR 与 NWS 单调合流及 SPECI 纯温高频截断。交付单调更新器、SPECI 纯温门禁、迟到不投丢弃器；单测覆盖单调不回退与异常跳温阻断（ADR-0011, ADR-0013）。 |
| **现役代码/资产** | 1. 现役数据管道：`src/pipeline/stream_confluence_pipeline.py`；<br>2. 实况流接入：`src/data_acquisition/observation_stream.py`；<br>3. 动态截断层：`src/prediction/truncated_probability_engine.py`；<br>4. 看门狗依赖：`src/risk/stream_watchdog.py`（R-16 例外保留模块）。 |
| **测试证据（P-3 补齐）** | 执行命令：`python3 -m pytest tests/unit/prediction/test_monotonic_confluence.py tests/unit/prediction/test_scenario_d.py tests/unit/prediction/test_w2_confluence_exemptions.py -q`<br>原始输出末尾：`tests/unit/prediction/test_w2_confluence_exemptions.py ..... [100%]`<br>`============================== 11 passed in 1.09s ==============================`<br>判定阈值：11 个单调合流与特报门禁测试用例全部 Pass；退出码 = 0；结论 = 通过。 |
| **两步判定** | - 原始观测值：单调推进、特报纯温门禁、迟到丢弃及跳温阻断均在线役树完整实现且单测通过；<br>- 判定阈值：v2.1 §4 交付物（单调更新器、SPECI 门禁、单测覆盖）；<br>- 状态判定：**已完成封盘（Completed & Sealed）**。 |
| **处置定稿（U-7 裁决）** | **正式 Close（完成封盘关闭）**。<br>W2 白名单合流资产已封盘，为只读下游提供确定性物理输入，任务使命完全达成。 |

---

### Task 03 · 统一异常仲裁中枢

| 检查维度 | 盘点事实与证据（原始观测值） |
| :--- | :--- |
| **定义原文** | 落地控制面统一异常仲裁中枢、台站级挂起协议与本地单站拔网线机制。交付 `CentralExceptionArbiter` 状态机；Fail-Closed 0ms 撤单；30s 预算衰竭升级；本地拔网线 CLI（顺延至实盘前置）。 |
| **现役代码/资产** | 1. 主树现状：`src/risk/` 下除 `stream_watchdog.py` 外无任何仲裁模块；<br>2. 归档现状：`central_arbiter.py`、`incident_protocol.py`、`emergency_control.py`、`cli.py` 已于 2026-10-13 依据裁决 R-16 方案 B 整体归档至 `docs/archive/trading_modules/src/risk/`；<br>3. 文档状态：v2.1 §4 标注为 `DEFERRED_TO_PRE_LIVE`（顺延至实盘前置）。 |
| **测试证据** | 归档测试处于物理隔离状态，现役树测试套件零污染。 |
| **两步判定** | - 原始观测值：主树无现役交易仲裁代码，旧实现物理归档封存；<br>- 判定阈值：v2.1 §4 规划为实盘前置任务；<br>- 状态判定：**已归档顺延中（Archived & Deferred）**。 |
| **处置定稿（U-7 裁决）** | **保持 停止/顺延（DEFERRED_TO_PRE_LIVE）**。<br>当前第一类阶段为只读纸面盘模拟，不涉及真实真金实弹交易与 CLOB 真实挂单撤单，中枢级 Fail-Closed 物理撤单无需在第一类激活，维持既有顺延。 |

---

### Task 04 · 概率映射与 EV 引擎

| 检查维度 | 盘点事实与证据（原始观测值） |
| :--- | :--- |
| **定义原文** | 连续物理分布向离散区间积分映射，动态注入 Polymarket 费率模型。交付 `BinConverter` (多族积分), `DynamicCorrector`, `ConstraintEnforcer`, `EVCalculator` 动态策略。 |
| **现役代码/资产** | 1. 现役离散映射：`src/prediction/discrete_bin_engine.py`（实现 2°F 精确吸附、半度修正，完全闭环）；<br>2. 现役约束与校准：`src/prediction/bin_converter.py`、`constraint_enforcer.py`、`dynamic_corrector.py`；<br>3. 归档 EV 引擎：`ev_engine.py` 随 R-16 被归档至 `docs/archive/trading_modules/src/pricing/`。 |
| **测试证据（P-3 补齐）** | 执行命令：`python3 -m pytest tests/unit/prediction/test_discrete_bin_engine.py tests/unit/prediction/test_discrete_bin_engine_2deg.py -q`<br>原始输出末尾：`tests/unit/prediction/test_discrete_bin_engine_2deg.py ...... [100%]`<br>`============================== 11 passed in 0.89s ==============================`<br>判定阈值：11 个 2°F 离散吸附测试用例全部 Pass；退出码 = 0；结论 = 通过。 |
| **两步判定** | - 原始观测值：物理概率离散映射（2°F 档位积分）在主树已完全闭环交付（11 个单测全绿）；交易侧动态 EV 计算在 R-16 归档区未交付；<br>- 判定阈值：物理与交易责任严格解耦；<br>- 状态判定：**物理映射部分闭环，交易 EV 部分移交新任务**。 |
| **处置定稿（U-9 裁决）** | **收口 Close：物理概率映射部分封盘；交易 EV 部分未完成、移交 Task 08 承接（P-5 修正）**。<br>理由：物理映射与交易定价彻底解耦。Task 04 物理离散映射宣告封盘；未完成的交易侧 EV 引擎按 DR-2026-1014-01 探针规则与 M-2 动态费率契约移交 Task 08 重建，不单独起 conversation，非永久搁置。 |

---

### Task 05 · 资金状态机与联合凯利

| 检查维度 | 盘点事实与证据（原始观测值） |
| :--- | :--- |
| **定义原文** | 实现四桶资金管理、僵尸仓位双轨估值与多项联合对数财富增量优化器。交付 `BankrollStateMachine` (Decimal 舍入闭环), `MultinomialKellyOptimizer` (SLSQP 鲁棒求解)（顺延至实盘前置）。 |
| **现役代码/资产** | 1. 主树现状：`src/bankroll/` 目录在主树不存在（R-16 归档）；<br>2. 归档现状：`bankroll_manager.py`、`multinomial_kelly.py`、`risk_limiter.py`、`zombie_evaluator.py` 归档封存；<br>3. 违宪与缺陷：归档多项凯利为点估计，判决书 M-1 已裁决重构为 EMOS 闭式 CDF 稳健结构；DR-2026-1014-02 已裁决后置乘法折剪废除、改为预算上限 $C_{\max}$ 前置折剪；DR-2026-1014-03 已裁决统一 $B_{\text{eff}}$ 分母。 |
| **测试证据** | 归档测试处于物理隔离状态。 |
| **两步判定** | - 原始观测值：主树零代码；归档代码存在数学违宪与结构缺陷（点估计、后置折剪、分母不一致）；<br>- 判定阈值：必须符合 P7-ALGO-VERDICT M-1 与 P7-ALGO-2 DR 规范；<br>- 状态判定：**已归档废除（Archived & Superseded）**。 |
| **处置定稿（U-7 裁决）** | **正式 废除（Deprecated / Superseded）**。<br>旧版实现与算法架构已被判决书与裁决记录彻底否定废弃，不做原样回迁，结案废除。由 Task 08 按稳健凯利新结构重建。 |

---

### Task 06 · 执行引擎与残局状态机

| 检查维度 | 盘点事实与证据（原始观测值） |
| :--- | :--- |
| **定义原文** | 深度穿透防御 IOC 保护价限价单路由与非原子成交残局对冲/止损。交付 `OrderRouter` (IOC 保护价), `ResidualRiskStateMachine` (补单/对冲/硬止损)（顺延至实盘前置）。 |
| **现役代码/资产** | 1. 主树现状：`src/execution/` 目录在主树不存在（R-16 归档）；<br>2. 归档现状：`clob_client.py`、`execution_engine.py`、`models.py`、`order_router.py`、`residual_risk.py` 归档封存；<br>3. 违宪与缺陷：归档残差状态机包含“反向对冲”与“市价止损卖出”，直接违反系统现行最高宪法“只买不卖（Buy-Only）”原则；原探针规模计算违背 DR-2026-1014-01 达标深度原则。 |
| **测试证据** | 归档测试处于物理隔离状态。 |
| **两步判定** | - 原始观测值：主树零代码；归档代码严重违背只买不卖宪法与最新探针裁决；<br>- 判定阈值：只买不卖宪法与 DR-2026-1014-01 规范；<br>- 状态判定：**已归档违宪失效（Archived & Constitutionally Invalid）**。 |
| **处置定稿（U-7 裁决）** | **正式 废除（Deprecated / Superseded）**。<br>包含卖出与对冲逻辑的旧残差状态机在只买不卖体制下已无合法地位，结案废除。由 Task 08 按精简补单自愈结构重建。 |

---

### Task 07 · 风控联动与纸面盘验证

| 检查维度 | 盘点事实与证据（原始观测值） |
| :--- | :--- |
| **定义原文** | 集成两维阶梯风控，全套注入测试 A~E，启动 Active 10 站只读纸面盘模拟（Paper Trading）。注入测试套件 CI 全绿；只读纸面盘运行 48h 零非物理撮合，净 EV 信号稳健。 |
| **现役代码/资产** | 1. 主树现状：无纸面盘与两维风控现役代码；<br>2. 归档现状：`two_dimensional_risk.py` 与 `simulation/` 下 7 个模块归档封存；<br>3. 架构缺陷：归档风控硬编码华氏度，违背 DR-2026-1014-04 标准化残差 $z$ 化要求；原验收标准预设“接入真实 WSS 盘口”（脱离当前未配生产密钥与长连接的工程现实）。 |
| **测试证据** | 归档测试处于物理隔离状态。 |
| **两步判定** | - 原始观测值：主树零代码；旧实现存在温标硬编码缺陷；原验收门禁凭空预设未接入的外部生产基础设施；<br>- 判定阈值：实事求是原则与 DR-2026-1014-04；<br>- 状态判定：**未完成且旧版废弃（Incomplete & Superseded）**。 |
| **处置定稿（U-7 裁决）** | **正式 终止（Terminated / Reset）**。<br>旧版实现与原不切实际的 WSS 验收门禁彻底重置，交由 Task 08 在只读仿真撮合环境下基于全量新算法闭环重构。 |

---

## 三、 任务树治理定稿矩阵与新任务立项

依据用户裁决 U-6~U-10 与 CHK-07 定稿，Phase 2 全量任务状态矩阵定稿如下：

| 任务编号 | 任务名称 | 最终处置状态 | 归宿与说明 |
| :--- | :--- | :--- | :--- |
| **Task 01** | 模型重训与验收 | **收窄口径 Close（封盘）** | 960 生产模型落盘（实测顶层 1200）+ 双城 TMax 24 时间格 P5/P6 审计封盘 + V2R01 尺子终审闭环；其余 8 站 TMax 与 10 站 TMin 余量标注留作未来横向训练回归。 |
| **Task 02** | 多源合流与特报引擎 | **Close（封盘）** | 主树在役（4 模块）+ 单测全绿（11 passed）。 |
| **Task 03** | 统一异常仲裁中枢 | **保持 停止/顺延** | 保持 `DEFERRED_TO_PRE_LIVE`，实盘前置阶段再行激活。 |
| **Task 04** | 概率映射与 EV 引擎 | **收口 Close + EV 移交** | 物理离散概率映射封盘；交易 EV 部分未完成，移交 Task 08 重建。 |
| **Task 05** | 资金状态机与联合凯利 | **废除（Superseded）** | M-1 / DR-02 / DR-03 彻底否定旧点估计与后置折剪实现，Task 08 重建。 |
| **Task 06** | 执行引擎与残局状态机 | **废除（Superseded）** | 只买不卖最高宪法与 DR-01 否定旧对冲与旧探针，Task 08 重建。 |
| **Task 07** | 风控联动与纸面盘验证 | **终止（Reset）** | DR-04 $z$ 化与 WSS 虚幻门禁重置，Task 08 仿真闭环重构。 |
| **Task 08** | **第一类投注定价算法与只读纸面盘落地** | **立项（新交付主任务）** | 采纳用户 U-10 裁决路径 2：承接 Q1 连续可信度折减、Q7 覆盖率双轨、ADR-0019 参数消费契约、EV 探针定价、稳健凯利与 48h 纸面盘落地，垂直切分为 24 张 Tickets。 |
