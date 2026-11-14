# P8-INSPECTION-C 司法级完整档案（方案 α 检验 C 全过程决策时间线与全部证据索引）

- **档案建立日期**：`2026-11-14`
- **适用范围**：本文件为方案 $\alpha$ 检验 C（2019 独立盲测年全年回放）之**司法级完整档案与唯一总索引**；后续任何治理审计、`G-14`/`G-15` 立法跟踪及 `β / γ` 备选架构立项与继承资产引用，一律以本文件及所挂接之原始工件为唯一事实依据。
- **终裁结论摘要**：**`TIER_C` / `C 档（终止可签）`**（$G1 \land G2 \land \neg G3 \land \neg \text{集中性}$；$G1 = \text{True}$ $[16/16\text{ 层 CRPS }-48.33\%]$，$G2 = \text{True}$ $[232\text{ 切片 } \max|\Delta E| \le 1.36^\circ\text{F} \le 2.0^\circ\text{F}]$，$G3 = \text{False}$ $[G3a\ 36/312 > 25,\ G3b\ 38/228 > 20,\ G3c\ 0.030586 > 0.020]$，集中性条件 = `False`）。

---

## 一、 检验 C 全过程决策时间线（附录一原文逐字归档）

- **首跑（2026-11-14 前）**：检验 C 2019 盲测首跑，`ECE_bridge` 显著超限，无法签发；设计组裁定“没有第三条路”挑战成立；
- **诊断轮**：`CRPS` 对照保住价值主张（全池 `−36.2%`，`14/16` 层）；发现双缺陷——① `KMIA Summer 06:00 ρ=+2.37` 均值幻觉（`+12.84°F`）；② 真值源混源（GHCN vs MADISHF，`20–24%` 天跨零档）；规则二“字面未中、精神命中”如实留档；规则三触发（体制漂移）；
- **真值源根因审计**：双机制确证——DST/LST 日界错位（解释 `−12.6°F` 全部极端异常）+ MADISHF 整度量化伪影（`±0.72°F`）；站点同一性核验；设计组裁决分支 A 主判（GHCN LST，归因洁净性）+ METAR 平行观察 + `G-15` 结算适配器挂账；W2 D1 裁定 `inw` 口径（历史执行实证，`MODEL_SCORECARD` 表头勘误，第三例文字-执行背离）；程序自认：G 门正文未随指令下发，被 agent“不自造阈值”纪律拦截；
- **修复 + 终跑**：LST 语料重建（`η_s` 敏感性 `max 0.0084`，冻结不动）；`ρ` 修复（`ρ(6:00)=1.006`，`608` 天 `232` 切片 `G2a` 全过 `max 1.15°F`）；终跑判定 $G1 \land G2 \land \neg G3 \land \neg \text{集中性} \to \text{TIER\_C}$（`G3a 36/312 z=5.3`、`G3b 38/228 z=8.1`、`G3c 0.0306` 十六层均匀失败 `0.026~0.037`）；
- **设计组质询与勘误**：① 更正“与市场盘口比对下注”系前瞻性误述（当前无任何盘口数据）；② “直击”降级为“机制对症+效果待验”，断言用语标准确立；③ 2019 封跑制度设立；④ 误差预算质询（设计组）：阈值 `0.020` 是否小于数据噪声——审查方摊开预算：先验同宇宙 `ECE 0.0036`（单年抽样噪声 `≤0.005` 量级）、METAR 换流 `ΔECE 0.0007`、真值错位方向不利、桥失准为主项（`~0.025+`），信噪比 `4~6` 倍，判决翻转需门禁放宽至 `0.031+` 且无噪声项可支持；设计组认可，C 档维持；程序教训（门禁立项须附预算）立为制度；多年度盲测写入 `β/γ` 协议占位；
- **终裁（2026-11-14）**：设计组签发 C 档，α 当前形态终止，[`v2.9#L127`](../项目方案和执行文档/项目方案%20(v2.9)：Polymarket%20温度市场量化投注系统.md#L125-L127) 备选架构条款触发。

---

## 二、 全部证据工件路径总索引（按阶段与提交线溯源）

### Stage 0｜前置冻结资产（检验 A / `s_oos v2` / `ρ_s,se(t)` 前两轮）
1. **契约与 `η_s(t)` 冻结基线**：
   - 契约 `v2`（`2000–2018` OOF CV `s_oos`）：[`evidence/p8_contract_s_oos_recalibration_report_20261113.md`](../../evidence/p8_contract_s_oos_recalibration_report_20261113.md)、[`evidence/p8_algo_shape_distance_calibration_20261113.csv`](../../evidence/p8_algo_shape_distance_calibration_20261113.csv)
   - 检验 A 609 天 `η_s(t)` 冻结表（DST 原子校准，未变）：[`scripts/run_p8_inspection_a_eta_calibration.py`](../../scripts/run_p8_inspection_a_eta_calibration.py)、[`evidence/p8_inspection_a_eta_s_calibration_20261113.csv`](../../evidence/p8_inspection_a_eta_s_calibration_20261113.csv)、[`evidence/p8_inspection_a_eta_s_calibration_20261113.json`](../../evidence/p8_inspection_a_eta_s_calibration_20261113.json)、[`evidence/p8_inspection_a_atomic_residuals_20261113.csv`](../../evidence/p8_inspection_a_atomic_residuals_20261113.csv)、[`evidence/p8_inspection_a_eta_calibration_report_20261113.md`](../../evidence/p8_inspection_a_eta_calibration_report_20261113.md)
2. **`μ_R` Round-1（提交 `924ba0d`）与 Round-2（提交 `611a06e`）前置标定**：
   - Round-1 固定斜坡 `(κ, δ)`：[`scripts/calibrate_p8_mu_r_cooling_drift.py`](../../scripts/calibrate_p8_mu_r_cooling_drift.py)、[`evidence/p8_mu_r_cooling_drift_calibration_20261114.json`](../../evidence/p8_mu_r_cooling_drift_calibration_20261114.json)、[`evidence/p8_mu_r_cooling_drift_report_20261114.md`](../../evidence/p8_mu_r_cooling_drift_report_20261114.md)
   - Round-2 释放 `ρ_s,se(t)`（纯 BCE，`06:00` 不可识别缺陷源）：[`scripts/calibrate_p8_mu_r_rho_released.py`](../../scripts/calibrate_p8_mu_r_rho_released.py)、[`evidence/p8_mu_r_rho_released_calibration_20261114.json`](../../evidence/p8_mu_r_rho_released_calibration_20261114.json)、[`evidence/p8_mu_r_rho_released_report_20261114.md`](../../evidence/p8_mu_r_rho_released_report_20261114.md)

### Stage 1｜检验 C 首跑回放（`run/replay`，提交 `4fe4698`）
- 入口脚本：[`scripts/run_p8_inspection_c_2019_replay.py`](../../scripts/run_p8_inspection_c_2019_replay.py)
- 首跑 5 件原始证据：
  1. [`evidence/p8_inspection_c_2019_replay_20261114.json`](../../evidence/p8_inspection_c_2019_replay_20261114.json)
  2. [`evidence/p8_inspection_c_2019_replay_report_20261114.md`](../../evidence/p8_inspection_c_2019_replay_report_20261114.md)
  3. [`evidence/p8_inspection_c_2019_16strata_20261114.csv`](../../evidence/p8_inspection_c_2019_16strata_20261114.csv)
  4. [`evidence/p8_inspection_c_2019_22cells_20261114.csv`](../../evidence/p8_inspection_c_2019_22cells_20261114.csv)
  5. [`evidence/p8_inspection_c_2019_atom_696_20261114.csv`](../../evidence/p8_inspection_c_2019_atom_696_20261114.csv)

### Stage 2｜诊断轮 7 件（CRPS + 结构拆解 + 预注册规则 1/2/3，提交 `d41c526`）
1. 只读诊断脚本：[`scripts/diagnose_p8_inspection_c_2019.py`](../../scripts/diagnose_p8_inspection_c_2019.py)
2. 诊断总 JSON（含 CRPS 核验误差、`608d/2019` 早窗均值差 `+11.81/+12.84°F`、分箱敏感性、W2 全表）：[`evidence/p8_inspection_c_diagnostics_20261114.json`](../../evidence/p8_inspection_c_diagnostics_20261114.json)
3. 诊断报告：[`evidence/p8_inspection_c_diagnostics_report_20261114.md`](../../evidence/p8_inspection_c_diagnostics_report_20261114.md)
4. 16 层连续 CRPS/RPS 对照表：[`evidence/p8_inspection_c_crps_16strata_20261114.csv`](../../evidence/p8_inspection_c_crps_16strata_20261114.csv)
5. 29 半小时切片剖面表：[`evidence/p8_inspection_c_timeslice_29_20261114.csv`](../../evidence/p8_inspection_c_timeslice_29_20261114.csv)
6. W2 22 格四维评分卡（`inw` + `w20`）：[`evidence/p8_inspection_c_w2_scorecard_22cells_20261114.csv`](../../evidence/p8_inspection_c_w2_scorecard_22cells_20261114.csv)
7. 审查记录 v3 追加归档：[`docs/audit/P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md`](P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md)

### Stage 3｜真值源根因审计、术语切换与预注册 G 门缺口治理（提交 `3ac0cbd` + 本轮工件）
- **真值源审计实证与裁决留痕**（基于对 `data/processed/truth_ghcn_daily/{KORD,KMIA}.parquet` 与 `data/raw/iem/{KORD,KMIA}/2019.parquet` 只读根因审计，`2019-10-02` `−12.6°F` 及跨零档归因）：
  - [`docs/audit/P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md`](P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md)（§七 v4 授权、§八 v5 真值源分岔裁决与《检验 C 终裁预注册判决标准 v1》附录原文）
  - [`docs/audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md`](P8-ALGO-REVIEW_待确认事项登记册_20261113.md)（`G-14` 宪法缺口与真值审计结论登记、`G-15` 结算适配器偏差指标 `+0.54/+0.83°F` 量化入账）
  - 2019/608d METAR(DST) 与 GHCN(LST) 逐日偏差定量工件：内含于终跑 JSON [`evidence/p8_inspection_c_2019_final_lst_20261114.json`](../../evidence/p8_inspection_c_2019_final_lst_20261114.json)（`non_gating_parallel_1_metar_dst_settlement_g15` 节）

### Stage 4｜单次修复（LST 语料重建 + `ρ` 可识别性修复与正则，零 2019）
- **LST 语料重建与 `η_s` 敏感性**：
  - 脚本：[`scripts/rebuild_p8_lst_corpus_and_check_eta.py`](../../scripts/rebuild_p8_lst_corpus_and_check_eta.py)
  - 语料与敏感性工件：[`evidence/p8_608d_5min_lst.parquet`](../../evidence/p8_608d_5min_lst.parquet)、[`evidence/p8_608d_snapshots_lst.parquet`](../../evidence/p8_608d_snapshots_lst.parquet)、[`evidence/p8_2019_5min_lst.parquet`](../../evidence/p8_2019_5min_lst.parquet)、[`evidence/p8_eta_s_calibration_lst.csv`](../../evidence/p8_eta_s_calibration_lst.csv)、[`evidence/p8_eta_s_calibration_lst.json`](../../evidence/p8_eta_s_calibration_lst.json)
- **`ρ` 可识别性修复与 `κ/δ` 正则重标定（`①/②′/③` + `G2a_608`）**：
  - 脚本：[`scripts/calibrate_p8_mu_r_lst_identifiable.py`](../../scripts/calibrate_p8_mu_r_lst_identifiable.py)
  - 工件：[`evidence/p8_mu_r_lst_identifiable_calibration_20261114.json`](../../evidence/p8_mu_r_lst_identifiable_calibration_20261114.json)、[`evidence/p8_mu_r_lst_identifiable_curves_20261114.csv`](../../evidence/p8_mu_r_lst_identifiable_curves_20261114.csv)、[`evidence/p8_mu_r_lst_identifiable_residuals_312_20261114.csv`](../../evidence/p8_mu_r_lst_identifiable_residuals_312_20261114.csv)、[`evidence/p8_mu_r_lst_identifiable_residuals_full_20261114.csv`](../../evidence/p8_mu_r_lst_identifiable_residuals_full_20261114.csv)、[`evidence/p8_mu_r_lst_identifiable_slices_232_20261114.csv`](../../evidence/p8_mu_r_lst_identifiable_slices_232_20261114.csv)、[`evidence/p8_mu_r_lst_identifiable_out95_dist_20261114.svg`](../../evidence/p8_mu_r_lst_identifiable_out95_dist_20261114.svg)、[`evidence/p8_mu_r_lst_identifiable_report_20261114.md`](../../evidence/p8_mu_r_lst_identifiable_report_20261114.md)

### Stage 5｜检验 C 2019 终跑与 G 门代码布尔判决（终跑全套 + 勘误登记）
- **终跑评估脚本**：[`scripts/run_p8_inspection_c_2019_final_lst.py`](../../scripts/run_p8_inspection_c_2019_final_lst.py)
- **终跑证据套件与 G 门判决 JSON**：
  1. G 门判决总 JSON（含 `G1/G2/G3`、`concentration_cond`、`TIER_C`、`METAR(DST)` 非门禁平行报告 1、`OfficialMETAR(LST)` 非门禁平行报告 2、重点观察项、W2 `KMIA_12h` 重读）：[`evidence/p8_inspection_c_2019_final_lst_20261114.json`](../../evidence/p8_inspection_c_2019_final_lst_20261114.json)
  2. 终跑判决报告：[`evidence/p8_inspection_c_2019_final_lst_report_20261114.md`](../../evidence/p8_inspection_c_2019_final_lst_report_20261114.md)
  3. 16 层 CRPS/ECE 表：[`evidence/p8_inspection_c_2019_final_16strata_lst_20261114.csv`](../../evidence/p8_inspection_c_2019_final_16strata_lst_20261114.csv)
  4. W2 22 格四维评分表（`inw` 主口径 + `w20` 伴随）：[`evidence/p8_inspection_c_2019_final_w2_22cells_lst_20261114.csv`](../../evidence/p8_inspection_c_2019_final_w2_22cells_lst_20261114.csv)
  5. 696 原子桶残差与 Wilson 95% CI 表：[`evidence/p8_inspection_c_2019_final_atom_696_lst_20261114.csv`](../../evidence/p8_inspection_c_2019_final_atom_696_lst_20261114.csv)
  6. 2019 232 切片塔性质期望检查表：[`evidence/p8_inspection_c_2019_final_slices_232_lst_20261114.csv`](../../evidence/p8_inspection_c_2019_final_slices_232_lst_20261114.csv)
- **口径勘误、登记闭合与制度存档**：
  - [`docs/MODEL_SCORECARD.md#L13-L19`](../MODEL_SCORECARD.md#L13-L19)（D1 `inw` 操作口径勘误）
  - [`docs/audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md`](P8-ALGO-REVIEW_待确认事项登记册_20261113.md)（`G-14` 闭合、`G-15` 新立、`KMIA_12h w20` 尾部退化观察、后续追加 `α` 冻结与 2019 消费台账）
  - [`docs/audit/P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md`](P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md)（`v5` + 附录一预注册标准 + 后续 `v6` 与设计组 C 档签字行）
  - [`docs/项目方案和执行文档/Phase 2 执行文件 v2.2：盘口定价、套利与执行引擎.md#L225-L226`](../项目方案和执行文档/Phase%202%20执行文件%20v2.2：盘口定价、套利与执行引擎.md#L225-L226) & [`docs/audit/P8-ALGO-DEF_第三段条件分布_20261110.md#L126`](P8-ALGO-DEF_第三段条件分布_20261110.md#L126)

---

## 三、 封跑反事实与判决稳健性（`2019-SEALED-001` 终闭合）

- **执行档案与摘要工件**：`2026-11-14` 由设计组按 `2019 封跑制度` 手动触发 [`scripts/run_p8_metar_counterfactual_sealed_2019.py`](../../scripts/run_p8_metar_counterfactual_sealed_2019.py)，产出唯一聚合摘要 [`evidence/p8_metar_counterfactual_sealed_2019_summary.json`](../../evidence/p8_metar_counterfactual_sealed_2019_summary.json)（SHA256 `ee6f809450803855efc56f300acbe3a7f1a842b59371382cfcf84f53133df789`，`run_utc=2026-11-14T15:51:53Z`），完成 `{5min_LST, OfficialMETAR_LST} × {GHCN_LST, OfficialMETAR_DST}` **2×2 全观测流×真值矩阵**实证闭环。

### 3.1 四配置 `G3` 对照表（含全部二项 `z` 值）

二项检验零假设 $p_0 = 0.05$，$z = \dfrac{k - 0.05 N}{\sqrt{0.05 \times 0.95 N}}$（门禁要求：`G3a <= 25/312` 且各族 `|wResid| <= 0.05`；`G3b <= 20`；`G3c <= 0.020`）：

| 过桥配置（观测流 × 结算真值） | 来源工单 | `CRPS_bridge` | `G3a` 午后出界 (`z` 值) & `B1/B2/B3 wResid` | `G3b` 早段 B12 出界 (`z` 值) | `G3c` `ECE_bridge(inw)` | `G3` 综合 |
| :--- | :--- | ---: | :--- | :--- | ---: | :--- |
| **终跑主判**（`5min_LST × GHCN_LST`） | `2019-HIST-02` | `1.294325` | `36/312` (**`z = +5.30`**, `5.2991`) \| `-0.0151 / -0.0062 / +0.0009` (**FAIL**) | `38/228` (**`z = +8.08`**, `8.0829`) (**FAIL**) | `0.030586` (**FAIL**) | **三败** |
| **平行变体 2**（`OfficialMETAR_LST × GHCN_LST`） | `2019-HIST-02`（非门禁） | `1.109202` *(18h 匹配)* | `49/312` (**`z = +8.68`**, `8.6761`) \| `+0.0161 / +0.0422 / +0.0354` (**FAIL**) | `50/224` (**`z = +11.89`**, `11.8949`) (**FAIL**) | `0.034378` (**FAIL**) | **三败** |
| **`T1` 反事实**（`5min_LST × OfficialMETAR_DST`） | `2019-SEALED-001` | `1.432047` | `50/312` (**`z = +8.94`**, `8.9358`) \| `-0.0024 / -0.0013 / -0.0034` (**FAIL**) | `56/228` (**`z = +13.55`**, `13.5525`) (**FAIL**) | `0.032407` (**FAIL**) | **三败** |
| **`T2` 同源反事实**（`OfficialMETAR_LST × OfficialMETAR_DST`） | `2019-SEALED-001` | **`1.193529`** | `60/312` (**`z = +11.53`**, `11.5334`) \| `+0.0021 / +0.0275 / +0.0155` (**FAIL**) | `59/224` (**`z = +14.65`**, `14.6540`) (**FAIL**) | **`0.008301`** (**PASS**) | **二败一过** |

### 3.2 五配置 `ECE` 全景表（`inw` 法定主口径 + `w20` 伴随）

| 评估配置 | 观测流 → 结算真值 | `ECE(inw)` | `ECE(w20)` | 相对先验 `ΔECE(inw)` | 对 `0.020` 门禁线 | 分量解释 |
| :--- | :--- | ---: | ---: | ---: | :--- | :--- |
| **1. 先验原生基线** | 无桥先验 → `GHCN(LST)` / `METAR(DST)` | `0.003641` / `0.002865` | `0.004521` / `0.002589` | `—` | **✅ 基准极洁净** | 年内抽样噪声水平 `<= 0.005` 量级 |
| **2. 终跑主判** | `5min(LST)` → `GHCN(LST)` | `0.030586` | `0.030621` | `+0.026945` | **❌ 超限** | `MADISHF 5min` 高频捕获+量子化 vs `GHCN` 跨通道地板 |
| **3. 平行变体 2** | `OfficialMETAR(LST)` → `GHCN(LST)` | `0.034378` *(匹配 5min `0.033727`)* | `—` | `+0.030737` | **❌ 超限** | 跨真值源（`METAR` vs `GHCN` `+0.54/+0.83°F`）日界错位叠加 |
| **4. `T1` 反事实** | `5min(LST)` → `OfficialMETAR(DST)` | `0.032407` | `0.032326` | `+0.029542` | **❌ 超限** | 切换真值但观测仍留 `5min(LST)`，跨源错位仍在 |
| **5. `T2` 同源反事实** | `OfficialMETAR(LST)` → `OfficialMETAR(DST)` | **`0.008301`** | **`0.008521`** | **`+0.005436`** | **✅ 唯一通过** | **同源流消除通道错位分量**；但 `G3a/b` 反而爆表至 `z=+11.5/+14.7` |

### 3.3 终闭合结论：双分量确证与 `C 档` 穷举稳健

1. **判决稳健性（穷举完结，无未测反事实）**：在当前可用的观测流与日界真值完整 `2×2` 组合空间中，方案 $\alpha$ 在全部 4 种过桥配置下的 `G3` 原子门禁**全线败北（`G3a z = +5.30..+11.53`，`G3b z = +8.08..+14.65`）**；**已不存在尚未检验的真值/观测反事实配置**，`C 档（终止可签）` 判决具有穷举稳健性。
2. **双分量机理确立（预判部分修正）**：`2019-SEALED-001` 以实证将检验 C 失真清晰分解为两项正交来源——① **通道错位分量**：当且仅当观测流与结算真值同源对齐（`T2: OfficialMETAR_LST -> OfficialMETAR_DST`）时，11 档全池 `ECE_bridge(inw)` 从 `0.0306–0.0344` 骤降至 **`0.008301 <= 0.020`**（此前对 `T2` 池化 `ECE` 亦败的悲观预判被证伪）；② **单高斯桥纯结构分量**：即使在通道完全同源且 `CRPS` 改善最大化（`-53.11%`）、池化 `ECE` 达标的 `T2` 下，锁顶原子 `G3a / G3b` 出界不仅没有改善反而升至 `60/312 (z=+11.53)` 与 `59/224 (z=+14.65)`，直接证明单高斯 $\mu_R$ 在“点质量 vs 上尾分布”上的结构耦合矛盾不可通过对齐数据源消除，为方案 `β/γ` 立项完成司法级终闭合归档。
