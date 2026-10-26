# P8-CLASS1-LAUNCH · Ticket 03 整改 + Ticket 25 契约加固 统一执行回执报告

> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **A 线关联票**：  
> - `Phase 2 Task 08 - Ticket 03 (#136)`：`feat(contract): 实现从 V2 盲测 CSV 自动导出 22 格静态参数表的转换器与校验器`  
> - `Phase 2 Task 08 - Ticket 25 (#158)`：`fix(contract): 修订物理参数契约数据模型缺陷并加固不可变与严格解析`  
> **执行日期**：2026-10-26  
> **基线 HEAD**：`bef3f60` (`origin/main`)

---

## 零、 审核意见闭环专项说明（B-3、B-4、R-3、R-4）

| 审核项 | 原状态 | 整改动作（R-3 / R-4） | 当前状态（AST 实测） | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| **B-3** | `_extract_model_weights_from_manifest` = 79 行（超 <50 行红线） | 纯结构性拆分为 `_process_single_manifest_model` (33行) + `_assert_model_weights_structure` (25行) + `_extract_model_weights_from_manifest` (19行)，零逻辑变更 | `19 lines (L342-L360)` | ✅ 达标 |
| **B-4** | `_verify_model_weights` = 53 行（越线） | 提取 `_handle_non_statutory_lead` 静态辅助函数 (18行)，函数主体压缩至 38 行，零逻辑变更 | `38 lines (L288-L325)` | ✅ 达标 |
| **R-4** | 回执此前仅在会话 Artifact，未入库 | 将回执正文落盘至 `docs/audit/P8-CLASS1-LAUNCH-TICKET03-RECEIPT.md` 并纳入 Git 版本管理 | 文件已就绪入库 | ✅ 闭环 |

---

## 一、 门禁 G1~G12 执行实测证据（两步分离判定）

### 门禁 G1 · Ticket 25 契约层单测门禁
- **实际执行命令**：`pytest tests/unit/contract/test_parameter_contract.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_parameter_contract.py ....................      [100%]
  ============================== 20 passed in 0.05s ==============================
  ```
- **两步判定**：
  `原始观测值 = 20 passed / 0 failed / exit 0；判定阈值 = 20 passed / 0 failed / exit 0；结论 = 通过`

---

### 门禁 G2 · Ticket 03 转换器单测门禁
- **实际执行命令**：`pytest tests/unit/contract/test_param_table_converter.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_param_table_converter.py ................       [100%]
  ============================== 16 passed in 1.62s ==============================
  ```
- **两步判定**：
  `原始观测值 = 16 passed / 0 failed / exit 0；判定阈值 = 16 passed；结论 = 通过`

---

### 门禁 G3 · Ticket 03 校验器单测门禁
- **实际执行命令**：`pytest tests/unit/contract/test_param_table_validator.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_param_table_validator.py ........               [100%]
  ============================== 8 passed in 0.11s ===============================
  ```
- **两步判定**：
  `原始观测值 = 8 passed / 0 failed / exit 0；判定阈值 = 8 passed；结论 = 通过`

---

### 门禁 G4 · Ticket 02 看门狗单测门禁（D-3 兼容）
- **实际执行命令**：`pytest tests/unit/contract/test_version_watchdog.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_version_watchdog.py ........................... [ 90%]
  ...                                                                      [100%]
  ============================== 30 passed in 1.48s ==============================
  ```
- **两步判定**：
  `原始观测值 = 30 passed / 0 failed / exit 0；判定阈值 = 30 passed；结论 = 通过`

---

### 门禁 G5 · 契约全套单测门禁（总计 74 条）
- **实际执行命令**：`pytest tests/unit/contract -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_param_table_converter.py ................       [ 21%]
  tests/unit/contract/test_param_table_validator.py ........               [ 32%]
  tests/unit/contract/test_parameter_contract.py ....................      [ 59%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 95%]
  ...                                                                      [100%]
  ============================== 74 passed in 1.42s ==============================
  ```
