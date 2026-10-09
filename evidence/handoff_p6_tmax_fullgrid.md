# P6-1-HANDOFF: 双城 TMax 全网格验证与方法论封盘交接协议 (Handoff Protocol)

> **工单编号**: `P6-1-HANDOFF`  
> **前置依赖**: `P6-0-DOC-SYNC` 验收通过（Commit `518cd63`）  
> **受控分支**: `feat/p4-audit-reliability-v1.2`  
> **生成时间**: 2026-10-09  
> **执行指引**: **新会话启动时，首条消息输入“请读取并严格执行 evidence/handoff_p6_tmax_fullgrid.md，SHA 校验通过后从事项 1 开始。”**，新会话 agent 必须完全按本文件执行。

---

## 一、 项目身份与任务目标 (Identity & Objectives)

1. **项目身份**:
   Polymarket 温度事件量化合约高精度物理概率定价系统（高精度物理概率模型 $\to$ 离散盘口转换 $\to$ 期望价值与凯利下注决策）。
2. **本任务目标 (P6-2-TMAX-FULLGRID)**:
   - **双城全网格抽检**: 对 `KORD`（芝加哥奥黑尔）与 `KMIA`（迈阿密）两座气候特征迥异的核心交易站点，执行 $2 \text{ 站} \times 12 \text{ 提前期}(12\text{h}\sim 78\text{h}) \times 4 \text{ 季} = \mathbf{96 \text{ 格}}$ 全网格抽检；
   - **复用说明**: 其中 `KORD / 18h / TMax` 4 个季节格直接**完全复用已关门的 v1.3b 终审结论**，不作重复跑数；
   - **实际新增跑数**: 严格完成其余 **92 格** 的 20 折 Block-CV 重采样、独立分布族拟合与可靠度审计；
   - **方法论封盘**: 测定 96 格逐格分布族选型规律、PIT 均匀性及提前期方差衰减曲线，落盘《方法论封盘法定文档》，为接入真实盘预测管道提供唯一量化根据。

---

## 二、 纪律条款全文 (Disciplinary Red Lines)

本仓库开发与审计执行以下**最高铁律**，任何违反即构成无效交付：
1. **先方案后编码（最高铁律）**：任何阶段在用户给出明确执行授权前，只能讨论方案、核查代码、确认思路，严禁擅自修改生产逻辑；
2. **原始观测结果不可篡改（最高铁律）**：凡代码、脚本、测试输出之原始数值（ECE、KS p 值、偏度、超额峰度、失效率等），只允许原样读取、原样汇报，严禁四舍五入、美化、重估或“解释性修正”；
3. **“通过/达标/完成”声明必须附执行证据（硬性）**：声称通过时必须同条输出：①实际执行命令；②输出末尾关键片段；③判定阈值与两步机械判定；未执行测试不得写“通过”；
4. **两步分离机械判定（硬性）**：固定输出格式 `原始观测值 = <原样值>；判定阈值 = <目标值>；结论 = 通过/不通过`；
5. **判定下沉到代码（硬性）**：凡布尔判断一律由脚本/代码输出布尔值，agent 禁止做心算或模型主观判断；
6. **Header 五要素完备性（硬性）**：测试汇报必须包含平台、Python 版本、pytest 版本、根目录、插件 5 项环境要素；
7. **契约测试先行（TDD 硬性）**：新增任何逻辑或参数化函数前，必须先在 `tests/` 下建立契约测试，全绿后方可推进主逻辑；
8. **丢弃 diff 必须留说明（硬性）**：任何丢弃、回滚或重置的操作，必须在汇报中留存 explicit diff 与丢弃原因；
9. **零形容词机械判定（硬性）**：严禁自由发挥或使用未受控形容词，指标只出数值、档位与布尔状态；
10. **零尾巴收口（硬性）**：“测试全绿 + 工件落盘 + 判定结论”一次做完，好坏如实入账；
11. **Git Push 严格遵从人工明确指令（硬性）**：严禁在未获明确指令前执行 `git push`（包括 `git push main` 或 `git push origin`）。

---

## 三、 已完成状态快照 (Completed Status Snapshot)

1. **v1.3b 关门结论快照 (KORD / 18h / TMax 四季)**:
   - **PIT 均匀性 KS 检验**: 统计量 $D = 0.00722$, $p = 0.46915 \gg 0.05$（机械检验 PASS，全局分布极度诚实）；
   - **PIT 重标残差矩**: 偏度 $\text{Skew} = +0.0471$（较旧高斯尺暴跌 92.2%），超额峰度 $\text{Kurt}_{\text{excess}} = +0.0667$（较旧高斯尺暴跌 97.3%，彻底收敛至高斯理论基线 0.0）；
   - **超越数收敛比**: $|z^*| > 2.0$ 发生率比率 $1.11\text{x}$（发生率 5.05% vs 理论 4.55%），$|z^*| > 2.5$ 发生率比率 $1.06\text{x}$（发生率 1.32% vs 理论 1.24%）；
   - **日峰值桶预测概率分布**: P10=`0.2264`, P25=`0.2375`, P50=`0.2766`, P75=`0.2964`, P90=`0.3038`, P99=`0.3118`, Max=`0.3177`；
   - **门禁断言**: 全样本日峰值概率 $\le 35\%$ 断言 **100% 成立**（最大值仅为 31.77%）；
   - **深尾定价与系数**: 右外尾期望命中 148.97 vs 实际命中 191（比率 1.28x，价格差仅 0.31¢），经验比率 **1.28** 入库为 KORD 18h TMax 专属深尾报价抬升系数。
