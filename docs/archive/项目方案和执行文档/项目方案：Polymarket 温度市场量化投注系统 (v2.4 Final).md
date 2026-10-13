---
created: 2026-09-01 17:30:00
updated: 2026-09-01 17:30:00
---

# 项目方案：Polymarket 温度市场量化投注系统 (v2.4 Final)

（对齐执行文件 v5.9.2：高斯 EMOS、5 成员集合、气候学基准、三重验收；§6 三项待确认项全部代码核验闭环）

## 0. 变更日志（Changelog）

|版本|日期|变更内容|
|---|---|---|
|v2.2|2026-08-11|初版：Wunderground 为真值，偏态 EMOS，四项验收指标|
|v2.3|2026-08-20|四处推翻级对齐（高斯 EMOS / 5 成员 / 气候学基准 / 三重验收）；新增 §6 三项 Pending 待确认区|
|**v2.4**|2026-08-20|**§6 三项 Pending 全部经代码核验闭环并回填正文：① 物理硬约束层独立保留（constraint_enforcer.py）；② 实况数据源为参数依赖注入，Phase 2 采用 METAR/Wunderground 双轨解耦；③ 触发范式为混合制（Phase 1 按需同步 / Phase 2 双事件驱动 + 双重防抖）。新增告警-降级事件契约、单位归一化强制关卡等 11 项观察点落位。Pending 区清空归档**|

> **⚠️ 参数复用警告**（延续 v2.3）：v2.2 时代已训练的偏态模型或 31 成员方差参数全部作废，严禁迁移至 v5.9.2 管道。

## 1. 项目目的与战略定位

**核心目标**：构建针对 Polymarket 温度市场的**连续概率预测系统**，输出最高温与最低温的概率分布，用于投注决策。

**战略分阶段原则**：

- **Phase 1（当前）**：高精度物理概率模型，Wunderground 历史数据为真值，不考虑盘口与资金管理。
- **Phase 2（后续）**：Phase 1 验收后引入盘口流动性、滑点控制与资金管理（详见《Phase 2 执行文件 v1.2 Engineering-Spec》）。

## 2. 模块一：数据架构

### 2.1 观测数据（真值与历史统计）

- **数据源**：Wunderground 历史页面（真值标签、气候学 Floor 唯一口径、回测结算标签）。
- **获取工具**：`requests` + `BeautifulSoup`，解析 “Day High” / “Day Low”。

### 2.2 预报数据（特征源）

- **数据源**：GEFS，**仅 5 成员 c00+p01-p04，11/31 成员一律忽略**；特征收敛为 $\bar{T}_{ens}$ 与 $S_{ens}$。
- **日极值窗口**：6h 窗口，完全包含 ⊆ 本地日，弃 3h。
- **获取工具**：Herbie + `xarray`/`cfgrib`；`xr.merge`/`xr.concat` 必须声明 `compat='override', coords='minimal'`。

### 2.3 实时数据（实战用）

- **[v2.4 闭环]** Phase 1 采用**参数依赖注入**（`current_temp` / `observation_time` 经 API/CLI 显式传入，回测可确定性重放）；Phase 2 接入 **METAR 分钟级实时流（高频截断）+ Wunderground（次日权威结算）双轨解耦**。
- **站点对齐**：中央字典 `STATION_METADATA`（`constants.py`）统一 ZSPD/KDEN 的经纬度、高程、时区、单位与 Polymarket ID。
- **脏数据清洗**：`DataValidator` 强制物理边界 $[-60^\circ\text{C}, +60^\circ\text{C}]$ 拦截。**[v2.4 新增强制关卡]** 所有观测值进入边界检查前，必须先经 `STATION_METADATA` 单位字段归一化为摄氏（防止丹佛华氏输入被误拦截或漏拦截）；配单测 `test_fahrenheit_input_normalized_before_physical_check`（Phase 2 Milestone 2.1 阻塞项）。

## 3. 模块二：动态概率预测模型（三层架构，均已代码核验）

### 3.1 第一层：静态基础模型（高斯 EMOS）

