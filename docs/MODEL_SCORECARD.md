# MODEL_SCORECARD.md - Active 10 站标的模型体检四维预注册指标与定级门禁体系

**工单来源**：`P7-W2-SHORTLOOP-R1` 任务 4 预注册门禁  
**生效范围**：全量 Active 10 交易站点（`KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS`）之所有已审计/待审计时效（00h, 06h, 12h, 18h）及标的（TMax / TMin）  
**不可篡改约束**：本文件一经提交立即锁定，运行期严禁动态上调、放宽或修饰任何数值阈值。判定严格遵守短板定级（Lowest-Pillar Decides）与机械两步比较原则。

---

## 1. 预注册四维体检指标与绿/黄/红阈值矩阵

| 评估维度 (Metric Dimension) | 指标定义与统计口径 | 🟢 绿级 (Green: 正常准入) | 🟡 黄级 (Yellow: 带旗收缩) | 🔴 红级 (Red: 禁开新仓) | 违规/失效判定逻辑 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **维度 1：校准 ECE**<br>(Calibration ECE) | 20 桶概率加权期望校准误差 (Weighted ECE over 20-bin Block-CV) | $\text{ECE} \le 0.0100$ | $0.0100 < \text{ECE} \le 0.0200$ | $\text{ECE} > 0.0200$ | 超出 0.0200 或缺少 20 折 Block-CV 证据直接判红 |
| **维度 2：预测偏差 Bias**<br>(Mean Systematic Bias) | 样本均值预测偏差（℉，带符号）：$\mathbb{E}[\hat{y} - y]$ | $|\text{Bias}| \le 0.50^\circ\text{F}$ | $0.50^\circ\text{F} < |\text{Bias}| \le 1.00^\circ\text{F}$ | $|\text{Bias}| > 1.00^\circ\text{F}$ | 绝对偏差超过 1.00°F 判红；带符号记录方向 |
| **维度 3：CRPS 技巧分**<br>(CRPSS vs Climatology) | 相较于气候学基线的连续分级概率技巧分：$1 - \frac{\text{CRPS}_{\text{model}}}{\text{CRPS}_{\text{clim}}}$ | $\text{CRPSS} \ge 0.150$ | $0.050 \le \text{CRPSS} < 0.150$ | $\text{CRPSS} < 0.050$ | 技巧分低于 5%（相比气候底座几乎无增益）判红 |
| **维度 4：90% 区间覆盖率**<br>(90% Prediction Interval Coverage) | 经验概率覆盖率：$\hat{P}(y \in [\hat{q}_{0.05}, \hat{q}_{0.95}])$ | $85.0\% \le \text{Cov} \le 95.0\%$ | $80.0\% \le \text{Cov} < 85.0\%$ 或<br>$95.0\% < \text{Cov} \le 97.0\%$ | $\text{Cov} < 80.0\%$ 或<br>$\text{Cov} > 97.0\%$ | 覆盖率严重偏离标称 90% 置信区间判红（过窄穿仓或过宽钝化） |

---

## 2. 交易治理与总评裁决规则 (Aggregation & Governance Rules)

1. **短板定级（No Weighted Average, Lowest-Pillar Decides）**：
   - **全绿（All-Green）** $\rightarrow$ **可投（TRADABLE / NORMAL）**：头寸调节系数 $S = 1.0$；
   - **任一黄（Any-Yellow）且无红** $\rightarrow$ **带旗收缩（FLAGGED / PENALIZED）**：头寸收缩系数 $S = 0.5$；严禁单向加仓，仅允许平仓或对冲；
   - **任一红（Any-Red）或无审计数据** $\rightarrow$ **禁投（BLOCKED / PROHIBITED）**：头寸收缩系数 $S = 0.0$；严禁开设任何新仓位，仅允许撤单与清算。
2. **两步分离执行原则**：
   - 严禁主观调和：每个标的的最终评级必须由代码布尔逻辑 `scorecard_level = min(dim1, dim2, dim3, dim4)` 直接计算，输出前必须附带原始测试或封卷报告数值。

---

## 3. 补充补充条款：未审计标的默认红级与追溯适用效力 (Supplementary Clauses)

1. **未审计标的默认红级禁投铁律**：
   - 凡属于 Active 10 宇宙或任何待扩展台站中，**尚未完成 20 折 Block-CV 独立选型、尚未通过四维全量可靠度审计、或未取得正式体检定级的标的与时效格，系统一律默认判定为 🔴 红级（禁投，BLOCKED / PROHIBITED，头寸系数 $S = 0.0$）**；
   - 严禁对未经法定审计确权的资产开立任何真实或虚拟单向新仓位。
2. **追溯适用说明 (Retroactive Application)**：
   - 本条款自 Phase 7 过渡态立项之日起具备完整追溯效力，向前完全覆盖既往已落盘但未经独立审计的 8 站 TMax 及全量 10 站 TMin（480 格）资产，杜绝无证裸跑风险。
