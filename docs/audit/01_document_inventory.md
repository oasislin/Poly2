# 工单 P7-DOC-RECON-2-R2：任务 1 · 文档盘点报告

**执行工单**：`P7-DOC-RECON-2-R2`  
**审计性质**：只读取证、法定文档资产存在性盘点与缺项登记  
**执行基准**：Git Commit HEAD = `ea72141e298d56a1f4f2d0de3e5ce41cda859d66`（分支 `fix/p7-w2-shortloop`）  
**执行时间**：2026-10-12  

---

## 一、 核心法定文档存在性核验表

依据工单任务 1 检查清单，使用 `git ls-files` 及文件系统状态进行逐一核验：

| 序号 | 目标文档路径 | Git 跟踪状态 | 物理文件状态 | 文件行数 / 字节数 | 校验结论 | 备注 / 核心定位 |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| 1 | `STATUS.md` | 存在 (Tracked) | 存在 | 33 行 / 4,730 B | **PASS** | 项目唯一最高状态入口（更新至 2026-10-10 20:55） |
| 2 | `docs/ROADMAP.md` | 存在 (Tracked) | 存在 | 157 行 / 13,907 B | **PASS** | 项目长线战略规划法定准绳（三波次路线图） |
| 3 | `docs/HANDOVER_P7.md` | 存在 (Tracked) | 存在 | 58 行 / 4,402 B | **PASS** | 新会话冷启动唯一交接引导包 (Handover Package) |
| 4 | `docs/SEALING_GATE.md` | 存在 (Tracked) | 存在 | 43 行 / 7,714 B | **PASS** | 双城封盘九项门禁总清单 |
| 5 | `docs/SYNC_POLICY.md` | 存在 (Tracked) | 存在 | 108 行 / 7,215 B | **PASS** | 受控出域通道与证据同步政策 (v1.0.1) |
| 6 | `evidence/p6_tmax_methodology_closure.md` | 存在 (Tracked) | 存在 | 149 行 / 18,153 B | **PASS** | Phase 6 双城 TMax 全网格验证与方法论封盘法定报告 |
| 7 | `evidence/p6_window_forensic_report.md` | 存在 (Tracked) | 存在 | 148 行 / 9,852 B | **PASS** | 生产评估窗口法医穿透取证报告（样本量与 Airgap） |

---

## 二、 `docs/adr/` 全目录清单核验与缺项登记

通过 `git ls-files docs/adr/` 提取，当前仓库中共有 18 份 ADR 文件：

| 序号 | 文件名 | 标题 / 裁决核心 | 状态 | 异常 / 缺项注记 |
| :---: | :--- | :--- | :---: | :--- |
| 1 | `docs/adr/0001-gaussian-emos-with-variance-floor.md` | 高斯 EMOS 基础模型与方差下限托底 | Accepted | 早期编号格式 |
| 2 | `docs/adr/0002-five-lead-time-nodes-with-interpolation.md` | 5 个提前期主节点与三次样条插值 | Accepted | 早期编号格式 |
| 3 | `docs/adr/0003-two-level-degradation.md` | 两级降级保护机制 | Accepted | 早期编号格式 |
| 4 | `docs/adr/0004-five-member-strict-alignment.md` | GEFS 5 成员严格时序对齐 | Accepted | 早期编号格式 |
| 5 | `docs/adr/0005-grib-merge-coordinate-tolerance.md` | GRIB2 合并坐标公差容忍度 | Accepted | 早期编号格式 |
| 6 | `docs/adr/0006-discrete-bin-probability-vs-cumulative-tail.md` | 离散档位区间概率 vs 累积尾部概率 | Accepted | 早期编号格式 |
| 7 | `docs/adr/ADR-0007：数据源重铸与站点宇宙扩展（M0'  Round 5 综合裁决）.md` | 废除 Wunderground，确立 GHCN/IEM/WRH 与 Active 10 | Accepted | 标准全称格式 |
| 8 | `docs/adr/ADR-0008：GEFS 再预报全池采购、源文件冷归档与时区自适应（GEFS-WI-v1.1 综合裁决）.md` | GEFS 7305 日全池冷归档与时区自适应 | Accepted | 标准全称格式 |
| 9 | `docs/adr/ADR-0009：芝加哥 08-31 特报（SPECI）结算语义裁决与截断层规则.md` | 特报结算效力与截断规则 | Accepted | 标准全称格式 |
| 10 | `docs/adr/ADR-0010：气候学方差门禁物理上限（15.0°F）标定与衍生推导规范.md` | 气候学方差上限 15.0°F 门禁 | Accepted | 标准全称格式 |
| 11 | `docs/adr/ADR-0011：双源单调合流架构、TMAX-TMIN对称截断与两维阶梯风控裁决.md` | 双源单调合流、对称截断与两维风控 | Accepted | 标准全称格式 |
| 12 | `docs/adr/ADR-0012：法定结算真值源（NWS WRH）、僵尸仓位双轨估值与舍入闭环裁决.md` | NWS WRH 时序表法定地位、僵尸双轨与 Decimal 舍入 | Accepted | 标准全称格式 |
| 13 | `docs/adr/ADR-0013：特报高频截断与异常安全阻断裁决.md` | SPECI 纯温三道门禁、迟到不投与安全阻断 | Accepted | 标准全称格式 |
| 14 | `docs/adr/ADR-0014：统一异常仲裁中枢与台站级安全挂起协议（架构原则与站位）.md` | CentralExceptionArbiter 统一中枢与本地拔网线 | Accepted | 标准全称格式 |
| 15 | `docs/adr/ADR-0015.md` | 废除气候方差加法项、确立物理方差底座（含 §3 方差地板实证与 KSFO d=0 成因） | Accepted | **文件重名/分叉（见下方缺项注记）** |
| 16 | `docs/adr/ADR-0015：废除高斯EMOS气候方差加法项、确立物理方差底座与离散校准门禁.md` | 废除气候方差加法项、确立物理方差底座与离散校准门禁 | Accepted | **文件重名/分叉（见下方缺项注记）** |
| 17 | `docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md` | ECE 统计口径规范、尖锐度概念纠偏与双层门禁仲裁 | Approved | 引用了缺失的 ADR-0016 |
| 18 | `docs/adr/ADR-0018-reliability-gate-hierarchical-calibration.md` | 可靠度门禁多层分级校准与 S1~S5 阶梯 | Approved | 最新门禁立法 |

