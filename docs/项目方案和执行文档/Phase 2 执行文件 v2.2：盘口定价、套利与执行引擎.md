---
created: 2026-09-20 14:45:00
updated: 2026-11-13
---

# Phase 2 执行文件 v2.2：盘口定价、套利与执行引擎

**版本**：v2.2 Engineering-Spec Final  
**状态**：APPROVED & READY FOR IMPLEMENTATION (W2 战术执行)  
**前置依赖**：
1. Phase 1.5 终局产物：统一校准数据集 `data/processed/calib-dataset-v2.0/`（Git Tag: `phase1.5-final`）；
2. 气象模型资产：Active 10 站 960 个生产级模型全矩阵（`data/models/` 已落盘）；KORD / KMIA 双城 TMax 24 时间格（96 季节格）20 折 Block-CV 审计封盘工件（PR #129, Commit `6fe386c`）；
3. 前置架构裁决：`ADR-0011`（双源合流）、`ADR-0012`（WRH 结算与僵尸估值）、`ADR-0013`（特报截断）、`ADR-0014`（统一异常仲裁中枢）；
4. 战略路线图：[`docs/ROADMAP.md`](../ROADMAP.md)（三波次路线图，W2 双站只读纸面盘短闭环）；
5. 交易宇宙：Active 10 交易台站（`KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS`）。

---

## 0. 版本变更摘要（v2.0 → v2.1 勘误与演化对账）

1. **补齐模型重训夹缝断层（新增 Task 01 门禁）**：彻底终结老 Phase 1 参数复用幻想，将“基于 `calib-dataset-v2.0` 训练 Active 10 站生产级 EMOS 参数并完成验收”确立为 Phase 2 首要交付项；
2. **彻底废除 Wunderground 切换窗，确立双源单调合流架构（对齐 ADR-0011）**：METAR 与 NWS 观测流仅用于高频单调截断，废弃跨源切换与短阈值，构建 TMAX/TMIN 对称截断与两维阶梯风控；
3. **法定结算真值源切换为 NWS WRH 官方时序表（Time Series Tabular，即 CF6 每日气候报表；对齐 ADR-0012）**：废弃 Wunderground 结算假定；引入低流动性下僵尸仓位“双轨估值”（风控盯模型、会计盯盘口）与全局精确 `Decimal` 舍入闭环；
4. **特报（SPECI）高频截断与极简物理门禁（对齐 ADR-0013）**：确立 SPECI 极简纯温门禁（杜绝非温复杂字段风暴）、“迟到不投”原则与跳温硬性物理安全阻断；
5. **统一异常仲裁中枢与台站级安全挂起协议（对齐 ADR-0014）**：废除各模块分散自作主张的异常处理，确立控制面统一中枢；划分数据面 30s 自愈静默预算与控制面升级边界；确立 Fail-Closed（0ms 撤单禁开新仓）、已成交仓位绝缘、交割日策略后门与本地单站拔网线机制；
6. **台站宇宙固化**：正式剔除 `KDCA`，纳入 `KAUS`，锁定 10 站主力宇宙；
7. **任务矩阵垂直切片化**：拆分为 7 个清晰递进、依赖严密的垂直任务切片（Task 01 ~ Task 07）；
8. **[v2.1 / P7-DOC-RECON 勘误与演化说明 (2026-10-10)]**：
   - **模型数量与资产演化**：澄清 Task 01 规划之“200 组参数矩阵”到生产模型库“960 个生产模型（10 站 × 2 标的 × 4 季 × 12 提前期）”的全量落盘演化路径；
   - **训练与评估窗口统一（D5 口径裁决）**：法定训练窗口统一确立为 2000–2018（19 日历年 / 6,940 天），2019 为独立样本外盲测年（物理 Airgap 隔离）；澄清 20 折 Block-CV 中的 13,740 / 13,739 实质为验证块折·日总和（覆盖 5,860 唯一日历日）；
   - **验收体系收口**：明示 Task 01 原三重验收标准由 P5/P6 生产审计体系（20 折 Block-CV + 两段式 BIC 竞争自动选型 + 气象门禁 ECE $\le 5.0\%$ 统一；交易窗口加权 ECE $\le 0.0100$ 为交易侧内部解耦口径）继承替代；
   - **三波次路线图对齐**：对齐 Phase 2 内部三波次执行节奏（`docs/ROADMAP.md`），Phase 2 执行战术收窄为波次二（W2）双站只读纸面盘短闭环（攻坚 Task 02 与 Task 04；Task 03/05/06 顺延至实盘前置阶段）。

