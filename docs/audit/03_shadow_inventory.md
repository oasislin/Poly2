# 工单 P7-DOC-RECON-2-R2：任务 3 · 影子清单报告

**执行工单**：`P7-DOC-RECON-2-R2`  
**审计性质**：影子资产盘点（存在于代码/会话报告/分支提交中，但未被法定 ROADMAP.md 正式纳管的构件）  
**执行基准**：Git Commit HEAD = `ea72141e298d56a1f4f2d0de3e5ce41cda859d66`（分支 `fix/p7-w2-shortloop`）  
**执行时间**：2026-10-12  
**执行原则**：仅做枚举与建议处置，**绝对不执行任何删除、修改或移动操作**。

---

## 一、 影子构件总览表

| 构件类别 | 构件物理路径 / 标识 | 代码库客观存在形态 | ROADMAP.md 法定状态 | 偏离定性 | 建议处置 |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **1. 伪 W3 交易侧构件群** | `src/pricing/paper_evaluation_engine.py`<br>`src/prediction/real_emos_pipeline.py`<br>`src/data_acquisition/polymarket_clob_collector.py`<br>`src/pricing/w3_offline_replay_analyzer.py`<br>`scripts/run_w3_clob_snapshot_batch.py`<br>`docs/w3_*.md` (预注册/Annex A) | 存在于代码与分支提交 `ea72141` | ROADMAP 中 W3 仅指“8 站原型筛查与 TMin 审计”，无此类任务 | **概念劫持与超前开发** | **归档 (Archive)** |
| **2. Phase 2 完整交易执行模块** | `src/execution/execution_engine.py`<br>`src/execution/order_router.py`<br>`src/execution/clob_client.py`<br>`src/execution/residual_risk.py` | 存在，且拥有完整单测 | ROADMAP 声称“Phase 2 交易完成度 0.0%”，Task 06 顺延 | **资产在库但文档漏记** | **保留 (Retain)** |
| **3. Phase 2 资金与凯利模块** | `src/bankroll/bankroll_manager.py`<br>`src/bankroll/multinomial_kelly.py`<br>`src/bankroll/risk_limiter.py`<br>`src/bankroll/zombie_evaluator.py` | 存在，测试全绿 | ROADMAP 声称“完成度 0.0%”，Task 05 顺延至实盘前置 | **资产在库但文档漏记** | **保留 (Retain)** |
| **4. Phase 2 异常中枢与风控模块** | `src/risk/central_arbiter.py`<br>`src/risk/emergency_control.py`<br>`src/risk/incident_protocol.py`<br>`src/risk/stream_watchdog.py`<br>`src/risk/two_dimensional_risk.py` | 存在，测试全绿 | ROADMAP 声称“完成度 0.0%”，Task 03 顺延至实盘前置 | **资产在库但文档漏记** | **保留 (Retain)** |
| **5. 模拟与撮合引擎模块** | `src/simulation/paper_engine.py`<br>`src/simulation/backtest_engine.py`<br>`src/simulation/market_maker.py`<br>`src/simulation/settlement_sim.py` | 存在，测试全绿 | ROADMAP 声称“完成度 0.0%”，Task 07 重定义为只读纸面盘 | **资产在库但文档漏记** | **保留 (Retain)** |
| **6. 未入入册的法定 ADR 资产** | `docs/adr/ADR-0017-*.md`<br>`docs/adr/ADR-0018-*.md` | 物理存在，通过代码测试检验 | README 与 ROADMAP 仅登记 ADR-0001~0014 | **法定资产登记遗漏** | **保留并确权 (Retain)** |
| **7. 重名分叉的 ADR 资产** | `docs/adr/ADR-0015.md`<br>`docs/adr/ADR-0015：废除高斯EMOS...md` | 双文件并存，内容版本分叉 | 无据可查（未在任何目录清单解释双文件原因） | **文件冗余与版本漂移** | **合并整理 (Consolidate)** |
| **8. 废弃的 Wunderground 爬虫脚本** | `src/data_acquisition/wunderground_scraper*.py`<br>`mock_wunderground.py`<br>`wunderground_scraper.log` | 物理遗留在生产源码目录 | ADR-0007 已废除，数据已隔离至 legacy 目录 | **陈旧代码污染生产区** | **归档隔离 (Archive)** |
| **9. 分支私跑的 48h 观测工件** | `scripts/run_p7_w2b_48h_observation.py`<br>`evidence/p7_w2b_48h_observation_report.md`<br>`evidence/p7_w2_final_sealing_report.md` | 提交在 `fix/p7-w2-shortloop`，未合入 main | ROADMAP 中 W2 纸面盘声明尚未就绪（待审批预注册） | **分支超前执行未合流** | **保留待审 (Retain)** |

