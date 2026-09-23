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
