# Polymarket 温度预测系统 - Phase 1.5 (数据管道重建与高精度物理概率模型)

> [!CAUTION]
> **CRITICAL NOTICE (Phase 2 Review Gate)**:
> Metrics fixed at commit `67d668b`. All pre-existing metric-dependent conclusions (including Phase 2 Task 07 signoff, 813-test pass claims, and 2019 backtest results) are **VOID pending `--recompute`** with verified statistical closure metrics.

本项目旨在构建一个高精度的物理概率模型，用于预测 Polymarket 气温市场的日最高和最低气温概率分布。系统以高斯 EMOS（Ensemble Model Output Statistics）模型为核心，采用“全球再预报特征提取 $\to$ 12 站全池模型矩阵训练 $\to$ 实时动态截断与物理约束 $\to$ Polymarket 离散盘口概率转换 $\to$ 严格样本外三重验收门禁回测与监控告警 $\to$ 状态机流水线编排”的全链路量化架构。

当前项目执行规范以 **《Phase 1.5 执行文件 v1.1：数据管道重建与校准语料库》** 及 **《工作指导文件：GEFS 数据补全、站点提取与质量验证（GEFS-WI-v1.1）》** 为准；业务需求来源为 **《项目方案：Polymarket 温度市场量化投注系统 (v2.6)》**。

---

## 核心系统架构 (Phase 1.5 12 站宇宙)

```
┌─────────────────────────────────────────────────────────────┐
│                    物理约束层 (Phase 1C)                    │
│  基于 12 站历史极端变温率与极值窗口的物理边界硬拦截          │
└─────────────────────────────────────────────────────────────┘
                               ▲
┌─────────────────────────────────────────────────────────────┐
│                    动态修正层 (Phase 1C)                    │
│  实时观测温度条件概率截断: P(X ≥ L | X > T_now)             │
└─────────────────────────────────────────────────────────────┘
                               ▲
┌─────────────────────────────────────────────────────────────┐
│                 静态高斯 EMOS 基础模型 (Phase 1B)           │
│  μ = a + b * ensemble_mean                                  │
│  σ² = c² + d² * ensemble_variance + σ_clim(d)² (平方参数化) │
│  (11 站 × 4 季 × 5 节点 = 220 组独立矩阵模型 + 时效插值)     │
└─────────────────────────────────────────────────────────────┘
                               ▲
┌─────────────────────────────────────────────────────────────┐
│                 数据工程与特征存储基石 (Phase 1.5)          │
│  • 真值源: IEM ASOS 原报 (RMK T 组 0.1°C) + NWS WRH 结算仲裁│
│  • 预报源: NOAA GEFS 全球再预报 (2000-2019, 7305 日冷归档) │
│  • 11 站统一特征库 (data/processed/gefs_factors/, 220 文件) │
│  • 本地日包含 6h 窗口切片 + 高程物理递减率修正 (Γ=0.0065K/m)│
└─────────────────────────────────────────────────────────────┘
```

---

### 站点宇宙体系 (11 站全美活跃交易大池)

根据《ADR-0007》及《项目方案 (v2.6)》，系统已彻底废除旧版 Wunderground 与无常态日盘的观察站（KDCA 已正式退役），全面聚焦于全美 11 个活跃交易站点：

1. **首发结算站**：`KORD`（芝加哥奥黑尔，Era 2 法定最高置信度站）
2. **Tier 1 主力站**：`KLGA`（纽约拉瓜迪亚）、`KATL`（亚特兰大哈兹菲尔德）、`KDAL`（达拉斯爱田）
3. **Tier 2 扩展站**：`KSEA`（西雅图塔科马）、`KLAX`（洛杉矶）、`KHOU`（休斯顿霍比）
4. **微气候重点站**：`KMIA`（迈阿密）、`KSFO`（旧金山）
5. **特许结算站**：`KBKF`（丹佛巴克利太空军基地，Polymarket 丹佛法定结算站）
6. **扩充主力站**：`KAUS`（奥斯汀，活跃日盘）

