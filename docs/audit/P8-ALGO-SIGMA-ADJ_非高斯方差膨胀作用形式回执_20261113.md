# 算法审阅回执：σ_adj 方差膨胀在非高斯先验上的作用形式（2026-11-13）

> **归档类型**：B 线算法审阅与理论复核回执（只读/对账级）  
> **关联议题**：P8-ALGO-REVIEW 待确认事项登记册 B-1 项  
> **落盘日期**：2026-11-13  
> **状态**：定稿已签收（业主委托算法审阅侧代签代定）

---

### 【头部勘误段】（根据 2026-11-13 审阅侧复核要求增补）

1. **方差膨胀乘数统一修正**：
   - 膨胀乘数法定统一规范为 $c \equiv \sqrt{\max(1.0, s_{\text{oos}})}$；
   - 此前部分讨论摘要中出现的“$s \equiv s_{\text{oos}}$”及汇总表中的“$\max(1.0, s_{\text{oos}})$”均系未开根号的笔误转录滑脱；推导正文保持历史原貌，统一以 $c = \sqrt{\max(1.0, s_{\text{oos}})}$ 为唯一准则（即 $\text{Var}_{\text{adj}} = \max(1.0, s_{\text{oos}}) \cdot \sigma_{\text{eff}}^2$）。
2. **EVT_Hybrid 拼接阈值口径修正**：
   - 问题 3 中的无量纲标准化阈值 $u_L, u_R$ 表述由“精确 $\pm 1.645$”更正为**“Scheme B 冻结的经验拼接常数”**；
   - 严格遵从 P6 封盘协议及 Ticket 06 既定口径（经验 5% / 95% 分位数截断常数，由历史样本校准冻结，非标准正态理论点），防止后续自动化校验误用理论高斯分位做刚性断言。

---

### 总体结论先行 (Executive Summary)

非高斯先验在方差膨胀下的**唯一数理自洽且物理保真的作用形式**是**以均值 $\mu_0$ 为中心的仿射缩放（Mean-Centered Affine Scaling）**：
$$T(X) = \mu_0 + c \cdot (X - \mu_0), \quad \text{其中 } c \equiv \sqrt{\max(1.0, s_{\text{oos}})}$$

在代码库现行的标准化残差架构（Standardized Residual Space $Z = (X - \mu_0) / \sigma$）下，该变换与**「保留拟合好的无量纲形态参数不变，在线仅将特征尺度 $\sigma_{\text{eff}}$ 替换为 $\sigma_{\text{adj}} = c \cdot \sigma_{\text{eff}}$」**完全等价。代码库在 `scripts/audit_v2/reliability_v2.py:63-75` 与 `scripts/evaluate_p4_2019_settlement.py:133-143` 中事实上已采用此逻辑，架构上无须引入非线性形变。

---

### 问题 1：目标变换 $T(X)$ 的形式与唯一性分析

#### 1. 变换形式推导
设随机变量 $X \sim F$，其均值为 $\mu_0 = \mathbb{E}[X]$，方差为 $\sigma^2 = \text{Var}(X)$。要求变换 $T(X)$ 满足：
1. 均值守恒：$\mathbb{E}[T(X)] = \mu_0$；
2. 方差膨胀：$\text{Var}(T(X)) = s_{\text{oos}} \cdot \sigma^2 \implies \text{Std}(T(X)) = c \cdot \sigma$（其中 $c = \sqrt{\max(1.0, s_{\text{oos}})}$）；
3. 形状（偏度/峰度/高阶标准化中心矩）严格不变；
4. 高斯退化：当 $X \sim \mathcal{N}(\mu_0, \sigma^2)$ 时，$T(X) \sim \mathcal{N}(\mu_0, c^2\sigma^2)$，退化为 $\sigma \to c\sigma$。

