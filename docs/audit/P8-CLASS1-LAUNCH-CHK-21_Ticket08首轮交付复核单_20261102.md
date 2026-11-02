# P8-CLASS1-LAUNCH-CHK-21 · Ticket 08 首轮交付复核单

> **日期**：2026-11-02
> **A 线锚点**：`Phase 2 Task 08 - Ticket 08` / [#141](https://github.com/oasislin/Poly2/issues/141)
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-21`
> **复核对象**：`e846509`（`src/pricing/penetration_probe.py` + 包导出 + 测试集 + 回执 + 台账）
> **立法依据**：`docs/audit/P7-ALGO-2_规格书.md` L60-63（M1 定价引擎 / DR-2026-1014-01）、L86（M4 逐档 `net_ev/q_eff`）、L154（`min_edge` `[待标定]`）、L159-162（R-16 不回迁）
> **前序单据**：`CHK-19`（Ticket 06 通过）、`CHK-20`（Ticket 07 通过，附 D-1/D-2 并入本票开工前微整改）
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）

---

## 一、 复核结论

**不通过（首轮）**。附 4 项整改（D-1 ~ D-4）与 1 项接受（D-5）。

- **工程姿态合规**：F-2 双防线（生产入口熔断 + 守卫路径拒算）实测生效；零标定数值写入 `src/`（`penetration_probe.py` 浮点字面量仅常量区 1 个 `0.05`）；异常族齐全；边界探针全部 Fail-Closed；禁区零触碰。
- **阻断性缺陷（D-1）**：逐层达标判定采用**纯价格边** `(p̂ − p_j)/p_j`，与立法 L61 `edge = net_ev / q_eff ≥ min_edge`、L86 逐档 `net_ev / q_eff ≥ min_edge` 不符。实测可产出「`s_target > 0` 但聚合 `edge < min_edge`」的自相矛盾结果，且使 `S_target` 高估至 **2 倍**。
- **证据完整性缺陷（D-2/D-3/D-4）**：回执 G1~G8 非同一快照、G4 数值不可复现、清单计数自相矛盾、微整改未独立 commit。

---

## 二、 门禁独立复验（复核方本机实测原始值）

> 全部命令在 `HEAD = e846509`、工作树 clean 的同一快照上一次性执行。

| 门禁 | 命令 / 探针 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | `python -m pytest tests/unit/pricing/test_penetration_probe.py -q` | `15 passed in 0.06s` | 全绿，≥14 | 通过 |
| **G2** | `python -m pytest tests/unit/pricing -q` | `47 passed in 7.35s` | 全绿，≥44 | 通过 |
| **G3** | `python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q` | `279 passed in 18.41s` | 全绿，≥276 | 通过 |
| **G3′** | `python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q`（交叉核账） | `232 passed in 18.91s` | `232 + 47 = 279` 自洽 | 通过 |
| **G4** | AST 函数长度扫描（`src/pricing/**` + `tests/unit/pricing/**`） | `scanned 8 files, funcs 65, max = 42, over_50 = 0`（TOP：`test_coverage_dual_track.py::test_t05_exact_track_misuse_online_pricing` 42 行） | `max < 50`，超限 = 0 | 通过（**但交付端 G4 数值不可复现，见 D-2**） |
| **G5** | `grep -rn "except Exception\|except:" src/pricing/ tests/unit/pricing/` | 无输出，`exit=1`（命中 0） | 命中 = 0 | 通过 |
| **G6** | `git diff --stat -- data/ evidence/ src/contract/ src/pricing/coverage_dual_track.py scripts/evaluate_p4_2019_settlement.py` | 输出为空，`exit=0` | 空 | 通过 |
| **G7** | `git status -sb` | `## main...origin/main [ahead 2]`，工作树 clean | 仅白名单改动 / 已收敛 | 通过 |
| **G8** | 浮点字面量 AST（`src/pricing/`） | `penetration_probe.py -> 1 [(22, 0.05)]`；`sigma_adj.py -> 0 []`；`__init__.py -> 0 []`；`coverage_dual_track.py -> 5`（Ticket 06 已批常量） | 仅常量区 | 通过 |
| **G9** | 命名空间 | `src.pricing.__all__` = **36 项**；`F2LockNotReleasedError`（σ_adj）与 `PenetrationF2LockNotReleasedError`（probe）双名并存，probe 类为 σ_adj 类子类 | 无漏导出 | 通过 |

---

## 三、 行为探针（复核方直连模块，绕过交付端测试）

| # | 探针 | 原始观测值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| 1 | 三层盘口 `((0.40,100),(0.45,200),(0.50,300))`，`p̂=0.60`，`min_edge=0.02` | `ProbeResult(p_bar=0.4666666666666667, q_eff=0.4791111111111111, net_ev=0.12088888888888888, edge=0.2523191094619666, s_target=600.0, qualified_levels=(0, 1, 2))` | 与手算 `280/600`、`0.4791111111111111`、`0.2523191094619666` 逐位一致 | 通过 |
| 2 | `load_penetration_policy()` | `F2LockNotReleasedError: ... LOCKED pending calibration release in #156.` | 必须抛错且含 `#156` | 通过 |
| 3 | 裸串 `lock_state="F-2 LOCKED"` 传入 `compute_probe` | `F2LockNotReleasedError` | 必须抛错 | 通过 |
| 4 | 枚举 `SigmaAdjLockState.LOCKED` 传入 `compute_probe` | `F2LockNotReleasedError` | 必须抛错 | 通过 |
| 5 | 异常继承 | MRO = `F2LockNotReleasedError → PenetrationError → F2LockNotReleasedError(σ_adj) → SigmaAdjError` | 双亲继承 | 通过 |
| 6-11 | `p̂ ∈ {0.0, 1.0, nan, inf, -0.1, 1.5}` | 6/6 `InvalidProbabilityError` | 必须抛错 | 通过 |
| 12-15 | 盘口空 / 价格倒序 / `size=0` / `price=1.0` | 4/4 `InvalidOrderBookError` | 必须抛错 | 通过 |
| 16-18 | `min_edge ∈ {-0.1, nan, inf}` | 3/3 `InvalidPenetrationPolicyError` | 必须抛错 | 通过 |
| 19 | 全层不达标 `((0.90,100),)`，`p̂=0.60` | `NoQualifiedLevelsError` | 必须抛错，不得返回 0 | 通过 |
| 20 | 捕获层命名空间 | `except src.pricing.F2LockNotReleasedError` 可覆盖 probe 异常（子类关系） | 不得漏捕 | 通过 |
| 21 | **达标口径一致性（D-1 实证）** | 见第四节 | 见第四节 | **不通过** |

---

## 四、 立法对齐核查（D-1 阻断项实证）

### 4.1 立法原文

- L60：`S_target := Σ_{j: edge_j ≥ min_edge} s_j = safe_capacity_at_min_edge`；
- L61：`net_ev = p̂ − q_eff`；`edge = net_ev / q_eff ≥ min_edge`；`q_eff = P̄·[1 + 0.05·(1 − P̄)]`；**严禁逐层非线性费率迭代**；
- L86（M4）：`P_protect` 计算「**遍历 ask 档锁定最后一个满足 net_ev / q_eff ≥ min_edge 档位**」。

### 4.2 交付实现（[penetration_probe.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/penetration_probe.py#L167-L171)）

```python
if (p_hat - price) / price >= policy.min_edge:   # 纯价格边，未含费率
```

即逐层判定使用 `(p̂ − p_j)/p_j`，与 L61/L86 的 `net_ev/q_eff`（含费）口径不同。

### 4.3 复核方实测反例（原始观测值）

| 场景 | 盘口 / `p̂` | 本实现观测值 | 立法口径应得值 |
|---|---|---|---|
| R-1 | `((0.50,300),)`，`p̂=0.52`，`min_edge=0.02` | `s_target=300.0, p_bar=0.5, q_eff=0.5125, net_ev=0.007500000000000062, edge=0.014634146341463537` → **`edge < min_edge` 却 `s_target=300`** | 该层 `q_eff=0.5125`、`edge=0.01463 < 0.02` → 不达标，应抛 `NoQualifiedLevelsError` |
| R-2 | `((0.40,100),(0.45,200),(0.50,300))`，`p̂=0.52` | `s_target=600.0, p_bar=0.4666666666666667, q_eff=0.4791111111111111, edge=0.08534322820037113` | `s_target=300.0, p_bar=0.433333333333333, q_eff=0.445611111111111, net_ev=0.074388888888889, edge=0.166936790923825` |

结论：R-1 违背 L61「可交易信号 `edge ≥ min_edge`」自洽性；R-2 使 `safe_capacity` 高估 **2 倍**（600 vs 300）。属算法口径与立法不符，非测试用例可覆盖的行为差异。

### 4.4 复核方裁定（口径归一）

1. **逐层达标判定必须使用含费边**：`q_eff_j = p_j·[1 + 0.05·(1 − p_j)]`，`edge_j = (p̂ − q_eff_j)/q_eff_j`；
2. **聚合仍一次性折算**：`P̄` 取达标层深度加权均价（纯价格），`q_eff = P̄·[1+0.05·(1−P̄)]` —— L61「严禁逐层非线性费率迭代」约束的是**聚合路径**（禁止对 `P̄` 做逐层费率不动点迭代），不禁止逐层阈值判定使用含费代价；
3. **该口径可证聚合自洽**：`q_eff(p)` 在 `(0,1)` 严格单调递增（`q′ = 1.05 − 0.1p > 0`），故 `P̄ ≤ p_max ⇒ q_eff(P̄) ≤ q_eff(p_max) ≤ p̂/(1+min_edge) ⇒ edge ≥ min_edge`。任何成功返回的 `ProbeResult` 必然满足 `edge ≥ min_edge`；本实现不满足该不变式。

### 4.5 D-1 连带整改清单（测试用例期望值须同步修正）

| 用例 | 修正后期望值（复核方按 4.4 口径手算） |
|---|---|
| **T02** `((0.40,100),(0.48,200),(0.52,300))`，`p̂=0.50` | `0.48` 层 `q_eff=0.49248`、`edge=0.01527 < 0.02` 应排除 → `qualified_levels=(0,)`、`s_target=100.0`、`p_bar=0.40`（现测为 `(0,1)` / `300.0`） |
| **T06** `p̂=0.50` @ `0.50` | 含费边 `q_eff=0.5125`、`edge=−0.024390`（原注释「edge=0」不成立），排除结论不变 |
| **T14** `((0.40,10),(0.45,30),(0.495,40),(0.55,20))`，`p̂=0.50` | `0.495` 层 `q_eff=0.50749875`、`edge=−0.014772` 排除；`qualified_levels=(0,1)` 不变，但断言中的 `level_edge` 公式须改为含费口径 |
| **新增** | 聚合不变式用例：任意成功返回的 `ProbeResult` 满足 `result.edge >= policy.min_edge`（含 R-1 反例作为 `NoQualifiedLevelsError` 断言） |

---

## 五、 处置表（不设观察项：每项一律"整改"或"接受"）

| 编号 | 事项（复核方实测） | 处置 | 落点 / 验收门禁 |
|---|---|---|---|
| **D-1** | 逐层达标判定用纯价格边 `(p̂−p_j)/p_j`，与 L61/L86 含费口径不符；实测 R-1 产出 `edge=0.0146341463 < min_edge=0.02` 而 `s_target=300`；R-2 容量高估 2 倍（600 vs 300） | **整改（P0）** | 改为 `q_eff_j` 含费判别；同步修正 T02/T06/T14；新增 `edge ≥ min_edge` 不变式用例。**必须在 Ticket 09 立项前完成**，否则错误口径将被测试集固化为契约 |
| **D-2** | 门禁证据非同一快照且 G4 不可复现：交付端 G3=`277 passed`，而复核在同一树实测 `232 + 47 = 279`；交付端 G4=`funcs 67, max=37`，复核=`funcs 65, max=42`（`test_coverage_dual_track.py` 存在 42 行函数，按回执命令扫描必然 ≥42） | **整改** | 在整改后最终树上一并重跑 G1~G9，原样贴出命令与末尾片段，禁止跨时点拼接 |
| **D-3** | 回执「交付物白名单（6 项完整闭环）」与其下 8 行条目矛盾；`e846509` 实含 8 文件（`git show --stat` 实测） | **整改** | 文本按实际条目数更正，与 `git show --stat` 逐行对齐 |
| **D-4** | 微整改未独立成 commit：`git log f34c380..HEAD -- src/pricing/sigma_adj.py` 仅命中 `e846509`；且 G7 采集时记 `[ahead 1]` + 9 个 `M`，最终为 `[ahead 2]` + clean，证据早于 commit | **整改** | 见第六节执行指令：`git reset --soft 787553c` 后按 ①②③ 三个原子 commit 重建，并重采 G7 |
| **D-5** | 包级 `F2LockNotReleasedError`（σ_adj）与 probe 同名类并存，靠别名 `PenetrationF2LockNotReleasedError` 区分 | **接受** | probe 类为 σ_adj 类子类，`except src.pricing.F2LockNotReleasedError` 可完整覆盖，无漏捕风险；再评估触发条件：出现需按类精确分流 handler 的第三方消费方 |

> **纪律说明**：本单沿用 CHK-20 §六 纪律，不设"观察项"。每项必为 `整改`（带验收门禁与落点）或 `接受`（附理由与再评估触发条件）。

---

## 六、 整改执行指令（交开发 Agent 执行，复核方不代跑 git）

> 前提：`787553c`、`e846509` **均未推送**（`origin/main = ca7b5c9`），历史可安全重建，无需 force push。

1. `git reset --soft 787553c`（保留工作树全部改动，撤销 `e846509` 提交边界）；
2. 按第四节 4.4 口径修正 [penetration_probe.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/penetration_probe.py#L167-L171) 的逐层判别，并同步修正 T02/T06/T14 与新增不变式用例；
3. 按 3 个原子 commit 重建：
   - `① fix(pricing): CHK-20 D-1/D-2 微整改（__all__ + lock_state 归一化）` → `sigma_adj.py` + `test_sigma_adj.py`
   - `② feat(pricing): Ticket 08 EV 引擎与 S1 盘口穿透探针（DR-2026-1014-01）` → `penetration_probe.py` + `__init__.py` + `test_penetration_probe.py`
   - `③ docs: Ticket 08 回执更正与台账同步` → 回执 + `STATUS.md` + `docs/ROADMAP.md`
4. 在最终树上一次性重跑 G1~G9（含 G4 原样输出、`git status -sb`、`git show --stat`），回执按实测贴出；
5. 不执行 `git push`，等待用户明确指令。

---

## 七、 当前仓库状态（复核方实测）

```
HEAD        = e846509（Ticket 08 代码提交）
origin/main = ca7b5c9
ahead       = 2（787553c、e846509 未推送）
工作树      = clean
```

---

## 八、 签署与不可变声明

本单由复核方签发，结论：**Ticket 08（#141）首轮交付复核不通过**，须完成 D-1 ~ D-4 整改并提交整改复验单（`CHK-22`）后方可关闭；本单 D-1 口径裁定同时构成 Ticket 09（#142）测试集的强制契约。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
