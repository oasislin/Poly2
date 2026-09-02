---
created: 2026-09-02 11:32:11
updated: 2026-09-02 11:32:11
---

# Phase 2 执行文件 v1.3：盘口定价、套利与执行引擎

**版本**：v1.3 Engineering-Spec Final  
**前置依赖**：Phase 1 v5.9.2 高斯 EMOS 两级降级模型输出 (μ,σ)(μ,σ)；项目方案 v2.4.1（数据架构与三层预测栈规格）

## 0. 版本变更摘要（v1.2 → v1.3）

1. 数据源陈旧降级条款重写——对齐 v2.4 双轨解耦架构，废弃“结算源与截断层源同源”旧前提；
2. 新增切换窗口短阈值（0.75h）与统一陈旧计时语义（数据时间戳龄，恒定连续）；
3. 新增降级幂等性保证与恢复稳定期机制；
4. 注入式测试 D 拆分为 D1/D2a/D2b/D2c/D3 五用例，全部可被 CI 构造与断言；
5. 工程规范新增第 4 条：凯利优化器输入安全。

## 一、核心目标与系统数据流

Polymarket 温度市场是离散区间的二元期权。Phase 2 的核心任务是将 Phase 1 输出的客观气象学概率分布 (μ,σ)(μ,σ)，与 Polymarket 市场主观报价进行高频比对，在严格控制微观结构摩擦与资金风险的前提下，**将气象预测的物理优势无损耗地转化为账户 USDC 的长期复利增长**。

采用**事件驱动架构**。WSS 秒级盘口推送作为主要触发源，模型重新定价与实况截断层作为辅助触发源。

```
┌──────────────────┐ ┌─────────────────────────┐ ┌──────────────────┐
│  Phase 1 Engine  │ │ Polymarket WSS (Market) │ │  REST /books API │
│  (μ, σ) 输出     │ └───────────┬─────────────┘ └────────┬─────────┘
└────────┬─────────┘             │ (Orderbook Push)       │ (Snapshot)
        │                        ▼                        │
        │             ┌──────────────────────┐             │
        └────────────▶│  Event Trigger Bus   │◀────────────┘
                      └──────────┬───────────┘
                                 ▼
                      ┌──────────────────────┐     ┌──────────────────────┐
   ┌─────────────┐    │   EV Calculator      │◀───▶│  四桶资金状态机       │
   │ METAR 实时流 │───▶│   (Fee Strategy注入) │     │ (Free/Locked/Zombie) │
   │ (高频截断源· │    └──────────┬───────────┘     └──────────────────────┘
   │  常规时段)   │               │ (+EV Signal)      ▲
   └─────────────┘               ▼                   │ (流动性水位约束)
   ┌─────────────┐    ┌──────────────────────┐       │
   │ Wunderground│───▶│  Multinomial Kelly   │───────┘
   │ (结算真值 +  │    │  SLSQP 优化器        │
   │  切换窗截断源 │    └──────────┬───────────┘
   │  阈值 0.75h) │               │ (OrderIntent)
   └─────────────┘               ▼
                      ┌──────────────────────┐
                      │   Order Router       │
                      │ (IOC保护价/残局状态机)│
                      └──────────────────────┘
```

> **数据源双轨说明**：METAR 与 Wunderground 为两个独立输入节点。METAR 承担常规时段的高频截断职责；Wunderground 承担次日结算真值职责，并在结算前口径切换窗口（名义极值时刻前 2h）内临时接管截断职责（阈值 0.75h）。两源的陈旧监测规则详见 §5.2。

## 二、概率映射与摩擦成本模型

### §1 离散概率映射

将 Phase 1 输出的连续高斯分布针对 Polymarket 当日定义的区间边界 [B0,B1,...,Bk][B0​,B1​,...,Bk​] 进行截断积分。

- **计算**：区间 [Bi,Bi+1)[Bi​,Bi+1​) 的模型预测概率 pmodel(i)=Φ(Bi+1−μσ)−Φ(Bi−μσ)pmodel​(i)=Φ(σBi+1​−μ​)−Φ(σBi​−μ​)。
- **精度保护**：使用 `scipy.special.ndtr` 替代 `norm.cdf` 防止极端尾部浮点下溢。所有离散区间 pmodelpmodel​ 之和严格等于 1.0。
- **上游拦截档位处理**：经 `ConstraintEnforcer` 物理硬拦截置 0 的档位，pmodel(i)pmodel​(i) 保持 0.0，正常参与后续 EV 与凯利计算（见 §6 规范 4）。

