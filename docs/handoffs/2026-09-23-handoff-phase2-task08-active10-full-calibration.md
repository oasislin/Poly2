# Handoff 指南：Phase 2 Task 08 - Active 10 站全量物理概率模型升级、方差校准与 2019 样本外终极验收

> **交接日期**: 2026-09-23  
> **前置会话结项状态**: Phase 1 先导站（KORD, KMIA, KSFO）已获 `FULLY VALIDATED` 终局裁决；Task 07“虚假盘口与合成做市商回测”已正式标记废除/挂起。  
> **接收对象**: 接棒进行 Phase 2 Task 08 全量生产级推广的新 Agent / 会话。  
> **核心使命**: 将先导站打磨成熟的整套物理模型升级规范（$c_{\text{train}}$ 外生冻结、因果滑动窗口、R-6 偏态校正、R-7 EVT 极值尾部、ADR-0017 离散化门禁），全量覆盖至全部 Active 10 交易台站，完成 2019 样本外全量法定盲测验收！

---

## 一、 为什么必须做 Task 08？（前情提要与战略定调）

1. **破除假象**：此前曾试图构建所谓的“Task 07 历史回测”，但经架构审查与用户指正，2019 年客观不存在 Polymarket 真实订单簿，用“自制合成做市商 + 粗糙下注规则”跑出的夏普和胜率属于**自欺欺人的无意义内耗**。该伪需求已被正式废除。
2. **战略归位**：用户明确裁定：**当前处于物理模型研发阶段，核心使命是确保物理模型本身对全美交易宇宙输出真实、精准、合格的概率分布。** 至于如何运用该概率进行交易决策，是后续独立的【投注算法与凯利决策引擎】的工作。
3. **严重断层现状**：
   - 基础 EMOS 模型在 `data/models/` 虽有 10 站文件，但属于未经修正的旧版基线；
   - 真正具备防数据泄漏（无 Case-B 前瞻）、因果滑动去偏、外生 $c_{\text{train}}$ 冻结、R-6/R-7 极值校准以及 ADR-0017 离散化半度修正的最新模型，**目前仅在 3 个先导站（KORD, KMIA, KSFO）跑通**；
   - 其余 7 个核心台站（`KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KAUS`）尚未进行新参数拟合与 2019 样本外验收！Task 08 就是补齐这块最核心的生产拼图。

---

## 二、 关键资产索引与可直接复用脚本 (Reusable Assets & Pipelines)

接棒 Agent 绝不需要从零造轮子，前序会话已沉淀出高纯度、高稳定性的工具与管道：