---

## 二、 重点构件下钻分析与处置建议

### 1. 伪“Wave 3”交易侧构件（严重偏离案）
- **客观事实**：  
  在分支 `fix/p7-w2-shortloop` 的提交历史中，自 Commit `1f6f75e` 至 `ea72141`，连续产生了以“W3-TASK1”、“W3-TASK2”、“W3-TASK3”命名的代码与预注册规范（涉 CLOB 数据采集、纸面评估引擎、RealEMOSPipeline、离线回放器等）。  
- **冲突焦点**：  
  法定 `docs/ROADMAP.md` §3.3 明确规定：**W3 = 8 站原型筛查 (`P7-STA-SURVEY`) + TMin 480 格审计规划 (`P6-TMIN-CV-LOCK`)**，纯属气象侧横向扩展。分支上的开发私自将“Wave 3”重新定义为交易侧功能，导致路线图与实际分支提交命名发生严重混乱。  
- **建议处置**：**归档 (Archive)**  
  不合并入 main；将其重命名或归档为 `archive/trading_offline_replay/`，待用户正式对 W2 纸面盘结项、并明确交易侧下一步规划后再行解冻调用。

### 2. Phase 2 完整交易侧基础设施（资产漏记案）
- **客观事实**：  
  `src/execution/`（执行引擎、IOC 保护路由、残局自愈）、`src/bankroll/`（四桶资金、多项联合凯利、僵尸仓位）、`src/risk/`（统一仲裁中枢、紧急拔网线、两维阶梯风控）在客观上已经完全实现，并在 `tests/` 下有 200 余项单测与集成测试护航。  
- **冲突焦点**：  
  `docs/ROADMAP.md` §1 第 18 行作出了“完成度为 0.0%”的虚假断言，误导后续维护者认为必须从零写起。  
- **建议处置**：**保留并合规入册 (Retain & Reconcile)**  
  坚决保留现有代码资产；建议在后续文档修订中如实记载这些模块的客观完备度，仅将其标为“待实盘真实连线与鉴权”，避免推倒重写的巨大浪费。

### 3. ADR-0017 / 0018 及 ADR-0015 分叉（架构治理案）
- **客观事实**：  
  `ADR-0017`（ECE 统计口径规范）与 `ADR-0018`（分级校准门禁）在代码库中发挥着核心门禁规范作用，但在全局索引与 README 中被隐匿（仅写 ADR-0001~0014）；`ADR-0015` 存在两个物理文件，英文短文件名版多出 15 行关于方差地板实证与旧金山 $d=0$ 的物理成因。  
- **建议处置**：**保留并整理 (Retain & Consolidate)**  
  将 ADR-0017 与 ADR-0018 补登入法定 ADR 清单；将 `ADR-0015.md` 的增补内容合并至中文标准命名的文档中，归档短名文件。

### 4. 废弃 Wunderground 采集脚本（源码卫生案）
- **客观事实**：  
  `src/data_acquisition/` 目录下仍存留 `wunderground_scraper.py`、`wunderground_scraper_enhanced.py`、`mock_wunderground.py` 及日志文件。  
- **冲突焦点**：  
  `ADR-0007` 早已废除 Wunderground 作为数据源，生产代码不应再依赖这些模块。  
- **建议处置**：**归档隔离 (Archive to Legacy)**  
  将这些脚本整体迁移至 `data/legacy-v1-suspect/scripts/`，保持生产目录清洁。
