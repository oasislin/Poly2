# Phase 2 短闭环预注册规格书 (docs/w2_shortloop_preregistration.md)

> **工单编号**：`P7-W2-SHORTLOOP`（账本对应：`ROADMAP.md §3.2 W2`、`Phase 2 Task 02`、`Phase 2 Task 04`）  
> **文档版本**：**Rev.1.1（委员会审议回单 P7-W2-PREREG-R1-RULING 修订呈报版）**  
> **前序版本**：Rev.1（2026-10-10 框架批准，4 项修订）  
> **文书编号**：`P7-W2-PREREG-R1.1`  
> **生效分支**：`main`（主干基线指针 `5c4a4c9`，HEAD `f7a3da4`）  
> **资产版本**：`data/models/manifest.json`（版本 `2.2.0-phase`，1200 节点）  
> **签发机构**：技术裁决委员会  
> **预注册状态**：**PENDING_COMMITTEE_APPROVAL_REV1.1 (等待委员会签发 W2-A 放行令)**  
> **治理铁律**：“预注册先行、判据两步分离、零无授权编辑、零 push”。在委员会正式签署批文前，严格执行生产代码与脚本零编辑、数据管线零动作纪律。

---

## 审议回单 (P7-W2-PREREG-R1-RULING) 修订对照索引

| 意见编号 | 修订性质 | 落实章节 | 核心处置与承诺摘要 |
| :---: | :--- | :---: | :--- |
| **R-W2-1** | WRH 迟到丢弃与结算权威源边界冲突 | **§2.1.1** | **采纳选项 (a) 建立豁免通道**：WRH 迟到极值豁免丢弃，允许单向推进 max/min 并打标 `WRH_LATE_ABSORB` 入审计底账；同时严格剥离交易驱动权（零反向追开仓）。C1 门禁增补 100% 覆盖率断言。 |
| **R-W2-2** | 跨源观测偏差监控缺失 | **§2.1.2** | **建立偏差打标机制**：同时间窗（$\le 5\text{min}$）双源温差 $|\Delta T| > 2.0^\circ\text{F}$ 强制打标 `CROSS_SOURCE_DIVERGENCE` 入审计流水；不阻断交易。C1/C2 增补 100% 覆盖率断言。 |
| **R-W2-3** | 资产调用层级与降级规则未锁定 | **§3.0, 表 3-1** | **全矩阵逐条锁定**：显式落表 1200 节点体系中 KORD/KMIA 调用路径；**KMIA_12h 显式带旗落表**（`COMPLETED_ECE_FLAGGED`）；**路由回退 FAILSAFE 资产强制降级为只读观察**（`READ_ONLY_OBSERVE`，禁出执行信号），纸面盘阶段坚决冻结。 |
| **残缺补正** | C3 门禁验证方法列截断补正 | **§4.1 C3** | **逐字修正闭合**：验证方法明确为“全格 $\mu$ 采样注入 `DiscreteBinEngine`，断言 $\sum p_k - 1.0 \le 1.0 \times 10^{-6}$ 且外尾两桶与解析积分一致”。文档本体确证 100% 完整。 |

---

## 一、 任务背景与战略战术定位

### 1.1 战略定位（依据 ROADMAP.md §3.2 与项目方案 v2.8）
在 Phase 7 过渡态下，项目主线由“横向扩展”全面转向“纵向落地”。随着波次一（W1，工单 `P7-W1-POOLPHASE`）圆满封卷并拔除运行旗 2，系统正式迈入**波次二（W2）：Phase 2 双站短闭环主线**。

- **先锋阵容**：锁定 **KORD**（芝加哥奥黑尔）与 **KMIA**（迈阿密国际机场）双站，直接入役 P6 封卷之 24 时间格 / 96 季节格 TMax 资产；
- **战术短闭环核心链路**：
  $$\text{物理概率分布 } (\mu, \sigma) \longrightarrow \text{双源单调合流与特报截断} \longrightarrow 2^\circ\text{F 离散区间积分} \longrightarrow \text{订单簿快照} \longrightarrow \text{净 EV 动态信号} \longrightarrow \text{只读纸面撮合流水}$$
