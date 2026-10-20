# 悬置裁决台账 (Decision Ledger)

**工单基准**：P7-ALGO-1B（v1 资产入库、零费率缺陷修复与登记）  
**创建时间**：2026-10-12  
**维护纪律**：按《AGENTS.md》审计纪律，本台账记录历史考古与审计排查中发现的所有未决事项、技术债务、设计分歧与悬置项。任何条目状态的流转必须附带证据（Commit Hash、文档章节或用户明确裁决令），严禁私自销项或篡改。

---

## 一、 P7-ALGO-1 卷宗 §6 五项未决事项状态追踪

| 编号 | 事项名称 | 原始发现（P7-ALGO-1 卷宗 §6） | 最新状态 | 处置依据 / 对应工单 / 证据 |
| :--- | :--- | :--- | :--- | :--- |
| **UNDECIDED-01** | 外部 v1 算法资产与当前代码库物理隔离 | v1 完整策略代码在外部目录 `Polymarket天气套利/`，本库零检入 | **已入库 (只读隔离)** | **P7-ALGO-1B Task 1** 已完整镜像至 `legacy/v1-strategy/`，附带隔离 `README.md`，禁止执行/import/构建/测试。Commit: `8b9f05b` |
| **UNDECIDED-02** | 费率模型在 v2 中降级为零费率假设 | `ev_engine.py` 硬编码 `fee_rate = 0.0`，低价 Token 存在严重负 EV 隐患 | **已修复** | **P7-ALGO-1B Task 2** 已对齐 v1 `strategy.py:691` 动态公式：$q = p \times [1 + \text{base\_fee} \times (1 - p)]$；Maker 联动返佣公式已实现；单测全绿。Commit: `0f1ac61` |
| **UNDECIDED-03** | 稳健凯利 Minimax 在 v2 中缺失 | `multinomial_kelly.py` 仅为普通点估计多项凯利，缺失 $(\theta, \eta)$ 不确定集投影 | **挂起 (C-1)** | 登记为独立演进候选，待用户后续授权与算法评审裁决 |
| **UNDECIDED-04** | Dutch Book 跨档锁利与对冲豁免机制在 v2 中缺失 | 缺失反向 NO 与全包 YES 锁利与 $C_{\text{loc}}$ 预算豁免逻辑 | **挂起 (C-2)** | 登记为独立演进候选，待实盘/纸面盘观察期根据盘口流动性裁决 |
| **UNDECIDED-05** | 两步标定法脚本未随文档入库 | 《参数标定方案》v1.0 配套脚本滞留外部，本库无复现脚本 | **已入库 (只读隔离)** | **P7-ALGO-1B Task 1** 已随 v1 资产完整入库至 `legacy/v1-strategy/scratch/`（含 `calibrate_financial_params.py` 等）。Commit: `8b9f05b` |

---

## 二、 C 类三案挂起条目 (Deferred Candidate Proposals)

依据 P7-ALGO-1 考古卷宗 §5.2，v2 在交易侧重构时与 v1 发生了一次断层式简化。以下三项列入悬置候选池，**严禁在无明确授权前擅自编写生产代码**：

### 1. 提案 C-1：多项稳健凯利 Minimax 不确定集最坏情况投影 (Robust Kelly Minimax)
- **历史事实**：v1 `strategy.py:243-345` 实现了 `project_worst_case_probabilities(p_model, q_market, theta, eta)`，在水深不足或天气噪声大时，将预测概率 $p$ 向市场价格 $q$ 作有界最坏情况收缩，有效抑制凯利过度下注。
- **当前现状**：v2 `src/bankroll/multinomial_kelly.py` 仅使用点估计概率 $p$ 求解 SLSQP。
- **挂起状态**：**【挂起待裁决】**。待气象端 EMOS 置信区间（或 CRPS 分布参数）与交易端衔接成熟后，由专门的架构评审决定是否引入 Minimax 投影或作为可插拔层接入。

