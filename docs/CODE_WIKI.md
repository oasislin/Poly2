# Code Wiki — Polymarket 温度预测与量化套利系统

> 本文档为仓库级代码百科（Code Wiki），基于主干代码（Phase 7 过渡态，主线基线 `5c4a4c9`，测试基线 `1006 passed, 10 skipped, 0 failed`）静态分析生成，覆盖整体架构、模块职责、关键类与函数、依赖关系与运行方式。生成日期：2026-10-24。

---

## 1. 项目概览

本项目构建一个高精度物理概率模型与量化套利系统：预测 Polymarket 气温市场的日最高温（TMax）/ 最低温（TMin）概率分布，并将气象预测的物理优势转化为正期望值（+EV）投注决策。

- **包名 / 版本**：`poly-way2` v2.2.0（见 `pyproject.toml`）
- **Python**：`>=3.13, <3.14`
- **核心链路**：GEFS 全球再预报特征提取 → 960 格生产模型库（10 站 × 2 标的 × 4 季 × 12 提前期）→ 实时单调合流与特报截断 → 物理机理硬拦截 → Polymarket 2°F 阶梯离散盘口映射 → 订单簿对账与 +EV 执行
- **站点宇宙**：Active 10 法定主力池 `KATL, KAUS, KDAL, KHOU, KLAX, KLGA, KMIA, KORD, KSEA, KSFO`（法定真值定义于 `src/data_processing/constants.py` 的 `ACTIVE_10_STATIONS` 与 `configs/climate_floor_v2.json`）
- **训练 / 盲测窗口**：2000–2018 训练（6,940 天），2019 为物理 Airgap 隔离的独立盲测年（代码级守卫 `src/utils/airgap.py`）

---

## 2. 整体架构

### 2.1 分层架构（自下而上数据流）

```
┌───────────────────────────────────────────────────────────────┐
│ L6 交易契约与风控层   src/contract · src/risk · src/settlement │
│   物理参数消费契约(ADR-0019) / 流风控看门狗 / NWS 舍入复刻     │
├───────────────────────────────────────────────────────────────┤
│ L5 验证与审计层       src/validation · src/verification        │
│   · src/metrics       三重门禁 / 回测 / P5 可靠度门 / ECE·PIT  │
├───────────────────────────────────────────────────────────────┤
│ L4 预测层             src/prediction                           │
│   静态预测 → 动态截断修正 → 物理硬约束 → 2°F/1°F 离散分桶      │
├───────────────────────────────────────────────────────────────┤
│ L3 建模层             src/modeling                             │
│   Gaussian EMOS / Johnson SU / EVT 三族池、BIC 选型、          │
│   30 天 Block-CV、模型注册表（ModelRegistry）                  │
├───────────────────────────────────────────────────────────────┤
│ L2 数据工程层         src/data_processing                      │
│   时区对齐 / 双线性空间插值 / 海拔递减率修正 / 集合统计 /      │
│   Parquet 特征库 + SQLite 时序库                               │
├───────────────────────────────────────────────────────────────┤
│ L1 数据采集层         src/data_acquisition                     │
│   GEFS GRIB2 下载(Herbie/AWS) / IEM METAR / NWS WRH /          │
│   Polymarket 市场爬虫                                          │
└───────────────────────────────────────────────────────────────┘
        编排中枢：src/pipeline（MainPipeline 五阶段 + 流合流水线）
        基础设施：src/utils（结构化日志 / 性能剖析 / Airgap 守卫）
```

### 2.2 双流水线中枢

系统存在两条互补的执行中枢：

1. **离线批处理流水线** `src/pipeline/main_pipeline.py` — `MainPipeline` 编排五个枚举阶段 `PipelineStage.INGEST → FEATURE → TRAIN → PREDICT → VALIDATE`，由 CLI `scripts/run_poly_pipeline.py` 驱动，支持 `--resume-from` 断点恢复。
2. **实时流合流流水线** `src/pipeline/stream_confluence_pipeline.py` — `StreamConfluencePipeline` 端到端串联观测包解析 → 温度清洗门禁 → 单调合流 → 流风控评估（`process_packet / process_raw_metar / process_raw_nws_dict` 三个入口）。

