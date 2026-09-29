# P5 分桶检验工具实现自查与现状拷问报告

> **报告性质**: 依据《【独立指令】P5 分桶检验工具——现状冻结、实现拷问与调整依据》执行的现状自查与信息收集报告。  
> **状态**: 冻结生效（数据冻结、结论冻结、开发冻结）。暂停新功能开发，暂不跑真实模型出结论。  
> **核查脚本对象**: `scripts/standalone_reliability_check.py` 及测试套件 `tests/unit/verification/test_reliability_check.py`。

---

## 第一部分：立即生效的三条冻结令执行声明

1. **数据冻结**:
   - 严正确认：自收到指令起，本工具及其测试严格禁止读取 2019 年任何文件（包括但不限于 `2019_oos_evaluation_arrays.parquet`、`2019_oos_round3_evaluation_arrays.parquet` 及 2019 年的原始特征/真值）。
   - 在开发调试期间，本工具**从未读取或调用过 2019 年数据**，详见 Q11 回答。
2. **结论冻结**:
   - 前期运行输出的任何加权 ECE、BSS 或 KSFO 夏季偏差等数字，一律归档为“工具原型调试产物”，不得写入任何正式质检报告，不得作为最终模型能力的凭据。
3. **开发冻结**:
   - 暂停所有新代码功能开发，全面梳理纸面逻辑，等待评审方对照第三部分规格出具调整稿。

---

## 第二部分：实现拷问清单（14 题逐题作答与证据链）

### A 组：归池逻辑（最核心的一题组）

#### Q1. 归池的键是什么？
- **回答**: 记录是**严格按预测概率值 `p_pred` 进行分段归池**（正确），**绝非**按桶标签 $b$ 分组。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 233–239 行：
```python
233:     p_arr = df_expanded["p_pred"].to_numpy(dtype=np.float64)
234:     h_arr = df_expanded["hit"].to_numpy(dtype=np.float64)
235:     n_total = len(p_arr)
236: 
237:     edges = np.linspace(0.0, 1.0, num_bins + 1)
238:     bin_idx = np.clip(np.digitize(p_arr, edges) - 1, 0, num_bins - 1)
```
- **说明**: 无论样本来自哪个站点、哪一天、哪个物理温度档位，只要该档位计算出的预测概率落入同一区间（如 $22.5\% \sim 27.5\%$），均被 `np.digitize(p_arr, edges)` 归入同一个概率段 $I_m$ 进行命中率核验。

---

#### Q2. 概率段怎么切？
- **回答**:
  - **段数与段宽**: 参数化支持，默认 `num_bins=20`，段宽 5%（`0.05`）；
  - **边界归属**: 左闭右开 $[edges[b], edges[b+1])$；最后一段（第 20 段）右端闭合 $[0.95, 1.00]$；
  - **尾部两端处理**: 允许极端段开区间（0.0 归入第 1 段，1.0 经 `clip` 归入第 20 段）；
  - **硬编码还是参数化**: 由参数 `num_bins: int = 20` 驱动，边界网格由 `np.linspace(0.0, 1.0, num_bins + 1)` 动态生成。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 237–248 行：
```python
237:     edges = np.linspace(0.0, 1.0, num_bins + 1)
238:     bin_idx = np.clip(np.digitize(p_arr, edges) - 1, 0, num_bins - 1)
243:     for b in range(num_bins):
244:         low_e, high_e = edges[b], edges[b + 1]
245:         range_str = f"[{low_e:.2f}, {high_e:.2f}{']' if b == num_bins - 1 else ')'}"
247:         mask = bin_idx == b
248:         stratum_count = int(np.sum(mask))
```

---

#### Q3. p_pred 怎么算出来的？
- **回答**:
  - 从模型连续分布积分到档位概率代码如下；
  - **尾部桶处理**: 最冷档采用 $\text{CDF}(B_1.\text{upper})$，最热档采用 $1.0 - \text{CDF}(B_7.\text{lower})$，严格作为极限半无界区间处理，未被当成普通有限区间；
  - **参数超物理范围行为（如 $c \to 10^{-7}$ 或 $\sigma \to 0$）**: 当前代码第 116 行 `z = (y - mu) / sigma_eff` **未设置 $\sigma_{\text{eff}}$ 下限断言**。若 $\sigma_{\text{eff}}$ 塌陷到 $10^{-7}$，代码将发生 $z \to \pm \infty$ 的浮点溢出，CDF 在 0.0 与 1.0 之间阶跃，**会静默输出极端尖锐假峰（单一档位 $p=1.0$，其余 $p=0.0$）**。此项属于严重漏洞，需在调整稿中增加物理下限防御截断。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 112–126 行、第 171–181 行：