---

## 一、 系统全景数据流与事件驱动架构

Polymarket 温度市场是完备互斥区间的二元期权集合。Phase 2 的核心使命是：**以 Phase 1.5 产出的客观物理概率分布为基石，通过高频实况单调截断与物理硬约束，结合订单簿微观结构与多项联合凯利优化，在统一异常仲裁中枢与两维风控的严密护航下，实现无滑点穿透、无逆向选择踩踏的稳健套利执行。**

```
                       ┌─────────────────────────────────────────────────────────┐
                       │               控制面：统一异常仲裁中枢 (ADR-0014)         │
                       │   [30s 自愈预算衰竭 / 物理撕裂 / 心跳超时 / 本地拔网线]   │
                       └────────────────────────────┬────────────────────────────┘
                                                    │ 广播 Incident / Fail-Closed 指令
                                                    ▼
┌──────────────────────┐               ┌─────────────────────────┐               ┌──────────────────┐
│  Phase 1.5 Dataset   │               │ Polymarket WSS (Market) │               │ REST /books API  │
│(calib-dataset-v2.0)  │               │   (Orderbook Push)      │               │   (Snapshot)     │
└──────────┬───────────┘               └────────────┬────────────┘               └────────┬─────────┘
           │                                        │                                     │
           ▼                                        ▼                                     │
┌──────────────────────┐               ┌─────────────────────────┐                        │
│ Task 01: EMOS Engine │               │   Event Trigger Bus     │◀───────────────────────┘
│ (Active 10 站重训)    │──────────────▶│  (观测事件 / 盘口推送)    │
│ 输出 960 生产模型     │               └────────────┬────────────┘
└──────────────────────┘                            │
                                                    ▼
┌──────────────────────┐               ┌─────────────────────────┐               ┌──────────────────┐
│  实况观测流接入       │               │      EV Calculator      │◀─────────────▶│  四桶资金状态机   │
│  - IEM METAR (高频)  │──────────────▶│  (区间概率积分 ndtr)     │               │  - Free USDC     │
│  - NWS (单调合流)    │               │  (FeeStrategy 动态注入) │               │  - Active Locked │
│  (ADR-0011 / 0013)   │               └────────────┬────────────┘               │  - Zombie Margin │
└──────────────────────┘                            │ (+EV 信号)                  │  - Disputed Pool │
                                                    ▼                            │  (ADR-0012 双轨) │
                                       ┌─────────────────────────┐               └────────┬─────────┘
                                       │   Multinomial Kelly     │                        │
                                       │    SLSQP 数值优化器      │◀───────────────────────┘
                                       │ (沉没成本增量 / 输入安全) │ (流动性水位与硬顶约束)
                                       └────────────┬────────────┘
                                                    │ (OrderIntent 向量)
                                                    ▼
                                       ┌─────────────────────────┐
                                       │   Order Router & Risk   │
                                       │ - IOC 保护价深度防御     │
                                       │ - 残局敞口重估状态机     │
                                       │ - 两维阶梯风控 (ADR-0011)│
                                       └─────────────────────────┘
```

---

## 二、 任务矩阵与实施路线图 (Task Matrix)

