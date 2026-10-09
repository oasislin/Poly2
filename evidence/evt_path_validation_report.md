# P6-EVT-GUARD: EVT 代码路径离线预验证与缺陷审计报告 (Synthetic Validation & Defect Audit Report)

> **工单编号**: `P6-EVT-GUARD`  
> **验证类型**: 测试沙箱离线预验证（零改动生产脚本与冻结工件）  
> **测试执行套件**: [`tests/unit/verification/test_evt_path_validation.py`](../tests/unit/verification/test_evt_path_validation.py)  
> **报告生成时间**: 2026-10-09  
> **状态**: **发现重大结构性实现缺陷（暂停并呈报评审委员会裁决，严禁自行修改）**

---

## 一、 事项 1：EVT 门槛规格书逐字取证 (Statutory Specifications Extraction)

根据《预注册规格书》[`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md) 与现行审计脚本 [`scripts/audit_p4_reliability_v13b.py`](../scripts/audit_p4_reliability_v13b.py)，逐字核定 EVT 门槛与评估流程如下：

### 1. 激活门槛的精确定义
- **单项独立门槛（非同时满足）**:
  - `specs/preregistration-p4-active10-retrain.md` 2.3 节第 1 条：
    > “若 $|\text{Skew}| > 0.40$，激活 Johnson SU 拟合；若 $\text{Kurt}_{\text{excess}} > 1.0$，激活 EVT GPD 拟合。”
  - 判定逻辑为**单项独立触发**：偏度超标单独激活 JSU，峰度超标单独激活 EVT。
- **峰度数学定义**:
  - `specs/preregistration-p4-active10-retrain.md` 2.2 节：
    > “本规范硬性定义峰度为 Fisher 超额峰度 (Fisher's Excess Kurtosis)：$\text{Kurt}_{\text{excess}} = \frac{\mu_4}{\sigma^4} - 3$。代码实现严格绑定为：`scipy.stats.kurtosis(residuals, fisher=True, bias=False)`。”
  - 标准正态分布 $\text{Kurt}_{\text{excess}} \equiv 0.0$。激活门槛 $\text{Kurt}_{\text{excess}} > 1.0$ 对应原始 Pearson 峰度 $> 4.0$。
- **残差计算口径（偏度与峰度来源）**:
  - 代码来源为 `src/modeling/resampling.py:567, 571`：
    `z_scores = (train_work["resid_calib"] / train_work["sig_eff"]).dropna().to_numpy()`
    `skew_val = float(stats.skew(z_scores))`
    `kurt_fisher = float(stats.kurtosis(z_scores, fisher=True, bias=False))`
  - **明确结论**：用于门槛判断与分布拟合的残差是折内训练期 EMOS 校准后的**原始标准化残差** $z = (y - \mu) / \sigma_{\text{eff}}$，**绝非事后 Probit 重标残差** $z^* = \Phi^{-1}(u)$（Probit 重标残差需已知分布 $F$ 才能计算，仅用于事后审计检验）。

### 2. 触发后的评估流程
- **GPD 拟合尾部**:
  - 规格书 2.1 节第 3 条与 3.2 节第 3 条明确规定拟合**双尾**：
    > “中心 $[u_L, u_R]$ 为高斯核心，左尾 ($< u_L$) 与右尾 ($> u_R$) 分别拟合 GPD”；
    > “EVT 阈值分位数：严格锁定为 $u_L = 5\%$ 与 $u_R = 95\%$”；
    > “EVT 形状参数：$\xi < 0.5$（确保有限二阶矩，方差有限性存在）”。
- **阈值 $u$ 的选取**:
  - 代码 `src/modeling/resampling.py:597-598` 采用经验分位数：
    `u_l = float(np.percentile(z_scores, 5.0))`
    `u_r = float(np.percentile(z_scores, 95.0))`
- **BIC 竞争计分**:
  - 似然口径（规格书 3.3 节第 3 条）：
    > “EVT GPD 混合体在计算 BIC 时，必须为两侧超额极值条件对数似然显式加入 $\log(p_L) = \log(0.05)$ 与 $\log(p_R) = \log(0.05)$ 的混合权重因子，以确保拼接概率密度在全实数域 $\mathbb{R}$ 上严格满足 $\int_{-\infty}^\infty f(z) dz \equiv 1.00$”；
  - 参数惩罚项：$k = 4.0$（左尾 $\xi_L, \beta_L$ 2 个参数 + 右尾 $\xi_R, \beta_R$ 2 个参数，核心高斯标准化后无自由参数），惩罚项为 $4.0 \ln(N)$；
  - 录取门槛：$\Delta\text{BIC} = \text{BIC}_{\text{EVT}} - \text{BIC}_{\text{Gauss}} < -10.0$；
  - 平局决胜规则：当 JSU 与 EVT 同时触发且 $|\Delta\text{BIC}_{\text{JSU}} - \Delta\text{BIC}_{\text{EVT}}| \le 2.0$ 时，EVT 强制优先。

### 3. 规格书含糊之处与潜在争议清单 (Ambiguity Inventory)
1. **分位数阈值定义歧义（核心缺陷诱因）**：
   规格书第 117 行写道“`EVT 阈值分位数：严格锁定为 $u_L = 5\%$ 与 $u_R = 95\%$`”，但**未说明是高斯理论分位数还是样本经验分位数**：
   - 若解释为高斯理论分位数：则 $u_L \equiv \Phi^{-1}(0.05) = -1.64485$, $u_R \equiv \Phi^{-1}(0.95) = +1.64485$；
   - 若解释为样本经验分位数：代码写成 `np.percentile(z_scores, 5.0)`。但此时若残差为厚尾，$u_L$ 可能为 $-2.0$ 或更小，而核心公式未做截断高斯重标，直接导致 CDF 严重不连续！
2. **中心高斯核心截断归一化缺失**：
   规格书第 146 行要求“确保拼接概率密度在全实数域严格满足全域积分为 1.00”，但数学规范中未给出中心高斯部分 $z \in [u_L, u_R]$ 是否除以 $(\Phi(u_R) - \Phi(u_L))$ 的精确解析公式。

---

## 二、 事项 2：离线预验证测试结果表 (Synthetic Validation Results)

执行命令：
```bash
python -m pytest tests/unit/verification/test_evt_path_validation.py -v
```

### 1. 契约测试指标与两步机械判定

| 测试编号与名称 | 输入真值 / 测试条件 | 恢复值 / 实测观测值 | 误差 / 统计量 | 判定阈值 | 机械判定结论 |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **Contract 1: 门槛边界** | 样本超额峰度 $1.0500$ | 触发布尔值 `True` | 峰度 `= 1.0500` | 峰度 $> 1.0 \to \text{True}$ | **通过 (PASS)** |
| **Contract 1: 门槛边界** | 样本超额峰度 $0.9500$ | 触发布尔值 `False` | 峰度 `= 0.9500` | 峰度 $\le 1.0 \to \text{False}$ | **通过 (PASS)** |
| **Contract 2: 右尾参数恢复** | $\xi_{\text{true}} = 0.2200$ | $\hat{\xi} = 0.2382$ | $\Delta\xi = +0.0182 (+8.26\%)$ | $|\Delta\xi| < 0.05$ | **通过 (PASS)** |
| **Contract 2: 右尾尺度恢复** | $\beta_{\text{true}} = 1.1500$ | $\hat{\beta} = 1.1500$ | $\Delta\beta = +0.0000 (+0.00\%)$ | $|\Delta\beta| < 0.08$ | **通过 (PASS)** |
| **Contract 2: 左尾参数恢复** | $\xi_{\text{true}} = 0.1800$ | $\hat{\xi} = 0.1755$ | $\Delta\xi = -0.0045 (-2.53\%)$ | $|\Delta\xi| < 0.05$ | **通过 (PASS)** |
| **Contract 2: 左尾尺度恢复** | $\beta_{\text{true}} = 1.0500$ | $\hat{\beta} = 1.0562$ | $\Delta\beta = +0.0062 (+0.59\%)$ | $|\Delta\beta| < 0.08$ | **通过 (PASS)** |
| **Contract 3: 高斯样本防误选** | 标准正态样本 $N=3000$ | 峰度 `=-0.1020` (未触发)<br>强制 $\Delta\text{BIC} = -9.79$ | $\Delta\text{BIC} = -9.79$ | 门槛 $\Delta\text{BIC} < -10.0$ | **通过 (PASS)** |
| **Contract 4: BIC 惩罚项核查** | $N=2000, k=4$ 参数 | 惩罚项 $= 30.4036$ | $\ln(0.05) = -2.9957$ | $4.0 \ln(N)$ 逐字一致 | **通过 (PASS)** |
| **Contract 5: 理论分位点拼接** | $u_L, u_R = \pm 1.64485$ | $F(u_L^-)=0.05, F(u_L^+)=0.05$ | 跳跃 $\Delta = 0.0000$ | $|\Delta| < 10^{-5}$ | **通过 (PASS)** |
| **Contract 6: 经验分位点缺陷** | 厚尾经验分位数 $u_L=-2.0$ | $F(u_L^-)=0.05, F(u_L)=0.0228$ | 跳跃 $\Delta = -0.0272$ | 缺陷捕获 $\Delta < -0.02$ | **通过 (PASS - 缺陷捕获)** |

---

## 三、 重大缺陷技术详情分析与证据 (Defect Technical Dossier)

### 1. 缺陷定位
- **受影响函数**: [`src/modeling/resampling.py:674-695`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/modeling/resampling.py#L674-L695) 之 `evaluate_evt_tail_cdf` 与 `resampling.py:597-606` 之 `loglik_evt`；
- **缺陷现象**:
  当拟合数据存在厚尾时，代码第 597 行计算的经验分位数 $u_L = \text{percentile}(5.0)$ 偏离正态理论值（如 $u_L = -2.0$）。在 `evaluate_evt_tail_cdf` 中：
  ```python
  if z < u_l:
      val = 1.0 + xi_l * (u_l - z) / beta_l
      return 0.0 if val <= 0 else float(0.05 * (val ** (-1.0 / xi_l)))
  elif z > u_r:
      val = 1.0 + xi_r * (z - u_r) / beta_r
      return 1.0 if val <= 0 else float(1.0 - 0.05 * (val ** (-1.0 / xi_r)))
  return float(stats.norm.cdf(z))
  ```
  - 当 $z < u_L$ 时，随 $z \to u_L^-$，CDF 逼近 $0.05$；
  - 当 $z = u_L$ 时，代码直接进入第三分支返回 `stats.norm.cdf(u_L)`。若 $u_L = -2.0$，则 `norm.cdf(-2.0) = 0.02275`；
  - **严重后果 1（CDF 负向跳跃与非单调）**: 在 $z = u_L$ 处，CDF 发生高达 **$-2.72\%$ 的瞬时负向跳跃**，导致 $F(z)$ 非单调（违背概率累积函数公理）；
  - **严重后果 2（离散盘口负概率）**: 若交易离散档位边界跨越 $u_L$（如 $[-2.05, -1.95]$），计算的合约概率为 $F(-1.95) - F(-2.05) = 0.0256 - 0.0476 = \mathbf{-0.0220}$（**负概率！系统将输出非法下注信号并崩溃**）；
  - **严重后果 3（全域概率积分不归一）**: 密度函数在 $(-\infty, +\infty)$ 上的真实积分等于 $0.05 + 0.05 + (\Phi(u_R) - \Phi(u_L)) = 0.10 + 0.9545 = \mathbf{1.0545 \neq 1.00}$（违背测度归一性）。

### 2. 存量模型受影响范围实测排查
工程组对已落盘的 960 矩阵模型资产 [`evidence/p4_active10_climate_calibration.json`](../evidence/p4_active10_climate_calibration.json) 中胜出 EVT 的 4 个单元进行了排查：
- **KATL Spring**: $u_L = -1.6430, u_R = 1.5485$，右尾跳跃 $+1.08\%$，全域积分 $0.9891$；
- **KDAL Autumn**: $u_L = -1.8238, u_R = 1.4519$，左尾跳跃 **$-1.59\%$**，全域积分 $0.9926$；
- **KLAX Autumn**: $u_L = -1.5664, u_R = 1.9496$，右尾跳跃 **$-2.44\%$**，全域积分 $1.0158$；
- **KSFO Spring**: $u_L = -1.5987, u_R = 1.8031$，右尾跳跃 **$-1.43\%$**，全域积分 $1.0094$。

**实测结论**：存量 4 个 EVT 单元全部受到此缺陷影响，其拼接点均存在 $1.08\% \sim 2.44\%$ 的非连续跳跃！

---

## 四、 委员会裁决申请与后续行动

根据本工单硬性红线：“**若发现 EVT 实现存在缺陷：停下呈报缺陷详情，由委员会裁决修复方案——修复属于方法改动，封盘版本号机制届时启用，严禁 agent 自行修复后继续。**”

### 待裁决方案建议（供委员会审议）：
- **方案 A（理论分位数锚定法）**：
  将 $u_L$ 与 $u_R$ 严格锁定为标准正态分布的理论分位数 $u_L \equiv \Phi^{-1}(0.05) \approx -1.6448536$ 与 $u_R \equiv \Phi^{-1}(0.95) \approx +1.6448536$。在此定义下，高斯核心在 $[u_L, u_R]$ 的积分为 $0.9000$，全域积分严格恒等于 $1.0000$，左右两端跳跃严格为 $0$。
- **方案 B（条件高斯重标截断法）**：
  保持经验分位数 $u_L, u_R$ 不变，但将核心高斯 CDF/PDF 重标为：
  $F_{\text{core}}(z) = 0.05 + 0.90 \times \frac{\Phi(z) - \Phi(u_L)}{\Phi(u_R) - \Phi(u_L)}$，消除跳跃并恢复单调性与归一化。
- **方案 C（EVT 门槛冻结不启用）**：
  若 92 格中无任何格触发超额峰度 $> 1.0$，则在 92 格全网格跑数中保持现有代码不动，并在封盘文档中如实声明“EVT 代码路径存在拼接非单调缺陷，实战未触发，列入已知技术债务，真实盘接入前禁止激活”。

**当前操作状态**：已落盘证据报告，工作在此停下，等待人工验收及评审委员会下发裁决指令。
