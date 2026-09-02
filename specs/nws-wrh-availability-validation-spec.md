# Spec: NWS WRH 服务可用性验证与数据源准入规范 (Round 4)

> **版本**：v1.0 (Round 4 Spec)  
> **状态**：Draft / Ready for Tickets  
> **上游依据**：《子任务执行单：NWS WRH 服务可用性验证（Round 4）.md》  
> **核心原则**：**冻结一切建模输出，把已有的 14 天管道转化为"NWS 服务可用性验证"工具，并用探测性实验回答悬而未决的可用性问题。**

---

## 1. 冻结规范 (Freeze & Containment)

### 1.1 标定文件隔离 (`config/zspd_metar_noise_calibration.json`)
- 必须包含字段：`"status": "NOT_FOR_PRODUCTION"` 与 `"frozen": true`；
- 移除所有面向生产决策的 `downstream_hint` 与 `recommended_sigma_inflation`；
- 任何下游模块读取该配置时必须抛出 `RuntimeError("Calibration file is frozen and NOT_FOR_PRODUCTION")`。

### 1.2 报告定位调整 (`docs/reports/zspd_data_availability_report_v0.9.md`)
- 报告标题统一为《NWS WRH 数据可用性验证报告（14 天阶段性）》，版本号降为 `v0.9-provisional`；
- 彻底移除任何面向定价的下游集成建议；
- 残差统计降级为附录说明，标注 $n=12$ 无统计推断力。

---

## 2. 四项可用性探测规范 (Probing Specifications)

### 2.1 探针 1：WRH 留存窗口实测 (Retention Window Boundary)
- **输入参数**：`days_back_list = [7, 14, 30, 60, 90, 365]`
- **请求协议**：分别测试 `units=metric` 与 `units=english`；
- **度量输出**：
  - 各回溯档位的 HTTP 状态码、耗时、返回记录数；
  - 实际返回的最早时间戳 `earliest_returned_timestamp` 与最新时间戳 `latest_returned_timestamp`；
  - 留存窗口真实天数结论（确定批处理可行域）。

### 2.2 探针 2：字段精度审计 (Field Precision Audit & F1 Fix)
- **输入数据**：`data/raw/nws_wrh/` 目录归档的全部原始 JSON Payload；
- **审计规则**：
  - 统计 `air_temp_set_1` 原始浮点数的离散分布；
  - 验证是否存在纯整数摄氏度（如 $28.0$）、一位小数摄氏度（如 $28.3$）或高精小数；
  - 验证英制 `air_temp_set_1` 是否为纯整数华氏度；
  - 消除适配器内部隐式 `round()`，在对账 CSV 中新增 `temp_nws_cal_max_raw_precision` 列。

### 2.3 探针 3：抓取稳定性量化 (Scraping Stability & Uptime Metrics)
- **度量指标**：
  - 成功率：$\text{Success Rate} = \frac{N_{\text{success}}}{N_{\text{total}}}$；
  - 失败分类：超时（Timeout）、401/403 反爬鉴权失败、空响应（Empty）、解析错误（ParseError）；
  - 耗时分布：P50 延迟、P95 延迟；
  - 字段漂移：每次请求响应 key 集合哈希对比，检测新增/缺失字段。
- **输出文件**：`data/processed/nws_wrh_uptime_metrics.csv`，字段：
  `timestamp_utc, station, total_requests, successful_requests, failed_requests, success_rate, latency_p50_sec, latency_p95_sec, failure_breakdown, schema_drift_detected`

### 2.4 探针 4：更新时延与断流分析 (Update Latency & Gap Distribution)
- **度量指标**：
  - 观测时刻至数据在 WRH 上线可抓取的传输时滞；
  - 24 小时各整点（00:00~23:00 CST）有效观测频次直方分布，诊断断流是否存在固定时段聚集。

---

## 3. 产物交付与验收规范

1. **可用性指标数据**：`data/processed/nws_wrh_uptime_metrics.csv`（格式合法且每日追加）；
2. **升级对账明细**：`data/processed/zspd_daily_diff.csv`（包含 `temp_nws_cal_max_raw_precision`）；
3. **可用性主报告**：`docs/reports/zspd_data_availability_report_v0.9.md`（完整回答四大核心问题）；
4. **冻结标定文件**：`config/zspd_metar_noise_calibration.json`（处于隔离保护态）。

---

## 4. 严格禁止项

- ❌ 禁止输出任何参数推荐或 Go/No-Go 评级；
- ❌ 禁止做残差分布拟合、正态检验或分位数外推；
- ❌ 禁止解除标定配置文件的冻结状态。
