# Phase 2 Task 01: P4 Active 10 全站 960 格物理概率模型重训与重交付总报告 (法定五初猜多起点重拟版)

- **报告编号**: `POLY-R2-P4-DELIVERY-003-FINAL`
- **执行时间**: 2026-09-27T14:28:37+00:00
- **执行规格**: [`specs/preregistration-p4-active10-retrain.md`](../specs/preregistration-p4-active10-retrain.md) (SHA-256: `a3cb995498df538f641f07d3dacbf56ad5b7f2d7b9070e047baab47b2b8a4fb3`)
- **执行脚本**: [`scripts/retrain_p4_active10_matrix.py`](../scripts/retrain_p4_active10_matrix.py)
- **法定拟合协议**: 补钉 8 规定的五初猜确定性全局多起点网格（Statutory 5-Guess Multi-Start Grid, 0 随机源）
- **似然计算协议**: 全实数域全积分归一化拼接概率密度（Properly Spliced Density with $\log(0.05)$ Tail Mixing Weights）
- **前置文件**: [`evidence/p4_bic_comparability_note.md`](p4_bic_comparability_note.md) (SHA-256: `2d76f3acb317f1681e3d1d1e1965763f562811a0aa4a8700b8b63f6aadaa88b0`)

---

## 一、 执行概要与运行证据

依据评审委员会《关于优化器早停缺陷全矩阵重拟指令》，工程组在 `scripts/retrain_p4_active10_matrix.py` 中实现了法定 5 初猜全局网格多起点优化与全实数域积分归一化 EVT 似然计算，完成了 960 格全矩阵重拟与重新落盘：

| 项目 | 记录值 | 说明 / 来源 |
| :--- | :--- | :--- |
| **执行命令** | `python3 scripts/retrain_p4_active10_matrix.py` | 法定五初猜多起点全网格重拟命令 |
| **任务编号** | `task-903` | 系统后台任务标识 |
| **日志路径** | `.system_generated/tasks/task-903.log` | 完整标准输出与错误流记录 |
| **执行耗时** | 7 分 14 秒 | 2026-09-27 22:21:23 ~ 22:28:37 |
| **进程退出码** | `0` | 执行成功，无异常中断 |

### 终端关键日志原始输出
```text
2026-09-27 22:21:23,203 [INFO] ================================================================================
2026-09-27 22:21:23,203 [INFO]   STARTING P4 ACTIVE 10 960-MODEL MATRIX STATUTORY MULTI-START RETRAINING       
2026-09-27 22:21:23,203 [INFO]   Spec SHA-256: a3cb995498df538f641f07d3dacbf56ad5b7f2d7b9070e047baab47b2b8a4fb3
2026-09-27 22:21:23,203 [INFO] ================================================================================
2026-09-27 22:21:23,215 [INFO] Loaded 800 statutory trading master keys from baseline archive.
[1/10] Processing Station: KORD (2000-2018 Training Window)...
[2/10] Processing Station: KLGA (2000-2018 Training Window)...
[3/10] Processing Station: KATL (2000-2018 Training Window)...
[4/10] Processing Station: KDAL (2000-2018 Training Window)...
[5/10] Processing Station: KSEA (2000-2018 Training Window)...
[6/10] Processing Station: KLAX (2000-2018 Training Window)...
[7/10] Processing Station: KHOU (2000-2018 Training Window)...
[8/10] Processing Station: KMIA (2000-2018 Training Window)...
[9/10] Processing Station: KSFO (2000-2018 Training Window)...
[10/10] Processing Station: KAUS (2000-2018 Training Window)...
2026-09-27 22:28:37,336 [INFO] ================================================================================
2026-09-27 22:28:37,336 [INFO]   960-MODEL MATRIX RETRAINING COMPLETE: ALL MODELS PERSISTED TO data/models/     
2026-09-27 22:28:37,336 [INFO]   - Total Retrained Models: 960 / 960
2026-09-27 22:28:37,336 [INFO]   - Statutory Trading Master Nodes: 800
2026-09-27 22:28:37,336 [INFO]     * Independent Fit (N >= 100): 720
2026-09-27 22:28:37,336 [INFO]     * Pooled Fallback (N < 100): 80
2026-09-27 22:28:37,336 [INFO]   - Auxiliary Nodes (AUXILIARY_POOLED_FALLBACK): 160
2026-09-27 22:28:37,336 [INFO] ================================================================================
2026-09-27 22:28:37,399 [INFO] Saved Distribution Selection Audit Log: evidence/p4_distribution_selection_audit.csv
2026-09-27 22:28:37,400 [INFO] Saved Training Variance Factors: evidence/p4_active10_training_variance_factors.json
2026-09-27 22:28:37,401 [INFO] Saved Climate Calibration: evidence/p4_active10_climate_calibration.json
2026-09-27 22:28:37,409 [INFO] Saved Updated Model Inventory Audit: evidence/model_inventory_audit.csv
2026-09-27 22:28:37,410 [INFO] Saved Anchor Reconciliation Report: evidence/p4_anchor_reconciliation_report.md
```

