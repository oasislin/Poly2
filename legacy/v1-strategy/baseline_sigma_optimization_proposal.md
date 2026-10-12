# 📈 Polymarket 天气套利策略：关于临近结算期基准噪声限制（baseline_sigma）的优化提案

## 1. 核心问题背景

在对 `highest-temperature-in-madrid-on-july-21-2026` 盘口进行异常分析时，我们发现修正了取整 Bug（Floor 改为 Round）后，模型计算出的 `37°C` 胜率（16.43%）与 Polymarket 实际盘口定价（75%）的绝对偏差不仅没有缩小，反而从 38.3% 扩大到了 58.6%。

其根本原因在于模型中的 **硬性基准噪声下限（`baseline_sigma = 1.2°C`）在临近结算时未进行合理衰减**：
1. **结算临近**：事件发生在下午 17:00，当前时间为 12:45，距离结算仅剩 4.25 小时。
2. **实际波动小**：此时气象站当天已发生的实况温度已达 30.0°C，且短时预测精度极高。根据最近 7 天滚动误差计算，真实预测标准差（`rolling_sigma`）仅为 **0.387°C**。
3. **强制 Clamp 稀释胜率**：模型目前的逻辑是 `base_sigma = max(rolling_sigma, baseline_sigma)`。强制使用中纬度基准下限 `1.2°C`。
4. **蒙特卡洛过度吹散**：强制使用 1.2°C 的大标准差在临近结算时注入了过多的噪声，导致原本大概率收敛于 `37°C` 的预测值被强行分摊至 `36°C` 到 `40°C` 档位，从而低估了高概率档位，错失了尾盘下注的最佳 Edge。

---

## 2. 优化建议：引入临近结算的噪声衰减因子 (Uncertainty Time-Decay)

为了在远期预报时保持保守（防止 Kelly 爆仓），同时在临近结算期允许概率快速收敛（捕捉高确定性的尾盘 Edge），建议对 `baseline_sigma` 引入一个**基于剩余时间（Hours to Maturity）的自适应衰减系数**。

### 2.1 衰减数学公式设计

令 $t$ 为距离结算的剩余小时数（`hours_to_maturity`），$T_{fade}$ 为噪声开始衰减的特征时间窗口（例如设为 12 小时）：

当距离结算时间 $t < T_{fade}$ 时，基准标准差 $Baseline(t)$ 应当随时间自适应收敛至真实的测量/预测误差下限（例如设为 $0.2\text{°C}$），具体公式如下：

$$Baseline(t) = \sigma_{final\_min} + (Baseline_{static} - \sigma_{final\_min}) \times f(t)$$

其中衰减因子 $f(t)$ 可以采用线性或平滑的 Sigmoid 曲线。例如采用简单的线性截断衰减：

$$f(t) = \min\left(1.0, \frac{t}{T_{fade}}\right)$$

对于马德里（$t = 4.25$ 小时），衰减后的 $Baseline(4.25)$ 大约只有：
$$0.2 + (1.2 - 0.2) \times \frac{4.25}{12} \approx 0.55\text{°C}$$
这能使模拟噪声大幅下降，概率向 `37°C` 快速收敛。

### 2.2 影响的核心代码位置

#### 1) `src/analyst.py` ([analyst.py](file:///Users/ericlin/SynologyDrive/Project/Polymarket%E5%A4%A9%E6%B0%94%E5%A5%97%E5%88%A9/src/analyst.py#L311-L320))
在时效衰减计算中，根据 `hours_to_maturity` 对 `baseline_sigma` 进行动态收缩：
```python
# 核心逻辑伪代码：
hours_to_maturity = delta_seconds / 3600.0
fade_window = 12.0 # 结算前 12 小时开始衰减基准噪声
final_min_sigma = 0.2 # 物理测温仪器的最低误差底限

if hours_to_maturity < fade_window and hours_to_maturity > 0:
    decay_ratio = max(0.0, hours_to_maturity / fade_window)
    # 动态调低基准噪声下限
    baseline_sigma = final_min_sigma + (baseline_sigma - final_min_sigma) * decay_ratio
```

---

## 3. 下一步行动计划

在另外的 Conversation 中开展以下任务：
1. **更新配置文件**：在 `config/config.yaml` 的 `risk_control_lock` 中新增 `sigma_fade_window_hours: 12` 和 `sigma_absolute_min_celsius: 0.2`。
2. **重构 `analyst.py` 的噪声计算逻辑**：计算 `hours_to_maturity` 并在此基础上对 `baseline_sigma` 应用时效衰减。
3. **重构 `backtest_loader.py` 的回测逻辑**：确保回测部分也对齐该衰减，以便正确拟合历史尾盘数据的表现。
4. **运行单元测试和历史回测**：验证修改后的回测收益率 and 胜率，评估引入动态噪声衰减后的期望收益提升。
