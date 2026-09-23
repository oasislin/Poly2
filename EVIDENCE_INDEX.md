# EVIDENCE_INDEX.md

本文件为《解阻断证据提交指令单 · 最终版》第二批提交之法定索引清单。每行一句话说明：编号 → 文件 / Raw 直链 → 对应阻断条款与解决说明。

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