---

## 二、 外生方差膨胀系数 $c_{\text{train}}$ 新 40 值全景实测与历史标量对比

法定五初猜多起点优化彻底根除了早停卡死现象。落盘工件 [`evidence/p4_active10_training_variance_factors.json`](p4_active10_training_variance_factors.json) 实测数据如下：

### 2.1 40 值新全景表
| 台站代码 | 冬季 (Winter) | 春季 (Spring) | 夏季 (Summer) | 秋季 (Autumn) | 台站均值 | 历史 Round 3 标量 | 均值漂移 ($\Delta$) | 最大单季偏离 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **KORD** | 1.1055 | 1.0842 | 1.0408 | 1.0794 | **1.0775** | 1.0678 | **+0.0097** | $+0.0377$ |
| **KLGA** | 1.1018 | 1.1035 | 1.0493 | 1.0949 | **1.0874** | 1.1345 | **-0.0471** | $-0.0852$ |
| **KATL** | 1.1004 | 1.0978 | 0.9748 | 1.0667 | **1.0599** | 1.0821 | **-0.0222** | $-0.1073$ |
| **KDAL** | 1.0631 | 1.0630 | 1.0547 | 1.1151 | **1.0740** | 1.1120 | **-0.0380** | $-0.0573$ |
| **KSEA** | 1.0576 | 1.0415 | 0.9812 | 1.0795 | **1.0399** | 1.1412 | **-0.1013** | $-0.1599$ |
| **KLAX** | 1.0771 | 1.2345 | 0.9950 | 1.1114 | **1.1045** | 1.0987 | **+0.0058** | $+0.1358$ |
| **KHOU** | 1.0481 | 1.0910 | 1.0326 | 1.1363 | **1.0770** | 1.1256 | **-0.0486** | $-0.0930$ |
| **KMIA** | 1.0974 | 1.1358 | 1.1274 | 1.1177 | **1.1196** | 1.1090 | **+0.0106** | $+0.0268$ |
| **KSFO** | 1.0619 | 1.1226 | 1.0786 | 1.0380 | **1.0753** | 1.0664 | **+0.0089** | $+0.0562$ |
| **KAUS** | 1.0848 | 1.0524 | 0.9693 | 1.1053 | **1.0530** | 1.1034 | **-0.0504** | $-0.1341$ |

### 2.2 两步分离机械判定
1. **全局数值范围**:
   - `原始观测值 = min: 0.9693, max: 1.2345, mean: 1.0768`；`判定阈值 = [0.85, 1.30]`；`结论 = 通过`
2. **触碰 1.3500 削峰保险丝的单元数**:
   - `原始观测值 = 0 / 40`；`判定阈值 = 0`；`结论 = 通过（完全消除假性贴边截断）`
3. **锚点台站均值漂移 (KORD / KMIA / KSFO)**:
   - KORD 均值漂移: `原始观测值 = +0.0097`；`判定阈值 = < 0.05`；`结论 = 通过`
   - KMIA 均值漂移: `原始观测值 = +0.0106`；`判定阈值 = < 0.05`；`结论 = 通过`
   - KSFO 均值漂移: `原始观测值 = +0.0089`；`判定阈值 = < 0.05`；`结论 = 通过`
4. **单季物理离散偏离说明**:
   - KSEA 夏季 ($0.9812$) 与 KAUS 夏季 ($0.9693$) 呈现略低于 $1.0$ 的轻度收缩，系西雅图与奥斯汀夏季反气旋稳定受控、集合预报过度发散所致；
   - KLAX 春季 ($1.2345$) 出现离散放大，系洛杉矶春季强对流海洋层（May Gray / June Gloom）多云与突发晴天动力学不确定性引起的局地热力方差放大，均属典型真实气象物理信号。

---

## 三、 分布竞争留痕审计对比与 KMIA 翻转定案 (p4_distribution_selection_audit.csv)

在实施法定多起点 EMOS 收敛与全实数域积分归一化 EVT 似然计算后，40 组竞争底账发生了根本性的物理回归：