| 资产类别 | 物理文件路径 | 作用说明与调用指南 |
| :--- | :--- | :--- |
| **全量训练/评估数据** | `data/processed/calib-dataset-v2.0/` | 包含 2000–2018 训练集与 2019 样本外评估集（Active 10 站全量覆盖） |
| **官方地面真值** | `data/processed/truth_ghcn_daily/{station}.parquet` | NWS GHCN-Daily 官方结算地面最高温真值（10 站全量具备） |
| **参数拟合核心脚本** | [`scripts/fit_training_variance_factors.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/fit_training_variance_factors.py) | **需修改其 `STATIONS` 列表为 10 站**，全量在 2000–2018 窗内拟合 $c_{\text{train}}$ 与去偏参数 |
| **主审计评估脚本** | [`scripts/audit_provenance_and_recompute.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/audit_provenance_and_recompute.py) | 读取冻结 $c_{\text{train}}$，在 2019 样本外推演 $\mu, \sigma_f$，执行抖动 PIT 与 ECE 计算 |
| **零依赖独立复算** | [`scripts/standalone_recompute_evaluation.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/standalone_recompute_evaluation.py) | 仅依赖 `scipy/numpy/pandas`，供独立复算方验证指标逐位一致性 |
| **先导站法定总表** | [`evidence/round3_settlement_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/round3_settlement_report.md) | 先导站黄金标杆，格式与指标标准直接参考 |
| **离散化与门禁规范** | [`docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md) | 1°F 档位半度连续性修正积分公式与 ECE 门禁法定定义 |

---

## 三、 Task 08 分阶段执行步骤与检查清单 (Step-by-Step Execution Plan)

### 第一阶段：Active 10 站训练窗参数离线全量拟合与冻结 (Ticket 01)
1. 将 `scripts/fit_training_variance_factors.py` 的 `STATIONS` 扩充为 Active 10 站宇宙：
   `["KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX", "KHOU", "KMIA", "KSFO", "KAUS"]`；
2. 运行脚本，严格在 **2000–2018 训练窗**执行：
   - 验证滑动去偏窗口最优长度（三站已实证 `window=30` 最优，对其余 7 站保持架构统一）；
   - 计算 10 站无偏残差方差 $\text{Var}(r_{\text{train}})$ 与 $\mathbb{E}[\sigma_{\text{raw}}^2]$，推导 $c_{\text{train}}$；
3. 将全量 10 站参数固化落盘为 `evidence/active10_training_variance_factors.json`，计算 SHA-256 并登记。

### 第二阶段：局地气候偏态(R-6)与极值理论厚尾(R-7)扩展 (Ticket 02)
1. **对流偏态诊断**：针对南部台站（`KHOU` 休斯敦、`KAUS` 奥斯汀、`KATL` 亚特兰大）的夏季午后雷暴对流，检查是否存在类似迈阿密（KMIA）的强负偏现象。若存在显著负偏，装配 Johnson SU 偏态变换；
2. **极值厚尾诊断**：针对夏季极端高温多发站点（`KDAL` 达拉斯、`KAUS`、`KSFO` 焚风日），核定广义帕累托分布（GPD）超额分位数与动态方差扩宽系数；
3. 产出全量校准参数配置 `evidence/active10_climate_calibration.json`。

### 第三阶段：2019 样本外盲测推演与底账生成 (Ticket 03)
1. 驱动 10 站 2019 年 365 天样本外数据（共 3,650 站·日），加载冻结的 $c_{\text{train}}$ 及局地校准参数；
2. 生成只读标准 Parquet 审计底账：`data/processed/audit_arrays/2019_oos_active10_arrays.parquet`；
3. 确保底层数据列完整包含：`target_date`, `station`, `obs_tmax_f`, `mu_forecast`, `sigma_forecast`, `pit_value`, `is_covered_90` 等核心字段。

### 第四阶段：ADR-0017 离散化门禁核验与统计汇总 (Ticket 04)
1. 运行双向核验：
   - 施加 $\pm 0.05^\circ\text{F}$ 离散抖动消除阶梯，运行双向 K-S 检验并由 `kstwo.sf(D, 365)` 反解 $p$ 值；
   - 按照 $\pm 0.5^\circ\text{F}$ 连续性积分计算 7 档位加权 ECE；
   - 计算方差比 $s_{\text{oos}} = \text{Var}(\text{resid}) / \mathbb{E}[\sigma_f^2]$；
2. 严格核对 **六大终极法定门禁**：
   - [ ] 1. 随机化 PIT K-S 检验 $p \ge 0.05$（全员通过）；
   - [ ] 2. 7 档位离散加权 ECE $\le 3.0\%$（全员通过）；
   - [ ] 3. 样本外方差比 $s_{\text{oos}} \in [0.85, 1.15]$（全员通过）；
   - [ ] 4. 双向检验 ①：PIT 均值 $\in [0.46, 0.54]$（全员通过）；
   - [ ] 5. 双向检验 ②：90% 名义覆盖率 $\in [83\%, 95\%]$（全员通过）；
   - [ ] 6. 均值层纯净性：MAE 与基线保持一致（证明未触碰 $\mu$ 层）。
3. 导出机器可读统计表 `evidence/active10_recomputed_statistics.csv`。

### 第五阶段：法定交付与独立复算闭环 (Ticket 05)
1. 撰写并交付覆盖 10 站的唯一法定结算报告：`evidence/active10_settlement_report.md`；
2. 交付零依赖独立复算脚本 `scripts/standalone_recompute_active10.py`，运行断言其输出与报告逐位一致；
3. 汇总生成全新签名哈希清单 `evidence/active10_manifest.json`，固化全生命周期不可篡改审计证据链！

---

## 四、 GitHub Issue 索引矩阵（已全部创建并在线生效）

全量 Issue 已遵照《AGENTS.md》显式全拼命名规范正式在 GitHub 上立项：

- **Spec 主 Issue**: [#114](https://github.com/oasislin/Poly2/issues/114) `Spec: Phase 2 Task 08 - Active 10 站全量物理概率模型升级、方差校准与 2019 样本外终极验收`
- **Ticket 01**: [#115](https://github.com/oasislin/Poly2/issues/115) `Phase 2 Task 08 - Ticket 01: feat(modeling): 扩展训练窗拟合引擎至 Active 10 站并冻结 c_train 与 window`
- **Ticket 02**: [#116](https://github.com/oasislin/Poly2/issues/116) `Phase 2 Task 08 - Ticket 02: feat(calibration): 推进 10 站局地气候偏态(R-6)与极值理论厚尾(R-7)参数化`
- **Ticket 03**: [#117](https://github.com/oasislin/Poly2/issues/117) `Phase 2 Task 08 - Ticket 03: feat(evaluation): 实施 10 站 2019 样本外盲测推演并生成 Parquet 审计底账`
- **Ticket 04**: [#119](https://github.com/oasislin/Poly2/issues/119) `Phase 2 Task 08 - Ticket 04: test(gates): 全量落实现代 ADR-0017 离散化门禁与六重统计指标核验`
- **Ticket 05**: [#123](https://github.com/oasislin/Poly2/issues/123) `Phase 2 Task 08 - Ticket 05: docs(settlement): 交付 Active 10 站唯一法定结算表、独立复算脚本与哈希清单`

