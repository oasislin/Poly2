# P8-CLASS1-LAUNCH · Ticket 08 交易 EV 引擎与 S1 盘口穿透探针计算交付回执

> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **A 线关联票**：`Phase 2 Task 08 - Ticket 08: feat(pricing): 承接 Task 04 交易 EV 引擎并实现 S1 盘口穿透探针计算 (DR-2026-1014-01)`（[#141](https://github.com/oasislin/Poly2/issues/141)）  
> **执行日期**：2026-11-02  
> **开工基线**：`ca7b5c9` (`origin/main`)  
> **立法依据**：`docs/audit/P7-ALGO-2_规格书.md` L60-63（M1 定价引擎 + DR-2026-1014-01 裁决）  
> **提交纪律**：本地原子 commit，严格未授权不 push  

---

## 一、 交付物清单与代码改动

### 1. 交付物白名单（6 项完整闭环）
| 序号 | 交付物文件路径 | 性质 | 说明 |
| :--- | :--- | :--- | :--- |
| 1 | `src/pricing/penetration_probe.py` | **新建** | 交易 EV 引擎与穿透探针唯一实现处（纯函数计算、F-2 熔断挂锁、逐层含费边判定、先均价后折算、盘口单调递增校验） |
| 2 | `src/pricing/__init__.py` | **修改** | 追加导出 EV 探针符号与数据结构，更新包文档，保留既有覆盖率与 σ_adj 符号 |
| 3 | `tests/unit/pricing/test_penetration_probe.py` | **新建** | EV 探针全量测试集（T01~T16 共 16 组用例，含 R-1/R-2 反例与单调性聚合不变式） |
| 4 | `docs/audit/P8-CLASS1-LAUNCH-TICKET08_交付回执_20261102.md` | **新建** | 本交付回执（含 G1~G8 逐条执行证据、两步分离判定与 T01~T16 明细） |
| 5 | `STATUS.md` | **修改** | 同步活跃工作流中 Ticket 08 交付状态 |
| 6 | `docs/ROADMAP.md` | **修改** | 同步 Task 08 路线图中 Ticket 08 闭环进度（满足 PR 合流检查单） |

> **微整改独立隔离说明**：CHK-20 D-1/D-2 针对 Ticket 07 的微整改（`sigma_adj.py` 补充 `__all__` 与 `lock_state` 枚举归一化，及 `test_sigma_adj.py` 2 条验收门禁）已独立移至 Commit ②（`fix(pricing): Ticket 07 补 __all__ 与 lock_state 归一化`），Ticket 08 本身交付物严格保持上述 6 项。

**禁区与红线遵守情况**：
- `src/pricing/coverage_dual_track.py`：**零触碰，字节零变动**；
- `src/contract/**` 目录：**零触碰，字节零变动**；
- `data/**` 目录：**零触碰，字节零变动**；
- `evidence/**` 目录：**零触碰，字节零变动**；
- `scripts/evaluate_p4_2019_settlement.py`：**零触碰，字节零变动**；
- 复用 Ticket 07 的 `SigmaAdjLockState` 枚举，严禁建立第二套锁状态枚举；
- `src/pricing/penetration_probe.py` 内部浮点字面量严格仅有常量区 `FEE_BASE_RATIO = 0.05`（T13 AST 机械证据钉死）；
- 严格遵守立法条文 L61/L86 与 CHK-21 裁决口径：逐层判定采用含费边 $q_{\text{eff},j} = p_j \cdot [1 + 0.05 \cdot (1 - p_j)]$ 与 $\text{edge}_j = (\hat p - q_{\text{eff},j})/q_{\text{eff},j} \ge \text{min\_edge}$；聚合仍为纯价格深度加权均价 $\bar P$ 后一次性折算，严禁逐层费率非线性迭代；
- `compute_probe` 在 `lock_state != SigmaAdjLockState.RELEASED` 时强拦截抛 `F2LockNotReleasedError`，杜绝未解锁求值；
- `AskBook` 严格校验价格自最优价（最低卖价）向下单调递增，违反抛 `InvalidOrderBookError`。

---

## 二、 验收门禁 G1~G8 实测证据（两步分离判定 · 开发端自测）

> **采集主体标注**：以下数值均为**开发端本机实测自测值**，采集自同一代码树快照。

### 门禁 G1 · Ticket 08 专属测试门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing/test_penetration_probe.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_penetration_probe.py ................            [100%]
  ============================== 16 passed in 0.05s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 16 passed in 0.05s（开发端自测）；判定阈值 = 全绿，≥ 14 用例；结论 = 通过`

### 门禁 G2 · 定价模块全量测试门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [ 29%]
  tests/unit/pricing/test_penetration_probe.py ................            [ 62%]
  tests/unit/pricing/test_sigma_adj.py ..................                  [100%]
  ============================== 48 passed in 1.35s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 48 passed in 1.35s（开发端自测）；判定阈值 = 全绿，≥ 44 用例；结论 = 通过`

### 门禁 G3 · 全链路跨层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [ 87%]
  tests/unit/pricing/test_penetration_probe.py ................            [ 93%]
  tests/unit/pricing/test_sigma_adj.py ..................                  [100%]
  ============================= 280 passed in 3.92s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 280 passed in 3.92s（开发端自测，交叉核账 232 + 48 = 280）；判定阈值 = 全绿，≥ 276 用例；结论 = 通过`

### 门禁 G4 · AST 函数长度扫描门禁（`src/pricing/` 与新测试）
- **实际执行命令**：
  ```bash
  python3 -c "
  import ast, glob
  files = sorted(glob.glob('src/pricing/**/*.py', recursive=True) + glob.glob('tests/unit/pricing/**/*.py', recursive=True))
  lens = []
  for f in files:
      tree = ast.parse(open(f).read(), filename=f)
      funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
      lens.extend([(f, fn.name, fn.end_lineno - fn.lineno + 1) for fn in funcs])
  max_l = max(l[2] for l in lens) if lens else 0
  over_50 = sum(1 for l in lens if l[2] >= 50)
  top_funcs = sorted(lens, key=lambda x: x[2], reverse=True)[:3]
  print(f'scanned {len(files)} files, funcs {len(lens)}, max = {max_l}, over_50 = {over_50}')
  for tf in top_funcs:
      print('TOP:', tf)
  "
  ```
- **输出末尾关键片段**：
  ```text
  scanned 8 files, funcs 66, max = 42, over_50 = 0
  TOP: ('tests/unit/pricing/test_coverage_dual_track.py', 'test_t05_exact_track_misuse_online_pricing', 42)
  TOP: ('tests/unit/pricing/test_coverage_dual_track.py', 'test_t11_coverage_rate_perfect_and_zero_hits', 41)
  TOP: ('src/pricing/coverage_dual_track.py', 'bounds', 39)
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
- **实际执行命令**：`git diff --stat ca7b5c9 -- data/ evidence/ src/contract/ src/pricing/coverage_dual_track.py scripts/evaluate_p4_2019_settlement.py`
- **输出末尾关键片段**：
  ```text
  （标准输出为空，exit code 0）
  ```
- **两步分离判定**：
  `原始观测值 = 标准输出为空（开发端自测）；判定阈值 = 输出为空；结论 = 通过`

### 门禁 G7 · 工作树仅白名单文件改动门禁
- **实际执行命令**：`git status -sb`
- **两步分离判定**：
  `原始观测值 = 按计划分立原子 commit 后工作树 clean；判定阈值 = 仅白名单文件变动；结论 = 通过`

### 门禁 G8 · Git Push 纪律核验
- **判定逻辑**：严格遵从人工指令。Commit ① 经人工授权 push 至远端；Commit ② 与 Commit ③ 严格保持本地（ahead 2），等待复核签发。
- **两步分离判定**：
  `原始观测值 = Commit ② 与 ③ 保持本地 ahead 2 未推送；判定阈值 = 代码 commit 严格未 push；结论 = 通过`

---

## 三、 T01~T16 测试清单覆盖明细

- **T01**：单层盘口下 `edge_0 >= min_edge` 达标判定（含费边 $q_{\text{eff}} = 0.412$），`s_target = 150.0`，`p_bar = 0.40`；
- **T02**：多层盘口下仅达标层计入容量与均价（$0.40$ 层达标，$0.48$ 与 $0.52$ 层含费边未达标被严格排除），`qualified_levels = (0,)`，`s_target = 100.0`，`p_bar = 0.40`；
- **T03**：$\bar P$ 深度加权均价精度断言，与手算公式偏差 $\le 10^{-12}$；
- **T04**：$q_{\text{eff}} = \bar P \cdot [1 + 0.05 \cdot (1 - \bar P)]$ 费率公式精度断言，与理论值偏差 $\le 10^{-12}$；
- **T05**：费后口径 $\text{net\_ev} = \hat p - q_{\text{eff}}$ 与 $\text{edge} = \text{net\_ev} / q_{\text{eff}}$ 计算，偏差 $\le 10^{-12}$；
- **T06**：$\hat p = a_j$ 边界测试，含费边 $q_{\text{eff}} = 0.5125$，$\text{edge} < 0 < \text{min\_edge}$ 被严格排除；
- **T07**：全层未达标时 Fail-Closed 强抛 `NoQualifiedLevelsError`，严禁返回 0 值；
- **T08**：`load_penetration_policy()` 强抛 `F2LockNotReleasedError` 且异常信息明确包含 `#156`；
- **T09**：外部构造 `lock_state="F-2 LOCKED"` 及 `SigmaAdjLockState.LOCKED` 策略传入 `compute_probe` 均强抛 `F2LockNotReleasedError`；
- **T10**：非法策略属性（$\text{min\_edge} < 0$、非有限值）强抛 `InvalidPenetrationPolicyError`；
- **T11**：非法概率 $\hat p \in \{0.0, 1.0, -0.1, 1.5, \text{nan}, \text{inf}\}$ 强抛 `InvalidProbabilityError`；
- **T12**：非法订单簿（空盘口、未严格按价格递增排序、$\text{size} \le 0$、$\text{price} \notin (0, 1)$）强抛 `InvalidOrderBookError`；
- **T13**：AST 静态扫描确认 `src/pricing/penetration_probe.py` 浮点字面量严格仅包含常量区 `0.05`；
- **T14**：逐层不变式验证：遍历所有盘口层，断言达标层必定满足含费边 $\text{edge}_j \ge \text{min\_edge}$，未达标层必定满足 $\text{edge}_j < \text{min\_edge}$；
- **T15**：F-2 异常继承与命名空间别名验证：`F2LockNotReleasedError` 同时继承 `PenetrationError` 与 `SigmaAdjF2LockNotReleasedError`，`src.pricing` 统一导出别名；
- **T16**：聚合不变式与 R-1/R-2 反例门禁：
  - R-1：单层 `((0.50, 300))` 在 $\hat p=0.52, \text{min\_edge}=0.02$ 下含费边未达标，强抛 `NoQualifiedLevelsError`，杜绝容量高估与自相矛盾；
  - R-2：多层 `((0.40, 100), (0.45, 200), (0.50, 300))` 在 $\hat p=0.52$ 下排除 0.50 层，容量严格收敛为 `300.0`（非高估的 600.0）；
  - 单调性不变式：任意成功返回的 `ProbeResult` 严格满足 `res.edge >= policy.min_edge`。
