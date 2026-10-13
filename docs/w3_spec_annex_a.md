# Phase 2 波次三 (W3) 真实盘口接入预注册规格书 · 附录 A (Annex A)

> **案卷编号**：`W3-SPEC-ANNEX-A-DRAFT`  
> **所属主件**：[`docs/w3_polymarket_ingestion_preregistration.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/w3_polymarket_ingestion_preregistration.md)（Rev.1.1 草案）  
> **编制依据**：委员会工单 **`P7-W3-GOV-001`**（治理追溯 + 规则升级令）  
> **编制主体**：W3 会话 Agent  
> **呈报对象**：技术裁决委员会  
> **呈报时间**：`2026-10-11 15:20:00 UTC` (Local `2026-10-11 23:20:00+08:00`)  
> **核心原则**：**落实红线 E-5，对既有实现代码中一切未载明算法、公式、连续性假定与工程阈值全量追溯、彻底曝光、数理自洽、呈请裁定。**

---

## 一、 E-5 全库常量与硬编码阈值扫描及规格出处对账表

对照红线 E-5，对 `src/` 中 W3 盘口接入及评估相关模块（`src/data_acquisition/polymarket_clob_collector.py`、`src/pricing/paper_evaluation_engine.py`、`src/prediction/real_emos_pipeline.py`）进行穷尽扫描与出处对账：

| 序号 | 标识符 / 变量名 | 常量取值 | 代码物理位置 | 规格定稿出处 / 依据 | 受控性质与状态 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **1** | `MIN_POSITIVE_EV_EDGE` | `0.05` (5%) | `paper_evaluation_engine.py:46` | **判据 B-3**（正 EV 门槛 $\ge 5$ 个百分点） | 法定受控常量（已在 Rev.1.0 冻结） |
| **2** | `MIN_ORDERBOOK_DEPTH` | `10.0` (10份) | `paper_evaluation_engine.py:47` | **判据 B-5**（最优档可成交量 $\ge 10$ 份） | 法定受控常量（已在 Rev.1.0 冻结） |
| **3** | `DIVERGENCE_THRESHOLD` | `0.15` (15%) | `paper_evaluation_engine.py:48` | **判据 B-6**（我方概率与中间价偏离 $> 15\%$ 打标） | 法定受控常量（已在 Rev.1.0 冻结） |
| **4** | 基准层快照周期 | `60 min` (3600s) | `polymarket_clob_collector.py:196` | **判据 A-1**（基准层每 60 分钟全量快照） | 法定受控常量（已在 Rev.1.0 冻结） |
| **5** | 结算探测层窗口 | `12.0 h` | `polymarket_clob_collector.py:200` | **判据 A-2**（结算探测层 $T-12\text{h}$ 起启动） | 法定受控常量（已在 Rev.1.0 冻结） |
| **6** | 数据来源戳 | `"POLYMARKET_LIVE_CLOB"` | `polymarket_clob_collector.py:26` | **红线 E-2**（数据性质法定标注） | 法定受控常量（已在 Rev.1.0 冻结） |
| **7** | 真实概率来源戳 | `"EMOS_PIPELINE"` | `real_emos_pipeline.py:30` | **训诫令 E-4**（模型溯源真实性红线） | 法定受控常量（本案卷提请裁定） |
| **8** | 占位概率来源戳 | `"CLIMATOLOGY_PLACEHOLDER"` | `real_emos_pipeline.py:31` | **训诫令 E-4**（显式占位物溯源红线） | 法定受控常量（本案卷提请裁定） |
| **9** | `MAX_MEDIAN_DEVIATION_THRESHOLD` | `8.0` (°F) | `paper_evaluation_engine.py:50` | **工单 P7-W3-TASK2-REDO-001**（输入偏差熔断） | 未在主规格书明载（本案卷提请裁定） |
| **10** | `PROB_STATIC_EPSILON` | `1e-6` | `paper_evaluation_engine.py:49` | **判据 A-4**（浮点判等容差） | 未在主规格书明载（本案卷提请裁定） |
| **11** | 半度连续性修正 | `±0.5` (°F) | `paper_evaluation_engine.py:71-99` | ASOS METAR 整数舍入逆变换 | 未在主规格书明载（本案卷提请裁定） |
| **12** | 单纯形归一化下界容差 | `1e-12` | `paper_evaluation_engine.py:176` | 数值防除零保护 | 未在主规格书明载（本案卷提请裁定） |
| **13** | HTTP 请求超时 | `15 s` | `polymarket_clob_collector.py:304` | 网络 I/O 健壮性 | 工程常量（本案卷提请裁定） |
| **14** | 代理探测超时 | `0.2 s` | `polymarket_clob_collector.py:323` | 本地回环连接探测 | 工程常量（本案卷提请裁定） |

---

## 二、 未明载算法、公式与数学假定逐项追溯与数学表述 (前置任务 1)

### 条款 Annex-A1：市场隐含中位数求解算法 ($M_{\text{market}}$)

1. **引入背景与工程目的**：  
   在委员会训诫令整改（`P7-W3-TASK2-REDO-001`）中，为彻底阻断类似 $N(62.0, 3.5)$ 离奇 edge 假账本进入底账，设立了中位数安全门禁 `INPUT_SUSPECT`。该门禁需要求解市场订单簿当前隐含的温度中位数 $M_{\text{market}}$。
2. **代码物理位置**：[`src/pricing/paper_evaluation_engine.py:108-146`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L108-L146)
3. **首次引入 Commit**：`9ef9101`
4. **完整数学表述**：
   - **Step 1: 有效中间价提取**  
     对于市场中的 $K$ 个离散温度档位 $i \in \{1, 2, \dots, K\}$，若该档位双边均有报价，取保守侧算术中间价：
     $$p_{\text{mid}, i} = \frac{\text{ask}_i + \text{bid}_i}{2}$$
     若该档位无中间价或 $p_{\text{mid}, i} \le 0$，则该档位不参与分布累积。
   - **Step 2: 单纯形归一化 (Simplex Normalization)**  
     计算所有有效档位中间价之和 $S_{\text{mid}} = \sum_{i=1}^K p_{\text{mid}, i}$。  
     若 $S_{\text{mid}} \le 10^{-6}$，判定订单簿无流动性，返回 `None`。否则，计算各档位归一化市场隐含概率：
     $$\hat{p}_i = \frac{p_{\text{mid}, i}}{S_{\text{mid}}}, \quad \text{满足} \sum_{i=1}^K \hat{p}_i = 1.0$$
   - **Step 3: 升序排列与累积分布阶梯构造**  
     按档位温度物理下界 $L_i$ 进行单调升序排列，得到区间序列 $[L_1, R_1), [L_2, R_2), \dots, [L_K, R_K)$。  
     定义离散阶梯累积分布函数：
     $$C_0 = 0.0, \quad C_k = \sum_{j=1}^k \hat{p}_j \quad (k = 1, \dots, K)$$
   - **Step 4: 50th 分位数定位与分段线性插值**  
     寻找满足 $C_{k-1} < 0.50 \le C_k$ 的唯一分位数落入区间 $k$。在 $[L_k, R_k)$ 内部假定概率密度均匀分布，执行线性插值求解 $M_{\text{market}}$：
     $$M_{\text{market}} = L_k + \left( \frac{0.50 - C_{k-1}}{\hat{p}_k} \right) \cdot (R_k - L_k)$$
   - **Step 5: 渐近极端尾部档位边界修正假定**：
     - 若 $L_k = -\infty$（左尾极端档，如 `73°F or below`，即 $(-\infty, 73.5)$），由于无下界，无法直接线性插值，算法取上界回退值：
       $$M_{\text{market}} = R_k - 1.0^\circ\text{F}$$
     - 若 $R_k = +\infty$（右尾极端档，如 `98°F or higher`，即 $[97.5, +\infty)$），算法取下界进位值：
       $$M_{\text{market}} = L_k + 1.0^\circ\text{F}$$

---

### 条款 Annex-A2：离散合约区间解析之半度连续性修正 (Half-Degree Continuity Correction)

1. **引入背景与工程目的**：  
   Polymarket 合约文本为离散整数度数（如 `86-87°F`、`73°F or below`），而结算源（NWS ASOS 官方地面气象观测）将连续摄氏度/华氏度温度计读数四舍五入至最接近的整数华氏度落入 METAR 报文。依据 NWS WRH 科学规范，测站报出 $86^\circ\text{F}$ 对应之真值区间为 $[85.5^\circ\text{F}, 86.5^\circ\text{F})$。为保证高斯 CDF 积分不漏缝、不重叠且覆盖实数全轴，必须施加 $\pm 0.5^\circ\text{F}$ 连续性修正。
2. **代码物理位置**：[`src/pricing/paper_evaluation_engine.py:53-106`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L53-L106)
3. **首次引入 Commit**：`d7a114d`
4. **数学映射规则**：
   - 双边闭区间：`T1-T2°F` $\implies [T_1 - 0.5, T_2 + 0.5)$
   - 左尾半开区间：`<= T` 或 `T or below` $\implies (-\infty, T + 0.5)$
   - 右尾半开区间：`>= T` 或 `T or above` $\implies [T - 0.5, +\infty)$
   - 单度档位：`T°F` $\implies [T - 0.5, T + 0.5)$
   - 连续性定理：对任意相邻档位 $T_a \sim T_b$ 与 $T_b+1 \sim T_c$，其分界点为 $(T_b + 0.5)$，左右邻域无空隙且测度为 0，严格满足全概率分解 $\sum P_i = 1.0$。

---

### 条款 Annex-A3：高斯 EMOS 模型分布中位数解析解假定 ($M_{\text{model}} \equiv \mu$)

1. **引入背景与工程目的**：  
   在门禁判定中，需要计算模型物理分布的中位数 $M_{\text{model}}$。
2. **代码物理位置**：[`src/pricing/paper_evaluation_engine.py:274-275`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L274-L275)
3. **首次引入 Commit**：`9ef9101`
4. **数学依据**：  
   本项目采用的生产级 EMOS 链接函数为高斯分布族：
   $$Y \sim \mathcal{N}(\mu, \sigma^2)$$
   由于高斯分布关于均值 $\mu$ 严格对称，其概率密度函数满足 $f(\mu - x) = f(\mu + x)$，故其累积分布函数在 $\mu$ 处严格恒等于 $0.5$：
   $$\Phi\left(\frac{\mu - \mu}{\sigma}\right) = \Phi(0) = 0.50 \implies M_{\text{model}} \equiv \mu$$
   直接采用解析解 $\mu$，无需调用费时的数值二分求根，兼具数学严谨性与纳秒级性能。

---

### 条款 Annex-A4：`INPUT_SUSPECT` 隔离门槛与熔断判定机制

1. **引入背景与工程目的**：  
   落实 `P7-W3-TASK2-REDO-001` 工单，防止外部数据损坏、极端模型偏离或恶劣假数据引发虚假套利信号。
2. **代码物理位置**：[`src/pricing/paper_evaluation_engine.py:50, 277-290, 390-396`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L50)
3. **首次引入 Commit**：`9ef9101`
4. **门槛数值**：`MAX_MEDIAN_DEVIATION_THRESHOLD = 8.0` (°F)
5. **判定逻辑与下沉规则**：
   $$\Delta_{\text{median}} = |M_{\text{model}} - M_{\text{market}}|$$
   - 若 $\Delta_{\text{median}} > 8.0^\circ\text{F}$：
     1. 快照总览置 `is_input_suspect = True`；
     2. 记录级打标 `tags.append("INPUT_SUSPECT")`；
     3. 信号熔断：若档位满足正 EV（$\text{edge} \ge 0.05$），**强制剥夺其交易资格**（`is_signal = False`），打标 `QUARANTINED`，状态置为 `QUARANTINED_INPUT_SUSPECT`；
     4. 底账记录：所有档位照常全量落盘（B-4），保留原始数值供观测期复核。

---

### 条款 Annex-A5：跨快照概率稳定容差 `PROB_STATIC_EPSILON`

1. **引入背景与工程目的**：  
   落实判据 A-4（跨快照模型概率不变标记 `PROB_STATIC`）。
2. **代码物理位置**：[`src/pricing/paper_evaluation_engine.py:49, 319-323`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L49)
3. **首次引入 Commit**：`d7a114d`
4. **常数取值**：`PROB_STATIC_EPSILON = 1e-6`
5. **数理依据**：  
   双精度浮点数（IEEE 754 float64）在跨快照序列化与反序列化中存在微小机器精度舍入，采用绝对相等 `p == prev_p` 会导致误漏标。取 $\epsilon = 10^{-6}$（远小于 B-3 门槛 $0.05$ 和价格最小跳位 $0.001$），既能精确捕获静态概率，又不受浮点噪声干扰。

---

### 条款 Annex-A6：单纯形归一化离散截断与均匀回退容差

1. **引入背景与工程目的**：  
   离散高斯区间概率累加防除零保护。
2. **代码物理位置**：[`src/pricing/paper_evaluation_engine.py:176-179`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py#L176-L179)
3. **首次引入 Commit**：`d7a114d`
4. **数学规则**：  
   若各档位高斯积分求和 $\sum_{i=1}^K p_i > 10^{-12}$，则各档位概率严格归一化为 $\tilde{p}_i = p_i / \sum p_j$；若极端情况下求和 $\le 10^{-12}$（如市场设定档位远离模型分布 10 个 $\sigma$ 之外），安全回退为均匀分布 $\tilde{p}_i = 1 / K$，防止程序异常崩溃。

---

### 条款 Annex-A7：生产级 5 成员 GEFS 实时系综提取规范

1. **引入背景与工程目的**：  
   落实位次 3/4 重做要求，接入真实公网 NWP 数据驱动 EMOS。
2. **代码物理位置**：[`src/prediction/real_emos_pipeline.py:33, 209-224, 280-310`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/prediction/real_emos_pipeline.py#L33)
3. **首次引入 Commit**：`9ef9101`
4. **技术规范明细**：
   - **系综协议**：5 成员标准协议，控制报 `c00` + 扰动报 `p01`, `p02`, `p03`, `p04`；
   - **产品网格**：NOAA GEFS `atmos.25` (0.25° 全球高精网格)；
   - **要素场变量**：`:TMAX:2 m above ground:`（日最高温 2m 气温预报）；
   - **起报循环与时效**：起报时次 $T_{\text{target}} - 1\text{day}$ 00:00 UTC，预报时效 $\text{lead\_hours} = 24\text{h}$；
   - **物理单位转换公式**：
     $$T(^\circ\text{F}) = (T_{\text{kelvin}} - 273.15) \times \frac{9}{5} + 32.0$$
   - **无偏方差统计量**：
     $$S^2_{\text{ens}} = \frac{1}{N - 1} \sum_{m=1}^N (T_m - \bar{T}_{\text{ens}})^2 \quad (\text{Python: } \texttt{ddof=1})$$
   - **EMOS 链接函数**：
     $$\mu = a + b \cdot \bar{T}_{\text{ens}}, \quad \sigma^2 = c^2 + d^2 \cdot S^2_{\text{ens}} + \sigma^2_{\text{clim}}(\text{DOY})$$

---

## 三、 委员会逐项裁定决议栏 (裁定席专用)

| 条款编号 | 审定条目名称 | 推荐意见 | 委员会裁定结果 (Approve / Modify / Reject) | 委员签字与批注 |
| :---: | :--- | :---: | :---: | :--- |
| **Annex-A1** | 市场隐含中位数分段线性插值算法 | 推荐批准 | `[ PENDING_COMMITTEE_RULING ]` | |
| **Annex-A2** | NWS ASOS 半度连续性修正 ($\pm 0.5^\circ\text{F}$) | 推荐批准 | `[ PENDING_COMMITTEE_RULING ]` | |
| **Annex-A3** | 高斯分布中位数解析解 ($M_{\text{model}} \equiv \mu$) | 推荐批准 | `[ PENDING_COMMITTEE_RULING ]` | |
| **Annex-A4** | 偏离门禁 `MAX_MEDIAN_DEVIATION_THRESHOLD = 8.0°F` | 推荐批准 | `[ PENDING_COMMITTEE_RULING ]` | |
| **Annex-A5** | 概率稳定容差 `PROB_STATIC_EPSILON = 1e-6` | 推荐批准 | `[ PENDING_COMMITTEE_RULING ]` | |
| **Annex-A6** | 单纯形积分极小值容差与均匀回退 | 推荐批准 | `[ PENDING_COMMITTEE_RULING ]` | |
| **Annex-A7** | GEFS 5 成员实时系综解码与单位转换标准 | 推荐批准 | `[ PENDING_COMMITTEE_RULING ]` | |

---

**呈报结论**：  
本草案所有内容均已对齐当前代码库实测实现（commit `9ef9101`），无任何隐藏数学或掩盖参数。特此呈交委员会审定裁决！
