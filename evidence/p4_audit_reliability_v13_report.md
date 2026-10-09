# P4 离散分桶可靠度审计法定报告 (v1.3 真物理分布 F 全量重跑版)

> ### 【前置法定审计三声明 (Mandatory Header Declarations)】
> 1. **当期规则回溯假设 (Current Rule Backcasting Assumption)**：
>    Historical validation period (2000-2018) objectively has no live Polymarket orderbook assets. All bin evaluations and settlement verdicts deterministically replay the 0.35 semantic routing specification (DiscreteBinEngine v1.3) and statutory Half-Up settlement rounding (ADR-0012) against full 13,740 validation station-days extracted strictly from 20-fold Block-CV out-of-fold prediction artifacts.
> 2. **规则版本依赖说明 (Rule Version Dependency)**：
>    This audit strictly depends on specification P4-AUDIT-RELIABILITY-v1.3 (2°F step size, even-integer grid lines, X.5 half-degree boundaries, 9-bin adsorbed window with center bin at slot 5, 11-bin mutually exclusive and collectively exhaustive structure). Any market structure change requires spec bump.
> 3. **真相源与审计透镜声明 (Ground Truth vs Audit Lens)**：
>    The underlying physics probability model is the non-linear distribution family F(y; mu, sigma, theta) winning the statutory in-fold competition (selected as the Johnson SU 4-parameter family, modulating higher-order skewness and kurtosis via Z = gamma + delta * asinh((z - xi)/lambda)). The 11-bin discrete grid probabilities are strictly integrated via analytical differencing over the true distribution function F, entirely eliminating any Gaussian symmetric degradation approximation. Production trading pricing integrates directly over F.

---

## 一、 审计执行环境与数据血统

- **规格版本**: `P4-AUDIT-RELIABILITY-v1.3`
- **验证样本量**: `13740` 站·日（严格取自 20 折 `cv_fold_0` 至 `cv_fold_19` 完整样本外验证块，全量覆盖）
- **数据血统映射**: 详见 `evidence/p4_audit_reliability_v13_lineage.json`（训练期数据零接触）
- **物理概率分布 $F$**: 严格还原逐折竞争选型胜出之 **Johnson SU 四参数非线性分布族**（彻底废除高斯降级近似）
- **网格几何参数**: 步长 2°F，偶数整数网格线，X.5 连续性边界，9 档吸附窗口使中心档严格居第 5 位，11 档完备
- **结算舍入规则**: 严格采用法定 `Half-Up` 舍入（防范 Python 原生 banker's rounding 偶数舍入偏差）

---

## 二、 “谱带 × 可交易窗口” 二维分列六元组与 Wilson 判定表 (真分布 F 积分)

### 1. 窗口内校准表 (In-Window Calibration —— 定价用 / 9 档合约区)
- **事件总容量**: `123660` 条
- **加权 ECE**: `0.0029` (0.29%)
- **Wilson 95% 置信区间覆盖率**: `50.00%`
- **逐带单调性违规数**: `0` 次

| 预测概率谱带 | 样本量 $N$ | 预测概率期望 $\bar{p}$ | 实际经验频率 $\bar{o}$ | 校准偏差 $|\bar{p} - \bar{o}|$ | 加权 ECE 贡献 | Brier 分数 | Wilson 95% CI 下限 | Wilson 95% CI 上限 | Wilson 覆盖判定 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `[0.00, 0.03)` | 35374 | `0.0152` | `0.0170` | `0.0019` | `0.0005` | `0.0167` | `0.0157` | `0.0184` | ❌ FAIL |
| `[0.03, 0.07)` | 22561 | `0.0476` | `0.0443` | `0.0033` | `0.0006` | `0.0422` | `0.0416` | `0.0470` | ❌ FAIL |
| `[0.07, 0.12)` | 16592 | `0.0936` | `0.0917` | `0.0020` | `0.0003` | `0.0830` | `0.0873` | `0.0961` | ✅ PASS |
| `[0.12, 0.18)` | 15671 | `0.1496` | `0.1561` | `0.0065` | `0.0008` | `0.1312` | `0.1504` | `0.1618` | ❌ FAIL |
| `[0.18, 0.25)` | 21813 | `0.2169` | `0.2168` | `0.0001` | `0.0000` | `0.1692` | `0.2113` | `0.2223` | ✅ PASS |
| `[0.25, 0.35)` | 11649 | `0.2826` | `0.2756` | `0.0070` | `0.0007` | `0.1994` | `0.2674` | `0.2837` | ✅ PASS |
| `[0.35, 0.50)` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |
| `[0.50, 1.00]` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |

### 2. 全分布校准表 (Full-Distribution Calibration —— 模型诚实度用 / 11 档全局区)
- **事件总容量**: `151140` 条
- **加权 ECE**: `0.0025` (0.25%)
- **Wilson 95% 置信区间覆盖率**: `50.00%`
- **逐带单调性违规数**: `0` 次