2. **已冻结工件 SHA256 签名清单**:
   - `scripts/audit_p4_reliability_v13b.py`: `b9b750620e24f2175540984a901cd362882cb3807bd60657122da61a1efc8707`
   - `evidence/p4_audit_reliability_v13b_summary.json`: `c513d6a76453d6619d6c98344ce7cab0bd1eb85793360c187e012bd8ca5a3c70`
   - `evidence/p4_audit_reliability_v13b_report.md`: `b7072e8a1c62b4f524f5470a0c4ab0637bb7958b40177930aabc93cf4b78aa6f`
   - `evidence/p4_audit_reliability_v13b_lineage.json`: `b850473be0d90037f6f0f5bd8531f4957280aa0c8ddf890e8e61902329893616`
   - `tests/unit/verification/test_p4_audit_reliability_v13b.py`: `a81f8386b16ab6ffe993865a47d9a34d79cda708bfd1fb7ae6c14b77ef51f217`
3. **版本库状态**:
   - 分支: `feat/p4-audit-reliability-v1.2`
   - 最新 Commit SHA: `518cd63`（P6-0-DOC-SYNC）
   - 回归测试基线: **970 项（960 passed, 10 skipped, 0 failed）**

---

## 四、 关键文件路径清单 (Key File Paths)

