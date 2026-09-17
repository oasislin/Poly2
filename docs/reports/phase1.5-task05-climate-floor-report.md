# Phase 1.5 Task 05: 气候方差下限 Floor 重建质检报告 (Variance Floor Rebuilding)

> **报告版本**：v1.0  
> **生成时间**：2026-09-17  
> **责任团队**：量化模型与气象物理工程组  
> **依据规范**：《项目执行文件 v5.9.2》§5、《Phase 1.5 执行文件 v1.1》§2 Task 05、§4.4  
> **前置依赖**：Task 01（基线封存 `35ecb4b`）、Task 02（生产级适配器 `cd942d4`）、Task 03（特报裁决 ADR-0009 `0ff9d0e`）、Task 04（11 站 27 年原报零偏差落盘 `147b32f`）  
> **终验结论**：**全美 11 活跃站 2000–2018（19年）IEM 高精真值日极值聚合全部完成，31 天滑动窗 + 环形高斯平滑 Floor 曲线重构闭环，严格 OOS 零污染，13 项单测全绿，GEFS 联网冒烟 PASS！**

---

## 1. 任务背景与核心使命

在 Phase 1 原型中，气候方差下限 $\sigma_{\text{clim}}$ 是基于旧 Wunderground 历史日表计算的。经过系统审计，旧数据源已被实证推翻：
1. **系统性偏差与截断误差**：旧 Wunderground 数据存在 $-2.0^\circ\text{F} \sim -5.1^\circ\text{F}$ 的系统性负偏差，且华盛顿（`KDCA`）与上海（`ZSPD`）等历史站点已退役或脱离 NWS 法定结算；
2. **缺乏环形周期平滑**：原滑动窗在跨年分界（12月31日 $\to$ 1月1日）存在阶跃跳变，且未对局部极端偶发天气进行连续物理滤波；
3. **方差坍塌风险**：在 5 成员 GEFS 集合小样本下，集合离散度 $S^2_{\text{ens}} \to 0$ 时容易过度自信。

Task 05 依托 Task 04 落地的高精 IEM ASOS 原始语料（`RMK T` 组 $0.1^\circ\text{C}$ 精度），**全量重建生产级 11 活跃交易站逐日 366 天高精度平滑方差底座曲线 $\sigma_{\text{clim}}(d)$ 与 $\mu_{\text{clim}}(d)$**。

---

## 2. 算法口径与核心设计

```
       [IEM ASOS 2000-2018 Raw Parquet]
                      │
                      ▼ (严格 OOS 隔离: 阻断 2019+)
     [Local Calendar Day Aggregation]
     (IANA Timezone, ADR-0009 Routine+SPECI)
                      │
                      ▼
     [31-Day Circular Sliding Window]
     (DOY 1..366, Half-Window=15 Days)
                      │
                      ▼
     [Periodic Gaussian Filter] (sigma=7.0d, mode='wrap')
     (Seamless Dec 31 -> Jan 1 Transition)
                      │
                      ▼
     [Physical Range Gate & Variance Floor]
     (sigma_floor = max(sigma, 1.5°F), Bound in [1.5, 15.0]°F)
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
[Station Parquets (x11)]    [Central Config]
(data/processed/...)        (configs/climate_floor_v2.json)
```

### 2.1 核心算法实现细节

1. **严格样本外（OOS）纪律**：
   - 算法严格限定 `2000 <= year <= 2018`（19年，每个站点 19 个 Parquet 文件，共计约 500 万条原始观测）。
   - 模块与 CLI 均内置硬性门禁：任何 `year >= 2019` 的输入均触发 `ValueError` 物理熔断。
2. **本地日历日极值聚合 (TMAX / TMIN)**：
   - 依照台站 IANA 官方时区（如 `America/Chicago`、`America/Denver`）切分本地日历日；
   - 遵照 ADR-0009 裁决，保留正点报（METAR）与特殊报（SPECI）在内的所有真实观测，计算日最高温 $T_{\max}$ 与日最低温 $T_{\min}$（$^\circ\text{F}$）。
