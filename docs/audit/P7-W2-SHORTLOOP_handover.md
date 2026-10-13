# 工单 P7-W2-SHORTLOOP-R1 完工交接包 (Handover Package)

**工单编号**：`P7-W2-SHORTLOOP-R1`  
**工单性质**：交易侧短闭环（W2）——纸面盘端到端跑通与首份人类可读模型体检报告  
**开工基准**：Git Commit HEAD = `ea72141e298d56a1f4f2d0de3e5ce41cda859d66`（分支 `fix/p7-w2-shortloop`）  
**开工全量测试基线**：`pytest -q` 输出 `1062 passed, 10 skipped, 3 warnings in 635.30s (exit code 0)`  
**完工全量测试终审**：`pytest -q` 输出 `1068 passed, 10 skipped, 3 warnings in 627.61s (exit code 0)`（净增 6 项通过测试，零失败、零退化）  
**执行原则**：零真实资金、零真实下单；Active 10 单一事实源驱动加载；双旗约束（KMIA 12h 惩罚收缩 0.5x，禁单向加仓）；判定两步分离、原始数据不可篡改。

---

## 一、 工单任务完成情况与验收证据索引

| 任务项 | 改造与产出核心内容 | 关键工件路径 | 实际执行验证命令与证据 | 状态 |
| :--- | :--- | :--- | :--- | :---: |
| **前置门禁** | 确认前序溯源报告存在且结论固定；获取开工 HEAD 与全量 pytest 基线 | `docs/audit/P7-PROV-1_provenance.md` | `git rev-parse HEAD`<br>`pytest -q` (1062 passed, 10 skipped) | ✅ 通过 |
| **四维门禁预注册** | 锁死校准 ECE、预测偏差 Bias、CRPS 技巧分、90% 区间覆盖率绿/黄/红阈值矩阵与短板定级规则 | [`docs/MODEL_SCORECARD.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/MODEL_SCORECARD.md) | 阈值落盘即刻锁定，禁止运行期动态修饰 | ✅ 通过 |
| **任务 1: CLOB 采集器改造** | 彻底移除硬编码城市台站字典；动态从 `ACTIVE_10_STATIONS` 与 `STATION_METADATA` 加载；修复达拉斯与休斯敦错配，清除 KBKF、EGLL；加入清单外站点抛错拦截 | [`src/data_acquisition/polymarket_clob_collector.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_acquisition/polymarket_clob_collector.py) | `pytest tests/unit/data_acquisition/test_polymarket_clob_collector.py -v`<br>14 passed (覆盖清单驱动加载与非法站点拒绝) | ✅ 通过 |
| **任务 2: 纸面盘评估引擎改造** | 补齐模型体检等级头寸惩罚（Green 1.0x, Yellow 0.5x, Red 0.0x 禁开）；串联日内 SPECI 动态截断层（淘汰死档归零、存活档位单纯形重新定价） | [`src/pricing/paper_evaluation_engine.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pricing/paper_evaluation_engine.py) | `pytest tests/unit/pricing/test_paper_evaluation_engine.py -v`<br>11 passed (覆盖正常结算、SPECI截断、黄级减半、红级阻断) | ✅ 通过 |
| **任务 3: 端到端短闭环联调** | KORD TMax（绿级 1.0x）与 KMIA TMax 12h（黄级 0.5x 带旗）各构造完整纸面周期（预测入参 $\to$ 定价 $\to$ 模拟挂单 $\to$ 模拟成交 $\to$ 次日结算评估），全链路结构化日志落盘 | [`scripts/run_p7_w2_shortloop_paper_simulation.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/run_p7_w2_shortloop_paper_simulation.py)<br>[`data/paper_trading/records/`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/data/paper_trading/records/) | `PYTHONPATH=. python scripts/run_p7_w2_shortloop_paper_simulation.py`<br>生成 `kord_tmax_shortloop_record.json`<br>`kmia_tmax_12h_shortloop_record.json` | ✅ 通过 |
| **任务 4: 模型体检报告** | 按四维预注册体系对 Active 10 逐站逐标的定级，输出人类可读四维明细表与逐站固定模板结论 | [`docs/audit/p7_w2_model_health_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/audit/p7_w2_model_health_report.md) | 只读 P6 封卷数据与底账，KORD/KMIA 已确权入役，其余 8 站 TMax 及 10 站 TMin 维持红级禁投 | ✅ 通过 |
| **任务 5: 文档同步与阻断门禁** | 修订 ROADMAP 勘误既往“完成度 0.0%”陈述为实际确权状态，登记本工单交付；在开发指南中新增合流 PR 必须同步更新 ROADMAP/STATUS 阻断门禁 | [`docs/ROADMAP.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/ROADMAP.md)<br>[`DEVELOPER_GUIDELINES.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/DEVELOPER_GUIDELINES.md) | 完成文档版本与合流检查单更新 | ✅ 通过 |

---

## 二、 遗留问题与已知技术债清单

1. **KMIA 12h 晨谷相位加权 ECE 越线历史旗（运行旗 2）**：
   - 现役加权 ECE 录得 0.018318（黄级），在实盘前需等待 W1（`P6-POOL-PHASE` 6h 池化分层重训与衰减公式补全）完成重训检验并由委员会审定拔旗。
2. **其余 8 站 TMax 与全量 10 站 TMin 审计空白（维持红级禁投）**：
   - 当前资产库仅 KORD 与 KMIA 具备 20 折 Block-CV 独立选型法定凭证；其余 8 站需在 W3 启动轻量三原型筛查（`P7-STA-SURVEY`），TMin 需执行 480 格全网格解锁审计（`P6-TMIN-CV-LOCK`）。
3. **真实网络环境与 CLOB WSS 生产订阅**：
   - 本次联调严格遵守“零真实资金、零私钥接触”铁律，走本地虚拟撮合与 Read-Only 快照；进入 Phase 3 实盘前需打通真实 Polymarket ClobClient 签名及订单生命周期追踪。

---

## 三、 待用户裁决事项清单 (编号单句)

1. **裁决项 1**：是否批准将 W2 交易短闭环核心代码（`polymarket_clob_collector.py` 与 `paper_evaluation_engine.py`）正式合流合并入主干？
2. **裁决项 2**：是否同意启动 W2 纸面盘 48 小时持续观测运行期，并在观测期间并行激活 W3（8 站轻量三原型筛查 `P7-STA-SURVEY` 与 TMin 480 格审计规划 `P6-TMIN-CV-LOCK`）？
3. **裁决项 3**：是否维持 KMIA 12h 的黄级 0.5x 仓位惩罚与单向加仓禁令，直至 W1 基础设施完成昼夜相位重训？
