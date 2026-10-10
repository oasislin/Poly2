# EVIDENCE_INDEX.md

本文件为《解阻断证据提交指令单 · 最终版》、《第二轮修复令 (R-1 ~ R-5)》及《P 系列数据工程令 (P-0 ~ P-3)》之法定索引清单。每行一句话说明：编号 → 文件 / Raw 直链 → 对应阻断条款与解决说明。

| 编号 | 文件名与 Raw 直链 | 对应阻断条款与处置说明 |
| :--- | :--- | :--- |
| **00** | [`00_commit_anchor.txt`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/00_commit_anchor.txt) | **阻断项 ⓪ (Commit 锚定)**：提供 `git log -5` 与 `git show 67d668b --stat` 完整 stdout，锚定代码提交与 r5 修正声明。 |
| **01A** | [`01_closure_fix.diff`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/01_closure_fix.diff) | **阻断项 ① (闭包断言修复)**：修复量级与均值闭包断言，实现 $\Phi_2$ 偏差感知理论推导、双容差解析导出、清除静默 clip 与十分位分层。 |
| **01B** | [`01_regression_tests.diff`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/01_regression_tests.diff) | **阻断项 ① (回归测试夹具)**：新增 `tests/test_closure_regression.py`，永久固化 KORD/KMIA/全绿表三组历史伪造现场，显式包含均值闭包负断言。 |
| **01C** | [`01_pytest_output.txt`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/01_pytest_output.txt) | **阻断项 ① (测试实跑凭据)**：实测通过 `pytest` 完整 stdout，打印理论均值与理论标准差，证实 3 组伪造用例全部以预期异常拦截。 |
| **02** | [`02_ece_decision.diff`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/02_ece_decision.diff) | **阻断项 ② (ECE 门禁口径)**：路径 A 落地，diff 确认硬性回滚至 $\le 3.0\%$，变更日志记录 3%→5%→3% 往返并归档未经授权偏离的教训。 |
| **03A** | [`03_orderbook_diff.diff`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/03_orderbook_diff.diff) | **阻断项 ③ (订单簿资产验明)**：路径 B 落地，正式定性当前纸面盘为纯合成对抗做市商仿真，删除订单簿回放表述，登记撮合沙盒推迟条件。 |
| **03B** | [`03_void_status.diff`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/03_void_status.diff) | **阻断项 ③+ (历史结论作废)**：在 README 状态区与 Task 07 spec 加注 pre-67d668b 基于旧度量的全部结论 VOID pending `--recompute` 警示。 |
| **04** | [`04_calibration_audit.py`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/04_calibration_audit.py)<br>([`04_self_audit.txt`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/04_self_audit.txt)) | **阻断项 ④ (度量代码形式冻结)**：冻结 `calibration_audit.py` (Blob `b771040d70b84cb475fe8a3ed56ec408f9487bf4`)，附 8 行自查声明及三条备注补丁。 |
| **05** | [`05_text_fixes.diff`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/05_text_fixes.diff) | **阻断项 ⑤ (文本三修)**：NOAA ASOS 1088 PRT $\pm 0.9^\circ\text{F}$ 规格出处 + ADR-0015 逐字引用被废止代码（Blob `58d713ce...`）+ 移除 BH 条款。 |

---

### 二、--recompute 全量重算与本源数据调取工件清单 (随行修正与调取令 T-1~T-5)

