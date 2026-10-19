# P4 复核对账 · 终审并表结论（技术审核方）· 2026-10-19

> **依据**：开发端《P4 复核对账单（开发端实测复检）交付报告》全项回交 MATCH + 审核方本地独立抽查。
> **性质**：本单只做事实并表与分层标注，**不替委员会裁决阈值、不放行开工、不改代码、不 push**。终审权归用户/评审委员会。

---

## 一、终审摘要（先读）

1. **对账层面：双方对物理工件与成文口径的观测全部一致（MATCH）**。审核方本地可独立复验的项（隔离件字节数、c_train、pooled ECE、3 折触发、1200 格、QUARANTINED 标记、flag 缺失、P5 代码常量、ADR/预注册原文、p5_integration:81）已逐项抽查吻合，**可背书**。
2. **MATCH ≠ 可开工放行**：对账只证明"两边看到的事实相同"，**没有解决任何决策问题**。P4 是否重启、基线取哪个 commit、ECE 层级书面裁决，仍待用户/委员会拍板（见 §五）。
3. **git / GitHub 项全部为开发端自述，审核方本地无 `.git`、无 gh，未独立复验**（见 §三），需用户在 GitHub 侧核对；其中存在三个 main 版本号并存，需澄清。

---

## 二、审核方可本地背书的事实（已独立抽查吻合）

> 以下均为审核方本地文件原文 + 本轮抽查，与开发端回交逐字一致。

| 编号 | 事实 | 审核方本地原始观测（出处） | 本地核验 |
| :--- | :--- | :--- | :--- |
| V1 | 隔离件字节数 | `standalone_recompute_active10.py`=10282 B；`active10_manifest.json`=3000 B；`active10_settlement_report.md`=11690 B；`2019_oos_active10_arrays.parquet`=367285 B（09-23 22:48:03） | 本轮 PowerShell 抽查吻合 |
| V2 | 授权 flag 缺失 | `evidence/preregistered_2019_authorization.flag` 不存在（`Test-Path=False`）；`airgap.py:57-63` 要求 5 个 frozen_gate_thresholds 字段 + `status=AUTHORIZED` | 本轮抽查吻合 |
| V3 | 20 折仅 KORD 先导 | `p4_block_cv_20fold_summary.json`：station=`KORD`，gate_passed_count=`17`，pooled `weighted_ece=0.0019467096618599276`、`ks_stat=0.00721790261024291`、`sample_count=96180`；fold_04 KS=`0.08669370`，fold_11/17 wilson=`0.66666667` | 原文一致 |
| V4 | 挂账4 c_train | mean=`0.9670247410738085`，CI=`[0.9653571613465265, 0.9686251342546373]`，min=`0.9589170815546266`，max=`0.9748712556432498` | 原文逐字一致 |
| V5 | 模型库格数 | `data/models/` 根目录 1200 pkl；archive 800；manifest `total_models=1200 / statutory=720 / aux=160`，status 720/240/160/80，max/min 各600，6h=320 | 本地计数吻合 |
| V6 | QUARANTINED 隔离 | `active10_settlement_report.md:1-5` 头部 `[QUARANTINED]`，禁引用为调参/验收依据 | 原文一致 |
| V7 | P5 代码默认常量 | `p5_gate.py`：max_ece=`0.05`(:137)、max_ks_stat=`0.08`(:140)、min_coverage=`0.90`(:138)、min_bss=`0.0`(:139)、σ<0.90 硬拦截(:105) | 原文一致 |
| V8 | p5_integration 文书滞后 | `p5_integration.md:81` ks_stat 写 `≤0.05`，与代码 0.08 / ADR-0018 的 0.08 不符，属未同步 | 本轮 Read 确认 |
| V9 | KMIA 挂旗 | ECE=`0.018318` 越 `0.0100`，计数 `1/2`，COMPLETED_ECE_FLAGGED（STATUS:11 / HANDOVER_P7:31 / Backlog03） | 原文一致 |
| V10 | 法定口径 | 2000–2018 训练 / 2019 Airgap；airgap 三道拦截 `verify_year_whitelist:104 / verify_file_path:134 / sanitize_dataframe:154` | 原文一致 |

