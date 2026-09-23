# EVIDENCE_INDEX.md

本文件为《解阻断证据提交指令单 · 最终版》及《第二轮修复令 (R-1 ~ R-5)》之法定索引清单。每行一句话说明：编号 → 文件 / Raw 直链 → 对应阻断条款与解决说明。

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

### 三、第二轮修复令交付工件清单 (Round 2 Remediation R-1 ~ R-5)

| 编号 | 工件名称与 Raw 直链 | 修复令条款 | 核心内容摘要 |
| :--- | :--- | :--- | :--- |
| **R-1** | [`r1_unit_and_rounding_audit.txt`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/r1_unit_and_rounding_audit.txt) | **修复令 R-1** | 预报与真值单位/舍入约定一致性核查，浮点残差 $1.42\times 10^{-14}$，排除常数错位，定性系统性气象物理冷偏差。 |
| **R-3A** | [`ADR-0015.md`](https://raw.githubusercontent.com/oasislin/Poly2/main/docs/adr/ADR-0015.md) | **修复令 R-3** | 架构决策增补 §3：方差地板历史脉络、Dawid 弱无偏方差重标机制与 KSFO 夏/冬 $d=0.0$ 逆温微气象物理成因。 |
| **R-4** | [`r4_ece_definition_audit.md`](https://raw.githubusercontent.com/oasislin/Poly2/main/evidence/r4_ece_definition_audit.md) | **修复令 R-4** | 加权 ECE 度量定义审计与统计功效分析报告，留痕 20 分桶微观机理，法定硬门禁 $\le 3.0\%$ 坚守不变。 |
| **R-2/5** | [`scripts/audit_provenance_and_recompute.py`](https://raw.githubusercontent.com/oasislin/Poly2/main/scripts/audit_provenance_and_recompute.py) | **修复令 R-2 & R-5** | 实现严格因果 40 天滚动残差偏置校正与方差膨胀重标流水线，通过十分位分层闭包断言与双实现交叉验证。 |