### 2. 提案 C-2：Dutch Book 跨档无风险反向锁利与 $C_{\text{loc}}$ 预算豁免 (Dutch Book & Hedging Exemption)
- **历史事实**：v1 `strategy.py:734-770` 实现了当全档位赔率倒挂（$\sum q_i < 1.0$）或反向 NO 存在确定性套利空间时，触发跨档锁利，并在资金池中豁免其 $C_{\text{loc}}$ 预算上限（因其为确定性回笼而非风险暴露）。
- **当前现状**：v2 纸面盘目前只支持单方向购买 YES 离散档位，无反向 NO 机制，无跨档套利状态机。
- **挂起状态**：**【挂起待裁决】**。属于多资产组合套利高级功能，在 W2 纸面盘基础闭环稳固前保持冻结。

### 3. 提案 C-3：两步标定法反事实模拟参数寻优 (Two-Stage Parameter Calibration Pipeline)
- **历史事实**：v1 《天气套利参数标定与联合优化方案》v1.0 与 `calibrate_financial_params.py` 实现了基于历史盘口与气象预测缓存反事实回测搜索 $(\theta, \eta, \gamma)$ 最优超参的自动化流程。
- **当前现状**：v2 目前使用执行文件与 ADR 预设的经验参数，尚未建立针对 Polymarket 历史分钟级盘口的反事实标定流水线。
- **挂起状态**：**【挂起待裁决】**。配套脚本已在 `legacy/v1-strategy/scratch/` 归档。待后续盘口高频数据累积充足后，再行评估是否复现为 Phase 2 生产级标定工具。

---

## 三、 本工单（P7-ALGO-1B）执行记录与凭据

### 1. 代码与工件改动清单

| 类别 | 相对路径 | 改动性质 | 关联任务 |
| :--- | :--- | :--- | :--- |
| **Legacy 资产** | `legacy/v1-strategy/` | 新建目录（含只读 `README.md`、策略源码、配置与 scratch 脚本） | 任务 1 |
| **定价核心** | `src/pricing/ev_engine.py` | 修正：移除 `fee_rate: 0.0` 默认假设，落地动态 Taker 费率与 Maker 返佣公式 | 任务 2 |
| **单测套件** | `tests/unit/pricing/test_ev_engine.py` | 新增：3 个测试用例（动态 Taker 费率、Maker 返佣、低价档位敏感性验证） | 任务 2 |
| **采集适配** | `src/data_acquisition/polymarket_clob_collector.py` | 适配：恢复 `ACTIVE_10` 站点映射导出接口保障单测自洽 | 任务 2 附属 |
| **审计台账** | `docs/audit/DECISION_LEDGER.md` | 新建：悬置裁决台账，追踪未决事项与 C 类提案 | 任务 3 |

### 2. 独立 Commit 凭据

- **任务 1 资产入库 Commit**：
  - Hash: `8b9f05b7647fb515b37092dbce9984070b91feeb`
  - Message: `chore(legacy): 入库 v1 策略代码与配置资产作为只读考古参照`
- **任务 2 缺陷修复 Commit**：
  - Hash: `0f1ac6153d801a13a88d4cee6307c4e7fa6ad49e`
  - Message: `fix(pricing): 修复零费率缺陷并落地 v1 动态费率与 Maker 返佣公式`
- **远端同步状态**：
  - 本地处于分支 `fix/p7-w2-shortloop`；
  - 严格遵守《AGENTS.md》铁律，**未执行 `git push`**。

---

## 四、 P7-ALGO-VERDICT-DOC 判决书落盘与对应关系登记

### 1. 判决书落盘凭据
- **文件路径**：`docs/audit/P7-ALGO-VERDICT.md`
- **版本与状态**：v0.2，框架定稿、判词除 M-2 外留白
- **落盘 Commit**：`8d68d93bb5273185f8d2758f1031fbbfbd7121dd`（`docs: P7-ALGO-VERDICT v0.2 框架定稿`）

