# 规格书：Active 10 站生产级概率分布模型重训与三重验收 (Phase 2 Task 01)

- **Spec Issue**: [#59](https://github.com/oasislin/Poly2/issues/59) (Spec: Phase 2 Task 01 - Active 10 站生产级概率分布模型重训与三重验收)
- **Tickets**:
  - `Phase 2 Task 01 - Ticket 01`: [#60](https://github.com/oasislin/Poly2/issues/60) (Frontier)
  - `Phase 2 Task 01 - Ticket 02`: [#61](https://github.com/oasislin/Poly2/issues/61)
  - `Phase 2 Task 01 - Ticket 03`: [#62](https://github.com/oasislin/Poly2/issues/62)
  - `Phase 2 Task 01 - Ticket 04`: [#63](https://github.com/oasislin/Poly2/issues/63)

## 问题陈述 (Problem Statement)

老 Phase 1 阶段训练的 40 组 EMOS 模型参数存在四个不可逾越的致命缺陷：
1. **站点完全脱节**：仅覆盖上海（ZSPD，Polymarket 无此盘口）与丹佛民航（KDEN，真实市场裁决结算于巴克利空军基地 KBKF），当前真实打仗的 Active 10 交易宇宙（KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS）参数覆盖率为零；
2. **数据源严重污染**：基于已被物理隔离的 Wunderground 爬虫脏数据训练，存在 -2°F ~ -5°F 的系统性负偏差与大量整度截断；
3. **方差底设定失效**：旧版 σ_clim 存在严重的摄氏/华氏度混淆，已被 ADR-0010 官方推翻重建；
4. **时效节点僵死硬编码**：硬编码东八区上海的 lead 节点，无法适配美洲 4 个时区以及冬夏令时（DST）带来的 6h 跨桶漂移。

若直接开启 Phase 2 盘口对接与执行引擎，下游的 EV 计算器与多项联合凯利优化器将面临无合法 (μ, σ) 物理先验参数可读的严重夹缝断层。

## 解决方案 (Solution)

以已发布的生产级统一校准数据集 `data/processed/calib-dataset-v2.0/`（Git Tag: phase1.5-final）为物理底座，激活并升级现有的 `TrainingPipeline` 自动化训练流水线：
1. 升级 `MatrixTrainer`，支持 Active 10 站 × 20 节点 = 200 组独立高斯 EMOS 参数的时区自适应矩阵批量并行训练（严格基于 2000–2018 OOS 训练集）；
2. 注入各台站经过 ADR-0010 门禁认证的全新 Climate Floor Parquet 文件（确保强大陆性站点冬季方差上限安全容纳至 15.0°F）；
3. 将收敛优化的 200 组生产级高斯 EMOS 参数完整持久化落盘至 `data/models/`，并同步生成包含 SHA256 校验和的 `manifest.json`；
4. 运行 `ValidationEngine` 在 2019 纯净验证集上执行完整的三重验收门禁（标准节点 CRPS/PIT、自适应留出插值节点精度守恒、极端压力测试），由 `ReportGenerator` 自动产出终验质检报告 `docs/reports/phase2-task01-model-calibration-acceptance-report.md`。

## 用户故事 (User Stories)

1. 作为量化交易员，我希望训练流水线能够全量训练 Active 10 站的 200 组离散本地化 EMOS 模型，以便每个活跃交易市场都具备高精度的客观物理先验概率。
2. 作为系统架构师，我希望每个台站的时效训练节点均由 `select_contained_6h_windows` 根据台站时区与夏令时偏移动态算定，以便彻底消除全美跨时区的时钟漂移。
3. 作为机器学习工程师，我希望训练流水线严格读取 `data/processed/calib-dataset-v2.0/` 并坚决拒绝任何旧版 Wunderground 路径，以便模型参数彻底摆脱系统性负偏差与整度伪影。
4. 作为风控经理，我希望气候学方差底直接读取通过 ADR-0010 验证（≤15.0°F 物理上限）的 2000–2018 IEM 真实方差 Parquet，以便内陆站点严冬的真实极涡方差不被粗暴截断。
5. 作为系统操作员，我希望优化器使用基于平方参数化（天然非负方差保障）的 L-BFGS-B 与 CRPS 闭式解析解，以便所有模型均能高确定性收敛且杜绝数值崩溃。
6. 作为量化开发人员，我希望所有训练好的模型参数按照 `(台站, 季节, 气温变量, 预测时效)` 的标准格式序列化存储至 `data/models/`，并附带防篡改的 `manifest.json`，以便 Phase 2 的 EV 计算器能在盘中秒级读取受信的物理先验。
7. 作为合规审计员，我希望严格遵循时间墙数据隔离纪律（2000–2018 严格用于训练与方差底构建，2019 严格保留用于验证），以便绝不发生样本外数据穿越泄露。
8. 作为质检工程师，我希望标准训练节点严格断言 `CRPS_model < CRPS_clim` 且 PIT K-S 均匀性检验 `p > 0.05`，以便在数学上确凿证明模型相较于气候学具有显著的预测技巧。
9. 作为风控审计员，我希望在自适应中位留出节点上重建的虚拟插值模型严格断言 `CRPS_virtual ≤ 1.05 * CRPS_real`，以便验证 6h 稠密线性插值的保真度与精度守恒。
10. 作为首席风控官，我希望 2019 验证集上的极端尾部样本（10th/90th 分位点）必须满足 `CRPS_model < CRPS_clim` 且 90% 置信区间覆盖率 ≥80%，以便极端寒潮或热浪等极端天气尾部风险不会导致穿仓。
11. 作为运维负责人，我希望系统自动生成详尽的 Markdown 验收报告，清晰汇总所有门禁的通过状态与模型矩阵记分卡，以便团队无条件签署并放行 Phase 2 盘口实时定价。

## 实现决策 (Implementation Decisions)

- **架构接缝 (Architecture Seam)**：核心业务与测试的主接缝确立为 `src/modeling/pipeline.py` 中的 `TrainingPipeline.run()` 及其 CLI 入口 `python -m src.modeling.pipeline`。
- **数据集消费 (Dataset Consumption)**：数据直接从 `data/processed/calib-dataset-v2.0/features/` 与 `climate_floor/` 读取，经 `DatasetPartitioner` 将长表 Parquet 切片对齐分发至训练分区。
- **自适应矩阵升级 (Adaptive Matrix Upgrade)**：`MatrixTrainer` 从原先硬编码的 2 站（40 模型）升级为动态 10 站（200 模型），训练节点由 `select_contained_6h_windows(station_id, target_date)` 动态计算。
- **降级保护策略 (Degradation Policy Enforcement)**：优化器超迭代未收敛或违反参数容差的模型，自动触发 Level 2 气候学硬降级，并在 `MatrixScorecard` 中明确记录降级标志与原因。
- **产物持久化规范 (Artifact Output)**：序列化参数存入 `data/models/emos/{station}/{variable}_{season}_{lead}h.json`，根目录生成 `data/models/manifest.json` 固化版本元数据与数据校验和。
- **验收报告产出 (Acceptance Report)**：由 `ReportGenerator` 自动渲染并保存至 `docs/reports/phase2-task01-model-calibration-acceptance-report.md`。

## 测试决策 (Testing Decisions)

- **单一主接缝测试 (Single Primary Seam Testing)**：集成测试通过调用 `TrainingPipeline` 传入测试夹具（覆盖 2 站、2 季节、极值时效节点），验证从特征加载、矩阵优化、插值到报告生成的端到端全链路。
- **契约与回归测试 (Contract & Regression Tests)**：单元测试严格断言平方参数化方差的绝对非负性、CRPS 闭式梯度正确性以及 PIT 统计校准分布。
- **全量验收门禁测试 (Full Acceptance Gate)**：设置专用的 CLI 冒烟与终验测试，断言在全量 `calib-dataset-v2.0` 上运行流水线退出码为 0，且产出的报告中三重验收指标全部为 `PASS`。

## 范围外声明 (Out of Scope)

- Polymarket 实时订单簿推送接收与 WebSocket 盘口监听（属于 Task 02/04 范畴）。
- 实时下单路由、多项联合凯利优化求解与资金状态机扣减（属于 Task 05/06 范畴）。
- 任何旧版 Wunderground 数据的重训或旧版已隔离数据的迁移。
- 非气温类气象变量（降水、风速等）。

## 补充说明 (Further Notes)

- 本任务项（Task 01）的验收闭环是彻底解锁 Phase 2 下游所有盘口定价与执行模块的唯一先决条件。
- 对 `src/modeling/` 模块的所有代码调整必须严格遵守现有的 ADR-0008、ADR-0010 与 ADR-0011 架构标准。
