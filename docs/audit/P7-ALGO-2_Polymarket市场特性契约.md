<!-- 供主导方/开发端/用户共同读取 | 日期: 2026-10-14 | 性质: 市场特性契约 v1.0（整体落盘 · 待开发端挑战） -->
# P7-ALGO-2 Polymarket 市场特性契约（Market Microstructure Contract）v1.0

> **版本变更 v0.3 → v1.0（整体落盘）**：v0.3 全部定案内容保留；补充归档代码证据（Grep 实证：归档代码用**自定义 CLOB 模型客户端**，OrderType=IOC/GTC、MARKET 禁止，**未直接依赖 py-clob-client、未引用 v1 数据接口**）→ 影响清单⑥⑦表述精确化（无现网断供，属新对接基础）；新增 §十「开发端挑战清单」。
> **目的**：将 Polymarket.com 国际站的市场微结构特性**参数化**，作为算法与执行层的受控契约，杜绝拍脑袋假设。
> **数据基准**：2026-10-14 联网核实 + 用户裁决 + 归档代码 Grep 实证。**未来任何参数变化时，必须先更新本表（版本+1）再联动算法/规格书。**
> **来源分级**：✅ = 官方一手（docs.polymarket.com / polymarket.com 官网 / 官方 GitHub SDK / 用户实测截图）；🔶 = 官方派生物/可靠镜像/代码实证；⚠️ = 第三方或待运行时实测。
> **平台锁定**：本项目交易 **Polymarket.com 国际站**（**非** Polymarket US、**非** Perps——三者费率/规则独立）。

---

## 〇、最重要的事实修正（先看这个）

| # | 事实 | 依据 | 状态 |
| :--- | :--- | :--- | :--- |
| 1 | **官方 py-clob-client 已归档废弃**，迁移到新统一 SDK `polymarket-client`（py-sdk）——"归档警告"指 GitHub 仓库只读弃用，**与 Data API v1 退役是两件独立的事**；**归档代码未直接依赖它**（自定义 CLOB 模型客户端） | github.com/Polymarket/py-clob-client + 归档代码 Grep | ✅ |
| 2 | **官方 Data API v1 于 2026-10-24 退役**：历史数据接口必须迁移到 **v2（data-api.polymarket.com）**；唯一例外 `/v1/accounting/snapshot` 不退役 | docs.polymarket.com 迁移指南 + Bravado 实证 | ✅ |
| 3 | **天气市场 taker 费率系数 = 0.05**，公式 `fee = C × 0.05 × p × (1−p)`；**base 仅是系数**，佣金必须按价格×股数计算；M-2 的 base=0.0125 已过时（差 4 倍） | docs.polymarket.com/trading/fees | ✅ |
| 4 | **结算资产 = pUSD（backed by USDC）**；deposit 支持 USDC/USDC.e/USDT/ARB/BNB/BTC/BTCB/BUSD/CASH/cbBTC/DAI/ETH（用户截图） | docs.polymarket.com/trading + 用户实测 | ✅ |
| 5 | **费用参数每市场由协议设定**，官方指引 "See Market Details to read the fee parameters for a market" → 运行时读市场元数据 | docs.polymarket.com/trading/fees | ✅ |
| 6 | 温度市场 = **NegRisk 互斥穷尽结构**（N 档只结算 1 档，YES=$1）；NO(bin i) = YES(其余档) | 官方市场结构 + 学术实证 | ✅ |
| 7 | **用户裁决：暂不做 maker** → maker rebate 建模挂起，统一按 taker 全额费率 0.05 计入 | 用户裁决 | ✅ |
| 8 | **归档代码订单类型实证**：OrderType.IOC / GTC、MARKET 禁止（自定义 CLOB 模型客户端）→ 与官方 FAK/GTC + 禁市价一致，IOC 语义映射 FAK | 归档代码 `tests/execution/test_clob_models_client.py`、`test_order_router.py` | ✅ |

---

## 一、费用契约（官方一手 + 用户裁决）

### 1.1 官方公式（docs.polymarket.com/trading/fees）

```
fee = C × feeRate × p × (1 − p)
```
C = 成交份额数；p = 成交价；**feeRate 仅是 base 系数，最终佣金 = 系数 × 股数 × 价格函数**。费用在成交时刻由协议自动计算（下单无需携带费用信息）；按每次成交实际匹配价计。

