# 工单 P7-DOC-RECON-2-R2：任务 2 · 三方对账报告

**执行工单**：`P7-DOC-RECON-2-R2`  
**审计性质**：对账审计（代码客观状态 vs 路线图/状态文档 vs README 导航）  
**开工基准**：Git Commit HEAD = `ea72141e298d56a1f4f2d0de3e5ce41cda859d66`（处于分支 `fix/p7-w2-shortloop`）  
**执行时间**：2026-10-12  

---

## 议题 ① · 主干 Commit 与测试基线对账

### 1.1 原始客观观测取证（禁止转述数字，逐字原样记录）

- **命令 1**：`git rev-parse HEAD`  
  **原始输出**：  
  ```
  ea72141e298d56a1f4f2d0de3e5ce41cda859d66
  ```
  **当前分支**：`fix/p7-w2-shortloop`（追踪 `origin/fix/p7-w2-shortloop`）  
  **本地 main 分支指针**：`f7a3da4`（提交信息：`docs(p7): 锚定主干基线指针至 5c4a4c9 (PR #132 W1 合流线)`）

- **命令 2**：`pytest -q`  
  **执行命令**：`pytest -q`  
  **输出末尾关键片段**：  
  ```
  =============================== warnings summary ===============================
  ../../../../../opt/miniconda3/lib/python3.13/site-packages/herbie/core.py:31
    /opt/miniconda3/lib/python3.13/site-packages/herbie/core.py:31: DeprecationWarning: Herbie: Custom model templates in the config path is deprecated. Please use a Herbie plugin: https://github.com/blaylockbk/herbie-plugin-tutorial
      import herbie.models as model_templates

  tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message
  tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message
    /opt/miniconda3/lib/python3.13/site-packages/herbie/core.py:390: Pandas4Warning: Timestamp.utcnow is deprecated and will be removed in a future version. Use Timestamp.now('UTC') instead.
      assert self.date < pd.Timestamp.utcnow().tz_localize(None), (

  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  =========== 1062 passed, 10 skipped, 3 warnings in 634.72s (0:10:34) ===========
  ```
  **退出码**：`0`

### 1.2 三方对账与差异判定

| 来源维度 | 记录的 Git Commit 基线 | 记录的测试基线 | 判定与偏差定性 |
| :--- | :--- | :--- | :--- |
| **客观实际（代码库实测）** | `ea72141`（分支 HEAD）<br>`5c4a4c9`（main 锚点） | `1062 passed, 10 skipped, 0 failed` | **基线实测值**（包含分支上新增的 56 项交易与预测单测） |
| **`STATUS.md`**（第 15 行） | PR #132 合流线 `5c4a4c9` | `1006 passed` 全绿 | **一致**（锚定 PR #132 封卷合并 commit 5c4a4c9） |
| **`docs/HANDOVER_P7.md`**（第 29-30 行） | 锁定于 `5c4a4c9` | `1006 passed, 10 skipped, 0 failed` (634.74s) | **一致**（与 STATUS.md 一致） |
| **`README.md`**（第 6 行、第 195 行） | 固化于 `2975ec1`（PR #130） | `987 passed, 10 skipped, 0 failed` | **严重滞后**（README 落后 main 两个 PR 合流：PR #131 与 PR #132，测试基线落后 75 项） |

---

## 议题 ② · KMIA_12h 双旗状态与 P7-W1-POOLPHASE 工单状态

### 2.1 对账数据对照表

