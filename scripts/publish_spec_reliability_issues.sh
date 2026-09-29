#!/usr/bin/env bash
# ==============================================================================
# Script: publish_spec_reliability_issues.sh
# Purpose: Publish GitHub issues for SPEC-RELIABILITY-001 Spec and Tickets
# Rule Compliance: specs/spec-reliability-001-strata-verification.md, ADR-0017
# ==============================================================================
set -euo pipefail

REPO="oasislin/Poly2-Phase1"

echo "=== Step 1: Creating Spec Issue ==="
SPEC_URL=$(gh issue create -R "$REPO" \
  --title "Spec: Reliability Check SPEC-RELIABILITY-001 - 训练窗逐概率段可靠性对账检验" \
  --label "spec,ready-for-agent" \
  --body "规格书详见本地文档: \`specs/spec-reliability-001-strata-verification.md\`

## 任务定位 (Mission)
决策面诊断视图开发（不改变 ADR-0017 法定门禁体系，法定口径照旧运行）。
将法定门禁 ②（7 档加权 ECE，单一汇总数字）展开为逐概率段的对账单：验证模型对每个档位报出的概率，在历史中是否以接近的频率兑现。

## 数据授权与铁律 (Data Authorization & Iron Rules)
- 仅使用 2000–2018 训练窗审计数组（\`data/processed/audit_arrays/2000_2018_training_arrays.parquet\`，SHA256: \`8f2a84d26aaeaeaaf7050424df6f7d19891d752fb01b89f49d3add79bbaf3a5c\`）；
- **2019 OOS 数组严禁触碰**（盲测额度已消耗、独立复算已封存）；
- 严禁用检验结果反向调整模型参数（单向消费隔离）。

## 核心交付工件 (Deliverables)
1. 主可靠性表（20 段全局归池）：\`evidence/reliability_check_main_global.csv\`
2. 分层预警表（12 格站点×季节）：\`evidence/reliability_check_stratified_station_season.csv\`
3. Brier 技能分计算：\`evidence/reliability_check_brier_skill.csv\`
4. 独立复算脚本：\`scripts/standalone_reliability_check.py\`
5. 规格落实说明与分析：\`evidence/reliability_check_spec_notes.md\`
6. 证据哈希固化：\`evidence/pilot_manifest.json\`")

SPEC_NUM=$(echo "$SPEC_URL" | grep -oE '[0-9]+$')
echo "Created Spec Issue: #$SPEC_NUM ($SPEC_URL)"

echo "=== Step 2: Creating Tickets ==="
T1_URL=$(gh issue create -R "$REPO" \
  --title "Reliability Check - Ticket 01: feat(diagnostic): 展开训练窗 20,820 站·日预测分布为档位预测概率与实测命中对" \
  --label "ticket,ready-for-agent" \
  --body "关联主 Spec Issue: #$SPEC_NUM
规格依据: \`specs/spec-reliability-001-strata-verification.md\` §二、§三

## 任务目标
1. 从 \`data/processed/audit_arrays/2000_2018_training_arrays.parquet\` 提取 KORD, KMIA, KSFO 共 20,820 站·日记录；
2. 严格对齐模型版本与分布：
   - KORD: 高斯正态分布；
   - KMIA: Johnson SU 分布（读取 \`evidence/r6_kmia_parameters.json\`）；
   - KSFO: 高斯中心 + EVT-GPD 极值厚尾混合分布（读取 \`evidence/r7_tail_parameters.json\`）；
3. 实现代表分桶（法定 7 档主检验与备选 2°F 网格）的概率积分 \$p_{\\text{pred}}(d,s,b)\$ 与实测命中指示变量 \$\\text{hit}(d,s,b)\$；
4. 严格固定观测温度离散抖动口径并添加注释。")
echo "Created Ticket 01: $T1_URL"

T2_URL=$(gh issue create -R "$REPO" \
  --title "Reliability Check - Ticket 02: feat(diagnostic): 构建全局 20 段等宽归池主可靠性对账表与 12 格站点季节分层预警表" \
  --label "ticket,ready-for-agent" \
  --body "关联主 Spec Issue: #$SPEC_NUM
规格依据: \`specs/spec-reliability-001-strata-verification.md\` §四、§五
前置依赖: Ticket 01

## 任务目标
1. 全局按预测概率 \$p_{\\text{pred}}\$ 执行 20 段等宽（段宽 5%）归池，计算 \$n, \\bar{p}, \\hat{f}\$, 绝对偏差与二项 95% 置信半宽，导出 \`evidence/reliability_check_main_global.csv\`；
2. 计算全表加权绝对偏差 \$\\text{ECE}_{\\text{strata}}\$，并给出与法定门禁 ② 的对比口径；
3. 将样本按 3 站 × 4 季切分 12 格，独立执行分层归池，导出 \`evidence/reliability_check_stratified_station_season.csv\`；
4. 显式核验 KSFO 夏季格的方差异质性与超 CI 带偏离，禁止缺省。")
echo "Created Ticket 02: $T2_URL"

T3_URL=$(gh issue create -R "$REPO" \
  --title "Reliability Check - Ticket 03: feat(diagnostic): 计算模型与历史气候基准 Brier 技能分 (BSS)" \
  --label "ticket,ready-for-agent" \
  --body "关联主 Spec Issue: #$SPEC_NUM
规格依据: \`specs/spec-reliability-001-strata-verification.md\` §六
前置依赖: Ticket 01

## 任务目标
1. 计算模型预测的 Brier 分数 \$\\text{BS}_{\\text{model}}\$；
2. 基于 2000–2018 训练窗历史经验频率（严格采用留一法避免自证泄漏），构建各站×各月气候基准概率并计算 \$\\text{BS}_{\\text{clim}}\$；
3. 计算 Brier 技能分 \$\\text{BSS} = 1 - \\text{BS}_{\\text{model}} / \\text{BS}_{\\text{clim}}\$；
4. 验证 \$\\text{BSS} > 0\$（若 \$\\le 0\$ 则显著预警标注），导出 \`evidence/reliability_check_brier_skill.csv\`。")
echo "Created Ticket 03: $T3_URL"

T4_URL=$(gh issue create -R "$REPO" \
  --title "Reliability Check - Ticket 04: docs(settlement): 交付独立复算脚本、落实说明与 pilot_manifest 哈希固化" \
  --label "ticket,ready-for-agent" \
  --body "关联主 Spec Issue: #$SPEC_NUM
规格依据: \`specs/spec-reliability-001-strata-verification.md\` §八、§九
前置依赖: Ticket 01, Ticket 02, Ticket 03

## 任务目标
1. 编写零私有依赖独立复算脚本 \`scripts/standalone_reliability_check.py\`（仅依赖标准库 + numpy, pandas, scipy），从训练窗 Parquet 逐位重现全部 CSV 工件；
2. 撰写规格落实说明与诊断报告 \`evidence/reliability_check_spec_notes.md\`，包含参数冻结声明、法定门禁对照归因说明；
3. 将所有交付工件哈希增量注册至 \`evidence/pilot_manifest.json\`，实现证据链防篡改固化。")
echo "Created Ticket 04: $T4_URL"

echo "=== All Issues Published Successfully ==="