| 任务项 | 核心目标 | 核心输入 / 依赖 | 交付物与验收标准 | 关联 ADR / 规范 |
|---|---|---|---|---|
| **Task 01 模型重训与验收** | 在 `calib-dataset-v2.0` 上全量重训 Active 10 站 960 个生产模型矩阵，通过 P5/P6 审计体系验收 | `calib-dataset-v2.0`, 新 Climate Floor | 960 个生产模型落盘 `data/models/`；KORD/KMIA 双城 24 时间格完成审计封卷（气象门禁 ECE $\le 5.0\%$；ECE $\le 0.0100$ 与挂旗治理属交易侧内部口径） | §3.1, §4, docs/ROADMAP.md |
| **Task 02 多源合流与特报引擎** | 搭建实况观测接入管道，实现 METAR 与 NWS 单调合流及 SPECI 纯温高频截断 | IEM METAR 流, NWS 观测流 | 单调更新器、SPECI 纯温门禁、迟到不投丢弃器；单测覆盖单调不回退与异常跳温阻断 | ADR-0011, ADR-0013 |
| **Task 03 统一异常仲裁中枢** | 落地控制面统一异常仲裁中枢、台站级挂起协议与本地单站拔网线机制 | 事件总线, 交易发射网关 | `CentralExceptionArbiter` 状态机；Fail-Closed 0ms 撤单；30s 预算衰竭升级；本地拔网线 CLI（顺延至实盘前置） | ADR-0014 |
| **Task 04 概率映射与 EV 引擎** | 连续物理分布向离散区间积分映射，动态注入 Polymarket 费率模型 | Task 01 (μ, σ), 订单簿快照 | `BinConverter` (多族积分), `DynamicCorrector`, `ConstraintEnforcer`, `EVCalculator` 动态策略 | §2, §6 |
| **Task 05 资金状态机与联合凯利** | 实现四桶资金管理、僵尸仓位双轨估值与多项联合对数财富增量优化器 | EV 信号, 账户资产状态 | `BankrollStateMachine` (Decimal 舍入闭环), `MultinomialKellyOptimizer` (SLSQP 鲁棒求解)（顺延至实盘前置） | ADR-0012, §3 |
| **Task 06 执行引擎与残局状态机** | 深度穿透防御 IOC 保护价限价单路由与非原子成交残局对冲/止损 | 订单意图, CLOB 盘口 | `OrderRouter` (IOC 保护价), `ResidualRiskStateMachine` (补单/对冲/硬止损)（顺延至实盘前置） | §4 |
| **Task 07 风控联动与纸面盘验证** | 集成两维阶梯风控，全套注入测试 A~E，启动 Active 10 站只读纸面盘模拟（Paper Trading） | 全部前序模块, 仿真测试集 | 注入测试套件 CI 全绿；只读纸面盘运行 48h 零非物理撮合，净 EV 信号稳健 | ADR-0011~0014, §5, §7 |

> **[v2.1 / P7-DOC-RECON 任务演化与收口说明]**：  
> - **Task 01 模型数量与资产演化路径**：原表述“200 组参数”系早期粗粒度规划，现已演化为完备生产模型库全矩阵：**Active 10 站 $\times$ 2 标的 (TMax / TMin) $\times$ 4 季 $\times$ 12 提前期 (6h~72h) = 960 个独立生产模型**（全量 `.pkl` 均已落盘 `data/models/`；注：依裁决 D6，6h 模型作为 PHASE-CLUSTER 回退层用于与实况对照印证，不直接预测、不进入主结算 PnL 计算）；  
> - **Task 01 训练窗口统一（D5 口径裁决）**：法定训练窗口锁定为 **2000–2018（19 个日历年 / 6,940 天）**，**2019 为独立样本外盲测检验年**（代码级 `verify_year_whitelist` 物理 Airgap 隔离，零未来信息泄露）；同时澄清：全网格交叉验证中的 13,740 / 13,739 实质为 20 折 Block-CV 验证块的**折·日总和（Total Fold-Days）**（对应 5,860 唯一独立日历日），绝非日历覆盖年数，不与口径 A（台站历史观测史 $\ge 30$ 年）冲突；  
> - **Task 01 验收体系继承替代条款**：原“三重验收标准”已由 **P5/P6 生产审计体系全面继承替代**（以 20 折 Block-CV + 两段式 BIC 竞争自动选型 + 气象门禁 ECE $\le 5.0\%$ 为准；交易窗口加权 ECE $\le 0.0100$ 属交易侧内部口径，两侧解耦）；KORD 与 KMIA 双城 TMax 24 时间格已完成审计封盘；KMIA 12h（ECE=0.018318）及 6h 池化回退层带旗服役并进入 W1 专单修复流程；  
> - **2019 盲测体检尺 V2.0 指针（P4-BLIND-AUDIT-V2R01，与本文件生产验收解耦）**：2019 独立样本外年的盲测评估尺已由 V1.0 固定工程带升级为 V2.0（$N_{\text{eff}}$ 动态非对称 Finf/Fstd 双带、KS+CvM 方案乙、11 档档级 ECE + 概率等宽桶敏感性、PIT 方差），终审四项通过、闭环；该尺为单年事后体检，不改变本文件 Task 01 的 P5/P6 生产验收体系（20 折 Block-CV + ECE≤5.0%），不重训、不改模型参数。规格见 `docs/audit/第二类_V2尺子升级_方案书_20261021.md`。
> - **Phase 2 战术执行收窄（三波次路线图对齐）**：依据委员会 P7 转向裁决，Phase 2 执行战术收窄为波次二（W2）双站只读纸面盘短闭环（先锋站 KORD/KMIA，攻坚 Task 02 与 Task 04，以只读观测模式验证正 EV 信号）；Task 03（异常仲裁）、Task 05（资金凯利）、Task 06（IOC 路由）顺延至实盘前置阶段（`DEFERRED_TO_PRE_LIVE`）。

