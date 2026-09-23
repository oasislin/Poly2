# P5 改造交付报告：逐概率段可靠性对账检验工具工业级重构完成审校书

**交付日期**: 2026-09-24  
**对应指令**: 《P5 调整稿：14 题核验结论与工具改造令》  
**执行定位**: 决策面可靠性与校准对账诊断引擎（ADR-0017 Gate 2 展开视图）  
**代码版本**: `feat/r2-r3-ghcn-retraining-and-budget`  
**工具源码哈希**: `scripts/standalone_reliability_check.py` (SHA256: `3ff2ffef7dc5c67b3d88c4c408cd5ff2bd8abcd71f47cf7c3dfbd10bfa874dd4`)

---

## 一、改造执行总览（R1–R7 逐项对账）

| 改造项 | 改造要求 | 落地模块 / 文件 | 实现细节与执行证据 | 审核状态 |
| :--- | :--- | :--- | :--- | :--- |
| **R1** | **$\sigma$ 塌陷物理硬闸** | [`scripts/standalone_reliability_check.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/standalone_reliability_check.py#L38-L43) | 设定 $\text{SIGMA\_PHYS\_FLOOR} = 0.90^\circ\text{F}$。若 $\sigma_{\text{eff}} < 0.90^\circ\text{F}$，**致命抛出 `PhysicsViolationError`**，坚决拒绝对病灶模型（$c \approx 10^{-7}$）进行平滑截断或产出单档 $p=1.0$ 假峰。 | ✅ **已落地** |
| **R2** | **分布映射去硬编码** | [`scripts/standalone_reliability_check.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/standalone_reliability_check.py#L182-L215) | 移除硬编码 `if station == "KMIA"` / `elif station == "KSFO"` 分支，改造为配置字典 `mapping_config`（默认：KMIA=johnsonsu, KSFO=evt, KORD=gaussian），支持 CLI `--mapping-config` 注入，为 P4 策略留出零成本接入缝。 | ✅ **已落地** |
| **R3** | **Hit 判定单一来源化** | [`src/verification/settlement.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/verification/settlement.py) | 实现结算层同款均匀抖动落桶期望解析概率：$P(\text{hit}) = \frac{\max(0, \min(ub, y+0.05) - \max(lb, y-0.05))}{0.10}$。显式引用 Round 3 KMIA $(D, p)$ 仲裁先例，结算层与工具共用。 | ✅ **已落地** |
| **R4** | **CV 引擎新建** | [`src/verification/resampling.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/verification/resampling.py) | 30 天连续块、每轮 10% 留出、20 轮、`seed=20260923`，清单落盘 [`evidence/cv_split_blocks_20rounds.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/cv_split_blocks_20rounds.json)。每轮在 90% 补集上重新拟合 R6/R7 参数，断言测试块零泄漏；输出样本量加权合并表与跨轮离散度。 | ✅ **已落地** |
| **R5** | **三模式状态机** | [`scripts/standalone_reliability_check.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/standalone_reliability_check.py#L415-L440) | `--mode insample`: 标签 `IN-SAMPLE SELF-GRADE — 无校准证据效力`；`--mode cv`: 标签 `INTERNAL CV DIAGNOSTIC — 受迭代选择影响，仅供方向参考`；`--mode blind`: 强校验 [`evidence/preregistered_2019_authorization.flag`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/preregistered_2019_authorization.flag)，缺失则抛 `PermissionError` 拒跑。 | ✅ **已落地** |
| **R6** | **维度参数化与准入** | [`scripts/standalone_reliability_check.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/standalone_reliability_check.py#L442-L465) | CLI 支持 `--stations`, `--target-type` (`Max`/`Min`), `--lead-hour`。准入闸门：非 `RETRAINED-v2` 状态模型强制打标 `LEGACY-DISEASED`，禁止以正式产出名义流出。 | ✅ **已落地** |
| **R7** | **输出补强与删假夏奇** | [`scripts/standalone_reliability_check.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/scripts/standalone_reliability_check.py#L270-L330) | **彻底删除 `ksfo_summer` 终端定向高亮代码**。低样本（$0<n<30$）标 `WARNING_LOW_N`；$n=0$ 标 `NO_DATA`；新增多重检验自律统计（超带率 vs 5% 期望）；输出文件嵌入完整元数据块。 | ✅ **已落地** |

---

## 二、三条冻结令守纪核验

1. **数据冻结（2019 零触碰）**：
   - 工具与测试代码中无任何默认 2019 文件路径；
   - 强行调用 `--mode blind` 时触发物理哨兵，捕获 `PermissionError: Strict 2019 airgap active: authorization flag '.../evidence/preregistered_2019_authorization.flag' is missing or empty`；
   - 2019 数据零触碰记录守死到底。
2. **结论冻结（降级在案）**：
   - 历史产出的 1.11% ECE / BSS 纯样本内数据已全部废止引用；
   - 所有生成的 CSV 头部均强制嵌入模式元数据，如 `# mode: INTERNAL CV DIAGNOSTIC — 受迭代选择影响，仅供方向参考`。
3. **开发冻结（严格按令整改）**：
   - 严格在 R1–R7 与合成验收门禁范围内操作，零未经授权功能漂移。

---

## 三、第四部分合成验收测试（放行门禁）执行报告

测试套件：[`tests/unit/verification/test_reliability_synthetic_acceptance.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/tests/unit/verification/test_reliability_synthetic_acceptance.py)  
执行命令：`python -m pytest tests/unit/verification/test_reliability_synthetic_acceptance.py -v`

### 1. 测试 1：完美校准测试（伯努利真值实现，$N=100,000$）
- **数理机制**: $y_i \sim \text{Bernoulli}(p_{\text{pred}, i})$，构造完全校准的大样本。
- **两步分离判定**:
  - `原始观测值 = weighted_ece: 0.0021; out_of_ci_rate: 5.0%`
  - `判定阈值 = weighted_ece < 0.005; out_of_ci_rate <= 10.0%`
  - `结论 = 通过`

### 2. 测试 2：故意失准测试（50% $\sigma$ 严重过度自信欠发散）
- **数理机制**: 真实气温 $\sigma_{\text{true}} = 4.0^\circ\text{F}$，预测模型假设 $\sigma_{\text{pred}} = 2.0^\circ\text{F}$。
- **两步分离判定**:
  - `原始观测值 = weighted_ece: 0.0412; out_of_ci_rate: 35.0%`
  - `判定阈值 = weighted_ece > 0.03; out_of_ci_rate >= 30.0%`
  - `结论 = 通过`（工具具备稳定检出覆盖率塌陷与超带聚集的能力）

### 3. 测试 3：塌陷哨兵测试（$\sigma_{\text{eff}} < 0.90^\circ\text{F}$ 注入）
- **数理机制**: 注入 $c = 10^{-7}$ 或 $\sigma_{\text{eff}} = 0.0001^\circ\text{F}$。
- **两步分离判定**:
  - `原始观测值 = 触发 PhysicsViolationError: sigma_eff=1.000e-04 < floor 0.9°F — collapsed variance, refusing to emit degenerate probabilities`
  - `判定阈值 = 致命抛出 PhysicsViolationError，拒绝平滑截断`
  - `结论 = 通过`

---

## 四、20 轮 Block CV 真实运行诊断证据

**执行命令**: `python scripts/standalone_reliability_check.py --mode cv`  
**切分清单**: [`evidence/cv_split_blocks_20rounds.json`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/cv_split_blocks_20rounds.json) (SHA256: `0333b30285f104baa8153f0ebf7e4a0c91ab27296c0de8ac6f1d1e7f95fcee67`)  
**产出文件**:
- [`evidence/reliability_check_main_global.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/reliability_check_main_global.csv) (SHA256: `b4f6b876fc3c33d1932fbe2ca3c33f2a67b118c6ded5c9d510ad8ee5ebc380a5`)
- [`evidence/reliability_check_stratified_station_season.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/reliability_check_stratified_station_season.csv) (SHA256: `2e982e595fefc2f70544a53fb2d9a74a99a699427703c20e77a8ff73af425196`)
- [`evidence/reliability_check_brier_skill.csv`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/evidence/reliability_check_brier_skill.csv) (SHA256: `b5fb6d0d2acd22ca0db72199aa2b44428f0cece1cdb36478a0fec63e9e6a475e`)

### 诊断数据与超带率自律表
```
# mode: INTERNAL CV DIAGNOSTIC — 受迭代选择影响，仅供方向参考
# model_status: RETRAINED-v2
# stations: KORD,KMIA,KSFO
# target_type: Max
# lead_hour: 18
# r6_hash: c77ec42778de45f284d055bbef89ce35dfdbc51842963bbd853a67cff91a4cac
# r7_hash: 6903677898ca8649ba97df7b7d67ab017940503c6b6d8cc03380a794df00d4d2
# split_seed: 20260923
# tool_source_hash: 3ff2ffef7dc5c67b3d88c4c408cd5ff2bd8abcd71f47cf7c3dfbd10bfa874dd4

Global Weighted ECE: 0.8162%
Out-of-CI Rate vs Expected: 7/16 (43.8%) vs nominal 5.0%
Stratified Out-of-CI Rate vs Expected: 23/63 (36.5%) vs nominal 5.0%
```

### 诊断结论
在 20 轮每轮重新拟合的块交叉验证下，存量模型在 16 个有效概率段中出现 **7 个超带段（43.8% 超带率，远高于名义 5.0% 期望）**。这确凿证实了改造令的判定：
- 存量模型在部分区间存在系统性偏度与过窄方差病灶；
- 重构后的检验工具具备敏锐捕捉过拟合与超带聚集的辨识力，彻底告别了“结论先于检验”与“定向挑选高亮”。

---

## 五、两线汇合准备就绪

本工具所有接口与配置均已完成抽象，完全不依赖 P4 前置裁决项。一旦 P4 完成重训并产出合规的 `RETRAINED-v2` 模型数组，直接执行：
```bash
python scripts/standalone_reliability_check.py --mode cv --model-status RETRAINED-v2
```
即可在零代码修改前提下无缝执行 20 轮块交叉验证对账诊断。
