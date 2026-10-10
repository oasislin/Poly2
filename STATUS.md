---
created: 2026-09-04 14:07:02
updated: 2026-10-10 20:55:00
---
# 项目状态（唯一状态入口）

> 📌 **法定长线规划与新会话交接导航**：项目长线路线图详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)；新会话冷启动交接清单详见 [`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)；封盘门禁总清单详见 [`docs/SEALING_GATE.md`](docs/SEALING_GATE.md)；受控出域同步政策详见 [`docs/SYNC_POLICY.md`](docs/SYNC_POLICY.md)。  
> 📚 **核心宪法文档指针**：顶层方案已对账升级至 [`项目方案 (v2.8)`](docs/项目方案和执行文档/项目方案%20(v2.8)：Polymarket%20温度市场量化投注系统.md)；Phase 2 执行文件已对账升级至 [`Phase 2 执行文件 v2.1`](docs/项目方案和执行文档/Phase%202%20执行文件%20v2.1：盘口定价、套利与执行引擎.md)（历史 v2.7/v2.0 保持冻结，修订依据：工单 P7-DOC-RECON / PR #131 / 批文 P7-DOC-RECON-GO-MERGE）。

> 🚩 **【法定运行旗持续生效（下游强制带旗）】**：  
> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（交易窗口加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 未达立项门槛；双城 24 格中 23 格 ECE 达标率 95.83%）。  
> （注：原【运行旗 2】`6h 池化回退层` 已依据裁决令 `P7-FLAG2-REMOVAL-R1` / 工单 `P7-W1-POOLPHASE` 正式拔除，拔旗依据：晨谷加权 ECE = `0.005977` 击穿 0.0100 硬门禁，四季方差膨胀比 1.0000 全面自洽；L3 Max 衰减函数休眠资产注记已关闭）  
> *下游引用约束*：交易盘口映射、分位数定价与风控链路在调用本格资产时，**必须显式带旗陈述，审慎收缩头寸，严禁脱旗裸跑**！

- **当前阶段**：Phase 7 过渡态（主线战略转向：由横向扩展转向纵向落地）。主干 `main` 基线更新至 PR #132 合流线 `5c4a4c9`（完成 W1 6h 池化层昼夜相位分层重训与 TMax 方差衰减补齐，全量通过 C1~C6 门禁，拔除运行旗 2），全库测试基线提升至 1006 passed 全绿。*主干基线指针锚定封卷 merge commit（当前 5c4a4c9）；锚点之上的 docs-only 修正不触发指针升版，除非发生新的工单合流。*（修订依据：工单 P7-W1-POOLPHASE 与裁决书 P7-W1-B-CLOSURE-VERDICT-R1 2026-10-10）
- **活跃工作流**：
  - 6h 池化回退层相位分层重训与 TMax 方差衰减补齐（工单 `P7-W1-POOLPHASE`）：已全量验收封卷并合流入 `main`（PR #132），状态 `COMPLETED_SEALED`，全库测试基线 1006 passed，拔旗令 `P7-FLAG2-REMOVAL-R1` 签署生效；
  - 宪法文档与演化全景对账（工单 `P7-DOC-RECON`）：PR #131 已正式合流至 `main`，原独立工单 `P7-DOC-README` 标记为 `SUPERSEDED_BY(P7-DOC-RECON)` 并随 PR #131 执结闭环；
  - 长线规划入册与新会话交接包组装（工单 `P7-TRANSITION-DOC`）：已执结归档。
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
- **更新纪律**：每周更新本文件，三行以内说清阶段变化

（最近更新：2026-10-10 20:55）