---

## 三、 核心模块技术规格细化

### §1 概率映射与动态截断层 (Task 01, Task 04)

1. **离散概率映射**：
   - 目标区间 $[B_i, B_{i+1})$ 的模型预测概率：
     $$p_{model}(i) = F(B_{i+1}) - F(B_i)$$
   - 其中 $F(\cdot)$ 为所选分布族的累积分布函数（CDF）：
     - 高斯分布：调用 `scipy.special.ndtr` 计算累积分布，杜绝浮点下溢；
     - Johnson SU 分布：调用 `scipy.stats.johnsonsu.cdf`；
     - EVT-Hybrid 极值混合：条件高斯分位数截断与广义帕累托尾部积分；
   - 概率离散归一化：所有档位概率和严格约束为 1.0（允许 $10^{-6}$ 浮点公差）。
2. **方差结构标准对齐（P6 BIC 裁决）**：
   - 废除历史气候方差加法项，严格采用 EMOS 平方参数化标准形式：
     $$\sigma^2 = c^2 + d^2 \cdot S_{ens}^2$$
   - 截距参数 $c$ 设有物理下限托底门限（防集合离散度坍缩时的过度自信）。
3. **物理硬拦截处理**：
   - 经三层预测栈顶级组件 `ConstraintEnforcer` 拦截置 0 的档位，保持 $p_{model}(i) = 0.0$；
   - 凯利优化器必须保证“乘法侧为零”，严禁预计算 $\ln(p_i)$。
4. **方案 `α` 分布契约与参数数据源（[v2.2] B1）**：
   - 定价面消费方案 `α` 五元组契约：$(\mu_0,\; \sigma_{\text{eff}},\; \text{family},\; \text{shape\_params},\; c)$，辅以标准化先验期望查表 $\mathbb{E}[Z]$（其中 $c = \sqrt{\max(1.0,\; s_{\text{oos}})}$）；
   - **数据源与资产实况**：
     - 盲测方差比 $s_{\text{oos}}$ 与样本契约源自 [`data/contracts/physical_param_contract.json`](../../data/contracts/physical_param_contract.json)；
     - `station × season` 分布族与形状参数源自 [`evidence/p4_active10_climate_calibration.json`](../../evidence/p4_active10_climate_calibration.json)；
     - 照录 [`data/models/manifest.json`](../../data/models/manifest.json) 实况：`1200` 项中 **`880 None / 127 {} / 193 非空 dict`**，尚未覆盖全部 `787` 个非高斯网格（关联 `D6` 整改项，当前须由站×季静态 JSON 兜底并待 `shape_params` 完整入库）；
   - **$\mu_0$ 动态组装规格**：$\mu_0 = \mu_{\text{calib}} = a + b \cdot \mu_{\text{ens}} + b_{30}$，线性回归参数 $(a, b)$ 读取自对应生产模型权重/元数据（`data/models/*.pkl` / `manifest.json`），$b_{30}$ 由历史观测与模型校准均值之因果 30 日滑动残差动态组装（冷启动默认 `0.0000°F`）；
   - **量化边际形状距离支撑**：引 [`evidence/p8_algo_2019_settlement_shape_distance_20261113.md`](../../evidence/p8_algo_2019_settlement_shape_distance_20261113.md) 2019 盲测 88 单元（族分布 vs 同均值同方差高斯矩匹配版）实测：右尾 `dq99` 峰值 **`+5.8458°F`**（`KORD_48h Winter`），左尾 `dq01` 峰值 **`-3.3565°F`**（保留两位小数 `-3.36°F`，`KMIA_48h Winter`），证实极端尾部偏离数度，禁止用单高斯近似代替偏态/厚尾分位数积分。
5. **日内方差修正前移与物理底合成规则（[v2.2] B2，按 `SPEC v2.0#L186, L206`）**：
   - 方差膨胀系数 $c = \sqrt{\max(1.0,\; s_{\text{oos}})}$ **必须在进入日内条件桥之前前移作用于先验基准**：
     $$\sigma_0 = c \cdot \sigma_{\text{eff}} = \sqrt{\max\!\big(10^{-8},\; c_{\text{emos}}^2 + d^2 \cdot \sigma_{\text{ens}}^2\big)} \cdot c$$
     随后随日内归一化剩余方差比例 $\eta_s(t)$ 演化，并与 ASOS 1088 PRT 物理仪表精度常数 $0.9^\circ\text{F}$ 取 `max`：
     $$\sigma_{\text{rem}}(t) = \max\!\left(\sigma_0 \cdot \sqrt{\eta_s(t)},\; 0.9^\circ\text{F}\right) \equiv \sigma_0 \sqrt{\max\!\left(\eta_s(t),\; \left(\frac{0.9^\circ\text{F}}{\sigma_0}\right)^2\right)}$$
   - **禁令**：**严禁将 $c$ 置于 $\max(\cdot, 0.9^\circ\text{F})$ 外侧后乘**——`0.9°F` 系传感器物理精度常数，不随模型方差校正缩放（$c \cdot \max(\sigma_{\text{eff}}\sqrt{\eta_s(t)}, 0.9^\circ\text{F}) \ne \max(c\sigma_{\text{eff}}\sqrt{\eta_s(t)}, 0.9^\circ\text{F})$）。
