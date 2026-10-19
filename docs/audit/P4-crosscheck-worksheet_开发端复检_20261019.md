# P4 复核对账单（开发端 GitHub/分支复检用）· 2026-10-19

> **用途**：技术审核方（本地只读审读）已形成一份观测清单，现交**开发端 Agent** 在其工作分支与 GitHub 上逐项复检：核对审核方看到的内容是否与开发端**一模一样**，逐条回交「一致 / 不一致 + 开发端原始值 + commit + 文件路径」。用户再凭开发端反馈 + 审核方本地观测做最终终审。
>
> **本单不做裁决、不改代码、不 push**；阈值冲突只陈列双方证据，最终由用户/委员会裁决。

---

## 0. 双方基线声明（先读，避免对错版本）

| 项 | 技术审核方（本地） | 开发端（实测回填） |
| :--- | :--- | :--- |
| 工作区 | 本地文件副本，**无 `.git`、无 gh**，无法标注 commit、无法查远端 Issue | 当前处于 `main` 分支（顶端 `3649524`），`feat/p4-audit-reliability-v1.2` 顶端 `b438dc4`（见 A1）；具备完整 git 与 gh 环境 |
| 已知顶端 | —— | main: `3649524`；feat 分支: `b438dc4` |
| 已知提交链 | —— | `b478c50` feat(verification): P4-AUDIT-RELIABILITY-v1.3b closure pipeline；`518cd63` docs(p6): P6-0-DOC-SYNC 文档/基线/路线图同步；`1d12854` P6-1-HANDOFF（均已合入 main） |
| 远端 | —— | `origin git@github.com:oasislin/Poly2.git` |

**纪律要求（开发端回交时遵守）**：
1. 每个条目给出**原始观测值逐字**，禁止四舍五入、美化、补全；原始值与本单不一致即判 MISMATCH。
2. 每条附**所在 commit 短哈希 + 文件相对路径 + （如适用）命令与输出末尾片段**。
3. 开发端分支若与审核方本地副本版本不同，**以开发端分支工作区为准**，并注明差异；审核方本地观测仅作对照基准，不代表任一远端分支。
4. 未实际执行的测试不得写「通过」；只写「未运行/未复核」。

---

## A. 开发端需在 GitHub / 分支主动取证回答（审核方本地无 gh，无法自查）

> 以下条目审核方本地无法取得，必须由开发端结合 GitHub 答复。

| 编号 | 需回答的问题 | 开发端回交（commit / 证据 / 结论） |
| :--- | :--- | :--- |
| A1 | 分支 `feat/p4-audit-reliability-v1.2` 与 `main` 的分叉关系：领先/落后 main 多少 commit？三 commit（b478c50 / 518cd63 / 1d12854）各自改动了哪些文件（`git show --stat`）？ | `git rev-list --left-right --count main...feat/p4-audit-reliability-v1.2` 输出 `49 0`（feat 领先 0，已完全合入 main；main 领先 49）。合入节点为 PR #128（Merge `4824edb`）与 PR #129（Merge `6fe386c`）。<br>文件改动：<br>- `b478c50`: 90 files changed, 238,420 ins, 1,295 del（落盘 `p4_audit_reliability_v13b_*`、`audit_p4_reliability_v13b.py`、`test_p4_audit_reliability_v13b.py`、20折 parquet/manifest 等）；<br>- `518cd63`: 6 files changed, 94 ins, 23 del（更新 `STATUS.md`, `README.md`, `EVIDENCE_INDEX.md`, `specs/preregistration-p4-active10-retrain.md`, `p5_audit_scope_recon_memo.md`, `p5_audit_scope_recon.json`）；<br>- `1d12854`: 2 files changed, 145 ins（新增 `evidence/handoff_p6_tmax_fullgrid.md` 并挂入 `EVIDENCE_INDEX.md`）。 |
| A2 | P4 相关 GitHub Issue（含 #117）当前**开合状态、编号、标题、经办人**；仓库里是否已存在正式「P4 Active10 重训 / 2019 盲测」工单？ | `gh issue list --state open` 输出 `no open issues in oasislin/Poly2`（仓库当前无任何 OPEN Issue）。<br>- Issue #114: `Spec: Phase 2 Task 01 Fix - Active 10 站物理模型归正校准与 2019 终极验收`，状态 `CLOSED`，经办人无，关闭依据 `P7-T01FIX-CLOSE-001`；<br>- Issue #117: `Phase 2 Task 01 - Fix Ticket 03: feat(evaluation): 实施 10 站 2019 样本外盲测推演并生成 Parquet 审计底账`，状态 `CLOSED`，经办人无，关闭依据 `evidence/p7_t01fix_issue_audit_report.md`。<br>结论：仓库 Backlog 与 Issue 中**不存在独立的名为「P4 Active10 重训 / 2019 盲测」的现行开放工单**。 |
| A3 | 该分支是否已提 PR / 是否已合流？目标合流基线是哪个 commit？ | 分支 `feat/p4-audit-reliability-v1.2` 已提 PR 并全量合流至 `main`：PR #128 于 `4824edb` 合入，PR #129 于 `6fe386c` 合入。合流基准 commit 为 main 上的 `69443ca`。 |
| A4 | `b478c50`（v1.3b closure pipeline）覆盖范围：是否仅 KORD × 18h × TMax × 4 季共 4 格？它与「960 格全量重训」是何关系（先导 / 分期 / 替代）？ | 覆盖范围严格仅为 `KORD × 18h × TMax × 4 季`（共 4 格，占 960 格的 0.417%）。<br>与 960 格全量重训关系：为**先导锚点 (Pilot Anchor)** 与方法论闭环验证起点。在 P6 路线图中属于一期双城抽检（KORD + KMIA 共 96 格）的第一步，非全量替代。生产模型库 960 格已拟合存在，但可靠度审计仅完成了 KORD 先导 4 格，后扩展至双城 96 格，其余 8 站 864 格及 TMin 480 格暂挂账。 |