### §2 摩擦成本与费率策略

**严格遵循开闭原则，EV 计算引擎不与具体的 Taker/Maker 费率硬绑定，而是通过依赖倒置注入费率策略。**  
Polymarket 动态费率公式：Fee=C×feeRate×p×(1−p)Fee=C×feeRate×p×(1−p)。

```
from abc import ABC, abstractmethod

class FeeStrategy(ABC):
    @abstractmethod
    def calculate_fee(self, price: float, size: int, category: str = "Weather") -> float:
        pass

class TakerFeeDynamic(FeeStrategy):
    """Taker 动态费率：C * theta * p * (1-p)"""
    def __init__(self, theta_table: dict, rebate_tier: float = 0.0):
        self.theta = theta_table
        self.rebate = rebate_tier

    def calculate_fee(self, price: float, size: int, category: str = "Weather") -> float:
        theta = self.theta.get(category, 0.05)
        raw_fee = size * theta * price * (1 - price)
        return round(raw_fee * (1 - self.rebate), 5)

class MakerFeePlaceholder(FeeStrategy):
    """Maker 占位符：返回 0 费率，不阻断 EV 计算，未来扩展 Rebate"""
    def calculate_fee(self, price: float, size: int, category: str = "Weather") -> float:
        return 0.0
```

## 三、资金管理与投资组合数学

### §1 四桶资金状态机与全局熔断

Total Bankroll=Free USDC+Active Locked+Zombie Margin+Disputed MarginTotal Bankroll=Free USDC+Active Locked+Zombie Margin+Disputed Margin

1. **全局流动性水位线**：设 70% 为硬性熔断线。分子仅包含 `Active Locked`。若 `Active Locked / Total Bankroll > 0.70`，触发流动性熔断，暂停新开仓。
2. **单市场硬顶**：任何单一互斥市场群，总下注本金绝对不超过 `Total Bankroll` 的 10%。
3. **僵尸仓位隔离**：预期结算时刻 TsettleTsettle​ 后宽限 12h，若未结算则移入 `Zombie Margin`。僵尸资产仍计入 Bankroll 基数，但**从流动性水位线分子中剔除**，防止外部结算延迟引发内部流动性挤兑。

### §2 多项分布联合对数财富最大化

废弃单标的独立凯利公式。对于完备互斥市场，设模型概率 P=(p1..pk)P=(p1​..pk​)，盘口成本 Q=(q1..qk)Q=(q1​..qk​)，下注向量 F=(f1..fk)F=(f1​..fk​)。  
**目标函数**：  

max⁡FG(F)=∑i=1kpiln⁡(1+fiqi−∑j=1kfj)Fmax​G(F)=i=1∑k​pi​ln(1+qi​fi​​−j=1∑k​fj​)

**约束**：fi≥0fi​≥0；∑fj≤min⁡(Wfree,0.10×Bankroll,流动性余量)∑fj​≤min(Wfree​,0.10×Bankroll,流动性余量)。  
采用 SLSQP 数值优化器实时求解 FF，自动消除互斥资产间的负协方差过度下注风险。

### §3 沉没成本增量再平衡

确立“只买不卖、坚决持有到期”原则。若模型概率发生转向，已持仓 N=(N1..Nk)N=(N1​..Nk​) 视为**外生固定收益项**注入增量优化：  

max⁡fGincr(f)=∑i=1kpinewln⁡(Wfree+Ni+fiqi−∑j=1kfj)fmax​Gincr​(f)=i=1∑k​pinew​ln(Wfree​+Ni​+qi​fi​​−j=1∑k​fj​)

  
*注：旧持仓的买入成本基础从公式中彻底消失，实现“向前看”的无平仓对冲。*  
**唯一卖出例外**：若极端反转导致“卖出持仓”的 EV > 5%，触发单次平仓指令。

## 四、订单簿微观结构与执行引擎

