# Phase 1.5 Task 08: 校准数据集发布与 Phase 1.5 终审闭环质检报告

> **数据集标识**：`calib-dataset-v2.0`  
> **报告日期**：2026-09-19  
> **责任团队**：量化工程与系统质控组  
> **依据规范**：《Phase 1.5 执行文件 v1.1》§2 Task 08、§4 全部验收标准、项目方案 (v2.6) §0.1 / §2.2、ADR-0007 / ADR-0008 / ADR-0009 / ADR-0010  
> **前置任务**：Task 01~07、Task 09 全部完成合入  
> **终审结论**：**六重验收大门（§4.1 ~ §4.6）全部通过（ALL 6 GATES PASSED），GEFS 真实网络冒烟绿灯，`calib-dataset-v2.0` 正式发布，Phase 1.5 宣布圆满收官结项！**

---

## 1. 发布概况与数据支柱汇流矩阵

`calib-dataset-v2.0` 是全美 Active 11 活跃交易站点的生产级统一校准数据集，由三大独立清洗与提取支柱汇流组成：

| 数据支柱 | 来源任务项 | 时间跨度 | 站点宇宙 | 产物文件数 | 总记录行数 | 核心特性 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **观测特征库 (`features`)** | Task 06 / 07 | 2000–2026 (27 年) | Active 11 站 | 297 个 | 107,251 站-日 | DST 本地日自适应切片、ADR-0009 特报双轨极值、2020 闰年基准 DOY、`era1`/`era2` 分层分级、标准摄氏度归一化 |
| **气候方差底座 (`climate_floor`)** | Task 05 | 2000–2018 (19 年) | Active 11 站 | 11 个 | 8,052 行 | 366 日逐日双轨（TMAX/TMIN）周期高斯平滑、严格 OOS 止步 2018、ADR-0010 物理上下限门禁 $[1.5^\circ\text{F}, 15.0^\circ\text{F}]$ |
| **预报因子库 (`gefs_factors`)** | Task 09 | 2000–2019 (20 年) | Active 11 站 | 220 个 | 9,641,830 行 | 12 时效段并集 (`f12`~`f78`)、5 集合成员、流式去重、V1~V13 全门禁零违规 |
| **合计汇总** | **Task 08 汇流发布** | **2000–2026** | **Active 11 站** | **528 个** | **9,757,133 行** | **完整元数据四元组 + SHA256 审计清单 `manifest.json`** |

> **站点宇宙铁律**：Active 11 活跃交易站为 `KORD`, `KLGA`, `KATL`, `KDAL`, `KSEA`, `KLAX`, `KHOU`, `KMIA`, `KSFO`, `KBKF`, `KAUS`。华盛顿 `KDCA` 已依据 commit `1b53879` 彻底退役注销，`KDEN`（无盘口）与 `ZSPD`（旧基准）物理隔离，严禁进入发布包。

---

## 2. 六重大门终审实测结果（§4 全部验收标准）

#### Gate 1：精度关（Precision Gate §4.1）
- **判定标准**：随机抽样 20 个站-日，比对 IEM 原报 RMK T 组高精温度与发布特征库极值，断言零偏差（$\Delta C < 10^{-4}$）。
- **实测结果**：**PASS**（20 样本全绿，最大绝对偏差 $0.00000^\circ\text{C}$）。
- **20 样本端到端独立正则审计明细表**：

