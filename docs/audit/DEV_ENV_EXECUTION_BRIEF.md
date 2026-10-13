# 开发环境执行清单（DEV_ENV_EXECUTION_BRIEF）

> **版本**：v1.1
> **日期**：2026-10-13
> **编制**：技术审核 Agent（基于本地文件系统实测 + 线上 GitHub 实时核对）
> **执行位置**：git 工作副本机器（开发环境 Agent 持有 git 文件；本地 Synology 目录无 `.git`，仅文件同步层）
> **上游依据**：《REMEDIATION_PLAN.md》v1.1 + 用户 2026-10-13 全部裁决（M-1~M-8 判词签署；R-02a：①合流②剔除 SERLV③伪 W3 交易侧 + `0f1ac61` 退回；R-12：A 方案用户 git 机器 push）
> **授权范围**：本清单所列操作与 push 已获用户明确授权；清单之外的内容一律不得触碰、不得 push。

---

## v1.1 更新说明（v1.0 → v1.1）

技术审核 Agent 于 2026-10-13 对开发环境 Agent 执行响应报告完成独立核对，新增两项关键发现，均已并入本清单：

1. **第一批次整改（R-06/07/08/13/18/判决书/台账/报告等）在线上 main 树零落地**——全部变更仅存在于本地文件层（Synology 同步），线上 main 的 `docs/adr/` 仍为旧英文命名（0001~0006、0017、0018）、`src/data_acquisition/` 仍含 Wunderground 6 文件 + `.log`、`docs/audit/` 整目录不存在、`docs/项目方案和执行文档/` 仍 25 份混杂。→ 新增 **§〇.5 第一批次整改 git 落地（前置）**，须在 R-02 合流前完成。
2. **Plan v1.2 未见证据**：开发环境 Agent 声称 REMEDIATION_PLAN 已升 v1.2，但审核侧本地实测仍为 v1.1。→ 交付物清单新增强制项：**必须提供 Plan v1.2 文件本体**（或明确其产生位置与同步路径）。

---

## 〇、执行前核对（开始前 5 分钟完成，与线上实际不符则停止并回报）

| 核对项 | 线上实测（2026-10-13 核对） | 说明 |
| :--- | :--- | :--- |
| 仓库 | `https://github.com/oasislin/Poly2` | |
| `main` HEAD | `f7a3da4` — "docs(p7): 锚定主干基线指针至 5c4a4c9 (PR #132 W1 合流线)" | 2026-10-10 |
| `fix/p7-w2-shortloop` HEAD | `7c0d9bc` — "docs(audit): 登记判决书 v0.2 落盘与 M-2 闭环及 C 类三案对应关系" | 2026-10-12 |
| main...shortloop 差异 | `17 commits ahead / 0 behind / status=ahead` | total_commits=17 |

**分支现状提示**：线上现共存 15 个分支（main、fix/p7-w2-shortloop、fix/p7-w1-poolphase、docs/p7-doc-recon、docs/p7-transition、feat/p4-* ×3、feat/p5-* ×2、feat/p-series-ghcn-truth-layer、feat/r2-r3-ghcn-retraining-and-budget、fix/def-08-*、fix/p5-035-*、fix/r1-*、run/p4-*）。**本清单只处理 R-02 涉及的 `main` 与 `fix/p7-w2-shortloop`，其他分支不得触碰。**

---

## 〇.5 第一批次整改 git 落地（前置，R-02 合流前完成）

**背景**：第一批次整改（R-06/07/08/13/18/判决书签署/台账/报告）已在本地文件层全部完成并经审核侧独立验证一致（ADR 16 份统一中文命名、归档区完整、`src/data_acquisition/` 已清 Wunderground），**但线上 main 树不含任何这些变更**。本小节将"本地整改后现状"以分组 commit 方式落地到 git 树。

**目标树 = 本地整改后现状**（审核侧已验证，见下方各分组校验值）。

### G1 — ADR 治理落地（R-06/07/08 + ADR-0015 归档）
- `git mv`：`docs/adr/0001-gaussian-emos-with-variance-floor.md` → `docs/adr/ADR-0001：标准高斯EMOS与气候学方差Floor.md`；同法处理 0002~0006（目标名见本地 `docs/adr/` 实测清单）；
- `git mv`：`docs/adr/ADR-0018-reliability-gate-hierarchical-calibration.md` → `docs/adr/ADR-0018：小样本分档断崖裁定与门禁分层口径规范.md`；
- `git mv`：`docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md` → `docs/archive/ADR-0017：期望校准误差 (ECE) 统计口径规范、尖锐度概念纠偏与双层门禁仲裁（已废止）.md`；
- `git mv`：`docs/adr/ADR-0015.md`（短名版）→ `docs/archive/ADR-0015.md`（保留 `ADR-0015：废除高斯EMOS气候方差加法项…md` 在 `docs/adr/`）。
- 校验：`docs/adr/` 恰 16 份中文命名；无 0016/0017。

