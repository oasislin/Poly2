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

**Ticket 02（#135）验收：通过**。ADR-0019 §二.6 启动期看门狗强校验、三道防线纵深防御、22 格全覆盖断言、6h 显式 WARN-only 旁路、真实 manifest 176 个模型文件完整性检验、双轴 Code Review 发现项重构均在代码中逐一落实；测试与汇报声明完全一致。

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

---

## 三、 复核边界（诚实披露）

1. **测试执行环境**：本地已安装 Python 3.13.5 与 pytest 8.3.4，3 个测试套件（19 专项 / 31 契约 / 144 回归）均在本地实测执行并通过，原始日志与两步机械判定齐全。
2. **Git Push 纪律遵从**：提交已在本地分支生成（`200d109`、`366b94f`），严格遵从《AGENTS.md》铁律，未向远端执行 `git push`，静待用户指令。
3. **真实模型未受任何篡改**：核验过程对 `data/models/*.pkl` 与 `data/models/manifest.json` 保持严格只读，哈希指纹未受改动。
4. **GEFS 真实网络测试豁免理由成立**：本票为模型看门狗与离线契约校验，不触及外部网络获取路径。

---

## 四、 下一步建议

Ticket 02 交付闭环后，根据 Phase 2 Task 08 架构依赖拓扑：
- **前置解锁**：Ticket 04（双城重测与契约闭环校验流水线）的看门狗接入依赖已解除；
- **建议推进顺序**：
  1. **建议推进 Ticket 03（#136）**：实现盲测标定 CSV 转 22 格法定契约 JSON 转换器与只读校验器，生成供看门狗消费的基准 `PhysicalParamContract` 数据文件；
  2. **可并行推进 Ticket 06（#139）**：实现基于 `PhysicalForecastOutput` 的两档行权概率动态计算器（Q7 双轨定价算法）。

---

## 五、 红线重申

不代跑 gh、push 严格凭用户明确指令；不重训、不改 EMOS 参数、不落定值；所有观测值以原件原样引用。
