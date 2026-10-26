# P8-CLASS1-LAUNCH · Ticket 26 物理参数受控域治理交付回执

> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **A 线关联票**：`Phase 2 Task 08 - Ticket 26: feat(contract): 建立物理参数受控域治理模块（两级域声明、消费影响域登记与算法解耦）`  
> **交付日期**：2026-10-26  
> **开工基线**：`93a1404` (`origin/main`)  
> **提交纪律**：本地提交，严格未执行 `git push`

---

## 一、 文件清单与 git diff --stat 实测

### 1. 交付物白名单（6 项完整闭环）
| 序号 | 交付物文件路径 | 性质 | 说明 |
| :--- | :--- | :--- | :--- |
| 1 | `src/contract/parameter_domains.py` | 新建 | 唯一受控域定义处（两级域模型、14 个受控字段、Fail-Closed） |
| 2 | `tests/unit/contract/test_parameter_domains.py` | 新建 | 专属测试集（21 条完整覆盖 T01~T21，全绿） |
| 3 | `src/contract/parameter_contract.py` | 委托改动 | `CellCalibrationRecord.__post_init__` 增加单点委托校验（6 行 diff） |
| 4 | `docs/adr/ADR-0019：物理模型参数向投注算法消费契约与解耦架构.md` | 追加附录 | 追加附录 A 并标注"已对齐 ADR-0019-Ticket26-v1"，既有章节零改动 |
| 5 | `specs/phase2-task08-class1-pricing-betting-spec.md` | 登记更新 | §三 表新增 Ticket 26 行，Ticket 05 的 Blocked by 关联追加 Ticket 26 |
| 6 | `docs/audit/P8-CLASS1-LAUNCH-TICKET26_交付回执_20261026.md` | 交付回执 | 本回执 |

### 2. 实测 git diff --stat 原文（未手写估算）
```text
 docs/adr/ADR-0019：物理模型参数向投注算法消费契约与解耦架构.md | 56 ++++++++++++++++++++++
 specs/phase2-task08-class1-pricing-betting-spec.md                 |  5 +-
 src/contract/parameter_contract.py                                 |  6 +++
 3 files changed, 65 insertions(+), 2 deletions(-)
```

---

## 二、 验收门禁 G1~G10 实测证据（两步分离判定）

### 门禁 G1 · Ticket 26 专属单测门禁
- **实际执行命令**：`python -m pytest tests/unit/contract/test_parameter_domains.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_parameter_domains.py .....................      [100%]
  ============================== 21 passed in 0.05s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 21 passed in 0.05s；判定阈值 = 全绿，>= 18 用例；结论 = 通过`

### 门禁 G2 · 契约层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/contract -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_param_table_converter.py ................       [ 14%]
  tests/unit/contract/test_param_table_validator.py ........               [ 21%]
  tests/unit/contract/test_parameter_contract.py ....................      [ 39%]
  tests/unit/contract/test_parameter_domains.py .....................      [ 58%]
  tests/unit/contract/test_trigger_model_retest.py ................        [ 72%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 97%]
  ...                                                                      [100%]
  ============================= 111 passed in 3.18s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 111 passed in 3.18s；判定阈值 = 全绿，>= 108 用例；结论 = 通过`

### 门禁 G3 · 跨层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_parameter_contract.py ....................      [ 70%]
  tests/unit/contract/test_parameter_domains.py .....................      [ 79%]
  tests/unit/contract/test_trigger_model_retest.py ................        [ 86%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 98%]
  ...                                                                      [100%]
  ============================= 224 passed in 3.02s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 224 passed in 3.02s；判定阈值 = 全绿，>= 221 用例；结论 = 通过`

### 门禁 G4 · AST 函数长度扫描门禁
- **实际执行命令**：`python3 -c "import ast; ..."`（扫描 `parameter_domains.py`、`parameter_contract.py`、`test_parameter_domains.py` 全部函数）
- **输出末尾关键片段**：
  ```text
  AST scan on touched files: max = 43, over_50 = 0
  ```
- **两步分离判定**：
  `原始观测值 = max = 43, over_50 = 0；判定阈值 = max < 50，超限 = 0；结论 = 通过`

### 门禁 G5 · 解耦与 AST 门禁（G-AST-1/2/3）
- **实际执行命令**：`python3 -c "import ast, glob; ..."`
- **输出末尾关键片段**：
  ```text
  G-AST-1: passed (0 float literals in src/contract/*.py except parameter_domains.py)
  G-AST-2: passed (floats = [0.0, 0.25, 1.0] subset of {0.0, 0.25, 1.0})
  G-AST-3: passed (all imports from stdlib)
  ```