- 只有 **taker**（移除流动性）付费；**maker 永不付费**；
- 费用随价格对称，**峰值在 50¢**（30¢ 与 70¢ 美元费用相同）；
- **精度**：四舍五入到 5 位小数，最小费用 0.00001（更小舍入为零）；
- **用户裁决：本系统暂不做 maker** → 统一按 taker 全额费率建模；maker rebate / taker tiered rebate 均不建模（挂起）。

### 1.2 官方分类费率表（docs.polymarket.com/trading/fees 原表）

| 分类 | Taker Fee Rate | Maker Fee Rate | Maker Rebate |
| :--- | :---: | :---: | :---: |
| Crypto | 0.07 | 0 | 20% |
| Sports | 0.05 | 0 | 15% |
| Finance | 0.04 | 0 | 25% |
| Politics | 0.04 | 0 | 25% |
| Economics | 0.05 | 0 | 25% |
| Culture | 0.05 | 0 | 25% |
| **Weather** | **0.05** | **0** | **25%** |
| Other / General | 0.05 | 0 | 25% |
| Mentions | 0.04 | 0 | 25% |
| Tech | 0.04 | 0 | 25% |
| Geopolitics | 0 | 0 | — |

> Weather 行已用：Taker Fee Rate = **0.05**；Maker 相关因"暂不做 maker"**挂起不建模**（官方值备查）。

### 1.3 官方费用页交叉验证（polymarket.com/fees，2026-10-14 抓取）

| 分类 | 活跃事件数 | 费用范围（100 contracts） | rebate 后 |
| :--- | :---: | :---: | :---: |
| **Weather** | **325** | **0 – 1.25%** | 0 – 0.94% |
| Politics | 2166 | 0 – 1.00% | 0 – 0.75% |
| Crypto v2 | 4011 | 0 – 1.75% | 0 – 1.40% |
| Sports v3 | 13317 | 0 – 1.25% | 0 – 1.06% |

> 天气 1.25%（100 shares @ 0.50）= 公式 `100 × 0.05 × 0.5 × 0.5 = 1.25` ✅ 与 1.2 完全一致。

### 1.4 与算法公式的对齐（最终口径）

算法：$q_{\text{eff}} = p[1 + \text{base}(1-p)]$，隐含费率率 $= \text{base}(1-p)$。
官方天气费率率（fee/premium）：$= 0.05(1-p)$。
**→ base = 0.05（官方 Weather taker 系数）；p=0.5 时费率率 2.5%（原 0.0125 假设仅 0.625%）。**

| 参数 | 旧值（M-2 [待核实]） | 官方实测 | 状态 |
| :--- | :---: | :---: | :--- |
| base（天气市场 taker 费率系数） | 0.0125 | **0.05** | ✅ 官方 Fees 页 |
| Maker 返佣 | 0.20 | **暂不做 maker，不建模**（官方 Weather 备查 25%） | ✅ 用户裁决挂起 |

---

## 二、订单与执行契约（官方 SDK/文档 + 归档代码实证）

| 参数 | 值 | 官方依据 | 状态 |
| :--- | :--- | :--- | :--- |
| 撮合机制 | 连续 CLOB，价格-时间优先 | 官方文档 | ✅ |
| 订单类型 | **GTC / GTD / FOK / FAK** | 官方 py-clob-client（已归档）、py-sdk、多语言官方 SDK | ✅ |
| **我们 IOC_LIMIT 的映射** | **FAK**（尽可能成交、剩余取消）——归档代码 OrderType.IOC 语义一致 | 官方 SDK 语义 + 归档代码实证 | ✅ |
| **我们 POST_ONLY 的映射** | **PostOnly 标志**（仅 GTC/GTD 可用；立即成交即拒单） | 官方 SDK | ✅ |
| 禁市价单 | 保持（归档代码已禁止 MARKET，类型层只用限价+FAK/IOC/PostOnly 表达） | 官方 SDK + 归档代码实证 | ✅ |
| **tick size** | 每市场不同（常见 "0.01" / "0.001"），**从市场元数据读取** | 官方 SDK TickSize + gamma `minimum_tick_size` | 🔶 运行时实测 |
| **最小订单量** | 每市场不同，**从市场元数据读取**（`minimum_order_size`） | gamma API 字段 | 🔶 运行时实测 |
| 价格/数量粒度对齐 | 算法 f* → 价格 quantize 到 tick、数量对齐 lot（ROUND_DOWN） | — | 待细化 |

---

## 三、市场结构（温度市场 = NegRisk）

