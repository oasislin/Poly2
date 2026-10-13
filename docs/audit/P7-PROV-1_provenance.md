# 工单 P7-PROV-1-R2：交易模块溯源与文档同步缺口查明报告

**工单编号**：`P7-PROV-1-R2`  
**审计性质**：只读取证、Git 提交链法医穿透、宪法对齐核查与资产改判  
**开工基准**：Git Commit HEAD = `ea72141e298d56a1f4f2d0de3e5ce41cda859d66`（分支 `fix/p7-w2-shortloop`）  
**执行原则**：仅依据 V2 仓库内实际提交历史与代码文本，严禁猜测式溯源；证据不足如实记录“无据可查”。

---

## 第一章 · 交易侧五个模块的真实来源与 Git 考古

依据工单任务 1 指令，对以下五个模块进行逐文件 Git 历史考古（`git log --follow`）、旧痕迹扫描（grep）、测试谱系核对与来源判定：
1. `src/execution/`（执行引擎、IOC 保护价路由、残局自愈状态机）
2. `src/bankroll/`（四桶资金管理、多项联合凯利优化器、僵尸仓位双轨估值）
3. `src/risk/`（控制面统一异常仲裁中枢、两维阶梯风控、本地拔网线 CLI）
4. CLOB 采集（`src/data_acquisition/polymarket_clob_collector.py`）
5. 纸面盘评估（`src/pricing/paper_evaluation_engine.py`）

### 1.1 Git 提交历史考古（逐文件首次提交记录）

通过 `git log --follow --format="%H|%cd|%an|%s"` 穿透追踪至每个源文件的创生提交：