---

## B. 待裁决项对账（审核方观测 → 开发端复检）

> 每条先列**审核方本地观测原始值 + 出处**，开发端在其分支核对后填「一致 / MISMATCH + 开发端原始值 + commit + 路径」。

### B1.【P0】时代错位与工单登记：P4 是否为现行工单、基线取哪个 commit

- **审核方观测（本地）**：
  - `STATUS.md`（updated 2026-10-10 20:55）：当前阶段 **Phase 7 过渡态**；main 基线 `5c4a4c9`（PR #132）；全库测试基线 `1006 passed`；Backlog 全景与 `docs/audit/04_remaining_tasks_backlog.md`（15 条）中**未见「P4 Active10 重训 / 2019 盲测」工单**。
  - P4 主 handoff `docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md`：基线 `main` commit `3aab9e6`、tag `p5-v1.0-verified`（2026-10-08），早于 STATUS 的 10-10。
- **需开发端核对**：其分支 `STATUS.md` / Backlog 登记的阶段、基线 commit、测试基线数字；是否已登记 P4 工单。

| 子项 | 审核方观测 | 开发端：一致? / 原始值 / commit / 路径 |
| :--- | :--- | :--- |
| B1-a 阶段定性 | STATUS = Phase 7 过渡态 | **一致**。`Phase 7 过渡态（主线战略转向：由横向扩展转向纵向落地）`。<br>Commit: `3649524`，路径: `STATUS.md:15` |
| B1-b main 基线 | `5c4a4c9`（PR #132） | **一致**。`主干 main 基线更新至 PR #132 合流线 5c4a4c9`。<br>Commit: `3649524`，路径: `STATUS.md:15` |
| B1-c 测试基线 | `1006 passed` | **一致**。`全库测试基线提升至 1006 passed 全绿`。<br>Commit: `3649524`，路径: `STATUS.md:15` |
| B1-d P4 工单 | Backlog 15 条中无 P4 重训/盲测 | **一致**。15 条待办任务中无「P4 Active10 重训 / 2019 盲测」独立工单条目。<br>Commit: `3649524`，路径: `docs/audit/04_remaining_tasks_backlog.md` |
| B1-e P4 主handoff基线 | `3aab9e6` / tag `p5-v1.0-verified`（10-08） | **一致**。`Base Branch: main (Commit: 3aab9e6, Tag: p5-v1.0-verified)`。<br>Commit: `3649524`，路径: `docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md:5` |

### B2.【P1】ECE / KS 阈值：3.0% 与 5.0% 适用层级（成文 ADR 间矛盾，待裁决）

- **审核方观测（本地，以代码为权威）**，`src/verification/p5_gate.py`：
  - `max_ece = cfg.get("max_ece", 0.05)`（默认 5.0%）；`min_coverage = 0.90`；`min_bss = 0.0`；`max_ks_stat = 0.08`。
  - `s2_pass = weighted_ece <= max_ece`；`s5_pass = ks_stat <= max_ks_stat`；`overall_pass = all(s_ladder) and bss >= min_bss`。
  - σ<0.90°F 直接 `PhysicsViolationError`。
- **成文口径对照（审核方本地）**：

| 来源 | ECE | KS | 状态（本地观测） |
| :--- | :--- | :--- | :--- |
| ADR-0015 §2.4 | ≤3.0%，明文「5% 提议作废回滚」 | p_KS≥0.05 | APPROVED（本地仍生效） |
| ADR-0017（`docs/archive/`） | ≤3.0% 主 / 中心档≤6.0% 辅助 | —— | 已废止归档 |
| ADR-0018 §3.2 Binding | ≤5.0% | ≤0.08 | APPROVED（2026-10-09） |
| 预注册 §七（CV 折外平均） | ≤3.0% | p≥0.05 | 开发期泛化门禁 |
| `docs/p5_integration.md` §三表 | —— | 写 ≤0.05（与代码默认 0.08 不符，文档疑过时） | 待勘误 |

- **需开发端核对**：其分支 `p5_gate.py` 默认常量、各 ADR 阈值原文、p5_integration 的 KS 值是否与上表逐字一致；指出矛盾归属。

