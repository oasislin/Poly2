# R-1 预报均值与观测真值单位约定与舍入核查报告

- **报告性质**: 修复轮第一批独立交付物 (R-1 Unit Convention & Rounding Audit)
- **审查令条款**: 修复轮执行指令（合并版）第一节
- **执行分支**: `fix/r1-unit-convention-audit`
- **核查范围**: KORD, KMIA, KSFO (2019 全年 365 天样本外及底层 METAR 报文)
- **最终结论判定**: **确认无错位，冷偏差定性为模型偏差** (No Unit/Rounding Misalignment; Cold Bias Confirmed as Model/NWP Bias)

---

## 一、 字段级对照表 (Field-Level Mapping Table)

### 1. 观测真值链路 (Ground Truth Pipeline)
- **原始数据源**: Iowa Environmental Mesonet (IEM) ASOS METAR 数据库 (`data/raw/iem/{station}/2019.csv.gz`)。
- **原始字段名**:
  - `metar`: 完整 METAR 报文文本字符串（包含正文 dry-bulb 与附注 RMK 节段）。
  - `tmpc` / `tmpf`: IEM 数据库端解析字段（摄氏度 / 华氏度，可能包含 null）。
- **RMK T-Group 判定与解析**:
  - **是否包含 RMK T 组**: 是。三站 2019 全年原始报文中，RMK T-Group 覆盖率分别为 KORD 99.76% (114,388/114,664)、KMIA 99.58% (112,989/113,460)、KSFO 99.62% (113,058/113,489)。
  - **解析代码**: `src/pipeline/iem_adapter.py` 第 133~136 行 (`_decode_signed_tenths`) 及 152~155 行 (`parse_metar_extreme_remarks`)：
    ```python
    match_t = re.search(r"(?:^|\s)T([01])(\d{3})([01])(\d{3})(?=\s|$)", metar_text)
    # T sTTT sTTT: s=0 正, s=1 负; TTT 为 0.1°C 精度值
    ```
- **舍入规则比对 (报文值 vs 全精度值)**:
  - 报文正文值 (Body): 整度摄氏度（如 `24/13`，分辨率 $1^\circ\text{C} \approx 1.8^\circ\text{F}$）；
  - 全精度值 (RMK T-Group): 十分之一摄氏度（如 `T02440133` $\implies 24.4^\circ\text{C}$，分辨率 $0.1^\circ\text{C} \approx 0.18^\circ\text{F}$）；
  - 降尺度日最高温提取: `src/data_processing/slicer.py` 第 207~208 行按日聚合各报文最大摄氏度 $T_{\max,\text{all}}^\circ\text{C}$；
  - 华氏度转换公式与发生行: `src/data_processing/slicer.py` 第 69~73 行：
    ```python
    tmax_daily_all_reports_f = round(float(temp_c) * 1.8 + 32.0, 4)
    ```
    实测逐日浮点误差绝对值为 $0.00\text{e}+00$（严格双精度一致）。

### 2. 预报链路 (GEFS Forecast Pipeline)
- **原始数据源**: NOAA GEFS Reforecast Version 12 (0.25° 网格，GRIB2 格式)。
- **GEFS 原始温度字段名与物理单位**:
  - 字段名: `tmax` (2 米最高气温)；
  - 物理单位: **开尔文 (Kelvin, K)**，来自 GRIB2 `step=18h` 报文。
- **转换代码行与系数**:
  - 代码位置: `scripts/audit_provenance_and_recompute.py` 第 87 行：
    ```python
    tmax_18h["temp_f"] = (tmax_18h["value_K"] - 273.15) * 1.8 + 32.0
    ```
  - 系数: 标准绝对零度常数 $273.15\text{ K}$，比例系数 $1.8$，偏移量 $32.0$。
- **预报均值 $\mu_f$ 生成单位**:
  - 集合均值与 EMOS 预测均值全程严格在**华氏度 (°F)** 尺度下拟合与推演。

---

## 二、 逐站点报文格式与一致性确认 (Station-Specific Consistency)

