# Phase 1.5 Task 07: 元数据扩展与单点摄氏度归一化质检终验报告

> **生成时间**：2026-09-19  
> **责任团队**：量化工程与系统质控组  
> **依据规范**：《Phase 1.5 执行文件 v1.1》§2 Task 07、项目方案 (v2.6) §0.1 / §2.3、ADR-0007（数据源重铸与站点宇宙扩展）  
> **前置依赖**：Task 01（基线封存）、Task 06（切片分层与特征库 v2 重建）、ADR-0009、ADR-0010  
> **终验结论**：**中央台站元数据字典 `STATION_METADATA` 全量升级至 v2（Active 11 活跃交易站六要素 100% 齐备，KDCA 彻底退役注销），采集入口单点 ℉→℃ 归一化彻底固化，防篡改契约单测全绿，GEFS 真实网络冒烟通过，准予结项！**

---

## 1. 任务背景与核心使命

随着 Task 06 特征切片分层语料库（11 站 × 27 年 = 107,251 站-日）顺利落盘，系统真值与特征矩阵已完全就绪。
**Task 07 的核心使命是规范中央元数据治理，固化数据管道内部纯摄氏度契约**：
1. **完善中央元数据字典（`STATION_METADATA` v2）**：将全美 Active 11 活跃交易站的六要素属性（经纬度、高程、时区、单位、发报特性与网络标签）全部受控固化；华盛顿 `KDCA` 依据 commit `1b53879` 与 Task 03（PENDING-06）裁决已彻底注销退役，本任务严格执行该决议，彻底剔除 KDCA 残留，保持站点宇宙纯净；
2. **采集入口单点 ℉→℃ 归一化**：确保外部观测源（如 IEM ASOS 原生 `tmpf`）在入口完成单点换算，管道内部全程以标准摄氏度（°C）流动，杜绝物理越界校验 `[-60°C, +60°C]` 被华氏输入误拦截或漏拦截；
3. **扩展自动化契约测试套件**：编写 `test_constants.py` 锁定 Active 11 站六要素防篡改契约与 KDCA 封禁隔离，落地项目方案法定单测 `test_fahrenheit_input_normalized_before_physical_check`；
4. **验证外部依赖与冒烟测试**：执行真实的 GEFS AWS S3 网络冒烟测试，保障外部契约坚固有效。

---

## 2. 交付产物清单与指标对照

| 交付项 / 指标 | 规格要求 | 实际达成 | 结论 |
| :--- | :--- | :--- | :---: |
| **中央元数据模块** | `src/data_processing/constants.py` 升级至 v2 | 齐备 Active 11 站六要素，KDCA 彻底剔除 | ✅ 达标 |
| **活跃站宇宙常量** | `ACTIVE_11_STATIONS` (11 活跃交易站) | KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KBKF, KAUS | ✅ 达标 |
| **单点归一化扩展** | `UnitConverter.normalize_observations` | 支持单站/多站 DataFrame 自动基于元数据单点归一化 | ✅ 达标 |
| **数据校验器适配** | `DataValidator.validate_observations` | 支持 `auto_normalize=True` 与 `normalize_and_validate_observations` | ✅ 达标 |
| **IEM 采集入口后备** | `IemAdapter._parse_single_csv_row` | 当 `tmpc` 缺失时由 `tmpf` 单点转摄氏度入库，增加 `_safe_float` 容错 | ✅ 达标 |
| **元数据契约测试** | `tests/unit/data_processing/test_constants.py` | 11 站 × 6 要素类型、范围、时区合法性断言及 KDCA 隔离断言全量覆盖 | ✅ 100% 绿灯 |
| **法定单测实现** | `test_fahrenheit_input_normalized_before_physical_check` | 验证 86°F 未归一化被拒、归一化后 30°C 顺利通过物理门禁 | ✅ 100% 绿灯 |
| **单元测试回归** | 全量单元测试集 | 633 项单元测试全量通过（0 failures） | ✅ 100% 绿灯 |
| **GEFS 真实网络冒烟** | `test_network_reforecast_single_message` | 真实 NOAA AWS S3 报文检索与切片通过 | ✅ 100% 绿灯 |

---

## 3. 全美 Active 11 活跃交易站六要素元数据总表

依据终审评分卡 v1.1 与项目方案 v2.6 §0.1，受控词表法定属性定义如下：