---

## 项目阶段与执行状态

| 阶段 / 模块 | 核心工作流与当前状态 | 完成度 | 核心交付物 |
| :--- | :--- | :---: | :--- |
| **Phase 1 基线封存** | **Git Tag `phase1-final` (Commit 53b1024)**<br>• 18 份 M0' 审计产物移入 `docs/frozen/phase1/`（只读）<br>• Wunderground 等旧数据物理隔离至 `data/legacy-v1-suspect/` | **100%** | 封存清单、只读声明头与隔离区 |
| **Phase 1.5: Task 09** | **GEFS 补全与 11 站特征提取**<br>• 外部冷存储 292,200 个 GRIB2 全球场补全与内容去重<br>• 11 站 × 20 年 (2000–2019) 因子长表提取（共 9,641,830 行）<br>• V1~V13 全部 13 项门禁 100% 验收通过 | **100%** | `gefs_factors/` (220 个 Parquet)<br>`gefs_task09_qc_v1.0.md`<br>`manifest.json` |
| **Phase 1.5: Task 01~08** | **数据管道重建与校准语料库**<br>• Task 01 封存基线 (已闭环)<br>• Task 02 IEM 管道正式化 (进行中)<br>• Task 03 挂账清账 (特报语义 ADR 与 19 年探针)<br>• Task 04~08 观测全量重取、Floor 重建与数据集发布 | **进行中** | `STATUS.md`<br>IEM 管道代码<br>校准数据集 v2.0 |
| **Phase 2: 生产投注系统** | 待 Task 08 与 Phase 2 前置 ADR 裁决后开工 | 待启动 | 交易引擎与自动化下注中枢 |

---

## 核心技术规格与设计决策

1. **真实观测与结算对齐协议**：
   - **IEM ASOS RMK T 组真值**：彻底废弃旧版 Wunderground，采用 ASOS 报文尾部 `T` 组编码（精确至 $0.1^\circ\text{C}$ / $0.18^\circ\text{F}$），杜绝整度截断误差；
   - **双源结算仲裁**：日常以 IEM 原报为主管线，遇到报文争议自动对齐 NWS WRH 结算网页快照（[ADR-0007](docs/adr/ADR-0007%EF%BC%9A%E6%95%B0%E6%8D%AE%E6%BA%90%E9%87%8D%E9%93%B8%E4%B8%8E%E7%AB%99%E7%82%B9%E5%AE%87%E5%AE%99%E6%89%A9%E5%B1%95%EF%BC%88M0%27%20%20Round%205%20%E7%BB%BC%E5%90%88%E8%A3%81%E5%86%B3%EF%BC%89.md)）；
   - **时区与市场 Era 分层**：严格区分 Era 1（$\le 2026\text{-}08\text{-}22$ 历史离线段）与 Era 2（$\ge 2026\text{-}08\text{-}23$ 现行法定小时报段），本地日切换自适应冬令时/夏令时（23h/25h）。

2. **气象预报因子与无损提取**：
   - **GEFS 全球场冷归档**：外部存储完整保留 7,305 天（2000–2019）原始 GRIB2 数据，禁止物理移动或删除；
   - **全池时效并集**：统一提取 `[12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]` 共 12 个时效时段，保障全美 4 大时区包含窗零截断；
   - **静态 $0.25^\circ$ 网格索引**：利用全球等距网格数学不变量公式实现向量化切片，12 站单遍扫描效率高达 $1.7\,\text{s}/\text{天}$，且通过 Gate V4 黄金样本零误差检验（误差 $\le 0.005\,\text{K}$）。

