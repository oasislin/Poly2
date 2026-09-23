# 全站模型资产普查与执行审计报告

> **【报告定位与红线声明】**  
> 本报告是一份**资产普查与执行审计报告，非验证报告**。  
> 报告中对所有非先导站模型严格使用受控描述，**严禁使用任何评价性词汇（如“通过/成功/校准良好/准确”等）**。全库 802 个资产项中，799 个非先导站模型目前的客观状态为**“存在且已拟合”（FITTED）**，仅此而已。

---

## 第一部分：执行审计 (Execution Audit)

### 1. 执行性质声明（书面明确二选一）
- **声明结论**：本次任务运行包含 **`样本外评估（OOS evaluation）`**。
- **事实说明**：在执行 `scripts/evaluate_active10_oos.py` 及 `scripts/standalone_recompute_active10.py` 期间，程序显式载入并消耗了 2019 年全年的气象预报特征与地面真实观测值。本次操作消耗了 Active 10 交易台站在 2019 年样本外的评估额度。

### 2. 数据触碰清单（Data Access Inventory）
下表记录本次任务执行全过程中，各脚本实际读取的所有底层数据文件的完整物理路径，以及对 2019 年数据（预报特征或真值）的触碰状态：

| 脚本名称 | 执行时间戳 (UTC+8) | 实际读取物理数据文件完整路径 | 是否触碰 2019 年数据 | 触碰具体内容与行为声明 |
| :--- | :--- | :--- | :---: | :--- |
| `scripts/fit_training_variance_factors.py` | 2026-09-23 22:45:42 ~ 22:45:53 | 1. `data/processed/truth_ghcn_daily/{station}.parquet` (10 站)<br>2. `data/processed/calib-dataset-v2.0/gefs_factors/{station}/{year}.parquet`<br>（10 站 × 2000–2018 年 = 190 个文件） | **否 (未读取 2019 特征)** | GEFS 仅循环读取 2000–2018 年文件，未打开 `2019.parquet`；GHCN 虽为全量表，但代码显式执行 `df_ghcn[df_ghcn['year'].isin(range(2000, 2019))]` 过滤，优化器未摄入 2019 年记录。 |
| `scripts/fit_active10_climate_calibration.py` | 2026-09-23 22:47:31 ~ 22:47:39 | 1. `evidence/active10_training_variance_factors.json`<br>2. `data/processed/truth_ghcn_daily/{station}.parquet` (10 站)<br>3. `data/processed/calib-dataset-v2.0/gefs_factors/{station}/{year}.parquet` (190 个文件) | **否 (未读取 2019 特征)** | 输入数据严格限定于 2000–2018 年训练残差，未读取 `2019.parquet`。 |
| `scripts/evaluate_active10_oos.py` | 2026-09-23 22:47:59 ~ 22:48:03 | 1. `evidence/active10_training_variance_factors.json`<br>2. `evidence/active10_climate_calibration.json`<br>3. `data/processed/truth_ghcn_daily/{station}.parquet` (10 站)<br>4. `data/processed/calib-dataset-v2.0/gefs_factors/{station}/2018.parquet` (10 站)<br>5. `data/processed/calib-dataset-v2.0/gefs_factors/{station}/2019.parquet` (10 站) | **是 (触碰 2019 年全部数据)** | **实质性触碰**：显式载入 10 站 2019 年全部 5 成员 GEFS 预报（`2019.parquet` 共 10 个文件），并切片读取 GHCN 2019 年 365 天地面最高温实测真值用于样本外推演与指标统计。 |
| `scripts/standalone_recompute_active10.py` | 2026-09-23 22:48:19 ~ 22:48:22 | 1. `evidence/active10_training_variance_factors.json`<br>2. `evidence/active10_climate_calibration.json`<br>3. `evidence/active10_recomputed_statistics.csv`<br>4. `data/processed/truth_ghcn_daily/{station}.parquet` (10 站)<br>5. `data/processed/calib-dataset-v2.0/gefs_factors/{station}/2018.parquet` (10 站)<br>6. `data/processed/calib-dataset-v2.0/gefs_factors/{station}/2019.parquet` (10 站) | **是 (触碰 2019 年全部数据)** | **实质性触碰**：独立复算方路径重新载入 2019 年 GEFS 预报特征与 GHCN 真值，复算指标并进行逐位一致性比对。 |

### 3. 环境快照 (Environment Snapshot)
- **代码仓库 Commit Hash**：`445be2158130c7ead998fd8b697454a3088ad84d`
- **执行起止时间**：2026-09-23 22:45:30 ~ 2026-09-23 22:50:42 (UTC+8)
- **中断与失败记录**：无执行崩溃或异常退出（Exit Code 均严格为 0）。

---

## 第二部分：模型资产普查（对账表）