### 2.3 预测执行栈（L4 内部）

`src/prediction/prediction_pipeline.py` 的 `PredictionPipeline.predict_single()` 串联四层：

```
StaticPredictor (静态 EMOS 分布 + 模型路由)
      → DynamicCorrector (实时观测条件截断 P(X ≥ L | X > T_now))
      → ConstraintEnforcer (历史极端升降温速率物理硬拦截, p=0.0)
      → BinConverter / DiscreteBinEngine (Polymarket 1°F/2°F 离散盘口概率)
      → TruncatedProbabilityEngine (观测锁定死亡 bin + simplex 重归一化)
```

---

## 3. 目录结构

```
Poly Way2/
├── src/                    # 全部生产代码（13 个子包，详见 §4）
├── scripts/                # 60+ 命令行工具与审计脚本（详见 §7）
├── configs/                # 运行配置 default.yaml / dev.yaml / test.yaml + climate_floor_v2.json
├── config/                 # 站点级标定配置（zspd_metar_noise_calibration.json）
├── data/
│   ├── processed/          # calib-dataset-v2.0 生产级校准因子库 (Parquet)
│   ├── models/             # 960 个生产模型资产 (.pkl/.json + manifest)
│   ├── db/                 # SQLite 时序库（观测/预测/验证指标）
│   ├── raw/ · cache/ · clob/ · paper_trading/ · reports/
│   ├── legacy-v1-suspect/  # 历史作废脏数据物理隔离区
│   └── gefs_*_download_state*.csv  # GEFS 分年下载状态机台账
├── tests/                  # unit / integration / e2e 三层测试（1006 项基线）
│   └── fixtures/           # p5_selfcheck 等黄金样本 oracle
├── docs/                   # 法定文档体系（ROADMAP / HANDOVER / ADR-0001~0019 / audit / frozen）
├── specs/                  # 阶段执行规格与预注册文件
├── evidence/               # 生产审计工件与封盘报告
├── logs/ · temp/ · legacy/ · models/ · reports/
├── conftest.py             # 将项目根注入 sys.path（全部导入使用 src. 前缀）
├── pyproject.toml          # 包元数据 + pytest 配置（testpaths=tests）
└── requirements.txt        # 依赖清单
```

---

## 4. 模块详解

### 4.1 `src/pipeline` — 编排中枢

| 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `main_pipeline.py` | 五阶段主编排器（ingest→feature→train→predict→validate） | `PipelineStage`(Enum)、`MainPipeline.run_all(resume_from, stages_to_run, date_str)`、`MainPipeline.run_stage()`、`PipelineExecutionResult` |
| `stream_confluence_pipeline.py` | 实时观测流端到端流水线：解析→清洗→单调合流→风控 | `StreamConfluencePipeline.process_packet() / process_raw_metar() / process_raw_nws_dict()`、`PipelineProcessResult` |
| `config.py` | 强类型配置系统（Ticket #40） | `PipelineConfig`（聚合 `DataConfig / ModelConfig / PredictionConfig / ValidationConfig / AlertConfig / TriggerConfig`）、`ConfigManager.load()` |
| `health.py` | 系统健康自检（存储/数据库/模型就绪） | `HealthChecker.check_storage() / check_database() / check_models() / run_all_checks()`、`HealthStatus` |
| `resilience.py` | 故障隔离与指数退避重试 | `retry_with_backoff(fn, max_retries, ...)`、`PipelineResilience.handle_failure()` |
| `gefs_extract.py` | GEFS 再预报站点特征提取器（GRIB→Parquet，含 SHA256 清单与黄金样本人检） | `extract_batch()`、`extract_station_year()`、`ManifestManager`、`assert_golden_samples_gate()`、`validate_physical_bounds()` |
| `iem_adapter.py` | IEM ASOS/METAR 正式观测适配（覆盖率/一致性双门禁） | `IemAdapter.fetch_station_year() / evaluate_gate1_coverage() / evaluate_gate2_wrh_consistency()`、`parse_metar_dry_bulb()`、`parse_metar_extreme_remarks()` |