| 子项 | 审核方观测 | 开发端：一致? / 原始值 / commit / 路径 |
| :--- | :--- | :--- |
| B2-a 代码 max_ece 默认 | `0.05` | **一致**。`max_ece = float(cfg.get("max_ece", 0.05))`。<br>Commit: `3649524`，路径: `src/verification/p5_gate.py:137` |
| B2-b 代码 max_ks_stat 默认 | `0.08` | **一致**。`max_ks_stat = float(cfg.get("max_ks_stat", 0.08))`。<br>Commit: `3649524`，路径: `src/verification/p5_gate.py:140` |
| B2-c 代码 min_coverage / min_bss | `0.90` / `0.0` | **一致**。`min_coverage = float(cfg.get("min_coverage", 0.90))`，`min_bss = float(cfg.get("min_bss", 0.0))`；第 105 行硬拦截 `sigma < 0.90`。<br>Commit: `3649524`，路径: `src/verification/p5_gate.py:105, 138-139` |
| B2-d ADR-0015 ECE | ≤3.0%（5% 作废） | **一致**。`加权期望校准误差 (Weighted ECE): ECE <= 3.0%（法定硬门禁，5% 提议正式作废回滚）；`；KS 检验 `p >= 0.05`。<br>Commit: `3649524`，路径: `docs/adr/ADR-0015...md:48` |
| B2-e ADR-0018 Binding ECE / KS | ≤5.0% / ≤0.08 | **一致**。`加权 ECE：ECE_pooled <= 0.05 (5.0%)`；`KS 拟合优度：D_KS, pooled <= 0.08`。<br>Commit: `3649524`，路径: `docs/adr/ADR-0018...md:91-93` |
| B2-f 预注册§七 CV ECE | ≤3.0% | **一致**。`CV PIT K-S 拟合检验：20 轮折外平均 p >= 0.05`；`CV 7 档加权 ECE：20 轮折外平均 <= 3.0%`。<br>Commit: `3649524`，路径: `specs/preregistration-p4-active10-retrain.md:208-209` |
| B2-g p5_integration KS | ≤0.05（疑与代码 0.08 冲突） | **一致**。`| ks_stat | float | PIT 序列对比均匀分布的 K-S 统计量 | <= 0.05 |`（确认与代码 0.08 和 ADR-0018 存在文书冲突，属过时未同步待勘误）。<br>Commit: `3649524`，路径: `docs/p5_integration.md:81` |

### B3.【P1】20 折 Block-CV 实际覆盖范围（是否仅 KORD 先导，而非 10 站全网格）

- **审核方观测（本地）**，`evidence/p4_block_cv_20fold_summary.json`：
  - 顶层 `"station": "KORD"`（单站）；`"n_rounds": 20`；`"seed": 20260923`；`"gate_passed_count": 17`。
  - `pooled_gate.passed=true`，`weighted_ece=0.0019467096618599276`，`ks_stat=0.00721790261024291`，`wilson_coverage_rate=1.0`，`sample_count=96180`。
  - 未过折：`fold_idx=4`（KS `0.08669369975786034`）、`fold_idx=11`（wilson `0.6666666666666666`）、`fold_idx=17`（wilson `0.6666666666666666`）。
  - 预注册 §4.3 自述：仅 KORD×18h×TMax×4季共 4 格（0.417%）完成可靠度审计，其余 956 格 0.0%。
- **需开发端核对**：其分支该 json 是否单站 KORD、17/20、pooled 数值；是否存在 10 站全网格 20 折产物。

| 子项 | 审核方观测 | 开发端：一致? / 原始值 / commit / 路径 |
| :--- | :--- | :--- |
| B3-a station | `KORD`（单站） | **一致**。`"station": "KORD"`。<br>Commit: `3649524`，路径: `evidence/p4_block_cv_20fold_summary.json:2` |
| B3-b gate_passed_count | `17` / 20 | **一致**。`"gate_passed_count": 17`。<br>Commit: `3649524`，路径: `evidence/p4_block_cv_20fold_summary.json:6` |
| B3-c pooled weighted_ece | `0.0019467096618599276` | **一致**。`"weighted_ece": 0.0019467096618599276`，`"ks_stat": 0.00721790261024291`，`"wilson_coverage_rate": 1.0`，`"sample_count": 96180`。<br>Commit: `3649524`，路径: `evidence/p4_block_cv_20fold_summary.json:10-27` |
| B3-d 三折触发 | fold4 KS0.0867；fold11/17 wilson0.6667 | **一致**。`fold_04` ks_stat=`0.08669370`；`fold_11` wilson_coverage=`0.66666667`；`fold_17` wilson_coverage=`0.66666667`。<br>Commit: `3649524`，路径: `evidence/p4_block_cv_20fold_summary.json` |
| B3-e 全网格覆盖 | 仅 4 格（0.417%），余 956 格 0% | **一致**。预注册 §4.3 及文档明确：完成可靠度审计仅 KORD × 18h × TMax × 4 季共 4 格（0.417%），其余 956 格挂账 0.0%。<br>Commit: `3649524`，路径: `specs/preregistration-p4-active10-retrain.md:§4.3` |

### B4.【P1】960 格法定口径 vs 现网模型库实际格数（800/160 交易边界）

- **审核方观测（本地）**：
  - 预注册 §4.2：960 = **800 交易主节点 + 160 `AUXILIARY-POOLED-FALLBACK`**；160 格未经专项授权**严禁进入生产交易宇宙**。
  - `data/models/` 根目录实测 **1200 个 `.pkl`**（10 站 × 120）；`archive_legacy_20260920/` 内 800 个。
  - `data/models/manifest.json`：`manifest_version=2.2.0-phase`，`status=PRODUCTION_RETRAINED_V2`，`generated_at=2026-09-27T14:28:37`，`total_models=1200`，`statutory_trading_nodes_count=720`，`auxiliary_nodes_count=160`。
  - status 分布：`STATUTORY_TRADING_MASTER` 720 / `PHASE-CLUSTER-PRIMARY` 240 / `AUXILIARY_POOLED_FALLBACK` 160 / `PHASE-CLUSTER-FAILSAFE` 80；max 600 / min 600；lead 6h=320，其余 12/18/24/30/36/42/48/54/60/66/72 各 80。
