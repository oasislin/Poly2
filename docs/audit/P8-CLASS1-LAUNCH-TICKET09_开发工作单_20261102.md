# P8-CLASS1-LAUNCH · Ticket 08 收尾 + Ticket 09 开发工作单

> **日期**：2026-11-02
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **基线快照**：`HEAD = 2c891f2`、`origin/main = f6d8e05`、`ahead 2`；工作树除本轮待提交文档（台账、`CHK-21` 尾部标记清理、`CHK-22`、Ticket 08 回执补正、本工作单）外无其他改动。Ticket 09 的门禁 G6 基线取「第一部分完成后的 HEAD」（即本轮 docs commit 的 SHA），不是 `2c891f2`。
> **立法依据**：`docs/audit/P7-ALGO-2_规格书.md` L60-63 / L86 / L154 / L159-162；`ADR-0019` §4-§5；`CHK-21` §4.4 口径裁定；`CHK-22` 冻结结论
> **接收方**：开发 Agent　**签发方**：PM / 算法复核方

---

# 第一部分 · Ticket 08 收尾（D-6 文本补正 + CHK-21 标记清理 + Push）

## 1.1 任务（共三项，按序执行）

1. **D-6 文本补正**：在 [P8-CLASS1-LAUNCH-TICKET08_交付回执_20261102.md](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/audit/P8-CLASS1-LAUNCH-TICKET08_%E4%BA%A4%E4%BB%98%E5%9B%9E%E6%89%A7_20261102.md) §二 门禁 G7 处，补入 `git status -sb` 的**原样输出**（不得只写文字描述）：

   ```text
   ## main...origin/main [ahead 2]
   ```

   > 采集时点：Ticket 08 交付快照 `2c891f2`；此行系原样补录，非本轮重跑输出。**注解不得写进代码块**，否则不构成"原样输出"。

2. **D-8 整改 · `CHK-21` 尾部残留标记清理**：删除 [CHK-21 复核单](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/audit/P8-CLASS1-LAUNCH-CHK-21_Ticket08%E9%A6%96%E8%BD%AE%E4%BA%A4%E4%BB%98%E5%A4%8D%E6%A0%B8%E5%8D%95_20261102.md) 文件**末尾两行**：

   ```text
   </content>
   </invoke>
   ```

   约束：**只删这两行，其余字节零变动**（正文、数值、结论、签名、冻结声明全部不动）。冻结条款约束的是「正文与数值」，尾部残留的标记不属于正文，故本次清理不构成改写；但也不得借此修改任何其他内容。

3. **提交并推送**：先本地提交本轮 **5 个文档**（`CHK-22` + 台账 + 上述回执补正 + `CHK-21` 清理 + 本工作单），再**推送全部本地未推送提交**至 `origin/main`。

> **Push 授权范围（用户本次明确指令）**：`ac08954`（Ticket 07 微整改）、`2c891f2`（Ticket 08 交付）、本轮 docs commit。除上述三者外的任何提交一律不得推送。

## 1.2 边界

- **只允许改文档**：回执、`CHK-22` 复核单（仅新增，不改正文）、`docs/项目编号与命名规范_20261021.md` 台账、`CHK-21`（**仅限删除文件末尾两行标记**）、本工作单（5 项，逐项对应 §1.1 第 3 条的白名单）；**禁止改任何生产代码、测试代码**。
- `CHK-21` / `CHK-22` 正文与数值**冻结**，不得回改（`CHK-21` 唯一例外见 §1.1 第 2 条；除此之外任何改动即判不通过）。
- 全仓已扫描：除 `CHK-21` 的待清理项、以及本工作单中作为**指令示例**出现的两行外，无其他文件残留 `</content>` / `</invoke>` / 伪「系统提醒」文本（`CHK-22` 的残留已由 PM 在签发前清除）。清理后须复查为零。
- 不得改写已推送的 `f6d8e05`（禁止 `rebase`/`force push`）；本轮对 `CHK-21` 的删除作为**新增 commit** 叠加，不改写历史。

## 1.3 收尾门禁