### 4.2 `src/data_acquisition` — 数据采集层

| 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `gefs_fetcher.py` | GEFS 再预报/实时下载核心（Herbie + AWS，区域裁剪、MD5 校验、代理/超时熔断） | `GEFSFetcher.download_reforecast() / download_realtime() / build_search() / extract_region() / select_contained_windows()` |
| `gefs_batch_downloader.py` | GEFS 批量下载状态机（分年分片、断点续传、坏片修复、月度进度） | `GEFSBatchDownloader.run() / process_year() / download_gap_days()`、`YearState.is_fully_done()` |
| `observation_adapter.py` | 观测适配器抽象接口 | `BaseObservationAdapter`（`fetch_raw_series / extract_calendar_day_max / get_source_precision_metadata`）、`ObservationRecord`、`WundergroundAdapter`（已废弃 legacy） |
| `iem_metar_collector.py` | IEM ASOS/METAR 历史报文采集与极值 T 组解析（0.1°C 精度） | `IemMetarAdapter`、`parse_metar_dry_bulb()`、`parse_metar_extreme_remarks()` |
| `nws_wrh_collector.py` | NWS WRH / MesoWest 时序采集（法定结算源，ADR-0012） | `NwsWrhAdapter.fetch_raw_series() / fetch_recent() / extract_calendar_day_max()` |
| `observation_stream.py` | 实时观测流标准化数据契约（ObservationPacket） | `ObservationStreamAdapter.parse_iem_metar() / parse_nws_wrh_dict() / parse_observation_record()` |
| `polymarket_crawler.py` | Polymarket 温度市场爬虫与规则解析（从市场描述提取 NWS WRH 结算站点） | `PolymarketCrawler.search_city_events() / fetch_event_details() / extract_site_from_description() / determine_winning_bracket()`、`PolymarketMarketEvent` |
| `iem_coverage_prober.py` | IEM 历史覆盖率探测 | `IemCoverageProber.probe_station_coverage() / probe_batch()` |
| `rate_limit_stress_tester.py` | NWS API 限流/并发压测 | `RateLimitStressTester.run_stress_test()` |
| `scraping_metrics.py` | 抓取稳定性与可用率指标 | `ScrapingStabilityTracker.record_attempt() / compute_metrics()` |

### 4.3 `src/data_processing` — 数据工程与存储层

| 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `constants.py` | 站点元数据唯一法定来源 | `STATION_METADATA`、`STATION_COORDINATES`、`STATION_TIMEZONES`、`STATION_DEFAULT_UNITS`、`ACTIVE_10_STATIONS`、`ACTIVE_11_STATIONS` |
| `data_processor.py` | 端到端特征工程服务（对齐→窗口选择→日出覆盖→插值→单位→海拔→集合统计） | `DataProcessor.process_forecast_to_features() / batch_process()` |
| `time_aligner.py` | 本地日历日 UTC 边界、6h 包含窗口选择、天文日出计算 | `get_local_day_bounds_utc()`、`select_contained_6h_windows()`、`calculate_sunrise_time()`、`verify_sunrise_coverage()`、`TimeAligner` |
| `spatial_interpolator.py` | 双线性空间插值（经度体系自适应） | `bilinear_interp_2d()`、`find_surrounding_grid_indices()`、`SpatialInterpolator.interpolate_station()` |
| `elevation_corrector.py` | 海拔气温递减率修正 | `correct_elevation()`、`ElevationCorrector.correct_xarray()` |
| `unit_converter.py` | 温度单位标准化（°C/°F/K） | `convert_temperature()`、`UnitConverter.normalize_observations()` |
| `feature_extractor.py` | 集合统计提取（日极值折叠、均值/方差/成员极值） | `collapse_daily_extreme()`、`calculate_ensemble_statistics()`、`FeatureExtractor` |
| `data_validator.py` | 特征与观测的物理边界/schema 校验 | `DataValidator.validate_features() / validate_observations()` |
| `parquet_store.py` | Parquet 特征库 | `ParquetFeatureStore.save_features() / load_features() / list_inventory()` |
| `database.py` | SQLite 时序库（观测/预测/验证指标三表） | `TimeSeriesDatabase.save_observations() / save_predictions() / save_validation_metrics()` |
| `storage_manager.py` | 统一存储门面（Parquet + SQLite 编排） | `StorageManager.load_training_dataset() / verify_storage_health()` |
| `calendar_day_qc.py` | 本地日历日切片与 QC（断流/平线异常检测） | `CalendarDaySlicer`、`ObservationQualityControl.evaluate_day() / check_pipeline_health_or_raise()` |
| `slicer.py` | 高分辨率 ASOS 特征切片引擎（SPECI 分歧检测） | `ObservationSlicer.get_hourly_window() / slice_dataframe()`、`check_speci_divergence()`、`DailyFeatureRecord` |