### 2. M-2 已闭环判词登记
- **条目**：M-2 动态费率模型
- **判词内容（已裁，2026-10）**：
  > 流程与方式确认无误；代码实现细节留一次复核（实盘亏损与费率无关，用户确认）。v2 修复（P7-ALGO-1B）予以追认；base 值与动态结构的对外核实一次后此条闭环。
- **关联台账状态**：UNDECIDED-02 已修复并闭环。

### 3. C 类三案挂起状态与判决书对应关系核验及解锁（2026-10-13 用户签署）
依据 2026-10-13 用户对《v1 遗产判决书》v0.2 之最终逐条签署（见 `REMEDIATION_PLAN.md` §五），C 类三案状态正式由【挂起】流转为【已解锁】（解锁语境 = P7-ALGO-2 算法规格书编制）：
- **提案 C-1 (shrinkage / Minimax 关联)** $\Longleftrightarrow$ **判决书 M-4 (胜率向市场价收缩 Shrinkage)**：**【已解锁 · 裁决废弃】**（微观结构报告证实我方物理信息优势，不移植 v1 Sigmoid 市场收缩，由概率层 𝒫 区间承担防守）；
- **提案 C-2 (Dutch Book & 对冲豁免)** $\Longleftrightarrow$ **判决书 M-3 (Dutch Book 扫描与对冲豁免)**：**【已解锁 · 裁决保留】**（作为独立通道不走凯利目标函数，豁免经 ADR-0014 中枢统一登记，写入 P7-ALGO-2 规格）；
- **提案 C-3 (两步标定法)** $\Longleftrightarrow$ **判决书 M-5 (两步标定法 Brier σ 标定 + 反事实 sizing)**：**【已解锁 · 框架复用】**（θ/η 网格搜索框架进规格；标定对象重定义为 EMOS 时代口径；挂 F-2 锁等待纸面盘自产数据，v1 历史样本不作先验）。

---

## 五、 REMEDIATION_PLAN 本地执行记录 (2026-10-13)

| 整改项 | 类别 | 实际执行动作 | 状态 |
| :--- | :--- | :--- | :--- |
| **R-04 & R-05** | 命名基线 | 修订《项目方案 (v2.8)》与《Phase 2 执行文件 v2.1》，彻底清理非法 "Phase 4~7" 描述，确立 Phase 1/1.5/2/3 四阶段 + 工单 P4~P7 + 任务 Task 01~07 + 波次 W1~W3 体系 | ✅ 已完成 |
| **R-06** | ADR 命名 | 统一为 `ADR-XXXX：中文主题.md` 单文件规范，完成 ADR-0001~0006 与 ADR-0018 重命名 | ✅ 已完成 |
| **R-07 & R-08** | ADR 治理 | 确认删除 ADR-0016 缺失占位；正式废止引用该文件的 ADR-0017，移入 `docs/archive/` 归档 | ✅ 已完成 |
| **R-13** | 历史文档归档 | 将方案历史版本（v2.2~v2.7）、执行文件旧版（Phase 1/1.5/2）、历史子任务单及早期英文文档统一移入 `docs/archive/`，新建索引 `docs/archive/README.md` | ✅ 已完成 |
| **R-16** | 交易模块归档 | 依据方案 B 将 `src/`（27）、`tests/`（20）、`scripts/`（5）共 52 文件移入 `docs/archive/trading_modules/` 并新建 `README.md`（共 53 文件）；保留 `src/risk/stream_watchdog.py` 原位依赖；全量现役测试通过（649 passed） | ✅ 已完成 |
| **R-18** | 代码卫生 | 移出 `src/data_acquisition/` 中的 Wunderground 历史抓取脚本至 `docs/archive/wunderground_scripts/`，清理 `__init__.py`，跑通单测（157 passed, 4 skipped） | ✅ 已完成 |

---

