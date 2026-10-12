import os
import json
import time
import re
import glob
import sqlite3
import requests
import concurrent.futures
import numpy as np
from scipy.optimize import minimize
from src.config import CONFIG, PROXIES, validate_contract, setup_logger

logger = setup_logger("Strategy")

PROTOCOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocols")
STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
DB_PATH = os.path.join(STORAGE_DIR, "arbitrage.db")

def extract_boundaries(ranges):
    """
    从所有温度区间条件中提取所有的边界数值。
    """
    boundaries = set()
    for r in ranges:
        cond = r["condition"].strip()
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", cond)
        for n in nums:
            boundaries.add(float(n))
    return list(boundaries)

def fetch_real_clob_book(token_id):
    """
    通过 CLOB API 拉取实时的订单簿挂单深度
    """
    if not token_id:
        return {"bids": [], "asks": []}
    clob_url = CONFIG["network_gateway"].get("polymarket_clob_url", "https://clob.polymarket.com")
    url = f"{clob_url}/book?token_id={token_id}"
    try:
        response = requests.get(url, proxies=PROXIES, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            # 必须显式排序：bids 按价格降序排列（最高买价优先），asks 按价格升序排列（最低卖价优先）
            sorted_bids = sorted([[float(b["price"]), float(b["size"])] for b in bids], key=lambda x: x[0], reverse=True)
            sorted_asks = sorted([[float(a["price"]), float(a["size"])] for a in asks], key=lambda x: x[0])
            
            return {
                "bids": sorted_bids,
                "asks": sorted_asks
            }
        elif response.status_code == 429:
            logger.warning(f"拉取 CLOB Book 触发频率限制 (429 Too Many Requests, Token: {token_id})")
        else:
            logger.warning(f"拉取 CLOB Book 状态码异常 (Token: {token_id}): {response.status_code}")
    except Exception as e:
        logger.warning(f"拉取实时 CLOB Book 异常 (Token: {token_id}): {e}")
    return {"bids": [], "asks": []}

def simulate_slippage(asks, stake_usdc, fallback_price=1.0):
    """
    模拟以总预算 stake_usdc 购买合约。
    asks: 格式为 [[price, size], ...]
    返回: (平均成交单价, 实际支出金额, 购买份数)
    """
    if stake_usdc <= 0:
        return fallback_price, 0.0, 0.0
    
    if not asks:
        # 降级：模拟真实盘口深度（符合 Polymarket 天气合约典型流动性）
        book = [
            (fallback_price, 300.0),                  # Best ask: 300 股
            (min(fallback_price + 0.01, 0.99), 500.0),  # +1% 价格: 500 股
            (min(fallback_price + 0.03, 0.99), 1000.0), # +3% 价格: 1000 股
            (min(fallback_price + 0.06, 0.99), 2000.0)  # +6% 价格: 2000 股
        ]
    else:
        book = asks
    
    remaining_usdc = stake_usdc
    shares_bought = 0.0
    actual_spent = 0.0
    
    for price, size in book:
        max_cost = price * size
        if remaining_usdc >= max_cost:
            shares_bought += size
            actual_spent += max_cost
            remaining_usdc -= max_cost
        else:
            shares_bought += remaining_usdc / price
            actual_spent += remaining_usdc
            remaining_usdc = 0.0
            break
            
    average_price = actual_spent / shares_bought if shares_bought > 0 else (book[0][0] if book else fallback_price)
    return average_price, actual_spent, shares_bought

def solve_kelly_yes_no(probs, q_eff_yes, q_eff_no, C_total, C_loc, K_u):
    """
    使用 scipy.optimize 求解包含双边 YES 和 NO 的多结局凸优化凯利公式
    """
    n = len(probs)
    limit = C_loc * K_u
    limit_fraction = limit / C_total
    
    # 优化变量为 2n 长度：f[:n] 为 YES 的投注比例，f[n:] 为 NO 的投注比例
    def objective(f):
        f_yes = f[:n]
        f_no = f[n:]
        
        total_fraction = np.sum(f_yes) + np.sum(f_no)
        
        sum_no_term = np.sum(f_no / q_eff_no)
        # 对于每种可能的结局 k，如果结算温度属于第 k 个档位：
        # NO 获胜的分红项为：除 k 之外的其他所有已买 NO 的总分红
        no_payouts = sum_no_term - (f_no / q_eff_no)
        yes_payouts = f_yes / q_eff_yes
        
        wealth_multipliers = 1.0 - total_fraction + yes_payouts + no_payouts
        
        if np.any(wealth_multipliers <= 1e-9):
            return 1e10
            
        return -np.sum(probs * np.log(wealth_multipliers + 1e-9))
        
    f0 = np.zeros(2 * n)
    bounds = [(0.0, limit_fraction) for _ in range(2 * n)]
    
    constraints = {
        'type': 'ineq',
        'fun': lambda f: limit_fraction - np.sum(f)
    }
    
    res = minimize(objective, f0, method='SLSQP', bounds=bounds, constraints=constraints)
    if res.success:
        x_yes = res.x[:n] * C_total
        x_no = res.x[n:] * C_total
        return x_yes, x_no
    return np.zeros(n), np.zeros(n)

def get_current_holdings(market_id):
    """
    查询本地数据库，获取当前该市场 pending 状态的持仓信息。
    返回: dict {"YES": {range_id: {...}}, "NO": {range_id: {...}}}
    """
    if not os.path.exists(DB_PATH):
        return {"YES": {}, "NO": {}}
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT range_id, stake_usdc, ask_price, trade_type FROM trades WHERE market_id = ? AND status = 'PENDING'", 
                (market_id,)
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            # 兼容未升级数据库表的情况
            cursor.execute(
                "SELECT range_id, stake_usdc, ask_price FROM trades WHERE market_id = ? AND status = 'PENDING'", 
                (market_id,)
            )
            rows = [row + ('YES',) for row in cursor.fetchall()]
            
        conn.close()
        
        raw_holdings = {"YES": {}, "NO": {}}
        for r_id, stake, price, t_type in rows:
            if price > 0:
                shares = stake / price
                t_type = t_type.upper() if t_type else "YES"
                if t_type not in raw_holdings:
                    raw_holdings[t_type] = {}
                if r_id not in raw_holdings[t_type]:
                    raw_holdings[t_type][r_id] = []
                raw_holdings[t_type][r_id].append((stake, shares))
                
        holdings = {"YES": {}, "NO": {}}
        for t_type in ["YES", "NO"]:
            for r_id, items in raw_holdings[t_type].items():
                tot_stake = sum(item[0] for item in items)
                tot_shares = sum(item[1] for item in items)
                avg_price = tot_stake / tot_shares if tot_shares > 0 else 0.0
                holdings[t_type][r_id] = {
                    "stake_usdc": tot_stake,
                    "avg_price": avg_price,
                    "shares": tot_shares
                }
        return holdings
    except Exception as e:
        logger.error(f"从数据库读取持仓失败: {str(e)}", extra={"market_id": market_id})
        return {"YES": {}, "NO": {}}

def calculate_single_strategy(snapshot_path, prob_path):
    """
    计算单个城市的套利期望和凸优化凯利仓位（双向 YES/NO）
    """
    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        with open(prob_path, "r", encoding="utf-8") as f:
            probability = json.load(f)
        validate_contract(snapshot, "market_snapshot")
        validate_contract(probability, "weather_probability")
    except Exception as e:
        logger.error(f"契约文件读取/校验失败，跳过策略分析！错误: {str(e)}", extra={"market_id": "STRATEGY"})
        return None

    market_id = snapshot["market_id"]
    status = snapshot.get("status", "active")
    if status != "active":
        logger.info(f"跳过 inactive/时间过滤 的合约策略分析: {market_id}", extra={"market_id": market_id})
        return None
        
    station_info = snapshot.get("station_info", {})
    timezone_str = station_info.get("timezone", "UTC")
    target_date_str = snapshot.get("target_date")
    
    # 确定结算参考时间点 (最高温当地 15:00, 最低温当地 05:00)
    is_lowest = "lowest" in market_id.lower()
    ref_hour = 5 if is_lowest else 15
    
    import datetime
    import pytz
    try:
        tz = pytz.timezone(timezone_str)
        now_station = datetime.datetime.now(tz)
        ref_dt = datetime.datetime.strptime(f"{target_date_str} {ref_hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
        ref_dt = tz.localize(ref_dt)
        delta_seconds = (ref_dt - now_station).total_seconds()
        hours_to_maturity = delta_seconds / 3600.0
    except Exception as e:
        logger.warning(f"计算剩余时间失败: {e}，默认设为临近决战时刻(3小时以内)", extra={"market_id": market_id})
        hours_to_maturity = 0.0

    # 读取系统参数
    risk_config = CONFIG.get("risk_control_lock", {})
    min_ev_threshold = risk_config.get("min_ev_threshold", 0.08)
    max_portfolio_exposure = risk_config.get("max_portfolio_exposure", 0.05)
    allocated_capital = risk_config.get("allocated_capital", 10000.0)
    taker_base_fee = risk_config.get("taker_base_fee", 0.0125)
    min_bet_usdc = risk_config.get("min_bet_usdc", 5.0)
    rebalance_hystersis_rate = risk_config.get("rebalance_hystersis_rate", 0.03)
    min_dutch_book_margin = risk_config.get("min_dutch_book_margin", 0.02)

    C_total = allocated_capital
    C_loc = C_total * max_portfolio_exposure  # 单市场最大资金占用上限

    # 提取概率映射和标准差
    prob_dist = probability["probability_distribution"]
    prob_map = {item["condition"]: item["calculated_prob"] for item in prob_dist}
    err_map = {item["condition"]: item.get("standard_error", 0.0) for item in prob_dist}
    simulated_sigma = probability.get("_simulated_sigma", 0.6)

    # 提取当前数据库持仓
    holdings = get_current_holdings(market_id)
    if holdings["YES"] or holdings["NO"]:
        logger.info(f"读取到当前活跃持仓: YES={holdings['YES']}, NO={holdings['NO']}", extra={"market_id": market_id})

    ranges = snapshot["ranges"]
    n = len(ranges)
    
    # 1. 收集需要拉取 CLOB 挂单薄的 token_id
    token_ids = []
    for r in ranges:
        yes_token = r.get("yes_token_id", "")
        no_token = r.get("no_token_id", "")
        if yes_token:
            token_ids.append(yes_token)
        if no_token:
            token_ids.append(no_token)
            
    # 并发拉取
    clob_books = {}
    if token_ids:
        # 并发上限控制为 5，温和拉取
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(token_ids), 5)) as executor:
            future_to_token = {executor.submit(fetch_real_clob_book, token_id): token_id for token_id in token_ids}
            for future in concurrent.futures.as_completed(future_to_token):
                token_id = future_to_token[future]
                try:
                    clob_books[token_id] = future.result()
                except Exception as e:
                    logger.warning(f"并发获取 CLOB Book 失败 (Token: {token_id}): {e}", extra={"market_id": market_id})
                    clob_books[token_id] = {"bids": [], "asks": []}
                    
    # 构建实时的 yes_prices 和 no_prices
    conditions = [r["condition"] for r in ranges]
    yes_prices_list = []
    no_prices_list = []
    
    for r in ranges:
        yes_token = r.get("yes_token_id", "")
        no_token = r.get("no_token_id", "")
        
        yes_asks = clob_books.get(yes_token, {}).get("asks", [])
        no_asks = clob_books.get(no_token, {}).get("asks", [])
        
        # 优先使用实时挂单的最佳 ask 价格
        yes_best = yes_asks[0][0] if yes_asks else r.get("yes_ask", r["ask_price"])
        no_best = no_asks[0][0] if no_asks else r.get("no_ask", 1.0)
        
        yes_prices_list.append(yes_best)
        no_prices_list.append(no_best)
        
    yes_prices = np.array(yes_prices_list)
    no_prices = np.array(no_prices_list)
    
    probs = np.array([prob_map.get(cond, 0.0) for cond in conditions])
    std_errors = np.array([err_map.get(cond, 0.0) for cond in conditions])
    
    # 提取系统参数用于时间自适应平滑收缩 (Time-Adaptive Sigmoid Shrinkage)
    q_min = risk_config.get("shrinkage_q_min", 0.01)
    q_max = risk_config.get("shrinkage_q_max", 0.05)
    t_scale = risk_config.get("shrinkage_t_scale", 24.0)
    k_exp = risk_config.get("shrinkage_k_exponent", 2.0)
    
    # 动态信任中值点 q_0
    q_0 = q_min + (q_max - q_min) * min(1.0, max(0.0, hours_to_maturity / t_scale))
    
    # 对胜率执行非线性平滑收缩，抵消尾部虚假高杠杆
    probs_shrunk = np.zeros(n)
    for i in range(n):
        p_model = probs[i]
        q_market = yes_prices[i]
        
        if q_market > 1e-9:
            w_q = 1.0 / (1.0 + (q_0 / q_market) ** k_exp)
        else:
            w_q = 0.0
            
        probs_shrunk[i] = w_q * p_model + (1.0 - w_q) * q_market
        logger.debug(
            f"尾部收缩 [{conditions[i]}]: q_market={q_market:.4f} | p_model={p_model:.4f} | "
            f"w_q={w_q:.4f} | p_shrunk={probs_shrunk[i]:.4f} | Edge_delta={p_model - q_market:+.4f} -> {probs_shrunk[i] - q_market:+.4f}",
            extra={"market_id": market_id}
        )
        
    logger.info(
        f"时间自适应胜率收缩: 距离结算 {hours_to_maturity:.1f}h | 信任中值点 q_0={q_0:.4f} | "
        f"最大胜率调整={np.max(np.abs(probs_shrunk - probs)):.4f}",
        extra={"market_id": market_id}
    )
    
    # 用收缩后的概率替代原始物理胜率进行下述归一化和测算
    probs = probs_shrunk

    # 归一化概率（确保和为 1.0）
    sum_probs = np.sum(probs)
    if sum_probs > 0:
        probs_normalized = probs / sum_probs
    else:
        probs_normalized = np.ones(n) / n

    # 确定分级置信系数 K_u (基础值 K_u_base)
    max_std_err = np.max(std_errors) if len(std_errors) > 0 else 0.0
    if max_std_err < 0.05:
        K_u_base = 0.50
        conf_level = "HIGH"
    elif max_std_err < 0.10:
        K_u_base = 0.25
        conf_level = "MEDIUM"
    else:
        K_u_base = 0.05
        conf_level = "LOW"
        
    # 升级 v3.8: 时间自适应分数凯利时间衰减 (Fractional Kelly Time-Decay)
    decay_lambda = risk_config.get("kelly_time_decay_lambda", 0.0578)
    min_fraction = risk_config.get("kelly_min_fraction", 0.20)
    
    # 根据剩余小时数计算时间衰减因子
    time_decay_factor = min_fraction + (1.0 - min_fraction) * np.exp(-decay_lambda * max(0.0, hours_to_maturity))
    K_u = K_u_base * time_decay_factor
    
    logger.info(
        f"市场置信度评级: {conf_level} (最大标准差={max_std_err:.4f}, 基础 K_u_base={K_u_base:.2f}) | "
        f"时间自适应分数凯利: 距离结算 {hours_to_maturity:.1f}h | 时间衰减因子={time_decay_factor:.4f} | "
        f"最终优化本金比例 K_u={K_u:.4f}",
        extra={"market_id": market_id}
    )

    # 动态手续费折算
    q_eff_yes = yes_prices * (1.0 + taker_base_fee * (1.0 - yes_prices))
    q_eff_no = no_prices * (1.0 + taker_base_fee * (1.0 - no_prices))

    # 1. Dutch Book 必胜套利与对冲标志初始化
    is_dutch_book = False
    is_hedge = False
    gamma_sigma = 1.0
    
    # 1.1 Dutch Book 必胜套利检查 (仅作用于 YES 互斥方向)
    sum_q_eff_yes = np.sum(q_eff_yes)
    
    if sum_q_eff_yes < 1.0 - min_dutch_book_margin:
        is_dutch_book = True
        logger.info(f"🔥 发现 Dutch Book 无风险套利机会！Σ q_eff_yes = {sum_q_eff_yes:.4f} < {1.0 - min_dutch_book_margin:.2f}", extra={"market_id": market_id})
        x_target_yes = (C_loc * K_u) * (q_eff_yes / sum_q_eff_yes)
        x_target_no = np.zeros(n)
        q_eff_yes_final = q_eff_yes
        q_eff_no_final = q_eff_no
    else:
        # 2. 反向锁利对冲（Reverse Lock-in Hedge）检查
        x_target_yes = np.zeros(n)
        x_target_no = np.zeros(n)
        q_eff_yes_final = q_eff_yes
        q_eff_no_final = q_eff_no
        
        # 优先使用买 NO 对冲
        for idx, r in enumerate(ranges):
            range_id = r["range_id"]
            if range_id in holdings["YES"]:
                h = holdings["YES"][range_id]
                p_yes_cost = h["avg_price"]
                shares = h["shares"]
                
                no_ask_eff = q_eff_no[idx]
                if p_yes_cost + no_ask_eff < 1.0 - min_dutch_book_margin:
                    is_hedge = True
                    logger.info(
                        f"🔒 发现直接买 NO 对冲机会！持有 YES range {range_id} 成本={p_yes_cost:.4f}, "
                        f"买入 NO 成本={no_ask_eff:.4f}, 合计={p_yes_cost + no_ask_eff:.4f} < 0.98",
                        extra={"market_id": market_id}
                    )
                    x_target_no[idx] = max(x_target_no[idx], shares * no_ask_eff)
                else:
                    # 降级方案：购买其他 YES 的组合对冲
                    other_sum_q_eff = np.sum([q_eff_yes[k] for k in range(n) if k != idx])
                    if p_yes_cost + other_sum_q_eff < 1.0 - min_dutch_book_margin:
                        is_hedge = True
                        logger.info(
                            f"🔒 发现多 outcome YES 组合对冲机会！持有 YES range {range_id} 成本={p_yes_cost:.4f}, "
                            f"其余档位买入总成本={other_sum_q_eff:.4f}, 合计={p_yes_cost + other_sum_q_eff:.4f} < 0.98",
                            extra={"market_id": market_id}
                        )
                        for k in range(n):
                            if k != idx:
                                x_target_yes[k] = max(x_target_yes[k], shares * q_eff_yes[k])
                                
        if is_hedge:
            # 限制对冲总额不超过本地预算
            tot_hedge = np.sum(x_target_yes) + np.sum(x_target_no)
            if tot_hedge > C_loc:
                scale = C_loc / tot_hedge
                x_target_yes *= scale
                x_target_no *= scale
        else:
            # 3. 标准双边 YES/NO 凸优化多结局凯利组合求解
            # 预过滤逻辑：仅将绝对亏损期望（Edge <= 0）的档位在求解器中设为极高价格（不可交易）
            q_eff_yes_pre = q_eff_yes.copy()
            q_eff_no_pre = q_eff_no.copy()
            for i in range(n):
                yes_edge = probs[i] - q_eff_yes[i]
                no_edge = (1.0 - probs[i]) - q_eff_no[i]
                if yes_edge <= 0.0:
                    q_eff_yes_pre[i] = 999.0
                if no_edge <= 0.0:
                    q_eff_no_pre[i] = 999.0

            # 第一轮：无滑点求解 Kelly
            x_raw_yes, x_raw_no = solve_kelly_yes_no(probs_normalized, q_eff_yes_pre, q_eff_no_pre, C_total, C_loc, K_u)
            
            # 第二轮：根据第一轮的资金大小，模拟订单簿滑点重新校正有效成本
            q_eff_yes_slip = np.zeros(n)
            q_eff_no_slip = np.zeros(n)
            for i in range(n):
                yes_token = ranges[i].get("yes_token_id", "")
                no_token = ranges[i].get("no_token_id", "")
                
                yes_asks = clob_books.get(yes_token, {}).get("asks", [])
                no_asks = clob_books.get(no_token, {}).get("asks", [])
                
                if x_raw_yes[i] > 0.1:
                    avg_price, _, _ = simulate_slippage(yes_asks, x_raw_yes[i], fallback_price=yes_prices[i])
                    q_eff_yes_slip[i] = avg_price * (1.0 + taker_base_fee * (1.0 - avg_price))
                else:
                    q_eff_yes_slip[i] = q_eff_yes_pre[i]
                    
                if x_raw_no[i] > 0.1:
                    avg_price, _, _ = simulate_slippage(no_asks, x_raw_no[i], fallback_price=no_prices[i])
                    q_eff_no_slip[i] = avg_price * (1.0 + taker_base_fee * (1.0 - avg_price))
                else:
                    q_eff_no_slip[i] = q_eff_no_pre[i]
            
            # 重新使用滑点校正后的价格求解 Kelly
            x_target_yes, x_target_no = solve_kelly_yes_no(probs_normalized, q_eff_yes_slip, q_eff_no_slip, C_total, C_loc, K_u)
            
            # 1. 计算物理噪声自适应资金缩水因子 gamma_sigma (仅作用于常规投机仓位，不影响 Dutch Book 和 Hedge 对冲)
            sigma_min = risk_config.get("obs_error_sigma_0", 0.6)
            gamma_min = risk_config.get("min_scaling_factor", 0.1)
            alpha = risk_config.get("scaling_sensitivity_alpha", 3.0)
            gamma_sigma = max(gamma_min, min(1.0, (sigma_min / simulated_sigma) ** alpha))
            
            x_target_yes *= gamma_sigma
            x_target_no *= gamma_sigma
            
            # 1.2 期望值非线性惩罚缩水因子 (Method B)
            # 对于低于 min_ev_threshold 但大于 0.0 的正 Edge 档位，应用立方衰减因子平滑限制下注额度
            for i in range(n):
                yes_edge = probs[i] - q_eff_yes[i]
                no_edge = (1.0 - probs[i]) - q_eff_no[i]
                
                # YES 档位缩水
                if yes_edge <= 0.0:
                    x_target_yes[i] = 0.0
                elif yes_edge < min_ev_threshold:
                    gamma_ev_yes = (yes_edge / min_ev_threshold) ** 3
                    x_target_yes[i] *= gamma_ev_yes
                    
                # NO 档位缩水
                if no_edge <= 0.0:
                    x_target_no[i] = 0.0
                elif no_edge < min_ev_threshold:
                    gamma_ev_no = (no_edge / min_ev_threshold) ** 3
                    x_target_no[i] *= gamma_ev_no
            
            logger.info(
                f"物理噪声自适应资金调控: 仿真标准差 σ={simulated_sigma:.3f}°C | 缩水因子 γ={gamma_sigma:.4f} | "
                f"最终缩水后投注额 YES/NO={np.sum(x_target_yes):.2f}/{np.sum(x_target_no):.2f} USDC",
                extra={"market_id": market_id}
            )
            
            # 2. 升级 v3.8: 移除旧硬顶，由于 K_u 已融入时间自适应分数衰减，Convex Optimizer 内部已实现平滑限仓
            q_eff_yes_final = q_eff_yes_slip
            q_eff_no_final = q_eff_no_slip

    execution_signals = []
    
    for i, r in enumerate(ranges):
        range_id = r["range_id"]
        cond = r["condition"]
        
        # 1. 评估 YES 信号
        yes_token = r.get("yes_token_id", "")
        yes_asks = clob_books.get(yes_token, {}).get("asks", [])
        
        # 实时计算当前计划买入金额 (delta_yes) 的滑点均价
        x_prev_yes = holdings["YES"].get(range_id, {}).get("stake_usdc", 0.0)
        delta_yes = x_target_yes[i] - x_prev_yes
        
        if delta_yes > 0:
            ask_price_yes, _, _ = simulate_slippage(yes_asks, delta_yes, fallback_price=yes_prices[i])
        else:
            ask_price_yes = yes_prices[i]
            
        real_prob_yes = probs[i]
        edge_yes = real_prob_yes - q_eff_yes_final[i]
        true_edge_yes = real_prob_yes - q_eff_yes[i]
        
        action_yes = "NO_ACTION"
        stake_yes = 0.0
        
        is_large_enough_yes = (delta_yes >= min_bet_usdc)
        is_above_hysteresis_yes = (delta_yes >= rebalance_hystersis_rate * C_loc) or is_dutch_book or is_hedge
        is_positive_edge_yes = (edge_yes > 0.0)
        expected_profit_yes = delta_yes * edge_yes
        is_worth_yes = (expected_profit_yes >= max(0.5, 0.05 * delta_yes)) or is_dutch_book or is_hedge
        
        if delta_yes > 0 and is_large_enough_yes and is_above_hysteresis_yes and is_positive_edge_yes and is_worth_yes:
            action_yes = "BUY_YES"
            stake_yes = round(float(delta_yes), 2)
            logger.info(
                f"区间 [{cond}] YES 确认生成买入信号！"
                f"目标: {x_target_yes[i]:.2f} USDC, 现有: {x_prev_yes:.2f} USDC, 新增: {stake_yes} USDC。"
                f"滑点均价: {ask_price_yes:.4f} | Edge: {edge_yes:.4f}",
                extra={"market_id": market_id}
            )

        # 2. 评估 NO 信号
        no_token = r.get("no_token_id", "")
        no_asks = clob_books.get(no_token, {}).get("asks", [])
        
        x_prev_no = holdings["NO"].get(range_id, {}).get("stake_usdc", 0.0)
        delta_no = x_target_no[i] - x_prev_no
        
        if delta_no > 0:
            ask_price_no, _, _ = simulate_slippage(no_asks, delta_no, fallback_price=no_prices[i])
        else:
            ask_price_no = no_prices[i]
            
        real_prob_no = 1.0 - probs[i]
        edge_no = real_prob_no - q_eff_no_final[i]
        true_edge_no = real_prob_no - q_eff_no[i]
        
        action_no = "NO_ACTION"
        stake_no = 0.0
        
        is_large_enough_no = (delta_no >= min_bet_usdc)
        is_above_hysteresis_no = (delta_no >= rebalance_hystersis_rate * C_loc) or is_hedge
        is_positive_edge_no = (edge_no > 0.0)
        expected_profit_no = delta_no * edge_no
        is_worth_no = (expected_profit_no >= max(0.5, 0.05 * delta_no)) or is_hedge
        
        if delta_no > 0 and is_large_enough_no and is_above_hysteresis_no and is_positive_edge_no and is_worth_no:
            action_no = "BUY_NO"
            stake_no = round(float(delta_no), 2)
            logger.info(
                f"区间 [{cond}] NO 确认生成买入信号！"
                f"目标: {x_target_no[i]:.2f} USDC, 现有: {x_prev_no:.2f} USDC, 新增: {stake_no} USDC。"
                f"滑点均价: {ask_price_no:.4f} | Edge: {edge_no:.4f}",
                extra={"market_id": market_id}
            )

        # 输出信号（划分 5 大精细化决策动作场景，保证监控与交易对账信息量最大化）
        has_positive_edge = (true_edge_yes > 0) or (true_edge_no > 0)
        
        if action_yes == "BUY_YES":
            final_action = "BUY_YES"
            final_stake = stake_yes
            final_ask = ask_price_yes
            final_prob = real_prob_yes
            final_ev = true_edge_yes
        elif action_no == "BUY_NO":
            final_action = "BUY_NO"
            final_stake = stake_no
            final_ask = ask_price_no
            final_prob = real_prob_no
            final_ev = true_edge_no
        elif x_prev_yes > 0 or x_prev_no > 0:
            final_action = "HOLD_SATISFIED" if has_positive_edge else "HOLD_INACTIVE"
            final_stake = 0.0
            if x_prev_yes > 0:
                final_ask = ask_price_yes
                final_prob = real_prob_yes
                final_ev = true_edge_yes
            else:
                final_ask = ask_price_no
                final_prob = real_prob_no
                final_ev = true_edge_no
        else:
            final_action = "IGNORE_LOW_EDGE" if has_positive_edge else "IGNORE_NO_EDGE"
            final_stake = 0.0
            final_ask = ask_price_yes
            final_prob = real_prob_yes
            final_ev = true_edge_yes
            
        execution_signals.append({
            "market_id": market_id,
            "range_id": range_id,
            "condition": cond,
            "market_ask": round(float(final_ask), 4),
            "real_prob": round(float(final_prob), 4),
            "expected_value": round(float(final_ev), 4),
            "action": final_action,
            "recommended_stake_usdc": final_stake,
            "yes_real_prob": round(float(real_prob_yes), 4),
            "no_real_prob": round(float(1.0 - real_prob_yes), 4),
            "yes_expected_value": round(float(true_edge_yes), 4),
            "no_expected_value": round(float(true_edge_no), 4)
        })

    signals_data = {
        "protocol_version": CONFIG["version"],
        "timestamp": int(time.time()),
        "execution_signals": execution_signals,
        "metadata": {
            "K_u": float(K_u),
            "K_u_base": float(K_u_base),
            "time_decay_factor": float(time_decay_factor),
            "gamma_sigma": float(gamma_sigma),
            "C_loc": float(C_loc),
            "C_total": float(C_total),
            "simulated_sigma": float(simulated_sigma),
            "hours_to_maturity": float(hours_to_maturity)
        },
        "_raw_clob_books": clob_books
    }

    try:
        validate_contract(signals_data, "arbitrage_signals")
        signals_path = os.path.join(PROTOCOLS_DIR, f"arbitrage_signals_{market_id}.json")
        with open(signals_path, "w", encoding="utf-8") as f:
            json.dump(signals_data, f, indent=2, ensure_ascii=False)
        logger.info(f"套利信号已持久化至 {signals_path}", extra={"market_id": market_id})
        return f"arbitrage_signals_{market_id}.json"
    except Exception as e:
        logger.error(f"策略引擎输出契约校验失败！错误: {str(e)}", extra={"market_id": market_id})
        return None

