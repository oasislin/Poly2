# Phase 2 开工前准备：交接文档（Step 1 双源切换窗阈值裁决）

> **文档版本**：v1.0  
> **生成时间**：2026-09-19  
> **前置任务状态**：
> - Phase 1.5 全部结项：Commit `73d24cd`，Tag `phase1.5-final` ✅
> - `calib-dataset-v2.0` 正式发布：528 文件，六重大门全部 PASS ✅
> - Active 11 活跃交易站宇宙固化（KDCA 彻底下线）✅
> **下游目标**：推进《项目方案 (v2.6)》§8.1 三项开工前 ADR 裁决之 **Step 1：双源切换窗阈值裁决**

---

## 1. 任务背景与核心使命

根据《项目方案 (v2.6)》§8.1 / §8.2，Phase 2 盘口定价与执行引擎开工前，必须完成三项阻塞级 ADR 裁决。
**当前第一步：双源切换窗阈值裁决**：
1. **历史冲突**：在 Phase 1（v1.3 方案）中，系统设定在名义极值时刻前 2h，将截断层输入由常规 METAR 切换至实况页（原为 Wunderground），陈旧超时阈值设为 0.75h（常规时段为 3.0h）；
2. **重铸后现状**：ADR-0007 已彻底废除 Wunderground，确立 IEM ASOS 与 NWS WRH 双源体系。WRH 与 IEM METAR 更新节奏存在差异，0.75h 的切换时序与判定阈值需要结合 Phase 1.5 留存的实测告警数据（`data/reports/dual_source_discrepancies.jsonl` 与 `data/processed/nws_wrh_uptime_metrics.csv`）进行裁决；
3. **核心任务**：
   - 审读双源时延、更新频率与历史偏差样本；
   - 裁决名义极值前切换窗口的具体触发时机、切换后的首选源与降级回退策略；
   - 裁决 `check_data_staleness()` 在切换窗口内的精确超时阈值；
   - 形成正式 ADR 决策文档（按仓库现有序列顺延领号，如 `ADR-0011`）。

---

## 2. 需重点读取的上下文与证据文件

1. **项目方案与执行规范**：
   - `docs/项目方案和执行文档/项目方案 (v2.6)：Polymarket 温度市场量化投注系统.md`（重点关注 §5、§8.1、§8.2）
   - `docs/项目方案和执行文档/Phase 2 执行文件 v1.3：盘口定价、套利与执行引擎.md`（重点关注截断层与数据获取时序）
2. **实测数据与历史档案**：
   - `data/reports/dual_source_discrepancies.jsonl`（IEM 与 WRH 实测极值差异留存记录）
   - `data/processed/nws_wrh_uptime_metrics.csv`（WRH 真实可用性与更新延迟指标）
   - `STATUS.md`（项目唯一状态入口）

---

## 3. 新 Session 快速启动指令

在新窗口中，请直接复制以下文本发送给 Agent：

```text
我们已经圆满完成 Phase 1.5 全部任务并发布了生产级数据集 calib-dataset-v2.0（Commit: 73d24cd，Tag: phase1.5-final）。
请读取 docs/reports/phase2-handover-adr-threshold.md，正式开始推进 Phase 2 开工前准备的三项 ADR 裁决之 Step 1：双源切换窗阈值裁决。

请严格遵从项目核心纪律：
1. 先输出详细的分析方案与 ADR 提案草案供我审阅讨论，在我明确确认前严禁编写或修改任何代码；
2. 严格基于 Active 11 活跃交易站点宇宙（KDCA 已彻底退役下线，严禁引入）；
3. 严格遵循六要素受控词表，严禁自由发挥非受控词汇；
4. 若涉及任何测试，必须维持每步真实网络冒烟绿灯：RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q。
```