## 六、 V1 盲测完善支线 T3 阶段一检测记录 (2026-10-20)

| 编号 | 事项名称 | 原始发现与实验设计 | 最新状态 | 处置依据 / 对应工单 / 证据 |
| :--- | :--- | :--- | :--- | :--- |
| **DECISION-20261020-01** | T3 阶段一 P-1 c_train 截断离线对照实验（E8-a/E8-b，KORD/KMIA） | 1. **E8-a 锚点原值复算（2000-2018）**：8 个站×季锚点（KORD/KMIA × 4季）未截断 $c_{\text{train}}$ 范围为 $[1.040819, 1.135775]$，**触界计数 0 / 8**，均未触碰 $[0.85, 1.35]$ 上下界。<br>2. **E8-b 留一年滚动对照（2000-2018，152 折）**：未截断 $c_{\text{train}}$ 范围为 $[1.035384, 1.154511]$，**触界计数 0 / 152**。Variant A (clip[0.85, 1.35]) 与 Variant B (完全不截断) 在所有 152 折测试年中的 $s_{\text{oos}}$、CRPS 与 90% coverage 完全逐位一致。<br>3. **实证结论**：实测推翻假说 H1（1.35 截断导致样本外失真），实证支持观察 H2（c_train 截断非失真因果，18h 标量缺乏 lead 维度及年际波动由分散度独立承担）。 | **审核通过（2026-10-20 机械判定）**：E8-a 触界 0/8、E8-b 152 折 A/B 三指标 max|Δ|=0.0；**H1 推翻、Q8 关闭，不为此重训**；结论限 KORD/KMIA × 2000-2018 × 18h 锚点层，不外推其余 8 站。Commit 2 `ee79e99` | 1. 任务书：`docs/audit/T3-第三类重训检测_开发端任务书_20261020.md`<br>2. 检测脚本：`scripts/audit_t3/offline_t3_detection.py` (SHA-256: `39bda1b202eb317fdfb2e13e0e56e32ab8da5cc22d0fe43aa2eee636f4443ac3`)<br>3. 原始数据：`evidence/audit_t3/t3_e8a_anchor_raw.csv` (SHA-256: `c7880c2a3e2e96d1bb338d46efc09b20aa9882230ba05ba6d4995aaae56683a5`)<br>4. 对照数据：`evidence/audit_t3/t3_e8b_rolling_loyo.csv` (SHA-256: `6dffbbc4fd9a5b91da4ad1999cd3226e779f679ef8d6223d4768a74909375585`)<br>5. 提交凭据：Commit 2 `ee79e99` |

---

## 七、 V1 盲测完善支线 T3 阶段二检测记录 (2026-10-21)