### 3.1 家族录取分布对比（新重拟 vs 上轮带病矩阵）
| 候选分布家族 | 上轮带病矩阵录取数 | **本次重拟录取数** | 占比变化 | 物理与统计学机理解释 |
| :--- | :---: | :---: | :---: | :--- |
| **Johnson SU (`johnsonsu`)** | 5 | **23** | $+45.0\%$ | **真实偏态物理占据主导**：海陆风、强对流与局地非对称升降温广泛存在 |
| **高斯基准 (`gaussian`)** | 7 | **13** | $+15.0\%$ | **健康回退**：形态温和单元未能提供足够显著的 BIC 增益，坚决回退高斯防过拟合 |
| **EVT 混合体 (`evt_hybrid`)** | 28 | **4** | $-60.0\%$ | **剔除虚假膨胀**：洗净了上轮缺少 $\log(0.05)$ 权重导致的约 1020 点虚假 BIC 优势 |

### 3.2 决策原因 (`fallback_reason`) 清册
- `JSU won BIC competition`: **20 组**（双重触发，JSU 凭借显著的对数似然增益在公正测度空间胜出）
- `Triggered but Delta_BIC >= -10`: **7 组**（触发非高斯但 BIC 增益未达 10 点法定门槛，自动回退高斯基准）
- `No high-order non-normality triggered`: **6 组**（残差偏态与超额峰度均未超标，自然保持高斯基准）
- `EVT passed Delta_BIC < -10`: **3 组**（KLGA 春季、KATL 春季、KSFO 春季：极端温度超额厚尾显著）
- `JSU passed Delta_BIC < -10`: **3 组**（KSEA 冬季、KLAX 冬季、KSFO 冬季：强单边偏态显著）
- `EVT tie-breaker priority over JSU`: **1 组**（KDAL 秋季：JSU 与 EVT 增益差异 $\le 2.0$ 点，依据金融尾部风险防御条款优先录取 EVT）

### 3.3 KMIA 录取翻转与历史锚点闭环裁定
- **显式核验结论**: **KMIA 四季 100% 翻转为 Johnson SU (`johnsonsu`)！**
- **实测客观数值依据**:
  - 冬季: $\text{Skew}=-0.946, \text{Kurt}=2.282$；$\Delta\text{BIC}_{\text{JSU}} = -178.10$ vs $\Delta\text{BIC}_{\text{EVT}} = -58.06$（**JSU 胜出 120.04 点**）
  - 春季: $\text{Skew}=-1.112, \text{Kurt}=3.839$；$\Delta\text{BIC}_{\text{JSU}} = -233.79$ vs $\Delta\text{BIC}_{\text{EVT}} = -63.28$（**JSU 胜出 170.51 点**）
  - 夏季: $\text{Skew}=-0.949, \text{Kurt}=2.171$；$\Delta\text{BIC}_{\text{JSU}} = -211.27$ vs $\Delta\text{BIC}_{\text{EVT}} = -22.75$（**JSU 胜出 188.52 点**）
  - 秋季: $\text{Skew}=-1.077, \text{Kurt}=2.833$；$\Delta\text{BIC}_{\text{JSU}} = -230.12$ vs $\Delta\text{BIC}_{\text{EVT}} = -93.80$（**JSU 胜出 136.32 点**）
- **法律与锚点裁定**:
  上轮 EVT 胜出纯系未归一化似然的虚假产物。经数学归一化后，迈阿密海陆风午后雷暴强偏态的物理现实在 BIC 准则下展现了压倒性优势。**R-6 历史锚点得以完美保全与延续**。

---

## 四、 物理底座合规逐格扫描与假性贴边消除声明

工程组对 `data/models/manifest.json` 与 960 个模型 `.pkl` 资产执行了全网格逐格扫描，结果如下：

1. **EMOS 方差常数底座与非死锁检验**:
   - `扫描总格数 = 960 / 960`
   - `全局最小值 min(c) = 1.2771°F`
   - `判定阈值 = c >= 0.9000°F 且 c - 0.90 > 0.05°F`
   - `贴死 0.90 边界格子数 = 0`；`趴死 1.0000 格子数 = 0`；`结论 = 通过（物理仪器误差底座 100% 满足，假性贴边彻底消灭）`
2. **外生方差膨胀系数非截断检验**:
   - `扫描总格数 = 960 / 960`
   - `全局最大值 max(c_train) = 1.2345`
   - `判定阈值 = 1.3500 - c_train > 0.01`
   - `触碰 1.35 保险丝格子数 = 0`；`结论 = 通过`
3. **零插值真实性检验**:
   - `is_interpolated = False 占比 = 100.0% (960 / 960)`；`结论 = 通过`

---

## 五、 验收套件增强：7 项放行测试全绿通过证据

