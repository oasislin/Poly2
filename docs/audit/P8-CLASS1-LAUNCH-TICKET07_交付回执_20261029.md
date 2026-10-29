# P8-CLASS1-LAUNCH · Ticket 07 定价端方差自适应膨胀 σ_adj 计算引擎交付回执

> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **A 线关联票**：`Phase 2 Task 08 - Ticket 07: feat(pricing): 实现基于 s_oos 的定价端方差自适应膨胀 σ_adj 计算引擎`（[#140](https://github.com/oasislin/Poly2/issues/140)）  
> **执行日期**：2026-10-29  
> **开工基线**：`2f1a886` (`origin/main`)  
> **提交纪律**：本地原子 commit，严格未授权不 push  

---

## 一、 交付物清单与代码改动

### 1. 交付物白名单（6 项完整闭环）
| 序号 | 交付物文件路径 | 性质 | 说明 |
| :--- | :--- | :--- | :--- |
| 1 | `src/pricing/sigma_adj.py` | **新建** | σ_adj 计算引擎唯一实现处（纯函数计算、F-2 熔断挂锁、零浮点字面量） |
| 2 | `src/pricing/__init__.py` | **修改** | 追加导出 σ_adj 引擎符号，保留既有覆盖率双轨符号 |
| 3 | `tests/unit/pricing/test_sigma_adj.py` | **新建** | σ_adj 全量测试集（T01~T16 共 16 组用例） |
| 4 | `docs/audit/P8-CLASS1-LAUNCH-TICKET07_交付回执_20261029.md` | **新建** | 本交付回执（含 G1~G8 逐条执行证据、两步分离判定与 T01~T16 明细） |
| 5 | `STATUS.md` | **修改** | 同步活跃工作流中 Ticket 07 交付状态 |
| 6 | `docs/ROADMAP.md` | **修改** | 同步 Task 08 路线图中 Ticket 07 闭环进度（满足 PR 合流检查单） |

**禁区与红线遵守情况**：
- `src/pricing/coverage_dual_track.py`：**零触碰，字节零变动**；
- `src/contract/**` 目录：**零触碰，字节零变动**；
- `data/**` 目录：**零触碰，字节零变动**；
- `evidence/**` 目录：**零触碰，字节零变动**；
- `scripts/evaluate_p4_2019_settlement.py`：**零触碰，字节零变动**；
- `src/pricing/sigma_adj.py` 内部浮点字面量命中数 = 0（T16 AST 机械证据已钉死）；
- `compute_sigma_adj` 在 `lock_state == "F-2 LOCKED"` 状态下强拦截抛 `F2LockNotReleasedError`，杜绝返回任何数值；
- 模块不涉及 `ψ(s_oos)`、`S_conf`、`s_oos < 0.70` 准入门禁；
- `sigma_adj_for_cell` 严格走 `contract.get_cell(station, lead_hours)`，严禁跨格聚合与均值化。

---

## 二、 验收门禁 G1~G8 实测证据（两步分离判定 · 开发端自测）

> **采集主体标注**：以下数值均为**开发端本机实测自测值**。

### 门禁 G1 · Ticket 07 专属测试门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing/test_sigma_adj.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_sigma_adj.py ................                    [100%]
  ============================== 16 passed in 0.05s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 16 passed in 0.05s（开发端自测）；判定阈值 = 全绿，≥ 16 用例；结论 = 通过`

### 门禁 G2 · 定价模块全量测试门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [ 46%]
  tests/unit/pricing/test_sigma_adj.py ................                    [100%]
  ============================== 30 passed in 1.48s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 30 passed in 1.48s（开发端自测）；判定阈值 = 全绿，≥ 30 用例；结论 = 通过`

### 门禁 G3 · 全链路跨层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [ 93%]
  tests/unit/pricing/test_sigma_adj.py ................                    [100%]
  ============================= 262 passed in 3.66s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 262 passed in 3.66s（开发端自测）；判定阈值 = 全绿，≥ 262 用例；结论 = 通过`

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
  scanned 6 files, funcs 42, max = 42, over_50 = 0
  ```
- **两步分离判定**：
  `原始观测值 = max = 42 lines, over_50 = 0（开发端自测）；判定阈值 = max < 50，超限 = 0；结论 = 通过`

### 门禁 G5 · 宽泛异常扫描门禁
- **实际执行命令**：`grep -rn "except Exception\|except:" src/pricing/sigma_adj.py tests/unit/pricing/test_sigma_adj.py`
- **输出末尾关键片段**：
  ```text
  0 hits (exit code 1)
  ```
- **两步分离判定**：
  `原始观测值 = 0 处命中（开发端自测）；判定阈值 = 命中数 = 0；结论 = 通过`

### 门禁 G6 · 禁区产物不变性门禁
- **实际执行命令**：`git diff --stat -- data/ evidence/ src/contract/ src/pricing/coverage_dual_track.py scripts/evaluate_p4_2019_settlement.py`
- **输出末尾关键片段**：
  ```text
  （标准输出为空，exit code 0）
  ```
- **两步分离判定**：
  `原始观测值 = 标准输出为空（开发端自测）；判定阈值 = 输出为空；结论 = 通过`

### 门禁 G7 · 工作树仅白名单文件改动门禁
- **实际执行命令**：`git status -sb`
- **输出末尾关键片段**：
  ```text
  ## main...origin/main
   M STATUS.md
   M docs/ROADMAP.md
   M src/pricing/__init__.py
  ?? docs/audit/P8-CLASS1-LAUNCH-TICKET07_交付回执_20261029.md
  ?? src/pricing/sigma_adj.py
  ?? tests/unit/pricing/test_sigma_adj.py
  ```
- **两步分离判定**：
  `原始观测值 = 仅白名单中 6 个文件改动/新建（开发端自测）；判定阈值 = 仅白名单文件改动；结论 = 通过`

### 门禁 G8 · Git Push 纪律核验
- **判定逻辑**：严禁自动 push，必须且仅在用户明确发出指令时执行。
- **两步分离判定**：
  `原始观测值 = 未执行 git push，待 commit 并等待用户指令；判定阈值 = 严格未 push；结论 = 通过`

---

## 三、 T01~T16 测试清单覆盖明细

- **T01**：注入策略 `(0.5, 1.0, F2_RELEASED)`，22 格真实 `s_oos` 全量比对与 `math.sqrt(max(1.0, s_oos))` 差 $\le 10^{-12}$；
- **T02**：`KORD_12h / 36h / 60h / 66h` 4 格 `s_oos < 1.0` 逐格验证 `σ_adj == σ_eff`（浮点精确恒等）；
- **T03**：`KMIA_30h` 最大比值点实测 `ratio = 1.167832`，差 $\le 10^{-6}$；
- **T04**：`s_oos = 1.0` 临界点精确恒等 `σ_adj == σ_eff`；
- **T05**：`s_oos ∈ [0.0, 0.5, 1.0, 1.2, 1.5, 2.0]` 严格单调非降；
- **T06**：`s_oos = 0.0` 地板保护生效，精确恒等 `σ_adj == σ_eff`；
- **T07**：`σ_eff` 加倍 $\to$ `σ_adj` 精确加倍（比值 = 2.0）；
- **T08**：退化性断言：注入 `(0.5, 1.0)` 与 ADR-0019 §4 公式在多组测试点差 $\le 10^{-12}$；
- **T09**：`σ_eff ∈ {0.0, -1.0, nan, inf, -inf}` 强拦截抛 `InvalidSigmaAdjInputError`；
- **T10**：`s_oos ∈ {-1.0, nan, inf, -inf}` 强拦截抛 `InvalidSigmaAdjInputError`；
- **T11**：`sigma_adj_for_cell` 查询未知站点 `("KATL", 12)` 强抛 `KeyError`，绝不回退它格；
- **T12**：22 格逐格比对 `sigma_adj_for_cell` vs `compute_sigma_adj` 差 $\le 10^{-12}$，实证零跨格聚合与均值化；
- **T13**：`load_sigma_adj_policy()` 强抛 `F2LockNotReleasedError` 且异常信息明确包含 `#156`；
- **T14**：外部构造 `lock_state="F-2 LOCKED"` 策略传入 `compute_sigma_adj` 强抛 `F2LockNotReleasedError`；
- **T15**：非法策略属性（`exponent <= 0`、`floor < 1.0`、非有限值、非法 `lock_state`）强抛 `InvalidSigmaAdjPolicyError`；
- **T16**：AST 静态扫描确认 `src/pricing/sigma_adj.py` 内部浮点字面量命中数恒等于 0（数值挂锁机械证据）。
