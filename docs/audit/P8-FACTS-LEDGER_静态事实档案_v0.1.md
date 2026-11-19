# P8-FACTS-LEDGER：Polymarket 外部静态事实档案（`v0.2` · `2026-11-18` 已对齐 `S1-01 D-A2` 与 `S1-02 T1 G-15`）

- **治理编号**：`P8-FACTS-LEDGER`（B 线治理 / 外部平台事实基线档案）
- **版本与日期**：`v0.1`（`2026-11-17`）→ `v0.2`（`2026-11-18`：`S1-01/S1-02`）→ `v0.3`（`2026-11-19`：`S1-06` `G-15` 落地）→ **`v0.4`（`2026-11-19`：`T8 v0.3` 增补 `CalculatorHelper.sol` `min(p, 1-p)` 链上签名上限澄清与 `py-clob-client #326` 佐证）**
- **性质声明**：
  > **参数账本（[`P8-CAPITAL-CONFIG §7`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#7-参数账本全案占位参数统一登记表--2026-11-17)）管我们要拟合与校准的内生模型/执行参数；本静态事实档案管外部世界（Polymarket 网关、Gamma 元数据、官方结算机构）的既成客观事实。所有新增结论均为 `2026-11-18` 当前实证基线（受官方规则后续修订约束）。**
- **强校验规则**：每一条记录必须写清 **值 / 来源（本地或线上核实）/ 核实日期 / 复核触发**；涉及与既有 `ADR` 文本存在客观背离的条款，原样如实列示并提交用户裁决，严禁擅自修改既有已批准 `ADR`。

---

## 一、 静态事实总表

| 事实编号 | 类别 | 项目 | 当前核定值 | 来源（本地或线上核实） | 核实日期 | 复核触发 | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`FACT-001`** | **费率与切换日程** | **Weather Taker 费率系数、公式与 `2026-11-20` 官方降费** | 1. 公式验证（`N6`）：官方 `fee = C × feeRate × p × (1 − p)`（5 位小数、最小 `0.00001 USDC`，更小舍入为 `0`），按股均摊即 **`q_eff = p × [1 + feeRate × (1 − p)]`**（数学逐点等价）；<br>2. **当前费率（截至 `2026-11-20T23:59Z` 前）**：`Weather feeRate = 0.05`（Gamma `feeSchedule = {"exponent": 1, "rate": 0.05, "takerOnly": True, "rebateRate": 0.25}`）；<br>3. **⚠️ 即将生效官方变更（`2026-11-20T23:59Z` 起）**：Polymarket 官方公告届时起 **`Weather feeRate` 由 `0.05` 下调至 `0.01`**（公式形态不变）；<br>4. **`D1` 运行时权威源判定**：Gamma `/markets` 之 `feeSchedule.rate` 为权威源（`"API_RUNTIME"`），CLOB `/fee-rate?token_id=` 实测返回 `{"base_fee": 1000}`（不作为小数 `feeRate` 直接消费）；Gamma 缺失时回退 `FACT-001` | ① [`docs.polymarket.com/trading/fees.md`](https://docs.polymarket.com/trading/fees.md)；<br>② [`docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md`](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md)；<br>③ `2026-11-18` 实测 `gamma-api.polymarket.com` (`highest-temperature-in-chicago-on-november-18-2026`) 与 `clob.polymarket.com/fee-rate` | `2026-11-18` 官方文档 + API 实测 | **`2026-11-20T23:59Z` 费率切换时刻强制复验 Gamma `feeSchedule.rate`**；后续每次版本切换或字段变动时 | **`API_VERIFIED（附 2026-11-20T23:59Z 变费预警）`** |
| **`FACT-002`** | **费率** | **Weather Maker 费率与返佣机制切换** | Maker fee 恒为 `0`；现行返佣 `25%`（每日池），`2026-11-20T23:59Z` 起切换为近 30 日加权成交量分档（`< $200,000` 为 `0%`）；Taker `< $200,000` 亦无返佣。`v1` 当前不开启 maker，不建模返佣 | `docs.polymarket.com/trading/fees.md` & `programs/fee-and-rebate-changes-november-2026.md` | `2026-11-18` | 未来启用 `PostOnly` 或 30 日量跨越 `$200,000` 门槛时 | **`API_VERIFIED（当前不建模）`** |
| **`FACT-003`** | **`tick_size` 与深度特征** | **最小跳价动态切换与天气浅盘分布** | 1. 天气活跃盘 `tick_size` 在 **`0.01` 与 `0.001`** 间**逐档动态切换**，且实证显示**非仅限 `<0.04/>0.96` 极端价位**（如 `2026-11-18` 芝加哥 `62-63°F` 在 `bestAsk=0.308` 时 `tick_size=0.001`，而相邻 `58-59°F`/`60-61°F` 为 `0.01`）；<br>2. 精度映射：`0.01` 对应 `(price 2位, size 2位, amount 4位)`；`0.001` 对应 `(3, 2, 5)`；WS 订阅 `tick_size_change` 事件更新；<br>3. 芝加哥 Nov 18/19 实测 22 档盘口分布：核心档 Top-3 卖盘美元深度 **`$10.1–$78.1`**、翼档 **`$0.5–$5.5`**，买卖强烈不对称（`asks: 27–85` 档 vs `bids: 0–16` 档，远翼档多无买单） | ① `2026-11-18` 实测 `clob.polymarket.com/book`（Chicago Nov 18/19 全 22 档）；<br>② `docs.polymarket.com/trading/place-orders.md` & `market-data/market-details.md` | `2026-11-18` | 实时被动录盘（`S1-05`）每帧携带 `tick_size` 并监听 `tick_size_change` | **`API_VERIFIED`** |
| **`FACT-004`** | **最小单双约束** | **`min_order_size_shares` 与 `min_notional_usd`** | 1. **`min_order_size_shares = 5`（单位：`shares`）**：CLOB `/book` (`min_order_size: 5`)、Gamma (`orderMinSize: 5`) 与 `place-orders.md` 一致确认为 **`5` 股**，且 live 订单簿实测存在 `0.12 × 5 = $0.60`、`0.001 × 259.87` 等挂单（直接证伪 `market-details.md` 描述中将 `orderMinSize` 误写成 USDC notional 的内部文档自相矛盾）；<br>2. **`min_notional_usd`（Market/FAK 买单）**：`place-orders.md` 规定 `BUY` Market/`FAK` 传参 `amount` 为 USD notional（社区/二线资料多记 `$1.00` 底线，官方 `place-orders.md` 与 `error-codes.md` 未明文写死 `$1.00`）；`P4-rc` 保持 `min_notional_usd = 1.0` 保守占位待真盘首单网关终验 | ① `2026-11-18` 实测 `clob.polymarket.com/book`（实盘 `5 shares @ 0.12 = $0.60`）；<br>② `docs.polymarket.com/trading/place-orders.md` & `market-details.md` | `2026-11-18` | 真盘切换门试单（首笔极小单验证 `<$1` `FAK` 网关是否拒单） | **`API_VERIFIED（`5 shares` 实盘实证；`$1` `FAK` 底线保留保守占位）`** |
| **`FACT-005`** | **接口与 `negRisk`** | **`NegRisk` 读写语义、`FAK` 批单、限频与 WS/REST 差异** | 1. **`negRisk` 读写语义**：Active 10 气象事件全数为 `negRisk: True`；**写侧** EIP-712 签名**必须**选用 NegRisk CTF 域（`verifyingContract = 0xe2222d279d744050d28e00520010520000310F59`）且需钱包授权 NegRisk Adapter（`0xd91E80cF...`）；**读侧** `/book` 与 WS 按单个 `token_id` 独立返回深度（不自动合成反面 `NO` 流动性），`v1` 直连单档 `YES` `AskBook`；<br>2. **订单类型与批单**：支持 `FAK`（映射 `IOC`）、`FOK`、`GTC`、`GTD`（最短期 `+3min`）；`POST /orders` 每次 **1–15 笔**；限频 `POST /order` `5,000/10s`、`POST /orders` `2,000/10s`；常见拒单：`no orders found to match with FAK order`、`Price (...) breaks minimum tick size rule`、`Size (...) lower than the minimum`、`post_only_mode` (`503`)、`425 Too Early`；<br>3. **WS vs REST 差异（`S1-05` 关键）**：`wss://ws-subscriptions-clob.polymarket.com/ws/market`（`PING/PONG 10s`）；**WS `book` 帧实测省略 `min_order_size` 与 `neg_risk`（返回 `None`）**，且 WS 与 REST 的 `asks` 均按价格**降序**（卖一在末位）、`bids` 按**升序**（买一在末位）；本地 Mac 环境带系统 SOCKS 代理须 `websockets.connect(..., proxy=None)` 直连 | ① `docs.polymarket.com/concepts/negative-risk.md`、`trading/place-orders.md`、`resources/error-codes.md`、`api-reference/rate-limits.md`、`market-data/realtime-data.md`；<br>② `2026-11-18` 实连 `wss://ws-subscriptions-clob.polymarket.com/ws/market` & `clob.polymarket.com/book` | `2026-11-18` | `S1-05` 采集器启动阶段对比 REST/WS 重连行为；网关 SDK 升版或切换 Protocol V2 时 | **`API_VERIFIED`** |
| **`FACT-006`** | **回执语义** | **`FAK` 回执字段与终态对账** | `POST /order` / `POST /orders` 返回 `{ok/success, orderID/orderId, status, makingAmount, takingAmount, transactionsHashes, tradeIds, errorMsg}`；部分成交后立即撤单；异步终态与实扣 fee 可通过 `user` WS / `/data/orders` / `/trades` 复核 | `docs.polymarket.com/trading/place-orders.md` & `resources/error-codes.md` | `2026-11-18` | 真盘极小单实测 `FAK` 部分成交字段精度 | **`DOC_VERIFIED（待真盘首单回执核验）`** |
| **`FACT-007`** | **结算规则 (`T1 G-15`)** | **Polymarket 现役气象市场官方结算口径（全十站实测）** | **⚠️ 已于 `S1-06 (2026-11-19)` 完成 `ADR-0009 / ADR-0012` 修订裁决落地（`~2026-10-23` 起全美十站同步生效）**：<br>1. **首选数据源**：NOAA **`https://aviationweather.gov/api/data/metar?ids=<ICAO>&format=raw&date=...&hours=30`** 之 **routine `METAR`**（优先解析 8 位 `T` 小时温度备注 **`0.1°C`**，缺备注时回退报文体 `TT/TD` 整度 `°C`；**明确排除 `SPECI`**：`"A report whose line begins with SPECI is a special observation and does not count"`）；<br>2. **备用数据源**：若次日 `11:59 PM ET` 前 AWC 无任何常规报，仅此时回退 **Weather Underground Daily Observations**（不再用 `weather.gov/wrh/timeseries`）；双方均无则结算至最低档；<br>3. **时区日界窗口**：观测归属按站点 **当地时间（含 DST，即 IANA `ZoneInfo` 自然日 `00:00:00–23:59:59`）**，非全年固定 LST（Gamma `endDate=12:00Z` 并非日界）；`T_settle_close_utc` = `(D+1) 00:00:00 Local (ZoneInfo)` 转 UTC；<br>4. **温度换算与舍入**：`°F = °C × 9/5 + 32`，`.5` **向正无穷进位**（原文例：**`−22.5°C is exactly −8.5°F and counts as −8°F`**，等价 `math.floor(x + 0.5)`，**不同于 Python `Decimal.ROUND_HALF_UP`** 后者得 `-9`）；<br>5. **发布与修订**：**次日首条常规 METAR 发布时 OR 次日 `11:59 PM ET`（先到者）锁定结算**，锁前 `COR` 计数、锁后修订不计（错报争议保留最多 7 日历天 ET 澄清期） | `2026-11-18` 实测 Gamma 十站模板；`2026-11-19` 修订已写入 [`ADR-0009 §4`](../adr/ADR-0009：芝加哥%2008-31%20特报（SPECI）结算语义裁决与截断层规则.md#4-2026-11-19-s1-06--g-15-修订节--世界事实变更跟随当前决策) & [`ADR-0012 §5`](../adr/ADR-0012：法定结算真值源（NWS%20WRH）、僵尸仓位双轨估值与舍入闭环裁决.md#5-2026-11-19-s1-06--g-15-修订节--世界事实变更跟随当前决策) | `2026-11-18`（规则核验）；`2026-11-19`（`G-15` 闭环） | 每月检查活跃事件 `description` 原文模板哈希，触发时按“世界事实变更跟随”登记 | **`G-15_CLOSED（S1-06 裁决落地 · 喂桥结算同构）`** |

---

## 二、 `S1-01 | D-A2` 五组调研实证汇总（`2026-11-18` 收口记录）

按 [`P8-ALGO-REVIEW G-19`](P8-ALGO-REVIEW_待确认事项登记册_20261113.md) 五组核查要求逐组收口：
1. **组 1｜Gamma ↔ CLOB 映射与 `negRisk`**：验证通过，见 `FACT-005 #1`；`v1` 读侧直连单档 `YES` `AskBook`，写侧（`T8` 后阶段）须按 `neg_risk: True` 对接 NegRisk CTF 域与 Adapter 授权。
2. **组 2｜可见深度与 `tick_size` 动态切换**：验证通过，见 `FACT-003`；核心确认 `tick_size` (`0.01`/`0.001`) 可在中性价位（实测 `0.308`）发生切换，已通过 `P4` 逐帧携带 + WS `tick_size_change` 事件防陈旧。
3. **组 3｜最小单双约束**：验证通过，见 `FACT-004`；`min_order_size_shares = 5`（shares）获 live 盘口 `0.12 × 5 = $0.60` 实证，`min_notional_usd = 1.0` 作为 Market/FAK 买单保守占位留待 `P4-rc`（`D-A2` 代码对接时无需修改结构）。
4. **组 4｜发单语义、WS/REST 差异与 `D1` 权威源**：验证通过，见 `FACT-001 #4` & `FACT-005 #2–3`；确立 Gamma `feeSchedule.rate` 为 `D1` 权威源（跳过 CLOB `/fee-rate` `base_fee: 1000`），并实测 WS `book` 缺失 `min_order_size`/`neg_risk` 及本机需 `proxy=None`。
5. **组 5（`N6`）｜`fee` 计费函数形式与 `2026-11-20` 降费发现**：验证通过，见 `FACT-001 #1–3`；官方公式与 `q_eff = p × [1 + feeRate × (1 − p)]` 严格一致，并**提前捕获 `2026-11-20T23:59Z` `Weather feeRate 0.05 → 0.01` 官方变费日程**（本批严禁修改 `src/pricing/` 锁定文件，`edge_math.py` 接受显式 `fee_rate` 参数由 `P4` 注入，天然兼容切换）。

### 2.1 `2026-11-19` `S1-06` 变费复核与 **费率时代标记规则**（当前决策）

1. **官方变费核对确认**：
   - 切换时间戳：**`2026-11-20T23:59:00Z`**（UTC 显式边界）；
   - `D1` 权威源字段：**Gamma `/markets` `feeSchedule.rate`**（运行时实时存在并 `feesEnabled=True` 时标 `fee_rate_provenance = "API_RUNTIME"`；仅字段缺失时回退 `FACT-001` 默认占位并标 `"FACT-001"`）；
   - 公式等价性代数核验：对任意成交份额 $C > 0$ 与档位卖价 $p \in (0, 1)$，协议买单总现金流出 $C \cdot p + C \cdot \text{feeRate} \cdot p(1 - p) = C \cdot p[1 + \text{feeRate}(1 - p)] = C \cdot q_{\text{eff}}$（注：实盘网关单笔费用按 `5` 位小数舍入、最小收费 `0.00001 USDC`，微差不超过 `0.00001`）。
   - **链上 `CalculatorHelper.sol` `min(p, 1 − p)` 条目澄清（`2026-11-19` `v0.4` 增补 · 杜绝二次混淆）**：
     - Polymarket 官方文档 [`docs.polymarket.com/trading/fees.md`](https://docs.polymarket.com/trading/fees.md) 逐字写明 **`fee = C × feeRate × p × (1 - p)`**，[`fee-and-rebate-changes-november-2026.md`](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md) 逐字重申 **`fee = shares × feeRate × price × (1 − price)`**，同页 `100 shares`（`Weather 0.05`）数值表 `$0.10 → $0.45`、`$0.25 → $0.94`、`$0.50 → $1.25` 亦精确符合 $p(1-p)$；
     - 链上合约 [`Polymarket/ctf-exchange/.../CalculatorHelper.sol`](https://raw.githubusercontent.com/Polymarket/ctf-exchange/main/src/exchange/libraries/CalculatorHelper.sol) 中出现之 `feeRateBps * min(price, 1 - price)` 实为**链上订单签名最大费用保护上限校验公式**（对应 CLOB `/fee-rate` 返回 `base_fee = 1000` 即 `10%` 签名上限），并非 Gamma `feeSchedule.rate`（`0.05 / 0.01`）的实际计费曲线；社区同源佐证见 [`Polymarket/py-clob-client#326`](https://github.com/Polymarket/py-clob-client/issues/326)（*"Fee documentation contradicts CLOB API fee-rate endpoint for Sports markets"*）。在 `p ∈ (0, 1)` 上实际扣费 `rate × p(1−p) ≤ 0.10 × min(p, 1−p)` 恒严格低于链上签名上限；现役只读 [`edge_math.py#L65`](../../src/pricing/edge_math.py#L65) 与 [`penetration_probe.py#L168`](../../src/pricing/penetration_probe.py#L168) 核验一致、无缺陷。
2. **费率时代标记规则（跨断点禁混采铁律）**：
   - 按 `P4.fee_rate` 将历史录盘帧与 `P1/P3` 日志严格划分为 **`fee_era = "0.05_PRE_20261120"`** 与 **`fee_era = "0.01_POST_20261120"`**；
   - **跨断点不混采**：一切费率敏感统计量（含 `friction_median` 换算后边际、`edge` 分布、净期望收益率、各时代滑点对比与盈亏回溯）**严禁跨越 `2026-11-20T23:59Z` 混合池化计算**；
   - **主校准样本选择（当前决策）**：所有面向切片 2 校准与切片 3 假盘/实盘上线之费率敏感统计，**主样本一律取 `0.01` 时代样本**；`0.05` 时代若已录盘仅作纯盘口微观结构（价差/挂单深度/`tick_size` 切换频率）参考或按帧 `P4.fee_rate` 独立分层对照。

---

## 三、 `S1-02 | T1 G-15` 结算口径三查与既有 `ADR` 分叉对照表（`2026-11-18`）

> 严格依据 [`P8-KERNEL-CONSENSUS v1.1 §六 B / §七`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md) 与 `S1-02` 任务要求回引执行：**不预判、逐字引用现役官方原文，并显式暴露与既有 `ADR` 之客观分叉。**

### 3.1 官方规则核心原文摘录（`2026-11-18` 全十站完全一致模板）

> *"The qualifying value is the highest temperature reported in the hourly temperature remark of any routine (METAR) observation for [Station] on that date, in tenths of a degree Celsius as reported. A report whose line begins with SPECI is a special observation and does not count. Every other report is routine, including one issued off the nominal hour and one that carries no METAR or SPECI label."*  
> *"If a routine observation does not carry the hourly temperature remark, the temperature group in the body of that observation governs for that observation, in whole degrees Celsius as reported."*  
> *"The qualifying value is converted using °F = °C × 9/5 + 32 and rounded to the nearest whole degree, with a value ending in exactly half rounded up to the next higher whole degree... −22.5°C is exactly −8.5°F and counts as −8°F."*  
> *"An observation counts if its time stamp, converted to the station's local time (including any daylight-saving shift in effect), falls on the observation date."*  
> *"This market will resolve at the issuance of the first METAR observation for the station on the day following the observation date or by 11:59 PM ET on the day following the observation date, whichever comes first... Changes to observations within this market's timeframe will be considered until the first datapoint for the following date has been published, after which any alterations will not be considered."*  
> *"In the event that the Aviation Weather Center has published no routine observation reporting a temperature for the observation date by 11:59 PM ET on the day following the observation date, the Weather Underground Daily Observations table will be used as the resolution source."*  
> *"https://aviationweather.gov/api/data/metar?ids=KORD&format=raw&date=2026-11-21T09:00:00Z&hours=30"*

### 3.2 与既有 `ADR-0009 / ADR-0012` 之三处分叉对照表（提请用户裁决）

| 核查维度 | 既有 `ADR-0009 / ADR-0012` 规定 | Polymarket 现役实盘规则（`2026-10-25 ~ 11-20` 十站） | 分叉性质与建议处置 |
| :--- | :--- | :--- | :--- |
| **第一查｜数据源** | [`ADR-0012 D1`](../adr/ADR-0012：法定结算真值源（NWS%20WRH）、僵尸仓位双轨估值与舍入闭环裁决.md#L32)：**NWS WRH** 时序表唯一法定，**强制纳入 `SPECI`**（对齐 `ADR-0009`） | **`aviationweather.gov` 常规 `METAR`**（`T` 组 `0.1°C` 优先，体 `1°C` 兜底）；**明确排除 `SPECI`**；AWC 全日无常规报才回退 **Weather Underground** | **真实规则切换**（平台于 `~2026-10-23` 改版）。**建议**：新立 `ADR` 修订或对齐勘误，将 `M9` 结算适配器与 `M1/M2` `M_now`（注意观测对齐）切换为现行 `AWC routine METAR` 口径；保留历史回测对旧期区分日期切分 |
| **第二查｜日界窗口** | `ADR-0012 D2`：`ZoneInfo` 当地自然日闭合（含 DST 23h/25h 守恒） | **站当地含 DST 时钟自然日**（`"including any daylight-saving shift in effect"`） | **完全一致（无分叉）**：正式锁定 `P5 tau_hours` 之 **`T_settle_close_utc = (target_date + 1d) 00:00:00 Local (tz=ZoneInfo(station.tz)) → UTC`**（注：Gamma `endDate=12:00Z` 非结算关窗锚） |
| **第三查｜舍入与修订** | `ADR-0012 D3`：`Decimal.ROUND_HALF_UP`（注：负数 `-8.5 → -9`） | **`.5` 向正无穷进位**（`-8.5°F → -8°F`），等效 `math.floor(x + 0.5)`；次日首条常规报锁前 `COR` 有效、锁后不计；错报 7 天 ET Hold | **负温半度舍入方向与锁定锚差异**。**建议**：`T8 M9` 按 `math.floor(x + 0.5)` / `ROUND_CEILING` 半度实现（或 `Decimal` 正无穷进位辅助函数）并锁定次日首条常规报为终态基准 |

### 3.3 `P9` 结算真值格式草案方向（供后续 `T8` 落盘 `M9`）

- 结合现役官方规则，`P9`（`M9 → M7 / M8`）建议核心字段：`station_id`, `target_date`, `target_type ("TMAX"|"TMIN")`, `resolution_source_used ("AWC_METAR"|"WU_FALLBACK"|"LOWEST_BRACKET")`, `routine_obs_count`, `speci_excluded_count`, `peak_temp_c_tenths`, `peak_temp_f_raw`, `settled_temp_f_int`, `settling_obs_utc`, `first_next_day_routine_obs_utc`, `cor_applied_count`, `resolution_status ("LOCKED"|"CLARIFICATION_HOLD"|"PENDING")`, `raw_source_url`。
- *备注*：Active 10 中 NYC（`KLGA`）同步实测存在 `Lowest temperature (Tmin)` 活跃市场；各具体站 `Tmin` 市场挂牌覆盖随每日事件元数据读取。