构造仿射变换：
$$T(X) = a X + b$$
由线性算子性质：
- $\text{Var}(T(X)) = a^2 \text{Var}(X) = a^2 \sigma^2 = c^2 \sigma^2 \implies a = c$（因变换需保序递增，取正根 $a > 0$）；
- $\mathbb{E}[T(X)] = a \mathbb{E}[X] + b = c \mu_0 + b = \mu_0 \implies b = (1 - c)\mu_0$。

代入得：
$$T(X) = \mu_0 + c (X - \mu_0)$$

#### 2. 形状不变量验证
对于任意 $k \ge 3$ 阶中心矩：
$$\mu_k(T(X)) = \mathbb{E}\left[(T(X) - \mathbb{E}[T(X)])^k\right] = \mathbb{E}\left[(c(X - \mu_0))^k\right] = c^k \mathbb{E}\left[(X - \mu_0)^k\right] = c^k \mu_k(X)$$
对应的标准化 $k$ 阶矩（偏度 $\gamma_1$、超额峰度 $\gamma_2$ 等）：
$$\tilde{\mu}_k(T(X)) = \frac{\mu_k(T(X))}{\left(\text{Var}(T(X))\right)^{k/2}} = \frac{c^k \mu_k(X)}{(c^2 \sigma^2)^{k/2}} = \frac{\mu_k(X)}{\sigma^k} = \tilde{\mu}_k(X)$$
**偏度、峰度及全部高阶标准化中心矩（包括全部 cumulant ratios）严格恒定。**

