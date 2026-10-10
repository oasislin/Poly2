---
created: 2026-09-04 14:07:02
updated: 2026-10-10 00:20:00
---
# 项目状态（唯一状态入口）

---
created: 2026-09-04 14:07:02
updated: 2026-10-10 14:00:00
---
# 项目状态（唯一状态入口）

> 📌 **法定长线规划与新会话交接导航**：项目长线路线图详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)；新会话冷启动交接清单详见 [`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)；封盘门禁总清单详见 [`docs/SEALING_GATE.md`](docs/SEALING_GATE.md)；受控出域同步政策详见 [`docs/SYNC_POLICY.md`](docs/SYNC_POLICY.md)。

> 🚩 **【双重法定运行旗持续生效（下游强制带旗）】**：  
> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（交易窗口加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 未达立项门槛；双城 24 格中 23 格 ECE 达标率 95.83%）；  
> 2. `6h 池化回退层 (80 格)`：状态 `FLAGGED_POOL_PHASE_ISSUE`（晨谷方差膨胀比 1.45~1.81x，KMIA 晨谷 ECE = `0.019657` 越线 0.0100；Max Temp 缺失衰减公式依赖 METAR 实况硬截断兜底）。  
> *下游引用约束*：交易盘口映射、分位数定价与风控链路在调用本格资产时，**必须显式带旗陈述，审慎收缩头寸，严禁脱旗裸跑**！

- **当前阶段**：Phase 7 过渡态（主线战略转向：由横向扩展转向纵向落地）。Phase 6 双城 TMax 24 时间格（96 季节格）验证收口、方法论封盘与池化 6h 审计全量合流入主干 `main`（严格固化于 `6fe386c`，全库测试基线 987 项全绿）。委员会立项会终裁确立三波次长线路线图（详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)）。（修订依据：立项会终裁与工单 P7-TRANSITION-DOC 2026-10-10）
- **活跃工作流**：长线规划入册与新会话交接包组装（工单 `P7-TRANSITION-DOC`）：① 新建长线规划法定文档 [`docs/ROADMAP.md`](docs/ROADMAP.md)；② 升版执行文件至 v6.0（增补 P7 修订章节）；③ 组装冷启动交接包 [`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)；④ 账本同步与 P6-PR-129 尾务核销。（修订依据：委员会令 2026-10-10）
- **冻结产物与专属红线**：`evidence/p4_audit_reliability_v13b_*` 与 `evidence/p6_tmax_methodology_closure.*` 冻结归档；主干 `main` 严格固化于 `6fe386c`，后续任何改动一律须新裁决令；生产代码（`src/` 与 `scripts/`）严格零无授权编辑。（修订依据：P6 终裁与 P7 治理纪律 2026-10-10）
- **待办事项（Backlog 全景）**：
  - **议题 P6-POOL-PHASE**：6h 池化回退层按验证时刻昼夜相位分层重训与 TMax 短时效物理方差衰减缺口评估（状态：`ACTIVATED_W1_PLANNED`，波次一列首，工单全文待下发）。
  - **议题 P6-CALM-OUTLIER**：平静日极端失准事前指纹判别与 Regime 条件模型评估（状态：`REGISTERED`，防删条款绝对维持，独立排期）。
  - **议题 P6-RESEARCH-NO-GATE-BIC**：去门控纯 BIC 竞赛评估机制研究（状态：`REGISTERED`，远期）。
  - **议题 P6-RESEARCH-DIURNAL-PHASE**：按验证时刻昼夜相位分层建模评估（状态：`REGISTERED`，远期，学术成果受 W1 实测反哺）。
  - **议题 P6-TMIN-CV-LOCK**：TMin 480 格交叉验证脚本 hardcode 解锁与审计规划（状态：`REGISTERED`，波次三）。
  - **议题 P7-STA-SURVEY**：Active 8 站轻量三原型机械归类与偏离筛选（状态：`REGISTERED`，波次三，纸面盘期间并行）。
- **为什么处于当前节点**：P6 封卷完成，战略转向落档入册，新会话交接包组装完毕，等待新会话请示 W1（P6-POOL-PHASE）工单全文鸣枪。
- **更新纪律**：每周更新本文件，三行以内说清阶段变化

（最近更新：2026-10-10 14:00）
