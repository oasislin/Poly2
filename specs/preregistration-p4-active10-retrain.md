# Phase 2 Task 01: P4 Active 10 全站物理概率模型重训预注册规格书 (Pre-Registration Specification)

**状态**: `PENDING_REVIEW` (已落实评审委员会全部 6 项补钉与 1 项缺失项裁定，提请终签)  
**签署日期**: 2026-09-24  
**前置约束**: 依据 R2 主线推进指令与评审委员会裁定，开工重训前必须在此预注册文本中彻底冻结全部数学、统计学与物理决策，报审签认后重训方可开跑。  
**研发环境**: 严格限定于 2000–2018 历史数据窗；2019 样本外盲测窗维持硬闸物理封存（Airgap Guardrail Active）。

---

## 一、 第一项决议：历史覆盖率矛盾彻底裁定与 90% 区间口径纠偏 (Coverage Metric Resolution)

### 1.1 历史事实调查与客观裁定（A 还是 B）
- **客观裁定结论**：**历史实现 100% 为 Option A（高斯分位数硬编码）**。
- **证据链溯源**：
  在 `scripts/evaluate_round3_oos.py` (line 247) 与 `scripts/evaluate_active10_oos.py` (line 192) 中，90% 名义区间覆盖率的底层实现均为：
  $$\text{Coverage}_{90} = \frac{1}{N} \sum_{i=1}^N \mathbb{I}\left( y_i \in [\mu_i - 1.645\sigma_{\text{eff}, i},\; \mu_i + 1.645\sigma_{\text{eff}, i}] \right)$$
  其中 $1.645 = \Phi^{-1}(0.95)$ 严格为标准正态分布的单侧 95% 分位数。
- **导致矛盾的根本原因**：
  虽然管线在 CDF 与 PIT 计算层引入了非线性 Johnson SU 与 EVT GPD 变换，但在区间覆盖率指标统计代码中，**从未调用非线性分布的逆累积分布函数 $Q(0.05)$ 与 $Q(0.95)$**，而是直接套用了高斯对称展开。
  因此，只要两个实验的 $\mu$ 与 $\sigma_{\text{eff}}$ 逐位一致，其计算出的区间覆盖率必然逐位一致，导致报告产生了“覆盖率不受分布非线性参数影响”的表象与表述矛盾。

### 1.2 P4 终极执行口径（双轨透明化）
为确保数理统计的绝对诚实与金融级对账严密性，P4 重训及验收中：
1. **主门禁口径**：采用**真实分布精确分位数覆盖率 (`coverage_90_exact`)**：
   $$\text{Coverage}_{90}^{\text{exact}} = \frac{1}{N} \sum_{i=1}^N \mathbb{I}\left( y_i \in [F^{-1}(0.05),\; F^{-1}(0.95)] \right)$$
   其中 $F^{-1}$ 为当前台站所选定的真实物理校准分布（Gaussian, Johnson SU 或 EVT Hybrid）的精确分位数函数。
