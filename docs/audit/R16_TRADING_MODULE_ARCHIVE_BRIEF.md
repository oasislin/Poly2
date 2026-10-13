# R-16 交易模块整体归档清单（R16_TRADING_MODULE_ARCHIVE_BRIEF）

> **版本**：v1.0
> **日期**：2026-10-13
> **编制**：技术审核 Agent（基于线上 main 树 + 本地同步层实测 + 引用安全检查）
> **执行位置**：git 工作副本机器（开发环境 Agent）
> **上游依据**：用户裁决 R-16 **方案 B**（交易模块整体归档、免依赖排查，仅归档时做最小引用安全检查防破坏）；《REMEDIATION_PLAN.md》v1.2
> **授权范围**：本清单所列 git mv / 验证 / push 操作；清单之外不得触碰。

---

## 一、归档背景与裁决

- 现状：`src/execution`、`src/bankroll`、`src/risk`、`src/pricing`、`src/simulation` 五个交易侧模块在 main 树中客观存在（含对应 tests），但用户裁决：交易引擎开发未获执行授权，"交易引擎完成度 0.0%"断言无效，应废止/终止。
- 处置：**整体归档至隔离区**（`docs/archive/trading_modules/`），撤销完成度断言，改为 **"已归档，待 P7-ALGO-2（《联合凯利与执行定价算法规格书》）重建"**。
- 免依赖排查，但归档时做**最小引用安全检查**（本清单已代执行完毕，见 §五 结果），确保归档后现役代码零断裂。

## 二、归档对象清单（53 个文件，git mv）

### 2.1 `src/` 交易模块（28 个文件 → `docs/archive/trading_modules/src/`）

| 源路径 | 文件 |
| :--- | :--- |
| `src/execution/` | `clob_client.py` `execution_engine.py` `models.py` `order_router.py` `residual_risk.py` `__init__.py` |
| `src/bankroll/` | `bankroll_manager.py` `multinomial_kelly.py` `risk_limiter.py` `zombie_evaluator.py` `__init__.py` |
| `src/risk/`（6 个） | `central_arbiter.py` `cli.py` `emergency_control.py` `incident_protocol.py` `pre_buy_gate.py` `two_dimensional_risk.py` |
| `src/pricing/` | `ev_engine.py` `__init__.py` |
| `src/simulation/` | `backtest_engine.py` `clock.py` `market_maker.py` `metrics.py` `models.py` `paper_engine.py` `settlement_sim.py` `__init__.py` |

> 注：`src/risk/__init__.py` **保留原位**（现役包完整性，见 §三）；`__pycache__/` 为本地缓存，git 不跟踪，无需处理（本地可留待系统清理）。

### 2.2 `tests/unit/` 交易模块测试（20 个文件 → `docs/archive/trading_modules/tests/`）

| 源路径 | 文件 |
| :--- | :--- |
| `tests/unit/execution/` | `test_clob_models_client.py` `test_execution_engine.py` `test_order_router.py` `test_residual_risk.py` |
| `tests/unit/bankroll/` | `test_bankroll_manager.py` `test_multinomial_kelly.py` `test_risk_limiter.py` `test_zombie_evaluator.py` |
| `tests/unit/risk/`（4 个） | `test_central_arbiter.py` `test_emergency_control.py` `test_incident_protocol.py` `test_pre_buy_gate.py` |
| `tests/unit/pricing/` | `test_ev_engine.py` `test_w2_asset_governance.py` |
| `tests/unit/simulation/` | `test_historical_backtest.py` `test_paper_engine.py` `test_paper_runner.py` `test_sim_metrics.py` `test_sim_models_clock.py` `test_synthetic_market_maker.py` |

### 2.3 `scripts/` 交易相关脚本（5 个文件 → `docs/archive/trading_modules/scripts/`）

| 源路径 | 文件 | 理由 |
| :--- | :--- | :--- |
| `scripts/` | `run_paper_trading.py` | 引用 bankroll/execution/pricing/risk/simulation |
| `scripts/` | `run_historical_backtest.py` | 引用 simulation.backtest_engine |
| `scripts/` | `run_p7_w2_shortloop_paper_simulation.py` | 引用 bankroll/execution/pricing（且 import 已删除的 `paper_evaluation_engine`，当前即为断裂引用） |
| `scripts/` | `run_p7_w2b_48h_observation.py` | 引用 pricing/risk/simulation |
| `scripts/` | `audit_p7_w2_shortloop.py` | 引用 pricing/risk |

## 三、例外保留清单（归档后现役代码零断裂的关键）

| 保留对象 | 保留理由（引用安全检查实证） |
| :--- | :--- |
| `src/risk/stream_watchdog.py` | 现役数据管道 `src/pipeline/stream_confluence_pipeline.py`（W2 白名单合流资产）`from src.risk.stream_watchdog import RiskStatus, StreamRiskWatchdog`——唯一现役模块对交易模块的引用；该文件自身仅依赖标准库 + 现役 `src.data_acquisition.observation_stream`，保留安全 |
| `tests/unit/risk/test_stream_watchdog.py` | stream_watchdog 的配套测试 |
| `src/risk/__init__.py` | 原位保留原样（保证 `src.risk` 包完整性），归档区 `src/risk/` 缺 `__init__.py` 属正常（存档参照性质） |
| `scripts/run_backtest.py` | Phase 1D 验证系统（引用 modeling/validation），**不引用**交易模块，不归档 |

## 四、目标归档结构与 git 操作

