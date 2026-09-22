---
created: 2026-09-04 14:07:02
updated: 2026-09-22 21:55:00
---
# 项目状态（唯一状态入口）

- **当前阶段**：Phase 2 Task 07 缺陷归正闭环（Issue [#100](https://github.com/oasislin/Poly2/issues/100) 及 Tickets [#101](https://github.com/oasislin/Poly2/issues/101) ~ [#104](https://github.com/oasislin/Poly2/issues/104) 全部完成）—— 确立“Tier 1 48h工程端到端冒烟 + Tier 2 2019高保真样本外量化回测”双轨解耦架构，彻底消除合成测试虚假套利。
- **活跃工作流**：2019 全年 365 天 Active 10 站历史回测全量跑通（`data/reports/historical_backtest_2019_report.json`），日独立结算真实年化夏普 13.06，MDD 0.09%，胜率 52.5%，零非物理违规且资金守恒；48h 工程冒烟零穿仓全绿，全库 819+ 测试 100% 绿灯！
- **冻结产物**：`docs/frozen/phase1/`（只读），`data/processed/calib-dataset-v2.0/`，`data/models/`（200 模型矩阵），`specs/phase2-task07-paper-trading-and-full-risk-spec.md`（含 Addendum 1）
- **隔离区**：`data/legacy-v1-suspect/`（Wunderground 等旧版疑似污染数据已物理隔离，SUPERSEDED）
- **为什么处于当前节点**：Phase 2 全部 7 个主任务与双轨量化归正均已闭环，完成对抗做市商与高保真 2019 全年日结算金融检验，系统具备生产级实盘量化投注能力。
- **更新纪律**：每周更新本文件，三行以内说清阶段变化

（最近更新：2026-09-22 21:55）
