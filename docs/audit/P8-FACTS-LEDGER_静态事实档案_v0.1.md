# P8-FACTS-LEDGER：Polymarket 外部静态事实档案（v0.1）

- **治理编号**：`P8-FACTS-LEDGER`（B 线治理 / 外部平台事实基线档案）
- **版本与日期**：`v0.1` · `2026-11-17`
- **性质声明**：
  > **参数账本（[`P8-CAPITAL-CONFIG §7`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#7-参数账本全案占位参数统一登记表--2026-11-17)）管我们要拟合与校准的内生模型/执行参数；本静态事实档案管外部世界（Polymarket 网关、Gamma 元数据、官方结算机构）的既成客观事实。**
- **强校验规则**：每一条记录必须写清 **值 / 来源（本地或线上核实）/ 核实日期 / 复核触发**；**本档案未核实确认之前，`G-15` 结论不予预判，最小单等未闭环字段仅在账本占位而不硬编码**。

---

## 一、 静态事实总表

| 事实编号 | 类别 | 项目 | 当前核定值 | 来源（本地或线上核实） | 核实日期 | 复核触发 | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`FACT-001`** | **费率** | **Weather Taker 费率系数与公式** | `feeRate = 0.05`（`fee = C × 0.05 × p × (1 − p)`；有效成本 $q_{\text{eff}} = p[1 + 0.05(1 - p)]$；5 位小数精度、最小 `0.00001`） | **① 本地检索基线**：[`P7-ALGO-2_Polymarket市场特性契约.md v1.0`](P7-ALGO-2_Polymarket市场特性契约.md#L18)（`2026-10-14` 抓取 `docs.polymarket.com/trading/fees`）及 [`src/pricing/penetration_probe.py#L22`](../../src/pricing/penetration_probe.py#L22)（`FEE_BASE_RATIO=0.05`）；<br>**② 线上再核实**：`search_web` 检索仍一致显示 `Weather taker feeRate = 0.05`、`fee = C × 0.05 × p × (1−p)`（命中二手镜像；`D-A2` 连线时再直连 `docs.polymarket.com/trading/fees` 与 `/markets` `feeRate` 字段复验） | 本地 `2026-10-14`；线上复核 `2026-11-17` | 每次版本切换、`D-A2` API 直连实测、或市场元数据 `feeRate` 变动时 | **`LOCAL_VERIFIED + WEB_RECHECKED（待 D-A2 API 直连确认）`** |
| **`FACT-002`** | **费率** | **Weather Maker 费率与返佣** | `Maker fee = 0`；官方 Weather 返佣池比例记录为 `25%`（当前决定：暂不做 maker，不建模返佣，全走 Taker 口径） | 本地 [`P7-ALGO-2_Polymarket市场特性契约.md#L36-L57`](P7-ALGO-2_Polymarket市场特性契约.md#L36-L57) + `2026-11-17` `search_web` 一致 | 本地 `2026-10-14`；线上复核 `2026-11-17` | 若未来决定开启 `PostOnly` / Maker 挂单策略时触发重核 | **`VERIFIED（当前不建模）`** |
| **`FACT-003`** | **`tick size`** | **价格最小变动单位 (`minimum_tick_size`)** | 骨架占位：本地档案记录按市场从 Gamma 元数据读取（常见 `0.01` 或极端价位 `0.001`），**实盘天气档位分布待 `D-A2` 实测** | 本地 [`P7-ALGO-2 市场特性契约#L92`](P7-ALGO-2_Polymarket市场特性契约.md#L92)（`gamma` `minimum_tick_size` / SDK `TickSize`） | 本地 `2026-10-14`（待线上 `D-A2` 实测） | `D-A2` 抽取现役活跃天气市场 `/markets` 响应体核实 | **`SKELETON / PENDING D-A2`** |
| **`FACT-004`** | **最小单** | **单笔最小股数与最小名义金额** | 骨架占位：本地 `SPEC §8` 载 `X_min = max(5, gamma.minimum_order_size)`（shares）；CLOB 是否另有 `$1.00` 最小名义金额底线及截断小数位 **待 `D-A2` 实测** | 本地 [`SPEC v2.0 阶段 8#L448-L452`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md#L448-L452) + [`P7-ALGO-2 市场特性契约#L93`](P7-ALGO-2_Polymarket市场特性契约.md#L93) | 本地 `2026-10-14 / 11-10`（待线上 `D-A2`） | `D-A2` 实测 `gamma` 活跃天气市场返回与网关拒单门槛 | **`SKELETON / PENDING D-A2`** |
| **`FACT-005`** | **接口行为** | **CLOB / Gamma / Data API / IOC & 批量与限频** | 骨架占位：本地契约载推荐 SDK `polymarket-client`（`py-clob-client` 已归档）、`Data API v1` 于 `2026-10-24` 退役切换 `v2`、禁市价、`IOC_LIMIT -> FAK`；**`POST /orders` 批量发单上限与实盘限频待 `D-A2` 实测** | 本地 [`P7-ALGO-2 市场特性契约#L16-L23, L87-L91, L131-L135`](P7-ALGO-2_Polymarket市场特性契约.md#L16-L23) | 本地 `2026-10-14`（待 `D-A2`） | `D-A2` 接口勘测与连接测试 | **`SKELETON / PENDING D-A2`** |
| **`FACT-006`** | **回执语义** | **成交回报与部分成交撤单终态语义** | 骨架占位：需核查 `FAK` 返回之立即成交额（`makingAmount/takingAmount`）精确性与需否异步对账 `user` WS / `/trades` 弥补回执延迟 | 本地 [`P7-ALGO-2 市场特性契约 §七`](P7-ALGO-2_Polymarket市场特性契约.md) 留白待实测 | 待 `D-A2` 实测 | `D-A2` 模拟/极小测试验证（不碰 `src/pricing/`） | **`SKELETON / PENDING D-A2`** |
| **`FACT-007`** | **结算规则** | **Polymarket 天气市场官方结算规则与 `G-15` 核对基准** | 骨架占位（**严禁预判 `G-15` 结论**）：本地曾记载 `NWS WRH timeseries` 最高整度、`pUSD (backed by USDC)`、`NegRisk` 互斥、`次日结算值确认`；**确切时区日界、发布形态、修订规则以 `T1 G-15`（`Polymarket FAQ` vs `ADR` 逐字比对）实查结果为准** | 本地 [`P7-ALGO-2 市场特性契约#L100-L109`](P7-ALGO-2_Polymarket市场特性契约.md#L100-L109) + [`polymarket_crawler.py`](../../src/data_acquisition/polymarket_crawler.py) | 待 `T1 G-15` 逐字核查闭合 | **`T1 G-15` 核查任务完成即锁定（当前最优先阻塞 `T8`）** | **`SKELETON / BLOCKING_T8 (T1 G-15)`** |

---

## 二、 本地检索引证说明（`2026-11-17` 对 `D-A2` 费率顺序之执行）

按任务指令要求“先全仓库检索本地已有费率研究记录，以本地为起点，再线上核实现状”：
1. **本地检索命中**：全仓 `rg` 检索精准命中 [`docs/audit/P7-ALGO-2_Polymarket市场特性契约.md`](P7-ALGO-2_Polymarket市场特性契约.md)（`2026-10-14` 对 `docs.polymarket.com/trading/fees` 官方页面实证抓取，纠正早期 `M-2` 过时 `0.0125` 口径至 **`0.05`**）及对应代码常量 [`FEE_BASE_RATIO = 0.05`](../../src/pricing/penetration_probe.py#L22)；不存在无记录的“从零盲猜”。
2. **线上复核与机制化**：`2026-11-17` 二次联网检索未见费率体系变动公告（`0.05` 与对称公式维持）。同时据此建立本静态事实档案 `P8-FACTS-LEDGER`，后续一切 **`D-A2` 平台接口、最小单、精度与 `T1 G-15` 结算原文**均须先写入本表并带核实日期，再供算法设计消费。
