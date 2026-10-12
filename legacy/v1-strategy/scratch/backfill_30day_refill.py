"""
补齐 30 天历史数据中缺失的部分
================================
只处理已有文件但数据不完整的情况，不创建新文件。
"""

import os
import sys
import json
import time
import datetime
import requests
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config import CONFIG, load_cities_config
from scratch.fetch_30day_data import (
    fetch_ensemble_forecast, fetch_wunderground_hourly,
    fetch_token_price_history, get_wunderground_station,
    WUNDERGROUND_API_KEY, PROXIES, GAMMA_URL, CLOB_URL
)

BASE_DIR = os.path.join(PROJECT_ROOT, "storage", "backfill_30day")


def load_all_events_by_date():
    """重新拉取所有 Polymarket 事件并预匹配站点"""
    cities = load_cities_config()
    stations = {k: v for k, v in cities.items() if v.get("is_tracked", False)}
    
    from scratch.fetch_30day_data import date_range, match_event_to_station, START_DATE, END_DATE
    all_dates = date_range(START_DATE, END_DATE)
    
    events_by_date = {}
    for d in all_dates:
        end_date_min = f"{d}T00:00:00Z"
        end_date_max = f"{d}T23:59:59Z"
        url = f"{GAMMA_URL}/events?closed=true&tag_id=84&end_date_min={end_date_min}&end_date_max={end_date_max}&limit=200"
        try:
            resp = requests.get(url, proxies=PROXIES, timeout=15)
            if resp.status_code == 200:
                events = [e for e in resp.json() if "temperature" in e.get("title", "").lower()]
                station_events = {}
                for e in events:
                    matched = match_event_to_station(e, stations)
                    if matched:
                        station_events[matched] = e
                events_by_date[d] = station_events
        except:
            events_by_date[d] = {}
        time.sleep(0.3)
    
    return events_by_date


def refill_single_file(station_id, station_info, date_str, events_by_date):
    """补齐单个文件的缺失数据"""
    filepath = os.path.join(BASE_DIR, station_id, f"{date_str}.json")
    if not os.path.exists(filepath):
        return "skip"
    
    with open(filepath, "r") as f:
        data = json.load(f)
    
    changed = False
    lat = station_info["lat"]
    lon = station_info["lon"]
    tz_str = station_info["timezone"]
    
    # 1. 补齐预报（重试 3 次）
    if not data.get("raw_forecast"):
        for attempt in range(3):
            try:
                forecast = fetch_ensemble_forecast(lat, lon, date_str, tz_str)
                if forecast and "hourly" in forecast:
                    data["raw_forecast"] = forecast
                    changed = True
                    break
            except:
                pass
            time.sleep(1)
    
    # 2. 补齐实况
    if len(data.get("raw_observed_hourly", [])) == 0:
        hourly_obs = fetch_wunderground_hourly(station_id, date_str, tz_str)
        if hourly_obs:
            data["raw_observed_hourly"] = hourly_obs
            changed = True
    
    # 3. 补齐盘口
    if not data.get("market_snapshot"):
        station_events = events_by_date.get(date_str, {})
        matched_event = station_events.get(station_id)
        if matched_event:
            target_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            decision_dt = target_dt - datetime.timedelta(days=1)
            decision_dt = decision_dt.replace(hour=10, minute=0, second=0, tzinfo=datetime.timezone.utc)
            target_timestamp = int(decision_dt.timestamp())
            
            slug = matched_event.get("slug", "")
            title = matched_event.get("title", "")
            markets = matched_event.get("markets", [])
            
            ranges = []
            clob_books = {}
            price_history = {}
            
            for m in markets:
                cond_str = m.get("groupItemTitle", "") or m.get("question", "")
                clob_tokens = m.get("clobTokenIds", [])
                if isinstance(clob_tokens, str):
                    try:
                        clob_tokens = json.loads(clob_tokens)
                    except:
                        clob_tokens = []
                
                token_id = clob_tokens[0] if clob_tokens and len(clob_tokens) > 0 else ""
                no_token_id = clob_tokens[1] if clob_tokens and len(clob_tokens) > 1 else ""
                
                price_val = 0.50
                if token_id:
                    price, hist = fetch_token_price_history(token_id, target_timestamp)
                    if price is not None:
                        price_val = price
                        price_history[token_id] = hist
                    time.sleep(0.15)
                
                ranges.append({
                    "range_id": f"r{len(ranges)+1}",
                    "condition": cond_str,
                    "ask_price": price_val,
                    "yes_ask": price_val,
                    "no_ask": round(1.0 - price_val, 4),
                    "yes_token_id": token_id,
                    "no_token_id": no_token_id,
                })
                
                if token_id:
                    clob_books[token_id] = {
                        "bids": [{"price": str(max(0.01, round(price_val - 0.02, 2))), "size": "100"}],
                        "asks": [{"price": str(min(0.99, round(price_val + 0.02, 2))), "size": "100"}],
                    }
            
            data["market_snapshot"] = {
                "market_id": slug,
                "title": title,
                "target_date": date_str,
                "station_info": {
                    "station_id": station_id,
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": tz_str,
                },
                "timestamp": target_timestamp,
                "ranges": ranges,
            }
            data["clob_books"] = clob_books
            data["price_history"] = price_history
            changed = True
    
    if changed:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    
    has_forecast = data.get("raw_forecast") is not None
    has_observed = len(data.get("raw_observed_hourly", [])) > 0
    has_market = data.get("market_snapshot") is not None
    
    if has_forecast and has_observed and has_market:
        return "ok"
    else:
        missing = []
        if not has_forecast: missing.append("forecast")
        if not has_observed: missing.append("observed")
        if not has_market: missing.append("market")
        return f"partial({','.join(missing)})"


