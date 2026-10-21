# P4-BLIND-AUDIT · V2R-01 第二类 V2.0 尺子升级 · 开发任务单（换尺子，不重训）

> 致：开发端 Agent。本单自包含，读完即可执行。
> 审核方：技术审核 Agent；用户已对 Q2–Q6 逐项拍板（见 §6）。
> 性质：**只读离线评估尺子升级**。新建独立评估脚本，不改冻结结算脚本，不重训、不写回 pkl/manifest/生产 c_train，不跑 2000-2018 训练。开发只交原始值与下沉布尔，门限由审核方机械判定，**开发不自定阈值、不写主观通过结论**。
> Git：本地提交可做，**push 必须等用户明确指令**，开发不代推。

## 1. 目的

V1 五道固定工程带（G1 KS / G2 7档ECE / G3 s_oos∈[0.85,1.15] / G4 PIT均值 / G5 coverage）口径有缺陷。本单**只换评估尺子**，对 2019 双城 22 格用新口径并行重打分，与 V1 结果并列对照；不改模型、不改 V1 冻结结论。

## 2. 输入工件（只读，禁止改写）

| 用途 | 路径 |
| :-- | :-- |
| 逐样本序列（主输入） | `data/processed/audit_arrays/2019_oos_p4_settlement_arrays.parquet` |
| V1 已结算统计（新旧对照基准，只读） | `evidence/p4_2019_settlement_statistics.csv` |
| 模型参数/manifest（仅核对，禁止写回） | `data/models/manifest.json` |
| 分布 family/shape（如需重建 CDF） | climate 配置 + manifest，只读 |

parquet 列：`target_date, tmax_f, month, season, ens_mean, ens_var, cell, mu_calib, sigma_calib, pit_u`；`cell` 共 22 个（KORD/KMIA × 12/18/24/30/36/42/48/54/60/66/72h，tmax）。`sigma_calib` 即 V1 的 sig_eff。

## 3. 任务 A（Q2+Q3）· s_oos 的 N_eff 动态非对称 F 带 + 单年置信口径

对每个 cell，按 `target_date` 排序后：

1. 残差 `e = tmax_f − mu_calib`；`n = len(e)`。
2. `s_oos = var(e, ddof=1) / mean(sigma_calib²)`（与 V1 同式）。
3. `rho1 = corr(e[:-1], e[1:])`，clip 到 `[0, 0.99]`。
4. `N_eff = n·(1−rho1)/(1+rho1)`。
5. 两套 95% 双侧带**并列**（α=0.05，不指定哪条法定）：
   - `Finf`：`[chi2.ppf(0.025,N_eff)/N_eff, chi2.ppf(0.975,N_eff)/N_eff]`；
   - `Fstd`：`[f.ppf(0.025,N_eff,n−1), f.ppf(0.975,N_eff,n−1)]`。
6. 下沉布尔（各自独立，不合并）：
   - `finf_in = bool(lo_f <= s_oos <= hi_f)`
   - `fstd_in = bool(lo_s <= s_oos <= hi_s)`
7. Q3：不另设独立 covers_one 列（见 §11-Q3）；"CI 覆盖 1"对偶等价于带内判定，直接复用 `finf_in/fstd_in`。

## 4. 任务 B（Q4）· KS + CvM 双检验，方案乙门禁

1. 取该 cell 的 `pit_u`（V1 已算，直接用；如需复算须与 V1 同 CDF）。
2. KS：`ks_stat, ks_p = scipy.stats.kstest(pit_u, "uniform")`。
3. CvM：`cvm_stat, cvm_p = scipy.stats.cramervonmises(pit_u, "uniform")`（scipy 1.17 已装；若该接口不可用，如实报错并说明，不得自行换用未验证替代）。
4. **下沉布尔（方案乙：准入宽、否决严）**：
   `reject_uniform = bool((ks_p < 0.05) and (cvm_p < 0.05))`
   仅当两者同时显著才否决；任一 p≥0.05 即不拒绝。开发原样输出 `ks_p`、`cvm_p`、`reject_uniform`，不另写"通过/不合格"主观结论。

## 5. 任务 C（Q5）· 固定 2°F 分箱 ECE + 分箱敏感性

