# P8-CLASS1-LAUNCH-CHK-18 · Ticket 05 首轮交付复核单

> **日期**：2026-10-26
> **A 线锚点**：`Phase 2 Task 08 - Ticket 05` / [#138](https://github.com/oasislin/Poly2/issues/138)
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-18`
> **复核对象**：`53731c7`（test(contract): 契约安全集成、防均值化与防污染测试集）
> **基线**：`15a4cb3`
> **前序单据**：`P8-CLASS1-LAUNCH-CHK-17`（Ticket 26 复验通过）
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）

---

## 一、 复核结论

**通过**。Ticket 05 交付了契约安全、防篡改、防均值化、防污染综合集成测试集（8 条用例）。4 项整改（回执 G8 补齐、辅助函数去重、领域模型强类型访问、22 格基数守卫、AST 关键字参数盲区）全部闭环。B-1~B-4 修订项（零魔法数 pvariance、结构化双站分化、空目录防空、端到端集成定位）逐项落实。真实 22 格产物兼容，禁区产物零变化，未 push。

---

## 二、 门禁独立复验（复核方本机实测原始值）

| 门禁 | 命令 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | `python -m pytest tests/unit/contract/test_contract_security_integration.py -q` | `8 passed in 10.54s` | 全绿，≥ 8 用例 | 通过 |
| **G2** | `python -m pytest tests/unit/contract -q` | `119 passed in 20.86s` | 全绿，≥ 119 用例 | 通过 |
| **G3** | `python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q` | `232 passed in 21.03s` | 全绿，≥ 232 用例 | 通过 |
| **G4** | AST 函数长度扫描 | `max = 40 lines`，`over_50 = 0` | `max < 50`，超限 = 0 | 通过 |
| **G5** | 静态 AST 防污染扫描（src/contract + src/risk） | `scanned files = 8`，`write violations = 0` | 写入调用 = 0 | 通过 |
| **G6** | `git diff 15a4cb3 HEAD --stat -- data/models/ data/contracts/` | 输出为空（exit 0） | 输出为空 | 通过 |
| **G7** | `grep -rn "except Exception\|except:" tests/unit/contract/test_contract_security_integration.py` | 0 处命中（exit 1） | 命中数 = 0 | 通过 |
| **G8** | `git status -sb` | `## main...origin/main [ahead 1]` | 仅本地 commit，未 push | 通过 |

> **两步分离判定汇总**：原始观测值 = G1~G8 全部满足阈值；判定阈值 = 各门禁目标；结论 = 全部通过。

---

## 三、 B-1~B-4 修订项独立核验

| 修订项 | 工作单要求 | 实测代码落实 | 结论 |
|---|---|---|---|
| **B-1** | TC-SEC-03 用 `pvariance > 0` 替代 `1e-6` 魔法阈值 | `var = statistics.pvariance(vals); assert var > 0`（L122-123） | 通过 |
| **B-2** | TC-SEC-04 用结构化 `diff_count >= 1` 替代「显著」 | `diff_count = sum(... != ...); assert diff_count >= 1`（L135-143） | 通过 |
| **B-3** | TC-SEC-05 范围限定 src/contract + src/risk，含防空断言 | `active_sources = glob("src/contract/*.py") + glob("src/risk/*.py"); assert len >= 8`（L148-151） | 通过 |
| **B-4** | TC-SEC-01/02 端到端从契约加载驱动 | `PhysicalParamContract.from_dict` → `ContractVersionWatchdog` → `watchdog.check()`（L85-92, L101-108） | 通过 |

### 关键语义独立探针（复核方直连产物）

```
cells = 22
  s_oos:            pvariance=2.28e-02 > 0 = True
  ece_2f:           pvariance=1.40e-05 > 0 = True
  v1_coverage_90:   pvariance=5.56e-04 > 0 = True
  pit_mean:         pvariance=7.09e-05 > 0 = True
  s_oos:            KORD!=KMIA leads = 11
  ece_2f:           KORD!=KMIA leads = 11
  v1_coverage_90:   KORD!=KMIA leads = 11
```

**原始观测值 = 4 字段 pvariance 均 > 0，3 字段双站分化均达 11/11 lead；判定阈值 = pvariance > 0 且 diff_count >= 1；结论 = 通过。**

---

## 四、 整改项（开发端自报 5 项）独立核验

| # | 整改项 | 核验 |
|---|---|---|
| 1 | G8 门禁补齐 `git status -sb` 命令与输出 | 回执已含 `## main...origin/main [ahead 1]` ✅ |
| 2 | `_compute_file_hashes` / `_load_contract_and_manifest` 辅助函数 | 已提取（L64-80），TC-SEC-01/02/06 复用 ✅ |
| 3 | TC-SEC-03/04 经 `PhysicalParamContract.from_dict` + `getattr(cell, field)` 强类型访问 | 已重构，无字典拼串 ✅ |
| 4 | TC-SEC-03 显式 `len(contract.cells) == 22` + `len(vals) == 22` 守卫 | 已加（L117, L121） ✅ |
| 5 | TC-SEC-05 `ast.unparse(node)` 深度扫描 + 关键字参数 + write_modes/write_methods 全模式拦截 | 已实现（L167-185） ✅ |

---

## 五、 改动范围核验

```
git diff 15a4cb3 HEAD --stat:
  P8-CLASS1-LAUNCH-TICKET05_交付回执_20261026.md | 141 +++
  test_contract_security_integration.py           | 250 +++
  2 files changed, 391 insertions(+)
```

仅新增测试文件 + 回执，**零 `src/` 改动、零 `data/` 改动**，与 `test(contract)` 范围一致。禁区清单（version_watchdog / converter / validator / parameter_contract / parameter_domains / data/models / physical_param_contract.json）全部未触碰。

---

## 六、 观察项登记（O-1）

1. **O-1（文档描述偏差，非阻塞）**：交付回执中 G5 门禁的命令片段使用了简化的内联检查（`func_name in ('open','write','dump','to_csv','to_parquet')`），与实际 `test_tc_sec_05` 的实现（`write_modes` 开模式集 + `write_methods` 写入方法集 + 关键字参数 `mode=` 检测 + `ast.unparse` 子树扫描）不一致。实际测试逻辑更严格且已通过，回执片段为粗略描述。建议后续回执直接引用测试文件中的实际扫描逻辑，避免描述与代码脱节。

---

## 七、 签署与不可变声明

本单由复核方独立签发，结论：**Ticket 05（#138）首轮交付复核通过，参数契约层全量封盘，具备关闭条件**。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
