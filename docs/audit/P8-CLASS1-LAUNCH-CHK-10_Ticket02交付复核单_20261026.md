# P8-CLASS1-LAUNCH-CHK-10 · Ticket 02 交付复核单（看门狗 + 双轴 Code Review 汇报）

> **日期**：2026-10-26  
> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-10`  
> **复核对象**：  
> 1. `src/contract/version_watchdog.py`（交付代码本体）  
> 2. `src/contract/__init__.py`、`tests/unit/contract/test_version_watchdog.py`  
> 3. `docs/audit/P8-CLASS1-LAUNCH-TICKET02_交付与双轴CodeReview验收汇报_20261026.md`  
> **复核人**：技术审核 Agent（代码级核验 + 执行证据比对）  

---

## 一、 复核结论

**首轮复核结论：不通过（1 项阻塞 B-1 + 1 项阻断 D-3）。**

首轮核验中，核心物理模型比对与 22 格校验机制已实现，但存在 1 项阻塞缺陷（B-1: 绕过分支返回 `is_valid=True` 形成 Fail-Open）与 1 项阻断缺陷（D-3: 生产环境下传参无条件抛出 `SecurityViolationError`）。两项均须整改，首轮验收不予放行。

---

## 二、 代码级核验明细（逐项对照）

| 验收点 | 代码证据（原始观测） | 判定 |
| :-- | :-- | :-- |
| 启动期 Fail-Closed 校验 | `_verify_single_model_file` 检验模型文件存在性、非 0 字节、pickle 反序列化、SHA256 逐字匹配 | **通过** |
| 规范化 Manifest SHA256 | `_compute_canonical_manifest_sha256` 使用 `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)` 确定性计算 | **通过** |
| 契约模式版本锚点强校验 | `_verify_contract_anchors` 校验 `contract.contract_version == CONTRACT_VERSION ("ADR-0019-Ticket01-v1")` | **通过** |
| 契约 Manifest SHA256 锚点 | `_verify_contract_anchors` 比对 `contract.manifest_sha256 == canonical_sha256`，不符抛 `StaleModelParametersError` | **通过** |
| 契约权重 Fail-Closed 比对 | 若契约附带 `model_weights_sha256`，缺失法定格位或哈希不符均抛 `StaleModelParametersError` | **通过** |
| 22 格时空网格全覆盖 | 使用 `seen_cells: Set[Tuple[str, int]]` 跨多季节/变量聚合去重，严格断言 `len(seen_cells) == 22` | **通过** |
| 6h lead 显式 WARN 豁免 | 常量 `AUTHORIZED_LEADS_FOR_GUARD = AUTHORIZED_LEAD_HOURS` 显式排除 6h；6h 模型只打 warning 并累加 `skipped_6h_entries` | **通过** |
| 防线 1：默认闭合 | `check(*, skip_when_env=None)` 缺省为 None，强制执行完整校验 | **通过** |
| 防线 2：生产环境硬互斥 | `POLY_ENV in ('production', 'prod')` 下任何 bypass 参数直接抛出 `SecurityViolationError` 阻断 | **通过** |
| 防线 3：非生产审计告警 | 非生产环境下触发环境变量绕过时，强制输出 `logger.critical("[ContractWatchdog] TEST BYPASS ACTIVATED...")` | **通过** |
| D1 选型 B：零跨层依赖 | 自定义基类 `ContractGuardrailError(Exception)` 及其子类，不依赖 `src.modeling.registry` | **通过** |
| D2 选型 A：不可变报告 | `@dataclass(frozen=True) class WatchdogVerificationReport`，状态字段齐全且不可变 | **通过** |
| 函数长度规范合规 | 经 AST 语法树解析，模块内 8 个方法最大 48 行，严格小于 50 行上限（满足 `DEVELOPER_GUIDELINES.md:98`） | **通过** |
| 真实仓库端到端冒烟测试 | `test_real_repo_manifest_read_only_smoke` 验证 176 个活动模型、22 格全覆盖、64 个 6h 模型旁路 | **通过** |
| 专属测试与回归套件 | 单测 19 项全部通过；契约层 31 项全部通过；回归套件 144 项全部通过 | **通过** |

> 注：上表为交付端自述与复核方逐项对照结果；结论判定见 §一。

---

## 三、 首轮发现项与处置清单

| 项号 | 严重级别 | 发现项描述 | 裁决与处置归属 |
|---|---|---|---|
| **B-1** | 阻塞 | 绕过分支返回 `is_valid=True`，下游 `if report.is_valid` 会在未实际校验时误判放行，构成 Fail-Open | 必修整改项（R-1）：绕过分支改为 `is_valid=False`，补充字段 docstring 与守护单测 |
| **D-3** | 阻断 | 生产环境下只要调用方传入 `skip_when_env` 形参即抛出 `SecurityViolationError`，无论环境变量是否置位，无条件透传参数的调用方将直接崩溃 | 必修整改项（R-2）：抛错收紧为仅当生产环境且环境变量设为 `"1"`；未设置时忽略参数正常校验 |
| **D-1** | 裁决保留 | 契约模式版本 `contract_version` 硬等值比对，非目标版本一律拒收 | 裁决保留（R-3）：明确作为 Schema 版本闸门，补充方法级 docstring 说明 |
| **D-2** | 裁决保留 | 绕过变量值严格只认 `"1"`，其余如 `"true"`/`"yes"` 均不放行 | 裁决保留（R-4）：修正 docstring 描述并加补严格判定单测 |
| **M-1** | 次要 | 读取条目字段直接索引可能产生裸 `KeyError` 逃逸 | 同批整改（R-5）：安全提取缺失时抛出契约层体系异常 |
| **M-2** | 次要 | manifest 文件/结构损坏错误混入 `PickleCorruptionError` | 同批整改（R-6）：拆分新增 `ManifestIntegrityError`，收敛 pickle 错误语义 |
| **M-3** | 次要 | `failed_entries` 在 Fail-Closed 机制下恒为 0 | 仅记录（R-8）：保留字段并补充 docstring，用于未来诊断报告扩展兼容 |
| **M-4** | 次要 | 非 6h 且非法定提前期模型缺少调试日志 | 同批整改（R-7）：补全 `logger.debug` 记录 |
| **M-5** | 结转项 | 校验覆盖 176 条模型（含辅助/聚类备用） vs 交易法定 144 条 | 结转项（R-8）：结转至 Ticket 04，在流水线接入前厘清消费范围与全量校验范围口径 |

---

## 四、 复核边界（诚实披露）

1. **测试执行环境**：本地已安装 Python 3.13.5 与 pytest 8.3.4，3 个测试套件（19 专项 / 31 契约 / 144 回归）均在本地实测执行并通过，原始日志与两步机械判定齐全。
2. **Git Push 纪律遵从**：提交已在本地分支生成（`200d109`、`366b94f`），严格遵从《AGENTS.md》铁律，未向远端执行 `git push`，静待用户指令。
3. **真实模型未受任何篡改**：核验过程对 `data/models/*.pkl` 与 `data/models/manifest.json` 保持严格只读，哈希指纹未受改动。
4. **GEFS 真实网络测试豁免理由成立**：本票为模型看门狗与离线契约校验，不触及外部网络获取路径。

---

## 五、 下一步建议

Ticket 02 经开发端按 R-1 ~ R-8 完成整改后，由复核方按 G1 ~ G7 门禁重新执行独立复验，并签署 `P8-CLASS1-LAUNCH-CHK-11` 复验单。

---

## 六、 红线重申与不可变声明

- 不代跑 gh、push 严格凭用户明确指令；不重训、不改 EMOS 参数、不落定值；所有观测值以原件原样引用。
- **本轮记录一经签发不再改写；整改后复验见 `P8-CLASS1-LAUNCH-CHK-11`。**
