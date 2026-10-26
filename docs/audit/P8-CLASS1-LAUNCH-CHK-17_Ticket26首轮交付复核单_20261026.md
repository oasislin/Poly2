# P8-CLASS1-LAUNCH-CHK-17 · Ticket 26 首轮交付复核单

> **日期**：2026-10-26
> **A 线锚点**：`Phase 2 Task 08 - Ticket 26` / [#159](https://github.com/oasislin/Poly2/issues/159)
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-17`
> **复核对象**：`0513631`（feat 契约受控域治理模块与两级域解耦）
> **基线**：`93a1404`
> **前序单据**：`P8-CLASS1-LAUNCH-CHK-14`（Ticket 25 复验通过）
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）

---

## 一、 复核结论

**通过**。Ticket 26 成功在契约层建立唯一、可执行、可审计的物理参数受控域治理模块：14 个受控字段的 Tier 1 数学定义域（Fail-Closed）、Tier 2 有效域 Schema（F-2 LOCKED，读取即抛）、CF-1 跨字段不变量、以及与算法层的完全解耦（浮点字面量唯一定义处、纯 stdlib 依赖、单点委托）。真实 22 格产物 100% 兼容，未触碰 `data/` 任何产物，未 push。Code Review 自报的 4 项整改（双锁加固、0.90 字面量清除、AST 防空扫描、状态文档同步）全部闭环。

---

## 二、 门禁独立复验（复核方本机实测原始值）

| 门禁 | 命令 / 探针 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | `python -m pytest tests/unit/contract/test_parameter_domains.py -q` | `21 passed in 0.21s` | 全绿，≥ 18 用例 | 通过 |
| **G2** | `python -m pytest tests/unit/contract -q` | `111 passed in 19.30s` | 全绿，≥ 108 用例 | 通过 |
| **G3** | `python -m pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q` | `224 passed in 19.36s` | 全绿，≥ 221 用例 | 通过 |
| **G4** | AST 函数长度扫描 | `max = 46 lines`（`param_table_converter.py:_build_single_cell_record`），超 50 行 = 0 | `max < 50`，超限 = 0 | 通过 |
| **G5-AST-1** | 非 `parameter_domains.py` 浮点字面量 | `param_table_converter / param_table_validator / parameter_contract / version_watchdog / __init__` 浮点集合均为空 | 0 个浮点字面量 | 通过 |
| **G5-AST-2** | `parameter_domains.py` 浮点字面量集合 | `{0.0, 0.25, 1.0}` | ⊆ `{0.0, 0.25, 1.0}` | 通过 |
| **G5-AST-3** | `parameter_domains.py` import | `dataclasses / math / types / typing`（4 项，纯 stdlib） | 零项目内 import | 通过 |
| **G6** | 真实产物 22 格全量校验 | `22-cell compatibility: 22/22 passed`；`tier2 fields all None: 14/14` | 22/22 全通过；14/14 Tier2 全 None | 通过 |
| **G7** | `git diff 93a1404..0513631 --stat -- data/contracts/ data/models/` | 输出为空（exit 0） | 输出为空 | 通过 |
| **G8** | 宽泛异常扫描 | `grep -rn "except Exception\|except:" src/contract/parameter_domains.py src/contract/parameter_contract.py tests/unit/contract/test_parameter_domains.py` → 0 处命中 | 0 处 | 通过 |
| **G9** | 跑测试后工作树 | `## main...origin/main [ahead 1]`，working tree clean | 无多余改动 | 通过 |
| **G10** | Push 纪律 | `## main...origin/main [ahead 1]` | 仅本地 commit，未 push | 通过 |

---

## 三、 关键语义独立对抗探针（复核方直连模块，不依赖测试文件）

| 探针 | 期望 | 复核方实测 |
|---|---|---|
| `s_oos=-1.0` | `ParameterDomainViolation` | 抛 `ParameterDomainViolation` |
| `s_oos=0.0` | 接受（下界闭） | 接受 |
| `pit_var=-1.0` | 拒绝 | 拒绝 |
| `pit_var=0.25` | 接受（Popoviciu 上界闭） | 接受 |
| `pit_var=0.2501` | 拒绝 | 拒绝 |
| `ece_2f=0.9` | **接受**（证明非质量阈值） | 接受 |
| `ece_2f=1.0` | 接受（上界闭） | 接受 |
| `ece_2f=1.0001` | 拒绝 | 拒绝 |
| `v1_coverage_90=1.5` | 拒绝 | 拒绝 |
| `neff=0.0` | 拒绝（下界开） | 拒绝 |
| `neff=1e-9` | 接受 | 接受 |
| `cvm_p=0.0 / 1.0 / 1.2` | 接受 / 接受 / 拒绝 | 接受 / 接受 / 拒绝 |
| `s_oos=NaN / +inf` | 拒绝 | 拒绝 |
| `fstd_in=1 / "true"` | 拒绝（严格 bool） | 拒绝 |
| `s_oos=True`（bool 误入数值字段） | 拒绝 | 拒绝 |
| 未知字段 `s_oos_v2` | 拒绝（禁静默跳过） | 拒绝 |
| `require_effective_domain("s_oos")` | `F2LockNotReleasedError` 含 `"F-2 LOCKED"` | 抛错且消息含锁定状态与解锁工单号 |
| CF-1 `fstd_lo==fstd_hi` / `fstd_lo>fstd_hi` | `CrossFieldInvariantViolation` | 均拒绝 |
| 域覆盖 | 14 受控字段 == 14 domain | `controlled_fields=14, PARAMETER_DOMAINS=14, match=True` |

**原始观测值 = 上述 20 项全部与期望一致；判定阈值 = 逐项行为与 Tier 1 定义、CF-1、F-2 锁语义吻合；结论 = 通过。**

---

## 四、 架构纪律核验

1. **`parameter_contract.py` 改动为单点委托**：diff 仅 2 处（import + `CellCalibrationRecord.__post_init__` 调用 `validate_cell_parameters(self)`），未重写任何既有解析逻辑。✓
2. **禁区字面量清零**：`grep -rn "0\.83|0\.90|0\.95" src/contract` → 0 命中。✓（Code Review 自报的 `degenerate_note` "0.90" 已修正为"经验覆盖率（标称分位点理论目标值）"）
3. **`require_effective_domain` 双保险锁**：`if "LOCKED" in domain.lock_state or (tier2_lower is None and tier2_upper is None)` — 杜绝单侧域短路放行。✓
4. **T19 AST 扫描防空断言**：`assert len(contract_py_files) >= 4` 存在。✓
5. **T20 域覆盖机械派生**：由 `fields(CellCalibrationRecord) - IDENTITY_FIELDS` 动态计算，非手抄字段列表。✓
6. **单向依赖**：`parameter_domains.py` 零项目内 import（仅 stdlib），无循环 import 风险。✓
7. **Tier 2 全部 LOCKED**：14/14 字段 `tier2_lower` 与 `tier2_upper` 均为 `None`，`tier2_tuning_ticket = "Phase 2 Task 08 - Ticket 23 (#156)"`。✓
8. **未引入业务门禁推导**：`v1_coverage_90_pass` 仅做 bool 类型校验，未断言与 `v1_coverage_90 >= 0.90` 的关系（回归探针 `v1_coverage_90=0.884615, pass=True` 通过）。✓

---

## 五、 文档与台账更新核验

- `docs/adr/ADR-0019：物理模型参数向投注算法消费契约与解耦架构.md`：追加**附录 A**（56 行），标注"已对齐 ADR-0019-Ticket26-v1"，含两级域模型定位、单向依赖图、17 字段受控域登记表、CF-1 跨字段不变量与架构纪律声明。既有章节未改写。✓
- `specs/phase2-task08-class1-pricing-betting-spec.md` §三 表：Ticket 25 标记为「已完成 (Closed / CHK-14 通过)」；新增 Ticket 26（#159）行；Ticket 05 依赖更新为 `Blocked by #137, Ticket 26`。✓
- `STATUS.md` / `docs/ROADMAP.md`：同步登记 Ticket 26 成果。✓

---

## 六、 观察项登记（O-1）

1. **O-1（格式一致性，非阻塞）**：Ticket 05 依赖栏写作 `Blocked by #137, Ticket 26`，其中"Ticket 26"未统一为 issue 号 `#159`。与同表其他依赖项（均用 `#NNN`）格式略不一致，但语义无歧义。建议在 Ticket 05 正式下发时统一为 `#159`。

---

## 七、 签署与不可变声明

本单由复核方独立签发，结论：**Ticket 26（#159）首轮交付复核通过，具备关闭条件**。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