### §1 深度穿透防御（IOC 保护价限价单）

**严禁发送纯市价单**。执行器须计算 **EV 零点保护价 PprotectPprotect​**：沿订单簿逐档累计，直至某档使单份 EV < 0（或低于门槛），取前档价格为保护价。  
订单路由下发 **IOC 限价单**，价格锁定 PprotectPprotect​。若发生竞态/撤单，订单最多吃到 PprotectPprotect​ 档即被 Cancel，从数学底层杜绝滑点穿透暴亏。

### §2 残局敞口重估状态机

因 CLOB 不支持原子多腿交易，联合凯利向量 FF 拆单后若发生部分成交残局，触发 `ResidualRiskStateMachine`：

1. **敞口重估**：冻结该市场后续主动下单，拉取最新盘口与 (μ,σ)(μ,σ) 重算。
2. **补单/替代对冲**：若原档位或替代档位在最新概率下仍具 +EV，重新发送 IOC 限价单补全对冲结构。
3. **硬止损平仓**：若盘口干涸无法对冲，且单腿裸敞口风险超红线，强制平仓已成交腿，宁可微小摩擦亏损，不留无保护敞口过夜。

## 五、动态风控与系统韧性

### §1 僵尸仓位阶梯熔断

设全局僵尸率 Rz=(Zombie+Disputed)/Total BankrollRz​=(Zombie+Disputed)/Total Bankroll：

- Rz>15%Rz​>15%：新开仓额度 ×0.5×0.5
- Rz>30%Rz​>30%：暂停新开仓，仅允许残局补单与止损
- Rz>50%Rz​>50%：全系统只读，人工介入

若 UMA 进入 Dispute，仓位移入 `Disputed` 并按期望折价估值（如胜率 0.8/0.2）。

### §2 数据源故障联动降级（v1.3 重写，权威定义）

**陈旧度定义（统一语义）**：任一实时源的陈旧度恒定为  

Age=tnow−tlast_observationAge=tnow​−tlast_observation​

  
即最新观测数据时间戳的龄期，**与监测对象切换时刻、窗口边界完全无关，计时器跨时段连续**。窗口切换仅改变“被监测的源”与“阈值档位”，绝不重置计时器。

**降级触发规则**：当**当前生效截断源**的陈旧度超过**当前时段阈值档位**时，发布 `DATA_STALENESS`（ERROR 级）事件：

|时段|生效截断源|陈旧阈值|监测对象|
|---|---|---|---|
|常规时段|METAR 分钟级实时流|**3.0h**|仅 METAR|
|切换窗口（名义极值时刻前 2h）|Wunderground 实况页|**0.75h（45 分钟）**|仅 Wunderground|

- **窗内短阈值依据**：切换窗仅 2h，若沿用 3.0h 阈值则窗内数学上不可能触发降级，保护形同虚设；取 0.75h 同时满足两个约束——高于 Wunderground 实况页 15~30 分钟自然更新上界 + 余量（防止进入窗口瞬间的假阳性降级），远小于窗长（保证窗内有 1h15m 的可触发区间）。
- **窗内卸责**：切换窗内 METAR 已卸下截断职责，其陈旧不触发降级（防窗口内敏感保护期被 METAR 抖动干扰）；其数据仍照常接收，供窗口结束后恢复常规态使用。
- **跨窗连续性**：若 Wunderground 在常规时段已断流（常规时段其不承担截断职责，不触发），进入切换窗时龄期连续累计，若已超 0.75h 则**进入窗口即触发降级**——切换瞬间源是死的，理应立即降级，无需额外状态跟踪。

**触发后降级动作**：

1. 动态截断层自动下线停用；
2. Effective σ 放大 1.3 倍（保守预测）；
3. EV 下单门槛由 0.03 上调至 0.05（两态配置固化，联动写入配置，不得静态单值）。

**幂等性保证**：降级动作为**状态机一次性迁移**，重复或并发的 `DATA_STALENESS` 事件（含双源同时断流场景）**不叠加降级系数**；状态恢复仅在生效源龄期回落至当前阈值以下且持续一个稳定期（15min）后执行。

