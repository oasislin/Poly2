# Polymarket 天气套利系统：参数标定与联合优化算法技术文档

> **文档版本**: v1.0.0  
> **更新时间**: 2026-07-25  
> **适用对象**: 量化工程师、策略回测研究员、外部自动化测试工具  
> **存储路径**: `Polymarket-Weather-Arbitrage/Polymarket天气套利参数标定与算法说明文档.md`

---

## 1. 系统架构概述与核心设计

本 Polymarket 天气套利系统是一个两阶段（Two-Stage）的量化交易系统：

1. **第一阶段：Analyst 物理与统计气象概率预测**
   - **偏置纠偏 (Bias Correction)**：基于历史 6 天的实际观测与预报偏差（ME, Mean Error）和标准差（StdDev），动态修正预报温度与不确定性。
   - **动态极值时刻判定 (DEHO)**：根据当地时区与气候特征（如最高温通常在 14:00~16:00，最低温在 05:00~07:00），提取参考时刻。
   - **条件时序高斯模拟 (CHSM)**：结合当前已有实况最高/最低温（`so far`），以自回归（$\rho=0.85$）条件高斯时序模拟未来剩余小时数，生成区间概率向量 $P = (p_1, p_2, \dots, p_K)$。

2. **第二阶段：Strategy 金融 sizing 与风控下注**
   - **物理噪声自适应资金调控 ($\gamma$)**：利用高斯噪声标准差 $\sigma$ 计算缩水因子 $\gamma$。
   - **时间自适应胜率收缩**：随距离结算时刻越近，胜率边界收缩越强。
   - **稳健凯利公式 (Robust Kelly)**：
     $$f^* = \text{clamp}\left( \theta \cdot \frac{p \cdot b - (1 - p)}{b} \cdot e^{-\eta \cdot \text{StdDev}}, 0, f_{\text{max}} \right)$$
     其中 $\theta$ 为安全缩放乘数，$\eta$ 为尾部不确定性惩罚指数。

---

## 2. 参数标定的数学模型与网格搜索空间

系统的全局表现由 3 个核心参数联立决定：

| 参数符号 | 配置键名 | 含义与作用 | 探索网格 (Grid Space) |
| :---: | :--- | :--- | :--- |
| **$\sigma_{\text{mid}}$** | `obs_error_sigma_baseline_mid_lat` | 中纬度站点物理预报噪声基准下限 (°C) | `[0.5, 0.7, 0.9, 1.2]` |
| **$\theta$** | `robust_kelly_theta` | 分数凯利资金分配乘数 (Kelly Multiplier) | `[1.0, 1.5, 2.0]` |
| **$\eta$** | `robust_kelly_model_uncertainty_eta` | 模型尾部不确定性缩水惩罚因子 | `[0.15, 0.25, 0.35]` |

- 组合总数：$4 \times 3 \times 3 = 36$ 组参数组合。
- 热带站点噪声基准由 $\sigma_{\text{mid}}$ 导出：
  $$\sigma_{\text{tropics}} = \text{clamp}(0.8 \cdot \sigma_{\text{mid}}, 0.4, 1.0)$$

---

## 3. 回测数据集结构与反事实决策点

标定脚本基于项目真实抓取的 30 天历史快照数据集进行盲测：

- **数据存储位置**：`storage/archive/*.json`（包含 24,990 个历史快照）。
- **实况结算数据库**：`storage/weather_cache.db` (`weather_daily_cache` 表，包含各个气象站已结算的真实日极端温度 `obs_extreme`)。
- **完备决策点筛选规则**：
  1. 快照中必须包含 Polymarket 盘口挂单（`market_snapshot`）、订单簿深度与对应时刻预报（`raw_forecast`）。
  2. 气象站与结算日期必须在 `weather_daily_cache` 中找到已被气象台确认的实际最值 `obs_extreme`。
  3. 通过实况最值判定具体哪个概率区间中奖（Winning Range / Winning Condition）。

---

## 4. 关键 Python 代码与模块入口

若要在外部工具（如 Custom Script, Go/C++ 引擎, Jupyter, 外部测试框架等）中进行测试或调调用，主要代码文件及关键函数如下：

