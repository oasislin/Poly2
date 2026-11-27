# Handoff：M10 前端监控页适配 `PAPER` 单站单盘口日双限额与 6 城 `\$6,000` 资金池（`2026-11-28`）

- **发送方**：交易决策 / 执行 / 资金风控后端
- **接收方**：`M10` 前台只读监控页开发与设计维护
- **前置参考**：[`P8-CAPITAL-CONFIG §1.5`](../audit/P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#15-utc-日部署上限与网关金额双闸口径v11-新增--2026-11-22-业主授权)、[`P8-M10-DESIGN`](../audit/P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md)

---

## 一、 后端最新口径与落盘数据源变更

依业主 `2026-11-28` 最新拍板，连续 `PAPER` 仿真（[`offline_scheduler.py`](../../src/decision/offline_scheduler.py) / [`run_s311_offline_scheduler.py`](../../scripts/run_s311_offline_scheduler.py)）已落地三项核心变更：

1. **单笔 `\$25` + 单站单盘口日 `\$250` 硬门控（[`paper_safety_gate.py`](../../src/execution/paper_safety_gate.py)）**：
   - `max_single_order_usd = \$25`、`max_daily_cumulative_usd = \$250`（读自 [`configs/clob_gateway.yaml`](../../configs/clob_gateway.yaml)）。
   - **关键口径**：`\$250` 不是整个账户按自然日共用，而是 **按 `(station_id, target_date)` 独立计算**（如 `KORD|2026-11-28` 上限 `\$250`，与 `KMIA|2026-11-28`、`KORD|2026-11-29` 各自独立）。
   - **独立账本文件**：持久写入 **`data/gateway/paper_daily_usage.json`**（格式 `{"KORD|2026-11-28": "120.50", ...}`，仅计净成交名义额不含费），绝不写入实盘 `data/gateway/daily_usage.json`。
   - **P3 拒单原因枚举**：超限拦截直接在 `P14` 预冻结前写 `p3_execution_attempts.jsonl`（`terminal_status = "REJECTED"`）：
     - `SAFETY_GATE_SINGLE_ORDER_EXCEEDED`
     - `SAFETY_GATE_DAILY_LIMIT_EXCEEDED`
2. **总资金池由 2 城 `\$2,000` 调整为 6 城 `\$6,000`**：
   - `--initial-pool-usd` 默认 `"6000"`（6 站 × `\$1,000/站`），回撤激活阈值同步设为 `\$6,000`，`P19` 会如实反映新资金池总额。

---

## 二、 请 `M10` 前端对应修改的 4 个要点

1. **卡片 4（风险参数面板）不再按“全账户总模拟成交 vs `\$250`”报 `超试单日限`**：
   - **现状问题**：当前 [`m10_cards.py`](../../src/ui/m10_cards.py) `use_sim_cap` 用全市场累计 `model.total_filled_usd` 去比 `\$250`，6 个城市加起来只要超 `\$250` 就会亮红标 `超试单日限` 并提示 `P18 未走 CLOB 网关`，在单站单盘口日口径下属于误报。
   - **建议修改**：
     - 当 `execution_mode == "PAPER"` 时，只读加载 **`data/gateway/paper_daily_usage.json`**（路径缺失或为空时再做降级提示）；
     - 卡片 4 主文案改为展示 **「单笔≤`\$25` · 站盘口日≤`\$250`」**；
     - 进度条与已用展示 **当前活跃 `(station_id, target_date)` 中最高占用的一档**（或展示例如 `最高占满 KORD 11-28: \$X / \$250 · 共 K 个盘口在控`，仅当存在任意单盘口 `> \$250` 时才亮红警告），并在副行注明账本源为 `paper_daily_usage.json`。
2. **新增 `P3` 网关安全闸拒单原因中文译文（[`m10_formatting.py`](../../src/ui/m10_formatting.py)）**：
   - 补齐两项枚举的人话说明与「一句话原因」映射：
     - `"SAFETY_GATE_SINGLE_ORDER_EXCEEDED"` → `超单笔限额 (\$25)`
     - `"SAFETY_GATE_DAILY_LIMIT_EXCEEDED"` → `超单站单盘口日限 (\$250)`
3. **城市持仓卡 / 独立盘口卡进度提示（可选增强，[`m10_cards.py`](../../src/ui/m10_cards.py)）**：
   - 在二级 `<details class="market-day-card">` 标题旁，可直接对照 `paper_daily_usage.json` 中对应的 `station_id|target_date` 已用额度，展示该盘口日剩余限额（`\$X / \$250`）。
4. **文档与约束要求**：
   - 同步更新 [`P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md`](../audit/P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md) 与 `§4` 安全边界；
   - 严守 `src/ui/` 零写回、无表单、`AST < 50` 行及现有 `test_m10_*` 单测全绿。