6. **现役实现状态声明——完整非对称分位/CDF 支持（[v2.2] B3）**：
   - **当前状态：现役未满足**。原规划 `EVCalculator`（`src/pricing/ev_engine.py`）已于 `2026-10-13` `R-16` 归档；现役最小内核 [`src/pricing/penetration_probe.py`](../../src/pricing/penetration_probe.py) 仅接收外部传入的标量概率 `p_hat`；现役推理概率链 `StaticPredictor` / `DiscreteBinEngine` / `BinConverter` 仅消费纯高斯（`ndtr`），**尚不具备对 Johnson SU / EVT-Hybrid 叠加 $\mathbb{E}[Z]$ 中心偏移与前移膨胀 $c$ 的完整分位/CDF 积分实现**，列为 Phase 2 待重建核心工程缺口。

### §2 多源单调合流与特报截断 (Task 02 - ADR-0011, ADR-0013)

1. **单调合流架构**：
   - 彻底废除旧版“极值前 2h 切换 Wunderground”逻辑；
   - 观测流接收 IEM METAR（高频整点与特报）与 NWS 本地观测；
   - 观测值推进执行**单调约束**：
     - 最高温（TMAX）：$T_{now}^{(t)} = \max(T_{now}^{(t-1)}, T_{obs})$（单调非递减）；
     - 最低温（TMIN）：$T_{now}^{(t)} = \min(T_{now}^{(t-1)}, T_{obs})$（单调非递增）。
2. **特报（SPECI）极简接入**：
   - **纯温门禁**：仅提取正文及 RMK 中的气温字段，严格忽略非温告警风暴；
   - **迟到不投**：若观测时间戳早于当前台站已处理的最新时间戳，视为迟到原报，直接丢弃，绝不反向重算；
   - **物理跳温阻断**：若单次跳温 $|\Delta T| > 15^\circ\text{F}$（且无雷暴/大风额外观测佐证），触发异常安全阻断，向统一中枢上报 `PHYSICAL_TEAR` Incident。

### §3 统一异常仲裁中枢与挂起协议 (Task 03 - ADR-0014)

1. **控制面唯一中枢**：
   - 模块内仅允许技术性瞬态自愈（重试预算 $\le 30\text{s}$）；
   - 自愈超时、物理撕裂、心跳断流强制向 `CentralExceptionArbiter` 提交标准 `IncidentReport`。
2. **Fail-Closed 物理动作**：
   - 触发严重异常后 0 毫秒内：下发 `cancel_all_open_orders(station)` 并设置 `forbid_new_positions(station)`；
3. **两阶段仲裁**：
   - 链路瞬断 $\to$ `SUSPENDED`（挂起冷却，保持健康探针检测，15min 稳定恢复）；
   - 物理撕裂 $\to$ `INVALIDATED`（作废当日交易至 00:00:00 LT）。
4. **仓位绝缘与本地拔网线**：
   - 异常触发时，已成交持仓坚决不市价踩踏强平（绝缘恐慌自残）；
   - 保留物理后门：检测到项目根目录 `EMERGENCY_STOP_<STATION>` 标记文件时，立即单站硬件级阻断。

### §4 资金管理、僵尸仓位与多项联合凯利 (Task 05 - ADR-0012)

1. **四桶资金状态机**：
   $$\text{Total Bankroll} = \text{Free USDC} + \text{Active Locked} + \text{Zombie Margin} + \text{Disputed Pool}$$
   - 全局流动性警戒线：$\text{Active Locked} / \text{Total Bankroll} > 0.70$ 触发熔断；
   - 单市场硬顶：单一互斥市场总下注 $\le 10\% \times \text{Total Bankroll}$。