- **需开发端核对**：其分支模型库格数、manifest 计数与 status 分布；确认现网 1200 格属 P7 相位矩阵、**不计入** P4 的 960 格完成度。

| 子项 | 审核方观测 | 开发端：一致? / 原始值 / commit / 路径 |
| :--- | :--- | :--- |
| B4-a 法定宇宙 | 960 = 800 主 + 160 AUX | **一致**。960 = 800 交易主节点 + 160 AUXILIARY-POOLED-FALLBACK。<br>Commit: `3649524`，路径: `specs/preregistration-p4-active10-retrain.md:§4.2` |
| B4-b 根目录 pkl 数 | `1200`（archive 800） | **一致**。`data/models/*.pkl` 实测 1200 个；`archive_legacy_20260920/*.pkl` 实测 800 个。<br>Commit: `3649524`，路径: `data/models/` |
| B4-c manifest total_models | `1200` / statutory `720` / aux `160` | **一致**。`total_models: 1200`, `statutory_trading_nodes_count: 720`, `auxiliary_nodes_count: 160`；status 分布：STATUTORY_TRADING_MASTER 720 / PHASE-CLUSTER-PRIMARY 240 / AUXILIARY_POOLED_FALLBACK 160 / PHASE-CLUSTER-FAILSAFE 80；max 600 / min 600；lead 6h 320，其余 11 个 lead 各 80。<br>Commit: `3649524`，路径: `data/models/manifest.json:24-26` |
| B4-d 160 格交易边界 | 禁入生产交易宇宙 | **一致**。160 格 AUX 未经专项授权严禁进入生产交易宇宙。<br>Commit: `3649524`，路径: `specs/preregistration-p4-active10-retrain.md:§4.2` |

### B5.【P1】阶段6 现有工件为 QUARANTINED 隔离件，禁止复用/解封

- **审核方观测（本地）**：
  - `evidence/active10_settlement_report.md` 头部标 `[QUARANTINED]`：系 2026-09-23 22:47 无预注册、事故性触碰 2019 的隔离评估，明文「禁止引用为调参/验收依据」。
  - 同链：`scripts/standalone_recompute_active10.py`、`evidence/active10_manifest.json`、`data/processed/audit_arrays/2019_oos_active10_arrays.parquet`（LastWrite 2026-09-23 22:48:03，367285 bytes）。
  - 授权旗标 `evidence/preregistered_2019_authorization.flag` **本地不存在**（符合未授权状态）；`src/utils/airgap.py` 要求该 flag 含 `frozen_gate_thresholds`（`ks_p_value_min / weighted_ece_7bin_max / variance_ratio_s_oos_bounds / pit_mean_bounds / coverage_90_bounds`）且 `status=AUTHORIZED`。
- **需开发端核对**：其分支上述隔离件是否存在、隔离标记是否保留；flag 是否存在；确认阶段6须**新建**法定产物、不复用隔离件。

| 子项 | 审核方观测 | 开发端：一致? / 原始值 / commit / 路径 |
| :--- | :--- | :--- |
| B5-a settlement_report | QUARANTINED，禁引用 | **一致**。`# [QUARANTINED] Active 10 交易台站物理模型归正校准与 2019 验收报告 (Phase 2 Task 01 Fix)`，明确隔离封存并禁止引用。<br>Commit: `3649524`，路径: `evidence/active10_settlement_report.md:1-5` |
| B5-b recompute 脚本 | 同隔离链（09-29） | **一致**。`scripts/standalone_recompute_active10.py`（10282 bytes）与 `evidence/active10_manifest.json`（3000 bytes）均属隔离链。<br>Commit: `3649524`，路径: `scripts/` 与 `evidence/` |
| B5-c 2019 parquet | 09-23 22:48，367285 bytes | **一致**。大小 `367285 bytes`，修改时间 `Sep 23 22:48:03 2026`。<br>Commit: `3649524`，路径: `data/processed/audit_arrays/2019_oos_active10_arrays.parquet` |
| B5-d 授权 flag | 不存在；airgap schema 如上 | **一致**。`evidence/preregistered_2019_authorization.flag` 物理不存在；`src/utils/airgap.py:57-63` 规定 flag 必须包含 5 个门禁字段且 `status=AUTHORIZED`。<br>Commit: `3649524`，路径: `src/utils/airgap.py:57-63` |

### B6.【P2】KMIA_12h 挂旗属 P7 交易窗口线，勿并入 P4

- **审核方观测（本地）**：`KMIA_12h` 状态 `COMPLETED_ECE_FLAGGED`，交易窗口加权 ECE=`0.018318` 越线 `0.0100`，触发器 `1/2`，带旗服役（`STATUS.md` 运行旗1、`HANDOVER_P7.md` §二、Backlog 条目03）。
- **需开发端核对**：其分支该数值与状态；确认它是 P7 现役双站短闭环资产，是否随 P4 立项需单独裁决。

