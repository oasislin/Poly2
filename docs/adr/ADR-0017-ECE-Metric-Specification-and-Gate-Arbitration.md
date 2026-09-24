# ADR-0017：期望校准误差 (ECE) 统计口径规范、尖锐度概念纠偏与双层门禁仲裁

- **状态**: APPROVED (修复轮指令 v3 / D-5 最终裁定)
- **提出日期**: 2026-09-24
- **决策者**: 评审委员会（统计独立审查方）、Polymarket 气象概率量化系统工程组
- **关联文档**: ADR-0015（离散校准门禁）、ADR-0016（GHCN-Daily 法定真值基线）

---

## 1. 背景与问题陈述

在前期研发与 Round 2 交付报告中，出现了以下两处统计学概念与门禁口径的混淆与争议：
1. **概念范畴混淆**：部分文档将“中心档位 ECE（预测最高概率档位上的条件期望校准误差）”表述为“尖锐度（Sharpness）”。
2. **门禁口径争议**：在 7 档位离散概率空间下，加权 ECE（全域边缘校准度）与中心档 ECE（高胜率众数档位条件校准度）数值尺度不同（前者约 0.3%~1.6%，后者约 2.2%~4.8%），引发两项指标哪一个作为法定主门禁 ② 的裁决争议。

依据《修复轮指令 v3》D-5 条款及用户授权条件 ③，特立此 ADR 彻底纠偏统计概念、明确测度数学定义，并确立法定门禁裁决规则。

---

## 2. 核心统计概念严格纠偏：校准度 vs 尖锐度

依据气象预报验证权威理论（Murphy & Winkler, 1987; Gneiting, Balabdaoui & Raftery, 2007 *Probabilistic Forecasts, Calibration and Sharpness*），概率预报评估严格遵循**“在满足校准的前提下最大化尖锐度（Maximizing sharpness subject to calibration）”**原则：

### 2.1 尖锐度（Sharpness）的外生性定义
- **理论定义**：尖锐度纯粹是预报分布 $F$ 本身的内在属性（Property of the forecast alone），衡量预测分布的集中紧凑程度，**与观测真值 $y$ 及其实现完全无关**。
- **数学测度**：对于连续或离散概率预报，尖锐度由分布的离散尺度量度，例如：
  - 预测区间宽度（Prediction Interval Width，如 90% 区间宽度 $q_{0.95} - q_{0.05}$）；
  - 预测方差或标准差 $\sigma_f$；
  - 离散概率分布的信息熵（Shannon Entropy）：$H(P) = -\sum_{k=1}^K p_k \log p_k$。
- **物理含义**：预报系统越有信心、不确定性越小，其分布越紧凑，尖锐度越高（Entropy 越小、PI 宽度越窄）。

### 2.2 中心档 ECE（Modal Bracket ECE）的本质归属
- **理论定义**：中心档 ECE 衡量的是：当模型以高概率（众数档位 $k^* = \arg\max_k p_k$）预测气温落入该区间时，预测概率 $p_{k^*}$ 与实际命中指示变量 $\mathbb{I}(y \in B_{k^*})$ 之间的条件校准差距：
  $$\text{ECE}_{\text{center}} = \frac{1}{N} \sum_{i=1}^N \left| p_{i, k^*(i)} - \mathbb{I}(y_i \in B_{k^*(i)}) \right| \quad \text{或可靠度分桶加权误差}$$
- **纠偏裁定**：中心档 ECE 明确依赖观测真值 $y_i$，它属于**众数档位条件校准性（Conditional Reliability / Calibration on Modal Bin）**，是校准性指标的一个条件切片，**绝非尖锐度**。
- **历史错误纠正**：全项目所有文档与代码注释即日起彻底废止将“中心档 ECE”等同于“尖锐度”的错误表述。

---

## 3. 两种 ECE 测度的数学规范与法定地位仲裁

在 Polymarket 7 档位离散合约场景下（每个站·日有 7 个互斥离散档位 $B_1, \dots, B_7$）：

### 3.1 法定主门禁 ②：全空间 7 档位离散加权 ECE（Weighted Multi-Class ECE）
- **计算定义**：
  将每个站·日的全部 7 个档位的预测概率 $p_{i, k}$ 与实际二元指示变量 $o_{i, k} = \mathbb{I}(y_i \in B_k)$ 汇入全域样本对池（样本容量 $7N$）。按预测概率区间划分为 $M=20$ 个分桶 $I_m = (\frac{m-1}{M}, \frac{m}{M}]$：
  $$\text{ECE}_{\text{7bin}} = \sum_{m=1}^M \frac{|I_m|}{7N} \left| \bar{p}_m - \bar{o}_m \right|$$
- **法定地位**：**全项目法定主门禁 ②（Primary Rejection Gate 2）**。
- **门禁阈值**：**$\text{ECE}_{\text{7bin}} \le 3.0\%$**（严格维持 ADR-0015 第 2.4 节裁定，任何放宽提案均属无效）。
- **数理依据**：在 7 档互斥离散合约中，系统不仅在最高概率档位下注，同时在边缘档位进行安全截断或逆向定价。全域加权 ECE 是全盘口概率真实校准度的无偏度量。在当前法定重算中，三站实测值分别为 KORD 0.74%、KMIA 1.62%、KSFO 0.34%，均极其扎实地满足 $\le 3.0\%$ 门禁。

### 3.2 辅助监控指标：中心档条件校准误差（Modal Bracket ECE）
- **计算定义**：
  仅抽取每个站·日预测概率最高的中心档（Modal Bracket $k^*(i)$），计算其可靠度加权误差：
  $$\text{ECE}_{\text{center}} = \sum_{m=1}^M \frac{|I_m^*|}{N} \left| \bar{p}_m^* - \bar{o}_m^* \right|$$
- **法定地位**：**辅助健康监控指标（Auxiliary Diagnostic Metric）**。
- **业务意义**：作为实际交易中“单档重仓押注”场景的条件风险安全垫参考。在当前法定重算中，实测值分别为 KORD 4.80%、KMIA 2.20%、KSFO 2.59%。
- **门禁约束**：不作为一票否决的主门禁，但设监控参考阈值 $\le 6.0\%$。若 $\text{ECE}_{\text{center}} > 6.0\%$，触发模型风控黄色预警。

---

## 4. 成对上报强制规则（Mandatory Paired Reporting）

依据指令 v3 授权协议，自 Round 2 起建立全项目强制报告规约：
1. **禁止单项孤立报告**：严禁在任何正式交付文件、质量报告、PR 描述或回测总结中仅报告单个 ECE 数字；
2. **成对列示标准**：凡出现校准误差之处，必须成对同时报告：
   - `ECE (7-bin weighted, Statutory Gate)`: 阈值 $\le 3.0\%$；
   - `ECE (center-bin conditional, Auxiliary)`: 参考阈值 $\le 6.0\%$；
3. **机器可读字段绑定**：`evidence/recomputed_statistics.csv` 与各导出的审计数组必须显式区分 `ece_7bin_weighted` 与 `ece_center_bin`，字段口径严格溯源至脚本 `scripts/standalone_recompute_evaluation.py`。