def main():
    cities = load_cities_config()
    stations = {k: v for k, v in cities.items() if v.get("is_tracked", False)}
    
    # 先扫描哪些需要补齐
    to_refill = []
    total = 0
    for station_id, info in stations.items():
        station_dir = os.path.join(BASE_DIR, station_id)
        if not os.path.isdir(station_dir):
            continue
        for f in os.listdir(station_dir):
            if not f.endswith('.json'):
                continue
            total += 1
            filepath = os.path.join(station_dir, f)
            date_str = f.replace('.json', '')
            with open(filepath, "r") as fp:
                data = json.load(fp)
            
            has_forecast = data.get("raw_forecast") is not None
            has_observed = len(data.get("raw_observed_hourly", [])) > 0
            has_market = data.get("market_snapshot") is not None
            
            if not (has_forecast and has_observed and has_market):
                to_refill.append((station_id, date_str))
    
    print(f"总文件: {total}")
    print(f"需补齐: {len(to_refill)}")
    for s, d in to_refill[:10]:
        print(f"  {s} {d}")
    if len(to_refill) > 10:
        print(f"  ... 共 {len(to_refill)} 个")
    
    # 重新拉取事件用于补齐盘口
    print("\n重新拉取 Polymarket 事件...")
    events_by_date = load_all_events_by_date()
    print(f"  共 {sum(len(v) for v in events_by_date.values())} 个事件匹配")
    
    # 并行补齐
    print(f"\n开始补齐 {len(to_refill)} 个文件...")
    done = 0
    ok = 0
    still_partial = 0
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for station_id, date_str in to_refill:
            future = executor.submit(
                refill_single_file, station_id, stations[station_id], date_str, events_by_date
            )
            futures[future] = (station_id, date_str)
        
        for future in as_completed(futures):
            station_id, date_str = futures[future]
            done += 1
            try:
                result = future.result()
                if result == "ok":
                    ok += 1
                else:
                    still_partial += 1
            except Exception as e:
                print(f"  [!] {station_id} {date_str}: {e}")
                still_partial += 1
            
            if done % 10 == 0 or done == len(to_refill):
                print(f"  [{done}/{len(to_refill)}] 成功:{ok} 仍缺失:{still_partial}")
    
    print(f"\n补齐完成！")
    print(f"  成功补齐: {ok}")
    print(f"  仍缺失: {still_partial}")


if __name__ == "__main__":
    main()
