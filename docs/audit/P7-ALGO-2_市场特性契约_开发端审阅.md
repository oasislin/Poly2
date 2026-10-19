<!-- 供主导方/用户审阅与收敛 | 日期: 2026-10-14 | 角色: 开发端 Agent -->
# P7-ALGO-2 Polymarket 市场特性契约开发端挑战与工程响应报告

> **审阅标的**：[`docs/audit/P7-ALGO-2_Polymarket市场特性契约.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/audit/P7-ALGO-2_Polymarket%E5%B8%82%E5%9C%BA%E7%89%B9%E6%80%A7%E5%A5%91%E7%BA%A6.md) (v1.0)  
> **编制角色**：开发端（执行端）Agent  
> **总体裁定**：**高度支持并全量赞同契约主体**。契约客观核实并校正了四大底层工程事实（Weather Taker base 系数 0.05、官方 Data API v1 退役与 v2 迁移、官方 py-sdk 演进、pUSD 结算资产真实形态）。这彻底消除了“闭门造车”带来的隐性穿仓隐患。
>
> 针对契约 §十 提出的 **9 项挑战点**，开发端基于工程实现可行性、计算复杂度、精度控制与防御性架构，逐项出具正式意见（支持 / 补充具体工程约束），作为后续联动修订规格书、算法描述文档与工程落档细化的最终基准。

---

## 一、 §十 9 项挑战点逐项工程意见与约束补充

### 挑战点 1：base=0.05 的链式影响与口径重算
- **开发端立场**：**【支持，明确影响范围边界】**。
- **数学与工程影响分析**：
  1. **影响公式（必须联动更新）**：
     - 有效成本公式：$q_{\text{eff}} = \bar{P} \cdot [1 + 0.05 \cdot (1 - \bar{P})]$（替代原 0.0125）。当 $\bar{P} = 0.50$ 时，有效成本从 $0.503125$ 跃升至 $0.5125$（单边手续费率从 0.625% 变为 2.50%）；
     - 净 EV 与 Edge：$\text{net\_ev} = \hat{p} - q_{\text{eff}}$ 与 $\text{edge} = \text{net\_ev} / q_{\text{eff}}$ 自动随 $q_{\text{eff}}$ 提高而受到更强烈的挤压；
     - 套利判定式：$\sum q_{\text{eff}, i} \le 1 - m_{\text{dutch}}$，因每档 $q_{\text{eff}}$ 变大，全包套利机会窗口变窄（更保守安全）。
  2. **不受影响公式（保持原样）**：
     - 多项凯利目标函数 $\sum \hat{p}_i \ln W_i(f)$ 与凹性引理 1~3 完全不受影响（$q_{\text{eff}}$ 仍为快照外生正参数）；
     - 不确定集区间 $[p_L, p_U]$ 纯由 EMOS CDF 和参数灵敏度决定，与费率完全解耦；
     - 门禁 G1~G7（10% 单市场、70% 利用率、7min 预购门）完全不受影响。
- **开发端补充工程约束**：
  - 严禁将费率写死为硬编码常数，必须以 `MarketFeeConfig(taker_fee_rate=Decimal("0.05"))` 形式注入，支持从 gamma API 元数据动态拉取并校验。

---

### 挑战点 2：“暂不做 maker”的执行语义与架构简化
- **开发端立场**：**【强烈支持，提出执行层彻底简化方案】**。
- **工程裁定与动作**：
  1. **执行模式全走 Taker (FAK)**：系统当前只下发 `OrderType.FAK`（限价即时成交剩余撤销，对齐 IOC 语义）。
  2. **类型系统与模块裁减**：
     - `OrderType.POST_ONLY` 标记为 `RESERVED_SUSPENDED`（保留枚举但禁止调用）；
     - 彻底切断执行路由中的 Maker 返佣补贴计算与挂单等待重试循环，消除做市排队底账管理；
  3. **对 S6 套利通道的影响**：
     - S6 套利通道（Dutch Book）同样**100% 采用 FAK 吃单**。若盘口 Ask 深度不足以覆盖套利目标，立即撤销剩余，严禁挂 Maker 单留下一腿单边敞口！

---

### 挑战点 3：Data API v2 迁移与回测/标定吞吐保障
- **开发端立场**：**【支持，补充两级缓存与分页约束】**。
- **工程分析与吞吐保障方案**：
  1. **契约核实**：Data API v1 将于 2026-10-24 退役，新建数据获取层必须 100% 走 `data-api.polymarket.com/v2`，入参严格使用 `token_id`（替代旧 `market`），采用 Cursor 分页（避免旧 offset 10,000 条上限）。
  2. **吞吐防爆工程约束（针对 200次/10s 频控）**：
     - **本地磁盘冷缓存（Airgap Cache）**：回测与两步标定严禁高频直连 Data API 实时轮询。必须建立 `data/cache/clob_v2/` Parquet/SQLite 离线缓存池；
     - **自适应令牌桶（Token Bucket）**：实时采集组件严格内置 `RateLimiter(max_rate=18.0, per=1.0)`（预留 10% 安全余量），单次抓取触发 429 立即指数退避（Backoff），退避总时限纳入 ADR-0014 30s 预算管理。

---

### 挑战点 4：tick / lot 粒度对齐落点与保护价衔接时序
- **开发端立场**：**【支持，明确不可逆的时序管道】**。
- **落点管道时序铁律（从数学连续量到链上离散单）**：
  ```
  S2: 连续优化输出 f* (USDC 金额)
      ↓ (第 1 步: 精度收口)
  quantize(Decimal("0.000001"), ROUND_DOWN)
      ↓ (第 2 步: 保护价与容量穿透)
  OrderRouter 扫描 Asks 锁定 P_protect 与 safe_capacity
      ↓ (第 3 步: 价格与数量离散化)
  1. 价格对齐: limit_price = quantize_to_tick(P_protect, tick_size, ROUND_DOWN)
  2. 名义股数: raw_shares = min(f* / limit_price, safe_capacity)
  3. 数量对齐: order_size = quantize_to_lot(raw_shares, lot_size, ROUND_DOWN)
      ↓ (第 4 步: 最小订单门禁)
  若 order_size < minimum_order_size:
      静默标记 SKIPPED_BELOW_MINIMUM_ORDER_SIZE，解锁资金，退出
  ```
- **核心原则**：所有离散化舍入**一律采用 ROUND_DOWN**，杜绝任何向上取整引发的资金超支。

---

### 挑战点 5：market_meta 进决策快照的生命周期与 Fail-Closed
- **开发端立场**：**【支持，确立两级缓存与缺失熔断】**。
- **工程约束规范**：
  1. **获取时序**：
     - **静态底表（盘前缓存）**：盘前由后台任务从 gamma API 拉取台站对应市场的 `market_meta`（含 `tick_size`, `minimum_order_size`, `clobTokenIds`, `fee_rate`）；
     - **决策时注入快照**：单次交易决策触发时，`DecisionContext` 从内存缓存只读拷贝一份 `market_meta`，在单次决策周期内**100% 冻结**。
  2. **缺失与异常 Fail-Closed 判定**：
     - 若 `market_meta` 缺失、解析失败、或 `tick_size <= 0`，判定为 `MARKET_METADATA_UNAVAILABLE`；
     - **立即 Fail-Closed**：该市场 `is_tradable = False`，拒绝发射任何订单，并向中央中枢上报 `IncidentEvent(SUB_PRICING, METADATA_CORRUPTED, SEV_DEGRADED)`。

---

### 挑战点 6：pUSD 资金模型与入金多代币边界
- **开发端立场**：**【支持，确立系统内“单币种绝缘”原则】**。
- **工程实现原则**：
  1. **系统内部核心账务（S5 / BankrollManager）**：
     - 统一以 **`pUSD`（ERC-20 6 位精度）** 作为法定计价基准（在数值上与 USDC 严格 1:1 对等）；
     - 四桶资金模型、Decimal 定点运算、下注与结算全流程**只认 pUSD**，不引入任何多币种汇率波动逻辑。
  2. **入金（Deposit）边界隔离**：
     - 官方支持的 12+ 种代币充值属于 Polymarket 平台与前端中介桥的职责；
     - 本系统**严格置身于充值兑换之后**，假定自由资金池进入系统时已全部兑付为平台内部的 pUSD，避免在量化交易核心中引入跨币种套期保值复杂度。

---

### 7. 费用精度衔接（官方 5 位 vs 算法 6 位）
- **开发端立场**：**【支持，明确保守防御原则】**。
- **工程处理规范**：
  1. **算法端预算与成本计算**：保持内部 6 位 Decimal 定点计算（`0.000001`）；
  2. **官方费用扣除模拟**：按官方规则 `round(fee, 5)`（最小费用 0.00001，更小舍入为 0）；
  3. **极端边缘价位（1¢ / 99¢）保护**：
     - 即使小单在官方可能被舍入为零费，**算法端在计算 $q_{\text{eff}}$ 时绝不主动抹去费率项**；
     - 保持 $q_{\text{eff}} = \bar{P}[1 + 0.05(1 - \bar{P})]$ 连续函数，坚持最坏情况保守防御（Minimax 精神），避免为了几微美分的免税诱惑去承担长尾逆向选择风险。

---

### 挑战点 8：NegRisk 互补性在 S6 套利通道的利用方式
- **开发端立场**：**【支持正反双轨，确立执行原子性门禁】**。
- **工程实现方案**：
  1. **双轨扫描判定式落位**：
     - **全包 YES 轨**：$\sum_{i=1}^K q_{\text{eff}, i}^{\text{YES}} \le 1 - m_{\text{dutch}}$；
     - **单档反向 NO 轨**：利用 NegRisk 互补性 $\text{NO}_i \equiv \sum_{j \neq i} \text{YES}_j$。当市场上出现 $\text{Ask}(\text{YES}_i) + \text{Ask}(\text{NO}_i) \le 1 - m_{\text{dutch}}$（或盘口价格倒挂）时触发反向配对锁利；
  2. **工程原子性硬门禁（防单腿击穿）**：
     - 现实盘口中，买入全部 11 档 YES 的网络开销与部分滑点极大；
     - **执行约束**：只有当所有拟买腿的 Asks 深度均 $\ge \text{target\_shares}$ 时，才允许同时下发 FAK 并发单；若任一腿成交失败，立即移交 `ResidualHealer` 并在 30s 内强行平价愈合，坚决杜绝敞口暴露。

---

### 挑战点 9：结算时序（整度 + 次日定稿 + 修订影响）对时钟与风控的联动
- **开发端立场**：**【支持，锁定 ADR-0012 物理时钟契约】**。
- **工程联动细则**：
  1. **距结算剩余时间 $t_{\text{remain}}$**：
     - 严格以**台站所属时区的当地自然日 23:59:59 闭合点**计算 $t_{\text{remain}}$（而非粗略的盘口标称时间）；
  2. **次日定稿与 12h 僵尸判定**：
     - 市场官方必须等次日首个数据点发布后方才清算，因此当地次日上午 00:00~12:00 属于正常预言机上链宽限期；
     - **超期 12h（即次日当地 12:00:00）硬红线保持刚性**：超时未结算仓位无条件切入 `Zombie Margin`，触发流动性折剪。
  3. **NWS WRH 整度取值与结算复刻**：
     - 复刻器严格按 `replicate_nws_temperature_rounding(temp_f)`（Decimal `ROUND_HALF_UP`）输出获胜档位，杜绝 Python 银行家舍入错档。

---

## 二、 影响清单落盘执行方案

经上述 9 项挑战与收敛，契约 §七 的 9 项影响项已完全具备工程落地条件。开发端确认在下一阶段对相关文档进行联动收口：

1. **《P7-ALGO-2 规格书》**：
   - §4 M1 / §7：正式将 `base` 参数由 `0.0125 [待核实]` 固化为 **`0.05`**；Maker 返佣标记为“暂不做 maker，不建模（挂起）”；
   - §4 M5：资金计价单位修正为 `pUSD (backed by USDC)`；
   - §4 M4：订单类型正式收敛为 `FAK`（实现 IOC 语义）与 `PostOnly`（挂起备用）；
   - §6：快照输入补充 `market_meta`（含 tick/lot 字段）。
2. **《P7-ALGO-2 算法描述文档》**：
   - §2.2 / §12：有效成本公式更新为 $q_{\text{eff}} = \bar{P}[1 + 0.05(1 - \bar{P})]$；
   - §8.1：新增 tick / lot 离散化 quantize 规则。
3. **《P7-ALGO-2 工程落档细化》**：
   - 增加 `MarketMeta` 数据结构；更新订单下发中的 FAK 参数装配与 Data API v2 端点映射。

---

开发端挑战与工程意见已落盘为 `docs/audit/P7-ALGO-2_市场特性契约_开发端审阅.md`，标志着市场微结构特性契约正式达成共识并闭环！
