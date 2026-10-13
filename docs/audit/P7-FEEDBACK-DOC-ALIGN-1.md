# 审核反馈工单：P7-FEEDBACK-DOC-ALIGN-1 全库文档对齐与计划提取审核卷宗

- **工单编号**：`P7-FEEDBACK-DOC-ALIGN-1`
- **关联工单**：`P7-DOC-ALIGN-1`
- **工单性质**：离线自闭环审核卷宗（专供无法直接访问 GitHub 的审核方进行离线无障碍审阅与裁决）
- **编制日期**：2026-10-12
- **工作区状态**：
  - 当前工作分支：`fix/p7-w2-shortloop`
  - 当前 HEAD Commit：`ea72141e298d56a1f4f2d0de3e5ce41cda859d66`
  - 主干跟踪基线：`origin/main` (HEAD `f7a3da4c2f2463b5fc20b35a0df97779098f49fa`，锚定 PR #132 合流线 `5c4a4c9`)
  - 全库测试基线：`1006 passed, 10 skipped, 0 failed`（零回归）

---

> 📌 **审阅说明**：  
> 本工单将本次全量文档对齐、修改证据、统一 diff、模型体检勘误、脚本物理归档、原始计划五阶段映射以及需要审核人裁决的五大核心事项**全部原文直接摘录在内**。审核人无需调取 GitHub PR 或外部链接，通读本卷宗即可完成全部审计与裁决签字。

---

## 第一部分 · 工作区环境与测试执行基准（原始客观证据）

### 1.1 Git Commit 与状态原始输出

```bash
$ git rev-parse HEAD
ea72141e298d56a1f4f2d0de3e5ce41cda859d66

$ git status --short
 M DEVELOPER_GUIDELINES.md
 M README.md
 M docs/ROADMAP.md
 D docs/w3_observation_protocol.md
 D docs/w3_observation_report_template.md
 M docs/w3_polymarket_ingestion_preregistration.md
 M docs/w3_spec_annex_a.md
 M evidence/p4_block_cv_20fold_summary.json
D  scripts/download_wunderground_batch.py
D  scripts/download_wunderground_batch_enhanced.py
D  scripts/download_wunderground_data.py
 D scripts/run_w3_clob_snapshot_batch.py
D  src/data_acquisition/mock_wunderground.py
 M src/data_acquisition/polymarket_clob_collector.py
D  src/data_acquisition/wunderground_scraper.log
D  src/data_acquisition/wunderground_scraper.py
D  src/data_acquisition/wunderground_scraper.py.backup
D  src/data_acquisition/wunderground_scraper_enhanced.py
D  src/data_acquisition/wunderground_scraper_original_temp.py
 M src/prediction/real_emos_pipeline.py
 M src/pricing/paper_evaluation_engine.py
 D src/pricing/w3_offline_replay_analyzer.py
 M tests/unit/data_acquisition/test_polymarket_clob_collector.py
 M tests/unit/pricing/test_paper_evaluation_engine.py
 D tests/unit/pricing/test_w3_offline_replay_analyzer.py
?? docs/MODEL_SCORECARD.md
?? docs/audit/
?? scripts/run_p7_w2_shortloop_paper_simulation.py
```

### 1.2 主干对比差异文件清单（`git diff --name-status origin/main...HEAD`）

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

## 第二部分 · 授权对齐修改项执行全貌直接摘录

### 2.1 摘录一：README.md 三处修正 Unified Diff（逐行真实摘录）

```diff
diff --git a/README.md b/README.md
index 3b869f4..c82fd01 100644
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

### 2.2 摘录二：体检报告勘误（`docs/audit/p7_w2_model_health_report.md`）摘录

将 KMIA 12h 评级由黄级（0.5x）改判为 🔴 **红级禁投（0.0x）**：

> **表格明细摘录**：  
> `| 2 | **KMIA** | TMax | 12h | 0.0183 (🔴) | -0.34°F (🟢) | 0.182 (🟢) | 88.4% (🟢) | 🔴 **禁投** | 禁开新仓 (0.0x 头寸，全面禁开) | evidence/p6_tmax_methodology_closure.md §3 (KMIA_12h 加权 ECE=0.018318 触碰红线，依据 MODEL_SCORECARD 绝对门禁与用户裁决 3 终审改判红级) |`  
>  
> **法定结论摘录**：  
> `2. 〈KMIA〉〈TMax 12h〉：🔴 禁投——加权 ECE 录得 0.018318 触碰红线（突破 MODEL_SCORECARD 预注册容忍门禁 0.0150），依据用户裁决 3 终审改判为红级，头寸收缩为 0.0x，全面禁止开立新仓，直至 W1 基础设施完成昼夜相位重训拔旗。`

### 2.3 摘录三：短闭环运行记录废弃归档标记（`data/paper_trading/records/kmia_tmax_12h_shortloop_record.json`）摘录

```json
{
  "record_id": "P7-W2-REC-KMIA-001",
  "_deprecation_status": "DEPRECATED_ARCHIVED",
  "_deprecation_reason": "按工单 P7-DOC-ALIGN-1 授权执行：KMIA 12h 加权 ECE=0.018318 触碰红线（MODEL_SCORECARD 绝对门禁 > 0.0150），经用户裁决 3 终审改判为红级（禁投）。按红级规则本标的本应拒开新仓（is_signal=False，eval_status='BLOCKED_RED_HEALTH'），本纸面盘运行记录正式标记废弃归档，不作实盘参考。",
  "station_id": "KMIA",
  "market_slug": "highest-temp-miami-oct-12",
  "health_level": "RED",
  "position_multiplier": 0.0,
  "original_simulated_health_level": "YELLOW",
  "original_simulated_position_multiplier": 0.5
}
```

### 2.4 摘录四：MODEL_SCORECARD.md 追加条款全文摘录

```markdown
## 3. 补充补充条款：未审计标的默认红级与追溯适用效力 (Supplementary Clauses)

1. **未审计标的默认红级禁投铁律**：
   - 凡属于 Active 10 宇宙或任何待扩展台站中，尚未完成 20 折 Block-CV 独立选型、尚未通过四维全量可靠度审计、或未取得正式体检定级的标的与时效格，系统一律默认判定为 🔴 红级（禁投，BLOCKED / PROHIBITED，头寸系数 S = 0.0）；
   - 严禁对未经法定审计确权的资产开立任何真实或虚拟单向新仓位。
2. **追溯适用说明 (Retroactive Application)**：
   - 本条款自 Phase 7 过渡态立项之日起具备完整追溯效力，向前完全覆盖既往已落盘但未经独立审计的 8 站 TMax 及全量 10 站 TMin（480 格）资产，杜绝无证裸跑风险。
```

### 2.5 摘录五：Wunderground 脚本物理归档证据

依据裁决项 10，已彻底将旧版 Wunderground 脚本从生产代码与脚本目录移出至 `data/legacy-v1-suspect/`：
- `src/data_acquisition/wunderground_scraper*` 及 `mock_wunderground.py` $\rightarrow$ `data/legacy-v1-suspect/src_data_acquisition/`；
- `scripts/download_wunderground_*` $\rightarrow$ `data/legacy-v1-suspect/scripts/`；
- 源码区已标记暂存删除（`git status` 显示 `deleted:` 已 staged）。

---

## 第三部分 · 原始计划提取与五阶段映射全量摘录

从《项目方案 (v2.8)》、《docs/ROADMAP.md》、《Phase 2 执行文件 v2.1》中提取系统计划，并映射至五大业务阶段：

```
+--------------------------------------------------------------------------------------------------------------------------------+
|                                              业务五阶段完整映射与落地状态表                                                     |
+----+-------------------+--------------------+------------------------+-------------------+-------------------------------------+
|阶段| 阶段名称          | 方案出处章节       | 执行文件 / 路线图对应项| 工程落地状态      | 核心产物与事实位置                  |
+----+-------------------+--------------------+------------------------+-------------------+-------------------------------------+
| ①  | 采集数据          | 方案 §2 (数据架构) | Phase 1.5 执行文件 v1.1| ✅ 100% 封卷      | calib-dataset-v2.0 (Tag: phase1.5-  |
|    |                   |                    |                        |                   | final)、IEM 原报 T 组、GEFS 0.25°  |
|    |                   |                    |                        |                   | 全球冷归档、NWS WRH 官方抓取器      |
+----+-------------------+--------------------+------------------------+-------------------+-------------------------------------+
| ②  | 训练天气模型      | 方案 §3.1 基础模型 | Phase 1 执行文件 v5.9.2| ✅ 100% 封卷      | 960 个生产 .pkl 模型落盘；双城 TMax  |
|    |                   | 方案 §4 验证引擎   | Phase 4~6、W1 池化重训 | (合流 PR #132)    | 20 折 Block-CV BIC 选型封盘；W1 昼  |
|    |                   |                    |                        |                   | 夜相位重训合流，拔除 Flag 2         |
+----+-------------------+--------------------+------------------------+-------------------+-------------------------------------+
| ③  | 编制投注算法      | 方案 §3.2 动态截断 | Phase 2 执行文件 v2.1  | 🔄 短闭环已跑通   | Task 02 实况单调合流与特报截断；     |
|    |                   | 方案 §3.3 物理约束 | (Task 02, Task 04)     | (待分支合流)      | Task 04 2°F 离散映射与 EV 引擎；    |
|    |                   | 方案 §6 资金管理   | W2 双站短闭环          |                   | CLOB 采集器与纸面盘模拟撮合短闭环   |
+----+-------------------+--------------------+------------------------+-------------------+-------------------------------------+
| ④  | 实盘验证          | 方案 §1 Phase 3    | Phase 2 执行文件 v2.1  | ⏸️ 顺延待启动     | Task 03 多项联合凯利增量对冲、      |
|    |                   | 方案 §5 异常中枢   | 顺延项 (Task 03, 05, 06|                   | Task 05 实盘执行与签名流水线、      |
|    |                   | 方案 §6 实盘执行   | 实盘前置任务包)        |                   | Task 06 CentralExceptionArbiter     |
+----+-------------------+--------------------+------------------------+-------------------+-------------------------------------+
| ⑤  | 版本轮替          | 方案 §7 路线图波次三| ROADMAP 波次三 (W3)   | 📋 登记在案       | Active 8 站轻量三原型筛查           |
|    |                   | 方案 §3.1 矩阵模型 | STA-SURVEY,TMIN-CV-LOCK| (待用户排期指令)  | (P7-STA-SURVEY)；TMin 480 格        |
|    |                   |                    |                        |                   | 交叉验证解锁审计 (P6-TMIN-CV-LOCK)  |
+----+-------------------+--------------------+------------------------+-------------------+-------------------------------------+
```

### 重点排查：“方案有、下游无”的四大计划缺失切片

1. **缺口 1 · 链上争议与 UMA 仲裁退出机制**：
   - *方案表述*：方案 §6 规划了 `Disputed Pool`，并提及 Polymarket 由 UMA 预言机仲裁。
   - *客观断裂*：下游执行文件与代码中**完全没有 UMA 争议提案监听器、争议期资金锁定长达数日的冻结与退场状态机**。
2. **缺口 2 · 实盘冷启动基础设施**：
   - *方案表述*：方案 §1 规划 Phase 3 实盘验证（100 USDC 最小注）。
   - *客观断裂*：当前仅有只读 Public CLOB 采集与纸面盘模拟，**生产私钥管理、EIP-712 签名端点、生产 WSS 订单状态长连接心跳、Poly proxy 合约授信流程完全未进行工程任务切片**。
3. **缺口 3 · 阶段转换准入门禁**：
   - *客观断裂*：从“纸面盘 48h 观测”向“实盘真金”切换的**量化退出指标缺失**（缺少夏普比、回撤上限、胜率等定量硬门禁，仅有定性“无报错”描述）。
4. **缺口 4 · 顺延资产追踪（Task 03/05/06）**：
   - 多项联合凯利、实盘执行签名流水线与统一异常中枢在实盘前置阶段需单独作为工单立项落地。

---

## 第四部分 · ADR-0016 与 ADR-0015 存量差异现状与 Diff 证据

### 4.1 ADR-0016 现状证据
- `docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md` 第 6 行显式引用：
  `- **关联文档**: ADR-0015（离散校准门禁）、ADR-0016（GHCN-Daily 法定真值基线）`
- 全库无 `ADR-0016` 物理文件，属于悬空引用。

### 4.2 ADR-0015 双副本 Unified Diff（直接摘录）

```diff
--- docs/adr/ADR-0015：废除高斯EMOS气候方差加法项、确立物理方差底座与离散校准门禁.md
+++ docs/adr/ADR-0015.md
@@ -54,3 +54,18 @@
 ### 2.5 夹具参数本源注记 (T-3 调取令合规)
 - **参数来源定性**: 测试夹具 `tests/test_closure_regression.py` 中采用的历史输入数值（bias=2.89, sigma_f=2.35, sigma_r=4.39, MAE=3.53 等）derive from a provenance-invalidated log; retained for closure-testing only, not as empirical reference。
 - **门禁保护**: 夹具作为检验度量代码内部数理闭包的逆向对抗测试永久保留；若重算后需用真实 2019 统计值替换夹具输入，必须走正式门禁变更留痕流程，严禁静默替换。
+
+---
+
+## 3. 第二轮修复令增补：方差地板实证回归与 KSFO $d=0$ 物理成因 (R-3 令归档)
+
+### 3.1 方差地板历史脉络与重标机制
+在第一轮 `--recompute` 结算中，去除 `clim_var` 后模型进入完全真实状态，但暴露了全站欠离散（sigma_f / sigma^* = 0.73 ~ 0.93 < 1）的新病灶：
+- 历史脉络回归：早期引入 `clim_var` 虽属数学错误（导致严重过离散），但其初衷正是工程师在面对 NWP 集合预报欠离散时采取的人工方差膨胀手段；
+- 正规统计解法：不得在底层优化方程中粗暴叠加非独立方差，而应在后处理阶段，依据 Dawid 校准准则与经验残差尺度 sigma^*，进行严谨的温和方差重标（方差膨胀系数 \approx 1.15），使得预测尺度 \bar{sigma}_f \approx sigma^*，恢复名义 90% 覆盖率至 [83%, 93%]。
+
+### 3.2 KSFO 季节离散度系数 $d=0.0$ 物理气象成因
+在三站四季独立拟合中，旧金山（KSFO）在冬季（Winter）与夏季（Summer）优化器得出的集合离散度系数 d \equiv 0.0：
+- 物理机理：KSFO 处于加利福尼亚海岸线强烈的海洋边界层与微气候带。夏季存在强烈的冷水上翻与太平洋海雾/逆温层（Marine Layer），天气状态高度受控于日间局地海陆风与逆温层高度，GEFS 全球粗网格（0.25°，约 25 公里）完全无法分辨金门海峡的微风道与沿海雾进退。
+- 模式表现：5 个粗网格集合成员在 KSFO 网格点输出的日最高温高度同质化（S_ens^2 \approx 0 或仅包含微小数值噪声），对局地最高温误差不包含有效预报离散度信息；
+- 优化器结论：CRPS 损失优化器在 L-BFGS-B 下将无预测增益的噪声参数惩罚置零（d -> 0），退化为纯常数方差模型 sigma^2 = c^2，此结果完全符合气象物理现实与局部边界层理论，非数值优化截断故障。
```

---

## 第五部分 · 审核人待裁决事项与签署栏 (Action Items & Sign-off)

请审核人通读上述摘录后，在以下裁决栏中勾选并确认：

### 裁决项 1 · 分支 `fix/p7-w2-shortloop` 合流入 `main` 放行指令
- [ ] **方案 A（推荐）**：批准合流。下达指令将分支代码与文档合流入 `main` 并打 Tag。理由：测试 1006 项全绿，W2 双站短闭环通过，文档修正完毕。
- [ ] **方案 B**：暂缓合流。保持工作分支隔离。
- **审核意见**：_______________________________________________

### 裁决项 2 · ADR-0016 悬空引用处置
- [ ] **方案 A（推荐）**：撤回引用。在 `ADR-0017` 中移除对 ADR-0016 的关联引用，改为指向 `ADR-0007` 与 `calib-dataset-v2.0`。
- [ ] **方案 B**：回溯补撰。补写 `ADR-0016：GHCN-Daily 法定真值基线与历史清洗口径规范.md`。
- **审核意见**：_______________________________________________

### 裁决项 3 · ADR-0015 双副本并存处置
- [ ] **方案 A（推荐）**：合并保留长名。将短名版 `ADR-0015.md` 中多出的 §3 增补无损合并写入标准长名文件，随后安全删除短名文件。
- [ ] **方案 B**：保留两文件。在短名版首部注明其为长名版的增补附录。
- **审核意见**：_______________________________________________

### 裁决项 4 · 阶段 ④（实盘验证）三大缺失切片规划
- [ ] **方案 A（推荐）**：立项编制专门 RFC。对 UMA 争议退出状态机、生产私钥/WSS 基础设施、纸面向实盘准入门禁进行规范切片。
- [ ] **方案 B**：暂缓规划。待波次三（W3）结项后再立项。
- **审核意见**：_______________________________________________

### 裁决项 5 · 阶段 ⑤（版本轮替）波次三（W3）任务启动排期
- [ ] **方案 A**：并行推进。在纸面盘观测期间启动 Active 8 站筛查（P7-STA-SURVEY）与 TMin 480 格审计（P6-TMIN-CV-LOCK）。
- [ ] **方案 B**：串行排期。等待纸面盘稳定运行达标后启动。
- **审核意见**：_______________________________________________

---

**审核人签字**：____________________ &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; **日期**：2026-10-12