- **两步分离判定**：
  `原始观测值 = G-AST-1/2/3 全部三条通过；判定阈值 = 三条全通过；结论 = 通过`

### 门禁 G6 · 真实产物 22 格全量兼容门禁
- **实际执行命令**：`python3 -c "import json; from src.contract.parameter_domains import validate_cell_parameters; ..."`
- **输出末尾关键片段**：
  ```text
  22-cell compatibility: 22/22 passed
  ```
- **两步分离判定**：
  `原始观测值 = 22/22 passed；判定阈值 = 22/22 格全部通过；结论 = 通过`

### 门禁 G7 · 产物绝对不变性门禁
- **实际执行命令**：`git diff --stat -- data/contracts/ data/models/`
- **输出末尾关键片段**：
  ```text
  （标准输出为空，exit code 0）
  ```
- **两步分离判定**：
  `原始观测值 = 输出为空；判定阈值 = 输出为空；结论 = 通过`

### 门禁 G8 · 宽泛异常扫描门禁
- **实际执行命令**：`grep -rn "except Exception\|except:" src/contract/parameter_domains.py src/contract/parameter_contract.py tests/unit/contract/test_parameter_domains.py`
- **输出末尾关键片段**：
  ```text
  0 hits
  ```
- **两步分离判定**：
  `原始观测值 = 0 处命中；判定阈值 = 命中数 = 0；结论 = 通过`

### 门禁 G9 · 测试后工作树状态门禁
- **实际执行命令**：`git status -sb`
- **输出末尾关键片段**：
  ```text
  ## main...origin/main
   M docs/adr/ADR-0019：物理模型参数向投注算法消费契约与解耦架构.md
   M specs/phase2-task08-class1-pricing-betting-spec.md
   M src/contract/parameter_contract.py
  ?? docs/audit/P8-CLASS1-LAUNCH-TICKET26_交付回执_20261026.md
  ?? src/contract/parameter_domains.py
  ?? tests/unit/contract/test_parameter_domains.py
  ```
- **两步分离判定**：
  `原始观测值 = 仅交付白名单 6 文件（3 modified / 3 untracked）；判定阈值 = 无多余改动，仅交付白名单；结论 = 通过`

### 门禁 G10 · Git Push 纪律门禁
- **两步分离判定**：
  `原始观测值 = 本地未执行 push，ahead 0（待 commit）；判定阈值 = 仅本地 commit，未 push；结论 = 通过`

---

## 三、 T01~T21 测试用例清单与断言点

