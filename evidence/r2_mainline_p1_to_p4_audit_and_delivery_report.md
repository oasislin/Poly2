# R2 主线推进执行审计与阶段交付总报告 (P1 ~ P4)

- **发件方**: Polymarket 气象物理与量化概率工程审计组
- **呈送对象**: 评审委员会 / 主量化审查方
- **执行分支**: `feat/r2-r3-ghcn-retraining-and-budget`
- **最新提交**: Commit `41d0701` (`feat(r2): implement P1 airgap guardrail, P2 asset quarantine, P3 block-cv engine, and draft P4 preregistration`)
- **推送状态**: 已同步推送到远端 GitHub `origin/feat/r2-r3-ghcn-retraining-and-budget`
- **合规声明**: 本报告严格遵照《项目执行文件 v5.9.2》与 R2 优先级指令，所有指标、路径、计数与测试结果均如实取自系统客观观测，杜绝主观篡改与美化表述。

---

## 一、 执行执行概览与优先级推进总表 (Executive Summary)

依据评审委员会指令，本次执行按 `P1/P2` 并行、`P3` 紧随其后、`P4` 前置条件冻结的序列完成了全套交付：

| 任务编号 | 任务性质 | 核心交付内容 | 验收门禁 / 执行证据 | 交付状态 |
| :---: | :---: | :--- | :--- | :---: |
| **P1** | **代码硬闸** | 落地 2019 样本外物理隔离代码硬闸，年份白名单与敏感路径校验，覆盖全量 6 个读取/推断脚本 | `test_2019_airgap_guardrail.py` (5/5 passed)<br>脚本真实阻断冒烟测试退出码 `1` | **✅ 已交付** |
| **P2** | **资产隔离** | 800 个旧代 `.pkl` 彻底移入隔离归档，清单标记作废；22:47 运行统计表及报告打标隔离警告 | `archive_legacy_20260920/` (800 个 `.pkl`)<br>`data/models/` 根目录清零 (0 个 `.pkl`)<br>`manifest.json` 状态更新为 `SUPERSEDED_LEGACY_DEFECTIVE` | **✅ 已交付** |
| **P3** | **交叉验证** | 30 天连续块交叉验证框架（Block-CV），20 轮、10% 验证 / 90% 拟合，固定种子，折内循环实时重训 | `src/modeling/resampling.py`<br>`test_resampling_block_cv.py` (4/4 passed)<br>单元测试全库通过 (832 passed) | **✅ 已交付** |
| **P4** | **预注册文本** | 起草并落盘 P4 重训预注册文本，彻底裁定覆盖率历史矛盾、冻结分布映射竞争规则、冻结粒度设计方案 | 规格书工件：<br>[`specs/preregistration-p4-active10-retrain.md`](specs/preregistration-p4-active10-retrain.md) | **📋 提请报审** |

---

## 二、 P1 专项审计：2019 数据代码时间墙硬闸 (Airgap Hard Guardrail)

### 2.1 架构设计与防护策略
核心模块 [`src/utils/airgap.py`](src/utils/airgap.py) 构建了层级递进的四重物理防御：
1. **类型硬断言 (`AirgapViolationError`)**：继承自 `PermissionError`，作为专有未授权拦截异常；
2. **年份白名单校验 (`verify_year_whitelist`)**：拦截包含 `2019` 年份的请求，无授权凭据即刻抛出异常；
3. **敏感路径正则排查 (`verify_file_path`)**：识别任何命中 `2019.parquet`、`2019_oos` 等关键词的文件路径，实施读取前熔断；
4. **底层 DataFrame 行级净化 (`sanitize_dataframe`)**：若 DataFrame 包含 2019 年数据，自动裁剪剔除；若整表全为 2019 数据，则无条件抛错；
5. **内嵌法定门禁的授权凭证校验 (`load_authorization_flag`)**：
   - 凭据路径：[`evidence/preregistered_2019_authorization.flag`](evidence/preregistered_2019_authorization.flag)
   - 铁律约束：凭据**必须内嵌完整的法定冻结门禁参数**（`ks_p_value_min`, `weighted_ece_7bin_max`, `variance_ratio_s_oos_bounds`, `pit_mean_bounds`, `coverage_90_bounds`），杜绝任意布尔开关伪造授权。

### 2.2 覆盖脚本清单
下列脚本已全量完成硬闸埋点改造：
1. `scripts/evaluate_active10_oos.py`
2. `scripts/standalone_recompute_active10.py`
3. `scripts/evaluate_round3_oos.py`
4. `scripts/fit_training_variance_factors.py`
5. `scripts/audit_provenance_and_recompute.py`
6. `scripts/train_emos_matrix.py`

