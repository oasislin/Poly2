# 算法审阅侧待确认事项登记册（定稿版）

> **文件性质**：登记装置，非裁决记录。决策权归业主；数学强制类结论的代签记录见首部。  
> **落盘建议路径**：`docs/audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md`  
> **维护规则**：活文档。事项关闭时标注关闭日期与依据（裁决/工单/提交 SHA），条目不删除。

---

## 第〇部分：B-1 签收记录（审计链）

### 签收对象
- $c \equiv \sigma_{\text{adj}} / \sigma_{\text{eff}} = \sqrt{\max(1, s_{\text{oos}})}$（无量纲标准差乘数）
- $Y = \mu_0 + c \cdot (X - \mu_0)$（随机变量形式）
- $F_{\text{inflated}}(y) = F_{\text{family}}(\mu_0 + (y - \mu_0)/c)$（CDF 形式）
- **高斯核验**：$X \sim \mathcal{N}(\mu_0, \sigma_{\text{eff}}^2) \implies Y \sim \mathcal{N}(\mu_0, c^2\sigma_{\text{eff}}^2) = \mathcal{N}(\mu_0, \sigma_{\text{adj}}^2)$，即 $F_{\text{inflated}}(y) = \Phi((y - \mu_0)/\sigma_{\text{adj}})$——与 `sigma_adj.py` 现行口径逐点一致。
- **方向语义**：$s_{\text{oos}} \le 1$ 时 $c = 1$（恒等映射）；过自信方向（$s_{\text{oos}} < 1$）由 $\psi$ 折减处置（ADR-0019 分工，继承既有裁决，非新决策）。
- **等价实现**：标准化 Z 空间形态参数冻结（JSU 的 $\gamma, \delta, \xi, \lambda$；EVT_Hybrid 的 $u_L, u_R, \xi_L, \xi_R, \beta_z$），在线仅将特征尺度 $\sigma_{\text{eff}}$ 代换为 $\sigma_{\text{adj}}$。与 `reliability_v2.py` 及 `evaluate_p4_2019_settlement.py` 现行逻辑一致，接线近零成本。

### 签收方式
2026-11-13，业主委托算法审阅侧代签（业主明示“你来定”）。

### 代签正当性
该结论为数学强制，非偏好性决策。三重独立证据收敛：
1. **校准要求唯一确定**：调整后方差须等于实测误差方差 $\text{Var}(e_{\text{oos}}) \implies \sigma_{\text{adj}}^2 = s_{\text{oos}} \cdot \sigma_{\text{eff}}^2 \implies$ 乘数必为 $\sqrt{s_{\text{oos}}}$，无第二解；
2. **代码权威**：`sigma_adj.py` 现行实现即此式；
3. **双向独立推导收敛**，且过程中的转录错误（两侧合计三处）经交叉比对全部暴露并修正。

### 业主保留撤销权
任何后出裁决或反证（含 C-1 三检验超限）可重开本条，按维护规则标注。

### 数值警示（防转录滑脱复发）
$s_{\text{oos}} = 1.44 \implies$ 正确 $\sigma_{\text{adj}} = 1.2 \cdot \sigma_{\text{eff}}$。若误用 $s_{\text{oos}}$ 本身作乘数（$1.44 \cdot \sigma_{\text{eff}}$），方差膨胀 2.07 倍而非 1.44 倍，多膨胀 44%，人为过度保守，宽档定价失真。乘数是 $\sqrt{\max(1, s_{\text{oos}})}$——不是 $s_{\text{oos}}$，不是 $\max(1, s_{\text{oos}})$。

---

## 第一部分：勘误类（Phase 0 一并落）

### A-1 SPEC 勘误：$\sigma_{\text{rem}}$ 地板公式量纲笔误 ｜ 已定
SPEC 原式 $\max(\eta_s, (0.9\sigma_0)^2)$ 无量纲与 $^\circ\text{F}^2$ 混用，字面不可实现。勘误为 $\sigma_{\text{rem}}(t) = \max(\sigma_0 \cdot \sqrt{\eta_s(t)}, 0.9^\circ\text{F})$。依据：开发侧回执 A2 的代数恒等式证明（audit 脚本实现即此式，代码对、SPEC 错）。笔误级，不改语义。

### A-2 注记作废：“匹配分位”句 ｜ 已定
`docs/audit/P8-ALGO-AUDIT_20261112.md#L179` 的“（若 R2 获胜分布族为 JSU/EVT_Hybrid，优先用该家族匹配分位…）”无裁决、无 SPEC 支撑（2026-11-13 考古确认“匹配分位”公式全仓不存在），且与 SPEC 取法 C 高斯主式冲突。作废，替换为：“有观测分支按 SPEC 取法 C 高斯桥执行；族形状经无观测分支与 A/B 升级接口生效。”

### A-3 权威序处置记录：11-06“阶段分离”建议 vs ADR-0019 ｜ 已定
`CHK-01-ANNEX-1` 建议生产暂用纯高斯系评审讨论（未升格法条）；ADR-0019（裁决级，2026-10-21）要求 JSU/EVT 必须向投注端消费且未被后出裁决推翻。处置：ADR-0019 胜出；其 $\le 5\text{ms}$ 性能验收项剥离保留（见 C-2）。

---

## 第二部分：定稿公式与口径类

### B-1 $\sigma_{\text{adj}}$ 非高斯膨胀的仿射形式 ｜ 已定稿（2026-11-13，签收记录见第〇部分）
唯一性依据：保序单调 + 全部标准化矩不变 + 高斯退化与现行一致，三条件唯一确定均值中心仿射形式。中位数中心被否决（引入 $(s-1)(\mu_0 - m_0)$ 系统偏移，破坏 MOS 与 $b_{30}$ 标定）；仅膨胀 $c_{\text{train}}^2$ 被否决（高离散日欠补偿，开发侧 P4 反证成立）；非参数重映射被否决（365 样本尾部仅 $\sim 18$ 点 + 阶梯伪影致窄档定价死锁）；形态参数形变被否决（参数强耦合 + $\xi \ge 0.5$ 矩崩溃风险 + 过拟合）。