2. **僵尸仓位双轨估值（ADR-0012）**：
   - 超过预计结算时点 12h 未结算者移入 `Zombie Margin`；
   - **风控轨**：按物理模型后验概率标记价值（Mark-to-Model），保守监控资产净值；
   - **会计轨**：按盘口可变现清算价计价（Mark-to-Market）；
   - 全流程资金出入与下注扣减必须采用 Python `Decimal` 进行截断舍入闭环，杜绝微小尾差放大。
3. **多项分布联合对数财富最大化（增量凯利）**：
   $$\max_{\mathbf{f}} G_{incr}(\mathbf{f}) = \sum_{i=1}^k p_i^{new} \ln\left(W_{free} + N_i + \frac{f_i}{q_i} - \sum_{j=1}^k f_j\right)$$
   - 旧持仓 $N_i$ 作为外生确定项注入，只买不卖，零摩擦自然向前对冲；
   - SLSQP 优化器初值设为 $10^{-4}$，若未收敛或异常，安全回退为零向量。

### §5 执行引擎、IOC 深度防御与两维风控 (Task 06, Task 07 - ADR-0011)

1. **IOC 保护价限价单**：
   - 严禁下发市价单。遍历订单簿至单份 EV $< 0$ 处的前一档价格记为 $P_{protect}$；
   - 发送 IOC 限价单，价格锁定 $P_{protect}$，杜绝深度击穿。
2. **残局状态机（Residual Risk）**：
   - 非原子成交导致单腿裸露时：重算残局 EV $\to$ 能补单对冲则限价补单 $\to$ 无法对冲且风险超标时触发保守止损平仓。
3. **两维阶梯风控矩阵（ADR-0011）**：
   - 距离关盘时间 $T_{remain}$ 与残差温度 $\Delta T = |T_{target} - T_{now}|$ 构成两维阶梯：
     - 临界区（$T_{remain} < 1\text{h}$ 且 $\Delta T > 3^\circ\text{F}$）：强制仓位额度打折至 0.2 或停止加仓；
     - 确定区（$\Delta T \le 0.5^\circ\text{F}$ 且 $T_{remain} < 0.5\text{h}$）：锁定既有胜利果实，禁开异向投机单。