3. **31 天环形滑动窗气候学统计**：
   - 建立标准闰年参考轴 $d \in [1, 366]$（2月29日 = Day 60，12月31日 = Day 366）；
   - 对每一天 $d$，提取 19 年中环形周期距离 $\text{circ\_dist} = \min(|d-s|, 366-|d-s|) \le 15$ 的所有日极值样本（每窗样本量 $N \approx 570 \sim 589$）；
   - 计算无偏样本标准差 $\sigma_{\text{raw}}(d)$（$ddof=1$）与样本均值 $\mu_{\text{raw}}(d)$。
4. **周期环形平滑 (Periodic Circular Gaussian Smoothing)**：
   - 采用 `scipy.ndimage.gaussian_filter1d(..., sigma=7.0, mode='wrap')`；
   - 严格消除日间高频采样噪声，确保 12月31日 与 1月1日 之间零阶与一阶导数连续，绝对无边界效应跳变。
5. **安全保底与物理门禁 (Variance Floor & Physical Gates)**：
   - 方差保底下限：$\sigma_{\text{floor}}(d) = \max(\sigma_{\text{clim}}(d), 1.5^\circ\text{F})$；
   - 物理区间门禁：全站全日期 $\sigma \in [1.5^\circ\text{F}, 15.0^\circ\text{F}]$（下限防过度自信爆仓，上限防数据畸变）。

### 2.2 物理上限 (15.0°F) 动力学推导与 ADR-0010 溯源

初始交接文档基于 Phase 1 摄氏度原型标注了 $[1.5^\circ\text{F}, 8.0^\circ\text{F}]$，但在全美 11 站实测中，丹佛（KBKF）冬季方差达 $13.74^\circ\text{F}$，芝加哥（KORD）达 $12.91^\circ\text{F}$。为此，项目开立 **`docs/adr/ADR-0010`** 进行了专项动力学裁决与防漂移规范：

1. **单位错位修复**：Phase 1 原型在上海（ZSPD）使用摄氏度 $8.0^\circ\text{C}$，换算为华氏度温差为 $\Delta 8.0^\circ\text{C} \times 1.8 = \mathbf{14.4^\circ\text{F}}$。原交接文档未做乘法换算导致物理阈值缩水 1.8 倍；
2. **数学推导公式**：
   $$\text{FLOOR\_PHYSICAL\_MAX\_F} = \text{round}\Big(\max_{s, d} \sigma_{\text{clim}}(s, d) + \Delta_{\text{buffer}}\Big) = 13.74^\circ\text{F} + 1.26^\circ\text{F} = \mathbf{15.0^\circ\text{F}}$$
3. **参数变更协议 (Change Protocol)**：未来若由于站池扩容或周期调整需变动此参数，严禁随意微调（如改写为 14.5 或 15.5），必须满足 $\ge$ 实测极大值，并依章修订 ADR-0010；测试套件 `test_floor_physical_max_governance_contract()` 机械断言守卫该防漂移红线。

---

## 3. 全美 11 活跃站实测统计数据汇总

基于 2000–2018 年 19 年实测 IEM 观测数据，重建后的 11 站逐日平滑方差底座指标如下：

