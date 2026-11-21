---
created: 2026-09-04 14:07:02
updated: 2026-11-19 00:00:00
---
# 项目状态（唯一状态入口 · 已对齐 `项目方案 v3.0 §8`）

> 📌 **法定长线规划与新会话交接导航**：最新架构基线与增量决议见 [`P8-KERNEL-CONSENSUS v1.1`](docs/audit/P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md)；资金与参数账本见 [`P8-CAPITAL-CONFIG v1.0`](docs/audit/P8-CAPITAL-CONFIG_资金参数配置_v1.0.md)；`w / φ` 执行设计见 [`P8-EXECUTION-DESIGN v1.0`](docs/audit/P8-EXECUTION-DESIGN_w与phi设计与决策记录_v1.0.md)；平台客观事实见 [`P8-FACTS-LEDGER v0.3`](docs/audit/P8-FACTS-LEDGER_静态事实档案_v0.1.md)；战术活队列与十模块动态状态详见 [`P8-GLOBAL-MAP v1.3`](docs/audit/P8-GLOBAL-MAP_项目全局图谱_v1.0_20261113.md)；战略路线图见 [`docs/ROADMAP.md v1.4.1`](docs/ROADMAP.md)；检验 C 全过程档案详见 [`P8-INSPECTION-C-FULL-DOSSIER`](docs/audit/P8-INSPECTION-C-FULL-DOSSIER_20261114.md)；新会话冷启动交接清单详见 [`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)；封盘门禁详见 [`docs/SEALING_GATE.md`](docs/SEALING_GATE.md)；受控出域同步政策详见 [`docs/SYNC_POLICY.md`](docs/SYNC_POLICY.md)。  
> 📚 **核心宪法文档指针**：顶层方案 [`项目方案 (v3.0)`](docs/项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md)（`§8` 新增 `M1–M10` 模块地图、`P1–P19` 协议清单、`rc` 草案与 `edge_math.py` 规格）与 Phase 2 执行文件 [`Phase 2 执行文件 v2.2`](docs/项目方案和执行文档/Phase%202%20执行文件%20v2.2：盘口定价、套利与执行引擎.md) 继续生效；`2026-11-17 / 2026-11-18` 所有新增参数与策略配置均为 **当前决策 / 首期选择 / 数据前预设（月度复检可替换）**。

> 🚩 **【法定运行旗持续生效（下游强制带旗）】**：  
> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（交易窗口加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 未达立项门槛；双城 24 格中 23 格 ECE 达标率 95.83%）。  
> （注：原【运行旗 2】`6h 池化回退层` 已依据裁决令 `P7-FLAG2-REMOVAL-R1` / 工单 `P7-W1-POOLPHASE` 正式拔除，拔旗依据：晨谷加权 ECE = `0.005977` 击穿 0.0100 硬门禁，四季方差膨胀比 1.0000 全面自洽；L3 Max 衰减函数休眠资产注记已关闭）  
> *下游引用约束*：交易盘口映射、分位数定价与风控链路在调用本格资产时，**必须显式带旗陈述，审慎收缩头寸，严禁脱旗裸跑**！

- **当前阶段**：Phase 7 过渡态（主线战略转向：由横向扩展转向纵向落地）。主干 `main` 基线更新至 PR #132 合流线 `5c4a4c9`（完成 W1 6h 池化层昼夜相位分层重训与 TMax 方差衰减补齐，全量通过 C1~C6 门禁，拔除运行旗 2），全库测试基线提升至 1006 passed 全绿。*主干基线指针锚定封卷 merge commit（当前 5c4a4c9）；锚点之上的 docs-only 修正不触发指针升版，除非发生新的工单合流。*（修订依据：工单 P7-W1-POOLPHASE 与裁决书 P7-W1-B-CLOSURE-VERDICT-R1 2026-10-10）
- **活跃工作流**：
  - 6h 池化回退层相位分层重训与 TMax 方差衰减补齐（工单 `P7-W1-POOLPHASE`）：已全量验收封卷并合流入 `main`（PR #132），状态 `COMPLETED_SEALED`，全库测试基线 1006 passed，拔旗令 `P7-FLAG2-REMOVAL-R1` 签署生效；
  - 宪法文档与演化全景对账（工单 `P7-DOC-RECON`）：PR #131 已正式合流至 `main`，原独立工单 `P7-DOC-README` 标记为 `SUPERSEDED_BY(P7-DOC-RECON)` 并随 PR #131 执结闭环；
  - 长线规划入册与新会话交接包组装（工单 `P7-TRANSITION-DOC`）：已执结归档；
  - 第一类物理参数受控域治理与契约解耦（工单 `P8-CLASS1-LAUNCH` / `Ticket 26`）：完成 `src/contract/parameter_domains.py` 两级受控域模块建立与 `CellCalibrationRecord` 委托校验，T01~T21 测试全绿，解耦算法层魔法数字，为 Ticket 05 铺平门禁；
  - 参数契约安全集成与防污染封盘（工单 `P8-CLASS1-LAUNCH` / `Ticket 05`）：完成 8 项安全防御用例，通过 CHK-18 签署复核，参数契约层全量封盘；
  - Q7 覆盖率双轨分工与计算解耦（工单 `P8-CLASS1-LAUNCH` / `Ticket 06`）：完成 `src/pricing/coverage_dual_track.py` 覆盖率双轨模块，实现 exact（事后审计）与 gaussian_proxy（在线定价）彻底解耦，三不混用与无状态上下文强校验（T01~T14 全绿）；
  - 基于 s_oos 的方差自适应膨胀 σ_adj 计算引擎（工单 `P8-CLASS1-LAUNCH` / `Ticket 07`）：完成 `src/pricing/sigma_adj.py` 纯函数引擎与 F-2 挂锁熔断架构，已通过 CHK-20 签署封盘（#140 闭环）；
  - 交易 EV 引擎与 S1 盘口穿透探针计算（工单 `P8-CLASS1-LAUNCH` / `Ticket 08`）：完成 `src/pricing/penetration_probe.py` 最小 EV 内核与安全容量 $S_{\text{target}}$ 探针计算，落地动态费率折算与 F-2 挂锁熔断防御，经 CHK-22 复验通过结项（#141 闭环）；
  - 覆盖率双轨三不混用与探针定价单测集（工单 `P8-CLASS1-LAUNCH` / `Ticket 09`）：完成 `tests/unit/pricing/test_order_probe_evaluator.py` 跨模块契约测试集建立，涵盖双轨三不混用（T01~T05）、纳秒级性能基准（T06）、σ_adj 22 格外展自洽（T07~T09）与探针含费边不变式（T10~T12），全量通过 G1~G8 门禁（T01~T12 全绿）。
- **冻结产物与专属红线**：`evidence/p4_audit_reliability_v13b_*` 与 `evidence/p6_tmax_methodology_closure.*` 冻结归档；主干 `main` 基线更新至 `5c4a4c9`（PR #132 合流），后续任何改动一律须新裁决令；生产代码（`src/` 与 `scripts/`）严格零无授权编辑。（修订依据：P6 终裁与 P7 治理纪律 2026-10-10）
- **待办事项（Backlog 全景）**：
  - **工单 P7-DOC-README**：状态 `SUPERSEDED_BY(P7-DOC-RECON)`（已并入 PR #131 执结闭环）。
  - **议题 P6-POOL-PHASE**：6h 池化回退层按验证时刻昼夜相位分层重训与 TMax 短时效物理方差衰减补齐（状态：`COMPLETED_SEALED`，工单 P7-W1-POOLPHASE 执结封卷，拔除运行旗 2）。
  - **议题 P6-CALM-OUTLIER**：平静日极端失准事前指纹判别与 Regime 条件模型评估（状态：`REGISTERED`，防删条款绝对维持，独立排期）。
  - **议题 P6-RESEARCH-NO-GATE-BIC**：去门控纯 BIC 竞赛评估机制研究（状态：`REGISTERED`，远期）。
  - **议题 P6-RESEARCH-DIURNAL-PHASE**：按验证时刻昼夜相位分层建模评估（状态：`REGISTERED`，远期，学术成果受 W1 实测反哺）。
  - **议题 P6-TMIN-CV-LOCK**：TMin 480 格交叉验证脚本 hardcode 解锁与审计规划（状态：`REGISTERED`，波次三）。
  - **议题 P7-STA-SURVEY**：Active 8 站轻量三原型机械归类与偏离筛选（状态：`REGISTERED`，波次三，纸面盘期间并行）。
- **为什么处于当前节点**：工单 P7-W1-POOLPHASE 全量通过验收并合流封卷（PR #132），拔旗令 P7-FLAG2-REMOVAL-R1 正式生效；当前节点 = W1 执结归档，进入 W2 短闭环预注册筹备。
- **`2026-11-14 ~ 2026-11-16` 最新节点切换（已对齐 `P8-KERNEL-CONSENSUS v1.0`）**：
  - **检验 C 终裁与 `α` 冻结**：方案 `α` 经 2019 分支 A 与 `2019-SEALED-001` 穷举反事实落地 **`TIER_C`**（推送提交 `58f5b22`），[`Proposal1CoolingDriftMuRHook`](src/prediction/dynamic_corrector.py) 已设生产 `default-off`，`F-2 LOCKED`（`src/pricing/`）保持冻结。
  - **内核定稿与资产/路线切换（`2026-11-16`）**：废止合流测绘协议与 `GFS 2020–2024` 历史回填、`GHCN backfill` 降级挂账、`β/γ` 选型考场收缩为分叉 1 形态冒烟；确立“生产即测绘（四元组日志）+ 防污染三条款（记录只读 / 模型冻结 / 单向收紧）”；**`G-15` 结算口径逐字核查（`T1`）** 升为最优先阻塞项（同阶段 `T2–T4` 零成本并行），待 **三个分叉（形态确认 / 冻结周期 / 首检内容）** 拍板及 **`D-6` 制度合龙** 产出后推进 `T8` 改版实现。
  - **`2026-11-17` 资金配置、`w / φ` 首期选择与分叉 1/2 关闭（当前决策 · 月度复检可替换）**：① 分叉 1（选 `1'`：移除 `T5`、`2019` 降级为 `T8` 影子形态验收）与分叉 2（首期 1 个月 + 方案 B）已关闭，新增 `T9` 后 **真盘切换门**；② [`P8-CAPITAL-CONFIG v1.0`](docs/audit/P8-CAPITAL-CONFIG_资金参数配置_v1.0.md) 确立总池 `$10,000 / $500/站 / k₀=2` 预设、门限额制与统一参数账本；③ [`P8-EXECUTION-DESIGN v1.0`](docs/audit/P8-EXECUTION-DESIGN_w与phi设计与决策记录_v1.0.md) 选定 `w=B2`（`p=1.5`）+ `φ=Edge` 感知 POV（`k=0` IOC）并暂缓主动退出至 `v2+`；④ [`P8-FACTS-LEDGER v0.1`](docs/audit/P8-FACTS-LEDGER_静态事实档案_v0.1.md) 建账收拢外生平台事实；⑤ 当前处于 [`ROADMAP v1.3.0`](docs/ROADMAP.md) **切片 1（`D-A2 + T1 G-15 + T4 + T2/T3` 并行）**，分叉 3 与合龙细则留待 `D-6` 下一桌议程。
  - **`2026-11-18` 切片 1（`S1-01 ~ S1-05`）全部收口（当前决策）**：① `S1-01`（`D-A2` 五组入 [`P8-FACTS-LEDGER v0.2`](docs/audit/P8-FACTS-LEDGER_静态事实档案_v0.1.md)，捕获 `11-20T23:59Z` Weather `feeRate 0.05→0.01`）；② `S1-02`（`T1 G-15` 三查锚定 `T_settle_close_utc` 并暴露 3 处 `ADR-0009/0012` 分叉）；③ `S1-03`（[`P8-T2-M7-LOGGING v1.0`](docs/audit/P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md)）；④ `S1-04`（[`P8-T4-M4M5-INTERFACE v1.0`](docs/audit/P8-T4-M4M5-INTERFACE_决策与执行接口规格_v1.0.md) + [`src/pricing/edge_math.py`](src/pricing/edge_math.py)，`74 passed`）；⑤ `S1-05`（[`passive_book_recorder.py`](src/data_acquisition/passive_book_recorder.py) 可启动态，`3 passed` + live `66` token 干跑通过，待用户批复开录）；见 [`ROADMAP v1.4.1 §3.5`](docs/ROADMAP.md#35-2026-11-18-当前决策-切片-1-任务表s1-01--s1-05--v140-新增)。
  - **`2026-11-19` `S1-06` 切片 1 补丁批收口关闭（当前决策）**：[`ADR-0009 §4`](docs/adr/ADR-0009：芝加哥%2008-31%20特报（SPECI）结算语义裁决与截断层规则.md#4-2026-11-19-s1-06--g-15-修订节--世界事实变更跟随当前决策) 与 [`ADR-0012 §5`](docs/adr/ADR-0012：法定结算真值源（NWS%20WRH）、僵尸仓位双轨估值与舍入闭环裁决.md#5-2026-11-19-s1-06--g-15-修订节--世界事实变更跟随当前决策) 增补落地 `G-15` 裁决；[`KERNEL §七`](docs/audit/P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md#七-s1-06-g-15-裁决事实增补max-恒等式定义域论证与-t8-m1-规格输入2026-11-19-当前决策) 闭合 `max` 恒等式定义域与 `M1 T8` 清单；[`FACTS-LEDGER v0.3`](docs/audit/P8-FACTS-LEDGER_静态事实档案_v0.1.md#21-2026-11-19-s1-06-变费复核与-费率时代标记规则当前决策) 确立 `0.05/0.01` 费率时代禁混采规则与 `P18` 帧时点费率回放规则；**切片 1 正式关闭，离实钱三步（录盘待批）**。
  - **`2026-11-21` 切片 2/3 并行推进中（实时唯一权威源见 [`P8-PROJECT-TASKS v1.0`](docs/audit/P8-PROJECT-TASKS_全量任务分解台账_v1.0.md)）**：`M1 (S3-01)` 已验收 `DONE`；`S2-01` (`M3`) 6 站 `Yes+No` 双分片被动录盘运行中；`M2 (S3-02)` 待并行验收闭环；`M4 (S3-04)` 与 `M5 (S3-05)` 桩路径代码与 `P4 v1.1` 双视角适配已完成本地单测（真实数据验收与回签挂 `S3-02 -> DONE` 及录盘积累）；`F-2` `src/pricing/` 保持零 diff 只读。
- **更新纪律**：每周更新本文件，三行以内说清阶段变化

（最近更新：2026-11-21）
