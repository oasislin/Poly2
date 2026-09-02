# Spec: NWS WRH 与 IEM METAR 派生日极值口径对比分析与误差标定系统

> **状态**：`Approved-ReadyForImplementation` (对齐 2026-09-02 Grilling 终局决策)  
> **GitHub Spec Issue**：[#40](https://github.com/oasislin/Poly2/issues/40)  
> **关联任务单**：`子任务执行单：NWS WRH 与 IEM METAR 派生日极值口径对比分析.md`

---

## Problem Statement

在针对 Polymarket 温度市场（如上海浦东 ZSPD 站点）构建高精度量化定价模型时，需要 19 年的历史真值日极值标签进行物理统计后处理（EMOS）与回测。然而，历史长序列真值来自 IEM 归档的 METAR 离散报文自行派生，而 Polymarket 结算源则是 NWS WRH 官方展示的实时温度数据。

由于气象报文存在半小时离散采样（丢失温度尖峰）、WMO 国际报文缺乏 24h 极值群码（RMK）、以及 NWS 内部存在华氏度与摄氏度双向转换（$C \to F \to C$）的舍入量化噪声，直接将裸派生数据作为真值标签会导致模型产生虚假的系统性偏差，并在二元期权边界悬崖处导致 SLSQP 优化器过度下注而产生尾部资金回撤。系统急需一个能够自动化抓取对账、解耦实证量化噪声、过滤脏数据、拟合残差分布并向资金管理层输出方差膨胀参数的端到端对账标定系统。

---

## Solution

实现一个基于策略模式（Strategy Pattern）的双轨观测采集与口径标定引擎：
1. **统一采集适配层**：定义抽象观测契约 `BaseObservationAdapter`，实现具备指数退避重试和全元数据持久化的 `NwsWrhAdapter`，并预留 `WundergroundAdapter` 适配插槽。
2. **双向探针逆向算子**：向 NWS API 并行发起 `units=si` 与 `units=english` 请求，实测逆向真实的温度舍入映射函数。
3. **严格时区与日历日切片**：按本地时区（`Asia/Shanghai`）采用 $[00:00:00, 24:00:00)$ 左闭右开标准聚合日极值。
4. **有效日质量控制闸门**：设定报文密度（$N \ge 36$）与日照升温时段覆盖（11:00~16:00 $N \ge 8$）准入规则，剔除残缺数据，缺测率 $>20\%$ 时触发系统级红色警报与非零退出码。
5. **正交代数三偏差分解**：将总偏差严格分解为量化噪声 $\Delta_{\text{quant}}$、真实残差 $\Delta_{\text{res}}$ 与口径错位差 $\Delta_{\text{align}}$。
6. **参数化下游契约导出**：对 $\Delta_{\text{res}}$ 进行高斯矩与经验分位数统计，生成包含尾部方差膨胀建议（$\max(\sigma_{\text{res}}, |p_{01}|, |p_{99}|)$）的 `config/zspd_metar_noise_calibration.json` 供量化核心层消费。
7. **自动化分析与报告**：生成每日对账明细 CSV、直方图/KDE 分布图及 Markdown 分析报告。

---

## User Stories

1. **As a 量化研究员**, I want 能够使用统一的抽象接口采集 NWS WRH 和 IEM 的历史时序数据, so that 我无需关心底层各数据源具体的 API 协议细节和数据结构差异。
2. **As a 量化研究员**, I want 采集器在请求 NWS WRH 时并行发起摄氏度（`si`）与华氏度（`english`）双向请求, so that 我能通过实测数据逆向出 NWS 底层的真实舍入算子，而非依赖未经实证的理论假设。
3. **As a 数据工程师**, I want 采集器具备 3 次指数退避重试机制并将原始 HTTP 响应、时间戳与状态码完整落盘, so that 在上游 API 发生网络波动或抽风时具备高容错性且可追溯排查。
4. **As a 量化研究员**, I want 系统将时间戳严格按 `Asia/Shanghai` 时区以 $[00:00:00, 24:00:00)$ 左闭右开切片, so that 日极值聚合完全符合 Polymarket 官方结算日历日语义，杜绝跨天临界报文重复计算。
5. **As a 气象算法工程师**, I want 解析器能够正则匹配 METAR 报文中的 `1/`（6h）和 `4/`（24h）极值群码并输出覆盖率统计, so that 能够实证验证国际站点是否退化为纯瞬时温度取 Max。
6. **As a 数据质控工程师**, I want 质控模块自动校验单日有效报文数（$N \ge 36$）及午间升温高峰（11:00~16:00 $N \ge 8$）, so that 严重残缺的脏数据能够被标记为 `INCOMPLETE_DATA` 并被剔除出下游分布拟合集。
7. **As a 系统运维工程师**, I want 当评估窗口内缺测日比例超过 20% 时系统自动输出红色警报并返回非零退出码, so that 数据管道断流能在第一时间被拦截与人工介入。
8. **As a 量化研究员**, I want 系统将总误差严格正交分解为量化噪声 $\Delta_{\text{quant}}$ 与采样残差 $\Delta_{\text{res}}$, so that 消除伪误差后剩余的物理漏报残差能得到纯净的统计建模。
9. **As a 投资组合经理 / 风控官**, I want 系统输出包含经验分位数（p01 至 p99）与方差膨胀建议 $\max(\sigma_{\text{res}}, |p_{01}|, |p_{99}|)$ 的标定配置文件, so that SLSQP 优化器在期权边界悬崖处能强制吸收长尾风险，防止过度下注。
10. **As a 量化研究员**, I want 能够通过 CLI 命令指定 `--days 14` 或 `--date-range` 执行增量及全量对账, so that 我可以无缝开展阶段 1（14 天初版）与阶段 2（30 天滚动终版）的分析交付。
11. **As a 团队协作者**, I want 系统自动生成包含直方图/KDE 曲线、极值偏离明细表及参数总结的 Markdown 报告, so that 团队能对 IEM 数据作为真值标签的有效性达成量化共识。

---

## Implementation Decisions

### 1. 架构模式与模块边界
- 采用策略模式。抽象 `BaseObservationAdapter` 基类，实现 `NwsWrhAdapter`，并预留 `WundergroundAdapter` 声明 `raise NotImplementedError`。
- 划分独立的数据获取层（`src/data_acquisition/`）、数据分析与标定层（`src/data_analysis/`）和顶层 CLI 入口（`scripts/`）。

### 2. 接口契约定义
- `BaseObservationAdapter` 必须暴露：
  - `fetch_raw_series(station: str, date: datetime) -> List[ObservationRecord]`
  - `extract_calendar_day_max(records: List[ObservationRecord], timezone: str) -> float`
  - `get_source_precision_metadata() -> dict`

### 3. 数据探针与算子逆向
- 请求参数固定为 `site={station}&units=si` 与 `site={station}&units=english`。
- 提取对应时刻的 $(F_{\text{raw}}, C_{\text{reported}})$ 配对序列，检验 $F_{\text{raw}}$ 是否为纯整数。若为整数，采用 $\text{Quantize}(C) = \frac{\text{round}(C \times 1.8 + 32) - 32}{1.8}$；若包含浮点，动态构建实证离散查找表（Lookup Table）。

### 4. 误差代数分解公式
- $\Delta_{\text{Total}} = T_{\text{NWS\_CalendarDayMax}} - T_{\text{IEM\_RawMax}}$
- $\Delta_{\text{quant}} = \text{Quantize}(T_{\text{IEM\_RawMax}}) - T_{\text{IEM\_RawMax}}$
- $\Delta_{\text{res}} = T_{\text{NWS\_CalendarDayMax}} - \text{Quantize}(T_{\text{IEM\_RawMax}})$
- $\Delta_{\text{align}} = T_{\text{NWS\_24hSummary}} - T_{\text{NWS\_CalendarDayMax}}$

### 5. 标定配置 Schema 规范
- 固化 `config/zspd_metar_noise_calibration.json`，必须包含 `gaussian_params`（均值、方差、偏度、峰度、Shapiro-Wilk p 值）、`empirical_quantiles`（p01, p05, p25, p50, p75, p95, p99）及 `downstream_hint`。

---

## Testing Decisions

### 1. 测试标准与原则
- 遵循黑盒与契约测试原则：只验证模块的外部行为、数据转换与统计代数正确性，不测内部私有实现。
- 外部网络交互必须编写隔离的单元/契约测试（使用真实抓取到的静态 JSON/METAR 样本作为 Fixture），配合真实网络冒烟测试。

### 2. 核心测试覆盖点
- **`TestObservationAdapter`**：测试 NWS API JSON 响应解析、华氏度/摄氏度双向配对提取、重试与异常处理。
- **`TestCalendarDaySlicing`**：测试 `[00:00:00, 24:00:00)` 开闭区间在 `Asia/Shanghai` 时区下的边界归属（例如 00:00 CST 与 24:00 CST 报文不跨天重复）。
- **`TestQualityControl`**：测试有效日准入规则（$N < 36$ 或午间缺测标记为 `INCOMPLETE_DATA`，缺测率 $>20\%$ 告警）。
- **`TestAlgebraicDecomposition`**：测试 $\Delta_{\text{Total}} == \Delta_{\text{quant}} + \Delta_{\text{res}}$ 代数恒等性及量化舍入算子映射正确性。
- **`TestDistributionCalibrator`**：测试统计矩计算、Shapiro-Wilk 检验、经验分位数提取及 JSON 导出格式合法性。

---

## Out of Scope

1. Wunderground 真实网页抓取接入（仅保留抽象接口骨架）；
2. 多站点批量扩展（本次聚焦 ZSPD）；
3. SLSQP 在线交易实时卷积引擎（归属 Phase 2）。

---

## Further Notes

- **两阶段交付安排**：
  - **阶段 1（当前）**：拉取 NWS WRH API 当前可用的最大滚动窗口（14 天），验证完整分析管道，生成初版报告与阶段标定参数；
  - **阶段 2（后续）**：持续每日自动化定时拉取累积至 30 天，更新生成终版全样本标定报告。