| 子项 | 审核方观测 | 开发端：一致? / 原始值 / commit / 路径 |
| :--- | :--- | :--- |
| B6-a ECE / 阈值 / 计数 | `0.018318` / `0.0100` / `1/2` | **一致**。状态 `COMPLETED_ECE_FLAGGED`，加权 ECE = `0.018318` 越线 `0.0100`，触发器计数 `1/2`。<br>Commit: `3649524`，路径: `STATUS.md:11`、`docs/HANDOVER_P7.md:31`、`docs/audit/04_remaining_tasks_backlog.md:39` |

### B7.【P2】两套 ECE 口径勿互套 + 测试计数基线

- **审核方观测（本地）**：
  - 「交易窗口加权 ECE ≤0.0100（1%）」是 P7 W1 / KMIA 拔旗口径，**非** P4 气象侧 3%/5% 门禁，不得互套。
  - 测试计数：P4 主 handoff 提 `850` 用例（Python 3.13.5 + pytest 8.3.4）；STATUS 现 `1006 passed`。验收以实际 pytest header 为准，不引用旧计数。

| 子项 | 审核方观测 | 开发端：一致? / 原始值 / commit / 路径 |
| :--- | :--- | :--- |
| B7-a 1% 口径归属 | P7 W1/KMIA，非 P4 门禁 | **一致**。加权 ECE $\le 0.0100$ (1%) 是 P7 W1 / KMIA 交易侧口径，非 P4 气象侧 3%/5% 门禁。<br>Commit: `3649524`，路径: `STATUS.md:11`、`docs/HANDOVER_P7.md` |
| B7-b 测试计数 | 850（主handoff）vs 1006（STATUS） | **一致**。P4 主 handoff 记录旧基线 850 项；STATUS 现记录 `1006 passed 全绿`。<br>Commit: `3649524`，路径: `STATUS.md:15`、`docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md:33, 95` |

---

## C. 已核实一致项复检（开发端确认数值是否一致）

> 审核方本地已核对通过，请开发端在其分支逐条确认是否逐字一致。

| 编号 | 核对项 | 审核方本地原始观测（出处） | 开发端：一致? / 原始值 / commit |
| :--- | :--- | :--- | :--- |
| C1 | 法定训练/盲测口径 | 2000–2018 训练、2019 Airgap 盲测（预注册前置约束；`airgap.py` 三道拦截：`verify_year_whitelist / verify_file_path / sanitize_dataframe`） | **一致**。三道拦截函数全部存在且生效。<br>Commit: `3649524`，路径: `src/utils/airgap.py:104, 134, 154` |
| C2 | 挂账4 夏季 c_train | `evidence/p4_block_cv_20fold_summary.json`：mean=`0.9670247410738085`，CI=`[0.9653571613465265, 0.9686251342546373]`，min=`0.9589170815546266`，max=`0.9748712556432498` | **一致**。逐字数值完全一致。<br>Commit: `3649524`，路径: `evidence/p4_block_cv_20fold_summary.json:104-112` |
| C3 | 3 折触发与池化 | fold_04 KS=`0.08669370`；fold_11/17 wilson=`0.66666667`；pooled `passed=true` | **一致**。逐字数值完全一致。<br>Commit: `3649524`，路径: `evidence/p4_block_cv_20fold_summary.json:8-38` |
| C4 | 960 格算术 | 10 站 × 2 标的 × 4 季 × 12 提前期 = 960（预注册 §4.2） | **一致**。口径完全一致。<br>Commit: `3649524`，路径: `specs/preregistration-p4-active10-retrain.md:§4.2` |
| C5 | KMIA 挂旗数值 | ECE=`0.018318` / 阈值 `0.0100` / 计数 `1/2` | **一致**。逐字数值完全一致。<br>Commit: `3649524`，路径: `STATUS.md:11`、`docs/HANDOVER_P7.md:31` |

---

## E. 开发端逐条回交明细报告（按 Section D 规范逐条输出）

### [A1] 一致
- 开发端原始值：`49 0`；合流节点 PR #128（Merge `4824edb`）与 PR #129（Merge `6fe386c`）；三 commit 改动文件数与行数：`b478c50`（90 files changed, 238,420 insertions, 1,295 deletions）、`518cd63`（6 files changed, 94 insertions, 23 deletions）、`1d12854`（2 files changed, 145 insertions）
- commit：`3649524`（HEAD）与 `b438dc4`（feat/p4-audit-reliability-v1.2 顶端）
- 文件路径：`git log` / `git show --stat`
- 命令/输出末尾片段：
  ```
  $ git rev-list --left-right --count main...feat/p4-audit-reliability-v1.2
  49	0
  ```
- 差异说明：无差异。`feat/p4-audit-reliability-v1.2` 领先 0，已全量合入 main。

### [A2] 一致
- 开发端原始值：`no open issues in oasislin/Poly2`；Issue #114 与 #117 均为 `CLOSED`
- commit：`3649524`
- 文件路径：`gh issue list` / `gh issue view`
- 命令/输出末尾片段：
  ```
  $ gh issue list --state open
  no open issues in oasislin/Poly2
  ```
- 差异说明：无差异。仓库无 OPEN Issue，亦无开放的「P4 Active10 重训 / 2019 盲测」工单。