> **增补锚定语义（2026-11-13 业主裁定追加）**：变换保持锚-形状分解 $X = \mu_0 + \sigma \cdot Z$ 之 $(\mu_0, Z)$ 不变，仅 $\sigma \to \sigma_{\text{adj}}$；高斯格退化为严格均值守恒；非高斯格 $\mathbb{E}[T(X)] = \mu_0 + \sigma_{\text{adj}} \cdot \mathbb{E}[Z]$，偏态离差期望随尺度同比例放大，系 $s_{\text{oos}}$ 校准语义（标定锚 $e = y - \mu_{\text{calib}}$）的忠实执行。  
> **EVT 伪影处置记录**：$\mathbb{E}[Z] \ne 0$ 系两尾分立拟合的无约束伪影，锚定语义下无害；不在族拟合阶段加均值守恒约束，不改 Scheme B，不重算 2019 基准——防止顺手优化。  
> **第二件规格更新**：`prior_mu` 不入静态字段（manifest 已有 $a/b/b_{30}$，消费端组装修）；矩层仅 $\sigma$ 侧（`prior_sigma` / `moment_source` / `moment_note`），原字段规格其余不变。

### B-2 $\eta_s$ 标定器口径 ｜ 已定（Phase 1.3 前置定义）
$\eta_s(t) \equiv 1 - \text{Var}_d(M_t(d)) / \mathbb{E}_d[\sigma_0^2(d)]$，其中 $\sigma_0(d) = \sqrt{\max(1, s_{\text{oos}})} \cdot \sigma_{\text{eff}}(d)$（D3 同源；注意：此前对话口头表述漏 $\sqrt{\phantom{x}}$，以本册为准）。同窗同日集，分母先平均。标定数据：纯 5-min 主源（2016-04-30 起，约 609 有效日，试点站各季 124–184 样本 > 51 门槛）；禁止与逐时混标——逐时丢失整点间极值 $\implies$ 低估 $\text{Var}(M_t) \implies$ 高估 $\eta_s \implies$ 原子压低 $\implies$ 近端档低估，方向与 C1 原病灶相同，非无害保守。19 年逐时 METAR 为后续扩充研究（需重叠窗修正系数，先建纯 5-min 基线）。$t$ 网格粒度随标定脚本设计定，不预填。

### B-3 取法 C 双分支法条归属（确认记录，非新决策） ｜ 已定
有观测分支（$D+0, M_t=m$）：$G_t = \mathcal{N}(\mu_R, \sigma_{\text{rem}}^2)$，族无关——SPEC v2.0#L198-L203。无观测分支（$M_t=\emptyset, D+1/D+2$）：先验族完整 CDF，JSU/EVT 形状生效——ADR-0019#L89-L90。$\beta$（族形状继承）/ $\gamma$（经验剩余）为同接口升级，v1 不引入。

### B-4 第二件（manifest 族无关矩字段）关闭记录 ｜ 已关闭（2026-11-13）
第二件（manifest 族无关矩字段）关闭：μ₀ ≡ μ_calib 动态组装不入库；静态层仅 σ 侧（`prior_sigma = κ` 即 Z 空间宽度常数：高斯 `1.0` / JSU·EVT 解析 / fallback 分位差÷3.92，`moment_source` 四枚举，`moment_note` 仅 fallback 必填）；κ 不进在线消费链（锚定语义下由 `s_oos` 吸收，`σ_eff→σ_adj` 动态组装自洽），用途锁定诊断与检验 B/C；分位差回退降级纯防御路径（ξ 全量实测 0 发散，`max=0.2013`）；验证门五条不变（门 4 预期 fallback 格 0 个）。另记资产架构事实：族分配为站×季级继承（40 剖面）+12 个 6h 格独立拟合，检验 C 族分组单位据此定为 `站×季×早/晚段`。

---

## 第三部分：检验与验收类

### C-1 取法 C 高斯桥证伪三检验 ｜ 已定，待执行
- **检验 A（原子校准，最重要）**：609 天“$t$ 后无新极值”经验频率 vs $\Phi(-\mu_R/\sigma_{\text{rem}})$，按 $t$ 网格 $\times$ 粗分位置桶。
- **检验 B**：剩余增量经验分位 vs 高斯 QQ。
- **检验 C（判别力最强）**：2019 全年 $D+0$ 回放，$p_{\text{cond}}$ 按族分组 $\times$ 早段/晚段档位可靠性对照；JSU/EVT 格早段系统性劣于高斯格 $\implies$ 高斯化代价超限。
- **超限处置**：任一超限 $\implies G_t$ 换 $\beta/\gamma$，接口不变。

### C-2 $\le 5\text{ms}$ 性能基准（重定位） ｜ 已定
- **来源**：11-06 建议的工程验收项，经权威序处置后剥离保留。
- **定位**：回归防御基准，非设计约束——JSU 与 GPD 均有闭式 CDF，本机微秒级完成，天然满足；用途是捕捉未来引入的意外退化（GPD 尾数值积分、阻塞 IO 污染参数加载等）。不为此阈值做任何优化决策。
- **待定项**：端到端定义、p99 度量、测试输入规格、环境基线（NumPy 版本/硬件）。超标处置 = 根因分析，阈值不动。
- **归属**：D6 完成定义（无观测分支族 CDF 路径）。

### C-3 插值节点样本外表现 ｜ 留档观察
授权未拟合节点的样本外表现无实测记录；Phase 1.2 的 2019 重算顺带产出，届时核一眼即可，现在不动。

---

## 第四部分：数据与后续研究类

### D-1 NCEI 1-min 扩窗研究项 ｜ 不阻塞，条件触发
2016–2018 的 5-min 窗口限制系上游 MADIS 归档链路历史（2009–2011 实验期、2011–2015 无存档、2015-10-27 起存 5-min、2017-11 起全 1-min），非数据本身不存在。NCEI 1-min ASOS 存档（DSI-6421）可回溯至 2000 年，理论上可将 $\eta_s$ 标定窗从 2.5 年扩至 19 年。前置条件：10 站覆盖核查、as-is 数据过质检管线、MADISHF/METAR 华氏摄氏口径一致性确认。触发条件：C-1 检验 A 失败，或 $\eta_s$ 样本量成为瓶颈。

### D-2 6h 增量训练前置质检 ｜ 已定，排在主线后
- **事实更新**（业主 2026-11-13 确认）：52 GiB 6h GEFS reforecast 已补录完成并入库（未训练）；B2 回执“6h 样本量 0、必然 100% 稀疏降级”两处结论作废。
- **训练前质检清单**：站 $\times$ 季 $\times$ 年覆盖完整性、Gate V2 双向核验、时间墙合规（2019 及以后不得渗入）、与既有 12–72h 同口径空间提取算子（最近邻）。
- **定位**：6h 训练定位为 D6 规范下的增量执行，排在主线 22 格训练与 2019 盲测之后。是否纳入契约（22 $\to$ 24 格）待 2 城投注试验跑通后再决。