| # | Station | Target Date | Obs Time (UTC) | Raw RMK T-Group (°C) | Dataset Feature (°C) | Deviation (°C) | Status |
|---|---|---|---|---|---|---|:---:|
| 1 | `KORD` | `2010-12-21` | `2010-12-21 19:51` | -0.6°C | -0.6°C | 0.00000°C | ✅ PASS |
| 2 | `KORD` | `2020-06-14` | `2020-06-14 19:50` | 20.0°C | 20.0°C | 0.00000°C | ✅ PASS |
| 3 | `KLGA` | `2010-07-20` | `2010-07-20 19:51` | 31.1°C | 31.1°C | 0.00000°C | ✅ PASS |
| 4 | `KLGA` | `2020-05-11` | `2020-05-11 18:55` | 16.0°C | 16.0°C | 0.00000°C | ✅ PASS |
| 5 | `KATL` | `2010-08-24` | `2010-08-24 20:52` | 32.2°C | 32.2°C | 0.00000°C | ✅ PASS |
| 6 | `KATL` | `2020-05-08` | `2020-05-08 14:30` | 18.0°C | 18.0°C | 0.00000°C | ✅ PASS |
| 7 | `KDAL` | `2010-11-16` | `2010-11-16 20:53` | 17.2°C | 17.2°C | 0.00000°C | ✅ PASS |
| 8 | `KDAL` | `2020-01-25` | `2020-01-25 20:05` | 19.0°C | 19.0°C | 0.00000°C | ✅ PASS |
| 9 | `KSEA` | `2010-06-05` | `2010-06-05 22:53` | 20.0°C | 20.0°C | 0.00000°C | ✅ PASS |
| 10 | `KSEA` | `2020-03-24` | `2020-03-24 20:40` | 10.0°C | 10.0°C | 0.00000°C | ✅ PASS |
| 11 | `KLAX` | `2010-08-24` | `2010-08-24 19:53` | 25.6°C | 25.6°C | 0.00000°C | ✅ PASS |
| 12 | `KLAX` | `2020-11-16` | `2020-11-16 20:53` | 32.2°C | 32.2°C | 0.00000°C | ✅ PASS |
| 13 | `KHOU` | `2010-04-12` | `2010-04-12 17:53` | 23.9°C | 23.9°C | 0.00000°C | ✅ PASS |
| 14 | `KHOU` | `2020-10-05` | `2020-10-05 20:30` | 29.0°C | 29.0°C | 0.00000°C | ✅ PASS |
| 15 | `KMIA` | `2010-02-01` | `2010-02-01 16:53` | 23.3°C | 23.3°C | 0.00000°C | ✅ PASS |
| 16 | `KMIA` | `2020-09-30` | `2020-09-30 17:10` | 33.0°C | 33.0°C | 0.00000°C | ✅ PASS |
| 17 | `KSFO` | `2010-04-19` | `2010-04-19 18:56` | 18.3°C | 18.3°C | 0.00000°C | ✅ PASS |
| 18 | `KSFO` | `2020-05-18` | `2020-05-18 20:30` | 19.0°C | 19.0°C | 0.00000°C | ✅ PASS |
| 19 | `KBKF` | `2020-05-03` | `2020-05-03 21:58` | 24.5°C | 24.5°C | 0.00000°C | ✅ PASS |
| 20 | `KAUS` | `2010-11-25` | `2010-11-25 18:53` | 26.7°C | 26.7°C | 0.00000°C | ✅ PASS |

---

### Gate 2：门禁关（QC Gate §4.2）
- **判定标准**：全站日级 T 组覆盖率 $\ge 99\%$；双源一致性零未解释告警。
- **实测结果**：**PASS**。
  - 特征库总站-日数：**107,251 站-日**；
  - 标称正常（`nominal`）：107,250 站-日；
  - 降级（`degraded`）：仅 1 站-日；
  - 实际标称覆盖率：**`99.999%`**（远超 $\ge 99\%$ 要求）；
  - 双源一致性：实测 1 项留存告警（KORD 2024-06-01 TMAX delta=0.48°F，记载于 `data/reports/dual_source_discrepancies.jsonl`），严格作为 Phase 2 §8.1 切换窗裁决原始证据留存，未解释告警为 **0 项**。

---

### Gate 3：覆盖关（Coverage Gate §4.3）
- **判定标准**：11 活跃站 2000–2026 覆盖率 100% 具备实测证据（297/297 站-年分块全部存在，零断代年）。
- **实测结果**：**PASS**。
  - 预期分区文件：297 个；
  - 实际分区文件：297 个；
  - 缺失分区数：0 个；
  - 历史假定值（`ASSUMED`）已于 Task 03/04 全部翻转为实测值（`VERIFIED`）。

---

### Gate 4：OOS 纪律关（OOS Discipline Gate §4.4）
- **判定标准**：气候学方差底座（Floor）与训练数据严格止步于 2018 年，2019+ 验证集纯净。
- **实测结果**：**PASS**。
  - 11 站 `climate_floor` 训练区间统一固化为 `2000-2018`；
  - 每站严格包含 366 日双轨（366 日 MAX + 366 日 MIN = 732 行）；
  - 2019+ 数据纯净隔绝，无任何前向信息泄漏（Zero Data Leakage）。

---

### Gate 5：台账关（Ledger Clearance Gate §4.5）
- **判定标准**：PENDING-01~08 全部关闭或显式挂接 Phase 2 验收点，零游离项。
- **实测结果**：**PASS**（发布脚本动态解析 `docs/reports/phase1.5-task03-pending-clearance.md`，确证 8 项挂账 100% 闭环，未决项为 0）：
  1. `PENDING-01`：**`ATTACHED_PHASE2`**（X.50 临界边界判例验证，挂接 Phase 2 结算复刻器）；
  2. `PENDING-02`：**`CLOSED_NO_MARKET`**（KDEN 无对应交易标的，正式注销）；
  3. `PENDING-03`：**`PARAMETER_LOCKED`**（Era 1 负偏差先验参数固化为 $N(-2.8, 1.5^2)$）；
  4. `PENDING-04`：**`VERIFIED`**（KMIA 历史判例 4/4 确证吻合）；
  5. `PENDING-05`：**`VERIFIED`**（KAUS 实测覆盖率 99.2%）；
  6. `PENDING-06`：**`RETIRED_DECOMMISSIONED`**（KDCA 随无常态日盘彻底退役下线）；
  7. `PENDING-07`：**`ADMITTED`**（KAUS 准入 Active 11 站池）；
  8. `PENDING-08`：**`RESOLVED`**（ADR-0009 确证特报结算效力并双轨分层）。