| 门禁 | 命令 | 判定阈值 |
|---|---|---|
| **A1** | `git status -sb`（提交前） | 仅上述 5 个文档变动，无代码/测试改动 |
| **A2** | `git log --oneline -5` | 出现本轮 docs commit |
| **A3** | `grep -nE '^## main\.\.\.origin/main \[ahead 2\]$' docs/audit/P8-CLASS1-LAUNCH-TICKET08_交付回执_20261102.md` | 命中 = 1，且代码块内无中文注解 |
| **A4** | `git push` 后 `git status -sb` | `## main...origin/main`（无 `[ahead N]`） |
| **A5** | `git rev-parse HEAD origin/main` | 两个 SHA 逐字相等 |
| **A6** | `git diff --unified=0 HEAD -- docs/audit/P8-CLASS1-LAUNCH-CHK-21_Ticket08首轮交付复核单_20261102.md` | 输出**只有**两行删除（`-</content>`、`-</invoke>`），新增行 = 0 |
| **A7** | `grep -rn "</content>\|</invoke>" . --exclude-dir=.git --exclude='P8-CLASS1-LAUNCH-TICKET09_开发工作单_20261102.md'` | 命中 = 0（全仓复查；排除本工作单的指令示例） |

---

# 第二部分 · Ticket 09 开发工作单

## 2.1 票面