- **范围收窄与顺延声明**：
  - **核心攻坚**：Task 02（实况多源单调合流与特报引擎）与 Task 04（离散概率映射与动态 EV 引擎）；
  - **顺延项 (`DEFERRED_TO_PRE_LIVE`)**：Task 03（控制面异常中枢跨模块编排）、Task 05（四桶资金与联合多项凯利）、Task 06（CLOB 交易路由与 IOC 保护价）顺延至实盘前置阶段；
  - **纸面盘模式重定义 (`REDEFINED_READ_ONLY`)**：Task 07 重定义为纯只读纸面盘观测模式，严格**零真实资金、零私钥接触、零生产网络下单**。

---

## 二、 双观测流单调合流契约 (Task 02 / ADR-0011 / ADR-0013)

### 2.1 多源职责分工与优先级规则
根据 `ADR-0011`，彻底废除旧版“名义极值前 2h 跨源切换”的时钟状态机，确立**双源全天候单调合流架构（Dual-Active Monotonic Driver）**：

1. **主力物理驱动源（Primary Physical Driver）—— IEM ASOS 实时原报流**：
   - 包含常规整点报（Routine METAR）与特报（SPECI）；
   - 提取精度：强制采用 RMK T 组高精温度（0.1°C 精度，换算为 $\approx 0.18^\circ\text{F}$）；
   - 职责：提供低延迟分钟级高频驱动，负责日内极值快速向前推进；
2. **异步影子对齐源（Asynchronous Shadow Observer）—— NWS WRH 官方时序表**：
   - 职责：定期轮询抓取，用于对齐 Polymarket 官方结算展示及网页端舍入特征；
3. **单调合流数学算子**：
   对于台站当前自然日内的累积极值状态，执行严格单调收紧算子：
   $$T_{\text{max\_so\_far}}^{(t)} = \max\left(T_{\text{max\_so\_far}}^{(t-1)}, T_{\text{IEM}}, T_{\text{WRH}}\right)$$
   $$T_{\text{min\_so\_far}}^{(t)} = \min\left(T_{\text{min\_so\_far}}^{(t-1)}, T_{\text{IEM}}, T_{\text{WRH}}\right)$$
   任何一源合法上报更高（最高温）或更低（最低温）有效物理观测，立即单向收紧截断门禁。

#### 2.1.1 法定结算真值源 WRH 迟到极值豁免通道条款（回应 R-W2-1 采纳选项 a）
针对“迟到不投（丢弃迟到帧）”与“NWS WRH 是官方结算唯一真值源”在时序延迟场景下的潜在背叛，建立严格的**极值推进权与交易驱动权两权分离豁免通道**：

1. **病灶与风险机理**：
   若 NWS WRH 报文因轮询周期、外部发布延迟或网络抖动晚到（如到达延迟 $>15\text{min}$），但其中包含一个更高的极值（例如 $74.0^\circ\text{F}$，而内部 IEM 实时仅记录到 $73.2^\circ\text{F}$）。若机械按迟到帧丢弃，内部截断层将遗漏真实极值，使 $74^\circ\text{F}$ 及更低档位未被正确截断，诱发向死档下注或错杀真实命中档；而 Polymarket 官方最终以 WRH 结算，必然导致真金白银亏损。
2. **豁免通道规则 (Option a)**：
   - **极值推进权豁免（Monotonic Extreme Update Exemption）**：
     NWS WRH 迟到极值记录**绝对豁免丢弃**！允许且必须单向推进累积极值状态：
     $$T_{\text{max\_so\_far}} \leftarrow \max(T_{\text{max\_so\_far}}, T_{\text{WRH}}), \quad T_{\text{min\_so\_far}} \leftarrow \min(T_{\text{min\_so\_far}}, T_{\text{WRH}})$$
     以确保系统内部截断物理状态 100% 与官方结算真值同源对齐；
   - **法医审计打标（Audit Tagging）**：
     该吸收动作必须强制打上 **`WRH_LATE_ABSORB`** 标签记入法医审计日志，记录迟到时长 $\Delta t_{\text{lag}}$ 与吸收前后极值差；
   - **交易驱动权严格剥离（零反向追开仓）**：
     WRH 迟到极值注入引发的重定价，**坚决禁止针对历史已过时刻反向补发开仓交易意图**；其唯一交易侧动作为**毫秒级触发 CancelAll 清空被该极值击穿之死档上的排队挂单**，严格捍卫“错失窗口不追投”原则。

#### 2.1.2 跨源观测偏差实时监控与打标条款（回应 R-W2-2）
为了实时感知双源数据质量与传感器异常，建立跨源瞬时偏差监控机制：

1. **监控触发条件**：
   同一台站在对齐时间窗口（时间戳匹配 $|\Delta t| \le 5\text{min}$）内，若 IEM ASOS 与 NWS WRH 均有有效温度观测值；