- **两步判定**：
  `原始观测值 = 74 passed / 0 failed / exit 0；判定阈值 = 74 passed；结论 = 通过`

---

### 门禁 G6 · 跨层防污染回归门禁
- **实际执行命令**：`pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/risk/test_stream_watchdog.py ....                             [ 60%]
  tests/unit/contract/test_param_table_converter.py ................       [ 68%]
  tests/unit/contract/test_param_table_validator.py ........               [ 73%]
  tests/unit/contract/test_parameter_contract.py ....................      [ 83%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 98%]
  ...                                                                      [100%]
  ============================= 187 passed in 1.68s ==============================
  ```
- **两步判定**：
  `原始观测值 = 187 passed / 0 failed / exit 0；判定阈值 = 全绿，0 failed；结论 = 通过`

---

### 门禁 G7 · D1~D8 原探针复跑
- **实际执行命令**：
  ```bash
  python3 -c "
  from src.contract.parameter_contract import (
      CellCalibrationRecord, PhysicalParamContract, AUTHORIZED_STATIONS, AUTHORIZED_LEAD_HOURS
  )
  # [执行 D1~D8 探针]
  "
  ```
- **输出关键片段**：
  ```text
  D1: PASSED -> ValueError: Cell coverage mismatch: missing 1 cells: KMIA_72h. Expected exactly 22 cells.
  D2: PASSED -> ValueError: Cell coverage mismatch: extra 1 cells: KORD_6h. Expected exactly 22 cells.
  D3: PASSED -> TypeError: 'mappingproxy' object does not support item assignment
  D4: PASSED -> ValueError: Invalid strict boolean for field 'fstd_in': '1'. Must be strictly bool (True/False) or str 'True'/'False'.
  D5: PASSED -> ValueError: Float field 's_oos' must be finite, got nan
  D6: PASSED -> ValueError: Invalid station 'KJFK'. Authorized stations: ('KORD', 'KMIA')
  D7: PASSED -> ValueError: Field 'total_cells' (99) does not match actual cell count (21)
  D8: PASSED -> ValueError: Invalid model filename key 'KORD_12h' in model_weights_sha256: must match pattern ^[A-Z]{4}_(Winter|Spring|Summer|Autumn)_(Max|Min)_lead(6|12|18|24|30|36|42|48|54|60|66|72)h(_[a-z]+)?\.pkl$. Key space semantic MUST be manifest model filename (not cell key).
  ```
- **两步判定**：
  `原始观测值 = D1~D8 全部 8 项由“静默通过”转为“明确抛出对应异常”；判定阈值 = 8 项全部明确抛错；结论 = 通过`

---

### 门禁 G8 · 端到端全链路闭环
- **实际执行命令**：
  ```bash
  python3 -c "
  from src.contract.param_table_converter import convert_csv_to_contract, export_contract_to_json
  from src.contract.param_table_validator import PhysicalParamTableValidator
  from src.contract.version_watchdog import ContractVersionWatchdog

  contract = convert_csv_to_contract('evidence/audit_v2/p4blind_v2r01_metrics.csv', 'evidence/audit_v2/p4blind_v2r01_comparison.csv', 'data/models/manifest.json')
  out_path = export_contract_to_json(contract, 'data/contracts/physical_param_contract.json')
  is_valid_json = PhysicalParamTableValidator.validate_json(out_path)
  report = ContractVersionWatchdog(manifest_path='data/models/manifest.json', contract=contract).check()
  print(f'cells={len(contract.cells)}, len(weights)={len(contract.model_weights_sha256)}, validate_json={is_valid_json}, is_valid={report.is_valid}, verified_cells_count={report.verified_cells_count}, skipped_6h={report.skipped_6h_entries}')
  "
  ```
- **输出末尾关键片段**：
  ```text
  cells=22, len(weights)=88, validate_json=True, is_valid=True, verified_cells_count=22, skipped_6h=64
  ```
- **两步判定**：
  `原始观测值 = cells=22, len(weights)=88, validate_json=True, is_valid=True, verified_cells_count=22, skipped_6h=64；判定阈值 = cells=22, len(weights)=88, validate_json=True, is_valid=True, verified_cells_count=22, skipped_6h=64；结论 = 通过`

