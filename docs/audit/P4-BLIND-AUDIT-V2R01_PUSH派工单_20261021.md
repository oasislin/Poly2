# P4-BLIND-AUDIT-V2R01 · 文档入库与 push 派工单（致开发端 Agent）

> 来源：技术审核方 ｜ 日期：2026-10-21 ｜ 授权：用户明确指令「发给开发 agent，让他 push to git」
> 性质：**纯 docs-only 入库**。本轮无任何代码、脚本、模型参数、2019 数据、manifest 改动。

## 1. 背景
V2R01 第二类尺子升级已终审四项通过、闭环；本轮完成文档对齐（README / 项目方案 v2.8 / Phase 2 执行文件 v2.1 补登 V1.0→V2.0 盲测尺演进）与闭环文档落盘。现需把下列文档提交并推送至 `origin/main`。

## 2. 执行步骤（在开发端持有 git 的仓库内操作）

1. **先核对，不盲目 add**：
   ```bash
   git status
   ```
   以 `git status` 实际列出的未跟踪/已修改文件为准；下列为应纳入的文件组，已入库的跳过。

2. **应纳入文件组**：

   **A. 文档对齐（本轮新改）**
   - `README.md`（验证与审计体系补 V1.0→V2.0 盲测尺演进）
   - `docs/项目方案和执行文档/项目方案 (v2.8)：Polymarket 温度市场量化投注系统.md`（§4 新增第 6 点盲测尺 V2.0）
   - `docs/项目方案和执行文档/Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md`（验收注记加 V2.0 指针）

   **B. V2R01 闭环文档**
   - `docs/audit/第二类_V2尺子升级_方案书_20261021.md`（已标闭环）
   - `docs/audit/P4-BLIND-AUDIT-V2R01_V2尺子升级_开发任务单_20261021.md`（§10 终审回填）
   - `docs/audit/P4-BLIND-AUDIT-V2R01-FIX1_Q5ECE口径补单_20261021.md`
   - `docs/audit/P4-BLIND-AUDIT-V2R01_闭环同步说明_20261021.md`
   - `docs/audit/v2-blindtest-report/V2_2019双城盲测_尺子升级报告_20261021.html`
   - `docs/audit/工作线登记_V1盲测完善支线_20261020.md`（追加 L8）
   - `docs/audit/DECISION_LEDGER.md`（追加 §十二 DECISION-20261021-06）

   > `v2-blindtest-report/_shots/` 为自检截图过程产物，非交付物，可不入库。

3. **提交（建议消息，可按仓库惯例微调）**：
   ```bash
   git add README.md "docs/项目方案和执行文档/项目方案 (v2.8)：Polymarket 温度市场量化投注系统.md" "docs/项目方案和执行文档/Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md" docs/audit/
   git commit -m "docs(audit): V2R01 尺子升级闭环文档与 README/方案/执行文件 V1→V2 尺演进对齐"
   ```

4. **推送**：
   ```bash
   git push origin main
   ```
   禁止 `--force` / `--no-verify`；若远端有新提交，先正常 rebase/merge 再推，不覆盖他人提交。

## 3. 红线
- 不改 `src/`、`scripts/` 任何代码；不重训、不改 EMOS 参数、不写回 pkl/manifest；
- 不改 `data/processed/audit_arrays/2019_oos_p4_settlement_arrays.parquet` 等原始数据；
- 不改动已冻结的 V1 结算结论与历史章节（仅追加/标注）。

## 4. 回交证据（开发完成后原样贴回）
1. `git status` 末尾片段（确认 working tree clean）；
2. `git log -3 --oneline`；
3. `git push origin main` 原始输出（含远端更新区间）；
4. 如对文件组有增删，逐条说明理由。
