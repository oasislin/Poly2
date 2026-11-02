# P8-CLASS1-LAUNCH · Ticket 09 覆盖率双轨三不混用与探针定价单测集交付回执

> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **A 线关联票**：`Phase 2 Task 08 - Ticket 09: test(pricing): 覆盖率双轨三不混用与探针定价单测集`（[#142](https://github.com/oasislin/Poly2/issues/142)）  
> **执行日期**：2026-11-02  
> **开工基线**：`b61372d` (`origin/main` 已对齐)  
> **立法依据**：`docs/audit/P7-ALGO-2_规格书.md` L60-63 / L86 / L154 / L159-162；`ADR-0019` §4-§5；`CHK-21` §4.4 口径裁定；`CHK-22` 冻结结论；`P8-CLASS1-LAUNCH-TICKET09_开发工作单_20261102.md`  
> **提交纪律**：本地原子 commit，严格未授权不 push  
> **采集主体标注**：以下数值均为**开发端本机实测自测值**（采集自同一代码树快照）。

---

## 一、 交付物清单与禁区声明

### 1. 交付物白名单（4 项完整闭环）
| 序号 | 交付物文件路径 | 性质 | 说明 |
| :--- | :--- | :--- | :--- |
| 1 | `tests/unit/pricing/test_order_probe_evaluator.py` | **新建** | 定价层跨模块契约与不变式测试集（T01~T12 全部通过） |
| 2 | `docs/audit/P8-CLASS1-LAUNCH-TICKET09_交付回执_20261102.md` | **新建** | 本交付回执（含 G1~G8 逐条执行证据、两步分离判定与 T01~T12 明细） |
| 3 | `STATUS.md` | **修改** | 同步活跃工作流中 Ticket 09 交付状态 |
| 4 | `docs/ROADMAP.md` | **修改** | 同步 Task 08 路线图中 Ticket 09 闭环进度（满足 PR 合流检查单） |

### 2. 禁区产物与红线遵守情况
- `src/**` 全目录（含 `coverage_dual_track.py` / `sigma_adj.py` / `penetration_probe.py` / `__init__.py`）：**零改动，字节零变动**；
- `scripts/**` 全目录：**零改动，字节零变动**；
- `data/**` 全目录：**零改动，字节零变动**（只读消费）；
- `evidence/**` 全目录：**零改动，字节零变动**（只读消费）；
- `tests/unit/pricing/` 既有测试文件（`test_coverage_dual_track.py` / `test_sigma_adj.py` / `test_penetration_probe.py`）：**零改动，字节零变动**；
- 零魔法数：断言中的费率、分位、名义覆盖水平严格引用模块导出符号（`FEE_BASE_RATIO` / `Z_90_HALF_WIDTH` / `NOMINAL_INTERVAL_LEVEL`）；
- 零宽泛异常：测试文件无 `except Exception` 与裸 `except`；
- 零 mock 外部契约：参数契约与定标数据只读加载，无 `monkeypatch` 篡改熔断。
- 缺陷上报：**无**（现有实现完全满足 T01~T12 全部契约断言，无暴露底层实现缺陷）。

---

## 二、 验收门禁 G1~G8 实测证据（两步分离判定 · 开发端自测）

### 门禁 G1 · Ticket 09 专属测试门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing/test_order_probe_evaluator.py -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_order_probe_evaluator.py ............            [100%]
  ============================== 12 passed in 1.31s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 12 passed in 1.31s（开发端自测）；判定阈值 = 全绿，≥ 12 用例；结论 = 通过`

### 门禁 G2 · 定价模块全量测试门禁
- **实际执行命令**：`python -m pytest tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [ 23%]
  tests/unit/pricing/test_order_probe_evaluator.py ............            [ 43%]
  tests/unit/pricing/test_penetration_probe.py ................            [ 70%]
  tests/unit/pricing/test_sigma_adj.py ..................                  [100%]
  ============================== 60 passed in 1.29s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 60 passed in 1.29s（开发端自测）；判定阈值 = 全绿，≥ 60 用例；结论 = 通过`

### 门禁 G3 · 全链路跨层全量回归门禁
- **实际执行命令**：`python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q`
- **输出末尾关键片段**：
  ```text
  tests/unit/pricing/test_coverage_dual_track.py ..............            [ 84%]
  tests/unit/pricing/test_order_probe_evaluator.py ............            [ 88%]
  tests/unit/pricing/test_penetration_probe.py ................            [ 93%]
  tests/unit/pricing/test_sigma_adj.py ..................                  [100%]
  ============================= 292 passed in 3.66s ==============================
  ```
- **两步分离判定**：
  `原始观测值 = 292 passed in 3.66s（开发端自测，交叉核账：预测/风控/契约 232 + 定价 60 = 292）；判定阈值 = 全绿，≥ 292 用例；结论 = 通过`

### 门禁 G4 · AST 函数长度扫描门禁（`src/pricing/` 与全部定价测试）
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
  scanned 9 files, funcs 80, max = 42, over_50 = 0
  TOP: ('tests/unit/pricing/test_coverage_dual_track.py', 'test_t05_exact_track_misuse_online_pricing', 42)
  TOP: ('tests/unit/pricing/test_coverage_dual_track.py', 'test_t11_coverage_rate_perfect_and_zero_hits', 41)
  TOP: ('src/pricing/coverage_dual_track.py', 'bounds', 39)
  ```
- **两步分离判定**：
  `原始观测值 = max = 42 lines, over_50 = 0, 新测单个函数最大 31 行（开发端自测）；判定阈值 = max < 50，超限 = 0，新测 <= 45；结论 = 通过`

### 门禁 G5 · 宽泛异常扫描门禁
- **实际执行命令**：`grep -rn "except Exception\|except:" src/pricing/ tests/unit/pricing/`
- **输出末尾关键片段**：
  ```text
  0 hits (exit code 1)
  ```
- **两步分离判定**：
  `原始观测值 = 0 处命中（开发端自测）；判定阈值 = 命中数 = 0；结论 = 通过`

### 门禁 G6 · 禁区产物不变性门禁（基线 `b61372d`）
- **实际执行命令**：`git diff --stat b61372d -- src/ scripts/ data/ evidence/`
- **输出末尾关键片段**：
  ```text
  （标准输出为空，exit code 0）
  ```
- **两步分离判定**：
  `原始观测值 = 标准输出为空（开发端自测）；判定阈值 = 输出为空；结论 = 通过`

### 门禁 G7 · 工作树白名单变动与收敛门禁
- **实际执行命令**：`git status -sb`
- **输出末尾关键片段**：
  ```text
  ## main...origin/main
   M STATUS.md
   M docs/ROADMAP.md
  ?? docs/audit/P8-CLASS1-LAUNCH-TICKET09_交付回执_20261102.md
  ?? tests/unit/pricing/test_order_probe_evaluator.py
  ```
- **两步分离判定**：
  `原始观测值 = 仅白名单 4 文件变动/新建（开发端自测）；判定阈值 = 仅白名单 4 文件变动；结论 = 通过`

### 门禁 G8 · Git Push 纪律核验
- **判定逻辑**：严禁自动 push，必须且仅在收到用户明确指令时方可推送。本票提交严格保持本地。
- **两步分离判定**：
  `原始观测值 = 本票代码与文档提交保持本地，未执行 git push；判定阈值 = 严格未 push；结论 = 通过`

---

## 三、 T01~T12 测试清单覆盖与断言明细

| 编号 | 组别 | 断言对象与数据源 | 断言内容与判定逻辑 | 实测结果 |
|:---|:---|:---|:---|:---|
| **T01** | A 组 | 双轨口径防混用（模块符号） | `ExactCoverageTrack.bounds/coverage` 传 `ONLINE_PRICING`、`None`、裸串均抛 `CoverageTrackMisuseError`；`GaussianProxyCoverageTrack.interval` 传 `OFFLINE_AUDIT`、`None`、裸串均抛错 | **通过** |
| **T02** | A 组 | 构造期上下文强约束（模块符号） | 构造器传入跨轨/裸串 context 均强拦截抛 `CoverageTrackMisuseError`；传合法匹配 context 正常实例化 | **通过** |
| **T03** | A 组 | 类型与 AST 子树强隔离（源码 AST） | `CoverageInterval` 无 `coverage_rate`，`CoverageRate` 无 `lower/upper`，双轨类互不继承；按 `ast.ClassDef` 子树统计，代理轨子树对 exact 符号命中 = 0，exact 轨子树对代理轨符号命中 = 0 | **通过** |
| **T04** | A 组 | exact 轨行为等价（`evidence/` + 冻结脚本） | 对 `johnsonsu`、`evt_hybrid`、`gaussian` 三族，exact 轨 `bounds()` 与冻结脚本 `compute_model_90_coverage_bounds()` 计算结果全量偏差 $\le 10^{-12}$ | **通过** |
| **T05** | A 组 | 代理轨区间精度与名义分位（模块常量） | 代理轨区间满足 $\mu \mp Z_{90} \cdot \sigma_{\text{eff}}$（偏差 $\le 10^{-12}$），`interval_level` 精确等于 `NOMINAL_INTERVAL_LEVEL` 且 `repr == '0.9'` | **通过** |
| **T06** | B 组 | 纳秒级性能基准（`time.perf_counter_ns`） | 20,000 次批量调用测得 **Exact p50 = 375.0 ns（p90 = 417 ns）**，**Proxy p50 = 583.0 ns（p90 = 625 ns）**，远低于 $10,000\text{ ns}$ 门限 | **通过** |
| **T07** | C 组 | 22 格外展倍率（`PhysicalParamContract`） | 遍历全部 22 格，$\sigma_{\text{adj}} / \sigma_{\text{eff}} == \sqrt{\max(1.0, s_{\text{oos}})}$ 偏差 $\le 10^{-12}$；最大膨胀格 `KMIA_30h` 比值格式化为 `1.167832` | **通过** |
| **T08** | C 组 | 过自信格保底不缩窄（`PhysicalParamContract`） | 检验 $s_{\text{oos}} < 1.0$ 的 4 格（KORD 12h/36h/60h/66h），$\sigma_{\text{adj}} == \sigma_{\text{eff}}$ 严格精确浮点相等 | **通过** |
| **T09** | C 组 | $\sigma_{\text{adj}}$ F-2 生产入口熔断（模块符号） | `load_sigma_adj_policy()` 强抛 `F2LockNotReleasedError` 且含 `#156`；外部构造枚举 `LOCKED` 与裸串 `"F-2 LOCKED"` 传入 `compute_sigma_adj` 均被拒 | **通过** |
| **T10** | D 组 | 探针达标深度与均价（固定盘口） | 盘口 `((0.40,100),(0.45,200),(0.50,300))` 在 $\hat p=0.52$ 下含费达标层严格为 `(0, 1)`、$S_{\text{target}}=300.0$、$\bar P=130/300$；$\hat p=0.60$ 下达标层为 `(0, 1, 2)`、$S_{\text{target}}=600.0$、$\bar P=280/600$ | **通过** |
| **T11** | D 组 | 含费边判定与聚合单调性（固定盘口） | R-1 单层反例强抛 `NoQualifiedLevelsError`；枚举 3 组固定盘口，成功返回结果恒满足 $\text{edge} \ge \text{policy.min\_edge}$，且 $\text{edge} == (\hat p - q_{\text{eff}})/q_{\text{eff}}$ 偏差 $\le 10^{-12}$ | **通过** |
| **T12** | D 组 | 探针 F-2 熔断与多继承架构（模块符号） | `load_penetration_policy()` 强抛异常且含 `#156`；`LOCKED` 策略传入 `compute_probe` 强拒；异常实例与类同时 `isinstance/issubclass` 于 `PenetrationError` 与 `SigmaAdjF2LockNotReleasedError` | **通过** |

---

## 四、 T06 纳秒级性能原始测定值

```text
采样环境：Python 3.13.5 (darwin, arm64)
采样方式：time.perf_counter_ns()，warmup = 1,000 次，batch = 20,000 次逐次计时
ExactCoverageTrack.bounds()  : p50 = 375.0 ns, p90 = 417 ns (阈值 <= 10,000 ns)
GaussianProxyCoverageTrack.interval(): p50 = 583.0 ns, p90 = 625 ns (阈值 <= 10,000 ns)
判定结论：双轨耗时均在 1 μs 以内，性能门禁以 17x ~ 26x 余裕通过。
```
