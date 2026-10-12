"""
Open-Meteo Ensemble API 多城市拉取（最近 3 天有效数据）
========================================================
与 main.py 中 analyst.py 保持一致：
  - API: ensemble-api.open-meteo.com/v1/ensemble
  - 模型: icon_seamless
  - 返回: hourly.temperature_2m + temperature_2m_member01~39（共 40 成员）

说明：
  Ensemble API 仅保留约 3 天历史数据。
  目标日：7/24 ~ 7/26（预报发出日 7/23 ~ 7/25）

11 个摄氏度 + Wunderground 结算的城市，覆盖不同气候带：
  亚洲: shanghai, beijing, tokyo, seoul, singapore
  欧洲: london, paris, milan
  美洲: sao-paulo, toronto
  非洲: cape-town

输出：
  openmeteo_ensemble_multi.csv
    city, target_date, forecast_issue_date, member_id, max_temp_c
  openmeteo_ensemble_multi.json
    {city: {target_date: {member_id: max_temp_c}}}
  openmeteo_ensemble_multi_summary.csv
    city, target_date, forecast_issue_date, mean, std, min, max, n_members
  openmeteo_ensemble_multi_raw/  （各城市原始 API 响应，备查）
"""

import os
import json
import csv
import math
import datetime
import time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

# 11 个城市配置（slug, 中文名/英文名, lat, lon, timezone）
CITIES = [
    {"slug": "shanghai",    "name": "Shanghai",     "lat": 31.15,   "lon": 121.8,    "tz": "Asia/Shanghai"},
    {"slug": "beijing",     "name": "Beijing",      "lat": 40.082,  "lon": 116.603,  "tz": "Asia/Shanghai"},
    {"slug": "tokyo",       "name": "Tokyo",        "lat": 35.553,  "lon": 139.781,  "tz": "Asia/Tokyo"},
    {"slug": "seoul",       "name": "Seoul",        "lat": 37.469,  "lon": 126.451,  "tz": "Asia/Seoul"},
    {"slug": "singapore",   "name": "Singapore",    "lat": 1.368,   "lon": 103.982,  "tz": "Asia/Singapore"},
    {"slug": "london",      "name": "London",       "lat": 51.5074, "lon": -0.1278,  "tz": "Europe/London"},
    {"slug": "paris",       "name": "Paris",        "lat": 48.97,   "lon": 2.441,    "tz": "Europe/Paris"},
    {"slug": "milan",       "name": "Milan",        "lat": 45.631,  "lon": 8.728,    "tz": "Europe/Rome"},
    {"slug": "sao-paulo",   "name": "Sao Paulo",    "lat": -23.432, "lon": -46.469,  "tz": "America/Sao_Paulo"},
    {"slug": "toronto",     "name": "Toronto",      "lat": 43.679,  "lon": -79.629,  "tz": "America/Toronto"},
    {"slug": "cape-town",   "name": "Cape Town",    "lat": -33.965, "lon": 18.602,   "tz": "Africa/Johannesburg"},
]

# 目标日范围（Ensemble API 仅保留约 3 天有效数据）
TARGET_START = datetime.date(2026, 7, 24)
TARGET_END = datetime.date(2026, 7, 26)

URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

# 40 个成员的 key
MEMBER_KEYS = ["temperature_2m"] + [f"temperature_2m_member{i:02d}" for i in range(1, 40)]


