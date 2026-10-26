# P8-CLASS1-LAUNCH-CHK-11 · Ticket 02 整改复验单

> **日期**：2026-10-26
> **A 线锚点**：`Phase 2 Task 08 - Ticket 02` / [#135](https://github.com/oasislin/Poly2/issues/135)
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-11`
> **复核对象**：`605eeb0`（fix 契约看门狗）、`744cf72`（docs 治理）
> **前序单据**：`P8-CLASS1-LAUNCH-CHK-10`（首轮不通过，不可变）
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）

---

## 一、 复验结论

**通过**。CHK-10 所列 1 项阻塞（B-1 `is_valid` Fail-Open）与 1 项阻断（D-3 生产绕过语义）均已整改并经独立实测确认；R-3/R-4 裁决保留项维持有效；R-5~R-8 同批次要项已落实。无新增阻塞项。

---

## 二、 门禁独立复验（复核方本机实测）

| 门禁 | 原始观测 | 判定阈值 | 结论 |
|---|---|---|---|
| G1 | `27 passed` | 全绿且用例数 ≥ 23 | 通过 |
| G2 | `39 passed` | 全绿 | 通过 |
| G3 | `152 passed` | 全绿 | 通过 |
| G4 | `is_valid=True, verified_cells_count=22, failed_entries=0, skipped_6h_entries=64, bypassed=False` | 22 / 64 / False | 通过 |
| G5 | `## main...origin/main [ahead 5]`，working tree clean | ahead 且无未授权 push | 通过 |
| G6 | `git diff --stat src/modeling/registry.py src/contract/parameter_contract.py` → 空 | 输出为空 | 通过 |
| G7 | `git diff --stat docs/audit/P8-CLASS1-LAUNCH-CHK-09_*` → 空 | 输出为空 | 通过 |
| 变更面 | 6 文件 / +290 / −55 | 与交付汇报一致 | 通过 |
| 用例守恒 | 19 → 27（+8），无既有用例被删 | 无删减 | 通过 |

---

## 三、 行为级探针（真实 manifest，非 mock）

| 探针 | 输入 | 原始观测 | 判定 |
|---|---|---|---|
| P1 | 非生产 + 绕过变量=`"1"` | `is_valid=False, bypassed=True, verified=0` | B-1 已修复 |
| P2 | 非生产 + 绕过变量=`"true"` | `is_valid=True, bypassed=False, verified=22` | D-2 只认字面量 `"1"` |
| P3 | 生产 + 绕过变量未设 | `is_valid=True, bypassed=False, verified=22` | D-3 已修复 |
| P4 | 生产 + 绕过变量=`"1"` | 抛 `SecurityViolationError` | 防线二有效 |

---

## 四、 代码级不变量复核

| 项 | 证据 |
|---|---|
| 无宽泛异常吞噬 | `except Exception` / `except:` 扫描结果为空 |
| 22 格硬断言保留 | `len(seen_cells) != TOTAL_AUTHORIZED_CELLS` 触发抛错 |
| 6h 显式排除保留 | `AUTHORIZED_LEADS_FOR_GUARD` 常量判定，仅 WARN |
| D-1 版本闸门保留 | `contract_version != CONTRACT_VERSION` 抛 `StaleModelParametersError` |
| R-6 语义拆分 | `ManifestIntegrityError` 新增并导出；`PickleCorruptionError` 收敛为 .pkl 专有 |
| R-5 无裸 KeyError | `_parse_model_entry` 统一 `.get()` + 类型校验 |

---

## 五、 R-1 ~ R-8 落实对照

| 项 | 要求 | 实测证据 | 判定 |
|---|---|---|---|
| R-1 | 绕过分支 `is_valid=False` + 字段 docstring + 守护用例 | P1 实测 + 27 项用例含 `test_bypass_report_is_not_valid` | 通过 |
| R-2 | 生产仅变量=`"1"` 时拒，未设则全量校验 | P3 / P4 | 通过 |
| R-3 | 版本闸门保留 + docstring | L223-226 | 通过 |
| R-4 | docstring 明确只认 `"1"` + 严格判定用例 | P2 + `test_bypass_env_value_must_be_literal_one` | 通过 |
| R-5 | 消除裸 KeyError | `_parse_model_entry` | 通过 |
| R-6 | 拆分 `ManifestIntegrityError` | 新类 + `__init__` 导出 | 通过 |
| R-7 | 非 6h 非法定 lead 补 debug 日志 | 代码已落 | 通过 |
| R-8 | M-3 docstring；M-5 结转 Ticket 04 | 字段 docstring + CHK-10 §三 M-5 行 | 通过 |

---

## 六、 遗留观察（不阻塞签发）

1. **M-5 结转**：校验覆盖 176 条（含 `AUXILIARY_POOLED_FALLBACK` 32 / `PHASE-CLUSTER-FAILSAFE` 16），交易法定 `STATUTORY_TRADING_MASTER` 为 144 条。须在 Ticket 04 接入前厘清「法定消费范围 vs 完整性校验范围」口径。
2. **CHK-10 首页缺 A 线锚点**：R-10.3 新口径要求 B 线单据正文首页写明对应 A 线 Issue；CHK-10 为不可变历史件，不回改。本单（CHK-11）为口径生效后首个带头锚点的示范件。
3. **交付端汇报措辞**：其「100% 对齐、无偏差」表述应修正为「按工作单执行完毕；新口径对 CHK-10 自身的回溯适用由 CHK-11 示范」。

---

## 七、 签发

本单由复核方签发，结论：**Ticket 02（#135）整改复验通过，具备关闭条件**。

> **本轮记录一经签发不再改写；后续任何追加发现另开 `P8-CLASS1-LAUNCH-CHK-12`。**