| 项 | 内容 |
|---|---|
| **A 线票** | `Phase 2 Task 08 - Ticket 09: test(pricing): 覆盖率双轨三不混用与探针定价单测集`（[#142](https://github.com/oasislin/Poly2/issues/142)） |
| **依赖** | `Blocked by #141` → 已解除（CHK-22 通过） |
| **性质** | **纯测试票**：只新增测试，**禁止修改 `src/` 任何一行** |
| **交付路径** | `tests/unit/pricing/test_order_probe_evaluator.py`（沿用拆票方案 #142 既定路径；本文件即定价层跨模块契约测试集） |

## 2.2 交付物白名单（严格 4 项）

| # | 文件 | 性质 |
|---|---|---|
| 1 | `tests/unit/pricing/test_order_probe_evaluator.py` | **新建** |
| 2 | `docs/audit/P8-CLASS1-LAUNCH-TICKET09_交付回执_20261102.md` | **新建** |
| 3 | `STATUS.md` | 修改（同步 Ticket 09 状态） |
| 4 | `docs/ROADMAP.md` | 修改（同步进度） |

**禁区**：`src/**`（含 `sigma_adj.py` / `penetration_probe.py` / `coverage_dual_track.py` / `__init__.py`）、`scripts/**`、`data/**`、`evidence/**`、`tests/unit/pricing/` 下既有三个测试文件（`test_coverage_dual_track.py`、`test_penetration_probe.py`、`test_sigma_adj.py`）—— **字节零变动**。

> **关键治理点**：测试票若暴露实现缺陷，**不得自行修 `src/`**，必须把复现命令、原始输入/输出原样上报并**停等复核方裁定**。

## 2.3 测试内容（T01~T12，全部必做）

### A 组 · 双轨三不混用（依据 `CHK-19` §四 + 裁决 R2）

| 编号 | 断言对象 | 断言内容 | 数据源 |
|---|---|---|---|
| **T01** | 口径不混用 | `ExactCoverageTrack.bounds/coverage` 传 `ONLINE_PRICING` → `CoverageTrackMisuseError`；`GaussianProxyCoverageTrack.interval` 传 `OFFLINE_AUDIT` → 同；`context=None` → 同；裸串 `"OFFLINE_AUDIT"`/`"ONLINE_PRICING"` → 同 | 模块导出 |
| **T02** | 上下文不混用（构造期） | 构造器传错轨/非法 context → `CoverageTrackMisuseError`；传合法 context → 正常实例化 | 模块导出 |
| **T03** | 类型不混用 | `CoverageInterval` **无** `coverage_rate` 属性；`CoverageRate` **无** `lower`/`upper`；两轨互不继承（`issubclass` 双向 = False）；**AST 必须按 `ast.ClassDef` 子树统计（禁止整文件扫描）**：`GaussianProxyCoverageTrack` 子树中 `johnsonsu`/`shape_params`/`evt_hybrid`/`ExactCoverageTrack` 的 `ast.Name.id + ast.Attribute.attr` 命中 = 0，`ExactCoverageTrack` 子树中 `GaussianProxyCoverageTrack`/`CoverageInterval` 命中 = 0 | 模块 + `ast` 读源码 |
| **T04** | exact 轨行为等价 | `johnsonsu` / `evt_hybrid` / `gaussian` 三族 bounds 与冻结脚本 `scripts.evaluate_p4_2019_settlement.compute_model_90_coverage_bounds` 偏差 ≤ 1e-12 | 冻结脚本 + `evidence/p4_active10_climate_calibration.json`（只读） |
| **T05** | 代理轨区间精度 | `interval.lower/upper == mu ∓ Z_90_HALF_WIDTH * sigma_eff`（偏差 ≤ 1e-12），且 `interval_level == NOMINAL_INTERVAL_LEVEL`（`repr` = `0.9`） | 模块导出常量 |

### B 组 · 性能（纳秒计时口径见 §2.5）

| 编号 | 断言对象 | 断言内容 |
|---|---|---|
| **T06** | 双轨单次调用耗时 | `time.perf_counter_ns()` 批量 N = 20,000 次，取 **p50**；双轨各自 `p50 ≤ 10,000 ns`；测试**必须**在断言失败信息中打印实测 p50/p90 原始值 |

### C 组 · σ_adj 纠偏有效性

| 编号 | 断言对象 | 断言内容 | 数据源 |
|---|---|---|---|
| **T07** | 22 格外展倍率 | 遍历 `PhysicalParamContract` 全部 22 格（遍历方式：`contract.cells.items()`——该契约无公开迭代方法，只暴露此 `MappingProxyType` 字段）：`σ_adj/σ_eff == √(max(1.0, s_oos))`，偏差 ≤ 1e-12；最大膨胀格 `KMIA_30h` 比值 = `1.167832`（测到 ≥ 6 位小数） | `data/contracts/physical_param_contract.json`（只读，经 `src.contract.parameter_contract.PhysicalParamContract` 加载） |
| **T08** | 过自信不缩窄 | `s_oos < 1.0` 的 4 格（KORD 12h/36h/60h/66h）`σ_adj == σ_eff`（`==` 精确相等，非近似） | 同上 |
| **T09** | F-2 生产路径熔断 | `load_sigma_adj_policy()` → `F2LockNotReleasedError` 且异常文本含 `#156`；外部构造 `LOCKED`/裸串 `"F-2 LOCKED"` 策略传入 `compute_sigma_adj` 亦拒绝 | 模块导出 |

### D 组 · 探针达标深度自洽（`CHK-22` 冻结口径）

| 编号 | 断言对象 | 断言内容 |
|---|---|---|
| **T10** | 达标深度与均价 | `((0.40,100),(0.45,200),(0.50,300))`、`p̂=0.52`、`min_edge=0.02` → `qualified_levels=(0,1)`、`s_target=300.0`、`p_bar=(0.40*100+0.45*200)/300`（偏差 ≤ 1e-12）；`((0.40,100),(0.45,200),(0.50,300))`、`p̂=0.60` → `s_target=600.0`、`p_bar=280/600` |
| **T11** | 含费边判定 + 聚合不变式 | R-1 `((0.50,300),)` `p̂=0.52` → `NoQualifiedLevelsError`；枚举 ≥ 3 组固定盘口，任一成功返回的 `ProbeResult` 必满足 `edge >= policy.min_edge`；`edge` 与手算 `(p̂−q_eff)/q_eff` 偏差 ≤ 1e-12 |
| **T12** | 探针 F-2 熔断 | `load_penetration_policy()` → `F2LockNotReleasedError` 且含 `#156`；`LOCKED` / 裸串 `"F-2 LOCKED"` 策略传入 `compute_probe` 均拒绝；异常须同时 `isinstance` 于 `PenetrationError` 与 `sigma_adj.F2LockNotReleasedError` |

## 2.4 硬性约束

1. **零 `src/` 改动**（§2.2 禁区）；发现缺陷只上报，不修。
2. **禁止魔法数**：断言中的费率、分位、名义覆盖水平必须引用模块导出常量（`FEE_BASE_RATIO`、`Z_90_HALF_WIDTH`、`NOMINAL_INTERVAL_LEVEL`）；仅"输入盘口/概率"等场景数据可写字面量，且须与 T01~T12 表中给出的一致。
3. **禁止 `except Exception` / 裸 `except`**；禁止 `monkeypatch` 掉 F-2 熔断以"让测试变绿"。
4. **禁止 mock 外部契约**：`sigma_eff`、数值族、盘口均为真实字面量；契约数据一律只读加载。
5. 每个测试函数 ≤ 45 行（门禁上限 50）；单文件用例 ≥ 12。
6. 断言失败必须可定位：涉及数值处使用 `pytest.approx` 外的显式 `abs(x - y) <= tol` 并带实测值。

## 2.5 判定口径裁定（由 PM 预先钉死，开发端不得自行放宽）

1. **"纳秒级响应"实现口径**：用 `time.perf_counter_ns()` 逐次计时，取 20,000 次调用序列的 **p50**，阈值 **`p50 ≤ 10,000 ns`（10 μs）**。理由：纯 Python 函数 + `math` 调用的典型值在 1 μs 量级，严格 `< 1,000 ns` 会因共享机器抖动与解释器差异产生假红。若实测 p50 超过 10 μs，**必须原样上报实测值并停等复核裁定**，不得自行调阈值。
2. **逐层达标口径（CHK-22 冻结）**：`q_eff_j = p_j·[1+0.05·(1−p_j)]`，`edge_j = (p̂−q_eff_j)/q_eff_j ≥ min_edge`；聚合仍为纯价格深度加权均价 `P̄` 后一次性折算。**任何实现回退到纯价格边即判不通过。**
3. **F-2 口径**：`min_edge`、`exponent`、`floor`、σ_adj 标定值均为 `[待标定]`；测试只允许经外部注入 `policy`（`RELEASED` 仅测试用），生产入口一律熔断。

## 2.6 门禁 G1~G8（同一快照一次性执行，原样贴出）

| 门禁 | 命令 | 阈值 |
|---|---|---|
| **G1** | `python -m pytest tests/unit/pricing/test_order_probe_evaluator.py -q` | 全绿，≥ 12 用例 |
| **G2** | `python -m pytest tests/unit/pricing -q` | 全绿，≥ 60 用例（现 48 + 新增 ≥ 12） |
| **G3** | `python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q` | 全绿，≥ 292 用例（现 280 + 新增 ≥ 12） |
| **G4** | AST 函数长度扫描（`src/pricing/**` + `tests/unit/pricing/**`） | `max < 50`，超限 = 0 |
| **G5** | `grep -rn "except Exception\|except:" src/pricing/ tests/unit/pricing/` | 命中 = 0 |
| **G6** | `git diff --stat <基线SHA> -- src/ scripts/ data/ evidence/` | 输出为空（基线取 Ticket 09 开工时 `HEAD`） |
| **G7** | `git status -sb` | 仅白名单 4 文件变动，提交后 clean |
| **G8** | push 纪律 | 未收到明确指令**不得 push**；本票代码提交保持本地 |

## 2.7 回执要求

`docs/audit/P8-CLASS1-LAUNCH-TICKET09_交付回执_20261102.md` 必须包含：

1. 交付物白名单（与实际 commit `git show --stat` 文件数逐行一致）；
2. G1~G8：**命令原文 + 输出末尾原样片段 + 采集方标注（开发端自测）**，并按 `原始观测值 = …；判定阈值 = …；结论 = …` 两步分离书写；
3. T01~T12 明细（每条对应的断言与数据源）；
4. T06 的实测 p50/p90 纳秒原始值；
5. 禁区声明（`src/` 零改动）与缺陷上报（如有）。

## 2.8 提交纪律

- 原子提交：`test(pricing): Ticket 09 定价层跨模块契约测试集（#142）`（测试文件）+ `docs: Ticket 09 回执与台账同步`（`STATUS.md`、`ROADMAP.md`、回执）。
- **不得自动 push**；等用户明确指令。
- 不得修改 `CHK-21` / `CHK-22` 正文（历史冻结件）；唯一例外是 `CHK-21` 尾部两行残留标记的删除（§1.1 第 2 条）。

---

# 第三部分 · 一页速览

```
第一部分（Ticket 08 收尾）：
  1) 回执 G7 补 git status -sb 原样片段（代码块内只放那一行）
  2) 删 CHK-21 末尾两行 </content> / </invoke>（只删这两行，新增 0）
  3) docs commit（5 个文档）→ push（授权范围：ac08954 / 2c891f2 / 本 docs commit）
  4) 门禁 A1~A7

第二部分（Ticket 09 开发）：
  新建 tests/unit/pricing/test_order_probe_evaluator.py（T01~T12）
  + 回执 + STATUS.md + ROADMAP.md；src/ 零改动
  门禁 G1(≥12) G2(≥60) G3(≥292) G4(max<50) G5(=0) G6(空) G7(白名单) G8(不 push)
  性能口径：p50 ≤ 10,000 ns（20,000 次批量，perf_counter_ns）
  含费边口径与 F-2 熔断口径：沿用 CHK-22 冻结结论，不得回退
```

> 本工作单由 PM / 算法复核方签发；Ticket 09 交付后由复核方出具 `CHK-23` 复核单。