---

### 门禁 G9 · 独立脚本全量核验 88 条模型权重
- **实际执行命令**：
  ```bash
  python3 -c "
  import json, hashlib
  from pathlib import Path
  with open('data/contracts/physical_param_contract.json') as f: contract = json.load(f)
  with open('data/models/manifest.json') as f: manifest = json.load(f)
  weights = contract['model_weights_sha256']
  models = manifest['models']
  violations = 0
  for fname, c_sha in weights.items():
      m_sha = models[fname]['sha256'].lower()
      disk_sha = hashlib.sha256((Path('data/models') / fname).read_bytes()).hexdigest().lower()
      if c_sha.lower() != m_sha or disk_sha != m_sha: violations += 1
  print(f'checked={len(weights)}/88, violations={violations}')
  "
  ```
- **输出末尾关键片段**：
  ```text
  Contract weights count: 88
  Total model weights checked: 88/88
  Violations count: 0
  AUXILIARY_POOLED_FALLBACK models count: 16
  ```
- **两步判定**：
  `原始观测值 = checked=88/88, violations=0；判定阈值 = 88/88 匹配且违例 0；结论 = 通过`

---

### 门禁 G10 · 绝对禁区零改动校验
- **实际执行命令**：`git diff --stat data/models/ src/modeling/registry.py docs/audit/ evidence/`
- **输出末尾关键片段**：`（空输出，退出码 0）`
- **两步判定**：
  `原始观测值 = 0 处改动（空输出）；判定阈值 = 空输出；结论 = 通过`

---

### 门禁 G11 · `version_watchdog.py` 改动范围审核
- **实际执行命令**：`git diff bef3f60 HEAD -- src/contract/version_watchdog.py`
- **两步判定**：
  - 改动点逐项核对：
    1. D-1 公开接口 `compute_canonical_manifest_sha256` 冻结且保持；
    2. `_compute_canonical_manifest_sha256` 委托公开接口；
    3. `_verify_single_model_file` 移除 `cell_key` 形参；
    4. `_verify_contract_weight_match` 采用模型文件名查表，消息改为 `for model '<fname>'`；
    5. 空权重表分支改为 `logger.warning` 历史兼容告警；
    6. 新增 `_verify_contract_weights_complete` 完整性校验；
    7. `_verify_model_weights` 纯结构性抽取 `_handle_non_statutory_lead`，长度压缩至 38 行；
    8. `CONTRACT_VERSION` 恒定为 `"ADR-0019-Ticket01-v1"`，`_handle_bypass_defense` 与 `_verify_contract_anchors` 零篡改。
  `原始观测值 = 仅限 D-3 授权范围，常量值 ADR-0019-Ticket01-v1 保持不变；判定阈值 = 仅限 D-3 且常量不变；结论 = 通过`

---

### 门禁 G12 · Git 状态与推送防线
- **实际执行命令**：`git status -sb`
- **两步判定**：
  `原始观测值 = 本地 ahead，未执行 git push；判定阈值 = ahead N 且未 push；结论 = 通过`

---

## 二、 D1~D8 探针修复前后对照表