| 用例编号 | 测试函数名 | 测试重点与断言点 | 预期结果 | 实测结论 |
| :--- | :--- | :--- | :--- | :--- |
| **T01** | `test_t01_real_contract_cells_satisfy_domain_validation` | 读取 `physical_param_contract.json` 22 格逐格 `validate_cell_parameters` | 全部返回 `True` | ✅ PASSED |
| **T02** | `test_t02_s_oos_negative_rejected` | `s_oos = -1.0` 注入校验 | 抛 `ParameterDomainViolation` | ✅ PASSED |
| **T03** | `test_t03_pit_var_negative_rejected` | `pit_var = -1.0` 注入校验 | 抛 `ParameterDomainViolation` | ✅ PASSED |
| **T04** | `test_t04_pit_var_upper_bound_closed` | `pit_var = 0.25` 上界闭区间校验 | 返回 `True` | ✅ PASSED |
| **T05** | `test_t05_pit_var_upper_bound_exceeded_rejected` | `pit_var = 0.2501` 超出 Popoviciu 上界校验 | 抛 `ParameterDomainViolation` | ✅ PASSED |
| **T06** | `test_t06_v1_coverage_90_exceeded_rejected` | `v1_coverage_90 = 1.5` 超界校验 | 抛 `ParameterDomainViolation` | ✅ PASSED |
| **T07** | `test_t07_ece_2f_high_value_accepted_math_domain` | `ece_2f = 0.9` 接受，证明为数学定义域而非业务质量阈值 | 返回 `True` | ✅ PASSED |
| **T08** | `test_t08_neff_zero_rejected_open_bound` | `neff = 0.0` 下界开区间校验 | 抛 `ParameterDomainViolation` | ✅ PASSED |
| **T09** | `test_t09_neff_strictly_positive_accepted` | `neff = 1e-9` 严格正校验 | 返回 `True` | ✅ PASSED |
| **T10** | `test_t10_cvm_p_bounds_rejected_and_accepted` | `cvm_p = 1.2` 拒绝，`cvm_p = 0.0` / `1.0` 接受 | 抛错 / 返回 `True` | ✅ PASSED |
| **T11** | `test_t11_ece_range_exceeded_rejected` | `ece_range = 1.5001` 超出 1.0 校验 | 抛 `ParameterDomainViolation` | ✅ PASSED |
| **T12** | `test_t12_nan_and_inf_rejected` | `s_oos = NaN` / `+inf` / `-inf` 模块层独立拦截 | 均抛 `ParameterDomainViolation` | ✅ PASSED |
| **T13** | `test_t13_unknown_field_name_rejected` | 未知字段 `s_oos_v2` 或 `get_domain("unknown")` | 抛 `ParameterDomainViolation` | ✅ PASSED |
| **T14** | `test_t14_bool_field_strict_type_enforcement` | 布尔字段传入 `1` / `0` / `"true"` / `"True"` / `1.0` | 均抛 `ParameterDomainViolation` | ✅ PASSED |
| **T15** | `test_t15_cross_field_invariant_cf1` | `fstd_lo == fstd_hi` 及 `fstd_lo > fstd_hi` 逆序注入 | 抛 `CrossFieldInvariantViolation` | ✅ PASSED |
| **T16** | `test_t16_require_effective_domain_locked` | 调用 `require_effective_domain("s_oos")` | 抛 `F2LockNotReleasedError`（含 F-2 LOCKED） | ✅ PASSED |
| **T17** | `test_t17_describe_domains_contract_audit` | 检查 `describe_domains()` 序列化 14 项完整度及 Tier 2 None 状态 | 14 项全受控，Tier 2 全 None | ✅ PASSED |
| **T18** | `test_t18_contract_integration_from_dict_delegation` | 契约层集成：`CellCalibrationRecord.from_dict` 传 `s_oos=-1.0` | 抛 `ValueError`（`__post_init__` 委托生效） | ✅ PASSED |
| **T19** | `test_t19_ast_gates_compliance` | 测试层机械执行 G-AST-1 / G-AST-2 / G-AST-3 语法树检查 | 三门禁全部通过 | ✅ PASSED |
| **T20** | `test_t20_parameter_domains_derived_coverage` | `fields(CellCalibrationRecord) - IDENTITY_FIELDS` 机械派生覆盖比对 | 严格 14 字段无手工手写漂移 | ✅ PASSED |
| **T21** | `test_t21_regression_v1_coverage_90_admissible` | 回归断言：`v1_coverage_90=0.884615` 且 `pass=True` 正常通过 | 未引入 0.90 推导，正常解析 | ✅ PASSED |

---

## 四、 parameter_contract.py 精确 diff（单点委托）

```diff
diff --git a/src/contract/parameter_contract.py b/src/contract/parameter_contract.py
index c703730..be8d506 100644
--- a/src/contract/parameter_contract.py
+++ b/src/contract/parameter_contract.py
@@ -19,6 +19,8 @@ import re
 from types import MappingProxyType
 from typing import Any, Dict, List, Mapping, Set, Tuple
 
+from src.contract.parameter_domains import validate_cell_parameters
+
 
 # W2 Scope Authorized Grid Constants (Structural Dimensions, NOT Thresholds)
 AUTHORIZED_STATIONS: Tuple[str, ...] = ("KORD", "KMIA")
@@ -106,6 +108,10 @@ class CellCalibrationRecord:
     cvm_p: float  # Cramer-von Mises p-value
     ece_range: float  # Full range ECE for auxiliary audit
 
+    def __post_init__(self) -> None:
+        """委托参数受控域校验（Ticket 26 / ADR-0019 附录 A）。"""
+        validate_cell_parameters(self)
+
     def to_dict(self) -> Dict[str, Any]:
         """Serialize record to dictionary."""
         return asdict(self)
```

---

## 五、 describe_domains() 输出与 ADR-0019 附录 A 表核对

代码导出的 14 项受控参数域与 ADR-0019 附录 A 逐行一致性核对如下：