| 站号 | 城市 | 时区 (IANA) | 单位 | 经度, 纬度 | 海拔 | IEM 网络 | 日发报数 | P50延迟 | 历史覆盖率 | 微气象评分 | 法定准入状态 (`audit_status`) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`KORD`** | 芝加哥 | `America/Chicago` | **℉** | `41.97, -87.90` | 205m | `IL_ASOS` | 311 报 | 19.0m | 99.7% | 98.0 | `ADMITTED_TIER_1` |
| **`KLGA`** | 纽约 | `America/New_York` | **℉** | `40.77, -73.87` | 4m | `NY_ASOS` | 313 报 | 18.2m | 99.6% | 82.0 | `ADMITTED_TIER_1` |
| **`KATL`** | 亚特兰大 | `America/New_York` | **℉** | `33.64, -84.43` | 313m | `GA_ASOS` | 312 报 | 18.0m | 99.7% | 95.0 | `ADMITTED_TIER_1` |
| **`KDAL`** | 达拉斯 | `America/Chicago` | **℉** | `32.85, -96.85` | 148m | `TX_ASOS` | 311 报 | 19.8m | 99.1% | 95.0 | `ADMITTED_TIER_1` |
| **`KSEA`** | 西雅图 | `America/Los_Angeles` | **℉** | `47.45, -122.31` | 132m | `WA_ASOS` | 310 报 | 19.0m | 99.4% | 85.0 | `ADMITTED_TIER_2` |
| **`KLAX`** | 洛杉矶 | `America/Los_Angeles` | **℉** | `33.94, -118.41` | 38m | `CA_ASOS` | 312 报 | 18.5m | 99.5% | 80.0 | `ADMITTED_TIER_2` |
| **`KHOU`** | 休斯顿 | `America/Chicago` | **℉** | `29.65, -95.28` | 14m | `TX_ASOS` | 311 报 | 19.5m | 99.2% | 80.0 | `ADMITTED_TIER_2` |
| **`KMIA`** | 迈阿密 | `America/New_York` | **℉** | `25.79, -80.29` | 3m | `FL_ASOS` | 317 报 | 20.5m | 99.5% | 75.0 | `ADMITTED_TIER_2` |
| **`KSFO`** | 旧金山 | `America/Los_Angeles` | **℉** | `37.62, -122.37` | 4m | `CA_ASOS` | 312 报 | 18.5m | 99.5% | 75.0 | `ADMITTED_TIER_2` |
| **`KBKF`** | 丹佛巴克利 | `America/Denver` | **℉** | `39.70, -104.75` | 1726m | `CO_ASOS` | 25 报 | 21.5m | 98.4% | 70.0 | `ADMITTED_TIER_3_WARNING` |
| **`KAUS`** | 奥斯汀 | `America/Chicago` | **℉** | `30.19, -97.67` | 165m | `TX_ASOS` | 312 报 | 19.2m | 99.2% | 92.0 | `ADMITTED_TIER_2` |

> **注**：`ACTIVE_11_STATIONS` 严格包含上述 11 个活跃交易站点；华盛顿 `KDCA` 因无常态日盘已彻底下线，严禁进入采集与模型管道。

---

## 4. 单点归一化与物理越界防护机制验证

### 4.1 物理边界防护原理
- 系统设定陆地气温绝对物理边界为 **$[-60.0^\circ\text{C}, +60.0^\circ\text{C}]$**；
- 若美国站点观测值（以 ℉ 计量，例如夏季高温 86.0°F ~ 105.0°F）未经摄氏度归一化直接流入 `DataValidator`，数值将因超出 $+60.0$ 被判定为非法异常值并硬性拦截；
- 同理，在寒冷冬季（如 10.0°F = -12.2°C），若未转换为摄氏度，数值 $10.0$ 会被误视作温和的 $+10^\circ\text{C}$，导致极端低温特征失效或遗漏拦截。

### 4.2 采集入口单点归一化落位
1. **`IemAdapter` 采集入口**：优先提取 METAR RMK T 组高精摄氏度（0.1°C 精度）；若 T 组与 `tmpc` 缺失，则在第一入口由 `fahrenheit_to_celsius(_safe_float(row['tmpf']))` 单点转换为摄氏度，内部落盘与派发全程为标准 °C；
2. **`UnitConverter.normalize_observations`**：支持自动读取 DataFrame 中 `station_id`，自适应执行 ℉→℃ 映射转换；
3. **`DataValidator.validate_observations(auto_normalize=True)`**：支持传入前预热归一化，确保下游数据消费零风险。

### 4.3 法定契约单测实测输出
测试用例 `test_fahrenheit_input_normalized_before_physical_check` 实测通过：
```python
# 1. 芝加哥 86.0°F 未经转换直接校验 -> 失败 (86.0 > 60.0°C)
assert not validator.validate_observations(raw_obs, auto_normalize=False).is_valid

# 2. 经 UnitConverter 单点归一化 -> 30.0°C -> 校验通过
norm_obs = converter.normalize_observations(raw_obs)
assert norm_obs["temp_max"].iloc[0] == pytest.approx(30.0)
assert validator.validate_observations(norm_obs).is_valid
```

---

## 5. 测试套件与网络冒烟实测记录

### 5.1 模块单测执行明细
- `test_constants.py`：覆盖 11 站六要素字段存在性、经纬度范围、高程、时区 ZoneInfo 解析、ASOS 网络标签、准入状态、衍生字典同步，以及 KDCA 严格剔除隔离断言全部通过；
- `test_unit_converter.py`：覆盖标量、矢量、XArray、Active 11 站自动转换、多站混合归一化及物理边界拦截单测全部通过；
- `test_data_validator.py`：观测与特征验证用例全部通过。

### 5.2 全量单元测试回归
全量 633 项单元测试无一报错（0 failures），整体系统零衰退。

### 5.3 GEFS 真实网络冒烟测试（硬性铁律）
成功直连 NOAA AWS S3 存储桶，验证 GEFS 再预报单条 GRIB 报文检索、切片与解码契约真实可用。

---

## 6. 任务闭环判定与下一步衔接

本任务已达成全部交付目标：
1. `STATION_METADATA` 升级至 v2，六要素属性与 Active 11 活跃交易站 100% 齐备，KDCA 彻底剔除；
2. 采集入口单点摄氏度归一化已物理固化于适配器与转换器中，包含异常值安全解析防护；
3. 新增 `test_constants.py` 与法定单测 `test_fahrenheit_input_normalized_before_physical_check` 并全部通过；
4. 真实网络冒烟测试绿灯通过。

**下游推进建议**：
准予结项 Phase 1.5 Task 07，下一步正式启动 **Phase 1.5 Task 08：校准数据集发布（`calib-dataset-v2.0`）与 Phase 1.5 终审闭环**。
