#!/usr/bin/env bash
# ==============================================================================
# Script: publish_phase2_task05_issues.sh
# Purpose: Publish GitHub issues for Phase 2 Task 05 Spec and Tickets
# Rule Compliance: specs/phase2-task05-bankroll-kelly-optimizer-spec.md, ADR-0012
# ==============================================================================
set -euo pipefail

REPO="oasislin/Poly2"

echo "=== Step 1: Creating Spec Issue ==="
SPEC_RESP=$(gh api -X POST "/repos/${REPO}/issues" \
  -f title="Spec: Phase 2 Task 05 - 四桶资金状态机、僵尸仓位双轨估值与多项联合凯利优化器" \
  -f body="规格书详见本地文档: \`specs/phase2-task05-bankroll-kelly-optimizer-spec.md\`

## 问题陈述 (Problem Statement)
传统量化预测市场在资金管理与仓位最优化上面临四大隐患：
1. 资金池划分模糊与浮点尾差撕裂（IEEE 754 累积误差导致总账破裂）；
2. 清算延迟传染与母数虚高爆仓（将未结算的僵尸资金继续充当新开仓母数）；
3. 沉没成本与多档位对冲失真（单档位独立下注违背互斥完备几何约束）；
4. 流动性过度占用与单点暴露（单市场无硬顶，全局占用率无安全警戒）。

## 解决方案 (Solution)
严格依据 ADR-0012 与《Phase 2 执行文件 v2.0》§3、§4 规范，在 \`src/bankroll/\` 架构资金与仓位优化系统：
1. **四桶资金状态机**：Free USDC / Active Locked / Zombie Margin / Disputed Margin 全流程强制 Decimal 定点截断；
2. **僵尸仓位双轨估值模型**：12h 阈值硬红线，下注母数轨 0.0x 严格剔除，净值轨 10% 折价计提，名义僵尸率阶梯熔断；
3. **多项联合增量对数财富最大化凯利优化器**：旧持仓作为外生确定项注入自然对冲，SLSQP 求解，对数输入安全防护，未收敛安全回退全零；
4. **两道风控硬约束**：单市场总敞口 <= 10%，全局活跃锁定 <= 70%。

## 切片 Tickets
- Ticket 01: feat(bankroll): 四桶资金状态机与全局 Decimal 截断舍入闭环
- Ticket 02: feat(zombie): 僵尸仓位双轨估值模型与流动性阶梯熔断看门狗
- Ticket 03: feat(kelly): 沉没成本增量对冲多项联合凯利 SLSQP 优化器
- Ticket 04: feat(risk): 单市场 10% 顶额与全局 70% 流动性防线约束器
- Ticket 05: test(acceptance): 资金凯利全链路与 Test-Scenario A/C 验收门禁")

SPEC_NUM=$(echo "$SPEC_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['number'])")
echo "Created Spec Issue: #${SPEC_NUM}"

echo ""
echo "=== Step 2: Creating Ticket 01 (Frontier) ==="
T1_RESP=$(gh api -X POST "/repos/${REPO}/issues" \
  -f title="Phase 2 Task 05 - Ticket 01: feat(bankroll): 四桶资金状态机与全局 Decimal 截断舍入闭环" \
  -f body="Part of #${SPEC_NUM}

### 目标
实现 \`src/bankroll/bankroll_manager.py\`，管理四桶资金状态机（Free USDC, Active Locked, Zombie Margin, Disputed Margin），全流程使用 Decimal 截断计算，提供出入金与仓位锁定释放接口。

### 核心任务
1. 确立四桶资金状态机与守恒方程：Total = Free + Active + Zombie + Disputed；
2. 全流程强制使用 Python \`Decimal\`（精度 10^-6），算术运算使用 \`ROUND_DOWN\` 杜绝透支；
3. 实现出入金、下单锁定、成交划转、结算释放与争议冻结事务方法；
4. 单元测试覆盖四桶恒等式守恒、Decimal 零尾差精度与并发安全。

### Blocked by
无 (Frontier，立即开工)")
T1_NUM=$(echo "$T1_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['number'])")
echo "Created Ticket 01: #${T1_NUM}"

echo ""
echo "=== Step 3: Creating Ticket 02 ==="
T2_RESP=$(gh api -X POST "/repos/${REPO}/issues" \
  -f title="Phase 2 Task 05 - Ticket 02: feat(zombie): 僵尸仓位双轨估值模型与流动性阶梯熔断看门狗" \
  -f body="Part of #${SPEC_NUM}

### 目标
实现 \`src/bankroll/zombie_evaluator.py\`，落地 12h 僵尸判定，实现双轨分离（母数轨 0.0x 剔除、净值轨 10% 折价）与名义僵尸率阶梯熔断（15% 折半、30% 禁开、50% 熔断）。

### 核心任务
1. 监控自然日闭合时钟，超时 12h 触发自动移入 Zombie Margin；
2. 下注母数轨：严格按 0.0x 剔除 Zombie 与 Disputed，输出真实有效母数；
3. 财务净值轨：对僵尸仓位计提 10% 流动性折价 (0.90 * EV)，争议资金计提折价；
4. 阶梯流动性熔断：R_z > 15% 开仓折半，> 30% 暂停开仓，> 50% 触发只读 SAFE_MODE；
5. 单元测试覆盖 12h 转移、双轨核算与阶梯熔断。

### Blocked by
#${T1_NUM}")
T2_NUM=$(echo "$T2_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['number'])")
echo "Created Ticket 02: #${T2_NUM}"

echo ""
echo "=== Step 4: Creating Ticket 03 (Frontier) ==="
T3_RESP=$(gh api -X POST "/repos/${REPO}/issues" \
  -f title="Phase 2 Task 05 - Ticket 03: feat(kelly): 沉没成本增量对冲多项联合凯利 SLSQP 优化器" \
  -f body="Part of #${SPEC_NUM}

### 目标
实现 \`src/bankroll/multinomial_kelly.py\`，建立注入旧持仓的外生增量对数财富目标函数，使用 SLSQP 鲁棒求解，对数输入边界防护与异常全零安全回退。

### 核心任务
1. 构造多项联合对数财富增量目标函数 G_incr(f)；
2. 旧持仓 N_i 作为外生确定项注入，只买不卖，零摩擦自然向前对冲；
3. 对数项输入安全守卫：边界惩罚杜绝 NaN / Inf；
4. SLSQP 优化器求解，未收敛或异常时 Fail-Closed 安全回退全零向量；
5. 单元测试覆盖概率突变自然对冲、多档位分配与异常回退。

### Blocked by
无 (可独立推进开发)")
T3_NUM=$(echo "$T3_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['number'])")
echo "Created Ticket 03: #${T3_NUM}"

echo ""
echo "=== Step 5: Creating Ticket 04 ==="
T4_RESP=$(gh api -X POST "/repos/${REPO}/issues" \
  -f title="Phase 2 Task 05 - Ticket 04: feat(risk): 单市场 10% 顶额与全局 70% 流动性防线约束器" \
  -f body="Part of #${SPEC_NUM}

### 目标
实现 \`src/bankroll/risk_limiter.py\`，约束单市场总敞口 <= 10%、全局流动性占用率 <= 70%，结合阶梯熔断计算实际允许分配资金。

### 核心任务
1. 单市场总敞口硬顶：单一互斥市场总资金 <= 10% * Bankroll_effective；
2. 全局流动性占用率硬顶：Active Locked / Total Bankroll <= 0.70（分子坚决剔除 Zombie 与 Disputed）；
3. 联动僵尸阶梯熔断调整分配额度（折半或归零）；
4. 单元测试覆盖超限拦截、额度折半与边界守卫。

### Blocked by
#${T1_NUM}, #${T2_NUM}, #${T3_NUM}")
T4_NUM=$(echo "$T4_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['number'])")
echo "Created Ticket 04: #${T4_NUM}"

echo ""
echo "=== Step 6: Creating Ticket 05 ==="
T5_RESP=$(gh api -X POST "/repos/${REPO}/issues" \
  -f title="Phase 2 Task 05 - Ticket 05: test(acceptance): 资金凯利全链路与 Test-Scenario A/C 验收门禁" \
  -f body="Part of #${SPEC_NUM}

### 目标
编写端到端集成测试，全量断言 Test-Scenario A（多项凯利增量对冲）与 Test-Scenario C（僵尸双轨估值与 Decimal 精度），确保持续满足 GEFS 真实网络冒烟绿灯。

### 核心任务
1. 实现 Test-Scenario A：模拟 4 档位冷空气概率突变，断言增量资金精准分配，旧持仓外生隔离无放大；
2. 实现 Test-Scenario C：注入 12h 僵尸仓位，断言从下注母数剔除，全流程 Decimal 零尾差撕裂；
3. 验证全系统测试套件与真实 GEFS 网络冒烟持续绿灯。

### Blocked by
#${T1_NUM}, #${T2_NUM}, #${T3_NUM}, #${T4_NUM}")
T5_NUM=$(echo "$T5_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['number'])")
echo "Created Ticket 05: #${T5_NUM}"

echo ""
echo "=== Step 7: Backfilling Issue Numbers into Spec Document ==="
SPEC_FILE="specs/phase2-task05-bankroll-kelly-optimizer-spec.md"
python3 -c "
import sys
spec_file = '$SPEC_FILE'
with open(spec_file, 'r') as f:
    c = f.read()
c = c.replace('Spec Issue**: 待发布', 'Spec Issue**: [#${SPEC_NUM}](https://github.com/${REPO}/issues/${SPEC_NUM})')
c = c.replace('Ticket 01\`: 待发布', 'Ticket 01\`: [#${T1_NUM}](https://github.com/${REPO}/issues/${T1_NUM})')
c = c.replace('Ticket 02\`: 待发布', 'Ticket 02\`: [#${T2_NUM}](https://github.com/${REPO}/issues/${T2_NUM})')
c = c.replace('Ticket 03\`: 待发布', 'Ticket 03\`: [#${T3_NUM}](https://github.com/${REPO}/issues/${T3_NUM})')
c = c.replace('Ticket 04\`: 待发布', 'Ticket 04\`: [#${T4_NUM}](https://github.com/${REPO}/issues/${T4_NUM})')
c = c.replace('Ticket 05\`: 待发布', 'Ticket 05\`: [#${T5_NUM}](https://github.com/${REPO}/issues/${T5_NUM})')
with open(spec_file, 'w') as f:
    f.write(c)
"

echo ""
echo "========================================================================"
echo "Phase 2 Task 05 All Issues Created and Spec Backfilled Successfully!"
echo "Spec Issue:   #${SPEC_NUM}"
echo "Ticket 01:    #${T1_NUM} (Frontier)"
echo "Ticket 02:    #${T2_NUM}"
echo "Ticket 03:    #${T3_NUM} (Frontier)"
echo "Ticket 04:    #${T4_NUM}"
echo "Ticket 05:    #${T5_NUM}"
echo "========================================================================"