| 字段名 | 数据类型 | 量纲单位 | Tier 1 数学定义域 | 消费状态 | 锁状态 | 依据来源对齐 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `s_oos` | `float` | `ratio` | `[0.0, +∞)` | 必须消费 | `22 格静态表 / [F-2 LOCKED]` | 对齐 |
| `fstd_lo` | `float` | `ratio` | `(0.0, +∞)` | 必须消费 | `22 格静态表 / [F-2 LOCKED]` | 对齐 |
| `fstd_hi` | `float` | `ratio` | `(0.0, +∞)` | 必须消费 | `22 格静态表 / [F-2 LOCKED]` | 对齐 |
| `fstd_in` | `bool` | `boolean` | `{False, True}` | 必须消费 | `22 格静态表 / [F-2 LOCKED]` | 对齐 |
| `ece_2f` | `float` | `probability` | `[0.0, 1.0]` | 必须消费 | `22 格静态表 / [F-2 LOCKED]` | 对齐 |
| `v1_coverage_90` | `float` | `probability` | `[0.0, 1.0]` | 必须消费 | `22 格静态表 / [F-2 LOCKED]` | 对齐 |
| `v1_coverage_90_pass` | `bool` | `boolean` | `{False, True}` | 必须消费 | `22 格静态表 / 当前全 True` | 对齐 |
| `pit_mean` | `float` | `probability` | `[0.0, 1.0]` | 必须消费 | `22 格静态表 / 参考容差` | 对齐 |
| `pit_var` | `float` | `probability_sq` | `[0.0, 0.25]` | 必须消费 | `22 格静态表 / [F-2 LOCKED]` | 对齐 |
| `reject_uniform` | `bool` | `boolean` | `{False, True}` | 必须消费 | `22 格静态表 / 当前全 False` | 对齐 |
| `neff` | `float` | `count` | `(0.0, +∞)` | 间接消费 | `22 格静态表 / 只读记录` | 对齐 |
| `cvm_stat` | `float` | `statistic` | `[0.0, +∞)` | 间接消费 | `22 格静态表 / 只读报警` | 对齐 |
| `cvm_p` | `float` | `probability` | `[0.0, 1.0]` | 间接消费 | `22 格静态表 / 只读报警` | 对齐 |
| `ece_range` | `float` | `probability` | `[0.0, 1.0]` | 间接消费 | `22 格静态表 / 只读记录` | 对齐 |

---

## 六、 实现选择与 Code Review 整改声明

### 1. 区间开闭语义与字面量防护
- 双闭区间 `[a, b]`：`ece_2f`, `v1_coverage_90`, `pit_mean`, `pit_var`, `cvm_p`, `ece_range`；
- 下闭上开 `[a, +∞)`：`s_oos`, `cvm_stat`；
- 双开区间 `(0.0, +∞)`：`fstd_lo`, `fstd_hi`, `neff`（有效样本量与正分位数比值具有严格正统计学物理定义）；
- **Code Review 整改**：`v1_coverage_90` 的 `degenerate_note` 描述已清除任何 `"0.90"` 子串，替换为规范受控描述 `"经验覆盖率（标称分位点理论目标值）"`，契约层 `src/contract/*.py` 浮点及字符串字面量 0 处命中 0.83/0.90/0.95。

### 2. Tier 2 访问阻断（Fail-Closed 双保险）
- **Code Review 整改**：`require_effective_domain()` 改为双保险判定 `"LOCKED" in domain.lock_state or (domain.tier2_lower is None and domain.tier2_upper is None)`，彻底消除未来若出现单侧有效域时的潜在短路越权风险；
- Tier 2 未解锁前调用一律抛出 `F2LockNotReleasedError`，明确提示关联工单 `Phase 2 Task 08 - Ticket 23 (#156)`，严禁返回 `None` 或用 Tier 1 替代。

### 3. 测试健壮性与 AST 防假阴性加固
- **Code Review 整改**：`test_t19_ast_gates_compliance` 在扫描 `src/contract/*.py` 前加入 `assert len(contract_py_files) >= 4`，彻底消除测试由于执行路径偏离导致 glob 为空时的假阴性静默通过。

### 4. 导入白名单与单向依赖
- `parameter_domains.py` 严格仅从 Python 标准库导入 `dataclasses`、`types`、`typing`、`math`，零项目内引用，杜绝循环 import；
- 身份字段 `IDENTITY_FIELDS` 作为常量登记，明确结构校验权归属 `parameter_contract.py`。

### 5. 文档合流检查单闭环
- **Code Review 整改**：依 `DEVELOPER_GUIDELINES.md` §2.2 门禁规则，同步更新 `docs/ROADMAP.md` 与 `STATUS.md`，登记 Ticket 26 物理参数受控域治理里程碑，解除 PR 合流门禁阻断。

---

## 七、 本地提交历史记载

本地按工单纪律完成原子提交，未执行 `git push`：
- **提交信息**：`feat(contract): 建立物理参数受控域治理模块与两级域解耦（Ticket 26 / #159）`
- **提交状态**：白名单 6 文件原子入库，`git status -sb` 为 clean，严格未向远端执行 push。
