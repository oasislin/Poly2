# P8-CLASS1-LAUNCH-CHK-20 · Ticket 07 首轮交付复核单

> **日期**：2026-11-02
> **A 线锚点**：`Phase 2 Task 08 - Ticket 07` / [#140](https://github.com/oasislin/Poly2/issues/140)
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-20`
> **复核对象**：`f34c380`（σ_adj 计算引擎 + Code Review 整改）
> **前序单据**：`CHK-19`（Ticket 06 通过）、`CHK-17`（Ticket 26 通过）
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）

---

## 一、 复核结论

**通过**。Ticket 07 建立 σ_adj 计算引擎，数学形态与 ADR-0019 §4 逐字等价，F-2 挂锁在**生产路径与守卫路径双重生效**，Code Review 提出的 4 项缺陷全部闭环，零标定数值写入 `src/`，准予结项。

---

## 二、 门禁独立复验（复核方本机实测原始值）

| 门禁 | 命令 / 探针 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | `pytest tests/unit/pricing/test_sigma_adj.py -q` | `16 passed in 0.19s` | ≥16 全绿 | 通过 |
| **G2** | `pytest tests/unit/pricing -q` | `30 passed in 7.19s` | ≥30 全绿 | 通过 |
| **G3** | `pytest tests/unit/prediction tests/unit/risk tests/unit/contract tests/unit/pricing -q` | `262 passed in 18.18s` | ≥262 全绿 | 通过 |
| **G4** | 函数长度扫描（`src/pricing` + `tests/unit/pricing`） | `funcs=42, max=42`，超 50 = 0 | `max < 50` | 通过 |
| **G5** | 宽泛异常扫描 | 命中 = 0 | 0 | 通过 |
| **G6** | `git diff 2f1a886..f34c380 -- data/ evidence/ src/contract/ src/pricing/coverage_dual_track.py` | 输出为空 | 空 | 通过 |
| **G7** | `src/pricing/sigma_adj.py` 浮点字面量 | `0`（`__init__.py` 亦为 `0`） | 0 | 通过 |
| **G8** | `git status -sb` | `## main...origin/main [ahead 1]`，未 push | 未 push | 通过 |

> G7 附注：`src/pricing` 全目录浮点字面量合计 5，全部位于 `coverage_dual_track.py`（Ticket 06 已批准的数学常量），`sigma_adj.py` 与 `__init__.py` 均为 0 —— 与本票"数值挂锁"要求一致。

---

## 三、 行为探针（复核方直连模块，绕过交付端测试）

| # | 探针 | 原始观测值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| 1 | `load_sigma_adj_policy()` | `F2LockNotReleasedError: ... LOCKED pending calibration release in #156.` | 必须抛错且含 #156 | 通过 |
| 2 | 22 格真实 `s_oos` 全量比对（`σ_eff=1.0`） | 最大偏差 `0.000e+00` | ≤ 1e-12 | 通过 |
| 3 | `s_oos < 1.0` 的 4 格（KORD 12h/36h/60h/66h） | `σ_adj == 1.0` 精确相等（True） | 精确相等 | 通过 |
| 4 | 最大膨胀格 KMIA_30h（`s_oos=1.363831`） | `ratio = 1.167832` | 与 √s_oos 一致 | 通过 |
| 5 | `lock_state` 裸串 `"F-2 LOCKED"` | `F2LockNotReleasedError` | 必须抛错 | 通过 |
| 6 | `lock_state = SigmaAdjLockState.LOCKED` | `F2LockNotReleasedError` | 必须抛错 | 通过 |
| 7 | 非法策略：`exponent ∈ {0.0, -0.5, nan}` | 均 `InvalidSigmaAdjPolicyError` | 必须抛错 | 通过 |
| 8 | 非法策略：`floor ∈ {0.9, 0.99}` | 均 `InvalidSigmaAdjPolicyError` | 必须抛错（`floor<1` 等于允许收窄） | 通过 |
| 9 | 非法策略：`lock_state ∈ {"RELEASED", "whatever"}` | 均 `InvalidSigmaAdjPolicyError` | 必须抛错 | 通过 |
| 10 | 合法对照：`lock_state` 枚举 / 裸串 `"F2_RELEASED"` | 均构造成功 | 向后兼容 | 通过 |
| 11 | `sigma_eff ∈ {0.0, -1.0, nan, inf}` | 均 `InvalidSigmaAdjInputError` | 必须抛错 | 通过 |
| 12 | `s_oos ∈ {-1.0, nan, inf}` | 均 `InvalidSigmaAdjInputError` | 必须抛错 | 通过 |
| 13 | 未授权格 `("KATL", 12)` | `KeyError` | 必须抛错，不得回退他格 | 通过 |
| 14 | 格级路由 `KORD_12h=1.0` vs `KMIA_30h=1.167832` | 差值 `0.167832`（>0） | 无均值化 | 通过 |
| 15 | 尺度线性：`σ_eff` 1.0 → 2.0 | 比值 `2.0` | 恒等 | 通过 |
| 16 | `SigmaAdjPolicy` 可变性 | `FrozenInstanceError` | 不可变 | 通过 |

---

## 四、 Code Review 整改项闭环核验

| 项 | 交付端整改声明 | 复核判定 |
|---|---|---|
| 消除重复校验 | 策略不变量统一收敛到 `SigmaAdjPolicy.__post_init__` | 通过（构造期即抛 `InvalidSigmaAdjPolicyError`，引擎内无二次校验） |
| 消除基本类型偏执 | 新增 `SigmaAdjLockState(str, Enum)`（`LOCKED` / `RELEASED`） | 通过（枚举与裸串双通道均被正确识别，裸串非约定值被拒） |
| 消除死 Fixture | `test_t01` 直接消费 `physical_contract.cells` | 通过（G1 16 条全绿，无额外磁盘读） |
| 强类型协议解耦 | 新增 `CellRecordProtocol` / `ParameterContractProtocol` 替换 `contract: Any` | 通过（`sigma_adj_for_cell` 形参已为协议类型） |

---

## 五、 F-2 治理合规性（本票核心）

1. **生产路径熔断**：`load_sigma_adj_policy()` 无条件抛 `F2LockNotReleasedError`，消息指向 `#156` → 生产环境无法取得任何 σ_adj 数值。
2. **守卫路径熔断**：即便外部硬构造 `lock_state="F-2 LOCKED"` 的策略，`compute_sigma_adj` 仍拒绝求值 —— 双重防线。
3. **零标定数值落码**：`sigma_adj.py` 与 `__init__.py` 浮点字面量均为 0，符合"标定与上线挂锁、规格书结构可先写"的 F-2 优先律。
4. **解锁路径**：Ticket 23（#156）标定完成后仅需回填策略源，引擎与测试零改动。

---

## 六、 观察项登记（O-1 ~ O-3，均不阻塞）

1. **O-1（模块命名空间外溢）**：`sigma_adj.py` 未定义 `__all__`，`dir()` 可见 `Enum`/`Protocol`/`dataclass`/`math` 等导入符号。建议后续统一补 `__all__`，纯代码卫生问题。
2. **O-2（裸串未归一化）**：`lock_state` 接受裸串 `"F2_RELEASED"` 时**不归一化为枚举**（实测 `repr` 保持 `'F2_RELEASED'`）。因 `SigmaAdjLockState` 继承 `str`，`==` 比较安全；但下游若使用 `is` 身份比较会失败，建议后续统一在 `__post_init__` 归一化。
3. **O-3（Tick 计量）**：本票交付文件命中 `STATUS.md` / `ROADMAP.md` 同步，与 Ticket 06 一致；后续若出现状态文档频繁微改，建议合并为按 Sprint 更新，减少噪声提交。

---

## 七、 签署与不可变声明

本单由复核方签发，结论：**Ticket 07（#140）首轮交付复核通过，具备关闭条件**。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
