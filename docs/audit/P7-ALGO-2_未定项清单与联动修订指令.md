<!-- 供开发端 Agent 读取与执行 | 日期: 2026-10-14 | 角色: 主导方（技术审核 Agent） -->
# P7-ALGO-2 未定项清单与三份文档联动修订指令 v1.0

> **用途**：随联动修订指令一并转开发端。明确"框架已定稿 vs 数值挂锁 vs 工程细节留白"的边界，防止修订过程中把未定数值误当定稿、或把挂锁项提前解锁。
> **实证基础**：本清单已核对 `P7-ALGO-2_工程落档细化.md` v1.1 源码级参数（Grep/Read 实证）：开发端已正确打标——`base_fee=0.0125 [待核实]`、`min_edge=0.02 [待标定]`、`margin_dutch [待标定]`、`θ/η/δμ/δσ [F-2 LOCKED]`；**早期印象中"initial_target_alloc_pct / rebalance_cooldown_minutes / advisor_risk_metrics_500 未裁决"在 v1.1 中不存在，作废**。

---

## 一、未定项全景（三层边界，修订时必须遵守）

### 第一层：已完全定稿（只回填，不重设计）

| 项 | 定稿位置 | 修订动作 |
| :--- | :--- | :--- |
| 多项凯利目标函数 + 凹性引理 1~3 + SLSQP 全局收敛 | 规格书 §3.3 | 不动 |
| 有效成本公式 `q_eff = P̄[1+base(1−P̄)]` | 算法描述 §2.2 | **仅回填 base: 0.0125→0.05** |
| 不确定集 `SE_i = max(SE_EMOS,i, η√(p̂(1−p̂)))` + Delta Method | 算法描述 §4 | 公式不动（η 值挂锁见第二层） |
| 贪心最坏投影（连续背包 LP O(K log K)） | 算法描述 §5 | 不动 |
| 门禁 G1~G7 + ALL_SYSTEMS_PASS | 规格书 §7 | 不动 |
| 套利双轨判定式 | 算法描述/规格书 S6 | 不动 |
| tick/lot 量化管道（全 ROUND_DOWN 时序铁律） | 开发端审阅报告挑战点 4 | **回填进落档细化** |
| 结算复刻（NWS WRH / ROUND_HALF_UP / 次日定稿 / 12h 僵尸） | ADR-0012 | 不动 |
| 市场契约 9 项影响清单（8 定案 + 1 待细化） | 市场特性契约 §七 | 本次回填主体 |

### 第二层：数值未定、机制已定（全部已打标，F-2 绿灯前禁动）

| 参数 | 当前状态 | 锁定/解锁依据 |
| :--- | :--- | :--- |
| base_fee | `0.0125 [待核实]` → **本次回填 0.05**（非标定，是官方定案回填） | 市场特性契约 v1.0 §1.4 |
| min_edge | `0.02 [待标定]`（edge 阈值机制已定：`edge ≥ min_edge` 才入队） | F-2 优先律：概率层 ECE/CRPSS 绿灯前不标定 |
| margin_dutch | `[待标定]`（用户裁决：不继承 v1，重新标定） | 用户 2026-10-13 裁决 |
| θ / η / δμ / δσ | `[F-2 LOCKED]`（不确定集公式已定，数值锁） | F-2 优先律 |
| 凯利分数缩放 / sizing 调优 | `[F-2 LOCKED]`（规格书结构可写、标定挂锁） | F-2 优先律 |
| ECE 阈值 | 继承模型训练/抽检口径 + 联动调整契约（不新增标定模块） | 用户确认 |
| 带旗资产 | 一律不交易（Paper/Live 只观测不入场）；FAILSAFE 只读 | 用户裁决方案 A |

### 第三层：概念已定、实现细节留白（本次修订的主要设计工作）