1. 本轮**不接真实市场 11 档**（2019 无当日在售档界存档）；预留接口，禁止自造档界度宽。
2. 在多套分箱口径下各算一次加权 ECE，并列报离散度：
   - 口径①固定 2°F 观测箱：按 `tmax_f` 落点切 2°F 宽箱，箱内平均预测置信度 vs 命中率，加权 ECE；
   - 口径②沿用 V1 7 档 ±3°F（复算，供对照）；
   - 口径③等频置信度分桶（num_bins=10 与 =20 各一）。
3. 输出每格：`ece_2f`、`ece_7bin_v1`、`ece_bins10`、`ece_bins20`、`ece_range = max−min`。
4. 预测概率/命中口径须与 V1 `compute_weighted_ece` 同源；若重建分布需要 family/shape，只读 manifest/climate，不改任何参数。

## 6. 任务 D（Q6）· PIT 方差与形态（本轮并入）

1. `pit_var = var(pit_u, ddof=1)`，理论值 1/12≈0.083333 仅作参照列。
2. PIT 等宽 10 档直方图计数（0–1 均分 10 格），原样输出各格占比，供审核判 U 型/凹型/均匀；开发不自行贴"U 型/合格"标签。
3. 与 V1 `pit_mean` 并列，不替代均值诊断。

## 7. 交付物

1. 新独立脚本（建议 `scripts/audit_v2/reliability_v2.py`），**不改** `scripts/evaluate_p4_2019_settlement.py`。
2. 22 格新指标 CSV（建议 `evidence/audit_v2/p4blind_v2r01_metrics.csv`），列至少含：
   `station, lead_hours, cell, n, s_oos, rho1, neff, finf_lo, finf_hi, finf_in, fstd_lo, fstd_hi, fstd_in, ks_stat, ks_p, cvm_stat, cvm_p, reject_uniform, ece_2f, ece_7bin_v1, ece_bins10, ece_bins20, ece_range, pit_mean, pit_var, pit_hist_b01…pit_hist_b10`（列名与格式见 §11-Q5）。
3. 新旧尺子对照 CSV：同一 cell 的 V1 旧门判定 vs V2 新布尔并列，不改写 V1 原值。
4. 复现命令、退出码、全部输入/输出文件 SHA-256、终端末尾原始片段。

## 8. 复现与证据要求（硬性）

- 交付说明必须附：①实际执行命令；②输出末尾含原始数值的片段；③每个下沉布尔列与原始量逐位对应。
- 未执行的测试/计算不得称"通过"；开发只回读代码原生布尔，不自行做阈值比较或美化数值。
- airgap 守卫回归（若涉及 2019 读取）仍须过：`pytest tests/unit/verification/test_2019_airgap_guardrail.py -q`，附输出。

## 9. 明确不做

- 不重训 EMOS a/b/c/d、不改 c_train、不写回 pkl/manifest；
- 不修改 V1 冻结结算脚本与 V1 结论；
- 不臆造 Polymarket 2019 当日档界；
- 不自行决定 ECE/PIT 方差法定阈值（留审核方）；
- 不擅自 push。

## 10. 执行结果（开发回交后由审核方填写）

- 脚本路径 / SHA-256：`scripts/audit_v2/reliability_v2.py` / `e821c0aa0079f483f3510698f919751886d908bae145e3cd5385eae9c14a68ba`
- 指标 CSV / 对照 CSV / SHA-256：
  - 指标表：`evidence/audit_v2/p4blind_v2r01_metrics.csv` (22 行) / `ae615945bc35a72fb9f9c2de04f26033637ad080f7cf70fc66b514065ccb611a`
  - 对照表：`evidence/audit_v2/p4blind_v2r01_comparison.csv` (22 行) / `572cc7cb8f033ddda8317d0e6b729ea8dc041cb085e1e1f0be3ffb022da6af21`
- 复现命令 / 退出码：`python3 scripts/audit_v2/reliability_v2.py --run` / `0`
- 下沉布尔原始汇总：
  - s_oos 带内：V1 原固定 [0.85, 1.15] 为 9/22；V2 Finf 带内为 11/22（救回 2 格：KMIA 18h/36h）；V2 Fstd 带内为 19/22（救回 10 格：KORD 24/36/60h，KMIA 18/24/36/42/60/66/72h；仅 KMIA 30h/48h/54h 仍超界）。
  - 均匀性：V1 原 KS 通过 20/22（KORD 48h/72h 挂掉）；V2 方案乙 reject_uniform 全体 False（0/22 否决，22/22 均不拒绝，CvM 救回两格边缘悬崖）。
  - ECE 均值（FIX1 档级加权修正）：V1 原 7 档 0.87%；V2 11 档档级直接可靠性 ECE 均值 1.18%，多分箱平均敏感性极差 0.78%（22/22 格 ece_2f 与 ece_bins20 严格不等，min diff 0.03%，max diff 1.69%），全部 22 格 ECE 均远低于 5% 门限。