### 4.4 `src/modeling` — 概率建模层

| 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `gaussian_emos.py` | 高斯 EMOS 分布核心（平方参数化 σ²=c²+d²·S_ens²，方差下限托底） | `GaussianEMOS.compute_params() / cdf() / pdf() / quantile() / crps()` |
| `crps.py` | Gneiting (2005) 高斯 CRPS 闭式解与优化损失 | `gaussian_crps(y, mu, sigma)`、`emos_crps_loss(params, ...)` |
| `emos_trainer.py` | EMOS 参数训练（L-BFGS-B、多起点、L2 正则） | `EMOSOptimizer.optimize() / fit()`、`ModelTrainingDiagnostics` |
| `climatology.py` | 气候学基线/方差底计算器 | `ClimatologyCalculator.fit() / get_climatology_variance()` |
| `climate_floor.py` | 气候方差底重建（滑窗 + 环形平滑 + 物理下限门禁） | `ClimateFloorBuilder.build_station()`、`ClimateFloorRegistry.save_to_json() / load_from_json()` |
| `partitioner.py` | 提前期分桶、名义本地时换算、季节矩阵分区 | `DatasetPartitioner.get_season() / get_lead_time_nodes() / split_by_season() / load_aligned_dataset()` |
| `matrix_trainer.py` | 矩阵批量训练编排与记分卡聚合 | `MatrixTrainer.train_all()`、`MatrixScorecard.summary_report()` |
| `interpolator.py` | 缺失提前期线性插值 + 短时效方差物理衰减（σ_L=σ_24h·√(L/24)） | `LeadTimeInterpolator.get_model_at_lead() / build_full_grid()` |
| `degradation.py` | 两级降级与软告警机制 | `DegradationHandler.evaluate() / get_active_distribution()` |
| `registry.py` | 模型持久化与统一推理门面（manifest 校验、原子写） | `ModelRegistry.save_model() / load_model() / verify_and_load_manifest() / predict()` |
| `validation_engine.py` | 样本外验证与滚动原点交叉验证（严格时间墙隔离） | `ValidationEngine.evaluate_slice() / generate_rolling_origin_folds()` |
| `resampling.py` | 30 天 Block-CV 引擎 + 季节 EMOS 三族 BIC 选型（Gaussian/JSU/EVT） | `BlockCrossValidator`、`run_block_cv()`、`fit_statutory_pipeline_fold()`、`partition_into_30day_blocks()` |
| `pipeline.py` | 训练端到端流水线（训练→持久化→验收验证） | `TrainingPipeline.run()`、`main()` |
| `report_generator.py` | 三重验收门禁报告生成 | `ReportGenerator.evaluate_gate1_pit() / evaluate_gate2_interpolation() / evaluate_gate3_extreme_tail() / generate_report()` |

### 4.5 `src/prediction` — 预测与盘口转化层

