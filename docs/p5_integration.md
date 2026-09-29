# P5 可靠性抽检门禁快速接线指南 (P5 Reliability Gate Integration Guide)

- **适用对象**: 主线模型训练研发（Phase 2/3 模型迭代与生产定型）
- **核心原则**: **`GateReport` 是主线与 P5 检验引擎之间的唯一契约**。主线训练代码禁止直接 import P5 内部脚本或算法函数，以确保底层演进时外部接口零破裂。
- **接线耗时**: 约 5 分钟。

---

## 一、 快速接入：最小可运行示例 (Minimal Runnable Example)

```python
import numpy as np
import pandas as pd
from src.verification import run_reliability_gate, GateReport

# 1. 准备模型训练产物的预测概率流与二元结算真值 (5,000 ~ 50,000 条)
n_samples = 10000
rng = np.random.default_rng(42)

# 模型输出预测概率 (p_pred) 与实际发生指示 (hit)
p_pred = rng.uniform(0.05, 0.95, size=n_samples)
hit = rng.binomial(1, p_pred).astype(float)

predictions_df = pd.DataFrame({
    "p_pred": p_pred,
    "hit": hit
})

# 2. 调用 P5 统一门禁 (一行接通)
report: GateReport = run_reliability_gate(
    predictions=predictions_df,
    config={
        "max_ece": 0.05,        # 允许的最大加权 ECE (默认 0.05)
        "min_coverage": 0.90,   # Wilson 95% 置信区间最低覆盖率 (默认 0.90)
    }
)

# 3. 结构化报告解读与上线判定
print(f"门禁是否放行:        {report.passed}")
print(f"加权 ECE:            {report.weighted_ece:.4f} (95% CI: [{report.ece_ci_lower:.4f}, {report.ece_ci_upper:.4f}])")
print(f"Brier Skill Score:   {report.bss:.4f}")
print(f"Wilson 覆盖率:       {report.wilson_coverage_rate * 100:.1f}%")
print(f"是否属于退化全同流:   {report.is_degenerate}")
print(f"S-Ladder 各阶梯状态: {report.s_ladder_status}")

# 4. 训练阻断断言 (CI/CD 门禁接入)
if not report.passed:
    raise RuntimeError(f"模型未通过 P5 生产可靠性门禁: {report.error_message}")
```

---

## 二、 格式支持：支持预测分布参数输入

除直接传入 `p_pred` 与 `hit` 外，`run_reliability_gate` 亦支持直接传入气温预测分布参数：

```python
# 支持包含真实观测温度与模型预报均值/方差的 DataFrame
forecast_df = pd.DataFrame({
    "obs": [72.5, 68.0, 75.1, ...],          # 观测实测温标 (°F)
    "mu": [71.8, 69.2, 74.0, ...],           # 模型预测均值 (°F)
    "sigma": [2.3, 1.8, 2.5, ...],           # 模型预测标准差 (°F, 必须 >= 0.90°F)
})

report = run_reliability_gate(forecast_df)
assert report.passed is True
```

---

## 三、 结构体契约：`GateReport` 字段速查

| 字段名 | 类型 | 说明 | 判定放行标准 (Default) |
| :--- | :--- | :--- | :--- |
| `passed` | `bool` | 全局门禁布尔判定（主线仅需判断此项） | 必须为 `True` |
| `weighted_ece` | `float` | 样本加权期望校准误差（Weighted ECE） | $\le 0.05$ (5.0%) |
| `ece_ci_lower` | `float` | 1,000 次确定性 Bootstrap 的 ECE 95% 置信下界 | 供审计记录 |
| `ece_ci_upper` | `float` | 1,000 次确定性 Bootstrap 的 ECE 95% 置信上界 | 供审计记录 |
| `bss` | `float` | 相对气候基线的 Brier 技能得分 | $\ge 0.0$ (具备正向预测技能) |
| `wilson_coverage_rate`| `float` | 各概率档 Wilson 95% 置信区间的实际覆盖比例 | $\ge 90.0\%$ |
| `ks_stat` | `float` | PIT 序列对比均匀分布的 K-S 统计量 | $\le 0.05$ |
| `is_degenerate` | `bool` | 是否属于方差塌缩的“全同值退化死模型” | 必须为 `False` |
| `s_ladder_status` | `dict` | 包含 S1(防御) ~ S5(拟合) 的子阶梯布尔值 | 全项为 `True` |
| `error_message` | `Optional[str]` | 未通过时的法定诊断报错信息 | 通过时为 `None` |

---

## 四、 异常与防御行为

1. **退化死模型拦截**: 当模型训练失败导致所有样本预测概率全为同一常数时，`report.is_degenerate == True`，`report.passed == False`，自动阻断入仓；
2. **物理下限硬拦截**: 任意样本 $\sigma_{\text{forecast}} < 0.90^\circ\text{F}$ 时，门禁直接标记失败并记录物理违规；
3. **序列单调性逆序拦截**: 出现概率升高但发生频率明显下降（倒挂逆序）时，`s_ladder_status["S3_monotonicity"]` 标记 `False`。
