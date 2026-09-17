# Phase 1.5 Task 06 交接文档：观测切片、特征重采样与分层语料库构建 (Slicing & Feature Alignment)

> **文档版本**：v1.0  
> **生成时间**：2026-09-17  
> **前置任务状态**：
> - Task 01（基线封存）：`35ecb4b` ✅
> - Task 09（GEFS 因子库 2000–2019）：`8899246` ✅
> - 站点宇宙退役固化（11 活跃站，KDCA 下线）：`1b53879` ✅
> - Task 02（生产级 IEM 适配器）：`cd942d4` ✅
> - Task 03（挂账清零与特报 ADR-0009 裁决）：`0ff9d0e` ✅
> - Task 04（11 站 × 2000–2026 IEM 原报重取与零偏差审计）：`147b32f` ✅
> - Task 05（气候方差下限 Floor 重建与 ADR-0010 治理）：`9c1fdd0` ✅
> **下游目标**：Task 06（切片与分层）→ Task 07（元数据扩展）→ Task 08（数据集正式发布）

---

## 1. 任务背景与核心命题

随着 Task 04（11 站 × 27 年高精度 IEM ASOS 原报本地落盘）与 Task 05（366 日双轨方差底座与 ADR-0010 治理闭环）圆满完成，系统已具备不可动摇的高精观测真值底座。
**Task 06 的核心使命是构建生产级的观测特征库与切片分层语料库（Feature Store v2）**，完成从“原始连续非定频气象报文”到“可用于 EMOS 模型训练与 GEFS 预报严格对齐的规整矩阵”的工程跃迁。

---

## 2. 核心规则与法定契约（最高纪律）

### 2.1 契约一：ADR-0009 D3 条目「真值标签 vs 预报特征」双轨分离（严禁混淆）
- **结算真值标签（Target / Label）**：
  字段名 `tmax_daily_all_reports` / `tmin_daily_all_reports`。必须取包含正点报（METAR）与特报（SPECI）在内的**全量高精观测极值**，确保与 Polymarket 官方结算真值绝对零偏差（0.0000°C 偏差）；
- **抗噪对照与预报匹配特征（Feature）**：
  字段名 `tmax_daily_hourly_only` / `tmin_daily_hourly_only`。仅采信 `:50-:55` 窗口整点报文。

### 2.2 契约二：统一日历轴投影（严禁使用原生 `dt.dayofyear`）
- 必须强制调用 `src.modeling.climate_floor.resolve_day_of_year`，以 **2020 闰年（366天）为绝对标准基准轴**；
- 平年 3 月 1 日强制映射为 Day 61（平年跳过 Day 60），确保与 Task 05 产出的 `climate_floor` 在时序相位上完全咬合（零天相位差）。

### 2.3 契约三：夏令时自适应与本地日切片（DST 23h/25h Adaptive）
- 依照台站 IANA 官方时区（如 `America/Chicago`、`America/New_York`）划分本地日历日；
- 严密兼容每年 3 月夏令时切换日（23 小时）与 11 月冬令时切换日（25 小时），复用 Phase 1 成熟的日切逻辑。

### 2.4 契约四：数据分层标签注入（Vintage & Usage Metadata）
- **2000–2018 年数据段**：物理打标 `vintage=era1, usage=stress-test-only`；
- **2019–2026 年数据段**：物理打标 `vintage=era2, usage=training-ready`。

---

## 3. 产物交付清单要求

1. **核心处理模块与批处理脚本**：
   - `src/data_processing/slicer.py`（或特征工程管道对应模块）
   - `scripts/build_feature_store.py`（全量切片构建脚本，单函数 <= 50 行）
2. **特征库物理落盘产物**：
   - `data/processed/features/{station}/{year}.parquet`（11 站 × 27 年规整特征长表）
   - `data/processed/features/manifest.json`（包含各文件校验和、行数、时区审计元数据）
3. **测试套件**：
   - `tests/unit/pipeline/test_feature_slicer.py`（覆盖夏令时 23h/25h 切片、整点采样精度、ADR-0009 双轨标签比对、DOY 映射守卫）
4. **质检报告**：
   - `docs/reports/phase1.5-task06-feature-slice-report.md`
5. **GEFS 真实网络冒烟测试**：
   - `RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`

---

## 4. 下一 Session 快速启动指令

用户在新 Session 中可直接输入以下指令推进：

```text
我们已经完成了 Phase 1.5 Task 05 并已本地提交（commit 9c1fdd0）。
请读取 docs/reports/phase1.5-handover-task06.md，直接开始推进 Phase 1.5 Task 06：切片与分层（特征库重建、:50-:55 整点重采样、DST 自适应与 ADR-0009 双轨支持）。
请先输出详细的 Implementation Plan 供我审阅，在我明确确认前严禁编写或修改代码。
```
