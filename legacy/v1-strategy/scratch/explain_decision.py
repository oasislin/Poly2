import os
import json
import glob
import numpy as np
import datetime

# 定义文件路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTOCOLS_DIR = os.path.join(BASE_DIR, "protocols")
ARTIFACTS_DIR = BASE_DIR  # 直接输出到项目根目录下，方便查看，或指定为用户的 artifact 目录

# 用户的 conversation artifact 路径
CONV_ARTIFACT_DIR = "/Users/ericlin/.gemini/antigravity/brain/3a8bba04-9044-4147-a61f-326432e7677a"

def load_newest_shanghai_files(target_date=None):
    # 将 YYYY-MM-DD 转换为 june-26-2026 英文小写格式
    target_date_str = None
    if target_date:
        try:
            dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
            month_name = dt.strftime("%B").lower()
            day = dt.day
            year = dt.year
            target_date_str = f"{month_name}-{day}-{year}"
        except Exception:
            target_date_str = target_date

    # 优先查找上海最高温（highest-temperature）相关的最新文件
    snapshots = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*highest-temperature*shanghai*.json"))
    probs = glob.glob(os.path.join(PROTOCOLS_DIR, "weather_probability_*highest-temperature*shanghai*.json"))
    signals = glob.glob(os.path.join(PROTOCOLS_DIR, "arbitrage_signals_*highest-temperature*shanghai*.json"))
    
    if target_date_str:
        snapshots = [f for f in snapshots if target_date_str in os.path.basename(f)]
        probs = [f for f in probs if target_date_str in os.path.basename(f)]
        signals = [f for f in signals if target_date_str in os.path.basename(f)] if signals else []
    
    if not snapshots or not probs:
        snapshots = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*highest-temperature*zsss*.json"))
        probs = glob.glob(os.path.join(PROTOCOLS_DIR, "weather_probability_*highest-temperature*zsss*.json"))
        signals = glob.glob(os.path.join(PROTOCOLS_DIR, "arbitrage_signals_*highest-temperature*zsss*.json"))
        if target_date_str:
            snapshots = [f for f in snapshots if target_date_str in os.path.basename(f)]
            probs = [f for f in probs if target_date_str in os.path.basename(f)]
            signals = [f for f in signals if target_date_str in os.path.basename(f)] if signals else []
        
    if not snapshots or not probs:
        # 兜底查找普通上海文件（如最低温）
        snapshots = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*shanghai*.json"))
        probs = glob.glob(os.path.join(PROTOCOLS_DIR, "weather_probability_*shanghai*.json"))
        signals = glob.glob(os.path.join(PROTOCOLS_DIR, "arbitrage_signals_*shanghai*.json"))
        if target_date_str:
            snapshots = [f for f in snapshots if target_date_str in os.path.basename(f)]
            probs = [f for f in probs if target_date_str in os.path.basename(f)]
            signals = [f for f in signals if target_date_str in os.path.basename(f)] if signals else []
        
    if not snapshots or not probs:
        return None, None, None
        
    # 获取最新的文件
    newest_snap = max(snapshots, key=os.path.getmtime)
    newest_prob = max(probs, key=os.path.getmtime)
    newest_sig = max(signals, key=os.path.getmtime) if signals else None
    
    return newest_snap, newest_prob, newest_sig