**告警契约**：`DATA_STALENESS`（ERROR 级）是 Phase 2 降级状态机的**唯一触发信号源**，与项目方案 v2.4.1 §5 的事件契约耦合；截断层缺测回退产生的 `WARNING` 级事件作为降级加权的辅助参考信号，不直接触发降级。

**风险边界澄清**：结算源（Wunderground 日极值）的可用性故障属另一风险类别，由 §1 僵尸仓位隔离机制管辖，不归本条管辖。

### §3 阈值参数化配置

```
staleness:
  normal_threshold_hours: 3.0          # 常规时段（METAR）
  switch_window_threshold_hours: 0.75  # 切换窗口（Wunderground）
  switch_window_before_peak_hours: 2.0 # 切换窗定义
  recovery_stable_minutes: 15          # 恢复稳定期
```

## 六、工程级实现规范

1. **量纲与精度基准**：系统内部所有资金与份额的计算均统一在 USDC 浮点数层面进行。由于 `1 Share = 1 USDC`，NiNi​ 在参与增量凯利计算时直接视为等额 USDC 期望值。API 接口层做边界转换（链上 BigInt 考虑 6 位小数，内部 Float64）。
2. **SLSQP 优化器鲁棒性**：初始猜想 x0x0​ 强制设为 `np.full(k, 1e-4)` 微小正数向量。若 SLSQP 未收敛或抛出异常，**严禁使用残缺结果**，必须捕获异常并将当次增量下注向量设为零向量。
3. **资金状态机并发互斥锁**：从 WSS 触发 EV 计算到 API 发单存在时间差，必须使用 `asyncio.Lock` 保护 `Free USDC` 的读取与扣减，绝对防止并发信号导致同一笔现金被重复分配。
4. **凯利优化器输入安全（v1.3 新增）**：`ConstraintEnforcer` 物理硬拦截产生的 pi=0pi​=0 档位，在 SLSQP 目标函数中必须保持“pipi​ 在乘法侧为零”的写法（pi⋅ln⁡(⋅)pi​⋅ln(⋅) 贡献为零），**严禁预计算 ln⁡(pi)ln(pi​)**（将直接产生 NaN）。同时对 pmodel≥0.995pmodel​≥0.995 的确定性档位施加**额外下注上限**（防止单档确定性赌注吃满 10% 单市场硬顶后遭遇极小概率黑天鹅，如结算口径争议）。

## 七、注入式故障测试套件（CI/CD 验收门禁）

**Test-Scenario A（多项凯利与沉没成本断言）**：  
构造 4 档位市场，注入初始 pmodel=[0.1,0.6,0.2,0.1]pmodel​=[0.1,0.6,0.2,0.1]，买入 100 份档位 2；模拟突发冷空气，注入新分布 pmodelnew=[0.5,0.1,0.3,0.1]pmodelnew​=[0.5,0.1,0.3,0.1]。  
*断言*：求解器输出增量 ΔfΔf 集中于档位 1，旧持仓作为外生项不影响新增资金分配，绝不发生报复性补仓放大。

**Test-Scenario B（订单簿深度穿透与 IOC 截断断言）**：  
Mock 一个总深度仅 50 份但买单需求 200 份的盘口，后序档位价格剧烈恶化。  
*断言*：发单价格严格等于 PprotectPprotect​，回报仅成交 50 份，剩余 150 份被 IOC 撤单，且成交均价满足 EV > 0。

**Test-Scenario C（僵尸仓位与流动性隔离断言）**：  
注入 3 笔 72 小时未结算的“僵尸仓位”，使其占总资产 25%。  
*断言*：70% 流动性水位线分子不包含该 25% 资金；新市场发出的下注额度触发 15% 僵尸熔断阈值，自动按 0.5 倍系数折剪。

**Test-Scenario D1（常规时段 METAR 断流断言）**：  
模拟常规时段 METAR 流断流，推进仿真时钟使 METAR 数据龄期 > 3.0h；**同时 Wunderground 结算源 mock 保持正常（日极值拉取可用），且 Wunderground 实况龄期任意**。  
_断言_：`DATA_STALENESS` 事件发布、截断层状态 Disabled、Effective σ 含 1.3x 系数、EV 门槛更新为 0.05；**且该降级与 Wunderground 可用性完全无关**。