| 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `prediction_pipeline.py` | 预测主编排：静态→动态→物理约束→分桶→落库 | `PredictionPipeline.predict_single() / predict_batch() / get_history()`、`PredictionRecord` |
| `static_predictor.py` | 静态 EMOS 预测与模型路由 | `StaticPredictor.predict_single() / predict_batch()`、`StaticPredictionResult.cdf() / quantile()` |
| `dynamic_corrector.py` | 实时观测条件截断修正 P(X ≥ L \| X > T_now) | `DynamicCorrector.update_observation() / correct_max_temp_probability() / correct_min_temp_probability()`、`TruncatedDistribution` |
| `constraint_enforcer.py` | 物理升降温速率与可达边界硬拦截 | `ConstraintEnforcer.from_historical_data() / calculate_reachable_range() / enforce()`、`ConstrainedDistribution` |
| `bin_converter.py` | Polymarket 规则离散分桶与结算判定（1°F） | `BinConverter.calculate_bin_probabilities() / generate_bins() / determine_winning_bin()`、`MarketBin` |
| `discrete_bin_engine.py` | 高精度离散分桶引擎（2°F 吸附档、half-up 结算舍入） | `DiscreteBinEngine.generate_2deg_adsorbed_bins() / calculate_2deg_bin_probabilities()`、`settle_half_up()` |
| `truncated_probability_engine.py` | 截断概率引擎：观测锁定死亡 bin + simplex 重归一化 | `TruncatedProbabilityEngine.apply_truncation() / reset_locks()` |
| `monotonic_confluence.py` | 双源单调合流状态机（TMax 非递减 / TMin 非递增） | `MonotonicConfluenceEngine.ingest() / get_station_state()`、`StationDayState` |
| `temperature_sanitizer.py` | 纯温门禁、迟到丢弃、跳温阻断（fail-closed 熔断） | `TemperatureSanitizer.validate() / is_station_blocked()`、`SanitizerConfig` |

### 4.6 `src/validation` — 回测与告警层

| 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `triple_gate.py` | v5.9.2 §5 三重验收门禁正式实现 | `TripleGateEvaluator.evaluate_gate1_pit() / evaluate_gate2_interpolation() / evaluate_gate3_extremes()`、`TripleGateReport.to_markdown()` |
| `backtester.py` | 历史回测引擎（无 lookahead，多基线对比） | `BacktestEngine.run_backtest()`、`BacktestResult` |
| `baselines.py` | 参照基线预测器 | `ClimatologyBaseline / RawGEFSBaseline / PersistenceBaseline` |
| `metrics_calculator.py` | 统一指标：CRPS/CRPSS/MAE/RMSE/Bias/CI 覆盖/PIT/Talagrand/Brier | `MetricsCalculator.mean_crps() / compute_pit_values() / brier_score()` |
| `statistical_tests.py` | 显著性检验：Diebold-Mariano / Wilcoxon / 配对 t / PIT-KS | `diebold_mariano_test()`、`pit_ks_test()`、`StatisticalSignificance` |
| `backtest_reporter.py` | 回测记分卡与报告（lead-time 衰减表、MD/JSON/CSV） | `BacktestReporter.generate_markdown_report() / export_csv_details()` |
| `alert_manager.py` | 性能退化与数据异常检测（CRPS 退化/PIT 失准/陈旧/物理异常） | `AlertManager.check_crps_degradation() / check_data_staleness()`、`Alert` |
| `alert_dispatcher.py` | 多渠道告警分发（日志/文件） | `AlertDispatcher.dispatch()`、`LoggingAlertChannel / FileAlertChannel` |

### 4.7 `src/verification` — 生产审计门禁层

| 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `p5_gate.py` | P5 可靠度门禁正式入口与公共契约 | `run_reliability_gate(predictions, reference, config)`、`GateReport` |
| `resampling.py` | 时间序列块重采样与 CV 切分清单 | `generate_30day_blocks()`、`get_or_create_cv_manifest()` |
| `settlement.py` | 结算命中判定唯一真值源（离散化抖动） | `compute_settlement_hit_probability(obs_y, lb, ub, jitter_half_width)` |
| `weather_metrics.py` | 纯物理统计指标：Wilson 区间/可靠度图/PIT 诊断/离散分桶 | `compute_reliability_diagram()`、`compute_pit_diagnostics()`、`calculate_bin_probabilities()` |

