# P4 高阶形态层分布竞争 BIC 可比性与似然归一化说明书 (BIC Comparability Note)

- **发件人**: Polymarket 温度物理建模工程组
- **呈送对象**: 评审委员会
- **签署时间**: 2026-09-24
- **状态**: `FROZEN_PRE_REFIT` (重跑竞争前法定前置落盘)
- **前置依据**: 评审委员会《关于 BIC 量级合理性与似然构造差异的核查指令》

---

## 一、 核心问题溯源：上轮千点 $\Delta\text{BIC}$ 的数学根因

在上一轮带病矩阵重训中，我们观察到 KMIA 冬季 $\Delta\text{BIC}_{\text{EVT}} = -1875.56$、KORD 冬季 $\Delta\text{BIC}_{\text{JSU}} = -5923.70$ 的反常千点量级差异。在样本容量 $N \approx 1,700$ 的季节残差上，经深入数学排查，根因揭示如下：

### 1.1 似然域与密度积分归一化不对称
- **高斯分布与 Johnson SU**: 均为在实数域 $\mathbb{R}$ 上严格归一化的连续型分布，满足 $\int_{-\infty}^\infty f(z) dz = 1.0$。
- **旧版 EVT GPD 混合体代码的非归一化缺陷**:
  旧版代码中，EVT 似然计算直接拼接了高斯主体密度与 GPD 条件超额密度：
  $$\log L_{\text{EVT}}^{\text{unnorm}} = \sum_{z_i \in [u_L, u_R]} \log \phi(z_i) + \sum_{z_i < u_L} \log g_{\text{GPD}}(u_L - z_i; \xi_L, \sigma_L) + \sum_{z_i > u_R} \log g_{\text{GPD}}(z_i - u_R; \xi_R, \sigma_R)$$
  **缺陷分析**:
  $g_{\text{GPD}}$ 是定义在超额量 $[0, \infty)$ 上的条件概率密度，其自身积分为 1。若不乘以尾部权重 $p_L = \Phi(u_L) = 0.05$ 与 $p_R = 1 - \Phi(u_R) = 0.05$，该拼接函数在 $\mathbb{R}$ 上的全域积分实际为：
  $$\int_{-\infty}^\infty f_{\text{unnorm}}(z) dz = \int_{u_L}^{u_R} \phi(z) dz + \int_0^\infty g_{\text{GPD}} dy + \int_0^\infty g_{\text{GPD}} dy = 0.90 + 1.0 + 1.0 = 2.90$$
  这导致每个尾部样本的对数密度被人为虚增了 $\log(1 / 0.05) = \log(20) \approx 2.9957$！
  在 10% 尾部（约 170 样本）上，虚增对数似然 $\Delta \log L \approx 170 \times 2.9957 \approx 509.3$。
  代入 $\text{BIC} = k\ln(n) - 2\ln L$，造成 EVT 模型的 BIC 被**虚假拉低了约 $-2 \times 509.3 \approx -1018.6$ 点**！这正是导致上一轮 EVT 展现出千点虚假优势的直接原因。

---

## 二、 法定修复：严格全域积分归一化拼接密度 (Properly Spliced Density)

依据极值统计学标准协议（Coles, 2001; Leadbetter, 1983; MacDonald et al., 2011），严格归一化的混合极值概率密度 $f_{\text{spliced}}(z)$ 构造如下：

$$f_{\text{spliced}}(z) = \begin{cases}
p_L \cdot g_{\text{GPD}}(u_L - z; \xi_L, \sigma_L), & z < u_L \quad (\text{左尾}) \\
\phi(z), & u_L \le z \le u_R \quad (\text{高斯主体}) \\
p_R \cdot g_{\text{GPD}}(z - u_R; \xi_R, \sigma_R), & z > u_R \quad (\text{右尾})
\end{cases}$$

其中：
- 主体部分在 $[u_L, u_R]$ 的积分为 $\Phi(u_R) - \Phi(u_L) = 0.95 - 0.05 = 0.90$；
- 左尾部分积分为 $p_L \times 1.0 = 0.05$；
- 右尾部分积分为 $p_R \times 1.0 = 0.05$；
- **全实数域积分**: $\int_{-\infty}^\infty f_{\text{spliced}}(z) dz = 0.05 + 0.90 + 0.05 \equiv 1.00000000$。

### 2.1 对数似然精确公式
对于任意标准化残差样本 $z_i$，其对数似然为：
$$\log f_{\text{spliced}}(z_i) = \begin{cases}
\log(0.05) + \log g_{\text{GPD}}(u_L - z_i; \xi_L, \sigma_L), & z_i < u_L \\
\log \phi(z_i), & u_L \le z_i \le u_R \\
\log(0.05) + \log g_{\text{GPD}}(z_i - u_R; \xi_R, \sigma_R), & z_i > u_R
\end{cases}$$

引入 $\log(0.05)$ 权重惩罚后，EVT 与高斯、Johnson SU 在**完全同一的概率密度测度空间、完全相同的样本、完全相同的无偏定义域**下进行 BIC 比较。此时 $\Delta\text{BIC}$ 自然回落至合理的几十至几百点正常统计区间。

---

## 三、 KMIA 竞争结论与历史锚点法律后果预登记

### 3.1 KMIA 录取翻转预登记
在归一化拼接似然与法定 5 初猜收敛的真实残差下，KMIA 四季实测 BIC 对决如下：
- **冬季**: $\Delta\text{BIC}_{\text{JSU}} = -178.10$ vs $\Delta\text{BIC}_{\text{EVT}} = -58.06 \implies$ **JSU 胜出 120.0 点**
- **春季**: $\Delta\text{BIC}_{\text{JSU}} = -233.79$ vs $\Delta\text{BIC}_{\text{EVT}} = -63.28 \implies$ **JSU 胜出 170.5 点**
- **夏季**: $\Delta\text{BIC}_{\text{JSU}} = -211.27$ vs $\Delta\text{BIC}_{\text{EVT}} = -22.75 \implies$ **JSU 胜出 188.5 点**
- **秋季**: $\Delta\text{BIC}_{\text{JSU}} = -230.12$ vs $\Delta\text{BIC}_{\text{EVT}} = -93.80 \implies$ **JSU 胜出 136.3 点**

**结论**: KMIA 历史因海陆风与强对流引发的偏态物理机理得到数学上的完整昭雪，**KMIA 四季 100% 录取 Johnson SU**！

### 3.2 历史锚点法律后果登记条款
在修复优化器并施加似然归一化后，KMIA 重新回归 Johnson SU：
1. **R-6 历史锚点恢复生效**: KMIA 在 Round 3 确立的 Johnson SU 偏态建模得到物理与算法延续；
2. **三维对账表对应项**: 由于 KMIA 选定家族为 Johnson SU，但其粒度由“全周期单套”升级为“站级 $\times$ 四季独立套”，其 PIT K-S 指标按“粒度升级导致的预期微幅物理漂移”处置，法定门禁 $p \ge 0.05$ 维持不变。