| 编号 | 工件名称与 Raw 直链 | 协议与调取令条款 | 核心内容摘要 |
| :--- | :--- | :--- | :--- |
| **T-1/2** | [`t1_t2_provenance_audit.txt`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/t1_t2_provenance_audit.txt) | **调取令 T-1 & T-2** | 2019 IEM ASOS 真值快照 SHA256 + 365 日无缺漏实证 + GEFS 2000-2019 全 20 年落库与 5 成员枚举。 |
| **T-1A** | [`t1_kord_obs_truth_2019_head20.csv`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/t1_kord_obs_truth_2019_head20.csv) | **调取令 T-1 (KORD 快照)** | KORD 2019 年真实地面观测温度原始真值前 20 行 CSV 导出，供公开比对。 |
| **T-1B** | [`t1_kmia_obs_truth_2019_head20.csv`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/t1_kmia_obs_truth_2019_head20.csv) | **调取令 T-1 (KMIA 快照)** | KMIA 2019 年真实地面观测温度原始真值前 20 行 CSV 导出，供公开比对。 |
| **T-1C** | [`t1_ksfo_obs_truth_2019_head20.csv`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/t1_ksfo_obs_truth_2019_head20.csv) | **调取令 T-1 (KSFO 快照)** | KSFO 2019 年真实地面观测温度原始真值前 20 行 CSV 导出，供公开比对。 |
| **T-4** | [`sigma_star_recomputed.json`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/sigma_star_recomputed.json) | **调取令 T-4 ($\sigma^*$ 重锚定)** | 基于真实 2019 样本外重算各站残差 MAE 与经验尺度：KORD=3.29°F, KMIA=1.74°F, KSFO=4.06°F。 |
| **RC-1** | [`pilot_parameters.json`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/pilot_parameters.json) | **重算协议 §4 (参数工件)** | 三站 × 4 季独立拟合参数、收敛状态码 (全 CONVERGED=True) 与迭代步数 JSON。 |
| **RC-2** | [`pilot_predictions_2019.parquet`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/pilot_predictions_2019.parquet)<br>([head20 CSV](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/pilot_predictions_2019_head20.csv)) | **重算协议 §4 (逐日推演)** | 2019 逐日实测、$\mu_f$、$\sigma_f$、随机化 PIT $U$，全站 1095 条日推演完整记录。 |
| **RC-3** | [`pit_histograms.svg`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/pit_histograms.svg) | **重算协议 §4 (PIT 矢量图)** | 三站 10 桶 PIT 直方图矢量图，对比理想均匀分布红虚线。 |
| **RC-4** | [`reliability_diagrams.svg`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/reliability_diagrams.svg) | **重算协议 §4 (可靠性图)** | 三站 20 桶离散分桶可靠度曲线矢量图，对比理想 45° 对角线。 |
| **RC-5** | [`recompute_settlement_report.md`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/recompute_settlement_report.md) | **重算协议 §5 (门禁结算)** | 依据重算协议第 5 节门禁标准逐项结算之裁决报告，如实报告各项真实读数。 |
| **RC-6** | [`pilot_manifest.json`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/pilot_manifest.json) | **重算协议 §4 (清单工件)** | 全量重算产出物 SHA256 签名与随机化种子 (seed=42) 锁定清单。 |

---

### 三、P 系列官方真值工程令工件清单 (P-0 ~ P-3 GHCN-Daily Truth Layer)