#### 3. 唯一性定理 (Uniqueness)
在**「确定性、连续且严格单调递增变换」** $\mathcal{T} = \{T: \mathbb{R} \to \mathbb{R} \mid T' > 0\}$ 集合中：
- 严格单调性保证了累积分布函数的映射关闭性：$F_Y(y) = F_X(T^{-1}(y))$，不产生概率折叠或原子堆积；
- 要求所有标准化矩 $\tilde{\mu}_k$ 保持不变，由概率论中特征函数与展开多项式同构定理，若变换 $T$ 不改变分布的无量纲标准化变量 $Z = \frac{X - \mu_0}{\sigma}$ 的测度结构（即 $Z_{T(X)} \overset{d}{=} Z_X$），则 $T$ **必为且仅为**均值中心仿射变换。该解在上述条件约束下是**唯一的**。

#### 4. 候选变换对比与差异
| 候选变换机制 | 具体形式 | 均值保持 | 方差膨胀 | 形状保持 | 高斯退化 | 理论缺陷 / 偏离点 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **均值中心仿射 (推荐)** | $T(X) = \mu_0 + c(X - \mu_0)$ | **是** | **是** | **是** | **是** | 无，数理性质最完备。 |
| **中位数中心仿射** | $T(X) = m_0 + c(X - m_0)$ | 否 ($\Delta\mu = (c-1)(m_0 - \mu_0)$) | 是 | 是 | 是 | 破坏均值无偏性，对偏态分布引入虚假一阶系统偏差。 |
| **加性卷积 (随机扰动)** | $Y = X + \varepsilon, \varepsilon \sim \mathcal{N}(0, (c^2-1)\sigma^2)$ | 是 | 是 | 否 | 是 | 卷积使得极值尾部与峰度被中心极限定理稀释，破坏 JSU/EVT 尾部厚度。 |
| **非线性参数微调** | 调节形态参数（如缩小 JSU 的 $\delta$） | 否 | 需数值逼近 | 否 | 否 | 导致偏度与峰度非线性耦合变形，破坏模型离线阶段对物理厚尾的参数识别。 |

---

### 问题 2：拉伸中心的选择：均值 vs 中位数

在非对称分布（如偏斜 JSU 分布，$\text{Skew} \ne 0 \implies \mu_0 \ne m_0$）下，拉伸中心的选择具有决定性的统计与物理意义：

#### 1. 均值中心 $T_{\text{mean}}(X) = \mu_0 + c(X - \mu_0)$ 的代数与统计行为
- **保持的性质**：
  - 严格保持点预报的**数学期望无偏性**：$\mathbb{E}[T_{\text{mean}}(X)] = \mu_0$；
  - 严格保持因果偏差修正项（如 $b_{30}$ 修正）与日内鞅过程（Martingale property）的无偏传递；
  - 保持 $L_2$ 误差测度的方差解析可加性：$\text{Var}(T_{\text{mean}}(X)) = c^2 \sigma^2$。
- **改变的性质**：
  - 中位数发生位移：$m_{\text{new}} = \mu_0 + c(m_0 - \mu_0) = m_0 + (c - 1)(m_0 - \mu_0)$。

#### 2. 中位数中心 $T_{\text{med}}(X) = m_0 + c(X - m_0)$ 的代数与统计行为
- **保持的性质**：
  - 保持中位数位置不变：$\mathbb{P}(T_{\text{med}}(X) \le m_0) = 0.5$。
- **破坏的性质**：
  - **严重破坏一阶均值预报**：
    $$\mathbb{E}[T_{\text{med}}(X)] = m_0 + c(\mu_0 - m_0) = \mu_0 + (c - 1)(\mu_0 - m_0) \ne \mu_0$$
    **实证后果**：当模型欠自信（$c > 1$）且气温残差呈右偏（如高温波事件，$\mu_0 > m_0$）时，以中位数中心拉伸会**凭空将预测气温均值人为拔高 $(c - 1)(\mu_0 - m_0)$**。这直接推翻了此前 Stage 1/Stage 2 历经严格标定的 MOS 点预报与 $b_{30}$ 因果修正，引入人为系统性偏差。

#### 3. $\sigma_{\text{adj}}$ 的标定语义更支持哪个中心？
$s_{\text{oos}}$ 的法定数学定义为（D4 定案）：
$$s_{\text{oos}} \equiv \frac{\text{Var}(e_{\text{oos}})}{\overline{\sigma_{\text{eff}}^2}} = \frac{\frac{1}{N}\sum_{i=1}^N (T_{\text{actual}, i} - \mu_{\text{forecast}, i})^2}{\overline{\sigma_{\text{eff}}^2}}$$
- 残差 $e = T_{\text{actual}} - \mu_{\text{forecast}}$ **在定义上即为围绕条件期望（均值 $\mu$）的一阶离差，属于经典的 $L_2$ 范数损失**，而非围绕条件中位数的绝对离差（$L_1$ 范数）；
- 在集合资料同化先例中，Whitaker & Hamill (2002, Mon. Wea. Rev.) 明确指出乘性协方差膨胀（Multiplicative Covariance Inflation）必须严格施加在**集合均值（Ensemble Mean）**的扰动项上：$x_i \to \bar{x} + r(x_i - \bar{x})$，以防止破坏大气物理守恒量；
- **结论**：无论是 $L_2$ 统计语义、气象同化惯例，还是因果偏差守恒，均绝对强制支持**均值中心（Mean $\mu_0$）**。

---

### 问题 3：EVT_Hybrid 拼接结构在仿射变换下的行为

在 `src/modeling/resampling.py:691-750` 中，EVT_Hybrid 分布在物理空间 $X$ 的构造方式为：通过物理均值 $\mu_0$ 与标准差 $\sigma$，将标准化变量 $Z \sim \text{EVT\_Hybrid}(u_L, u_R, \xi_L, \beta_L, \xi_R, \beta_R)$ 映射到 $X = \mu_0 + \sigma Z$。其标准化结构为：
- 左尾（$z < u_L$）：广义帕累托分布（GPD），覆盖质量 $p_L = 0.05$；
- 核部（$u_L \le z \le u_R$）：截断并重缩放的高斯核，覆盖质量 $p_C = 0.90$；
- 右尾（$z > u_R$）：广义帕累托分布（GPD），覆盖质量 $p_R = 0.05$。

当施加均值中心仿射变换 $Y = \mu_0 + c(X - \mu_0) = \mu_0 + (c\sigma) Z$ 时，各组件的解析行为如下：

#### 1. 拼接阈值（Splicing Thresholds）
- **物理空间阈值**：
  $$T_L' = \mu_0 + c(T_L - \mu_0) = \mu_0 + (c\sigma) u_L, \quad T_R' = \mu_0 + c(T_R - \mu_0) = \mu_0 + (c\sigma) u_R$$
  物理拼接点随方差同比例线性外扩；
- **无量纲标准化空间阈值**：
  令标准化变量 $z_Y = \frac{Y - \mu_0}{c\sigma} = \frac{c\sigma Z}{c\sigma} = Z$。标准化空间下的阈值 $u_L, u_R$ **严格恒定不变**（即为 **Scheme B 冻结的经验拼接常数**）。

#### 2. 尾部累积概率质量（Tail Masses）
由于 $T(X)$ 为严格单调递增映射：
$$\mathbb{P}(Y < T_L') = \mathbb{P}\left(\mu_0 + c(X - \mu_0) < \mu_0 + c(T_L - \mu_0)\right) = \mathbb{P}(X < T_L) = 0.05$$
$$\mathbb{P}(Y > T_R') = \mathbb{P}(X > T_R) = 0.05$$
**左、右尾部质量精确保持 5% 与 5%，核部质量精确保持 90%，无任何概率泄漏或畸变。**

#### 3. 极值形状参数 $\xi$ 与尺度参数 $\beta$ 的行为
根据极值理论中的 Pickands-Balkema-de Haan 定理及 GPD 的位置-尺度族性质（Coles 2001, Ch. 2 & 3）：
若超额变量 $W = X - T_R \mid X > T_R \sim \text{GPD}(\xi, \beta_{\text{phys}})$，则缩放后的超额变量：
$$W' = Y - T_R' = c(X - T_R) = c W$$
其累积分布函数为：
$$\mathbb{P}(W' \le w) = \mathbb{P}\left(c W \le w\right) = \mathbb{P}\left(W \le \frac{w}{c}\right) = 1 - \left(1 + \frac{\xi (w/c)}{\beta_{\text{phys}}}\right)^{-1/\xi} = 1 - \left(1 + \frac{\xi w}{c \beta_{\text{phys}}}\right)^{-1/\xi}$$
由此可得解析推论：
1. **形状参数 $\xi$ 严格不变**：$\xi' \equiv \xi$（尾部衰减的重尾/轻尾指数与帕累托曲率由数据物理极值性质决定，不随坐标拉伸而改变）；
2. **物理尺度参数线性缩放**：$\beta'_{\text{phys}} = c \cdot \beta_{\text{phys}}$；
3. **标准化空间尺度参数恒定**：在标准化残差空间中，$\beta_z = \beta_{\text{phys}} / \sigma$。缩放后 $\beta'_z = \frac{\beta'_{\text{phys}}}{\sigma_{\text{new}}} = \frac{c \beta_{\text{phys}}}{c \sigma} = \beta_z$ **严格不变**。

#### 4. 结构关闭性结论
仿射变换后的分布**严格闭合于 EVT_Hybrid 族自身**。在工程实现上，**完全不需要重新拟合 EVT 或改变任何尾部参数**，只需将输入 CDF 算子的特征尺度从 $\sigma$ 替换为 $\sigma_{\text{adj}}$：
$$F_{Y}(y) = F_{\text{EVT\_Hybrid}}\left(\frac{y - \mu_0}{\sigma_{\text{adj}}}; \; u_L, u_R, \xi_L, \beta_{z,L}, \xi_R, \beta_{z,R}\right)$$

---

### 问题 4：方差膨胀的作用范围与口径对应关系

#### 1. 先验膨胀应作用于全先验方差还是残差部分？
**必须且只能作用于全先验方差 $\sigma_{\text{eff}}^2$。**

理由与数理推导：
在两阶段预报架构中，预测方差由环境确定性预报不确定性与集合扰动离散度联合构成：
$$\sigma_{\text{eff}}^2 = c_{\text{train}}^2 + d^2 \sigma_{\text{ens}}^2$$
样本外（OOS）的实际误差定义为真实气温与均值预报的离差：$e_{\text{oos}} = T_{\text{actual}} - \mu_{\text{forecast}}$。
根据大样本统计，样本外观测残差的总方差为 $\text{Var}(e_{\text{oos}})$。

根据 D4 裁决与 Gneiting et al. (2007) 的概率校准条件（Marginal Calibration / Spread-Error Consistency）：
$$s_{\text{oos}} \equiv \frac{\text{Var}(e_{\text{oos}})}{\overline{\sigma_{\text{eff}}^2}}$$
若使调整后的全先验方差在 OOS 期间满足方差无偏（即调整后方差比值恰好为 1）：
$$\frac{\text{Var}(e_{\text{oos}})}{\overline{\sigma_{\text{adj}}^2}} \equiv 1 \iff \overline{\sigma_{\text{adj}}^2} = \text{Var}(e_{\text{oos}}) = s_{\text{oos}} \cdot \overline{\sigma_{\text{eff}}^2}$$
因此，对单点盘中预测，其瞬时全方差的校准调整量必须为：
$$\sigma_{\text{adj}}^2(t) = s_{\text{oos}} \cdot \sigma_{\text{eff}}^2(t) \implies \sigma_{\text{adj}}(t) = \sqrt{\max(1.0, s_{\text{oos}})} \cdot \sigma_{\text{eff}}(t)$$

#### 2. 反证：若仅膨胀残差常数项 $c_{\text{train}}^2$ 的后果
若错误地将膨胀作用于加性残差项 $c^2 \to s_{\text{oos}} c^2$ 而保持 $d^2 \sigma_{\text{ens}}^2$ 不变，则调整后总方差为 $\sigma_{\text{wrong}}^2 = s_{\text{oos}} c^2 + d^2 \sigma_{\text{ens}}^2$。
其样本外期望为：
$$\overline{\sigma_{\text{wrong}}^2} = s_{\text{oos}} c^2 + d^2 \overline{\sigma_{\text{ens}}^2} < s_{\text{oos}} (c^2 + d^2 \overline{\sigma_{\text{ens}}^2}) = \text{Var}(e_{\text{oos}}) \quad (\text{当 } s_{\text{oos}} > 1)$$
**这将导致高集合离散度（高天气不确定性）的日子无法获得足够的方差补偿，模型依然处于显著的欠自信/过度自信失衡状态，违背方差校准初衷。**

#### 3. 口径对应关系汇总
$$\begin{array}{rcccl}
\text{样本外实测总离散度} & \text{Var}(e_{\text{oos}}) & \longleftrightarrow & s_{\text{oos}} \cdot \overline{\sigma_{\text{eff}}^2} & \text{样本外预测总离散度} \\
\text{盘中先验特征尺度} & \sigma_{\text{adj}} & \longleftrightarrow & \sqrt{\max(1.0, s_{\text{oos}})} \cdot \sigma_{\text{eff}} & \text{基准先验特征尺度}
\end{array}$$
该口径在代码库 `src/pricing/sigma_adj.py:88-109` 中被严格执行：`sigma_adj = math.sqrt(max(1.0, s_oos)) * sigma_eff`。

---

### 问题 5：设计候选、证据需求与失效边界评估

除了「均值中心仿射缩放（方案 A）」之外，学术与工程领域可能考虑的候选设计及其可行性评估如下：

#### 方案 A（基准推荐）：标准化 Z 空间尺度置换（Global Z-Scale Replacement）
- **机制**：保持离线拟合的所有无量纲形态参数（JSU 的 $\gamma, \delta, \xi, \lambda$；EVT 的 $u_L, u_R, \xi, \beta_z$）原样不动。在消费端求取分位数或累积概率时，直接代入 $z = \frac{x - \mu_0}{\sigma_{\text{adj}}}$。
- **优点**：
  1. 与现行 `scripts/audit_v2/reliability_v2.py` 和 `scripts/evaluate_p4_2019_settlement.py` 的代码逻辑 100% 吻合，无需调整工件反序列化接口；
  2. 保证了 $L_2$ 误差完全对齐与极端厚尾的形态闭合；
  3. 自由度消耗为 0，杜绝二次过拟合。
- **失效边界**：假定样本外的离散度误差在所有分位点上是**同比例缩放**的。如果实测极端尾部的发散速度远超中心核部（如高斯核匹配但尾部爆发），该方案仅能按比例整体拉宽，无法局部加厚极端尾部。

#### 方案 B：形态参数直接非线性形变（Parametric Shape Deformation）
- **机制**：不改变尺度参数 $\lambda$ 或 $\sigma_{\text{eff}}$，直接调整形态参数。例如在 JSU 中通过压缩 $\delta$（$\delta \to \delta / \sqrt{s_{\text{oos}}}$）来使分布整体变扁平；或在 EVT 中强行增加尾部指数 $\xi \to \xi + \Delta\xi$。
- **所需证据**：需要建立从一维标量 $s_{\text{oos}}$ 到高阶矩形变参数的解析双射函数，并证明 2019 OOS 残差的样本峰度与离线训练峰度存在显著的统计漂移（需要高阶矩置信区间检验）。
- **失效边界**：
  1. **参数强耦合**：JSU 中 $\delta$ 不仅决定方差，还与 $\gamma$ 高度非线性耦合决定偏度和峰度，单独修改 $\delta$ 会导致均值和偏度严重漂移；
  2. **矩崩溃风险**：对于 EVT，当 $\xi \ge 0.5$ 时方差发散（无穷大），任意上调 $\xi$ 极易击穿二阶矩存在性边界；
  3. **数据量匮乏**：在仅有一年（365天）OOS 样本的情况下，估计四阶矩形态形变的估计方差极大，属于典型的过拟合陷阱。

#### 方案 C：非参数 PIT 经验分位重映射（Non-parametric PIT/Quantile Recalibration）
- **机制**：借鉴统计保序回归或 Copula 变换，计算 OOS 样本的 PIT 值 $U_i = F_0(T_i)$，拟合经验校准曲线 $C(u) = \text{Isotonic}(U)$，在线输出为 $F_{\text{adj}}(x) = C(F_0(x))$。
- **所需证据**：需要 OOS 样本在各个概率分桶（尤其是 1%~5% 尾部分桶）具有充分的大样本覆盖度（尾部单桶有效样本量 $N_{\text{tail}} \ge 1000$）。
- **失效边界**：
  1. **样本极小**：2019 盲测仅约 365 个样本，5% 极端尾部仅有约 18 个点，无法构建平滑连续的非参数经验分位数阶梯；
  2. **阶跃伪影**：非参数阶梯函数会导致 Polymarket 2°F 狭窄价格档位上出现概率差分断崖或局部导数为零，导致定价死锁与做市阶梯跳折。

#### 方案 D：核-尾分立双膨胀（Dual-Scale Core/Tail Inflation）
- **机制**：对 EVT_Hybrid 模型，将 $s_{\text{oos}}$ 拆解为核部方差膨胀系数 $s_{\text{core}}$ 与尾部 GPD 尺度膨胀系数 $s_{\text{tail}}$。
- **所需证据**：需在 `physical_param_contract.json` 中扩展双重膨胀系数标准，并在校准工件中分别记录核部误差与超额极值误差。
- **失效边界**：一年盲测数据中超额极值事件（$|z| > 1.645$）仅十余次，无法稳定辨识 $s_{\text{tail}}$，极差的统计功效将导致极端天气盘口价格剧烈震荡。

---

### 总结建议

综上所述，无论是从 Johnson SU 的双参数尺度分解、Coles (2001) 极值仿射闭合性、Whitaker & Hamill (2002) 气象集合同化准则，还是代码库实际接口对齐角度：
**方案 A（均值中心仿射缩放，即在线以 $\sigma_{\text{adj}}$ 等效代换物理尺度）是唯一在数学上严格闭合、物理语义自洽且工程代价为零的标准解。**
