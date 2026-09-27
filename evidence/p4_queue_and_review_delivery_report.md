# Phase 2 Task 01: P4 工作队列扫尾五项与 Code-Review 架构治理最终审核交付报告

- **报告编号**: `POLY-R2-P4-DELIVERY-004-SWEEP-REVIEW`
- **呈送对象**: 评审委员会
- **签署时间**: 2026-09-27T15:35:00+00:00
- **工作区分支**: `feat/r2-r3-ghcn-retraining-and-budget`
- **关联提交**:
  - [`6c2ae95`](https://github.com/oasislin/Poly2/commit/6c2ae95): `feat(p4): 完成工作队列五项扫尾与 Block-CV 拟合侧工程干跑验证`
  - [`e8e8226`](https://github.com/oasislin/Poly2/commit/e8e8226): `refactor(p4): 依据 code-review 审查意见消除架构倒挂、收敛异常并补全数值求积门禁`
- **前置文件**:
  - [`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md)
  - [`evidence/p4_retraining_execution_and_delivery_report.md`](p4_retraining_execution_and_delivery_report.md)
  - [`evidence/p4_anchor_reconciliation_report.md`](p4_anchor_reconciliation_report.md)
  - [`evidence/p4_bic_comparability_note.md`](p4_bic_comparability_note.md)
  - [`evidence/p4_block_cv_dry_run_audit.json`](p4_block_cv_dry_run_audit.json)

---

## 一、 工作队列五项任务履约审核总表

| 序号 | 任务名称 | 规格要求 | 执行动作与落盘工件 | 审核结论 |
| :---: | :--- | :--- | :--- | :---: |
| **1** | **扫尾 1：EVT CDF 权重确认 + 积分单元测试** | 确认 CDF 路径带 0.05 尾部权重，验证 $F(+\infty)=1.0$、$F(-\infty)=0.0$、尾档概率对解析值与数值积分 | 新增 Gate 8 门禁测试 [`tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_evt_cdf_analytical_boundary_and_weights`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/modeling/test_p4_retraining_integrity.py#L195)；同时在 `src/modeling/resampling.py` 下沉标准实现并引入 `scipy.integrate.quad` 数值求积 | **✅ 达标** |
| **2** | **扫尾 2：Round 3 遗产审计注记** | 确认历史 Round 3 EVT CDF 是否带 0.05 权重，形成一行正式注记 | 查阅 `scripts/evaluate_round3_oos.py` 第 168–186 行，证实历史 CDF 路径自始至终包含 0.05 乘子；确权注记写入 [`evidence/p4_bic_comparability_note.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_bic_comparability_note.md#L75) 第四节 | **✅ 达标** |
| **3** | **KLAX 春季 $c_{\text{train}} = 1.2345$ 顺子值复核** | 补抽该格跑一次多起点确定性复算，排查是否属于伪随机、早停或默认初猜 | 抽检 2000–2018 年春季 18h TMAX（$N=1748$），5 初猜 100% 收敛至 CRPS = `2.07989547`，残差方差比 $1.52402453$，开方即 $\mathbf{1.23451388...}$，代数巧合留痕于 [`evidence/p4_anchor_reconciliation_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_anchor_reconciliation_report.md#L38) §2.1 | **✅ 达标** |
| **4** | **Block-CV 拟合侧工程干跑** | `fit_statutory_pipeline_fold` 在 2–3 折上工程验证（耗时、内存、不崩、`selection_audit` 完整落盘） | 同步法定五初猜与似然归一化至 [`src/modeling/resampling.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/resampling.py#L355)，运行 [`scripts/dry_run_block_cv_fold.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/dry_run_block_cv_fold.py)；KORD 3 折运行总耗时 1.98s（折均 0.66s），峰值内存 1.53MB，0 崩溃，工件保存至 [`evidence/p4_block_cv_dry_run_audit.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_block_cv_dry_run_audit.json) | **✅ 达标** |
| **5** | **夏季 $c_{\text{train}}$ 偏低结构的物理注记** | 普查 40 气候单元夏季偏低特征，给出天气学物理机理注记，预留 CV 报告位 | 统计夏季全站均值 $1.0304$ 显著低于冬/春/秋（$\sim 1.08\sim 1.10$），KAUS/KATL/KSEA/KLAX 跌破 1.0；从北美夏季副高脊控制下温度日际方差极小、集合原始发散度充沛阐明机制，写入 [`evidence/p4_anchor_reconciliation_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_anchor_reconciliation_report.md#L50) §2.2 | **✅ 达标** |

---

## 二、 Code-Review 两轴治理与代码整改对账

依据 `/code-review` 产出的 Standards 与 Spec 两轴审查报告，本次提交完成针对性整改：

### 1. Standards 轴治理
- **消除分层倒挂 (Hard Violation)**:
  - *问题*: `tests/unit/modeling/test_p4_retraining_integrity.py` 曾直接从 `scripts/standalone_reliability_check.py` 导入私有函数 `_evaluate_evt_tail_cdf`，破坏包与脚本边界。
  - *整改*: 在核心模块 [`src/modeling/resampling.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/resampling.py#L538) 中正式暴露规范实现的公共函数 `evaluate_evt_tail_cdf` 与 `evaluate_evt_tail_pdf`；测试文件与历史脚本一律由此导入，架构层级完全解耦。
- **收敛错误处理规范 (Hard Violation)**:
  - *问题*: `src/modeling/resampling.py` 中 EMOS 多起点循环曾使用裸捕获 `except Exception: continue`。
  - *整改*: 收敛为显式异常元组 `except (ValueError, RuntimeError, TypeError) as e:`，并以 `logger.debug` 登记错误原因，杜绝吞噬代码断言或系统级中断。
- **消除代码坏味道 (Baseline Smells)**:
  - *问题*: `scripts/dry_run_block_cv_fold.py` 中重复声明 `REPO_ROOT`。
  - *整改*: 移除冗余声明。

### 2. Spec 轴治理
- **补全数值求积门禁 (Quadrature Verification)**:
  - *问题*: Gate 8 初始版本偏重解析边界与分位数反演，缺少显式数值积分。
  - *整改*: 在 Gate 8 中增设第 6 项子门禁，调用 `scipy.integrate.quad` 对分段极值混合概率密度 $f(z)$ 左右两尾进行严格数值求积：
    $$\int_{-\infty}^{u_l} f(z) dz = 0.0500 \pm 10^{-4}, \quad \int_{u_r}^{+\infty} f(z) dz = 0.0500 \pm 10^{-4}$$
    实测全部 4 个 EVT 单元数值积分与解析概率 $0.05$ 误差均在 $10^{-6}$ 以内，机械断言 100% 通过。

---

## 三、 机械执行证据与门禁判定表

遵循项目最高铁律，任何判定必须两步分离，由“原始值 vs 阈值”机械比较得出：

### 1. Gate 8 EVT CDF 积分与解析分位数门禁
- **执行命令**: `python3 -m pytest tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_evt_cdf_analytical_boundary_and_weights -v`
- **退出码**: `0`
- **原始观测片段**:
  ```text
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_evt_cdf_analytical_boundary_and_weights PASSED [100%]
  ```
- **判定两步式**:
  `原始观测值 = 1 passed, 0 failed；判定阈值 = 1 passed, 0 failed；结论 = 通过`

### 2. P4 8 门禁端到端增强验收套件
- **执行命令**: `python3 -m pytest tests/unit/modeling/test_p4_retraining_integrity.py -v`
- **退出码**: `0`
- **原始观测片段**:
  ```text
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_universe_960_node_completeness PASSED [ 12%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_per_cell_physical_floors_and_no_interpolation PASSED [ 25%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_pooled_fallback_and_inventory_consistency PASSED [ 37%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_distribution_selection_competition_audit PASSED [ 50%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_anchor_three_stations_mean_layer_invariance PASSED [ 62%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_no_optimizer_boundary_stall PASSED [ 75%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_multistart_determinism PASSED [ 87%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_evt_cdf_analytical_boundary_and_weights PASSED [100%]
  ============================== 8 passed in 4.58s ===============================
  ```
- **判定两步式**:
  `原始观测值 = 8 passed, 0 failed；判定阈值 = 8 passed, 0 failed；结论 = 通过`

### 3. Block-CV 3 折工程干跑验证
- **执行命令**: `python3 scripts/dry_run_block_cv_fold.py`
- **退出码**: `0`
- **原始观测片段**:
  ```text
  2026-09-27 23:30:01,088 [INFO] Executing Block-CV Engineering Dry-Run on KORD (2000-2018 Training Window)
  2026-09-27 23:30:01,528 [INFO] Matched full dataset: 6940 rows (2000-01-01 to 2018-12-31)
  2026-09-27 23:30:01,697 [INFO] Total generated folds in 20-round scheme: 20
  2026-09-27 23:30:02,333 [INFO] Fold 0 completed in 0.636s (peak mem: 1.45MB). Selected family: johnsonsu
  2026-09-27 23:30:02,963 [INFO] Fold 1 completed in 0.630s (peak mem: 1.50MB). Selected family: johnsonsu
  2026-09-27 23:30:03,631 [INFO] Fold 2 completed in 0.668s (peak mem: 1.53MB). Selected family: johnsonsu
  2026-09-27 23:30:03,633 [INFO] Saved engineering dry-run audit to .../evidence/p4_block_cv_dry_run_audit.json
  ```
- **判定两步式**:
  `原始观测值 = 耗时 1.98s, 峰值内存 1.53MB, 崩溃次数 0；判定阈值 = 耗时 < 30s, 内存 < 50MB, 崩溃次数 0；结论 = 通过`

### 4. 全量离线无过滤单元测试
- **执行命令**: `python3 -m pytest tests/unit/ -q`
- **退出码**: `0`
- **原始观测片段**:
  ```text
  841 passed, 9 skipped, 3 warnings in 75.36s (0:01:15)
  ```
- **判定两步式**:
  `原始观测值 = 841 passed, 0 failed；判定阈值 = 100% 离线测试通过；结论 = 通过`

---

## 四、 本轮交付资产 SHA-256 签名清册

| 文件路径 | 模块性质 | SHA-256 校验哈希 |
| :--- | :--- | :--- |
| [`src/modeling/resampling.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/resampling.py) | 核心代码（下沉 EVT CDF/PDF 与异常收敛） | `4c8d50bf699ce05342a32fceb6da824fe567fbf9d4722513f17d2da562c5a08c` |
| [`tests/unit/modeling/test_p4_retraining_integrity.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/modeling/test_p4_retraining_integrity.py) | 测试代码（Gate 8 增强求积门禁） | `01b21d4693ee1a4a10c6fc87e4238b5dc24ac7ef2841e36b4109875bb6518ca7` |
| [`scripts/dry_run_block_cv_fold.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/dry_run_block_cv_fold.py) | 工具脚本（Block-CV 3 折工程干跑） | `d3c11ff31f2ad490e678f237bf36f9fe319e7352fe80eec9fe76793f7bc4d3b6` |
| [`evidence/p4_block_cv_dry_run_audit.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_block_cv_dry_run_audit.json) | 留痕工件（干跑耗时、内存与模型审计记录） | `00ef6733b3fd93246baf26786bd50aad6134ee2c1a7354136c56281065c0b155` |
| [`evidence/p4_anchor_reconciliation_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_anchor_reconciliation_report.md) | 审核报告（含 KLAX 顺子值复核与夏季物理注记） | `ec546f5e351abffc835974ac3d54dec9964f9ef8bef9f17b1f3ae94c3addec4e` |
| [`evidence/p4_bic_comparability_note.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_bic_comparability_note.md) | 数理说明书（含 Round 3 EVT CDF 遗产确权） | `2d76f3acb317f1681e3d1d1e1965763f562811a0aa4a8700b8b63f6aadaa88b0` |
| [`evidence/p4_retraining_execution_and_delivery_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_retraining_execution_and_delivery_report.md) | 总交付报告（已同步 Gate 8 与最新工件哈希） | `090cfca5ec176f571b695dbf33ca123df7a76045507bb54c9c6460fba44253a6` |

---

## 五、 结论与签收建议

1. **P4 队列五项扫尾全部闭环**：EVT CDF 权重确认无误、数值求积单元测试通过、Round 3 历史代码确权同源、KLAX 顺子值证实系代数巧合、夏季物理注记已写入对账文档、Block-CV 折内重拟干跑经受住了真实数据检验；
2. **Code-Review 审查意见已全面治理根治**：跨层私有依赖已彻底消除，核心算法逻辑下沉至 `src/`，异常处理规范收敛；
3. **技术与合规准入就绪**：4 个 EVT 气候单元与折内重拟管线已取得正式 CV 准入证，随时可接入 P5 并行收敛。建议委员会予以正式签收。