| 编号 | 事项名称 | 原始发现与实验设计 | 最新状态 | 处置依据 / 对应工单 / 证据 |
| :--- | :--- | :--- | :--- | :--- |
| **DECISION-20261021-01** | T3 阶段二 lead 维离散度归因诊断 D-1/D-2（服务 P-3/P-2，KORD/KMIA） | 1. **D-1 全格离散度归因（88 格）**：计算未含 $c_{\text{train}}$ 的纯格级离散度匹配比 $raw\_ratio = Var(resid_{calib}) / mean(c^2 + d^2 \cdot ens\_var)$。发现 $raw\_ratio$ 沿 lead 呈现显著 24h 周期性日变化特征（如 KORD Winter 在 18h/42h/66h 达 1.19~1.22，而在 36h/60h 降至 1.04~1.05）。生产模型 $c_{\text{train}}$ 采用 18h 标量（1.1055，对应方差扩张 1.2221），导致在 36h/60h lead 产生人工方差高估/欠自信下压（$s_{\text{oos}} \approx 0.86$），从机理上完整复现并解释了 V1 盲测中 KORD $s_{\text{oos}}$ 震荡现象。<br>2. **D-1 噪声基线对照（KORD 19 折 LOYO）**：KORD 逐季逐 lead 的相邻步进 $|\Delta raw\_ratio|$（如 0.14~0.17）达对应折间自然噪声标准差 $\sigma_{\text{fold}}$（0.01~0.02）的 3~11 倍，实证 lead 维震荡并非样本折间随机扰动，而是强物理/日变化特征。<br>3. **D-2 参数跳变描述**：全窗 $(a, b, c, d)$ 沿 lead 原始数值与差分已全量提取入表，供审核方机械判定。| **审核通过（2026-10-21 机械判定）**：D-1 周期结构超噪声（9.2~16.9 倍）、锚点除法机制成立；**P-3 不进单调正则，转 `P4-BLIND-AUDIT-CHK-03` 相位归因；P-2 收缩证据不足暂不进入**。更正 manifest hash 笔误（真实 `8bb364e2…`）；KMIA 系统性 >1.2 单列待查。 | 1. 任务书：`docs/audit/T3-阶段二_lead维归因诊断_开发端任务书_20261021.md`<br>2. 诊断脚本：`scripts/audit_t3/lead_attribution.py` (SHA-256: `b8dc80a27f671aba685f2f4ee6ae357a31ad23f9fb08c80f409cd9f62a96a4e8`)<br>3. 全格归因表：`evidence/audit_t3/t3_d1_lead_attribution.csv` (SHA-256: `1fa63317d49eb7a410222ce0378ba6648e57beb81b9c29ab11b284b93f4a1407`)<br>4. 沿 lead 序列表：`evidence/audit_t3/t3_d1_lead_sequence.csv` (SHA-256: `b64924f492f5e1c3816b68a8b79802261db0519edfddad8f5599fd157e4c0e6d`)<br>5. 提交凭据：Commit 1 `1707e56` + Commit 2 `f05bdb1` |

---

## 八、 P4-BLIND-AUDIT-CHK-03 相位归因检测记录 (2026-10-21)

| 编号 | 事项名称 | 原始发现与实验设计 | 最新状态 | 处置依据 / 对应工单 / 证据 |
| :--- | :--- | :--- | :--- | :--- |
| **DECISION-20261021-02** | CHK-03 lead 24h 周期相位归因只读诊断（KORD/KMIA） | 1. **相位分组跨季一致性（32 行）**：UTC 相位 $lead \pmod{24}$ 四组中，KORD 四季 group_mean 相位 12h=0.9880（谷）至相位 18h=1.1381（峰）；KMIA 四季 group_mean 相位 18h=1.2757（谷）至相位 0h=1.5006（峰）。同相位内不同 lead 高度聚合（如 KORD 冬相 0h leads 24/48/72 极差仅 0.0247，CV 1.2%）。<br>2. **跨年稳定性（152 行）**：KORD 2000-2018 逐年跨年相位峰谷高度稳定重复（18/19 年 18h 显著高于 12h）；KMIA 按指导表项留空。<br>3. **实证结论**：实证强烈支持假设 (a) 物理日循环相位成立（非拟合伪影），为后续「分相位离散度」建模提供实证依据。 | **诊断完成，待审核方机械判定** | 1. 任务书：`docs/audit/P4-BLIND-AUDIT-CHK-03_相位归因_任务书_20261021.md`<br>2. 诊断脚本：`scripts/audit_t3/phase_attribution.py` (SHA-256: `f0c552cd8151a037bb5e8ceec26424c263c21b39053fe5a647dc0988c7797536`)<br>3. 相位分组表：`evidence/audit_t3/p4blind_chk03_phase_group.csv` (SHA-256: `3ddd99564804edf332562797015fda9596ba6338524b346cb12c97359f3d11eb`)<br>4. 跨年相位表：`evidence/audit_t3/p4blind_chk03_year_phase.csv` (SHA-256: `348b55c9a871a43b3864d33009d081b0fc6ef238a49f624c5599947e48926f18`)<br>5. 提交凭据：见本次 Commit 2 |




