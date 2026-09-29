# 门禁标定与变更管理协议 (Gate Calibration and Change Protocol)

- **发件单位**: Polymarket 气象概率量化系统工程组
- **文档性质**: 第二轮修复令 R-4 并行轨交付工件
- **约束层级**: 顶层统计合规与变更冻结控制
- **对齐标准**: 严格对齐《项目执行文件》与《致项目开发组：R-1 完整评估报告与后续任务执行指令》

---

## 一、协议主旨与防篡改铁律

为彻底杜绝“因指标未达标而事后调参放水、改动门禁阈值、或以修改统计口径来掩盖模型缺陷”的伪造与不合规行为，本项目确立《门禁标定与变更管理协议》。

1. **绝对禁止事后调宽门禁（Hard Gate Immutability）**：所有法定验收门禁（包括 PIT 均匀性、加权 ECE、置信区间覆盖率）在任何情况下不得由工程组单方面放宽；
2. **外生变量必须具有严格的物理或解析推导（Analytic Exogeneity）**：模型中使用的先验常数、物理下界与理论基准，必须源于传感器硬件规格或数理严格推导，严禁使用经验调参的拟合数值；
3. **变更预注册与审批程序（Pre-Registration Requirement）**：任何涉及评估门禁或真值源定义的变更，必须事前提交数学推导与功效分析，经评审委员会审批确认后方可启用。

---

## 二、外生变量的解析推导与物理基准 (Exogenous Derivations)

### 2.1 传感器物理噪声下界 $\sigma_{\text{inst}} = 0.9^\circ\text{F}$
- **物理源头**: 美国国家海洋和大气管理局（NOAA）与联邦航空局（FAA）联合 ASOS 规范（NWS Observing Handbook No. 7）；
- **传感器型号**: ASOS 采用的标准铂电阻温度计（Platinum Resistance Thermometer, PRT 1088）；
- **解析约束**: 在 $-58^\circ\text{F} \sim +122^\circ\text{F}$ 的工作温区内，该传感器的现场测量法定不确定度为 $\pm 0.9^\circ\text{F}$。因此，任何气温离散分布预测的弥散度 $\sigma$ 物理上不可能小于 $\sigma_{\text{inst}} = 0.9^\circ\text{F}$。在 EMOS 拟合中将其硬性钉为参数下界：$c \ge 0.9^\circ\text{F}$。

### 2.2 理论锚定弥散度 $\sigma^* = \frac{\text{MAE}}{\sqrt{2/\pi}} \approx \frac{\text{MAE}}{0.7979}$
- **数学假定**: 设模型预测残差服从零均值高斯分布 $\epsilon = y - \mu \sim \mathcal{N}(0, \sigma^2)$；
- **解析推导**:
  $$\mathbb{E}[|\epsilon|] = \int_{-\infty}^{\infty} |x| \frac{1}{\sqrt{2\pi}\sigma} \exp\left(-\frac{x^2}{2\sigma^2}\right) dx = 2 \int_{0}^{\infty} \frac{x}{\sqrt{2\pi}\sigma} \exp\left(-\frac{x^2}{2\sigma^2}\right) dx = \sigma \sqrt{\frac{2}{\pi}}$$
  由此可解出与观测 MAE（平均绝对误差）严格相容的理论标准差：
  $$\sigma^* \equiv \frac{\text{MAE}}{\sqrt{2/\pi}} = \frac{\text{MAE}}{\sqrt{2} \cdot \Gamma(1/2)^{-1} \cdot \dots} \approx \frac{\text{MAE}}{0.79788456}$$
- **外生意义**: $\sigma^*$ 完全由样本外预测误差的大小决定，是评估模型是否欠离散（Under-dispersed）的客观外生锚尺。

### 2.3 方差比门禁 $s = \frac{\text{Var}(r)}{\overline{\sigma_f^2}} \approx 1.0$
- **理论基准**: 当模型预测方差完全反映真实预测不确定性时，经验残差方差 $\text{Var}(r)$ 与预测平均方差 $\mathbb{E}[\sigma_f^2]$ 之比必须为 $1.0$；
- **统计门禁**: 辅助以分层方差齐性 F 检验（Variance Ratio F-test），在自由度为 $(N-1, N-1)$ 下拒绝 $s \gg 1$（严重欠离散）或 $s \ll 1$（严重过度平滑）。

### 2.4 Polymarket 离散气温多档位加权 ECE 定义
- **市场契约结构**: Polymarket 气温盘口每天由 7 个连续的 $1^\circ\text{F}$ 离散档位组成；
- **加权 ECE 公式**:
  $$\text{ECE} = \sum_{m=1}^{M} \frac{|B_m|}{N \times K} \left| \text{conf}(B_m) - \text{acc}(B_m) \right|$$
  其中 $M=20$（等宽分桶），$K=7$（每日档位数），总事件数 $N_{\text{total}} = 365 \times 7 = 2555$；
- **硬门禁标准**: 加权 $\text{ECE} \le 3.0\%$，保持对均值漂移与方差失真的极高统计敏感度。

---

## 三、门禁基准与变更触发条件清单

| 门禁分类 | 指标名称 | 现行法定门禁标准 | 变更触发条件与许可边界 |
| :--- | :--- | :---: | :--- |
| **主门禁 ①** | 随机化 PIT K-S 检验 | $p \ge 0.05$ | **绝对冻结**，严禁放宽；样本量不足时仅允许补充 bootstrap $p$-val，不得修改检验类型 |
| **主门禁 ②** | 7 档位加权 ECE | $\text{ECE} \le 3.0\%$ | **绝对冻结**，严禁放宽至 5% 或采用可调等频分桶掩饰 |
| **主门禁 ③** | 十分位统计闭关断言 | 全部分层校验 PASS | **代码逻辑冻结**，作为管线完整性核心断言 |
| **双向门禁 ①** | PIT 一阶矩 (Mean) | $0.50 \pm 0.04$ ($[0.46, 0.54]$) | **绝对冻结**，直接反映冷热偏差与预测中心偏移 |
| **双向门禁 ②** | 名义 90% 置信区间覆盖率 | $[83.0\%, 93.0\%]$ | 允许根据微观离散化效应微调下界，但严禁低于 $80\%$ |
| **双实现门禁** | 双独立实现数值偏差 | 偏差 $< 10^{-3}$ | **绝对冻结**，跨算法实现数值一致性基石 |

---

## 四、变更生命周期管理与审查存证

1. **预注册申请 (RFC)**: 任何参数调整或算法优化，必须提前生成包含理论证明的 RFC 文档；
2. **审查方独立复核**: 提交测试脚本与工件清单，由审查方独立复算确认；
3. **版本清单锁定 (Manifest Hashing)**: 所有参数文件、推演数据均需录入 `evidence/pilot_manifest.json`，并由 SHA256 哈希值锁定，杜绝暗中替换。
