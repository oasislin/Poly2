"""
Polymarket 多城市结算结果拉取（7/24~7/26）
=============================================
11 个摄氏度 + Wunderground 结算的城市，与 ensemble 数据对齐。

拉取每个城市 highest-temperature-in-{city}-on-july-N-2026 (N=24,25,26) 共 33 个已关闭市场，
解析每个市场的 11 个温度 bin，找出胜出的那个 bin。

API：
  https://gamma-api.polymarket.com/events?slug=<slug>

输出：
  polymarket_settlements_multi.csv
    city, target_date, market_slug, winning_bin_title, settlement_temp_int_c, is_closed, is_resolved, n_markets
  polymarket_settlements_multi.json  （原始 events 响应，备查）
"""

import os
import json
import csv
import re
import datetime
import time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

CITIES = [
    "shanghai", "beijing", "tokyo", "seoul", "singapore",
    "london", "paris", "milan", "sao-paulo", "toronto", "cape-town",
]

# 目标日：7/24~7/26
DATES = [
    datetime.date(2026, 7, 24),
    datetime.date(2026, 7, 25),
    datetime.date(2026, 7, 26),
]

GAMMA_URL = "https://gamma-api.polymarket.com/events"


def date_to_slug(d):
    """date → 'july-24-2026'"""
    months = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]
    return f"{months[d.month - 1]}-{d.day}-{d.year}"


def _parse_prices(prices):
    """outcomePrices 可能是 JSON 字符串或 list。"""
    if isinstance(prices, list):
        return prices
    if isinstance(prices, str):
        try:
            return json.loads(prices)
        except (json.JSONDecodeError, TypeError):
            return [prices]
    return ["0", "0"]


def parse_bin_int(title):
    """从 groupItemTitle 解析出结算整数温度（向下取整后的值）。"""
    if not title:
        return None
    s = title.replace("°C", "").replace("°F", "").strip()
    m = re.match(r"^(\d+)\s*or\s*below$", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)\s*or\s*higher$", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)\s*to\s*(\d+)$", s)
    if m:
        return int(m.group(1))  # 区间取下界
    m = re.match(r"^(\d+)$", s)
    if m:
        return int(m.group(1))
    return None


def fetch_settlement(city_slug, target_date):
    date_slug = date_to_slug(target_date)
    event_slug = f"highest-temperature-in-{city_slug}-on-{date_slug}"
    try:
        r = requests.get(GAMMA_URL, params={"slug": event_slug}, timeout=20)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        events = r.json()
        if not events:
            return None, "NOT FOUND"
        ev = events[0]
        markets = ev.get("markets", [])
        if not markets:
            return None, "NO MARKETS"

        is_closed = ev.get("closed", False)
        is_resolved = False
        winning_title = None

        for m in markets:
            prices = _parse_prices(m.get("outcomePrices", ["0", "0"]))
            uma_status = m.get("umaResolutionStatus", "") or m.get("resolutionSource", "")
            if "resolved" in uma_status.lower() or (len(prices) >= 2 and (prices[0] == "1" or prices[1] == "1")):
                is_resolved = True
            if prices[0] == "1":
                winning_title = m.get("groupItemTitle", "")

        result = {
            "city": city_slug,
            "target_date": target_date.isoformat(),
            "market_slug": event_slug,
            "winning_bin_title": winning_title or "",
            "settlement_temp_int_c": parse_bin_int(winning_title) if winning_title else None,
            "is_closed": is_closed,
            "is_resolved": is_resolved,
            "n_markets": len(markets),
        }
        return result, ev  # 返回结果 + 原始事件
    except Exception as e:
        return None, str(e)


def main():
    all_rows = []
    all_raw = {}

    total = len(CITIES) * len(DATES)
    count = 0

    for ci, city in enumerate(CITIES):
        print(f"\n=== [{ci+1}/{len(CITIES)}] {city} ===")
        for d in DATES:
            count += 1
            print(f"  [{count}/{total}] {d.isoformat()} ...", end=" ")

            result, raw = fetch_settlement(city, d)
            if result:
                all_rows.append(result)
                status = "RESOLVED" if result["is_resolved"] else "UNRESOLVED"
                print(f"{status}  bin={result['winning_bin_title']}")
                if raw:
                    key = f"{city}_{d.isoformat()}"
                    all_raw[key] = {k: v for k, v in raw.items() if k != "markets"}
                    all_raw[key]["markets"] = [
                        {
                            "groupItemTitle": m.get("groupItemTitle"),
                            "outcomePrices": m.get("outcomePrices"),
                            "umaResolutionStatus": m.get("umaResolutionStatus"),
                        }
                        for m in raw.get("markets", [])
                    ]
            else:
                print(f"❌ {raw}")
            time.sleep(0.2)

    # 保存 CSV
    csv_path = os.path.join(HERE, "polymarket_settlements_multi.csv")
    fieldnames = ["city", "target_date", "market_slug", "winning_bin_title",
                  "settlement_temp_int_c", "is_closed", "is_resolved", "n_markets"]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nCSV 已保存: {csv_path} ({len(all_rows)} 行)")

    # 保存 JSON
    json_path = os.path.join(HERE, "polymarket_settlements_multi.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_raw, f, indent=2, ensure_ascii=False)
    print(f"JSON 已保存: {json_path}")

    # 摘要
    resolved = [r for r in all_rows if r["is_resolved"] and r["winning_bin_title"]]
    print(f"\n=== 摘要 ===")
    print(f"总请求数: {len(all_rows)}")
    print(f"已结算且有胜出 bin: {len(resolved)}")
    print(f"未结算/未找到: {len(all_rows) - len(resolved)}")

    if resolved:
        print(f"\n已结算的 city-day:")
        for r in resolved:
            print(f"  {r['city']:<15} {r['target_date']}  {r['winning_bin_title']}")


if __name__ == "__main__":
    main()
