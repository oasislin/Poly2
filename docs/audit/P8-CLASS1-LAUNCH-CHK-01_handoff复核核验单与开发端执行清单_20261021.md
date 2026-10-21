# P8-CLASS1-LAUNCH-CHK-01 · 第一类投注/定价层 handoff 复核核验单与开发端执行清单

> **日期**：2026-10-21
> **工单（B 线）**：`P8-CLASS1-LAUNCH`（治理批次 8，继承 P4/P6/P7 编号序列；命名依据《项目编号与命名规范_20261021.md》§1）
> **核验单**：`P8-CLASS1-LAUNCH-CHK-01`
> **复核对象**：`docs/handoffs/2026-10-21-handoff-class1-pricing-betting.md`
> **复核人**：技术审核 Agent（只读复核，未改代码；git 状态以开发端仓库为准）
> **复核方式**：本地同步副本 + 证据资产（CSV/台账/判决书/裁决记录）交叉对账；判定采用「原始观测值 vs 判定阈值」两步分离，不掺主观结论。

---

## 一、 复核结论摘要

handoff 的三项核心声明（三分法位置、KMIA 欠自信承接数值、Q1/Q7 范围与红线）**全部核验通过**；另发现 **2 处文档一致性修正 + 1 处归属补正 + 1 项裁决锚定**，均不改变本阶段使命与红线，但必须随盘点与方案书一并落实。

---

## 二、 逐项核验结果

| # | 核验项 | 证据（原始值/原文） | 判定阈值 | 结论 |
| :-- | :-- | :-- | :-- | :-- |
| 1 | handoff 已落盘且与交接转述一致 | 文件存在，正文与转述逐节一致 | 文件存在且内容一致 | **通过** |
| 2 | Q1/Q7 转述忠实 | 对照 `docs/audit/P4-2019双城盲测_算法门禁说明与待challenge问题_20261020.md` §5：Q1「1.11 与 1.15 不应被悬崖式区别对待」、Q7「exact 与 gaussian_proxy 分工」「上界 0.95 防区间过宽」逐字一致；exact=真实分布 5/95 经验分位、gaussian_proxy=μ±1.64485·σ_eff 定义一致 | 转述与原文一致 | **通过** |
| 3 | KMIA 三格 Fstd 超界数值 | `evidence/audit_v2/p4blind_v2r01_metrics.csv`（s_oos 列）：KMIA_30h=1.363831→1.364、KMIA_48h=1.293564→1.294、KMIA_54h=1.284506→1.285；三行 `fstd_in=False`，其 Fstd 上界 1.2511/1.2524/1.2563 < 各自 s_oos；24h(1.236, in)/60h(1.231, in) 对照在带内 | 三格超界且数值一致 | **通过** |
| 4 | 尺子体检量：finf_in 11/22、fstd_in 19/22、reject_uniform 0/22、ece_2f 均值 0.0118、ece_range 均值 0.0078、pit_var 0.08242~0.09173 | 同上 CSV + `P4-BLIND-AUDIT-V2R01_V2尺子升级_开发任务单_20261021.md` §10（独立复算一致；ece_2f 均值 0.011835、ece_range 0.007836、pit_var 0.082422~0.091727） | 与 handoff §二一致 | **通过** |
| 5 | 第三类封闭、第二类闭环 | `DECISION_LEDGER.md` §十一 DECISION-20261021-05（已封闭）、§十二 DECISION-20261021-06（终审四项通过、commit `70c15f3`+`2d91cf3`） | 台账状态与 handoff §一一致 | **通过** |
| 6 | KMIA 整体欠自信移交第一类（z²>1.27，非相位结构） | DECISION-05 处置行；CHK-05 附表 KMIA 四相位 z² 1.2867~1.5585 全 >1.27 | 与 handoff §二一致 | **通过** |
| 7 | 未把 V2 体检尺升格为生产门 | handoff §一「已排除的弯路」+ §五「待标定项」自限一致；DECISION-06「ECE 法定阈值、PIT 通用带边界留审核方/用户」 | 自限声明与台账一致 | **通过** |
| 8 | git 基线（main@e421ac8、工作树干净、推送区间 2d91cf3..e421ac8） | 本地同步副本**非 git 仓库**（无 .git），无法本地核验 | — | **待开发端确认**（执行清单 Step 0） |

---

## 三、 发现与修正（审核裁决）

### 修正-1 · R-16 交易模块归档状态（文档一致性，必须补注记）

