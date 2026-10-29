# P8-CLASS1-LAUNCH-CHK-19 · Ticket 06 首轮交付复核单

> **日期**：2026-10-27  
> **A 线锚点**：`Phase 2 Task 08 - Ticket 06` / [#139](https://github.com/oasislin/Poly2/issues/139)  
> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-19`  
> **复核对象**：`b5216f7`（feat 双轨实现）、`04c210c`（fix M-1 / O-1~O-3 微整改）  
> **前序单据**：`CHK-18`（Ticket 05 复验通过，契约层全量封盘）  
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）  

---

## 一、 复核结论

**通过**。Ticket 06 成功将 Q7 覆盖率两个口径（exact / gaussian_proxy）抽离为语义独立、上下文互斥的两个类，行为与冻结的结算审计脚本**逐字等价**（实测最大绝对偏差 = 0.0），三不混用防御由类型系统 + 上下文强校验双层落实，且两轨间无任何共享逻辑。首轮阻塞项 M-1 与观察项 O-1~O-3 经单一微整改 commit（`04c210c`）全部闭环，准予结项。

---

## 二、 门禁独立复验（复核方本机实测原始值）

| 门禁 | 命令 / 探针 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | `python -m pytest tests/unit/pricing -q` | `14 passed in 7.15s` | 全绿，≥ 12 | 通过 |
| **G2** | `python -m pytest tests/unit/pricing tests/unit/contract -q` | `133 passed` | 全绿，≥ 131 | 通过 |
| **G3** | `python -m pytest tests/unit/pricing tests/unit/contract tests/unit/risk tests/unit/prediction -q` | `246 passed in 18.83s` | 全绿，≥ 244 | 通过 |
| **G4** | AST 函数长度扫描（`src/pricing/`） | `max_len = 39`，超 50 行 = 0 | 严格 `< 50` | 通过 |
| **G5** | 浮点字面量白名单（AST） | `{0.0, 0.05, 0.95, 1.6448536269514722}`，subset = True | ⊆ 白名单 | 通过 |
| **G6** | 禁区产物差分 | `git diff 6a59c0e..HEAD --stat -- data/ evidence/ scripts/evaluate_p4_2019_settlement.py` 输出为空（exit 0） | 输出为空 | 通过 |
| **G7** | 宽泛异常扫描（`src/pricing`） | `except Exception` / 裸 `except:` → 0 命中（grep exit 1） | 0 命中 | 通过 |
| **G8** | Git 纪律 | `## main...origin/main [ahead 1]`，工作树 clean，未 push | clean 且未 push | 通过 |
| **附加** | G5 门禁带字面量 | `src/pricing` 内 `0.83` 命中 0 | 0 命中 | 通过 |

---

## 三、 行为等价钉死核验（本单最强证据）

复核方以真实资产 `evidence/p4_active10_climate_calibration.json` 中 **KORD / Winter**（`selected_family = johnsonsu`，`shape_params` 键 `gamma/delta/xi/lambda`）为输入，`mu = 72.5`、`sigma_eff = 1.85`，直连冻结脚本 [compute_model_90_coverage_bounds](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/evaluate_p4_2019_settlement.py#L146-L170) 逐值比对：

```
exact  got: (69.90910348065484, 75.79187553925915)
exact  ref: (69.90910348065484, 75.79187553925915)
max abs diff = 0.0
```

`原始观测值 = 最大绝对偏差 0.0；判定阈值 = ≤ 1e-12；结论 = 通过。`

`gaussian_proxy` 轨输出与 `mu ± Z_90_HALF_WIDTH · sigma_eff`（`Z = 1.6448536269514722`）精确一致。

> `evt_hybrid` 以拼接点 `u_left/u_right` 充当 z 分位的既有近似口径**未被改动**，符合工作单"不得顺手修正"约束。

---

## 四、 三不混用与解耦防御核验（复核方自建对抗探针）

| 探针 | 复核方实测结果 |
|---|---|
| `ExactCoverageTrack.bounds` 传 `ONLINE_PRICING` | 抛 `CoverageTrackMisuseError` |
| `GaussianProxyCoverageTrack.interval` 传 `OFFLINE_AUDIT` | 抛 `CoverageTrackMisuseError` |
| 两轨方法传 `context = None` | 抛 `CoverageTrackMisuseError` |
| **裸字符串** `"OFFLINE_AUDIT"` / `"ONLINE_PRICING"`（O-1 整改后） | 抛 `CoverageTrackMisuseError` |
| 构造器传非法/错轨 context | 抛 `CoverageTrackMisuseError` |
| 构造器传合法 context | 正常实例化（无异常） |
| 未知族 `student_t` | 抛 `UnsupportedDistributionFamilyError` |
| `sigma_eff ∈ {0.0, -1.0, nan, inf}` | 均抛 `InvalidCoverageInputError` |
| `johnsonsu` 缺 `gamma` | 抛 `KeyError`（零默认兜底） |
| 空 observations 序列（O-2 整改后） | 抛 `InvalidCoverageInputError` |
| 类型隔离 | `CoverageInterval` 无 `coverage_rate`；`CoverageRate` 无 `lower/upper` |

**AST 解耦断言**：代理轨源码中 `johnsonsu` / `shape_params` / `evt_hybrid` / `ExactCoverageTrack` 命中 = 0；exact 轨中 `GaussianProxyCoverageTrack` / `CoverageInterval` 命中 = 0。两轨互不继承、互不调用，唯一共享为两个数学常量。

---

## 五、 微整改闭环记载

| 项 | 发现事实（首轮） | 整改措施 | 复核方验证 |
|:---|:---|:---|:---|
| **M-1（阻塞）** | `NOMINAL_INTERVAL_LEVEL = 0.95 - 0.05` 在二进制浮点下求值为 `0.8999999999999999`，下游 `== 0.90` 断言会静默失败 | 改为 `round(0.95 - 0.05, 12)` | 实测 `repr(NOMINAL_INTERVAL_LEVEL) = 0.9`，`interval.interval_level == 0.9` → `True`；浮点字面量集未变（`12` 为整数） |
| **O-1** | `TrackContext(str, Enum)` 下裸字符串可绕过严格类型 | 三处校验增加 `not isinstance(context, TrackContext)` | 裸字符串探针实测抛错；合法枚举仍可实例化 |
| **O-2** | `coverage()` 的 `else 0.0` 为死分支 | 精简为 `rate = hits / total` | 空序列路径由前置校验拦截，抛 `InvalidCoverageInputError` |
| **O-3** | 构造器缺类型强校验 | `__init__` 同步补 `isinstance` | 构造器传裸字符串实测抛错 |

> M-1 的设计缺陷源自复核方首轮工作单中 `0.95 - 0.05` 的写法（为规避 `0.90` 字面量），**责任在复核方**，此处如实登记。

---

## 六、 交付范围核验

`git diff 6a59c0e..HEAD --stat` 实测：

| 文件 | 变更 |
|---|---|
| `src/pricing/coverage_dual_track.py` | +18 / −7（含 M-1 与 O-1~O-3） |
| `tests/unit/pricing/test_coverage_dual_track.py` | +18 |
| `docs/audit/P8-CLASS1-LAUNCH-TICKET06_交付回执_20261027.md` | +4 / −4 |
| `STATUS.md` / `docs/ROADMAP.md` | 状态同步登记 |

零 `data/`、零 `evidence/`、零冻结脚本改动。

---

## 七、 观察项登记（O-1 ~ O-3，非阻塞）

1. **O-1（后续版本增强建议）**：`TrackContext` 同时继承 `str` 与 `Enum` 带来双重可比较性，虽已加 `isinstance` 硬校验，仍建议后续版本评估是否改为纯 `Enum`（影响面需单独评估，本票不动）。
2. **O-2（语义近似口径留痕）**：`evt_hybrid` 以拼接点充当 5%/95% 分位属既有近似，其与 `johnsonsu` 的语义差异未在本票澄清，建议 Ticket 07/08 在 σ_adj 与 EV 环节明确该近似的影响边界。
3. **O-3（下游断言基线）**：`interval_level` 现为精确 `0.9`，Ticket 08/09 可直接做等值断言，无需容差；后续若调整名义水平须同步更新本模块唯一常量。

---

## 八、 签署与不可变声明

本单由复核方签发，结论：**Ticket 06（#139）首轮交付复核通过，具备关闭条件**。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
