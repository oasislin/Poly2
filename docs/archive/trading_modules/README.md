# 交易与仿真模块归档区（Trading & Simulation Modules Archive）

> **归档日期**：2026-10-13  
> **归档依据**：工单 R-16 用户裁决（方案 B：整体归档至隔离区，免复杂依赖排查，执行最小引用安全检查）  
> **状态变更**：撤销原"交易引擎完成度 0.0%"断言，正式标记为 **"已归档，待 P7-ALGO-2（《联合凯利与执行定价算法规格书》）重建"**。

---

## 一、归档背景与定位

本目录下归档的文件为早期与过渡态期间开发的交易、执行、资金池、风控、动态定价与回测仿真模块。

根据管理委员会与用户裁决：
1. 交易引擎此前未获正式执行授权，原评估报告中的"完成度 0.0%"结论不成立；
2. 现有交易模块整体移入隔离归档区，与现役气象数据采集、特征处理、EMOS 统计概率建模及验证系统彻底物理隔离；
3. 本目录下的所有模块**禁止在生产或现役预测管道中 import**，仅作为考古资产与后续 P7-ALGO-2 重建时的参考代码。

---

## 二、归档内容清单（共 53 个文件）

### 1. `src/` 核心交易与仿真模块（27 个文件）
- **`src/execution/`** (6 个): `clob_client.py`, `execution_engine.py`, `models.py`, `order_router.py`, `residual_risk.py`, `__init__.py`
- **`src/bankroll/`** (5 个): `bankroll_manager.py`, `multinomial_kelly.py`, `risk_limiter.py`, `zombie_evaluator.py`, `__init__.py`
- **`src/risk/`** (6 个): `central_arbiter.py`, `cli.py`, `emergency_control.py`, `incident_protocol.py`, `pre_buy_gate.py`, `two_dimensional_risk.py`
  - *注：`src/risk/__init__.py` 保留原位以维护 Python 包结构，此处不重复放置 `__init__.py`。*
- **`src/pricing/`** (2 个): `ev_engine.py`, `__init__.py`
- **`src/simulation/`** (8 个): `backtest_engine.py`, `clock.py`, `market_maker.py`, `metrics.py`, `models.py`, `paper_engine.py`, `settlement_sim.py`, `__init__.py`

### 2. `tests/` 配套单元测试（20 个文件）
- **`tests/execution/`** (4 个): `test_clob_models_client.py`, `test_execution_engine.py`, `test_order_router.py`, `test_residual_risk.py`
- **`tests/bankroll/`** (4 个): `test_bankroll_manager.py`, `test_multinomial_kelly.py`, `test_risk_limiter.py`, `test_zombie_evaluator.py`
- **`tests/risk/`** (4 个): `test_central_arbiter.py`, `test_emergency_control.py`, `test_incident_protocol.py`, `test_pre_buy_gate.py`
- **`tests/pricing/`** (2 个): `test_ev_engine.py`, `test_w2_asset_governance.py`
- **`tests/simulation/`** (6 个): `test_historical_backtest.py`, `test_paper_engine.py`, `test_paper_runner.py`, `test_sim_metrics.py`, `test_sim_models_clock.py`, `test_synthetic_market_maker.py`

### 3. `scripts/` 交易与仿真脚本（5 个文件）
- **`scripts/`** (5 个):
  - `run_paper_trading.py`
  - `run_historical_backtest.py`
  - `run_p7_w2_shortloop_paper_simulation.py`
  - `run_p7_w2b_48h_observation.py`
  - `audit_p7_w2_shortloop.py`

---

## 三、例外保留清单（严格保留在原位）

为确保现役气象预测流水线零断裂，以下 4 个对象严格保留在主代码树原位：
1. **`src/risk/stream_watchdog.py`**：现役核心流式管道 `src/pipeline/stream_confluence_pipeline.py` 唯一依赖的风控监视器。自身仅依赖 Python 标准库与 `src.data_acquisition.observation_stream`。
2. **`tests/unit/risk/test_stream_watchdog.py`**：`stream_watchdog.py` 的配套单元测试。
3. **`src/risk/__init__.py`**：原位保留原样，确保 `src.risk` 作为 Python 包的完整性。
4. **`scripts/run_backtest.py`**：Phase 1D 气象模型离线回测验证系统，仅依赖 modeling/validation，不依赖交易模块。

---

## 四、引用安全快照与验证结论

归档执行时已执行严格的引用安全验证（全部通过）：
1. **现役核心代码 (`src/`) 引用**：除保留的 `stream_confluence_pipeline.py` -> `src.risk.stream_watchdog` 之外，零命中交易模块引用；
2. **现役单测 (`tests/unit/`) 引用**：零命中任何已归档的交易模块；
3. **全仓现役管道套件**：涵盖 `data_acquisition`, `data_processing`, `modeling`, `prediction`, `validation`, `pipeline`, `stream_watchdog` 的全量单测全部通过（649 passed, 5 skipped, 0 failed）。

---

## 五、恢复与重建指引

后续启动 **P7-ALGO-2《联合凯利与执行定价算法规格书》** 编制与工程落地时：
1. **不进行盲目原样回迁**：必须严格基于《v1 遗产判决书》v0.2 裁定之 M-1~M-8 原则、F-2 优先律以及全新规格书重新设计并实现模块；
2. **参考依据**：本归档区代码仅作为逻辑参照与历史实现对比物。
