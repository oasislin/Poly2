#!/usr/bin/env bash
# ==============================================================================
# Script: publish_phase2_task02_issues.sh
# Purpose: Publish GitHub issues for Phase 2 Task 02 Spec and Tickets
# Rule Compliance: specs/phase2-task02-multi-source-stream-spec.md, ADR-0011, ADR-0013
# ==============================================================================
set -euo pipefail

REPO="oasislin/Poly2-Phase1"

echo "=== Step 1: Creating Spec Issue ==="
SPEC_URL=$(gh issue create -R "$REPO" \
  --title "Spec: Phase 2 Task 02 - 多源实况合流、特报高频截断与两维阶梯风控引擎" \
  --label "spec,ready-for-agent" \
  --body "规格书详见本地文档: \`specs/phase2-task02-multi-source-stream-spec.md\`

## 问题陈述 (Problem Statement)
旧版 Phase 1/v1.3 存在三大致命隐患：
1. 存在“名义极值前 2h 切换 Wunderground 抓取”的倒挂逻辑与脏数据依赖；
2. 降级策略在数据超时后“下线截断层并放大方差”，违背物理不可逆性，诱发向死档下注穿仓；
3. 缺乏特报（SPECI）高频处理机制与纯气温本征门禁，无跳温安全阻断；
4. 45 分钟单一超时阈值过于粗放，无法适配 Active 10 站每 5 分钟高频发报现实，造成 45m 逆向选择盲盒。

## 解决方案 (Solution)
根据 ADR-0011 与 ADR-0013 搭建多源实况单调合流与特报截断引擎：
1. **双源单调合流架构**：IEM METAR/SPECI 为主力驱动源，NWS WRH 为影子对齐源，全天候单调更新 TMAX(只增不减)/TMIN(只减不增)；
2. **三道纯温本征门禁**：极值域([-40, 135]°F)、正文-RMK交叉检验(<=1.8°F)、5m单步跳变(<=15.0°F)；
3. **迟到不投原则**：延迟超15m或时间戳倒退直接丢弃，不触发重算与开仓；
4. **单站安全熔断阻断**：突破门禁触发 Fail-Closed，0ms 撤单并置 STATION_BLOCKED；
5. **两维阶梯风控与迟滞恢复**：15m心跳超时撤销挂单(CancelAll)，35m物理龄期熔断(SAFE_MODE)，连续3帧健康发报迟滞恢复；
6. **截断约束永久锁定**：物理极值事实永久有效，失明期截断绝不下线。

## 切片 Tickets
- Ticket 01: feat(ingestion): 观测数据流接入适配器与 IEM/NWS 双源报文解析器
- Ticket 02: feat(truncation): 三道纯温本征门禁与物理跳温安全阻断器
- Ticket 03: feat(pipeline): 双源单调合流状态机与日历日极值跟踪器
- Ticket 04: feat(risk): 15m到达心跳与35m物理龄期两维阶梯风控监控器
- Ticket 05: test(acceptance): 多源合流端到端集成与 Test-Scenario D 验收套件")

SPEC_NUM=$(echo "$SPEC_URL" | grep -oE '[0-9]+$')
echo "Created Spec Issue: #$SPEC_NUM ($SPEC_URL)"

echo ""
echo "=== Step 2: Creating Ticket 01 (Frontier) ==="
T1_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 02 - Ticket 01: feat(ingestion): 观测数据流接入适配器与 IEM/NWS 双源报文解析器" \
  --label "ready-for-agent" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`ObservationStreamAdapter\`，流式接入并解析 IEM METAR / SPECI 报文及 NWS WRH 观测，高精度提取纯气温（含正文整度数与 RMK T 组 0.1°C 解码），输出规范化 \`ObservationPacket\` 与标准化 UTC 时间戳。

### 核心任务
1. 统一接入 IEM ASOS METAR/SPECI 报文与 NWS WRH 时序表；
2. 纯气温提取与高精度解码（0.1°C RMK T 组优先，正文整度兜底）；
3. 输出统一 \`ObservationPacket (station_id, timestamp_utc, temp_c, temp_f, source_type, is_speci)\`；
4. 单元测试覆盖各类报文边界解码（负温、缺失、格式异常）。

### Blocked by
无 (Frontier，立即开工)")
T1_NUM=$(echo "$T1_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 01: #$T1_NUM ($T1_URL)"

echo ""
echo "=== Step 3: Creating Ticket 02 ==="
T2_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 02 - Ticket 02: feat(truncation): 三道纯温本征门禁与物理跳温安全阻断器" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`TemperatureSanitizer\`，校验三道纯温本征门禁与迟到丢弃机制，落地物理跳温安全阻断状态机（对齐 ADR-0013）。

### 核心任务
1. 校验门禁 1（绝对极值域 [-40°F, 135°F]）、门禁 2（正文-RMK 交叉偏差 <= 1.8°F）、门禁 3（5分钟单步跳变 <= 15.0°F）；
2. 迟到不投丢弃器（到达延迟 > 15m 或时间戳倒退直接丢弃，不触发重算与开仓）；
3. 异常安全阻断（突破门禁触发 Fail-Closed，上报 PHYSICAL_TEAR，单站锁定 STATION_BLOCKED，排队未成交挂单清空）；
4. 单元测试覆盖三道门禁拦截、迟到丢弃与安全熔断。

### Blocked by
#${T1_NUM}")
T2_NUM=$(echo "$T2_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 02: #$T2_NUM ($T2_URL)"

echo ""
echo "=== Step 4: Creating Ticket 03 ==="
T3_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 02 - Ticket 03: feat(pipeline): 双源单调合流状态机与日历日极值跟踪器" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`MonotonicConfluenceEngine\`，管理 Active 10 站本地自然日内的极值推进与截断约束单向永久锁定（对齐 ADR-0011）。

### 核心任务
1. 双源单调合流算子：TMAX 只增不减 (max(IEM, NWS))，TMIN 只减不增 (min(IEM, NWS))；
2. Active 10 站本地时区自然日（当地 00:00:00 ~ 23:59:59）隔离跟踪，午夜零点原子重置；
3. 升级 \`DynamicCorrector\`：确保截断门禁在数据断流失明期单向永久锁定，绝不下线；
4. 单元测试覆盖乱序极值单调性、跨自然日翻转与永久截断约束。

### Blocked by
#${T2_NUM}")
T3_NUM=$(echo "$T3_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 03: #$T3_NUM ($T3_URL)"

echo ""
echo "=== Step 5: Creating Ticket 04 ==="
T4_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 02 - Ticket 04: feat(risk): 15m到达心跳与35m物理龄期两维阶梯风控监控器" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
实现 \`StreamRiskWatchdog\`，双轨监控台站到达心跳与绝对物理龄期，落地 CancelAll 挂单撤销与连续 3 帧迟滞恢复（对齐 ADR-0011）。

### 核心任务
1. 第一道防线：到达心跳超时 > 15m 触发 WARNING，立即下发 cancel_all 撤销全部未成交限价挂单，禁开新仓；
2. 第二道防线：物理龄期超限 > 35m 触发 DATA_STALENESS (ERROR)，系统进入 SAFE_MODE 熔断；
3. 迟滞恢复看门狗：恢复必须满足物理龄期 < 20m 且连续 3 帧（15分钟）持续健康发报；
4. 单元测试覆盖两维超时状态跃迁与迟滞恢复逻辑。

### Blocked by
#${T1_NUM}, #${T3_NUM}")
T4_NUM=$(echo "$T4_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 04: #$T4_NUM ($T4_URL)"

echo ""
echo "=== Step 6: Creating Ticket 05 ==="
T5_URL=$(gh issue create -R "$REPO" \
  --title "Phase 2 Task 02 - Ticket 05: test(acceptance): 多源合流端到端集成与 Test-Scenario D 验收套件" \
  --label "blocked" \
  --body "Part of #${SPEC_NUM}

### 目标
构建多源合流端到端集成测试，全量断言 Test-Scenario D（执行文件 v2.0 §四.4），确保全链路验收与网络冒烟通过。

### 核心任务
1. 实现 Test-Scenario D1：迟到 METAR 原报丢弃负断言；
2. 实现 Test-Scenario D2：正文与 RMK T 组交叉纠偏正断言；
3. 实现 Test-Scenario D3：异常跳温 20°F 触发 Fail-Closed 安全阻断与单站锁定断言；
4. 端到端链路贯通测试与真实网络冒烟绿灯校验。

### Blocked by
#${T1_NUM}, #${T2_NUM}, #${T3_NUM}, #${T4_NUM}")
T5_NUM=$(echo "$T5_URL" | grep -oE '[0-9]+$')
echo "Created Ticket 05: #$T5_NUM ($T5_URL)"

echo ""
echo "========================================================================"
echo "Phase 2 Task 02 All Issues Created Successfully!"
echo "Spec Issue:   #${SPEC_NUM}"
echo "Ticket 01:    #${T1_NUM} (Frontier)"
echo "Ticket 02:    #${T2_NUM}"
echo "Ticket 03:    #${T3_NUM}"
echo "Ticket 04:    #${T4_NUM}"
echo "Ticket 05:    #${T5_NUM}"
echo "========================================================================"