- 均值 $\mu = a + b \cdot \bar{T}_{ens}$；方差（平方参数化）$\sigma^2 = c^2 + d^2 S_{ens}^2 + \sigma_{clim}^2(d)$。
- 气候学 Floor：仅站点实测、2000-2018 严格 OOS、31 天窗 × 19 年逐日平滑。
- 40 组参数（20 模型/站 × 2 站）；TMAX 节点 $\{6h, 30h, 54h\}$，TMIN 节点 $\{24h, 48h\}$；仅 00Z 起报，`round_to_nearest_6h` 归桶。
- 训练：CRPS 闭式解 + L-BFGS-B；L2 仅对 $d$（$\lambda = 10^{-3}$）；热启动 $(0,1,0,1)$ + 扰动。
- 降级：硬触发（未收敛 / NaN/Inf）→ Level 2 气候学；软触发（CRPS 劣于气候学 $p < 0.05$）；$\|c\|, \|d\| > 10$ 仅告警。

### 3.2 第二层：动态修正层（动态截断层）

- 截断修正：TMAX $P(X \ge L \mid X > T_{now})$；TMIN $P(X \le L \mid X < T_{now})$。
- 插值/外推：TMAX 内插节点 $\{12, 18, 24, 36, 42, 48\}$；TMIN < 24h 借用 24h 参数 + $\sigma \sqrt{L/24}$ 衰减；极短时效截断层接管主导权。
- **缺测容灾**：$T_{now}$ 为 None/NaN 时透明回退静态先验（`is_truncated=False`）。**[v2.4 新增]** 该回退必须配对上报 `WARNING` 级事件（区别于 ERROR 级陈旧告警），禁止静默降级。
- **[v2.4 闭环] 触发范式（混合制）**：
    - **Phase 1**：CLI/API 按需同步触发，无常驻调度器（截断计算 <1ms，纯内存闭式运算）。
    - **Phase 2**：METAR 观测事件 + 盘口推送事件双驱动；节流采用**或逻辑双重防抖**——$|T_{new} - T_{prev}| \ge 0.1^\circ\text{C}$ **或** $\Delta t \ge 60\text{s}$。**周期刷新（60s）具有真实计算意义**：`ConstraintEnforcer` 的可达区间随 $\Delta t$ 收缩，即使气温不变也须重算，严禁以“气温没变”为由裁剪周期触发。
    - **[v2.4 强制规范]** 告警层冷却（MD5 语义指纹，3600s）与计算触发节流（$\Delta T / \Delta t$ 双重防抖）为**两套独立机制，严禁复用**——告警节流防刷屏，计算节流省算力，语义不同，混用将导致极短时效窗口截断严重滞后。
    - 配置两态：`min_reprice_edge` 基线 0.03 / 数据陈旧降级态 0.05，联动固化，不得静态单值。
    - `configs/default.yaml` 预留 `trigger:` 区块骨架（Phase 2 schema 锚点）。

### 3.3 第三层：物理硬约束（独立保留）

- **[v2.4 闭环]** **独立顶级组件** `ConstraintEnforcer`（`src/prediction/constraint_enforcer.py`），架构与 StaticPredictor / DynamicCorrector / BinConverter 平级，位于预测栈第 3 层（先验 → 截断 → **物理硬拦截** → 档位转换），对前序输出具绝对覆盖优先级。
- **机理**：计算距名义极值时刻（TMAX 15:00 / TMIN 06:00 LT）剩余时间 $\Delta t = \max(0, t_{peak} - t_{now})$；基于站点季节历史升/降温速率计算物理可达区间 $[T_{now} - r_{cool}\Delta t, \, T_{now} + r_{warm}\Delta t]$；超限档位硬拦截（概率强制 0.0）；CDF 全域单调不减。
- **速率口径**：基于站点季节历史速率的 **99.9% 分位数**（工程化准最大值，v2.2 的“绝对最大”表述据此修正）；配置层保留强制覆盖开关，允许人工注入绝对极值。
- **边界语义**：$\Delta t = 0$（越过名义极值时刻）时可达区间坍缩为闭区间单点，**属设计决策而非缺陷**；固化单测 `test_deltat_zero_after_peak_collapse` 防止误“修复”。
- **缺测容灾**：实况缺测时标记 `is_constrained=False` 优雅回退，不阻断预测。
- **Phase 2 兼容性**（转 backlog）：概率硬置 0 的档位流入凯利 SLSQP 时，$p_i$ 必须保持在乘法侧为零的写法（严禁预计算 $\ln p_i$）；$p_{model} \ge 0.995$ 的确定性档位施加额外下注上限。

