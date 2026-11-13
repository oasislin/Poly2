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