2. **偏差判定阈值**：
   计算瞬时温度绝对偏差 $|\Delta T| = |T_{\text{IEM}} - T_{\text{WRH}}|$。若：
   $$|\Delta T| > 2.0^\circ\text{F}$$
   （远超正常的四舍五入与传感器微小差异极限 $0.48^\circ\text{F}$）；
3. **处置动作**：
   - 强制向风控总线与审计日志打标 **`CROSS_SOURCE_DIVERGENCE`** 警示标签；
   - **不阻断交易**（保持系统连续性，因为单调合流算子 $\max / \min$ 具备物理单向保底安全性）；
   - 输出包含双源时间戳、原始温度与差值的法医事件条目供盘后复盘。

### 2.2 覆盖缺口与断流处置机制
1. **NWS WRH 缺失或失联时**：
   - 系统依靠 IEM ASOS 单流维持日内物理极值推进，业务不中断；
   - **自动化绝对红线（ADR-0012 D1）**：在 NWS WRH 页面缺失或失联期间，**绝对严禁任何自动化模块依据 IEM ASOS 数据自动向自由资金池（Free USDC）释放流动性或确认已实现盈亏**，法医影子底账仅供只读留存；
2. **IEM ASOS 断流与两维阶梯风控防线（ADR-0011 D3）**：
   - **第一道防线：到达心跳超时（Feed Arrival Lag > 15 分钟）**：
     系统距离上一成功接收报文超过 15 分钟（连续丢失 3 个 5 分钟发报周期），触发 `WARNING`；
     **CancelAll 铁律**：立即撤销订单簿上所有该站未成交排队挂单，坚决禁止发送任何新开仓订单；已成交持仓绝缘持有至结算；
   - **第二道防线：绝对物理龄期超限（Observation Staleness > 35 分钟）**：
     报文内部 UTC 时间戳距当前墙上时间超过 35 分钟，触发 `DATA_STALENESS`（ERROR 级），该台站强制切入 `SAFE_MODE` 交易熔断；
3. **抗震荡迟滞恢复机制（ADR-0011 D5）**：
   处于降级或撤单保护的站点，必须同时满足：① 接收到新报文且物理龄期 $< 20$ 分钟；② **维持连续 3 帧（至少 15 分钟）持续健康发报**，方可解除封锁，杜绝高频挂撤单震荡。

### 2.3 时间戳基准与物理时空对齐规范
1. **时间戳基准唯一性（ADR-0011 D5）**：
   所有时延、龄期、日历日划分一律以报文解析出的 **UTC 物理观测时间戳（`timestamp_utc`）** 为唯一法定基准；
2. **台站本地自然日划分**：
   绑定台站法定 IANA 时区（`America/Chicago` 用于 KORD，`America/New_York` 用于 KMIA）：
   $$\text{local\_date} = \text{timestamp\_utc}.\text{astimezone}(\text{ZoneInfo}(\text{station.timezone})).\text{date}()$$
   每日当地时间 00:00:00 原子复位日内累积极值状态机；标准库自动吸收夏令时（DST）23h/25h 变换；
3. **常规迟到不投原则（ADR-0013 D2）**：
   除 §2.1.1 明确豁免的 WRH 极值推进外，常规 IEM 报文若物理时间戳早于当前已处理的最大时间戳（乱序帧），或到达延迟超过 15 分钟（迟到帧），系统判定为错过投资窗口，**坚决直接丢弃，绝不反向重算极值，绝不触发模型重新定价，绝不触发新开仓**。

### 2.4 特报（SPECI）纯温三道门禁与跳温安全阻断 (ADR-0013)
1. **极简纯温门禁**：仅提取正文及 RMK 气温，严禁依赖风速、气压、离散天气现象等未审计变量；
2. **三道纯温本征门禁（Pure-Temperature Sanity Gates）**：
   - **门禁 1（绝对气候极值域）**：$T_{\text{dry}} \in [-40.0^\circ\text{F}, 135.0^\circ\text{F}]$，死防溢出与负数乱码；
   - **门禁 2（正文与 RMK T 组交叉检验）**：$|\Delta T_{\text{body-rmk}}| \le 1.8^\circ\text{F}$，防止传输解码撕裂；
   - **门禁 3（单步跳变硬门禁）**：5 分钟单步跳变 $|\Delta T_{5\text{min}}| \le 15.0^\circ\text{F}$（对齐 ADR-0010 物理上限）；
