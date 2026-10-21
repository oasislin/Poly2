# P8-CLASS1-LAUNCH-CHK-05 · Task 01~07 处置建议复核单（开发端盘点表 + ADR-0019 定稿审阅）

> **日期**：2026-10-21
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-05`（父工单第 5 号核验单）
> **复核对象**：
> 1. `P8-CLASS1-LAUNCH-TASK-INVENTORY_Task01-07状态盘点与处置建议表_20261021.md`
> 2. `docs/adr/ADR-0019：物理模型参数向投注算法消费契约与解耦架构.md`（APPROVED 定稿）
> **复核方式**：审核方只读；逐条对照 v2.1 任务矩阵、P7-ALGO-VERDICT、P7-ALGO-2 裁决记录、DECISION_LEDGER、ROADMAP/SEALING_GATE、本地代码与 data/models 实测

---

## 一、 总体结论

- **七项处置建议：五项核准、两项需改口径后核准**（P-1 Task 01、P-5 Task 04）；
- **ADR-0019 定稿：核验通过**（编号未占用、矩阵列名准确、数值修正到位、F-2 锁与版本戳齐全）；
- **新任务编号：开发端推荐路径 1（原地重建 05）不予背书，推荐路径 2（Task 08）**，理由见 §三 P-4。

---

## 二、 逐项核验结果

| 任务 | 处置建议 | 复核证据（审核方独立核） | 核验结论 |
| :-- | :-- | :-- | :-- |
| **Task 01** | Close（封盘） | 960 规格 / **实测 data/models 顶层 1200 pkl + archive_legacy 800 = 2000**（manifest.json 存在）；DECISION-20261021-06 V2R01 终审闭环 ✓；但 **P5/P6 审计仅覆盖双城 TMax 24 时间格**（SEALING_GATE：96 季节格 100% 跑数、23/24 格 ECE≤0.0100、KMIA_12h 0.0183 挂旗），ROADMAP 明载其余 8 站 TMax 与全量 TMin 审计覆盖率 **0%** | **不核准（口径过宽）** → P-1 改收窄口径后核准 |
| **Task 02** | Close（封盘） | 代码在役：`src/pipeline/stream_confluence_pipeline.py`、`observation_stream.py`、`truncated_probability_engine.py`、`monotonic_confluence.py`；测试文件齐备（test_monotonic_confluence / test_scenario_d / test_w2_confluence_exemptions） | **核准**（P-3 补证据引用） |
| **Task 03** | 保持停止/顺延 | R-16 归档属实（archive/.../src/risk/）；v2.1 原文 DEFERRED_TO_PRE_LIVE；第一类为只读纸面盘，不涉真实挂撤单 | **核准** |
| **Task 04** | 收口 Close（物理映射封盘） | `discrete_bin_engine.py`/`constraint_enforcer.py`/`dynamic_corrector.py` 在役且测试文件齐备；`ev_engine.py` 已归档 | **不核准（标注缺失）** → P-5 补"交易 EV 未完成、移交新任务"后核准 |
| **Task 05** | 废除 | M-1 判词（EMOS 闭式 CDF 重写、θ/η 不继承，VERDICT L24-38）✓；DR-02 τ 前置唯一化 ✓；DR-03 B_eff ✓ | **核准** |
| **Task 06** | 废除 | 只买不卖宪法（VERDICT L58/L106）✓；DR-01 S_target 探针 ✓ | **核准** |
| **Task 07** | 终止 | DR-04 z 标准化残差 ✓；WSS 盘口门禁不符工程现实（AGENTS.md 严禁凭空预设未接入基础设施）✓ | **核准** |

---

## 三、 修正项（开发端执行，P-1~P-5）

### P-1（关键）· Task 01 Close 必须收窄口径
- **原始观测**：SEALING_GATE「双城 TMax 96 季节格（24 时间格）20 折 Block-CV 100% 完成，23/24 格 ECE≤0.0100，1 格挂旗」；ROADMAP「其余 8 站 TMax 覆盖率 0%、全量 10 站 TMin（480 格）审计覆盖率 0%」。
- **判定**：Task 01 定义"960 模型矩阵通过 P5/P6 审计体系验收"——**960 落盘已完成，但 P5/P6 审计仅双城 TMax 闭合**，全量网格审计未完成。
- **修正**：盘点表改口径为「**按 W2 收窄口径 Close**：960 生产模型落盘 ✓ + 双城 TMax 24 时间格 P5/P6 审计封盘 ✓ + V2R01 尺子闭环 ✓；其余 8 站 TMax 与 10 站 TMin 审计余量标注顺延至 W3/实盘前置」。第一类任务仅消费双城 TMax 22 格（全部已审计），不受影响。
- **用户裁决项**：是否同意按收窄口径关闭 Task 01 并标注余量顺延。

### P-2 · 模型落盘数量以实测为准
- **原始观测**：`data/models` 顶层 **1200** 个 .pkl + `archive_legacy_20260920` **800** 个 = 2000；manifest.json 存在。
- **修正**：盘点表观测值如实写 1200（顶层），960 标注为规格口径（10 站×2 标的×4 季×12 lead），并附 manifest.json 构成核对说明（差异构成：含何类变体/6h 池化/额外 lead），不得以规格数代替观测数。

### P-3 · 测试证据补执行输出（AGENTS.md 硬性）
- Task 01/02/04 的"测试全部通过"未附命令+输出末尾片段+通过数+阈值。
- **修正**：补 `python3 -m pytest … -q` 实际输出片段；或引用 Step 0-3 已记录的 `113 passed in 2.33s`（覆盖 tests/unit/prediction + tests/unit/risk）并逐条注明所列测试文件在该运行内。

### P-4 · 新任务编号：推荐路径 2（Task 08），不背书路径 1（原地重建 05）
- **理由**：
  1. AGENTS.md 历史向前兼容条款：已完成/已冻结 Issue 保持原貌、**杜绝引用断裂**——Task 05 作为历史 Issue 关闭后仍留档，复用编号将产生**同阶段双义"Task 05"**（旧=资金凯利，新=第一类），历史文档全部引用歧义化；
  2. 命名规范精神：严禁易生歧义的编号复用；
  3. 01~07 全部处置完成后（01/02/04 Close、03 顺延、05/06 废除、07 终止），**08 为序列首个空闲号**，紧凑且零歧义；
  4. 用户先前"多出 08 不合适"的表述语境是 01~07 未处置；处置完成后再立 08 不与之冲突。
- **用户裁决项**：路径 1（开发端推荐）/ 路径 2（审核方推荐）/ 用户指定。

### P-5 · Task 04 处置措辞补未完成标注
- 交易 EV 部分（EVCalculator 动态策略）未交付、已归档，须由新第一类任务按 DR-2026-1014-01 探针与新费率契约承接重写。
- **修正**：措辞改「**Task 04 收口 Close：物理概率映射部分封盘；交易 EV 部分未完成，移交新任务**」——禁止将未完成部分混入 Close 掩盖。

---

## 四、 ADR-0019 定稿核验（通过）

- 编号 0019 未占用 ✓；参数矩阵仅列名无列号 ✓；KMIA_12h=0.871233 / KORD_18h=0.909589 修正到位 ✓；22 格组织 ✓；G-1 正交化（S_conf 剔 x_s、ψ 独占方差）✓；G-2 双防线 ✓；过自信边界 ✓；版本戳 SHA256 看门狗 ✓；C_max 折剪点唯一化 ✓。
- 一处待标注：§6「重测触发流程 `trigger_model_retest.py`」为新建/包装脚本名，当前主树未见该脚本——需在 Ticket 04 中标注为新实现（包装 `evaluate_p4_2019_settlement.py`），并注明与 V2R01 复现命令一致。

---

## 五、 呈请用户裁决（8 项）

1. Task 01：按**收窄口径** Close（960 落盘 + 双城 TMax 审计封盘 + V2R01 闭环；余量网格审计顺延 W3/实盘前置）？
2. Task 02：Close？
3. Task 03：保持顺延？
4. Task 04：收口 Close（物理映射封盘 + 交易 EV 未完成移交新任务）？
5. Task 05：废除？
6. Task 06：废除？
7. Task 07：终止？
8. 新任务编号：**路径 1（原地重建 05，开发端推荐）/ 路径 2（Task 08，审核方推荐）/ 用户指定**？

用户裁决后，开发端按 P-1~P-5 修正盘点表并复呈；复核通过即生成 gh 发布命令（Spec 主 Issue + 24 票，全拼前缀 + Blocked by），交用户执行。
