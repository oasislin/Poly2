# P8-ALGO-PENDING · 待执行清单（冻结）

> ⚠️ **历史快照（只读留档 · 2026-11-21 标定）**：本文档反映 **[2026-11-06 基线 `HEAD=75db953` 时勘定之代码/定义不一致待执行快照]** 之历史事实与一次性登记底稿，依据《项目编号与命名规范 v1.1 §8.1 / §10.2》冻结留档——**严禁回改 `§0–§4` 原有正文、严禁删除或移动路径**。当前实时权威承接请跳转：[`P8-PROJECT-TASKS_全量任务分解台账_v1.0.md §2.2 S2-06`](../audit/P8-PROJECT-TASKS_全量任务分解台账_v1.0.md#22-切片-2基线录盘制度合龙待成文协议-p10-与管控收口) 与 [`P8-ALGO-REVIEW_待确认事项登记册_20261113.md`](../audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md)；全量 8 条并账去向映射见文末 **`§5（§10 增补）`**。

> **本清单内所有项当前均不得执行。**
> 当前主线为「算法定义、代码、数据三方一致，其中算法定义文件（`P8-ALGO-DEF_v0`）是唯一真源」。本清单只做登记，**不含任何执行授权**；任何一项在未取得新的明确指令前，禁止改动 `src/`、`tests/`、`data/`、`scripts/`。
> 编制日期：2026-11-06；编制时仓库基线 `HEAD = 75db953337632cc900816f115293ad7e1a58a2dc`（与 `origin/main` 同点）。

---

## 0. 清单总则

1. 本清单记录的是**已勘定的代码与算法定义不一致项**，不是待讨论项；是否修、何时修，均需用户单独指令。
2. 执行任一项前必须同时满足：① 用户给出明确的代码修改指令；② 该项在 `P8-ALGO-DEF_v0` 中已有对应定义（定义先行，代码后行）。缺一不可开工。
3. 任何一项执行完毕，验收判据必须是**布尔可判定**（原值 vs 阈值），并按《AGENTS.md》要求附命令与原始输出片段。

---

## 1. P-1a（高优先 · 冻结）删除气候方差加法项 + 生产补 `c_train`

| 项 | 内容 |
| :-- | :-- |
| **位置** | ① `src/modeling/gaussian_emos.py` L56（docstring 方程）、L62（`clim_var` 取值）、L65（`variance = self.c**2 + self.d**2 * ens_var + clim_var`）、L68-69；② `src/modeling/registry.py` L462-489（`predict()` 形参 `sigma_clim_squared` L470，直通 L479 / L487）；③ `src/prediction/static_predictor.py` L161（形参）、L173（`_resolve_variance_floor`）、L174-176（传参链）。 |
| **依据** | `docs/adr/ADR-0015：废除高斯EMOS气候方差加法项、确立物理方差底座与离散校准门禁.md`（状态 `APPROVED`，2026-10-19）：§2.1 L19 点名 `src/modeling/gaussian_emos.py` 为被废止代码并给出 blob hash；L23/L25 逐字引用该行；L26-27 裁定「正式彻底废除 `clim_var` 加法项」，恢复 `σ_f² = c² + d²·S_ens²`。 |
| **现状事实** | 生产推理路径仍加 `clim_var`；`c_train` 只在训练期产生（`src/modeling/resampling.py` L552-565，按季节 `sqrt(Var(resid_calib)/E[sig_raw²])`，裁剪 `[0.8, 1.4]`），**生产推理路径不消费 `c_train`**（`grep -n "c_train" src/` 命中 8 行，全部在 `resampling.py`：L434/440/461/470/552/560/562/565）。 |
| **正确做法（定义口径）** | `σ_eff = c_train · √(c² + d²·S_ens²)`，**无气候加法项**。`c_train` 按季节从 `data/models/manifest.json` 取（文件内 1200 条 `c_train` 记录）。 |
| **数据事实** | `data/models/manifest.json`：`manifest_version=2.2.0-phase`，`status=PRODUCTION_RETRAINED_V2`，`generated_at=2026-09-27T14:28:37Z`；`c_train` 统计 `n=1200 / min=0.9409 / max=1.3095 / median=1.0759`；文件 `sha256 = 8bb364e26b8228a50372cfbcd7b0f7a5378b083b99bcb648c727d5e8c4de98eb`。 |
| **验收判据（布尔）** | 改后线上推理在 22 格上 90% 覆盖率均值 `Cov̄ ∈ [0.877, 0.897]`（目标 `88.7% ± 1%`）。判定式：`pass = (0.877 <= Cov̄ <= 0.897)`。改前同口径重算记录值为 `98.60%`（见下「基线记录」），改后须与改前同脚本、同 22 格、同区间口径。 |
| **基线记录** | 口径 A（`c_train·√(...)`，无 clim）实测覆盖率均值 `0.887358`（即 88.74%，高斯代理口径 `90.04%`，标准差均值 `4.33°F`）；口径 B（生产现行含 clim）重算覆盖率均值 `98.60%`（标准差均值 `10~15°F`，其中 5 格达 100%）。两值来源：`docs/audit/P8-ALGO-AUDIT-CHK-01_算法链路与S_conf独立性复核_20261106.md` §2 L79 / §3 L95-100（开发侧复核实测），本清单只做原样引用。 |
| **状态** | **未授权执行，仅登记。** |
| **解除条件** | ① 用户明确下达「开始修改」类指令；② `P8-ALGO-DEF_v0` 已定稿，且其「分布层」章节已写明 `c_train` 的统计学身份与 `σ_eff` 的最终式；③ 明确批准对象为「删除 clim 加法项 + 生产接线 `c_train`」这一组改动（两项不可拆分批准）。 |

---

## 2. P-1b（挂起 · 冻结）补 `b30` 因果偏差项

| 项 | 内容 |
| :-- | :-- |
| **位置** | `src/modeling/resampling.py` L548（`train_work["b30"] = resid_raw.shift(1).rolling(30, min_periods=10).mean().fillna(0.0)`）、L549（`mu_calib = mu_raw + b30`）。生产推理路径无对应项（`grep -n "b30" src/` 仅命中 L548、L549 两行）。 |
| **现状事实** | 训练期 `b30` 已进入 `mu_calib`，并进一步影响 `resid_calib` → `c_train`（L550、L557）。生产推理只输出 `μ = a + b·ens_mean`，**未加 `b30`**。即训练与推理的均值口径不一致。 |
| **正确做法（待前置确认后定）** | 若在线可复现：`μ_prod = a + b·ens_mean + b30_live`，其中 `b30_live` 为「过去 30 天逐日真值减对应预测」的滚动均值（`min_periods=10`，不足 10 天取 0，与训练期一致）。若不可复现：**不得改代码**，只登记为已知偏差并写入 `P8-ALGO-DEF_v0` 的「已声明偏差」条目。 |
| **前置条件（硬）** | 必须先确认线上能否取得「过去 30 天逐日真值 + 对应预测」。**不得先改代码再找数据**；不可用假设值、不可用回填补数冒充在线可得。 |
| **验收判据（布尔）** | 若执行：22 格上 `μ` 的残差均值（bias）绝对值从现有水平降至 `≤ 0.1°F`（`pass = abs(bias) <= 0.1`），且 90% 覆盖率仍满足 P-1a 的 `[0.877, 0.897]`。若不执行：`P8-ALGO-DEF_v0` 中必须出现一条「已知偏差：训练含 `b30`、推理不含」的可定位记录。 |
| **状态** | **未授权执行，仅登记。** |
| **解除条件** | ① 用户明确下达执行指令；② 前置条件「线上 30 天真值与预测可得」已完成核验并留证（数据文件/接口/命令与输出）；③ `P8-ALGO-DEF_v0` 分布层已写明 `b30` 的偏差修正身份。 |

---

## 3. 算法侧冻结项（D3~D8）

以下各项在 `P8-ALGO-DEF_v0` 定稿前**一律不得改动**（含文档、代码、契约字段）：

| 编号 | 冻结对象 | 当前位置 | 冻结理由（一句话） |
| :-- | :-- | :-- | :-- |
| D3 | `σ*`（`σ*_ece / σ*_cov / σ*_pit`）的取值与口径 | `ADR-0019` §3 L40-42；契约无对应字段；`src/contract/parameter_domains.py` L36-38 / L341-354 为 `None` | 三式是"零假设标准误"还是"经验容差"，直接决定 `z` 的量纲与零基线，必须先由定义定死 |
| D4 | 特征集合（`S_conf` 用 `x_ece/x_cov/x_pit` 中的哪几个） | `ADR-0019` §3 L40；方案书 L195 仍含 `w_s` | 特征集合与正交性判据互相约束，A1 硬伤未消解前不得增删 |
| D5 | 权重 `w` 的归属与取值 | `ADR-0019` §3 L42（仅 `Σw=1`）；`#156` 只承诺 `θ/η/ψ`；Tier 2 无 `w` 字段 | 无字段即无法定值；擅自填值等于凭空立法 |
| D6 | 衰减核（`exp(−Σz²)` vs 死区 `exp(−κΣmax(0,z²−1))` 等）与 `κ` | `ADR-0019` §3 L41 | 核函数决定零基线（`e^{−3}=0.0498` vs 死区系），改核等于改算法语义 |
| D7 | `σ_adj` 的指数与下界 | `ADR-0019` §4 L50（固定 0.5）；方案书 L198（`α∈[0.4,0.5]` 待标定）；`src/pricing/sigma_adj.py` L50-57 / L108-109（`policy.exponent` 可注入） | 三处口径冲突（A2），必须由定义裁一次 |
| D8 | `fractional_multiplier` 的归并位置与取值 | 方案书 §2.4（并入 `C_max`）；`src/` 无对应实现（`grep fractional_multiplier src/` 无命中） | 与 `τ_conf` 叠加会造成常数级重复压缩，归并点必须先定 |

**D3~D8 的统一解除条件**：`P8-ALGO-DEF_v0` 定稿（用户确认）→ 由该文件指定每个量的身份（解析式 / 数据标定 / 设计常数）与唯一取值来源 → 才允许生成对应 Ticket。

---

## 4. 登记纪律

1. 本清单不产生 GitHub Issue、不产生 Ticket；如需执行，另行按 A 线规范开 Ticket。
2. 本清单的「现状事实」均为只读取证，行号以 `HEAD = 75db953` 为准；若 `HEAD` 变更，执行前须重新取行号。
3. 本清单**不含** `S_conf`、`σ*`、`w` 的设计判断；这些属于 `P8-ALGO-DEF_v0` 的产出范围，不在本清单内预设结论。

---

## 5. 全量 8 条并账去向显式映射表（`2026-11-21` 依《规范 §10.1》核查增补）

> 按《项目编号与命名规范 v1.1 §10.1》核查当前仓内事实与现役承载去向（原有 `§0–§4` 正文与数字零改动）。

| 原编号 | 原对象 | 现行源码 / 架构核查事实 | 现役正式承载去向 / 处置归口 |
| :--- | :--- | :--- | :--- |
| **`P-1a`** | 删 `clim_var` + 生产补 `c_train` | `HEAD` [`gaussian_emos.py#L68`](../../src/modeling/gaussian_emos.py#L68) 仍含 `+ clim_var`（修复处于 `G-5` 工作区 `M`）；旧 `ModelRegistry` 未接 `c_train`；新 `T8 M2` [`PriorParameters`](../../src/prediction/forecast_distribution_engine.py) 改从外部收 `(mu0, sigma0)` | 代码合入归 **`S2-06`（`P8-ALGO-REVIEW G-5#L191` P0 审查）**；先验组装口径见 [`P8-ALGO-REVIEW B-1 / B-4`](../audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md#L56) |
| **`P-1b`** | 补 `b30` 因果偏差项 | `src/prediction/` 全包未消费 `b30`（仅 [`resampling.py#L548-L549`](../../src/modeling/resampling.py#L548-L549) 存在）；`Phase 2 v2.2#L251` 与 `B-1` 明确 `μ₀` 由消费端动态组装 | 代码归口同上归 **`S2-06`（`G-5` 清点）**；规格口径归 [`P8-ALGO-REVIEW B-1`](../audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md#L56) |
| **`D3`** | `σ*_ece / cov / pit` 口径与取值 | [`parameter_domains.py#L341-L354`](../../src/contract/parameter_domains.py#L341-L354) 仍处 `F-2 LOCKED`；`v3.0` 后 `α` 已转用 `P16 λ(L)` + `ECE` 临界锚，未实现 `σ*` | **`v3.0` 架构已被 `D-6` 制度取代**；历史 `F-2` / 域表清理评估归 **`S2-06`** |
| **`D4`** | `S_conf` 特征集合 | [`P7-ALGO-2_裁决记录#L112-L120`](../audit/P7-ALGO-2_裁决记录.md#L112-L120) 曾定 `ADR-0019 §3`，现已被 post-α `P16 λ(L)` 与决策级四元组抽检替代 | **`v3.0` 架构已被 [`P8-D6-POLICY-CLOSURE`](../audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) 取代**；遗留注释保留 `F-2` 不动，处置归 **`S2-06`** |
| **`D5`** | `S_conf` 权重 `w` | Ticket 23（`#156`）未实施，`v3.0` 已切换 `P16` 离散灯级 | 同上：已由 [`P8-D6-POLICY-CLOSURE §一.3`](../audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#L39-L45) 取代，历史遗留归 **`S2-06`** |
| **`D6`** | 衰减核与 `κ`（`S_conf` 旧项） | 同上：未在 `src/bankroll/` 实现，已由 `v3.0 / P16 λ(L)` 取代（**非 `P8-D6-POLICY-CLOSURE`**） | 同上：已由 [`P8-D6-POLICY-CLOSURE`](../audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) 取代，历史遗留归 **`S2-06`** |
| **`D7`** | `σ_adj` 指数与下界 | **已正式定稿闭环**：`2026-11-13` `B-1` 数学强制签收 $c \equiv \sqrt{\max(1, s_{\text{oos}})}$，指数 `0.5` 唯一确定 | [`P8-ALGO-REVIEW 第〇部分#L12, L32`](../audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md#L12)（`已定稿闭环`）；`sigma_adj.py` 维持 `F-2 LOCKED` |
| **`D8`** | `fractional_multiplier` 归并 | 已由 post-α `v3.0` 门限额制 `G = B·w(τ)·[s(edge)·λ(L)]` 与 `S3-04/S3-06` 替代 | [`P8-CAPITAL-CONFIG v1.0`](../audit/P8-CAPITAL-CONFIG_资金参数配置_v1.0.md) ＋ [`P8-D6-POLICY-CLOSURE §六`](../audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#L97-L110) ＋ [`S3-04 / S3-06`](../audit/P8-PROJECT-TASKS_全量任务分解台账_v1.0.md#L64-L66) |