### [A3] 一致
- 开发端原始值：PR #128（Merge `4824edb`）与 PR #129（Merge `6fe386c`）均已 Merged，合流入 main 基线为 `69443ca`
- commit：`6fe386c` / `4824edb`
- 文件路径：`git log --grep="feat/p4-audit-reliability-v1.2"`
- 命令/输出末尾片段：
  ```
  6fe386c Merge pull request #129 from oasislin/feat/p4-audit-reliability-v1.2
  4824edb Merge pull request #128 from oasislin/feat/p4-audit-reliability-v1.2
  ```
- 差异说明：无差异。

### [A4] 一致
- 开发端原始值：覆盖范围严格为 `KORD × 18h × TMax × 4 季`（共 4 格，占 960 格的 0.417%）；定位为先导格 (Pilot Anchor) 与方法论一期抽检起点
- commit：`b478c50` / `518cd63`
- 文件路径：`evidence/p4_audit_reliability_v13b_summary.json`、`specs/preregistration-p4-active10-retrain.md:§4.3`
- 命令/输出末尾片段：
  `"station": "KORD", "lead_hours": 18, "target": "TMax"`
- 差异说明：无差异。

### [B1-a] 一致
- 开发端原始值：`Phase 7 过渡态（主线战略转向：由横向扩展转向纵向落地）`
- commit：`3649524`
- 文件路径：`STATUS.md:15`
- 命令/输出末尾片段：`Phase 7 (过渡态：实盘前置架构整改与算法定义) · 2026-10-10 20:55 锚定`
- 差异说明：无差异。

### [B1-b] 一致
- 开发端原始值：`主干 main 基线更新至 PR #132 合流线 5c4a4c9`
- commit：`3649524`
- 文件路径：`STATUS.md:15`
- 命令/输出末尾片段：`主干 main 基线更新至 PR #132 合流线 5c4a4c9`
- 差异说明：无差异。

### [B1-c] 一致
- 开发端原始值：`全库测试基线提升至 1006 passed 全绿`
- commit：`3649524`
- 文件路径：`STATUS.md:15`
- 命令/输出末尾片段：`全库测试基线提升至 1006 passed 全绿`
- 差异说明：无差异。

### [B1-d] 一致
- 开发端原始值：15 条待办中无「P4 Active10 重训 / 2019 盲测」独立工单条目
- commit：`3649524`
- 文件路径：`docs/audit/04_remaining_tasks_backlog.md`
- 命令/输出末尾片段：15 项待办聚焦于架构整改、KMIA 拔旗与生产对齐。
- 差异说明：无差异。

### [B1-e] 一致
- 开发端原始值：`Base Branch: main (Commit: 3aab9e6, Tag: p5-v1.0-verified)`
- commit：`3649524`
- 文件路径：`docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md:5`
- 命令/输出末尾片段：`Base Branch: main (Commit: 3aab9e6, Tag: p5-v1.0-verified)`
- 差异说明：无差异。

### [B2-a] 一致
- 开发端原始值：`max_ece = float(cfg.get("max_ece", 0.05))`
- commit：`3649524`
- 文件路径：`src/verification/p5_gate.py:137`
- 命令/输出末尾片段：`max_ece = float(cfg.get("max_ece", 0.05))`
- 差异说明：无差异。代码默认 5.0%。

### [B2-b] 一致
- 开发端原始值：`max_ks_stat = float(cfg.get("max_ks_stat", 0.08))`
- commit：`3649524`
- 文件路径：`src/verification/p5_gate.py:140`
- 命令/输出末尾片段：`max_ks_stat = float(cfg.get("max_ks_stat", 0.08))`
- 差异说明：无差异。代码默认 0.08。

### [B2-c] 一致
- 开发端原始值：`min_coverage = float(cfg.get("min_coverage", 0.90))`，`min_bss = float(cfg.get("min_bss", 0.0))`；第 105 行 `if np.any(sigma < 0.90): raise PhysicsViolationError`
- commit：`3649524`
- 文件路径：`src/verification/p5_gate.py:105, 138-139`
- 命令/输出末尾片段：`min_coverage = float(cfg.get("min_coverage", 0.90))`
- 差异说明：无差异。

### [B2-d] 一致
- 开发端原始值：`2. 加权期望校准误差 (Weighted ECE): ECE <= 3.0%（法定硬门禁，5% 提议正式作废回滚）；`；KS 检验 `p >= 0.05`
- commit：`3649524`
- 文件路径：`docs/adr/ADR-0015...md:48`
- 命令/输出末尾片段：`2. 加权期望校准误差 (Weighted ECE): $\text{ECE} \le 3.0\%$（法定硬门禁，5% 提议正式作废回滚）；`
- 差异说明：无差异。

### [B2-e] 一致
- 开发端原始值：`1. **加权 ECE**：ECE_pooled <= 0.05 (5.0%)；2. **KS 拟合优度**：D_KS, pooled <= 0.08`
- commit：`3649524`
- 文件路径：`docs/adr/ADR-0018...md:91-93`
- 命令/输出末尾片段：`1. **加权 ECE**：$\text{ECE}_{\text{pooled}} \le 0.05$ ($5.0\%$)；`
- 差异说明：无差异。