3. **Fail-Closed 异常安全阻断（Station Circuit Breaker）**：
   若单步跳温 $> 15.0^\circ\text{F}$ 或违反上述门禁：
   - 0ms 触发撤销该站全部排队未成交挂单；
   - 该台站当日置为 `STATION_BLOCKED` 状态，禁止开新仓；
   - 已成交链上持仓保持绝缘，持有至到期。

### 2.5 单调合流的可审计判定与截断单向锁定法则 (ADR-0011 D4)
1. **数学不变量审计**：
   对于任意时间点序列 $t_1 < t_2$（同属一个当地自然日）：
   $$T_{\text{max\_so\_far}}^{(t_2)} \ge T_{\text{max\_so\_far}}^{(t_1)}, \quad T_{\text{min\_so\_far}}^{(t_2)} \le T_{\text{min\_so\_far}}^{(t_1)}$$
   此不变量在任何数据断流、丢包、乱序、或重启恢复场景下**绝对不得违背**；
2. **截断门禁单向永久锁定**：
   已被实测超越的死档区间概率（对于 TMax，所有满足区间上限 $\le T_{\text{max\_so\_far}}$ 的档位）置为 0.0。无论外部数据链路发生何种断流、降级或熔断，**已生效的截断概率归零约束永久有效，绝不下线、绝不清空**。

---

## 三、 2°F 离散定价引擎契约 (Task 04 / ADR-0012)

### 3.0 1200 节点资产体系调用路径与降级规则锁定（回应 R-W2-3）

在 manifest `2.2.0-phase`（1200 节点）体系下，先锋双站（KORD / KMIA）在各提前期、标的与季节下的模型调用路径、挂旗状态与降级规则严格逐条锁定如下：

#### 表 3-1：W2 双站模型调用矩阵与挂旗治理表
| 站点 | 标的 | 提前期 Lead | 季节 Season | 磁盘调用路径 (基于 `data/models/`) | 资产类别 | 治理状态与法定运行旗 | 运行时行为与定价约束 |
| :---: | :---: | :---: | :---: | :--- | :---: | :---: | :--- |
| **KORD** | Max/Min | **$L \in [12, 78]\text{h}$** (12 格) | 全四季 | `{STATION}_{SEASON}_{VAR}_lead{L}h.pkl` | `STATUTORY_TRADING_MASTER` | `COMPLETED_UNFLAGGED` (全绿) | 磁盘直读，正常输出 EV 交易信号 |
| **KMIA** | **Max** | **$L = 12\text{h}$** | **全四季** | `KMIA_{SEASON}_Max_lead12h.pkl` | `STATUTORY_TRADING_MASTER` | 🚩 **`COMPLETED_ECE_FLAGGED`**<br>(加权 ECE = 0.018318) | **带旗调用**：必须显式输出 `flag` 注记，头寸硬折剪 50% |
| **KMIA** | Max/Min | **$L \in [18, 78]\text{h}$** (11 格) | 全四季 | `KMIA_{SEASON}_{VAR}_lead{L}h.pkl` | `STATUTORY_TRADING_MASTER` | `COMPLETED_UNFLAGGED` (全绿) | 磁盘直读，正常输出 EV 交易信号 |
| **KMIA** | Min | **$L = 12\text{h}$** | 全四季 | `KMIA_{SEASON}_Min_lead12h.pkl` | `STATUTORY_TRADING_MASTER` | `COMPLETED_UNFLAGGED` (全绿) | 磁盘直读，正常输出 EV 交易信号 |
| **双站** | Max/Min | **$L = 6\text{h}$** | 全四季 | `{STATION}_{SEASON}_{VAR}_lead6h_{cluster}.pkl`<br>(`cluster` $\in$ {`valley`, `peak`, `transition`}) | `PHASE-CLUSTER-PRIMARY` | `COMPLETED_UNFLAGGED`<br>(运行旗 2 已拔除) | 依据本地验证时刻 $LT$ 路由对应簇资产直读，正常输出 EV |
| **双站** | Max/Min | **$0 < L < 6\text{h}$** | 全四季 | 无独立模型，由 `constraint_enforcer.py` 兜底 | `CONSTRAINT_ENFORCER` | `ACTIVE_PRODUCTION_GATE` | 热力学实况硬截断主导，不调用衰减插值器 |
| **双站** | Max/Min | **$L=6\text{h}$ 异常回退** | 全四季 | `{STATION}_{SEASON}_{VAR}_lead6h.pkl`<br>或 `AUXILIARY_POOLED_FALLBACK` | `PHASE-CLUSTER-FAILSAFE` | ⚠️ **`FALLBACK_ASSET`** | **【纸面盘坚决冻结降级】**：**强制降级为只读观察模式 (`READ_ONLY_OBSERVE`)**，打标 `FAILSAFE_DEGRADED_READONLY`，**绝对禁出执行交易信号**！ |

