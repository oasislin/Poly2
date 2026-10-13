# 工单交付报告：P7-DOC-ALIGN-1 文档全量收集与授权对齐执行

- **工单编号**：`P7-DOC-ALIGN-1`
- **角色定位**：文档协作 Agent（只读盘点、授权对齐执行、原始计划提取、呈报，不承担功能开发）
- **执行日期**：2026-10-12
- **工作分支**：`fix/p7-w2-shortloop` (HEAD `ea72141e298d56a1f4f2d0de3e5ce41cda859d66`)
- **主干基线**：`origin/main` (HEAD `f7a3da4c2f2463b5fc20b35a0df97779098f49fa`，锚定 PR #132 合流线 `5c4a4c9`)
- **全库测试状态**：开工基线 1006 passed, 10 skipped, 0 failed（耗时 ~42s，零失败）

---

## 任务 1 · 文档全量收集与只读盘点

### 1.1 全库核心活性文档盘点清单

依工单要求，对全库活性文档进行系统性只读排查，登记版本、最后实质修改 Commit、所处分支以及与代码现实的一致性判定：

| 序号 | 文档相对路径 | 版本 / 标识日期 | 最后实质修改 Commit 与日期 | 分支位置 | 一致性状态 | 依据与事实说明 |
| :---: | :--- | :--- | :--- | :--- | :---: | :--- |
| 1 | `README.md` | 对齐 Phase 7 过渡态 | `85f17d7` (2026-10-10) [本次前] / 当前工作区已修 | `fix/p7-w2-shortloop` (未提交) | **已修正** | 原内容滞后于 PR #130（987 passed），现已通过任务 2 授权修正锚定 PR #132（1006 passed、NWS WRH 真值源、Flag 2 拔除）。 |
| 2 | `docs/ROADMAP.md` | v1.1.0 推进版 | `0f62bca` (2026-10-10) [分支新增修改] | `fix/p7-w2-shortloop` (未提交) | **一致** | 反映 W1 已封卷、W2 短闭环跑通、W3 待启动，与代码现实一致。 |
| 3 | `STATUS.md` | 唯一状态入口 (2026-10-10) | `f7a3da4` (2026-10-10) | `origin/main` / 本分支同步 | **一致** | 主干与分支均已锚定至 `5c4a4c9` (PR #132)，Flag 2 记录拔除，反映 W1 执结与 W2 筹备，状态自洽。 |
| 4 | `DEVELOPER_GUIDELINES.md` | 开发指南规范 | `fe46f24` (2026-09-02) / 工作区增补 Checklist | `fix/p7-w2-shortloop` (未提交) | **一致** | 包含开发流程与 PR Checklist 门禁阻断要求，与纪律现实一致。 |
| 5 | `docs/MODEL_SCORECARD.md` | 四维体检预注册门禁体系 | 新建未跟踪文件 (2026-10-12) | `fix/p7-w2-shortloop` (Untracked) | **一致** | 完整包含 ECE、Bias、CRPSS、Coverage 四维红黄绿门禁，并已追加未审计默认红级补充条款。 |
| 6 | `docs/项目方案和执行文档/项目方案 (v2.8).md` | v2.8 Final | `85f17d7` (2026-10-10) | `origin/main` / 本分支同步 | **一致** | 顶层方案，已吸收 ADR-0011~0014、废除方差加法项、对齐 960 模型库与三波次路线图。 |
| 7 | `docs/项目方案和执行文档/Phase 2 执行文件 v2.1.md` | v2.1 盘口定价与执行 | `85f17d7` (2026-10-10) | `origin/main` / 本分支同步 | **一致** | 细化执行文件，收窄 W2 为双站纸面盘短闭环，Task 03/05/06 顺延至实盘前置。 |
| 8 | `docs/audit/01_document_inventory.md` | P7 对账文档盘点 | 新建文件 (2026-10-12) | `fix/p7-w2-shortloop` | **一致** | 历史盘点底稿，已完整归档。 |
| 9 | `docs/audit/02_three_way_reconciliation.md` | 三方对账报告 | 新建文件 (2026-10-12) | `fix/p7-w2-shortloop` | **一致** | 涵盖主干基线、KMIA 双旗、W1~W3 进度三方对账。 |
| 10 | `docs/audit/03_shadow_inventory.md` | 影子资产清单 | 新建文件 (2026-10-12) | `fix/p7-w2-shortloop` | **一致** | 登记代码先于路线图的构件清单。 |
| 11 | `docs/audit/04_remaining_tasks_backlog.md` | 剩余任务 Backlog | 新建文件 (2026-10-12) | `fix/p7-w2-shortloop` | **一致** | 登记未完成任务条目与依赖关系。 |
| 12 | `docs/audit/05_handover_package.md` | 新会话交接包 | 新建文件 (2026-10-12) | `fix/p7-w2-shortloop` | **一致** | 阶段性交接说明。 |
| 13 | `docs/audit/P7-PROV-1_provenance.md` | 交易模块溯源报告 | 新建文件 (2026-10-12) | `fix/p7-w2-shortloop` | **一致** | 确权五个交易模块来源与宪法对齐状态。 |
| 14 | `docs/audit/P7-W2-SHORTLOOP_handover.md` | W2 短闭环交接报告 | 新建文件 (2026-10-12) | `fix/p7-w2-shortloop` | **一致** | 记录 W2 纸面盘端到端联调全流程。 |
| 15 | `docs/audit/p7_w2_model_health_report.md` | Active 10 模型体检报告 | 新建文件 (2026-10-12) / 已勘误 | `fix/p7-w2-shortloop` | **已勘误一致** | 已将 KMIA 12h 改判为红级禁投（0.0x），与 MODEL_SCORECARD 绝对红线一致。 |

### 1.2 架构决策记录（ADR 0001 ~ ADR 0018）全量盘点

| ADR 编号与文件名 | 状态 | 提出日期 | 分支位置 | 一致性状态与核心要旨 |
| :--- | :---: | :---: | :---: | :--- |
| `0001-gaussian-emos-with-variance-floor.md` | SUPERSEDED | 2026-08-15 | `main` | 历史基线，由 ADR-0010/0015 继承替代。 |
| `0002-five-lead-time-nodes-with-interpolation.md` | SUPERSEDED | 2026-08-15 | `main` | 历史基线，由自适应时区与动态插值继承替代。 |
| `0003-two-level-degradation.md` | ACTIVE | 2026-08-15 | `main` | 两级降级原则有效。 |
| `0004-five-member-strict-alignment.md` | ACTIVE | 2026-08-15 | `main` | GEFS 5 成员对齐有效。 |
| `0005-grib-merge-coordinate-tolerance.md` | ACTIVE | 2026-08-20 | `main` | GRIB 网格容差规范有效。 |
| `0006-discrete-bin-probability-vs-cumulative-tail.md` | ACTIVE | 2026-09-01 | `main` | 离散分桶概率计算规范有效。 |
| `ADR-0007：数据源重铸与站点宇宙扩展.md` | ACTIVE | 2026-09-04 | `main` | 废除 Wunderground，确立 IEM 原报真值，扩展 12 站池。 |
| `ADR-0008：GEFS 再预报全池采购与时区自适应.md` | ACTIVE | 2026-09-07 | `main` | 全球 0.25° 网格采购与冷归档，动态时区自适应。 |
| `ADR-0009：芝加哥 08-31 特报结算语义裁决.md` | ACTIVE | 2026-09-11 | `main` | 特报实况截断层规则基石。 |
| `ADR-0010：气候学方差门禁物理上限标定.md` | ACTIVE | 2026-09-17 | `main` | 标定 15.0°F 方差上限。 |
| `ADR-0011：双源单调合流架构与两维阶梯风控.md` | ACTIVE | 2026-09-19 | `main` | 彻底废除切换窗，确立单调合流与残差两维风控。 |
| `ADR-0012：法定结算真值源（NWS WRH）与双轨估值.md` | ACTIVE | 2026-09-19 | `main` | 确立 NWS WRH 结算源、僵尸仓位双轨估值。 |
| `ADR-0013：特报高频截断与异常安全阻断.md` | ACTIVE | 2026-09-20 | `main` | 特报纯温门禁、迟到不投、跳温阻断。 |
| `ADR-0014：统一异常仲裁中枢与安全挂起协议.md` | ACTIVE | 2026-09-20 | `main` | 控制面 CentralExceptionArbiter 与 Fail-Closed 机制。 |
| `ADR-0015：废除高斯EMOS气候方差加法项...md` | ACTIVE | 2026-09-23 | `main` | 废除加法项，确立平方参数化与方差底座。 |
| `ADR-0015.md` (英文短名版本) | CONCURRENT | 2026-09-23 | `main` | **格式异常（双副本并存）**：比长名版多出 §3 方差重标与 KSFO d=0 成因。 |
| `ADR-0016` (缺失) | MISSING | 无据可查 | 缺失 | **物理缺失**：被 ADR-0017 引用，全库无独立物理文件。 |
| `ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md` | ACTIVE | 2026-09-24 | `main` | 纠偏校准度与尖锐度，确立交易窗口加权 ECE 0.0100 门禁。 |
| `ADR-0018-reliability-gate-hierarchical-calibration.md` | ACTIVE | 2026-10-09 | `main` | 确立分层校准门禁体系。 |

### 1.3 附：`git status` 原始输出

```
On branch fix/p7-w2-shortloop
Your branch is up to date with 'origin/fix/p7-w2-shortloop'.

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
	deleted:    scripts/download_wunderground_batch.py
	deleted:    scripts/download_wunderground_batch_enhanced.py
	deleted:    scripts/download_wunderground_data.py
	deleted:    src/data_acquisition/mock_wunderground.py
	deleted:    src/data_acquisition/wunderground_scraper.log
	deleted:    src/data_acquisition/wunderground_scraper.py
	deleted:    src/data_acquisition/wunderground_scraper.py.backup
	deleted:    src/data_acquisition/wunderground_scraper_enhanced.py
	deleted:    src/data_acquisition/wunderground_scraper_original_temp.py

Changes not staged for commit:
  (use "git add/rm <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   DEVELOPER_GUIDELINES.md
	modified:   README.md
	modified:   docs/ROADMAP.md
	deleted:    docs/w3_observation_protocol.md
	deleted:    docs/w3_observation_report_template.md
	modified:   docs/w3_polymarket_ingestion_preregistration.md
	modified:   docs/w3_spec_annex_a.md
	modified:   evidence/p4_block_cv_20fold_summary.json
	deleted:    scripts/run_w3_clob_snapshot_batch.py
	modified:   src/data_acquisition/polymarket_clob_collector.py
	modified:   src/prediction/real_emos_pipeline.py
	modified:   src/pricing/paper_evaluation_engine.py
	deleted:    src/pricing/w3_offline_replay_analyzer.py
	modified:   tests/unit/data_acquisition/test_polymarket_clob_collector.py
	modified:   tests/unit/pricing/test_paper_evaluation_engine.py
	deleted:    tests/unit/pricing/test_w3_offline_replay_analyzer.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	docs/MODEL_SCORECARD.md
	docs/audit/
	scripts/run_p7_w2_shortloop_paper_simulation.py
```

### 1.4 附：`git diff --name-status origin/main...HEAD` 原始输出

```
A	docs/p7_w3_handoff.md
A	docs/w2_shortloop_preregistration.md
A	docs/w3_observation_protocol.md
A	docs/w3_observation_report_template.md
A	docs/w3_polymarket_ingestion_preregistration.md
A	docs/w3_spec_annex_a.md
A	evidence/p7_t01fix_issue_audit_report.md
A	evidence/p7_w2_final_sealing_report.md
A	evidence/p7_w2_shortloop_audit_report.md
A	evidence/p7_w2b_48h_observation_report.md
A	evidence/p7_w3_env_freeze.md
A	evidence/p7_w3_reprimand_explanation.md
A	scripts/audit_p7_w2_shortloop.py
A	scripts/run_p7_w2b_48h_observation.py
A	scripts/run_w3_clob_snapshot_batch.py
A	src/data_acquisition/polymarket_clob_collector.py
M	src/pipeline/stream_confluence_pipeline.py
A	src/prediction/real_emos_pipeline.py
M	src/prediction/temperature_sanitizer.py
M	src/pricing/ev_engine.py
A	src/pricing/paper_evaluation_engine.py
A	src/pricing/w3_offline_replay_analyzer.py
A	tests/unit/data_acquisition/test_polymarket_clob_collector.py
A	tests/unit/prediction/test_w2_confluence_exemptions.py
A	tests/unit/prediction/test_w2_gate_c3_sampling.py
A	tests/unit/pricing/test_paper_evaluation_engine.py
A	tests/unit/pricing/test_w2_asset_governance.py
A	tests/unit/pricing/test_w3_offline_replay_analyzer.py
```

---

## 任务 2 · 授权对齐项执行记录与 Diff 清单

### 2.1 体检报告勘误执行（`docs/audit/p7_w2_model_health_report.md`）

- **执行动作**：将 KMIA TMax 12h 评级由黄级（0.5x）改判为 🔴 **红级禁投（0.0x）**，头寸调节系数严格收缩为 0.0x，禁开任何新仓。
- **改判依据**：
  1. `docs/MODEL_SCORECARD.md` 绝对门禁：加权 ECE 超过 0.0150 触碰绝对红线（KMIA 12h 实测加权 ECE = `0.018318`）；
  2. 用户关于工单 P7-DOC-ALIGN-1 的第 3 项明确授权裁决令。
- **对应正文片段**：
  > `| 2 | **KMIA** | TMax | 12h | 0.0183 (🔴) | -0.34°F (🟢) | 0.182 (🟢) | 88.4% (🟢) | 🔴 **禁投** | 禁开新仓 (0.0x 头寸，全面禁开) | ... 终审改判红级 |`

### 2.2 运行记录作废标记（`data/paper_trading/records/kmia_tmax_12h_shortloop_record.json`）

- **执行动作**：在 JSON 文件首部注入作废归档元数据，保持原运行步骤不删除、不重跑。
- **废弃声明**：
```json
{
  "record_id": "P7-W2-REC-KMIA-001",
  "_deprecation_status": "DEPRECATED_ARCHIVED",
  "_deprecation_reason": "按工单 P7-DOC-ALIGN-1 授权执行：KMIA 12h 加权 ECE=0.018318 触碰红线（MODEL_SCORECARD 绝对门禁 > 0.0150），经用户裁决 3 终审改判为红级（禁投）。按红级规则本标的本应拒开新仓（is_signal=False，eval_status='BLOCKED_RED_HEALTH'），本纸面盘运行记录正式标记废弃归档，不作实盘参考。",
  "station_id": "KMIA",
  "market_slug": "highest-temp-miami-oct-12",
  "health_level": "RED",
  "position_multiplier": 0.0,
  ...
}
```

### 2.3 README.md 三处修正执行与 Diff

- **修订项 1**：测试基线指针同步至 PR #132 现实：锚定 `5c4a4c9`，测试用例基线更新为 `1006 passed, 10 skipped, 0 failed`；
- **修订项 2**：ADR-0012 结算源表述纠偏：由“CF6 每日气候报表”修正为“NWS WRH 官方时序表”；
- **修订项 3**：运行旗状态同步：Flag 2（6h 池化回退层）标注 `UNFLAGGED (已正式拔除)`；KMIA 12h 标注红级禁投。
- **统一 Diff 输出**：
```diff
--- a/README.md
+++ b/README.md
@@ -3,7 +3,7 @@
 > [!NOTE]
 > **[P7-DOC-RECON 文档勘误与法定状态对齐 (2026-10-10)]**：  
 > 本文档已依据工单 `P7-DOC-RECON`、`STATUS.md`、`docs/HANDOVER_P7.md` 与 `docs/ROADMAP.md` 全面重写，对齐 **Phase 7 过渡态**（主线战略由“横向扩展”全面转向“纵向落地”）。  
-> 主干代码库严格固化于 **`2975ec1`**（PR #130 合流线；前基线 `6fe386c` 为 P6 封卷线），全库测试基线保持 **`987 passed, 10 skipped, 0 failed`**。
+> 主干代码库严格固化于 **`5c4a4c9`**（PR #132 W1 合流线；前基线 `2975ec1` 为 PR #130 路线图线），全库测试基线保持 **`1006 passed, 10 skipped, 0 failed`**。
 
 > 📌 **法定长线规划与新会话交接导航**：  
 > • 项目状态总入口：[`STATUS.md`](STATUS.md)  
@@ -12,9 +12,9 @@
 > • 双城封盘九项门禁清单：[`docs/SEALING_GATE.md`](docs/SEALING_GATE.md)  
 > • 受控出域同步政策：[`docs/SYNC_POLICY.md`](docs/SYNC_POLICY.md)
 
-> 🚩 **【双重法定运行旗持续生效（下游强制带旗引用）】**：  
-> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（交易窗口加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 未达立项门槛；双城 24 格中 23 格 ECE 达标率 95.83%）；  
-> 2. `6h 池化回退层 (80 格)`：状态 `FLAGGED_POOL_PHASE_ISSUE`（晨谷方差膨胀比 1.45~1.81x，KMIA 晨谷 ECE = `0.019657` 越线 0.0100；Max Temp 缺失衰减公式依赖 METAR 实况硬截断兜底；工单 `P7-W1-POOLPHASE` 专项修复中）。  
+> 🚩 **【法定运行旗状态（对齐 main 现实）】**：  
+> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（加权 ECE = `0.018318` 越线 0.0100；经 MODEL_SCORECARD 与裁决令判为红级禁投 0.0x）；  
+> 2. `6h 池化回退层 (80 格)`：状态 **`UNFLAGGED` (已正式拔除)**（依据裁决令 `P7-FLAG2-REMOVAL-R1` / 工单 `P7-W1-POOLPHASE`，晨谷 ECE = `0.005977` 击穿 0.0100，四季膨胀比 1.0000 自洽，随 PR #132 合流入主干拔旗）。  
 > *下游引用约束*：交易盘口映射、分位数定价与风控链路在调用本格资产时，**必须显式带旗陈述，审慎收缩头寸，严禁脱旗裸跑**！
 
 ---
@@ -100,7 +100,7 @@
 
 1. **真实观测与法定结算真值协议**：
    - **IEM ASOS RMK T 组真值**：彻底废弃旧版 Wunderground，采用 ASOS 报文尾部 `T` 组编码（精确至 $0.1^\circ\text{C}$ / $0.18^\circ\text{F}$），杜绝整度截断误差；
-   - **法定结算源（ADR-0012）**：Polymarket 官方 100% 结算于 **NWS WRH CF6 每日气候报表**；
+   - **法定结算源（ADR-0012）**：Polymarket 官方 100% 结算于 **NWS WRH 官方时序表**；
    - **单调合流架构（ADR-0011 / 0013）**：IEM METAR 与 NWS 观测流在日内单调非递减（TMax）/单调非递增（TMin）合流；特报 SPECI 实施“纯温门禁、迟到不投、跳温阻断”。
 
 2. **气象预报因子与训练窗口对账（D5 裁决）**：
@@ -116,7 +116,7 @@
 4. **验证与审计体系（继承替代条款）**：
    - 原“三重验收标准”已由 **P5/P6 生产审计体系全面继承替代**；
    - **法定硬门禁**：交易窗口加权 **$\text{ECE} \le 0.0100$**（20 桶 $\times$ 5% 等宽分桶，样本数 $n < 30$ 且 $\bar{p}$ 最接近的相邻非空桶合并）；
-   - **全库测试基线**：全量 **987 项测试全绿** 护航（10 skipped, 0 failed），代码交付零回归。
+   - **全库测试基线**：全量 **1006 项测试全绿** 护航（10 skipped, 0 failed），代码交付零回归。
```

### 2.4 Wunderground 废弃脚本归档执行

- **执行动作**：执行裁决项 10，将全库现存的 Wunderground 相关采集与测试脚本物理移入隔离目录 `data/legacy-v1-suspect/`：
  - `src/data_acquisition/wunderground_scraper*` 及 `mock_wunderground.py` $\rightarrow$ `data/legacy-v1-suspect/src_data_acquisition/`；
  - `scripts/download_wunderground_*` $\rightarrow$ `data/legacy-v1-suspect/scripts/`。
- **Git 变更状态**：源码目录中对应文件已加入暂存区（Changes to be committed: deleted）。

### 2.5 MODEL_SCORECARD 补充条款执行（`docs/MODEL_SCORECARD.md`）

- **执行动作**：在 `docs/MODEL_SCORECARD.md` 末尾追加 §3 补充条款：
```markdown
## 3. 补充补充条款：未审计标的默认红级与追溯适用效力 (Supplementary Clauses)

1. **未审计标的默认红级禁投铁律**：
   - 凡属于 Active 10 宇宙或任何待扩展台站中，尚未完成 20 折 Block-CV 独立选型、尚未通过四维全量可靠度审计、或未取得正式体检定级的标的与时效格，系统一律默认判定为 🔴 红级（禁投，BLOCKED / PROHIBITED，头寸系数 S = 0.0）；
   - 严禁对未经法定审计确权的资产开立任何真实或虚拟单向新仓位。
2. **追溯适用说明 (Retroactive Application)**：
   - 本条款自 Phase 7 过渡态立项之日起具备完整追溯效力，向前完全覆盖既往已落盘但未经独立审计的 8 站 TMax 及全量 10 站 TMin（480 格）资产，杜绝无证裸跑风险。
```

### 2.6 STATUS.md 状态核查结论

- **核查事实**：
  - 当前主干与本分支中的 `STATUS.md` 均已在 2026-10-10 20:55 同步至 commit `f7a3da4`；
  - 正文已明确锚定 PR #132（`5c4a4c9`），明确记录 1006 passed 测试基线与 Flag 2 拔除状态；
  - 当前节点与分支现实完全一致。
- **判定结论**：**状态一致，无需额外文本变动。**

### 2.7 ADR-0016 与 ADR-0015 现状证据与处置方案对比

#### (1) ADR-0016 现状证据与方案对比
- **现状证据**：
  - `docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md` 第 6 行显式引用：`- **关联文档**: ADR-0015（离散校准门禁）、ADR-0016（GHCN-Daily 法定真值基线）`；
  - 全库执行 `git ls-files docs/adr/*0016*` 结果为空，物理文件不存在。
- **处置方案对比**：
  - **方案 A（推荐）：撤回悬空引用**。在 `ADR-0017` 中移除对 ADR-0016 的关联引用，改为直接指向 `ADR-0007` 及已封存的数据资产 `calib-dataset-v2.0`（Git Tag: `phase1.5-final`）。
    - *理由*：GHCN-Daily 清洗口径已在 Phase 1.5 全量闭环封卷，无独立补撰 ADR 的工程必要，修改成本低且消除了断链引用。
  - **方案 B：按历史规范补撰**。新起文档 `docs/adr/ADR-0016：GHCN-Daily 法定真值基线与历史清洗口径规范.md`，回溯补充 Phase 1.5 期间关于 GHCN-Daily 的口径决策。
    - *理由*：形式上保持编号连续与完整历史留痕。

#### (2) ADR-0015 现状证据与方案对比
- **现状证据**：
  - `docs/adr/` 下并存两个文件：
    1. `ADR-0015：废除高斯EMOS气候方差加法项、确立物理方差底座与离散校准门禁.md`（修改于 2026-09-23 13:28:20）
    2. `ADR-0015.md`（修改于 2026-09-23 14:08:22）
  - 两者 unified diff 证实：短文件名版本系工程师在长文件名版本基础上的最新增补提交，多出了整整 15 行的“**## 3. 第二轮修复令增补：方差地板实证回归与 KSFO $d=0$ 物理成因 (R-3 令归档)**”。
- **处置方案对比**：
  - **方案 A（推荐）：合并保留中文标准长文件名**。将 `ADR-0015.md` 中的 §3 无损合入 `ADR-0015：废除高斯EMOS气候方差加法项、确立物理方差底座与离散校准门禁.md` 末尾，随后安全删除短名文件 `ADR-0015.md`。
    - *理由*：符合本仓库 ADR 均采用“ADR-xxxx：描述”长文件名的命名规范，同时完整保留 R-3 令关于方差重标与 KSFO 微气候的珍贵科学分析。
  - **方案 B：主从关系声明**。保留两个物理文件，在短名文件首部声明其为长名文件的“附录/第二轮增补案”。
    - *理由*：不改动历史提交的文件索引。
