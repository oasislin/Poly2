# P8-CLASS1-LAUNCH-CHK-23 · Ticket 09 交付复核单

> **日期**：2026-11-02
> **A 线锚点**：`Phase 2 Task 08 - Ticket 09: test(pricing): 覆盖率双轨三不混用与探针定价单测集` / [#142](https://github.com/oasislin/Poly2/issues/142)
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-23`
> **复核对象**：`77e0243`（Ticket 09 测试文件）、`0127321`（Ticket 09 docs）
> **前序单据**：`CHK-22`（Ticket 08 整改复验 · 通过）、`P8-CLASS1-LAUNCH-TICKET09_开发工作单_20261102.md`、`P8-CLASS1-LAUNCH-TICKET09_交付回执_20261102.md`
> **复核人**：独立复核 Agent（本机重新实测，不采信开发端自测数值）

---

## 一、 复核结论

**通过**。Ticket 09 交付（#142）满足全部门禁 G1~G8 与 T01~T12 断言实质要求；第一部分 Ticket 08 收尾 A1~A7 全部闭环。无阻断整改项。Ticket 09（#142）具备关闭条件。

---

## 二、 快照与提交结构（复核方实测）

```
HEAD        = 0127321（Ticket 09 docs commit：STATUS.md / ROADMAP.md / 回执）
origin/main = b61372d（审计文档已推送，含 CHK-22、台账、Ticket 08 回执补正、CHK-21 清理、Ticket 09 工作单）
ahead       = 2（77e0243、0127321 未推送）
工作树      = clean
```

| Commit | `git show --stat` 实测文件数 | 文件构成 | 判定 |
|---|---|---|---|
| `77e0243` | 1 | `tests/unit/pricing/test_order_probe_evaluator.py`（新建，329 行） | 与工作单白名单 4 项之一一致，通过 |
| `0127321` | 3 | `STATUS.md` / `docs/ROADMAP.md` / Ticket 09 交付回执（新建） | 与工作单白名单剩余 3 项一致，通过 |

**origin/main 推送核验**：`ac08954`（Ticket 07 微整改）、`2c891f2`（Ticket 08 交付）、`b61372d`（本轮 docs）三者均在 origin/main 上，此外无额外推送。`origin/main` 顶端 log：`b61372d → 2c891f2 → ac08954 → f6d8e05 …`。

---

## 三、 第一部分 A1~A7 Ticket 08 收尾回查

| 门禁 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|
| **A1** | `git status -sb`（提交前）仅 5 个文档变动，无 `src/` / `tests/` 改动 | 仅 5 个文档变动 | 通过 |
| **A2** | `git log --oneline -5` 含 `b61372d docs(audit): 签发 CHK-22 复验单并补正 Ticket 08 回执与台账 (含 Ticket 09 工作单)` | 出现本轮 docs commit | 通过 |
| **A3** | `grep -nE '^## main\.\.\.origin/main \[ahead 2\]$' TICKET08_交付回执` → 第 129 行命中；上下文为 ```text 代码块，块内仅 `## main...origin/main [ahead 2]` 一行，无中文注解 | 命中 = 1，代码块内无中文注解 | 通过 |
| **A4** | `git status -sb` 在 `b61372d` 上：`## main...origin/main`（无 ahead 标记） | 无 ahead | 通过 |
| **A5** | `git rev-parse b61372d origin/main` 均为 `b61372d74c1f0600d295cc46f2af176b5a85aaef` | SHA 相等 | 通过 |
| **A6** | `git diff --unified=0 b61372d^ -- CHK-21` → 仅两行删除 `-</content>` / `-</invoke>`，新增 0；正文/数值/结论/签名逐字未变 | 只有两行删除，新增 0 | 通过 |
| **A7** | `grep -rn "</content>\|</invoke>" . --exclude-dir=.git --exclude='TICKET09_开发工作单'` → exit=1（全仓零命中） | 命中 = 0 | 通过 |

---

## 四、 门禁 G1~G8 独立复跑（同一 HEAD `0127321`，复核方本机实测）

| 门禁 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|
| **G1** | `python -m pytest tests/unit/pricing/test_order_probe_evaluator.py -q` → `12 passed in 6.63s` | ≥ 12 且全绿 | 通过 |
| **G2** | `python -m pytest tests/unit/pricing -q` → `60 passed in 6.64s` | ≥ 60 且全绿 | 通过 |
| **G3** | `python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q` → `292 passed in 17.14s`；交叉核账：非 pricing = `232 passed`（复核方单独复跑），232 + 60 = 292 自洽 | ≥ 292 且全绿 | 通过 |
| **G4** | AST 扫描 `src/pricing/** + tests/unit/pricing/**` → `scanned 9 files, funcs 80, max = 42, over_50 = 0`；新增文件 `test_order_probe_evaluator.py` 单函数最大 31 行 | max < 50，新增文件 ≤ 45 | 通过 |
| **G5** | `grep -rn "except Exception\|except:" src/pricing/ tests/unit/pricing/` → exit=1（命中 0） | 命中 = 0 | 通过 |
| **G6** | `git diff --stat b61372d -- src/ scripts/ data/ evidence/` → 输出为空，exit=0；额外：既有三测试文件 diff 亦为空 | 输出为空 | 通过 |
| **G7** | `git status -sb` → `## main...origin/main [ahead 2]`，工作树 clean；白名单文件全部在 commit 内 | clean，白名单 4 项 | 通过 |
| **G8** | `git rev-list --count origin/main..HEAD` = 2；77e0243 / 0127321 均未推送 | ahead 2，未 push | 通过 |

---

## 五、 T01~T12 断言实质核查

### A 组 · 双轨三不混用

| 编号 | 断言内容 | 复核方实测验证 | 弱化检查 | 结论 |
|---|---|---|---|---|
| **T01** | 口径不混用：Exact rejects ONLINE_PRICING/None/裸串；Proxy rejects OFFLINE_AUDIT/None/裸串 | 源码 L72-93：`exact.bounds(..., context=TrackContext.ONLINE_PRICING/None/"OFFLINE_AUDIT")` 全部 `pytest.raises(CoverageTrackMisuseError)`；Proxy 对称覆盖 | 无弱化：每条路径独立 `raises` 三行 | 通过 |
| **T02** | 构造期 context 强约束 + 裸串拒入 | 源码 L98-114：跨轨 context 拒入、裸串拒入、合法实例化各 4 条独立断言 | 无弱化 | 通过 |
| **T03** | 类型隔离（hasattr + issubclass + **AST ClassDef 子树统计**） | 源码 L122-144：`not hasattr(interval, "coverage_rate")` + `not hasattr(rate, "lower/upper")` + `issubclass` 双向 False；AST 扫描 `tree.body` **按 `ast.ClassDef` 定位**（不是整文件扫描），分别对 `ExactCoverageTrack` 和 `GaussianProxyCoverageTrack` 子树做 `isdisjoint` | 无弱化：**明确使用 `ast.ClassDef` 子树**而非整文件 | 通过 |
| **T04** | exact 三族 bounds 与冻结脚本偏差 ≤ 1e-12 | 源码 L147-169：从真实 `evidence/p4_active10_climate_calibration.json` 扫描 `johnsonsu`/`evt_hybrid`/`gaussian` 三族样本；`compute_model_90_coverage_bounds` vs `exact.bounds` 逐族比对 | 无弱化：逐样本显式 `abs(act - exp) <= 1e-12` | 通过 |
| **T05** | `interval.lower/upper == mu ∓ Z_90_HALF_WIDTH * sigma_eff` + `interval_level == NOMINAL_INTERVAL_LEVEL` + `repr == "0.9"` | 源码 L172-186：用 **模块常量 `Z_90_HALF_WIDTH`** 和 **模块常量 `NOMINAL_INTERVAL_LEVEL`**，显式 `abs(...) <= 1e-12` + `repr(res.interval_level) == "0.9"` | 无弱化：显式 `repr` 断言保证类型，不是宽松的 `float ==` | 通过 |

### B 组 · 性能

| 编号 | 断言内容 | 复核方实测验证 | 弱化检查 | 结论 |
|---|---|---|---|---|
| **T06** | `perf_counter_ns` 20,000 次，p50 ≤ 10,000 ns；失败时打印实测 p50/p90 | 复核方自跑：Exact p50 = 416 ns, p90 = 417 ns；Proxy p50 = 583 ns, p90 = 625 ns。均远低于 10,000 ns 阈值。开发端报 Exact p50=375 ns 是不同运行的机器抖动差异，Proxy p50=583 ns 逐位一致 | 无弱化：源码 L218-219 断言含实测值打印 `f"... {exact_p50} ns (p90: {exact_p90} ns)"` | 通过 |

### C 组 · σ_adj 纠偏有效性

| 编号 | 断言内容 | 复核方实测验证 | 弱化检查 | 结论 |
|---|---|---|---|---|
| **T07** | 22 格全量遍历（`contract.cells.items()`）；`σ_adj/σ_eff == √(max(1.0, s_oos))` 偏差 ≤ 1e-12；`KMIA_30h` 比值 ≥ 6 位小数 | 复核方自跑：`total cells = 22`，`mismatches = 0`；`KMIA_30h ratio = 1.167831751581` → `:.6f` = `1.167832`（与开发端声称一致） | 无弱化：L228 `assert len(contract.cells) == 22` + L239 `assert f"{kmia_ratio:.6f}" == "1.167832"`（格式化字符串精确比对，而非 `pytest.approx`） | 通过 |
| **T08** | `s_oos < 1.0` 四格 `σ_adj == σ_eff`（**精确 `==` 浮点相等**，非近似） | 复核方自跑：overconfident 格 = 4：`KORD 12/36/60/66`；全部 `sigma_adj == 2.0` → `exact_float_eq=True` | 无弱化：源码 L257 用 `==` 精确浮点相等，不是 `abs(...) <= eps` | 通过 |
| **T09** | `load_sigma_adj_policy()` → `F2LockNotReleasedError` 含 `#156`；LOCKED/裸串 `"F-2 LOCKED"` 传入 `compute_sigma_adj` 均被拒 | 源码 L260-272：三条 `pytest.raises` + `assert "#156" in str(exc_info.value)` | 无弱化：枚举 LOCKED + 裸串 `"F-2 LOCKED"` 两种路径独立 `raises` | 通过 |

### D 组 · 探针达标深度自洽

| 编号 | 断言内容 | 复核方实测验证 | 弱化检查 | 结论 |
|---|---|---|---|---|
| **T10** | 盘口 `((0.40,100),(0.45,200),(0.50,300))` + `p̂=0.52` → `qualified_levels=(0,1)`、`s_target=300.0`、`p̄=130/300`；`p̂=0.60` → `s_target=600.0`、`p̄=280/600` | 复核方自跑：`levels=(0,1), s_target=300.0, p_bar=0.433333333333`（`diff=0.0`）；case2 全量一致 | 无弱化：显式 tuple/整数精确匹配 + `abs <= 1e-12` | 通过 |
| **T11** | R-1 `((0.50,300),)` + `p̂=0.52` → `NoQualifiedLevelsError`；≥ 3 组盘口 `edge >= min_edge`；`edge == (p̂ - q_eff)/q_eff` | 复核方自跑：R-1 正确抛 `NoQualifiedLevelsError`；3 组盘口 `edge` 分别为 0.1669 / 0.2011 / 0.4836，均 `>= 0.02`；`edge` 公式偏差全为 `diff=0.0`（精确相等） | 无弱化：含费边 + 聚合不变式 + 公式精确比对均到位 | 通过 |
| **T12** | `load_penetration_policy()` 抛异常含 `#156`；LOCKED/裸串拒入；异常同时 `isinstance(PenetrationError)` 与 `SigmaAdjF2LockNotReleasedError` | 复核方自跑：`Exception type: F2LockNotReleasedError`（实际运行类名）；`isinstance PenetrationError: True`；`isinstance SigmaAdjF2LockNotReleasedError: True`；`contains '#156': True`；`issubclass` 双向 True | 无弱化：源码 L317-320 显式 `isinstance` + `issubclass` 检查双继承架构 | 通过 |

---

## 六、 红线检查复核（§2.4 硬性约束逐条）

| 约束 | 复核方实测 | 判定 |
|---|---|---|
| **零 `src/` 改动** | `git diff --stat b61372d -- src/` 输出为空 | 通过 |
| **零魔法数（费率/分位/覆盖水平引用模块常量）** | `Z_90_HALF_WIDTH` L21 导入 + L179 断言使用；`NOMINAL_INTERVAL_LEVEL` L20 导入 + L119-120/L185 断言使用；`FEE_BASE_RATIO` L19 导入（probe 内部自行计算含费边，测试不直接计算费率，不违规） | 通过 |
| **零 `except Exception` / 裸 `except`** | `grep -rn "except Exception\|except:" tests/unit/pricing/test_order_probe_evaluator.py` → exit=1，命中 0 | 通过 |
| **零 `monkeypatch` F-2 熔断** | `grep -n "monkeypatch" tests/unit/pricing/test_order_probe_evaluator.py` → exit=1，命中 0 | 通过 |
| **零 mock 外部契约** | 契约数据通过 `PhysicalParamContract.from_dict(json.load(fp))` 只读真实文件；无 `unittest.mock` / `pytest.monkeypatch` | 通过 |
| **单函数 ≤ 45 行** | 新增文件 `test_order_probe_evaluator.py` 单函数最大 31 行（AST 扫描，复核方实测） | 通过 |
| **断言失败可定位（显式 `abs <= tol` + 实测值）** | 全文件使用 `abs(...) <= 1e-12` + f-string 带实测值；**无 `pytest.approx`** | 通过 |
| **门禁 G6 基线正确** | `git diff --stat b61372d -- src/ scripts/ data/ evidence/` 空输出 | 通过 |

---

## 七、 处置表（仅整改 / 接受两类）

| 编号 | 事项（复核方实测） | 处置 | 落点 |
|---|---|---|---|
| — | — | — | — |

> 无整改项，全部通过。Ticket 09 交付满足全部工作单要求，具备关闭条件。

---

## 八、 签署与不可变声明

本单由复核方签发，结论：**Ticket 09（#142）交付通过，第一部分 Ticket 08 收尾 A1~A7 闭环**。无阻断整改项。Ticket 09 可以关闭，交付回执与工作单白名单逐项对齐；门禁 G1~G8 复核方独立复跑全部通过；T01~T12 断言实质核查全部到位，无弱化、无魔法数、无宽泛异常、无 mock 外部契约、无 `src/` 改动。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
