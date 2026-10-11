# Phase 2 波次三 (W3) 真实盘口接入预注册规格书 · 附录 A (Annex A · 终版)

> **案卷编号**：`W3-SPEC-ANNEX-A-FINAL`  
> **所属主件**：[`docs/w3_polymarket_ingestion_preregistration.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/w3_polymarket_ingestion_preregistration.md)（Rev.1.1 终版）  
> **审定工单**：委员会裁定批复 **`P7-W3-GOV-001`**（通过令）  
> **生效状态**：**正式生效（全项批准，含两项强制标注条款）**  
> **编制主体**：W3 会话 Agent  
> **生效时间**：`2026-10-11 15:25:00 UTC` (Local `2026-10-11 23:25:00+08:00`)  
> **核心原则**：**严格落实 E-5 红线，全量封存既有算法与常量法定出处，消除任何隐式未申报数学与未受控工程决策。**

---

## 一、 常量与硬编码阈值分类对账表 (经 P7-W3-GOV-001 裁定批准)

### 1.1 类别 A：数学与风控核心常量（需委员会逐项审定）

| 序号 | 标识符 / 变量名 | 常量取值 | 代码物理位置 | 规格定稿出处 / 依据 | 委员会裁定结果 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **1** | `MIN_POSITIVE_EV_EDGE` | `0.05` (5%) | `paper_evaluation_engine.py:46` | **判据 B-3**（正 EV 门槛 $\ge 5$ 个百分点） | **批准**（出处确凿，属 Rev.1.0 冻结范围） |
| **2** | `MIN_ORDERBOOK_DEPTH` | `10.0` (10份) | `paper_evaluation_engine.py:47` | **判据 B-5**（最优档深度 $\ge 10$ 份） | **批准**（出处确凿，属 Rev.1.0 冻结范围） |
| **3** | `DIVERGENCE_THRESHOLD` | `0.15` (15%) | `paper_evaluation_engine.py:48` | **判据 B-6**（偏离 $> 15\%$ 打标监控） | **批准**（出处确凿，属 Rev.1.0 冻结范围） |
| **4** | 基准层快照周期 | `60 min` (3600s) | `polymarket_clob_collector.py:196` | **判据 A-1**（每 60 分钟全量快照） | **批准**（出处确凿，属 Rev.1.0 冻结范围） |
| **5** | 结算探测层窗口 | `12.0 h` | `polymarket_clob_collector.py:200` | **判据 A-2**（$T-12\text{h}$ 起探测层启动） | **批准**（出处确凿，属 Rev.1.0 冻结范围） |
| **6** | 数据来源戳 | `"POLYMARKET_LIVE_CLOB"` | `polymarket_clob_collector.py:26` | **红线 E-2**（数据性质法定标注） | **批准**（出处确凿，属 Rev.1.0 冻结范围） |
| **7** | 真实概率来源戳 | `"EMOS_PIPELINE"` | `real_emos_pipeline.py:30` | **训诫令 E-4**（模型真实性红线） | **批准**（训诫令直系产物） |
| **8** | 占位概率来源戳 | `"CLIMATOLOGY_PLACEHOLDER"` | `real_emos_pipeline.py:31` | **训诫令 E-4**（显式占位物溯源） | **批准**（训诫令直系产物） |
| **9** | `MAX_MEDIAN_DEVIATION_THRESHOLD` | `8.0` (°F) | `paper_evaluation_engine.py:50` | **工单 P7-W3-TASK2-REDO-001** | **批准**（出处清晰） |
| **10** | `PROB_STATIC_EPSILON` | `1e-6` | `paper_evaluation_engine.py:49` | **判据 A-4**（浮点判等容差） | **批准**（判据工程附随物） |
| **11** | 半度连续性修正 | `±0.5` (°F) | `paper_evaluation_engine.py:71-99` | ASOS METAR 整数舍入逆变换 | **批准，附特别说明**（见下文） |
| **12** | 单纯形归一化下界容差 | `1e-12` | `paper_evaluation_engine.py:176` | 数值防除零保护 | **批准**（数值保护） |

> **第 11 项特别说明（委员会批复原文）**：  
> 这是全部 14 项中唯一一个实质性影响概率数值的算法选择，且它是在假演示 commit（`d7a114d`）中静默引入的。但裁定批准，因为它是物理上正确的：METAR 官方温度按整数 °F 舍入，整数区间 $[T_1, T_2]$ 的连续真值域就是 $[T_1-0.5, T_2+0.5)$。交叉验证：用演示数据复核 $P(\le 79^\circ\text{F})$，$z=(79.5-90.01)/3.99 \approx -2.63$，$\Phi \approx 0.0043$，与呈报的 $0.0042$ 吻合——连续化处理确实在生效。这类“实质正确但未申报”的条目，正是 E-5 要终结的行为模式：这次是对的数学，不代表下次也是。

---

### 1.2 类别 B：工程级 I/O 常量（仅需登记备案，免逐项裁定）

| 序号 | 标识符 / 变量名 | 常量取值 | 代码物理位置 | 用途与工程依据 | 治理性质 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **13** | HTTP 请求超时 | `15 s` | `polymarket_clob_collector.py:304` | 避免只读 API 挂起阻塞批处理周期 | 工程级网络 I/O 备案 |
| **14** | 代理嗅探超时 | `0.2 s` | `polymarket_clob_collector.py:323` | 本地回环端口探测防假死 | 工程级网络 I/O 备案 |

---

## 二、 算法数学表述与两项强制标注条款 (经 P7-W3-GOV-001 裁定批准)

### 条款 Annex-A1：市场隐含中位数求解算法 ($M_{\text{market}}$)

1. **代码位置**：[`src/pricing/paper_evaluation_engine.py:108-146`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L108-L146)（首次引入 Commit：`9ef9101`）
2. **完整数学表述**：
   - **Step 1: 有效中间价提取**：
     对 $K$ 个离散温度档位 $i \in \{1, \dots, K\}$，若双边有报价，取 $p_{\text{mid}, i} = \frac{\text{ask}_i + \text{bid}_i}{2}$。无报价（NO_QUOTE）或 $p_{\text{mid}, i} \le 0$ 不参与累积。
   - **Step 2: 单纯形归一化 (Simplex Normalization)**：
     $$S_{\text{mid}} = \sum_{i \in \text{valid}} p_{\text{mid}, i}$$
     若 $S_{\text{mid}} \le 10^{-6}$，返回 `None`；否则归一化：
     $$\hat{p}_i = \frac{p_{\text{mid}, i}}{S_{\text{mid}}}, \quad \sum_{i \in \text{valid}} \hat{p}_i = 1.0$$
   - **Step 3: 升序排列与累积分布阶梯**：
     按档位温度下界 $L_i$ 单调升序排列，构造累积分布：
     $$C_0 = 0.0, \quad C_k = \sum_{j=1}^k \hat{p}_j \quad (k = 1, \dots, K_{\text{valid}})$$
   - **Step 4: 50th 分位数分段线性插值**：
     定位满足 $C_{k-1} < 0.50 \le C_k$ 的区间 $k$，线性插值求解 $M_{\text{market}}$：
     $$M_{\text{market}} = L_k + \left( \frac{0.50 - C_{k-1}}{\hat{p}_k} \right) \cdot (R_k - L_k)$$
   - **Step 5: 尾部边界处理**：
     左尾 $(-\infty, R_k)$ 取 $M_{\text{market}} = R_k - 1.0^\circ\text{F}$；右尾 $[L_k, +\infty)$ 取 $M_{\text{market}} = L_k + 1.0^\circ\text{F}$。

> [!CAUTION]
> **强制标注条款一（已知局限声明）**：  
> 市场隐含中位数算法仅对有报价档位的中间价进行归一化。在真实盘口（如迈阿密实测 11 档中 4 档为 NO_QUOTE）中，被剔除的档位集中在分布两翼，归一化会系统性高估尾部的相对权重、轻微压缩中位数区间的隐含概率。  
> **裁定约束**：当前本算法仅用作 8.0°F 熔断的粗粒度哨兵（该偏差量级远小于 8.0°F 阈值），保留使用；**但在后续 D-3 分析及任何研究中使用 $M_{\text{market}}$ 的场合，必须同步引用本局限声明**。

> [!WARNING]
> **强制标注条款二（尾部取值性质声明）**：  
> 极端尾部档位中 $\pm 1.0^\circ\text{F}$ 的取值是**便利性近似值，而非理论推导值**。因其数值影响被 8.0°F 熔断门槛量级完全吸收，裁定批准保留，但**严禁后人误将其当作有物理或统计理论依据的设计**。

---

### 条款 Annex-A2：离散合约区间解析之半度连续性修正 ($\pm 0.5^\circ\text{F}$)

1. **代码位置**：[`src/pricing/paper_evaluation_engine.py:53-106`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L53-L106)（首次引入 Commit：`d7a114d`）
2. **物理映射规则**：
   - 双边闭区间：`T1-T2°F` $\implies [T_1 - 0.5, T_2 + 0.5)$
   - 左尾半开区间：`<= T` 或 `T or below` $\implies (-\infty, T + 0.5)$
   - 右尾半开区间：`>= T` 或 `T or above` $\implies [T - 0.5, +\infty)$
   - 单度档位：`T°F` $\implies [T - 0.5, T + 0.5)$
3. **物理依据**：NWS ASOS 观测数据整数舍入逆变换，确保高斯 CDF 积分在实数轴测度自洽，总概率恒等于 1.0。

---

### 条款 Annex-A3：高斯 EMOS 分布中位数解析解 ($M_{\text{model}} \equiv \mu$)

1. **代码位置**：[`src/pricing/paper_evaluation_engine.py:274-275`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L274-L275)（首次引入 Commit：`9ef9101`）
2. **数学依据**：高斯分布关于均值严格对称，$f(\mu - x) = f(\mu + x) \implies \Phi(0) = 0.50 \implies M_{\text{model}} \equiv \mu$。

---

### 条款 Annex-A4：偏离熔断门禁 `MAX_MEDIAN_DEVIATION_THRESHOLD = 8.0°F`

1. **代码位置**：[`src/pricing/paper_evaluation_engine.py:50, 277-290`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L50)（首次引入 Commit：`9ef9101`）
2. **判定与动作**：$|M_{\text{model}} - M_{\text{market}}| > 8.0^\circ\text{F} \implies \text{is\_input\_suspect} = \text{True}$；档位正 EV 信号强制剥离可执行性（`is_signal = False`，打标 `QUARANTINED`，状态 `QUARANTINED_INPUT_SUSPECT`）；B-4 全量落盘底账。

---

### 条款 Annex-A5：跨快照概率稳定容差 `PROB_STATIC_EPSILON = 1e-6`

1. **代码位置**：[`src/pricing/paper_evaluation_engine.py:49, 319-323`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L49)（首次引入 Commit：`d7a114d`）
2. **数理依据**：判据 A-4 的浮点工程实现容差，规避 IEEE 754 机器舍入误差。

---

### 条款 Annex-A6：单纯形积分极小值容差与均匀回退

1. **代码位置**：[`src/pricing/paper_evaluation_engine.py:176-179`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L176-L179)（首次引入 Commit：`d7a114d`）
2. **数理依据**：积分和 $\le 10^{-12}$ 时安全回退为均匀分布 $1/K$，提供数值防除零保护。

---

### 条款 Annex-A7：生产级 5 成员 GEFS 实时系综提取规范

1. **代码位置**：[`src/prediction/real_emos_pipeline.py:33, 209-224, 280-310`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/prediction/real_emos_pipeline.py#L33)（首次引入 Commit：`9ef9101`）
2. **技术规范**：
   - 成员：控制报 `c00` + 扰动报 `p01`–`p04`；产品 `atmos.25`；变量 `:TMAX:2 m above ground:`；
   - 单位转换：$T(^\circ\text{F}) = (T_{\text{kelvin}} - 273.15) \times 9/5 + 32.0$；
   - 样本方差：$S^2_{\text{ens}} = \frac{1}{N-1}\sum_{m=1}^N (T_m - \bar{T}_{\text{ens}})^2$（`ddof=1`）；
   - 链接函数：$\mu = a + b \bar{T}_{\text{ens}}$，$\sigma^2 = c^2 + d^2 S^2_{\text{ens}} + \sigma^2_{\text{clim}}$。

---

## 三、 裁定生效签署

本附录所有条款已获技术裁决委员会正式批准（批复案卷 `P7-W3-GOV-001`），两项强制标注条款已不可撤销地并入规格书法定体系。  
**E-5 红线自即日起全面生效，位次 4/4 及后续阶段实现中严禁出现任何未申报数学与工程假定。**