### ADR 缺项与异常登记
1. **【严重缺项】`ADR-0016` 物理缺失**：
   - 证据：在 `docs/adr/ADR-0017-ECE-Metric-Specification-and-Gate-Arbitration.md` 第 6 行显式引用：`- 关联文档: ADR-0015（离散校准门禁）、ADR-0016（GHCN-Daily 法定真值基线）`。
   - 现状：经 `git ls-files` 与磁盘全局扫描，全库不存在任何名为 `ADR-0016` 或匹配 `*0016*` 的 ADR 文件。
   - 登记：**无据可查（文件缺失）**。
2. **【文件冗余与版本分叉】`ADR-0015` 双文件并存**：
   - `docs/adr/ADR-0015.md`（71 行）与 `docs/adr/ADR-0015：废除高斯EMOS气候方差加法项、确立物理方差底座与离散校准门禁.md`（56 行）并存；
   - 差异比对：英文短文件名版本比中文长文件名版本多出 `## 3. 第二轮修复令增补：方差地板实证回归与 KSFO d=0 物理成因 (R-3 令归档)` 章节（15 行）。

---

## 三、 `docs/项目方案和执行文档/` 全目录清单核验

当前目录共持有 24 份法定文档（均在 Git 跟踪且物理存在）：

### 3.1 顶层业务方案谱系（全量 8 份）
1. `docs/项目方案和执行文档/项目方案：Polymarket 温度市场量化投注系统 (v2.2).md`
2. `docs/项目方案和执行文档/项目方案：Polymarket 温度市场量化投注系统 (v2.3).md`
3. `docs/项目方案和执行文档/Polymarket 温度市场量化投注系统 (v2.3).md`（根名重名冗余）
4. `docs/项目方案和执行文档/项目方案：Polymarket 温度市场量化投注系统 (v2.4 Final).md`
5. `docs/项目方案和执行文档/项目方案 (v2.4.1)：Polymarket 温度市场量化投注系统.md`
6. `docs/项目方案和执行文档/项目方案 (v2.5)：Polymarket 温度市场量化投注系统.md`
7. `docs/项目方案和执行文档/项目方案 (v2.6)：Polymarket 温度市场量化投注系统.md`
8. `docs/项目方案和执行文档/项目方案 (v2.7)：Polymarket 温度市场量化投注系统.md`
9. `docs/项目方案和执行文档/项目方案 (v2.8)：Polymarket 温度市场量化投注系统.md`（**当前最高宪法版本，PASS**）

### 3.2 阶段执行文件谱系（全量 10 份）
- **Phase 1 执行文件**：
  1. `Phase 1 执行文件：项目执行文件（Phase 1：高精度物理概率模型构建）v5.5.pdf`
  2. `Phase 1 执行文件：项目执行文件 v5.6.md`
  3. `Phase 1 执行文件：项目执行文件 v5.7.md`
  4. `Phase 1 执行文件：项目执行文件 v5.9.md`
  5. `Phase 1 执行文件：项目执行文件 v5.9.1(细化版).md`
  6. `Phase 1 执行文件：项目执行文件 v5.9.2(细化版).md`
- **Phase 1.5 执行文件**：
  7. `Phase 1.5 执行文件 v1.0：数据管道重建与校准语料库.md`
  8. `Phase 1.5 执行文件 v1.1：数据管道重建与校准语料库.md`
- **Phase 2 执行文件**：
  9. `Phase 2 执行文件 v1.3：盘口定价、套利与执行引擎.md`
  10. `Phase 2 执行文件 v2.0：盘口定价、套利与执行引擎.md`
  11. `Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md`（**当前最高生效版本，PASS**）

### 3.3 专项指导与执行单（全量 5 份）
1. `子任务执行单：Polymarket 结算站点身份审计与闭环评分（M0'）.md`
2. `子任务执行单 V3.0：NWS WRH 服务可用性验证（Round 4）.md`
3. `子任务执行单：NWS WRH 精度裁决与边界补测（Round 5）.md`
4. `子任务执行单：NWS WRH 与 IEM METAR 派生日极值口径对比分析.md`
5. `工作指导文件：GEFS 数据补全、站点提取与质量验证（GEFS-WI-v1.1）.md`

---

## 四、 文档盘点综合结论

1. 任务要求盘点的法定核心单据（`STATUS.md`、`docs/ROADMAP.md`、`docs/HANDOVER_P7.md`、`docs/SEALING_GATE.md`、`docs/SYNC_POLICY.md`、`evidence/` 两份封卷报告、项目方案 v2.8 及执行文件）**100% 物理存在且受 Git 版本跟踪**。
2. 发现的文书资产缺项与异常共 2 项：
   - `docs/adr/ADR-0016`（GHCN-Daily 法定真值基线）**确实缺失**；
   - `docs/adr/ADR-0015` **存在双文件并存分叉**。
