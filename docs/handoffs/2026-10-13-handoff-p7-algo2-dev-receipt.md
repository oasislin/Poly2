# P7-ALGO-2《联合凯利与执行定价算法规格书》开发端（执行端）接收单

> **接收日期**：2026-10-13  
> **接收方**：开发端（执行端）Agent（本会话）  
> **交接依据**：`docs/handoffs/2026-10-13-handoff-p7-algo2-design.md`  
> **协作模式**：与主导方 Agent（量化投资专家 + 算法专家）通过共享文件（`docs/audit/`）异步 Debate 协作  
> **上游依据**：《REMEDIATION_PLAN.md》v1.2（R-17）+ 判决书 `docs/audit/P7-ALGO-VERDICT.md` + 用户 2026-10-13 流程指令

---

## 一、理解确认与角色定位

1. **核心使命**：
   本 Agent 作为**开发端（执行端）Agent**，以“落档细化与工程可行性把关”角色参与工单 `P7-ALGO-2《联合凯利与执行定价算法规格书》` 及其配套算法描述文档的编制工作。
2. **职责边界**：
   - **主导方 Agent**：主导算法框架（算法目的提取、数学建模、Kelly 公式形态、sizing 方案、执行定价、门禁设计）。
   - **开发端 Agent（本角色）**：
     - 全面通读历史素材与归档代码，完成客观盘点与逻辑抽象；
     - 深度审查主导方的算法框架初稿，从代码级可行性、数据结构定义、参数类型与约束、接口签名、状态机流转等工程实现视角提出质询与补充；
     - 与主导方开展多轮 debate，推进达成一致；
     - 负责算法规格书与数学公式完备的算法描述文档落盘细化，呈交用户最终裁决与确认。
3. **关键红线承诺**：
   - **判词签署权属于用户**：判决遗留项、裁决项均不擅自判定，分歧如实列为待裁决项呈报用户；
   - **F-2 优先律严格遵守**：概率层 ECE/CRPSS 门禁未绿灯前，凯利标定与 sizing 调优挂锁不标定，仅完成数学结构推导与算法规范落盘；
   - **四层命名宪法**：严格遵守 Phase 1 → 1.5 → 2 → 3，P4~P7 仅作工单编号，W1~W3 仅作波次，Task 01~07 为切片，绝不出现“Phase 4~7”；
   - **严禁凭空捏造前置条件与实证声明附工件**：基于当前代码库、真实资产（CLOB 现实、归档代码、方案 v2.8、ADR）；
   - **原始观测不可篡改**：代码盘点与历史审读坚持客观真实，原样汇报。

---

## 二、素材通读与代码盘点工作计划

按交接单 § 四 要求，严格分批进行全量通读与系统梳理：

### 2.1 必读文档清单（15 份）
1. **判决书与溯源**：
   - `docs/audit/P7-ALGO-VERDICT.md`（判决书 v0.2，M-1~M-8、F-2、C 类三案）
   - `docs/audit/P7-ALGO-1_kelly_provenance.md`（凯利公式溯源）
2. **方案与基线策略**：
   - `docs/项目方案和执行文档/项目方案 (v2.8)：Polymarket 温度市场量化投注系统.md`（算法目的法定来源）
   - `docs/项目方案和执行文档/天气套利参数标定与联合优化方案.md`
   - `docs/archive/项目方案和执行文档/Polymarket 天气套利投注与对冲算法策略（old）.md`
   - `legacy/v1-strategy/Polymarket天气套利参数标定与算法说明文档.md`
   - `legacy/v1-strategy/README_V1_ORIGINAL.md`
   - `legacy/v1-strategy/baseline_sigma_optimization_proposal.md`
   - `docs/archive/trading_modules/README.md`（交易模块归档说明与恢复指引）
3. **关联 ADR 边界约束**：
   - `docs/adr/ADR-0011-dual-source-fusion-and-two-dim-risk-gate.md`（合流、截断、两维风控、φ=1.3）
   - `docs/adr/ADR-0012-nws-wrh-settlement-and-zombie-valuation.md`（结算真值源、僵尸仓位）
   - `docs/adr/ADR-0013-speci-high-freq-cutoff-and-breaker.md`（特报高频截断、M-6 条件）
   - `docs/adr/ADR-0014-central-arbiter-and-station-safe-suspend.md`（异常仲裁中枢与安全挂起）
   - `docs/adr/ADR-0015-abolish-gaussian-emos-additive-variance.md`（物理方差底座、离散校准门禁）
   - `docs/adr/ADR-0018-sample-cliff-verdict-and-gate-hierarchy.md`（小样本分档断崖与门禁分层）

### 2.2 归档代码深度盘点（`docs/archive/trading_modules/`）
覆盖 5 大模块、27 个源文件、5 个脚本及 20 个测试文件：
- **bankroll**：多项凯利优化器（`multinomial_kelly.py`）、资金池管理（`bankroll_manager.py`）、风险限制（`risk_limiter.py`）、僵尸仓位评估（`zombie_evaluator.py`）；
- **pricing**：EV 计算引擎（`ev_engine.py`）；
- **execution**：订单路由与执行（`execution_engine.py`, `order_router.py`, `clob_client.py`, `residual_risk.py`, `models.py`）；
- **risk**：两维风控门禁（`two_dimensional_risk.py`）、预购拦截（`pre_buy_gate.py`）、中枢仲裁（`central_arbiter.py`）、应急控制（`emergency_control.py`）；
- **simulation & scripts & tests**：撮合模拟、纸面交易、反事实回测等。
- **盘点产出目标**：系统整理数据流、输入输出、核心数学公式；无完整逻辑的模块，列出模块清单、职责及接口签名，落盘至 `docs/audit/P7-ALGO-2_代码盘点.md`。

---

## 三、跨 Agent 异步协同协议（Debate 流程约定）

1. **共享工作区**：
   - 协作文件统一存放于 `docs/audit/`。
   - 开发端质询与反馈文件命名规范：`docs/audit/P7-ALGO-2_debate_dev_response_YYYYMMDD.md` 或专项议题文档。
   - 文件头部严格注明：“`<!-- 供主导方 debate 读取 | 日期: 2026-10-13 | 角色: 开发端 Agent -->`”。
2. **Debate 交互步调**：
   - **Step 1（当前）**：开发端完成素材通读与代码盘点，落盘 `docs/audit/P7-ALGO-2_代码盘点.md`，提供工程底座全景；
   - **Step 2**：读取主导方提交的《算法框架初稿》，针对：
     ① 算法目标对齐度（方案 v2.8）；
     ② 数学公式闭环性与物理约束；
     ③ 接口入参/出参及类型系统定义；
     ④ 异常分支与边界状态处理；
     ⑤ F-2 优先律与标定门禁挂锁点；
     进行逐条 Cross-check，出具《开发端质询与细化意见》；
   - **Step 3**：双方多轮异步对齐。达成共识点直接冻结；分歧点提取出《待裁决项表》呈交用户裁决；
   - **Step 4**：基于共识与用户裁决，开发端编制高精度《P7-ALGO-2 联合凯利与执行定价算法规格书》及算法描述文档。

---

## 四、执行状态

- [x] 接收单编制完成并落盘
- [ ] 正在执行：第二步 素材通读与代码盘点（文档 + 归档代码）
- [ ] 待执行：产出 `docs/audit/P7-ALGO-2_代码盘点.md` 与素材盘点摘要
- [ ] 待执行：第三步 等待并读取主导方框架初稿，开启异步 Debate

确认完毕，立即进入第二步：全面通读与代码盘点。