| 参数 | 值 | 官方依据 | 状态 |
| :--- | :--- | :--- | :--- |
| 结构 | NegRisk 事件：N 个互斥穷尽档位（bin），每档一个二元市场 | 官方事件/市场模型 + 学术实证 | ✅ |
| 结算 | 仅 1 档 YES 结算 $1/份 | 官方 | ✅ |
| 互补性 | NO(bin i) = YES(其余档)（NegRisk conversion） | 学术实证 | ✅ 支撑反向套利/对冲 |
| **结算源** | NOAA **`weather.gov/wrh/timeseries?site=XXX`** 当日全时次 "Temp" 列**最高值** | 官方市场规则文本（真实市场实例） | ✅ 与规格书 NWS WRH 一致 |
| 站点指定 | 每市场规则指定（KMIA/KDFW/KLGA/KORD/UUWW/LLBG/ZSPD…） | 官方市场规则 | ✅ 按市场读 |
| 精度 | 整度（US 站 °F / 国际站 °C） | 官方市场规则 | ✅ |
| 定稿时点 | 次日首个数据点发布后才可结算；时间窗内修订影响结算 | 官方市场规则 | ✅ t_remain 对齐 |
| 双源 | NWS WRH 市场与 Wunderground 市场**并存**（ZSPD 已确认） | 项目 frozen 文件 | ✅ 对账/后备 |

---

## 四、资金与链上契约（官方一手 + 用户实测）

| 参数 | 值 | 官方依据 | 状态 |
| :--- | :--- | :--- | :--- |
| 链 | Polygon（CLOB + 链上结算） | 官方 SDK（HOST=clob.polymarket.com） | ✅ |
| **结算/计价资产** | **pUSD**（Polymarket USD，**backed by USDC**） | docs.polymarket.com/trading + 用户确认 | ✅ |
| **入金代币选项（deposit）** | **USDC / USDC.e / USDT / ARB / BNB / BTC / BTCB / BUSD / CASH / cbBTC / DAI / ETH**（用户截图，列表最下方未截全） | 用户实测截图 | ✅ |
| 存取款 | 平台无费用（中介如 Coinbase/MoonPay 可能另收）；桥/gas/兑换成本另计 | 官方 Fees 页 | ✅ |
| 结算方式 | 订单成交后链上结算：pUSD 与 outcome tokens 在交易账户间转移 | docs.polymarket.com/trading | ✅ |
| 签名 | EOA / Magic(email) / 浏览器代理（signature_type 0/1/2） | 官方 py-clob-client | ✅ |
| Polygon gas | 低但非零（链上结算有成本） | 常识 | ✅ 批量聚合待细化 |

---

## 五、运行时数据源（官方一手，含 Data API v2 迁移）

| 数据 | 接口 | 官方依据 | 状态 |
| :--- | :--- | :--- | :--- |
| 市场元数据（tick/lot/fee 参数/condition/outcomes/clobTokenIds/结算日期） | **gamma API**（`gamma-api.polymarket.com`；`/markets`、`/events`、`/keyset`） | docs.polymarket.com/developers/gamma-markets-api | ✅ |
| 盘口/中点/下单 | **CLOB API**（`clob.polymarket.com`） | 官方 SDK | ✅ |
| **历史价格/成交/持仓/开仓量** | **Data API v2**（`data-api.polymarket.com/v2/...`）——**v1 于 2026-10-24 退役** | docs.polymarket.com 迁移指南 | ✅ **新数据获取层直接用 v2** |
| Data API v2 要点 | 价格历史 = `GET /v2/prices-history?token_id=...`（参数用 token_id，v1 用 market）；cursor 分页（v1 offset 有 10,000 上限）；字段 snake_case + 重命名（asset→token_id 等）；`condition` 替代 `market`；`/v1/accounting/snapshot` 唯一例外不退役 | Bravado 实证 | ✅ |
| 官方 SDK | **py-sdk（`polymarket-client`）**——替代已归档 py-clob-client | 官方 GitHub | ✅ **新对接基础** |
| 结算数据 | NWS WRH 页面（`weather.gov/wrh/timeseries`）+ WU 后备 | 官方市场规则 + 项目文件 | ✅ |

> **归档代码实证**（Grep `docs/archive/trading_modules/`）：未发现 `py-clob-client` / `prices-history` / `data-api` 引用——历史数据与对接层为自定义实现，**无 2026-10-24 断供风险**；但新实现应以 py-sdk + Data API v2 为基础，不沿用旧接口路径。

---