4. **模型健康四维评级与纸面盘仓位缩放规则（[v2.2] B4，从 `ROADMAP.md` 迁入；`[2026-11-14 勘误，不升版]`）**：
   - 正式收编 [`docs/MODEL_SCORECARD.md#L13-L16`](../MODEL_SCORECARD.md#L13-L16) 官方四维模型体检标准与阈值：
     1. **Weighted ECE**（权重最高）：绿 `<= 0.0100` / 黄 `(0.0100, 0.0200]` / 红 `> 0.0200`；
     2. **Abs(Residual Bias)**：绿 `<= 0.50°F` / 黄 `(0.50, 1.00]°F` / 红 `> 1.00°F`；
     3. **CRPSS**：绿 `>= 0.150` / 黄 `[0.050, 0.150)` / 红 `< 0.050`；
     4. **Empirical Cov90**：绿 `[85.0%, 95.0%]` / 黄 `[80.0%, 85.0%) ∪ (95.0%, 97.0%]` / 红 `< 80.0%` 或 `> 97.0%`。
   - **`[2026-11-14 W2 口径勘误注记｜业主裁决]`**：原 v2.2 初稿（`2026-11-13` 提交 `a603910` 迁入时）第 2–4 维曾误写为 `Bias <= 0.15°F / CRPSS >= 0.50 / Cov90 [88%, 92%]`；经 `git log -S` 核证全仓无第二出处，呈维度间数字对调指纹（`0.15` 与 `0.50` 在 Bias/CRPSS 两列互换；`[88%, 92%]` 贴合体检实测读数而非法定期望定义），且与上一行 `L195` 自引 [`docs/MODEL_SCORECARD.md`](../MODEL_SCORECARD.md) 直接矛盾，判定为转写错误而非经程序之法定收紧（见 [`P8-DESIGN-TEAM-REVIEW §v2.四`](../audit/P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md)）。依 `2026-11-14` 业主裁决以勘误方式回改对齐 `MODEL_SCORECARD.md#L13-L16`，不升版。
   - **纸面盘仓位缩放执行规则**：依模型综合评级对下单头寸实施乘性缩放——**绿级 `1.0x` 全额**、**黄级 `0.5x` 审慎收缩**（如 `KMIA 12h` 带旗减半）、**红级 `0.0x` 禁开新仓**；同时挂接日内 SPECI 动态截断层与结构化日志落盘 `data/paper_trading/records/`；
   - **第五维（形状距离）状态注记**：非高斯形状距离定量校准维度及红/黄/绿阈限**当前处于方法评审中（详见技术评审第二部分）**，不写入本版正式风控评级条款。

---

## 四、 验收测试套件 (CI/CD 门禁与纸面盘)

1. **Test-Scenario A（多项凯利与沉没成本增量断言）**：
   - 构造 4 档位市场，模拟冷空气概率突变，断言增量资金精准分配，旧持仓外生隔离无放大。
2. **Test-Scenario B（订单簿深度击穿与 IOC 防御断言）**：
   - Mock 深度不足薄盘口，断言仅成交安全档位，剩余订单 IOC 自动撤单，成交均价 EV $> 0$。
3. **Test-Scenario C（僵尸仓位双轨估值与 Decimal 精度断言）**：
   - 注入超期未结算仓位，断言从 Active Locked 剔除，下注运算全流程 Decimal 零精度撕裂。
4. **Test-Scenario D（单调合流与特报门禁断言 - ADR-0011/0013）**：
   - D1: 迟到 METAR 原报丢弃负断言；
   - D2: 正文与 RMK 气温冲突单调纠偏正断言；
   - D3: 异常跳温 $20^\circ\text{F}$ 触发安全阻断断言。
5. **Test-Scenario E（统一异常中枢 Fail-Closed 断言 - ADR-0014）**：
   - 模拟心跳丢失超 30s，断言 0ms 触发撤销全站挂单并禁开新仓；已成交仓位保持绝缘。
6. **Paper Trading 仿真门禁（Task 07 只读纸面盘）**：
   - 接入真实 WSS 盘口与实况流运行 48 小时；
   - 零非物理下单、无滑点穿仓、无未捕获异常、模拟资金夏普比率 $> 2.0$。
   - **[v2.2 追加｜B5] 方案 `α` 上线后监控口径**：`α` 架构上线后，纸面及实盘运行期间持续按 **`站 × 季 × 早晚段`** 分桶统计结算偏差（口径与检验 C 完全兼容）。
7. **检验 C 离线 `bridge-ECE` 只读差值诊断与判决状态（[v2.2] B6；`[2026-11-14 状态与工件指针登记，不升版]`）**：
   - **检验 C 当前状态**：**`终跑裁决落地 = TIER_C（C 档：终止可签，2026-11-14）`**（基于 LST 语料可识别性修复与正则重标定工件；2019 分支 A 主判实测 `G1=True` (`CRPS -48.33%`, `16/16` 层改善) & `G2=True` (`G2a 608d/2019 max 1.15/1.36°F ≤ 2.0°F`, `G2b -32.7%`)，但 `G3=False` (`aft out95=36/312`, `early B12 out95=38/228`, `pooled ECE_bridge(inw)=0.030586 > 0.020`) 且 `concentration_cond=False`，见 [`evidence/p8_inspection_c_2019_final_lst_20261114.json`](../../evidence/p8_inspection_c_2019_final_lst_20261114.json) 与 `G-15` 结算适配器工项登记）。
   - **`[2026-11-16 版本标注：已对齐 内核讨论定稿 v1.0]`**：上述 `-48.33%` 属相对检验 C 气候学先验之实验对照读数，**禁止在后续改版收益预期中引用**；生产真实形态与后续冻结运行四元组日志评估（替代前置历史测绘、`G-15` 核查升为阶段 0 `T1` 最优先阻塞项、`F-2 LOCKED` 不动）详见 [`P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md`](../audit/P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md)。
   - **现役 $\mu_R$ 标定工件指针（单一事实来源）**：**`现役 μ_R 标定工件 = evidence/p8_mu_r_lst_identifiable_calibration_20261114.json（LST 608d 连续CRPS+塔锚正则版）`**。
   - **本轮检验 C 2019 回放三项重点观察项**：① `KORD` 春秋午后过渡窗（Round-2 残留 `6/312` 格所属族）；② `KMIA Winter early`（原生 `ECE_族 = 0.0125`，全表绝对校准最差格）；③ `KMIA_12h` 交易窗原 `ECE = 0.0183` 挂旗读数在 `v2`（2000–2018 折外 `s_oos`）契约下的重读值。
   - **三数同源并产**：检验 C（2019 独立盲测年全年回放）必须在**同一份 2019 盲测数据、同一条回放管道、同一次运行**中同时产出以下三项校准读数：
     1. **桥前原生 ECE（`ECE_native`）**；
     2. **桥后条件 ECE（`ECE_bridge`）**；
     3. **高斯对照 ECE（`ECE_gauss`）**。
   - **现实侧唯一基准**：2019 实际落档观测频率在同一次运行中共用同一份，仅在预测分布侧对比上述三类分布输出；
   - **只读差值边界**：桥后读数以差值 $\Delta_{\text{bridge}} = \text{ECE}_{\text{bridge}} - \text{ECE}_{\text{native}}$（及相对 `ECE_gauss` 差值）形式只读呈现，**严禁将 `ECE_bridge` 与 `0.0100` 法定线比对，不设放行/阻断门禁，不阻塞工程交付或上线，不进入任何在线定价/风控参数**；
   - **设计原则声明**：桥对分布的任何数学效应须于设计时推导并量化，自带补偿机制（中心偏移 $\to$ 完整分位、尾形 $\to$ 评级缩放）；不可推导的未知偏差视为设计缺陷，由检验 C（2019 回放，物理观测为唯一有效尺子）证伪。
   - **现役三条桥前原生 ECE 代码链路在案坐标**：
     1. 20 折 Block-CV / P5 门禁链路：[`scripts/standalone_reliability_check.py#L730-L885`](../../scripts/standalone_reliability_check.py#L730-L885)、[`src/verification/p5_gate.py#L202-L246`](../../src/verification/p5_gate.py#L202-L246)、[`scripts/audit_p4_reliability_v13.py#L140-L312`](../../scripts/audit_p4_reliability_v13.py#L140-L312)；
     2. 2019 P4 结算 7 档 V1 / Active 10 OOS 链路：[`scripts/evaluate_p4_2019_settlement.py#L297-L337`](../../scripts/evaluate_p4_2019_settlement.py#L297-L337)、[`scripts/evaluate_active10_oos.py#L244-L249`](../../scripts/evaluate_active10_oos.py#L244-L249)；
     3. V2 尺子 2°F 11 档直接 ECE 链路：[`scripts/audit_v2/reliability_v2.py#L130-L264`](../../scripts/audit_v2/reliability_v2.py#L130-L264)。

---

## 五、 版本修订与签署留痕

| 修订版本 | 修订内容 | 签署日期 | 状态 |
|---|---|---|---|
| **v1.3** | 提出双源解耦初步草案与切换窗阈值 | 2026-09-04 | SUPERSEDED |
| **v2.0** | 吸收 ADR-0011~0014 全部裁决，确立单调合流与统一中枢，补齐 Task 01 生产级重训门禁 | 2026-09-20 | SUPERSEDED |
| **v2.1** | **[P7-DOC-RECON 勘误与演化对账]** 对账 Task 01 模型数量口径（960 生产模型库）；统一训练与评估窗口为 2000–2018（19 日历年 / 6,940 天，2019 为独立盲测年）；明示 Task 01 原三重验收由 P5/P6 审计体系（20 折 Block-CV + 两段式 BIC 竞争选型 + 气象 ECE $\le 5.0\%$；交易窗口 ECE $\le 0.0100$ 为交易侧解耦口径）继承替代；标注三波次路线图（W1 $\to$ W2 $\to$ W3）与只读纸面盘降级范围 | 2026-10-10 | SUPERSEDED |
| **v2.2** | **[P8-ALGO-AUDIT 裁决合流 / G-9 闭环升版]** ① 新增方案 `α` 五元组分布契约、`manifest.json` 实况（880 None / 127 {} / 193 非空 dict）、$\mu_0$（$a+b\cdot\mu_{\text{ens}}+b_{30}$）组装说明与 2019 分位形状距离支撑（`dq99 +5.8458°F` / `dq01 -3.3565°F`）；② 按 `SPEC v2.0#L186, L206` 明确方差修正前移 $\sigma_0 = c\cdot\sigma_{\text{eff}}$ 合成 $0.9^\circ\text{F}$ 仪表底并禁 $c$ 外乘；③ 如实登记完整非对称分位/CDF 支持「现役未满足」（`ev_engine.py` 已归档，`penetration_probe.py` 仅收标量 `p_hat`）；④ 按 `MODEL_SCORECARD.md#L11-L16` 正式收编四维评级与纸面盘 `1.0x / 0.5x / 0.0x` 缩放规则（从 `ROADMAP.md` 迁入），注记第五维方法评审中；⑤ 追加 `α` 上线后按 `站×季×早晚段` 监控结算偏差与检验 C 离线 `bridge-ECE` 三数同源并产只读差值诊断条款 | 2026-11-13 | **APPROVED** |
