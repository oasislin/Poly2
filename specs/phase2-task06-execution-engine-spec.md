# 规格书：CLOB 执行引擎、IOC 保护价限价单路由与非原子成交残局状态机 (Phase 2 Task 06)

- **Spec Issue**: [#88](https://github.com/oasislin/Poly2/issues/88) (Spec: Phase 2 Task 06 - CLOB 执行引擎、IOC 保护价限价单路由与非原子成交残局状态机)
- **Tickets**:
  - `Phase 2 Task 06 - Ticket 01`: [#89](https://github.com/oasislin/Poly2/issues/89)
  - `Phase 2 Task 06 - Ticket 02`: [#90](https://github.com/oasislin/Poly2/issues/90)
  - `Phase 2 Task 06 - Ticket 03`: [#91](https://github.com/oasislin/Poly2/issues/91)
  - `Phase 2 Task 06 - Ticket 04`: [#92](https://github.com/oasislin/Poly2/issues/92)
  - `Phase 2 Task 06 - Ticket 05`: [#93](https://github.com/oasislin/Poly2/issues/93)

---

## 一、 问题陈述 (Problem Statement)

在去中心化预测市场（如 Polymarket CLOB）的温度合约交易中，由于气象概率分布由多个离散温区档位互斥完备组成，且链下撮合/链上结算具有薄流动性与非原子性，直接下单面临三大执行级系统性风险：
1. **订单簿流动性薄弱与市价单击穿穿仓**：
   预测市场冷门档位挂单深度极浅。若直接下发市价单或无保护限价单，会连续吃穿深层极高价格的挂单，导致实际成交均价对应的期望收益暴跌为负（$\overline{\text{EV}} \ll 0$），产生毁灭性滑点甚至瞬间穿仓；
2. **多档位跨区间撮合的非原子性与裸露残局风险**：
   依据多项联合凯利优化器输出的向量，系统可能需要在同一市场的多个档位同时建仓。但在去中心化订单簿撮合中，多笔订单的撮合是彼此独立的非原子事件（Non-Atomic Partial Fills）。一旦出现“某一单腿成交、其余档位因深度不足或价格触顶被撤销”，系统将陷入极度危险的“单腿裸露残局”（Residual Exposure），彻底破坏原有的概率分布对冲结构；
3. **风控前置拦截与异常熔断迟滞**：
   若执行引擎与统一异常仲裁中枢（ADR-0014）以及两维阶梯风控（ADR-0011）脱节，在台站数据流丢心跳（>15m/30s）或临近关盘突发剧烈气温震荡时，仍然继续盲目发单，将被场内套利者逆向选择严重蚕食。

---

## 二、 解决方案与数学契约 (Architecture & Mathematical Contracts)

严格遵从《Phase 2 执行文件 v2.0》§4、§5 及 ADR-0011 ~ ADR-0014 规范，在 `src/execution/` 下构建生产级执行系统：

### 1. 绝对禁止市价单与 IOC 保护价限价单路由 (`OrderRouter`)
- **零市价单铁律**：系统内部代码与客户端接口严格禁止 `MARKET` 订单类型，任何尝试下发市价单的行为在接口层触发异常拦截；
- **保护价定位算法**：
  对拟买入档位，消费微观订单簿深度 asks（按价格升序），遍历档位 $k \in \{1, \dots, M\}$：
  $$\text{EV}_k = \frac{p_{\text{model}} - P_k}{P_k}$$
  寻找满足 $\text{EV}_k < \text{min\_edge}$（默认 0% 或配置阈值）的第一个档位 $k^*$，将其前一档价格锁定为保护价：
  $$P_{\text{protect}} = P_{k^* - 1}$$
  若所有可用卖单均满足 $\text{EV} \ge \text{min\_edge}$，则以满足正期望的最大价格（或 $p_{\text{model}} - \epsilon$）作为保护价。
- **IOC 组装与自动撤销**：
  订单类型严格设为 `IOC`（Immediate-Or-Cancel），以 $P_{\text{protect}}$ 为限价。订单进入撮合引擎时，仅撮合 $\le P_{\text{protect}}$ 的流动性；一旦深度不足或价格超过 $P_{\text{protect}}$，剩余部分由 CLOB 协议自动撤单，**数学上严格保证实际成交均价期望收益恒为正（$\overline{\text{EV}} > 0$）**。

### 2. 非原子成交残局三级自愈状态机 (`ResidualRiskStateMachine`)
- **残局风险监控**：当多档位 IOC 订单部分成交、部分撤单时，立即触发残局状态机：
  1. **实时残差 EV 重算**：
     结合最新已成交持仓向量 $\mathbf{N}_{\text{filled}}$ 与最新 EMOS 概率分布 $\mathbf{p}_{\text{model}}$，计算残余组合的净期望收益与最大回撤/VaR；
  2. **限价补单对冲 (Rehedge)**：
     若盘口仍有正期望且符合单市场 10% 资金上限的对冲档位，生成次优限价单补充对冲，消除单腿裸露；
  3. **确定性保守硬止损 (Hard Stop Loss)**：
     若超过时限（默认 30 秒）仍无法补齐对冲，或裸露持仓下行风险超过预设容忍度，果断下发保守平仓/对冲单锁定止损，绝不放任敞口裸露至自然日结算。

### 3. 两维阶梯风控与异常中枢联动 (`TwoDimensionalRiskController` & `CentralExceptionArbiter`)
- **两维阶梯风控控制器**：
  - **临界区**（距离关盘时间 $T_{\text{remain}} < 1.0\text{h}$ 且残差气温 $\Delta T = |T_{\text{bin}} - T_{\text{now}}| > 3.0^\circ\text{F}$）：强制下注额度折剪至 0.2 倍；
  - **确定区**（$\Delta T \le 0.5^\circ\text{F}$ 且 $T_{\text{remain}} < 0.5\text{h}$）：锁定胜利果实，禁开异向投机单；
- **异常中枢与本地硬阀门联动**：
  - 订单路由前置调用 `CentralExceptionArbiter.is_station_tradable(station_id)` 及 `LocalHardValve.assert_can_emit(station_id)`；
  - 若台站处于 `SUSPENDED` 或数据流心跳中断超限，瞬时拒绝新单；
  - 触发异常时毫秒级下发 `cancel_all_orders(station_id)` 撤销排队挂单，同时绝缘已成交持仓（杜绝恐慌践踏平仓）。

### 4. 全链路 Decimal 定点数截断
- 订单价格（精确到 4 位小数）、订单数量（精确到 6 位小数）、资金出入（USDC）全流程使用 Python `Decimal`，除法与份额换算一律采用 `ROUND_DOWN` 截断，杜绝浮点累积误差与资金账面撕裂。

---

## 三、 垂直切片与落地计划

- **Ticket 01 (`#89`)**: `feat(execution): CLOB 订单数据模型、签名器桩与基础接口契约`
  - 落地 `src/execution/models.py` 与 `src/execution/clob_client.py`
  - 单元测试：`tests/unit/execution/test_clob_models_client.py`
- **Ticket 02 (`#90`)**: `feat(router): 深度穿透防御 IOC 保护价限价单计算与路由分发器`
  - 落地 `src/execution/order_router.py`
  - 单元测试：`tests/unit/execution/test_order_router.py`
- **Ticket 03 (`#91`)**: `feat(residual): 非原子成交残局风险评估与补单对冲/止损状态机`
  - 落地 `src/execution/residual_risk.py`
  - 单元测试：`tests/unit/execution/test_residual_risk.py`
- **Ticket 04 (`#92`)**: `feat(integration): 串联两维阶梯风控与统一异常中枢熔断阻断门禁`
  - 落地 `src/risk/two_dimensional_risk.py` 与 `src/execution/execution_engine.py`
  - 单元测试：`tests/unit/execution/test_execution_engine.py`
- **Ticket 05 (`#93`)**: `test(acceptance): CLOB 执行全链路与 Test-Scenario B 深度击穿防御验收门禁`
  - 落地 `tests/integration/test_scenario_b_ioc_execution.py`

---

## 四、 验收测试标准

1. **Test-Scenario B 深度击穿防御断言**：
   - 构造流动性匮乏的薄盘口，断言仅成交安全档位，超出保护价的超额订单被 IOC 自动撤销；
   - 断言实际成交均价的期望收益 $\overline{\text{EV}} > 0$。
2. **非原子残局自愈与止损断言**：
   - 模拟单腿成交场景，断言状态机平稳启动残差 EV 重算，支持限价补单或 30 秒超时确定性止损。
3. **两维阶梯与异常中枢断言**：
   - 临界区额度折剪 0.2，确定区拦截异向投机单；
   - 台站挂起或心跳超时 0ms 阻断。
4. **全库回归与冒烟纪律**：
   - 真实 GEFS 网络冒烟全绿；
   - 全库测试 100% 绿灯通过。