```python
112: def evaluate_station_cdf(station: str, y: float, mu: float, sigma_eff: float, ...):
113:     if math.isinf(y):
114:         return 1.0 if y > 0 else 0.0
115:     z = (y - mu) / sigma_eff
116:     if station == "KMIA":
117:         p = r6_params["johnsonsu_parameters"]
118:         z_norm = p["gamma"] + p["delta"] * np.arcsinh((z - p["xi"]) / p["lambda"])
119:         return float(stats.norm.cdf(z_norm))
120:     elif station == "KSFO":
121:         return _evaluate_evt_tail_cdf(z, r7_params["stations"]["KSFO"])
122:     return float(stats.norm.cdf(z))

171:     cdfs = [evaluate_station_cdf(st, b[1], mu, sig_eff, r6_params, r7_params) for b in bounds]
172:     p_bins = np.zeros(num_bins, dtype=np.float64)
173:     p_bins[0] = cdfs[0]
174:     for k in range(1, num_bins - 1):
175:         p_bins[k] = cdfs[k] - cdfs[k - 1]
176:     p_bins[num_bins - 1] = 1.0 - cdfs[num_bins - 2]
```

---

#### Q4. 命中判定 hit 的口径？
- **回答**:
  - **真值来源与列名**: 取自输入 parquet 中的 `obs_tmax_f`（最高温）；
  - **抖动口径**: 当前实现**未添加任何随机抖动**，采用的是标准半闭半开离散区间 `lb <= obs_y < ub`。
  - **KMIA 仲裁教训比对**: Round 3 的 KMIA 仲裁教训表明抖动口径不可漂移。当前在 `scripts/standalone_reliability_check.py` 中，命中判定完全固定为纯确定性区间匹配，不存在两套并存问题；但代码中缺少显式的物理离散度（0.1°C / 1°F）注释说明。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 183–187 行：
```python
183:     records = []
184:     for k in range(num_bins):
185:         lb, ub = bounds[k]
186:         hit = 1 if (obs_y >= lb and obs_y < ub) else 0
```

---

### B 组：交叉验证结构

#### Q5. 有没有“每轮重拟”？
- **回答**: **完全没有重拟（未实现）**。
- **现状说明**: 当前实现直接从 `evidence/r6_kmia_parameters.json` 与 `evidence/r7_tail_parameters.json` 读取由 2000–2018 全量数据拟合好的静态参数，全量推导检验。属于**静态离线回测对账**，没有在循环层级内实现抽块与参数重拟。
- **循环层级证据**: `scripts/standalone_reliability_check.py` 第 219 行直接遍历全量数据 `for _, row in valid.iterrows()`，不存在外层拟合循环。

---

#### Q6. 抽块还是抽天？
- **回答**: **未实现抽块或抽天**。
- **现状说明**: 当前代码对 2000–2018 训练窗的 20,800 个有效站·日进行了全量 100% 静态展开。没有实现 30 天连续块抽样，没有跨年边界处理，未涉及重采样随机种子。

---

#### Q7. 轮数与汇总
- **回答**: **未实现多轮 CV 机制**。
- **现状说明**: 当前实现仅输出 1 轮静态主表（20 行）和 1 轮分层表（120 行），没有跨轮样本量加权合并，也没有输出同一概率段在多轮重拟下的 $\hat{f}$ 波动范围（离散度）。

---

### C 组：维度与分层

#### Q8. 当前支持哪些维度？
- **回答**:
  - **站点 (station)**: 硬编码仅支持先导 3 站 `['KORD', 'KMIA', 'KSFO']`（第 212、284 行）；其余 7 个 Active 台站尚未接入本脚本；
  - **气温变量 (target_type)**: 硬编码仅支持最高温 `obs_tmax_f`（Max）；**未实现 Min**；
  - **时效 (lead_hour)**: 输入数据固定对应 18h lead time；**未实现其他 lead time**；
  - **季节 (season)**: 支持 4 季（`Winter, Spring, Summer, Autumn`），硬编码在分层函数中；
  - **分层预警表层级**: 当前仅做了 1 层切片：`站点 × 季节`（3 站 × 4 季 = 12 格）。未实现 `target × lead` 主表。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 283–296 行：
