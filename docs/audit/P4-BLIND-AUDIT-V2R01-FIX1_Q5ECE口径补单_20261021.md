# P4-BLIND-AUDIT-V2R01-FIX1 · Q5 ECE 档级口径修正与证据补查单

> 父工单：`P4-BLIND-AUDIT-V2R01`（第二类 V2.0 尺子升级）
> 签发时间：2026-10-21 13:51 ｜ 执行时间：2026-10-21 13:55
> 性质：技术审核方 review 打回修正（Q5 ECE 档级口径与敏感性极差修复）。

---

## 1. 审核方 review 裁决对账

### 1.1 审核通过（保持冻结，不用动）✅
- **Q2/Q3 F 带**：独立复算 22 格全部一致。传入连续浮点 $N_{\text{eff}}$，双带并列（$F_{\text{inf}}$ 救回 2 格，$F_{\text{std}}$ 救回 10 格），无恒真列。
- **Q4 方案乙**：`reject_uniform = (ks_p < 0.05 and cvm_p < 0.05)` 下沉正确，0/22 被否决，成功消除 `KORD_48h` 与 `KORD_72h` 边缘悬崖误杀。
- **Q6 PIT 方差与直方图**：复算一致，方差贴近理论 $1/12 \approx 0.083333$，10 列区间占比和严格为 1.0。

### 1.2 审核打回（FIX1 必修）❌
- **问题**：初版实现中 `ece_2f` 与 `ece_bins20` 均直接调用 `compute_weighted_ece(probs_2f, hits_2f, num_bins=20)`，导致 22/22 格的 `ece_2f` 与 `ece_bins20` 数值完全相等（diff=0），“2°F 梯子 ECE”名实不符，且将分箱敏感性极差 `ece_range` 严重压缩。
- **修正口径**：
  - `ece_2f` 改为 **11 档档级直接可靠性 ECE**（按档聚合每档的 $|\text{mean\_p}_k - \text{hit\_rate}_k|$ 进行全覆盖等权加权均值）；
  - `ece_bins10` 与 `ece_bins20` 保留为 2°F 梯子全展开概率对的等宽置信度桶敏感性对照；
  - `ece_7bin_v1` 保留为 V1 7 档复算基准；
  - 重新计算 `ece_range = max(ece_set) - min(ece_set)`。

---

## 2. 修正实现与数理规则

### 2.1 11 档全覆盖梯子档级定义（±9°F 与 Catch-All 截断）
以每日中心整度 $c_0 = \text{round}(\mu_{\text{calib}})$ 为基准：
- **Bracket 0（左侧 catch-all）**：$[-\infty, c_0 - 9^\circ\text{F})$
- **Bracket 1~9（中间 9 档 2°F 内部档位）**：
  $[c_0 - 9, c_0 - 7), [c_0 - 7, c_0 - 5), [c_0 - 5, c_0 - 3), [c_0 - 3, c_0 - 1), [c_0 - 1, c_0 + 1), [c_0 + 1, c_0 + 3), [c_0 + 3, c_0 + 5), [c_0 + 5, c_0 + 7), [c_0 + 7, c_0 + 9)$
- **Bracket 10（右侧 catch-all）**：$[c_0 + 9^\circ\text{F}, +\infty)$

### 2.2 概率守恒与无漏检证明
- 每日实际观测 $y_i$ 必定严格落入且仅落入上述 11 档中的 1 档（$h_{i,k} \in \{0, 1\}$ 且 $\sum_{k=0}^{10} h_{i,k} \equiv 1$）；
- 每档预测概率由模型连续 CDF 解析计算：$p_{i,k} = F(b_{hi}) - F(b_{lo})$；
- **全样本 8,000 天实测概率和偏差**：`max_prob_dev = 0.0`（严格等于 1.0，无浮点截断漏检）。

### 2.3 档级直接可靠性 ECE 计算公式
对第 $k$ 档（$k \in \{0, \dots, 10\}$）：
$$\overline{p}_k = \frac{1}{n}\sum_{i=1}^n p_{i,k}, \quad \overline{h}_k = \frac{1}{n}\sum_{i=1}^n h_{i,k}$$
全 11 档直接可靠性加权 ECE：
$$\text{ece\_2f} = \frac{1}{11}\sum_{k=0}^{10} |\overline{p}_k - \overline{h}_k|$$

---

## 3. 执行证据与回归验证

### 3.1 Airgap 守卫回归验证
```text
$ pytest tests/unit/verification/test_2019_airgap_guardrail.py -q
......                                                                   [100%]
============================== 6 passed in 0.59s ===============================
```
- 退出码：`0`

### 3.2 敏感性分歧消除验证
修正后 22 格的 `ece_2f` 与 `ece_bins20` 全部不等（`diff != 0`）：
- 不等比例：`22 / 22` 格（100% 区分度）
- 最小差异：`0.000334`（0.03%）
- 最大差异：`0.016930`（1.69%）
- 均值对比：
  - `ece_2f`（11 档档级直接 ECE）均值：`0.0118`（1.18%）
  - `ece_7bin_v1`（V1 7 档）均值：`0.0087`（0.87%）
  - `ece_bins10`（10 概率桶）均值：`0.0053`（0.53%）
  - `ece_bins20`（20 概率桶）均值：`0.0092`（0.92%）
  - `ece_range` 敏感性极差均值：`0.0078`（0.78%）

---

## 4. 产出工件校验和

- 脚本：`scripts/audit_v2/reliability_v2.py`（SHA-256: `e821c0aa0079f483f3510698f919751886d908bae145e3cd5385eae9c14a68ba`）
- 指标表：`evidence/audit_v2/p4blind_v2r01_metrics.csv`（SHA-256: `ae615945bc35a72fb9f9c2de04f26033637ad080f7cf70fc66b514065ccb611a`）
- 对照表：`evidence/audit_v2/p4blind_v2r01_comparison.csv`（SHA-256: `572cc7cb8f033ddda8317d0e6b729ea8dc041cb085e1e1f0be3ffb022da6af21`）
