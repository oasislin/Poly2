# P8-CLASS1-LAUNCH-CHK-16 · CHK-15 文本勘误与答辩记录单

> **日期**：2026-10-26
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-16`
> **A 线锚点**：`Phase 2 Task 08 - Ticket 04 / #137`
> **本单性质**：对已推送冻结件 `CHK-15` 的**补正单**（依规范 §2.5「已封盘历史件不回改，勘误走新单」）
> **关联件**：`P8-CLASS1-LAUNCH-CHK-15`（`430f6ab`，不可改写）
> **前序**：复核方质询单（Q-1~Q-4）→ 开发端《质询答复书》→ 本单裁决

---

## 一、裁决结论

**Ticket 04（#137）通过。CHK-15 的功能性结论有效；其文本层三处瑕疵由本单补正，CHK-15 正文不重签、不 force push。**

责任划分如下，不得含糊：

| 质询 | 事项 | 责任方 | 裁定 |
| :-- | :-- | :-- | :-- |
| **Q-1** | G1~G3 耗时填开发端自测值，却沿用「复核方本机实测原始值」表头 | **开发端** | 成立，已自认，记一次 |
| **Q-2** | 观察项 O-1 / O-2 未经定义即写入 | **复核方（我）** | **撤销质询**，开发端无责 |
| **Q-3** | 第 34 行 `git diff` 命令基线选错 + 路径简写 | **开发端** | 成立，且比自述更严重（见 §三） |
| **Q-4** | 已推送单据处置方式 | 无责 | 接受其纪律承诺 |

**推送合规性**：`430f6ab` 于 2026-10-26 22:04:02 由用户明确授权推送（`reflog: update by push`）。复核方先前「擅自 push」的判定（V-1）**予以作废**，不记违规。

---

## 二、Q-1 裁定与事实

| 项 | 开发端答复书自述 | 复核方实测 | 差异 |
| :-- | :-- | :-- | :-- |
| G1 | `16 passed in 2.52s`（自测） | `16 passed in 15.75s` | 计数一致，**耗时为本机自测值** |
| G2 | `90 passed in 2.42s`（自测） | `90 passed in 23.13s` | 计数一致，**耗时为自测值** |
| G3 | `203 passed in 2.70s`（自测） | `203 passed in 17.85s` | 计数一致，**耗时为自测值** |

- CHK-15 表头标注「复核方本机实测原始值」，但主列耗时为开发端本机输出 → **身份混淆成立**。
- 开发端答复原文：「这严重混淆了『复核方审计实测』与『开发端本地执行』的身份边界……诚恳认错，接受质询核减。」——自认有效，记录在案。
- **实质影响**：不影响任何通过/不通过判定（计数与布尔结论全部相符），仅影响溯源可信度。

**附加说明（复核方自责）**：CHK-15 草稿中 G1 记为「14 passed」，系复核方沿用首轮数值、未在第二轮重测所致。开发端将其更正为 16 并同时保留两轮数值，**该处更正方向正确**。

---

## 三、Q-3 裁定：比自述更严重

开发端自述仅为「路径简写」。复核方实测发现**两个叠加缺陷**：

1. **路径简写**：`registry.py`、`version_watchdog.py` 在仓库根不存在，真实路径为 `src/modeling/registry.py`、`src/contract/version_watchdog.py`。简写路径下的 `git diff` **恒为空**，结论「禁区差异为空」属假阴性。
2. **基线退化（开发端未自述）**：命令基线选用 `origin/main`。该单据推送后 `HEAD == origin/main`（均为 `430f6ab`），**两个相同 commit 相减恒为空**，命令在任何情况下都失去鉴别力。

复核方以正确基线 `d302d14`（Ticket 04 开工前基线）实跑：

```bash
git diff d302d14 HEAD -- data/models/ src/modeling/registry.py src/contract/version_watchdog.py
# → （标准输出为空，exit code 0）
```

**原始观测值 = 空；判定阈值 = 空；结论 = 通过。** 禁区零改动这一**事实成立**，但依据不是 CHK-15 所载命令。

---

## 四、Q-2 裁定：责任在复核方

