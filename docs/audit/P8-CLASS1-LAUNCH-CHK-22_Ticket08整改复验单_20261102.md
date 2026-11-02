# P8-CLASS1-LAUNCH-CHK-22 · Ticket 08 整改复验单

> **日期**：2026-11-02
> **A 线锚点**：`Phase 2 Task 08 - Ticket 08` / [#141](https://github.com/oasislin/Poly2/issues/141)
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-22`
> **复验对象**：`ac08954`（微整改原子提交）、`2c891f2`（Ticket 08 交付）、`f6d8e05`（审计文档）
> **前序单据**：`CHK-21`（Ticket 08 首轮**不通过**，D-1 ~ D-4）
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）

---

## 一、 复验结论

**通过**。CHK-21 的 D-1 ~ D-4 四项整改全部实测闭环；附 1 项文本补正（D-6）与 1 项接受（D-7）。Ticket 08（#141）具备关闭条件，Ticket 09（#142）解除阻塞。

---

## 二、 快照与提交结构（复核方实测）

```
HEAD        = 2c891f2（Ticket 08 交付）
origin/main = f6d8e05（审计文档已推送）
ahead       = 2（ac08954、2c891f2 未推送）
工作树      = clean
```

| Commit | `git show --stat` 实测文件数 | 文件构成 | 判定 |
|---|---|---|---|
| `f6d8e05` | 3 | CHK-20 复核单 / CHK-21 复核单 / 命名规范台账 | 文档原子提交，通过 |
| `ac08954` | 2 | `sigma_adj.py`、`test_sigma_adj.py` | 微整改独立隔离，通过 |
| `2c891f2` | 6 | `penetration_probe.py`、`__init__.py`、`test_penetration_probe.py`、交付回执、`STATUS.md`、`docs/ROADMAP.md` | 与回执白名单 6 项逐一对应，通过 |

---

## 三、 整改项闭环核验（D-1 ~ D-4）

| 项 | 验收门禁（CHK-21 原定） | 复核方实测原始值 | 判定 |
|---|---|---|---|
| **D-1** | 逐层达标改用含费边，且聚合 `edge ≥ min_edge` | 代码 [L167-172](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/penetration_probe.py#L167-L172) 实测为 `q_eff_j = price*(1+FEE_BASE_RATIO*(1-price))`；`(p̂ - q_eff_j)/q_eff_j >= min_edge` | 通过 |
| **D-1a** | R-1 反例须 Fail-Closed | `AskBook(((0.50,300)),) + p̂=0.52` → `NoQualifiedLevelsError: No ask levels meet min_edge threshold 0.02 with p_hat=0.52` | 通过 |
| **D-1b** | R-2 容量收敛至 300 | `p_bar=0.43333333333333335, q_eff=0.4456111111111111, net_ev=0.0743888888888889, edge=0.16693679092382496, s_target=300.0, qualified_levels=(0, 1)`；与 CHK-21 §4.3 应得值一致（差 ≤ 1e-15） | 通过 |
| **D-1c** | T02/T06/T14 期望值同步 | [T02](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/pricing/test_penetration_probe.py#L58-L72) 断言 `(0,)`/`100.0`/`0.40`；[T14](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/pricing/test_penetration_probe.py#L250-L256) 断言式改为含费边 | 通过 |
| **D-1d** | 新增聚合不变式用例 | [T16](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/pricing/test_penetration_probe.py#L268-L287) 含 R-1 抛错、R-2 容量 300、`edge >= min_edge` 三条断言 | 通过 |
| **D-2** | 门禁同一快照、数值可复现 | 见第四节，计数与交付端逐项一致 | 通过 |
| **D-3** | 清单计数与提交实况对齐 | 回执白名单 6 行 ↔ `2c891f2` 6 文件 | 通过 |
| **D-4** | 微整改独立 commit | `git log ca7b5c9..HEAD -- src/pricing/sigma_adj.py` 仅命中 `ac08954` | 通过 |

---

## 四、 门禁独立复跑（同一快照一次性执行）

| 门禁 | 命令 | 复核方实测原始值 | 交付端自述 | 判定 |
|---|---|---|---|---|
| **G1** | `pytest tests/unit/pricing/test_penetration_probe.py -q` | `16 passed in 0.05s` | `16 passed in 0.05s` | 通过 |
| **G2** | `pytest tests/unit/pricing -q` | `48 passed in 8.22s` | `48 passed in 1.35s` | 通过 |
| **G3** | `pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q` | `280 passed in 19.37s` | `280 passed` | 通过 |
| **G3′** | `pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q` | `232 passed in 20.61s`（`232 + 48 = 280` 自洽） | `232 + 48 = 280` | 通过 |
| **G4** | AST 函数长度扫描 | `scanned 8 files, funcs 66, max = 42, over_50 = 0`（TOP `test_coverage_dual_track.py` 42 行） | `funcs 66, max = 42, over_50 = 0` | 通过 |
| **G5** | 宽泛异常扫描 | 无输出，`exit=1`（命中 0） | `0 hits` | 通过 |
| **G6** | `git diff --stat ca7b5c9 -- data/ evidence/ src/contract/ coverage_dual_track.py evaluate_p4_2019_settlement.py` | 输出为空，`exit=0` | 输出为空 | 通过 |
| **G7** | 浮点字面量 AST | `penetration_probe.py -> 1 [(22, 0.05)]`；`sigma_adj.py -> 0 []`；`__init__.py -> 0 []` | 同 | 通过 |
| **G8** | 推送纪律 | 代码 commit `ac08954`/`2c891f2` 保持本地 `ahead 2`；`origin/main = f6d8e05` | 同 | 通过 |
| **G9** | `src.pricing.__all__` | 36 项；`lock_state="F2_RELEASED"` 归一化为 `SigmaAdjLockState.RELEASED`（`isinstance` = True），`compute_sigma_adj(1.21, 2.0, pol) = 2.2` | — | 通过 |

> 计时差异（如 G2 `8.22s` vs `1.35s`）为机器负载波动，计数逐项一致，不构成证据不一致。

---

## 五、 处置表（不设观察项：每项一律"整改"或"接受"）

| 编号 | 事项（复核方实测） | 处置 | 落点 / 依据 |
|---|---|---|---|
| **D-6** | 回执 G7 仅以文字表述「按计划分立原子 commit 后工作树 clean」，未贴 `git status -sb` 原样输出，不满足「证据须原样贴出」的硬性要求（实测值见第二节） | **整改（文本）** | 下次文档 commit 补入原样片段 `## main...origin/main [ahead 2]`（无 `M` 行）；不阻断功能结项 |
| **D-7** | `origin/main` 已前进至 `f6d8e05`（推送内容仅审计文档与台账，不含生产代码） | **接受** | 生产代码 `ac08954`/`2c891f2` 严格保持本地，符合「代码 push 需明确指令」；再评估触发条件：若出现代码 commit 未经指令推送，即刻升级为整改 |

---

## 六、 签署与不可变声明

本单由复核方签发，结论：**Ticket 08（#141）整改复验通过**，D-1 口径裁定（逐层含费边 + 聚合一次性折算 + `edge ≥ min_edge` 不变式）自此冻结，构成 Ticket 09（#142）测试集的强制契约。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**