| 预测概率谱带 | 样本量 $N$ | 预测概率期望 $\bar{p}$ | 实际经验频率 $\bar{o}$ | 校准偏差 $|\bar{p} - \bar{o}|$ | 加权 ECE 贡献 | Brier 分数 | Wilson 95% CI 下限 | Wilson 95% CI 上限 | Wilson 覆盖判定 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `[0.00, 0.03)` | 62795 | `0.0118` | `0.0133` | `0.0014` | `0.0006` | `0.0130` | `0.0124` | `0.0142` | ❌ FAIL |
| `[0.03, 0.07)` | 22620 | `0.0476` | `0.0443` | `0.0033` | `0.0005` | `0.0422` | `0.0416` | `0.0469` | ❌ FAIL |
| `[0.07, 0.12)` | 16592 | `0.0936` | `0.0917` | `0.0020` | `0.0002` | `0.0830` | `0.0873` | `0.0961` | ✅ PASS |
| `[0.12, 0.18)` | 15671 | `0.1496` | `0.1561` | `0.0065` | `0.0007` | `0.1312` | `0.1504` | `0.1618` | ❌ FAIL |
| `[0.18, 0.25)` | 21813 | `0.2169` | `0.2168` | `0.0001` | `0.0000` | `0.1692` | `0.2113` | `0.2223` | ✅ PASS |
| `[0.25, 0.35)` | 11649 | `0.2826` | `0.2756` | `0.0070` | `0.0005` | `0.1994` | `0.2674` | `0.2837` | ✅ PASS |
| `[0.35, 0.50)` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |
| `[0.50, 1.00]` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |

---

## 三、 双尾质量机械诊断表 (Dual-Tail Mechanical Diagnostics)

### 1. 真实物理模型 $F$ 机械判定 (True Model F)

| 尾部区间 | 样本容量 $N$ | 期望命中数 $\sum p$ | 实际命中数 $\sum o$ | 平均预测 $\bar{p}$ | 实际频率 $\bar{o}$ | 放大倍数 (Obs/Exp) | Poisson 上尾 p 值 | 机械判定状态 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Left-Tail (< Window Lower Bound) [True Model F]** | 13740 | 59.74 | 40 | `0.0043` | `0.0029` | `0.67x` | `0.997188` | ✅ PASS |
| **Right-Tail (>= Window Upper Bound) [True Model F]** | 13740 | 148.97 | 191 | `0.0108` | `0.0139` | `1.28x` | `0.000531` | ⚠️ FLAG |

### 2. 真实模型 $F$ vs 降级高斯近似对比 (Ground Truth vs Proxy Impact)

| 评估口径 | 右尾实际命中数 | 右尾期望命中数 $\sum p$ | 放大倍数 (Obs/Exp) | Poisson 上尾 p 值 | 机械判定状态 | 形态还原结论 |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **真实物理分布 $F$ (Johnson SU)** | 191 | **148.97** | **1.28x** | `0.000531` | ⚠️ **FLAG** | 概率质量大幅还原 (+139% 期望命中)，紧贴实际厚尾 |
| **降级高斯近似 (Gaussian Proxy)** | 191 | **62.26** | **3.07x** | `0.000000` | ⚠️ **FLAG** | 高斯尾部衰减过快，虚假低估 3.07 倍 (严重失真) |

---

## 四、 峰度与尾部形态诊断 (Kurtosis & Tail Shape Diagnostics)

- **标准化残差统计量**: 均值 $\bar{z} = 0.0174$, 标准差 $s_z = 1.0154$
- **样本偏度 (Skewness)**: `0.6043` (正偏度，极端偏高温事件偏多)
- **样本超额峰度 (Excess Kurtosis)**: `2.4612` (Leptokurtic 尖峰肥尾，显著大于高斯理论值 0.0)
- **“肩胖顶矮尾瘦”形态复现判定**: `复现 (REPRODUCED)`

### 全量样本极端超越数对比 (Exceedance Comparison vs Gaussian Theory)

| 阈值条件 | 实际发生次数 | 实际发生率 | 高斯理论发生率 | 放大倍数 (Obs/Exp) |
| :--- | :---: | :---: | :---: | :---: |
| $|z| > 2.0$ (双侧 $2\sigma$) | 735 | `0.0535` | `0.0455` | `1.18x` |
| $|z| > 2.5$ (双侧 $2.5\sigma$) | 287 | `0.0209` | `0.0124` | `1.69x` |
| $z > +2.0$ (单侧极端高温) | 469 | `0.0341` | `0.0228` | `1.50x` |
| $z < -2.0$ (单侧极端低温) | 266 | `0.0194` | `0.0228` | `0.85x` |

---

## 五、 审计结论与机械判定

1. **设计意图忠实性**: 彻底废除高斯降级近似，严格按 `specs/preregistration-p4-active10-retrain.md` 规范还原逐折竞争胜出之 Johnson SU 四参数非线性分布 $F$；
2. **全量血统链完整性**: 13,740 个样本外验证日 100% 映射至 20 折验证预测工件，逐日 SHA 钉死，训练期数据零接触；
3. **定价区校准质量**: 在真分布 $F$ 积分下，窗口内可交易区加权 ECE 为 **`0.29%`**，Wilson 覆盖率为 **`50.00%`**；
4. **右尾泊松显著性与形态还原**: 真实分布 $F$ 使右尾期望命中数自降级高斯的 62.26 恢复至 **`148.97`**（实际命中 191，比率自 3.07x 收窄至 **1.28x**）；Poisson 上尾 $p = 0.000531$，按事先钉死之机械阈值 ($p < 0.05$) 判定为 **`FLAG`**；
5. **形态诊断呈报**: 全样本残差超额峰度为 `+2.4612`，偏度为 `+0.6043`，物理模型保持不动，客观呈报入档。
