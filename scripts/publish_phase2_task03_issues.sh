#!/usr/bin/env bash
# ==============================================================================
# Script: publish_phase2_task03_issues.sh
# Purpose: Publish GitHub issues for Phase 2 Task 03 Spec and Tickets
# Rule Compliance: specs/phase2-task03-central-arbiter-spec.md, ADR-0014
# ==============================================================================
set -euo pipefail

REPO="oasislin/Poly2-Phase1"

echo "=== Step 1: Creating Spec Issue ==="
SPEC_URL=$(gh issue create -R "$REPO" \
  --title "Spec: Phase 2 Task 03 - 控制面统一异常仲裁中枢与台站级安全挂起协议" \
  --label "spec,ready-for-agent" \
  --body "规格书详见本地文档: \`specs/phase2-task03-central-arbiter-spec.md\`

## 问题陈述 (Problem Statement)
在量化交易系统工程中，各业务子模块（数据接入、截断层、定价计算、订单执行、风控看门狗）各自编写局部兜底逻辑是导致系统极端行情下发生状态分裂（Split-Brain）和隐性穿仓的最主要根源。当前系统存在四大痛点：
1. 异常标准碎片化，缺乏全系统统一的 Incident 契约语言；
2. 数据面与控制面职责不清，缺乏 30 秒自愈预算衰竭自动升级机制；
3. 买单前缺乏对观测物理新鲜度（<=7.0m）与网络连通性的纯内存同步双硬门禁，存在盲盒下注风险；
4. 缺乏本地内存物理硬关阀（Local Hard Valve Shutdown）与一键硬件级断电拔网线（Emergency Stop）机制。

## 解决方案 (Solution)
严格依据已裁决的 ADR-0014 与《Phase 2 执行文件 v2.0》，在 \`src/risk/\` 架构控制面统一异常仲裁中枢：
1. **统一 Incident 契约标准**：落地 ADR-0014 §3 法定 7 字段（incident_id, timestamp_utc, station_id, subsystem, severity, reason_code, evidence_snapshot）；
2. **数据面与控制面分离与 30s 自愈预算**：底层技术瞬态允许就地退避重试（<=30s），预算衰竭强制升格为 Incident 移交控制面；
3. **二元定性仲裁机制**：
   - 物理不可信 -> 标的当日作废 (\`INVALIDATED\`)，剥夺交易资格直至次日 00:00:00 物理复位；
   - 外部通信受阻 -> 标的暂时安全挂起 (\`SUSPENDED\`)，反振荡滞后恢复锁检验（强制冷却 + 3 帧健康发报），单日满 3 次衰变为作废；
4. **买单前双连通硬门禁与本地硬关阀**：
   - 买单前纯内存同步校验：气象新鲜度 <= 7.0m + 网络连通，不满足直接打回 REJECTED_STALE_DATA；
   - 严重异常 0ms 本地硬关阀零发射，远端 Best-Effort Cancel，已成交持仓坚决不市价自残平仓（到期前 30min 特别后门）；
5. **本地拔网线 CLI 与文件哨兵**：根目录 \`EMERGENCY_STOP_<STATION>\` 标记文件侦测与专用 CLI 一键硬件级切断。

## 切片 Tickets
- Ticket 01: feat(core): 统一 Incident 契约标准、枚举体系与事件总线总管
- Ticket 02: feat(arbiter): 控制面 CentralExceptionArbiter 状态机与二元仲裁定性引擎
- Ticket 03: feat(risk): 买单前双连通硬门禁、本地零发射硬关阀与挂起协议
- Ticket 04: feat(emergency): 根目录紧急制动触发器与拔网线运维 CLI
- Ticket 05: test(acceptance): 统一异常中枢端到端全链路与 Test-Scenario E 验收门禁")

SPEC_NUM=$(echo "$SPEC_URL" | grep -oE '[0-9]+$')
echo "Created Spec Issue: #$SPEC_NUM ($SPEC_URL)"

echo ""
echo "=== Step 2: Creating Ticket 01 (Frontier) ==="
T1_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 03 - Ticket 01: feat(core): 统一 Incident 契约标准、枚举体系与事件总线总管" \
  --label "ready-for-agent" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/risk/incident_protocol.py\`，确立全系统统一的 Incident 契约标准与受控枚举体系（对齐 ADR-0014 §3）。

### 核心任务
1. 严格落实 ADR-0014 §3 规定的 7 个法定字段：\`incident_id\`, \`timestamp_utc\`, \`station_id\`, \`subsystem\`, \`severity\`, \`reason_code\`, \`evidence_snapshot\`；
2. 建立不可变数据类 \`IncidentReport\` 与受控枚举（Subsystem, Severity, ReasonCode）；
3. 抽象事件总线监听/分发接缝与基础校验器，确保快照只读与字段不可篡改；
4. 单元测试覆盖合规字段校验、非法枚举拒绝与序列化一致性。

### Blocked by
无 (Frontier，立即开工)")
T1_NUM=$(echo "$T1_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 01: #$T1_NUM ($T1_URL)"

echo ""
echo "=== Step 3: Creating Ticket 02 ==="
T2_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 03 - Ticket 02: feat(arbiter): 控制面 CentralExceptionArbiter 状态机与二元仲裁定性引擎" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/risk/central_arbiter.py\`，管理 Active 10 交易站点的全生命周期状态机与二元定性仲裁准则（对齐 ADR-0014 §2）。

### 核心任务
1. 维护 Active 10 站生命周期受控状态（\`ACTIVE\`, \`SUSPENDED\`, \`INVALIDATED\`, \`EMERGENCY_HALT\`）；
2. 落地二元仲裁分类：物理不可信 (CORRUPTED) -> \`INVALIDATED\`（当日作废至次日 00:00:00 LT 复位），通信受阻 (DEGRADED) -> \`SUSPENDED\`（挂起观察）；
3. 落地反振荡滞后恢复锁（Hysteresis Lock）：强制冷却期 + 连续 3 帧健康探针，一日内累计挂起满 3 次强制衰变为 \`INVALIDATED\`；
4. 数据面 30 秒自愈预算衰竭自动升级机制与次日自然日零点原子复位；
5. 单元测试覆盖二元定性仲裁、状态转移闭环、滞后恢复与 3 次挂起衰变。

### Blocked by
#${T1_NUM}")
T2_NUM=$(echo "$T2_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 02: #$T2_NUM ($T2_URL)"

echo ""
echo "=== Step 4: Creating Ticket 03 ==="
T3_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 03 - Ticket 03: feat(risk): 买单前双连通硬门禁、本地零发射硬关阀与挂起协议" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/risk/pre_buy_gate.py\`，落地买单前纯内存同步双硬门禁与本地零发射硬关阀控制器（对齐 ADR-0014 §2 原则一/二/四）。

### 核心任务
1. 策略买单前强制纯内存同步校验：观测数据新鲜度（Δt_age <= 7.0 分钟）+ 网络连通与台站 ACTIVE 确证，任一不满足本地物理打回（\`REJECTED_STALE_DATA\`），绝对静默零发射；
2. 落地本地硬关阀（Local Hard Valve Shutdown）：中枢阻断时 0ms 锁死内存发射阀，并发下发 \`cancel_all_open_orders\`；
3. 已成交资产绝缘持有（坚决禁止自动市价抛售自残），预留交割日前 30 分钟特别后门通道；
4. 单元测试覆盖买单拦截打回、硬关阀锁死、Best-Effort Cancel 与仓位绝缘。

### Blocked by
#${T1_NUM}, #${T2_NUM}")
T3_NUM=$(echo "$T3_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 03: #$T3_NUM ($T3_URL)"

echo ""
echo "=== Step 5: Creating Ticket 04 ==="
T4_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 03 - Ticket 04: feat(emergency): 根目录紧急制动触发器与拔网线运维 CLI" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`src/risk/emergency_control.py\` 与 \`src/risk/cli.py\`，建立文件哨兵与专用运维 CLI，提供单站/全站硬件级物理断电能力（对齐 ADR-0014 §2 与执行文件 v2.0 §3.4）。

### 核心任务
1. 实现文件哨兵 \`EmergencyFileSentinel\`：自动监听根目录下 \`EMERGENCY_STOP_<STATION>\` 与 \`EMERGENCY_STOP_ALL\` 标记文件；
2. 侦测到标记文件瞬间联动中枢将台站置为 \`EMERGENCY_HALT\` 并触发本地硬关阀；
3. 开发专用命令行运维 CLI（\`python -m src.risk.cli stop <STATION>\`，\`status\`，\`resume\`）；
4. 单元测试覆盖文件哨兵毫秒级侦测、CLI 命令解析与状态阻断联动。

### Blocked by
#${T2_NUM}")
T4_NUM=$(echo "$T4_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 04: #$T4_NUM ($T4_URL)"

echo ""
echo "=== Step 6: Creating Ticket 05 ==="
T5_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 03 - Ticket 05: test(acceptance): 统一异常中枢端到端全链路与 Test-Scenario E 验收门禁" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
构建统一异常中枢端到端集成测试，全量断言 Test-Scenario E（执行文件 v2.0 §四.5），确保全链路验收与 GEFS 网络冒烟通过。

### 核心任务
1. 实现 Test-Scenario E1：模拟自愈超时超 30s 自动升格，0ms 触发 CancelAll 并禁开新仓，已成交仓位保持绝缘；
2. 实现 Test-Scenario E2：物理撕裂（跳温 >15°F 或 COR 极值倒退）触发二元仲裁定性为 INVALIDATED，当日严禁复活；
3. 实现 Test-Scenario E3：买单前数据龄期 7.5min 注入，断言被 PreBuyGate 纯内存打回，零发射；
4. 实现 Test-Scenario E4：通信恢复连续 3 帧健康发报探针滞后恢复，单日第 4 次挂起单向衰变为 INVALIDATED；
5. 实现 Test-Scenario E5：注入 EMERGENCY_STOP_<STATION> 标记文件，断言单站硬件级阻断；
6. 验证全系统测试套件与真实 GEFS 网络冒烟持续绿灯。

### Blocked by
#${T1_NUM}, #${T2_NUM}, #${T3_NUM}, #${T4_NUM}")
T5_NUM=$(echo "$T5_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 05: #$T5_NUM ($T5_URL)"

echo ""
echo "=== Step 7: Backfilling Issue Numbers into Spec Document ==="
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
echo "Phase 2 Task 03 All Issues Created and Spec Backfilled Successfully!"
echo "Spec Issue:   #${SPEC_NUM}"
echo "Ticket 01:    #${T1_NUM} (Frontier)"
echo "Ticket 02:    #${T2_NUM}"
echo "Ticket 03:    #${T3_NUM}"
echo "Ticket 04:    #${T4_NUM}"
echo "Ticket 05:    #${T5_NUM}"
echo "========================================================================"
