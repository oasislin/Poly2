# P8-MODEL PENDING：未阻塞待办登记（2026-11-10）

> ⚠️ **历史快照（只读留档 · 2026-11-21 标定）**：本文档反映 **[2026-11-10 `P8-MODEL` 第二步核验未阻塞待办记录]** 之历史事实与并账前原貌，其唯一活条目 **`P8-MODEL-PENDING-01`（`OPEN / NON-BLOCKING`）已于 `2026-11-21` 依 `P8-WO-20261123-G5FACT-CHECK` 按《项目编号与命名规范 v1.1 §10》正式迁入模块支撑文档**，依据《规范 §8.1 / §10.2》冻结留档——**严禁回改正文、严禁删除或移动路径**。当前实时跟踪与后续维护去向请跳转：[`P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md §2.4`](../audit/P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md#24-模块内遗留工程待办2026-11-21-依规范-10-自-p8-model_pending_20261110-并账迁入)。

> 来源：[P8-MODEL_第二步核验ticket_20261110.md](./P8-MODEL_第二步核验ticket_20261110.md) §三「记一笔（不阻塞，但须登记）」。
> 纪律：本清单仅登记问题、影响与后续处置方案；**不在第二步核验 ticket 内修改 `src/modeling/registry.py`**。

---

## 一、`ModelRegistry` 对已归档目录 `base_dir / "emos"` 的静默空集风险

| 项 | 内容 |
| :--- | :--- |
| **编号** | `P8-MODEL-PENDING-01` |
| **涉及文件** | [src/modeling/registry.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py)（[L88](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L88)、[L175](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L175)、[L536](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L536)） |
| **状态** | `OPEN / NON-BLOCKING`（不阻塞第二步核验与第三步重训，须在后续工程单清理） |
| **前置背景** | 第一步已完成旧 200 个 JSON 资产归档：`data/models/emos/` 已整体移至 `data/models/archive_legacy_climvar_20261110/`（保留 `DEPRECATED.md`）。生产运行轨为 `data/models/*.pkl` + [retrain_p4_active10_matrix.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/retrain_p4_active10_matrix.py) / [train_p7_w1_pooled_phase.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/train_p7_w1_pooled_phase.py) 写入的 `data/models/manifest.json`。 |

### 1. 逐点位置与静默行为

1. **[L88](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L88)（`format_model_relpath_json`）**：
   - 固定拼接 `Path("emos") / st / f"{var}_{seas}_{lead}h.json"`。
   - 被 `save_model_json()`（[L102](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L102)）和 `load_model_json()`（[L142](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L142)）消费。
   - `TrainingPipeline.run()` 中的 `save_scorecard_json()`（[pipeline.py L104](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/pipeline.py#L104)）若在生产目录执行，会重新创建 `data/models/emos/` 并发出 JSON-only manifest；而只读调用 `load_model_json()` 在 `emos/` 已归档时会因缺失文件抛出 `FileNotFoundError`。

2. **[L175](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L175)（`generate_manifest` 默认扫盘分支）**：
   - 当 `saved_relpaths is None` 时执行 `sorted((self.base_dir / "emos").glob("**/*.json"))`。
   - 归档后 `data/models/emos` 不存在，`glob` **静默返回空列表 `[]` 不报警**；若外部脚本无参调用 `ModelRegistry("data/models").generate_manifest()`，会把生产 `data/models/manifest.json` 覆盖成 `total_models: 0, models: {}`（严重破坏性副作用）。

3. **[L536](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L536)（`list_inventory` JSON 扫描分支）**：
   - 第 2 步先检查 `if emos_dir.exists():` 再扫 `**/*.json`。
   - 对 `data/models/` 而言第 1 步（[L516](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/registry.py#L516)）仍会返回 `.pkl` 清单，但 JSON 分支**静默跳过且无告警**；若某仓库目录仅有 JSON 约定或盘点脚本过滤 `format == "json"`，则返回空集而不提示 `emos/` 已归档/下线。

### 2. 影响范围评估

- **当前是否阻塞第二步/第三步**：**不阻塞**。
  - 推理入口 `ModelRegistry.load_model()` 已改为 `.pkl` 优先、JSON 兜底；[run_predictions.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/run_predictions.py) 正常读取 `data/models/*.pkl`。
  - 第三步重训脚本（[retrain_p4_active10_matrix.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/retrain_p4_active10_matrix.py) 与 [train_p7_w1_pooled_phase.py](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/train_p7_w1_pooled_phase.py)）直接构建 1,200 格 `.pkl` 与 `manifest.json`，不调用 `generate_manifest()`。
- **潜在风险**：
  1. 若后续有人在生产 `data/models` 上误调 `registry.generate_manifest()`（未传 `saved_relpaths`），会静默覆写 `manifest.json` 为空。
  2. 若下游盘点工具依赖 `list_inventory()` 的 `format == "json"` 行，会无预警得到空集。

### 3. 后续处置方案（待单独工单实施）

1. **防御 `generate_manifest()` 静默清零**：
   - 当 `saved_relpaths is None` 且 `(self.base_dir / "emos")` 不存在或匹配为空时，禁止覆写现有 `manifest.json`（改为抛出明确错误或支持扫描 `*.pkl` 构建多格式 manifest，除非显式传入空列表允许初始化）。
2. **`list_inventory()` 显式告警与格式兼容**：
   - 当 `emos_dir` 不存在时记录 `logger.info` / `WARNING` 提示「JSON archive absent (`emos/` archived or unused)」，并可选同时从 `manifest.json` 补充登记摘要字段。
3. **统一 `TrainingPipeline.run()` 与生产双轨**：
   - 评估是否淘汰 `save_scorecard_json()` 对 `data/models/emos/` 的写入或将其迁移为与 1,200-node `.pkl` manifest 对齐，避免误写回被归档的 `emos/` 目录。