3. **数学模型与方差保护**：
   - **平方参数化方差**：$\sigma^2 = c^2 + d^2 S_{ens}^2 + \lambda \cdot \sigma_{clim}^2(d)$，天然保证非负性，消除负参数误判风险；
   - **气候学方差 Floor**：基于 2000–2018 严格 OOS 实测数据，采用 31 天滑动窗计算，彻底防止 5 成员小集合在低离散度天气下的过度自信与方差坍塌（[ADR 0001](docs/adr/0001-gaussian-emos-with-variance-floor.md)）；
   - **时效分桶与内插外推**：最高温真实节点 `{6h, 30h, 54h}`，最低温真实节点 `{24h, 48h}`。缺失时效线性内插，$<24\text{h}$ 最低温模型引入 $\sigma \cdot \sqrt{L/24}$ 物理衰减（[ADR 0002](docs/adr/0002-five-lead-time-nodes-with-interpolation.md)）。

4. **三层预测与盘口转化**：
   - **实时动态截断**：结合日内最新实况，对累积极值进行条件概率截断 $P(X \ge L \mid X \ge T_{now})$，后验单调性保障与 $\epsilon=10^{-7}$ 边界保护；
   - **变温率硬拦截**：基于站点历史最大升/降温速率 $\times$ 极值窗口剩余时间 $\Delta t$ 计算机理不可达边界，硬截断超限概率；
   - **Polymarket 盘口映射**：针对各站市场规则（华氏度 ℉ 或 摄氏度 ℃），生成互斥 Bins，施加连续性修正并保证概率全概率归一化（$\sum P = 1.0$）。

4. **v5.9.2 三重验收门禁**：
   - **标准节点校准**：真实时效节点 PIT 直方图 K-S 检验 $p > 0.05$；
   - **留出插值守恒**：30h 留出插值虚拟模型 $\text{CRPS}_{virt} \le 1.05 \times \text{CRPS}_{real}$ 且 PIT $p > 0.05$；
   - **极端天气压力测试**：2019 严格 OOS 极端事件 90% 置信区间覆盖率 $\ge 80\%$，且 $\text{CRPS}_{model} < \text{CRPS}_{clim}$（战胜气候学）。

---

## 目录结构