### D-3 短时效家族构成查询 ｜ 已完成（2026-11-13 实测回传）
66% 非高斯为全 1200 格口径；开发侧已于 2026-11-13 完成 `evidence/p8_model_pre_retrain_manifest_20260927_baseline.json` 全量查询，结论如下：
- **全量 1200 格**：非高斯占 **65.58%**（JSU 687 格 / 57.25%，EVT_Hybrid 100 格 / 8.33%，高斯 413 格 / 34.42%）；
- **D+0 消费的核心短时效（12h，共 80 格）**：非高斯占 **67.50%**（JSU 46 格 / 57.50%，EVT_Hybrid 8 格 / 10.00%，高斯 26 格 / 32.50%）；
- **TMAX 12h（共 40 格）**：非高斯占 **67.50%**（JSU 23 格 / 57.50%，EVT_Hybrid 4 格 / 10.00%，高斯 13 格 / 32.50%）；
- **试点两站（KORD / KMIA）TMAX 12h（共 8 格）**：JSU 占比高达 **87.50%**（7/8 格，仅 KORD 夏季获胜族为高斯，其余 7 格全部由 JSU 胜出）。
> **影响面结论**：短时效非高斯占比（67.5%）与全盘口径（65.6%）高度一致，且试点两站高温几乎全为 JSU。D1/B-3 将有观测分支条件化定型为取法 C（高斯桥）直接阻断了高比例 JSU 先验在盘中硬截断导致的形态畸变，收益覆盖面达 87.5% 试点盘口。

### D-4 取法 B 数据就位记录 ｜ 记录在案
19 年逐时 METAR 可用性确认（B2 回传）使取法 B（历史同时段增量经验分位）从 11-10 裁决表的“需核查”变为“可选”。激活时机由 C-1 检验结果决定；若启动，纯 5-min 主源原则照用（逐时混标偏差同 B-2 警示）。

### D-5 全量 100 个 EVT_Hybrid 格 ξ 分布明细表（16 聚类，D6 重训前置分母留档） ｜ 记录在案
数据源：`evidence/p8_model_pre_retrain_manifest_20260927_baseline.json` 与 `evidence/p4_active10_climate_calibration.json` 全量实测（N=100 个 EVT_Hybrid 模型；`xi >= 0.5` 计数 0；`xi >= 1.0` 计数 0；全局最大 `xi_r = 0.201332`，全局最大 `xi_l = 0.069080`）。

| 站 | 季 | 指标 | 格数 | 参数来源 | `xi_l` | `xi_r` |
|---|---|---|---|---|---|---|
| KATL | Spring | max | 11 | `climate_calibration` | `-0.094006` | `-0.127074` |
| KATL | Spring | min | 11 | `climate_calibration` | `-0.094006` | `-0.127074` |
| KATL | Summer | max | 1 | `manifest` | `-0.152846` | `-0.120933` |
| KDAL | Autumn | max | 11 | `climate_calibration` | `-0.089145` | `0.201332` |
| KDAL | Autumn | min | 11 | `climate_calibration` | `-0.089145` | `0.201332` |
| KLAX | Autumn | max | 11 | `climate_calibration` | `-0.227376` | `-0.281440` |
| KLAX | Autumn | min | 11 | `climate_calibration` | `-0.227376` | `-0.281440` |
| KLAX | Summer | max | 4 | `manifest` | `0.017226` ~ `0.069080` | `0.041967` ~ `0.107386` |
| KLGA | Autumn | max | 1 | `manifest` | `-0.018849` | `-0.238099` |
| KLGA | Spring | max | 1 | `manifest` | `-0.051537` | `-0.104908` |
| KLGA | Summer | max | 1 | `manifest` | `-0.048592` | `-0.050132` |
| KLGA | Winter | max | 1 | `manifest` | `-0.042075` | `-0.271419` |
| KORD | Spring | max | 1 | `manifest` | `-0.088392` | `0.149939` |
| KSEA | Autumn | max | 2 | `manifest` | `-0.100963` | `-0.128663` |
| KSFO | Spring | max | 11 | `climate_calibration` | `-0.091454` | `-0.323002` |
| KSFO | Spring | min | 11 | `climate_calibration` | `-0.091454` | `-0.323002` |

---

## 第五部分：交易半链输入记录（预测半链只出信号）

### E-1 天气异变识别器 ｜ 记录在案，交易半链开工时展开
- **业主架构定案**：统计模型不覆盖突变事件，识别 $\implies$ 停止投注/止损，Fail-Closed。
- **物理方向修正**：TMAX 的真实异常暴露为骤升类（焚风、锋后爆发性增温、下沉增温）——$M_t$ 已实现部分不可撤销，原子结构 $G_t(0^-)$ 恰处理“不再创新高”；冷锋骤跌是 TMIN 的威胁（不在授权宇宙）。
- **实现方向**：5-min 观测导数阈值检测（气候门限由 609 天数据标定），分级处置（停止新开仓 / 持仓评估 / 主动止损）；预测半链 R4 层挂观测信号输出（打标不决策），交易半链 Gate 消费。

---

## 第六部分：术语备忘（低优先级）

### F-1 “欠自信”标签
$s_{\text{oos}} > 1$（误差方差大于预报方差，分布过窄）在学术文献中常称 overconfident / underdispersive，项目文档称“欠自信”（Underconfident，意指模型对外给出的置信度不足，方差需放大）。操作方向已由 D4 定死不受影响；建议术语表统一，防跨文献误读 $\psi / \sigma_{\text{adj}}$ 分工。

---

## 第七部分：已关闭事项（审计留痕）

### G-1 超集/子集结构（业主 2026-11-13 确认）
模型库 10 城高低备货，契约开 2 城高温 22 格；先 2 城投注试验跑通完整流程再扩。

### G-2 KBKF 5-min 100% 缺失
与 ADR-0011 静态回落一致，不在试点站，无影响。

### G-3 考古结论（2026-11-13）
“非高斯先验观测后条件化”历史上从未被闭环定义（全仓检索确认，仅三处非裁决留痕）；现行方案与 SPEC/ADR 法条对齐，非新算法。

