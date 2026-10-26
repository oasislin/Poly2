# P8-CLASS1-LAUNCH · Ticket 05 契约安全与防污染测试集交付回执

> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **A 线关联票**：`Phase 2 Task 08 - Ticket 05: test(contract): 编写参数契约、版本戳校验与防污染契约测试集`（[#138](https://github.com/oasislin/Poly2/issues/138)）  
> **执行日期**：2026-10-26  
> **开工基线**：`15a4cb3` (`origin/main`)  
> **提交纪律**：本地原子 commit，严格未授权不 push

---

## 一、 交付物清单与代码改动

### 1. 交付物白名单（2 项完整闭环）
| 序号 | 交付物文件路径 | 性质 | 说明 |
| :--- | :--- | :--- | :--- |
| 1 | `tests/unit/contract/test_contract_security_integration.py` | **新建** | 契约安全、版本戳篡改阻断、防均值化、静态/运行时防污染综合集成测试集（8 组用例） |
| 2 | `docs/audit/P8-CLASS1-LAUNCH-TICKET05_交付回执_20261026.md` | **新建** | 本交付回执（含 G1~G8 逐条执行证据、两步分离判定与 TC-SEC-01~08 明细） |

**禁区与红线遵守情况**：
- `data/models/` 目录：**零触碰，字节零变化**；
- `data/contracts/` 目录：**零触碰，字节零变化**；
- `src/contract/` 生产代码：**保持原样冻结，零修改**。

---

## 二、 验收门禁 G1~G8 实测证据（两步分离判定 · 开发端自测）

> **采集主体标注**：以下数值均为**开发端本机实测自测值**。

### 门禁 G1 · Ticket 05 专属集成测试门禁
- **实际执行命令**：`python -m pytest tests/unit/contract/test_contract_security_integration.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_contract_security_integration.py ........       [100%]
  ============================== 8 passed in 1.95s ===============================
  ```
- **两步分离判定**：
  `原始观测值 = 8 passed in 1.95s（开发端自测）；判定阈值 = 全绿，≥ 8 用例；结论 = 通过`

### 门禁 G2 · 契约层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/contract -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_contract_security_integration.py ........       [  6%]
  tests/unit/contract/test_param_table_converter.py ................       [ 20%]
  tests/unit/contract/test_param_table_validator.py ........               [ 26%]
  tests/unit/contract/test_parameter_contract.py ....................      [ 43%]
  tests/unit/contract/test_parameter_domains.py .....................      [ 61%]
  tests/unit/contract/test_trigger_model_retest.py ................        [ 74%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 97%]
  ...                                                                      [100%]
  ============================= 119 passed in 3.16s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 119 passed in 3.16s（开发端自测）；判定阈值 = 全绿，≥ 119 用例；结论 = 通过`

### 门禁 G3 · 跨层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_contract_security_integration.py ........       [ 52%]
  tests/unit/contract/test_param_table_converter.py ................       [ 59%]
  tests/unit/contract/test_param_table_validator.py ........               [ 62%]
  tests/unit/contract/test_parameter_contract.py ....................      [ 71%]
  tests/unit/contract/test_parameter_domains.py .....................      [ 80%]
  tests/unit/contract/test_trigger_model_retest.py ................        [ 87%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 98%]
  ...                                                                      [100%]
  ============================= 232 passed in 3.38s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 232 passed in 3.38s（开发端自测）；判定阈值 = 全绿，≥ 232 用例；结论 = 通过`

### 门禁 G4 · AST 函数长度扫描门禁
- **实际执行命令**：`python3 -c "import ast; tree = ast.parse(open('tests/unit/contract/test_contract_security_integration.py').read()); funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]; lens = [(f.name, f.end_lineno - f.lineno + 1) for f in funcs]; print(f'max = {max(l[1] for l in lens)}, over_50 = {sum(1 for l in lens if l[1] >= 50)}');"`
- **输出末尾关键片段**：
  ```text
  max = 40, over_50 = 0
  ```
- **两步分离判定**：
  `原始观测值 = max = 40 lines, over_50 = 0（开发端自测）；判定阈值 = max < 50，超限 = 0；结论 = 通过`

### 门禁 G5 · 静态 AST 扫描防污染门禁
- **实际执行命令**（完全对齐 `test_tc_sec_05` 实际扫描逻辑：`write_modes` + `write_methods` + `ast.unparse` 调用子树全匹配）：
  ```bash
  python3 -c '
  import ast, glob
  active_sources = glob.glob("src/contract/*.py") + glob.glob("src/risk/*.py")
  assert len(active_sources) >= 8, f"Expected >= 8 files, found {len(active_sources)}"
  write_modes = {"w", "wb", "a", "ab", "w+", "wb+"}
  write_methods = {"write", "write_text", "write_bytes", "dump", "to_pickle"}
  violations = 0
  for file_path in active_sources:
      tree = ast.parse(open(file_path, "r", encoding="utf-8").read(), filename=file_path)
      for node in ast.walk(tree):
          if not isinstance(node, ast.Call):
              continue
          func_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
          call_source = ast.unparse(node)
          has_models = "data/models" in call_source or "models_dir" in call_source
          has_write_mode = any(isinstance(a, ast.Constant) and a.value in write_modes for a in node.args) or any(kw.arg == "mode" and isinstance(kw.value, ast.Constant) and kw.value.value in write_modes for kw in node.keywords)
          if (func_name == "open" and has_models and has_write_mode) or (func_name in write_methods and has_models):
              violations += 1
  print(f"G5 check: scanned {len(active_sources)} files, write violations = {violations}")
  '
  ```
- **输出末尾关键片段**：
  ```text
  G5 check: scanned 8 files, write violations = 0
  ```
- **两步分离判定**：
  `原始观测值 = 扫描 8 文件（≥8 防空），向 data/models/ 写入调用 = 0（开发端自测）；判定阈值 = 写入调用 = 0；结论 = 通过`

### 门禁 G6 · 禁区产物不变性门禁
- **实际执行命令**：`git diff 15a4cb3 HEAD --stat -- data/models/ data/contracts/`
- **输出末尾关键片段**：
  ```text
  （标准输出为空，exit code 0）
  ```
- **两步分离判定**：
  `原始观测值 = 标准输出为空（开发端自测）；判定阈值 = 输出为空；结论 = 通过`

### 门禁 G7 · 宽泛异常扫描门禁
- **实际执行命令**：`grep -rn "except Exception\|except:" tests/unit/contract/test_contract_security_integration.py`
- **输出末尾关键片段**：
  ```text
  0 hits
  ```
- **两步分离判定**：
  `原始观测值 = 0 处命中（开发端自测）；判定阈值 = 命中数 = 0；结论 = 通过`

### 门禁 G8 · Git Push 纪律门禁
- **实际执行命令**：`git status -sb`
- **输出末尾关键片段**：
  ```text
  ## main...origin/main [ahead 1]
  ```
- **两步分离判定**：
  `原始观测值 = 本地 ahead 1，未执行 git push（开发端自测）；判定阈值 = 仅本地 commit，未 push；结论 = 通过`

---

## 三、 TC-SEC-01~08 测试用例清单与断言点

| 用例编号 | 测试函数名 | 测试重点与断言设计 | 预期结果 | 实测结论 |
| :--- | :--- | :--- | :--- | :--- |
| **TC-SEC-01** | `test_tc_sec_01_version_tamper_blocks_transaction` | 从契约加载端到端驱动：在沙箱中篡改任一模型 SHA256，调用 `watchdog.check()` | 抛 `StaleModelParametersError` | ✅ PASSED |
| **TC-SEC-02** | `test_tc_sec_02_missing_model_blocks_transaction` | 从契约加载端到端驱动：在沙箱中删除任一授权模型文件，调用 `watchdog.check()` | 抛 `PickleCorruptionError` | ✅ PASSED |
| **TC-SEC-03** | `test_tc_sec_03_anti_global_averaging_heterogeneity` | 22 格中 `s_oos`、`ece_2f`、`v1_coverage_90`、`pit_mean` 计算 `statistics.pvariance`，零魔法阈值 | 全部断言 `pvariance > 0` | ✅ PASSED |
| **TC-SEC-04** | `test_tc_sec_04_station_divergence_heterogeneity` | 断言 KORD 与 KMIA 在同一 lead 下至少存在一个时效取值不相等（无非受控形容词） | 11/11 leads 全部分化（≥1） | ✅ PASSED |
| **TC-SEC-05** | `test_tc_sec_05_anti_pollution_static_ast_scan` | AST 扫描 `src/contract/` + `src/risk/`（8 个文件，含 `len >= 8` 防空断言） | 针对 `data/models/` 写操作 = 0 | ✅ PASSED |
| **TC-SEC-06** | `test_tc_sec_06_anti_pollution_runtime_hash_zero_drift` | 快照 `data/models/` 下全部 1201 个文件哈希，真实触发看门狗校验，比对哈希 | 1201 文件 100% 零漂移 | ✅ PASSED |
| **TC-SEC-07** | `test_tc_sec_07_read_only_deep_frozen_immutability` | 契约与单元格深冻结测试：修改 `cells[k]` 抛 `TypeError`，修改属性抛 `FrozenInstanceError` | 全部拦截抛出不可变异常 | ✅ PASSED |
| **TC-SEC-08** | `test_tc_sec_08_controlled_domain_end_to_end_injection_rejection` | 注入越界负方差、越界覆盖率等脏值，经 `PhysicalParamContract.from_dict` 解析 | 抛 `ParameterDomainViolation` / `ValueError` | ✅ PASSED |

---

## 四、 本地提交历史记载

本地按工单纪律完成原子提交，未执行 `git push`：
- **基线 Commit**：`15a4cb3`
- **提交信息**：`test(contract): 编写参数契约安全集成、防均值化与防污染测试集（Ticket 05 / #138）`
- **提交范围**：白名单 2 个新建文件，生产代码零变动。