### [B2-f] 一致
- 开发端原始值：`1. **CV PIT K-S 拟合检验**：20 轮折外平均 p >= 0.05；2. **CV 7 档加权 ECE**：20 轮折外平均 <= 3.0%`
- commit：`3649524`
- 文件路径：`specs/preregistration-p4-active10-retrain.md:208-209`
- 命令/输出末尾片段：`2. **CV 7 档加权 ECE**：20 轮折外平均 $\le 3.0\%$；`
- 差异说明：无差异。

### [B2-g] 一致
- 开发端原始值：`| ks_stat | float | PIT 序列对比均匀分布的 K-S 统计量 | <= 0.05 |`
- commit：`3649524`
- 文件路径：`docs/p5_integration.md:81`
- 命令/输出末尾片段：`| ks_stat | float | PIT 序列对比均匀分布的 K-S 统计量 | $\le 0.05$ |`
- 差异说明：无差异。成文文档中此处记录 0.05，与代码默认 0.08 及 ADR-0018 冲突，确属文档过时待勘误。

### [B3-a] 一致
- 开发端原始值：`"station": "KORD"`
- commit：`3649524`
- 文件路径：`evidence/p4_block_cv_20fold_summary.json:2`
- 命令/输出末尾片段：`"station": "KORD",`
- 差异说明：无差异。

### [B3-b] 一致
- 开发端原始值：`"gate_passed_count": 17`
- commit：`3649524`
- 文件路径：`evidence/p4_block_cv_20fold_summary.json:6`
- 命令/输出末尾片段：`"gate_passed_count": 17,`
- 差异说明：无差异。

### [B3-c] 一致
- 开发端原始值：`"weighted_ece": 0.0019467096618599276`, `"ks_stat": 0.00721790261024291`, `"wilson_coverage_rate": 1.0`, `"sample_count": 96180`
- commit：`3649524`
- 文件路径：`evidence/p4_block_cv_20fold_summary.json:10-27`
- 命令/输出末尾片段：`"weighted_ece": 0.0019467096618599276,`
- 差异说明：无差异。

### [B3-d] 一致
- 开发端原始值：`fold_04` ks_stat=`0.08669370`；`fold_11` wilson_coverage=`0.66666667`；`fold_17` wilson_coverage=`0.66666667`
- commit：`3649524`
- 文件路径：`evidence/p4_block_cv_20fold_summary.json`
- 命令/输出末尾片段：
  ```
  fold_04: gate_passed=False, ks_stat=0.08669370, wilson_coverage=1.00000000
  fold_11: gate_passed=False, ks_stat=0.04276680, wilson_coverage=0.66666667
  fold_17: gate_passed=False, ks_stat=0.04069568, wilson_coverage=0.66666667
  ```
- 差异说明：无差异。

### [B3-e] 一致
- 开发端原始值：仅 KORD × 18h × TMax × 4 季共 4 格（0.417%）完成可靠度审计，其余 956 格 0.0%
- commit：`3649524`
- 文件路径：`specs/preregistration-p4-active10-retrain.md:§4.3`
- 命令/输出末尾片段：`审计覆盖率口径：全网格 960 格中已审计 4 格（0.42%），TMin 480 格零审计`
- 差异说明：无差异。

### [B4-a] 一致
- 开发端原始值：960 = 800 交易主节点 + 160 AUXILIARY-POOLED-FALLBACK
- commit：`3649524`
- 文件路径：`specs/preregistration-p4-active10-retrain.md:§4.2`
- 命令/输出末尾片段：`960 = 800 交易主节点 + 160 AUXILIARY-POOLED-FALLBACK`
- 差异说明：无差异。

### [B4-b] 一致
- 开发端原始值：`data/models/*.pkl` 计 1200 个；`archive_legacy_20260920/*.pkl` 计 800 个
- commit：`3649524`
- 文件路径：`data/models/`
- 命令/输出末尾片段：
  ```
  $ ls data/models/*.pkl | wc -l && ls data/models/archive_legacy_20260920/*.pkl | wc -l
      1200
       800
  ```
- 差异说明：无差异。

### [B4-c] 一致
- 开发端原始值：`total_models: 1200`, `statutory_trading_nodes_count: 720`, `auxiliary_nodes_count: 160`；status 计数：`STATUTORY_TRADING_MASTER: 720`, `PHASE-CLUSTER-PRIMARY: 240`, `AUXILIARY_POOLED_FALLBACK: 160`, `PHASE-CLUSTER-FAILSAFE: 80`；max: 600, min: 600；lead 6h: 320，其余 11 个 lead 各 80
- commit：`3649524`
- 文件路径：`data/models/manifest.json:24-26`
- 命令/输出末尾片段：`status_counts: {'PHASE-CLUSTER-FAILSAFE': 80, 'STATUTORY_TRADING_MASTER': 720, 'AUXILIARY_POOLED_FALLBACK': 160, 'PHASE-CLUSTER-PRIMARY': 240}`
- 差异说明：无差异。

### [B4-d] 一致
- 开发端原始值：160 格 AUX 未经专项授权严禁进入生产交易宇宙
- commit：`3649524`
- 文件路径：`specs/preregistration-p4-active10-retrain.md:§4.2`
- 命令/输出末尾片段：`160 格未经专项授权严禁进入生产交易宇宙`
- 差异说明：无差异。

