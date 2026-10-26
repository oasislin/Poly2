# P8-CLASS1-LAUNCH · Ticket 02 交付与双轴 Code Review 验收汇报

- **报告编号**：`P8-CLASS1-LAUNCH-TICKET02-REPORT`
- **日期**：2026-10-26
- **父工单（B 线）**：`P8-CLASS1-LAUNCH`
- **Spec 主工单**：`Spec: Phase 2 Task 08 - 第一类投注定价算法与只读纸面盘落地` ([#133](https://github.com/oasislin/Poly2/issues/133))
- **切片 Ticket**：`Phase 2 Task 08 - Ticket 02: feat(contract): 实现 manifest SHA256 版本戳强校验看门狗` ([#135](https://github.com/oasislin/Poly2/issues/135))
- **交付代码**：
  - [`src/contract/version_watchdog.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py)（核心看门狗实现）
  - [`src/contract/__init__.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/__init__.py)（纯加法符号导出）
  - [`tests/unit/contract/test_version_watchdog.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/contract/test_version_watchdog.py)（单测与真实冒烟）
- **Git 提交（本地）**：
  - `200d109` `feat(contract): 实现 manifest SHA256 版本戳强校验看门狗 (#135)`
  - `366b94f` `refactor(contract): 修复真实manifest多季节聚合、加固Fail-Closed契约比对与函数长度规范 (#135)`
- **执行环境**：macOS (Darwin) / Python 3.13.5 / pytest 8.3.4
- **判定纪律**：两步分离原则（原始观测值 vs 判定阈值机械比对，无模型主观判断）。

---

## 一、 交付目标与架构对账

依据《ADR-0019：物理模型参数向投注算法消费契约与解耦架构》§二.6 与 GitHub Issue [#135](https://github.com/oasislin/Poly2/issues/135)，Ticket 02 承担交易模块启动期与流水线第一道安全防线：

1. **启动期 Fail-Closed 物理模型一致性防御**：
   - 彻底杜绝生产环境下模型二进制文件被篡改、损坏、版本陈旧或物理丢失；
   - 逐一比对活动 `.pkl` 文件的 SHA256 哈希值与 `manifest.json` 中声明的 `models[*].sha256`；
   - 深度检验模型反序列化合法性（`pickle.loads`）与文件非 0 字节完整性。
2. **规范化 Manifest SHA256 锚点比对**：
   - 实现规范化、确定性 JSON 序列化（`json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)`）与 SHA256 计算；
   - 校验注入契约中声明的 `PhysicalParamContract.manifest_sha256` 是否与活动 manifest 的 canonical SHA256 逐字一致。
3. **注入契约权重哈希比对（Fail-Closed）**：
   - 若注入契约附带 `model_weights_sha256`，严格比对每个法定格位的 SHA256，一旦缺失格位或哈希不符直接阻断。
4. **22 法定消费网格覆盖率硬断言**：
   - 严格覆盖 2 站（KORD/KMIA）× 11 提前期（12h~72h）= 22 格；
   - 真实数据集中每个格位包含多季节/变量模型，看门狗校验全部活动文件，并断言唯一法定网格覆盖恰好为 22。
5. **6h Lead 显式豁免与 WARN 旁路**：
   - 常量显式定义 `AUTHORIZED_LEADS_FOR_GUARD = AUTHORIZED_LEAD_HOURS`（显式排除 6h）；
   - 遭遇 6h 模型条目仅触发 `logger.warning` 并在报告中记录 `skipped_6h_entries`，不阻塞启动。
6. **纵深防御体系（Three Lines of Defense）**：
   - 防线 1：`check(*, skip_when_env=None)` 默认闭合；
   - 防线 2：生产环境硬互斥（`POLY_ENV in ('production', 'prod')` 严格禁止任何绕过，抛出 `SecurityViolationError`）；
   - 防线 3：非生产环境受控绕过时记录 `logger.critical` 审计日志。
7. **设计决策敲定（D1 / D2）**：
   - **D1 选型 B**：零跨层依赖，定义独立基类 [`ContractGuardrailError(Exception)`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L48-L51)，不导入 `src.modeling.registry`；
   - **D2 选型 A**：不可变结果报告 [`WatchdogVerificationReport(frozen=True)`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L72-L82)。

---

## 二、 双轴 Code Review 审查与重构加固

初版实现（commit `200d109`）经 Standards Reviewer 与 Spec Reviewer 双轴审查，发现并修复了以下工程与规格问题（完成于 commit `366b94f`）：

| 审查维度 | 发现问题 | 重构解决方案 | 落实代码位置 |
|---|---|---|---|
| **Spec** | 真实 `manifest.json` 多季节/变量聚合导致原计数器冲突（实际 176 个模型文件 vs 22 网格） | 引入 `seen_cells: Set[Tuple[str, int]]`，逐文件物理校验的同时去重统计网格覆盖，严格断言 `len(seen_cells) == 22` | `version_watchdog.py#L213-L250` |
| **Standards** | 函数长度超出规范（原 `_verify_model_weights_sha256` 达 95 行，违背 `< 50` 行硬性标准） | 拆解为 `_handle_bypass_defense`、`_verify_contract_anchors`、`_verify_single_model_file`，所有函数最大 48 行 | `version_watchdog.py` 全模块 |
| **Spec** | 契约模式版本常量 `CONTRACT_VERSION` 定义后未参与校验 | 在 `_verify_contract_anchors` 中增加 `contract.contract_version == CONTRACT_VERSION` 比对，版本不符抛 `StaleModelParametersError` | `version_watchdog.py#L192-L196` |
| **Spec** | 契约权重比对存在静默跳过隐患（若 `cell_key` 不在契约权重中曾直接 continue） | 改为 Fail-Closed 强校验：只要 `contract.model_weights_sha256` 非空，缺失法定格位直接抛出 `StaleModelParametersError` | `version_watchdog.py#L286-L299` |
| **Standards** | 反序列化异常捕获范围较窄（仅捕获 `UnpicklingError` 和 `EOFError`） | 扩充捕获族系为 `(pickle.UnpicklingError, EOFError, AttributeError, ValueError, TypeError)` | `version_watchdog.py#L273` |
| **Spec** | 缺少真实仓库 `data/models/manifest.json` 的端到端冒烟测试 | 增加 `test_real_repo_manifest_read_only_smoke`，只读验证 176 个真实物理模型 | `test_version_watchdog.py#L427-L442` |

---

## 三、 自动化测试执行证据与两步分离判定

### 1. 看门狗专项单元与集成测试（19 项）

- **执行命令**：`python -m pytest tests/unit/contract/test_version_watchdog.py -v`
- **控制台输出片段**：
```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.3.4, pluggy-1.5.0 -- /opt/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collected 19 items                                                             

tests/unit/contract/test_version_watchdog.py::test_t1_normal_all_pass PASSED [  5%]
tests/unit/contract/test_version_watchdog.py::test_t2_sha256_tamper_fails_closed PASSED [ 10%]
tests/unit/contract/test_version_watchdog.py::test_t3_missing_pkl_file_raises_corruption PASSED [ 15%]
tests/unit/contract/test_version_watchdog.py::test_t4_zero_byte_pkl_file_raises_corruption PASSED [ 21%]
tests/unit/contract/test_version_watchdog.py::test_t5_production_bypass_rejected PASSED [ 26%]
tests/unit/contract/test_version_watchdog.py::test_t6_test_env_controlled_bypass PASSED [ 31%]
tests/unit/contract/test_version_watchdog.py::test_t7_incomplete_statutory_cells_coverage PASSED [ 36%]
tests/unit/contract/test_version_watchdog.py::test_t8_6h_lead_warn_only PASSED [ 42%]
tests/unit/contract/test_version_watchdog.py::test_manifest_file_not_found PASSED [ 47%]
tests/unit/contract/test_version_watchdog.py::test_manifest_invalid_json PASSED [ 52%]
tests/unit/contract/test_version_watchdog.py::test_contract_manifest_sha256_mismatch PASSED [ 57%]
tests/unit/contract/test_version_watchdog.py::test_contract_model_weight_sha256_mismatch PASSED [ 63%]
tests/unit/contract/test_version_watchdog.py::test_check_without_contract_injection PASSED [ 68%]
tests/unit/contract/test_version_watchdog.py::test_corrupted_pickle_content PASSED [ 73%]
tests/unit/contract/test_version_watchdog.py::test_exception_inheritance_hierarchy PASSED [ 78%]
tests/unit/contract/test_version_watchdog.py::test_contract_version_and_guard_constants PASSED [ 84%]
tests/unit/contract/test_version_watchdog.py::test_contract_version_mismatch_raises_stale_model_parameters_error PASSED [ 89%]
tests/unit/contract/test_version_watchdog.py::test_non_authorized_station_in_manifest_ignored PASSED [ 94%]
tests/unit/contract/test_version_watchdog.py::test_real_repo_manifest_read_only_smoke PASSED [100%]

============================== 19 passed in 1.49s ==============================
```
- **机械两步判定**：
  `原始观测值 = 19 passed in 1.49s, exit code 0；判定阈值 = 19 passed, exit code 0；结论 = 通过`

---

### 2. 契约层全量测试（Ticket 01 Schema + Ticket 02 看门狗）

- **执行命令**：`python -m pytest tests/unit/contract -q`
- **控制台输出片段**：
```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.3.4, pluggy-1.5.0
rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collected 31 items                                                             

tests/unit/contract/test_parameter_contract.py ............              [ 38%]
tests/unit/contract/test_version_watchdog.py ...................         [100%]

============================== 31 passed in 1.12s ==============================
```
- **机械两步判定**：
  `原始观测值 = 31 passed in 1.12s, exit code 0；判定阈值 = 31 passed, exit code 0；结论 = 通过`

---

### 3. 活跃生产与回归测试集（Prediction + Risk + Contract）

- **执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q`
- **控制台输出片段**：
```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.3.4, pluggy-1.5.0
rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collected 144 items                                                            

tests/unit/prediction/test_bin_converter.py ..........                   [  6%]
tests/unit/prediction/test_constraint_enforcer.py ............           [ 15%]
tests/unit/prediction/test_discrete_bin_engine.py .....                  [ 18%]
tests/unit/prediction/test_discrete_bin_engine_2deg.py ......            [ 22%]
tests/unit/prediction/test_dynamic_corrector.py ............             [ 31%]
tests/unit/prediction/test_monotonic_confluence.py ...                   [ 33%]
tests/unit/prediction/test_prediction_pipeline.py .....                  [ 36%]
tests/unit/prediction/test_scenario_d.py ...                             [ 38%]
tests/unit/prediction/test_static_predictor.py ........                  [ 44%]
tests/unit/prediction/test_temperature_sanitizer.py .......              [ 49%]
tests/unit/prediction/test_truncated_probability_engine.py ....          [ 52%]
tests/unit/prediction/test_w2_confluence_exemptions.py .....             [ 55%]
tests/unit/prediction/test_w2_gate_c3_sampling.py ...................... [ 70%]
.......                                                                  [ 75%]
tests/unit/risk/test_stream_watchdog.py ....                             [ 78%]
tests/unit/contract/test_parameter_contract.py ............              [ 86%]
tests/unit/contract/test_version_watchdog.py ...................         [100%]

============================= 144 passed in 1.40s ==============================
```
- **机械两步判定**：
  `原始观测值 = 144 passed in 1.40s, exit code 0；判定阈值 = 144 passed, exit code 0；结论 = 通过`

---

## 四、 真实环境资产只读核验证据（实证数据）

在本地真实仓库环境下运行 `ContractVersionWatchdog("data/models/manifest.json").check()` 产生如下客观输出：

```
[ContractWatchdog] 6h lead model SKIPPED from betting contract verification: station=KORD, model=KORD_Winter_Max_lead6h.pkl
...（共 64 个 6h lead 模型触发 WARN 旁路日志）...
Report: WatchdogVerificationReport(
    is_valid=True,
    verified_cells_count=22,
    failed_entries=0,
    skipped_6h_entries=64,
    bypassed=False,
    checked_at='2026-10-26T04:36:05.485522+00:00'
)
```

- **核验证明**：
  - 活动模型二进制文件：176 个（KORD 与 KMIA 各 88 个，分布于四季与最高/最低温变量）全部通过 SHA256 校验与反序列化测试；
  - 6h 豁免模型：恰好 64 个，全部记录 warning 并准确计入 `skipped_6h_entries`；
  - 核心法定网格：22 格全部覆盖（`verified_cells_count == 22`）；
  - 失败条目：0 个。

---

## 五、 红线与开发规范审计对照表

| 审计项 | 规则来源 | 审计结果 | 说明 |
|---|---|---|---|
| **代码修改授权** | AGENTS.md 最高铁律 | **完全合规** | 在用户明确指令“对 完整修改”后方执行代码编辑与提交 |
| **原始观测结果不可篡改** | AGENTS.md 最高铁律 | **完全合规** | 汇报中所有命令、输出片段、退出码与统计值原样引用，无任何修饰 |
| **两步分离判定** | AGENTS.md 硬性 | **完全合规** | 严格遵循 `原始观测值 = <val>；判定阈值 = <tgt>；结论 = 通过/不通过` |
| **Git Push 严格遵从指令** | AGENTS.md 硬性 | **完全合规** | 仅在本地进行 git commit，绝对未执行 `git push`，静待用户指令 |
| **冻结文件与模型文件保护** | ADR-0019 / AGENTS.md | **完全合规** | 未修改 `src/modeling/registry.py`、`src/contract/parameter_contract.py`，未修改任何 `data/models/*.pkl` |
| **函数行数规范** | DEVELOPER_GUIDELINES.md:98 | **完全合规** | 经 AST 解析，全模块 8 个函数/方法均 ≤ 48 行（阈值 < 50） |
| **零跨层依赖** | ADR-0019 / Ticket 02 决策 D1 | **完全合规** | 异常基类 `ContractGuardrailError(Exception)` 纯内聚，无跨层耦合 |

---

## 六、 交付物清单与代码符号链接

1. **核心看门狗**：[`src/contract/version_watchdog.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py)
   - 核心常量：[`CONTRACT_VERSION`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L38)、[`AUTHORIZED_LEADS_FOR_GUARD`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L43-L45)
   - 异常基类与子类：[`ContractGuardrailError`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L48-L51)、[`StaleModelParametersError`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L54-L57)、[`PickleCorruptionError`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L60-L63)、[`SecurityViolationError`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L66-L69)
   - 报告数据结构：[`WatchdogVerificationReport`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L72-L82)
   - 主看门狗类：[`ContractVersionWatchdog`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/version_watchdog.py#L84-L123)
2. **包导出入口**：[`src/contract/__init__.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/contract/__init__.py)（纯加法导出 7 个看门狗新符号，零破坏性修改）
3. **单元与冒烟测试**：[`tests/unit/contract/test_version_watchdog.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/contract/test_version_watchdog.py)（19 项用例）

---

## 七、 后续步骤与排程建议

Ticket 02 现已完备交付，且具备真实物理资产验证证据。
根据 Phase 2 Task 08 的依赖拓扑：
- **Ticket 02 完成后解除的直接依赖**：Ticket 04 (`feat(contract): 构建 2019 双城重测与契约闭环校验流水线`, Issue [#137](https://github.com/oasislin/Poly2/issues/137)) 的前置启动门禁。
- **当前并行可推进票**：
  1. **Ticket 03** (`feat(contract): 实现盲测标定 CSV 转 22 格法定契约 JSON 转换器与只读校验器`, Issue [#136](https://github.com/oasislin/Poly2/issues/136))：离线生产静态标定契约，承接 "恰好 22 格" 转换强约束；
  2. **Ticket 06** (`feat(pricing): 实现基于 PhysicalForecastOutput 的两档行权概率动态计算器`, Issue [#139](https://github.com/oasislin/Poly2/issues/139))：交易定价计算核心。

**待确认动作**：请用户下达明确指令是否执行 `git push origin main` 同步远端，并由用户关闭 GitHub Issue [#135](https://github.com/oasislin/Poly2/issues/135)。