**Test-Scenario D2a（切换窗 Wunderground 断流正断言）**：  
模拟进入切换窗后，冻结 Wunderground 实况（最后一帧龄期从 30min 起算），推进仿真时钟至龄期 **> 0.75h（45min）**。  
_断言_：`DATA_STALENESS` 发布、截断层 Disabled、σ×1.3、EV 门槛 = 0.05。

**Test-Scenario D2b（切换窗假阳性防御负断言）**：  
模拟进入切换窗时 Wunderground 龄期恰为 30min（其自然更新上界的健康状态）。  
*断言*：**不触发**降级；同场景下 METAR 即使断流也**不触发**降级（已卸截断职责）。

**Test-Scenario D2c（跨窗计时连续性断言）**：  
模拟 Wunderground 在常规时段断流 1h（此时不触发，因其不承担截断职责），随后进入切换窗。  
*断言*：进入窗口时龄期连续累计（1h > 0.75h），**立即触发降级**——固化“计时器跨时段连续、无重置”语义。

**Test-Scenario D3（降级幂等性断言）**：  
构造双源同时断流或短窗口内连续多次超阈值的场景。  
*断言*：降级动作仅执行一次状态迁移，σ 系数恒为 1.3（不叠加为 1.69），EV 门槛恒为 0.05；源恢复且稳定期（15min）未满前，状态不翻转回常规态。

## 八、验收标准

1. **映射准确性**：所有离散区间 pmodelpmodel​ 之和严格等于 1.0（允许 10−610−6 浮点误差）。
2. **架构解耦**：单元测试覆盖 `EVCalculator` 注入 `MakerFeePlaceholder` 时，能在不触发任何 Taker 硬编码逻辑的情况下正确计算 EV。
3. **资金安全性**：Test Scenario A~D3 全部通过断言；流动性不足或残局发生时，下注量自动缩减或阻断，绝不产生穿透或裸敞口过夜。
4. **降级链路正确性**：双源陈旧监测在各自职责时段内独立有效，切换窗短阈值（0.75h）与跨窗计时连续性语义经 D1/D2a/D2b/D2c/D3 全覆盖验证，无假阳性、无保护真空。
5. **历史回测**：多项联合凯利策略回测夏普比率 > 2.0，最大回撤 < 15%，无单日爆仓记录。

## 九、版本修订留痕（v1.3 Changelog Detail）

|修订项|v1.2 原文|v1.3 定稿|修订依据|
|---|---|---|---|
|§5.2 降级触发前提|“Wunderground 实况断流（结算源与截断层源同源故障）”|“当前生效截断源陈旧度超当前时段阈值”，双源并行独立监测|v2.4 §2.3 双轨解耦决策，旧单源前提失效|
|§5.2 切换窗阈值|无（单一 3.0h）|切换窗内 0.75h|修复 2h 窗长 vs 3h 阈值的量纲矛盾；0.75h 高于 Wunderground 30min 自然更新上界防假阳性|
|§5.2 计时语义|未定义|数据时间戳龄，恒定连续，跨窗不重置|消灭计时起点歧义，D2c 固化语义|
|§5.2 幂等性|未定义|状态机一次性迁移 + 15min 恢复稳定期|双源同时断流不叠加降级系数|
|§7 Test D|单用例"实况断流>3h"|拆分为 D1/D2a/D2b/D2c/D3 五用例|原用例在切换窗内无法构造，且无法验证负向防御与幂等性|
|§6 规范|3 条|4 条（新增凯利输入安全）|承接项目方案 §3.3 观察点|
|§1 数据流图|Wunderground 单输入|METAR / Wunderground 双输入节点，标注职责与阈值|图文同步|

**最终状态声明**：项目方案 **v2.4.1 Final** 与 Phase 2 执行文件 **v1.3 Final**（连同未动的 Phase 1 执行文件 v5.9.2）三方完全对齐——项目方案 v2.4.1 §5 已同步 v1.3 的两档阈值口径，并通过“参数权威权属声明”将后续参数维护权单一化归属执行文件，杜绝跨文档漂移。无遗留矛盾、无 Pending 项，可交付编程 Agent 启动 Phase 1 收尾（Step 1.5）与 Phase 2 脚手架开发。