```
Poly Way2/
├── configs/                     # 系统配置文件
│   ├── default.yaml             # 生产级默认配置
│   ├── dev.yaml                 # 开发与快速调试配置
│   └── test.yaml                # 单元/集成测试配置
├── src/
│   ├── data_acquisition/        # 数据采集层
│   │   ├── gefs_fetcher.py              # NOAA GEFS GRIB2 下载器与区域裁剪
│   │   ├── gefs_batch_downloader.py     # CSV 状态机驱动的批量下载调度器
│   │   └── wunderground_scraper.py      # Wunderground 历史实测爬虫
│   ├── data_processing/         # 数据工程与存储层
│   │   ├── constants.py                 # 站点坐标、高程及中央常量
│   │   ├── unit_converter.py            # 温度单位向量化转换 (K/C/F)
│   │   ├── elevation_corrector.py       # 高程递减率物理订正
│   │   ├── spatial_interpolator.py      # 4 点双线性空间插值
│   │   ├── time_aligner.py              # 本地日时效对齐与 NOAA 天文日出校验
│   │   ├── feature_extractor.py         # 6h 极值折叠与 5 成员统计量提取
│   │   ├── data_processor.py            # 端到端数据处理统一编排
│   │   ├── data_validator.py            # Schema 与物理合理性校验器
│   │   ├── parquet_store.py             # Parquet 分区特征库 ({station}/{year}.parquet)
│   │   ├── database.py                  # SQLite 时序与指标数据库引擎
│   │   └── storage_manager.py           # 统一存储管理门面 (对齐训练集 X, y)
│   ├── modeling/                # EMOS 概率建模层
│   │   ├── climatology.py               # 31 天滑动窗 OOS 气候学方差 Floor
│   │   ├── gaussian_emos.py             # 平方参数化高斯 EMOS 分布类
│   │   ├── crps.py                      # Gneiting 闭式高斯 CRPS 向量化损失
│   │   ├── emos_trainer.py              # L-BFGS-B 参数优化器与体检评分卡
│   │   ├── degradation.py               # 两级降级容灾与过拟合软告警
│   │   ├── partitioner.py               # 季节分集与 6h 时效归桶器
│   │   ├── interpolator.py              # 缺失节点参数插值与短时效物理衰减
│   │   ├── matrix_trainer.py            # 40 组矩阵批量训练与评估看板
│   │   ├── registry.py                  # 模型持久化与注册中心门面
│   │   ├── validation_engine.py         # 样本外时序交叉验证引擎
│   │   ├── report_generator.py          # 三重门禁评估报告生成器
│   │   └── pipeline.py                  # 端到端模型训练编排器
│   ├── prediction/              # 三层预测与盘口转化层
│   │   ├── static_predictor.py          # 静态基础预测与模型路由
│   │   ├── dynamic_corrector.py         # 实时实况条件概率截断
│   │   ├── constraint_enforcer.py       # 历史变温率物理极限硬约束
│   │   ├── bin_converter.py             # Polymarket 盘口区间转换与结算判定
│   │   └── prediction_pipeline.py       # 端到端四层预测流水线与持久化
│   ├── validation/              # 回测验证与监控告警层
│   │   ├── metrics.py                   # CRPS / Brier / LogLoss / PIT / ECE 指标库
│   │   ├── significance.py              # Diebold-Mariano / Wilcoxon 统计显著性检验
│   │   ├── triple_gate.py               # v5.9.2 三重验收门禁独立评估器
│   │   ├── backtester.py                # Rolling-Origin 历史时序回测引擎
│   │   ├── backtest_reporter.py         # 回测综合评估看板与时序诊断生成器
│   │   ├── alert_manager.py             # 性能劣化与数据异常告警管理器
│   │   └── alert_dispatcher.py          # 告警防抖节流与多通道分发器
│   ├── pipeline/                # 全局流水线与健康中枢
│   │   ├── config.py                    # 强类型 Pydantic 配置管理系统
│   │   ├── health.py                    # 存储/数据库/模型就绪健康诊断
│   │   ├── resilience.py                # 全局重试与异常隔离
│   │   └── main_pipeline.py             # Ingest->Feature->Train->Predict->Validate 编排器
│   └── utils/                   # 通用工具层
│       ├── logger.py                    # 结构化上下文日志记录器
│       └── profiler.py                  # 阶段耗时统计与 Profiler
├── scripts/                     # 命令行工具与可执行脚本
│   ├── run_poly_pipeline.py             # 生产级统一 CLI 交互中枢
│   ├── train_emos_matrix.py             # 40 组矩阵模型一键训练脚本
│   ├── run_predictions.py               # 盘口概率预测 CLI 工具
│   ├── run_backtest.py                  # 历史时序回测与门禁评估 CLI 工具
│   ├── download_gefs_batch.py           # GEFS 历史数据批量下载
│   └── download_wunderground_batch.py   # Wunderground 历史实测批量抓取
├── tests/                       # 测试套件 (347+ 项测试全绿)
│   ├── unit/                            # 单元测试 (按模块分层隔离)
│   ├── integration/                     # 模块间集成测试
│   └── e2e/                             # 系统级全链路 E2E 验收测试
├── docs/                        # 项目文档体系
│   ├── adr/                             # 架构决策记录 (ADR 0001 ~ 0005)
│   ├── configuration-guide.md           # 生产配置手册
│   ├── troubleshooting.md               # 实战排障与运维指南
│   └── spec-update-process.md           # 规格变更流程
└── specs/                       # 实施任务与工程规格跟踪
    └── implementation-tasks-phase1.md   # Phase 1 细化任务跟踪表 (100% Complete)
```

---

## 快速上手与 CLI 命令

统一 CLI 入口为 [`scripts/run_poly_pipeline.py`](scripts/run_poly_pipeline.py)：

### 1. 系统健康自检
检查 SQLite 数据库、Parquet 特征库及 40 组模型就绪状态：
```bash
python scripts/run_poly_pipeline.py health --config configs/default.yaml
```

