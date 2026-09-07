---
created: 2026-09-02 13:41:46
updated: 2026-09-02 14:06:00
version: v2.0-GrillingFinal
status: Approved-ReadyForImplementation
---

# 📋 子任务执行单：NWS WRH 与 IEM METAR 派生日极值口径对比分析 (v2.0 终局拍板版)

## 1. 任务背景与核心目的
当前量化模型针对 Polymarket 温度市场采用“双轨独立训练”策略。针对 NWS 结算市场（如上海 ZSPD），计划使用从 Iowa Environmental Mesonet (IEM) 下载的历史 METAR 报文**自行派生日历日最高温**作为长序列模型真值标签。

### 1.1 Polymarket 官方结算规则前置事实
Polymarket 在 ZSPD 站点存在按批次切换的双结算源特性，且规则文字存在结构性约束：
1. **Wunderground 市场**：规则明确指定取 Weather Underground "Daily Observations" 表中的**逐条时序最高温**，而非其 'Day High' 汇总字段。
2. **NWS WRH 市场**：规则明确指定取 `weather.gov/wrh/timeseries` 页面该日所有时次 **'Temp' 列的最高温**（即本地日历日逐条时序 Max，而非滚动的 24 Hour High 字段）。

### 1.2 核心目的
在投入 19 年全量训练前，必须实证检验 IEM METAR 派生日极值与 NWS WRH 官方展示值的数学口径一致性，将总偏差严格解耦为**量化噪声（$C \to F \to C$ 舍入）**与**残差（离散采样漏报/传输差异）**，并向量化核心层（SLSQP / 凯利公式）输出参数化的误差分布画像与方差膨胀建议。

---

## 2. 目标站点、时间范围与报告节奏
- **测试站点**：ZSPD（上海浦东国际机场，时区 `Asia/Shanghai`）
- **数据回溯与对账节奏**：
  - **长期训练底座**：直接使用 IEM 提供的 ZSPD 历年（2001 年至今）METAR 归档。
  - **阶段 1（初版报告）**：利用 NWS WRH API 当前可获取的最近 14 天滚动数据，快速闭环对账算法、逆向舍入算子并出具初版报告。
  - **阶段 2（终版报告）**：通过每日定时抓取持续累积满 30 天样本，出具终版标定报告与长效校准参数。

---

## 3. 架构设计与数据获取规格 (Strategy Pattern)

### 3.1 采集适配器抽象契约 (`BaseObservationAdapter`)
在 `src/data_acquisition/` 中定义统一观测基类，预留双轨插槽：
- `fetch_raw_series(station: str, date: datetime) -> List[ObservationRecord]`
- `extract_calendar_day_max(records: List[ObservationRecord], timezone: str) -> float`
- `get_source_precision_metadata() -> dict`

> **实施边界**：本次核心完整实现 `NwsWrhAdapter`。`WundergroundAdapter` 仅预留类定义并声明 `raise NotImplementedError`。

### 3.2 NWS WRH 双向探针抓取策略 (Dual-Unit Probe)
- **探针请求**：向 NWS WRH API 并行发起 `units=si` 与 `units=english` 两个请求。
- **实证逆向**：对比 $F_{raw}$ 与 $C_{reported}$，反向绘制 NWS 后端真实的 `round()` 算子。若发现 $F_{raw}$ 含小数，则立即停用理论公式，转为直接使用实测映射表。
- **健壮性保障**：支持 3 次指数退避重试；原始响应连同请求时间戳、HTTP 状态码完整落盘至 `data/raw/nws_wrh/{date}.json`。

### 3.3 IEM METAR 报文获取
- 抓取接口：IEM Mesonet (`network=CN__ASOS`, `station=ZSPD`) 原始报文与解析字段。

---

## 4. 数据清洗、日历日切片与极值派生算法

### 4.1 日历日切片与临界报文归属
- 转换所有时间戳至 `Asia/Shanghai` 时区。
- **切片区间**：严格采用 **$[00:00:00, 24:00:00)$ 左闭右开** 标准（Pandas 时区过滤显式声明 `inclusive='left'`），杜绝临界报文跨天双计。

### 4.2 极值派生策略
- **策略 A（瞬时温度逐条 Max）**：提取日历日内所有有效 METAR 干球温度，取最大值 $T_{\text{IEM\_RawMax}}$。
- **策略 B（极值群码解析）**：代码中实现完整的 WMO/ASOS 极值群组正则解析器（`1snTxTxTx` 6h 极值、`4sn...` 24h 极值）。如实统计并输出 ZSPD 的覆盖率（预期 0%），作为策略 B 退化为策略 A 的实证。