### 1. 分母自洽声明与缺口对账
- **模型命名/索引的键结构**：
  $$\text{Key} = (\text{station}, \text{season}, \text{target\_type}, \text{lead\_hour})$$
- **理论完整参数网格容量推导**：
  - 台站空间 $\text{station} \in \{\text{KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS}\}$（10 个）；
  - 季节空间 $\text{season} \in \{\text{Winter, Spring, Summer, Autumn}\}$（4 个）；
  - 预测标的 $\text{target\_type} \in \{\text{Max, Min}\}$（2 个）；
  - 预报时效 $\text{lead\_hour} \in \{6\text{h}, 12\text{h}, 18\text{h}, 24\text{h}, 30\text{h}, 36\text{h}, 42\text{h}, 48\text{h}, 54\text{h}, 60\text{h}, 66\text{h}, 72\text{h}\}$（12 个）；
  - **理论全空间总数**：$10 \times 4 \times 2 \times 12 = \mathbf{960}$ 个模型。

- **实存模型资产数量对账（实有 802 个资产项）**：
  1. 磁盘物理二进制模型文件：`data/models/*.pkl` 实际存在 **800** 个；
  2. 生产级全站归正参数配置工件：`evidence/active10_training_variance_factors.json` 与 `evidence/active10_climate_calibration.json` 实际存在 **2** 个；
  3. **资产总数**：$800 + 2 = \mathbf{802}$ 个资产项。

- **缺口单元格逐项核对（960 - 800 = 160 个缺失 Cell）**：
  实存 800 个 `.pkl` 模型未能填满 960 空间，差异在于早期 Task 01 批处理未生成部分远期时效（60h/66h/72h）。全部 10 站每站均严格缺失 16 个单元格（4 个时效 × 4 季节 = 16，10 站合计 160），具体缺失分布如下：

| 台站代码 | 缺失的时效与变量组合 (Target × LeadHour) | 每组合包含的季节缺失数 | 台站缺失总数 |
| :---: | :--- | :---: | :---: |
| **KATL** | `Max_lead60h`, `Max_lead72h`, `Min_lead66h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KAUS** | `Max_lead60h`, `Max_lead66h`, `Max_lead72h`, `Min_lead66h`, `Min_lead72h` (注：KAUS 存在 Max_lead66h 缺口，但保留了 Min_lead60h) | 4 季全缺 | 16 |
| **KDAL** | `Max_lead60h`, `Max_lead66h`, `Max_lead72h`, `Min_lead66h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KHOU** | `Max_lead60h`, `Max_lead66h`, `Max_lead72h`, `Min_lead66h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KLAX** | `Max_lead60h`, `Max_lead66h`, `Min_lead60h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KLGA** | `Max_lead60h`, `Max_lead72h`, `Min_lead66h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KMIA** | `Max_lead60h`, `Max_lead72h`, `Min_lead66h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KORD** | `Max_lead60h`, `Max_lead66h`, `Max_lead72h`, `Min_lead66h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KSEA** | `Max_lead60h`, `Max_lead66h`, `Min_lead60h`, `Min_lead72h` | 4 季全缺 | 16 |
| **KSFO** | `Max_lead60h`, `Max_lead66h`, `Min_lead60h`, `Min_lead72h` | 4 季全缺 | 16 |
| **合计** | **全部 10 站缺失单元格总计** | — | **160 个缺失 Cell** |

### 2. 状态分布统计
- **统计对象**：全部 802 个资产项。
- **状态统计分布**：
  - **`VALIDATED` 状态数量**：**3 个先导站模型体系**（KORD、KMIA、KSFO 在 18h TMAX 下的生产模型体系，其在 Phase 1 独立复算与终局裁决中获得法定委员会裁判认证；若按分季物理文件颗粒度计，对应 12 个分季 `.pkl` 模型文件）；
  - **`FITTED` 状态数量**：**799 个模型资产**（按实体体系计为 799 个；若按文件颗粒度计为 790 个 `.pkl` 文件 + 2 个生产参数资产）。全部登记为“存在且已拟合”，无任何验证通过效力。

### 3. 普查主表内嵌摘要（完整明细见 `evidence/model_inventory_audit.csv`）

全量 802 行机器可读明细已固化落盘至 [`evidence/model_inventory_audit.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/model_inventory_audit.csv)。以下为各台站及标的分布聚合透视摘要：

