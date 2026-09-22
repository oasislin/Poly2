# 规格书：四桶资金状态机、僵尸仓位双轨估值与多项联合凯利优化器 (Phase 2 Task 05)

- **Spec Issue**: [#82](https://github.com/oasislin/Poly2/issues/82) (Spec: Phase 2 Task 05 - 四桶资金状态机、僵尸仓位双轨估值与多项联合凯利优化器)
- **Tickets**:
  - `Phase 2 Task 05 - Ticket 01`: [#83](https://github.com/oasislin/Poly2/issues/83) (Frontier)
  - `Phase 2 Task 05 - Ticket 02`: [#84](https://github.com/oasislin/Poly2/issues/84)
  - `Phase 2 Task 05 - Ticket 03`: [#85](https://github.com/oasislin/Poly2/issues/85) (Frontier)
  - `Phase 2 Task 05 - Ticket 04`: [#86](https://github.com/oasislin/Poly2/issues/86)
  - `Phase 2 Task 05 - Ticket 05`: [#87](https://github.com/oasislin/Poly2/issues/87)

---

## 问题陈述 (Problem Statement)

在 Polymarket 温度量化交易中，资金管理是决定长期几何复利增长与杜绝破产穿仓的最核心防线。传统量化系统在预测市场多档位下注与去中心化清算延迟上面临四大根本性痛点：
1. **资金池划分模糊与浮点尾差撕裂**：将链上未结算资金与可用资金混为一谈；且在频繁的份额乘除与出入金中若采用浮点运算（IEEE 754 浮点累积误差），会导致账户账面资产与链上 USDC 实际余额发生微小尾差撕裂，诱发资金总账破裂（Broken Ledger）；
2. **结算延迟传染与母数虚高爆仓**：Polymarket 去中心化预言机由于链上拥堵或节假日可能延迟数小时结算，原方案若将这些迟迟未结算的头寸继续计入总资产并充当后续下注的安全垫母数，一旦遭遇极端行情或争议冻结，将引发毁灭性的母数虚高连锁爆仓；
3. **沉没成本与多档位对冲失真**：当天气概率由于突发冷空气剧烈跳变时，散户往往陷入“沉没成本谬误”盲目割肉或重仓补仓；若凯利公式仅针对单档位独立求解，将违背温度市场各档位互斥完备的几何约束，导致总体下注比例超出最优边界；
4. **流动性过度占用与单点暴露**：缺乏对账户全局资金占用率（Utilization Ratio）和单一气象市场最大持仓的硬性约束，极易在单日恶劣天气中将所有本金压满，丧失后续交易流动性。

---

## 解决方案 (Solution)

严格依据已裁决落地的 `ADR-0012`（法定结算真值源、僵尸仓位双轨估值与舍入闭环）及《Phase 2 执行文件 v2.0》§3、§4 规范，在 `src/bankroll/` 架构生产级资金管理与仓位最优化系统：

1. **四桶资金状态机与全局 Decimal 截断舍入闭环 (`BankrollManager`)**：
   - 确立四桶资金恒等式：
     $$\text{Total Bankroll} = \text{Free USDC} + \text{Active Locked} + \text{Zombie Margin} + \text{Disputed Margin}$$
   - 全流程资金出入、锁定、释放、下注运算**强制使用 Python `Decimal` 定点小数**（精度 $10^{-6}$ USDC，对齐链上 ERC-20 标准）；
   - 除法运算严格采用 `ROUND_DOWN` 截断，杜绝向下一分钱透支。
2. **僵尸仓位双轨制估值与流动性阶梯熔断 (`ZombieEvaluator`)**：
   - **12h 触发硬红线**：超过当地自然日闭合预期结算时点 12h（即次日当地中午 12:00:00）链上仍未清算的仓位，无条件移入 `Zombie Margin`；
   - **双轨估值分离原则 (ADR-0012 §D4)**：
     - **下注母数轨（Trading Book）**：计算凯利母数时，`Zombie Margin` 与 `Disputed Margin` **严格按 0.0x 剔除**：
       $$\text{Bankroll}_{\text{effective}} = \text{Free USDC} + \text{Active Locked}$$
       不可流通资金绝对禁止作为下注安全垫，彻底切断外部清算延迟向内部交易的风险传染；
     - **财务净值轨（Financial NAV Book）**：维持账面平稳，对僵尸仓位计提 10% 流动性冻结折价：$V_{\text{zombie}} = 0.90 \times \mathbb{E}[V]$；争议资金计提折价：$V_{\text{disputed}} = \min(0.50 \times \text{Cost}, P_{\text{model}} \cdot \text{Shares} \cdot 0.60)$；
   - **名义僵尸率阶梯流动性熔断（$R_z = \frac{\text{Nominal Zombie} + \text{Nominal Disputed}}{\text{Total Bankroll}}$）**：
     - $R_z > 15\%$：新开仓额度强制打折 $\times 0.5$；
     - $R_z > 30\%$：暂停新开仓，仅允许残局补单与硬止损；
     - $R_z > 50\%$：系统切入只读 `SAFE_MODE`，呼叫人工处置。
3. **多项联合增量对数财富最大化凯利优化器 (`MultinomialKellyOptimizer`)**：
   - 目标函数：
     $$\max_{\mathbf{f}} G_{\text{incr}}(\mathbf{f}) = \sum_{i=1}^k p_i^{new} \ln\left(W_{\text{free}} + N_i + \frac{f_i}{q_i} - \sum_{j=1}^k f_j\right)$$
   - 将既有旧持仓 $N_i$ 作为外生确定项注入，只买不卖，零摩擦自然向前对冲；
   - 对数输入严格守卫：内部表达式必须 $> 0$，趋近边界施加极大数值惩罚，杜绝数值爆炸与奇异值；
   - 优化求解：使用 `scipy.optimize.minimize` (SLSQP 算法)，初值设为 $10^{-4}$；
   - **Fail-Closed 安全回退**：若优化器未收敛、超出迭代或抛出异常，强制回退为全零向量 $\mathbf{f} = \mathbf{0}$。
4. **单市场 10% 硬顶与全局 70% 流动性警戒线 (`RiskLimiter`)**：
   - 单市场硬顶：单一互斥温度市场的总持仓敞口（历史旧持仓成本 + 本次增量拟买入金额）不得超过有效总资金的 10%：
     $$\sum_{i \in \text{Market}} (\text{Cost}_{old, i} + f_i) \le 10\% \times \text{Bankroll}_{\text{effective}}$$
   - 全局流动性占用率：$\text{Utilization} = \frac{\text{Active Locked}}{\text{Total Bankroll}} \le 0.70$（分子坚决剔除 Zombie 与 Disputed）。

---

## 用户故事 (User Stories)

1. 作为资金风控官，我希望系统的资金状态机将可用资金、活跃锁定、超时僵尸与争议资金物理隔离为四个独立桶，以便清晰把控资产流动性全貌。
2. 作为量化总账会计，我希望所有资金计算全流程采用 Python Decimal 定点截断，以便杜绝浮点误差累积导致账面与链上余额偏差。
3. 作为交易策略架构师，我希望计算凯利下注母数时坚决将僵尸仓位与争议资金按 0.0x 完全清零，以便杜绝因预言机链上结算滞后引发母数虚高的爆仓风险。
4. 作为交易算法工程师，我希望多项联合凯利优化器将既有旧持仓作为外生确定项直接注入对数财富目标函数，以便在概率突变时只买不卖，实现零手续费摩擦的自然正向对冲。
5. 作为执行交易员，我希望优化器在发生未收敛或数值异常时自动 Fail-Closed 回退为全零开仓，以便绝对不盲目下发未经数学严格验证的仓位向量。
6. 作为系统风险经理，我希望单市场最大总下注金额严格锁定在 10% 以内，全局活跃锁定不超过 70%，以便保证极端恶劣天气下系统具备持续的自愈与周转能力。
7. 作为质检工程师，我希望通过完整的 Test-Scenario A（增量凯利断言）与 Test-Scenario C（僵尸双轨估值与 Decimal 精度断言）集成套件，确保资金与仓位模块的数学正确性。

---

## 实现决策 (Implementation Decisions)

- **核心接口与分层设计**：
  - `src/bankroll/bankroll_manager.py`：实现 `BankrollManager`，维护 `FourBucketBalance` 状态机，提供出入金、锁定、成交扣减、结算释放等事务接口；
  - `src/bankroll/zombie_evaluator.py`：实现 `ZombieEvaluator`，监控物理时钟 12h 阈值，输出双轨估值（母数轨 0.0x、净值轨折价）与阶梯流动性熔断指标；
  - `src/bankroll/multinomial_kelly.py`：实现 `MultinomialKellyOptimizer`，使用 SLSQP 算法求解增量对数财富最大化问题，内置对数输入守卫与全零安全回退；
  - `src/bankroll/risk_limiter.py`：实现 `RiskLimiter`，施加 10% 单市场上限、70% 全局流动性上限与阶梯额度折剪。
- **配置持久化规范**：
  - 在 `configs/default.yaml` 中新增/规范 `bankroll` 与 `kelly` 受控配置节（`max_active_utilization: 0.70`, `single_market_max_pct: 0.10`, `zombie_grace_hours: 12.0`, `zombie_haircut: 0.10`, `disputed_haircut: 0.50`）。
- **Active 10 交易宇宙锁定**：
  - 仓位记录按 Active 10 站 (`KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS`) 隔离跟踪。

---

## 测试决策 (Testing Decisions)

- **单元与组件测试**：
  - `test_bankroll_manager.py`: 验证四桶平衡守恒性、Decimal 定点截断舍入、出入金与锁定释放事务；
  - `test_zombie_evaluator.py`: 验证超过 12h 触发僵尸状态转移、母数轨 0.0x 剔除、净值轨 10% 折价与名义僵尸率阶梯熔断；
  - `test_multinomial_kelly.py`: 验证多项凯利分配、旧持仓沉没成本注入、对数输入守卫、未收敛全零回退；
  - `test_risk_limiter.py`: 验证单市场 10% 硬顶拦截、70% 全局流动性超标拦截与阶梯折半。
- **集成与验收测试 (Test-Scenario A & C)**：
  - `tests/integration/test_scenario_a_c_bankroll_kelly.py`:
    - **Scenario A**: 构造 4 档位市场，模拟冷空气概率突变，断言增量资金精准分配，旧持仓外生隔离无放大；
    - **Scenario C**: 注入超期 12h 未结算仓位，断言从 Active Locked 剔除，下注母数严格扣减，全流程 Decimal 零精度撕裂。
- **网络与冒烟硬性纪律**：
  - 持续保证真实 GEFS 网络冒烟绿灯：
    `RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`。

---

## 范围外声明 (Out of Scope)

- CLOB 订单签名、IOC 限价单路由与非原子成交残局处理（属于 Task 06 范畴）；
- 两维阶梯风控联动实盘 48 小时纸面模拟（属于 Task 07 范畴）。

---

## 任务垂直切片拆分 (Tickets Breakdown)

1. **`Phase 2 Task 05 - Ticket 01: feat(bankroll): 四桶资金状态机与全局 Decimal 截断舍入闭环`**
   - **内容**：实现 `src/bankroll/bankroll_manager.py`，管理四桶资金状态机（Free USDC, Active Locked, Zombie Margin, Disputed Margin），全流程使用 Decimal 截断计算，提供出入金与仓位锁定释放接口；
   - **依赖**：无（Frontier）。

2. **`Phase 2 Task 05 - Ticket 02: feat(zombie): 僵尸仓位双轨估值模型与流动性阶梯熔断看门狗`**
   - **内容**：实现 `src/bankroll/zombie_evaluator.py`，落地 12h 僵尸判定，实现双轨分离（母数轨 0.0x 剔除、净值轨 10% 折价）与名义僵尸率阶梯熔断（15% 折半、30% 禁开、50% 熔断）；
   - **依赖**：Blocked by `Ticket 01`。

3. **`Phase 2 Task 05 - Ticket 03: feat(kelly): 沉没成本增量对冲多项联合凯利 SLSQP 优化器`**
   - **内容**：实现 `src/bankroll/multinomial_kelly.py`，建立注入旧持仓的外生增量对数财富目标函数，使用 SLSQP 鲁棒求解，对数输入边界防护与异常全零安全回退；
   - **依赖**：无（可独立推进开发）。

4. **`Phase 2 Task 05 - Ticket 04: feat(risk): 单市场 10% 顶额与全局 70% 流动性防线约束器`**
   - **内容**：实现 `src/bankroll/risk_limiter.py`，约束单市场总敞口 $\le 10\%$、全局流动性占用率 $\le 70\%$，结合阶梯熔断计算实际允许分配资金；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 02`, `Ticket 03`。

5. **`Phase 2 Task 05 - Ticket 05: test(acceptance): 资金凯利全链路与 Test-Scenario A/C 验收门禁`**
   - **内容**：编写端到端集成测试，全量断言 Test-Scenario A（多项凯利增量对冲）与 Test-Scenario C（僵尸双轨估值与 Decimal 精度），确保持续满足 GEFS 真实网络冒烟绿灯；
   - **依赖**：Blocked by `Ticket 01`, `Ticket 02`, `Ticket 03`, `Ticket 04`。
