# P5-AUDIT-SCOPE: 模型覆盖范围与检验范围对账报告

> **工单编号**: `P5-AUDIT-SCOPE`  
> **任务性质**: 纯取证与备忘（零代码改动、零重跑拟合、不启动 TMin 审计）  
> **核查基准**: `specs/preregistration-p4-active10-retrain.md`（P4 预注册规格书第 4.2 节）  
> **生成时间**: 2026-10-09  

---

## 事项 1：模型训练覆盖范围核实对账表

依据设计文档、数据管道、拟合代码及磁盘模型工件进行逐项物理取证，对账矩阵如下：

| 目标变量 | 设计文档条款 (specs/) | 数据管道 (GHCN/GEFS) | 拟合实现 (Fitting Pipeline) | 逐折工件 (cv_fold_*) | 生产模型资产 (data/models/) | 可靠度审计覆盖 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TMax** | **存在**<br>[`specs/preregistration-p4-active10-retrain.md:158`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/specs/preregistration-p4-active10-retrain.md#L158)<br>“960 完整连续全网格（10 台站 × 4 季 × 2 标的(Max/Min) × 12 提前期）” | **存在**<br>[`src/data_acquisition/gefs_fetcher.py:201`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_acquisition/gefs_fetcher.py#L201)<br>[`src/data_processing/slicer.py:237`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_processing/slicer.py#L237)<br>支持 `tmax_2m`, `tmax_f`, METAR/SPECI | **存在**<br>[`scripts/retrain_p4_active10_matrix.py:442`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/retrain_p4_active10_matrix.py#L442)<br>[`tests/unit/modeling/test_p4_block_cv_20fold.py:71`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/modeling/test_p4_block_cv_20fold.py#L71)<br>支持 960 格与 20 折 Block-CV | **存在**<br>[`evidence/cv_fold_0_model.json:3`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/cv_fold_0_model.json#L3)<br>20/20 折存在，分布族为 `johnsonsu`，完备导出形态参数 | **存在**<br>[`data/models/*.pkl`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/data/models/)<br>**480 个 Max 模型** 完备落盘入库 | **已覆盖**<br>[`evidence/p4_audit_reliability_v13_summary.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_audit_reliability_v13_summary.json)<br>覆盖 KORD 站 18h TMax 全量 13,740 验证日 |
| **TMin** | **存在**<br>[`specs/preregistration-p4-active10-retrain.md:158`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/specs/preregistration-p4-active10-retrain.md#L158)<br>“960 完整连续全网格（10 台站 × 4 季 × 2 标的(Max/Min) × 12 提前期）” | **存在**<br>[`src/data_acquisition/gefs_fetcher.py:201`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_acquisition/gefs_fetcher.py#L201)<br>[`src/data_processing/slicer.py:239`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_processing/slicer.py#L239)<br>支持 `tmin_2m`, `tmin_f`, METAR/SPECI | **存在 (全矩阵网格)**<br>[`scripts/retrain_p4_active10_matrix.py:442`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/retrain_p4_active10_matrix.py#L442)<br>`for var in ["Max", "Min"]:` 遍历拟合全部 Min 模型 | **不存在 (Block-CV 缺口)**<br>[`tests/unit/modeling/test_p4_block_cv_20fold.py:71`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/modeling/test_p4_block_cv_20fold.py#L71)<br>CV 脚本硬编码 `variable="tmax"`，无 TMin 逐折工件 | **存在**<br>[`data/models/*.pkl`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/data/models/)<br>**480 个 Min 模型** 完备落盘入库 | **完全未覆盖 (0%)**<br>除门禁缺列防御外，**全库无任何 TMin 可靠度审计、ECE 或双尾检验工件** |

### 查证结论核心总结：
1. **用户预判核验**：“TMax 与 TMin 均已训练”——**该预判在【全矩阵生产模型资产层】完全成立**！`data/models/` 目录下实测存在 480 个 Min 模型 `.pkl` 文件（如 `KMIA_Autumn_Min_lead42h.pkl` 等），与 480 个 Max 模型严格构成 960 完整全网格；
2. **缺口定责**：但在【20 轮 30-Day Block-CV 重采样层】，既有脚本硬编码了 `variable="tmax"`，导致 Block-CV 阶段**从未对 TMin 跑过 20 折交叉验证**，亦未生成任何 `cv_fold_*_model.json` (TMin) 或 `cv_fold_*_predictions.parquet` (TMin)。

---

## 事项 2：检验范围缺口确认声明

### 1. 当前 v1.3 审计样本覆盖口径核实（直接回答用户第一问）
- **核实问题**: 当前 v1.3 审计的 13,740 验证日中，TMax 是全部站点还是部分站点？
- **物理客观事实**:
  - 当前 13,740 验证日**仅覆盖 KORD 单一站点（芝加哥奥黑尔机场）**！
  - 溯源证据：[`tests/unit/modeling/test_p4_block_cv_20fold.py:54`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/modeling/test_p4_block_cv_20fold.py#L54) 硬编码 `station = "KORD"`，20 轮 Block-CV 每折约 687 验证日，累加得到池化 13,740 站·日，全部为 KORD 单站数据。
- **与全量训练范围的比例关系**:
  - **台站覆盖比**: $1 / 10 = \mathbf{10.0\%}$（Active 10 宇宙中，KMIA, KSFO, KDEN, KATL, KDAL, KHOU, KPHX, KLAS, KSEA 9 站尚未经过 20 折审计）；
  - **时效覆盖比**: $1 / 12 = \mathbf{8.33\%}$（仅 18h 单一时效，其余 11 提前期未审计）；
  - **标的覆盖比**: $1 / 2 = \mathbf{50.0\%}$（仅 TMax，TMin 为 0%）；
  - **全矩阵网格覆盖比**: $4 / 960 = \mathbf{0.417\%}$（仅覆盖了 KORD 站 18h TMax 四季网格）。

### 2. TMin 零可靠度审计证据清单（直接回答用户第二问）
- **证据 1 (输入端无数据)**：审计主脚本 [`scripts/audit_p4_reliability_v13.py:90`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/audit_p4_reliability_v13.py#L90) 仅读取 `cv_fold_{r}_predictions.parquet`，其中只有 `obs_tmax_f`，无任何最低温输入通道；
- **证据 2 (产物端无指标)**：全库 `evidence/` 目录下所有已归档审计报告（v1.1、v1.2、v1.3）中，无任何关于 TMin 的 ECE、Brier 分数、Wilson 覆盖率或双尾泊松记录；
- **证据 3 (门禁端反证)**：全库唯一出现 `obs_tmin_f` 的测试为 [`tests/unit/verification/test_p5_unified_spec_requirements.py:71`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/verification/test_p5_unified_spec_requirements.py#L71)，该用例仅用于验证“当输入缺失 `obs_tmin_f` 时防御性抛出契约异常”，并非真实可靠度评测；
- **缺口认定结论**: **TMin 模型虽然在生产模型库中已训练入库（480 格），但在统计可靠度层面迄今为止处于“100% 未检验”状态（审计覆盖率 = 0%）**。

---

## 事项 3：TMin 审计预研备忘 (Feasibility & Defense Memo)

### 1. 现有审计管线组件可复用性矩阵
| 模块 / 组件 | 规格现状 | 对 TMin 的复用裁定 | 改造要求与说明 |
| :--- | :--- | :---: | :--- |
| **`DiscreteBinEngine` 网格生成** | 2°F 步长，偶数整数网格线 | **直接复用** | Polymarket 日最低温合约采用完全相同的 2°F 偶数档几何网格 |
| **9 档吸附窗口与 11 档完备性** | 中心档居第 5 位，双尾截断 | **直接复用** | 最低温市场同样采用 9 档可交易窗口，结构完备对称 |
| **`settle_half_up` 结算舍入** | `math.floor(x + 0.5)` | **直接复用** | NWS WRH 最低温日结算取整规则与最高温完全一致 |
| **连续 $F$ CDF 解析差分积分** | 无近似 $\Delta F$ 概率计算 | **直接复用** | 只要传入真实的 TMin 分布函数 $F_{\text{min}}$，积分器完全通用 |
| **概率谱带划分 (8 谱带)** | `STRATA_EDGES` [0, 0.03, ... 1.0] | **直接复用** | 概率空间度量与温标无关，六元组与 Wilson 置信区间直接复用 |
| **双尾泊松显著性判定** | Poisson 上尾检验 + FLAG 状态 | **直接复用** | 两步分离判定与零形容词纪律完全适用于最低温极值 |
| **特征提取与目标列** | `obs_tmax_f`, GEFS `tmax` | **需参数化改造** | 数据加载需参数化为 `obs_tmin_f` 及 GEFS `tmin` 集合统计 |
| **物理主极值时效节点** | TMax 主时效 18h (约 15:00 LT) | **需参数化改造** | TMin 主极值时效通常发生在日出前后（约 12h / 06:00 LT），时效节点需对齐 |

---

### 2. 防移植条款预声明（物理机制差异与独立选型铁律）

> ⚠️ **【严禁跨变量参数移植法定声明】**  
> 任何后续 TMin 审计与验证管线，**严禁直接移植 TMax 的 Johnson SU 形态参数（如 $\gamma \approx -0.46, \delta \approx 2.10$）或 1.28× 右尾抬升系数**！TMin 的残差偏态方向、分布族选型（BIC 竞争）及尾部参数必须**完全独立重新拟合与统计检验**。

#### 物理与气象动力学机制差异依据：
1. **热力驱动机理的非对称性**:
   - **TMax 物理机理**：白天强太阳短波辐射驱动，地表强烈湍流混合与对流活动占主导，极端高温受副高下沉或强烈暖平流控制，残差易呈现**正偏态（右侧高温厚尾，$\text{Skew} > 0$）**；
   - **TMin 物理机理**：夜间以地面长波辐射冷却（Nocturnal Radiative Cooling）与逆温层（Inversion Layer）发展为主导。在晴空、静风、干空气夜间，地表热量剧烈散失，极易发生温度断崖式骤降，残差往往呈现**强负偏态（左侧极低温厚尾，$\text{Skew} < 0$）**；
2. **气象平流与湍流时间尺度不同**:
   - 冬季冷锋爆发过境时，剧烈冷平流可能打破夜间辐射节律，导致日最低温出现在白天或午后，具有多模态特征；
   - 气象预报集合（GEFS）在夜间近地层稳定边界层（Stable Boundary Layer）的参数化方案与白天对流边界层差异巨大，预报误差方差结构不可同日而语；
3. **数理结论**:
   - TMin 的超额峰度与偏态方向具有自身独立的物理指纹，若盲目套用 TMax 的正偏 JSU 参数，将直接导致最低温左尾极端冷事件被严重误判！

---

### 3. 工作量粗估与建议排期（供评审委员会裁决）

| 实施阶段 | 核心任务 | 工作量预估 | 交付成果与门禁 |
| :---: | :--- | :---: | :--- |
| **阶段 1** | **TMin 20 折 Block-CV 跑数任务** | 0.5 人·天 | 运行 `tests/unit/modeling/test_p4_block_cv_20fold_tmin.py`，产出 `cv_fold_*_model_tmin.json` 与 predictions 工件 |
| **阶段 2** | **TMin 独立分布族 BIC 竞争与形态提取** | 0.5 人·天 | 独立测定 TMin 残差偏度、超额峰度，完成 JSU vs EVT 竞争胜出，落盘底账 |
| **阶段 3** | **TMin 审计管线与全谱表导出** | 0.5 人·天 | 执行 `scripts/audit_p4_reliability_tmin.py`，导出“谱带 × 窗口”二维分列表与泊松机械判定 |
| **阶段 4** | **回归套件接线与基线申报** | 0.5 人·天 | 补齐单测，执行全库 967+ 项回归，提交正式审计报告 |
| **合计** | **端到端完整周期** | **2.0 人·天** | **建议排期：待 P4-AUDIT-RELIABILITY-v1.3b（TMax 收尾）关门后，由委员会裁决择机启动** |

---

## 四、 本单交付与零代码改动留痕

1. **执行边界遵守**:
   - 本工单期间**零代码改动**（未修改任何 `src/` 模型代码，未重跑拟合，未触发 TMin 审计）；
   - 测试基线保持不变，申报 **“零基线变更”（维持 967 项基线）**；
2. **交付工件落盘清单**:
   - 结构化数据：[`evidence/p5_audit_scope_recon.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p5_audit_scope_recon.json)  
     SHA-256: `3b469f2ea71060ca8b990e729ea57fa0d02462e92cff8217bbba94285bf63673`
   - 取证备忘全文：[`evidence/p5_audit_scope_recon_memo.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p5_audit_scope_recon_memo.md)  
     SHA-256: `18fbe95ce6ae16a75a7ffbc8990c74fb36b04e6c382103f6f34e56598587d159`