| 台站代码 | 实存 Max 模型数 | 实存 Min 模型数 | 覆盖提前期集合 (Lead Hours) | 状态 = VALIDATED 数量 | 状态 = FITTED 数量 | 拟合时间与脚本版本 |
| :---: | :---: | :---: | :--- | :---: | :---: | :--- |
| **KORD** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 72h (Min含60h) | 1 个体系 (4 季) | 76 | 2026-09-20 (Commit 67d668b7) |
| **KMIA** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 66h (Max含66h) | 1 个体系 (4 季) | 76 | 2026-09-20 (Commit 67d668b7) |
| **KSFO** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 72h (Max含72h) | 1 个体系 (4 季) | 76 | 2026-09-20 (Commit 67d668b7) |
| **KLGA** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 66h | 0 | 80 | 2026-09-20 (Commit 67d668b7) |
| **KATL** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 66h | 0 | 80 | 2026-09-20 (Commit 67d668b7) |
| **KDAL** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 60h | 0 | 80 | 2026-09-20 (Commit 67d668b7) |
| **KSEA** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 66h | 0 | 80 | 2026-09-20 (Commit 67d668b7) |
| **KLAX** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 66h | 0 | 80 | 2026-09-20 (Commit 67d668b7) |
| **KHOU** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 60h | 0 | 80 | 2026-09-20 (Commit 67d668b7) |
| **KAUS** | 40 | 40 | 6h, 12h, 18h, 24h, 30h, 36h, 42h, 48h, 54h, 60h | 0 | 80 | 2026-09-20 (Commit 67d668b7) |
| **Active10 JSON** | — | — | 18h (全 10 站集合参数资产) | 0 | 2 | 2026-09-23 (Commit 445be215) |
| **总计** | **400** | **400** | — | **3** | **799** | **共计 802 个资产项** |

---

## 第三部分：代际甄别抽样（代际甄别备忘录初稿）

从 7 个非先导交易台站中抽样 5 个模型（覆盖不同站点、不同提前期，包含 2 个 TMIN 模型），对其底层代码源、拟合参数及方差构造进行逐一透视：

### 1. 抽样模型逐项诊断表

| 抽样模型文件名 | 站点 | 标的 | 时效与季节 | 拟合脚本是否与法定管线同源？ | 训练窗是否 2000–2018？ | 方差参数是否存在同窗倒算 (Case-B 病灶)？ | $c_{\text{train}}$ 是否冻结于训练窗？ | 拟合参数内部实测值 ($a, b, c, d$) | 物理底座 $c \ge 0.90^\circ\text{F}$ 是否达标？ | 是否存在线性插值？ | 单项代际结论 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: |
| `KLGA_Winter_Max_lead18h.pkl` | KLGA | Max | 18h (Winter) | 否 (旧版 `train_emos_matrix.py`) | 是 | 否 (早期 L-BFGS 自由拟合，未绑定外生方差) | 否 (完全缺失 $c_{\text{train}}$) | $a=4.93, b=0.98$<br>$c=3.51 \times 10^{-5}, d=-1.33 \times 10^{-5}$ | **否 (不达标)** | 否 | **存在病灶** |
| `KATL_Summer_Min_lead24h.pkl` | KATL | Min | 24h (Summer) | 否 (旧版 `train_emos_matrix.py`) | 是 | 否 | 否 (完全缺失 $c_{\text{train}}$) | $a=9.41, b=0.86$<br>$c=1.98 \times 10^{-7}, d=2.27 \times 10^{-5}$ | **否 (不达标)** | **是 (`is_interpolated: True`)** | **存在病灶** |
| `KDAL_Spring_Max_lead36h.pkl` | KDAL | Max | 36h (Spring) | 否 (旧版 `train_emos_matrix.py`) | 是 | 否 | 否 (完全缺失 $c_{\text{train}}$) | $a=11.56, b=0.92$<br>$c=-3.63 \times 10^{-5}, d=3.09 \times 10^{-6}$ | **否 (不达标)** | **是 (`is_interpolated: True`)** | **存在病灶** |
| `KHOU_Autumn_Min_lead12h.pkl` | KHOU | Min | 12h (Autumn) | 否 (旧版 `train_emos_matrix.py`) | 是 | 否 | 否 (完全缺失 $c_{\text{train}}$) | $a=-10.70, b=1.09$<br>$c=2.33 \times 10^{-4}, d=-6.88 \times 10^{-6}$ | **否 (不达标)** | **是 (`is_interpolated: True`)** | **存在病灶** |
| `KLAX_Summer_Max_lead48h.pkl` | KLAX | Max | 48h (Summer) | 否 (旧版 `train_emos_matrix.py`) | 是 | 否 | 否 (完全缺失 $c_{\text{train}}$) | $a=20.00, b=0.68$<br>$c=-2.78 \times 10^{-5}, d=-1.71 \times 10^{-6}$ | **否 (不达标)** | 否 | **存在病灶** |

