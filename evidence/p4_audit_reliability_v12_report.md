# P4 离散分桶可靠度审计法定报告 (v1.2 数据血统重钉版)

> ### 【前置法定审计三声明 (Mandatory Header Declarations)】
> 1. **当期规则回溯假设 (Current Rule Backcasting Assumption)**：
>    Historical validation period (2000-2018) objectively has no live Polymarket orderbook assets. All bin evaluations and settlement verdicts deterministically replay the 0.35 semantic routing specification (DiscreteBinEngine v1.2) and statutory Half-Up settlement rounding (ADR-0012) against 600 validation days extracted strictly from 20-fold Block-CV out-of-fold prediction artifacts.
> 2. **规则版本依赖说明 (Rule Version Dependency)**：
>    This audit strictly depends on specification P4-AUDIT-RELIABILITY-v1.2 (2°F step size, even-integer grid lines, X.5 half-degree boundaries, 9-bin adsorbed window with center bin at slot 5, 11-bin mutually exclusive and collectively exhaustive structure). Any market structure change requires spec bump.
> 3. **真相源与审计透镜声明 (Ground Truth vs Audit Lens)**：
>    The underlying continuous probability distribution F(mu, sigma) is the sole physics ground truth; the 11-bin discrete grid is merely an evaluation lens for contract settlement and market mapping. Production trading pricing integrates directly over F, free from discrete resolution constraints.

---

## 一、 审计执行环境与数据血统

- **规格版本**: `P4-AUDIT-RELIABILITY-v1.2`
- **验证样本量**: `600` 站·日（严格取自 20 折 `cv_fold_XX_predictions.parquet` 样本外验证块，每折 30 天）
- **数据血统映射**: 详见 `evidence/p4_audit_reliability_v12_lineage.json`（训练期数据零接触）
- **网格几何参数**: 步长 2°F，偶数整数网格线，X.5 连续性边界，9 档吸附窗口使中心档严格居第 5 位，11 档完备
- **结算舍入规则**: 严格采用法定 `Half-Up` 舍入（防范 Python 原生 banker's rounding 偶数舍入偏差）

---

## 二、 “谱带 × 可交易窗口” 二维分列六元组与 Wilson 判定表

### 1. 窗口内校准表 (In-Window Calibration —— 定价用 / 9 档合约区)
- **事件总容量**: `5400` 条
- **加权 ECE**: `0.0074` (0.74%)
- **Wilson 95% 置信区间覆盖率**: `83.33%`
- **逐带单调性违规数**: `0` 次

| 预测概率谱带 | 样本量 $N$ | 预测概率期望 $\bar{p}$ | 实际经验频率 $\bar{o}$ | 校准偏差 $|\bar{p} - \bar{o}|$ | 加权 ECE 贡献 | Brier 分数 | Wilson 95% CI 下限 | Wilson 95% CI 上限 | Wilson 覆盖判定 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `[0.00, 0.03)` | 1341 | `0.0143` | `0.0134` | `0.0009` | `0.0002` | `0.0132` | `0.0073` | `0.0196` | ✅ PASS |
| `[0.03, 0.07)` | 935 | `0.0472` | `0.0342` | `0.0129` | `0.0022` | `0.0335` | `0.0226` | `0.0459` | ❌ FAIL |
| `[0.07, 0.12)` | 813 | `0.0944` | `0.0849` | `0.0095` | `0.0014` | `0.0775` | `0.0657` | `0.1040` | ✅ PASS |
| `[0.12, 0.18)` | 851 | `0.1502` | `0.1669` | `0.0167` | `0.0026` | `0.1388` | `0.1418` | `0.1919` | ✅ PASS |
| `[0.18, 0.25)` | 1096 | `0.2101` | `0.2089` | `0.0012` | `0.0002` | `0.1655` | `0.1849` | `0.2330` | ✅ PASS |
| `[0.25, 0.35)` | 364 | `0.2648` | `0.2747` | `0.0099` | `0.0007` | `0.1993` | `0.2289` | `0.3206` | ✅ PASS |
| `[0.35, 0.50)` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |
| `[0.50, 1.00]` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |

### 2. 全分布校准表 (Full-Distribution Calibration —— 模型诚实度用 / 11 档全局区)
- **事件总容量**: `6600` 条
- **加权 ECE**: `0.0064` (0.64%)
- **Wilson 95% 置信区间覆盖率**: `83.33%`
- **逐带单调性违规数**: `0` 次