### G-4 Phase 0 三项（P0 缺陷单代码提交、gefs_extract 提交、SPEC 勘误 A-1/A-2） ｜ 已全部执行并完成原子提交（2026-11-13）
- **A-1 / A-2 SPEC 勘误**：已于 2026-11-13 完成落盘修改：
  - A-1 见 [`P8-ALGO-DEF-SPEC_v2.0.md#L206`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md#L206)，明确规范式 $\sigma_{\text{rem}}(t) = \max(\sigma_0 \cdot \sqrt{\eta_s(t)}, 0.9^\circ\text{F})$；
  - A-2 见 [`P8-ALGO-AUDIT_20261112.md#L179`](P8-ALGO-AUDIT_现状代码与目标全链路算法对照复核_20261112.md#L179)，作废“匹配分位”并更正为取法 C 双分支法条；
- **gefs_extract 单消息缺陷提交**：
  - Commit SHA: `6af817d` (`fix(pipeline): 修复 gefs_extract 单消息 step 标量导致解码迭代崩溃缺陷`)；
- **P0 缺陷单代码原子提交（D1-Max / D2 / D3）**：
  - D1-Max: Commit SHA: `f2e01d2` (`fix(modeling): 禁止 Max 气温侧在锚点边界外平钳 (P8 短时效路由缺陷单 D1-Max)`)；
  - D2: Commit SHA: `ca7dbc8` (`fix(pipeline): 消除主预测流水线静默吞异常并改为响亮失败 (P8 短时效路由缺陷单 D2)`)；
  - D3: Commit SHA: `fccae33` (`fix(modeling): 预测入口接入契约层 AUTHORIZED_LEAD_HOURS 强校验 (P8 短时效路由缺陷单 D3)`)（原混杂提交 `31e1d33` 已按业主批准拆分为纯 D3 提交，`load_model` 改动退回工作区并归入 G-5）。

### G-5 待办项：273 项在途与未追踪文件（56 M + 217 ??）的盘点分流 ｜ 待办（后续安排）
- **盘点范围**：当前工作区快照共 **273 项（`56 M + 217 ??`）**（注：随本批 `Commit A` 3 份新文档、`Commit B` 2 份基线文档与 1 份独立测试文件入库后，留待 G-5 窗口清点分流为 **267 项：`56 M + 211 ??`**）；分流三去向不变：**正式提交 / `.gitignore` 忽略 / 清理抛弃**。
- **`M` 计数对账（`57 → 56` vs 预期 `54`）**：
  - 实测 `56 M` 构成为：`docs/` 4 项 + `evidence/` 19 项 + `scripts/` 5 项 + `src/` 13 项 + `tests/` 15 项。
  - **已核实非今日测试运行再生 `evidence` 所致**：`19` 个 `M` 状态 `evidence/` 文件的 `mtime` 均停留在 `2026-10`～`2026-11-10 16:14:26`（`2026-11-13` 再生成数为 `0`）；仅減至 `56` 而非 `54` 的原因在于 `registry.py`（`fccae33`）拆分后 `load_model` PKL-first 改动留回 `M`、`gefs_extract.py`/`interpolator.py`/`main_pipeline.py` 经 `6af817d`/`f2e01d2`/`ca7dbc8` 清空（原“57”为提交前叠加口径估算）。另将 `evidence/` 下可再生成评估工件列为 `.gitignore` 候选。
- **`M` 状态 `src/` 文件（13 项）按 D6 相关性标注优先级**：
  - **D6 动工前正式审查（P0 同级）**：`src/modeling/registry.py`（`load_model` JSON-first→PKL-first）、`src/modeling/resampling.py`、`src/modeling/gaussian_emos.py`、`src/prediction/truncated_probability_engine.py`（族拟合、方差口径与分布核心，直接交互 `shape_params` 入库与先验消费）；
  - **其余在途 `src/` 文件（P1 随模块核对）**：`src/modeling/crps.py`、`src/modeling/degradation.py`、`src/modeling/emos_trainer.py`、`src/modeling/matrix_trainer.py`、`src/metrics/calibration_audit.py`、`src/prediction/constraint_enforcer.py`、`src/prediction/prediction_pipeline.py`、`src/utils/airgap.py`、`src/verification/p5_gate.py`。
- **治理文档单列（入库时优先）**：`docs/handoffs/` 下的 `P8-ALGO-DEF_搁置项总账_20261110.md`、`P8-ALGO-PENDING_待执行清单_20261106.md`、`P8-ALGO-PENDING_待改进登记_20261108.md`、`P8-MODEL_PENDING_20261110.md` 等治理文档单列分类，G-5 执行时优先入库。
- **ROADMAP 角色收窄迁移清单（2026-11-13 手术追加）**：
  1. `docs/项目编号与命名规范_20261021.md` 当前处于历史在途 `M` 状态，暂不触碰；其待写入的四条 ROADMAP 制度（定义/禁载清单/更新规则/单向引用）暂存于 [`P8-GLOBAL-MAP_项目全局图谱_v1.0_20261113.md §5.2`](P8-GLOBAL-MAP_项目全局图谱_v1.0_20261113.md)，待 G-5 窗口清点该文件在途 diff 后统一合入；
  2. `docs/ROADMAP.md` 中已标注`[待分流 · 2026-11-13]`的越权项清单，待后续窗口分别迁入目标载体：① `§1.3`/`§2.1`/`§3.1` 资产落盘与审计覆盖状态及 `§4` Backlog 状态表 → `STATUS.md`；② `§3.2` W2 执行成果、Task 08 Ticket 01~09 逐票进度 → `P8-GLOBAL-MAP` / `P8-GitHub工单对账`；③ `§3.2` L88–89 纸面盘仓位缩放规则（绿 1.0x / 黄 0.5x / 红 0.0x）与 `§5` 生产代码时代治理条款 → `Phase 2 执行文件`（预计 v2.2 升版时迁入）。
- **排期定位**：不阻塞预测半链主线，后续专门安排窗口执行。

### G-6 待办项：D1-Max 边界断言推迟固化（待与 D1-Min 边界策略整体审完后统一固化） ｜ 待办（分层裁决已批准）
- **分层执行结论**：`D2`（异常注入 → `status=FAILED` + `exceptions_count`）与 `D3`（非授权 `lead` 拒绝 + `ERROR` 日志机制）已先行固化于独立测试文件 `tests/unit/test_p0_short_lead_routing_defects.py`（含变更协议：行为若经裁决变更，测试同步更新并在登记册记录）。
- **推迟范围**：`D1-Max`（`f2e01d2`）并入 `D1-Min` 的未来裁决，待边界策略整体审完后一次性固化。

### G-7 定向考古确认结论（2026-11-13） ｜ 已核查留档
- **搜索范围**：`docs/` 全树、`evidence/`、仓库根目录、`.scratch/`、`temp/`、`reports/`、`specs/`、`git stash@{0}` 及 `git log --all`。
- **结论**：
  1. `SPEC v2.0`（`docs/audit/P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md`）与 `P8-ALGO-AUDIT_20261112.md`（`docs/audit/P8-ALGO-AUDIT_现状代码与目标全链路算法对照复核_20261112.md`）之 **A-1/A-2 勘误前文件版本确认不存在**（两者均未曾 commit，且原位覆写无 `.bak`/副本留存；`docs/audit/` 中仅存早期 `v1.2` 前驱稿 `..._20261107.md` 及记录 `2026-11-08` 两小时覆写史且注明“对象 B 仅在会话 Artifacts 面板、非文件系统对象”的 `P8-ALGO-DEF-SPEC_V2.0_两处副本差异_20261108.md`）；
  2. 过程性文档（`σ_adj` 讨论摘要、`μ₀` 拷问中间记录、`2026-11-13` 历史回执早期版本）**确认不存在**。
- **演化链文档清单（在盘未入库，留待 G-5 分流）**：`docs/audit/P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261107.md`（v1.2 祖本） / `docs/audit/P8-ALGO-DEF-SPEC_V2.0_两处副本差异_20261108.md`（两处副本差异） / `docs/audit/P8-ALGO-DEF_第三段条件分布_20261110.md`（第三段条件分布） / `docs/audit/P8-ALGO-DEF_v2.3合入答复_20261110.md`（v2.3 合入答复）。

### G-8 文档对账差异登记（2026-11-13） ｜ 已登记在案
1. **`Phase 2 执行文件 v2.1` 任务矩阵缺失 `Task 08` 条目**：[`docs/项目方案和执行文档/Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md`](../项目方案和执行文档/Phase%202%20执行文件%20v2.1：盘口定价、套利与执行引擎.md) 任务矩阵仅列 `Task 01–07`，`Task 08`（第一类投注定价与契约治理，`#133–#158`）系后续文档（`docs/ROADMAP.md`、`docs/audit/P8-GitHub工单对账_20261110.md` 等）追加所致，执行文件待后续 v2.2 升版并入对账。
2. **`docs/ROADMAP.md` L18 所记代码落盘状态与实际不符**：原行记录“核心代码 `src/execution/`、`src/bankroll/`、`src/risk/` 2026-09-22 已落盘并通过单测”，与 [`docs/audit/P8-GitHub工单对账_20261110.md`](P8-GitHub工单对账_20261110.md) 实测不符（`src/bankroll`、`src/execution`、`src/simulation` 三目录当前未建成）。已于 `2026-11-13` `ROADMAP.md` 角色收窄手术中将该行改指向 `STATUS.md`，原失真内容留痕于本条。

### G-9 `v2.9 / v2.2` 升版评审技术异议与暂缓登记（2026-11-13） ｜ **已裁决闭环（合流升版 `v2.9 / v2.2`）**
- **业主终裁与合流闭环（2026-11-13）**：G-9 全部技术异议经业主裁决采纳，[`项目方案 (v2.9)`](../项目方案和执行文档/项目方案%20(v2.9)：Polymarket%20温度市场量化投注系统.md) 与 [`Phase 2 执行文件 v2.2`](../项目方案和执行文档/Phase%202%20执行文件%20v2.2：盘口定价、套利与执行引擎.md) 已完成合流升版（原 `v2.8 / v2.1` 归档至 `docs/archive/项目方案和执行文档/`），`docs/ROADMAP.md` 迁移标记同步更新为“已迁入”。核心定案：
  1. `A1 / A2 / A3 / A4`：`v2.9 §3.4` 确立预测-结算分离架构（方案 α）“锚-形状仿射变换 $Y = \mu_0 + \sigma_{\text{adj}} Z$”表述并废弃“单高斯桥”混称（修正中心偏移为 `KORD` 春长时效 `-0.084°F` / `KMIA` 最大 `+0.0285°F`）；前提契约更名 **`α-P` 系列**（避 `P1–P4` 阶段重名）；检验 C 粒度对齐 `站×季×早晚段`；ECE 三层管辖落 `v2.9 §4 模块三` 并声明全仓现役 ECE 均计量桥前原生分布。
  2. `B1–B7`：`v2.2` 收录 `dq99 +5.8458°F` / `dq01 -3.3565°F`、`manifest.json` 实况（`880 None / 127 {} / 193 非空 dict`）、$\mu_0 = a + b\cdot\mu_{\text{ens}} + b_{30}$ 组装口径；按 `SPEC v2.0#L186, L206` 严格落地 $\sigma_0 = c\cdot\sigma_{\text{eff}}$ 方差修正前移并禁 $c$ 外乘；如实登记完整非对称分位/CDF 支持「现役未满足」；按 [`docs/MODEL_SCORECARD.md#L11-L16`](../MODEL_SCORECARD.md#L11-L16) 正式收编四维评级与纸面盘 `1.0x / 0.5x / 0.0x` 缩放规则（第五维注记方法评审中）；追加 `α` 上线后按 `站×季×早晚段` 监控偏差及检验 C `bridge-ECE` 三数（桥前原生 / 桥后 / 高斯对照）同源并产只读差值条款（严禁与 `0.0100` 比对/设门禁）。
- **`SPEC v2.0` 勘误指针（C 项，正式落盘）**：[`P8-ALGO-DEF-SPEC v2.0`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md) **保持不升版**；其中「结算桥表述（单高斯仅指有观测剩余增量分支 $G_t$，整体先验-结算为锚-形状仿射变换 $Y = \mu_0 + \sigma_{\text{adj}} Z$）与门 1/2/3（含 `KORD_72h Spring` `-0.0841°F` / `KMIA_48h Winter` `+0.0285°F` 中心偏移、$\sigma_0 = c\cdot\sigma_{\text{eff}}$ 前移及 `0.9°F` 物理底内包）」均以 [`项目方案 (v2.9)`](../项目方案和执行文档/项目方案%20(v2.9)：Polymarket%20温度市场量化投注系统.md) 与 [`Phase 2 执行文件 v2.2`](../项目方案和执行文档/Phase%202%20执行文件%20v2.2：盘口定价、套利与执行引擎.md) 为法定准源。

<details>
<summary>历史记录：G-9 升版评审原异议明细（已于 2026-11-13 经业主裁决全部采纳关闭）</summary>

1. **`bridge-ECE` 监控条款强异议（`B6` / `A3` 关联，只登记不执行）**：
   - **已核实客观事实**：全仓三条现役离线 ECE 链路均确系“未过日内高斯桥 $G_t$ 且未乘 $c = \sqrt{\max(1, s_{\text{oos}})}$”的静态先验分布：
     1. 20 折 Block-CV / P5 门禁：[`scripts/standalone_reliability_check.py#L730-L885`](../../scripts/standalone_reliability_check.py#L730-L885)、[`src/verification/p5_gate.py#L202-L246`](../../src/verification/p5_gate.py#L202-L246)、[`scripts/audit_p4_reliability_v13.py#L140-L312`](../../scripts/audit_p4_reliability_v13.py#L140-L312)；
     2. 2019 P4 结算 7 档 V1 / Active 10 OOS：[`scripts/evaluate_p4_2019_settlement.py#L297-L337`](../../scripts/evaluate_p4_2019_settlement.py#L297-L337)、[`scripts/evaluate_active10_oos.py#L244-L249`](../../scripts/evaluate_active10_oos.py#L244-L249)；
     3. V2 尺子 2°F 11 档直接 ECE：[`scripts/audit_v2/reliability_v2.py#L130-L264`](../../scripts/audit_v2/reliability_v2.py#L130-L264)。
   - **强烈技术异议（针对「由 `B5` 结算偏差代偿、不新建 `bridge-ECE`、等纸面盘暴露再立项」）**：
     1. **矩阶数不可代偿**：`B5` 结算偏差为一阶矩指标，对二阶矩错配（如 $s_{\text{oos}} > 1$ 或 $\eta_s(t)$ 标定失真）一阶不敏感。以 2019 盲测 [`evidence/p4_2019_settlement_statistics.csv`](../../evidence/p4_2019_settlement_statistics.csv) `KMIA_30h` 为例：`PIT Mean = 0.5124` 几乎无偏，但 `s_oos = 1.3638` 致 `ece_7bin = 0.01534`（超 `0.0100` 触发挂旗）且 `Cov90 = 85.99%`。二元期权分档定价 $p_k$ 直接消费二阶矩与边界原子，均值无偏无法代偿概率校准度（ECE）；
     2. **W2 纸面盘样本检定力不足**：单日每站每标仅 1 个结算日真值，按 `族 × 早晚段` 分桶后短期样本方差极大，难以检验系统性误定价，等纸面盘暴露后才立项属事后补救而非前置验证；
     3. **检验 C 本可低成本并产离线 `bridge-ECE`**：本册 `C-1` 检验 C（2019 全年 `D+0` 回放）本即按分桶统计 $p_{\text{cond}}$ 可靠性，可直接附带输出只读诊断级 `bridge-ECE`（不设新增阻塞门禁即可），替代“仅靠 `B5` 一阶偏差代偿”。
2. **本轮其余升版条款阻塞挂起汇总（均未改写 `v2.8 / v2.1 / ROADMAP / SPEC`）**：
   - `A1`：混同「先验尺度变换 $Y = \mu_0 + \sigma_{\text{adj}} Z$（$Z \sim F_{\text{family}}$）」与「有观测剩余增量单高斯桥 $G_t = \mathcal{N}(\mu_R, \sigma_{\text{rem}}^2)$」，且错将全矩阵 `EVT_Hybrid` 极值（`0.30~0.51°F`）归因于「`KORD 春长时效 |峰值| ≈ 0.5°F`」（[`evidence/p8_algo_2019_settlement_shape_distance_20261113.md#L87`](../../evidence/p8_algo_2019_settlement_shape_distance_20261113.md#L87) 实测 `KORD_72h Spring` 为 `-0.0841°F`）。
   - `A2`：依赖 `A1`“同节”；「前提契约 P1–P4」全仓无定义且与 [`P8-ALGO-AUDIT_20261112.md`](P8-ALGO-AUDIT_现状代码与目标全链路算法对照复核_20261112.md) 离线流程阶段 `P1–P4` 重名冲突；检验 C 分组粒度需对齐本册第 65 行 `站×季×早/晚段`。
   - `A3`：`v2.8` 中 ECE 规则位于 **`§4`**（`L116, L118`）而非 **`§5`**（异常治理与风控宪法），且含 `B6` 关联条款。
   - `B1`：`dq99` 峰值实测为 `+5.8458°F`（`KORD_48h` 冬），非 `+5.82°F`（`KORD_24h` 冬为 `+5.8178°F`）；`data/models/manifest.json` 实况为 `880 None / 127 {} / 193 非空`（非全部 `None`）；`b30` / $\mu_0$ 动态组装接口未在两静态文件中闭环。
   - `B2`：现役 [`DynamicCorrector`](../../src/prediction/dynamic_corrector.py) 不计算 $\sigma_{\text{dyn}}(t)$ 且 [`sigma_adj.py`](../../src/pricing/sigma_adj.py)（`F-2 LOCKED`）未接线；「$\sigma_{\text{adj}}(t) = c \cdot \sigma_{\text{dyn}}(t)$（$c$ 后乘）」违背 `SPEC#L186, L206` 方差修正前移（$\sigma_0 = c \cdot \sigma_{\text{eff}}$ 先行），且在物理仪表底 `0.9°F` 处与外乘 $c$ 严格不可交换（$c \cdot \max(\sigma_{\text{eff}}\sqrt{\eta_s}, 0.9^\circ\text{F}) \ne \max(c\sigma_{\text{eff}}\sqrt{\eta_s}, 0.9^\circ\text{F})$），同时与本册 `B-2` 分母 $\sigma_0$ 冲突。
   - `B3`：现役 `src/` 中不存在 `EVCalculator`（`ev_engine.py` 已于 `R-16` 归档），[`penetration_probe.py`](../../src/pricing/penetration_probe.py) 仅接收标量 `p_hat`，上游 `StaticPredictor` / `DiscreteBinEngine` / `BinConverter` 仅消费纯高斯 `GaussianEMOS`，未满足完整非对称分位/CDF 要求。
   - `B4`：`ROADMAP v1.1.0` 原文为 `MODEL_SCORECARD.md` 四维，而 `B4` 拟改为「`ECE 维 + 形状距离维`」却无形状距离红/黄/绿阈值定义；且 `v2.2` 暂缓发行，`ROADMAP` 迁移标记维持原状。
   - `B5`（技术内容无异议，因 `B1–B4, B6` 阻塞 `v2.2` 发行而暂随 `B7` 挂起待整批落盘）；`A4` / `B7` 随正文阻塞暂缓；`C`（`SPEC v2.0` 勘误指针）待 `v2.9 / v2.2` 正式落盘后再写入，避免产生悬空引用。

</details>

### G-10 `s_oos` 二阶矩重推升版与第五维（形状距离 Δ）定标收口（2026-11-13） ｜ **已完成落盘与测试验证**
- **任务一（`s_oos` 契约重推与 v2 升版）**：
  1. **二阶矩先验泄漏消除**：正式废弃 2019 盲测样本内估计的旧 $s_{\text{oos}}$（如 `KORD_36h = 0.833009`、`KMIA_30h = 1.363831`），确立检验 C 的独立判官合法性；
  2. **2000–2018 二十折 Block-CV OOF 重推**：以 19 年留出残差为法定基准，计算覆盖 KORD / KMIA 22 个法定网格单元；全 22 格新 $s_{\text{oos}}$ 均值由 `1.107053` 收敛至 `1.006456`（极差 `[0.979838, 1.067892]`），膨胀乘数 $c = \sqrt{\max(1.0, s_{\text{oos}})}$ 整体紧贴 `1.0000 ~ 1.0334`；
  3. **契约版本化入库**：更新 `data/contracts/physical_param_contract.json`；旧 2019 样本内值 100% 保留于各 cell 的 `s_oos_historical.v1_2019_in_sample` 并显式标注 `"样本内估计，仅诊断参考，禁止入检验 C"`；
  4. **工件落盘与单测全绿**：说明文档落盘于 [`evidence/p8_contract_s_oos_recalibration_report_20261113.md`](../../evidence/p8_contract_s_oos_recalibration_report_20261113.md)；同步更新 `test_sigma_adj.py` 与 `test_order_probe_evaluator.py` 断言，契约与定价相关单测全量 141 项测试全绿通过。
- **任务二（第五维形状距离 Δ 定标与数值留白）**：
  1. **方法定稿与翻转判罚正式废弃**：正式废弃“翻转判罚”方案（因 2019 77 组实证显示正/反翻转对称 9:9 且 52/77 组高斯基线本身 > 0.0100 陷入单边失效高本底盲区；确认 2019 单年每组仅 87~92 天不可作定标样本，样本池正式迁移至 2000–2018 二十折 Block-CV 留出池）；
  2. **反事实矩匹配分解实施**：$\Delta \equiv \text{ECE}_{\text{族}} - \text{ECE}_{\text{矩匹配高斯}}$，对照组严格采用 $\mathcal{N}(\mu_0 + \sigma_{\text{adj}}\mathbb{E}[Z], \sigma_{\text{adj}}^2 \text{Var}(Z))$，共用同一锚 $\mu_0$ 与现实命中向量 $\text{hit}$，彻底隔离一阶/二阶矩效应；
  3. **双线并报与 Bootstrap 置信区间**：完成主口径 `inw`（中间 9 档可交易窗，8 谱带）与副口径 `w20`（全 11 档，20 等宽桶）双线并报，采用按日期聚类的 Bootstrap（$B = 1000$）计算 95% 置信区间；
  4. **数值留白与索引入库**：客观实证数值表落盘于 [`evidence/p8_algo_shape_distance_calibration_20261113.md`](../../evidence/p8_algo_shape_distance_calibration_20261113.md) 与 [`evidence/p8_algo_shape_distance_calibration_20261113.csv`](../../evidence/p8_algo_shape_distance_calibration_20261113.csv)；严格执行不私自划定红/黄/绿阈值、不设判定颜色的纪律，数值待后续与 W2 仓位规则、差异化 EV 门槛同批呈交业主统一定标；
  5. **量化记分卡状态同步**：[`docs/MODEL_SCORECARD.md`](../MODEL_SCORECARD.md) 增补第五维技术注记为“方法已定稿（反事实矩匹配分解），数值待数值裁决批定标”。

### G-11 检验 A 执行（$\eta_s(t)$ 标定）及随批勘误与覆写风险警示（2026-11-13） ｜ **已完成落盘**
- **检验 A（609 天日内原子校准与 $\eta_s(t)$ 标定）**：
  1. **严格 2019 前数据边界**：脚本 [`scripts/run_p8_inspection_a_eta_calibration.py`](../../scripts/run_p8_inspection_a_eta_calibration.py) 仅读取 `2016–2018` 纯 5-min MADISHF 实况（KORD / KMIA 各 609 候选日，剔除仅含 18h 后半日、缺失日峰的跨年边界日 `2017-12-31` 后各保留 **608 有效日**，范围 `2016-04-30 ~ 2018-12-30`，QC 越界 0 / 跳变 0）、`2000_2018_training_arrays.parquet`（18h 先验）及 `v2_2000_2018_oof_cv` `s_oos`，严禁任何 2019 数据参与；
  2. **分组粒度与标定口径**：按 `station × season`（8 组，30 分钟网格 `06:00–20:00` 共 29 切片，`232` 行）标定 $\eta_s(t)$（检验 C 方按 `站 × 季 × 早晚段` 分组，`η_s(t)` 按 `v2.9 §3.4` 与 `第三段条件分布#L117` 取站×季无量纲曲线；报告第 5 节另附 `12h~72h` 跨提前量诊断）；位置桶按 $M_t - \mu_0$ 分为 `< -2°F` / `[-2, 0)°F` / `>= 0°F` 三桶（`696` 单元，`642` 非空，`85` 个 `<10` 低样本桶全量标注）；实证采用条件桥剩余残差归一化均方误差加权 PAVA 单调映射至 `[0, 1]`（同时记录字面 `1 - Var_d(M_t)/E[σ_0²]` 因混入跨日气候方差而恒负的等价性核查）；
  3. **关键结构性诊断（只实测汇报、不擅改模型）**：由于 `SPEC v2.0#L208` 固定 $\mu_R(t, m) = \rho(t)\max(0, \mu_0 - m) \ge 0$，连续原生原子预测 $\Phi(-\mu_R/\sigma_{\text{rem}})$ 在全 696 桶内数学封顶于 `0.500`，`14:00–20:00` 午后段连续原子加权平均残差达 **`+0.4774`**、1°F 结算格加权平均残差达 **`+0.2999`**（早中段 `06:00–13:30` 加权 MAE 仅 `0.0687 / 0.0712`），且 KMIA 因 $\sigma_{0,\text{rms}} \approx 1.65\text{--}1.93^\circ\text{F}$ 于 `13:30~14:30` 即触及 `0.9°F` 物理底（$\eta_{\text{floor}} \approx 0.22\text{--}0.30$）；
  4. **工件与 SPEC 勘误指针**：落盘 [`evidence/p8_inspection_a_eta_s_calibration_20261113.csv`](../../evidence/p8_inspection_a_eta_s_calibration_20261113.csv)、[`.json`](../../evidence/p8_inspection_a_eta_s_calibration_20261113.json)、[`evidence/p8_inspection_a_atomic_residuals_20261113.csv`](../../evidence/p8_inspection_a_atomic_residuals_20261113.csv) 与 [`evidence/p8_inspection_a_eta_calibration_report_20261113.md`](../../evidence/p8_inspection_a_eta_calibration_report_20261113.md)；同步在 [`SPEC v2.0#L205`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md#L205) 以勘误登记方式（不升版）将 $\eta(t)$ 状态更新为“检验 A 已标定”。
- **随批附带勘误与风险警示（无新计算）**：
  1. **`src/contract/param_table_converter.py` 再生覆盖风险警示**：现役 [`src/contract/param_table_converter.py`](../../src/contract/param_table_converter.py) 的默认/主数据源仍指向 2019 盲测统计表；**未来重跑 `param_table_converter.py` 前必须先将 `s_oos` 数据源切换至 2000–2018 20 折 Block-CV OOF 产物**，否则将覆写 `data/contracts/physical_param_contract.json` 中 `v2_2000_2018_oof_cv` 版本的 `s_oos`，重新引入 2019 二阶矩泄漏；
  2. **`s_oos` 重推报告公式笔误勘误**：[`evidence/p8_contract_s_oos_recalibration_report_20261113.md#L40`](../../evidence/p8_contract_s_oos_recalibration_report_20261113.md#L40) 原文公式注记写作“其中 $\sigma_i = \max(0.90, \sigma_{\text{raw}, i} \cdot c_{\text{train}})$”，系文档笔误——实际计算脚本 [`scripts/compute_p8_oos_and_shape_calibration.py`](../../scripts/compute_p8_oos_and_shape_calibration.py) 直接读取 Block-CV 折外 parquet 中的 `sigma` 列，未额外施加 `0.90` 后置截断；**契约与报告中的全 22 格数值产物不受影响**（已核查留档，不改原数字）。

### G-12 业主审查记录落盘、方案一 `μ_R` 标定/接口重构、SPEC 勘误与重测阻塞升级登记（2026-11-14） ｜ **部分闭环 / 检验 C 判决跑批继续冻结**
- **业主侧审查与裁决记录落盘（双向引用）**：已于 [`P8-OWNER-REVIEW_裁决与审查记录.md`](P8-OWNER-REVIEW_裁决与审查记录.md) 原样录入《业主审查记录 v1》（§一~§七），明确“本文件为业主侧审查记录，构成审计链组成部分，agent 仅代为落盘，内容责任在业主”；本登记册继续独占事项状态、阻塞与闭环追踪职责。
- **方案一 $\mu_R(t,m,X_t)$ 608 天标定（[`scripts/calibrate_p8_mu_r_cooling_drift.py`](../../scripts/calibrate_p8_mu_r_cooling_drift.py)，零 2019 参与）**：
  - 产出于 [`evidence/p8_mu_r_cooling_drift_calibration_20261114.json`](../../evidence/p8_mu_r_cooling_drift_calibration_20261114.json)、[`evidence/p8_mu_r_cooling_drift_curves_20261114.csv`](../../evidence/p8_mu_r_cooling_drift_curves_20261114.csv)、[`evidence/p8_mu_r_cooling_drift_residuals_20261114.csv`](../../evidence/p8_mu_r_cooling_drift_residuals_20261114.csv) 与 [`evidence/p8_mu_r_cooling_drift_report_20261114.md`](../../evidence/p8_mu_r_cooling_drift_report_20261114.md)。
  - **KMIA 午后（15:00–20:00）可达性**：`min_mu_r = -23.6809°F`，分位数 `[-8.8902, -6.2878, -4.2175, -2.3840, -1.5097]`°F，`Phi(-mu_R/0.9) >= 0.95` 占比 `0.9030`（`reachable = True`）。
  - **机械验收三判据**：① 早段 `B1/B2` 不劣化 **通过**（`pooled wMAE: 0.051684 -> 0.048242`，`out95`: `B1 43->26`, `B2 26->26`）；③ 早段冷却 `B3` 显著收敛 **通过**（全量 `B3 wResid: +0.192482 -> +0.002143`，冷却子集 `+0.325476 -> +0.039360`）；② 午后 `14:00–20:00` 全落 Wilson 95% CI **不通过**（`28/312` 出界 vs 阈值 `0/312`，其中 `KMIA 2/156`、`KORD 26/156`；固定 `ρ(t)=(20-t)/14` 下无约束理论极限仍余 `14/312` 互斥出界）。**检验 C 判决跑批冻结令依法持续。**
- **三实况接口重构与 SPEC 勘误**：
  - 接口层完成 [`StationDayState`](../../src/prediction/monotonic_confluence.py) `current_temp_f` 帧级瞬时气温保留、[`DynamicCorrector`](../../src/prediction/dynamic_corrector.py) `(extreme_m, instant_x_t, t_local)` 三实况重构及可插拔 `MuRHook`（默认挂载 `Proposal1CoolingDriftMuRHook`，修复 `correct_with_station_state` 极值/瞬时混叠）、以及 [`PredictionPipeline`](../../src/prediction/prediction_pipeline.py) 调用链同步（`F-2 LOCKED` 相关文件未触碰）。
  - [`SPEC v2.0#L201–L209`](P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md#L201-L209) 完成不升版勘误，落盘方案一公式、定理级缺陷与挑战回合四族否定结论、业主批准日 `2026-11-14` 及 $T_{\min}$ 镜像对偶警示。
- **随批治理与重测阻塞登记（依据 [`P8-OWNER-REVIEW §六`](P8-OWNER-REVIEW_裁决与审查记录.md)）**：
  1. **3 项集成测试失败列为已知重测阻塞项（`BLOCKER_FOR_RETEST`）**：`tests/unit/contract/test_contract_security_integration.py` 中 `test_tc_sec_01_version_tamper_blocks_transaction`、`test_tc_sec_02_missing_model_blocks_transaction`、`test_tc_sec_06_anti_pollution_runtime_hash_zero_drift` 因契约锚 `manifest_sha256`（`fc2212a5...`）与磁盘 1200 模型实算 canonical SHA256（`25226190...`）不一致而 FAIL。**属 ADR-0019 Fail-Closed 预期保护设计；法定处置 = 待检验 C 全量通过后，经 `scripts/trigger_model_retest.py` 走完整重测协议重签发，严禁豁免、严禁修改测试断言、严禁手动篡改哈希。**
  2. **`G-11` `param_table_converter.py` 警示升级为重测签发前硬性前置（`HARD_PRECONDITION_BEFORE_RETEST`）**：已核 `scripts/trigger_model_retest.py#L77-78, L230-233` 默认向 `convert_csv_to_contract()` 传入 2019 盲测文件 `evidence/audit_v2/p4blind_v2r01_metrics.csv`，而 `src/contract/param_table_converter.py#L241` 直接按 `m_row["s_oos"]` 导出。**必须先将 converter / retest 的 `s_oos` 输入源切换至 2000–2018 20 折 Block-CV OOF 产物（`v2_2000_2018_oof_cv`），再触碰 converter 或执行 `trigger_model_retest.py` 重签发。**
  3. **数值裁决批补料（W2 仓位缩放与差异化 EV 门槛现役输入）**：已只读捞取全量现役来源与当前值，随本批工单回传呈裁。