### 4.8 其余支撑包

| 包 / 文件 | 职责 | 关键类 / 函数 |
|---|---|---|
| `src/contract/parameter_contract.py` | 物理参数消费契约（ADR-0019），气象层→交易层解耦接口 | `PhysicalParamContract.get_cell() / validate_cells_coverage()`、`CellCalibrationRecord`、`PhysicalForecastOutput` |
| `src/metrics/calibration_audit.py` | 统计闭合计量：PIT 理论矩、KS、加权 ECE、方差比 F 检验 | `assert_statistical_closure()`、`randomized_pit()`、`compute_weighted_ece()` |
| `src/risk/stream_watchdog.py` | 两级流风控看门狗与迟滞恢复 | `StreamRiskWatchdog.record_packet() / evaluate()`、`RiskLevel`、`WatchdogConfig` |
| `src/settlement/rounding_simulator.py` | NWS WRH 官方舍入复刻与临界哨兵 | `replicate_nws_temperature_rounding()`、`BorderlineSentinel.analyze()` |
| `src/data_analysis/` | M0' 审计工具组：站点记分卡、结算站审计、偏差分解、精度仲裁、时延/中断分析、分布标定 | `StationScorecardEvaluator`、`SettlementStationAuditor`、`DeviationDecomposer`、`PrecisionArbitrator`、`LatencyOutageAnalyzer`、`DistributionCalibrator` |
| `src/utils/logger.py` | 结构化日志（JSON/Console、上下文传播） | `setup_logger()`、`get_logger()`、`contextualize()` |
| `src/utils/profiler.py` | 阶段性能剖析 | `StageProfiler.profile() / to_markdown()`、`profile_stage()` |
| `src/utils/airgap.py` | 2019 盲测 Airgap 硬守卫（年份白名单/路径/数据帧净化） | `verify_year_whitelist()`、`verify_file_path()`、`sanitize_dataframe()`、`AirgapViolationError` |

---

## 5. 依赖关系

### 5.1 内部依赖主干（谁调用谁）

```
scripts/run_poly_pipeline.py
  └─ src/pipeline/main_pipeline.py (MainPipeline)
       ├─ pipeline.config / pipeline.health / pipeline.resilience
       ├─ [FEATURE]  data_processing.data_processor
       │    └─ time_aligner · spatial_interpolator · unit_converter
       │       · elevation_corrector · feature_extractor · constants
       ├─ [TRAIN]    modeling.pipeline (TrainingPipeline)
       │    └─ partitioner · climatology · emos_trainer · gaussian_emos
       │       · matrix_trainer · interpolator · degradation · registry
       │       · validation_engine · report_generator
       │         （底层：crps ← gaussian_emos ← emos_trainer ← degradation）
       ├─ [PREDICT]  prediction.prediction_pipeline
       │    └─ static_predictor → dynamic_corrector → constraint_enforcer
       │       → bin_converter / discrete_bin_engine → truncated_probability_engine
       │       （依赖 modeling.registry / climatology + data_processing.database）
       └─ [VALIDATE] validation.triple_gate
            └─ metrics_calculator · statistical_tests

scripts/standalone_reliability_check.py
  └─ verification.p5_gate · verification.resampling · modeling.resampling
       └─ utils.airgap（2019 净化守卫，建模重采样链路强制经过）

实时流链路：
pipeline.stream_confluence_pipeline
  └─ data_acquisition.observation_stream
     → prediction.temperature_sanitizer → prediction.monotonic_confluence
     → risk.stream_watchdog
```

