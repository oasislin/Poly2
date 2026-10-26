# P8-CLASS1-LAUNCH-CHK-14 · Ticket 25 交付复核单

> **日期**：2026-10-26  
> **A 线锚点**：`Phase 2 Task 08 - Ticket 25` / [#158](https://github.com/oasislin/Poly2/issues/158)  
> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-14`  
> **复核对象**：`11fe7de`（Ticket 25 契约层加固）  
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）  

---

## 一、 复核结论

**通过**。Ticket 25 针对 Ticket 01 既有交付件中遗留的 D1~D8 八项数据模型缺陷全部实施了严格的防御性加固，所有非法参数与结构缺陷由隐式静默通过彻底转为显式抛错；不可变性深冻结机制经验证有效；`CONTRACT_VERSION` 严格恒定未 bump。本单首轮复核即完全达标，准予结项。

---

## 二、 门禁独立复验（复核方本机实测）

| 门禁 | 命令 / 探针 | 原始观测值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | `pytest tests/unit/contract/test_parameter_contract.py -q` | `20 passed in 0.05s` | 全绿（20 用例全部通过） | 通过 |
| **G5** | `pytest tests/unit/contract -q` | `74 passed in 1.42s` | 全绿（契约全套 74 用例） | 通过 |
| **G6** | `pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q` | `187 passed in 1.68s` | 全绿（跨层无破坏） | 通过 |
| **G8** | AST 函数长度扫描 | `max lineno span = 40` (L158-L197 `from_dict`) | 严格 `< 50` 行 | 通过 |
| **G12** | `CONTRACT_VERSION` 常量比对 | `CONTRACT_VERSION = "ADR-0019-Ticket01-v1"` | 未 bump，字面量保持一致 | 通过 |

---

## 三、 D1~D8 八项加固落地对照

| 缺陷编号 | 加固前风险 | 加固后防御实现（`src/contract/parameter_contract.py`） | 独立探针与测试用例验证 |
|---|---|---|---|
| **D1** | `station` 允许任意字符串 | 严格校验必须属于 `AUTHORIZED_STATIONS` (`{"KORD", "KMIA"}`)，否则抛 `ContractValidationError` | `test_invalid_station_raises` 通过 |
| **D2** | `variable` 允许非标量 | 严格限定仅允许 `"max"`（第一类投注法定），非法取值抛 `ContractValidationError` | `test_invalid_variable_raises` 通过 |
| **D3** | `lead_hours` 允许任意整数 | 严格限制为 `AUTHORIZED_LEAD_HOURS` (`12..72h` 步长 6h，排除 6h），非法抛错 | `test_invalid_lead_hours_raises` 通过 |
| **D4** | `weights` 键语义混淆且允许任意对象 | 规范为 `model_weights_sha256: Mapping[str, str]`，强校验键为 `.pkl` 结尾、值为 64 位十六进制 SHA256 | `test_invalid_model_weights_format_raises` 通过 |
| **D5** | `created_at` 接受任意格式文本 | 强制校验必须符合严格 ISO-8601 UTC 格式，无法解析即抛错 | `test_invalid_created_at_format_raises` 通过 |
| **D6** | `total_cells` 冗余未核验 | 强校验 `total_cells == len(cells) == TOTAL_AUTHORIZED_CELLS (22)`，不一致抛错 | `test_total_cells_mismatch_raises` 通过 |
| **D7** | `cells` 键名与内容脱节 | 强制校验键名必须为 `{station}_{lead}h` 且与其内部字段完全一致，且必须满 22 格无重无漏 | `test_cells_missing_or_extra_raises` 通过 |
| **D8** | 契约对象构建后属性可被篡改 | 对 `cells` 与 `model_weights_sha256` 采用 `MappingProxyType` 进行运行时深冻结，属性赋值立即抛 `TypeError` | `test_immutability_mapping_proxy` 通过 |

---

## 四、 架构基线与治理记载

1. **授权变更已关闭交付件形成新基准**：
   - 本次修改经正式授权，对已关闭 Ticket 01 交付件 `src/contract/parameter_contract.py` 实施破坏性加固，形成 Phase 2 物理参数契约的新基准线（Baseline）。
2. **零版本震荡原则落实**：
   - 尽管契约解析机制与内部数据模型进行了全方位严格加固，但对外契约版本标识 `CONTRACT_VERSION` 恒定维持 `"ADR-0019-Ticket01-v1"`，避免向下游引发不必要的版本升级震荡。
3. **不可变性深冻结机制**：
   - 采用标准库 `types.MappingProxyType` 封装暴露的只读映射视图，确保数据契约自装配完成后具有只读物理不可篡改性。

---

## 五、 签发

本单由复核方签发，结论：**Ticket 25（#158）交付复核通过，具备关闭条件**。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