### 4.3 有效日准入与质量防御闸门 (Valid Day QC)
进入误差分布拟合与下游标定的样本日必须同时满足：
1. 单日有效观测报文数 $N_{\text{obs}} \ge 36$（全天覆盖率 $\ge 75\%$）；
2. 完整覆盖午间日照升温时段（11:00 至 16:00 CST 之间至少 8 次有效记录）。
- **未达标处理**：在明细中标记 `status = "INCOMPLETE_DATA"`，**剔除出误差分布拟合集**。
- **系统断流红线告警**：若评估窗口内 `INCOMPLETE_DATA` 天数比例 $>20\%$，分析脚本在报告头部输出**红色警报**，并返回**非零退出码**。

---

## 5. 偏差代数分解与统计建模

### 5.1 三类偏差正交分解
总偏差严格按代数分解：
$$\Delta_{\text{Total}} = T_{\text{NWS\_CalendarDayMax}} - T_{\text{IEM\_RawMax}} = \Delta_{\text{quant}} + \Delta_{\text{res}}$$

1. **量化噪声（可完全公式解析）**：
   $$\Delta_{\text{quant}} = \text{Quantize}_{C \to F \to C}(T_{\text{IEM\_RawMax}}) - T_{\text{IEM\_RawMax}}$$
   其中 $\text{Quantize}_{C \to F \to C}(C) = \frac{\text{round}(C \times 1.8 + 32) - 32}{1.8}$（或实测映射表）。
2. **真实残差（离散采样漏报 + 传输残差，拟合输入）**：
   $$\Delta_{\text{res}} = T_{\text{NWS\_CalendarDayMax}} - \text{Quantize}_{C \to F \to C}(T_{\text{IEM\_RawMax}})$$
3. **官方口径错位差（独立对照组）**：
   $$\Delta_{\text{align}} = T_{\text{NWS\_24hSummary}} - T_{\text{NWS\_CalendarDayMax}}$$

### 5.2 统计画像与正态性检验
对有效日序列的 $\Delta_{\text{res}}$ 进行分布拟合：
- 均值 $\mu_{\text{res}}$、方差 $\sigma_{\text{res}}^2$、偏度（Skewness）、峰度（Kurtosis）；
- Shapiro-Wilk 正态性检验（输出 p-value）；
- 经验分位数：$p_{01}, p_{05}, p_{25}, p_{50}, p_{75}, p_{95}, p_{99}$。

---

## 6. 下游量化核心层接口契约 (`config/zspd_metar_noise_calibration.json`)

下游 SLSQP 优化器与凯利资金管理模块通过读取该配置实现误差卷积：
$$\sigma_{\text{eff}} = \sqrt{\sigma_{\text{model}}^2 + \sigma_{\text{inflation}}^2}$$

**JSON Schema 规范**：
```json
{
  "station_id": "ZSPD",
  "data_source_pair": "IEM_METAR_vs_NWS_WRH",
  "sample_days_total": 14,
  "sample_days_valid": 14,
  "incomplete_ratio": 0.0,
  "calibration_window": {
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  },
  "empirical_rounding_operator": {
    "is_pure_integer_fahrenheit": true,
    "quantization_variance": 0.0081
  },
  "gaussian_params": {
    "mu_res": 0.0,
    "sigma_res": 0.0,
    "skewness": 0.0,
    "kurtosis": 3.0,
    "shapiro_wilk_p": 1.0
  },
  "empirical_quantiles": {
    "p01": 0.0,
    "p05": 0.0,
    "p25": 0.0,
    "p50": 0.0,
    "p75": 0.0,
    "p95": 0.0,
    "p99": 0.0
  },
  "downstream_hint": {
    "recommended_sigma_inflation": 0.0,
    "tail_risk_formula": "max(sigma_res, abs(p01), abs(p99))",
    "requires_non_gaussian_tail_hedge": false
  },
  "updated_at": "ISO-8601-Timestamp"
}
```

---

## 7. 工程组织与交付物清单

### 7.1 代码与脚本目录
- `src/data_acquisition/nws_wrh_collector.py`：含 `BaseObservationAdapter`、`NwsWrhAdapter`（带重试/双向探针/落盘）。
- `src/data_analysis/metar_wrh_comparator.py`：IEM 解析、时间切片、三类偏差分解、正态/分位数拟合、图表与 JSON 生成。
- `scripts/run_zspd_comparison.py`：CLI 入口（支持 `--date-range`、`--days 14`、`--plot` 等参数）。

### 7.2 数据与分析交付物
1. `data/raw/nws_wrh/*.json`：NWS WRH 原始 API 响应及请求元数据。
2. `data/processed/zspd_daily_diff.csv`：每日对账明细表，字段严格为：
   `date, temp_nws_summary, temp_nws_cal_max, temp_iem_raw_max, temp_iem_quant_sim, delta_align, delta_quant, delta_res, status`
3. `config/zspd_metar_noise_calibration.json`：下游消费的标准误差分布配置文件。
4. `docs/reports/zspd_temperature_comparison_report.md`：包含群码覆盖率、实测舍入算子验证、偏差分解直方图/KDE、极值偏离明细及量化建议的 Markdown 报告。