关键横向依赖：
- `modeling/resampling.py` → `src.utils.airgap` + `src.verification.p5_gate`（训练侧强制 Airgap 净化）
- `validation/backtester.py` → `prediction.bin_converter`（回测复用盘口映射）
- `pipeline/resilience.py` → `validation.alert_dispatcher / alert_manager`（故障联动告警）
- `prediction/monotonic_confluence.py`、`temperature_sanitizer.py` → `data_processing.constants`（站点时区/元数据）
- `contract/parameter_contract.py` 无 src 内部依赖，为交易层消费的纯契约层

### 5.2 第三方依赖（requirements.txt）

| 类别 | 依赖 |
|---|---|
| 数值/科学计算 | `numpy`, `pandas`, `scipy`, `scikit-learn`, `statsmodels` |
| 气象网格数据 | `xarray`, `cfgrib`, `herbie-data`（GEFS 从 AWS Open Data 下载） |
| 存储 | `pyarrow`（Parquet）、`sqlite3`（标准库） |
| 网络采集 | `requests`, `aiohttp`, `aiofiles`, `beautifulsoup4` |
| 配置/时区 | `pyyaml`, `python-dateutil`, `pytz` |
| 测试 | `pytest==8.3.4`, `pytest-cov`, `pytest-mock`, `hypothesis` |
| 代码质量/文档 | `black`, `flake8`, `mypy`, `sphinx` |
| 其他 | `tqdm` |

---

## 6. 配置体系

- **入口配置**：`configs/default.yaml`（另有 `dev.yaml` / `test.yaml` 环境覆盖），由 `src/pipeline/config.py` 的 `ConfigManager.load()` 深合并加载为强类型 `PipelineConfig`。
- **主要配置段**：
  - `data`：站点列表、GEFS 成员（0–4 共 5 成员）、目录路径、`train_years: [2000, 2018]`、`val_years: [2019, 2019]`
  - `model`：lead time 节点（max: 6/30/54h，min: 24/48h）、`l2_reg: 0.001`、`optimizer: L-BFGS-B`、`variance_floor_type: climatology`
  - `prediction`：动态修正/物理约束开关、`bin_width: 1.0`
  - `validation`：三重门禁开关、显著性 α=0.05、极值 CI 目标 0.90
  - `alert` / `trigger`：退化阈值、轮询间隔、重定价边缘
  - `network`：代理开关、跨洋链路保底超时 180s
  - `storage.cold_storage_root`：GEFS 冷归档外部存储根（`/Volumes/EricSSD/Poly RawData/gefs_reforecast`）
  - `truncation_rules` / `arbiter` / `pre_buy_gate`：跳温步长 15°F、过期包阈值 15min、仲裁冷却等
- **气候方差底**：`configs/climate_floor_v2.json`（按 `day_of_year` 组织 `mu_raw/sigma_raw/variance_clim` 等字段），由 `ClimateFloorRegistry` 读写。
- **站点噪声标定**：`config/zspd_metar_noise_calibration.json`。

---

## 7. 运行方式

### 7.1 环境准备

```bash
pip install -r requirements.txt   # 需 Python 3.13
cp .env.example .env              # 按需填写密钥
```

### 7.2 统一 CLI：`scripts/run_poly_pipeline.py`

公共参数：`--config`、`--env`、`--log-level`、`--json-logs`；子命令：`health / all / ingest / feature / train / predict / backtest`。

```bash
# 系统健康自检（SQLite / Parquet 特征库 / 模型就绪）
python scripts/run_poly_pipeline.py health --config configs/default.yaml

# 端到端全流水线（支持断点恢复）
python scripts/run_poly_pipeline.py all --env dev
python scripts/run_poly_pipeline.py all --resume-from train

# 单站单日盘口概率预测
python scripts/run_poly_pipeline.py predict --station KORD --date 2026-10-10 --target-type max
```

### 7.3 关键专项脚本（scripts/ 共 60+）