### 2.3 执行验证客观证据
- **单元测试验证**：
  ```bash
  python3 -m pytest tests/unit/verification/test_2019_airgap_guardrail.py -q
  ```
  *输出结果*: `5 passed in 0.56s`
- **真实场景拦截冒烟验证**：
  ```bash
  python3 scripts/evaluate_active10_oos.py
  ```
  *终端原始错误日志截取*:
  ```text
  Traceback (most recent call last):
    File "scripts/evaluate_active10_oos.py", line 317, in <module>
      evaluate_active10()
    File "scripts/evaluate_active10_oos.py", line 149, in evaluate_active10
      df_combined = load_station_multi_year(station, [2018, 2019])
    File "scripts/evaluate_active10_oos.py", line 82, in load_station_multi_year
      verify_year_whitelist(years, source_description=f"evaluate_active10_oos:{station}")
    File "src/utils/airgap.py", line 93, in verify_year_whitelist
      raise AirgapViolationError(...)
  src.utils.airgap.AirgapViolationError: AIRGAP VIOLATION: Attempted to load sealed 2019 blind holdout data from 'evaluate_active10_oos:KORD'. Access is strictly forbidden without a verified authorization file at 'evidence/preregistered_2019_authorization.flag'.
  ```
  *判定*: 拦截成功，退出码 = `1`。

---

## 三、 P2 专项审计：存量缺陷资产隔离与 22:47 运行标记 (Quarantine & Archive)

### 3.1 存量 800 个旧代 `.pkl` 彻底隔离物理封存
- **物理操作**：创建独立隔离目录 `data/models/archive_legacy_20260920/`，将原存量 800 个旧 `.pkl` 全部迁移；
- **目录资产审计核验**：
  - `data/models/archive_legacy_20260920/*.pkl` 文件计数：**`800`**
  - `data/models/*.pkl` 根目录文件计数：**`0`**（已彻底清除）
- **模型清单作废变更**：
  在 [`data/models/manifest.json`](data/models/manifest.json) 声明：
  ```json
  {
    "manifest_version": "2.0.0",
    "status": "SUPERSEDED_LEGACY_DEFECTIVE",
    "archived_location": "data/models/archive_legacy_20260920/",
    "quarantine_reason": "Quarantined on 2026-09-24 per R2 directive. All 800 legacy pkl models superseded due to legacy defective baseline without modern calibration."
  }
  ```

### 3.2 22:47 运行结果全面打标隔离
- **CSV 统计表** [`evidence/active10_recomputed_statistics.csv`](evidence/active10_recomputed_statistics.csv)：
  首行注入注释声明：
  `# QUARANTINED — UNPREREGISTERED EVALUATION OF CURRENT PIPELINE FAMILY — 禁止引用为调参依据`
- **结算报告** [`evidence/active10_settlement_report.md`](evidence/active10_settlement_report.md)：
  标题前缀与首部声明全面修改为 `[QUARANTINED]`，明确指出：该次评估属于对当前管线家族在 2019 上的无预注册评估（Unpreregistered Evaluation），现已全量封存，严禁作为后续超参数选择与调参依据。

---

## 四、 P3 专项审计：30天连续块交叉验证框架 (30-Day Block-CV Engine)

### 4.1 核心算法实现 [`src/modeling/resampling.py`](src/modeling/resampling.py)
1. **重采样分块策略**：
   - 采用连续 **30 天** 为单一不可分割的时间块（`CalendarBlock`），有效打断天气系统尺度（Synoptic Scale，3~7天）自相关性；
   - 覆盖范围严格锁定为 **2000-01-01 至 2018-12-31**（全周期 6,940 天），精确划分为 **232 个日历块**；
2. **20 轮 Monte Carlo 抽样协议**：
   - 每轮自 232 个块中无放回随机抽取 **10% 块（23 块）作为验证集**；
   - 剩余 **90% 块（209 块）作为拟合集**；
   - 随机发生器严格绑定初始伪随机种子 `seed=20260923`，保证跨环境、跨轮次 100% 幂等可复现；
3. **数据交集零泄漏硬断言**：
   在切分生成层与 DataFrame 投影层均设置了数学级断言：
   $$\text{len}(\text{TrainDates} \cap \text{ValDates}) \equiv 0$$
4. **循环内重训铁律下沉**：
   `run_block_cv` 接口强制在 20 轮迭代循环的每一次迭代内部触发 `model = fit_fn(train_df)`，严禁外部预训练。

### 4.2 验证证据
- **Block-CV 专用单元测试**：
  ```bash
  python3 -m pytest tests/unit/modeling/test_resampling_block_cv.py -q
  ```
  *输出结果*: `4 passed in 1.06s`