#### 降级规则冻结理由书（R-W2-3 终审锁定）
当 router 发生异常或缺失对应主节点/分簇节点，被迫回退至 `PHASE-CLUSTER-FAILSAFE` 资产时：
1. **物理事实**：FAILSAFE 资产为未分层的粗粒度池化模型，已知在昼夜谐波谷底存在方差系统性虚胖（膨胀比 1.45~1.81），无法保证可靠概率输出；
2. **最高纪律**：“宁可错失，绝不乱投（When in doubt, stay out）”。回退兜底资产在纸面盘中仅用于计算并输出理论参考值以供对比，**坚决置 `is_actionable = False` 且 `suppress_trade = True`，禁止计入虚拟撮合成交**。该规则在纸面盘阶段冻结，严禁推迟至实盘前夕临场裁量！

---

### 3.1 2°F 几何网格生成规格
严格绑定现役 P4/P6 封卷之法定 2°F 吸收分桶引擎（[`src/prediction/discrete_bin_engine.py`](../src/prediction/discrete_bin_engine.py) 之 `generate_2deg_adsorbed_bins`）：

1. **刻度与步长**：步长固定为 $2.0^\circ\text{F}$，区间分割点严格位于偶数整数 $\pm 0.5^\circ\text{F}$ 处（即半度连续性分割线）；
2. **吸收中心确定**：包含预测均值 $\mu$ 的中心偶数整数记为 $2k^* = 2 \times \lfloor(\mu + 0.5) / 2\rfloor$；
3. **完备 11 桶架构**：
   - **左外尾部桶 (Index 0)**：$(-\infty, 2k^* - 8 - 0.5)$，标签形如 `"<52°F"`，`is_tradeable_window = False`；
   - **9 个交易窗口桶 (Index 1 ~ 9)**：从 $2k^* - 8$ 到 $2k^* + 8$，每个跨度 $2^\circ\text{F}$，区间 $[e_k - 0.5, e_k + 2.0 - 0.5)$，中心桶严格落在 Index 5（0-based 4），`is_tradeable_window = True`；
   - **右外尾部桶 (Index 10)**：$[2k^* + 8 + 2.0 - 0.5, +\infty)$，标签形如 `"≥72°F"`，`is_tradeable_window = False`；
   - 11 个分桶严格构成完备互斥事件集合。

### 3.2 离散概率积分与单纯形归一化
1. **多族闭式连续积分**：
   对于分桶 $B_k = [L_k, U_k)$，其物理模型预测概率为：
   $$p_{\text{raw}}(k) = F(U_k) - F(L_k)$$
   其中 $F(\cdot)$ 为 P6 封卷胜出分布族累积分布函数：
   - Gaussian：`scipy.special.ndtr((x - mu) / sigma)`，杜绝浮点下溢；
   - Johnson SU：`scipy.stats.johnsonsu.cdf`；
   - EVT-Hybrid：条件高斯核心段分位数截断与 GPD 厚尾解析积分；
2. **概率单纯形约束**：
   $$p_k = \frac{p_{\text{raw}}(k)}{\sum_{j=0}^{10} p_{\text{raw}}(j)}, \quad \sum_{k=0}^{10} p_k \equiv 1.00000000 \quad (\text{容差 } \le 1.0 \times 10^{-6})$$
3. **截断后条件单纯形重正化**：
   当实况极值注入导致某些档位物理死亡（$p_{\text{dead}} \equiv 0.0$）后，剩余存活档位执行单纯形条件概率重正化：
   $$p'_k = \frac{p_k}{\sum_{j \in \text{Alive}} p_j}$$
   确保乘法侧严格归一，防止概率和萎缩扭曲胜率。

