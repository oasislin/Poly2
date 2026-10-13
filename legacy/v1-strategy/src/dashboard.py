import os
import sys

# 必须在导入任何 src 项目内包前强行注入项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import json
import sqlite3
import datetime
import glob
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from src.config import CONFIG, LOG_PATH, STORAGE_DIR


# 页面基础配置
st.set_page_config(
    page_title="Polymarket 天气套利自动化交易系统",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)
from streamlit_autorefresh import st_autorefresh

# 每 30 秒自动刷新一次前端界面，确保数据与后台常驻进程保持同步
st_autorefresh(interval=30000, key="global_dashboard_refresh")

# 注入高阶暗色系与玻璃拟态 CSS
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=Outfit:wght@400;600;800&family=JetBrains+Mono:wght@400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    h1, h2, h3 {
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        letter-spacing: -0.5px;
    }
    
    .metric-card {
        background: rgba(25, 30, 40, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        margin-bottom: 20px;
    }
    
    .metric-label {
        font-size: 14px;
        color: #8A99AD;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
        font-weight: 600;
    }
    
    .metric-value {
        font-size: 32px;
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        background: linear-gradient(135deg, #FFF 0%, #8A99AD 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .metric-value-green {
        font-size: 32px;
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        background: linear-gradient(135deg, #00FFCC 0%, #009977 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .metric-value-red {
        font-size: 32px;
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        background: linear-gradient(135deg, #FF3366 0%, #990033 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .terminal-box {
        background-color: #0E1117;
        border: 1px solid #1E293B;
        border-radius: 12px;
        padding: 16px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        color: #00FFCC;
        height: 250px;
        overflow-y: scroll;
        white-space: pre-wrap;
    }
    </style>
""", unsafe_allow_html=True)

# ----------------- 数据加载函数 -----------------
PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
DB_PATH = os.path.join(STORAGE_DIR, "arbitrage.db")

def get_active_markets():
    """
    扫描 protocols/ 文件夹下所有的 market_snapshot_*.json 文件，获取所有被监控的城市/事件
    """
    snapshot_files = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
    markets_list = []
    for fpath in snapshot_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                snap = json.load(f)
                slug = snap["market_id"]
                city = snap["station_info"]["city"]
                icao = snap["station_info"]["station_id"]
                date = snap["target_date"]
                precision = snap["resolution_precision"]
                
                status = snap.get("status", "active")
                
                markets_list.append({
                    "slug": slug,
                    "city": city,
                    "icao": icao,
                    "date": date,
                    "precision": precision,
                    "status": status,
                    "fpath": fpath
                })
        except Exception:
            pass
    return markets_list

def load_json_protocol(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def get_db_connection():
    if os.path.exists(DB_PATH):
        return sqlite3.connect(DB_PATH)
    return None

def format_action(action, stake=None):
    action = action.upper().strip() if isinstance(action, str) else "NO_ACTION"
    emoji_map = {
        "BUY_YES": "🔥 [BUY YES]",
        "BUY_NO": "🔥 [BUY NO]",
        "HOLD_SATISFIED": "⏸️ [HOLD (Satisfied)]",
        "HOLD": "⏸️ [HOLD (Satisfied)]",
        "HOLD_INACTIVE": "⏳ [HOLD (Inactive)]",
        "HOLD_LIMIT_REACHED": "🔒 [HOLD (Limit Reached)]",
        "HOLD_FORCED_NO_SELL": "🛡️ [HOLD (Forced No Sell)]",
        "IGNORE_LOW_EDGE": "➖ [IGNORE (Low Edge)]",
        "IGNORE_NO_EDGE": "➖ [IGNORE (No Edge)]",
        "NO_ACTION": "➖ [IGNORE (No Edge)]"
    }
    base = emoji_map.get(action, f"➖ [{action}]")
    if stake is not None and stake > 0:
        return f"{base} ({stake:.2f} USDC)"
    return base

def load_market_data(slug):
    """
    加载指定盘口的数据。优先从 protocols/ 读取。
    如果不存在，从 storage/archive/ 中匹配并解析归档文件。
    """
    snap_path = os.path.join(PROTOCOLS_DIR, f"market_snapshot_{slug}.json")
    prob_path = os.path.join(PROTOCOLS_DIR, f"weather_probability_{slug}.json")
    sig_path = os.path.join(PROTOCOLS_DIR, f"arbitrage_signals_{slug}.json")
    
    if os.path.exists(snap_path) and os.path.exists(prob_path) and os.path.exists(sig_path):
        return (
            load_json_protocol(snap_path),
            load_json_protocol(prob_path),
            load_json_protocol(sig_path),
            False # is_archived
        )
        
    # 尝试从归档中加载
    archive_pattern = os.path.join(STORAGE_DIR, "archive", f"*_{slug}.json")
    archive_files = glob.glob(archive_pattern)
    if archive_files:
        # 取最新的一份归档
        latest_archive = sorted(archive_files)[-1]
        try:
            with open(latest_archive, "r", encoding="utf-8") as f:
                arc = json.load(f)
            
            # 从归档数据中重构 snapshot, probability, signals
            snapshot = arc["raw_data"]["market_snapshot"]
            
            # Reconstruct probability
            probability = {
                "market_id": slug,
                "target_date": snapshot["target_date"],
                "probability_distribution": arc["calculated_results"]["probability_distribution"],
                "_raw_member_temps": [],
                "_simulated_sigma": arc["algorithm_metadata"]["parameters"].get("obs_error_sigma_0", 0.6)
            }
            
            # Reconstruct signals
            signals = {
                "execution_signals": [],
                "metadata": {
                    "hours_to_maturity": 0.0,
                    "time_decay_factor": 1.0,
                    "gamma_sigma": 1.0,
                    "C_loc": 200.0,
                    "K_u": 0.05
                }
            }
            
            # 我们可以从数据库中读取交易决策来填充 execution_signals
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT range_id, stake_usdc, ask_price, trade_type, expected_value, real_prob, status
                        FROM trades WHERE market_id = ?
                    """, (slug,))
                    rows = cursor.fetchall()
                    for r_id, stake, price, t_type, ev, prob, status in rows:
                        signals["execution_signals"].append({
                            "market_id": slug,
                            "range_id": r_id,
                            "condition": next((r["condition"] for r in snapshot["ranges"] if r["range_id"] == r_id), r_id),
                            "market_ask": price,
                            "real_prob": prob,
                            "expected_value": ev,
                            "action": f"BUY_{t_type.upper()}" if status != "PENDING" else "HOLD",
                            "recommended_stake_usdc": stake
                        })
                except Exception:
                    pass
                finally:
                    conn.close()
                    
            return snapshot, probability, signals, True
        except Exception as e:
            pass
            
    return None, None, None, False

def get_all_perspectives():
    """
    聚合 protocols 文件夹下的快照以及 database 中的交易历史，
    构建包含所有盘口（城市 - 极值类型 - 日期）的完整视角列表。
    """
    perspectives = {}
    
    # 1. 扫描 protocols 文件夹下的所有快照文件
    active_markets = get_active_markets()
    for am in active_markets:
        slug = am["slug"]
        is_lowest = "lowest-temperature" in slug
        event_type = "🔵 最低温" if is_lowest else "🔴 最高温"
        perspectives[slug] = {
            "slug": slug,
            "city": am["city"],
            "icao": am["icao"],
            "date": am["date"],
            "event_type": event_type,
            "status": "开放中" if am["status"] == "active" else "已过期未交易",
            "volume_usdc": 0.0,
            "realized_pnl": 0.0,
            "pending_exposure": 0.0
        }
        
    # 2. 从数据库中读取所有交易的汇总
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    market_id, 
                    station_id, 
                    settlement_date,
                    SUM(stake_usdc) as total_stake,
                    SUM(realized_pnl) as total_pnl,
                    SUM(CASE WHEN status = 'PENDING' THEN stake_usdc ELSE 0 END) as pending_stake,
                    SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) as won_count,
                    SUM(CASE WHEN status = 'LOST' THEN 1 ELSE 0 END) as lost_count
                FROM trades
                GROUP BY market_id
            """)
            rows = cursor.fetchall()
            for market_id, station_id, settlement_date, total_stake, total_pnl, pending_stake, won_count, lost_count in rows:
                is_lowest = "lowest-temperature" in market_id
                event_type = "🔵 最低温" if is_lowest else "🔴 最高温"
                
                # 从 station_id 找城市名称
                from src.config import load_cities_config
                cities = load_cities_config()
                city_name = cities.get(station_id, {}).get("city", market_id.split("-on-")[0].replace("highest-temperature-in-", "").replace("lowest-temperature-in-", "").replace("-", " ").title())
                
                if pending_stake > 0:
                    status = "待结算"
                else:
                    if total_pnl > 0:
                        status = "已结算 (盈利)"
                    elif total_pnl < 0:
                        status = "已结算 (亏损)"
                    else:
                        status = "已结算 (平手)"
                    
                if market_id in perspectives:
                    perspectives[market_id]["volume_usdc"] = total_stake
                    perspectives[market_id]["realized_pnl"] = total_pnl
                    perspectives[market_id]["pending_exposure"] = pending_stake
                    perspectives[market_id]["status"] = status
                else:
                    perspectives[market_id] = {
                        "slug": market_id,
                        "city": city_name,
                        "icao": station_id,
                        "date": settlement_date,
                        "event_type": event_type,
                        "status": status,
                        "volume_usdc": total_stake,
                        "realized_pnl": total_pnl,
                        "pending_exposure": pending_stake
                    }
        except Exception as e:
            pass
        finally:
            conn.close()
            
    return list(perspectives.values())

# ----------------- 侧边栏 -----------------
st.sidebar.markdown(f"## ⚙️ 系统控制中心")
st.sidebar.markdown(f"**当前运行模式**: `{CONFIG['trading_mode'].upper()}`")
show_inactive = st.sidebar.checkbox("👀 显示已过结算期/非活性盘口", value=False)

# 侧边栏显示静态风控配置
st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ 风控与分数凯利参数")
st.sidebar.markdown(f"- **最低期望回报 (EV)**: `{CONFIG['risk_control_lock']['min_ev_threshold']} USDC`")
st.sidebar.markdown(f"- **最大允许滑点**: `{CONFIG['risk_control_lock']['max_slippage_allowance'] * 100:.1f}%`")
st.sidebar.markdown(f"- **最大事件头寸**: `{CONFIG['risk_control_lock']['max_portfolio_exposure'] * 100:.1f}%`")
st.sidebar.markdown(f"- **气温边界缓冲区**: `±{CONFIG['risk_control_lock'].get('boundary_buffer_celsius', 0.2)} °C`")
st.sidebar.markdown(f"- **凯利时间衰减 λ**: `{CONFIG['risk_control_lock'].get('kelly_time_decay_lambda', 0.0578)}`")
st.sidebar.markdown(f"- **远期最低保留比例**: `{CONFIG['risk_control_lock'].get('kelly_min_fraction', 0.20) * 100:.1f}%`")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🌐 网络网关")
proxy_status = "🟢 代理正常" if CONFIG["http_proxy"] else "⚪ 直连运行"
st.sidebar.markdown(f"**代理状态**: {proxy_status}")
if CONFIG["http_proxy"]:
    st.sidebar.caption(f"地址: {CONFIG['http_proxy']}")

# ----------------- 加载监控市场数据 -----------------
all_markets = get_active_markets()
if show_inactive:
    active_markets = all_markets
else:
    active_markets = [m for m in all_markets if m.get("status", "active") == "active"]

# 初始化选中城市的 session state，供全局表格和钻取下拉框联动使用
if active_markets:
    if "selected_slug" not in st.session_state:
        st.session_state.selected_slug = active_markets[0]["slug"]

def get_markdown_report(snap, prob, sig):
    market_id = snap["market_id"]
    target_date = snap["target_date"]
    station_id = snap["station_info"]["station_id"]
    precision = snap["resolution_precision"]
    city = snap["station_info"]["city"]
    
    # 获取风控元数据
    meta = sig.get("metadata", {}) if sig else {}
    k_u = meta.get("K_u", 0.05 * 0.5)
    k_u_base = meta.get("K_u_base", 0.05)
    time_decay = meta.get("time_decay_factor", 0.5)
    gamma_sigma = meta.get("gamma_sigma", 1.0)
    c_loc = meta.get("C_loc", 200.0)
    c_total = meta.get("C_total", 10000.0)
    sim_sigma = meta.get("simulated_sigma", prob.get("_simulated_sigma", 0.6))
    hours_to_maturity = meta.get("hours_to_maturity", 24.0)
    
    # 集合预报直方图分析
    raw_temps = prob.get("_raw_member_temps", [])
    temp_counts = {}
    for t in raw_temps:
        temp_counts[t] = temp_counts.get(t, 0) + 1
        
    sorted_temps = sorted(temp_counts.keys())
    max_count = max(temp_counts.values()) if temp_counts else 1
    
    histogram_md = ""
    for t in sorted_temps:
        count = temp_counts[t]
        bar = "█" * count + "░" * (max_count - count)
        histogram_md += f"| {t} °C | {count:2d} 成员 | `{bar}` |\n"
        
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
        
        taker_base_fee = 0.0125
        q_eff = ask_price * (1.0 + taker_base_fee * (1.0 - ask_price))
        total_q_eff += q_eff
        
        # 使用收缩后的真实计算概率
        sig_item = sig_map.get(cond, {})
        # 始终使用 YES 合约的收缩后概率，避免口径混淆
        yes_shrunk_prob = sig_item.get("yes_real_prob", calculated_p)
        
        action = sig_item.get("action", "NO_ACTION")
        stake = sig_item.get("recommended_stake_usdc", 0.0)
        
        # 期望值 Edge 展示推荐交易动作的真实 Edge（BUY_NO 时为 NO 合约 Edge，其余为 YES 预测 Edge）
        ev_net = sig_item.get("expected_value", yes_shrunk_prob - q_eff)
        
        action_emoji = format_action(action)
        
        table_rows += (
            f"| `{cond}` | {ask_price:.4f} | {q_eff:.4f} | {calculated_p * 100:.1f}% / **{yes_shrunk_prob * 100:.1f}%** (±{std_err*100:.2f}%) | "
            f"{ev_net:+.4f} | {action_emoji} | **{stake:.2f} USDC** |\n"
        )
        
    is_dutch_book = total_q_eff < 0.98
    dutch_book_status = (
        f"**触发** 🔴 (总有效单价 $\\sum q_{{eff}} = {total_q_eff:.4f} < 0.98$，算法绕过凯利直接无风险套利)"
        if is_dutch_book else
        f"**未触发** 🟢 (总有效单价 $\\sum q_{{eff}} = {total_q_eff:.4f} \\ge 0.98$，使用 Convex Kelly 求解)"
    )
    
    report_md = fr"""# 📊 {city}天气套利决策与算法推演报告
 
- **对赌市场**: `{market_id}`
- **结算日期**: `{target_date}`
- **目标气象站**: `{station_id} ({city})`
- **分析精度**: `{precision}`
- **生成时间**: `{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`
 
---
 
## 🌡️ 1. 气象预报输入：ICON 40 成员分布
 
Open-Meteo 历史/实时 ICON 集合预报（含时效噪声 $\sigma = {sim_sigma:.4f}$°C）重采样后，40名数模型成员最高温度物理分布如下：
 
| 最高气温 | 成员频数 | 分布直方图可视化 |
| :--- | :--- | :--- |
{histogram_md}
 
---
 
## 📈 2. 盘口对比与最优化推演矩阵
 
| 档位条件 | 市场 YES Ask | 费率折算 YES $q_{{eff}}$ | 预测/收缩后 YES 概率 (Raw / Shrunk) | 交易期望值 Edge | 策略决策动作 | 推荐投注金额 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{table_rows}
 
---
 
## 🧮 3. 算法决策推演说明
 
### 3.1 Dutch Book 无风险套利判定
根据设计文档中的数学定义，无风险套利利润边界阈值为 $0.98$。
* **判定状态**：{dutch_book_status}
* **推演公式**：
  $$\sum_{{i}} q_{{eff, i}} = \sum_{{i}} \text{{Ask}}_i \cdot [1 + \gamma(1 - \text{{Ask}}_i)]$$
  代入当前数据得：
  $$\sum q_{{eff}} = {total_q_eff:.4f}$$
 
### 3.2 SLSQP 凸优化凯利求解 (Convex Kelly Optimizer)
若未触发 Dutch Book，系统将利用 SciPy 的 `SLSQP` 算法求解期望对数财富最大化分配。
* **目标函数**：
  $$\max \sum_{{i=1}}^{{n}} P_i \ln (1 - f_{{sum}} + \frac{{f_i}}{{q_{{eff, i}}}})$$
* **原始资金限制约束**：单盘口投资总上限 $C_{{loc}} = {c_loc:.2f} \text{{ USDC}}$。
 
### 🛡️ 3.3 风控限额与下注缩水推演 (Wind Control & Stake Scaling)
在生成最终推荐投注额度前，系统会对原始优化仓位进行时效与气象噪声的双重风控平滑缩水：

1. **时效衰减 (Time-Decay)**:
   * 距离对赌市场结算仍有 `{hours_to_maturity:.1f}` 小时。
   * 置信评级基础资金比例 $K_{{u\_base}} = {k_u_base:.4f}$。
   * 计算得到时间缩水因子 $\text{{decay\_factor}} = {time_decay:.4f}$。
   * 最终优化本金比例 $K_u = K_{{u\_base}} \times \text{{decay\_factor}} = {k_u:.4f}$。
   * 调控后单盘口优化可用上限 $C_{{loc}} \times K_u = {c_loc * k_u:.2f} \text{{ USDC}}$。

2. **气象噪声缩水 (Noise Scaling)**:
   * 目标气象站模拟标准差 $\sigma = {sim_sigma:.3f}$°C，基准标准差 $\sigma_0 = 0.6$°C。
   * 自适应噪声资金缩水因子 $\gamma_{{\sigma}} = (\sigma_0 / \sigma)^3 = {gamma_sigma:.4f}$。
   * 常规交易仓位将在原始最优分配基础上乘以该因子进行防守性缩水。

3. **期望值非线性缩水 (EV Cubic Decay - Method B)**:
   * 对于处于区间 $0 < \text{{Edge}} < 8.0\%$ 的正期望档位，其目标额度将乘以立方衰减因子 $(\text{{Edge}} / 0.08)^3$。
   * 最终计算仓位如果低于最小投注额限制（当前配置为 5.0 USDC），将自动被舍入归零（显示为 NO_ACTION），避免细碎交易与高频摩擦成本。
"""
    return report_md

# ----------------- 主面板标题 -----------------
st.markdown("<h1>🚀 Polymarket 天气套利控制台</h1>", unsafe_allow_html=True)
status_col1, status_col2 = st.columns([4, 1])
with status_col2:
    st.markdown("<div style='text-align: right; color: #00FFCC; font-weight: bold;'>● 系统状态: 监控中 (Dry-Run)</div>", unsafe_allow_html=True)

# ----------------- 人工干预系统 (Human-in-the-Loop) -----------------
PENDING_STATIONS_PATH = os.path.join(STORAGE_DIR, "pending_stations.json")
if os.path.exists(PENDING_STATIONS_PATH):
    try:
        with open(PENDING_STATIONS_PATH, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception:
        pending = {}
else:
    pending = {}

if pending:
    st.markdown("### ⚠️ 【人工干预提示】检测到未映射或有异常的气象站")
    st.info("以下气象站因为时区不被 Open-Meteo 支持或经纬度坐标解析失败，可能导致对应的套利分析无法加载。请您手工录入正确的映射：")
    
    import pytz
    for station_id, info in pending.items():
        with st.expander(f"🔴 气象站 {station_id} ({info.get('city', '未知城市')}) - 错误类型: {info.get('error_type')}", expanded=True):
            st.markdown(f"**详细描述**: {info.get('details')}")
            
            with st.form(key=f"form_{station_id}"):
                col_form1, col_form2, col_form3 = st.columns(3)
                with col_form1:
                    tz_list = sorted(list(pytz.common_timezones))
                    default_tz_idx = tz_list.index("Asia/Shanghai") if "Asia/Shanghai" in tz_list else 0
                    tz_input = st.selectbox("选择时区 Timezone:", options=tz_list, index=default_tz_idx)
                with col_form2:
                    lat_val = st.number_input("纬度绝对值 (0 ~ 90):", min_value=0.0, max_value=90.0, value=0.0, format="%.4f")
                    lat_hem = st.selectbox("南北半球:", options=["北纬 (N)", "南纬 (S)"])
                with col_form3:
                    lon_val = st.number_input("经度绝对值 (0 ~ 180):", min_value=0.0, max_value=180.0, value=0.0, format="%.4f")
                    lon_hem = st.selectbox("东西半球:", options=["东经 (E)", "西经 (W)"])
                
                submit_button = st.form_submit_button(label="💾 保存并恢复该站点")
                if submit_button:
                    final_lat = -lat_val if lat_hem == "南纬 (S)" else lat_val
                    final_lon = -lon_val if lon_hem == "西经 (W)" else lon_val
                    from src.config import save_custom_station_mapping
                    save_custom_station_mapping(station_id, tz_input, final_lat, final_lon)
                    st.success(f"气象站 {station_id} 配置已保存！系统将在下个轮询周期或重新运行后恢复。")
                    st.rerun()

# 选项卡切换
tab_desk, tab_pers, tab_ledger, tab_config = st.tabs([
    "📊 盘口实时监控桌面 (Real-Time Desk)", 
    "🗂️ 盘口视角列表与检索 (Market Perspectives)",
    "📈 历史战绩与期望收敛 (Ledger)",
    "⚙️ 城市配置与白名单管理 (Cities & Whitelist Config)"
])


# ----------------- 选项卡 A: 实时套利监控 -----------------
with tab_desk:
    if not active_markets:
        st.warning("⏱️ 暂无实时行情快照。请确保扫描器 Scanner 已经成功运行。")
    else:
        # 1. 顶部全局套利汇总矩阵（Global Arbitrage Matrix）
        st.markdown("### 🌐 【全网监控城市套利概览 (Global Summary)】")
        
        summary_rows = []
        for am in active_markets:
            slug = am["slug"]
            city = am["city"]
            icao = am["icao"]
            date = am["date"]
            precision = am["precision"]
            
            # 读取对应的 signals 文件
            sig_file = os.path.join(PROTOCOLS_DIR, f"arbitrage_signals_{slug}.json")
            signals = load_json_protocol(sig_file)
            
            best_ev = -999.0
            best_cond = "-"
            best_price = 0.0
            action_disp = "➖ [IGNORE (No Edge)]"
            
            if signals:
                for sig in signals.get("execution_signals", []):
                    ev = sig.get("expected_value", -999.0)
                    if ev > best_ev:
                        best_ev = ev
                        best_cond = sig["condition"]
                        best_price = sig["market_ask"]
                        action = sig["action"]
                        if "BUY" in action:
                            action_disp = f"{format_action(action)} {best_cond} (${best_price:.2f})"
                        elif action in ("HOLD_SATISFIED", "HOLD_INACTIVE", "HOLD", "HOLD_LIMIT_REACHED", "HOLD_FORCED_NO_SELL") and ev > 0:
                            action_disp = f"{format_action(action)} {best_cond} (${best_price:.2f})"
                        else:
                            action_disp = format_action(action)

            
            event_type = "🔴 最高温" if "highest-temperature" in slug else "🔵 最低温"
            summary_rows.append({
                "城市": city,
                "事件类型": event_type,
                "气象站": icao,
                "结算日期": date,
                "数值单位/精度": "摄氏度 (Celsius)" if precision == "INT_CELSIUS" else "华氏度 (Fahrenheit)",
                "最佳套利区间": best_cond,
                "盘面价格": f"${best_price:.2f}" if best_price > 0 else "-",
                "最佳数学期望 (Best EV)": f"${best_ev:.4f}" if best_ev > -900 else "-",
                "推荐交易指令": action_disp
            })
            
        df_summary = pd.DataFrame(summary_rows)
        
        def highlight_row(row):
            val = row.get("推荐交易指令", "")
            if not val and "交易决策" in row:
                val = row["交易决策"]
            if "BUY" in str(val):
                return ['background-color: rgba(0, 255, 204, 0.15)'] * len(row)
            return [''] * len(row)
            
        # 启用交互式单行选择，绑定 session state 实现表格 -> 钻取卡片联动
        event_slugs = [am["slug"] for am in active_markets]
        selection = st.dataframe(
            df_summary.style.apply(highlight_row, axis=1), 
            use_container_width=True, 
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun"
        )
        
        if selection and selection.selection and selection.selection.rows:
            selected_row_idx = selection.selection.rows[0]
            clicked_slug = event_slugs[selected_row_idx]
            if clicked_slug != st.session_state.selected_slug:
                st.session_state.selected_slug = clicked_slug
                st.rerun()
        
        st.markdown("---")
        
        # 2. 单城市盘口钻取详情
        st.markdown("### 🔍 【单城市气象数据钻取 (Drilldown Area)】")
        
        # 获取所有视角以支持钻取历史/未在监控列表中的盘口
        all_perspectives_list = get_all_perspectives()
        market_options = {}
        for p in all_perspectives_list:
            t_type = "最高温" if "highest-temperature" in p["slug"] else "最低温"
            market_options[p["slug"]] = f"{p['city']} ({p['icao']}) - {t_type} - {p['date']} [{p['status']}]"
        market_slugs = list(market_options.keys())
        
        if st.session_state.selected_slug not in market_slugs and market_slugs:
            st.session_state.selected_slug = market_slugs[0]
            
        default_index = market_slugs.index(st.session_state.selected_slug) if st.session_state.selected_slug in market_slugs else 0
        
        selected_slug = st.selectbox(
            "选择要钻取的城市事件:", 
            options=market_slugs, 
            index=default_index,
            format_func=lambda s: market_options[s]
        )
        
        if selected_slug != st.session_state.selected_slug:
            st.session_state.selected_slug = selected_slug
            st.rerun()
        
        # 使用自适应加载函数支持 protocols 和 archive 自动回溯
        snapshot, probability, signals, is_archived = load_market_data(selected_slug)
        
        if snapshot and probability and signals:
            # 针对使用预置兜底气象站（非标准 ICAO 代码）的城市进行醒目的风险提示
            fallback_stations = ["ATLA", "HOUS", "CHIC", "AUST", "DENV", "MIAI", "MIAM", "SEAT", "DALL"]
            station_id = snapshot['station_info']['station_id']
            if station_id in fallback_stations:
                st.error(f"⚠️ **【容错运行提示】该城市当前正处于容错对齐状态！** \n\n"
                         f"由于 Polymarket 合约中使用了非标/错误的机场代码（当前抓取为: `{station_id}`），系统已自动强制启用本地预置的真实地理坐标与时区参数进行估值计算。请在交易前人工核对该坐标与 Polymarket 最终结算气象站是否一致，谨防结算偏差！")
            
            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                t_type_disp = "🔴 最高温" if "highest-temperature" in selected_slug else "🔵 最低温"
                st.markdown(f"**🎯 钻取目标**: {snapshot['station_info']['city']} ({snapshot['station_info']['station_id']}) {t_type_disp}")
                st.markdown(f"**📅 对赌结算日**: {snapshot['target_date']}")
            with col_info2:
                try:
                    from src.analyst import resolve_station_coordinates
                    lat, lon = resolve_station_coordinates(snapshot['station_info']['station_id'])
                    coords_str = f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"
                except Exception:
                    coords_str = "未知"
                st.markdown(f"**🌐 气象站位置 (经纬度)**: `{coords_str}`")
                try:
                    import pytz
                    station_tz = pytz.timezone(snapshot['station_info']['timezone'])
                    local_time = datetime.datetime.now(station_tz).strftime('%Y-%m-%d %H:%M:%S')
                    tz_display = f"{snapshot['station_info']['timezone']} (当地时间: `{local_time}`)"
                except Exception:
                    tz_display = snapshot['station_info']['timezone']
                st.markdown(f"**🕰️ 结算时区**: {tz_display}")
            with col_info3:
                update_time = datetime.datetime.fromtimestamp(snapshot['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                st.markdown(f"**⏱️ 盘面同步时间**: {update_time}")
                st.markdown(f"**⚡ 数值精度/单位**: `{'摄氏度' if snapshot['resolution_precision'] == 'INT_CELSIUS' else '华氏度'}`")
                if is_archived:
                    st.markdown("⚠️ *数据来源: 历史归档协议 (Archived)*")

            # 增加外部参考链接
            st.markdown(f"""
            🔗 **相关外部参考链接 (External Links)**:
            &nbsp;&nbsp;•&nbsp;&nbsp;[🏛️ Polymarket 原始盘口页面](https://polymarket.com/event/{selected_slug})
            &nbsp;&nbsp;•&nbsp;&nbsp;[🌦️ Wunderground 对应气象站实况历史](https://www.wunderground.com/history/daily/{snapshot['station_info']['station_id']}/date/{snapshot['target_date']})
            """)
            
            # 🛡️ 风控与资金缩水调控详情 (Wind Control & Risk Regulation)
            metadata = signals.get("metadata", {})
            if metadata:
                st.markdown("##### 🛡️ 【风控资金限额与下注缩水调控详情】")
                col_mc1, col_mc2, col_mc3, col_mc4 = st.columns(4)
                with col_mc1:
                    st.metric(
                        label="⏳ 距离结算 (Maturity)", 
                        value=f"{metadata.get('hours_to_maturity', 24.0):.1f} 小时",
                        help="当前时间距离对赌合约官方结算参考点剩余的小时数。"
                    )
                with col_mc2:
                    st.metric(
                        label="📉 时效衰减因子", 
                        value=f"{metadata.get('time_decay_factor', 1.0):.4f}",
                        help=f"时效衰减比例。距离结算时间越远，该系数越低以规避远期预测风险。(K_u_base={metadata.get('K_u_base', 0.05):.2f} -> 最终优化比例 K_u={metadata.get('K_u', 0.02):.4f})"
                    )
                with col_mc3:
                    st.metric(
                        label="❄️ 气象噪声缩水 (gamma)", 
                        value=f"{metadata.get('gamma_sigma', 1.0):.4f}",
                        help=f"噪声自适应缩水比例。当站点模拟标准差 σ={metadata.get('simulated_sigma', 0.6):.3f}°C 偏大（大于基准标准差 0.6°C）时，系统将通过立方因子进行防守性缩水。"
                    )
                with col_mc4:
                    limit_val = metadata.get('C_loc', 200.0) * metadata.get('K_u', 0.02)
                    st.metric(
                        label="💰 单盘口优化资金上限", 
                        value=f"${limit_val:.2f} USDC",
                        help=f"该天气事件允许买入的虚拟本金总上限。计算公式: 总预算 C_loc (${metadata.get('C_loc', 200.0):.1f}) * 衰减本金比例 K_u ({metadata.get('K_u', 0.02):.4f})"
                    )
                
                # 如果单盘口可用上限小于最小下注额，进行预警提示说明
                min_bet = CONFIG['risk_control_lock']['min_bet_usdc']
                if limit_val < min_bet:
                    st.warning(f"⚠️ **【资金限额预警】** 当前市场的优化资金上限为 **${limit_val:.2f} USDC**，已经低于单笔最小投注额 **${min_bet:.1f} USDC**。因此，即使某些档位有着极高的正期望值（EV），算出来的投注金额也会因为低于最小门槛而被系统强制舍入至 0（显示为 `NO_ACTION`）。")
            
            # 单城市套利矩阵
            st.markdown(f"**【{snapshot['station_info']['city']} 实时套利矩阵 (Arbitrage Matrix)】**")
            
            matrix_data = []
            sig_map = {s["condition"]: s for s in signals["execution_signals"]}
            
            # 单位标识
            unit_sym = "°C" if snapshot['resolution_precision'] == "INT_CELSIUS" else "°F"
            
            def sort_key_condition(r):
                import re
                cond = r["condition"]
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", cond)
                val = float(nums[0]) if nums else 0.0
                if "<=" in cond:
                    return (0, val)
                elif ">=" in cond:
                    return (2, val)
                else:
                    return (1, val)
            
            for r in sorted(snapshot["ranges"], key=sort_key_condition):
                cond = r["condition"]
                ask_price = r["ask_price"]
                prob = next((item["calculated_prob"] for item in probability["probability_distribution"] if item["condition"] == cond), 0.0)
                
                sig = sig_map.get(cond, {})
                action = sig.get("action", "NO_ACTION")
                stake = sig.get("recommended_stake_usdc", 0.0)
                
                # 读取并向下兼容单向信号数据，保证展示指标基准统一为 YES 方向的概率
                yes_real_prob = sig.get("yes_real_prob", sig.get("real_prob", 0.0) if action != "BUY_NO" else 1.0 - sig.get("real_prob", 0.0))
                yes_ev = sig.get("yes_expected_value", sig.get("expected_value", 0.0) if action != "BUY_NO" else 0.0)
                no_ev = sig.get("no_expected_value", sig.get("expected_value", 0.0) if action == "BUY_NO" else 0.0)
                
                if "BUY" in action:
                    action_display = f"{format_action(action, stake)}"
                else:
                    action_display = format_action(action)
                    
                matrix_data.append({
                    f"气温区间 ({unit_sym})": cond,
                    "Polymarket YES 价格": f"${ask_price:.4f}",
                    "市场 implied YES 概率": f"{ask_price*100:.1f}%",
                    "模型预测 YES 概率 (Raw)": f"{prob*100:.1f}%",
                    "收缩后 YES 概率 (Shrunk)": f"{yes_real_prob*100:.1f}%",
                    "YES 期望 (EV)": f"${yes_ev:+.4f}" if yes_ev != 0.0 else "-",
                    "NO 期望 (EV)": f"${no_ev:+.4f}" if no_ev != 0.0 else "-",
                    "交易决策": action_display
                })
                
            df_matrix = pd.DataFrame(matrix_data)
            st.dataframe(df_matrix.style.apply(highlight_row, axis=1), use_container_width=True, hide_index=True)
            
            # 温度数模成员直方图
            raw_temps = probability.get("_raw_member_temps", [])
            if raw_temps:
                df_hist = pd.DataFrame({"Temperature": raw_temps})
                t_type_plain = "最高温度" if "highest-temperature" in selected_slug else "最低温度"
                fig = px.histogram(
                    df_hist, 
                    x="Temperature", 
                    nbins=12,
                    title=f"ICON 40个气象成员{t_type_plain}预测分布直方图 ({unit_sym})",
                    labels={"Temperature": f"{t_type_plain} ({unit_sym})", "count": "数模成员个数 (个)"},
                    color_discrete_sequence=["#00FFCC"]
                )
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#8A99AD",
                    xaxis=dict(showgrid=True, gridcolor="#1E293B"),
                    yaxis=dict(showgrid=True, gridcolor="#1E293B"),
                    bargap=0.08
                )
                
                from src.strategy import extract_boundaries
                boundaries = extract_boundaries(snapshot["ranges"])
                for b in boundaries:
                    fig.add_vline(x=b, line_dash="dash", line_color="#FF3366", annotation_text=f"边界 {b}{unit_sym}", annotation_position="top left")
                    
                st.plotly_chart(fig, use_container_width=True)
                
            st.caption(f"ℹ️ *说明: 当前城市采用 Wunderground 结算判定。气象直报数据为摄氏度。如果快照检测为华氏度盘口，分析器已自动在下载端将 40 成员预测转换为华氏度（°F = °C * 1.8 + 32）并取整，再投射进押注条件，避免温度单位混淆。*")
            
            st.markdown("---")
            
            # 3. 展现该盘口的本地投注历史
            st.markdown(f"**📜 【该盘口的本地投注历史 (Betting History)】**")
            conn = get_db_connection()
            if conn:
                try:
                    df_market_trades = pd.read_sql_query(
                        "SELECT timestamp, condition, trade_type, stake_usdc, ask_price, expected_value, status, realized_pnl FROM trades WHERE market_id = ? ORDER BY timestamp DESC", 
                        conn, 
                        params=(selected_slug,)
                    )
                    if not df_market_trades.empty:
                        df_market_trades["交易时间"] = pd.to_datetime(df_market_trades["timestamp"], unit='s', utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d %H:%M:%S')
                        df_market_trades_show = df_market_trades[[
                            "交易时间", "condition", "trade_type", "stake_usdc", "ask_price", "expected_value", "status", "realized_pnl"
                        ]].copy()
                        df_market_trades_show.columns = [
                            "交易时间", "押注区间", "合约类型", "投注金额 (USDC)", "成交价格", "期望值 (EV)", "状态", "实现净利 (USDC)"
                        ]
                        st.dataframe(df_market_trades_show, use_container_width=True, hide_index=True)
                    else:
                        st.info("📜 该盘口目前暂无本地投注记录。")
                except Exception as e:
                    st.error(f"加载投注历史异常: {e}")
                finally:
                    conn.close()

            # 4. 投资分析决策室与归因原因分析
            st.markdown("---")
            st.markdown("### 📊 【投资分析决策室 (Investment Insight & Analytics)】")
            col_insight1, col_insight2 = st.columns(2)
            with col_insight1:
                st.markdown("""
                **📈 数理期望与实际盈亏收敛说明**
                * **大数定律收敛性**: 量化套利策略在单笔交易中存在气象变异引起的短期盈亏随机波动。但当交易笔数增加时，实际盈亏（PnL）将会向累计数学期望值（EV）收敛。
                * **风控阈值作用**: 系统设置最低期望回报（EV）门槛，用于防范手续费和滑点侵蚀利润。
                """)
            with col_insight2:
                # 动态归因分析说明
                has_active_signal = any(s.get("recommended_stake_usdc", 0.0) > 0 for s in signals.get("execution_signals", []))
                if has_active_signal:
                    st.success("🟢 **归因分析**: 当前盘口部分档位存在显著的错误定价（Model Edge > EV门槛），且距离结算时效合适，分数凯利分配可用资金，已生成明确买入推荐。")
                else:
                    st.info("🟡 **归因分析**: 当前盘口未生成投注指令。主要原因可能是：\n"
                            "1. 市场 YES 价格与模型胜率高度匹配，无明显定价偏差（Edge 小于 EV 门槛 8%）。\n"
                            "2. 距离对赌市场结算时间较远，时间自适应分数凯利限仓比例较低，使投注额低于最小门槛（5 USDC）而被系统防守性舍入。")

            st.markdown("---")
            if st.button("📝 生成该城市算法推演报告 (Markdown Report)"):
                report_content = get_markdown_report(snapshot, probability, signals)
                # 写入本地文件
                reports_dir = os.path.join(STORAGE_DIR, "reports")
                os.makedirs(reports_dir, exist_ok=True)
                report_path = os.path.join(reports_dir, f"{selected_slug}_decision_explainer.md")
                with open(report_path, "w", encoding="utf-8") as f_rep:
                    f_rep.write(report_content)
                st.success(f"🎉 决策推演报告成功生成！已保存至 `{report_path}`")
                st.rerun()

            # 自动加载展示已生成的报告
            reports_dir = os.path.join(STORAGE_DIR, "reports")
            report_path = os.path.join(reports_dir, f"{selected_slug}_decision_explainer.md")
            if os.path.exists(report_path):
                with st.expander("📄 展开查看已生成的算法推演报告 (Markdown Preview)", expanded=True):
                    with open(report_path, "r", encoding="utf-8") as f_rep:
                        st.markdown(f_rep.read())
            
        else:
            st.info("⌛ 正在加载或缺少该城市的分析结果协议，请等待守护进程完成完整分析。")

# ----------------- 选项卡 B: 盘口视角列表与检索 -----------------
with tab_pers:
    st.markdown("### 🗂️ 【全网盘口视角列表 (Market Perspectives List)】")
    st.markdown("""
    本列表聚合了当前正在监控的实时盘口与数据库中的历史交易盘口。
    选择任意一行可自动加载并钻取该城市的详细契约、气象数模分布与投注历史。
    """)
    
    all_perspectives = get_all_perspectives()
    
    if not all_perspectives:
        st.info("🗂️ 暂无盘口视角数据。")
    else:
        # 分层检索过滤器
        col_fil1, col_fil2 = st.columns(2)
        with col_fil1:
            unique_cities = sorted(list(set(p["city"] for p in all_perspectives)))
            selected_city = st.selectbox("选择城市过滤:", options=["全部 (All)"] + unique_cities, key="pers_city_select")
        with col_fil2:
            selected_type = st.radio("选择气温极值类型:", options=["全部 (All)", "🔴 最高温", "🔵 最低温"], horizontal=True, key="pers_type_select")
            
        # 应用过滤
        filtered_p = all_perspectives
        if selected_city != "全部 (All)":
            filtered_p = [p for p in filtered_p if p["city"] == selected_city]
        if selected_type != "全部 (All)":
            filtered_p = [p for p in filtered_p if p["event_type"] == selected_type]
            
        # 排序：将开放中/待结算的置顶，然后再按日期降序
        def sort_key_p(p):
            status_order = {
                "开放中": 0,
                "待结算": 1,
                "已结算 (盈利)": 2,
                "已结算 (亏损)": 3,
                "已结算 (平手)": 4,
                "已过期未交易": 5,
                "已关闭": 6
            }
            return (status_order.get(p["status"], 9), p["date"])
            
        sorted_p = sorted(filtered_p, key=sort_key_p)
        
        df_perspectives = pd.DataFrame([{
            "城市": p["city"],
            "气象站": p["icao"],
            "类型": p["event_type"],
            "日期": p["date"],
            "状态": p["status"],
            "投注金额": f"${p['volume_usdc']:.2f}" if p["volume_usdc"] > 0 else "-",
            "实现盈亏": f"${p['realized_pnl']:+.2f}" if p["realized_pnl"] != 0 else "-",
            "未结算仓位": f"${p['pending_exposure']:.2f}" if p["pending_exposure"] > 0 else "-",
        } for p in sorted_p])
        
        pers_selection = st.dataframe(
            df_perspectives,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="perspectives_table"
        )
        
        if pers_selection and pers_selection.selection and pers_selection.selection.rows:
            selected_row_idx = pers_selection.selection.rows[0]
            clicked_slug = sorted_p[selected_row_idx]["slug"]
            if clicked_slug != st.session_state.selected_slug:
                st.session_state.selected_slug = clicked_slug
                st.rerun()

        # 针对当前选中的盘口，直接在视角列表下方展开其投注仓位
        if "selected_slug" in st.session_state and st.session_state.selected_slug:
            selected_p_info = next((p for p in all_perspectives if p["slug"] == st.session_state.selected_slug), None)
            if selected_p_info:
                st.markdown(f"#### 💼 【{selected_p_info['city']} ({selected_p_info['icao']}) - 当前未结算仓位与投注历史】")
                
                conn = get_db_connection()
                if conn:
                    try:
                        df_sel_trades = pd.read_sql_query(
                            "SELECT timestamp, condition, trade_type, stake_usdc, ask_price, expected_value, real_prob, status, realized_pnl FROM trades WHERE market_id = ? ORDER BY timestamp DESC",
                            conn, params=(st.session_state.selected_slug,)
                        )
                        if not df_sel_trades.empty:
                            df_sel_trades["交易时间"] = pd.to_datetime(df_sel_trades["timestamp"], unit='s', utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d %H:%M:%S')
                            
                            # 未结算仓位
                            df_pend = df_sel_trades[df_sel_trades["status"] == "PENDING"]
                            if not df_pend.empty:
                                st.markdown("**🟢 进行中的未结算投注 (Active Positions):**")
                                df_pend_show = df_pend[[
                                    "交易时间", "condition", "trade_type", "stake_usdc", "ask_price", "expected_value", "real_prob"
                                ]].copy()
                                df_pend_show.columns = [
                                    "交易时间", "押注区间", "合约类型", "下注金额 (USDC)", "买入均价", "期望值 (EV)", "预测概率"
                                ]
                                st.dataframe(df_pend_show, use_container_width=True, hide_index=True)
                            else:
                                st.info("💡 该盘口当前无未结算的持仓。")
                                
                            # 已结算历史
                            df_sett = df_sel_trades[df_sel_trades["status"] != "PENDING"]
                            if not df_sett.empty:
                                with st.expander("📜 展开查看该盘口已结算的投注历史 (Settled History)"):
                                    df_sett_show = df_sett[[
                                        "交易时间", "condition", "trade_type", "stake_usdc", "ask_price", "expected_value", "realized_pnl"
                                    ]].copy()
                                    df_sett_show.columns = [
                                        "交易时间", "押注区间", "合约类型", "投注金额 (USDC)", "买入价格", "数学期望", "实现盈亏 (USDC)"
                                    ]
                                    st.dataframe(df_sett_show, use_container_width=True, hide_index=True)
                        else:
                            st.info("📜 数据库中暂无针对该盘口的本地投注记录。")
                    except Exception as e:
                        st.error(f"加载盘口仓位历史异常: {e}")
                    finally:
                        conn.close()

# ----------------- 选项卡 C: 历史战绩 LEDGER -----------------
with tab_ledger:
    conn = get_db_connection()
    if conn:
        df_trades = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp DESC", conn)
        conn.close()
        
        if not df_trades.empty:
            total_volume = df_trades["stake_usdc"].sum()
            net_pnl = df_trades["realized_pnl"].sum()
            
            # 当前未结算仓位资金
            unsettled_trades = df_trades[df_trades["status"] == "PENDING"]
            total_unsettled = unsettled_trades["stake_usdc"].sum()
            
            settled = df_trades[df_trades["status"] != "PENDING"]
            if not settled.empty:
                won_count = len(settled[settled["status"] == "WON"])
                win_rate = won_count / len(settled)
            else:
                win_rate = 0.0
                
            # 按目标气象结算日期（settlement_date）正序计算累计曲线，并按天合并（解决一天内有多个城市的多个交易导致坐标重合连线垂直的问题）
            df_cum = df_trades[df_trades["status"] != "PENDING"].copy()
            if not df_cum.empty:
                # 转换 settlement_date 为 datetime
                df_cum["settle_dt"] = pd.to_datetime(df_cum["settlement_date"])
                
                # 按天进行聚合分组，求和当日的所有已结算 PnL 以及期望价值
                df_cum["trade_ev_usdc"] = df_cum["stake_usdc"] * df_cum["expected_value"]
                df_daily = df_cum.groupby("settle_dt").agg({
                    "realized_pnl": "sum",
                    "trade_ev_usdc": "sum"
                }).reset_index()
                
                # 排序并计算累计值
                df_daily = df_daily.sort_values("settle_dt").reset_index(drop=True)
                df_daily["cum_pnl"] = df_daily["realized_pnl"].cumsum()
                df_daily["cum_ev"] = df_daily["trade_ev_usdc"].cumsum()
                
                # 将累计值赋给 df_cum 用于画图
                df_cum = df_daily
                
                # 计算历史最大回撤 (USDC)
                pnl_series = pd.concat([pd.Series([0.0]), df_cum["cum_pnl"]]).reset_index(drop=True)
                peaks = pnl_series.cummax()
                drawdowns = peaks - pnl_series
                max_dd_usdc = drawdowns.max()
            else:
                df_cum = pd.DataFrame(columns=["settle_dt", "cum_pnl", "cum_ev"])
                max_dd_usdc = 0.0

            total_ev = (df_trades["stake_usdc"] * df_trades["expected_value"]).sum()
            
            col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5, col_kpi6 = st.columns(6)
            with col_kpi1:
                st.markdown(f"""
                    <div class='metric-card'>
                        <div class='metric-label'>累计下注额 (Volume)</div>
                        <div class='metric-value'>${total_volume:,.2f} USDC</div>
                    </div>
                """, unsafe_allow_html=True)
            with col_kpi2:
                pnl_class = "metric-value-green" if net_pnl >= 0 else "metric-value-red"
                st.markdown(f"""
                    <div class='metric-card'>
                        <div class='metric-label'>历史实现净利润 (PnL)</div>
                        <div class='metric-value {pnl_class}'>${net_pnl:+,.2f} USDC</div>
                    </div>
                """, unsafe_allow_html=True)
            with col_kpi3:
                st.markdown(f"""
                    <div class='metric-card'>
                        <div class='metric-label'>当前未结算仓位 (Exposure)</div>
                        <div class='metric-value-green'>${total_unsettled:,.2f} USDC</div>
                    </div>
                """, unsafe_allow_html=True)
            with col_kpi4:
                st.markdown(f"""
                    <div class='metric-card'>
                        <div class='metric-label'>模拟综合胜率 (Win Rate)</div>
                        <div class='metric-value'>{win_rate*100:.1f}%</div>
                    </div>
                """, unsafe_allow_html=True)
            with col_kpi5:
                st.markdown(f"""
                    <div class='metric-card'>
                        <div class='metric-label'>累计数学期望值 (Total EV)</div>
                        <div class='metric-value-green'>${total_ev:+,.2f} USDC</div>
                    </div>
                """, unsafe_allow_html=True)
            with col_kpi6:
                st.markdown(f"""
                    <div class='metric-card'>
                        <div class='metric-label'>历史最大回撤 (Max DD)</div>
                        <div class='metric-value-red'>${max_dd_usdc:,.2f} USDC</div>
                    </div>
                """, unsafe_allow_html=True)
                
            # 展现当前仓位表格
            st.markdown("### 💼 【当前投注中 / 未结算持仓 (Current Active Positions)】")
            if not unsettled_trades.empty:
                unsettled_trades["交易时间"] = pd.to_datetime(unsettled_trades["timestamp"], unit='s', utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d %H:%M:%S')
                df_unsettled_show = unsettled_trades[[
                    "交易时间", "market_id", "station_id", "condition", "trade_type",
                    "stake_usdc", "ask_price", "expected_value", "real_prob"
                ]].copy()
                df_unsettled_show.columns = [
                    "交易时间", "市场合约ID", "气象站", "押注区间", "押注类型",
                    "投注金额 (USDC)", "买入单价", "数学期望 (EV)", "预测胜率"
                ]
                st.dataframe(df_unsettled_show, use_container_width=True, hide_index=True)
            else:
                st.info("💼 目前暂无未结算的模拟持仓。")
                
            st.markdown("### 📈 【量化收敛监控：实际利润与数理期望收敛曲线】")
            
            fig_cum = go.Figure()
            # 使用 pd.to_datetime 转化后的真实时间作为 x 轴，使横轴时间轴按真实比例均匀排布（ Plotly 会自动按时间线性缩放）
            fig_cum.add_trace(go.Scatter(x=df_cum["settle_dt"], y=df_cum["cum_pnl"], name="实现净利润 (PnL)", line=dict(color="#00FFCC", width=3)))
            fig_cum.add_trace(go.Scatter(x=df_cum["settle_dt"], y=df_cum["cum_ev"], name="累计数学期望 (EV)", line=dict(color="#FF3366", width=2, dash="dash")))
            
            fig_cum.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#8A99AD",
                hoverlabel=dict(
                    bgcolor="#0F172A",     # 深黑蓝色背景提供高对比度
                    font_size=20,          # 放大到 20px 字体，确保极佳清晰度
                    font_family="Arial, sans-serif",
                    font_color="#FFFFFF"   # 高亮纯白字
                ),
                xaxis=dict(
                    showgrid=True, 
                    gridcolor="#1E293B",
                    type="date",
                    tickformat="%Y-%m-%d",
                    dtick=86400000  # 强制刻度最小单位为 1 天 (86400000ms)，防止 Plotly 自动细分生成半天刻度导致日期文字重复
                ),
                yaxis=dict(showgrid=True, gridcolor="#1E293B"),
                legend=dict(bgcolor="rgba(0,0,0,0)")
            )
            # 使用 theme=None 禁用 Streamlit 对 Plotly 的全局样式覆盖，使得我们自定义的超大 tooltip (hoverlabel) 能够完美生效
            st.plotly_chart(fig_cum, use_container_width=True, theme=None)
            
            st.markdown("### 📜 【已结算交易明细账本 (Live Ledger)】")
            df_trades["交易时间"] = pd.to_datetime(df_trades["timestamp"], unit='s', utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d %H:%M:%S')
            df_ledger_show = df_trades[df_trades["status"] != "PENDING"][[
                "交易时间", "market_id", "station_id", "condition", "trade_type",
                "stake_usdc", "ask_price", "expected_value", "status", "realized_pnl"
            ]].copy()
            df_ledger_show.columns = [
                "交易时间", "市场合约ID", "气象站", "押注区间", "押注类型",
                "买入额 (USDC)", "买入价格", "单笔 EV", "状态", "实现净利 (USDC)"
            ]
            st.dataframe(df_ledger_show, use_container_width=True, hide_index=True)
            
        else:
            st.info("📜 账本数据库中目前暂无模拟交易记录。待有套利机会并自动下单后，本页面将实时展现数据。")
    else:
        st.warning("⚠️ 未找到 SQLite 账本文件 (`storage/arbitrage.db`)。")

# ----------------- 选项卡 C: 城市配置与白名单管理 -----------------
with tab_config:
    st.markdown("### ⚙️ 【全网气象站点追踪与下注白名单管理 (Central Cities Manager)】")
    st.markdown("""
    在这里您可以设置每一个气象站点的各项参数：
    - **是否追踪数据 (is_tracked)**：控制 Scanner 与 Analyst 模块是否拉取与处理该站点的数据。
    - **是否允许下注 (is_tradable)**：控制 Executor 执行阶段是否允许针对该城市的预期动作下单投注。
    """)
    
    import src.config
    import importlib
    importlib.reload(src.config)
    from src.config import load_cities_config, save_cities_config
    cities_dict = load_cities_config()
    
    if cities_dict:
        # Convert dictionary to DataFrame for user editing
        table_data = []
        import pytz
        
        # 使用 Session State 中的固定基准时间，避免每次交互触发重构时数据内容发生微秒级变化导致 st.data_editor 重置编辑状态
        if "config_base_time" not in st.session_state:
            st.session_state.config_base_time = datetime.datetime.now(pytz.UTC)
        base_time = st.session_state.config_base_time
        
        for icao, details in cities_dict.items():
            tz_str = details.get("timezone", "UTC")
            try:
                station_tz = pytz.timezone(tz_str)
                local_time = base_time.astimezone(station_tz).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                local_time = "未知"
                
            table_data.append({
                "气象站 ICAO": icao,
                "城市名称": details.get("city", ""),
                "气象参考网站": f"https://www.wunderground.com/weather/{icao}",
                "当地时区": tz_str,
                "当地时间": local_time,
                "纬度 (Latitude)": details.get("lat", 0.0),
                "经度 (Longitude)": details.get("lon", 0.0),
                "是否追踪数据": details.get("is_tracked", True),
                "是否允许下注": details.get("is_tradable", True)
            })
            
        df_cities = pd.DataFrame(table_data)
        
        # 使用 Streamlit 交互式数据表编辑器 st.data_editor
        edited_df = st.data_editor(
            df_cities,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "气象参考网站": st.column_config.LinkColumn(display_text="🔗 访问 Wunderground"),
                "是否追踪数据": st.column_config.CheckboxColumn(),
                "是否允许下注": st.column_config.CheckboxColumn()
            },
            key="cities_editor"
        )
        
        col1, col2 = st.columns([1, 5])
        with col1:
            if st.button("💾 保存并应用配置"):
                # Convert edited DataFrame back to dict and save
                new_cities_dict = {}
                for idx, row in edited_df.iterrows():
                    icao = str(row["气象站 ICAO"]).upper().strip()
                    if not icao:
                        continue
                    new_cities_dict[icao] = {
                        "city": str(row["城市名称"]),
                        "lat": float(row["纬度 (Latitude)"]),
                        "lon": float(row["经度 (Longitude)"]),
                        "timezone": str(row["当地时区"]),
                        "is_tracked": bool(row["是否追踪数据"]),
                        "is_tradable": bool(row["是否允许下注"])
                    }
                save_cities_config(new_cities_dict)
                st.success("🎉 城市配置与下注白名单已成功持久化并应用！")
                st.rerun()

# 底部运行日志
st.markdown("---")
st.markdown("### 📟 【系统运行日志 (System Daemon Logs)】")
if os.path.exists(LOG_PATH):
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            last_lines = lines[-30:] if len(lines) > 30 else lines
            log_content = "".join(last_lines)
            st.markdown(f"<div class='terminal-box'>{log_content}</div>", unsafe_allow_html=True)
    except Exception as e:
        st.error(f"读取日志异常: {str(e)}")
else:
    st.info("📟 暂无日志数据。")