2. **辅门禁对账号**：同步输出高斯代理覆盖率 (`coverage_90_gaussian_proxy`，即 $\mu \pm 1.645\sigma_{\text{eff}}$），专用于与历史基线、Round 3 进行方差膨胀层 ($\sigma_{\text{eff}}$) 的隔离对账。
3. **法定门禁阈值**：双轨覆盖率均须落入法定区间 **$[83.0\%, 95.0\%]$**。

### 1.3 补钉 1：历史锚点复现预期表 (Anchor Reproduction Expectation Table)
双轨制确立后，历史指标对应关系明确厘定如下，杜绝重训后出现“指标波动是否代表损坏”的无效争论：

| 指标项 | 预期与 Round 3 关系 | 统计学与物理学理由 |
| :--- | :---: | :--- |
| **真实 MAE** | **逐位一致 ($0.00\text{e}+00$)** | 30 天因果滑动偏差 $b_{30}$ 与 EMOS 线性均值参数 $(a, b)$ 均在 18h 上保持相同训练窗与优化目标，均值层纯净不受方差与形态层影响 |
| **锚定 $\sigma^*$** | **逐位一致 ($0.00\text{e}+00$)** | $\sigma^* = \text{MAE} \times \sqrt{\pi/2}$ 纯由样本外 MAE 确定性解析推导 |
| **预测均值 $\mathbb{E}[\sigma_f]$** | **逐位一致 ($0.00\text{e}+00$)** | 季节性 EMOS $(c, d)$ 与外生 $c_{\text{train}}$ 保持相同物理约束 ($c \ge 0.9^\circ\text{F}$)，展开完全同构 |
| **样本外方差比 $s_{\text{oos}}$** | **逐位一致 ($0.00\text{e}+00$)** | 实测残差样本内方差与预测方差比值，在 18h 上基线完全同构 |
| **外生膨胀系数 $c_{\text{train}}$** | **逐位一致 ($0.00\text{e}+00$)** | 2000–2018 训练窗无偏残差方差推导，参数外生冻结 |
| **覆盖率代理轨 (`coverage_90_gaussian_proxy`)** | **逐位一致 ($0.00\text{e}+00$)** | 对应历史统计代码（$\mu \pm 1.645\sigma_{\text{eff}}$），因 $\mu, \sigma_{\text{eff}}$ 完全一致故必然逐位吻合 |
| **覆盖率精确轨 (`coverage_90_exact`)** | **新指标，无历史锚点** | 采用真实校准分布分位数 $F^{-1}(0.05)$ 与 $F^{-1}(0.95)$ 计算，真实反映物理形态变换，历史未曾计算过此指标 |
| **KMIA PIT K-S $(D, p)$** | **若 JSU 录取则预期一致** | Round 3 KMIA 录取了 Johnson SU 偏态校正。若 P4 竞争仍录取 JSU，因训练数据同为 2000–2018，参数与随机抖动（`seed=42`）一致，预期高度吻合 |
| **KORD / KSFO PIT K-S $(D, p)$** | **不预期逐位一致** | Round 3 对两站施加了 EVT GPD 厚尾方差扩宽。P4 引入 $\Delta\text{BIC} < -10$ 样本内竞争机制，若两站未达到显著性门槛而回退高斯基准，则分布形态发生客观变更，指标必然存在物理漂移，需以审计表登记映射变更理由 |

---

## 二、 第二项决议：分布映射政策完全冻结 (Frozen Distribution Mapping Policy)

### 2.1 候选分布族定义
为所有台站提供统一的三种物理分布候选集：
1. **分布 1：高斯分布 (Gaussian Baseline)**
   $$F(y) = \Phi\left(\frac{y - \mu}{\sigma_{\text{eff}}}\right)$$
   适用于残差无显著高阶偏态与厚尾的温和气候站。
2. **分布 2：Johnson SU 四参数分布 (Convective Skewness)**
   $$Z = \gamma + \delta \sinh^{-1}\left(\frac{y - \xi}{\lambda}\right) \sim \mathcal{N}(0, 1)$$
   适用于由强对流或海陆风午后剧烈升温/雷暴降温引起的非对称偏态站（如 KMIA, KHOU）。
3. **分布 3：EVT 极值超额广义帕累托混合体 (GPD Hybrid Tails)**
   中心 $[u_L, u_R]$ 为高斯核心，左尾 ($< u_L$) 与右尾 ($> u_R$) 分别拟合 GPD：
   $$G(y; \xi, \beta) = 1 - (1 + \xi y / \beta)^{-1/\xi}$$
   适用于具有极端焚风、极寒极热厚尾特征的内陆与复杂地形站（如 KSFO, KDAL, KAUS）。

### 2.2 补钉 3：峰度数学定义硬性锁定 (Fisher's Excess Kurtosis)
本规范硬性定义峰度为 **Fisher 超额峰度 (Fisher's Excess Kurtosis)**：
$$\text{Kurt}_{\text{excess}} = \frac{\mu_4}{\sigma^4} - 3 = \frac{\frac{1}{N}\sum_{i=1}^N (x_i - \bar{x})^4}{\left(\frac{1}{N}\sum_{i=1}^N (x_i - \bar{x})^2\right)^2} - 3$$
代码实现严格绑定为：`scipy.stats.kurtosis(residuals, fisher=True, bias=False)`。
标准正态分布的 $\text{Kurt}_{\text{excess}} \equiv 0.0$。激活门槛 $\text{Kurt}_{\text{excess}} > 1.0$ 意味着必须超出标准正态分布 1.0 以上（对应原始 Pearson 峰度 $> 4.0$）方构成显著厚尾，彻底排除原始四阶矩定义混淆。

### 2.3 补钉 2：激活条件与冲突处置优先级 (Activation & Conflict Priority)
在 2000–2018 训练窗（扣除缺报后约 6,940 站·日）残差上：
1. **单项触发门槛**：
   - 若 $|\text{Skew}| > 0.40$，激活 Johnson SU 拟合；
   - 若 $\text{Kurt}_{\text{excess}} > 1.0$，激活 EVT GPD 拟合。
2. **同时触发时的优先级规则**：
   当某个台站/季节同时满足 $|\text{Skew}| > 0.40$ 与 $\text{Kurt}_{\text{excess}} > 1.0$ 时：
   - 系统在 2000–2018 训练集上**同时拟合 Johnson SU 与 EVT GPD 混合体**；
   - 分别计算相对于基准高斯分布的贝叶斯信息准则差值 $\Delta\text{BIC}_{\text{JSU}} = \text{BIC}_{\text{JSU}} - \text{BIC}_{\text{Gauss}}$ 与 $\Delta\text{BIC}_{\text{EVT}} = \text{BIC}_{\text{EVT}} - \text{BIC}_{\text{Gauss}}$；
   - **BIC 择优录取**：录取 $\Delta\text{BIC}$ 较小（即负得更多，似然增益最显著）的模型；
   - **EVT 风险平局优势**：若 $|\Delta\text{BIC}_{\text{JSU}} - \Delta\text{BIC}_{\text{EVT}}| \le 2.0$（差异无统计学显著性），**强制以 EVT 优先录取**。物理与金融量化依据：极端厚尾（Fat-tail）对于天气二元期权尾部定价具有灾难性单边巨亏风险，四阶厚尾在金融风险对冲中拥有更高防护权重。
3. **录取门槛与自动回退**：
   - 只有当备选模型在 BIC 上优于基准高斯模型至少 $\Delta\text{BIC} < -10$，且在 20 轮 Block-CV 中验证集平均 PIT $p$ 值 $\ge 0.05$ 时，方可录取；
   - **未显著优于高斯基准者强制回退为高斯基准**，杜绝任何参数过拟合。

### 2.4 补钉 4：CV 双重用途与选择效应法定声明 (Selection Effect Disclosure)
> ⚠️ **【合规披露声明】**  
> 本规格书明确声明：在分布映射竞争规则中，将 20 轮 30-Day Block-CV 的验证折表现（平均 PIT $p \ge 0.05$）作为模型录取的门禁条件，**导致 Block-CV 结论被模型选择过程实质消费，从而在验证集诊断表上引入了统计学上的轻微选择乐观偏差（Selection Optimism）**。  
> 因此，**20 轮 Block-CV 诊断表仅具开发期模型泛化能力的方向性参考效力；全系统终极推断与不可篡改的法定验收唯一以 2019 样本外盲测窗为准**。  
> 此声明必须作为法定元数据，直接印入 P5 检验工具在 `--mode cv` 下生成的全量输出报告与终端 Summary 标签中。

### 2.5 补钉 5：模型竞争过程全量留痕底账 (Audit Trail CSV)
重训管线必须将所有单元的分布竞争过程逐一落盘至不可篡改底账：
📄 [`evidence/p4_distribution_selection_audit.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_distribution_selection_audit.csv)  
包含字段：`station, season, variable, n_samples, skewness, kurtosis_fisher, jsu_triggered, evt_triggered, bic_gaussian, bic_jsu, bic_evt, delta_bic_winner, cv_pit_p_mean, final_selected_family, fallback_reason`。  
该文件的 SHA-256 校验哈希必须写入交付清单，严禁拍脑袋指定模型。

---

## 三、 第三项决议：形状层与方差层粒度方案完全冻结 (Granularity Resolution)

### 3.1 粒度层级设计矩阵

| 架构层级 | 数学参数 | 拟合粒度 (Granularity) | 物理与气象学依据 |
| :--- | :--- | :--- | :--- |
| **均值校正层** | 30天滚动偏差 $b_{30}$ | **站级 $\times$ 逐日因果滑动** (`shift(1).rolling(30)`) | 追踪局地环流天气尺度（Synoptic Scale）动态漂移 |
| **EMOS 线性展开层** | $(a, b, c, d)$ | **站级 $\times$ 季节 (4) $\times$ 提前期 (Lead Time)** | 季节性热力动力学差异巨大；预报误差方差随 lead time 单调发散 |
| **外生方差膨胀层** | $c_{\text{train}}$ | **站级 $\times$ 季节 (4)** | 样本量约 1,735 天，捕捉各季节集合预报离散度的系统性低估/高估特征 |
| **高阶形态层** | Johnson SU / EVT GPD | **站级 $\times$ 季节 (4)** | 强对流偏态（如迈阿密）主要集中在夏季/初秋，极寒厚尾集中在冬季，分季节表征物理机理更精确 |

### 3.2 物理底座与参数边界硬性下沉
1. **EMOS 方差常数底座**：$c \ge 0.90^\circ\text{F}$（强制满足 NOAA ASOS 物理仪器误差 ADR-0010 下限）；
2. **集合离散斜率约束**：$d \ge 0.0$（保证方差非负且与集合扰动同向）；
3. **EVT 阈值分位数**：严格锁定为 $u_L = 5\%$ 与 $u_R = 95\%$；
4. **EVT 形状参数**：$\xi < 0.5$（确保有限二阶矩，方差有限性存在）。

### 3.3 补钉 6：薄样本约束、回退规则与 $c_{\text{train}}$ 粒度变更留痕 (Thin-Sample Fallback Rules)
1. **最低样本容量门槛**：
   当 EMOS 参数拟合展开至【站级 $\times$ 季节 $\times$ 提前期】微观单元时，每个单元训练样本量约 145 天（6,940 天 $\div$ 4 季 $\div$ 12 提前期）。若任意单元内有效匹配站·日样本量 **$N_{\text{valid}} < 100$**，严禁进行独立无约束拟合。
2. **确定性级联回退顺序（Cascade Fallback Order）**：
   - **第一级回退（时效池化，Adjacent Lead Pooling）**：合并相邻 $\pm 6\text{h}$ 提前期样本联合拟合 $(a, b, c, d)$；
   - **第二级回退（跨季同时效池化，Cross-Season Pooling）**：若第一级合并后样本仍不足或优化不收敛，合并该台站全年同时效数据拟合均值斜率 $b$，仅保留季节常数偏置 $a$；
   - **第三级回退（先验物理常数兜底）**：回退至气候学物理托底基线（$a=0, b=1, c=\sigma_{\text{clim}}, d=0$）。
3. **状态审计标记**：
   凡触发回退的单元，在模型资产元数据及普查总表中必须显式标记为 `status = "POOLED-FALLBACK"` 及回退层级代码，**严禁静默伪装为独立拟合**。交付报告必须汇总统计全网格‘独立拟合单元数 vs 回退拟合单元数’。
4. **$c_{\text{train}}$ 粒度方案修订与历史留痕**：
   【口径变更声明】：本规格书正式确认，外生方差膨胀系数 $c_{\text{train}}$ 的计算粒度由此前讨论草案中的‘站级 $\times$ 提前期独立推导’**最终冻结为【站级 $\times$ 季节（不含提前期）】**。
   - **变更理由**：Cell 级 145 天样本推导经验方差噪声过大，极易因单次离群点导致膨胀因子过度失真；而站级 $\times$ 季节聚合样本量达约 1,735 站·日，信噪比提升 3.46 倍（$\sqrt{1735/145} \approx 3.46$），方差比估算高度稳健。

---

## 四、 缺失项 7：宇宙定义最终裁定与 160 个缺失格处置定案 (Universe Definition & Final Arbitration)

### 4.1 存量数据资产全面实测核查
工程组对 `data/processed/calib-dataset-v2.0/gefs_factors/` 下 10 个代表台站全量 2000–2018 年 Parquet 文件进行了逐年逐格排查：
- **实测结论**：全部 10 个台站的 GEFS 因子文件中，**全量 12 个提前期 (`lead_hours` $\in [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]$) 的预报数据 100% 存在且物理完整**。
- **160 格缺失根因揭示**：旧版管线存量 800 个模型相比理论 960 格缺失的 160 格（Max 60h 40格、Max 66h 16格、Max 72h 24格、Min 60h 12格、Min 66h 28格、Min 72h 40格），**并非由于缺乏 GEFS 原始气象数据，而是由于旧版 `src/modeling/partitioner.py` 强行施加了‘站点本地时区日极值时间窗口硬匹配’**（Max 必须落在 15:00 LT 附近，Min 必须落在 06:00 LT 附近），将偏离极值发生窗口的时效硬性丢弃。

### 4.2 宇宙定义终局裁定
依据委员会‘二选一、杜绝临时缩编’的指令，本规格书正式将 P4 重训的模型宇宙**确定性定案为【960 完整连续全网格】**（10 台站 $\times$ 4 季节 $\times$ 2 标的(Max/Min) $\times$ 12 提前期(6h~72h)）：
1. **法定日极值主交易节点 (800 格)**：与日极值时窗完全对齐的时效，执行独立无约束/弱约束拟合，作为法定结算主宇宙；
2. **时序平滑补全节点 (160 格)**：利用物理存在的 GEFS 存量数据，按照补钉 6 的时效池化规则（`POOLED-FALLBACK`）完成重训补齐，生成全量合规 `.pkl` 模型入库；
3. **彻底消灭悬空断层**：宇宙总格数永远固化为 960 格，杜绝后续生产与回测时出现‘部分时效无模型’的降级异常。

---

## 五、 P4 终极配置与 22:47 隔离运行之差异清单 (Explicit Diff vs 22:47)

| 维度 | 22:47 运行 (已隔离封存) | P4 重训终极方案 (本次预注册) |
| :--- | :--- | :--- |
| **预注册授权状态** | 无预注册授权（事故性触碰 2019） | 完整预注册文本报审签认，内置冻结门禁 |
| **宇宙定义与网格** | 仅 18h 单一提前期 (10 站·日) | 960 完整全网格（800 独立格 + 160 POOLED-FALLBACK 池化补齐格） |
| **参数粒度** | $c_{\text{train}}$ 站级单一标量 | $c_{\text{train}}$ 站级 $\times$ 季节 (4) 稳健估计 |
| **模型资产落盘** | 未生成 `.pkl`，仅输出 JSON 参数 | 生成全量 960 个标准命名 `.pkl` 与元数据 JSON，全面接入 Registry |
| **分布形态选择** | 混合并存（全部 10 站套用 EVT 扩宽） | 站级 BIC/Block-CV 统计竞争，无偏态/无厚尾站强制回退高斯 |
| **90% 覆盖率计算** | Option A (高斯分位数硬编码) | 双轨制：真实分布分位数 `coverage_90_exact` + 高斯代理对账号 |
| **样本外评估授权** | 严禁引用 22:47 数据为重训依据 | P4 阶段仅使用 2000–2018 拟合并经 20 轮 Block-CV 检验通过后，由用户签发旗标方可开封 2019 |

---

## 六、 与 P5 交叉验证与验收工具线的协调对齐 (Coordination with P5 Mainline)

1. **执行解耦**：P4 的模型参数拟合、全量 960 格模型落盘及训练窗内 BIC 竞争完全自洽，不依赖 P5 代码，可先行动工；
2. **汇合前置门禁**：P4 重训交付报告中的 20 轮 Block-CV 外部检验表，必须调用经评审委员会三组合成测试验收合格后的 P5 工具（`standalone_reliability_check.py --mode cv`）；
3. **时间线安排**：P4 启动模型矩阵拟合落盘期间，P5 推进自查清单与合成测试核验；两线于重训脚本收敛时汇合执行最终 Block-CV 跑数。

---

## 七、 预注册法定门禁声明 (Statutory Gates)

P4 研发在 2000–2018 跨 20 轮 30-Day Block-CV 中，必须满足以下平均泛化门禁指标方可申请 2019 样本外终极开封：
1. **CV PIT K-S 拟合检验**：20 轮折外平均 $p \ge 0.05$；
2. **CV 7 档加权 ECE**：20 轮折外平均 $\le 3.0\%$；
3. **CV 方差比 $s_{\text{cv}}$**：20 轮折外平均 $\in [0.85, 1.15]$；
4. **CV PIT 均值**：20 轮折外平均 $\in [0.46, 0.54]$；
5. **CV 90% 精确覆盖率**：20 轮折外平均 $\in [83\%, 95\%]$。

**拟制工程师声明**：本预注册文本完全遵守数理统计客观性，杜绝先看数据后定标准。  
**拟制人**: Antigravity Quantitative Met Audit Engineer  
**提交日期**: 2026-09-24  