### 4.1 Analyst 预测模块：`src/analyst.py`
```python
from src.analyst import analyze_single_market

# 输入：market_snapshot JSON 文件路径
# 输出：生成的概率文件路径（存入 PROTOCOLS_DIR），格式为 probability_report_{market_id}.json
prob_filename = analyze_single_market(snapshot_json_path)
```

### 4.2 Strategy 决策模块：`src/strategy.py`
```python
from src.strategy import calculate_single_strategy

# 输入：market_snapshot JSON 路径，probability_report JSON 路径
# 输出：生成的下注信号路径，格式为 execution_signals_{market_id}.json
sig_filename = calculate_single_strategy(snapshot_json_path, prob_json_path)
```

### 4.3 PnL 评估与结算计算
单次下注的 PnL 评估逻辑（在回测中计算真实收益）：
```python
def evaluate_pnl(sig_output, winning_cond, market_snapshot):
    total_stake = 0.0
    total_payout = 0.0
    wins = 0
    total_bets = 0
    
    signals = sig_output.get("execution_signals", [])
    range_prices = {r["range_id"]: r.get("ask_price", 0.5) for r in market_snapshot.get("ranges", [])}
    
    for sig in signals:
        action = sig["action"]
        stake = sig["recommended_stake_usdc"]
        cond = sig["condition"]
        range_id = sig["range_id"]
        
        if stake <= 0.0 or action not in ["BUY_YES", "BUY_NO"]:
            continue
            
        total_bets += 1
        price = range_prices.get(range_id, sig.get("market_ask", 0.5))
        if price <= 0:
            price = 0.01
            
        shares = stake / price
        total_stake += stake
        
        is_yes = (action == "BUY_YES")
        is_winning_cond = (cond == winning_cond)
        
        won = (is_yes and is_winning_cond) or (not is_yes and not is_winning_cond)
        if won:
            total_payout += shares
            wins += 1
            
    profit = total_payout - total_stake
    return total_stake, total_payout, profit, wins, total_bets
```

---

## 5. 性能优化建议与外部测试注意事项

如果您希望使用第三方工具或其他回测框架重新测试或运行标定，请特别注意以下内存与 IO 优化要点：

1. **避免全局多进程一次性在内存中全量驻留**：
   - 全量 13,916 个决策点在 4 种 $\sigma$ 参数下的概率结果字典极其庞大，若直接存在 RAM 中（如 Python 列表），多进程 `fork` 或反序列化时会触发内存拷贝，极其容易造成 **macOS RAM 爆满/OOM 崩溃**。

2. **避免 SQLite 在多进程下的高频写锁竞争**：
   - 若将概率向量频繁写入/读取同一个 SQLite 文件，多进程锁竞争会导致 **95% 以上的时间全卡在 OS 文件锁挂起状态**，使回测几乎停滞。

3. **推荐的最佳优化架构（Chunking + Disc File Cache）**：
   - **分批处理 (Chunking)**：按时间或按批次（例如每次 1,000 个快照）分块推演。
   - **独立临时文件隔离**：为每个工作进程 (Process/Worker) 分配独立的临时文件目录（如 `worker_{PID}/`），计算完立刻清空临时文件。
   - **按需加载 (Lazy Loading)**：阶段 2 在推演某组参数组合时，随用随读，读完立即释放内存句柄。

---

## 6. 参数保存配置文件与交互格式

最终标定出的最优参数配置约定持久化落盘至以下 JSON 文件，策略主程序启动时会自动加载：

**文件路径**：`storage/calibrated_financial_params.json`

**格式规范**：
```json
{
  "calibrated_at": "2026-07-25T11:00:00.000000",
  "best_params": {
    "obs_error_sigma_baseline_mid_lat": 0.5,
    "obs_error_sigma_baseline_tropics": 0.4,
    "robust_kelly_theta": 2.0,
    "robust_kelly_model_uncertainty_eta": 0.35
  },
  "backtest_performance": {
    "total_stake_usdc": 315082.15,
    "total_profit_usdc": 422290.49,
    "roi_pct": 134.02,
    "win_rate_pct": 42.4,
    "max_single_loss_usdc": 100.0
  }
}
```

---

*（本文档已保存在项目根目录下，方便您随时使用其他工具或自定义框架读取并开展测试。）*
