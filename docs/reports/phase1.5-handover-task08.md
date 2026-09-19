# Phase 1.5 Task 08 交接文档：校准数据集发布与 Phase 1.5 终审闭环 (Dataset Release & Final Acceptance)

> **文档版本**：v1.0  
> **生成时间**：2026-09-19  
> **前置任务状态**：
> - Task 01（基线封存）：`35ecb4b` ✅
> - Task 09（GEFS 因子库 2000–2019）：`8899246` ✅
> - 站点宇宙退役固化（11 活跃站，KDCA 下线）：`1b53879` ✅
> - Task 02（生产级 IEM 适配器）：`cd942d4` ✅
> - Task 03（挂账清零与特报 ADR-0009 裁决）：`0ff9d0e` ✅
> - Task 04（11 站 × 2000–2026 IEM 原报重取与零偏差审计）：`147b32f` ✅
> - Task 05（气候方差下限 Floor 重建与 ADR-0010 治理）：`9c1fdd0` ✅
> - Task 06（切片分层与特征库 v2 重建）：`297/297` 分区落盘 ✅
> - Task 07（元数据扩展与单点归一化）：`4a8a38e` ✅
> **下游目标**：Task 08（`calib-dataset-v2.0` 正式发布与 Phase 1.5 终审闭环）→ Phase 2 启动准备（§8.1 三项 ADR 裁决）

---

## 1. 任务背景与核心使命

随着 Task 07（元数据治理与单点摄氏度归一化）以 628 项单测全绿及真实网络冒烟通过并顺利合并入远端 `main`，系统已完成底层数据管道与特征矩阵的彻底重铸。
**Task 08 是 Phase 1.5 的收官终审任务，核心使命是组装发布正式生产级数据集 `calib-dataset-v2.0` 并闭环全部门禁**：
1. **数据集正式打包与 Manifest 固化**：汇流观测真值特征库（Task 06，11 站 × 27 年 = 107,251 站-日）、气候学方差底座（Task 05，366 日双轨 Floor）与 GEFS 集合预报因子表（Task 09，11 站 × 20 年 × 12 段），固化包含 SHA256 校验和与元数据四元组的权威发布包清单；
2. **六重验收大门全面检验（§4 全部验收标准）**：
   - 精度关：抽样 20 个站-日比对 IEM 原报 T 组，执行零偏差人工/自动抽验；
   - 门禁关：全站日级 T 组覆盖率 ≥99% 与双源一致性校验；
   - 覆盖关：11 活跃站 2000–2026 覆盖率 100% 具备实测证据；
   - OOS 纪律关：严格检验 Floor 与训练集截止于 2018，2019+ 验证集纯净；
   - 台账关：PENDING-01~08 全部关闭或显式挂接 Phase 2 验收点；
   - 预报特征关：GEFS 因子表 V1~V13 逐项零违规确认；
3. **交付终审报告与阶段切换**：产出 `phase1.5-task08-dataset-release-report.md`，打上阶段完成 Git Tag，更新 `STATUS.md`。

---

## 2. 产物交付清单要求

1. **数据集发布包**：
   - `data/processed/calib-dataset-v2.0/`（或符号链接/打包目录）
   - `data/processed/calib-dataset-v2.0/manifest.json`（全量文件 SHA256 与四元组清单）
2. **发布与抽检脚本**：
   - `scripts/publish_calibration_dataset.py`（自动化发布与校验脚本）
3. **质检终审报告**：
   - `docs/reports/phase1.5-task08-dataset-release-report.md`（包含六重大门验收证据与 20 样本抽检明细）
4. **GEFS 真实网络冒烟测试**：
   - `RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`
5. **项目状态更新**：
   - `STATUS.md`（更新为 Phase 1.5 全部结项，准备进入 Phase 2 开工前裁决）

---

## 3. 下一 Session 快速启动指令

用户在新 Session 中可直接复制以下文本发送给 Agent：

```text
我们已经完成了 Phase 1.5 Task 07 并已同步至 GitHub（Commit: 4a8a38e）。
请读取 docs/reports/phase1.5-handover-task08.md，直接开始推进 Phase 1.5 收官任务 Task 08：校准数据集发布与 Phase 1.5 终审闭环。
请遵循硬性铁律：
1. 先输出详细的 Implementation Plan 供我审阅，在我明确确认前严禁编写或修改任何代码；
2. 严格基于 Active 11 活跃交易站点宇宙（KDCA 彻底下线）；
3. 严格遵循六要素受控词表，严禁自由发挥非受控词汇。
```