### 3.3 法定结算口径与临界四舍五入规范 (ADR-0012 D3)
1. **算术四舍五入（Half-Up）**：
   Polymarket 官方结算严格遵循 NWS WRH 算术四舍五入，强制采用 Python `decimal` 模块 `ROUND_HALF_UP` 定点计算：
   $$\text{settle\_temp} = \text{int}\left(\text{Decimal}(\text{str}(T_{\text{obs\_f}})).\text{quantize}(\text{Decimal}("1"), \text{rounding}=\text{ROUND\_HALF\_UP})\right)$$
   严禁使用 Python 原生 `round()`（银行家舍入）；.50 必须坚决向上进位；
2. **临界哨兵预警（Borderline Sentinel）**：
   当观测极值落在任何整数的 $[X.45, X.55]^\circ\text{F}$ 闭区间内时，自动标记 `BORDERLINE_CRITICAL` 标签，并输出进位与舍去双向结算沙盘。

### 3.4 动态 EV 报价与订单簿穿透规则
1. **输入要素**：
   - 档位存活概率向量 $\mathbf{p}'$；
   - CLOB 订单簿深度快照（Ask 深度向量：价格 $P_m$、数量 $Q_m$）；
   - 动态费率模型 $f$（Polymarket 费率，Taker/Maker）；
2. **穿透有效加权买入成本**：
   对于欲买入数量 $V$，加权成本 $P_{\text{eff}} = \frac{\sum P_m \cdot q_m}{V}$；
3. **净期望收益与边缘**：
   $$\text{EV}_{\text{net}} = p_k \cdot (1.0 - f) - P_{\text{eff}}, \quad \text{Edge} = \frac{\text{EV}_{\text{net}}}{P_{\text{eff}}}$$
4. **正 EV 信号生成契约**：
   仅当 $\text{Edge} \ge \text{min\_reprice\_edge}$（受控配置值，默认 0.03）且 $p_k > 0.0$ 且非 `FAILSAFE_DEGRADED_READONLY` 状态时，生成有效 `EVTradeSignal`；死档（$p_k = 0.0$）净 EV 必然为负，绝对禁止生成买入信号。

### 3.5 可交易窗口（is_tradeable_window）过滤规则
1. **执行侧过滤**：
   系统严格禁止向任何 `is_tradeable_window == False` 的分桶（即 Index 0 与 Index 10 两个外侧长尾桶）下达任何交易意图或挂单；
2. **评估侧同源过滤（继承 P6 0.018318 管道）**：
   在门禁可靠度评估与 ECE 计算中，严格对齐 P6 封卷管道：
   `is_tradeable_window = (prob >= 0.02) | (bin_index in window_slots)`。

---

## 四、 门禁与判据预定义 (C1 ~ C6 体系，先冻结后执行)

参照 W1 先例，W2 所有开发与验证动作必须严格受控于以下预定义门禁。判据两步分离：**原始实测值 vs 冻结阈值 $\implies$ 机械结论**。

### 4.1 验收门禁判据表（吸收 R-W2-1 ~ R-W2-3 与残缺补正）

