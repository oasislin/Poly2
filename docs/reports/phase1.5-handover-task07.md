# Phase 1.5 Task 07 交接文档：元数据扩展与单点摄氏度归一化 (Metadata Expansion & Ingestion Normalization)

> **文档版本**：v1.0  
> **生成时间**：2026-09-18  
> **前置任务状态**：
> - Task 01（基线封存）：`35ecb4b` ✅
> - Task 09（GEFS 因子库 2000–2019）：`8899246` ✅
> - 站点宇宙退役固化（11 活跃站，KDCA 下线）：`1b53879` ✅
> - Task 02（生产级 IEM 适配器）：`cd942d4` ✅
> - Task 03（挂账清零与特报 ADR-0009 裁决）：`0ff9d0e` ✅
> - Task 04（11 站 × 2000–2026 IEM 原报重取与零偏差审计）：`147b32f` ✅
> - Task 05（气候方差下限 Floor 重建与 ADR-0010 治理）：`9c1fdd0` ✅
> - Task 06（切片分层与特征库 v2 重建）：`297/297` 分区落盘 ✅
> **下游目标**：Task 07（元数据扩展）→ Task 08（数据集正式发布）

---

## 1. 任务背景与核心命题

随着 Task 06 生产级特征库（Feature Store v2，11 站 × 27 年 = 107,251 站-日）顺利落盘与闭环，系统已构建起完整的真值与特征矩阵。
**Task 07 的核心使命是扩展台站元数据中央字典（`STATION_METADATA`）与固化采集入口单点 ℉→℃ 归一化关卡**：
1. 完善 12 站美国站池（11 交易站 + KDCA 观察站）的六要素元数据定义（经纬度、高程、时区、单位、发报特性与网络标签）；
2. 确保所有外部数据源在采集入口执行单点 ℉→℃ 归一化，使得后续管道内部全程以摄氏度运行，杜绝物理越界校验被误触发或漏触发；
3. 扩展并强化单元测试集，保障全局元数据契约不可篡改。

---

## 2. 产物交付清单要求

1. **中央元数据模块升级**：
   - `src/data_processing/constants.py`（升级至 v2，六要素属性全量齐备）
2. **测试套件扩展**：
   - `tests/unit/data_processing/test_unit_converter.py`（单点归一化扩展测试）
   - `tests/unit/data_processing/test_constants.py`（或元数据契约测试，验证 12 站六要素完整性）
3. **质检报告**：
   - `docs/reports/phase1.5-task07-metadata-expansion-report.md`
4. **GEFS 真实网络冒烟测试**：
   - `RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`

---

## 3. 下一 Session 快速启动指令

用户在新 Session 中可直接输入以下指令推进：

```text
我们已经完成了 Phase 1.5 Task 06。
请读取 docs/reports/phase1.5-handover-task07.md，直接开始推进 Phase 1.5 Task 07：元数据扩展与单点摄氏度归一化。
请先输出详细的 Implementation Plan 供我审阅，在我明确确认前严禁编写或修改代码。
```