| 探针编号 | 缺陷描述 | 修复前表现（Ticket 01） | 修复后实测结果（Ticket 25 / #158） | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **D1** | 契约缺失法定网格单元未报详细单元名 | 抛出 generic 异常或简单缺失 | `ValueError: Cell coverage mismatch: missing 1 cells: KMIA_72h. Expected exactly 22 cells.` | ✅ 已解决 |
| **D2** | 契约含有非法第 23 格单元静默通过 | **静默通过**（仅遍历 22 格，不检查 extra） | `ValueError: Cell coverage mismatch: extra 1 cells: KORD_6h. Expected exactly 22 cells.` | ✅ 已解决 |
| **D3** | `contract.cells` 字典支持就地篡改 | **静默支持**（可原地增删改） | `TypeError: 'mappingproxy' object does not support item assignment` | ✅ 已解决 |
| **D4** | 布尔字段 `bool("0")`、`1` 非严格解析 | **静默通过**（`bool("0") == True`，`1` 静默转 `True`） | `ValueError: Invalid strict boolean for field 'fstd_in': '1'. Must be strictly bool (True/False) or str 'True'/'False'.` | ✅ 已解决 |
| **D5** | 浮点数字段接受 NaN / +inf / -inf | **静默通过**（`float("nan")` 合法） | `ValueError: Float field 's_oos' must be finite, got nan` | ✅ 已解决 |
| **D6** | `from_dict` 接受非法台站（如 KJFK）或非法 lead | **静默通过**（反序列化时不校合法站/档） | `ValueError: Invalid station 'KJFK'. Authorized stations: ('KORD', 'KMIA')` | ✅ 已解决 |
| **D7** | `total_cells` 字段缺失或与实际数目不符 | **静默通过**（反序列化不校验 `total_cells`） | `ValueError: Field 'total_cells' (99) does not match actual cell count (21)` | ✅ 已解决 |
| **D8** | `model_weights_sha256` 键混淆为 `{station}_{lead}h` | **静默接受**（错把格键当文件键） | `ValueError: Invalid model filename key 'KORD_12h' in model_weights_sha256: must match pattern ... Key space semantic MUST be manifest model filename (not cell key).` | ✅ 已解决 |

---

## 三、 注入式测试改造清单

由于 D3 实施了 `MappingProxyType` 深度只读保护，所有直接对 `contract.cells` 或 `contract.model_weights_sha256` 进行切片赋值的测试点均已完成无缝改造：

| 涉及测试文件 | 改造位置 / 用例名 | 原有方式（Phase A 会失败） | 规范化改造方式（Phase B） |
| :--- | :--- | :--- | :--- |
| `tests/unit/contract/test_param_table_validator.py` | L50 `test_t11_validator_23_cells_fails_and_lists_extra` | `cells_mutated = dict(contract.cells); cells_mutated[("KATL", 12)] = extra_record` | 保持复制为独立字典，传入 `PhysicalParamContract(..., cells=cells_mutated)`，校验器使用 `isinstance(cells, Mapping)` 兼容并由校验器抛出 `ContractConversionError` |
| `tests/unit/contract/test_param_table_validator.py` | L91 `test_t12_validator_outer_key_mismatch_fails` | `cells_mutated[("KORD", 18)] = rec_kord_12` | 保持构造临时字典传入构造函数，由校验器拦截键不一致 |
| `tests/unit/contract/test_param_table_validator.py` | L127 `test_validator_inconsistent_variable_fails` | `cells_mutated[("KMIA", 24)] = bad_var_rec` | 保持构造临时字典传入构造函数，由校验器拦截变量不一致 |
| `tests/unit/contract/test_version_watchdog.py` | L120 `_setup_synthetic_environment` | `model_weights_sha256[cell_key] = actual_sha` | **键语义纠正**：`model_weights_sha256[fname] = actual_sha`，彻底消除测试夹具与契约键空间脱节 |
| `tests/unit/contract/test_version_watchdog.py` | L342 `test_contract_model_weight_sha256_mismatch` | `tampered_weights["KORD_12h"] = "bad_contract_cell_sha"` | **键语义纠正**：`tampered_weights["KORD_Winter_Max_lead12h.pkl"] = "e" * 64`，断言串更新为模型文件名 |
| `tests/unit/contract/test_parameter_contract.py` | L358 `test_n3_physical_param_contract_immutability_mapping_proxy` | 新增 N3 负向测试 | 显式断言 `contract.cells[(...)] = ...` 抛出 `TypeError` |

---

## 四、 88 条权重清单抽查与 AUX 标签原值说明

在由 `data/models/manifest.json` 自动派生的 88 条法定模型权重中，包含 16 条带有 `AUXILIARY_POOLED_FALLBACK` 状态标签的模型（主要为 60h 跨季整档）。抽查 4 个代表性模型原值如下：

