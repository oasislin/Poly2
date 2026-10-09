# P7-SYNC-BRIDGE 事项 1：推送完整性核验与仓库体检报告

> **工单编号**：`P7-SYNC-BRIDGE`（事项 1）  
> **核验目标**：在建立受控出域通道前，对已推送提交 `ec3acf4` 与 `d944424` 进行本地↔远端↔账本三方一致性验证与仓库体积健康度检查。  
> **核验时间**：2026-10-10 00:17:00 (UTC+8)  
> **受检分支**：`feat/p4-audit-reliability-v1.2` (远端：`origin/feat/p4-audit-reliability-v1.2`)  

---

## 一、 本地 ↔ 远端 ↔ 账本三方一致性核验 (Three-Way Consistency Audit)

### 1. 抽样与全查设计
- **版本总文件数**：在 Commit `ec3acf4` 下包含 1,668 个文件；
- **必查关键工件 (6/6)**：
  1. `STATUS.md`
  2. `EVIDENCE_INDEX.md`
  3. `docs/SEALING_GATE.md`
  4. `evidence/fullgrid_tmax/PROGRESS.json`
  5. `evidence/p6_heavytail_diag_results.json`
  6. `evidence/p6_sealing_gate_sync_report.md`
- **随机抽检 (10%)**：166 个其余文件（固定随机种子 `seed=20261010`，全量覆盖代码、测试、配置与模型工件）；
- **总核验样本量**：172 个文件。

### 2. 必查关键工件比对明细表

| 序号 | 文件路径 | 本地文件 SHA256 | 远端 Git Blob SHA256 | 账本挂账/预期状态 | 比对结论 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| 1 | `STATUS.md` | `f99a1902871f43ad05ab75f633e9dd9ecada140f1769a4f8e642f7019080043f` | `f99a1902871f43ad05ab75f633e9dd9ecada140f1769a4f8e642f7019080043f` | 本地唯一状态入口最新节点 | **一致 (PASS)** |
| 2 | `EVIDENCE_INDEX.md` | `96857dcd13bcd6a3289cb46dcb39bb8c0ae63437adbd98766090225a832b6428` | `96857dcd13bcd6a3289cb46dcb39bb8c0ae63437adbd98766090225a832b6428` | 法定凭据总账本最新节点 | **一致 (PASS)** |
| 3 | `docs/SEALING_GATE.md` | `ccc0dff199d1719dcccca360fb87f8e3684b431cef52c9354b027a18d7c98a07` | `ccc0dff199d1719dcccca360fb87f8e3684b431cef52c9354b027a18d7c98a07` | 封盘门禁八项检查表 | **一致 (PASS)** |
| 4 | `evidence/fullgrid_tmax/PROGRESS.json` | `a383e56de9c63041f03566bdbf4da998c76ffe92281765390976cd52be24e05e` | `a383e56de9c63041f03566bdbf4da998c76ffe92281765390976cd52be24e05e` | 全网格断点与 Backlog 账本 | **一致 (PASS)** |
| 5 | `evidence/p6_heavytail_diag_results.json` | `9037db2cc4167ff6940d115c2033598c634cff5caa4e40fd3d87950cd6a7c73a` | `9037db2cc4167ff6940d115c2033598c634cff5caa4e40fd3d87950cd6a7c73a` | P6-HTD-2 挂账数值工件 | **一致 (PASS)** |
| 6 | `evidence/p6_sealing_gate_sync_report.md` | `98657adc3df1bf0c0574d08ed3e737eb18718b3989955b1885652aad20f68c74` | `98657adc3df1bf0c0574d08ed3e737eb18718b3989955b1885652aad20f68c74` | 同步推送汇报文件 | **一致 (PASS)** |

### 3. 抽样比对结论
- **核验脚本执行结果**：`Total checked: 172, Mismatches: 0`；
- **三方一致性判定**：本地物理文件内容哈希与远端推送对应 Blob 内容哈希 100% 逐位一致，三方通道完全可信。

---

## 二、 仓库体积健康度体检 (Repository Size Health Check)

### 1. 实际执行命令与原始观测值

- **执行命令 1**：`git count-objects -vH`
  - 原始输出：
    ```text
    count: 0
    size: 0 bytes
    in-pack: 3701
    packs: 1
    size-pack: 52.50 MiB
    prune-packable: 0
    garbage: 0
    size-garbage: 0 bytes
    ```
  - **仓库 Git 历史总体积**：`52.50 MiB`。

- **执行命令 2**：`git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | grep '^blob' | sort -k3 -n -r | head -n 10`
  - 原始输出前 10 大 Blob：
    1. `7,714,305 bytes (~7.36 MiB)` - `evidence/p4_audit_reliability_v13_lineage.json`
    2. `2,785,174 bytes (~2.66 MiB)` - `evidence/cv_split_blocks_20rounds.json`
    3. `1,950,177 bytes (~1.86 MiB)` - `data/processed/audit_arrays/2000_2018_training_arrays.parquet`
    4. `1,922,073 bytes (~1.83 MiB)` - `configs/climate_floor_v2.json`
    5. `1,824,947 bytes (~1.74 MiB)` - `evidence/fullgrid_tmax/cells/KORD_42h/cv_pooled_predictions.parquet`
    6. `1,820,907 bytes (~1.74 MiB)` - `evidence/fullgrid_tmax/cells/KORD_24h/cv_pooled_predictions.parquet`
    7. `1,820,509 bytes (~1.74 MiB)` - `evidence/fullgrid_tmax/cells/KORD_30h/cv_pooled_predictions.parquet`
    8. `1,819,930 bytes (~1.74 MiB)` - `evidence/fullgrid_tmax/cells/KORD_36h/cv_pooled_predictions.parquet`
    9. `1,816,592 bytes (~1.73 MiB)` - `evidence/fullgrid_tmax/cells/KORD_12h/cv_pooled_predictions.parquet`
    10. `1,815,068 bytes (~1.73 MiB)` - `evidence/fullgrid_tmax/cells/KORD_66h/cv_pooled_predictions.parquet`

- **最大单个 Blob 体积**：`7.36 MiB` (`evidence/p4_audit_reliability_v13_lineage.json`)。
- **全网格 Parquet 单文件体积**：约 `1.7~1.8 MiB/格`，已全部收录于 `ec3acf4` 历史提交中。

---

## 三、 两步分离机械判定与分支决策 (Two-Step Mechanical Decision)

- **原始观测值**：
  - 仓库总体积 = `52.50 MiB`
  - 最大单个 Blob = `7.36 MiB` (`evidence/p4_audit_reliability_v13_lineage.json`)
  - 逐文件比对 Mismatches = `0`
- **判定阈值**：
  - 仓库总体积 $< 500 \text{ MiB}$
  - 单个 Blob $< 50 \text{ MiB}$
  - 比对 Mismatches $= 0$
- **判定结论**：
  - `52.50 MiB < 500 MiB` 成立；
  - `7.36 MiB < 50 MiB` 成立；
  - `Mismatches = 0` 成立；
  - **判定结果**：**通道可信，走分支 A（接受现状，未来增量走 Git LFS）**。
