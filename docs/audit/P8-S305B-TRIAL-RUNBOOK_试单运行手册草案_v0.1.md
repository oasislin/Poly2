# P8-S305B-TRIAL-RUNBOOK：CLOB 实盘试单运行手册（`v0.2` · 已对齐两段式授权 `S3-14 / S3-15` · 冻结待触发）

> **⏸️ 常设指令冻结横幅（`P8-WO-20261123-STANDING-DIRECTIVE-NOREAL-ORDER` · `2026-11-22`）**：
> **真钱轨道暂停 · 账户开通类操作统一延后**：链上 `Approve`（`NegRisk CTF Exchange / Adapter`）、`CLOB API` 凭据创建与资金入金全部延后至业主宣布之 **“统一开通”** 时点（不设预期日期，**任何人不得催办、不得代为推进、不得申请提前**）。暂停期内 [`configs/clob_gateway.yaml`](../../configs/clob_gateway.yaml) 保持 `execution_mode: PAPER`，`config/credentials.local.yaml` 保持**不存在状态**；**严禁发出任何真实订单（含 `$0` 成本边界探针单）**，仅允许 `S3-14` 软件轨 `PAPER` 自动化测试。

> **📋 两段式试单架构（`P8-OWNER-CONSOLIDATED-20261123-v2` 丙项 · `2026-11-22` 业主批复）**：
> 1. **`S3-14`（`PAPER` 验证段 · 软件轨 / `PAPER` 态，零真钱）**：本件批准立项（`PLANNED`），随后续 Runner 开发单实现 `trial_runner` CLI、`P14 fee_paid_usd` 守恒补丁、`daily_ledger_path` YAML 必填强制化、Preflight 固化（含链上 `allowance` **只读**查询占位，零 `Approve` 交易）、CLOB↔`P3` 两层对账，以及五项可重复自动化验收门（删除 72h 长跑）。
> 2. **`S3-15`（真钱试单段 · 实盘轨，冻结待触发）**：须待业主宣布 **“统一开通”并终签试单授权单** 方可执行；链上授权清单届时逐项签。

---

## 1. `S3-15` 真钱试单参数表（两段式定版 · **待触发**）

| 字段 | 授权定版口径 | 说明 |
| :--- | :--- | :--- |
| **试单额度闸与敞口上限** | 单笔 **`$6`** / 日累计 **`$15`**；全单真实总敞口 **`<= $5`** | 试单执行前按 `CAPITAL-CONFIG §5c` 临时从 `$25/$250` 单向调小至 `$6/$15`；`daily_ledger_path` 跨重启持久 |
| **选市场与锚定规则** | **`KMIA` 或 `KORD`** `D+1` 核心温区 `YES`（`best_ask ∈ [0.25, 0.55]`，`neg_risk == True`）；**严禁按 `mid` 锚定** | 避开单侧尾部；以 `best_ask` 为锚按实时 `tick_size`（`0.01/0.001`）偏移 |
| **执行时段（UTC 窗口）** | **`15:00Z – 20:00Z`**（`10:00–15:00 ET`，北京时间 `23:00–04:00`） | 北美日间活跃窗，错开 `00:05Z` 录盘日切轮转 |
| **触发单型与数量下限** | `IOC_FAK` 限价买单，`>= 5 shares`、`limit_price <= 0.99` | 禁止市价单；先过本地校验与 `P14` 含费现金预冻结 |

### 1.1 试单三探针保留设计（统一状态：**待触发（业主统一开通后随试单授权单生效执行）**）

| 探针编号 | 探针定位与挂单口径 | 目标验证点 | 当前状态 |
| :--- | :--- | :--- | :---: |
| **`Probe 1`** | **边界 `FAK` 无成交闭环探针**（`5 shares @ best_ask - 2*tick`，`$0` 成本） | 验证 `EIP-712 NegRisk` 签名、Level-2 HMAC 认证与 `FAK no match -> CANCELLED_UNFILLED` 闭环 | **待触发（业主统一开通后随试单授权单生效执行）** |
| **`Probe 2`** | **极小真成交探针**（`5–6 shares @ best_ask` 或 `+1*tick`，`~$2` 真成交） | 验证 `FILLED/PARTIAL`、`0.01×C×p(1-p)` 实扣费、往返 RTT（→回填 `S3-11 latency_ms`）与实测滑点（→对照 `S2-02 friction_median`） | **待触发（业主统一开通后随试单授权单生效执行）** |
| **`Probe 3`** | **`<$1` 名义额探针**（`5 shares` 低价档，约 `$0.50–$0.60`） | 验证 CLOB 对 `< $1` `FAK` 买单之实际接单/拒单行为以闭合 `FACT-004` 保守占位 | **待触发（业主统一开通后随试单授权单生效执行）** |