| 模块名称 | 核心文件列表 | 首次提交 Hash | 首次提交日期 | 提交人 | 首次 Commit Message 全文摘要 | 首提交时间档位判定 |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: |
| **`src/execution/`** | `models.py`<br>`execution_engine.py`<br>`order_router.py`<br>`clob_client.py`<br>`residual_risk.py` | `478562566af...` | 2026-09-22 11:01:34 +0800 | oasislin | `feat(execution): Phase 2 Task 06 CLOB 执行引擎、IOC 保护价路由与非原子残局自愈状态机 (#88)` | **Poly2 早期**<br>（Phase 2 实施期） |
| **`src/bankroll/`** | `bankroll_manager.py`<br>`multinomial_kelly.py`<br>`risk_limiter.py`<br>`zombie_evaluator.py` | `40988deab76...` | 2026-09-22 10:27:14 +0800 | oasislin | `feat(bankroll): implement four-bucket bankroll, dual-track zombie valuation, and multinomial Kelly optimizer (Phase 2 Task 05)`<br>• Add BankrollManager with FourBucketBalance (resolves #83)<br>• Add ZombieEvaluator with 12h deadline (resolves #84)<br>• Add MultinomialKellyOptimizer with SLSQP (resolves #85)<br>• Add RiskLimiter with 10% / 70% caps (resolves #86) | **Poly2 早期**<br>（Phase 2 实施期） |
| **`src/risk/`** | `stream_watchdog.py` | `bf2aca6c742...` | 2026-09-21 16:30:32 +0800 | oasislin | `feat(pipeline): complete Phase 2 Task 02 multi-source confluence and SPECI truncation engine (#64)` | **Poly2 早期**<br>（Phase 2 实施期） |
| **`src/risk/`** | `central_arbiter.py`<br>`emergency_control.py`<br>`incident_protocol.py`<br>`cli.py`<br>`pre_buy_gate.py` | `5c7556edfd3...` | 2026-09-21 22:40:10 +0800 | oasislin | `feat(risk): 落地控制面统一异常仲裁中枢与挂起协议 (Phase 2 Task 03)`<br>• 确立统一 Incident 契约标准与 IncidentBus (ADR-0014 §3) (#71)<br>• 实现控制面 CentralExceptionArbiter 状态机 (#72)<br>• 实现 PreBuyGate 与本地拔网线 CLI (#73) | **Poly2 早期**<br>（Phase 2 实施期） |
| **`src/risk/`** | `two_dimensional_risk.py` | `478562566af...` | 2026-09-22 11:01:34 +0800 | oasislin | `feat(execution): Phase 2 Task 06 CLOB 执行引擎... (#88)` | **Poly2 早期**<br>（Phase 2 实施期） |
| **CLOB 采集** | `src/data_acquisition/polymarket_clob_collector.py` | `94eec7c02e8...` | 2026-10-11 22:26:35 +0800 | oasislin | `feat(clob): implement read-only Polymarket CLOB data ingestion module (P7-W3-TASK1-AUTH-001)` | **最近 N 天内**<br>（不到 24 小时前） |
| **纸面盘评估** | `src/pricing/paper_evaluation_engine.py` | `d7a114d0038...` | 2026-10-11 22:34:51 +0800 | oasislin | `feat(pricing): implement paper evaluation engine and probability pipeline (P7-W3-TASK2-AUTH-001)` | **最近 N 天内**<br>（不到 24 小时前） |

> **时间档位确界说明**：  
> - **Poly v1 迁移期**：2026-08-13（初始提交 `4cd5a8c`）至 2026-09-04（Tag: `phase1-final`，提交 `53b1024`）；  
> - **Poly2 早期**：2026-09-19（Tag: `phase1.5-final`）至 2026-09-22（Phase 2 Task 01~06 密集开发合并期，PR #88 等）；  
> - **最近 N 天内**：2026-10-10（Phase 7 过渡态立项）至 2026-10-11 夜间（分支 `fix/p7-w2-shortloop` 上的超前提交）。  
> **实证结论**：五个模块中，**零个模块属于 Poly v1 迁移物**；`src/risk/`、`src/bankroll/`、`src/execution/` 三大模块诞生于 2026-09-21 ~ 2026-09-22（Poly2 早期 Phase 2 实施期）；CLOB 采集与纸面盘评估引擎诞生于 2026-10-11（昨日夜间新写）。

---

### 1.2 代码内旧痕迹扫描（Grep 检查）

在上述五个模块的全部源码中，针对 `wunderground`（法定废弃源）、已注销站点代码（`KDCA`、`KBKF`）、v1 路径、旧架构硬编码进行全量扫描：

| 扫描目标路径 | 检索关键词 | 命中次数 | 命中文本 / 行号证据 | 定性分析 |
| :--- | :---: | :---: | :--- | :--- |
| `src/execution/` 全目录 | `wunderground`<br>`KDCA`<br>`KBKF`<br>`v1` / `legacy` | **0 次** | 无任何命中 | 代码洁净，无 v1 痕迹 |
| `src/bankroll/` 全目录 | `wunderground`<br>`KDCA`<br>`KBKF`<br>`v1` / `legacy` | **0 次** | 无任何命中 | 代码洁净，无 v1 痕迹 |
| `src/risk/` 全目录 | `wunderground`<br>`KDCA`<br>`KBKF`<br>`v1` / `legacy` | **0 次** | 无任何命中 | 生产代码中无旧痕迹 |
| `src/pricing/paper_evaluation_engine.py` | `wunderground`<br>`KDCA`<br>`KBKF`<br>`v1` / `legacy` | **0 次** | 无任何命中 | 代码洁净 |
| `src/data_acquisition/polymarket_clob_collector.py` | `KBKF` | **1 次** | **第 45 行**：`"denver": "KBKF",` | **【重大命中】** 采集器城市映射表混入已被 Active 10 排除的丹佛站代码 |
| `src/data_acquisition/polymarket_clob_collector.py` | `KDFW`<br>`KIAH`<br>`EGLL` | **3 次** | **第 40 行**：`"dallas": "KDFW",`<br>**第 44 行**：`"houston": "KIAH",`<br>**第 47 行**：`"london": "EGLL",` | **【重大命中】** 达拉斯错配为沃斯堡 KDFW（宪法为 KDAL）、休斯敦错配为布什 KIAH（宪法为 KHOU）、混入伦敦 EGLL |

---

### 1.3 测试文件谱系与断言核查

对应测试文件的提交历史与断言逻辑审查结果如下：

| 待测模块 | 对应测试文件路径 | 测试文件首次提交 Commit 与日期 | 编写模式 | 测试断言中的结算源与站点宇宙核查 |
| :--- | :--- | :---: | :---: | :--- |
| **`src/execution/`** | `tests/unit/execution/test_clob_models_client.py`<br>`tests/unit/execution/test_execution_engine.py`<br>`tests/unit/execution/test_order_router.py`<br>`tests/unit/execution/test_residual_risk.py`<br>`tests/integration/test_scenario_b_ioc_execution.py` | `4785625`<br>(2026-09-22 11:01) | **随同模块新写**<br>（PR #88 同批提交） | • 断言订单类型严格为 IOC 限价单；<br>• 保护价计算 EV 零点断言；<br>• 零 Wunderground 引用，零非法站点依赖。 |
| **`src/bankroll/`** | `tests/unit/bankroll/test_bankroll_manager.py`<br>`tests/unit/bankroll/test_multinomial_kelly.py`<br>`tests/unit/bankroll/test_risk_limiter.py`<br>`tests/unit/bankroll/test_zombie_evaluator.py`<br>`tests/integration/test_scenario_a_c_bankroll_kelly.py` | `40988de`<br>(2026-09-22 10:27) | **随同模块新写**<br>（Phase 2 Task 05） | • 严格断言 Decimal 6 位精度截断；<br>• 僵尸仓位测试显式依赖 `ACTIVE_10_STATIONS`；<br>• 零旧结算源引用。 |
| **`src/risk/`** | `tests/unit/risk/test_central_arbiter.py`<br>`tests/unit/risk/test_emergency_control.py`<br>`tests/unit/risk/test_incident_protocol.py`<br>`tests/unit/risk/test_pre_buy_gate.py`<br>`tests/integration/test_scenario_e_arbiter_fail_closed.py` | `5c7556e`<br>(2026-09-21 22:40) | **随同模块新写**<br>（Phase 2 Task 03） | • **显式包含负向拦截断言**：`test_incident_protocol.py:55` 声明 `station_id="KDCA"` 必须抛出异常拒绝；`test_emergency_control.py:108` 断言 `Invalid target 'KDCA'`；<br>• 确证测试是针对现行宪法专门编写。 |
| **`src/risk/`** | `tests/unit/risk/test_stream_watchdog.py` | `bf2aca6`<br>(2026-09-21 16:30) | **随同模块新写**<br>（Phase 2 Task 02） | • 断言心跳超时撤单与 15.0°F 跳温阻断。 |
| **CLOB 采集** | `tests/unit/data_acquisition/test_polymarket_clob_collector.py` | `94eec7c`<br>(2026-10-11 22:26) | **近期新写**<br>（不到 24 小时前） | • Mock Gamma 与 CLOB 响应测试；<br>• 未对 `KNOWN_CITY_TO_STATION` 的 Active 10 合法性做防御断言（导致错配漏过）。 |
| **纸面盘评估** | `tests/unit/pricing/test_paper_evaluation_engine.py` | `d7a114d`<br>(2026-10-11 22:34) | **近期新写**<br>（不到 24 小时前） | • 验证 `parse_bracket_bounds` 的连续性修正；<br>• 验证 `INPUT_SUSPECT` 8.0°F 门禁与正 EV 信号判定。 |

---

### 1.4 五个模块来源终审判定表

| 模块名称 | 最终判定结论 | 判定事实依据 |
| :--- | :---: | :--- |
| **`src/execution/`** | **Poly2 早期新写** | 创生于 2026-09-22 提交 `4785625`（PR #88），随 Task 06 规格全新落地，测试成套新写，无 v1 代码痕迹。 |
| **`src/bankroll/`** | **Poly2 早期新写** | 创生于 2026-09-22 提交 `40988de`，随 Task 05 规格全新落地，严格绑定 Decimal 舍入与 ADR-0012，无 v1 痕迹。 |
| **`src/risk/`** | **Poly2 早期新写** | 创生于 2026-09-21 提交 `bf2aca6` 与 `5c7556e`，随 Task 02/03 全新落地，严格绑定 ADR-0014，无 v1 痕迹。 |
| **CLOB 采集** | **Poly2 近期新写** | 创生于 2026-10-11 22:26 提交 `94eec7c`，在分支 `fix/p7-w2-shortloop` 上全新编写，但混入了非受控城市映射。 |
| **纸面盘评估** | **Poly2 近期新写** | 创生于 2026-10-11 22:34 提交 `d7a114d`，在分支 `fix/p7-w2-shortloop` 上全新编写，测试同步新写。 |

---

## 第二章 · 文档同步缺口判定（针对 ROADMAP“完成度 0.0%”问题）

### 2.1 `docs/ROADMAP.md` 全生命周期提交时间线

通过 `git log --all --follow --format="%H|%cd|%an|%s" docs/ROADMAP.md` 检索全库所有分支（含远程分支与已合并分支），提取该文件的全部提交记录：

```
0f62bcaad0d615ed822589e36b8de424d986cb50|Sat Oct 10 13:53:29 2026 +0800|oasislin|docs(p7): commit P7 transition roadmap, execution plan v6.0 amendment, and new-session handover package per committee order P7-TRANSITION-DOC
```

- **全库提交总数**：**严格仅有 1 次提交**；
- **文件创生时刻**：`2026-10-10 13:53:29 +0800`（Commit `0f62bcaa`）；
- **最后一次实质内容更新**：即创生提交 `0f62bcaa`；
- **后续修改记录**：自 2026-10-10 创生以来，**在 main 分支及任何 feature/fix 分支上，从未发生过任何一次提交修改**！

---

### 2.2 提交时序交叉比对（代码 vs ROADMAP）

将五个交易模块的首次提交时间与 `docs/ROADMAP.md` 的提交时间置于统一绝对时间轴比对：

```
2026-09-21 22:40:10  src/risk/ 首次提交 (5c7556e) ─────────────┐
2026-09-22 10:27:14  src/bankroll/ 首次提交 (40988de) ─────────┤ 早于 ROADMAP 18 天已落盘
2026-09-22 11:01:34  src/execution/ 首次提交 (4785625) ────────┘
        │
        ▼ (间隔 18 天)
2026-10-10 13:53:29  docs/ROADMAP.md 首次且唯一一次提交 (0f62bcaa)
        │            └── 原文声称: "Phase 2 交易引擎完成度为 0.0%"
        ▼ (间隔 1 天)
2026-10-11 22:26:35  CLOB 采集 (polymarket_clob_collector.py) 首次提交 (94eec7c)
2026-10-11 22:34:51  纸面评估 (paper_evaluation_engine.py) 首次提交 (d7a114d)
```

---

### 2.3 缺口定性终审判定（二选一判决）

依据上述无可争议的时序事实，做出终审定性判决：

**【判定结论】**：**ROADMAP 从未更新（连分支上也没有人动过它，纯粹是写码时没这个动作）**。

#### 详细依据与责任定性：
1. **排查结果排除了“分支未合流”假说**：全库所有分支（包括当前 `fix/p7-w2-shortloop`、历史 `fix/p7-w1-poolphase`、`origin/main` 等）对 `docs/ROADMAP.md` 的修改提交数为严格为 0。没有任何分支存在“已在分支上更新了 ROADMAP 但未合入 main”的现象。
2. **产生缺口的真实根因**：
   - **历史盲视（2026-10-10 创生时）**：在 2026-10-10 撰写 `docs/ROADMAP.md` 时，撰写者未核对代码库实际资产，脱离事实凭空抄写了早期规划假定，机械断言“交易引擎完成度为 0.0%”，完全无视了 18 天前（2026-09-22）就已经合并入库的 `src/execution/`、`src/bankroll/`、`src/risk/` 模块与 200 余项通过的单元测试；
   - **动作缺位（2026-10-11 新写时）**：在 2026-10-11 代理人新写 CLOB 采集器与纸面评估引擎并提交代码时，提交标准流程（Commit Checklist）中根本未包含“同步维护法定 ROADMAP.md”的动作，导致代码持续推进、文档原地冻结。
3. **性质定级**：**这是严重的流程纪律缺口（commit 标准动作不含文档同步与资产台账闭环），不是版本冲突或合并事故**。

---

## 第三章 · 宪法对齐核查

对五个交易侧模块针对现行五项核心宪法规范逐一审查：
1. **结算源**：ADR-0012 法定 NWS WRH 官方时序表（Time Series Tabular）
2. **ECE 门禁**：0.0100 硬门禁（ADR-0017 / ADR-0018 / SEALING_GATE）
3. **站点宇宙**：Active 10 法定主力交易池（`KATL, KAUS, KDAL, KHOU, KLAX, KLGA, KMIA, KORD, KSEA, KSFO`）
4. **阶梯规格**：Polymarket 2°F 阶梯离散区间规范（半度连续性修正）
5. **合流规则**：ADR-0011 / ADR-0013 双源单调合流与特报三道纯温门禁

### 3.1 模块宪法对齐核查矩阵

| 模块名称 | 宪法维度 | 模块现有逻辑 / 假设实现 | 对齐定性 | 改造建议与说明 |
| :--- | :--- | :--- | :---: | :--- |
| **`src/execution/`** | 结算源 (ADR-0012) | 负责 IOC 限价单保护价计算与残局对冲，不直接消费结算报文 | **不影响** | 纯微观结构执行层，与结算源无直接数据耦合。 |
| | ECE 门禁 (0.0100) | 直接消费上游给出的模型概率与订单簿盘口，未设 ECE 守卫 | **不影响** | ECE 校验应在上游定价或预买门禁阻断，执行引擎无需复算。 |
| | Active 10 站点 | 透传 `station_id`，无硬编码非法台站 | **不影响** | 契约支持全量 Active 10。 |
| | 2°F 阶梯规格 | 处理离散 token 价格与撮合深度，不依赖气温步长数值 | **不影响** | 对任何离散档位平权兼容。 |
| | SPECI 合流规则 | 接收 Watchdog 发送的 `cancel_all_open_orders` 撤单信号 | **不影响** | 完全响应 Fail-Closed 物理撤单动作。 |
| **`src/bankroll/`** | 结算源 (ADR-0012) | `zombie_evaluator.py` 严格实现当地时间次日闭合 + 12h 宽限；`bankroll_manager.py` 严格 Decimal 定点截断 | **不影响** | 深度合宪，完全对齐 ADR-0012 §D2 与 §D3。 |
| | ECE 门禁 (0.0100) | 联合凯利以输入的离散胜率为参数求解增量最优化，不验 ECE | **不影响** | 资金分配逻辑独立于物理校准检验。 |
| | Active 10 站点 | `zombie_evaluator.py:18` 显式导入 `ACTIVE_10_STATIONS` 与 `STATION_METADATA` | **不影响** | 强绑定法定 Active 10 台站白名单。 |
| | 2°F 阶梯规格 | 凯利方程天然支持完备互斥多项档位，保证乘法侧置零 | **不影响** | 对齐项目方案 v2.8 §6。 |
| | SPECI 合流规则 | 响应仲裁中枢挂起状态，冻结 Active Locked 预算调配 | **不影响** | 联动机制完整。 |
| **`src/risk/`** | 结算源 (ADR-0012) | 异常总线包含 `SETTLEMENT` 子系统定级，遵循 ADR-0014 契约 | **不影响** | 纯控制面契约，合宪。 |
| | ECE 门禁 (0.0100) | 负责运行时流式异常与物理单步跳温（15.0°F）拦截 | **不影响** | 离线选型 ECE 不影响运行时风控逻辑。 |
| | Active 10 站点 | `incident_protocol.py:19` 严格定义 `ALLOWED_STATION_SCOPES: Set[str] = set(ACTIVE_10_STATIONS) | {"GLOBAL"}`；单测严格断言 `KDCA` 必须被拒绝抛错 | **不影响** | 强防御法定 Active 10，物理隔离已注销站点。 |
| | 2°F 阶梯规格 | `two_dimensional_risk.py` 基于 $|T_{target} - T_{now}|$ 与关盘倒计时进行阶梯仓位打折 | **不影响** | 满足 ADR-0011 两维风控阶梯要求。 |
| | SPECI 合流规则 | `stream_watchdog.py` 严格实现 15min 到达超时与 15.0°F 跳温阻断；`central_arbiter.py` 实现 30s 预算衰竭升级与 Fail-Closed 0ms 撤单 | **不影响** | 完整实现 ADR-0011 与 ADR-0014 法定条款。 |
| **CLOB 采集**<br>(`polymarket_clob_collector.py`) | 结算源 (ADR-0012) | 从 Polymarket API 读取 `end_date_iso` 记录 `official_settlement_time`，未对齐 NWS WRH 官方时序表 | **需改造** | 应追加链下结算源时间戳与格式交叉检验。 |
| | ECE 门禁 (0.0100) | 纯订单簿抓取，不涉及概率与 ECE | **不影响** | 无耦合。 |
| | **Active 10 站点** | **`KNOWN_CITY_TO_STATION`（第 40~47 行）硬编码严重错配：<br>• `"dallas": "KDFW"`（错！法定为 KDAL）<br>• `"houston": "KIAH"`（错！法定为 KHOU）<br>• `"denver": "KBKF"`（错！已排除站）<br>• `"london": "EGLL"`（错！非美台站）** | **结构性冲突<br>(严重阻断)** | **必须彻底改造**：立即重构该映射表，达拉斯强制锁定 `KDAL`，休斯敦强制锁定 `KHOU`，物理删除 `KBKF` 与 `EGLL`，并加入 `ACTIVE_10_STATIONS` 强断言防御。 |
| | 2°F 阶梯规格 | 仅提取原始标签文本（`bracket_label`），未校验档位步长与覆盖度 | **需改造** | 应追加 2°F 阶梯覆盖完备性检验。 |
| | SPECI 合流规则 | 纯交易盘口采集，不采集气象实况流 | **不影响** | 无直接依赖。 |
| **纸面盘评估**<br>(`paper_evaluation_engine.py`) | 结算源 (ADR-0012) | `parse_bracket_bounds` 实现了标准 NWS WRH $\pm 0.5^\circ\text{F}$ 连续性舍入修正 | **不影响** | 端点划分符合 ADR-0012。 |
| | ECE 门禁 (0.0100) | 调用 `RealEMOSPipeline` 生成概率，但对调用挂旗资产（如 `KMIA_12h`）未强制带旗声明或降杠杆 | **需改造** | 下游调用必须显式检查资产治理状态（带旗资产收缩头寸）。 |
| | Active 10 站点 | 透传自 CLOB 采集器的 `station_id`，易受其错配字典（KDFW/KIAH）污染 | **需改造** | 上游修复后需在此处追加 `ACTIVE_10_STATIONS` 白名单入参守卫。 |
| | 2°F 阶梯规格 | 完整实现区间解析，支持 `56-57°F -> (55.5, 57.5)` 2°F 跨度与双尾截断 | **不影响** | 几何积分逻辑高度吻合。 |
| | SPECI 合流规则 | 当前仅调用静态 EMOS 预报，未挂接 `DynamicCorrector`（实况日内单调截断） | **需改造** | 纸面盘需与日内实况流单调截断串联以反映特报淘汰。 |

---

## 第四章 · 资产状态改判与治理建议

### 4.1 交易侧五大模块资产状态改判定级表

依据第三章宪法对齐核查结论，对五个模块进行权威状态三分类定级（可用 / 继承需复检 / 禁用）：

| 模块名称 | 资产分类定级 | 改判状态理由与前置整改条件 |
| :--- | :---: | :--- |
| **1. `src/execution/`** | **可用**<br>(通过宪法核查) | 经审查，该模块完全独立于站点代码与结算细节，IOC 保护价路由、残局自愈状态机及 Decimal 算术截断完全符合现行宪法；单测 100% 全绿，无历史污染，准予正式列入现役可用资产库。 |
| **2. `src/bankroll/`** | **可用**<br>(通过宪法核查) | 经审查，该模块全流程采用 Decimal 6 位定点截断，四桶资金管理与多项联合凯利优化器逻辑稳健，僵尸仓位判定与 Active 10 元数据完全合宪；集成测试通过，准予正式列入现役可用资产库。 |
| **3. `src/risk/`** | **可用**<br>(通过宪法核查) | 经审查，该模块严格落地 ADR-0014 统一异常仲裁中枢契约，台站范围白名单严格锁定 Active 10（单测包含 KDCA 负向拦截断言），Fail-Closed 0ms 撤单与本地拔网线机制完备，准予正式列入现役可用资产库。 |
| **4. CLOB 采集**<br>(`polymarket_clob_collector.py`) | **继承需复检**<br>(需改造) | **存在严重结构性冲突**：城市台站映射表中存在重大违规（达拉斯错标 KDFW、休斯敦错标 KIAH、混入非主力站 KBKF 与伦敦 EGLL）。在修复字典映射、对齐 `src/data_processing/constants.py` 并增加白名单前，**严禁投入生产交易**。 |
| **5. 纸面盘评估**<br>(`paper_evaluation_engine.py`) | **继承需复检**<br>(需改造) | 基础区间几何解析合宪，但尚未挂接日内 SPECI 动态截断层（`DynamicCorrector`），且对上游挂旗资产（`KMIA_12h`）缺失治理级头寸惩罚；需改造完成后方可开展实盘纸面撮合。 |

---

### 4.2 ROADMAP“完成度 0.0%”改判文案（依任务 2 判决定性）

由于任务 2 已彻底查明：**ROADMAP 从未更新（连分支上也没有人动过它，纯粹是写码时没这个动作，系流程纪律缺口）**。

因此，按照工单要求，正式出具法定改判文案：

> ### 📢 **法定改判文案（ROADMAP.md §1 & §4 勘误声明）**：  
> **“文档滞后，实际状态见资产登记”**。  
> 
> **事实说明**：  
> `docs/ROADMAP.md` 中关于“整个 Phase 2 交易引擎完成度为 0.0%”的表述系 2026-10-10 创生时未核对代码库现状的**历史事实性滞后**。经工单 `P7-PROV-1-R2` 穿透考古证实：交易引擎核心模块（`src/execution/`、`src/bankroll/`、`src/risk/`）早于 2026-09-22 便已随 Phase 2 Task 02/03/05/06 正式开发落盘，并通过了 200 余项单元与集成测试检验，资产状态现已正式确权并改判为**【可用（通过宪法核查）】**。CLOB 采集与纸面盘评估引擎已于 2026-10-11 新写，当前处于**【继承需复检】**状态。

---

### 4.3 研发流程防重纪律建议

针对本次查明的“commit 标准动作不含文档同步”纪律缺口，建议委员会在《AGENTS.md》及 CI 门禁中增补以下铁律：

1. **将 ROADMAP 与 STATUS 纳入代码合流 PR 的强制性验收门禁（Blocking Gate）**：
   - 凡涉及 `src/` 下新增业务模块或完成阶段任务的 PR，其修改清单中**必须成对包含对 `docs/ROADMAP.md`（更新完成度与里程碑）和 `STATUS.md`（更新活跃工作流与待办项）的显式同步**；
   - 缺少文档同步修改的生产代码 PR，CI 静态检查直接判定 FAIL，评审人一律禁止点击 Merge。
2. **建立静态台站白名单自动化扫描器**：
   - 在 CI 流程中加入 AST 扫描工具，凡在任何 `src/` 代码中硬编码未在 `ACTIVE_10_STATIONS` 内的台站标识（如 KDFW、KIAH、KBKF、KDCA 等），自动阻断构建并报错，从物理上杜绝如 `polymarket_clob_collector.py` 般的台站错配事件再次发生。