| 类别 | 脚本 | 用途 |
|---|---|---|
| 生产审计 | `run_p6_fullgrid_tmax.py` | P6 双城 TMax 24 时间格 Block-CV 审计（`--station KORD/KMIA/ALL`、`--lead-hour`、`--zero-drift-check-only`） |
| 可靠度 | `standalone_reliability_check.py` | 独立可靠度检验（`--mode insample/cv/blind` + 分桶方案/站点/提前期参数） |
| 数据采集 | `download_gefs_batch.py`、`download_gefs_b2.py`、`download_gefs_b1_gaps.py` | GEFS 分年批量下载与缺口补全 |
| 观测采集 | `fetch_all_iem_observations.py`、`probe_iem_coverage.py`、`probe_nws_wrh_availability.py` | IEM/NWS 观测抓取与可用性探测 |
| 特征工程 | `build_feature_store.py`、`publish_calibration_dataset.py`、`probe_gefs_fxx_union.py` | 特征库构建与校准数据集发布 |
| 训练 | `train_emos_matrix.py`、`retrain_p4_active10_matrix.py`、`train_p7_w1_pooled_phase.py` | EMOS 矩阵训练与 Active 10 重训 |
| 评估 | `evaluate_active10_oos.py`、`evaluate_p4_2019_settlement.py`、`standalone_recompute_active10.py` | 样本外评估与重计算 |
| 回测/预测 | `run_backtest.py`、`run_predictions.py`、`run_pipeline_year.py` | 回测与批量预测 |
| 审计工具 | `audit_iem_precision_sample.py`、`audit_p4_reliability_v11~v13b.py`、`audit_provenance_and_recompute.py` | 精度/可靠度/溯源审计 |
| 其他 | `dashboard.py`、`benchmark_960_cells.py`、`inventory_external_gefs.py` | 看板、960 格基准、冷归档盘点 |

### 7.4 测试

```bash
pytest -q                          # 全量套件（基线 1006 passed, 10 skipped, 0 failed）
pytest tests/unit/ tests/integration/ -q
# 真实 NOAA AWS 网络冒烟（需外网；mock 全绿 ≠ 真实网络可用）
RUN_NETWORK_TESTS=1 pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q
```

- 测试三层结构：`tests/unit/`（按 src 子包镜像组织）、`tests/integration/`（模块间场景 A–E、定价 EV、存储、训练流水线）、`tests/e2e/`（全链路、单调性、百万级基准、跨种子）。
- `pyproject.toml` 配置 `testpaths = ["tests"]`、`addopts = "-p no:anyio -v"`；根 `conftest.py` 将项目根注入 `sys.path`，全部模块以 `src.` 前缀导入。

---

## 8. 测试与质量治理要点

- **契约测试纪律**：GEFS GRIB idx 正则、真实解码变量名（tmax/tmin）、网格方向等外部契约钉为快速单元测试；mock 仅 mirror 已联网验证的契约。
- **Airgap 守卫**：`src/utils/airgap.py` 在训练/重采样链路强制 2019 年份白名单校验，违规抛 `AirgapViolationError`。
- **判定下沉**：门禁判定（如 ECE ≤ 0.0100）以布尔结果落在代码中（`verification/p5_gate.py`、`metrics/calibration_audit.py`），报告层只读引用。
- **存储可审计**：`gefs_extract.py` 的 `ManifestManager` 记录每个工件 SHA256 与 git commit，保证溯源可复现。

---

## 9. 法定文档与进一步阅读

| 主题 | 位置 |
|---|---|
| 项目实时状态（唯一状态入口） | `STATUS.md` |
| 三波次长线路线图 | `docs/ROADMAP.md` |
| 新会话冷启动交接 | `docs/HANDOVER_P7.md` |
| 双城封盘九项门禁 | `docs/SEALING_GATE.md` |
| 架构决策记录（ADR-0001 ~ ADR-0019） | `docs/adr/` |
| 业务方案与阶段执行文件 | `docs/项目方案和执行文档/` |
| 阶段规格与预注册文件 | `specs/` |
| 生产审计工件 / 封盘报告 | `evidence/`（索引见 `EVIDENCE_INDEX.md`） |
| 模型记分卡 | `docs/MODEL_SCORECARD.md` |

---

*本 Wiki 为代码现状的静态快照；当主干结构、模块边界或 CLI 发生变化时，应同步更新对应章节。*