---

## 2. Preflight 强检清单（`S3-14` 固化执行 · `S3-15` 届时逐项签）

1. **SDK 与依赖版本锁定**：确认运行环境 `py-clob-client == 0.34.6`（`verify_locked_sdk_version()` 通过）。
2. **凭据与最小权限**：
   - 本地凭据仅存于 `config/credentials.local.yaml`（已确认 `.gitignore` 拦截；暂停期保持不存在状态）或 `POLY_CLOB_*` 环境变量；
   - 核验钱包与 API Key **仅有 CLOB 交易签名权限、无提现权限**；确认二次确认环境变量 `POLY_LIVE_CONFIRM=CONFIRM_LIVE` 仅在试单窗口临时注入。
3. **配置与账本路径齐备**：
   - 核对 [`configs/clob_gateway.yaml`](../../configs/clob_gateway.yaml) 含必填 `daily_ledger_path` 与当期双闸；核对 `get_risk_panel_snapshot()`；
4. **`P3` 异步审计就绪**：确认 `AsyncAuditLogger` 在线且 `PAPER/LIVE` 目录物理隔离；
5. **链上 `Allowance` 只读核查占位**：`S3-14` 仅允许**只读**查询 ERC-20/CTF `allowance` 与 `POL` 余额占位，**严禁发任何链上 `Approve` 交易**；真实授权清单待“统一开通”时随 `S3-15` 逐项签批。

---

## 3. 五条定量中止线（Kill Criteria · 触一即停）与熔断复位

- **五条中止判据（触一即刻停）**：
  1. 发生 **重单** 或 CLOB 订单与 `P3 attempt_id` 无法 `1:1` 映射；
  2. **`P3` 日志损坏行**（`corrupt_lines > 0`）或私钥/HMAC 凭据片段泄露；
  3. 实际扣费相对官方 `0.01 × C × p × (1 - p)` 偏差 **`> 0.001 USDC`**；
  4. 单笔实测成交均价相对决策 `best_ask` 恶化 **`> +0.05`**；
  5. 日累计买入成交额触 **`$15`** 或连续失败 `>= 5` 次触发熔断。
- **紧急止血与熔断复位**：请求超时/断连后先查单防重复（宁可漏单、绝不重单）；熔断后只能人工核查无重单后显式调用 `reset_circuit_breaker(operator=..., reason=...)`；改 `configs/clob_gateway.yaml` `execution_mode: PAPER` 下单即时止血。

---

## 4. 三层对账清单与反馈回填（`S3-14` 先通前两层，`S3-15` 全三层）

| 对账项 | 来源 A（本地 `M7 P3` / `P14` / `daily_ledger`） | 来源 B（CLOB REST） | 来源 C（次日结算 `AWC routine METAR` / `P9`） | 校验阈值 | 状态 |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **`attempt_id / orderID / tradeIds`** | `[P3 HTTP_REQUEST / HTTP_RESPONSE]` | `[CLOB /data/orders & /trades]` | `—` | `1:1 匹配、零重单` | `S3-14 先通 A↔B` |
| **成交股数与实花含费美元** | `[P3 filled_shares / filled_usd / fee_paid_usd]` | `[takingAmount / makingAmount / fee]` | `—` | `费偏差 <= 0.001 USDC` | `S3-14 先通 A↔B` |
| **日累计账本 & `P14` 守恒** | `[daily_used_usd + free + locked + held]` | `[试单后余额变动]` | `—` | `含费守恒残差 == 0` | `S3-14 自动化门` |
| **真实 RTT 与滑点观测回填** | `[P3 final_ts - submit_ts / slippage]` | `[成交时间戳]` | `—` | `RTT → S3-11 latency_ms；滑点 → 对照 S2-02` | `S3-15 待触发` |
| **结算终态盈亏核对** | `[M6 held cost basis]` | `[USDC 最终余额]` | `[AWC routine METAR → P9]` | `终态盈亏核对一致` | `S3-15 待触发` |