`src/bankroll/`、`src/execution/`、`src/risk/` 六个交易模块（central_arbiter/emergency_control/incident_protocol/pre_buy_gate/two_dimensional_risk/cli）已于 **2026-10-13 按用户裁决 R-16 方案 B 整体归档**至 `docs/archive/trading_modules/`（DECISION_LEDGER §五 R-16 ✅已完成；`R16_TRADING_MODULE_ARCHIVE_BRIEF.md`），现役树仅保留 `src/risk/__init__.py` + `src/risk/stream_watchdog.py`（+ 测试），归档状态为「待 P7-ALGO-2 重建，不做原样回迁」。

- handoff §四按归档前布局描述模块现状，须补注记：**盘点对象 = `docs/archive/trading_modules/src/{bankroll,execution,risk,pricing,simulation}` + 现役 `src/risk/stream_watchdog.py` + 现役 `src/prediction/discrete_bin_engine.py`、`truncated_probability_engine.py`**；
- 开发端 Step 0 必须先确认 e421ac8 主树实际状态：若 `src/bankroll` 等在主树存在，须先说明与 R-16 的矛盾再继续，不得静默假设。

### 修正-2 · C-1 状态过时（文档一致性，按判词更新）

handoff §四「稳健 Minimax 投影 C-1 挂起待裁决」为 **2026-10-12 台账旧状态**。2026-10-13 用户逐条签署《v1 遗产判决书》v0.3 后（LEDGER §四.3；`P7-ALGO-VERDICT.md`）：

- **M-4（p→q 市场价收缩）＝ 裁决废弃**：由概率层（𝒫 区间）承担防守，不移植 v1 Sigmoid 收缩；
- **M-1（稳健凯利 Minimax 求解器）＝ 裁决改造移植**：按 EMOS 闭式 CDF 重写入 P7-ALGO-2 规格，θ/η 标定挂 F-2 锁；
- C 类三案状态由【挂起】流转为【已解锁】（M-3/M-4/M-5 判词同步）。

注记须按 M-1/M-4 判词更新，不得沿用「挂起待裁决」。

### 修正-3 · 归属补正：第一类 Q1/Q7 属 P7-ALGO-2 管辖域（必须对账）

Q1（与 Kelly 联动的仓位折减）与 Q7（定价区间口径）落在 P7-ALGO-2《联合凯利与执行定价算法规格书》域内。handoff §四「规划依据」仅引 Phase 2 执行文件 v2.1，**须补 P7-ALGO-2 文档指针**，方案书必须对账：

| 对账项 | 出处 | 要求 |
| :-- | :-- | :-- |
| 折剪点唯一化 | `P7-ALGO-2_裁决记录.md` DR-2026-1014-02 | Q1 折减必须**并入 S2 预算公式（C_max）为唯一折剪点**，不新增后置乘子；τ_z/τ_2D 前置为既有先例 |
| G4 标准化残差 | DR-2026-1014-04 | σ 归一化 z 阈值属[待标定]，Q1 若复用须注明 |
| 不确定集 θ/η/δμ/δσ | 裁决记录附录 #6 | `[F-2 LOCKED]`，方案书不得给生产定值 |
| M-4 废弃收缩 vs Q1 折减 | VERDICT M-4 | Q1 折减基于**方差/校准量**（σ_adj），非 p→q 收缩，方案书须显式区分，避免与 M-4 判词冲突 |
| F-2 优先律 | VERDICT 总纲 | 折减系数、权重、曲线参数的**定值挂 F-2 锁**，概率层法定门（ECE 法定阈值、PIT 通用带）未设定前不落生产定值；设计可先行 |

### 裁决-R1 · F-2 优先律锚定（业务/技术裁决）

本阶段允许完成：连续可信度/置信度评分的**设计**（基于已测连续校准量 s_oos/ECE/覆盖率/PIT）与折减机制的**结构设计**。本阶段**禁止**：给评分权重、折减曲线、σ_adj 系数落生产定值（全部[待标定]，挂 F-2 锁）；用 2019 单年事后体检量充当生产验收门。

### 裁决-R2 · Q7 覆盖率双轨分工原则（业务/技术裁决）

- **exact（真实分布 5/95 经验分位）＝ 结算核验 / 事后校验口径**；
- **gaussian_proxy（μ±1.64485·σ_eff）＝ 实时定价区间口径**（与 M-1「EMOS 闭式 CDF 区间」一致）；
- G5 冻结带 [0.83, 0.95] 为门禁口径（防区间过宽解读成立与否须在方案书中论证），方案书须写明 G5、exact、gaussian_proxy 三者各自度量对象与**不得混用条款**。