## 六、参数汇总表（供算法/代码引用）

| 参数名 | 当前值 | 依据 | 状态 |
| :--- | :--- | :--- | :--- |
| platform | Polymarket.com 国际站 | 项目文件 + 官方 fees 页 | ✅ 锁定 |
| 费率公式 | `fee = C × r × p(1−p)`（r 仅是系数） | docs.polymarket.com/trading/fees | ✅ |
| r（Weather taker） | **0.05** | 同上 | ✅（替代 0.0125） |
| maker | **暂不做 maker**（rebate 不建模） | 用户裁决 | ✅ |
| 费用精度 | 5 位小数；最小 0.00001 | 官方 Fees 页 | ✅ |
| fee 参数来源 | 市场元数据（Market Details），协议设定 | 官方 Fees 页 | 🔶 运行时读 |
| 订单类型 | GTC/GTD/FOK/FAK + PostOnly(GTC/GTD) | 官方 SDK | ✅ |
| 我们的映射 | IOC_LIMIT→FAK；POST_ONLY→PostOnly | 官方 SDK + 归档代码实证 | ✅ |
| tick_size | 运行时读元数据（常见 0.01/0.001） | 官方 SDK + gamma 字段 | 🔶 |
| minimum_order_size | 运行时读元数据 | gamma 字段 | 🔶 |
| 撮合 | 价格-时间优先 CLOB | 官方 | ✅ |
| 市场结构 | NegRisk 互斥穷尽 | 官方/学术 | ✅ |
| 结算源 | NWS WRH（+WU 双源） | 官方规则 + 项目文件 | ✅ |
| 结算精度/定稿 | 整度、次日定稿 | 官方规则 | ✅ |
| **结算资产** | **pUSD（backed by USDC）**；入金可用 USDC 等 12+ 种代币 | 官方 Trading 页 + 用户截图 | ✅ |
| 链 | Polygon | 官方 SDK | ✅ |
| 官方 SDK | py-sdk（polymarket-client） | 官方 GitHub | ✅ |
| **历史数据接口** | **Data API v2**（v1 2026-10-24 退役） | 官方迁移指南 | ✅ |

---

## 七、对现有规格书/算法文档的影响清单（定案，待开发端挑战后落进规格书）

| # | 影响项 | 现状 | 结论 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **M-2 base** | 0.0125 `[待核实]` | **0.05**（Weather taker 系数，官方 Fees 页；base 仅是系数，佣金=C×r×p(1−p)） | ✅ 定案 |
| 2 | **Maker 返佣** | 0.20 `[待核实]` | **暂不做 maker → 不建模**（挂起；官方 Weather 备查 25%） | ✅ 用户裁决 |
| 3 | **资金单位** | "USDC" | **pUSD（backed by USDC）**；入金支持 USDC 等 12+ 种代币；规格书表述更新 | ✅ 定案 |
| 4 | **订单类型映射** | IOC_LIMIT/POST_ONLY | **FAK / PostOnly(GTC/GTD)**；归档代码 OrderType.IOC 语义一致 | ✅ 定案 |
| 5 | **价格/数量粒度** | 未定义 | **新增**：价格 quantize 到 tick、数量对齐 lot（ROUND_DOWN）；tick/lot 运行时读元数据 | 🔶 待细化 |
| 6 | **对接 SDK** | 自定义 CLOB 客户端 | **py-sdk（polymarket-client）为新对接基础**；归档代码未直接依赖旧 SDK，无断供 | ✅ 定案 |
| 7 | **历史数据接口** | 未定义 | **Data API v2**（v1 2026-10-24 退役；价格历史 `/v2/prices-history?token_id=`；cursor 分页）；归档代码未引用 v1，无断供 | ✅ 定案 |
| 8 | 结算 | NWS WRH | 官方规则一致；细化"整度+次日定稿+修订影响" | ✅ |
| 9 | 运行时元数据 | 未定义 | **决策快照增加 market_meta**（tick/lot/fee 参数读取） | ✅ |

---

## 八、更新契约（未来变化管理，硬性）

1. **本契约冻结于 2026-10-14（v1.0）**；
2. 任何参数变化（费率公式/系数/rebate、资金资产、SDK、Data API 版本、结算规则、订单类型）→ **先更新本表（版本+1）→ 再联动规格书/算法/代码**；禁止直接改代码绕过本契约；
3. 更新触发：官方文档变更、市场元数据实测偏离、SDK 迁移、Data API 版本变动、结算规则调整、pUSD/入金通道变化、**未来决定做 maker**；
4. 更新动作：记录变更日期、官方来源 URL、旧值→新值、对算法的影响（公式/门禁/参数）；
5. 🔶 待实测项（tick/lot/fee 状态实例值、Data API v2 接入验证）在对接冒烟时闭环，升级为 ✅ 并留痕。