| 站点代码 | 机场全称 | 2019 报文总行数 | RMK T 组配对记录数 | T 组覆盖率 | 报文格式特征与规范配置 |
| :---: | :--- | :---: | :---: | :---: | :--- |
| **KORD** | Chicago O'Hare | 114,664 | 114,388 | **99.76%** | 标准 FAA/NWS ASOS 格式，包含 MADISHF 与 AO2 报文，整点与特报齐全。 |
| **KMIA** | Miami International | 113,460 | 112,989 | **99.58%** | 标准 FAA/NWS ASOS 格式，包含 GHCNH 与 MADISHF 报文，T 组极性符合热带气候。 |
| **KSFO** | San Francisco Int'l | 113,489 | 113,058 | **99.62%** | 标准 FAA/NWS ASOS 格式，Nominal window offset :56 分（按规范自适应匹配）。 |

**确认结论**: KORD、KMIA、KSFO 三站真值文件所用报文格式完全统一，均为标准 NWS ASOS 报文体系，无站点特异性解码异构。

---

## 三、 排除性检查实测数字 (Exclusion Check Numeric Results)

执行脚本: `scripts/check_r1_unit_and_rounding.py`  
完整 stdout 凭据已落盘: [`evidence/r1_exclusion_check_stdout.txt`](https://raw.githubusercontent.com/oasislin/Poly2/fix/r1-unit-convention-audit/evidence/r1_exclusion_check_stdout.txt)

### 1. 报文整度舍入值 vs 全精度 T 组实测统计
| 站点 | 单条报文均值差 (Body - High-Res) | 单条报文平均绝对差 | 日最高温均值差 (Daily Tmax Diff) | 日最高温平均绝对差 |
| :---: | :---: | :---: | :---: | :---: |
| **KORD** | $+0.000025^\circ\text{F} \ (+0.000014^\circ\text{C})$ | $0.037215^\circ\text{F}$ | **$-0.102857^\circ\text{F}$** | $0.107802^\circ\text{F}$ |
| **KMIA** | $-0.000327^\circ\text{F} \ (-0.000181^\circ\text{C})$ | $0.035333^\circ\text{F}$ | **$-0.172088^\circ\text{F}$** | $0.174066^\circ\text{F}$ |
| **KSFO** | $-0.004784^\circ\text{F} \ (-0.002658^\circ\text{C})$ | $0.032245^\circ\text{F}$ | **$-0.094945^\circ\text{F}$** | $0.120659^\circ\text{F}$ |

### 2. 特报 (SPECI) 极值贡献 vs 原始冷偏差量级对比
| 站点 | 原始 GEFS 冷偏差 (All-Reports) | 原始 GEFS 冷偏差 (Hourly-Only) | 特报差异贡献 (All - Hourly) | 舍入偏置量级 (Rounding Bias) |
| :---: | :---: | :---: | :---: | :---: |
| **KORD** | **$+3.913567^\circ\text{F}$** | $+3.507704^\circ\text{F}$ | $+0.405863^\circ\text{F}$ | $\approx 0.10^\circ\text{F}$ |
| **KMIA** | **$+3.365164^\circ\text{F}$** | $+2.932671^\circ\text{F}$ | $+0.432493^\circ\text{F}$ | $\approx 0.17^\circ\text{F}$ |
| **KSFO** | **$+4.576648^\circ\text{F}$** | $+4.081031^\circ\text{F}$ | $+0.495616^\circ\text{F}$ | $\approx 0.09^\circ\text{F}$ |

---

## 四、 验收判定 (Acceptance Verdict)

1. **数值量级判定**:
   - 报文舍入偏差贡献的期望值仅为 **$0.09^\circ\text{F} \sim 0.17^\circ\text{F}$**；
   - 特报 (SPECI) 全天峰值捕获贡献约为 **$0.40^\circ\text{F} \sim 0.50^\circ\text{F}$**；
   - 而原始预报链路的系统性冷偏差高达 **$3.36^\circ\text{F} \sim 4.58^\circ\text{F}$**（即使在第一轮 EMOS 拟合后仍残留 $0.74^\circ\text{F} \sim 2.04^\circ\text{F}$）。
   - 舍入误差比冷偏差低 **整整一个数量级**，无法解释冷偏差的主体成因。
2. **二选一法定裁决**:
   - 经全面代码与数据核验，预报链路与真值链路单位绝对一致（均为标准华氏度）、物理常数转换无误、各站点格式完全规整。
   - 正式裁定：**确认无错位，冷偏差定性为模型偏差**（源自 GEFS 粗网格地形下垫面平滑效应与年际气候变暖漂移）。
3. **git diff 说明**:
   - 因未发现任何代码单位转换错误，本次不生成修复代码 diff，保持数据管道原本物理逻辑不变。
