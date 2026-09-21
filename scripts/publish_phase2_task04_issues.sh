#!/usr/bin/env bash
# ==============================================================================
# Script: publish_phase2_task04_issues.sh
# Purpose: Publish GitHub issues for Phase 2 Task 04 Spec and Tickets
# Rule Compliance: specs/phase2-task04-pricing-ev-engine-spec.md, ADR-0012
# ==============================================================================
set -euo pipefail

REPO="oasislin/Poly2-Phase1"

echo "=== Step 1: Creating Spec Issue ==="
SPEC_URL=$(gh issue create -R "$REPO" \
  --title "Spec: Phase 2 Task 04 - Polymarket 盘口定价映射、区间积分与动态 EV 引擎" \
  --label "spec,ready-for-agent" \
  --body "规格书详见本地文档: \`specs/phase2-task04-pricing-ev-engine-spec.md\`

## 问题陈述 (Problem Statement)
在 Polymarket 二元期权温度预测市场中，原有系统在概率映射与 EV 计算上存在四大缺陷：
1. 旧版 BinConverter 硬编码历史废弃站点，且未强制采用 scipy.special.ndtr，在尾部容易产生数值下溢；
2. 实况单调极值截断后，缺少对剩余存活档位的条件概率重正化，概率和失真；
3. 未落地 ADR-0012 规定的 NWS WRH 算术四舍五入 (Half-Up)，存在银行家舍入错档与临界点未决隐患；
4. 缺乏订单簿微观深度穿透与真实费率动态 EV 计算，极易买入负 EV 陷阱。

## 解决方案 (Solution)
严格依据 ADR-0012 与《Phase 2 执行文件 v2.0》§1、§2、§6 规范，在 \`src/prediction/\` 与 \`src/pricing/\` 搭建定价与动态 EV 引擎：
1. **高精 ndtr 离散区间积分转换器**：原生适配 Active 10 站 1°F 档位，半度连续性积分，保证概率单纯形约束；
2. **极值单调截断与条件单纯形重正化**：对接合流极值，死档概率不可逆归零，活档条件重正化归一；
3. **法定 NWS WRH 算术四舍五入与临界哨兵**：Decimal ROUND_HALF_UP 消除银行家舍入，[X.45, X.55] 临界双向情景沙盘；
4. **订单簿深度穿透与动态 EV 引擎**：穿透加权成本，注入费率模型，计算净 EV 与有效 Edge，过滤正期望收益开仓信号。

## 切片 Tickets
- Ticket 01: feat(pricing): 高精 ndtr 连续分布向 Active 10 站离散区间积分转换器
- Ticket 02: feat(truncation): 极值单调截断概率归零与单纯形条件重正化引擎
- Ticket 03: feat(settlement): 法定 NWS WRH 算术四舍五入 (Half-Up) 与临界哨兵沙盘
- Ticket 04: feat(ev): 订单簿深度穿透加权与微观结构动态 EV 计算引擎
- Ticket 05: test(acceptance): 盘口定价与 EV 全链路端到端集成测试套件")

SPEC_NUM=$(echo "$SPEC_URL" | grep -oE '[0-9]+$')
echo "Created Spec Issue: #$SPEC_NUM ($SPEC_URL)"

echo ""
echo "=== Step 2: Creating Ticket 01 (Frontier) ==="
T1_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 04 - Ticket 01: feat(pricing): 高精 ndtr 连续分布向 Active 10 站离散区间积分转换器" \
  --label "ready-for-agent" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/prediction/discrete_bin_engine.py\`，使用 \`scipy.special.ndtr\` 原生适配 Active 10 站 1°F 离散档位高精累积分布区间积分。

### 核心任务
1. 原生适配 Active 10 站 1°F 档位区间定义（<=T_min, T1, T2, ..., >=T_max）；
2. 半度连续性修正积分：整数 T 映射至 [T - 0.5, T + 0.5)°F；
3. 严格使用 \`scipy.special.ndtr\` 计算高斯累积分布，杜绝尾部下溢；
4. 保证概率单纯形约束 sum(P_i) == 1.000000（容差 <= 1e-6）；
5. 单元测试覆盖标准分布、极端偏移、尾部档位积分。

### Blocked by
无 (Frontier，立即开工)")
T1_NUM=$(echo "$T1_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 01: #$T1_NUM ($T1_URL)"

echo ""
echo "=== Step 3: Creating Ticket 02 ==="
T2_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 04 - Ticket 02: feat(truncation): 极值单调截断概率归零与单纯形条件重正化引擎" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/prediction/truncated_probability_engine.py\`，对接实测合流极值，执行死档不可逆置零与活档条件概率单纯形重正化。

### 核心任务
1. TMAX 截断：实测达 T_obs 则所有上界 <= T_obs 的档位概率归零；
2. TMIN 截断：实测达 T_obs 则所有下界 >= T_obs 的档位概率归零；
3. 条件概率单纯形重正化：剩余存活档位按 sum(p_alive) 归一化为 1.0；
4. 单元测试覆盖死档单向锁定、连续极值推进与完全截断异常保护。

### Blocked by
#${T1_NUM}")
T2_NUM=$(echo "$T2_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 02: #$T2_NUM ($T2_URL)"

echo ""
echo "=== Step 4: Creating Ticket 03 ==="
T3_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 04 - Ticket 03: feat(settlement): 法定 NWS WRH 算术四舍五入 (Half-Up) 与临界哨兵沙盘" \
  --label "ready-for-agent" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/settlement/rounding_simulator.py\`，落地 ADR-0012 法定结算真值算术四舍五入 (Half-Up) 与 [X.45, X.55] 临界哨兵预警沙盘。

### 核心任务
1. 强制采用 Python \`decimal\` 模块的 \`ROUND_HALF_UP\` 算术四舍五入复刻官方结算（彻底终结 PENDING-01）；
2. 建立临界哨兵 (Borderline Sentinel)：实测极值落在 [X.45, X.55] 闭区间时触发 BORDERLINE_CRITICAL 告警；
3. 输出进位与舍去双向结算概率情景沙盘；
4. 单元测试覆盖 .49°F 舍去、.50°F 进位与银行家舍入差异对比。

### Blocked by
无 (可独立验证)")
T3_NUM=$(echo "$T3_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 03: #$T3_NUM ($T3_URL)"

echo ""
echo "=== Step 5: Creating Ticket 04 ==="
T4_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 04 - Ticket 04: feat(ev): 订单簿深度穿透加权与微观结构动态 EV 计算引擎" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/pricing/ev_engine.py\`，结合订单簿深度与 Polymarket 费率模型，计算净期望收益 (EV) 与有效 Edge。

### 核心任务
1. 订单簿深度穿透加权成本计算（遍历 Ask 档位计算平均成交价）；
2. 注入 Polymarket 费率模型扣除摩擦成本；
3. 计算净 EV = p_model * (1 - fee) - P_eff 与 Edge = EV / P_eff；
4. 过滤输出正期望收益交易信号 \`EVTradeSignal\` (满足 Edge >= min_reprice_edge)；
5. 单元测试覆盖薄盘口穿透、费率扣除与正负 EV 判别。

### Blocked by
#${T1_NUM}, #${T2_NUM}")
T4_NUM=$(echo "$T4_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 04: #$T4_NUM ($T4_URL)"

echo ""
echo "=== Step 6: Creating Ticket 05 ==="
T5_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 04 - Ticket 05: test(acceptance): 盘口定价与 EV 全链路端到端集成测试套件" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
构建端到端全链路集成测试套件，验证从高斯参数输入、极值截断、四舍五入复刻到深度 EV 信号生成的全流程闭环。

### 核心任务
1. 编写端到端管道测试：(μ, σ) -> 离散区间 ndtr 积分 -> 实况极值截断重正化 -> 订单簿注入 -> 净 EV 信号输出；
2. 验证临界哨兵与双向沙盘输出；
3. 验证 GEFS 真实网络冒烟与全库测试持续全绿。

### Blocked by
#${T1_NUM}, #${T2_NUM}, #${T3_NUM}, #${T4_NUM}")
T5_NUM=$(echo "$T5_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 05: #$T5_NUM ($T5_URL)"

echo ""
echo "=== Step 7: Backfilling Issue Numbers into Spec Document ==="
SPEC_FILE="specs/phase2-task04-pricing-ev-engine-spec.md"
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
echo "Phase 2 Task 04 All Issues Created and Spec Backfilled Successfully!"
echo "Spec Issue:   #${SPEC_NUM}"
echo "Ticket 01:    #${T1_NUM} (Frontier)"
echo "Ticket 02:    #${T2_NUM}"
echo "Ticket 03:    #${T3_NUM} (Frontier)"
echo "Ticket 04:    #${T4_NUM}"
echo "Ticket 05:    #${T5_NUM}"
echo "========================================================================"