def run_strategy():
    """
    遍历计算所有城市的策略
    """
    logger.info("启动套利策略与期望值过滤引擎...", extra={"market_id": "STRATEGY"})

    snapshot_files = glob.glob(os.path.join(PROTOCOLS_DIR, "market_snapshot_*.json"))
    active_sig_files = []
    if snapshot_files:
        for fpath in snapshot_files:
            filename = os.path.basename(fpath)
            slug = filename.replace("market_snapshot_", "").replace(".json", "")
            prob_path = os.path.join(PROTOCOLS_DIR, f"weather_probability_{slug}.json")
            
            if os.path.exists(prob_path):
                sig_file = calculate_single_strategy(fpath, prob_path)
                if sig_file:
                    active_sig_files.append(sig_file)
            else:
                logger.warning(f"缺失该城市的概率契约文件，跳过策略: {prob_path}", extra={"market_id": "STRATEGY"})
    else:
        logger.warning("未在 protocols/ 目录下发现任何活跃的 market_snapshot 协议文件。", extra={"market_id": "STRATEGY"})
            
    # 清理陈旧的历史信号文件
    all_sig_files = glob.glob(os.path.join(PROTOCOLS_DIR, "arbitrage_signals_*.json"))
    for fpath in all_sig_files:
        fname = os.path.basename(fpath)
        if fname not in active_sig_files:
            try:
                os.remove(fpath)
                logger.info(f"清理陈旧的历史信号文件: {fname}", extra={"market_id": "STRATEGY"})
            except Exception as e:
                logger.warning(f"清理陈旧协议 {fname} 失败: {str(e)}", extra={"market_id": "STRATEGY"})
                
    # 兼容性清理原先单个 arbitrage_signals.json
    legacy_signals = os.path.join(PROTOCOLS_DIR, "arbitrage_signals.json")
    if os.path.exists(legacy_signals):
        os.remove(legacy_signals)

if __name__ == "__main__":
    run_strategy()
