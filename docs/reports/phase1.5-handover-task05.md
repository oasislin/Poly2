# Phase 1.5 Task 05 交接文档：气候方差下限 Floor 重建 (Variance Floor Rebuilding)

> **文档版本**：v1.0  
> **生成时间**：2026-09-17  
> **前置任务状态**：
> - Task 01（基线封存）：`35ecb4b` ✅
> - Task 09（GEFS 因子库 2000–2019）：`8899246` ✅
> - 站点宇宙退役固化（11 活跃站，KDCA 下线）：`1b53879` ✅
> - Task 02（生产级 IEM 适配器）：`cd942d4` ✅
> - Task 03（挂账清零与特报 ADR-0009 裁决）：`0ff9d0e` ✅
> - Task 04（11 站 × 2000–2026 IEM 原报重取与零偏差审计）：`147b32f` ✅
> **下游目标**：Task 05（气候方差下限 Floor 重建）→ Task 06（切片与分层）

---

## 1. 核心背景与任务命题

在 Phase 1 原型中，气候方差下限 $\sigma_{\text{clim}}$ 是基于旧 Wunderground 数据计算的，已被实证存在严重的系统性负偏差与截断误差。
随着 Task 04 成功完成 11 站全量 27 年高精度 IEM ASOS（RMK T-group $0.1^\circ\text{C}$ 精度）原报的本地落盘，**Task 05 的核心任务是重建生产级的 $\sigma_{\text{clim}}$ 方差底座曲线**。

### 核心纪律红线（最高铁律）
1. **严格样本外（OOS）纪律**：
   - 只能消费 **2000–2018 年（19年）** 的 IEM 观测数据。
   - **绝对严禁触碰 2019–2026 年** 的任何数据，防止前瞻偏差（Lookahead Bias）。
2. **严禁擅自修改代码 / Git Push**：
   - 遵循 `AGENTS.md`，方案未获批准不得修改代码，严禁私自 `git push`。
3. **无硬编码魔法数字（No Magic Numbers）**：
   - 所有窗口大小、分位点阈值、物理上下限均以具名常量或配置注入。
4. **单函数 $\le 50$ 行**。

---

## 2. 算法口径与设计要点

根据《项目执行文件 v5.9.2》§5 及《Phase 1.5 执行文件 v1.1》§2 Task 05：

1. **输入数据**：
   - 路径：`data/raw/iem/{station}/{year}.parquet`
   - 站池：全美 11 个活跃交易站点 (`KORD`, `KLGA`, `KATL`, `KDAL`, `KSEA`, `KLAX`, `KHOU`, `KMIA`, `KSFO`, `KBKF`, `KAUS`)
   - 年份范围：`2000 <= year <= 2018`（共 19 年，每个站点 19 个 Parquet 文件）
2. **日极值聚合 (TMAX / TMIN)**：
   - 区分正点报与特殊报（保留 ADR-0009 裁决的完整发报记录）。
   - 聚合每个本地日历日（Local Date）的高精度最高温 $T_{\max}$ 与最低温 $T_{\min}$（单位归一化为华氏度 $^\circ\text{F}$）。
3. **31 天滑动窗气候方差**：
   - 对一年中的每一天 $d \in [1, 366]$：
   - 提取 19 年中处于 $[d-15, d+15]$（以 365/366 周期性环形闭合）的所有历史日极值样本（样本量约 $19 \times 31 \approx 589$ 个）。
   - 计算该窗口内日极值的样本标准差 $\sigma_{\text{raw}}(d)$。
4. **曲线平滑（Smoothing）**：
   - 使用环形周期性平滑滤波器（如高斯滤波或周期性核滑动平滑，窗宽建议 15~31 天），确保 12 月 31 日平滑过渡到 1 月 1 日，无跳变。
   - 获得每日连续平滑方差 $\sigma_{\text{clim}}(d)$。
5. **安全下限与全站保护（Variance Floor）**：
   - 确立方差绝对下限 $\sigma_{\min} = \max(\sigma_{\text{clim}}(d), \text{FLOOR\_ABS\_MIN})$，防止模型预测发散度塌缩导致边缘爆仓。
   - 物理合理性区间校验：确保全站点全日期的 $\sigma$ 落在物理合理区间 $[1.5^\circ\text{F}, 8.0^\circ\text{F}]$。

---

## 3. 产物交付清单要求

1. **模块与脚本**：
   - `src/models/climate_floor.py`（或在现有模块升级重构）
   - `scripts/rebuild_climate_floor.py`（执行 11 站批处理）
2. **配置产物**：
   - `data/processed/climate_floor/` 或 `configs/climate_floor_v2.json`：落盘 11 站逐日 366 天的 $\sigma_{\text{clim}}$ 表。
3. **测试套件**：
   - `tests/unit/models/test_climate_floor.py`：覆盖 OOS 年份隔离校验、周期性平滑无缝校验、物理值域门禁校验。
4. **质检报告**：
   - `docs/reports/phase1.5-task05-climate-floor-report.md`：对比旧 WU 版 Floor vs 新 IEM 版 Floor 的变化，提供可解释性统计图表或表格。
5. **冒烟测试**：
   - 依照硬性规则执行 GEFS 联网冒烟测试：
     `RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`

---

## 4. 下一 Session 快速启动指令

用户在新 Session 中可直接输入以下 Prompt：

```text
我们已经完成了 Phase 1.5 Task 04 并已本地提交（commit 147b32f）。
请读取 docs/reports/phase1.5-handover-task05.md，直接开始推进 Phase 1.5 Task 05：气候方差下限 Floor 重建（Variance Floor Rebuilding）。
请先输出详细的 Implementation Plan 供我审阅，在我确认前严禁编写或修改代码。
```