| 站点代码 | 城市 / 机场名称 | 时区 | 沿海微气候 (`coastal_microclimate`) | TMAX $\sigma$ 区间 (Min / P50 / Max) | TMIN $\sigma$ 区间 (Min / P50 / Max) | 全年平均 $\sigma_{\text{max}}$ | 全年平均 $\sigma_{\text{min}}$ |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`KORD`** | 芝加哥奥黑尔 | America/Chicago | `False` | $6.09^\circ\text{F}~/~10.82^\circ\text{F}~/~\mathbf{12.91^\circ\text{F}}$ | $5.41^\circ\text{F}~/~8.40^\circ\text{F}~/~11.99^\circ\text{F}$ | $10.05^\circ\text{F}$ | $8.75^\circ\text{F}$ |
| **`KLGA`** | 纽约拉瓜迪亚 | America/New_York | `True` | $6.24^\circ\text{F}~/~9.19^\circ\text{F}~/~10.34^\circ\text{F}$ | $4.49^\circ\text{F}~/~7.06^\circ\text{F}~/~9.80^\circ\text{F}$ | $8.62^\circ\text{F}$ | $6.99^\circ\text{F}$ |
| **`KATL`** | 亚特兰大 | America/New_York | `False` | $4.49^\circ\text{F}~/~7.73^\circ\text{F}~/~10.71^\circ\text{F}$ | $2.85^\circ\text{F}~/~8.02^\circ\text{F}~/~10.79^\circ\text{F}$ | $7.67^\circ\text{F}$ | $7.39^\circ\text{F}$ |
| **`KDAL`** | 达拉斯爱田 | America/Chicago | `False` | $4.88^\circ\text{F}~/~8.49^\circ\text{F}~/~12.39^\circ\text{F}$ | $3.72^\circ\text{F}~/~8.33^\circ\text{F}~/~10.19^\circ\text{F}$ | $8.39^\circ\text{F}$ | $7.55^\circ\text{F}$ |
| **`KSEA`** | 西雅图塔科马 | America/Los_Angeles | `True` | $5.44^\circ\text{F}~/~6.46^\circ\text{F}~/~8.02^\circ\text{F}$ | $3.51^\circ\text{F}~/~4.38^\circ\text{F}~/~6.37^\circ\text{F}$ | $6.48^\circ\text{F}$ | $4.59^\circ\text{F}$ |
| **`KLAX`** | 洛杉矶国际 | America/Los_Angeles | `True` | $3.47^\circ\text{F}~/~6.22^\circ\text{F}~/~7.67^\circ\text{F}$ | $2.41^\circ\text{F}~/~3.53^\circ\text{F}~/~4.44^\circ\text{F}$ | $5.90^\circ\text{F}$ | $3.56^\circ\text{F}$ |
| **`KHOU`** | 休斯顿霍比 | America/Chicago | `True` | $3.79^\circ\text{F}~/~5.98^\circ\text{F}~/~10.62^\circ\text{F}$ | $2.10^\circ\text{F}~/~7.63^\circ\text{F}~/~10.14^\circ\text{F}$ | $6.59^\circ\text{F}$ | $6.97^\circ\text{F}$ |
| **`KMIA`** | 迈阿密国际 | America/New_York | `True` | $\mathbf{2.08^\circ\text{F}}~/~3.86^\circ\text{F}~/~6.20^\circ\text{F}$ | $2.45^\circ\text{F}~/~4.58^\circ\text{F}~/~8.78^\circ\text{F}$ | $3.96^\circ\text{F}$ | $4.95^\circ\text{F}$ |
| **`KSFO`** | 旧金山国际 | America/Los_Angeles | `True` | $3.93^\circ\text{F}~/~6.00^\circ\text{F}~/~7.48^\circ\text{F}$ | $2.55^\circ\text{F}~/~3.47^\circ\text{F}~/~4.82^\circ\text{F}$ | $5.91^\circ\text{F}$ | $3.57^\circ\text{F}$ |
| **`KBKF`** | 丹佛巴克利基地 | America/Denver | `False` | $6.91^\circ\text{F}~/~12.35^\circ\text{F}~/~\mathbf{13.74^\circ\text{F}}$ | $4.00^\circ\text{F}~/~8.03^\circ\text{F}~/~10.67^\circ\text{F}$ | $11.38^\circ\text{F}$ | $7.96^\circ\text{F}$ |
| **`KAUS`** | 奥斯汀机场 | America/Chicago | `False` | $4.50^\circ\text{F}~/~7.60^\circ\text{F}~/~11.69^\circ\text{F}$ | $2.92^\circ\text{F}~/~9.75^\circ\text{F}~/~11.61^\circ\text{F}$ | $7.85^\circ\text{F}$ | $8.86^\circ\text{F}$ |
| **全站综合** | **11 个活跃交易站点** | **四大主时区** | **6 沿海 / 5 内陆** | **$2.08^\circ\text{F} \sim 13.74^\circ\text{F}$** | **$2.10^\circ\text{F} \sim 11.99^\circ\text{F}$** | **$7.53^\circ\text{F}$** | **$6.47^\circ\text{F}$** |

### 3.1 旧版 WU 估算缺陷与新版 IEM 逐日平滑 Floor 演进对比

依交接文档与质检规范要求，对系统从 Phase 1 原型（Wunderground）到 Phase 1.5（IEM ASOS）的底座演进进行全面对比：