```text
docs/archive/trading_modules/
├── README.md            ← 归档说明（新建，见 §六）
├── src/
│   ├── execution/  bankroll/  pricing/  simulation/
│   └── risk/        （6 个文件，无 __init__，README 注明）
├── tests/
│   ├── execution/  bankroll/  pricing/  simulation/
│   └── risk/        （4 个文件）
└── scripts/        （5 个脚本）
```

### 4.1 推荐命令序列（方法：git mv 分组提交，一次 push）

```bash
git fetch origin && git checkout main && git pull origin main

# ① src/ 交易模块
git mv src/execution docs/archive/trading_modules/src/execution
git mv src/bankroll  docs/archive/trading_modules/src/bankroll
git mv src/risk/central_arbiter.py src/risk/cli.py src/risk/emergency_control.py \
        src/risk/incident_protocol.py src/risk/pre_buy_gate.py src/risk/two_dimensional_risk.py \
        docs/archive/trading_modules/src/risk/
git mv src/pricing   docs/archive/trading_modules/src/pricing
git mv src/simulation docs/archive/trading_modules/src/simulation

# ② tests/unit/
git mv tests/unit/execution docs/archive/trading_modules/tests/execution
git mv tests/unit/bankroll  docs/archive/trading_modules/tests/bankroll
git mv tests/unit/risk/test_central_arbiter.py tests/unit/risk/test_emergency_control.py \
        tests/unit/risk/test_incident_protocol.py tests/unit/risk/test_pre_buy_gate.py \
        docs/archive/trading_modules/tests/risk/
git mv tests/unit/pricing   docs/archive/trading_modules/tests/pricing
git mv tests/unit/simulation docs/archive/trading_modules/tests/simulation

# ③ scripts/
git mv scripts/run_paper_trading.py scripts/run_historical_backtest.py \
        scripts/run_p7_w2_shortloop_paper_simulation.py scripts/run_p7_w2b_48h_observation.py \
        scripts/audit_p7_w2_shortloop.py docs/archive/trading_modules/scripts/

# ④ 归档 README（§六 内容）
# ⑤ 提交 + push
git add -A
git commit -m "chore(archive): R-16 交易模块整体归档至 docs/archive/trading_modules（保留 stream_watchdog 现役依赖，撤销交易引擎完成度断言）"
git push origin main
```

## 五、最小引用安全检查结果（已代执行，归档前复核）

| 检查项 | 结果 |
| :--- | :--- |
| `src/` 现役代码 import 交易模块 | 仅 `src/pipeline/stream_confluence_pipeline.py` → `src.risk.stream_watchdog`（例外保留解决） |
| `src/` 交易模块内部互引 | 51 处互引全部随模块一起归档（同批移动，无悬挂） |
| `tests/` 非交易目录引用 | 零命中 |
| `conftest.py` / `pyproject.toml` / `requirements.txt` | 零命中 |
| `scripts/` 引用交易模块 | 5 个脚本（§2.3 归档）；`run_backtest.py` 不引用（保留） |

**归档后验证（执行 Agent 必跑）**：
1. `git grep -E "from src\.(execution|bankroll|pricing|simulation)" src/` → 空
2. `git grep "src\.risk" src/` → 仅命中 `stream_confluence_pipeline.py`（保留引用）
3. `git grep -E "from src\.(execution|bankroll|pricing|simulation)" tests/` → 空（交易 tests 已移走）
4. `python -m pytest tests/unit/data_acquisition tests/unit/data_processing tests/unit/modeling tests/unit/prediction tests/unit/validation -q` → 现役管道模块全绿（不涉及交易模块）
5. `git status` → 干净

## 六、归档 README.md 必含内容

1. **归档声明**：R-16 用户裁决 B，交易模块整体归档（2026-10-13），撤销"交易引擎完成度 0.0%"断言，改为 **"已归档，待 P7-ALGO-2 重建"**；
2. **归档范围**：src/（28）、tests/（20）、scripts/（5）共 53 文件 + 本 README；
3. **例外保留说明**：`src/risk/stream_watchdog.py`（+ test）因现役管道依赖保留于原树；
4. **恢复指引**：P7-ALGO-2 重建时从此目录恢复并重新设计，不做原样回迁；
5. **引用关系快照**：§五 检查结果存档；
6. **同步治理**：更新 `docs/audit/DECISION_LEDGER.md`（登记 R-16 归档）、`docs/REMEDIATION_PLAN.md`（R-16 状态 → 已完成）。

## 七、交付物清单（执行完成后提供）

| # | 交付物 | 内容要求 |
| :--- | :--- | :--- |
| 1 | 执行报告 | 命令 + 原始输出末尾 + 判定两步分离（格式同 BATCH1 报告） |
| 2 | 归档验证输出 | §五 5 项验证命令的原始输出 |
| 3 | `git log --oneline -5 main` | 归档提交记录 |
| 4 | 归档 README 副本 | `docs/archive/trading_modules/README.md` |
| 5 | 线上确认 | push 后 main HEAD + 归档目录 URL |
| 6 | 治理文档更新 | DECISION_LEDGER 登记、Plan v1.2 R-16 状态行 |

## 八、纪律红线

1. **push 仅限本清单内容**，且需用户最终确认（沿用既往约定）；
2. 不删除任何文件（一律 git mv，历史保留）；
3. `stream_watchdog.py` / `run_backtest.py` 不得误移（例外清单受保护）；
4. 原始观测原样汇报；"通过"必须附命令与输出证据；
5. 执行中发现归档对象与清单不符，停止回报，不得自行扩展范围。
