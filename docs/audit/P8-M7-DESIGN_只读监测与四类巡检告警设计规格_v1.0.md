# P8-M7-DESIGN：只读监测与四类巡检告警设计规格（`v1.0` · `2026-11-24`）

- **治理编号**：`P8-M7-DESIGN`
- **对应任务编号**：**`S2-07`**（`M7, M10` · 监测与告警设计规格；后续实现单为 **`S3-13`** `PLANNED`）
- **依据工单**：[`P8-WO-20261124-M10-EXEC4`](P8-PROJECT-TASKS_全量任务分解台账_v1.0.md#6-重要治理节点与收口工单追踪日志)（C 部分）
- **法定锚点**：
  - [`P8-T2-M7-LOGGING v1.2 §3.2`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#32-p10m7--m10-前台只读视图兼容约束与正式查询契约v11--s2-04-正文冻结)（`P10` 兼容约束、并发尾行语义与零写回强制校验清单）
  - [`项目方案 (v3.0) §8.1 M7 / M10`](../项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#81-模块地图m1m10-十模块静态架构--2026-11-18-当前决策)
  - [`P8-PROJECT-TASKS v3.0 §2.2 S2-07 / §2.3 S3-13`](P8-PROJECT-TASKS_全量任务分解台账_v1.0.md#22-切片-2基线录盘制度合龙待成文协议-p10-与管控收口)
  - 被巡检基线工具与源码：[`scripts/record_status.py`](../../scripts/record_status.py)、[`scripts/run_passive_book_recorder_daily.py`](../../scripts/run_passive_book_recorder_daily.py)、[`configs/passive_book_recorder.example.yaml`](../../configs/passive_book_recorder.example.yaml)、[`src/audit/p10_reader.py`](../../src/audit/p10_reader.py)、[`src/risk/stream_watchdog.py`](../../src/risk/stream_watchdog.py)
- **文件增殖判据说明（依 [`《项目编号与命名规范 v1.1》§9`](../项目编号与命名规范_20261021.md)）**：[`P8-T2-M7-LOGGING`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md) 承载 `P1/P3/P9/P12/P13/P17/P19` 协议落盘与 `P10` 查询契约，[`P8-M10-DESIGN`](P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md) 承载 `M10` 前台静态 HTML 聚合与呈现规则；二者均不宜混入“四类后台只读巡检阈值、恢复迟滞与独立告警输出契约”职责，且台账 `S2-07` 与 `EXEC4` 工单明确要求独立成文，故以 `docs/audit/P8-M7-DESIGN_只读监测与四类巡检告警设计规格_v1.0.md` 规范落盘并挂载回唯一台账。

---

## §1 职责边界、输入观测源与只读零写回铁律

### 1.1 定位与人工巡检脚本化目标

当前 `M3` 被动录盘与 `M7` 审计流依赖人工执行 [`scripts/record_status.py`](../../scripts/record_status.py) 查看 `frames`、`corrupt_lines`、`incomplete_trailing_lines`、`gap_count`、`token_coverage` 与 `disk_bytes`。`S2-07` 将人工巡检经验固化为**可判定的四类自动化巡检口径与阈值规格**，供后续 `S3-13`（`PLANNED`）无歧义编码实现；**本设计规格阶段不改动任何代码**。

### 1.2 允许的只读输入源

巡检器仅允许以**只读方式**读取以下路径与元信息：

1. **录盘健康快照与分片流**（`data/market_recordings/`）：调用或复用 [`inspect_recording_status`](../../scripts/record_status.py#L226-L259) 与 [`load_latest_session`](../../scripts/record_status.py) 读取 `latest_session.json` 及各分片 `p13_book_stream_*.jsonl`。
2. **审计日志分片流**（`data/audit_logs/<execution_mode>/<YYYY-MM-DD>/`）：调用只读 `query_p10_session_view`（[`src/audit/p10_reader.py`](../../src/audit/p10_reader.py)），收集 `valid_lines`、`corrupt_lines`、`partial_tail_skipped_lines` 与 `render_status`。
3. **只读宿主容量与只读进程探针**：仅允许通过 `os.stat` / `shutil.disk_usage` 检查存储空间与文件体积；若核查 `latest_session.json` 记录之 `child_pid` / `supervisor_pid` 存活态，仅允许零扰动探测（如 `os.kill(pid, 0)`）。

### 1.3 零写回与三层隔离铁律（严格对齐 `P8-T2-M7-LOGGING §3.2 #4`）

| 约束维度 | 强制要求（`S3-13` AST 与测试门禁基线） | 禁止行为（零容忍） |
| :--- | :--- | :--- |
| **只读句柄约束** | 读取 `data/market_recordings/` 与 `data/audit_logs/` 时仅限 `open(..., "r")` | 严禁调用 `.write()`、`truncate()`、`unlink()`、`rename()`、`rmdir()` 或 `mkdir()` 触碰上述两目录 |
| **运行态零扰动** | 对在产录盘 `PID`（如 `supervisor_pid` / `child_pid`）仅做非破坏性存在性检查 | 严禁发送 `SIGTERM` / `SIGKILL` / `SIGHUP`，严禁修改 `latest_session.json` 或清理 `.jsonl` 历史录盘 |
| **告警输出物理隔离** | 所有告警状态快照、事件流与历史滚存**严格输出至独立告警目录 `data/alerts/`** | 严禁回写 `data/market_recordings/`、`data/audit_logs/` 或 `configs/` |
| **前台安全三禁兼容** | 若未来 `M10` 展示告警摘要，须遵守 [`src/ui/m10_view.py`](../../src/ui/m10_view.py) 只读与静态安全约束 | 零独立业务数据库、零写回动作按钮、零 JS / 零 CDN |

---

## §2 四类巡检告警定量口径、阈值与恢复迟滞规格

> 所有阈值以实仓配置为锚：被动录盘默认监控 `6` 站（`KORD, KMIA, KLGA, KATL, KDAL, KSEA`）、`heartbeat_timeout_sec = 25.0`、`rest_fallback_interval_sec = 5.0`（见 [`configs/passive_book_recorder.example.yaml`](../../configs/passive_book_recorder.example.yaml)），日切重启窗口为每日 **`00:05Z`**（见 [`scripts/run_passive_book_recorder_daily.py`](../../scripts/run_passive_book_recorder_daily.py)）；行情/气象物理陈旧护栏参考 [`src/risk/stream_watchdog.py`](../../src/risk/stream_watchdog.py)（`ADR-0011` `15m` WARNING / `35m` STALENESS）。

### 2.1 第一类：`gap 率`（录盘断流与静默缺口检测）

- **观测指标来源**：
  1. **事件级 `gap_rate`**：取活跃会话（或最近 `15m` 滚动窗口）内 `P13` 信封 `gap_detected == True` 帧数与总有效帧数比值：
     `gap_rate = gap_count / max(1, frames)`，并附带 `gap_reasons` 分类计数（`WS_HEARTBEAT_TIMEOUT` / `WS_RECONNECT` / `REST_POLL_ERROR`；依 `C3` 契约严禁将 `single_side` 记作 `gap`）。
  2. **逐站挂钟静默时长 `silence_sec`**：`silence_sec = now_utc - max(last_recv_ts_utc, last_recorded_ts_utc)`（针对当前预期在录各站）。
- **计划窗口与非计划停机区分（防误报）**：
  - **日切宽限窗**：每日 `00:04:30Z – 00:07:00Z`（共 `150s`）为 [`run_passive_book_recorder_daily.py`](../../scripts/run_passive_book_recorder_daily.py) 优雅重启轮转窗口，该窗口内短时 `silence_sec <= 150s` 记 `INFO / PLANNED_ROLLOVER`，不升级 `WARN / CRITICAL`。
  - **主动优雅停机**：若检测到进程已退出且 `latest_session.json` 对应分片 `corrupt_lines == 0`、`incomplete_trailing_lines == 0`，且运维维护标记（如 `data/alerts/maintenance_window.json` 有效期内）声明计划停机，则输出 `INFO / PLANNED_MAINTENANCE_STOP` 并保留停机起止时长供 `S3-08` 评估；**无维护标记的进程退出一律记 `CRITICAL / RECORDER_PROCESS_DOWN`**。
- **分级阈值与恢复迟滞**：
  - **`WARN`**：窗口内 `gap_rate > 1.0%`（且 `frames >= 60`）**或** 任一活跃站非轮转期间 `silence_sec > 120s`（约 `5 × 25s` 心跳超时）。
  - **`CRITICAL`**：窗口内 `gap_rate > 5.0%`（且 `frames >= 60`）**或** 任一活跃站非轮转期间 `silence_sec > 300s`（`5m` 无新帧）**或** 录盘进程无维护声明意外离线（`>= 3/6` 站同时静默超过 `300s` 升级标定 `GLOBAL_STREAM_STALL`）。
  - **`RECOVER`（迟滞回落）**：连续 **`3`** 次巡检周期满足所有在录站 `silence_sec <= 60s` 且滚动 `gap_rate <= 1.0%` 后解除告警。

### 2.2 第二类：`损坏行`（JSON 解析失败与 `record_sha256` 校验失败）

- **观测指标来源**：同时扫描 `data/market_recordings/`（`P13`）与 `data/audit_logs/<mode>/<date>/`（`P1/P3/P9/P12/P17/P19`），严格复用 [`P8-T2-M7-LOGGING §3.2 #2–#3`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#32-p10m7--m10-前台只读视图兼容约束与正式查询契约v11--s2-04-正文冻结) 边界切分：
  1. **并发尾行豁免（`incomplete_trailing_lines` / `partial_tail_skipped_lines`）**：文件末尾未以 `\n` 结尾的在写行**绝不计入 `corrupt_lines`**，仅记录 `(file_path, byte_offset, content_len)`；
  2. **真损坏行（`corrupt_lines`）**：所有**已以 `\n` 结尾**但 `json.loads` 失败或 `verify_record_sha256_line` 失败的完整行，连同 `corrupt_rate = corrupt_lines / max(1, valid_lines + corrupt_lines)` 逐条归档文件与行号。
- **分级阈值与处理原则**：
  - **`OK`**：全量 `corrupt_lines == 0`，且并发未完尾行未在同一字节偏移长期滞留。
  - **`WARN`（卡死半写尾行预警）**：同一文件、同一 `byte_offset` 的 `incomplete_trailing_lines` 在连续 **`>= 3`** 次巡检（持续 `> 90s`）内字节偏移无前进，提示写端进程可能卡死或异常截断（仍严禁删改原行）。
  - **`CRITICAL`（零容忍 `fail-closed`）**：**任意文件 `corrupt_lines >= 1`** 即刻触发 `CRITICAL / INTEGRITY_CORRUPT_LINE`（与 `P10` 视图 `render_status = "DEGRADED_CORRUPT_LINES"` 口径完全对齐），输出精确 `(file_path, line_no, reason)` 证据。
  - **解除条件**：须人工核查损坏行并完成离线处置/归档切换至干净新会话后，连续巡检 `corrupt_lines == 0` 方可恢复 `OK`；**巡检器严禁自动修复、截断或丢弃任何原文件行**。

### 2.3 第三类：`token 覆盖骤降`（6 站双侧 `YES/NO` 订阅覆盖监控）

- **观测指标来源**：复用 [`record_status.py`](../../scripts/record_status.py#L278-L310) 逐站统计的 `token_coverage.{total, YES, NO}`（去重活跃 `token_id` 数）。
- **动态基线与盘口制度区分**：
  - **期望基线 `baseline_tokens(station_id)`**：取同一活跃会话在启动满 `180s` 后的峰值（若当前会话运行不足 `180s`，回退取最近一个健康完整会话同站点值；若历史均无，则以首次稳态采样建线）。
  - **制度区分铁律（对齐 `C3`）**：`single_side = "bid_only" | "ask_only"` 表示某已知 `token_id` 当前盘口仅单边有价（市场流动性特征，正常）；而**`token_coverage.YES == 0` 或 `token_coverage.NO == 0`** 表示整侧合同 `token_id` 在录盘流中完全缺失（订阅/目录发现故障），二者严禁混淆。
- **分级阈值与恢复迟滞**：
  - **日切宽限**：每日 `00:05Z` 轮转及市场日切换后 `180s` 预热期内暂免覆盖骤降告警，仅采集建线。
  - **`WARN`**：预热期外任一站 `coverage_ratio = current_tokens / max(1, baseline_tokens) <= 0.80`（即相对基线骤降 **`>= 20%`**）。
  - **`CRITICAL`**：预热期外任一站 `coverage_ratio <= 0.50`（骤降 **`>= 50%`**）、**或** `current_tokens == 0`、**或** 单站虽有帧但整侧缺失（`YES == 0` 且 `NO > 0`，或 `NO == 0` 且 `YES > 0`），触发 `TOKEN_COVERAGE_COLLAPSE` / `TOKEN_SIDE_MISSING`。
  - **`RECOVER`**：连续 **`2`** 次巡检恢复至 `coverage_ratio > 0.85` 且同站 `YES > 0` 与 `NO > 0`。

### 2.4 第四类：`磁盘 watchdog`（录制体量、审计日志增长率与宿主机剩余空间）

- **观测指标来源**：
  1. `recordings_bytes`（[`record_status.py`](../../scripts/record_status.py) `overall.disk_bytes`）与 `audit_logs_bytes`（`data/audit_logs/` 总字节）；
  2. 宿主机挂载卷可用容量 `shutil.disk_usage(output_root)`：`free_bytes`、`total_bytes`、`free_ratio = free_bytes / max(1, total_bytes)`；
  3. 滚动字节增长速率 `growth_bytes_per_hour`（近 `1h` 增量）与预计耗尽时间 `eta_full_hours = free_bytes / max(1, growth_bytes_per_hour)`。
- **分级阈值**：
  - **`WARN`**：
    - 容量水位：`free_ratio < 20%` **或** `free_bytes < 10 GiB`；
    - 增速异常（防无限循环刷帧/日志风暴）：近 `1h` 增速 `growth_bytes_per_hour >= max(3.0 * trailing_24h_avg_bph, 512 MiB/h)`。
  - **`CRITICAL`**：
    - `free_ratio < 10%` **或** `free_bytes < 4 GiB` **或** `eta_full_hours < 24.0h`。
  - **零自动清理铁律**：`disk_watchdog` **仅触发告警**，绝对禁止在脚本内执行 `rm / unlink / gzip / truncate` 等任何写入或删除动作（须由人工或独立经批复的冷归档流程处理）。

---

## §3 独立告警输出目录与去重输出契约（`data/alerts/`）

### 3.1 目录布局（物理独立于 `market_recordings/` 与 `audit_logs/`）

```text
data/alerts/
├── watchdog_status.json                   # 最新一次巡检全量状态快照（原子替换 temp+replace，仅限本目录内）
└── <YYYY-MM-DD>/                          # 按 UTC 日分片追加历史告警事件
    └── alerts.jsonl                       # 仅记录状态跃迁（OK->WARN / WARN->CRITICAL / ->OK）或到期重发事件
```

> 若生产巡检发现 `data/market_recordings/` 本身缺失（`output_root_exists == False`），在预期有产线运行的情况下于 `data/alerts/` 输出 `CRITICAL / RECORDING_ROOT_MISSING` 告警，不得擅自创建 `data/market_recordings/` 掩盖缺口。

### 3.2 `watchdog_status.json` 与 `alerts.jsonl` 核心字段

- **`watchdog_status.json`**（供 CLI、`cron` 与未来 `M10` 只读摘要消费）：
  - `schema_version = "watchdog.v1"`、`checked_ts_utc`、`overall_severity`（`OK | WARN | CRITICAL`）
  - `checks`: `{gap_rate, corrupt_lines, token_coverage, disk_watchdog}` 四对象，各自包含 `status`、`metrics`、`thresholds`、`triggered_scopes`（如站点列表/文件路径与行号）
  - `planned_windows_active`: 当前是否处于 `00:05Z` 日切窗或有效运维维护窗
- **`alerts.jsonl`** 去重与冷却规则：
  - 同一 `(check_name, scope_key)` 在同等级别下设置 **`cooldown_sec = 300s`**（`5` 分钟）防止告警风暴；
  - 发生等级升级（`OK/WARN -> CRITICAL`）或恢复闭合（`WARN/CRITICAL -> OK`）时**忽略冷却立即落盘事件**。

---

## §4 后续实施单（`S3-13`）与 `M10` 联动说明（本单零代码改动）

1. **后续实施单 `S3-13`（`PLANNED`）范围边界**：
   - 将本设计定案为只读巡检模块（如 `src/audit/readonly_watchdog.py`）与 CLI 入口（如 `scripts/run_readonly_watchdog.py`，支持 `--once` / `--json` / 退出码分级 `0=OK, 1=WARN, 2=CRITICAL`）；
   - 配套单测须包含 AST 静态守卫，验证巡检主链路对 `data/market_recordings/` 与 `data/audit_logs/` 仅存在只读读取调用、零写删除句柄，以及四类阈值 + 迟滞恢复 + 并发尾行豁免 + `00:05Z` 轮转宽限测试。
2. **与 `M10` 前台（[`src/ui/m10_view.py`](../../src/ui/m10_view.py) / [`scripts/render_m10_dashboard.py`](../../scripts/render_m10_dashboard.py)）的双向联动关系**：
   - **上游保真保障（已通过口径对齐实现）**：`S2-07` 与 `M10` 共享 [`P8-T2-M7-LOGGING §3.2 #3`](P8-T2-M7-LOGGING_日志与审计协议规格_v1.0.md#32-p10m7--m10-前台只读视图兼容约束与正式查询契约v11--s2-04-正文冻结) 同一套“并发尾行豁免 + 真损坏行零容忍”规则，提前阻断损坏 JSONL、掉站缺盘或磁盘写满导致 `M10` 监控视图缺页或降级；
   - **只读摘要展示预留（待 `S3-13` 后期按需接入，本单不动 `M10` 代码）**：未来 [`scripts/render_m10_dashboard.py`](../../scripts/render_m10_dashboard.py) 可按需增加只读可选参数 `--alerts-status data/alerts/watchdog_status.json`，在 `M10` 顶部只读状态区渲染四类巡检摘要徽标；[`m10_view.py`](../../src/ui/m10_view.py) 严禁主动调用巡检写操作，保持纯展示属性。