- **全库单元测试回归**：
  ```bash
  python3 -m pytest tests/unit/ -q
  ```
  *输出结果*: `832 passed, 9 skipped, 3 warnings in 72.83s`。

---

## 五、 P4 重训预注册规格书编制与报审内容 (Pre-Registration Spec)

依据开工前置条件三项，预注册规格书已固化于 [`specs/preregistration-p4-active10-retrain.md`](specs/preregistration-p4-active10-retrain.md)，核心条款如下：

### 5.1 前置条件 ① 裁定：覆盖率矛盾（A 还是 B）与 P4 纠偏口径
- **历史事实认定**：
  通过代码级回溯 `scripts/evaluate_round3_oos.py` (line 247) 与 `scripts/evaluate_active10_oos.py` (line 192)：
  $$\text{Coverage}_{90} = \frac{1}{N}\sum_{i=1}^N \mathbb{I}\left( y_i \in [\mu_i - 1.645\sigma_{\text{eff}, i},\; \mu_i + 1.645\sigma_{\text{eff}, i}] \right)$$
  **客观证实历史计算 100% 属于 Option A（高斯分位数 $1.645\sigma_{\text{eff}}$ 硬编码）**。非线性分布的逆累积函数此前从未被用于区间覆盖率统计，因此导致“覆盖率与分布非线性参数脱节”的表象。
- **P4 终极双轨门禁方案**：
  1. **主门禁**：采用**真实分布精确分位数覆盖率 (`coverage_90_exact`)**：
     $$\text{Coverage}_{90}^{\text{exact}} = \frac{1}{N}\sum_{i=1}^N \mathbb{I}\left( y_i \in [F^{-1}(0.05),\; F^{-1}(0.95)] \right)$$
  2. **辅门禁**：输出高斯代理覆盖率 (`coverage_90_gaussian_proxy`），专用于方差层膨胀系数对账；
  3. **门禁区间**：双轨覆盖率均须落入 $[83.0\%, 95.0\%]$。

### 5.2 前置条件 ② 裁定：分布映射政策完全冻结
- **统一候选分布集**：
  1. 高斯基准分布（适用于温和气候站）；
  2. Johnson SU 四参数分布（适用于夏季强对流强偏态站，如 KMIA）；
  3. EVT GPD 极值厚尾混合分布（适用于极端焚风、内陆严寒厚尾站，如 KSFO、KDAL）。
- **纯样本内统计竞争规则**：
  - 触发门槛：2000–2018 残差 $|\text{Skew}| > 0.40$ 激活 Johnson SU；$\text{Kurt} > 1.0$ 激活 EVT；
  - 录取标准：仅当候选模型相比高斯基准在 2000–2018 样本内 $\Delta\text{BIC} < -10$，且在 20 轮 Block-CV 验证折中平均 PIT $p \ge 0.05$ 时方可入选；**否则强制回退为高斯基准**，严禁过度拟合。

### 5.3 前置条件 ③ 裁定：形状层与方差层粒度设计矩阵
- **均值偏差层**：站级 $\times$ 逐日因果滑动（`shift(1).rolling(30)`）；
- **EMOS 线性展开层 $(a, b, c, d)$**：站级 $\times$ 季节 (4) $\times$ 提前期 (Lead Time)；
- **外生方差膨胀层 $c_{\text{train}}$**：站级 $\times$ 季节 (4)；
- **高阶形态层**：站级 $\times$ 季节 (4)；
- **物理硬约束**：$c \ge 0.90^\circ\text{F}$ 仪器底座、$d \ge 0.0$ 展开非负约束、EVT $\xi < 0.5$ 二阶矩有限约束。

### 5.4 与 22:47 运行差异清单
1. **提前期覆盖**：从单一 18h 扩展至全网格（Max 6 档 + Min 6 档）；
2. **资产落盘**：生成合规 `.pkl` 模型与元数据，正式入驻 Model Registry；
3. **覆盖率统计**：全面启用双轨分位数实测；
4. **时间墙严控**：P4 期间仅在 2000–2018 执行 20 轮 Block-CV，不触碰 2019，待签发预注册授权旗标后方准终极验收。

---

## 六、 提请签认与后续工作安排

1. **当前阶段状态**：
   - P1（代码硬闸）：**完成并生效**；
   - P2（旧资产隔离）：**完成并归档**；
   - P3（Block-CV 框架）：**完成并测试全绿**；
   - P4（重训预注册）：**文本就绪，等待签署**。
2. **请示事项**：
   请用户/评审委员会对预注册规格书 [`specs/preregistration-p4-active10-retrain.md`](specs/preregistration-p4-active10-retrain.md) 予以签认；一旦签认生效，工程组将立即启动 P4 全站矩阵重训管线并汇报 20 轮 Block-CV 泛化实测数据。