### 2. 端到端全流程运行
按顺序执行 `Ingest -> Feature -> Train -> Predict -> Validate` 全阶段：
```bash
# 开发环境运行
python scripts/run_poly_pipeline.py all --env dev

# 从训练阶段断点恢复运行后续所有阶段
python scripts/run_poly_pipeline.py all --resume-from train
```

### 3. 单阶段调用
```bash
# 训练 40 组 EMOS 矩阵模型
python scripts/run_poly_pipeline.py train --start-year 2000 --end-year 2018

# 单站单日盘口概率预测 (上海最高温)
python scripts/run_poly_pipeline.py predict --station ZSPD --date 2026-08-21 --target-type max

# 执行历史时序回测与三重门禁裁决
python scripts/run_poly_pipeline.py backtest --start-year 2018 --end-year 2019
```

---

## Python API 调用示例

### 1. 三层预测系统调用 (静态基准 + 动态截断 + 物理约束 + 盘口转换)
```python
from datetime import date
from src.prediction import PredictionPipeline
from src.pipeline.config import ConfigManager

# 1. 加载配置并初始化端到端预测流水线
config = ConfigManager.load_config("configs/default.yaml")
pipeline = PredictionPipeline(config=config)

# 2. 执行单站单日预测 (包含实时实况动态修正)
result = pipeline.predict_single_day(
    station_id="ZSPD",
    target_date=date(2026, 8, 21),
    target_type="max",
    current_obs_temp=32.5,  # 实时观测温度 (℃)
    lead_hours=18.0         # 距离目标有效时间提前量
)

# 3. 查看输出的高斯参数与 Polymarket 离散盘口概率
print(f"校准高斯分布: μ={result.static_mu:.2f}°C, σ={result.static_sigma:.2f}°C")
print("Polymarket 盘口区间概率分布:")
for bin_name, prob in result.bin_probabilities.items():
    print(f"  {bin_name}: {prob * 100:.1f}%")
```

### 2. 统一全流程编排器调用 (`MainPipeline`)
```python
from src.pipeline.main_pipeline import MainPipeline
from src.pipeline.config import ConfigManager

config = ConfigManager.load_config(env="dev")
pipeline = MainPipeline(config=config)

# 运行全链路流水线并获取各阶段执行摘要
summary = pipeline.run_all(resume_from="train")
print(f"流水线状态: {summary['status']}, 耗时报告: {summary['profile_report_path']}")
```

---

## 测试套件执行与验证

项目采用严格的 TDD（测试驱动开发）规范开发，全量覆盖单元测试、集成测试与系统级 E2E 测试：

```bash
# 1. 运行全量测试套件 (347+ 项测试全绿通过)
pytest tests/unit/ tests/integration/ tests/e2e/ -q

# 2. 运行系统级全链路 E2E 测试
pytest tests/e2e/test_e2e_pipeline.py -v

# 3. 运行真实 NOAA AWS 网络冒烟测试 (需外网访问)
RUN_NETWORK_TESTS=1 pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -v
```

---

## 文档索引

- **系统配置指南**：[`docs/configuration-guide.md`](docs/configuration-guide.md)
- **运维排障手册**：[`docs/troubleshooting.md`](docs/troubleshooting.md)
- **架构决策记录 (ADR)**：[`docs/adr/`](docs/adr/)
  - `0001`: 高斯 EMOS 与 31 天滑动窗气候学方差 Floor
  - `0002`: 五个时效节点与参数插值/物理衰减
  - `0003`: 两级降级容灾架构
  - `0004`: 5 成员集合协议严格对齐
  - `0005`: GRIB 变量合并容差约束
  - `0006`: 离散区间全概率映射与严禁累积尾部单向交易原则
- **任务实施规格**：[`specs/implementation-tasks-phase1.md`](specs/implementation-tasks-phase1.md)
- **核心执行规范**：[`项目执行文件 v5.9.2(细化版)`](项目执行文件%20v5.9.2(细化版).md)
- **业务方案蓝图**：[`项目方案：Polymarket 温度市场量化投注系统 (v2.4 Final)`](项目方案：Polymarket%20温度市场量化投注系统%20(v2.4%20Final).md)