## 九、来源清单（2026-10-14 实抓/实测）

| 来源 | 类型 | 用途 |
| :--- | :--- | :--- |
| docs.polymarket.com/trading/fees | ✅ 官方一手 | 国际站费率公式/分类系数/Maker Rebate/精度 |
| docs.polymarket.com/trading | ✅ 官方一手 | pUSD 结算资产、订单-结算流程 |
| polymarket.com/fees | ✅ 官方一手（官网） | 各分类费用范围与 after-rebate（交叉验证） |
| docs.polymarket.com/developers/gamma-markets-api/get-markets | ✅ 官方一手 | Event/Market 结构、gamma 端点 |
| docs.polymarket.com 迁移指南/Changelog（Data API v2） | ✅ 官方一手 | v1 2026-10-24 退役、v2 端点 |
| github.com/Polymarket/py-clob-client | ✅ 官方（已归档） | OrderType/TickSize；归档警告 |
| github.com/Polymarket/py-sdk | ✅ 官方 | 新统一 SDK（polymarket-client） |
| bravadotrade.com/blog/polymarket-data-api（2026-10-08） | 🔶 第三方实证 | Data API v1→v2 字段/分页/速率差异 |
| 用户实测截图（Transfer Crypto / deposit 选项） | ✅ 用户实测 | 入金代币选项（USDC 等 12+ 种） |
| 归档代码 Grep（`docs/archive/trading_modules/`） | ✅ 代码实证 | OrderType.IOC/GTC/MARKET 禁止；未依赖旧 SDK/v1 数据接口 |
| 官方市场规则文本（真实温度市场） | 🔶 官方规则原文 | NWS WRH 结算细则 |
| 项目 `frozen/phase1/zspd_temperature_comparison_report.md` | ✅ 项目文件 | 平台锁定（国际站）、ZSPD 双源 |

## 十、开发端挑战清单（供开发端 Agent 第一轮挑战）

以下 9 点请开发端逐项给出意见/挑战（支持/反对/补充工程约束），收敛后落进规格书/算法文档/落档细化：

1. **base=0.05 的链式影响**：M-2 费率系数从 0.0125→0.05 后，q_eff、edge、套利判定 `Σq_eff ≤ 1−m_dutch`、门禁 G 系（利用率/edge 阈值）是否全部需要重算口径？哪些现有公式不受影响？
2. **"暂不做 maker"的执行语义**：订单执行路径是否全部走 taker（FAK/IOC 吃单）？POST_ONLY 是保留为可选挂单模式还是彻底移除？对 S6 套利通道（若需挂单实现）有无影响？
3. **Data API v2 迁移**：回测/标定/运行时价格数据获取层设计——cursor 分页、`token_id` 参数、字段重命名映射（asset→token_id 等）、速率限制（价格历史 200 次/10s）是否满足回测吞吐？
4. **tick/lot 粒度对齐**：SLSQP 输出 f* → shares 换算 → 价格 quantize 到 tick、数量对齐 lot（ROUND_DOWN）的落点位置；与 safe_capacity、保护价 P_protect 的衔接顺序。
5. **market_meta 进决策快照**：tick/lot/fee 参数的读取时机（决策初始化时一次还是每次循环刷新）、缺失/异常字段的 Fail-Closed 行为。
6. **pUSD 资金模型**：账务层（6 位 Decimal）以 pUSD 计价、入金通道 12+ 种代币是否需要建模换算；USDC 与 pUSD 汇率处理。
7. **费用精度衔接**：官方费用 5 位小数、最小 0.00001 与算法 Decimal 精度的衔接；极端价位（1¢/99¢）小单零费对 edge 判定的影响。
8. **NegRisk 互补性利用**：NO(bin i) = YES(其余档) 是否纳入 S6 套利判定（反向互补折算），还是仅用正向 Σq_eff 全包判定？
9. **结算时序**："整度 + 次日定稿 + 修订影响"对 t_remain、结算模拟器、门禁 G 系时间窗的具体影响。

*契约 v1.0 整体落盘；挑战收敛后，§七 9 项影响清单正式落入规格书/算法文档/落档细化。*