### G2 — 归档区落地（R-13）
- `git mv` 21 份历史文档：`docs/项目方案和执行文档/`（Phase 1 v5.5~v5.9.1、Phase 1.5 v1.0、Phase 2 v1.3/v2.0、方案 v2.2~v2.7 ×8、子任务单 ×4、旧策略 1 份）→ `docs/archive/项目方案和执行文档/`；
- `git mv` 5 份英文文档 → `docs/archive/early_english_docs/`（注意：线上 `docs/archive/` 现有 5 份英文文档直接平铺在 archive 下，需移动并保持 `docs/archive/` 内其余位置干净）；
- `git add`：`docs/archive/README.md`（归档索引）；
- `git add`：本地现行目录 2 份线上不存在的新文件——`Polymarket 温度市场微观结构、玩家画像与 Alpha 边界实证分析.md`、`天气套利参数标定与联合优化方案.md`（确认在本地存在后随 G5 一并提交）。
- 校验：`docs/项目方案和执行文档/` 恰 7 份现行；`docs/archive/项目方案和执行文档/` 21 份。

### G3 — 代码卫生落地（R-18）
- `git mv`：`src/data_acquisition/` 下 `mock_wunderground.py`、`wunderground_scraper.py`、`wunderground_scraper.py.backup`、`wunderground_scraper_enhanced.py`、`wunderground_scraper_original_temp.py`、`wunderground_scraper.log` → `docs/archive/wunderground_scripts/`（连同 README.md）；
- `git add`：`src/data_acquisition/__init__.py`（本地已清理，仅留归档注释）。
- 校验：`git ls-files src/data_acquisition/` 不含任何 `wunderground` 文件。

### G4 — 审计资产落地（判决书 / 台账 / 报告）
- `git add`：`docs/audit/` 整目录（P7-ALGO-VERDICT.md、DECISION_LEDGER.md、REMEDIATION_EXECUTION_REPORT_BATCH1.md、DEV_ENV_EXECUTION_BRIEF.md 等）。
- 校验：线上 `docs/audit/` 从 404 → 存在完整文件集。

### G5 — 文档修订落地（R-04/05/12 + v2.8 清理 + Plan）
- `git add`：`README.md`（CF6 结算源替换 + 框线对齐）、`docs/项目方案和执行文档/项目方案 (v2.8)…md`（Phase 4~7 三处已清，本地实测零命中）、`docs/REMEDIATION_PLAN.md`（**须为 v1.2，见交付物 #5**）。
- 校验：`git grep "Phase [4-7]" docs/项目方案和执行文档/` 零命中。

### G0 — 分组提交建议
每组合并为一个 commit（G1~G5 共 5 个 commit），消息带整改编号，如 `docs(adr): R-06/07/08 ADR 命名统一与废止归档`。**先提交 G1~G5 到 main**（这些变更与分支无关，属于"本地现状 → git 树"的纯落地），**再执行 §一 R-02 合流**，最后统一 push。

### GX — Synology 同步漂移警示（重要）
若 git 工作副本即 Synology 同步目录，`git checkout` / `git merge` 会改写工作区文件并同步到审核侧本地（文件状态漂移）。执行期间审核侧本地文件仅供参考，**验收一律以 git 树与线上为准**；执行 Agent 在报告交付物 #7 中说明同步影响。

---

### 1.1 合流白名单 —— 8 个提交（按时间序）