---

### Gate 6：预报特征关（Forecast Feature Gate §4.6）
- **判定标准**：GEFS 因子库 11 站 × 20 年 × 12 时效段 × 5 成员，物理与金样本门禁 V1~V13 全部零违规。
- **实测结果**：**PASS**。
  - 220 个 GEFS Parquet 文件齐全；
  - 因子记录总行数：9,641,830 行；
  - 发布脚本抽检因子表列模式完整性（7 必选字段 `init_date`, `target_date`, `station`, `variable`, `member`, `lead_hours`, `value_K` 齐备，空值率为 0）；
  - 验证 `docs/reports/gefs_task09_qc_v1.0.md` 明确载明 V1~V13 全部门禁 100% 通过（ALL 13 GATES PASSED）。

---

## 3. 发布包结构与 Manifest 规格

发布产物位于 `data/processed/calib-dataset-v2.0/`，采用相对符号链接结构（保障单点真实且零冗余）：

```text
data/processed/calib-dataset-v2.0/
├── manifest.json                                      # 全量四元组与 SHA256 审计清单
├── features/                                          # 观测切片特征库
│   ├── KATL/ [2000.parquet ... 2026.parquet] (27 文件)
│   ├── KAUS/ [2000.parquet ... 2026.parquet] (27 文件)
│   └── ... (共 11 站 x 27 年 = 297 文件)
├── climate_floor/                                     # 气候学方差底座
│   ├── KATL_climate_floor.parquet
│   └── ... (共 11 站 = 11 文件)
└── gefs_factors/                                      # GEFS 集合预报因子库
    ├── KATL/ [2000.parquet ... 2019.parquet] (20 文件)
    └── ... (共 11 站 x 20 年 = 220 文件)
```

`manifest.json` 包含：
- `version`: `"2.0.0"`
- `dataset_name`: `"calib-dataset-v2.0"`
- `timestamp`: UTC ISO-8601 时间戳
- `git_commit_sha`: 当前 Git Commit
- `station_universe`: Active 11 站点数组
- `total_files`: 528
- `total_rows`: 9,757,133
- `gates_verification`: 六重大门验证结果字典及 20 样本抽检明细
- `files`: 每个文件的相对路径、站号、年份、组件、文件大小、SHA256 与行数。

---

## 4. 自动化测试与网络冒烟证据

### 4.1 单元测试套件
```bash
pytest tests/unit/pipeline/test_publish_calibration_dataset.py -v
```
- **测试用例**：
  - `TestStationUniverseValidation`: 验证 Active 11 站准入，严格拦截 `KDCA`, `KDEN`, `ZSPD` 及未知站；
  - `TestGateVerifications`: 验证 Gate 1~6 的判定与异常分支；
  - `TestAssemblyAndManifest`: 验证目录组装、符号链接、SHA256 计算及 Manifest 格式。
- **结果**：9 passed in 0.58s ✅。

### 4.2 真实网络冒烟测试（硬性铁律）
```bash
RUN_NETWORK_TESTS=1 python -m pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q
```
- **结果**：`1 passed in 33.28s` ✅。

---

## 5. Phase 1.5 终审结项与 Phase 2 启动交接

至此，**Phase 1.5 全部任务（Task 01~09）已 100% 闭环验收**：
- 底层观测管道：由 Wunderground 脏数据彻底重铸为 IEM ASOS 官方高精原报（零偏差）；
- 极值口径：完成 ADR-0009 特报双轨架构；
- 方差底座：完成 ADR-0010 物理平滑重建；
- 预报特征源：完成 GEFS 全球场 12 时效段全池提取；
- 站点宇宙：正式固化为全美 Active 11 活跃交易站（KDCA 彻底退出）。

### Phase 2 开工条件对照表

| 启动前置条件 | 依据文件 | 当前达成状态 |
| :--- | :--- | :---: |
| **Task 08 正式发布** | 《Phase 1.5 执行文件 v1.1》§2 | ✅ `calib-dataset-v2.0` 正式发布闭环 |
| **ADR 条目 1：切换窗阈值裁决** | 《项目方案 (v2.6)》§8.1 | ⏳ 待裁决（双源告警样本已留存就绪） |
| **ADR 条目 2：临界边界判例裁决** | 《项目方案 (v2.6)》§8.1 | ⏳ 待裁决（复刻器判例池就绪） |
| **ADR 条目 3：盘口定价与执行架构** | 《项目方案 (v2.6)》§8.1 | ⏳ 待裁决（Phase 2 执行文件 v1.3） |

**结论**：Phase 1.5 正式宣布胜利收官！系统已完全具备进入 Phase 2 开工前 ADR 裁决与定价引擎研发的全部物质与数据基础！
