# P8-S305B-TRIAL-RUNBOOK：CLOB 实盘试单运行手册草案（`v0.1` · 待批准占位）

> **⚠️ 严正边界声明（`P8-WO-20261123-S305B-GATEWAY-DEV v3 §7a`）**：
> 本手册仅为 **试单操作规程与对账草案占位**；**试单执行本身须业主单独签署批准单另行授权**。在获得业主明确签字指令及完成 `GATE-LIVE` 前置检查前，[`configs/clob_gateway.yaml`](../../configs/clob_gateway.yaml) 强制保持 `execution_mode: PAPER`，任何代码与脚本严禁发出真单。

---

## 1. 试单范围与占位参数表（待业主签发试单批时填实）

| 字段 | 试单前占位口径 | 说明 |
| :--- | :--- | :--- |
| **试单单笔额度闸** | `[占位：$25 / 待定低额，<= configs/clob_gateway.yaml:max_single_order_usd]` | 由试单期缺省值 `$25` 硬封顶；**只允许下调，上调须业主签字** |
| **试单日累计额度闸（UTC）** | `[占位：$250 / 待定，<= max_daily_cumulative_usd]` | UTC 自然日界累计（含 `PARTIAL` 部分成交名义金额） |
| **目标站点与格子（Station / Bin）** | `[待填：如 KORD / KMIA 指定温度档位 YES token_id]` | 仅允许选择活跃且 `neg_risk == True` 档位；`tick_size` 现场验证（`0.01 / 0.001`） |
| **执行时段（UTC 窗口）** | `[待填：YYYY-MM-DD HH:MMZ – HH:MMZ]` | 避开日界结算切换窗口与外部 AWC/WSS 已知维护期 |
| **触发单型与数量下限** | `IOC_FAK` 限价买单，`>= 5 shares`、`limit_price <= 0.99` | 禁止市价单；先过本地校验与 `P14` 现金预冻结 |

---

## 2. 试单前强检清单（Preflight · 任一不通过即中止）

1. **SDK 与依赖版本锁定**：确认运行环境 `py-clob-client == 0.34.6`（`verify_locked_sdk_version()` 通过）。
2. **凭据与最小权限**：
   - 本地凭据仅存于 `config/credentials.local.yaml`（已确认 `.gitignore` 拦截、未进 Git）或 `POLY_CLOB_*` 环境变量；
   - 核验钱包与 API Key **仅有 CLOB 交易签名权限、无提现权限**；资金余额不超过试单封顶需求；
   - 确认二次确认环境变量 `POLY_LIVE_CONFIRM=CONFIRM_LIVE` 仅在本次试单窗口临时注入。
3. **配置热读与面板核对**：
   - 核对 [`configs/clob_gateway.yaml`](../../configs/clob_gateway.yaml) `max_single_order_usd`、`max_daily_cumulative_usd` 与本次批文一致；
   - 核对只读面板快照（`get_risk_panel_snapshot()`）：`execution_mode == LIVE`、`circuit_open == False`、`daily_used_usd`、`model_frozen == True`。
4. **P3 异步审计就绪**：确认 `AsyncAuditLogger(root_dir, execution_mode="LIVE")` 正常开启，预写入路径 `<audit_root>/LIVE/<YYYY-MM-DD>/p3_execution_attempts.jsonl` 可写且独立于 `PAPER`。

---

## 3. 异常处置与熔断手工复位规程

- **超限 / 校验失败**：网关本地拦截（不发 HTTP），立即停止追单，检查配置阈值或盘口 `tick_size` / `neg_risk`。
- **请求超时或断连**：系统自动指数退避+抖动并先执行 **查单（`GET /data/order` / `/data/orders` / `/data/trades`）**；**若未确证服务端状态，宁可漏单、绝不重发第二笔 `POST /order`**。
- **连续失败 `>= 5` 次熔断**：触发 `CIRCUIT_BREAKER` 告警并锁定拒绝所有后续发单；须人工排查网络/RPC/CLOB 状态并核对链上与 `/data/trades` 无重复成交后，方可执行显式 `reset_circuit_breaker(operator=..., reason=...)`。
- **紧急止血切换**：将 `configs/clob_gateway.yaml` 中 `execution_mode` 改为 `PAPER`（下次下单即时生效）或撤销 `POLY_LIVE_CONFIRM` 环境变量并重启，即刻切断全部实盘通道。

---

## 4. 试单后对账清单占位（Post-Trade Reconciliation）

| 对账项 | 来源 A（本地 `M7 P3` / `P14` / `P19`） | 来源 B（CLOB REST / 链上回执） | 校验阈值 | 结论占位 |
| :--- | :--- | :--- | :--- | :---: |
| **`client_order_id / orderID / tradeIds`** | `[P3 HTTP_REQUEST / HTTP_RESPONSE]` | `[CLOB /data/orders & /data/trades]` | `1:1 匹配、无重复成交` | `[待填]` |
| **成交股数与名义金额** | `[P3 filled_shares / filled_usd]` | `[takingAmount / makingAmount]` | `差异 == 0` | `[待填]` |
| **实际扣费验证（`FACT-001`）** | `[P3 fee_paid_usd (0.01×p(1-p))]` | `[CLOB trade fee_rate_bps 实扣]` | `<= 0.00001 USDC 舍入差` | `[待填]` |
| **日累计额度账本更新** | `[daily_used_usd + daily_remaining_usd]` | `[试单后余额变动]` | `守恒无漏记（含 PARTIAL）` | `[待填]` |
| **`P14` 现金守恒** | `[Bankroll conservation_residual_usd]` | `[M6 free + locked + held]` | `== Decimal("0")` | `[待填]` |
