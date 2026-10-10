# Polymarket 温度预测与量化套利系统 - Phase 7 过渡态

> [!NOTE]
> **[P7-DOC-RECON 文档勘误与法定状态对齐 (2026-10-10)]**：  
> 本文档已依据工单 `P7-DOC-RECON`、`STATUS.md`、`docs/HANDOVER_P7.md` 与 `docs/ROADMAP.md` 全面重写，对齐 **Phase 7 过渡态**（主线战略由“横向扩展”全面转向“纵向落地”）。  
> 主干代码库严格固化于 **`2975ec1`**（PR #130 合流线；前基线 `6fe386c` 为 P6 封卷线），全库测试基线保持 **`987 passed, 10 skipped, 0 failed`**。

> 📌 **法定长线规划与新会话交接导航**：  
> • 项目状态总入口：[`STATUS.md`](STATUS.md)  
> • 三波次长线路线图：[`docs/ROADMAP.md`](docs/ROADMAP.md)  
> • 新会话冷启动交接清单：[`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)  
> • 双城封盘九项门禁清单：[`docs/SEALING_GATE.md`](docs/SEALING_GATE.md)  
> • 受控出域同步政策：[`docs/SYNC_POLICY.md`](docs/SYNC_POLICY.md)

> 🚩 **【双重法定运行旗持续生效（下游强制带旗引用）】**：  
> 1. `KMIA_12h`：状态 `COMPLETED_ECE_FLAGGED`（交易窗口加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 未达立项门槛；双城 24 格中 23 格 ECE 达标率 95.83%）；  
> 2. `6h 池化回退层 (80 格)`：状态 `FLAGGED_POOL_PHASE_ISSUE`（晨谷方差膨胀比 1.45~1.81x，KMIA 晨谷 ECE = `0.019657` 越线 0.0100；Max Temp 缺失衰减公式依赖 METAR 实况硬截断兜底；工单 `P7-W1-POOLPHASE` 专项修复中）。  
> *下游引用约束*：交易盘口映射、分位数定价与风控链路在调用本格资产时，**必须显式带旗陈述，审慎收缩头寸，严禁脱旗裸跑**！

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
│  • 结算源: NWS WRH CF6 每日气候报表 (Polymarket 法定结算源)  │
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
| **Phase 7: 过渡态 (当前活跃)** | **长线路线图入册与三波次战略推进 (PR #130 合流至 `2975ec1`)**<br>• 战略转向：气象侧地基巩固，主线全面转向交易侧纵向落地<br>• **W1**: `P6-POOL-PHASE` 6h 池化按相位分层重训与衰减补全（工单领单中）<br>• **W2**: Phase 2 双站（KORD/KMIA）只读纸面盘短闭环主线（待启动）<br>• **W3**: Active 8 站三原型轻量筛查与 TMin 480 格审计规划（纸面盘期并行） | **进行中** | [`STATUS.md`](STATUS.md)<br>[`docs/ROADMAP.md`](docs/ROADMAP.md)<br>[`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md) |
| **生产交易引擎** | 盘口撮合、多项增量联合凯利、IOC 订单路由与异常中枢（实盘前置阶段） | 待实盘前置 | `OrderRouter`, `CentralExceptionArbiter` |

---

## 核心技术规格与设计决策

1. **真实观测与法定结算真值协议**：
   - **IEM ASOS RMK T 组真值**：彻底废弃旧版 Wunderground，采用 ASOS 报文尾部 `T` 组编码（精确至 $0.1^\circ\text{C}$ / $0.18^\circ\text{F}$），杜绝整度截断误差；
   - **法定结算源（ADR-0012）**：Polymarket 官方 100% 结算于 **NWS WRH CF6 每日气候报表**；
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
   - **法定硬门禁**：交易窗口加权 **$\text{ECE} \le 0.0100$**（20 桶 $\times$ 5% 等宽分桶，样本数 $n < 30$ 且 $\bar{p}$ 最接近的相邻非空桶合并）；
   - **全库测试基线**：全量 **987 项测试全绿** 护航（10 skipped, 0 failed），代码交付零回归。

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
│   ├── data_acquisition/        # 数据采集层 (GEFS GRIB2 下载器与解析)
│   ├── data_processing/         # 数据工程与存储层 (常量、转换、物理递减率、时序对齐)
│   ├── modeling/                # 概率建模层 (EMOS、JSU、EVT、CRPS、BIC 选型、插值器)
│   ├── prediction/              # 三层预测与盘口转化层 (静态预测、动态截断、物理硬拦截、2°F 映射)
│   ├── validation/              # 审计与验证层 (ECE、PIT、Block-CV、可靠度检验工具)
│   ├── pipeline/                # 统一流水线与健康中枢
│   └── utils/                   # 结构化日志与通用工具
├── scripts/                     # 命令行工具与全网格审计脚本
│   ├── run_poly_pipeline.py     # 生产统一 CLI 交互中枢
│   ├── run_p6_fullgrid_tmax.py  # P6 双城 TMax 24 时间格 Block-CV 审计脚本
│   └── standalone_reliability_check.py # 可靠度独立检验工具
├── tests/                       # 测试套件 (987 项测试基线)
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

- **项目实时状态（唯一状态入口）**：[`STATUS.md`](STATUS.md)
- **三波次长线路线图**：[`docs/ROADMAP.md`](docs/ROADMAP.md)
- **新会话冷启动交接清单**：[`docs/HANDOVER_P7.md`](docs/HANDOVER_P7.md)
- **双城封盘门禁与事实核验报告**：[`evidence/p6_tmax_methodology_closure.md`](evidence/p6_tmax_methodology_closure.md)
- **生产评估窗口法医穿透报告**：[`evidence/p6_window_forensic_report.md`](evidence/p6_window_forensic_report.md)
- **业务方案蓝图**：[`项目方案 (v2.8)：Polymarket 温度市场量化投注系统`](docs/项目方案和执行文档/项目方案%20(v2.8)：Polymarket%20温度市场量化投注系统.md)
- **Phase 2 执行文件**：[`Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎`](docs/项目方案和执行文档/Phase%202%20执行文件%20v2.1：盘口定价、套利与执行引擎.md)
- **架构决策记录 (ADR)**：[`docs/adr/`](docs/adr/)