| sha | 日期 | 提交消息 | 归类 |
| :--- | :--- | :--- | :--- |
| `d7c3e62` | 10-10 | docs(w2): submit Phase 2 shortloop preregistration specification Rev.1.1 | W2 预注册规格 |
| `8335b44` | 10-10 | feat(w2): implement Phase 2 short loop confluence, asset governance, and audit | W2 短闭环核心 |
| `2cabfc0` | 10-11 | feat(w2): add 48h observation runner, empirical report, and closure errata | 48h 观测运行器 |
| `c718802` | 10-11 | docs(w2): add final sealing report and closure chain index | W2 封卷报告 |
| `a99b14d` | 10-11 | docs(audit): deliver Phase 2 Task 01 Fix issue closure audit report | T01 审计 |
| `8b9f05b` | 10-12 | chore(legacy): 入库 v1 策略代码与配置资产作为只读考古参照 | v1 遗产归档（**含 SERLV 杂质，见 1.3**） |
| `8d68d93` | 10-12 | docs: P7-ALGO-VERDICT v0.2 框架定稿 | 判决书 |
| `7c0d9bc` | 10-12 | docs(audit): 登记判决书 v0.2 落盘与 M-2 闭环及 C 类三案对应关系 | 判决书登记 |

### 1.2 退回黑名单 —— 9 个提交（伪 W3 交易侧 + v1 费率修复；`git revert` 保留历史，禁止 force push 删历史）

| sha | 日期 | 提交消息 | 退回理由 |
| :--- | :--- | :--- | :--- |
| `1f6f75e` | 10-11 | docs(w3): add environment freeze report and preregistration framework draft | 伪 W3 |
| `b7dc6e5` | 10-11 | docs(handoff): add Phase 2 Wave 3 task handoff document | 伪 W3 |
| `f357fa9` | 10-11 | docs(w3): finalize preregistration specification Rev.1.0 | 伪 W3 |
| `94eec7c` | 10-11 | feat(clob): implement read-only Polymarket CLOB data ingestion module | 伪 W3 交易侧 |
| `d7a114d` | 10-11 | feat(pricing): implement paper evaluation engine and probability pipeline | 伪 W3 交易侧 |
| `9ef9101` | 10-11 | fix(pricing): address reprimand P7-W3-REPRIMAND-001 and implement real EMOS | 伪 W3 交易侧 |
| `7ad54ea` | 10-11 | docs(spec): draft Annex A, conduct E-5 scan, and codify E-5 redline | 伪 W3 |
| `ea72141` | 10-11 | feat(w3): deliver offline replay framework and observation period handover | 伪 W3 |
| `0f1ac61` | 10-12 | fix(pricing): 修复零费率缺陷并落地 v1 动态费率与 Maker 返佣公式 | v1 费率修复入 pricing（用户裁决退回） |

### 1.3 SERLV 冲突副本剔除 —— 实测 **8 个**（⚠️ 修正 Plan v1.1 第六节"9 个"表述，以本清单实测为准）

全部位于 `legacy/v1-strategy/`，随白名单提交 `8b9f05b` 入库，属同步残留杂质，须从跟踪中剔除（保留 `legacy/v1-strategy/` 其余正式资产）：

```text
legacy/v1-strategy/config/config_SERLV_9月-07-190055-2026_Conflict.yaml
legacy/v1-strategy/src/analyst_SERLV_9月-07-191106-2026_Conflict.py
legacy/v1-strategy/src/config_SERLV_9月-07-191110-2026_Conflict.py
legacy/v1-strategy/src/dashboard_SERLV_9月-07-191104-2026_Conflict.py
legacy/v1-strategy/src/executor_SERLV_9月-07-191110-2026_Conflict.py
legacy/v1-strategy/src/main_SERLV_9月-07-191111-2026_Conflict.py
legacy/v1-strategy/src/scanner_SERLV_9月-07-191117-2026_Conflict.py
legacy/v1-strategy/src/strategy_SERLV_9月-07-191125-2026_Conflict.py
```

### 1.4 推荐执行序列（命令级）

**方法 A（推荐）：revert 黑名单 → 剔除 SERLV → 合流 main**

```bash
git fetch origin
git checkout fix/p7-w2-shortloop
git pull origin fix/p7-w2-shortloop

# ① 逆序 revert 黑名单 9 提交（先 revert 最新的）
git revert --no-edit 0f1ac61
git revert --no-edit ea72141
git revert --no-edit 7ad54ea
git revert --no-edit 9ef9101
git revert --no-edit d7a114d
git revert --no-edit 94eec7c
git revert --no-edit f357fa9
git revert --no-edit b7dc6e5
git revert --no-edit 1f6f75e

# ② 剔除 SERLV 冲突副本（8 个）
git rm --cached legacy/v1-strategy/config/config_SERLV_9月-07-190055-2026_Conflict.yaml
git rm --cached legacy/v1-strategy/src/*_SERLV_*_Conflict.py
git commit -m "chore(legacy): 剔除 SERLV 同步残留冲突副本 8 个（R-02 用户裁决）"

# ③ 合流到 main
git checkout main
git pull origin main
git merge fix/p7-w2-shortloop --no-ff -m "Merge fix/p7-w2-shortloop: R-02 合流（W2 核心 + T01 审计 + v1 归档 + 判决书；剔除伪 W3 与 SERLV 残留）"

# ④ 验证（见 1.5）通过后 push
git push origin main
```