---

## 四、 开发端执行清单（按序执行，先审核后编码）

### Step 0 · 开发端仓库基线确认（必做，原样上报）
1. `git status`（工作树是否干净）、`git log`（main @ `e421ac8`、推送区间 `2d91cf3..e421ac8`）原始输出；
2. **确认主树交易模块实际状态**：`src/bankroll/`、`src/execution/`、`src/risk/{central_arbiter,cli,emergency_control,incident_protocol,pre_buy_gate,two_dimensional_risk}.py` 在 e421ac8 是否存在；存在 → 停止并说明与 R-16 的矛盾；不存在 → 按归档目录盘点。

### Step 1 · 只读盘点（交付：盘点表）
- 对象：`docs/archive/trading_modules/src/{bankroll,execution,risk,pricing,simulation}`（bankroll_manager/multinomial_kelly/risk_limiter/zombie_evaluator；execution_engine/order_router/residual_risk/clob_client/models；risk 六模块；ev_engine；paper_engine 等）+ 现役 `src/risk/stream_watchdog.py` + `src/prediction/discrete_bin_engine.py` + `truncated_probability_engine.py` + 对应归档测试（`docs/archive/trading_modules/tests/`）；
- 每模块交付：路径 × 关键接口/函数签名 × 依赖 × 测试存在性与状态 × 备注；
- **纪律**：盘点为只读；不得把归档模块 import 进现役路径；不得凭本地副本或 handoff 假设；原始状态原样记录。

### Step 2 · 方案书（Q1+Q7 设计，交付审核）
必含：
1. Q1：连续可信度得分设计（四连续量输入）+ 仓位折减映射（与 Kelly 联动）+ 硬准入边界保留 + 无 1.11-vs-1.15 悬崖的软折减曲线 + KMIA 欠自信格在 σ_adj/Kelly 侧的收缩方案（不重训、不改 EMOS）；
2. Q7：exact/gaussian_proxy 分工成文 + 上界 0.95 解读论证 + 不得混用条款；
3. **P7-ALGO-2 对账节**（修正-3 表逐项回执：折剪点唯一化并入 C_max、M-4 区分、F-2 LOCKED 项、G4 z 阈值）；
4. 标定项清单：评分权重、折减曲线参数、σ_adj 系数、ECE 法定阈值、PIT 通用带边界——全部[待标定]，其中权重/系数挂 F-2 锁；
5. 出处核对：handoff §五「ECE≤0.0100 为交易侧内部口径」未在本次复核材料中找到出处 → **注明出处（预期 P7-ALGO-2 规格书/算法描述）或删除**，不留悬空数值；
6. 编码阶段 A 线编号建议（Phase 2 Task YY - Ticket ZZ，依命名规范 §1），审计项留在 P8-CLASS1-LAUNCH；
7. 红线重申：不重训 EMOS、不改 a/b/c/d 与 c_train、不写回 pkl/manifest、不改冻结 V1 结算与 2019 原始数组；实证数字附可复现工件引用（脚本路径 + 数据校验和 + 复现命令）。

### Step 3 · 提交审核
盘点表 + 方案书交回本审核方；**未获授权不编码、不落定值、不 push**。

---

## 五、 入库指令

- **允许 commit（不 push）**：handoff + handoff 审核注记（修正-1/2/3 三节内容，版本标注、不改写既有正文）+ 本核验单；
- **禁止 push**：push 仅凭用户明确指令，不代推、不 force、不 --no-verify。

---

## 六、 关键文档指针

- 待 challenge 原文：`docs/audit/P4-2019双城盲测_算法门禁说明与待challenge问题_20261020.md` §5
- V2R01 任务单/终审：`docs/audit/P4-BLIND-AUDIT-V2R01_V2尺子升级_开发任务单_20261021.md` §10
- 决议台账：`docs/audit/DECISION_LEDGER.md`（§四.3、§五 R-16、§十一、§十二）
- 归档清单：`docs/audit/R16_TRADING_MODULE_ARCHIVE_BRIEF.md`
- 判决书：`docs/audit/P7-ALGO-VERDICT.md`（M-1/M-4/F-2）
- P7-ALGO-2 裁决记录：`docs/audit/P7-ALGO-2_裁决记录.md`（DR-2026-1014-02/04、附录 #6）
- 规划依据：`docs/项目方案和执行文档/Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md`
