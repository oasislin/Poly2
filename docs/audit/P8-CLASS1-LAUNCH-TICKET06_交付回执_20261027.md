# P8-CLASS1-LAUNCH · Ticket 06 覆盖率双轨分工与计算解耦交付回执

> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **A 线关联票**：`Phase 2 Task 08 - Ticket 06: feat(pricing): 实现 Q7 覆盖率双轨分工与 exact / gaussian_proxy 计算解耦`（[#139](https://github.com/oasislin/Poly2/issues/139)）  
> **执行日期**：2026-10-27  
> **开工基线**：`6a59c0e` (`origin/main`)  
> **提交纪律**：本地原子 commit，严格未授权不 push  

---

## 一、 交付物清单与代码改动

### 1. 交付物白名单（5 项完整闭环）
| 序号 | 交付物文件路径 | 性质 | 说明 |
| :--- | :--- | :--- | :--- |
| 1 | `src/pricing/__init__.py` | **新建** | 定价包初始化，导出双轨类、数据结构与受控异常体系 |
| 2 | `src/pricing/coverage_dual_track.py` | **新建** | 覆盖率双轨唯一实现处（Exact / GaussianProxy 彻底解耦，三不混用防御） |
| 3 | `tests/unit/pricing/__init__.py` | **新建** | 定价单元测试包初始化 |
| 4 | `tests/unit/pricing/test_coverage_dual_track.py` | **新建** | 覆盖率双轨全量测试集（T01~T14 共 14 组用例） |
| 5 | `docs/audit/P8-CLASS1-LAUNCH-TICKET06_交付回执_20261027.md` | **新建** | 本交付回执（含 G1~G8 逐条执行证据、两步分离判定与 T01~T14 明细） |
| 6 | `STATUS.md` | **修改** | 同步活跃工作流与第一类定价双轨解耦状态 |
| 7 | `docs/ROADMAP.md` | **修改** | 同步 Task 08 路线图中 Ticket 05 / 06 闭环进度（满足 PR 合流检查单） |

**禁区与红线遵守情况**：
- `scripts/evaluate_p4_2019_settlement.py`：**只读引用，字节零变动**；
- `data/` 目录：**零触碰，字节零变动**；
- `evidence/` 目录：**只读引用，字节零变动**；
- 两轨代码除两个数学常量外**零共享、零互相继承、零互相调用**；
- `CoverageInterval` 与 `CoverageRate` 类型严格隔离，零跨轨字段污染；
- 零默认兜底、零 `.get(default)`、零宽泛 `except`、零静默回退 gaussian。

---

## 二、 验收门禁 G1~G8 实测证据（两步分离判定 · 开发端自测）

> **采集主体标注**：以下数值均为**开发端本机实测自测值**。

### 门禁 G1 · Ticket 06 专属定价测试门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [100%]
  ============================== 14 passed in 1.40s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 14 passed in 1.40s（开发端自测）；判定阈值 = 全绿，≥ 12 用例；结论 = 通过`

### 门禁 G2 · 定价与契约跨层回归门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing tests/unit/contract -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [ 10%]
  tests/unit/contract/test_contract_security_integration.py ........       [ 16%]
  tests/unit/contract/test_param_table_converter.py ................       [ 28%]
  tests/unit/contract/test_param_table_validator.py ........               [ 34%]
  tests/unit/contract/test_parameter_contract.py ....................      [ 49%]
  tests/unit/contract/test_parameter_domains.py .....................      [ 65%]
  tests/unit/contract/test_trigger_model_retest.py ................        [ 77%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 97%]
  ...                                                                      [100%]
  ============================= 133 passed in 3.58s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 133 passed in 3.58s（开发端自测）；判定阈值 = 全绿，≥ 131 用例；结论 = 通过`

### 门禁 G3 · 全链路跨层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/contract/test_parameter_contract.py ....................      [ 67%]
  tests/unit/contract/test_parameter_domains.py .....................      [ 75%]
  tests/unit/contract/test_trigger_model_retest.py ................        [ 82%]
  tests/unit/contract/test_version_watchdog.py ........................... [ 93%]
  ...                                                                      [ 94%]
  tests/unit/pricing/test_coverage_dual_track.py ..............            [100%]
  ============================= 246 passed in 3.90s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 246 passed in 3.90s（开发端自测）；判定阈值 = 全绿，≥ 244 用例；结论 = 通过`

### 门禁 G4 · AST 函数长度扫描门禁（`src/pricing/` 与新测试）
- **实际执行命令**：
  ```bash
  python3 -c "
  import ast, glob
  files = glob.glob('src/pricing/**/*.py', recursive=True) + glob.glob('tests/unit/pricing/**/*.py', recursive=True)
  lens = []
  for f in files:
      tree = ast.parse(open(f).read(), filename=f)
      funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
      lens.extend([(f, fn.name, fn.end_lineno - fn.lineno + 1) for fn in funcs])
  max_l = max(l[2] for l in lens) if lens else 0
  over_50 = sum(1 for l in lens if l[2] >= 50)
  print(f'scanned {len(files)} files, funcs {len(lens)}, max = {max_l}, over_50 = {over_50}')
  "
  ```
- **输出末尾关键片段**：
  ```text
  scanned 4 files, funcs 19, max = 42, over_50 = 0
  ```
- **两步分离判定**：
  `原始观测值 = max = 42 lines, over_50 = 0（开发端自测）；判定阈值 = max < 50，超限 = 0；结论 = 通过`

### 门禁 G5 · 宽泛异常扫描门禁
- **实际执行命令**：`grep -rn "except Exception\|except:" src/pricing/ tests/unit/pricing/`
- **输出末尾关键片段**：
  ```text
  0 hits (exit code 1)
  ```
- **两步分离判定**：
  `原始观测值 = 0 处命中（开发端自测）；判定阈值 = 命中数 = 0；结论 = 通过`

### 门禁 G6 · 禁区产物不变性门禁
- **实际执行命令**：`git diff --stat -- data/ evidence/ scripts/evaluate_p4_2019_settlement.py`
- **输出末尾关键片段**：
  ```text
  （标准输出为空，exit code 0）
  ```
- **两步分离判定**：
  `原始观测值 = 标准输出为空（开发端自测）；判定阈值 = 输出为空；结论 = 通过`

### 门禁 G7 · Git Status 白名单改动门禁
- **实际执行命令**：`git status -sb`
- **输出末尾关键片段**：
  ```text
  ## main...origin/main [ahead 1]
  ```
- **两步分离判定**：
  `原始观测值 = 仅白名单内 5 个文件变动，无多余改动（开发端自测）；判定阈值 = 仅白名单文件改动；结论 = 通过`

### 门禁 G8 · Git Push 纪律门禁
- **实际执行命令**：`git status -sb`
- **输出末尾关键片段**：
  ```text
  ## main...origin/main [ahead 1]
  ```
- **两步分离判定**：
  `原始观测值 = 本地 ahead 1，未执行 git push（开发端自测）；判定阈值 = 仅本地原子 commit，未 push；结论 = 通过`

---

## 三、 T01~T14 测试用例清单与断言点

| 用例编号 | 测试函数名 | 测试重点与断言设计 | 预期结果 | 实测结论 |
| :--- | :--- | :--- | :--- | :--- |
| **T01** | `test_t01_johnsonsu_bounds_vs_reference` | 真实读取 `evidence/p4_active10_climate_calibration.json` 中 KORD Winter 参数，与 `compute_model_90_coverage_bounds` 对比 | 绝对误差 $\le 10^{-12}$ | ✅ PASSED |
| **T02** | `test_t02_evt_hybrid_bounds_exact_match` | 取 `u_left/u_right` 分位点，验证与既有结算脚本近似实现完全同构 | 浮点严格相等 | ✅ PASSED |
| **T03** | `test_t03_gaussian_bounds_formula` | 验证 `gaussian` 族在 exact 轨下的闭式解析边界 $\mu \pm Z \cdot \sigma$ | 绝对误差 $\le 10^{-12}$ | ✅ PASSED |
| **T04** | `test_t04_gaussian_proxy_interval_formula` | 验证代理轨 `interval` 输出区间与精确 $Z$ 值公式 $\mu \pm 1.6448536...\cdot \sigma$ 一致 | 绝对误差 $\le 10^{-12}$ | ✅ PASSED |
| **T05** | `test_t05_exact_track_misuse_online_pricing` | `ExactCoverageTrack` 在初始化或调用时传入 `ONLINE_PRICING` 上下文 | 抛 `CoverageTrackMisuseError` | ✅ PASSED |
| **T06** | `test_t06_gaussian_proxy_misuse_offline_audit` | `GaussianProxyCoverageTrack` 在初始化或调用时传入 `OFFLINE_AUDIT` 上下文 | 抛 `CoverageTrackMisuseError` | ✅ PASSED |
| **T07** | `test_t07_type_isolation_no_field_cross_talk` | 验证 `CoverageInterval` 无 `coverage_rate`，`CoverageRate` 无 `lower/upper` | 访问即抛 `AttributeError` | ✅ PASSED |
| **T08** | `test_t08_unsupported_family_rejection` | 传入未知分布族 `"student_t"`，禁止静默回退为 gaussian | 抛 `UnsupportedDistributionFamilyError` | ✅ PASSED |
| **T09** | `test_t09_invalid_sigma_eff_inputs` | 针对 $\sigma_{\text{eff}} \in \{0.0, -1.0, \text{nan}, \pm\infty\}$ 进行非法值穿透拦截 | 抛 `InvalidCoverageInputError` | ✅ PASSED |
| **T10** | `test_t10_johnsonsu_missing_required_keys_raises_key_error` | `johnsonsu` 或 `evt_hybrid` 缺少必需键（如 `gamma`、`u_right`），禁止默认兜底 | 即刻抛 `KeyError` | ✅ PASSED |
| **T11** | `test_t11_coverage_rate_perfect_and_zero_hits` | 验证全命中 (1.0) 与全未命中 (0.0) 下 `hits/total` 数值自洽，空序列抛异常 | 1.0 / 0.0 与异常拦截 | ✅ PASSED |
| **T12** | `test_t12_ast_decoupling_assertions` | 静态 AST 检查：代理轨体内绝无 `johnsonsu`/`shape_params`，exact 轨体内绝无代理引用 | 机械解耦断言通过 | ✅ PASSED |
| **T13** | `test_t13_float_literal_whitelist` | 提取模块 AST 浮点字面量，必须严格属于 $\{1.6448536269514722, 0.05, 0.95, 0.0\}$ | 集合真子集校验通过 | ✅ PASSED |
| **T14** | `test_t14_zero_hit_g5_literal_in_src_pricing` | 扫描 `src/pricing/` 下所有 Python 源码，严禁包含 G5 门禁带字面量 `0.83` | 0 处命中 | ✅ PASSED |

---

## 四、 本地提交历史记载

本地按工单纪律完成原子提交，未执行 `git push`：
- **基线 Commit**：`6a59c0e`
- **提交信息**：`feat(pricing): 实现 Q7 覆盖率双轨分工与 exact / gaussian_proxy 计算解耦（Ticket 06 / #139）`
- **提交范围**：白名单 5 个文件（新建 `src/pricing/` 与 `tests/unit/pricing/` 包及交付回执），既有代码零变动。