复核方调阅自己签发的定稿指令原件，确认其中包含「登记 O-1~O-4（含 O-3 报告与差分不对齐、O-4 审计语义）」一句，而草稿正文仅列出 O-3 / O-4。

- 开发端依该句补齐 O-1~O-4，属**照令执行**，且 O-1 的素材直接取自复核方此前的正面评语，O-2 取自 Stage 4 内存对象改造事实，内容与实测相符。
- **裁定：撤销 Q-2，开发端无责。** 该瑕疵归因于复核方起草时「正文与指令不一致」。

---

## 五、复核方独立实测汇总（本单唯一有效观测源）

| 项 | 命令 | 原始观测值 | 判定阈值 | 结论 |
| :-- | :-- | :-- | :-- | :-- |
| G1 | `pytest tests/unit/contract/test_trigger_model_retest.py -q` | `16 passed in 15.75s` | 16 / 0 failed | 通过 |
| G2 | `pytest tests/unit/contract -q` | `90 passed in 23.13s` | 90 / 0 failed | 通过 |
| G3 | `pytest tests/unit/prediction tests/unit/risk tests/unit/contract -q` | `203 passed in 17.85s` | 203 / 0 failed | 通过 |
| G3b | 同上 `--collect-only -q` | `203 tests collected in 7.70s` | 收集数 = 203 | 通过 |
| G4 | AST 扫描 `scripts/trigger_model_retest.py` | `max = 39`，超 50 行 = 无 | < 50 | 通过 |
| G5 | `PhysicalParamTableValidator.validate_json(...)` | `True` | True | 通过 |
| G6 | `ContractVersionWatchdog().check()` | `is_valid=True, verified=22, failed=0, skipped_6h=64, bypassed=False` | is_valid=True / failed=0 | 通过 |
| G7 | `reconcile_m5_asset_counts(...)` | `22 / 88 / 144 / 176, all_passed=True` | all_passed=True | 通过 |
| 禁区 | `git diff d302d14 HEAD -- <三禁区路径>` | 空（exit 0） | 空 | 通过 |
| 异常 | `grep "except Exception\|except:"` | 0 处 | 0 处 | 通过（M-3 闭合） |
| 函数名 | `grep "convert_v2_blindtest_to_contract"` | 0 命中 | 0 | 通过 |
| 工作树 | `git status -sb` | `## main...origin/main`（无 ahead/behind） | 与远端一致 | 通过 |

---

## 六、CHK-15 三处文本瑕疵清单（补正对象）

| 序号 | 位置 | 瑕疵 | 正确表述 | 归责 |
| :-- | :-- | :-- | :-- | :-- |
| T-1 | 第 23~25 行 G1~G3 表 | 耗时为开发端自测值，表头标为复核方实测 | 复核方实测为 15.75s / 23.13s / 17.85s；开发端自测值须单独标注 | 开发端 |
| T-2 | 第 77~86 行 观察项 | O-1 / O-2 为复核方指令要求但未在正文定义 | 序号歧义源于复核方指令 | 复核方 |
| T-3 | 第 34 行 禁区差分 | 路径简写 + 基线 `origin/main` 退化 | 应为 `git diff d302d14 HEAD -- data/models/ src/modeling/registry.py src/contract/version_watchdog.py` | 开发端 |

---

## 七、本单确立的审计纪律（建议同步入 `项目编号与命名规范` §5）

1. **审计单据中的 `git diff` 命令，基线不得使用 `origin/main`**（推送后退化为恒空）；必须写明具体 commit SHA 或 `HEAD~N`。
2. **命令字符串落盘前必须实跑一次，并附输出**；凡「输出为空即通过」的判定，须证明该命令在**非退化基线**下执行。
3. **审计单据内一切数值必须标注采集方**（复核方实测 / 开发端自测），不得混用。
4. **正文与指令必须自洽**：复核方起草时应保证正文条目与指令描述逐条对应，避免下游按指令补齐形成序号歧义。

---

## 八、签署与不可变声明

- **Ticket 04（#137）首轮交付复核：通过**，具备关闭条件。
- CHK-15 保持 `430f6ab` 原状，不重签、不 force push、不回改。
- 复核方未代跑 `gh`、未执行任何 push；本轮未改动任何代码文件。
- **本单一经签发永久冻结，正文与数值永不改写。**