def generate_explainer_report(target_date=None):
    snap_path, prob_path, sig_path = load_newest_shanghai_files(target_date)
    if not snap_path or not prob_path:
        print("未在 protocols 目录中发现上海的运行协议文件。请先运行交易脚本！")
        return
        
    print(f"解析上海数据中:\n- Snapshot: {os.path.basename(snap_path)}\n- Probability: {os.path.basename(prob_path)}\n- Signals: {os.path.basename(sig_path) if sig_path else 'N/A'}")
    
    with open(snap_path, "r", encoding="utf-8") as f:
        snap = json.load(f)
    with open(prob_path, "r", encoding="utf-8") as f:
        prob = json.load(f)
        
    sig = None
    if sig_path and os.path.exists(sig_path):
        with open(sig_path, "r", encoding="utf-8") as f:
            sig = json.load(f)
            
    market_id = snap["market_id"]
    target_date = snap["target_date"]
    station_id = snap["station_info"]["station_id"]
    precision = snap["resolution_precision"]
    
    # 集合预报直方图分析
    raw_temps = prob.get("_raw_member_temps", [])
    temp_counts = {}
    for t in raw_temps:
        temp_counts[t] = temp_counts.get(t, 0) + 1
        
    sorted_temps = sorted(temp_counts.keys())
    max_count = max(temp_counts.values()) if temp_counts else 1
    
    # 准备 Markdown 直方图
    histogram_md = ""
    for t in sorted_temps:
        count = temp_counts[t]
        bar = "█" * count + "░" * (max_count - count)
        histogram_md += f"| {t} °C | {count:2d} 成员 | `{bar}` |\n"
        
    # 汇总计算对照表
    ranges = snap["ranges"]
    prob_dist = prob["probability_distribution"]
    prob_map = {item["condition"]: item["calculated_prob"] for item in prob_dist}
    err_map = {item["condition"]: item.get("standard_error", 0.0) for item in prob_dist}
    
    sig_map = {}
    if sig:
        for s in sig.get("execution_signals", []):
            sig_map[s["condition"]] = s
            
    table_rows = ""
    total_q_eff = 0.0
    for r in ranges:
        cond = r["condition"]
        ask_price = r["ask_price"]
        calculated_p = prob_map.get(cond, 0.0)
        std_err = err_map.get(cond, 0.0)
        
        # 费率换算 q_eff
        taker_base_fee = 0.0125
        q_eff = ask_price * (1.0 + taker_base_fee * (1.0 - ask_price))
        total_q_eff += q_eff
        
        # 使用收缩后的真实计算概率并区分 YES/NO EV
        act_sig = sig_map.get(cond, {})
        action = act_sig.get("action", "NO_ACTION")
        stake = act_sig.get("recommended_stake_usdc", 0.0)
        
        yes_real_prob = act_sig.get("yes_real_prob", act_sig.get("real_prob", calculated_p) if action != "BUY_NO" else 1.0 - act_sig.get("real_prob", calculated_p))
        yes_ev = act_sig.get("yes_expected_value", calculated_p - q_eff if action != "BUY_NO" else 0.0)
        no_ev = act_sig.get("no_expected_value", (1.0 - calculated_p) - (1.0 - q_eff) if action == "BUY_NO" else 0.0)
        
        action_emoji = "🔥 [BUY YES]" if action == "BUY_YES" else "🔥 [BUY NO]" if action == "BUY_NO" else "⏸️ [HOLD]" if action == "HOLD" else "➖ [IGNORE]"
        
        yes_ev_str = f"{yes_ev:+.4f}" if yes_ev != 0.0 else "-"
        no_ev_str = f"{no_ev:+.4f}" if no_ev != 0.0 else "-"
        
        table_rows += (
            f"| `{cond}` | {ask_price:.4f} | {q_eff:.4f} | {calculated_p * 100:.1f}% / **{yes_real_prob * 100:.1f}%** (±{std_err*100:.2f}%) | "
            f"{yes_ev_str} | {no_ev_str} | {action_emoji} | **{stake:.2f} USDC** |\n"
        )
        
    # 套利判定解释
    is_dutch_book = total_q_eff < 0.98
    dutch_book_status = (
        f"**触发** 🔴 (总有效单价 $\\sum q_eff = {total_q_eff:.4f} < 0.98$，算法绕过凯利直接无风险套利)"
        if is_dutch_book else
        f"**未触发** 🟢 (总有效单价 $\\sum q_eff = {total_q_eff:.4f} \\ge 0.98$，使用 Convex Kelly 求解)"
    )

    report_md = f"""# 📊 上海天气套利决策与算法推演报告

- **对赌市场**: `{market_id}`
- **结算日期**: `{target_date}`
- **目标气象站**: `{station_id} (上海虹桥/浦东)`
- **分析精度**: `{precision}`
- **生成时间**: `{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`

---

## 🌡️ 1. 气象预报输入：ICON 40 成员分布

Open-Meteo 历史/实时 ICON 集合预报（含时效噪声 $\\sigma = {prob.get('_simulated_sigma', 0.6):.4f}$°C）重采样后，40名数模型成员最高温度物理分布如下：

| 最高气温 | 成员频数 | 分布直方图可视化 |
| :--- | :--- | :--- |
{histogram_md}

---

## 📈 2. 盘口对比与最优化推演矩阵

| 档位条件 | 市场 Ask 价格 | 费率折算 $q_{{eff}}$ | 预测/收缩后概率 (Raw / Shrunk) | YES 期望 (EV) | NO 期望 (EV) | 策略决策动作 | 推荐投注金额 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{table_rows}

---

## 🧮 3. 算法决策推演说明

### 3.1 Dutch Book 无风险套利判定
根据设计文档中的数学定义，无风险套利利润边界阈值为 $0.98$。
* **判定状态**：{dutch_book_status}
* **推演公式**：
  $$\\sum_{{i}} q_{{eff, i}} = \\sum_{{i}} \\text{{Ask}}_i \\cdot [1 + \\gamma(1 - \\text{{Ask}}_i)]$$
  代入当前数据得：
  $$\\sum q_{{eff}} = {total_q_eff:.4f}$$

### 3.2 SLSQP 凸优化凯利求解 (Convex Kelly Optimizer)
若未触发 Dutch Book，系统将利用 SciPy 的 `SLSQP` 算法求解期望对数财富最大化分配。
* **目标函数**：
  $$\\max \\sum_{{i=1}}^{{n}} P_i \\ln (1 - f_{{sum}} + \\frac{{f_i}}{{q_{{eff, i}}}})$$
* **资金硬约束**：单盘口投资总上限 $C_{{loc}} \\times K_u = {10000.0 * 0.05 * 0.50} \\text{{ USDC}}$ (受最大标准差置信度分级调节限制)。
* **防抖机制 (Hysteresis)**：新增投注量 $\\Delta_i$ 必须满足 $\\ge 3.0\\% \\times C_{{loc}} = 15.0\\text{{ USDC}}$ 且 $\\Delta_i \\ge 5.0\\text{{ USDC}}$ 才会触发下单，以防高频摩擦成本。

---

## 📌 4. 结论与实操建议
* 本轮对上海最高气温盘口的评估已完成。
* 信号生成状态：{ "已生成买入指令，请核对推荐投注额度。" if sig and any(s["action"] == "BUY_YES" for s in sig["execution_signals"]) else "无推荐交易信号，建议保持观望 (HOLD/IGNORE)。" }
"""

    # 保存报告至 artifacts 目录
    os.makedirs(CONV_ARTIFACT_DIR, exist_ok=True)
    report_path = os.path.join(CONV_ARTIFACT_DIR, "shanghai_decision_explainer.md")
    with open(report_path, "w", encoding="utf-8") as f_rep:
        f_rep.write(report_md)
        
    print(f"\n🎉 决策解释报告成功生成！\n- 报告路径: [shanghai_decision_explainer.md](file://{report_path})")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生成决策解释报告")
    parser.add_argument("--date", type=str, default=None, help="指定需要解析的天气结算日期 (YYYY-MM-DD)")
    args = parser.parse_args()
    generate_explainer_report(args.date)