| 项 | 已定约束 | 留白内容（需细化到可编码） |
| :--- | :--- | :--- |
| ResidualHealer | 30s 平价愈合、单腿失败移交 | 买回量/价格/腿间优先级的确定规则；与 SKIPPED 日志 Tag 的衔接 |
| settlement_sim / paper_engine | 模块职责已定（自产订单簿、结算时序推演、metrics） | 模拟循环细节：快照频率、成交撮合规则、结算判定时序 |
| Data API v2 接入 | 端点 `data-api.polymarket.com/v2`、token_id、cursor 分页、Airgap Cache + RateLimiter 18/s | 缓存 schema（Parquet/SQLite 字段）、429 指数退避参数、冷热缓存一致性 |
| MarketMeta | 字段：tick_size/minimum_order_size/clobTokenIds/fee_rate；盘前缓存 + 决策时深拷贝冻结；缺失→is_tradable=False | 完整数据类定义、gamma API 拉取任务、校验规则（tick_size>0 等） |
| tick/lot 实例值 | 机制：运行时读元数据 | 真实值待对接冒烟实测（闭环后契约 🔶→✅） |
| OrderRouter 订单下发 | 类型已定 FAK（禁 Market） | 当前 v1.1 写"下发 IOC 限价单"→ **回填 FAK**（见修订指令 3.4） |

---

## 二、三份文档联动修订指令

### 修订总则
- 三份文档各升一个版本，头部标注 **"已对齐 Polymarket 市场特性契约 v1.0（2026-10-14）"**；
- **只回填、不重设计**：第一层定稿公式一律原样保留；第二层挂锁项一律维持 [F-2 LOCKED]/[待标定] 标签，**不得填入虚假实值**；第三层细化不得与已定约束冲突；
- 修订完成后，附"修订对照表"（旧值→新值→来源），供主导方复核。

### 修订范围

**1.《P7-ALGO-2 规格书》→ v0.4**
- §4 M1/M-2：`base` 由 `0.0125 [待核实]` → **`0.05`**（官方 Weather taker 系数，来源 docs.polymarket.com/trading/fees）；Maker 返佣标记"暂不做 maker，不建模（挂起，官方 Weather 备查 25%）"；
- §4 M5：资金计价单位 → **pUSD（backed by USDC）**，入金 12+ 代币由平台中介处理、核心单币种绝缘；
- §4 M4：订单类型收敛 **FAK**（IOC 语义）+ PostOnly（挂起备用 RESERVED_SUSPENDED）；
- §6 快照输入：新增 **market_meta**（tick/lot/fee 参数读取）；
- §7 参数挂锁表：保持第二层全部挂锁状态不变，逐项复核标签。

**2.《P7-ALGO-2 算法描述文档》→ v0.4**
- §2.2：有效成本公式回填 `q_eff = P̄[1 + 0.05(1−P̄)]`；
- §8.1：新增 **tick/lot 离散化 quantize 规则**（时序铁律：f* → 精度收口 1e-6 ROUND_DOWN → 保护价穿透 → quantize_to_tick → quantize_to_lot → 最小订单门禁 SKIPPED_BELOW_MINIMUM_ORDER_SIZE）；
- §12：Data API v2 端点映射（`/v2/prices-history?token_id=` + cursor）与费用精度衔接（官方 5 位 / 算法 6 位，极端价位不抹费率）。

**3.《P7-ALGO-2 工程落档细化》→ v1.2**
- 新增 `MarketMeta` 数据类与 gamma 拉取/校验任务；
- `OrderRouter.route_allocations`：订单类型回填 FAK；补 tick/lot 量化管道与最小订单门禁；
- 数据层：Data API v2 接入（Airgap Cache + RateLimiter 18/s + 429 退避）与端点映射；
- 挑战点 8 落地：S6 双轨判定 + 并发 FAK 原子性门禁 + ResidualHealer 30s 愈合；
- 挑战点 9 落地：t_remain 以台站当地自然日 23:59:59（ADR-0012）+ 12h 僵尸红线 + ROUND_HALF_UP；
- 参数表：复核所有标签（base_fee=0.05 回填后改标 ✅官方定案；min_edge/margin_dutch 维持 [待标定]）。

---

## 三、开发端需要回执的确认点（随修订稿一并返回）

1. 修订对照表（每处旧值→新值→官方来源 URL）是否齐全；
2. 第二层挂锁项是否全部维持原标签、未填虚假实值；
3. 第三层细化项是否与已定约束（契约 v1.0 / 开发端审阅报告 9 项）无冲突；
4. 有无发现新的实现级阻塞（如 gamma 元数据实际缺字段、Data API v2 实测差异），如有则列为新增待核实项，**不擅自绕过**。

*本清单 v1.0 由主导方编制，经用户确认后随联动修订指令转开发端。*