---

## 三、开发端自述 · 审核方未复验（本地无 git/gh）

> 以下来自开发端回交，审核方**无法在本地独立验证**，需用户在 GitHub / 其克隆侧核对，**不得视为已证实**。

| 编号 | 开发端自述 | 审核方状态 |
| :--- | :--- | :--- |
| U1 | 分支 `feat/p4-audit-reliability-v1.2` 顶端 `b438dc4`；main HEAD `3649524`；`rev-list main...分支 = 49 0`（分支领先 0，已全量合入 main） | 未复验 |
| U2 | PR #128（Merge `4824edb`）、PR #129（Merge `6fe386c`）均 Merged；合流基线 `69443ca` | 未复验 |
| U3 | 三 commit 改动：b478c50（90 files / +238420 / -1295）、518cd63（6 files / +94 / -23）、1d12854（2 files / +145） | 未复验 |
| U4 | `gh issue list --state open` = no open issues；#114、#117 均 CLOSED；无开放 P4 工单 | 未复验 |
| U5 | 全库 `1006 passed`（测试基线） | **未运行测试，未复验** |

### ⚠ 需用户在 GitHub 澄清的版本号并存
开发端回交中出现**三个 main 版本号**，关系未说明，审核方无法判定：
- `3649524`（自述 main HEAD，U1）；
- `69443ca`（自述合流基线，U2）；
- `5c4a4c9`（STATUS.md:15 文字记录的 PR#132 合流线）。
且 PR #128/#129 编号小于 #132。**请用户在 GitHub 核对当前 main 真实顶端、分支合流状态与 STATUS 记录是否一致**，再定 P4 基线。

---

## 四、ECE/KS 门禁层级厘清（双方解释一致，仍待书面裁决）

开发端分层与审核方判断一致，**作为解释陈列，不视为矛盾已消除**：

| 层级 | ECE | KS | 出处 |
| :--- | :--- | :--- | :--- |
| 研发 / 单折 CV 泛化门禁 | ≤3.0% | p≥0.05 | ADR-0015 §2.4；预注册 §七（20 折折外平均） |
| Phase 2 生产池化终验（Binding Pooled） | ≤5.0% | D_KS≤0.08 | ADR-0018 §3.2；`p5_gate.py` 默认 |

- 待办文书动作：`p5_integration.md:81` ks `≤0.05` 勘误为 `≤0.08`（与代码/ADR-0018 同步）。
- ADR-0015(3.0%) 与 ADR-0018(5.0%) 的成文并存，**仍需委员会正式书面裁决/立新 ADR**，审核方不代裁。

---

## 五、待用户 / 委员会终审裁决清单（对账未解决项）

| 编号 | 待裁决项 | 现状（双方已核实事实） |
| :--- | :--- | :--- |
| D1 | **P4 是否正式重启/立项？基线 commit 取哪个？** | 无开放 Issue（自述），全 CLOSED；当前 main 版本号待澄清（§三）。对账未授权开工。 |
| D2 | ECE 层级书面裁决 + `p5_integration.md:81` 勘误 | 3.0%=研发/CV，5.0%=生产 Binding（§四），待成文固化 |
| D3 | KMIA_12h 是否随 P4 立项 | ECE 0.018318/0.0100、1/2，属 P7 带旗服役；默认不并入 P4，待裁 |
| D4 | 开发端承接会话窗口 | 沿用 `P2 Task01 Fix`（`8f3244dd-…`）或新开，待用户定 |
| D5 | 960 格全网格重训/CV 的分期与启动 | 当前仅 KORD/18h/TMax/4 格（0.417%）先导，余 956 格 0%；现网 1200 格属 P7 矩阵，不计入 P4 完成度 |

---

## 六、纪律声明

- 零代码修改：未改 `src/`、`scripts/`、`tests/`。
- 零 push：未触发任何 git push。
- 未运行测试：1006 passed 等测试结论均标注「未复验」，未作通过声明。
- 客观并表：git/GitHub 项标注为开发端自述，未代证；阈值未代裁。

**编制**：技术审核 Agent | 2026-10-19 | 供用户/委员会终审。