**方法 B（备选）：cherry-pick 白名单到 main**（失去原 sha，且 `8b9f05b` 须先剔除 SERLV 文件再 pick）——仅当方法 A 遇不可解冲突时采用，采用前先回报。

### 1.5 验证要求（全部通过才能 push / 交付）

| # | 验证命令 | 预期结果 |
| :--- | :--- | :--- |
| 1 | `git log --oneline main` | 包含 8 个白名单提交（或其内容等价物）；含 9 个 revert 记录 + 1 个 SERLV 剔除提交 |
| 2 | `git ls-files | findstr SERLV` | 空（无任何 SERLV 文件被跟踪） |
| 3 | `git diff --stat main origin/fix/p7-w2-shortloop` | 合流后应接近一致（如有差异须说明） |
| 4 | `git log --oneline --grep revert` | 9 条 revert 记录（历史保留） |
| 5 | `git status` | 干净 |

### 1.6 执行注意与冲突处理

1. **白名单/黑名单历史交错**：时间序上 `1f6f75e`(W3 文档) 早于 `a99b14d`(T01 审计白名单)，revert 黑名单只产生新的 revert 提交、不删历史，不影响白名单内容。
2. **revert 冲突**：`d7a114d`/`94eec7c`(pricing/CLOB) 若与白名单提交（如 `8335b44` W2 短闭环）触碰同一文件而冲突，处理原则 = **保留白名单内容，丢弃黑名单功能**；无法机械解决时停止并回报，不得擅自裁剪白名单内容。
3. **本地文件交叉核对**：本地同步目录 `src/data_acquisition/` 现存在 `polymarket_clob_collector.py` 与 `polymarket_crawler.py`（疑似来自黑名单提交 `94eec7c` 的同步残留）。R-02 合流后，需核对 main 实际树中这两个文件的去留，并给出"本地同步目录中该文件的处理建议"（保留/删除由用户裁决，执行 Agent 不得自行删除本地文件）。
4. 合流前若 `main` 已推进（HEAD ≠ `f7a3da4`），先停止、回报新状态，不得擅自 rebase。

---

## 二、R-12 线上 README 同步（用户裁决：A 方案——用户 git 机器 push，我方提供替换依据）

### 2.1 背景
本地 `README.md` 已按用户裁决完成 CF6 术语替换与排版修正，但线上仓库 README 尚未同步。本次由开发环境 Agent 将本地权威版本推送上线。

### 2.2 操作
1. 从同步目录取权威版本：`C:\SynologyDrive\Project\Poly Way2\README.md`（经 Synology Drive 同步到达开发机；若开发机未同步到，向用户/管理侧索取该文件）；
2. 覆盖仓库内 `README.md` → `git add README.md` → `git commit -m "docs(readme): CF6 结算源术语对齐官方时序表（Time Series Tabular）表述并修正排版（R-12）"` → `git push`；
3. **push 后**：提供线上 README 链接 + commit sha + 变更行摘要（本地第 56 行结算源 + 框线对齐）。

### 2.3 交付
- 线上 README URL：`https://github.com/oasislin/Poly2/blob/main/README.md`
- commit sha（8 位）
- 同步回本地说明（README 在本地与线上应一致）

---

## 三、文档补齐（若在开发环境一并执行，则与上述内容一起 push）

### 3.1 项目方案 v2.8 —— 残留 "Phase 4~7" 清理（3 处）

文件：`docs/项目方案和执行文档/项目方案 (v2.8)：Polymarket 温度市场量化投注系统.md`

| 行号 | 残留原文 | 建议替换（四层命名体系口径） |
| :--- | :--- | :--- |
| 8 | `对齐 Phase 7 过渡态与三波次路线图` | `对齐 Phase 2 波次路线图（W1~W3）与工单序列（P4~P7）执行节奏` |
| 21 | `吸收 Phase 7 过渡态长线规划裁决（docs/ROADMAP.md）` | `吸收 Phase 2 后续波次长线规划裁决（docs/ROADMAP.md）` |
| 88 | `在 Phase 4 / Phase 6 实际工程落盘中` | `在 P4 / P6 工单实际工程落盘中` |