- 审核方机械判定（2026-10-21 FIX1 终审，独立复算，两步分离）：

  **复核方式**：审核方从 parquet 独立重建 CDF 重算 22 格档级 ECE、s_oos/ρ₁/N_eff/Finf/Fstd、KS/CvM/reject_uniform/pit_var，与两 CSV 逐格对账。

  - **Q2/Q3 F 带 → 通过**：原始观测值 finf_in 11/22、fstd_in 19/22；独立复算无漂移。双带并列、无法定门。
  - **Q4 方案乙 → 通过**：原始观测值 reject_uniform 0/22；独立复算一致，KORD_48/72 边缘被 CvM 救回。
  - **Q5 ECE（FIX1 后）→ 通过**：原始观测值 ece_2f 独立复算 22/22 匹配（NONE mismatch）；ece_2f≠ece_bins20 22/22（min 0.000334 / max 0.016930）；ece_2f 均值 0.011835、ece_range 均值 0.007836；四口径 ECE 全部 <0.05（max 0.019610）。判定阈值=档级直接可靠性 ECE 与概率桶分离。结论=口径缺陷已闭合。
  - **Q6 PIT → 通过**：pit_var 0.082422~0.091727 贴理论 1/12，10 档和=1，复算一致。
  - **SHA-256**：脚本 e821c0aa…、对照 572cc7cb… MATCH；metrics ae615945…（开发初抄漏首字符，已按本地实算更正）。
  - **airgap**：开发附真实输出 `6 passed in 0.59s`、退出码 0；审核本地 pytest 7.4.3<8.3 未复跑，采纳开发片段。

  **终审结论：四项全部通过，V2R01 尺子升级闭环。** 不产出综合 candidate_pass（依 §11-Q6）；ECE 法定阈值与 PIT 通用带边界留审核方/用户，本轮不代判。已 push（用户授权），工作树干净。

## 11. 开发端拷问裁定（2026-10-21，本节优先级高于前文歧义表述）

**裁定 Q1（2°F 积分几何）→ 方案 A：逐日局部梯子全覆盖。**
- 逐日以 `mu_calib` 为锚铺 2°F 宽离散档（整度锚定、档宽 2°F），用模型 CDF 积分每档概率，观测唯一落档命中 h∈{0,1}，Σp≈1，无尾部漏检。
- 否决方案 B（每天只取命中箱则 h≡1，ECE 退化）与方案 C（全局全箱塞入大量 p≈0/h=0 假阴性，污染加权 ECE）。
- 尾部按 CDF 双侧截断，交付说明写明截断规则并记录 Σp 与 1 的偏差；本方案为 2019 历史降级近似，**不声称等于真实盘口档界**，真实 11 档接口预留。

**裁定 Q2（分桶定义与输入对）→ 口径③取方案 A 的完整 (p,h) 对，用标准等宽 `compute_weighted_ece` 分别 num_bins=10、20**（与库 `np.linspace(0,1,nb+1)` 等宽、count 加权同源可比）；真·等频分位数桶仅作可选附加，非法定主口径。

**裁定 Q3（covers_one 语义）→ 删除独立 covers_one 列。** 零假设接受域 [lo,hi] 恒含 1，字面 `lo<=1<=hi` 恒真无鉴别力；"CI 覆盖 1"对偶等价于 `s_oos∈[lo,hi]`，直接复用 `finf_in/fstd_in`，文档注明数学对偶，不输出恒真布尔。

**裁定 Q4（N_eff 精度）→ 方案 A：浮点 N_eff 直接传入 `chi2.ppf/f.ppf`，不 round；** CSV 中 neff 与临界值保留 4 位小数。

**裁定 Q5（PIT 直方图）→ 列名 `pit_hist_b01…b10`，值=count/n 占比、6 位小数，10 列和≈1.0。**

**裁定 Q6（对照表）→ 并列客观量与 V1 原布尔；不生成 `v2_candidate_pass` 综合标签；** Q2 双带并列无法定，s_oos 不产生单一改判布尔，只并列 `finf_in/fstd_in`；仅 Q4 给 `v1_ks_pass` vs `v2_reject_uniform` 对照。改判汇总归审核方。