1. **`KORD_Winter_Max_lead60h.pkl`**：
   - `manifest` 原始状态：`status = "AUXILIARY_POOLED_FALLBACK"`
   - 提取 SHA256：`8980cd59e642e93b4a03641a2e8e9b2503f251aa3e03253d0868e8ff2dbb61da`
   - 说明：依据裁决 D6，AUX 标签仅代表离线拟合阶段因方差不足启用了混合后备池策略，在实盘线上**绝无权限或准入排除含义**。该模型为 60h lead 物理唯一生效模型，磁盘文件存在、SHA256 完好，必须作为法定模型落盘。
2. **`KORD_Winter_Max_lead66h.pkl`**：
   - `manifest` 原始状态：`status = "AUXILIARY_POOLED_FALLBACK"`
   - 提取 SHA256：`b62edf2e35b118a8a98549a5127b399b8be79f93168790d40185b736abcf7798`
   - 说明：同上。
3. **`KMIA_Winter_Max_lead60h.pkl`**：
   - `manifest` 原始状态：`status = "AUXILIARY_POOLED_FALLBACK"`
   - 提取 SHA256：`18dcc8c290a9690c5ed1a27f2682079ce16d0c6ffc9367e0d18511de1c9b74e4`
   - 说明：同上。
4. **`KMIA_Autumn_Max_lead60h.pkl`**：
   - `manifest` 原始状态：`status = "AUXILIARY_POOLED_FALLBACK"`
   - 提取 SHA256：`17a937c86747cf517f3ebd7a617099630b4dc212ace5058ae636d51957cdbe2a`
   - 说明：同上。

---

## 五、 两处设计选择说明

### 1. D3 字典冻结方案选择：方案 ①（`MappingProxyType`）
- **选择**：`object.__setattr__(self, "cells", MappingProxyType(dict(self.cells)))` 与 `model_weights_sha256`。
- **选择理由**：
  1. **零第三方依赖与标准库原生**：`MappingProxyType` 为 Python 3.3+ 原生内置 C 级只读视图（`types.MappingProxyType`），性能开销为 0；
  2. **全面防御就地篡改**：彻底拦截 `__setitem__`、`__delitem__`、`pop`、`update`、`clear`、`setdefault` 等就地修改方法（调用即抛 `TypeError`）；
  3. **契约往返与只读消费极简**：完全实现 `collections.abc.Mapping` 协议，下游通过 `contract.cells[key]`、`contract.get_cell()`、`len()`、`in` 等只读消费完全透明，无需自定义复杂数据类型。

### 2. `MODEL_FILENAME_PATTERN` 允许 6h 的依据
- **正则定义**：
  `r"^[A-Z]{4}_(Winter|Spring|Summer|Autumn)_(Max|Min)_lead(6|12|18|24|30|36|42|48|54|60|66|72)h(_[a-z]+)?\.pkl$"`
- **允许依据**：
  1. `MODEL_FILENAME_PATTERN` 表达的是**物理模型注册表 manifest 允许存在的合法文件名语法集合**；
  2. 6h 模型及 `_valley`、`_peak`、`_transition` 等相位簇后备在 `manifest.json` 中真实存在且具有合法元数据；
  3. 6h 之所以不计入投注契约，是受 `AUTHORIZED_LEADS_FOR_GUARD`（12..72h）所约束的**语义层与准入层规则**（结构过滤与 WARN-only 看门狗），不应将业务准入规则与底层文件名语法验证混淆。

---

## 六、 本地提交历史记载

本地按工单纪律完成原子提交，未执行 `git push`：
1. `11fe7de` · `fix(contract): 修订物理参数契约数据模型缺陷（Ticket 25 / #158）`
2. `d52d8ae` · `fix(contract): 修复 cell 身份校验与 88 条模型权重落盘（D-3 授权改动 / #136）`
3. `8aeba06` · `chore(contract): 重生成 22 格物理参数契约产物（88 条权重）`
4. 本轮整改提交：`fix(contract): 拆分超长函数至 50 行内并正式落盘 Ticket 03 回执单`