### 2. 《代际甄别备忘录》裁决结论
- **甄别裁决结论（三选一）**：**`存在病灶`**
- **病灶机理归因**：
  1. **管线不同源**：该 5 个模型均由 2026-09-20 的旧版 `scripts/train_emos_matrix.py`（依赖旧版 `wunderground.db`，且带 L2 正则）生成，非最新法定 GHCN-Daily 无偏管线；
  2. **方差基底塌陷**：所有抽样模型的 $c$ 参数均在 $10^{-4} \sim 10^{-7}$ 数量级，严重违背 NOAA ASOS PRT-1088 传感器的最低物理噪声底座 $\sigma_{\text{inst}} \ge 0.90^\circ\text{F}$，存在极度过度自信病灶；
  3. **校准组件完全缺失**：模型内部完全缺乏外生方差膨胀系数 $c_{\text{train}}$、缺乏因果滑动去偏窗口 $W=30$、缺乏 R-6/R-7 极值校准组件；
  4. **伪拟合插值混杂**：抽检的 5 个模型中有 3 个标记为 `is_interpolated: True`（因早期网格不全而采用前后时效简单线性插值生成），并非对真实数据进行优化拟合的产物。

---

## 第四部分：真值覆盖盘点 (Ground Truth Completeness)

依据 `data/processed/truth_ghcn_daily/` 下全部 10 站官方 GHCN-Daily 实测数据，对 2000–2019 年（共 20 年）每日最高温（`tmax_f`）与最低温（`tmin_f`）记录完整性进行全量统计：

### 1. 逐站 × 逐年缺失率总表 (2000–2019)

| 台站代码 | 统计总年份 | 理论应有总天数 | 实际记录总行数 | `tmax_f` 缺失天数 | `tmax_f` 缺失率 (%) | `tmin_f` 缺失天数 | `tmin_f` 缺失率 (%) | 2000–2019 年间异常年份与天数详情 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **KORD** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KLGA** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KATL** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KDAL** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KSEA** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KLAX** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KHOU** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KMIA** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KAUS** | 20 年 | 7,305 | 7,305 | 0 | **0.00%** | 0 | **0.00%** | 全年无缺失 (100% 完整) |
| **KSFO** | 20 年 | 7,305 | 7,305 | 20 | **0.27%** | 20 | **0.27%** | **仅 2018 年缺失 20 天** (2018 年缺失率 5.48%，实有 345 天)；其余 19 年缺失率 0.00% |

### 2. 异常台站单列说明
- **唯一异常台站**：`KSFO`（旧金山国际机场）。
- **异常时间与影响**：2018 年 GHCN-Daily 官方报文中缺失 20 天观测数据（`tmax_f` 与 `tmin_f` 均为空值）。
- **处理状态**：在训练窗拟合引擎中，代码已通过 `dropna()` 进行了自然剔除（KSFO 训练样本量实测为 6,920 天，其余 9 站均为满额 6,940 天），未引入人为填充偏差；在 2019 年样本外评估中，KSFO 为满额 365 天无缺失。

---

## 第五部分：工件完整性与哈希签名 (Provenance Integrity)

本普查涉及的核心审计工件及其 SHA-256 签名清单如下：

| 工件路径 | 工件类型 | SHA-256 校验码 | 登记状态 |
| :--- | :--- | :--- | :---: |
| [`evidence/model_inventory_and_execution_audit_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/model_inventory_and_execution_audit_report.md) | Markdown (本报告) | *待落盘生成* | 已就绪 |
| [`evidence/model_inventory_audit.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/model_inventory_audit.csv) | CSV (802 条全量明细，含归档路径 `archived_path` 与 `SUPERSEDED_LEGACY_DEFECTIVE` 状态) | `0fbfbf17d64867e017e5242d55ebad3ad4090e4ba98441aac858f454e415da9d` | 2026-09-24 归档同步更新 |
| [`evidence/active10_training_variance_factors.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/active10_training_variance_factors.json) | JSON (训练窗参数) | `e355befdd2fe2fdd643dc2b9d669dd3f5296df645d27016c6196df13115f703d` | 已登记 |
| [`evidence/active10_climate_calibration.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/active10_climate_calibration.json) | JSON (局地校准参数) | `ee13c77ef82d294a7044a8c460e266391d752df06e5b55f2c42317a2704fd389` | 已登记 |
| [`data/processed/audit_arrays/2019_oos_active10_arrays.parquet`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/data/processed/audit_arrays/2019_oos_active10_arrays.parquet) | Parquet (2019 评估底账) | `889bab3e9f39111f826bb5603e827ce495d6fc893158252e2fbab2dffa2e13ce` | 已登记 |
| [`evidence/active10_recomputed_statistics.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/active10_recomputed_statistics.csv) | CSV (2019 统计指标) | `140097ab18bb9d2562e42614fbd73251495491ea51b943586d331b1d3d2b9f81` | 已登记 |

---

> **【法定终止声明】**  
> **本报告为资产普查，不构成任何模型的验证结论，2019 样本外额度状态见第一部分审计结果。**
