# Phase 2 波次三 (W3) 真实盘口观测期启动台账与检查单 (Checklist)

> **工单编号**：`P7-W3-TASK3-AUTH-001`（位次 4/4 · 离线拟合框架与观测期移交放行令）  
> **规格依据**：[`docs/w3_polymarket_ingestion_preregistration.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/w3_polymarket_ingestion_preregistration.md) Rev.1.1 & Annex A 终版  
> **登记状态**：**正式登记启动 · 观测期移交就绪**  
> **登记时刻**：**`2026-10-11 15:30:00 UTC`** (当地时间 **`2026-10-11 23:30:00+08:00`**)  
> **执纪红线**：E-1 ~ E-5 全面生效（零资金变动、零私钥、只读 API、真实证据链、自创决策零容忍）。

---

## 一、 观测期启动检查单逐项执行与核验证据

| 检查项编号 | 检查内容 | 检验方法与判定阈值 | 执行实测结果 | 结论 |
| :---: | :--- | :--- | :--- | :---: |
| **CHK-01** | **cron 定时批处理调度架构** | 必须为单次无状态批处理，严禁常驻监控守护进程（判据 A-5） | 脚本 `scripts/run_w3_clob_snapshot_batch.py` 实测单次运行退出码 0，耗时 33.7s，内存自动释放 | **通过** |
| **CHK-02** | **双层采样频率配置自洽性** | 基准层 60m（A-1）+ 结算探测层 15m（A-2），T-0 为合约官方结算时间（A-3） | `calculate_snapshot_cadence` 经单元测试覆盖全部窗口，支持 `--layer BASELINE` 与 `--layer PROBE` 独立调用 | **通过** |
| **CHK-03** | **落盘 Schema 关键字段验证** | 必须包含 `data_provenance`、`prob_source`、`is_input_suspect`、`quarantined_signals` | 抽检实测落盘 JSON，四字段完整存在：`POLYMARKET_LIVE_CLOB`、`EMOS_PIPELINE`、`false`、`0` | **通过** |
| **CHK-04** | **隔离熔断与打标门禁** | $\Delta_{\text{median}} > 8.0^\circ\text{F}$ 时必须打标 `INPUT_SUSPECT` 且剥离可执行性 `QUARANTINED` | `test_input_suspect_triggers_quarantine_on_large_deviation` 单测 $100\%$ 拦截验证通过 | **通过** |
| **CHK-05** | **离线重放与拟合框架就绪** | D-1（门槛扫描）、D-2（指标 A 领先性）、D-3（指标 B 校准）代码就绪 | `src/pricing/w3_offline_replay_analyzer.py` 经 6 项单元测试全绿验证 | **通过** |
| **CHK-06** | **C5 最高安全红线** | 资金变动 $\equiv \$0.00$；私钥数 $\equiv 0$；下单调用 $\equiv 0$ | 全库静态检索零交易私钥，网络请求仅使用只读公共端点 | **通过** |

---

## 二、 生产 Cron 定时调度部署规范 (A-5 契约)

为严格执行“定时快照批处理、禁止常驻监控进程”的 A-5 条款，系统通过操作系统的 crontab 进行定时驱动：

```cron
# ==============================================================================
# Polymarket W3 温度盘口观测期定时采集任务 (A-5 契约: 单次批处理, 零常驻)
# ==============================================================================

# 1. 基准层 (A-1): 每 60 分钟整点执行一次全量市场快照与纸面评估
0 * * * * cd /Users/ericlin/SynologyDrive/Project/Poly\ Way2 && /opt/miniconda3/bin/python3 scripts/run_w3_clob_snapshot_batch.py --layer BASELINE >> logs/cron_baseline.log 2>&1

# 2. 结算探测层 (A-2): 每 15 分钟执行一次针对 T-12h 临近结算市场的密集快照
*/15 * * * * cd /Users/ericlin/SynologyDrive/Project/Poly\ Way2 && /opt/miniconda3/bin/python3 scripts/run_w3_clob_snapshot_batch.py --layer PROBE >> logs/cron_probe.log 2>&1
```

---

## 三、 落盘 Schema 样例比对 (JSON 契约)

实测落盘工件示例：[`data/clob/evaluations/2026-10-11/eval_highest-temperature-in-miami-on-october-12-2026_20261011T152704Z.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/data/clob/evaluations/2026-10-11/eval_highest-temperature-in-miami-on-october-12-2026_20261011T152704Z.json)

```json
{
  "evaluation_id": "eval_highest-temperature-in-miami-on-october-12-2026_20261011T152704Z",
  "timestamp_iso": "2026-10-11T15:27:11.181829+00:00",
  "snapshot_id": "highest-temperature-in-miami-on-october-12-2026_20261011T152704Z",
  "market_slug": "highest-temperature-in-miami-on-october-12-2026",
  "station_id": "KMIA",
  "settlement_time_iso": "2026-10-12T12:00:00+00:00",
  "data_provenance": "POLYMARKET_LIVE_CLOB",
  "prob_source": "EMOS_PIPELINE",
  "summary": {
    "total_brackets": 11,
    "evaluated_count": 11,
    "positive_ev_signals": 2,
    "quarantined_signals": 0,
    "divergence_count": 1,
    "static_prob_count": 0,
    "no_quote_count": 4,
    "is_input_suspect": false,
    "market_implied_median": 90.5611,
    "model_median": 90.013,
    "median_deviation": 0.5481,
    "prob_source": "EMOS_PIPELINE"
  }
}
```

---

## 四、 观测期状态登记

- **观测期正式启动时刻**：`2026-10-11 15:30:00 UTC`
- **计划观测跨度**：72 小时连续离线纸面观测
- **移交责任人**：W3 会话 Agent
- **观测期间纪律**：只读运行、自动落盘、无热拔插、无手工干预、无临场改参。