def fetch_ensemble_day(lat, lon, target_date_str, timezone):
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": target_date_str,
        "end_date": target_date_str,
        "hourly": "temperature_2m",
        "models": "icon_seamless",
        "timezone": timezone,
    }
    r = requests.get(URL, params=params, timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


def extract_member_max_temps(data, target_date_str):
    hourly = data.get("hourly", {}) or {}
    times = hourly.get("time", [])
    target_indices = [i for i, t in enumerate(times) if t.startswith(target_date_str)]
    if not target_indices:
        return {}

    result = {}
    for mid, key in enumerate(MEMBER_KEYS):
        if key not in hourly:
            continue
        vals = hourly[key]
        day_vals = [vals[i] for i in target_indices if i < len(vals) and vals[i] is not None]
        if day_vals:
            result[mid] = max(day_vals)
    return result


def main():
    all_rows = []       # 逐成员明细
    all_summaries = []  # 逐日摘要
    all_data = {}       # {city: {target_date: {member_id: max_temp}}}

    raw_dir = os.path.join(HERE, "openmeteo_ensemble_multi_raw")
    os.makedirs(raw_dir, exist_ok=True)

    total = len(CITIES)
    for ci, city in enumerate(CITIES):
        slug = city["slug"]
        print(f"\n=== [{ci+1}/{total}] {city['name']} ({slug}) ===")
        all_data[slug] = {}

        cur = TARGET_START
        while cur <= TARGET_END:
            td = cur.isoformat()
            forecast_issue_dt = cur - datetime.timedelta(days=1)
            print(f"  [{td}] 拉取 ensemble（预报发出日 {forecast_issue_dt}）...")

            data = fetch_ensemble_day(city["lat"], city["lon"], td, city["tz"])
            if not data:
                print(f"    ❌ 拉取失败")
                cur += datetime.timedelta(days=1)
                continue

            # 存原始响应
            raw_path = os.path.join(raw_dir, f"{slug}_{td}.json")
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            member_max = extract_member_max_temps(data, td)
            all_data[slug][td] = member_max

            n_members = len(member_max)
            if n_members == 0:
                print(f"    ⚠️  无有效成员数据（全 null）")
                cur += datetime.timedelta(days=1)
                continue

            # 逐成员明细
            for mid, tmax in sorted(member_max.items()):
                all_rows.append({
                    "city": slug,
                    "target_date": td,
                    "forecast_issue_date": forecast_issue_dt.isoformat(),
                    "member_id": mid,
                    "max_temp_c": round(tmax, 2),
                })

            # 摘要
            temps = list(member_max.values())
            mean_t = sum(temps) / len(temps)
            std_t = math.sqrt(sum((t - mean_t) ** 2 for t in temps) / len(temps))
            all_summaries.append({
                "city": slug,
                "target_date": td,
                "forecast_issue_date": forecast_issue_dt.isoformat(),
                "mean_max_temp_c": round(mean_t, 2),
                "std_max_temp_c": round(std_t, 2),
                "min_max_temp_c": round(min(temps), 2),
                "max_max_temp_c": round(max(temps), 2),
                "n_members": n_members,
            })
            print(f"    ✅ {n_members} 成员, mean={mean_t:.1f}°C, std={std_t:.2f}°C, range=[{min(temps):.1f}, {max(temps):.1f}]°C")

            cur += datetime.timedelta(days=1)
            time.sleep(0.2)

    # 保存成员最高温 dict
    max_path = os.path.join(HERE, "openmeteo_ensemble_multi.json")
    serializable = {
        city: {
            td: {str(mid): round(t, 2) for mid, t in members.items()}
            for td, members in tds.items()
        }
        for city, tds in all_data.items()
    }
    with open(max_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print(f"\n成员最高温已保存: {max_path}")

    # 保存明细 CSV
    csv_path = os.path.join(HERE, "openmeteo_ensemble_multi.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "target_date", "forecast_issue_date", "member_id", "max_temp_c"])
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"明细 CSV 已保存: {csv_path} ({len(all_rows)} 行)")

    # 保存摘要 CSV
    summary_path = os.path.join(HERE, "openmeteo_ensemble_multi_summary.csv")
    with open(summary_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "city", "target_date", "forecast_issue_date",
            "mean_max_temp_c", "std_max_temp_c", "min_max_temp_c", "max_max_temp_c", "n_members"
        ])
        writer.writeheader()
        writer.writerows(all_summaries)
    print(f"摘要 CSV 已保存: {summary_path} ({len(all_summaries)} 行)")

    # 统计
    valid = [s for s in all_summaries if s["n_members"] > 0]
    print(f"\n=== 统计 ===")
    print(f"城市数: {len(CITIES)}")
    print(f"每个城市目标天数: {(TARGET_END - TARGET_START).days + 1}")
    print(f"有效 ensemble 样本数: {len(valid)} 个 city-day")
    print(f"总成员-日样本数: {sum(s['n_members'] for s in valid)}")


if __name__ == "__main__":
    main()