## 4. 模块三：验证引擎（三重验收）

### 4.1 交付物标准

预测结果文件（时间、站点、PDF 参数、Wunderground 真值）+ 分 TMAX/TMIN 的统计校准报告。

### 4.2 三重验收指标

**① 标准节点**：CRPS；PIT K-S 检验 $p > 0.05$；**$\text{CRPS}_{model} < \text{CRPS}_{clim}$（门禁级）**。  
**② 插值节点（留出节点法）**：30h 留出，6h & 54h 重建；双断言：$\text{CRPS}_{virtual} \le 1.05 \times \text{CRPS}_{real}$ 且 PIT K-S $p > 0.05$。  
**③ 极端压力测试**：阈值取 2000-2018 的 90th/10th 分位；样本仅取 2019 超阈值部分；双底线：$\text{CRPS}_{model} < \text{CRPS}_{clim}$ 且 90% CI 覆盖率 $\ge 80\%$。

### 4.3 废弃声明

- **MPIW**：废弃。**Talagrand 图**：废弃，职能由“PIT K-S + 覆盖率断言”替代，验收脚本不得实现。

**判定规则**：三重验收全部通过，方允许启动 Phase 2 资金投入。

## 5. 数据源故障联动与告警契约

- **陈旧监控**：`check_data_staleness()` 阈值**固化 3.0h**（代码默认 6.0h 须改配置覆盖）。
- **[v2.4 新增] 告警-降级事件契约**：`DATA_STALENESS`（ERROR 级）是 Phase 2 降级状态机的**唯一触发信号源**，双方经固定事件契约耦合——触发后：动态截断层停用、Effective $\sigma \times 1.3$、EV 门槛 0.03 → 0.05。
- **降级加权参考**：截断层缺测回退的 `WARNING` 级事件（§3.2）作为 Phase 2 降级加权的辅助信号。
- **[v2.4 新增] 结算前口径切换**（Phase 2 backlog）：进入名义极值时刻前 2h 窗口，截断层输入源由 METAR 切换为 Wunderground 实况，消除仪器口径差在档位边界附近的翻转风险。

## 6. ~~待确认项~~ → 已归档核验记录

> 三项 Pending 已全部经代码核验闭环并回填正文（§2.3 / §3.2 / §3.3 / §5），本区转为核验档案：

|#|结论|代码位置|观察点去向|
|---|---|---|---|
|1|物理硬约束层：独立保留|`src/prediction/constraint_enforcer.py`|速率口径→§3.3；Δt=0 单测→Phase 1 单测清单；凯利兼容→Phase 2 backlog|
|2|实况源：参数依赖注入，Phase 2 METAR/Wunderground 双轨|`dynamic_corrector.py` / `constants.py`|单位归一化→**Phase 2 M2.1 阻塞项**；阈值固化+事件契约→§5；口径切换→backlog；回退告警→§3.2|
|3|触发范式：混合制（按需同步 / 双事件驱动）|`run_predictions.py` / `main_pipeline.py`|或逻辑防抖+冷却器隔离+两态 edge→§3.2；配置骨架→default.yaml|

## 7. 实施路线图（Phase 1 剩余项）

- **Step 1.5（新增）**：固化 3.0h 陈旧阈值配置；实现缺测回退 WARNING 配对；补 `test_deltat_zero_after_peak_collapse` 单测；`default.yaml` 预留 `trigger:` 骨架。

**v2.4 定稿声明**：本文档与执行文件 v5.9.2、Phase 2 执行文件 v1.2 Engineering-Spec 三位一体，文档-代码口径完全对齐，无 Pending 项。可交付编程 Agent 进入 Phase 1 收尾（Step 1.5）与 Phase 2 脚手架开发。