| 维度 / 指标 | Phase 1 旧版 WU 历史底座 | Phase 1.5 新版 IEM ASOS 生产底座 | 改进效果与量化价值 |
| :--- | :--- | :--- | :--- |
| **覆盖站点宇宙** | 仅覆盖退役站 `KDCA`、`ZSPD` 及 `KDEN`（其余站缺失） | 全面覆盖全美 **11 个活跃交易站点** | 补全所有核心流动性标的（如芝加哥、纽约、休斯顿等） |
| **观测精度与真值口径** | 网页爬虫抓取，存在整度截断与 $-2.0^\circ\text{F} \sim -5.1^\circ\text{F}$ 系统性负偏差 | ASOS 原始长表，精准解析 `RMK T` 组（$0.1^\circ\text{C}$ 真实物理精度，0.0000°C 偏差） | 彻底消除了数据截断误差与历史负偏差污染 |
| **日历日切分口径** | 依赖第三方网页本地日粗略汇总，存在时区夏令时跳变 | 基于 IANA 标准官方时区（如 `America/Chicago`）严格按 UTC 转换本地日历日 | 杜绝日极值归属漂移与跨日重采样污染 |
| **滑动窗统计深度** | 单点逐年粗糙均值，有效样本量不足 | 31 天环形滑动窗，跨 19 年聚合约 $570 \sim 589$ 条日极值真实物理样本 | 极值样本充分，估计无偏标准差稳定可靠 |
| **年际跨年平滑连续性** | 无平滑机制，12月31日 $\to$ 1月1日 存在明显的阶跃断点跳变 | 采用 `mode='wrap'` 环形周期高斯平滑（$\sigma=7.0\text{d}$） | 保证跨年连续性，$|d=366 - d=1| < 0.15^\circ\text{F}$ 且导数平滑无尖点 |
| **物理上限门禁设定** | 错用摄氏度数值标定 $8.0^\circ\text{F}$（单位混淆），极易在大陆性站点产生误报熔断 | 经 ADR-0010 正式推导标定为 $[1.5^\circ\text{F}, 15.0^\circ\text{F}]$，并由合约测试固化 | 容纳丹佛（$13.74^\circ\text{F}$）和芝加哥（$12.91^\circ\text{F}$）的严冬极涡真实方差，彻底杜绝误熔断与参数漂移 |

---

## 4. 气象物理学规律实证分析

本次 11 站方差底座重建呈现出完全符合经典动力气象学与气候物理学的两大规律：

### 4.1 大陆性 vs 海洋性鲜明对比
1. **强大陆性/高原大平原站点（`KBKF` 丹佛、`KORD` 芝加哥、`KDAL` 达拉斯）**：
   - 丹佛（`KBKF`）冬季最高方差达 **$13.74^\circ\text{F}$**，芝加哥（`KORD`）达 **$12.91^\circ\text{F}$**；
   - **成因**：冬季受极地冷气团南下（Polar Vortex）、落基山焚风（Chinook Winds）及锋面剧烈交替影响，同历日日最高气温跨度可从 $-10^\circ\text{F}$ 剧烈摆动至 $+60^\circ\text{F}$，天然具有极高的气候波动度。
2. **强海洋性/低纬热带站点（`KMIA` 迈阿密、`KLAX` 洛杉矶、`KSFO` 旧金山）**：
   - 迈阿密（`KMIA`）夏季日最高温方差仅 **$2.08^\circ\text{F}$**，旧金山与洛杉矶全年最高方差均被压制在 **$7.6^\circ\text{F}$** 以内；
   - **成因**：海洋巨大热容的平抑调节效应与低纬副热带高压控制，日极值温度日复一日高度收敛。

### 4.2 强烈的冬高夏低季节性波动
- 芝加哥（`KORD`）：夏季 7 月方差低至 $6.09^\circ\text{F}$，冬季 1 月方差飙升至 $12.91^\circ\text{F}$（波动放大 2.1 倍）；
- 达拉斯（`KDAL`）：夏季 8 月受副高稳定控制方差仅 $4.88^\circ\text{F}$，冬季受冷锋切变影响达 $12.39^\circ\text{F}$（波动放大 2.5 倍）。
- **交易指导意义**：在冬季交易大陆性站点二元期权时，模型必须具有足够大的方差底座保护，切忌沿用夏季窄区间先验过度重仓两翼。

---

## 5. 产物交付清单与校验和 (Gate 3 Provenance)

所有重构产物均已落盘，元数据完整收录于 `data/processed/climate_floor/manifest.json`：

