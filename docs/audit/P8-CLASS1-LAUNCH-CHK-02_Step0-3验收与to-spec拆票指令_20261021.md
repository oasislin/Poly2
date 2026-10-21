# P8-CLASS1-LAUNCH-CHK-02 · Step 0–3 交付验收核验单与 Task 04 to-spec 拆票指令

> **日期**：2026-10-21
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-02`（父工单下第 2 号核验单，CHK-01 已完成并入库 commit `f187881`）
> **复核对象**：开发端 Step 0–3 交付 = `P8-CLASS1-LAUNCH-INVENTORY_交易模块现状只读盘点表_20261021.md` + `P8-CLASS1-LAUNCH-PROPOSAL_第一类投注定价算法方案书_20261021.md` + handoff §8 审核注记
> **复核人**：技术审核 Agent（只读复核；git 证据以开发端原样输出为准，本地同步副本非 git 仓库）
> **判定纪律**：原始观测值 vs 判定阈值两步分离；结论由机械比较得出。
> **追加（2026-10-21 用户补充裁定）**：物理模型参数 → 投注算法消费契约，见 §六，并入 Step 4 执行。

---

## 一、 逐项验收结论

| # | 交付项 | 开发端原始观测值 / 证据 | 判定阈值 | 结论 |
| :-- | :-- | :-- | :-- | :-- |
| 1 | Step 0 · git 基线 | `git log`：`f187881 (HEAD->main)`，e421ac8 = origin/main；`git status`：ahead 1 commit、仅两件未跟踪文档；commit f187881 仅含 handoff+CHK-01 | 基线与 CHK-01 §二-8 要求一致 | **通过**（git 证据以开发端为准） |
| 2 | Step 0 · 主树交易模块状态 | `src/bankroll`、`src/execution`：No such file or directory；`src/risk`：仅 `__init__.py`+`stream_watchdog.py` | 与 R-16 方案 B 归档一致 | **通过** |
| 3 | Step 0 · 测试状态 | 现役 `tests/unit/prediction tests/unit/risk`：`113 passed in 2.33s`；归档测试 collect 期 20 模块 `ModuleNotFoundError`（退出码 2） | 现役全绿、归档零污染 | **通过** |
| 4 | Step 1 · 盘点表 | 归档 5 域 17+ 模块 + 现役 3 模块，接口/依赖/测试/重建建议逐项成表 | 覆盖 CHK-01 指令全部对象 | **通过** |
| 5 | Step 2 · 方案书设计 | Q1 四连续量得分+ψ 软折减+τ_conf 唯一并入 C_max（DR-2026-1014-02）+σ_adj；Q7 双轨矩阵+0.95 论证+三不混用；P7-ALGO-2 对账 5 项回执；7 项[待标定/F-2 LOCKED]；ECE≤0.0100 三源溯源（v2.1 §3.1/§4、w1 预注册 §4.1、归档脚本行 71/238） | 满足 CHK-01 §四-Step 2 全部要求 | **设计部分通过** |
| 6 | Step 2 · 工单拆分 | 仅 3 个 Ticket（pricing/bankroll/simulation 各 1） | 用户裁定：粒度不足，须 to-spec 重拆，下限 ≥20（本单 §四） | **不通过（发回重拆）** |
| 7 | handoff 审核注记 | §8 以版本标注形式补充修正-1/2/3 与裁决-R1/R2，未改写既有正文 | 与 CHK-01 §三要求一致 | **通过** |

---

## 二、 方案书待决问题清单（to-spec ② grilling 必答，本轮仅列项不定案）

- **G-1（双重计权）**：S_conf 的输入含 `x_s=|s_oos−1|`，而 `τ_conf = ψ(s_oos)·S_conf` 又对 s_oos 折减一次——同源信号乘法叠乘是否构成双重惩罚？须裁：ψ 吸收 s_oos 维度（S_conf 剔除 x_s）或成文论证叠乘保守性。
- **G-2（双处理边界）**：σ_adj 外展（扩大定价不确定集/探针区间）与 ψ 预算折减（压缩 C_max）对同一欠自信信号双管齐下；须裁明分工（前者管区间诚实性，后者管风险敞口）并写入方案书。
- **G-3（数据源）**：metrics CSV 无覆盖率列；`x_cov` 的 Cov_90 须取 `p4blind_v2r01_comparison.csv` 的 `v1_coverage_90` 列（已核存在，KORD_12h=0.936986/KORD_18h=0.909589），方案书注明数据源；并厘清与 G5 带 [0.83,0.95] 的关系。
- **G-4（Task 边界）**：提议的「Task 04 · 联合凯利与执行定价层算法重构与纸面盘落地」与 v2.1 既有 Task 04（2°F 映射+动态 EV）、Task 07（只读纸面盘）范围不一致；to-spec ① 文档审读须产出冲突清单，确认重定义 Task 04 或新建 Task，经用户确认。
- **G-5（表述口径）**：「KMIA 预算压降至 40%~60%」依赖 ψ_floor/λ 参考值（[F-2 LOCKED]），方案书须标注为工程预期而非承诺值。

---

## 三、 Step 0–3 验收结论

**Step 0 / Step 1 / handoff 注记：通过。**
**Step 2 方案书：设计、对账、溯源部分通过；工单拆分部分不通过**——按用户裁定（2026-10-21）执行 §四 to-spec 重拆流程，重拆结果经审核与用户确认后再行编码授权。

---

## 四、 用户裁定与 to-spec 拆票指令（开发端执行，Step 4）

### 4.1 用户裁定（2026-10-21，记录在案）
第一类投注/定价层为大型工程，现 3 个 Ticket 拆分粒度不足；裁定按模块/细节算法解耦拆分，**下限 ≥20 个 Ticket**，且须走 to-spec 标准流程（`docs/spec-update-process.md`），不凭拍脑袋编号。

### 4.2 开发端执行指令（按 docs/spec-update-process.md 完整四步）

**① 文档审读**：通读 方案书 + `Phase 2 执行文件 v2.1` + `P7-ALGO-2 规格书`（含裁决记录/判决书），产出冲突清单（逐条：覆盖/保留/待确认；必含 G-4 Task 边界对账），呈用户确认后再进入 ②。

**② grill-with-docs**：逐轮 frontier 提问（每轮附推荐答案，一轮问完等用户答复），必答 G-1~G-6（G-6 见 §六）；涉及架构/口径的决策产出 ADR（`docs/adr/ADRNNN-标题.md`），术语变更更新术语表；直至设计树 frontier 清空。

**③ to-spec / to-tickets + 本地文档更新**：
- 按附录 A 模板合成 spec（Problem/Solution/User Stories/Implementation Decisions/Testing Decisions/Out of Scope）；
- 按**垂直切片 + 模块解耦**拆分 tickets：每票独立可演示、声明 Blocked by、无依赖票进入 frontier；**粒度以模块/细节算法为单元（如：Q7 双轨切分、S_conf 得分模块、ψ 曲线、σ_adj、C_max 折剪集成、S3 布尔门禁、保护价探针、残差状态机精简、四桶账务 B_eff 统一、多项凯利 M-1 重构、两维风控 z 化、纸面盘装配、资金守恒观测、标定脚手架、配置/注册、测试基建等），下限 20 票**；
- 命名强制全拼前缀：`Spec: Phase 2 Task YY - <描述>`、`Phase 2 Task YY - Ticket ZZ: <type>(<scope>): <描述>`（Task 号以 ① 冲突清单裁决为准）；
- **先呈现拆分方案（票单+依赖关系）给用户确认，批准后再生成 gh 发布命令**；
- 发布命令交**用户执行**（agent 不代跑 gh），用户反馈 issue 编号后回填本地文档；
- 同步更新 `specs/` 相关文档（只更新未完成任务描述，已完成内容零改动）。

**④ 冻结规则校验**：`git diff` 确认不含对已完成任务内容的改动；设计文档更新一律版本标注，不重写既有内容。

### 4.3 交付物（Step 4）
1. 冲突清单（①）→ 2. grilling 问答记录 + ADR/术语表（②）→ 3. spec 草案 + ticket 拆分方案（③，先呈确认）→ 4. gh 发布命令（用户执行）→ 5. issue 编号回填 + specs/ 同步 → 6. 冻结校验报告。

---

## 五、 红线重申（全程有效）

不重训 EMOS、不改 a/b/c/d 与 c_train、不写回 pkl/manifest；不改冻结 V1 结算与 2019 原始数组；未授权不编码、不落定值（权重/曲线/σ_adj 系数挂 F-2 锁）；不代跑 gh；不 push（push 仅凭用户明确指令）。

---

## 六、 用户补充裁定（追加）· 物理模型参数 → 投注算法消费契约

### 6.1 用户裁定要点（2026-10-21，原文要点记录）

- 天气物理模型分布与投注算法**解耦**，物理模型中的参数需被投注算法**消费**；
- 上一版文档对「如何消费」说明不清晰；且**抽检所用模型已更新**，须对参数消费内容重新 check 并形成**新决议**；
- 依据 **V2.0 落盘（2019 数据盲测结果）**逐项考虑：绝大部分参数可能决定**不同时间、不同城市预测模型的可用程度**，或决定**是否需要补偿或调整**。

### 6.2 V2R01 落盘参数清单（22 格 × 参数，供逐项裁决）

**A. `evidence/audit_v2/p4blind_v2r01_metrics.csv` 全列**：`n, s_oos, rho1, neff, finf_lo, finf_hi, finf_in, fstd_lo, fstd_hi, fstd_in, ks_stat, ks_p, cvm_stat, cvm_p, reject_uniform, ece_2f, ece_7bin_v1, ece_bins10, ece_bins20, ece_range, pit_mean, pit_var, max_prob_dev, ece_eqfreq_q10, pit_hist_b01…b10`

**B. `evidence/audit_v2/p4blind_v2r01_comparison.csv` 全列**：`v1_s_oos, v1_s_oos_pass, v2_s_oos, v2_neff, v2_finf_lo/hi/in, v2_fstd_lo/hi/in, s_oos_rescued_by_finf/fstd, v1_ks_stat/p, v1_ks_pass, v2_cvm_stat/p, v2_reject_uniform, uniform_rescued, v1_ece_7bin, v1_ece_pass, v2_ece_2f, v2_ece_range, v1_pit_mean, v1_pit_mean_pass, v2_pit_var, v1_coverage_90, v1_coverage_90_pass, v1_all_gates_pass`

**C. 物理模型层输出（未入 CSV，须从 registry/manifest 与逐日数组导出）**：`mu_calib`（位置）、`sig_eff`（离散度，含 c_train 站×季膨胀因子）、分布族（KORD：冬/春/秋 JSU + 夏 Gaussian；KMIA：四季 JSU）及族参数（Johnson SU γ/δ/ξ/λ 或 Gaussian σ）、2°F 离散档位概率 `p_j`（`DiscreteBinEngine` 输出）。

### 6.3 G-6 待决问题（grilling 必答，产出 ADR：物理参数消费契约）

1. **逐参数用途裁决**：§6.2 A/B/C 逐参数裁定——投注算法消费（具体用途）/ 不消费（理由）/ [待标定]；
2. **按格组织**：参数按 **time×city 格（22 格）**组织消费，禁止以全局均值掩盖格级差异；明确样本量 n≈365 下参数的抽样不确定性（如 N_eff/rho1 影响 F 带宽度）在投注层如何体现；
3. **可用程度规则**：每格「是否可投 / 可用置信级别 / 对应仓位档」的判定规则（F 带内外、ECE、KS/CvM、coverage、pit_var 的组合规则），对应「不同时间/城市可用程度」诉求；
4. **补偿/调整规则**：欠自信（s_oos>1，如 KMIA 30/48/54h）σ_adj 外展与 ψ 折减；**过自信/过度离散（s_oos<1，如 KORD 36/60h 0.818~0.833）是否处置、如何处置或明确不处置的理由**；不重训前提下的交易侧处置边界；
5. **模型版本/陈旧性契约**：抽检模型已更新 → 参数须**绑定模型版本戳**（pkl/manifest 校验和），投注层消费前校验版本一致性；模型更新后参数**重测的触发条件与流程**成文；
6. **数据源与再测路径**：参数表存储位置（evidence CSV / registry / 逐日数组）、由谁何时重测（评估脚本）、投注层读取路径；
7. **与 Q1/Q7 归属切分**：Q1 四连续量（s_oos/ECE/Cov/PIT）与 Q7 的 σ_eff/gaussian_proxy 均属本契约消费子集，G-6 裁决不得与 Q1 得分结构、Q7 双轨分工自相矛盾。

### 6.4 执行要求（并入 Step 4）

- **① 文档审读增补**：`src/modeling/registry.py`（manifest 结构与版本戳）、`scripts/evaluate_p4_2019_settlement.py`（参数导出路径）、`evidence/audit_v2` 两 CSV 全列；
- **② grilling 必答 G-6**，产出 ADR（物理参数消费契约）；
- **③ 拆票须含独立 tickets**：参数契约/逐格参数表/版本戳校验/重测触发；
- **交付物增补**：G-6 裁决记录 + ADR + **参数消费矩阵**（参数 × 消费/不消费 × 用途 × 数据源 × 版本约束 × 待标定标记）。