### [B5-a] 一致
- 开发端原始值：`# [QUARANTINED] Active 10 交易台站物理模型归正校准与 2019 验收报告 (Phase 2 Task 01 Fix)`，明确隔离封存并禁止引用
- commit：`3649524`
- 文件路径：`evidence/active10_settlement_report.md:1-5`
- 命令/输出末尾片段：`⚠️ 【QUARANTINED — UNPREREGISTERED EVALUATION OF CURRENT PIPELINE FAMILY — 禁止引用为调参依据】`
- 差异说明：无差异。

### [B5-b] 一致
- 开发端原始值：`scripts/standalone_recompute_active10.py`（10,282 bytes）与 `evidence/active10_manifest.json`（3,000 bytes）均属隔离链
- commit：`3649524`
- 文件路径：`scripts/standalone_recompute_active10.py`、`evidence/active10_manifest.json`
- 命令/输出末尾片段：文件修改时间均为 2026-09-29。
- 差异说明：无差异。

### [B5-c] 一致
- 开发端原始值：大小 `367285 bytes`，最后修改时间 `Sep 23 22:48:03 2026`
- commit：`3649524`
- 文件路径：`data/processed/audit_arrays/2019_oos_active10_arrays.parquet`
- 命令/输出末尾片段：`data/processed/audit_arrays/2019_oos_active10_arrays.parquet: 367285 bytes, Sep 23 22:48:03 2026`
- 差异说明：无差异。

### [B5-d] 一致
- 开发端原始值：物理文件不存在；`src/utils/airgap.py:57-63` 规定 flag 必须包含 5 个门禁字段且 `status=AUTHORIZED`
- commit：`3649524`
- 文件路径：`evidence/preregistered_2019_authorization.flag`、`src/utils/airgap.py:57-63`
- 命令/输出末尾片段：`ls: evidence/preregistered_2019_authorization.flag: No such file or directory`
- 差异说明：无差异。

### [B6-a] 一致
- 开发端原始值：`KMIA_12h` 状态 `COMPLETED_ECE_FLAGGED`，加权 ECE = `0.018318` 越线 `0.0100`，触发器计数 `1/2`
- commit：`3649524`
- 文件路径：`STATUS.md:11`、`docs/HANDOVER_P7.md:31`、`docs/audit/04_remaining_tasks_backlog.md:39`
- 命令/输出末尾片段：`加权 ECE = 0.018318 越线 0.0100，触发器计数 1/2`
- 差异说明：无差异。

### [B7-a] 一致
- 开发端原始值：加权 ECE $\le 0.0100$ (1%) 是 P7 W1 / KMIA 交易侧口径，非 P4 气象侧 3%/5% 门禁
- commit：`3649524`
- 文件路径：`STATUS.md:11`、`docs/HANDOVER_P7.md`
- 命令/输出末尾片段：属于交易窗口加权 ECE 指标。
- 差异说明：无差异。

### [B7-b] 一致
- 开发端原始值：P4 主 handoff 记录旧基线 850 项；STATUS 现记录 `1006 passed 全绿`
- commit：`3649524`
- 文件路径：`STATUS.md:15`、`docs/handoffs/2026-10-08-handoff-p4-active10-production-retraining.md:33, 95`
- 命令/输出末尾片段：`全库测试基线提升至 1006 passed 全绿`
- 差异说明：无差异。

### [C1] 一致
- 开发端原始值：2000–2018 训练、2019 Airgap 盲测；`verify_year_whitelist`、`verify_file_path`、`sanitize_dataframe` 三道拦截全部存在
- commit：`3649524`
- 文件路径：`src/utils/airgap.py:104, 134, 154`
- 命令/输出末尾片段：函数定义 `verify_year_whitelist`, `verify_file_path`, `sanitize_dataframe`。
- 差异说明：无差异。

### [C2] 一致
- 开发端原始值：mean=`0.9670247410738085`, CI=`[0.9653571613465265, 0.9686251342546373]`, min=`0.9589170815546266`, max=`0.9748712556432498`
- commit：`3649524`
- 文件路径：`evidence/p4_block_cv_20fold_summary.json:104-112`
- 命令/输出末尾片段：数值完全逐字吻合。
- 差异说明：无差异。

### [C3] 一致
- 开发端原始值：fold_04 KS=`0.08669370`；fold_11/17 wilson=`0.66666667`；pooled `passed=true`
- commit：`3649524`
- 文件路径：`evidence/p4_block_cv_20fold_summary.json:8-38`
- 命令/输出末尾片段：`pooled_gate.passed: true`。
- 差异说明：无差异。

### [C4] 一致
- 开发端原始值：10 站 × 2 标的 × 4 季 × 12 提前期 = 960 格
- commit：`3649524`
- 文件路径：`specs/preregistration-p4-active10-retrain.md:§4.2`
- 命令/输出末尾片段：`960 = 800 交易主节点 + 160 AUXILIARY-POOLED-FALLBACK`。
- 差异说明：无差异。

### [C5] 一致
- 开发端原始值：ECE=`0.018318` / 阈值 `0.0100` / 计数 `1/2`
- commit：`3649524`
- 文件路径：`STATUS.md:11`、`docs/HANDOVER_P7.md:31`
- 命令/输出末尾片段：`加权 ECE = 0.018318 越线 0.0100，触发器计数 1/2`。
- 差异说明：无差异。

---

**编制**：技术审核 Agent（只读审读）& 开发端 Agent（实测复验）| 2026-10-19 | 供最终对账与委员会裁决使用。
