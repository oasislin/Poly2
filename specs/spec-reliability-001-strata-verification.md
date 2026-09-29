# 规格书：训练窗逐概率段可靠性对账检验 (SPEC-RELIABILITY-001)

- **Spec Issue**: [#118](https://github.com/oasislin/Poly2/issues/118) (Spec: Reliability Check SPEC-RELIABILITY-001 - 训练窗逐概率段可靠性对账检验)
- **Tickets**:
  - `Reliability Check - Ticket 01`: [#120](https://github.com/oasislin/Poly2/issues/120)
  - `Reliability Check - Ticket 02`: [#121](https://github.com/oasislin/Poly2/issues/121)
  - `Reliability Check - Ticket 03`: [#122](https://github.com/oasislin/Poly2/issues/122)
  - `Reliability Check - Ticket 04`: [#124](https://github.com/oasislin/Poly2/issues/124)

> **规格编号**: SPEC-RELIABILITY-001  
> **任务定位**: 决策面诊断视图开发（不改变 ADR-0017 法定门禁体系，法定口径照旧运行）  
> **数据授权**: 仅使用 2000–2018 训练窗审计数组（`data/processed/audit_arrays/2000_2018_training_arrays.parquet`，同构验证）。**2019 OOS 数组禁止触碰**（盲测额度已消耗、独立复算已封存）。  
> **交付流程**: 预注册流程（Preregistration）——本规格书即预注册文本，实现前不得修改判定标准；如需修改，走版本变更留痕。  
> **模型版本与参数基准**: 严格对齐 Round 3 终局法定模型版本（KORD 高斯正态、KMIA R-6 Johnson SU、KSFO R-7 EVT-GPD 极值厚尾混合分布）。

---

## 一、 问题背景与使命陈述 (Problem Statement & Purpose)

在 ADR-0017 中确立的法定门禁 ② 为全空间 7 档位离散加权期望校准误差（Weighted Multi-Class ECE $\le 3.0\%$）。虽然加权 ECE 提供了宏观边缘校准度的一票否决标准，但它是一个**单一汇总标量**，具有以下固有诊断盲区：
1. **局部偏差稀释**：在概率极小（如 $<5\%$）或极高（如 $>40\%$）的深水档位，局部的系统性高估或低估可能在样本权重加权平均后被中间海量样本掩盖；
2. **缺乏直观兑现率对账**：量化交易决策层需要确切回答：“当模型给出 25% 的胜率估值时，在历史样本中该类状态实际兑现的频率是多少？是否在可接受的置信区间内？”

**SPEC-RELIABILITY-001 的核心目的**：  
将法定门禁 ② 的单一汇总数字展开为一张详尽的**逐概率段可靠性对账单（Reliability Check by Probability Strata）**，通过训练窗展开的 20,820 站·日全量档位预测，建立经验命中频率与名义预测概率的逐段核验视图，并补充站点×季节分层预警表与 Brier 技能分，为实盘交易与下注提供微观条件可靠度依据。

---

## 二、 严格受限数据与模型版本契约 (Data & Model Contracts)

### 1. 数据资产授权与隔离铁律
- **唯一输入文件**: `data/processed/audit_arrays/2000_2018_training_arrays.parquet`
  - SHA256 校验和: `8f2a84d26aaeaeaaf7050424df6f7d19891d752fb01b89f49d3add79bbaf3a5c`
  - 记录容量: 20,820 行（覆盖 KORD 6,940、KMIA 6,940、KSFO 6,940 站·日，2000-01-01 至 2018-12-31）
- **禁止触碰 2019 数据**: 严禁读取 `data/processed/audit_arrays/2019_oos_evaluation_arrays.parquet` 或 `2019_oos_round3_evaluation_arrays.parquet`。盲测额度已耗尽并封存，本诊断仅服务于训练窗基准对账。
- **单向消费隔离铁律**: 本检验为纯消费方，严禁用本检验的对账结果反向调整模型参数。

### 2. 模型版本与分布函数严格对齐
必须严格遵循 Round 3 终局模型结构（参数文件见 `evidence/r6_kmia_parameters.json` 与 `evidence/r7_tail_parameters.json`）：

1. **KORD（芝加哥奥黑尔）**:
   - 基础预测均值: $\mu_f = \text{mu\_forecast}$
   - 有效预测标准差: $\sigma_{\text{eff}} = \text{sigma\_forecast} \times \kappa_{\text{evt}}$，其中 $\kappa_{\text{evt}} = \sqrt{\text{var\_evt\_factor}}$（取自 R-7 尾部方差因子）
   - 分布形式: 标准高斯正态分布 $F(y) = \Phi\left(\frac{y - \mu_f}{\sigma_{\text{eff}}}\right)$
2. **KMIA（迈阿密）**:
   - 基础预测均值与方差: $\mu_f = \text{mu\_forecast}, \sigma_{\text{eff}} = \text{sigma\_forecast} \times \kappa_{\text{evt}}$
   - 偏度修正: 采用 R-6 冻结的 Johnson SU 分布参数：
     $$\gamma = 0.7645691412470903, \quad \delta = 1.668232534241755, \quad \xi = 0.7016806459852685, \quad \lambda = 1.2322473920735264$$
   - 变换公式: $z = \frac{y - \mu_f}{\sigma_{\text{eff}}}$，标准化变量 $z_{\text{norm}} = \gamma + \delta \cdot \text{arcsinh}\left(\frac{z - \xi}{\lambda}\right)$，分布函数 $F(y) = \Phi(z_{\text{norm}})$
3. **KSFO（旧金山）**:
   - 基础预测均值与方差: $\mu_f = \text{mu\_forecast}, \sigma_{\text{eff}} = \text{sigma\_forecast} \times \kappa_{\text{evt}}$
   - 极值厚尾: 采用 R-7 冻结的 EVT-GPD 混合分布参数：
     - 分位截断点: $u_L = -1.5639721477171529$ (5th), $u_R = 1.7363677989708575$ (95th)
     - 左尾 GPD: $\xi_L = -0.10403629751198618, \beta_L = 0.7228020583196235$
     - 右尾 GPD: $\xi_R = 0.28589704797071285, \beta_R = 0.6974251147551061$
   - 变换公式: $z = \frac{y - \mu_f}{\sigma_{\text{eff}}}$：
     - 当 $z < u_L$: $F(y) = 0.05 \times \left(1 + \frac{\xi_L (u_L - z)}{\beta_L}\right)^{-1/\xi_L}$
     - 当 $u_L \le z \le u_R$: $F(y) = \Phi(z)$
     - 当 $z > u_R$: $F(y) = 1 - 0.05 \times \left(1 + \frac{\xi_R (z - u_R)}{\beta_R}\right)^{-1/\xi_R}$

---

## 三、 数据展开与分桶方案规范 (Record Expansion & Binning)

### 1. 记录展开架构
对训练窗内每一个有效站·日 $(d, s)$ 及每一个分桶档位 $b \in \{1, \dots, K\}$：
- **预测概率**: $p_{\text{pred}}(d, s, b) = F(y_{\text{upper}}(b)) - F(y_{\text{lower}}(b))$
  - 尾部开放区间采用极限或边界条件（左开放区间下界为 $-\infty$，右开放区间上界为 $+\infty$）。
- **实测命中指示变量**:
  $$\text{hit}(d, s, b) = \mathbb{I}(y_{\text{obs}}(d, s) \in [y_{\text{lower}}(b), y_{\text{upper}}(b)))$$
- **辅助维度保留**: `station`, `year`, `month`, `season`。

### 2. 分桶方案（历史验证面）
- **分桶基准**: 训练窗全期 20 年采用**固定法定代表分桶方案**（全期一致，禁止逐年动态漂移）：
  - **主检验分桶（法定 7 档对齐）**: 以每日中心档 $c_0 = \text{round}(\mu_f)$ 为中心，构建 7 档离散区间：
    $$B_1=(-\infty, c_0-5.5), B_2=[c_0-5.5, c_0-3.5), B_3=[c_0-3.5, c_0-1.5), B_4=[c_0-1.5, c_0+1.5), B_5=[c_0+1.5, c_0+3.5), B_6=[c_0+3.5, c_0+5.5), B_7=[c_0+5.5, +\infty)$$
    该分桶产生 $20,820 \times 7 = 145,740$ 条样本对，直接与 ADR-0017 法定主门禁 ② 结构同构。
  - **精细气候固定分桶（气候网格 2°F 等宽备选）**: 覆盖各站历史温标全域的固定 2°F 等宽网格（例如 KORD: [-20°F, 110°F]，KMIA: [30°F, 105°F]，KSFO: [30°F, 110°F]），提供更高分辨率的展开核验。
- **分辨率抖动口径固定**: 实测气温 $y_{\text{obs}}$ 命中判定与法定管线严格统一，半闭半开区间 $[y_{\text{lower}}, y_{\text{upper}})$，抖动口径在脚本内固定常数与注释，严禁存在口径漂移。

---

## 四、 主表构造：全局 20 段等宽概率归池 (Global 20-Strata Pooling)

### 1. 归池算法
将全部展开样本对 $(p_{\text{pred}}, \text{hit})$ 汇入全域样本池，按 $p_{\text{pred}}$ 划分为 20 个等宽概率段（段宽 5%）：
$$I_m = [0.05 \times (m-1), 0.05 \times m), \quad m = 1, \dots, 20$$
（其中首尾端点分别处理 $[0.0, 0.05)$ 与 $[0.95, 1.0]$）。

### 2. 主表字段规约
主表必须完整输出以下列（无缺行、无省略）：
1. `stratum_id`: 分段编号 (1 ~ 20)
2. `stratum_range`: 概率区间字符串（如 `[0.20, 0.25)`）
3. `sample_count_n`: 段内样本条数 $n_m$
4. `mean_pred_prob`: 段内平均预测概率 $\bar{p}_m = \frac{1}{n_m} \sum_{i \in I_m} p_i$
5. `empirical_hit_freq`: 段内实测命中频率 $\hat{f}_m = \frac{1}{n_m} \sum_{i \in I_m} \text{hit}_i$
6. `abs_bias`: 绝对偏差 $|\bar{p}_m - \hat{f}_m|$
7. `ci_95_half_width`: 二项分布 95% 置信半宽 $1.96 \cdot \sqrt{\frac{\hat{f}_m (1 - \hat{f}_m)}{n_m}}$（当 $\hat{f}_m=0$ 或 $1$ 时采用 Wilson 评分区间修正）
8. `is_outside_ci`: 布尔标志，标明偏差是否超出自身 95% 置信带

### 3. 全局汇总指标
- **全表加权绝对偏差（加权 ECE）**:
  $$\text{ECE}_{\text{strata}} = \frac{\sum_{m=1}^{20} n_m |\bar{p}_m - \hat{f}_m|}{\sum_{m=1}^{20} n_m}$$
- 与法定门禁 ② 的对比说明：数值与 `scripts/standalone_recompute_evaluation.py` 在概念上互为映射，因分桶粒度差异导致的微小非严格相等需给出合理解释。

---

## 五、 分层预警表：站点 × 季节（12 格）独立归池 (Stratified Warning Matrix)

### 1. 分层目的与已知先验
全局归池容易稀释局部微气候的异质性失准（例如 KSFO 夏季已知存在海洋内流与高温热浪切换带来的方差扰动，局部 2pp 的虚低混入全局可能被稀释至 $<0.5\text{pp}$）。

### 2. 12 格独立归池规约
将数据集切分为 **3 站（KORD, KMIA, KSFO）× 4 季（DJF, MAM, JJA, SON）共 12 个独立子集**：
- 每个子集独立执行 5~10 段概率归池（推荐 10 段，段宽 10%）；
- 产出分层表 `evidence/reliability_check_stratified_station_season.csv`；
- 重点标注超 CI 带的段位，**KSFO 夏季格（KSFO-JJA）必须显式呈现并重点分析，严禁缺省**。

---

## 六、 Brier 技能分：防止“背气候表”的诚实笨蛋 (Brier Skill Score)

### 1. 测度定义
为防止模型仅通过输出样本内历史气候平均概率来伪装“完美校准”，必须计算模型相对于气候基准的 Brier 技能分（BSS）：
1. **模型 Brier 分数**:
   $$\text{BS}_{\text{model}} = \frac{1}{N} \sum_{i=1}^N (p_{\text{pred}, i} - \text{hit}_i)^2$$
2. **历史气候基准 Brier 分数**:
   各站×各月的历史气候经验概率 $p_{\text{clim}}(s, m, b)$ 严格基于 2000–2018 训练窗（采用留一法 LOYO 或剔除当日计算，杜绝自证泄漏）：
   $$\text{BS}_{\text{clim}} = \frac{1}{N} \sum_{i=1}^N (p_{\text{clim}, i} - \text{hit}_i)^2$$
3. **Brier 技能分 (BSS)**:
   $$\text{BSS} = 1 - \frac{\text{BS}_{\text{model}}}{\text{BS}_{\text{clim}}}$$

### 2. 门禁与呈现准则
- 验收准则: $\text{BSS} > 0$（确保证明模型具备真正的气象动力学预测技巧）。
- 若 $\text{BSS} \le 0$，必须在报告主表及结论中显著以警告（WARNING）标注，严禁藏入附录。

---

## 七、 明确禁止事项 (Explicit Prohibitions)

1. **禁止按桶标签 pooling 后对单一名义概率对账**: 严禁将不同 $\sigma_f$ 或不同中心位置的同名桶简单合并；必须严格按照预测概率值 $p_{\text{pred}}$ 进行区间分组。
2. **禁止触碰 2019 数据**: 严禁使用任何 2019 年观测真值或预测数组。
3. **禁止反向调参（单向消费隔离）**: 检验结论为诊断视图，不得反向调整 EMOS 参数或 R-6/R-7 权重。
4. **禁止省略或过滤极端段位**: 无论样本数多寡或偏差大小，20 个段位必须全部同表完整呈现，秉持损益/偏差双向真实呈现原则。
5. **禁止使用庆祝性或主观修饰词**: 报告用词保持中立客观。

---

## 八、 交付工件清单与哈希规约 (Deliverables)

| 工件项 | 规划路径 | 职责说明 |
| :--- | :--- | :--- |
| **主可靠性表** | `evidence/reliability_check_main_global.csv` | 20 段等宽全局归池主表（含 $n, \bar{p}, \hat{f}, \text{CI}$, 超限标志） |
| **分层预警表** | `evidence/reliability_check_stratified_station_season.csv` | 12 格（站点×季节）独立归池分层对账表 |
| **Brier 技能分** | `evidence/reliability_check_brier_skill.csv` | $\text{BS}_{\text{model}}, \text{BS}_{\text{clim}}, \text{BSS}$ 统计汇总表 |
| **独立复算脚本** | `scripts/standalone_reliability_check.py` | 零项目私有依赖，仅依赖标准库+numpy/pandas/scipy，可逐位重现所有 CSV |
| **规格落实说明** | `evidence/reliability_check_spec_notes.md` | 参数冻结声明、口径对照说明与诊断分析报告 |
| **证据清单固化** | `evidence/pilot_manifest.json` | 将上述 5 项工件的 SHA256 校验和增量注册落盘 |

---

## 九、 验收标准 (Acceptance Criteria - Preregistered)

1. [ ] **主表完整性**: 20 段概率对账表无空缺行，全量指标齐全；
2. [ ] **分层全覆盖**: 12 格分层表完整呈现，KSFO 夏季格清晰列示并分析；
3. [ ] **BSS 显著性**: 全局与分站 Brier Skill Score 完整列出且满足 $\text{BSS} > 0$；
4. [ ] **逐位确定性复现**: 运行 `python scripts/standalone_reliability_check.py` 输出与 `evidence/` 下所有交付 CSV 逐位完全一致；
5. [ ] **法定门禁对照自洽**: 给出与法定主门禁 ② 差异的数理归因说明。
