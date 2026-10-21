#!/usr/bin/env bash
# gh_publish_task08_issues.sh
# Phase 2 Task 08 主 Issue 与 24 张切片 Tickets 发布命令
# 依据: P8-CLASS1-LAUNCH-CHK-07, 用户裁决 U-5/U-10
# 纪律: 本脚本交由用户在终端独立执行，Agent 不代跑 gh。

set -euo pipefail

echo "=== 开始创建 Phase 2 Task 08 主 Issue 与 24 张 Tickets ==="

# 1. 创建 Spec 主 Issue
SPEC_ISSUE_URL=$(gh issue create \
  --title "Spec: Phase 2 Task 08 - 第一类投注定价算法与只读纸面盘落地" \
  --label "spec,phase-2" \
  --body "## 任务概述 (Spec: Phase 2 Task 08)
承接盲测上游实测连续校准量，在不重训物理模型、不改 EMOS 参数的前提下，设计软平滑、无悬崖的连续可信度得分与仓位折减机制（Q1），成文厘清 exact 与 gaussian_proxy 覆盖率双轨分工（Q7），落地物理模型参数向投注算法消费契约（ADR-0019），承接 Task 04 未完成的交易 EV 引擎与达标深度保护价探针计算（DR-2026-1014-01），重构稳健多项凯利优化器（M-1）并将折剪点唯一并入 S2 预算上限 C_max（DR-2026-1014-02），重塑 S3 纯布尔门禁体系与精简残差状态机，最终在只读纸面盘中完成 48h 闭环仿真与两步标定脚手架落地。

## 关联 ADR 与宪法决议
- ADR-0019：物理模型参数向投注算法消费契约与解耦架构
- P7-ALGO-VERDICT：M-1（闭式稳健凯利）、M-2（动态费率）、M-4（废除胜率收缩）、F-2 优先律
- P7-ALGO-2 裁决记录：DR-2026-1014-01（探针定价）、DR-2026-1014-02（C_max 唯一前置折剪）、DR-2026-1014-03（B_eff 统一分母）、DR-2026-1014-04（标准化残差 z 化）
- 治理核验单：P8-CLASS1-LAUNCH-CHK-01 ~ CHK-07

## 切片 Tickets 规划
本任务下设 24 张垂直切片 Tickets（Ticket 01 ~ Ticket 24），全部按模块/细节算法解耦，首张 Frontier 票为 Ticket 01。")

echo "Spec 主 Issue 已创建: $SPEC_ISSUE_URL"

# 2. 逐张创建 24 张切片 Tickets

# Ticket 01 (Frontier)
gh issue create \
  --title "Phase 2 Task 08 - Ticket 01: feat(contract): 定义物理模型参数消费契约数据模型与格级配置 Schema" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
定义 PhysicalParamContract 与 CellCalibrationRecord 数据模型；按 22 格字典组织；实现 ADR-0019 参数消费矩阵定义的必须消费字段（mu_calib, sig_eff, p_j, s_oos, F_std, reject_uniform, ECE_2F, Cov_90, PIT_mean, PIT_var）与间接消费字段的 Schema 与类型约束。

### 依赖关系
- Blocked by: 无 (Frontier)

### 交付物与验证
- 交付代码: src/contract/parameter_contract.py
- 验证: 编写单元测试断言 22 格字典加载与类型强校验。"

# Ticket 02
gh issue create \
  --title "Phase 2 Task 08 - Ticket 02: feat(contract): 实现物理模型与 manifest SHA256 版本戳强校验看门狗" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
实现启动期模型版本强校验，比对 data/models/manifest.json 与对应 .pkl 模型文件的 SHA256 校验和。若版本不一致，立即抛出 StaleModelParametersError 阻断交易引擎启动。落实 ADR-0019 §二.6。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 01

### 交付物与验证
- 交付代码: src/contract/version_watchdog.py
- 验证: 注入虚假 SHA256，断言抛出 StaleModelParametersError 熔断阻断。"

# Ticket 03
gh issue create \
  --title "Phase 2 Task 08 - Ticket 03: feat(contract): 实现从 V2 盲测 CSV 自动导出 22 格静态参数表的转换器与校验器" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
读取 evidence/audit_v2/p4blind_v2r01_metrics.csv 与 comparison.csv（严格按列名读取，避免列号漂移），自动提取并生成 22 格标准配置 JSON；核验 22 格字段完整性与数值边界。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 01

### 交付物与验证
- 交付代码: src/contract/param_extractor.py
- 交付配置: data/processed/calibration/active10_v2r01_betting_params.json
- 验证: 断言生成的 JSON 包含恰好 22 格且数值与 CSV 原件逐位一致。"

# Ticket 04
gh issue create \
  --title "Phase 2 Task 08 - Ticket 04: feat(contract): 实现物理模型重测触发与契约更新审计流水线" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
新建包装脚本 scripts/trigger_model_retest.py：封装包装 scripts/evaluate_p4_2019_settlement.py，与 V2R01 复现命令保持严格一致；在物理模型重训或更新后，自动驱动再测并调用 param_extractor 刷新参数表，附带审计留痕。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 02, Phase 2 Task 08 - Ticket 03

### 交付物与验证
- 交付脚本: scripts/trigger_model_retest.py
- 验证: 模拟运行重测封装脚本，验证输出数据格式与校验和一致性。"

# Ticket 05
gh issue create \
  --title "Phase 2 Task 08 - Ticket 05: test(contract): 编写参数契约、版本戳校验与防污染契约测试集" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
编写契约保护综合测试集，验证版本戳篡改阻断断言、22 格参数映射完整性、防全局均值化断言及物理模型只读不可变保护测试（确保投注层绝无向 data/models 回写的代码路径）。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 04

### 交付物与验证
- 交付测试: tests/unit/contract/test_parameter_contract.py
- 验证: pytest 运行全绿。"

# Ticket 06
gh issue create \
  --title "Phase 2 Task 08 - Ticket 06: feat(pricing): 实现 Q7 覆盖率双轨分工与 exact / gaussian_proxy 计算解耦" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
落实裁决-R2：实现事后审计 exact（经验 5/95 分位）与在线实时 gaussian_proxy（mu +/- 1.64485*sig_eff）双轨独立类；在在线定价调用栈中内嵌三不混用防御断言（严禁在线调用 exact 数值求逆）。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 01

### 交付物与验证
- 交付代码: src/pricing/coverage_dual_track.py
- 验证: 对照真实 Johnson SU 与正态分布断言区间计算精度及三不混用异常阻断。"

# Ticket 07
gh issue create \
  --title "Phase 2 Task 08 - Ticket 07: feat(pricing): 实现基于 s_oos 的定价端方差自适应膨胀 σ_adj 计算引擎" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
落实 ADR-0019 G-2 裁决：实现 sig_adj = sqrt(max(1.0, s_oos)) * sig_eff。仅在欠自信（s_oos > 1.0）时外展定价不确定集防虚报 Edge；过自信时不人为缩窄方差（sig_adj = sig_eff）。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 03, Phase 2 Task 08 - Ticket 06

### 交付物与验证
- 交付代码: src/pricing/adaptive_variance.py
- 验证: 断言 KMIA 欠自信格方差适度膨胀，KORD 过自信格方差保持原样。"

# Ticket 08
gh issue create \
  --title "Phase 2 Task 08 - Ticket 08: feat(pricing): 承接 Task 04 交易 EV 引擎并实现 S1 盘口穿透探针计算 (DR-2026-1014-01)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
承接 Task 04 移交的交易 EV 引擎：注入 M-2 动态费率契约 q = p*[1+base*(1-p)]；依据 DR-2026-1014-01 实现达标深度 S_target 自动确定，穿透计算深度加权均价 P_bar 与有效成本 q_eff，消除探针独立参数。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 07

### 交付物与验证
- 交付代码: src/pricing/order_probe_evaluator.py
- 验证: 断言订单薄穿透均价 P_bar、有效成本与达标深度计算完全自洽。"

# Ticket 09
gh issue create \
  --title "Phase 2 Task 08 - Ticket 09: test(pricing): 覆盖率双轨三不混用与探针定价单测集" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
编写定价层覆盖率双轨与探针单测集，测试双轨计算纳秒级响应、在线误调 exact 抛出异常、sig_adj 纠偏有效性及达标深度穿透单测。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 08

### 交付物与验证
- 交付测试: tests/unit/pricing/test_order_probe_evaluator.py
- 验证: pytest 运行全绿。"

# Ticket 10
gh issue create \
  --title "Phase 2 Task 08 - Ticket 10: feat(bankroll): 实现基于 ECE/Cov/PIT 正交三特征的连续可信度得分 S_conf 引擎" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
依据 ADR-0019 G-1 裁决，剔除 x_s，基于 ECE_2F、Cov_90 偏离与 PIT_var 偏离计算平方高斯连续得分 S_conf；形式化实现加权衰减结构；参数标记 [F-2 LOCKED]。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 03

### 交付物与验证
- 交付代码: src/bankroll/confidence_scorer.py
- 验证: 断言在零偏离处 S_conf = 1.0，随可靠性误差扩大呈平滑单调衰减。"

# Ticket 11
gh issue create \
  --title "Phase 2 Task 08 - Ticket 11: feat(bankroll): 实现平滑无悬崖的三段式方差软折减曲线 ψ(s_oos) 映射器" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
实现绿区平坦带、余弦升降平滑过渡带、底仓衰减带与硬熔断带四级架构；消除 1.11 与 1.15 的断崖效应；二阶连续可微平滑连接；参数标记 [F-2 LOCKED]。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 03

### 交付物与验证
- 交付代码: src/bankroll/soft_shrinkage_curve.py
- 验证: 数值断言 1.11 与 1.15 输出平滑微变，无阶跃跳变。"

# Ticket 12
gh issue create \
  --title "Phase 2 Task 08 - Ticket 12: feat(bankroll): 实现综合可信度折减因子 τ_conf 组合计算与硬准入熔断逻辑" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
计算 tau_conf = psi(s_oos) * S_conf；机械核验硬准入极值熔断门槛（s_oos > s_max_hard）与 reject_uniform 标志，若不合格强制输出 tau_conf = 0.0；输出合法取值区间 [0.0, 1.0]。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 10, Phase 2 Task 08 - Ticket 11

### 交付物与验证
- 交付代码: src/bankroll/credibility_gate.py
- 验证: 编写单元测试断言正常格输出平滑折减，严重失真格输出 0.0 硬熔断。"

# Ticket 13
gh issue create \
  --title "Phase 2 Task 08 - Ticket 13: test(bankroll): Q1 连续可信度平滑性与断崖消除特性测试集" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
验证余弦过渡带二阶平滑性、1.11 与 1.15 微变特性、极值硬阻断及信号正交无双重惩罚特性。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 12

### 交付物与验证
- 交付测试: tests/unit/bankroll/test_credibility_gate.py
- 验证: pytest 运行全绿。"

# Ticket 14
gh issue create \
  --title "Phase 2 Task 08 - Ticket 14: feat(bankroll): 四桶资金账务统一 B_eff 分母与资金守恒审计机制 (DR-2026-1014-03)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
依据 DR-2026-1014-03，统一全局利用率分母为 B_eff = Free + Active，Zombie 与 Disputed 从分子分母全剔除；全链路 Decimal 实现出入金、锁定、释放与资金守恒机械校验。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 01

### 交付物与验证
- 交付代码: src/bankroll/four_bucket_manager.py
- 验证: 模拟多笔资金划转，断言全局利用率分母为 B_eff 且四桶资金绝对守恒。"

# Ticket 15
gh issue create \
  --title "Phase 2 Task 08 - Ticket 15: feat(bankroll): 实现风控折剪前置并入 S2 预算上限 C_max 唯一折剪点 (DR-2026-1014-02)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
依据 DR-2026-1014-02，实现 C_max = tau_conf * tau_z * tau_2D * min(0.10*B_eff, 0.70*B_eff - Active, W_free) 前置预算注入，S3 门禁仅作布尔放行，彻底消除后置乘法折剪。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 12, Phase 2 Task 08 - Ticket 14

### 交付物与验证
- 交付代码: src/bankroll/budget_controller.py
- 验证: 断言 C_max 正确整合各项前置乘子，预算截断符合单市场 10% 硬顶。"

# Ticket 16
gh issue create \
  --title "Phase 2 Task 08 - Ticket 16: feat(bankroll): 重构多项凯利优化器为基于 EMOS 闭式 CDF 的稳健结构 (M-1 判词落地)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
落实判决书 M-1：替代旧版点估计多项凯利，重构为基于 EMOS 闭式不确定集 P 的稳健求解器（SLSQP 求解对数增长率）；在压缩后的 C_max 预算约束下凸优化，预算向最高 Edge 档位集中；参数 theta/eta 挂 [F-2 LOCKED]。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 15

### 交付物与验证
- 交付代码: src/bankroll/robust_multinomial_kelly.py
- 验证: 断言优化解满足 simplex 约束，在压缩预算下资金自动聚焦于优势档位。"

# Ticket 17
gh issue create \
  --title "Phase 2 Task 08 - Ticket 17: test(bankroll): 稳健凯利预算前置集中性测试集" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
验证压缩预算下资金向最高 Edge 档位自动集中特性、跨过 minimum_order_size 门槛断言及单市场 10% 硬顶约束测试。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 16

### 交付物与验证
- 交付测试: tests/unit/bankroll/test_robust_kelly.py
- 验证: pytest 运行全绿。"

# Ticket 18
gh issue create \
  --title "Phase 2 Task 08 - Ticket 18: feat(risk): 两维阶梯风控残差阈值无量纲标准化 z 化改造 (DR-2026-1014-04)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
依据 DR-2026-1014-04，残差阈值统一为 z = |Delta T| / sig_EMOS，消解华氏与摄氏温标差异；输出两维调制乘数 tau_2D；z 阈值列入 [待标定]。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 07

### 交付物与验证
- 交付代码: src/risk/dimension_two_controller.py
- 验证: 断言华氏站与摄氏站在相同无量纲 z 偏离下输出完全一致的 tau_2D 决策。"

# Ticket 19
gh issue create \
  --title "Phase 2 Task 08 - Ticket 19: feat(risk): 重塑 S3 下单前门禁为纯布尔放行体系 (消除后置物料折剪)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
重构 S3 下单前门禁：仅检查 tau > 0 有效性、点差门限、流动性深度门限与紧急熔断哨兵文件，输出纯布尔放行信号，彻底消除 S3/S4 后置乘法折剪。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 15, Phase 2 Task 08 - Ticket 18

### 交付物与验证
- 交付代码: src/risk/pre_buy_boolean_gate.py
- 验证: 模拟各类边界条件，断言纯布尔放行/拦截逻辑，无任何乘数折剪外溢。"

# Ticket 20
gh issue create \
  --title "Phase 2 Task 08 - Ticket 20: feat(execution): 精简 IOC 残差状态机 (只买不卖模式下的补单与预算释放)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
移除违宪的反向对冲与市价卖出逻辑，严格在只买不卖框架下实现未成交敞口的残差补单评估与资金原路释放；输出 ResidualRiskReport。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 08

### 交付物与验证
- 交付代码: src/execution/residual_state_machine.py
- 验证: 模拟 IOC 部分成交场景，断言未成交资金安全释放回 Free 桶，无任何卖出或对冲下单。"

# Ticket 21
gh issue create \
  --title "Phase 2 Task 08 - Ticket 21: feat(simulation): 装配端到端 S1~S5 只读纸面盘事件驱动调度器" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
串联天气更新驱动、ADR-0019 参数装载、S1 探针定价、S2 稳健凯利、S3 布尔门禁、S4/S5 仿真撮合与资金出入结算状态机，驱动纸面盘全流程。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 08, Phase 2 Task 08 - Ticket 16, Phase 2 Task 08 - Ticket 19, Phase 2 Task 08 - Ticket 20

### 交付物与验证
- 交付代码: src/simulation/paper_trading_pipeline.py
- 验证: 模拟单日观测流驱动，断言端到端决策管线顺畅闭环。"

# Ticket 22
gh issue create \
  --title "Phase 2 Task 08 - Ticket 22: feat(simulation): 集成纸面盘实时资金守恒与连续净 EV 观测看门狗" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
记录每笔决策的连续校准量、tau_conf、净 EV 与资金变动；严格机械核验资金守恒 sum(Buckets) == Initial，发现任何非物理撕裂立即触发熔断。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 21

### 交付物与验证
- 交付代码: src/simulation/capital_watchdog.py
- 验证: 注入多轮成交，断言资金守恒核验机械通过，异常时精准报警。"

# Ticket 23
gh issue create \
  --title "Phase 2 Task 08 - Ticket 23: feat(calibration): 搭建 F-2 参数两步标定脚手架 (M-5 判词落地)" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
落实判决书 M-5：基于纸面盘自产数据，提供离线网格搜索与反事实 sizing 分析脚手架，为未来概率层绿灯后标定 theta, eta, psi 参数提供工具链。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 16, Phase 2 Task 08 - Ticket 21

### 交付物与验证
- 交付代码: scripts/calibrate_kelly_parameters.py
- 验证: 离线跑通假定样本下的网格搜索流程。"

# Ticket 24
gh issue create \
  --title "Phase 2 Task 08 - Ticket 24: test(simulation): 纸面盘端到端 48h 仿真验收测试集" \
  --label "ready-for-agent,phase-2" \
  --body "### 目标与算法细节
模拟 48h 连续观测输入，验证 KMIA 欠自信自动折减、KORD 正常运行、零非物理撮合、资金守恒连续观测通过与净 EV 稳健。

### 依赖关系
- Blocked by: Phase 2 Task 08 - Ticket 22, Phase 2 Task 08 - Ticket 23

### 交付物与验证
- 交付测试: tests/integration/test_paper_trading_end_to_end.py
- 验证: pytest 运行全绿并通过 48h 连续仿真门禁。"

echo "=== 全部 24 张切片 Tickets 创建完成 ==="
