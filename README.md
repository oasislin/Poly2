# Polymarket 温度预测与量化套利系统

> [!NOTE]
> **[2026-11-28 已对齐 [`项目方案 (v3.0) §8`](docs/项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#8-模块地图与协议层总索引v30-后-α-十模块静态结构与-p1p19-契约--2026-11-18-当前决策) 与 [`P8-PROJECT-TASKS v3.14`](docs/audit/P8-PROJECT-TASKS_全量任务分解台账.md)（`DONE = 27/33`）]**：
> - **当前实盘前产线态势（`PAPER` 连续仿真运行中）**：全系统依常设指令 `P8-WO-20261123-STANDING-DIRECTIVE-NOREAL-ORDER` 维持 **`PAPER` 假盘模式**（[`configs/clob_gateway.yaml`](configs/clob_gateway.yaml)，实钱轨道暂停至“统一开通”）。6 站主力盘口被动录盘、`live_p5` 实时预报、`S3-11` 连续假盘决策与延迟撮合（`M4→M5 P18 v1.1→M6 P14→M7→M9 P9/P15`）及本地只读 `M10` 实时看板（`127.0.0.1:8765`）持续运行；`2026-11-27/28` 完成四批演进（存储节流与 `.jsonl.gz` 原子归档、`M6` 重启审计历史恢复、`P18 v1.1` 静息盘口回退与 `τ` 分级事件调度、`P2 v1.2` `plan_slice` 陡峭尾档预冻结感知修复）。`F-2 LOCKED`（[`src/pricing/`](src/pricing/)）保持严格冻结不动。
> - **历史基线记录（保留不改）**：`2026-11-17` 收敛内核 `v1.1`（`T5` 取消、`$10,000 / $500 站限 / k₀=2`、`w=B2 + φ=Edge 感知 POV`）及 `[P7-DOC-RECON]` 主干基线 `5c4a4c9`（PR #132 W1 合流，`1006 passed, 10 skipped, 0 failed`）。

> 📌 **核心文档与导航入口**：  
> • **唯一实时任务台账（`v3.14`）**：[`P8-PROJECT-TASKS_全量任务分解台账.md`](docs/audit/P8-PROJECT-TASKS_全量任务分解台账.md) ｜ **离线可视化看板**：[`progress_board.html`](docs/audit/progress_board.html)  
> • **业务方案与十模块协议索引（`v3.0`）**：[`项目方案 (v3.0)`](docs/项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md#8-模块地图与协议层总索引v30-后-α-十模块静态结构与-p1p19-契约--2026-11-18-当前决策) ｜ **决策与执行接口（`v1.2`）**：[`P8-T4-M4M5-INTERFACE_决策与执行接口规格.md`](docs/audit/P8-T4-M4M5-INTERFACE_决策与执行接口规格.md)  
> • **算法四单设计（`v0.3`）**：[`P8-T8-ALGO4-DESIGN`](docs/audit/P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md) ｜ **制度合龙规范（`D-6`）**：[`P8-D6-POLICY-CLOSURE v1.0`](docs/audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) ｜ **监控页设计（`M10`）**：[`P8-M10-DESIGN`](docs/audit/P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md)  
> • **资金配置与参数账本（`v1.1`）**：[`P8-CAPITAL-CONFIG`](docs/audit/P8-CAPITAL-CONFIG_资金参数配置_v1.0.md) ｜ **执行设计 `w/φ`**：[`P8-EXECUTION-DESIGN v1.0`](docs/audit/P8-EXECUTION-DESIGN_w与phi设计与决策记录_v1.0.md) ｜ **静态事实档案**：[`P8-FACTS-LEDGER`](docs/audit/P8-FACTS-LEDGER_静态事实档案_v0.1.md)  
> • **项目历史状态与路线图**：[`STATUS.md`](STATUS.md) ｜ [`docs/ROADMAP.md`](docs/ROADMAP.md) ｜ [`P8-GLOBAL-MAP`](docs/audit/P8-GLOBAL-MAP_项目全局图谱_v1.0_20261113.md) ｜ [`docs/SEALING_GATE.md`](docs/SEALING_GATE.md)

> 🚩 **【法定运行旗状态（对齐 main 现实）】**：  
> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（加权 ECE = `0.018318` 越线 0.0100；经 MODEL_SCORECARD 与裁决令判为红级禁投 0.0x）；  
> 2. `6h 池化回退层 (80 格)`：状态 **`UNFLAGGED` (已正式拔除)**（依据裁决令 `P7-FLAG2-REMOVAL-R1` / 工单 `P7-W1-POOLPHASE`，晨谷 ECE = `0.005977` 击穿 0.0100，四季膨胀比 1.0000 自洽，随 PR #132 合流入主干拔旗）。  
> *下游引用约束*：交易盘口映射、分位数定价与风控链路在调用本格资产时，**必须显式带旗陈述，审慎收缩头寸，严禁脱旗裸跑**！

---

## 内核讨论定稿 v1.0 核心原则摘要（2026-11-16）

> 完整条文、防污染约束与待拍板分叉见 [`P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md`](docs/audit/P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md)。

1. **赚钱逻辑与市场定位（`D-1 / D-2 / D-5`）**：
   - **目标式**：$\text{edge} = \text{我们的校准分布} - \text{市场隐含概率} - \text{摩擦（价差} + \text{冲击} + \text{安全垫）}$；参照系为市场价格而非绝对真值，**盈利性尚未实测（三项假设全部待真实盘口数据检验）**；
   - **市场微观结构**：天气盘深度低、散户为主（`> 70%`，出处待入档），做市商属收费通道而非对手；仓位上限自改版首日起按**盘口深度倒推**，以持有至结算为主，采用**概率驱动退出**（不设主观价格阈值）与**多次、少金额、中频扫描**。
2. **生产真实形态与基准澄清（`D-3`）**：
   - 系统真实生产形态为：**`GFS` 翻译层（全程） + 桥收敛层（临近激活） + `G-15` 结算口径适配**；由 $\max$ 恒等式驱动，日内条件分布天然呈现 **“点质量（不创新高原子 `p_stay`）+ 条件超越”** 形态；
   - **澄清入档**：生产线自始至终消费 `GFS` 预报；检验 C 中的气候学先验仅属离线实验隔离对照，**严禁在任何改版收益预期中引用该对照下的 `−48.3%`**。
3. **生产即测绘、防污染与路线切换（`D-4` + 废止清单）**：
   - **废止前置历史回填与测绘协议**：正式废止多年度“合流测绘协议（梯 0/1/2）”与 `GFS 2020–2024` 历史存档回填；`GHCN backfill` 降级挂账；原 `β/γ` 选型考场收缩为改版前形态冒烟（分叉 1）；市场侧快照自改版第一天起被动记录；
   - **生产即测绘 + 防污染三条款**：桥随改版直接上线并在冻结周期内采集**四元组日志**（决策上下文 / 模型侧 / 市场侧 / 结算侧），以每个冻结周期沉淀日志作下一轮独立盲池；运行期严格执行 **记录只读 / 模型冻结（带版本号） / 单向收紧**（`F-2 LOCKED` 不动）。
4. **当前推进队形（阶段 0 并行可开工 + 待定项）**：
   - **阶段 0（零成本并行）**：**`T1` `G-15` 结算口径逐字核查（Polymarket FAQ vs ADR，最优先且阻塞代码实现）**、`T2` 四元组决策快照 schema、`T3` 市场侧被动记录管道设计、`T4` 改版设计文档；
   - **待定议程**：`D-6` 制度合龙下一桌产出（`抽检定义 + 亮灯规则 + 灯到钱映射表`）及 **三个分叉**（形态确认 / 冻结周期 / 首检最小内容）待拍板后转入阶段 1–3（`T5 → T12`）。

---

## 核心系统架构 (Phase 7 生产全景)

本项目旨在构建一个高精度的物理概率模型与自动化量化套利系统，用于预测 Polymarket 气温市场的日最高（TMax）与最低（TMin）气温概率分布，并将气象预测的客观物理优势转化为正期望值（+EV）套利回报。

系统采用“全球再预报特征提取 $\to$ 960 生产模型库 $\to$ 实时单调合流与特报截断 $\to$ 物理机理硬拦截 $\to$ Polymarket 2°F 阶梯离散盘口映射 $\to$ 订单簿微观结构对账与正期望值执行”的全链路量化架构：

```
┌─────────────────────────────────────────────────────────────┐
│             交易与执行微观结构层 (Phase 2 / W2 短闭环)       │
│  订单簿快照撮合、2°F 离散区间积分映射、动态 EV 引擎、只读纸面盘 │
└─────────────────────────────────────────────────────────────┘
                               ▲
┌─────────────────────────────────────────────────────────────┐
│                    物理硬约束层 (ConstraintEnforcer)         │
│  基于站点历史极端升降温速率与极值窗口的物理边界硬拦截 (p=0.0) │
└─────────────────────────────────────────────────────────────┘
                               ▲
┌─────────────────────────────────────────────────────────────┐
│                    动态截断修正层 (DynamicCorrector)         │
│  实时观测流单调合流与条件概率截断: P(X ≥ L | X > T_now)      │
│  SPECI 特报纯温门禁、迟到不投丢弃与异常跳温物理阻断          │
└─────────────────────────────────────────────────────────────┘
                               ▲
┌─────────────────────────────────────────────────────────────┐
│               静态生产模型库 (960 个生产模型已落盘)           │
│  • 预注册封闭三族池: Gaussian / Johnson SU / EVT-Hybrid     │
│  • 方差结构: EMOS 平方参数化 σ² = c² + d² * S_ens² (含下限托底)│
│  • 机械选型: 20 折 Block-CV 独立选型 + 两段式 BIC 竞争机制   │
│  • 资产矩阵: 10 站 × 2 标的 (Max/Min) × 4 季 × 12 提前期     │
└─────────────────────────────────────────────────────────────┘
                               ▲
┌─────────────────────────────────────────────────────────────┐
│                    数据工程与特征存储基石                    │
│  • 观测真值: GHCN-Daily (10 站历史 78.55~96.72 年无断崖)     │
│  • 结算源: NWS WRH 官方时序表 (Time Series Tabular, 即 CF6)│
│  • 预报源: NOAA GEFSv12 全球再预报 (2000-2019, 7305 日冷归档)│
│  • 训练评估: 2000–2018 训练 (6940 日), 2019 独立盲测 Airgap │
└─────────────────────────────────────────────────────────────┘
```

---

### 站点宇宙体系 (Active 10 法定主力交易池)

根据《ADR-0007》及《项目方案 (v2.7)》，系统已彻底废除旧版 Wunderground 与无常态日盘的观察站（KDCA 已正式注销退役，KBKF 因微气候警示排除在 Active 10 校准矩阵之外），全面聚焦于全美 10 个核心活跃交易站点：

| 站代码 | 台站名称 | 气候特征与代表原型 | 观测历史深度 | 当前审计状态 |
| :---: | :--- | :--- | :---: | :---: |
| **KORD** | 芝加哥奥黑尔 (Chicago O'Hare) | 内陆温带正午加热型（高斯主导 + 正午峰度 JSU） | 78.55 年 | `COMPLETED_SEALED` (基线 987) |
| **KMIA** | 迈阿密国际 (Miami Intl) | 副热带沿海对流负偏型（厚尾 JSU 主导 + 午后对流 EVT） | 78.72 年 | `COMPLETED_SEALED_FLAGGED` (双旗在役) |
| **KLGA** | 纽约拉瓜迪亚 (LaGuardia) | 沿海温带复合型 | 85.23 年 | 96 格模型已落盘，待 P7 原型归类 |
| **KATL** | 亚特兰大哈兹菲尔德 (Atlanta) | 亚热带湿润大陆型 | 94.61 年 | 96 格模型已落盘，待 P7 原型归类 |
| **KDAL** | 达拉斯爱田 (Dallas Love Field) | 南方内陆强变温型 | 84.42 年 | 96 格模型已落盘，待 P7 原型归类 |
| **KHOU** | 休斯敦霍比 (Houston Hobby) | 墨西哥湾沿海湿热型 | 92.15 年 | 96 格模型已落盘，待 P7 原型归类 |
| **KLAX** | 洛杉矶国际 (Los Angeles Intl) | 地中海沿岸海风逆温型 | 81.33 年 | 96 格模型已落盘，待 P7 原型归类 |
| **KSEA** | 西雅图塔科马 (Seattle-Tacoma) | 西岸海洋性多云雨型 | 78.56 年 | 96 格模型已落盘，待 P7 原型归类 |
| **KSFO** | 旧金山国际 (San Francisco) | 太平洋强海雾逆温型 | 79.25 年 | 96 格模型已落盘，待 P7 原型归类 |
| **KAUS** | 奥斯汀伯格斯特龙 (Austin-Bergstrom) | 德州过渡型活跃日盘 | 96.72 年 | 96 格模型已落盘，待 P7 原型归类 |

> **【Active 10 法定真值基准】**：  
> `KATL, KAUS, KDAL, KHOU, KLAX, KLGA, KMIA, KORD, KSEA, KSFO`（共 10 站，真值定义以代码 `src/data_processing/constants.py:395-406` 及配置文件 `configs/climate_floor_v2.json` 为准）。

---

## 项目阶段与执行状态

| 阶段 / 模块 | 核心工作流与当前状态 | 完成度 | 核心交付物与状态索引 |
| :--- | :--- | :---: | :--- |
| **Phase 1 基线封存** | **Git Tag `phase1-final` (Commit 53b1024)**<br>• 18 份 M0' 审计产物移入 `docs/frozen/phase1/`（只读）<br>• Wunderground 等旧数据物理隔离至 `data/legacy-v1-suspect/` | **100%** | 封存清单、只读声明头与隔离区 |
| **Phase 1.5: 数据重建** | **生产级校准语料库 `calib-dataset-v2.0` (Tag: `phase1.5-final`)**<br>• 外部冷存储 292,200 个 GRIB2 全球场补全与去重<br>• 10 站统一特征长表与 2000–2018 严格 OOS 气候方差底重建 | **100%** | `calib-dataset-v2.0/`<br>`gefs_factors/` (Parquet 特征库) |
| **Phase 5: 审计工具重构** | **Layer 2 门禁立法与测试基线大筑底**<br>• 可靠度工具重构（S1~S5 盲测、20 桶分桶合并算法防凑答案审计）<br>• 全库 987 项测试基线（10 skipped, 0 failed）建立 | **100%** | `standalone_reliability_check.py`<br>测试基线 987 项全绿 |
| **Phase 6: 双城封盘** | **双城 TMax 24 时间格 (96 季节格) 全网格 Block-CV 审计与封盘**<br>• KORD (11/12 Gaussian + 1 JSU) 封卷于 `COMPLETED_SEALED`<br>• KMIA (10/12 JSU + 1 EVT + 1 Split) 封卷于 `COMPLETED_SEALED_FLAGGED`<br>• 合流入主干基线 `6fe386c`（PR #129） | **100% 封卷** | `evidence/p6_tmax_methodology_closure.md`<br>双城 96 季节格审计汇总表 |
| **Phase 7: 过渡态 (历史锚点)** | **长线路线图入册与三波次战略推进 (PR #130 合流至 `2975ec1`)**<br>• **W1**: `P6-POOL-PHASE` 已封卷合流（`5c4a4c9`），运行旗 2 已拔除<br>• **W2 / Task 08**: `F-2 LOCKED` 定价内核（`sigma_adj.py` / `penetration_probe.py`）已封盘 | **W1 封卷 / F-2 锁定** | [`STATUS.md`](STATUS.md)<br>[`docs/ROADMAP.md`](docs/ROADMAP.md)<br>[`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md) |
| **Phase 8: 后 α 十模块建设与连续假盘 (`2026-11-28` 当前)** | **十模块 `M1–M10` 与 `P1–P19` 协议体系落地（`DONE = 27/33`）**<br>• 切片 1 全闭合；切片 2 `S2-01`（6 站双侧录盘）、`S2-02`（`friction_median=0.071645`）、`S2-03 D-6`、`S2-04 P10`、`S2-05` 看板、`S2-06 G-5`、`S2-07` 告警全闭合<br>• 切片 3 完成 `S3-01..S3-10 / S3-13 / S3-14 / S3-17`；`PAPER` 6 站实时预报、连续决策撮合、审计恢复与只读 `M10` 监控服务持续运行中 | **27/33 已闭合** | [`P8-PROJECT-TASKS`](docs/audit/P8-PROJECT-TASKS_全量任务分解台账.md)<br>[`progress_board.html`](docs/audit/progress_board.html)<br>[`P8-D6-POLICY-CLOSURE`](docs/audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md) |
| **交易与执行引擎 (`M4–M7/M9/M10`)** | `DeterministicDecider`、`plan_slice (P2 v1.2)`、`ReplayMatcher (P18 v1.1)`、`BankrollManager (P14/P15)` 与 `M9SettlementEngine` 全量上线于 `PAPER` 轨；`S3-05b` CLOB 网关已交付，`S3-15` 真钱试单依业主常设指令暂停至“统一开通” | **`PAPER` 连续仿真运行中** | [`P8-T4-M4M5-INTERFACE`](docs/audit/P8-T4-M4M5-INTERFACE_决策与执行接口规格.md)<br>[`P8-M10-DESIGN`](docs/audit/P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md) |

---

## 核心技术规格与设计决策

1. **真实观测与法定结算真值协议**：
   - **IEM ASOS RMK T 组真值**：彻底废弃旧版 Wunderground，采用 ASOS 报文尾部 `T` 组编码（精确至 $0.1^\circ\text{C}$ / $0.18^\circ\text{F}$），杜绝整度截断误差；
   - **法定结算源（ADR-0012）**：Polymarket 官方 100% 结算于 **NWS WRH 官方时序表**；
   - **单调合流架构（ADR-0011 / 0013）**：IEM METAR 与 NWS 观测流在日内单调非递减（TMax）/单调非递增（TMin）合流；特报 SPECI 实施“纯温门禁、迟到不投、跳温阻断”。

2. **气象预报因子与训练窗口对账（D5 裁决）**：
   - **GEFS 全球场冷归档**：外部存储完整保留 7,305 天（2000–2019）原始 GRIB2 数据，禁止删除；
   - **法定训练窗口**：统一确立为 **2000–2018（19 个日历年，共 6,940 天）**，**2019 日历年作为严格物理 Airgap 隔离的独立样本外检测年**（代码级 `verify_year_whitelist` 守卫）；
   - **验证样本量澄清**：全网格交叉验证中的 `13,740 / 13,739` 指标实质为 20 折 Block-CV 验证块的**折·日总和（Total Fold-Days）**（对应 5,860 唯一独立日历日），绝非日历覆盖年数，不与口径 A（台站历史观测史 $\ge 30$ 年）冲突。

3. **数学模型与方差结构（P6 BIC 裁决）**：
   - **平方参数化方差**：$\sigma^2 = c^2 + d^2 S_{ens}^2$（废除历史气候方差加法项 $\sigma^2_{clim}(d)$，防止违反校准不等式 $\mathbb{E}[\sigma_{forecast}^2] \le \text{Var}(T)$；$c$ 设物理下限托底防过度自信）；
   - **预注册三族分布池**：Gaussian / Johnson SU / EVT-Hybrid（条件高斯截断），由 20 折 Block-CV 两段式 BIC 竞争机制驱动机械自动选型；
   - **短时效方差衰减**：$<24\text{h}$ 模型满足 $\sigma_L = \sigma_{24\text{h}} \cdot \sqrt{\max(0, L)/24.0}$ 物理衰减机制（W1 专项补全）。

4. **验证与审计体系（继承替代条款）**：
   - 原“三重验收标准”已由 **P5/P6 生产审计体系全面继承替代**；
   - **法定硬门禁**：交易窗口加权 **$\text{ECE} \le 0.0100$**（20 桶 $\times$ 5% 等宽分桶，样本数 $n < 30$ 且 $\bar{p}$ 最接近的相邻非空桶合并；该值为交易侧内部治理口径，最终生产交易门尚待标定，非气象层强制拦截）；
   - **全库测试基线**：全量 **1006 项测试全绿** 护航（10 skipped, 0 failed），代码交付零回归。
   - **2019 独立盲测评估尺子 V1.0 → V2.0 演进（换尺子、不重训）**：
     - *V1.0 盲测尺*（2019 双城 KORD/KMIA × 11 lead = 22 格首次结算）：套用五道固定工程带——KS p≥0.05、7 档 ±3°F 自定窗 ECE、$s_{\text{oos}}$ 固定对称带 [0.85, 1.15]、PIT 均值∈[0.46,0.54]、90% 覆盖∈[0.83,0.95]；22 格仅 7 格全过，含 CV 平均带套单年、对称带不符 F 偏态、KS 功效弱、自定窗漏检尾部等口径缺陷。
     - *V2.0 盲测尺*（工单 P4-BLIND-AUDIT-V2R01，终审四项通过、闭环）：① $s_{\text{oos}}$ 由残差 lag-1 自相关 $\rho_1$ 算 $N_{\text{eff}}$，出 Finf / Fstd 两套动态非对称 95% 带并列（不设单一法定）；② 均匀性改 KS + CvM 方案乙（仅两者 p<0.05 同时显著才否决）；③ ECE 改 11 档市场梯子（左 catch-all + 9 个 2°F 档 + 右 catch-all）档级直接可靠性 ECE，并并列 10/20 概率等宽桶敏感性；④ 补 PIT 方差（理论 1/12）与 10 档直方图形态。终审实测：finf_in 11/22、fstd_in 19/22、reject_uniform 0/22、四口径 ECE 全 <5%、PIT 方差贴 1/12。
     - *边界*：V2.0 是 2019 单年盲测的**事后体检尺**，与 P5/P6 生产 20 折 Block-CV 审计体系解耦，不改 EMOS 参数、不重训、不写回模型；ECE 法定门与 PIT 通用带边界留待标定。详见 `docs/audit/第二类_V2尺子升级_方案书_20261021.md` 与 `docs/audit/P4-BLIND-AUDIT-V2R01_V2尺子升级_开发任务单_20261021.md`。

---

## 目录结构

```
Poly Way2/
├── configs/                     # 系统配置文件 (default.yaml, dev.yaml, test.yaml)
├── data/
│   ├── processed/calib-dataset-v2.0/  # 生产级统一校准数据集 (Parquet 因子库)
│   ├── models/                  # 960 个生产模型资产 (.pkl)
│   └── legacy-v1-suspect/       # 历史作废脏数据物理隔离区
├── src/
│   ├── data_acquisition/        # M1/M3 数据采集层 (GEFS/AWC METAR 与 P13 被动盘口录盘)
│   ├── data_processing/         # 数据工程与存储层 (常量、转换、物理递减率、时序对齐)
│   ├── modeling/                # 概率建模层 (EMOS、JSU、EVT、CRPS、BIC 选型、插值器)
│   ├── prediction/              # M2 预测引擎 (静态预测、动态截断、2°F 映射与 live_p5 生产)
│   ├── pricing/                 # 定价内核 [F-2 LOCKED] (edge_math.py, sigma_adj.py 等)
│   ├── decision/                # M4 决策引擎与连续假盘调度器 (engine.py, offline_scheduler.py)
│   ├── execution/               # M5 执行器 (P2 v1.2 plan_slice, P18 v1.1 ReplayMatcher, CLOB 网关)
│   ├── bankroll/                # M6 资金风控 (P7/P14/P15, 重启审计历史恢复 recovery.py)
│   ├── audit/                   # M7 审计日志与只读巡检 (p10_reader .jsonl.gz, readonly_watchdog.py)
│   ├── calibration/             # M8 校准账本与 ECE 评估 (policy_ledger, p13_book_walk, ece_evaluator)
│   ├── settlement/              # M9 官方结算对账 (AWC/WU 回退, DST 日界与 P15 释放)
│   ├── ui/                      # M10 纯只读监控视图、5 项一致性核验与增量缓存
│   ├── validation/              # 审计与验证层 (ECE、PIT、Block-CV、可靠度检验工具)
│   ├── pipeline/                # 统一流水线与健康中枢
│   └── utils/                   # 结构化日志、Decimal 守卫与通用工具
├── scripts/                     # 命令行工具、产线守护与运维脚本
│   ├── run_poly_pipeline.py     # 历史模型流水线统一 CLI 入口
│   ├── run_passive_book_recorder_daily.py # M3 每日 00:05Z 轮转被动录盘守护
│   ├── run_live_p5_producer.py  # M1/M2 在线 P5 概率分布定时生产
│   ├── run_s311_offline_scheduler.py # S3-11 连续假盘决策/撮合/结算主链
│   ├── serve_m10_live.py        # M10 本地回环只读实时监控服务 (127.0.0.1:8765)
│   ├── archive_audit_logs.py    # 历史审计日志原子 .jsonl.gz 压缩归档 (SHA-256 校验)
│   ├── render_progress_board.py # 唯一任务台账解析与离线 progress_board.html 生成校验
│   └── standalone_reliability_check.py # 可靠度独立检验工具
├── tests/                       # 测试套件 (unit / integration / e2e)
│   ├── unit/                    # 单元测试 (数据获取、处理、建模、预测)
│   ├── integration/             # 模块间集成测试
│   └── e2e/                     # 系统级全链路 E2E 验收测试
├── docs/                        # 项目法定文档体系
│   ├── ROADMAP.md               # 项目长线三波次路线图 (法定纲领)
│   ├── HANDOVER_P7.md           # 新会话冷启动唯一交接引导清单
│   ├── SEALING_GATE.md          # 双城封盘九项门禁检查表
│   ├── SYNC_POLICY.md           # 受控出域同步政策
│   ├── adr/                     # 架构决策记录 (ADR-0001 ~ ADR-0014)
│   └── 项目方案和执行文档/        # 顶层业务方案与阶段执行文件
└── evidence/                    # 生产审计工件与封盘报告
```

---

## 快速上手与 CLI 命令

统一 CLI 入口为 [`scripts/run_poly_pipeline.py`](scripts/run_poly_pipeline.py)：

### 1. 系统健康自检
检查 SQLite 数据库、Parquet 特征库及生产模型就绪状态：
```bash
python scripts/run_poly_pipeline.py health --config configs/default.yaml
```

### 2. 端到端流水线调用
```bash
# 开发环境运行
python scripts/run_poly_pipeline.py all --env dev

# 从训练阶段断点恢复运行后续所有阶段
python scripts/run_poly_pipeline.py all --resume-from train
```

### 3. 单阶段与单站盘口预测
```bash
# 单站单日盘口概率预测 (芝加哥奥黑尔最高温)
python scripts/run_poly_pipeline.py predict --station KORD --date 2026-10-10 --target-type max

# 运行独立可靠度审计工具
python scripts/standalone_reliability_check.py --help
```

### 4. 当前 `PAPER` 假盘运维、看板校验与本地 `M10` 监控
```bash
# 1. 校验唯一任务台账与离线进度看板字节级一致性
python3 scripts/render_progress_board.py --check

# 2. 启动本地只读 M10 实时刷新服务 (仅监听 127.0.0.1:8765，支持 GET/HEAD)
python3 scripts/serve_m10_live.py --host 127.0.0.1 --port 8765

# 3. 原子归档历史审计日志为 .jsonl.gz (自动跳过今日 UTC 目录并校验 SHA-256)
python3 scripts/archive_audit_logs.py --audit-root data/audit_logs/PAPER
```

---

## 测试套件执行与验证

项目采用严格的测试护航纪律，任何交付必须附带回归测试证据：

```bash
# 1. 运行全量测试套件 (全库 987 项基线测试: 987 passed, 10 skipped, 0 failed)
pytest -q

# 2. 运行单测与集成测试
pytest tests/unit/ tests/integration/ -q

# 3. 运行真实 NOAA AWS 网络冒烟测试 (需外网访问)
RUN_NETWORK_TESTS=1 pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q
```

---

## 核心文档索引

- **唯一实时任务台账（`v3.14`）**：[`docs/audit/P8-PROJECT-TASKS_全量任务分解台账.md`](docs/audit/P8-PROJECT-TASKS_全量任务分解台账.md)（[离线进度看板](docs/audit/progress_board.html)）
- **决策与执行接口规格（`v1.2` · 含 `P2 v1.2 / P18 v1.1`）**：[`docs/audit/P8-T4-M4M5-INTERFACE_决策与执行接口规格.md`](docs/audit/P8-T4-M4M5-INTERFACE_决策与执行接口规格.md)
- **算法四单工程设计书（`v0.3` · 含 `2026-11-28` 增量）**：[`docs/audit/P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md`](docs/audit/P8-T8-ALGO4-DESIGN_算法四单工程设计书_v0.3.md)
- **监控页业务逻辑设计说明（`M10` · 含 5 项一致性核验）**：[`docs/audit/P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md`](docs/audit/P8-M10-DESIGN_监控页业务逻辑设计说明_v1.0.md)
- **制度合龙与标定规范（`D-6 v1.0`）**：[`docs/audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md`](docs/audit/P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md)

- **内核架构档案（`v1.1` · `2026-11-17`）**：[`docs/audit/P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md`](docs/audit/P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md)
- **资金参数配置与参数账本（`v1.0` · `2026-11-17`）**：[`docs/audit/P8-CAPITAL-CONFIG_资金参数配置_v1.0.md`](docs/audit/P8-CAPITAL-CONFIG_资金参数配置_v1.0.md)
- **`w` 与 `φ` 执行设计与决策记录（`v1.0` · `2026-11-17`）**：[`docs/audit/P8-EXECUTION-DESIGN_w与phi设计与决策记录_v1.0.md`](docs/audit/P8-EXECUTION-DESIGN_w与phi设计与决策记录_v1.0.md)
- **Polymarket 静态事实档案（`v0.2` · `2026-11-18`）**：[`docs/audit/P8-FACTS-LEDGER_静态事实档案_v0.1.md`](docs/audit/P8-FACTS-LEDGER_静态事实档案_v0.1.md)
- **项目实时状态（唯一状态入口）**：[`STATUS.md`](STATUS.md)
- **战术全局图谱与活队列（`v1.3`）**：[`docs/audit/P8-GLOBAL-MAP_项目全局图谱_v1.0_20261113.md`](docs/audit/P8-GLOBAL-MAP_项目全局图谱_v1.0_20261113.md)
- **战略阶段路线图（`v1.4.0`）**：[`docs/ROADMAP.md`](docs/ROADMAP.md)
- **检验 C 司法级完整档案（含 `2019-SEALED-001`）**：[`docs/audit/P8-INSPECTION-C-FULL-DOSSIER_20261114.md`](docs/audit/P8-INSPECTION-C-FULL-DOSSIER_20261114.md)
- **备选架构立项与机制分析（已对齐内核 v1.0）**：[`docs/audit/P8-BETA-GAMMA-PROPOSAL_备选架构立项报告_20261114.md`](docs/audit/P8-BETA-GAMMA-PROPOSAL_备选架构立项报告_20261114.md)
- **待确认事项登记册 & 2019 消费台账**：[`docs/audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md`](docs/audit/P8-ALGO-REVIEW_待确认事项登记册_20261113.md)
- **设计组裁决与审查记录**：[`docs/audit/P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md`](docs/audit/P8-DESIGN-TEAM-REVIEW_裁决与审查记录.md)
- **端到端数学模型规格书（v2.0 含 G-14 勘误）**：[`docs/audit/P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md`](docs/audit/P8-ALGO-DEF-SPEC_气象物理预测到投注端到端严谨数学模型规格书_20261108_v2.0.md)
- **新会话冷启动交接清单**：[`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)
- **双城封盘门禁与事实核验报告**：[`evidence/p6_tmax_methodology_closure.md`](evidence/p6_tmax_methodology_closure.md)
- **生产评估窗口法医穿透报告**：[`evidence/p6_window_forensic_report.md`](evidence/p6_window_forensic_report.md)
- **业务方案蓝图（`v3.0` · 含 §8 模块地图与 `P1–P19` 协议索引）**：[`项目方案 (v3.0)：Polymarket 温度市场量化投注系统`](docs/项目方案和执行文档/项目方案%20(v3.0)：Polymarket%20温度市场量化投注系统.md)
- **Phase 2 执行文件**：[`Phase 2 执行文件 v2.2：盘口定价、套利与执行引擎`](docs/项目方案和执行文档/Phase%202%20执行文件%20v2.2：盘口定价、套利与执行引擎.md)
- **架构决策记录 (ADR)**：[`docs/adr/`](docs/adr/)