| 编号 | 工件名称与 Raw 直链 | 协议条款 | 核心内容摘要 |
| :--- | :--- | :--- | :--- |
| **P-1A** | [`p1_download_metrics.csv`](https://raw.githubusercontent.com/oasislin/Poly2/feat/p-series-ghcn-truth-layer/evidence/p1_download_metrics.csv) | **工程令 P-1** | 10 站 × 30 样本抽样实测指标：实际字节数、墙钟时间、p95 耗时、成功率 (100%) 与网络时间戳。 |
| **P-1B** | [`p1_decision_summary.md`](https://raw.githubusercontent.com/oasislin/Poly2/feat/p-series-ghcn-truth-layer/evidence/p1_decision_summary.md) | **工程令 P-1** | 下载模式量化判定总表：全量 10 站归档单站平均 15s 落地，总耗时 ~150s << 1 小时，裁定为交互式直接下载。 |
| **P-2** | [`p2_qc_summary.md`](https://raw.githubusercontent.com/oasislin/Poly2/feat/p-series-ghcn-truth-layer/evidence/p2_qc_summary.md) | **工程令 P-2** | 2000–2019 全 20 年质控报告：各站 7305 记录、缺失率核验、与 METAR All/Hourly 双轨逐年均值差比对。 |
| **P-3** | [`p3_truth_manifest.json`](https://raw.githubusercontent.com/oasislin/Poly2/feat/p-series-ghcn-truth-layer/evidence/p3_truth_manifest.json) | **工程令 P-3** | 10 站独立落库 Parquet 文件 SHA256 签名清单，锁定真值源版本，保证 100% 离线可复现。 |

---

### 四、第二轮修复令 R-1 ~ R-5 与澄清工件清单 (R-1 ~ R-5 Remediation & Clarifications)

| 编号 | 工件名称与 Raw 直链 | 协议条款 | 核心内容摘要 |
| :--- | :--- | :--- | :--- |
| **R-1** | [`r1_unit_convention_audit.md`](https://raw.githubusercontent.com/oasislin/Poly2/fix/r1-unit-convention-audit/evidence/r1_unit_convention_audit.md) | **修复令 R-1** | 单位约定与舍入审计对照表，排除真值与预报单位错位假设，定性冷偏差为模型偏差（PR #111 已闭环）。 |
| **R-1B** | [`r1_exclusion_check_stdout.txt`](https://raw.githubusercontent.com/oasislin/Poly2/fix/r1-unit-convention-audit/evidence/r1_exclusion_check_stdout.txt) | **修复令 R-1** | 排除性验证脚本纯数字凭据，逐项证明 0.1°C 秒组与 1°F 整度报文一致性。 |
| **CLR-1** | [`p1_bulk_download_log.csv`](https://raw.githubusercontent.com/oasislin/Poly2/feat/r2-r3-ghcn-retraining-and-budget/evidence/p1_bulk_download_log.csv) | **澄清 ①** | 10 站实际批量归档文件下载耗时（总耗时 304s / 5.1min）与字节数日志，澄清 300 样本探针口径。 |
| **CLR-2** | [`r2_speci_all_hourly_yearly_breakdown.csv`](https://raw.githubusercontent.com/oasislin/Poly2/feat/r2-r3-ghcn-retraining-and-budget/evidence/r2_speci_all_hourly_yearly_breakdown.csv) | **澄清 ②** | 2000–2019 全 20 年 × 10 站 All−Hourly 逐年差值表，证实 2016+ 高频 SPECI 升级导致 4~6 倍阶跃放大。 |
| **CLR-3** | [`r2_target_switch_budget.csv`](https://raw.githubusercontent.com/oasislin/Poly2/feat/r2-r3-ghcn-retraining-and-budget/evidence/r2_target_switch_budget.csv) | **澄清 ③** | 切靶预算实测表：量化切靶消解比例（KORD 83.4%, KMIA 69.2%, KSFO 30.2%），如实记录残余真模型偏差。 |
| **R-2/3** | [`r2_r3_diagnosis_and_budget_report.md`](https://raw.githubusercontent.com/oasislin/Poly2/feat/r2-r3-ghcn-retraining-and-budget/evidence/r2_r3_diagnosis_and_budget_report.md) | **修复令 R-2 / R-3** | R-2 诊断附页：包含澄清 ②③ 专项答复、台站地形与下垫面气象分型诊断（KSFO 圣克鲁兹山/海洋平流，KMIA 对流云）。 |
| **R-4A** | [`r4_ece_definition_audit.md`](https://raw.githubusercontent.com/oasislin/Poly2/feat/r2-r3-ghcn-retraining-and-budget/evidence/r4_ece_definition_audit.md) | **修复令 R-4** | 离散 7 档位加权 ECE 功效审计报告，维持硬门禁 $\le 3.0\%$，论证多档位分布与第一轮中心档位假象病灶。 |
| **R-4B** | [`r4_gate_calibration_protocol.md`](https://raw.githubusercontent.com/oasislin/Poly2/feat/r2-r3-ghcn-retraining-and-budget/evidence/r4_gate_calibration_protocol.md) | **修复令 R-4** | 《门禁标定与变更管理协议》：解析推导外生变量（$\sigma_{\text{inst}}$, $\sigma^*$, 方差比），确立预注册与防篡改规则。 |
| **R-5** | [`recompute_settlement_report.md`](https://raw.githubusercontent.com/oasislin/Poly2/feat/r2-r3-ghcn-retraining-and-budget/evidence/recompute_settlement_report.md) | **修复令 R-5** | 基于 GHCN-Daily 官方气候真值重算结算报告：加权 ECE 全绿（0.46%~2.39% $\le 3.0\%$），十分位闭包全绿，如实记录 KMIA KS-test。 |

---

### 五、P4 可靠度审计与 P5 范围核查工件清单 (P4-AUDIT-RELIABILITY & P5-AUDIT-SCOPE)

| 编号 | 工件名称与路径 | 协议与任务条款 | 核心内容摘要 |
| :--- | :--- | :--- | :--- |
| **P4-v1.3b-1** | [`evidence/p4_audit_reliability_v13b_report.md`](evidence/p4_audit_reliability_v13b_report.md) | **工单 P4-AUDIT-RELIABILITY-v1.3b** | TMax KORD 关门审计法定报告：PIT 均匀性 $p=0.46915 \gg 0.05$、残差偏度 0.0471、超额峰度 0.0667、实质分档（全部微小偏差）、峰值桶断言 $\le 35\%$ 全绿（Max 31.77%）、1.28 深尾系数。 |
| **P4-v1.3b-2** | [`evidence/p4_audit_reliability_v13b_summary.json`](evidence/p4_audit_reliability_v13b_summary.json) | **工单 P4-AUDIT-RELIABILITY-v1.3b** | v1.3b 关门法定统计结构化数据，含前置三声明与审计范围声明。 |
| **P4-v1.3b-3** | [`evidence/p4_audit_reliability_v13b_lineage.json`](evidence/p4_audit_reliability_v13b_lineage.json) | **工单 P4-AUDIT-RELIABILITY-v1.3b** | 13,740 样本外验证日 100% 逐日数据血统映射与 SHA256 签名。 |
| **P5-SCP-1** | [`evidence/p5_audit_scope_recon_memo.md`](evidence/p5_audit_scope_recon_memo.md) | **工单 P5-AUDIT-SCOPE** | 训练覆盖范围核实备忘：960 格模型已训练、20 折审计覆盖率 4/960 (0.42%)、Active 10 站真值修正、TMin 零审计定责。 |
| **P5-SCP-2** | [`evidence/p5_audit_scope_recon.json`](evidence/p5_audit_scope_recon.json) | **工单 P5-AUDIT-SCOPE** | 覆盖范围核查结构化对账矩阵与台站缺口清单。 |
| **P6-HDF-1** | [`evidence/handoff_p6_tmax_fullgrid.md`](evidence/handoff_p6_tmax_fullgrid.md) | **工单 P6-1-HANDOFF** | 双城 TMax 全网格验证与方法论封盘新会话交接协议，包含八节法定内容与 92 格执行路径。 |
| **P6-EVT-G1** | [`evidence/evt_path_validation_report.md`](evidence/evt_path_validation_report.md) | **工单 P6-EVT-GUARD** | EVT 代码路径离线预验证与缺陷审计报告：捕获经验分位数拼接负跳跃（-2.72%）与全域积分不归一（1.0545）重大缺陷，KATL/KDAL/KLAX/KSFO 四格隔离标记生效。 |
| **P6-EVT-F1** | [`evidence/p6_evt_fix_remediation_report.md`](evidence/p6_evt_fix_remediation_report.md) | **工单 P6-EVT-FIX** | EVT 核心逻辑成对修补、四格受控重算与解禁验收报告：落地 Scheme B 条件高斯重标截断公式，扩展 10 项契约测试全绿，四格积分恢复 1.00000000 且解除隔离，零漂移基线 100% 守住。 |
| **P6-HTD-1** | [`evidence/p6_heavytail_diag_report.md`](evidence/p6_heavytail_diag_report.md) | **工单 P6-HEAVYTAIL-DIAG** | KORD 42h 厚尾归因拆层与机制诊断四件套质检报告：完成锋面条件化、sigma_eff 离散度、留一法敏感度、折内季节构成四项实测与机械两步判定。 |
| **P6-HTD-2** | [`evidence/p6_heavytail_diag_results.json`](evidence/p6_heavytail_diag_results.json) | **工单 P6-HEAVYTAIL-DIAG** | 机制诊断四件套结构化结果工件，包含 42h 目标格与 12h..36h 对照组完整统计数值。 |
| **P6-CALM-1** | [`evidence/p6_calm_outlier_precheck_report.md`](evidence/p6_calm_outlier_precheck_report.md) | **工单 P6-CALM-OUTLIER** | 平静日极端失准的事前指纹判别与 Regime 条件模型评估报告：确证稀疏极端日支配厚尾（年均不足 1 天）、失准日集中于天气学平静日；提供 5 元组实证、清晨中性相位特征（sigma_ens < 0.50°F）与 2°F 整度判定几何边界伪影证据；重呈闭环；SHA256: `a2da866edc1e3c4680eab1d3c9241ca47561b07cb382b0da3afbedf0bf92c7bb`。 |
| **P6-KMIA-GATE-1** | [`evidence/kmia_12h_gate_report.md`](evidence/kmia_12h_gate_report.md)<br>[`evidence/kmia_12h_data_gate_audit.md`](evidence/kmia_12h_data_gate_audit.md) | **工单 P6-KMIA-GATE** | KMIA_12h 回溯门禁取证与预注册放行裁决报告：数据五件套全绿、20 折 EVT 碾压获胜（中位数 ΔBIC=-291.96）、Top-5 极端失准均为预报集体失效且集合极窄离散度、达成自动放行分支；加权 ECE 0.0183 越法定门槛 0.0100 挂旗 COMPLETED_ECE_FLAGGED 入账。 |
| **P6-KMIA-18H-GATE-1** | [`evidence/kmia_18h_jsu_gate_report.md`](evidence/kmia_18h_jsu_gate_report.md) | **工单 P6-KMIA-18H-GATE** | KMIA_18h 轻量级 JSU 门禁取证与自动放行裁决报告：J1 参数稳定无贴界（CV<3.2%）、J2 20 折 JSU 全胜碾压（中位 ΔBIC=-787.93）、J3 Top-5 均为雷暴暴雨集体失准、J4 加权 ECE 0.0031 优良达标；达成自动放行分支入账 COMPLETED_JSU，确立 JSU 胜出冻结格常设规则。 |
| **P6-KORD-18H-GATE-1** | [`evidence/kord_18h_jsu_gate_report.md`](evidence/kord_18h_jsu_gate_report.md) | **工单 P6-KORD-18H-JSU-GATE** | KORD_18h 轻量级 JSU 门禁补验报告：正偏态形态下 J1 普适性核验（gamma=-0.50, delta=2.14, CV<6.3% 零贴界）、J2 20/20 折全胜（中位 ΔBIC=-253.87）、J3 Top-5 均为强暖平流漏报预报集体失效、J4 加权 ECE 0.0029 最优校准；解除脚注正式入账 COMPLETED_JSU；SHA256: `7b00770b8e3964c9a1b5498882e955c7db8a8c72434dc6ffd3d5facfdf276676`。 |
| **P6-KMIA-24H-GATE-1** | [`evidence/kmia_24h_jsu_gate_report.md`](evidence/kmia_24h_jsu_gate_report.md) | **工单 P6-KMIA-24H-GATE** | KMIA_24h 常设 JSU 门禁取证与自动放行裁决报告：J1 参数稳定无贴界（CV<=2.07%）、J2 20 折 JSU 全胜碾压（中位 ΔBIC=-1229.08）、J3 Top-5 均为预报集体失效（卡特里娜飓风等大失准）、J4 加权 ECE 0.0062 达标；达成自动放行分支入账 COMPLETED_JSU，记录双站残差反向时效梯度。 |
| **P6-WIN-FOR-1** | [`evidence/p6_window_forensic_report.md`](evidence/p6_window_forensic_report.md) | **工单 P6-WINDOW-FORENSIC** | 生产评估窗口法医穿透取证报告：确证 2019 盲测年严格物理隔离（Airgap 零泄漏）；解剖 13,739/13,740 实质为 20 折验证块折·日总和（对应 5,859 唯一独立日历日）；出具 1a 双口径判定对照表（如实双录入账，口径 B 字面 19 年<30 年经委员会立法解释判 PASS）并定级良性；SHA256: `7800bf6c8d9ed20b7fc3fd0418e480ea982a42f08a6ce24b7cd3e2fb822ad55c`。 |
| **P6-KMIA-36H-1** | [`evidence/kmia_36h_split_audit_report.md`](evidence/kmia_36h_split_audit_report.md) | **工单 P6-KMIA-36H-SPLIT-AUDIT** | KMIA 36h 混合胜出与门控机制深度审计报告：门槛敏感性与边缘效应解剖（14 折超 0.40 选 JSU，6 折在 0.37~0.39 选 EVT）；分族拼接与可靠性核验（JSU ECE 0.0046，全池 ECE 0.0079 达标）；验证时刻映射与昼夜谐波归因（07:00/08:00 LT 早晨热力中性谷底）；委员会 J2 修订条款（全池 >=60% 事后追认、子集 ECE 越线挂旗但不计入全格计数）正式入册；入账 COMPLETED_HYBRID_SPLIT_SUBSET_FLAGGED 附三层真相注；SHA256: `a9a6d25ba9ae132d96f994deb958ee44305f4cd112a2127a6765cebfb42dfffc`。 |
| **P6-FGD-1** | [`evidence/p6_fullgrid_96cells_summary.json`](evidence/p6_fullgrid_96cells_summary.json) | **工单 P6-2-FULLGRID** | 双城 TMax 全网格 24 时间格（96 季节格）20 折 Block-CV 汇聚总表：覆盖 KORD 与 KMIA 全 12 时效，包含胜出家族、逐格加权 ECE、PIT KS 指标与血统 SHA；SHA256: `a9986fbe041b9157037b7d2f39f8592b3c98328dd52683e90abf4e87e75674f0`。 |
| **P6-FGD-2** | [`evidence/p6_fullgrid_leadtime_decay.json`](evidence/p6_fullgrid_leadtime_decay.json) | **工单 P6-2-FULLGRID** | 双城全网格提前期衰减与指标趋势数据工件：记录随 12h~78h 步进的锋利度衰减、加权 ECE 波动与残差高阶矩演化；SHA256: `a0b31781b2c0542b3aa0224c01acec54e252d8eede07548c6c45ca2ab77b8f13`。 |
| **P6-CLS-1** | [`evidence/p6_tmax_methodology_closure.md`](evidence/p6_tmax_methodology_closure.md) | **工单 P6-METHODOLOGY-CLOSURE** | Phase 6 双城 TMax 全网格验证与方法论封盘法定报告：落地两段式家族选择披露、双城昼夜谐波与正午峰度周期统一物理机制、A1 残差相位分解对照表（4.2 节谐波外推证据）、24 时间格唯一事实层对账表、三层真相注、方法论注记 4（AC-3 衰减缺口与实况硬截断兜底）、已知限制（含池化 6h 谷底过宽实证）与封盘终审法定结论；SHA256: `b813f1c914b3f9c90c6e4a031ff0c6465cbdbb1c278bdd3699686e0a9ca15f2c`。 |
| **P6-CLS-2** | [`evidence/p6_tmax_methodology_closure.json`](evidence/p6_tmax_methodology_closure.json) | **工单 P6-METHODOLOGY-CLOSURE** | 方法论封盘结构化数据工件：记录全网格 24 格胜出模型族、加权 ECE、PIT KS 指标、已知限制、池化 6h 审计指标与封盘后 Backlog 议题清单；SHA256: `a970181c4239875f6015b252d7ea1cbe5bd74e779bf40596a82424548f74d315`。 |
| **P6-POOL6H-1** | [`evidence/p6_pool6h_audit_report.md`](evidence/p6_pool6h_audit_report.md) | **工单 P6-POOL6H-AUDIT** | 池化 6 小时回退层四项审计质检报告：完成 A1 相位分解（谷底方差膨胀比 1.45~1.81x）、A2 6h 样本外校准（KORD ECE=0.005128 达标，KMIA ECE=0.019657 越线）、A3 衰减锚点核验（Max Temp 缺失开方衰减依靠 METAR 实况硬截断层兜底）、A4 回退交接连续性；触发分支一入账 FLAGGED_POOL_PHASE_ISSUE；记录红线应停未停程序违规并补办 A3 停机呈报形式要件；SHA256: `3998315f764ed050737f18a1c4b34c5a203dab43c7008a99ef91fbcc99bba1cd`。 |
| **P6-POOL6H-2** | [`evidence/p6_pool6h_audit_results.json`](evidence/p6_pool6h_audit_results.json) | **工单 P6-POOL6H-AUDIT** | 池化 6 小时回退层四项审计结构化数据工件：记录双站 A1 矩统计与方差比、A2 加权 ECE、A3 衰减代码剖析与 A4 参数台阶；SHA256: `385430a9d1ee2a0d72dda0782d26dcdf34febed6316fb70d36869ed851a164e7`。 |
| **P7-SYNC-1** | [`evidence/p7_sync_bridge_audit.md`](evidence/p7_sync_bridge_audit.md)<br>[`docs/SYNC_POLICY.md`](docs/SYNC_POLICY.md) | **工单 P7-SYNC-BRIDGE**<br>*(别名备注：原 P7-SYNC-AUDIT-1)* | 受控出域通道建设、三方一致性核验与同步政策入册：172 采样文件 100% 一致 (0 mismatch)，Git 总体积 52.50 MiB，最大 blob 7.36 MiB；确立 Git LFS 分层与“未验收不出域、验收必出域”政策，主干 PR #128 关门合流。 |