| 编号 | 门禁名称 | 判定阈值 / 门槛指标 | 门禁性质 | 验证计算方法与数据源 |
| :---: | :--- | :--- | :--- | :--- |
| **C1** | **单调合流不变量、截断单向锁定与 WRH 豁免门禁** | **单调违规次数 $\equiv 0$；<br>数据断流期截断下线次数 $\equiv 0$；<br>WRH 迟到极值豁免与打标覆盖率 $= 100\%$；<br>跨源偏差 $>2.0^\circ\text{F}$ 监控打标覆盖率 $= 100\%$** | 物理与数据硬门禁 | 全天候时序流式注入下，断言 $T_{\text{max}}^{(t)} \ge T_{\text{max}}^{(t-1)}$ 且 $T_{\text{min}}^{(t)} \le T_{\text{min}}^{(t-1)}$ 100% 成立；断流期死档概率保持 0.0；注入迟到 WRH 报文，断言极值吸收且打标 `WRH_LATE_ABSORB`；注入同窗偏差 $>2.0^\circ\text{F}$ 报文，断言打标 `CROSS_SOURCE_DIVERGENCE` |
| **C2** | **特报纯温门禁与迟到阻断门禁** | **常规迟到帧丢弃率 $= 100\%$ (漏检 0)；<br>跳温 $>15^\circ\text{F}$ 阻断率 $= 100\%$；<br>未成交撤单率 $= 100\%$；持仓绝缘率 $= 100\%$** | 风控硬门禁 | 注入 $[-40, 135]^\circ\text{F}$ 越界、正文 vs RMK 偏差 $>1.8^\circ\text{F}$、跳变 $20^\circ\text{F}$、常规迟到 $25\text{min}$ 报文，断言 Fail-Closed 触发 |
| **C3** | **2°F 离散区间积分单纯形守恒门禁**<br>*(残缺补正对齐)* | **全格最大单纯形偏差 $|\sum p_k - 1.0| \le 1.0 \times 10^{-6}$；<br>外尾两桶与解析积分绝对吻合** | 数学硬门禁 | **全格 $\mu$ 采样注入 `DiscreteBinEngine`，断言 $\sum p_k - 1.0 \le 1.0 \times 10^{-6}$ 且外尾两桶与解析积分一致**（覆盖 Gaussian, JSU, EVT 三族分布） |
| **C4** | **动态 EV 计算、净 Edge 真实性与降级防护门禁** | **死档买入信号数 $\equiv 0$；<br>浮点误差 vs 定点 Decimal $\le 1.0 \times 10^{-6}$；<br>FAILSAFE 资产可交易信号数 $\equiv 0$** | 定价硬门禁 | 注入多档位订单簿快照（薄/厚盘口与死档报价），断言费率扣减后 EV 与 Edge 严格无误，死档零开仓；模拟路由失败退入 FAILSAFE，断言强制降级为只读观察，可执行信号为 0 |
| **C5** | **双站只读纸面盘零资金零私钥门禁** | **真实外部资金变动 $\equiv \$0.00$；<br>生产私钥加载次数 $\equiv 0$；<br>模拟撮合流水真实性 $= 100\%$** | 治理安全门禁 | 运行纸面盘模拟链路，静态扫描代码与动态监控环境变量，确证处于 `REDEFINED_READ_ONLY` 模式 |
| **C6** | **全量测试套件零回归护航门禁** | **`1006 + N passed, 0 failed`；<br>退出码严格为 0；必须附带真实执行用时** | 交付门槛 | 全库回归测试套件 `pytest tests/` 机械判定，零失败，零退化 |

### 4.2 门禁计算口径冻结规范
1. **数据与样本隔离**：单测与集成测试均基于受控合成用例与既有历史夹具，**严禁触碰 2019 年数据**；
2. **台站宇宙锁定**：严格限定为 **KORD** 与 **KMIA** 双站，严格引用 `src/data_processing/constants.py` 受控元数据；
3. **数值精度**：温度统一至 $0.01^\circ\text{F}$，概率单纯形容差 $10^{-6}$，资金计算强制采用 6 位 `Decimal`。

---

## 五、 禁触清单预定义 (Ironclad Prohibited List)

在 W2 研发、测试与纸面盘运行全周期，以下清单为**绝对禁触红线**，未经委员会专项立宪裁决严禁任何形式的触碰或修改：

1. **2019 独立样本外盲测年物理隔离（Airgap）**：
   - 2019 年日历数据作为终极封盘盲测集，代码级受 `verify_year_whitelist` 保护；
   - 严禁在 W2 中以任何形式加载、训练、微调或泄漏 2019 年样本；
2. **封卷 24 时间格 / 96 季节格主节点资产体系保持 100% 冻结**：
   - P6 封卷之 24 时间格（96 季节格）主节点与 W1 重训之 6h 分簇资产保持封存；
   - 严禁擅自修改参数、重拟合模型或扩张不存在的时效节点（如严禁新建 24h Max 主节点）；
3. **JSU-GATE 两段式门控立法绝对维持**：
   - 偏度门控 $|\text{Skew}| > 0.40$、峰度门控 $\text{Kurt} > 1.00$、$\Delta\text{BIC} < -10.0$；
   - 严禁借短闭环之机搭车修改为去门控纯 BIC 机制（议题 `P6-RESEARCH-NO-GATE-BIC` 维持 `REGISTERED`）；
4. **顶级组件 `constraint_enforcer.py` METAR 热力学上限硬截断层绝对维持**：
   - $T_{\text{max\_possible}} = T_{\text{now}} + r_{\text{warm}}\cdot \Delta t$ 物理可达区间硬截断层保持现役效力，严禁移除或削弱；
5. **R2 §8.2.3 四项已知分桶缺陷带旗沿用（禁止顺手修补）**：
   - ① 吸收分桶极值截断效应；
   - ② `settle_half_up` 边界偏置；
   - ③ 低频桶合并方差失配；
   - ④ 有限样本 ECE 向上有偏性；
   - 上述 4 项属于历史冻结口径，Phase 2 若受影响必须在报告中显式披露挂旗，严禁擅自修改底层分桶逻辑；
