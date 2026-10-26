# P8-CLASS1-LAUNCH-CHK-13 · Ticket 03 整改复验单

> **日期**：2026-10-26  
> **A 线锚点**：`Phase 2 Task 08 - Ticket 03` / [#136](https://github.com/oasislin/Poly2/issues/136)  
> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-13`  
> **复核对象**：`9cabc96`（首轮）、`d52d8ae`（整改）、`8aeba06`（产物重生成）、`8351b64`（函数拆分与回执落盘）  
> **前序单据**：`P8-CLASS1-LAUNCH-CHK-12`（首轮不通过，不可变）  
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）  

---

## 一、 复验结论

**通过**。CHK-12 所列 2 项阻塞（B-1 cell 串未双向交叉校验、B-2 回执与实测不符）已彻底整改；R-3（AST 行数合规）与 R-4（回执落盘入库）均已收口；D-3 授权变更完成并经全套单测回归验证。无新增阻塞缺陷，准予结项。

---

## 二、 门禁独立复验（复核方本机实测）

| 门禁 | 命令 / 探针 | 原始观测值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | `pytest tests/unit/contract/test_parameter_contract.py -q` | `20 passed in 0.05s` | 全绿（20 用例） | 通过 |
| **G2** | `pytest tests/unit/contract/test_param_table_converter.py -q` | `16 passed in 1.62s` | 全绿（16 用例） | 通过 |
| **G3** | `pytest tests/unit/contract/test_param_table_validator.py -q` | `8 passed in 0.11s` | 全绿（8 用例） | 通过 |
| **G4** | `pytest tests/unit/contract/test_version_watchdog.py -q` | `30 passed in 1.48s` | 全绿（30 用例） | 通过 |
| **G5** | `pytest tests/unit/contract -q` | `74 passed in 1.42s` | 全绿（74 用例） | 通过 |
| **G6** | `pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q` | `187 passed in 1.68s` | 全绿（187 用例） | 通过 |
| **G8** | AST 函数长度扫描 (`max lineno span`) | 转换器 46 行 / 校验器 27 行 / 看门狗 39 行 / 契约 40 行 | 所有函数严格 `< 50` 行 | 通过 |
| **G10** | `PhysicalParamTableValidator.validate_json` | 返回 `True`，`cells=22`，`weights=88` | 22 格 + 88 权重完全自洽 | 通过 |
| **G11** | `ContractVersionWatchdog.check()` 真实看门狗核验 | `is_valid=True, verified_cells_count=22, failed_entries=0, skipped_6h_entries=64, bypassed=False` | `is_valid=True, failed=0` | 通过 |

---

## 三、 核心缺陷整改与核验记载

1. **R-1 / B-1 修复（cell 身份双向交叉校验）**：
   - `param_table_converter._build_single_cell_record` 实现双向交叉断言：解析 `cell` 必须严格由 `{station}_{variable}_{lead_hours}h` 格式构成，且 `station`、`variable` 与 `lead_hours` 必须与整行数据逐字匹配；
   - `comparison` 表中同样强制断言 `station` 与 `{lead}h` 前后缀必须与各指标列所属 cell 严格一致，任何错配立即抛出 `ContractConversionError`。
2. **M-2 88 条文件名键权重落盘**：
   - 契约产物 `data/contracts/physical_param_contract.json` 中，`model_weights_sha256` 字典已完整写入双城（KORD, KMIA）× 11 时效（12h..72h）× 4 季节 = 88 个法定 `max` 模型文件名键与其 SHA256 哈希；
   - 严格落实裁决 D6：16 个带有 `AUXILIARY_POOLED_FALLBACK` 状态标签的模型（如 60h 整档及部分 66h/72h）全部保留并入库，无准入排除。
3. **M-1 `manifest_path` 必填化**：
   - `convert_v2_blindtest_to_contract` 与 `PhysicalParamTableConverter` 彻底移除默认 `manifest_path=None`，强制要求显式传入并断言文件存在且为 `.json`，杜绝静默跳过模型哈希校验。
4. **R-2 报告更正**：
   - 废除首轮估算式 git diff 输出，所有 diffstat 与单测用例数完全由机器实测执行生成并逐字记录。
5. **R-3 / R-4 收口**：
   - **AST 函数行数合规（R-3）**：对超出 50 行红线的 `_extract_model_weights_from_manifest`（79 行）与 `_verify_model_weights`（53 行）进行了纯结构性解耦拆分，拆分后全模块最大函数行数为 46 行（均 `< 50` 行）；
   - **回执正式落盘入库（R-4）**：将执行回执正文落盘至 `docs/audit/P8-CLASS1-LAUNCH-TICKET03-RECEIPT.md` 并纳管入库。
6. **D-3 授权变更记录（关闭件向前兼容升级）**：
   - 经正式授权，已关闭 Ticket 02 交付件 `src/contract/version_watchdog.py` 实施向前兼容升级：模型权重键语义由抽象格键 `cell_key`（`{station}_{lead}h`）升级为具体文件名键 `model_filename`（`{station}_{season}_{variable}_lead{lead}h.pkl`）；
   - 同步更新测试用例断言，Ticket 02 守护测试集扩充至 30 项且持续 100% 通过（G4: 30 passed）。

---

## 四、 结转事项（结转至 Ticket 04 接入）

依据架构设计与复核意见，下列事项不阻塞 Ticket 03 签发，正式结转至 Ticket 04 处理：

1. **M-3 宽泛 except 结转 Ticket 04**：
   流水线与抽取脚本中若存在宽泛异常捕获，在 Ticket 04 编写重测封装脚本与审计流水线时，统一收敛为显式精确异常体系。
2. **M-5 多维口径勘定结转 Ticket 04**：
   在流水线端到端串联前，对以下四层资产口径进行最终对账锁定：
   - **88 条**：当前落盘契约法定消费的最高温模型权重哈希；
   - **144 条**：交易法定主表模型范围；
   - **176 条**：看门狗当前双城 12h..72h 完整性校验覆盖全量；
   - **22 格**：第一类投注算法核心消费的离散参数格（双城 × 11 时效）。

---

## 五、 签发

本单由复核方签发，结论：**Ticket 03（#136）整改复验通过，具备关闭条件**。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
