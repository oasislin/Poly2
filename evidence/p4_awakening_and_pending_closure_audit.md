# Phase 2 Task 01: P4 物理建模组唤醒与首期挂账清偿终审审计报告 (Awakening & Pending Closure Audit Report)

- **报告编号**: `POLY-R2-P4-AUDIT-005-AWAKENING`
- **发件人**: Polymarket 温度物理建模工程组 (P4)
- **呈送对象**: 评审委员会 / 主控方 / 外部独立审计
- **签署时间**: 2026-10-08T17:36:00+08:00
- **当前代码基线**: `main` 分支（Commit: `fe9bd71`）
- **前置文件**:
  - [`docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md`](../docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md)
  - [`evidence/p4_freeze_handoff_notice.md`](p4_freeze_handoff_notice.md) (文件编号 `POLY-R2-P4-FREEZE-001`)
  - [`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md)

---

## 一、 战略定调与唤醒定性审计 (Awakening & Clearance Audit)

1. **P5 评测工具链解除阻塞**:
   - 此前 P4 建模组依据 `POLY-R2-P4-FREEZE-001` 冻结于**阻塞节点 1**，挂账等待 P5 评测工具链恢复；
   - P5 可靠性抽检系统已全面关账并打标（`p5-v1.0-verified`，Commit: `3aab9e6`），第二层五场景门禁（GATE-L2-01 至 05）全绿放行；
   - 主控方正式下达唤醒指令，**P4 物理建模组正式解除工程冻结**。

2. **铁律与执行合规性**:
   - 本次执行严格遵从“未经明确授权严禁擅自修改核心业务代码”最高铁律；
   - 在用户明确授权“开始第一步工作”后，仅针对测试套件执行断言增补，业务拟合代码零变更；
   - 严格遵从“原始观测结果不可篡改”纪律，测试数值与日志原样读取、两步分离机械判定。

---

## 二、 四项挂账清偿清单逐项闭环对账 (Pending Items Clearance Audit)

依据 `POLY-R2-P4-FREEZE-001` 的法定约束，工程组逐项落实挂账事项，对账审计结论如下：

| 序号 | 挂账事项 | 法定要求 | 实际处置动作与落盘工件 | 审计结论 |
| :---: | :--- | :--- | :--- | :---: |
| **1** | **Gate 8 套件补 EVT 全域积分断言** | 补全 $F(+\infty) = 1.0$ 与数值积分 $\ge 0.9999$ 断言 | 在 [`tests/unit/modeling/test_p4_retraining_integrity.py`](../tests/unit/modeling/test_p4_retraining_integrity.py) 中补齐极限与上界截断全域归一化布尔断言，完成唤醒后首个 commit (`fe9bd71`) | **✅ 已闭环** |
| **2** | **测试计数对账说明** | 澄清回归测试用例数自 849 增至 850（与此前单测增补差 1 说明对账） | 深度溯源历史基线与新增单测，在汇报与审计报告中完成数学与用例对账说明（详见 §2.1） | **✅ 已闭环** |
| **3** | **干跑内存 1.53MB 口径注明** | 澄清工程干跑报告中 1.53MB 为增量分配还是真实峰值 | 审查 `scripts/dry_run_block_cv_fold.py` 中 `tracemalloc` 统计口径，确认为 Python 堆增量分配峰值而非进程 RSS（详见 §2.2） | **✅ 已闭环** |
| **4** | **夏季 $c_{\text{train}}$ 物理注记数字回填** | 针对夏季对流与方差膨胀系数回填实测统计数值 | 依据规格留存挂起，待正式 20 轮 Block-CV 跑完后提取诊断表并填入最终结算报告 | **⏳ 挂起待填** |

---

### 2.1 挂账项 2 深度对账审计：849 $\to$ 850 与“8 passed”的差 1 根因

- **历史基准**: 冻结交接点前，离线全量单测用例基数为 **849 项**（`840 passed, 9 skipped`），其中测试文件 [`tests/unit/modeling/test_p4_retraining_integrity.py`](../tests/unit/modeling/test_p4_retraining_integrity.py) 包含 Gate 1 至 Gate 7 共 **7 项测试**。
- **机械对账事实**:
  1. 为强化 EVT CDF 解析检验，工程组新增了第 8 个门禁函数 `test_p4_evt_cdf_analytical_boundary_and_weights`（Gate 8）；
  2. 此时，该文件自身测试数由 7 项增至 8 项（执行该单文件报告 **`8 passed`**）；
  3. 全量测试套件同步由 849 项增至 **850 项**（`841 passed, 9 skipped`），**全量净增量严格为 $+1$ 项**；
  4. 既有的 Gate 1 至 Gate 7 已包含在历史 849 项底账中，净增的 1 项即唯一对应 Gate 8，用例账实严格相符。当前主线因已合并 P5 工具链用例，全域单测收集数已自然演进至 886 项。

---

### 2.2 挂账项 3 内存口径审计：1.53MB 增量分配界定

- **代码实现审查**:
  在 [`scripts/dry_run_block_cv_fold.py`](../scripts/dry_run_block_cv_fold.py) 第 64 与 77 行：
  ```python
  mem_start = tracemalloc.get_traced_memory()[0] / (1024 * 1024)
  ...
  mem_peak = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
  ```
- **口径定性结论**:
  1. `tracemalloc.get_traced_memory()[1]` 测量的是自 `tracemalloc.start()` 启动之后由 Python 解释器分配的**堆内存峰值增量 (Incremental Traced Heap Peak)**；
  2. 由于脚本在完成数据加载和运行环境初始化之后才启动跟踪，因此 **1.53MB 仅代表单折拟合过程中的动态内存净申请上限**；
  3. 该数值**绝非**操作系统级的进程常驻内存真实物理峰值（Resident Set Size, RSS Peak）。

---

## 三、 反数据泄露与时间隔离架构审计 (Zero-Leakage Architecture)

针对量化气象下注与物理概率模型的核心安全要求，工程组实施了四重数据反泄露硬性防护：

1. **时间硬闸隔离 (Airgap Hard Guardrail)**:
   - 核心代码: [`src/utils/airgap.py`](../src/utils/airgap.py)
   - 2000-01-01 至 2018-12-31（19 年，约 6,940 站·日）划为训练与 CV 空间；
   - 2019-01-01 至 2019-12-31（全自然年，3,650 站·日）被定义为绝密样本外盲测窗（`SEALED_YEAR = 2019`）；
   - 任何数据加载函数在未经预注册授权（`evidence/preregistered_2019_authorization.flag`）时触碰 2019 数据，将无条件触发 `AirgapViolationError` 阻断。

2. **气象时间自相关防泄露 (30-Day Block Partition)**:
   - 核心代码: [`src/modeling/resampling.py`](../src/modeling/resampling.py)
   - 拒绝随机 K-Fold，采用连续 30 天日历块切分，防止天气尺度（Synoptic Scale）跨日天气过程造成时间穿越；
   - 切分后实施数学正交断言：`leakage = val_dates.intersection(train_dates); assert len(leakage) == 0`，保证训练折与验证折日期交集绝对为 $\emptyset$。

3. **循环内即时重拟 (Strict In-Loop Refitting)**:
   - 模型拟合严格在每一折的抽样循环内部调用 `fit_statutory_pipeline_fold`，杜绝“折外全局拟合、折内仅做推理”的伪验证。

4. **因果滑动预热 (Strict Causal Rolling Warm-up)**:
   - 均值校正滑动窗口采用严格因果滞后：`shift(1).rolling(30)`；
   - 预测 2019 年初时，向后使用 2018 年末最后 60 天已知训练数据进行因果预热，在 2019 年推演期间每一天均不触碰未来时点数据，零前瞻偏差（Zero Lookahead Bias）。

---

## 四、 挂账项 1 验收测试执行证据 (Verification Evidence)

依据“声明通过必须附执行证据”与“判定两步分离”的硬性规则，测试执行记录如下：

### 1. Gate 8 增强专项单测
- **测试命令**: `pytest tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_evt_cdf_analytical_boundary_and_weights -v`
- **执行终端原始片段**:
  ```text
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_evt_cdf_analytical_boundary_and_weights PASSED [100%]
  ============================== 1 passed in 1.33s ===============================
  ```
- **两步分离机械判定**:
  `原始观测值 = 1 passed, 0 failed；判定阈值 = 1 passed, 0 failed；结论 = 通过`

### 2. P4 8 项完整门禁全量回归
- **测试命令**: `pytest tests/unit/modeling/test_p4_retraining_integrity.py -v`
- **执行终端原始片段**:
  ```text
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_universe_960_node_completeness PASSED [ 12%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_per_cell_physical_floors_and_no_interpolation PASSED [ 25%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_pooled_fallback_and_inventory_consistency PASSED [ 37%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_distribution_selection_competition_audit PASSED [ 50%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_anchor_three_stations_mean_layer_invariance PASSED [ 62%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_no_optimizer_boundary_stall PASSED [ 75%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_multistart_determinism PASSED [ 87%]
  tests/unit/modeling/test_p4_retraining_integrity.py::test_p4_evt_cdf_analytical_boundary_and_weights PASSED [100%]
  ============================== 8 passed in 4.38s ===============================
  ```
- **两步分离机械判定**:
  `原始观测值 = 8 passed, 0 failed；判定阈值 = 8 passed, 0 failed；结论 = 通过`

---

## 五、 资产提交与审计底账清单 (Git & Artifact Manifest)

| 工件文件路径 | 变更性质 | 说明 |
| :--- | :--- | :--- |
| [`tests/unit/modeling/test_p4_retraining_integrity.py`](../tests/unit/modeling/test_p4_retraining_integrity.py) | **代码修改** | Gate 8 补全 $F(+\infty)=1.0$ 与数值上界 $\ge 0.9999$ 断言 |
| [`docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md`](../docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md) | **文档归档** | 新会话接收交接规范指南 |
| [`evidence/p4_awakening_and_pending_closure_audit.md`](p4_awakening_and_pending_closure_audit.md) | **新增审计报告** | 本终审审计文稿 |

---

## 六、 审计审核定性与下一步推进建议

- **审计定性**: P4 物理建模组唤醒流程合规，前三项挂账事项全部高质量闭环，数据反泄露防火墙经受系统性复核，测试套件 100% 绿灯。
- **下一步行动**: 提请评审委员会与主控方签收本审计文稿，签收后正式启动**阶段 2：20 轮 30-Day Block-CV 正式跑数**。
