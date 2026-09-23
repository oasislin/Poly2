# ADR-0015：废除高斯 EMOS 气候方差加法项、确立物理方差底座与离散校准门禁

- **状态**: APPROVED (Review R5 最终闭环)
- **提出日期**: 2026-09-23
- **决策者**: 架构委员会、统计独立审查方、Polymarket 气象量化工程组
- **关联文档**: ADR-0001 (SUPERSEDED), ADR-0010 (SUPERSEDED / VOID)

---

## 1. 背景与问题陈述

既有高斯 EMOS（Ensemble Model Output Statistics）实现中，在条件方差拟合上引入了逐日气候学平滑方差 $\sigma_{\text{clim}}^2$ 作为直接加法项，导致预测分布的期望方差恒大于物理无条件总方差，造成不可逆的系统性过离散（Over-dispersion）与倒 U 型 PIT 拱形伪缺陷。

---

## 2. 核心架构与数学决策

### 2.1 逐字引用被废止历史公式与源码 Blob 锚定
- **被废止代码来源**: `src/modeling/gaussian_emos.py` (Commit `608731f` / `81168c7`)
- **Git Blob Hash**: `58d713ce75c17b29e37e931bb05da1569429c88f`
- **历史代码原句逐字引用**:
  ```python
  variance = (self.c ** 2) + (self.d ** 2) * ens_var + clim_var
  ```
- **历史公式定性**: 历史代码实为 $\sigma^2 = c^2 + d^2 \cdot S_{\text{ens}}^2 + \sigma^2_{\text{clim}}$，而非 $(c + d \cdot S)^2$。
- **废止裁定**: 正式彻底废除 `clim_var` 加法项，恢复标准 Gneiting (2005) EMOS 方程：
  $$\sigma_f^2 = c^2 + d^2 \cdot S_{\text{ens}}^2$$

### 2.2 Dawid 弱无偏校准不等式严格证明
根据全方差定理：
$$\text{Var}(T) = \mathbb{E}[\text{Var}(T \mid \mathcal{F})] + \text{Var}(\mathbb{E}[T \mid \mathcal{F}]) = \mathbb{E}[\sigma_f^2] + \text{Var}(\mu_f)$$
因预测均值方差非负（$\text{Var}(\mu_f) \ge 0$），概率校准系统必须满足：
$$\mathbb{E}[\sigma_f^2] \le \text{Var}(T) = \sigma_{\text{clim}}^2$$
加法项导致 $\mathbb{E}[\sigma_{\text{corrupted}}^2] > \sigma_{\text{clim}}^2$，在第一原理上必然不可校准。

### 2.3 物理方差底座 $\sigma_{\text{inst}}$ 权威引用与物理尺度
- **权威文献引用**: *NOAA / FAA / DOD Automated Surface Observing System (ASOS) User's Guide (1998)*, Section 3.1.1 "Temperature Sensor".
- **传感器出厂物理规格**: 全美 ASOS 气象台站标准配置 1088 型三线白金电阻温度计（Platinum Resistance Thermometer, PRT），在 $-50^\circ\text{C} \sim +50^\circ\text{C}$ 量程内的仪器精度规格为 $\pm 0.9^\circ\text{F} \ (\pm 0.5^\circ\text{C})$。
- **物理尺度与报告粒度统一性**:
  - 传感器仪器精度极限: **$\sigma_{\text{inst}} = 0.9^\circ\text{F}$**（严格对齐引文 $\pm 0.9^\circ\text{F}$，彻底消除 $0.5^\circ\text{C} \leftrightarrow 0.5^\circ\text{F}$ 单位混淆错位）；
  - METAR 报文发布的量化舍入步长: 整度 $1^\circ\text{F}$ 或 $0.1^\circ\text{C}$；
  - 确立以数据驱动的 $\min(\hat{c})$ 或 $\sigma_{\text{inst}} = 0.9^\circ\text{F}$ 作为方差参数下限，绝不再人工拍脑袋设定无物理依据的宏观大底座。

### 2.4 法定门禁层级规范与废除 BH 条款
- **废除条款**: 彻底移除 Benjamini-Hochberg (BH) 假发现率多重假设检验条款（避免在离散分桶下的多重假设检验谬误）；
- **主门禁（Primary Rejection Gates）**:
  1. 随机化 PIT 均匀性 Kolmogorov-Smirnov 检验: $p_{\text{KS}} \ge 0.05$（严守单调无偏）；
  2. 加权期望校准误差 (Weighted ECE): $\text{ECE} \le 3.0\%$（法定硬门禁，5% 提议正式作废回滚）；
- **辅助诊断（Auxiliary Diagnostics）**:
  1. 去偏分层方差比 F 检验: 必须按 $\sigma_f$ 十分位数分层调用，禁止全年池化；
  2. 加权 ECE bootstrap 95% 置信区间；
  3. 20 分桶 Wilson 95% 置信区间可靠度图目视诊断。

### 2.5 夹具参数本源注记 (T-3 调取令合规)
- **参数来源定性**: 测试夹具 `tests/test_closure_regression.py` 中采用的历史输入数值（$\text{bias}=2.89, \sigma_f=2.35, \sigma_r=4.39, \text{MAE}=3.53$ 等）**derive from a provenance-invalidated log; retained for closure-testing only, not as empirical reference**。
- **门禁保护**: 夹具作为检验度量代码内部数理闭包的逆向对抗测试永久保留；若重算后需用真实 2019 统计值替换夹具输入，必须走正式门禁变更留痕流程，严禁静默替换。