> 替换口径约束（硬）：全仓仅允许四个阶段（Phase 1 / 1.5 / 2 / 3）；"P4~P7"仅作工单编号；"W1~W3"仅作 Phase 2 内部波次；不得再出现 "Phase 4~7"。若建议措辞与上下文语境冲突，可微调，但必须符合上述约束。
> 完成后同步更新 `docs/archive/README.md` 索引中对该文件的描述（如有涉及）。

### 3.2 REMEDIATION_PLAN 升版 v1.2

- **强制交付**：开发环境 Agent 声称已升 v1.2（执行响应报告），但审核侧本地实测 `docs/REMEDIATION_PLAN.md` 仍为 v1.1。**必须提供 v1.2 文件本体**（或明确其产生位置与同步路径），审核侧将逐条核对内容；
- 升版 v1.2 须包含（若尚未完成）：
  1. 状态总览刷新：R-06 / R-07 / R-08 / R-04 / R-05 / R-13 / R-18 + 台账 → **已完成项 12 项**；
  2. **修正第六节 SERLV 计数：9 个 → 8 个**（实测值）；
  3. 新增 R-02 执行结果记录（合流 8 / revert 9 / SERLV 剔除 8 / 合流后 main HEAD）；
  4. 记录 v2.8 三处残留清理完成情况；
  5. 更新 v1.2 更新说明（版本标注：v1.1 → v1.2，日期 2026-10-13）。
- 升版后交付 v1.2 文件（同步回本地），审核侧将验证：头部版本标注、12 项完成统计、SERLV 8 个修正。`

---

## 四、完成后必须提供（交付物清单）

执行完成后，以下文件/证据需一并提供（供同步回本地 + 线上核对）：

| # | 交付物 | 内容要求 |
| :--- | :--- | :--- |
| 1 | 执行报告 | 每条关键命令 + **原始输出末尾片段**（不得修饰）+ 判定两步分离（原始观测值 = …；判定阈值 = …；结论 = 通过/不通过）；格式参照 `docs/audit/REMEDIATION_EXECUTION_REPORT_BATCH1.md` |
| 2 | 合流后 main 提交记录 | `git log --oneline -30 main` 输出 |
| 3 | SERLV 剔除验证 | `git ls-files \| findstr SERLV`（应为空）输出 |
| 4 | revert 记录 | `git log --oneline --grep revert` 输出 |
| 5 | **REMEDIATION_PLAN.md v1.2 文件本体** | **强制交付**：审核侧本地实测仍 v1.1，必须提供 v1.2 全文；连同 README.md、v2.8 修改文件 |
| 6 | 线上确认 | push 后的 commit sha 列表 + PR 链接（如走 PR 流程） |
| 7 | 本地同步说明 | 哪些文件已改、如何经 Synology Drive 同步回本地、本地需复查项；含 GX 漂移警示（若 git 操作发生在 Synology 目录） |
| 8 | **G1~G5 落地验证** | ① `git ls-files docs/adr/`（恰 16 份中文命名）；② `git ls-files src/data_acquisition/`（无 wunderground）；③ `git ls-files docs/audit/`（存在）；④ `git ls-files docs/项目方案和执行文档/`（恰 7 份）；⑤ `git grep "Phase [4-7]" docs/项目方案和执行文档/`（零命中） |

---

## 五、纪律与红线（AGENTS.md 铁律 + 用户裁决）

1. **push 范围**：仅限本清单所列内容（第一批次 G1~G5 落地、R-02 合流结果、README、v2.8、Plan v1.2）；其他分支/提交一律不 push。**push 动作本身仍需用户最终明确点头**（AGENTS.md 铁律：push 仅凭人工明确指令）；
2. **禁止 force push 删历史**：退回一律 `git revert` 保留历史记录。
3. **原始观测不可篡改**：命令输出原样引用，不得改写、美化、四舍五入。
4. **"通过"声明必须附证据**：未执行的验证不得写"通过"，只能写"未验证"。
5. **术语红线**：四层命名体系（阶段/工单/波次/任务）是用户裁决的宪法级口径，不得自由发挥。
6. **异常即停**：执行中发现与本清单不符的线上状态、冲突无法机械解决、或 main 已推进，立即停止并回报，不得自行裁决。
7. **不擅自删除本地文件**：本地同步目录中的文件（如疑似残留的 clob 采集文件）只报告建议，删除与否由用户裁决。