```python
283: def build_stratified_warning_table(df_expanded: pd.DataFrame, num_bins: int = 10):
284:     stations = ["KORD", "KMIA", "KSFO"]
285:     seasons = ["Winter", "Spring", "Summer", "Autumn"]
287:     all_stratified_rows = []
288:     for st in stations:
289:         for se in seasons:
...
```

---

#### Q9. 多重检验意识
- **回答**:
  - **对账格总数**: 全局主表 20 格；分层表 12 格 × 10 段 = 120 格；
  - **超带格子占比 vs 期望 5% 对照**: **未实现**。没有在全表输出整体“实际超带率 vs 5% 名义置信水平”的比对统计；
  - **挑选个别格子下结论的逻辑**: **存在局部定向挑选**。在 CLI 打印主入口中，代码专门将 `KSFO Summer` 过滤出来作为独立高亮块打印到终端（第 478–483 行）。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 478–483 行：
```python
478:     ksfo_summer = res["table_stratified"][
479:         (res["table_stratified"]["station"] == "KSFO") & (res["table_stratified"]["season"] == "Summer")
480:     ]
481:     print("\nHighlight: KSFO Summer Diagnostic View:")
482:     print(ksfo_summer.to_string(index=False))
```

---

### D 组：Brier 技能分

#### Q10. 气候基线怎么定义？
- **回答**:
  - 基线概率取自 **2000–2018 训练窗内各站×各月的历史实测气温分布**；
  - **严格采用了留一法（Leave-One-Year-Out, LOYO）杜绝自证泄漏**。在计算年份 $y$ 的某一天所面临的档位气候概率时，历史样本池严格剔除了年份 $y$ 的所有实测值（仅使用其余 18 年的历史频数构建经验 CDF）。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 303–326 行：
```python
303: def _build_loyo_climatology_cache(valid_raw: pd.DataFrame):
...
318:     loyo_pool_cache: Dict[Tuple[str, int, int], np.ndarray] = {}
319:     for (st, mo), yr_dict in clim_lookup.items():
320:         all_yrs = list(yr_dict.keys())
321:         for yr in all_yrs:
322:             other_arrs = [yr_dict[y] for y in all_yrs if y != yr]
323:             loyo_pool_cache[(st, mo, yr)] = np.sort(np.concatenate(other_arrs)) if other_arrs else yr_dict[yr]
```

---

### E 组：模式闸门与已发生的触碰

#### Q11. 2019 通道现状
- **回答**:
  - **代码内是否存在 2019 路径**: `scripts/standalone_reliability_check.py` 中**不存在任何 2019 文件路径**（默认路径第 21 行明确指向 `2000_2018_training_arrays.parquet`）；
  - **双模式闸门**: `--mode blind` 与 `--mode cv` **尚未实现**；
  - **触碰历史交代**: 在本工具（`standalone_reliability_check.py` 及 `test_reliability_check.py`）的开发与测试过程中，**零触碰 2019 年任何数据**。

---

#### Q12. 工具开发自测用了什么数据？
- **回答**:
  - **真实数据**: 仅读取了 `data/processed/audit_arrays/2000_2018_training_arrays.parquet`（SHA256: `8f2a84d26aaeaeaaf7050424df6f7d19891d752fb01b89f49d3add79bbaf3a5c`）；
  - **模型文件**: 读取了 Round 3 产出的 JSON 参数文件（`evidence/r6_kmia_parameters.json`、`evidence/r7_tail_parameters.json`），**未加载任何 `data/models/*.pkl` 旧代模型**；
  - **单元测试**: 使用了合成的小型 Pandas DataFrame（`tests/unit/verification/test_reliability_check.py` 中构造的 3 行与合成随机数组）；
  - **输出的结果文件清单**:
    - `evidence/reliability_check_main_global.csv`
    - `evidence/reliability_check_stratified_station_season.csv`
    - `evidence/reliability_check_brier_skill.csv`
    - `evidence/reliability_check_spec_notes.md`

---

### F 组：输出与可复算