| 业务角色 | 文件路径 | 关键内容与修改建议 |
| :--- | :--- | :--- |
| **审计主引擎** | [`scripts/audit_p4_reliability_v13b.py`](scripts/audit_p4_reliability_v13b.py) | 现行 KORD 18h TMax 审计脚本。包含 11 档吸附网格生成、真分布 CDF 差分积分、PIT Probit 重标、实质分档逻辑。**待参数化改造以支持多台站与多时效**。 |
| **Block-CV 测试/入口** | [`tests/unit/modeling/test_p4_block_cv_20fold.py`](tests/unit/modeling/test_p4_block_cv_20fold.py) | 当前第 54 行硬编码 `station = "KORD"`, 第 71 行硬编码 `variable = "tmax"`, `lead_hour = 18`。需解耦为支持 CLI 传参 `--station` 与 `--lead-hour` 的独立批处理执行器。 |
| **重采样与选型核心** | [`src/modeling/resampling.py`](src/modeling/resampling.py) | 包含 20 折 30-Day Block-CV 划分、逐折 BIC 竞争选型（Gaussian vs JohnsonSU vs EVT）及形态参数拟合逻辑。 |
| **折工件与预测存储** | `evidence/cv_fold_{0..19}_predictions.parquet` | 存储 20 折折外预测。每行包含 `target_date`, `obs`, `mu`, `sigma`, `selected_family` 及分布族参数 (`jsu_gamma`~`jsu_lambda` 或 `family_shape_params`)。 |
| **谱带与分档阈值常量** | [`scripts/audit_p4_reliability_v13b.py:62-63`](scripts/audit_p4_reliability_v13b.py#L62-L63) | `STRATA_EDGES = [0.00, 0.03, 0.07, 0.12, 0.18, 0.25, 0.35, 0.50, 1.00]`<br>`SUBSTANTIVE_THRESHOLD = 0.02` (2.0%)。全网格统一恒定，严禁逐格擅改。 |
| **台站宇宙真值定义** | [`src/data_processing/constants.py:395-406`](src/data_processing/constants.py#L395-L406) | `ACTIVE_10_STATIONS`: `KATL, KAUS, KDAL, KHOU, KLAX, KLGA, KMIA, KORD, KSEA, KSFO`。 |
| **封盘文档目标落点** | `evidence/p6_tmax_methodology_closure.md`<br>`evidence/p6_tmax_methodology_closure.json` | P6-2 最终方法论封盘报告与统计摘要落盘路径。 |
| **全网格汇总与衰减表** | `evidence/p6_fullgrid_96cells_summary.json`<br>`evidence/p6_fullgrid_leadtime_decay.json` | 96 格逐格汇总与 12 个提前期方差/PIT 衰减曲线工件。 |

---

## 五、 执行顺序与实施路径 (Execution Sequence)

新会话必须严格按以下 4 个阶段顺序推进：

### 阶段 1：参数化改造与零漂移回归门禁 (Zero-Drift Baseline Gate)
1. **测试先行**: 针对参数化改造后的批处理调用接口编写快速契约测试；
2. **脚本参数化**:
   - 提取 `run_block_cv_20fold` 与 `audit_reliability` 为通用参数化管道，支持 `station`（KORD/KMIA）与 `lead_hour`（12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78）；
3. **逐位零漂移回归断言**:
   - 在传入 `station="KORD"`, `lead_hour=18`, `variable="tmax"` 时，其计算结果必须与 `v1.3b` 已归档的指标**逐字逐位严格一致**（加权 ECE `0.0029`，KS $p = `0.46915`$，偏度 `0.0471`，峰度 `0.0667`，Max 峰值 `0.3177`）；
   - 零漂移验证通过前，**严禁启动任何新格子运算**。

### 阶段 2：92 格全量逐格审计与工件导出 (92-Cell Full Grid Audit)
1. **独立选型执行**:
   - 对 92 个新增格子，严格在折内执行 Gaussian vs JohnsonSU vs EVT 的独立 BIC 竞争与激活门槛（$|\text{Skew}| > 0.40$, $\text{Kurt}_{\text{excess}} > 1.0$）；
   - **红线**：严禁直接预设 Johnson SU 默认胜出，若 BIC 未显著优于高斯（$\Delta\text{BIC} < -10$）或未触发激活门槛，必须客观回退高斯；
2. **逐格可靠度指标导出**:
   - 逐格计算：全量验证日 PIT KS 检验 p 值、重标残差矩（偏度/峰度）、窗口内/全分布六元组与加权 ECE、双尾 Poisson p 值与状态、日峰值桶分位数；
   - 产出各格独立的 summary 与工件。

### 阶段 3：方法论封盘文档编制 (Methodology Closure Dossier)
1. 汇总 96 格分布族胜出矩阵（各季节 $\times$ 各提前期下胜出的分布族：Gaussian / JSU / EVT）；
2. 总结局地对流与海洋气候对分布族偏态的影响规律（芝加哥内陆冷暖锋面 vs 迈阿密亚热带海洋对流）；
3. 形成《双城 TMax 概率分布方法论封盘法定报告》（`evidence/p6_tmax_methodology_closure.md`）。

### 阶段 4：全网格总表与提前期衰减曲线落盘 (Summary & Decay Curves)
1. 导出 96 格指标全景总表（含 ECE、KS p、双尾状态、胜出分布族）；
2. 绘制/导出 12 个提前期 ($12\text{h} \to 78\text{h}$) 下不确定性方差膨胀、ECE 漂移及峰值桶概率衰减曲线；
3. 申报全部交付工件 SHA256 校验和与新基线。

---

## 六、 红线条款与禁止事项 (Forbidden Actions)

1. **严禁跨格移植专属参数**:
   - 1.28 深尾报价抬升系数仅适用于 KORD 18h TMax，**严禁套用至 KMIA 或其余提前期**；
   - KORD 18h 的 JSU 四参数（$\gamma, \delta, \xi, \lambda$）为局地拟合产物，**严禁跨格复制**；
   - $\le 35\%$ 锋利度断言为 KORD 专属检验，KMIA 亚热带低方差环境下日峰值概率可能自然偏高，**严禁套用 35% 门禁去判定 KMIA 失准**；
2. **严禁改动机械判定层**:
   - Wilson 95% 置信区间判定、加权 ECE、Poisson 上尾检验判定逻辑与阈值一字不动；
   - 实质分档阈值维持 `SUBSTANTIVE_THRESHOLD = 0.02` 恒定；
3. **严禁擅自修改统计方法**:
   - 在封盘文档正式归档前，严禁中途修改任何分布定义、优化器或门禁判定代码；
4. **严禁代跑 push**:
   - 未经用户明确指令，绝不在终端执行 `git push`。

---

## 七、 待裁决升级路径 (Escalation Triggers)

执行过程中若遭遇以下任一情形，**立即停下工作，保存当前状态并呈报用户/委员会裁决，严禁 agent 自行主观处置**：
1. **KMIA 胜出非 JSU 分布**: 若迈阿密某提前期或季节胜出 EVT GPD 混合分布，或无显著偏态回退高斯；
2. **某格 KS 检验严重不过**: 若某格在胜出分布族下 PIT KS 检验 $p < 0.01$；
3. **结算站点数据争议**: 若发现 KMIA 在历史观测数据中存在站址搬迁、RMK T 组缺失或单位异常；
4. **零漂移断言破缺**: 若参数化重构导致 KORD 18h 原有指标发生哪怕千分之一的浮点漂移。

---

## 八、 完成定义与验收标准 (Definition of Done)

工单 P6-2 的最终验收条件为**全部一次收口，缺一不可**：
1. **92 格逐格报告完整落盘**: 全部 92 个新增格子的 20 折 Block-CV 工件与审计结构化数据入库；
2. **零漂移门禁证据**: 提供参数化管道对 KORD 18h TMax 逐位无漂移的回归测试 stdout；
3. **方法论封盘文档落盘**: `evidence/p6_tmax_methodology_closure.md` 与 `.json` 完备归档；
4. **96 格全景总表与衰减曲线**: `evidence/p6_fullgrid_96cells_summary.json` 与衰减曲线分析落盘；
5. **全库回归 0 failed**: 保持所有契约与历史测试 100% 绿灯；
6. **SHA256 校验清单完备**: 列出所有核心交付工件的 SHA256 签名；
7. **等待人工验收指令**: 提交 commit（不 push），等待人工验收并下发第三阶段（真实盘管道接入）指令。