6. **🚩 KMIA_12h 挂旗资产下游强制带旗引用**：
   - 交易盘口映射与定价引擎调用 KMIA 12h 时，必须在日志与元数据中显式带旗（`COMPLETED_ECE_FLAGGED`），审慎收缩仓位，严禁脱旗裸跑；
7. **历史 Wunderground 资产绝缘隔离**：
   - 严禁在生产代码中引入任何 Wunderground 数据抓取或依赖；
8. **零无授权生产代码修改与零 push**：
   - 未获批文前，严格执行生产代码（`src/` 与 `scripts/`）零编辑纪律；
   - 代码同步严格遵循人工指令，绝不擅自执行 `git push`。

---

## 六、 自动化测试护航清单规划

为确保 C6 门禁顺利达标，W2 计划扩展并加固以下测试组件：

1. **多源单调合流与特报门禁测试套件 (`tests/unit/prediction/test_monotonic_confluence.py`, `test_temperature_sanitizer.py`)**：
   - 覆盖单调性单向累积（TMax 只增不减，TMin 只减不增）；
   - 覆盖三道纯温门禁与跳温 15°F 拦截；
   - 覆盖常规迟到 15min 丢弃与时间戳乱序丢弃；
   - **覆盖 WRH 迟到极值豁免通道、单向极值推进与 `WRH_LATE_ABSORB` 打标断言 (R-W2-1)**；
   - **覆盖同窗双源温差 $>2.0^\circ\text{F}$ 触发 `CROSS_SOURCE_DIVERGENCE` 打标断言 (R-W2-2)**；
   - 覆盖当地自然日 00:00:00 原子跨日复位；
2. **两维阶梯风控与迟滞恢复测试套件 (`tests/unit/risk/test_stream_watchdog.py`)**：
   - 覆盖 15min 心跳丢失触发 CancelAll 未成交撤单断言；
   - 覆盖 35min 绝对物理龄期超限触发 SAFE_MODE 熔断断言；
   - 覆盖连续 3 帧（15min）健康发报迟滞恢复断言；
3. **2°F 离散区间积分与单纯形测试套件 (`tests/unit/prediction/test_discrete_bin_engine_2deg.py`)**：
   - 覆盖 11 桶几何网格生成与中心桶对齐断言；
   - 覆盖 Gaussian / JSU / EVT 三族分布全格 $\mu$ 采样区间积分，断言单纯形和 $\sum p_k - 1.0 \le 1.0 \times 10^{-6}$ 且外尾两桶与解析积分一致 (R-W2-3 / 残缺补正)；
   - 覆盖死档截断置零与条件概率重正化；
4. **动态 EV 引擎与资产降级测试套件 (`tests/unit/pricing/test_dynamic_ev_engine.py`)**：
   - 覆盖订单簿薄/厚深度加权成本 $P_{\text{eff}}$ 计算；
   - 覆盖手续费扣减与正 EV 信号阈值过滤；
   - 覆盖死档（$p=0$）强制拒绝生成交易信号；
   - **覆盖 KMIA_12h 带旗调用输出与仓位折剪断言 (R-W2-3)**；
   - **覆盖路由回退 FAILSAFE 资产强制降级为只读观察（`READ_ONLY_OBSERVE`）与禁出交易信号断言 (R-W2-3)**；
5. **集成与端到端测试套件 (`tests/integration/test_w2_shortloop_pipeline.py`)**：
   - 双站实况流 $\to$ 单调截断 $\to$ 2°F 积分 $\to$ 订单簿撮合 $\to$ 模拟流水端到端贯通；
   - 断言零资金、零私钥、零未捕获异常。

---

## 七、 结论与呈报批复请示

本规格书已按委员会审议回单 `P7-W2-PREREG-R1-RULING` 完成全部 4 项修订：
1. 确立 WRH 迟到极值豁免通道（选项 a）与两权分离，消除截断伪安全盲区；
2. 建立跨源温差 $>2.0^\circ\text{F}$ 的 `CROSS_SOURCE_DIVERGENCE` 监控打标机制；
3. 逐条锁定双站 1200 节点资产调用矩阵，KMIA_12h 显式带旗落表，冻结 FAILSAFE 资产降级只读观察规则；
4. 闭合 C3 门禁验证方法定义，确保全书字句严密、无残缺。

**现正式呈报《Phase 2 短闭环预注册规格书 (Rev.1.1)》，请委员会终审并签发 W2-A 放行令！**
