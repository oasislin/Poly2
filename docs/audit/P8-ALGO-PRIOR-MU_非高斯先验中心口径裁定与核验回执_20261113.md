# 算法审阅回执：非高斯格先验中心 μ₀ 口径裁定与核验回执（2026-11-13）

> **归档类型**：B 线算法审阅与理论复核回执（只读/对账级）  
> **关联议题**：P8-ALGO-REVIEW 待确认事项登记册 B-1 项增补与第二件规格更新  
> **落盘日期**：2026-11-13  
> **裁定状态**：业主已批准（法定先验中心 $\mu_0 \equiv \mu_{\text{calib}} = a + b \cdot \mu_{\text{ens}} + b_{30}$）

---

### 一、核心裁定与规格收口

1. **法定先验中心唯一口径**：
   $$\mu_0 \equiv \mu_{\text{calib}} = a + b \cdot \mu_{\text{ens}} + b_{30}$$
   作为全链唯一法定统一锚，贯穿以下四处消费端：
   - 取法 C 的剩余均值锚：$\mu_R(t, m) = \left[\frac{t_{\text{close}} - t}{t_{\text{close}} - t_{\text{open}}}\right]^+ \cdot \max(0, \mu_0 - m)$；
   - $\sigma_{\text{adj}}$ 仿射拉伸中心（登记册 B-1）：$T(X) = \mu_0 + c \cdot (X - \mu_0)$，其中 $c = \sqrt{\max(1.0, s_{\text{oos}})}$；
   - 无观测分支的先验分布 CDF 代入点：$z = (x - \mu_0) / \sigma$；
   - $\eta_s$ 标定器的基准方差同源点：$\sigma_0(d) = \sqrt{\max(1.0, s_{\text{oos}})} \cdot \sigma_{\text{eff}}(d)$。
2. **B-1 增补锚定语义**：
   变换保持“锚-形状分解” $X = \mu_0 + \sigma \cdot Z$ 之 $(\mu_0, Z)$ 不变，仅 $\sigma \to \sigma_{\text{adj}}$；
   - 高斯格退化为严格均值守恒；
   - 非高斯格 $\mathbb{E}[T(X)] = \mu_0 + \sigma_{\text{adj}} \cdot \mathbb{E}[Z]$，偏态离差期望随尺度同比例放大，系 $s_{\text{oos}}$ 校准语义（标定锚 $e = y - \mu_{\text{calib}}$）的忠实执行。
3. **EVT 伪影处置记录**：
   $\mathbb{E}[Z] \ne 0$ 系两尾分立拟合的无约束伪影，在锚定语义下无害；不在族拟合阶段加均值守恒约束，不改 Scheme B，不重算 2019 基准——防止顺手优化。
4. **第二件规格更新**：
   `prior_mu` 不入静态字段（manifest 已有 $a, b, b_{30}$，消费端组装修）；矩层仅 $\sigma$ 侧（`prior_sigma` / `moment_source` / `moment_note`），原字段规格其余不变。

---

### 二、现役代码事实查询（100% 对齐）

- `scripts/audit_v2/reliability_v2.py:129, 136, 193`：严格使用 `mu_calib` 作为误差定义基准与 CDF 算子代换中心；
- `scripts/evaluate_p4_2019_settlement.py:286-296, 307`：构造 `mu_calib = a + b * ens_mean + b30`，直接传入 `construct_model_cdf` 作为中心；
- `src/prediction/static_predictor.py:10, 42`：点预报 `mu` 严格定义为回归方程。全仓从未读取或计算族解析均值 $\mu_{\text{family}}$。

---

### 三、标准化空间期望解析推导与参数依赖

#### 1. Johnson SU 族解析期望（排版修正版）
$$Z = \xi + \lambda \sinh\left(\frac{U - \gamma}{\delta}\right), \quad U \sim \mathcal{N}(0, 1)$$
利用对数正态矩母函数，解析期望闭式解为：
$$\mathbb{E}[Z] = \xi - \lambda \cdot \exp\left(\frac{1}{2\delta^2}\right) \sinh\left(\frac{\gamma}{\delta}\right)$$
MLE 估计时位置参数 $\xi$ 自动吸收偏度位移 $\lambda e^{1/(2\delta^2)} \sinh(\gamma/\delta)$，使得 $\mathbb{E}[Z] \approx 0$（实测中位数仅 0.0043，最大仅 0.0150）。

#### 2. EVT_Hybrid 族解析期望
在 Scheme B 拼接结构（90% 截断正态核 + 左右各 5% GPD 尾）下：
$$\mathbb{E}[Z] = 0.90 \left(\frac{\phi(u_L) - \phi(u_R)}{\Phi(u_R) - \Phi(u_L)}\right) + 0.05 \left(u_L - \frac{\beta_L}{1 - \xi_L}\right) + 0.05 \left(u_R + \frac{\beta_R}{1 - \xi_R}\right)$$
因左右尾 GPD 系分立独立拟合，无均值约束，尾部厚度非对称性导致 $\mathbb{E}[Z]$ 出现轻微正偏（实测达到 $+0.0858$）。

---

### 四、数值实测分布

1. **2019 年全年盲测集（6,988 个预测行实测）**：
   - $\min = 0.0023^\circ\text{F}$
   - $\text{median} = 0.0168^\circ\text{F}$
   - $\text{mean} = 0.0210^\circ\text{F}$
   - $\max = 0.1545^\circ\text{F}$
2. **JSU 族（23 个基础气候格位）**：
   - 物理差值中位数仅 $0.017^\circ\text{F}$，最大仅 $0.06^\circ\text{F} \sim 0.09^\circ\text{F}$，普遍严格 $< 0.1^\circ\text{F}$，影响完全可忽略。
3. **EVT_Hybrid 族（4 个基础气候格位）**：
   - 物理差值在 $\sigma = 4.0^\circ\text{F}$ 下为 $0.20^\circ\text{F} \sim 0.34^\circ\text{F}$，在 $\sigma = 6.0^\circ\text{F}$ 下达 $0.30^\circ\text{F} \sim 0.51^\circ\text{F}$。
   - 锁定法定中心为 $\mu_{\text{regression}}$ 彻底隔绝了 EVT 分立拟合伪影对点预报中枢的侵蚀。