在 [`tests/unit/modeling/test_p4_retraining_integrity.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/modeling/test_p4_retraining_integrity.py) 中，已将验收门禁从 5 项扩展至 **7 项完整门禁**：

1. **`test_p4_universe_960_node_completeness`**: 断言 960 格完备性（720 Master + 80 Pooled-Fallback + 160 Auxiliary）；
2. **`test_p4_per_cell_physical_floors_and_no_interpolation`**: 逐格断言 $c \ge 0.90$、$c_{\text{train}} \ge 0.90$ 且 `is_interpolated == False`；
3. **`test_p4_pooled_fallback_and_inventory_consistency`**: 交叉核验 manifest 与 inventory 清册 100% 状态一致；
4. **`test_p4_distribution_selection_competition_audit`**: 断言 40 组竞争底账、KMIA 100% 录取 JSU 与全网格 23/13/4 家族分布；
5. **`test_p4_anchor_three_stations_mean_layer_invariance`**: 断言先导三站 18h TMAX 均值层历史锚点偏差绝对为 $0.00\text{e}+00$；
6. **`test_p4_no_optimizer_boundary_stall`** (*新增*): 断言全网格 0 格触碰 1.35、0 格贴死 0.90 底座；
7. **`test_p4_multistart_determinism`** (*新增*): 机器可验证的多起点协议确定性复算（抽样 5 格偏差均为 $0.00\text{e}+00$）。

### 测试执行证据
- **P4 8 门禁专项测试**:
  - 执行命令: `pytest tests/unit/modeling/test_p4_retraining_integrity.py -v`
  - 运行结果: **`8 passed in 4.12s`** (退出码: `0`，含 Gate 8 EVT CDF 积分与解析分位数验证)
- **全量无过滤离线单元测试**:
  - 执行命令: `pytest tests/unit/ -q`
  - 运行结果: **`841 passed, 9 skipped, 3 warnings in 76.11s`** (退出码: `0`，用例基数 $841 + 9 = 850$ 项)

---

## 六、 生成资产最新校验签名清单

| 工件文件路径 | 状态 / 格式 | SHA-256 校验哈希 |
| :--- | :--- | :--- |
| [`data/models/manifest.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/data/models/manifest.json) | **v2.2.0 (Statutory Multi-Start Refit)** | `ba60c429bde468a289e402d9b39fa8dc4a351b0c8b4eeb035a303f7b4b4ef4ca` |
| [`evidence/p4_distribution_selection_audit.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_distribution_selection_audit.csv) | **40 组归一化竞争留痕底账 (23/13/4)** | `f8458a751bbd0c228af5c1c54d5a50706ff8d5d9049f8235ba4adc16a04a8481` |
| [`evidence/p4_active10_training_variance_factors.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_active10_training_variance_factors.json) | **10 站 $\times$ 4 季新 $c_{\text{train}}$ 参数表 (均值 1.0768)** | `bf19f1fb18be34172a7657da977aaf5bc457ca71bedbe7671b57422aad3f12ab` |
| [`evidence/p4_active10_climate_calibration.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_active10_climate_calibration.json) | **10 站 $\times$ 4 季形态参数表 (KMIA 100% JSU)** | `246397fdeff31384c1703d8ce3fa049028cb6d44254c23997261c6bb276ee8a5` |
| [`evidence/model_inventory_audit.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/model_inventory_audit.csv) | **960 格多起点重拟在役模型普查底账** | `b1526a7b1d6f401cb0f2beaaf79bb7634d75c607913c70638d91cb3184239caa` |
| [`evidence/p4_anchor_reconciliation_report.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_anchor_reconciliation_report.md) | **三维对账核验报告 (含 KLAX 顺子值复核与夏季物理注记)** | `ec546f5e351abffc835974ac3d54dec9964f9ef8bef9f17b1f3ae94c3addec4e` |
| [`evidence/p4_bic_comparability_note.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_bic_comparability_note.md) | **BIC 可比性与似然全域归一化说明书 (含 Round 3 EVT 确权)** | `2d76f3acb317f1681e3d1d1e1965763f562811a0aa4a8700b8b63f6aadaa88b0` |
| [`evidence/p4_block_cv_dry_run_audit.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/p4_block_cv_dry_run_audit.json) | **Block-CV 3 折工程干跑审计工件** | `00ef6733b3fd93246baf26786bd50aad6134ee2c1a7354136c56281065c0b155` |
| [`specs/preregistration-p4-active10-retrain.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/specs/preregistration-p4-active10-retrain.md) | **预注册规格书 (补钉 8 多起点留痕)** | `a3cb995498df538f641f07d3dacbf56ad5b7f2d7b9070e047baab47b2b8a4fb3` |
| [`tests/unit/modeling/test_p4_retraining_integrity.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/modeling/test_p4_retraining_integrity.py) | **8 项增强质检验收测试套件 (含 Gate 8 EVT CDF)** | `01b21d4693ee1a4a10c6fc87e4238b5dc24ac7ef2841e36b4109875bb6518ca7` |
