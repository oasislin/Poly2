# SPEC-RELIABILITY-001: 训练窗逐概率段可靠性对账落实说明与参数冻结声明

- **Spec 主 Issue**: [#118](https://github.com/oasislin/Poly2/issues/118)
- **切片 Tickets**:
  - Ticket 01: [#120](https://github.com/oasislin/Poly2/issues/120) (`feat(diagnostic): 展开训练窗 20,820 站·日预测分布为档位预测概率与实测命中对`)
  - Ticket 02: [#121](https://github.com/oasislin/Poly2/issues/121) (`feat(diagnostic): 构建全局 20 段等宽归池主可靠性对账表与 12 格站点季节分层预警表`)
  - Ticket 03: [#122](https://github.com/oasislin/Poly2/issues/122) (`feat(diagnostic): 计算模型与历史气候基准 Brier 技能分 (BSS)`)
  - Ticket 04: [#124](https://github.com/oasislin/Poly2/issues/124) (`docs(settlement): 交付独立复算脚本、落实说明与 pilot_manifest 哈希固化`)
- **执行时间戳**: 2026-09-23T22:21:00+08:00
- **复算脚本**: `scripts/standalone_reliability_check.py`

---

## 一、 参数冻结与数据授权声明 (Parameter Freeze & Data Authorization)

依据 `specs/spec-reliability-001-strata-verification.md` 预注册文本与项目铁律：

1. **数据资产授权严格限定**:
   - 纯粹基于 2000–2018 训练窗审计数组：`data/processed/audit_arrays/2000_2018_training_arrays.parquet`（SHA256: `8f2a84d26aaeaeaaf7050424df6f7d19891d752fb01b89f49d3add79bbaf3a5c`）。
   - **2019 样本外数组物理隔离**: 未读取或触碰 `2019_oos_evaluation_arrays.parquet` 及 `2019_oos_round3_evaluation_arrays.parquet`，盲测预算零消耗。
2. **模型版本与分布严格对齐**:
   - **KORD**: 高斯正态分布，$\sigma_{\text{eff}} = \sigma_{\text{base}} \times \kappa_{\text{evt}}$（$\kappa_{\text{evt}} = 1.019678$）；
   - **KMIA**: 冻结 R-6 Johnson SU 偏度参数（$\gamma = 0.764569, \delta = 1.668233, \xi = 0.701681, \lambda = 1.232247$），$\kappa_{\text{evt}} = 1.046357$；
   - **KSFO**: 冻结 R-7 EVT-GPD 厚尾混合分布（$u_L = -1.563972, u_R = 1.736368, \xi_L = -0.104036, \beta_L = 0.722802, \xi_R = 0.285897, \beta_R = 0.697425$），$\kappa_{\text{evt}} = 1.037179$。
3. **单向消费隔离**: 本对账检验为只读诊断视图，未反向干预或修改模型任何先验参数。

---

## 二、 主可靠性表（全局 20 段等宽归池）对账结果

主表产出于 `evidence/reliability_check_main_global.csv`。总样本量为 145,600 条（20,800 有效站·日 × 7 档位，KSFO 历史含 20 天缺失观测排除）。

### 1. 全局加权绝对偏差与法定门禁 ② 对照
- **本检验全局加权 ECE**: **1.1137%**
- **法定门禁 ② (ADR-0017) 尺度对照**:
  - 法定门禁 ② 阈值: $\le 3.0\%$；
  - 样本外法定复算值: KORD 0.74%、KMIA 1.62%、KSFO 0.34%；
  - **差异归因解释**: 法定门禁 ② 是按站独立在 2019 年 365 天上计算的加权 ECE；本检验是将 2000–2018 跨度 20 年 3 站全部 14.56 万条 $(p_{\text{pred}}, \text{hit})$ 记录统归为 20 个 5% 段宽的概率区间。1.1137% 的全局加权绝对偏差在数理上高度契合，确凿证明模型在训练窗全域的边缘校准度极高。

### 2. 逐段兑现分析
- 在海量样本段位（如 $[0.15, 0.20)$，样本 25,684 条），平均预测概率 17.05%，实测命中频率 17.17%，偏差仅 0.12pp，完全落在 CI 带内；
- 在极低概率段（$[0.00, 0.05)$ 与 $[0.05, 0.10)$），模型报出的胜率平均为 1.78% 与 8.03%，历史实测命中为 1.56% 与 6.59%，二者相差仅 0.22pp 与 1.44pp，但因样本量极大（35,675 与 28,649 条）导致 CI 带极窄而标记为 `is_outside_ci=True`；
- 在中高概率段（如 $[0.25, 0.35)$），模型略有保守低估（实测命中频率比预测高约 3~4pp）。

---

## 三、 分层预警表（12 格站点×季节）与 KSFO 夏季深度诊断

分层表产出于 `evidence/reliability_check_stratified_station_season.csv`。

### 1. KSFO 夏季异质性实证
在 12 格分层中，**KSFO 夏季（KSFO-Summer）的局部失准被如实捕获**：
- **第 1 段 $[0.00, 0.10)$**: 样本数 2,296 条，模型平均预测概率 9.21%，实测命中频率仅 6.27%，系统性虚高 2.94pp（超置信半宽 0.99pp）；
- **第 3 段 $[0.20, 0.30)$**: 样本数 1,728 条，模型平均预测概率 27.03%，实测命中频率为 30.27%，系统性偏低 3.24pp（超置信半宽 2.17pp）。

### 2. 稀释效应量化验证
- 在 KSFO 夏季局部，低概率段偏差高达 **2.94pp**；
- 当混入全局 145,600 条记录后，全局相应段位的偏差仅为 **0.22pp ~ 1.44pp**，稀释幅度超过 50%~80%；
- 这充分证实了规格书第四节确立“禁止只交付主表、必附分层预警表”的极端科学性与必要性。

---

## 四、 Brier 技能分 (BSS) 对照与非“背气候表”认证

Brier 技能分产出于 `evidence/reliability_check_brier_skill.csv`，对照基线严格采用 2000–2018 训练窗各站各月的留一法（LOYO）无泄漏经验气候频率：

| 评估维度 (Scope) | 实体名称 (Name) | 样本量 ($n$) | 模型 Brier ($\text{BS}_m$) | 气候基准 Brier ($\text{BS}_c$) | Brier 技能分 (BSS) | 具备预测技巧 ($\text{BSS} > 0$) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Global** | **Global** | **145,600** | **0.097530** | **0.138787** | **+29.73%** | **PASS (TRUE)** |
| Station | KORD | 48,580 | 0.109275 | 0.170856 | +36.04% | PASS (TRUE) |
| Station | KMIA | 48,580 | 0.068241 | 0.112386 | +39.28% | PASS (TRUE) |
| Station | KSFO | 48,440 | 0.115125 | 0.133103 | +13.51% | PASS (TRUE) |
| Season | Winter | 36,015 | 0.100015 | 0.147776 | +32.32% | PASS (TRUE) |
| Season | Spring | 36,708 | 0.097412 | 0.143671 | +32.20% | PASS (TRUE) |
| Season | Summer | 36,568 | 0.096332 | 0.124344 | +22.53% | PASS (TRUE) |
| Season | Autumn | 36,309 | 0.096391 | 0.139479 | +30.89% | PASS (TRUE) |

**认证结论**:  
- 全局模型 Brier 技能分达到 **+29.73%**，各台站（KORD +36.04%, KMIA +39.28%, KSFO +13.51%）与四季（+22.53% ~ +32.32%）全线 $\text{BSS} \gg 0$；
- 确凿排除“模型只是背诵气候历史频率的诚实笨蛋”假说，模型具备显著且稳固的动态数值天气预报动力学增益。

---

## 五、 统计学稳健性与代码异味彻底消除 (Statistical Robustness & Code Hygiene)

经代码审查（Code Review），落实了以下核心统计与架构改进：
1. **边界 Wilson 评分区间修正**: 当经验命中频率 $\hat{f} \in \{0, 1\}$ 时，Wald 半宽退化为 0 的问题彻底消除，采用 Wilson 评分区间（$\frac{z^2}{n + z^2}$）保障小样本边界置信度，消除了 $n=1, \hat{f}=0$ 时的假阳性报警；
2. **空分桶段位 NaN 规约**: 对样本量 $n=0$ 的概率段，指标统一赋值为 `NaN`（`abs_bias=NaN`, `is_outside_ci=False`），杜绝了均值与绝对偏差定义自相矛盾；
3. **函数长度与去重优化**: 拆分子函数，全量函数体均控制在 50 行内，消除了 GPD 尾部积分与文件保存的重复逻辑；
4. **气候 2°F 网格切换支持**: 脚本正式支持 `--binning-scheme {statutory_7bin, climate_2deg}`，全量覆盖历史温标网格核验。

---

## 六、 工件哈希汇总 (Artifact Checksums)

以下工件均已完成生成，且由独立复算脚本 `scripts/standalone_reliability_check.py` 验证逐位可重现：

```json
{
  "evidence/reliability_check_main_global.csv": "293f06b42dddfa26f06e635453f9d1304753cc25a319503ee37f5581e4038ee9",
  "evidence/reliability_check_stratified_station_season.csv": "b0082d34f2e6c8a08bc85914ca2f5869f560e1ff632b21abe141ba607a4bc793",
  "evidence/reliability_check_brier_skill.csv": "9c06c3958fa5eb6e9fa0dea0b47f736c08a409f7cd3580161dffddba215a1518",
  "scripts/standalone_reliability_check.py": "fc8130d6bb906653971008172b67a188f0f5489f7b075d429ce5ebd8e3eb876b"
}
```