| 产物路径 | 文件大小 | SHA-256 校验和前缀 | 说明 |
| :--- | :--- | :--- | :--- |
| `data/processed/climate_floor/KORD_climate_floor.parquet` | 39.2 KB | `fb44482106...` | 芝加哥 366 日双轨方差表 |
| `data/processed/climate_floor/KLGA_climate_floor.parquet` | 39.3 KB | `097de46182...` | 纽约 366 日双轨方差表 |
| `data/processed/climate_floor/KATL_climate_floor.parquet` | 38.7 KB | `2c1f296a98...` | 亚特兰大 366 日双轨方差表 |
| `data/processed/climate_floor/KDAL_climate_floor.parquet` | 38.2 KB | `2ebd5c6da0...` | 达拉斯 366 日双轨方差表 |
| `data/processed/climate_floor/KSEA_climate_floor.parquet` | 38.6 KB | `f1f461cef3...` | 西雅图 366 日双轨方差表 |
| `data/processed/climate_floor/KLAX_climate_floor.parquet` | 38.5 KB | `630c4fdcef...` | 洛杉矶 366 日双轨方差表 |
| `data/processed/climate_floor/KHOU_climate_floor.parquet` | 39.7 KB | `c32f036ab2...` | 休斯顿 366 日双轨方差表 |
| `data/processed/climate_floor/KMIA_climate_floor.parquet` | 37.7 KB | `bfd0b8185e...` | 迈阿密 366 日双轨方差表 |
| `data/processed/climate_floor/KSFO_climate_floor.parquet` | 37.8 KB | `3511e2cdc9...` | 旧金山 366 日双轨方差表 |
| `data/processed/climate_floor/KBKF_climate_floor.parquet` | 39.2 KB | `969de5d16f...` | 丹佛 366 日双轨方差表 |
| `data/processed/climate_floor/KAUS_climate_floor.parquet` | 39.5 KB | `3553d77322...` | 奥斯汀 366 日双轨方差表 |
| `configs/climate_floor_v2.json` | 1.88 MB | `034a49df8e...` | 全美 11 站逐日方差底座中央配置字典 |
| `data/processed/climate_floor/manifest.json` | 6.4 KB | 动态生成 | 完整审计哈希与批处理元数据 |

---

## 6. 质量门禁与验收测试执行

### 6.1 单元测试套件全绿
- 执行命令：`/opt/miniconda3/bin/pytest tests/unit/modeling/test_climate_floor.py tests/unit/modeling/test_gaussian_emos.py tests/unit/modeling/test_crps.py tests/unit/pipeline/test_task04_batch_orchestrator.py -v`
- **实测结果**：**38/38 全部 PASSED（100% 通过，耗时 2.95s）**。
- 涵盖门禁：
  1. OOS 严格隔离测试：传入 2019+ 年份 100% 熔断；
  2. 台站宇宙白名单测试：只允许 11 活跃站，违规站点一律拒绝；
  3. 周期高斯平滑连续性测试：$|d=366 - d=1| < 0.15^\circ\text{F}$ 且导数连续；
  4. 物理合理性值域测试：全站无 NaN、无 Inf，全量 $\sigma \in [1.5^\circ\text{F}, 15.0^\circ\text{F}]$；
  5. 下游 `ClimatologyCalculator` 接口 100% 兼容回归。

### 6.2 GEFS 联网真实冒烟测试（硬性规则）
- 执行命令：`RUN_NETWORK_TESTS=1 /opt/miniconda3/bin/pytest tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message -q`
- **实测结果**：**1 passed, 3 warnings in 32.06s**。真实 AWS S3 GRIB 再预报切片抓取与内存解析畅通无阻，网络链路健康。

---

## 7. 任务交付结论与下游解锁

- **Task 05 状态**：**COMPLETED（已全面完成并闭环）**。
- **核心价值**：彻底终结了旧版 Wunderground 带来的负偏差与方差塌缩隐患，为整个量化预测系统构建了基于 19 年真实 ASOS 极值和高斯平滑的高可靠方差护城河。
- **下游解锁**：正式解锁 **Phase 1.5 Task 06：特征库重建与切片（整点重采样 `:50-:55` + 本地日切片 + 预报-观测特征库对齐）**。
