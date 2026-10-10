---
created: 2026-09-04 14:07:02
updated: 2026-10-10 17:00:00
---
# 项目状态（唯一状态入口）

> 📌 **法定长线规划与新会话交接导航**：项目长线路线图详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)；新会话冷启动交接清单详见 [`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)；封盘门禁总清单详见 [`docs/SEALING_GATE.md`](docs/SEALING_GATE.md)；受控出域同步政策详见 [`docs/SYNC_POLICY.md`](docs/SYNC_POLICY.md)。  
> 📚 **核心宪法文档指针**：顶层方案已对账升级至 [`项目方案 (v2.8).md`](项目方案%20(v2.8).md)；Phase 2 执行文件已对账升级至 [`Phase 2 执行文件 v2.1.md`](Phase%202%20执行文件%20v2.1.md)（历史 v2.7/v2.0 保持冻结，修订依据：工单 P7-DOC-RECON / PR #131 / 批文 P7-DOC-RECON-GO-MERGE）。

> 🚩 **【双重法定运行旗持续生效（下游强制带旗）】**：  
> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（交易窗口加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 未达立项门槛；双城 24 格中 23 格 ECE 达标率 95.83%）；  
> 2. `6h 池化回退层 (80 格)`：状态 `FLAGGED_POOL_PHASE_ISSUE`（晨谷方差膨胀比 1.45~1.81x，KMIA 晨谷 ECE = `0.019657` 越线 0.0100；Max Temp 缺失衰减公式依赖 METAR 实况硬截断兜底）。  
> *下游引用约束*：交易盘口映射、分位数定价与风控链路在调用本格资产时，**必须显式带旗陈述，审慎收缩头寸，严禁脱旗裸跑**！

- **当前阶段**：Phase 7 过渡态（主线战略转向：由横向扩展转向纵向落地）。主干 `main` 基线更新至 PR #131 合流线 `122d872`（完成全生命周期宪法文档对账升级与 README 重写），Phase 6 双城 TMax 24 时间格（96 季节格）验证收口、方法论封盘与池化 6h 审计全量合流入主干 `main`（全库测试基线 987 项全绿）。委员会立项会终裁确立三波次长线路线图（详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)）。（修订依据：立项会终裁与工单 P7-TRANSITION-DOC / P7-DOC-RECON 2026-10-10）
- **活跃工作流**：
  - 宪法文档与演化全景对账（工单 `P7-DOC-RECON`）：PR #131 已正式合流至 `main`，原独立工单 `P7-DOC-README` 标记为 `SUPERSEDED_BY(P7-DOC-RECON)` 并随 PR #131 执结闭环；
  - 长线规划入册与新会话交接包组装（工单 `P7-TRANSITION-DOC`）：已执结归档。
- **冻结产物与专属红线**：`evidence/p4_audit_reliability_v13b_*` 与 `evidence/p6_tmax_methodology_closure.*` 冻结归档；主干 `main` 基线更新至 `122d872`（PR #131 合流），后续任何改动一律须新裁决令；生产代码（`src/` 与 `scripts/`）严格零无授权编辑。（修订依据：P6 终裁与 P7 治理纪律 2026-10-10）
- **待办事项（Backlog 全景）**：
  - **工单 P7-DOC-README**：状态 `SUPERSEDED_BY(P7-DOC-RECON)`（已并入 PR #131 执结闭环）。
  - **议题 P6-POOL-PHASE**：6h 池化回退层按验证时刻昼夜相位分层重训与 TMax 短时效物理方差衰减缺口评估（状态：`ACTIVATED_W1_PLANNED`，波次一列首，工单全文待下发）。
  - **议题 P6-CALM-OUTLIER**：平静日极端失准事前指纹判别与 Regime 条件模型评估（状态：`REGISTERED`，防删条款绝对维持，独立排期）。
  - **议题 P6-RESEARCH-NO-GATE-BIC**：去门控纯 BIC 竞赛评估机制研究（状态：`REGISTERED`，远期）。
  - **议题 P6-RESEARCH-DIURNAL-PHASE**：按验证时刻昼夜相位分层建模评估（状态：`REGISTERED`，远期，学术成果受 W1 实测反哺）。
  - **议题 P6-TMIN-CV-LOCK**：TMin 480 格交叉验证脚本 hardcode 解锁与审计规划（状态：`REGISTERED`，波次三）。
  - **议题 P7-STA-SURVEY**：Active 8 站轻量三原型机械归类与偏离筛选（状态：`REGISTERED`，波次三，纸面盘期间并行）。
- **为什么处于当前节点**：P6 封卷完成，战略转向落档入册，新会话交接包组装完毕，P7-DOC-RECON 规格对账合流落盘，等待新会话请示 W1（P6-POOL-PHASE）工单全文鸣枪。
- **更新纪律**：每周更新本文件，三行以内说清阶段变化

（最近更新：2026-10-10 17:00）