#### Q13. 输出表结构
- **回答**:
  - **四列完整性**: 输出严格包含 `sample_count_n` ($n$)、`mean_pred_prob` ($\bar{p}$)、`empirical_hit_freq` ($\hat{f}$)、`ci_95_half_width` (CI 半宽)；
  - **低样本段与零样本段标注**:
    - 当 $n=0$ 时，所有均值与偏差赋值为 `NaN`，`is_outside_ci=False`；
    - 当 $n>0$ 且 $\hat{f} \in \{0, 1\}$ 时，采用 Wilson 评分区间修正半宽；
    - **遗漏点**: 尚未对 $0 < n < 30$ 的低样本段添加 `WARNING_LOW_N` 显式文本标签；
  - **静默丢弃**: **绝无静默丢弃**。全量 20 个概率段哪怕 $n=0$ 也全部完整保留行结构输出。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 250–273 行。

---

#### Q14. 复算保证
- **回答**:
  - **零私有状态**: 是，从 Parquet 输入到 CSV 输出完全具备确定性，无外部隐式状态；
  - **项目内部依赖**: **零依赖**。仅导入 Python 标准库 + `numpy, pandas, scipy`，未从 `src.*` 导入任何内部模块。
- **证据文件**: `scripts/standalone_reliability_check.py`，第 10–18 行：
```python
10: import argparse
11: import json
12: import math
13: from pathlib import Path
14: from typing import Dict, Any, Tuple, List, Optional
16: import numpy as np
17: import pandas as pd
18: from scipy import stats, integrate
```

---

## 第三部分：对照预置参考规格的差距自查矩阵

| 维度 | 参考规格要求（第三部分） | 当前实现现状 | 差距判定与重构要点 |
| :--- | :--- | :--- | :--- |
| **归池键** | 按 $p_{\text{pred}}$ 等宽 20 段归池 | 按 $p_{\text{pred}}$ 等宽 20 段归池 | ✅ **符合**，保留当前核心分组逻辑 |
| **交叉验证** | 30 天连续块、抽 10% 补集重拟、20 轮、跨轮离散度 | 全量静态单次推导，无重拟，无抽块 | ❌ **重大差距**。需重构 CV 引擎，嵌入参数重拟循环 |
| **维度覆盖** | (target × lead) 逐格出表为主，站×季为预警层 | 仅支持 18h TMAX 单一切片，仅 3 站 | ❌ **重大差距**。需接入 NWS 真值库与全部 lead times、Min/Max |
| **运行模式** | `--mode cv` 与 `--mode blind` 强制预注册硬锁 | 仅支持无模式限制的单一静态回测 | ❌ **缺失**。需增加运行模式状态机与时间墙拦截拦截器 |
| **基线 BSS** | 留一法/滚动杜绝自证 | 训练窗留一法（LOYO） | ✅ **符合**，算法无自证泄漏，需扩展至双温与全时效 |
| **标签纪律** | 携带模式标签与模型状态标签 (LEGACY-DISEASED) | 输出表头无元数据状态标签 | ❌ **缺失**。表头需统一打标隔离病灶品 |
| **参数防御** | $\sigma$ 塌陷等超物理参数时拦截报错 | 无物理下限防御，静默输出尖锐假峰 | ❌ **漏洞**。需增加参数越界阻断与报警机制 |

---

## 第四部分：涉及代码与数据文件资产清单

- 待调整工具源码: `scripts/standalone_reliability_check.py` (SHA256: `fc8130d6bb906653971008172b67a188f0f5489f7b075d429ce5ebd8e3eb876b`)
- 工具测试套件: `tests/unit/verification/test_reliability_check.py`
- 调试输出文件（冻结前调试产物，不具质量效力）:
  - `evidence/reliability_check_main_global.csv`
  - `evidence/reliability_check_stratified_station_season.csv`
  - `evidence/reliability_check_brier_skill.csv`
  - `evidence/reliability_check_spec_notes.md`
- 输入数据底座（只读）:
  - `data/processed/audit_arrays/2000_2018_training_arrays.parquet` (SHA256: `8f2a84d26aaeaeaaf7050424df6f7d19891d752fb01b89f49d3add79bbaf3a5c`)
  - `data/processed/truth_ghcn_daily/{station}.parquet` (NWS 地面观测真值库)
  - `evidence/pilot_manifest.json`