| 预测概率谱带 | 样本量 $N$ | 预测概率期望 $\bar{p}$ | 实际经验频率 $\bar{o}$ | 校准偏差 $|\bar{p} - \bar{o}|$ | 加权 ECE 贡献 | Brier 分数 | Wilson 95% CI 下限 | Wilson 95% CI 上限 | Wilson 覆盖判定 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `[0.00, 0.03)` | 2540 | `0.0097` | `0.0110` | `0.0013` | `0.0005` | `0.0109` | `0.0070` | `0.0151` | ✅ PASS |
| `[0.03, 0.07)` | 936 | `0.0472` | `0.0342` | `0.0130` | `0.0018` | `0.0335` | `0.0225` | `0.0458` | ❌ FAIL |
| `[0.07, 0.12)` | 813 | `0.0944` | `0.0849` | `0.0095` | `0.0012` | `0.0775` | `0.0657` | `0.1040` | ✅ PASS |
| `[0.12, 0.18)` | 851 | `0.1502` | `0.1669` | `0.0167` | `0.0021` | `0.1388` | `0.1418` | `0.1919` | ✅ PASS |
| `[0.18, 0.25)` | 1096 | `0.2101` | `0.2089` | `0.0012` | `0.0002` | `0.1655` | `0.1849` | `0.2330` | ✅ PASS |
| `[0.25, 0.35)` | 364 | `0.2648` | `0.2747` | `0.0099` | `0.0005` | `0.1993` | `0.2289` | `0.3206` | ✅ PASS |
| `[0.35, 0.50)` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |
| `[0.50, 1.00]` | 0 | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | ✅ PASS |

---

## 三、 双尾质量机械诊断表 (Dual-Tail Mechanical Diagnostics)

| 尾部区间 | 样本容量 $N$ | 期望命中数 $\sum p$ | 实际命中数 $\sum o$ | 平均预测 $\bar{p}$ | 实际频率 $\bar{o}$ | Poisson 上尾 p 值 | 零方差退化/下溢计数 | 机械判定状态 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Left-Tail (< Window Lower Bound)** | 600 | 2.75 | 1 | `0.0046` | `0.0017` | `0.936388` | 0 | ✅ PASS |
| **Right-Tail (>= Window Upper Bound)** | 600 | 2.67 | 9 | `0.0044` | `0.0150` | `0.001758` | 0 | ⚠️ FLAG |

---

## 四、 峰度与尾部形态诊断 (Kurtosis & Tail Shape Diagnostics)

- **标准化残差统计量**: 均值 $\bar{z} = 0.0201$, 标准差 $s_z = 1.0233$
- **样本偏度 (Skewness)**: `0.6026` (正偏度，极端偏高温事件不对称多发)
- **样本超额峰度 (Excess Kurtosis)**: `1.3669` (Leptokurtic 尖峰肥尾，显著大于高斯理论值 0.0)
- **“肩胖顶矮尾瘦”形态复现判定**: `复现 (REPRODUCED)`

### 极端超越数对比 (Exceedance Comparison vs Gaussian Theory)

| 阈值条件 | 实际发生次数 | 实际发生率 | 高斯理论发生率 | 放大倍数 (Obs/Exp) |
| :--- | :---: | :---: | :---: | :---: |
| $|z| > 2.0$ (双侧 $2\sigma$) | 30 | `0.0500` | `0.0455` | `1.10x` |
| $|z| > 2.5$ (双侧 $2.5\sigma$) | 13 | `0.0217` | `0.0124` | `1.75x` |
| $z > +2.0$ (单侧极端高温) | 21 | `0.0350` | `0.0228` | `1.54x` |
| $z < -2.0$ (单侧极端低温) | 9 | `0.0150` | `0.0228` | `0.66x` |

---

## 五、 审计结论与机械判定

1. **血统链完整性**: 600 个验证日 100% 映射至 20 折验证预测工件，逐日 SHA 钉死，训练期数据零接触；
2. **定价区校准质量**: 窗口内可交易区加权 ECE 为 **`0.74%`**，Wilson 覆盖率为 **`83.33%`**；
3. **右尾泊松显著性判定**: 期望命中数 `2.67`，实际命中数 `9`，Poisson 上尾 $p = 0.001758$，按机械阈值 ($p < 0.05$) 判定为 **`FLAG`**；
4. **形态诊断呈报**: 残差超额峰度为 `+1.3669`，偏度为 `+0.6026`，确凿复现“肩胖顶矮尾瘦”形态，物理模型保持不动，客观呈报入档。
