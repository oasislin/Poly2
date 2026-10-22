# P8-CLASS1-LAUNCH・Ticket 01 交付与双轴 Code Review 验收汇报

- **报告编号**：`P8-CLASS1-LAUNCH-TICKET01-REPORT`
- **日期**：2026-10-22
- **父工单（B 线）**：`P8-CLASS1-LAUNCH`
- **Spec 主工单**：`Spec: Phase 2 Task 08 - 第一类投注定价算法与只读纸面盘落地` ([#133](https://github.com/oasislin/Poly2/issues/133))
- **切片 Ticket**：`Phase 2 Task 08 - Ticket 01: feat(contract): 定义物理模型参数消费契约数据模型与格级配置 Schema` ([#134](https://github.com/oasislin/Poly2/issues/134))
- **交付代码**：
  - [`src/contract/parameter_contract.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/parameter_contract.py)
  - [`src/contract/__init__.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/__init__.py)
  - [`tests/unit/contract/test_parameter_contract.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/contract/test_parameter_contract.py)
- **执行环境**：macOS (Darwin) / Python 3.13.5 / pytest 8.3.4
- **判定纪律**：两步分离原则（原始观测值 vs 判定阈值机械比对，无主观判断）。

---

## 一、 交付目标与架构对账

依据《ADR-0019：物理模型参数向投注算法消费契约与解耦架构》与 GitHub Issue [#134](https://github.com/oasislin/Poly2/issues/134)，Ticket 01 承担上游物理模型参数向交易配资层注入的核心契约定义：

1. **时空网格结构契约**：严格按 2 站（KORD/KMIA）× 11 提前期（12h~72h）= 22 格字典组织，防范全局均值化；
2. **全量参数消费矩阵对账**：
   - 必须消费字段：`s_oos`、`fstd_lo`、`fstd_hi`、`fstd_in`、`ece_2f`、`v1_coverage_90`、`v1_coverage_90_pass`、`pit_mean`、`pit_var`、`reject_uniform`；
   - 间接消费/审计字段：`neff`、`cvm_stat`、`cvm_p`、`ece_range`；
   - 动态在线预测模型：`mu_calib`、`sig_eff`、`distribution_family`、离散概率向量 `p_j`（全链路 Decimal）；
3. **版本看门狗锚点契约**：内嵌合约版本 `contract_version`、模型权重哈希映射 `model_weights_sha256` 与清单哈希 `manifest_sha256`。

---

## 二、 双轴 Code Review 审查与问题识别

初版实现（commit `2a3af76`）经 Standards Reviewer 与 Spec Reviewer 双轴审查，发现以下规范与契约缺陷：

1. **【硬性规范违规】数据模型中预设了合成默认值**：
   - `CellCalibrationRecord` 中为 `s_oos`、`fstd_lo`、`ece_2f` 等字段设置了理想缺省值（如 `= 1.0`、`= 0.8`、`= 0.01`）；
   - **违规性质**：严重违背《AGENTS.md》“严禁脱离客观工程现实与数据资产凭空捏造前置条件”及“原始观测结果不可篡改”铁律。标定记录必须完全由客观盲测数据显式填充，绝不能有默认及格假象。
2. **【代码坏味道】反序列化静默回退**：
   - `from_dict()` 采用 `data.get("neff", 300.0)` 等缺省回退，掩盖数据源不完整；遍历时丢弃了外层键，未校验外层键与内层记录一致性。
3. **【契约遗漏】**：
   - 遗漏了动态在线预测输出 Schema（`PhysicalForecastOutput`）与模型权重二进制哈希字段。
4. **【用户明确裁决与红线指示】**：
   > **用户裁定**：“不能有任何门限类的硬编码常量，请检查。如果有需要赋值的缺失，那么这是设计方案的问题，反推问题回到评审会员会。”

---

## 三、 零硬编码彻底重构要点

针对上述问题，开发端于 commit `e9b9f87` 执行彻底重构：

1. **零默认值（Zero Defaults）**：
   - `CellCalibrationRecord` 与 `PhysicalForecastOutput` 移除所有默认赋值，全部改为纯类型声明；未显式传参时直接引发 `TypeError`。
2. **零容错回退与 Fail-Closed**：
   - `from_dict()` 彻底移除所有 `.get(..., default)`，全部采用直接索引 `data["..."]`；缺少任何法定字段直接抛出 `KeyError` 阻断，将数据缺失暴露于启动期。
3. **零门限判定（Zero Threshold Decisions in Contract）**：
   - 契约层明确只作为强类型容器与 Schema，**严禁包含任何业务或统计门限数值比较逻辑**；
   - 历史门限布尔值（如 `fstd_in`, `v1_coverage_90_pass`）纯系上游盲测脚本离线审计记录的客观事实列，契约层仅原样搬运；
   - 所有交易端的评分权重、软折减曲线参数、稳健凯利 $\theta/\eta$ 严格受 `[F-2 LOCKED]` 保护，不在契约层硬编码。
4. **外层键与内层标识一致性强校验**：
   - 反序列化时核验外层字典键（如 `KORD_12h`）是否与内层 `record.station` / `record.lead_hours` 严格一致，防止格位错配。

---

## 四、 自动化测试执行证据与两步分离判定

### 1. Ticket 01 专属契约单元测试（含 Fail-Closed 防护测试）

- **执行命令**：`python -m pytest tests/unit/contract/test_parameter_contract.py -v`
- **控制台输出片段**：
```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.3.4, pluggy-1.5.0 -- /opt/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collected 12 items                                                             

tests/unit/contract/test_parameter_contract.py::test_cell_calibration_record_creation_and_frozen PASSED [  8%]
tests/unit/contract/test_parameter_contract.py::test_cell_calibration_record_no_defaults_fail_closed PASSED [ 16%]
tests/unit/contract/test_parameter_contract.py::test_cell_calibration_record_dict_roundtrip PASSED [ 25%]
tests/unit/contract/test_parameter_contract.py::test_cell_calibration_record_from_dict_missing_field_raises_key_error PASSED [ 33%]
tests/unit/contract/test_parameter_contract.py::test_physical_forecast_output_creation_and_roundtrip PASSED [ 41%]
tests/unit/contract/test_parameter_contract.py::test_physical_param_contract_get_cell_success PASSED [ 50%]
tests/unit/contract/test_parameter_contract.py::test_physical_param_contract_get_cell_missing_raises_key_error PASSED [ 58%]
tests/unit/contract/test_parameter_contract.py::test_physical_param_contract_validation_success PASSED [ 66%]
tests/unit/contract/test_parameter_contract.py::test_physical_param_contract_validation_missing_cell_raises PASSED [ 75%]
tests/unit/contract/test_parameter_contract.py::test_physical_param_contract_no_global_averaging_defense PASSED [ 83%]
tests/unit/contract/test_parameter_contract.py::test_physical_param_contract_dict_roundtrip PASSED [ 91%]
tests/unit/contract/test_parameter_contract.py::test_physical_param_contract_key_mismatch_raises_value_error PASSED [100%]

============================== 12 passed in 0.02s ==============================
```
- **机械判定**：
  `原始观测值 = 12 passed in 0.02s, exit code 0；判定阈值 = 12 passed, exit code 0；结论 = 通过`

### 2. 现役全量交易与契约模块回归测试（prediction + risk + contract）

- **执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q`
- **控制台输出片段**：
```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.3.4, pluggy-1.5.0
rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collecting 4 items                                                             collected 125 items                                                            

tests/unit/prediction/test_bin_converter.py ..........                   [  8%]
tests/unit/prediction/test_constraint_enforcer.py ............           [ 17%]
tests/unit/prediction/test_discrete_bin_engine.py .....                  [ 21%]
tests/unit/prediction/test_discrete_bin_engine_2deg.py ......            [ 26%]
tests/unit/prediction/test_dynamic_corrector.py ............             [ 36%]
tests/unit/prediction/test_monotonic_confluence.py ...                   [ 38%]
tests/unit/prediction/test_prediction_pipeline.py .....                  [ 42%]
tests/unit/prediction/test_scenario_d.py ...                             [ 44%]
tests/unit/prediction/test_static_predictor.py ........                  [ 51%]
tests/unit/prediction/test_temperature_sanitizer.py .......              [ 56%]
tests/unit/prediction/test_truncated_probability_engine.py ....          [ 60%]
tests/unit/prediction/test_w2_confluence_exemptions.py .....             [ 64%]
tests/unit/prediction/test_w2_gate_c3_sampling.py ...................... [ 81%]
.......                                                                  [ 87%]
tests/unit/risk/test_stream_watchdog.py ....                             [ 90%]
tests/unit/contract/test_parameter_contract.py ............              [100%]

============================= 125 passed in 1.34s ==============================
```
- **机械判定**：
  `原始观测值 = 125 passed in 1.34s, exit code 0；判定阈值 = 125 passed, exit code 0；结论 = 通过`

### 3. GEFS 真实网络测试豁免说明
- **豁免理由**：Ticket 01 为纯离线强类型数据契约与 Schema 定义，未修改亦不调用任何外部 GEFS 联网与下载流水线。

---

## 五、 Git 提交与同步状态

- **相关提交链**：
  1. `2a3af76`: `feat(contract): 完成 Ticket 01 物理参数消费契约数据模型与格级配置 Schema (#134)`
  2. `e9b9f87`: `refactor(contract): 清除门限硬编码与默认值，落实零硬编码强校验与动态模型 Schema (#134)`
  3. `[本报告 commit]`: `docs(audit): 交付 Ticket 01 物理参数契约实现与双轴 Code Review 汇报文件 (#134)`
- **远端同步**：依用户明确指令执行 `git push origin main`。

---

## 六、 结论与后续工作

Ticket 01 验收结论：**完全达标，已完成代码实现、双轴 Code Review 整改、零硬编码防御与自动化测试验证。**

后续依赖解锁：
- **Ticket 02** ([#135](https://github.com/oasislin/Poly2/issues/135))：`feat(contract): 实现物理模型与 manifest SHA256 版本戳强校验看门狗` (已解除 Blocked)
- **Ticket 03** ([#136](https://github.com/oasislin/Poly2/issues/136))：`feat(contract): 实现从 V2 盲测 CSV 自动导出 22 格静态参数表的转换器与校验器` (已解除 Blocked)
- **Ticket 06** ([#139](https://github.com/oasislin/Poly2/issues/139))：`feat(pricing): 实现 Q7 覆盖率双轨分工与 exact / gaussian_proxy 计算解耦` (已解除 Blocked)