| 文档 / 渠道 | `KMIA_12h` 运行旗状态 | `6h 池化回退层` 运行旗状态 | `P7-W1-POOLPHASE` 工单状态 |
| :--- | :--- | :--- | :--- |
| **`STATUS.md`**（第 10-18 行） | `COMPLETED_ECE_FLAGGED`<br>（加权 ECE = `0.018318` 越线 0.0100，触发器 1/2） | **`UNFLAGGED` (已正式拔除)**<br>依据裁决令 `P7-FLAG2-REMOVAL-R1` | `COMPLETED_SEALED`<br>已全量验收封卷并合流入 `main` (PR #132) |
| **`docs/HANDOVER_P7.md`**（第 31-34 行） | `COMPLETED_ECE_FLAGGED`<br>（加权 ECE = `0.018318` 越线 0.0100） | **`UNFLAGGED` (已正式拔除)**<br>晨谷 ECE = `0.005977`，膨胀比 1.0000 | `COMPLETED_SEALED`<br>拔旗令生效，测试基线 1006 passed |
| **`README.md`**（第 15-18 行、第 94 行） | `COMPLETED_ECE_FLAGGED`<br>（加权 ECE = `0.018318` 越线 0.0100） | **`FLAGGED_POOL_PHASE_ISSUE` (严重滞后)**<br>仍声称双重法定运行旗在役，未拔旗 | **进行中 / 领单中 (严重滞后)**<br>声称“工单 P7-W1-POOLPHASE 专项修复中” |

### 2.2 结论
- `KMIA_12h` 运行旗：三方文件均确认其状态为 `COMPLETED_ECE_FLAGGED`，必须持续带旗引用。
- `6h 池化回退层` 运行旗与工单 `P7-W1-POOLPHASE`：`STATUS.md` 与 `HANDOVER_P7.md` 真实反映了 PR #132 已结项封卷并拔除运行旗的事实；而 `README.md` 完全未同步，仍停留于修复前陈旧草稿。

---

## 议题 ③ · W1 实际进度对账

1. **`docs/ROADMAP.md` §3.1 规划定义**：
   - 目标：6h 池化回退模型按验证时刻昼夜相位分层重训 + `src/modeling/interpolator.py` Max Temp 短时效 $\sigma_L = \sigma_{24\text{h}}\sqrt{\max(0, L)/24.0}$ 物理方差衰减补齐；
   - 验收出口：加权 ECE $\le 0.0100$ 并拔除运行旗 2；
   - 路线图制定时状态：`ACTIVATED_W1_PLANNED`。
2. **实际工程进度取证**：
   - Commit `f023182`（P7-W1-A）：完成 Max Temp 短时效开方方差衰减补齐；
   - Commit `5d4dcb0`（P7-W1-B）：完成 6h 池化层昼夜相位（晨谷簇 vs 峰顶簇）分层重训，通过门禁 C1~C6；
   - Commit `fcab6e1`（P7-W1 结项）：签发裁决书 `P7-W1-B-CLOSURE-VERDICT-R1` 与拔旗令 `P7-FLAG2-REMOVAL-R1`；
   - PR #132（Commit `5c4a4c9`）：正式合并入 `main`。
3. **判定**：**W1 已 100% 完工封卷并出域合流入 main**。当前状态为 `COMPLETED_SEALED`。

---

## 议题 ④ · W2 实际进度与“代码先于路线图”异常登记

### 4.1 路线图与交接文档声称
- **`docs/ROADMAP.md` §1 第 18 行、§3.2**：
  - 声称：“整个 Phase 2 交易引擎（实况多源单调合流、特报截断、异常仲裁、离散 EV 映射、资金凯利、IOC 订单路由、纸面盘模拟）完成度为 0.0%”；
  - 规定：“在动手编写任何 Phase 2 生产代码前，agent 必须先向委员会呈报《Phase 2 短闭环预注册规格书》... 批准后方可开跑”；
- **`docs/HANDOVER_P7.md` §二、§三**：
  - 声明：“W2 开工条件：未就绪 (准备中)，须经委员会审批签署《Phase 2 短闭环预注册规格书》”；
  - 声明：“当前唯一标准动作：向委员会呈报 W1 全量结项封卷... 准备开启 W2 短闭环预注册”。

### 4.2 实际代码库（`src/`）物理存在性审查

对代码库进行只读扫描，发现大量交易侧模块**早在历史提交中就已经存在且有完整单元测试**：

| 模块类别 | 文件物理路径 | Git 跟踪状态 | 所属历史任务 | 标注说明 |
| :--- | :--- | :---: | :--- | :--- |
| **盘口数据采集** | `src/data_acquisition/polymarket_clob_collector.py` | 存在 (Tracked) | Phase 2 / W3-T1 | **代码先于路线图** |
| **盘口定价与 EV** | `src/pricing/ev_engine.py` | 存在 (Tracked) | Phase 2 Task 04 | **代码先于路线图**（Commit 98c85c4） |
| **纸面盘评估引擎** | `src/pricing/paper_evaluation_engine.py` | 存在 (Tracked) | Phase 2 / W3-T2 | **代码先于路线图**（Commit d7a114d） |
| **执行引擎与路由** | `src/execution/execution_engine.py`<br>`src/execution/order_router.py`<br>`src/execution/clob_client.py`<br>`src/execution/residual_risk.py` | 全部存在 (Tracked) | Phase 2 Task 06 | **代码先于路线图**（PR #88 / Commit 4785625） |
| **资金与凯利优化** | `src/bankroll/bankroll_manager.py`<br>`src/bankroll/multinomial_kelly.py`<br>`src/bankroll/risk_limiter.py`<br>`src/bankroll/zombie_evaluator.py` | 全部存在 (Tracked) | Phase 2 Task 05 | **代码先于路线图** |
| **异常仲裁与风控** | `src/risk/central_arbiter.py`<br>`src/risk/emergency_control.py`<br>`src/risk/incident_protocol.py`<br>`src/risk/stream_watchdog.py`<br>`src/risk/two_dimensional_risk.py` | 全部存在 (Tracked) | Phase 2 Task 03 | **代码先于路线图** |
| **模拟与撮合** | `src/simulation/paper_engine.py`<br>`src/simulation/backtest_engine.py`<br>`src/simulation/market_maker.py`<br>`src/simulation/settlement_sim.py` | 全部存在 (Tracked) | Phase 2 Task 07 | **代码先于路线图** |

### 4.3 判定结论
**【严重定性：代码先于路线图 (Code Preceded Roadmap)】**  
ROADMAP.md 在编写时做出了脱离代码库现实的断言（声称交易引擎完成度为 0.0%），而实际上核心交易侧模块早已编写并在 tests 下拥有 200+ 单元测试。不仅如此，在分支 `fix/p7-w2-shortloop` 上，开发代理人已私下推进了 W2-A、48h 观测，甚至所谓 W3-Task 1~3 的开发。形成了“**文档宣称未动工、实际代码已写完半套、分支私跑脱节**”的严重背离。

---

## 议题 ⑤ · W3 两项在 ROADMAP 原文表述

查阅 `docs/ROADMAP.md`，两项任务的法定原文表述如下：

1. **`P7-STA-SURVEY` 原文表述（`docs/ROADMAP.md` §3.3 第 97-102 行）**：
   > **8 站 P7 原型筛查 (`P7-STA-SURVEY`)**：  
   > 彻底摒弃逐格耗费两周的重复慢速取证，采用**轻量三原型机械归类**：  
   > 1. **内陆温带正午峰度型**（以 KORD 为原型）；  
   > 2. **副热带沿海对流负偏型**（以 KMIA 为原型）；  
   > 3. **特殊物理偏离型**（强逆温海雾 KSFO/KLAX、阿巴拉契亚山麓冷池 KATL 等）。  
   > 对 8 站提取 12 提前期矩全景、晨谷/峰顶残差相位分解与 PIT 方差三指标，凡严格吻合原型 1 或 2 者，直接套用已封盘的门禁规约批量入账；唯有落入原型 3 者，方升级开立单站专项 P6 级审计；

2. **`P6-TMIN-CV-LOCK` 原文表述（`docs/ROADMAP.md` §3.3 第 103-105 行）**：
   > **TMin 审计线 (`P6-TMIN-CV-LOCK`)**：  
   > 解锁 `tests/unit/modeling/test_p4_block_cv_20fold.py` 中 `variable="tmax"` 的硬编码，完成参数化改造；  
   > 编制 480 格 TMin 的 Block-CV 审计推进计划。

3. **时序前置依赖（`docs/ROADMAP.md` §3.3 第 96 行）**：
   > **依赖声明**：W3 开工时间不得早于 W2 纸面盘只读观测模式平稳启动运行。

---

## 议题 ⑥ · ADR-0011 / 0012 / 0013 与 README 转述一致性核验

| ADR 编号与主题 | ADR 法定原文核心裁决 | `README.md` 转述内容 | 一致性判定 | 差异下钻与定性 |
| :--- | :--- | :--- | :---: | :--- |
| **ADR-0011**<br>双源单调合流与两维风控 | 确立 IEM ASOS 主力驱动与 NWS WRH 异步影子对齐；$T_{\text{max}} = \max(T_{\text{IEM}}, T_{\text{WRH}})$；15min 心跳撤单与 35min 龄期休眠。 | 第 104 行提及单调合流、日内单调非递减/非递增。第 135 行提及 ADR-0011 两维阶梯风控。 | **基本一致** | README 仅保留了概念定性，未载入 15min 与 35min 具体动作门槛。 |
| **ADR-0012**<br>法定结算真值源与僵尸双轨 | **D1 明文确立：“NWS WRH 官方时序表（Time Series Tabular）为结算复刻器的唯一外部法定真值消费源”**；全美三大时区当地日闭合 12h 宽限；Decimal 算术四舍五入。 | **第 56 行与第 103 行转述：“NWS WRH CF6 每日气候报表 (Polymarket 法定结算源)”** | **不一致 (严重概念漂移)** | **重大概念漂移**：ADR-0012 全文为“时序表 (Time Series Tabular)”，从未提及“CF6 报表”。README 擅自转述为 CF6 报表，混淆了高频逐时时序表与月末气象汇总表（CF6），违反词表受控铁律。 |
| **ADR-0013**<br>特报高频截断与异常阻断 | SPECI 零延迟单向截断；三道纯温门禁（极值域 $[-40, 135]^\circ\text{F}$、正文 vs RMK 偏差 $\le 1.8^\circ\text{F}$、跳温 $\le 15.0^\circ\text{F}$）；迟到（>15min）不投；异常直接阻断 Fail-Closed。 | 第 104 行转述：“特报 SPECI 实施‘纯温门禁、迟到不投、跳温阻断’”。 | **基本一致** | 提炼了三字定性，符合 ADR 原文精神，但具体数值门禁未转述。 |

---

## 三方对账总结

1. **主干基线与测试**：main 停留在 PR #132（`5c4a4c9`，1006 项测试全绿），分支 HEAD 处于 `ea72141`（1062 项测试全绿）；README 严重滞后于 `2975ec1`（987 项测试）。
2. **运行旗状态**：KMIA_12h 生效持续；6h 池化层已于 PR #132 正式拔旗；README 滞后未更新。
3. **架构资产与客观现实**：存在严重的“代码先于路线图”问题。大量交易侧生产模块已编写测试就绪，但法定路线图与状态文档未对其进行资产建账与合流管理。
4. **术语口径漂移**：README 将 ADR-0012 法定“NWS WRH 官方时序表”错误转述为“CF6 每日气候报表”，需用户裁决纠正。
