"""
多城市 Ensemble 40 成员 vs Polymarket 结算 对比分析
====================================================
按 (city, target_date) 对齐：
  - Open-Meteo Ensemble (icon_seamless, 40 成员)
  - Polymarket (Wunderground 结算，°C)

统计维度：
  1. 逐日逐城市：精确命中率、±1°C 命中率、集合均值误差
  2. 按城市汇总：3 天平均表现
  3. 全局汇总：所有 city-day 合并统计
  4. 按地区汇总：亚洲/欧洲/美洲/非洲

输出：
  comparison_multi_detail.csv   逐 city-day 明细
  comparison_multi_by_city.csv  按城市汇总
  comparison_multi.json         完整 JSON
"""

import os
import csv
import json
import re
import math

HERE = os.path.dirname(os.path.abspath(__file__))

CITY_REGIONS = {
    "shanghai": "Asia",
    "beijing": "Asia",
    "tokyo": "Asia",
    "seoul": "Asia",
    "singapore": "Asia",
    "london": "Europe",
    "paris": "Europe",
    "milan": "Europe",
    "sao-paulo": "Americas",
    "toronto": "Americas",
    "cape-town": "Africa",
}


def load_ensemble():
    """{city: {target_date: {member_id: max_temp_c}}}"""
    path = os.path.join(HERE, "openmeteo_ensemble_multi.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for city, tds in data.items():
        result[city] = {}
        for td, members in tds.items():
            result[city][td] = {int(mid): float(t) for mid, t in members.items()}
    return result


def load_settlements():
    """{city: {target_date: {winning_bin_title, settlement_temp_int_c, ...}}}"""
    path = os.path.join(HERE, "polymarket_settlements_multi.csv")
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            city = r["city"]
            td = r["target_date"]
            if city not in result:
                result[city] = {}
            stl = r.get("settlement_temp_int_c", "")
            r["settlement_temp_int_c"] = int(stl) if stl and stl != "None" else None
            result[city][td] = r
    return result


def compute_stats(member_temps, settlement_int):
    """
    给定 40 个成员的最高温列表 和 结算整数温度，
    返回各种命中率统计。
    """
    n = len(member_temps)
    if n == 0 or settlement_int is None:
        return None

    n_hit_exact = 0
    n_hit_within_1 = 0
    n_hit_within_2 = 0
    floors = []
    for t in member_temps:
        f = math.floor(t)
        floors.append(f)
        if f == settlement_int:
            n_hit_exact += 1
        if abs(f - settlement_int) <= 1:
            n_hit_within_1 += 1
        if abs(f - settlement_int) <= 2:
            n_hit_within_2 += 1

    mean_t = sum(member_temps) / n
    std_t = math.sqrt(sum((t - mean_t) ** 2 for t in member_temps) / n)
    min_t = min(member_temps)
    max_t = max(member_temps)
    mean_err = mean_t - settlement_int
    abs_mean_err = abs(mean_err)
    mean_floor_err = abs(math.floor(mean_t) - settlement_int)

    return {
        "n_members": n,
        "ensemble_mean_c": round(mean_t, 2),
        "ensemble_std_c": round(std_t, 2),
        "ensemble_min_c": round(min_t, 2),
        "ensemble_max_c": round(max_t, 2),
        "settlement_int_c": settlement_int,
        "mean_error_c": round(mean_err, 2),
        "abs_mean_error_c": round(abs_mean_err, 2),
        "mean_floor_abs_err": mean_floor_err,
        "n_hit_exact": n_hit_exact,
        "pct_hit_exact": round(100.0 * n_hit_exact / n, 1),
        "n_hit_within_1c": n_hit_within_1,
        "pct_hit_within_1c": round(100.0 * n_hit_within_1 / n, 1),
        "n_hit_within_2c": n_hit_within_2,
        "pct_hit_within_2c": round(100.0 * n_hit_within_2 / n, 1),
        "floor_distribution": sorted(floors),
    }


def main():
    ens = load_ensemble()
    pm = load_settlements()

    detail_rows = []
    by_city = {}
    by_region = {}

    all_cities = sorted(set(list(ens.keys()) + list(pm.keys())))

    for city in all_cities:
        ens_dates = ens.get(city, {})
        pm_dates = pm.get(city, {})
        all_dates = sorted(set(list(ens_dates.keys()) + list(pm_dates.keys())))

        city_stats_list = []
        for td in all_dates:
            members = ens_dates.get(td, {})
            pmr = pm_dates.get(td, {})
            stl_int = pmr.get("settlement_temp_int_c")

            member_temps = list(members.values())
            stats = compute_stats(member_temps, stl_int) if member_temps and stl_int is not None else None

            row = {
                "city": city,
                "region": CITY_REGIONS.get(city, "?"),
                "target_date": td,
                "n_members": len(member_temps),
                "winning_bin_title": pmr.get("winning_bin_title", ""),
                "settlement_int_c": stl_int,
                "ensemble_mean_c": stats["ensemble_mean_c"] if stats else None,
                "ensemble_std_c": stats["ensemble_std_c"] if stats else None,
                "ensemble_min_c": stats["ensemble_min_c"] if stats else None,
                "ensemble_max_c": stats["ensemble_max_c"] if stats else None,
                "abs_mean_error_c": stats["abs_mean_error_c"] if stats else None,
                "pct_hit_exact": stats["pct_hit_exact"] if stats else None,
                "pct_hit_within_1c": stats["pct_hit_within_1c"] if stats else None,
                "pct_hit_within_2c": stats["pct_hit_within_2c"] if stats else None,
                "n_hit_exact": stats["n_hit_exact"] if stats else None,
                "n_hit_within_1c": stats["n_hit_within_1c"] if stats else None,
                "floor_dist_csv": ",".join(str(f) for f in stats["floor_distribution"]) if stats else "",
            }
            detail_rows.append(row)
            if stats:
                city_stats_list.append(stats)

        if city_stats_list:
            n = len(city_stats_list)
            by_city[city] = {
                "city": city,
                "region": CITY_REGIONS.get(city, "?"),
                "n_days": n,
                "avg_pct_hit_exact": round(sum(s["pct_hit_exact"] for s in city_stats_list) / n, 1),
                "avg_pct_hit_within_1c": round(sum(s["pct_hit_within_1c"] for s in city_stats_list) / n, 1),
                "avg_pct_hit_within_2c": round(sum(s["pct_hit_within_2c"] for s in city_stats_list) / n, 1),
                "avg_abs_mean_err_c": round(sum(s["abs_mean_error_c"] for s in city_stats_list) / n, 2),
                "avg_ensemble_std_c": round(sum(s["ensemble_std_c"] for s in city_stats_list) / n, 2),
            }

            region = CITY_REGIONS.get(city, "?")
            if region not in by_region:
                by_region[region] = []
            by_region[region].extend(city_stats_list)

    # 写明细 CSV
    detail_fields = [
        "city", "region", "target_date", "n_members",
        "winning_bin_title", "settlement_int_c",
        "ensemble_mean_c", "ensemble_std_c", "ensemble_min_c", "ensemble_max_c",
        "abs_mean_error_c",
        "pct_hit_exact", "pct_hit_within_1c", "pct_hit_within_2c",
        "n_hit_exact", "n_hit_within_1c",
        "floor_dist_csv",
    ]
    detail_path = os.path.join(HERE, "comparison_multi_detail.csv")
    with open(detail_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(detail_rows)

    # 写按城市汇总 CSV
    city_fields = [
        "city", "region", "n_days",
        "avg_pct_hit_exact", "avg_pct_hit_within_1c", "avg_pct_hit_within_2c",
        "avg_abs_mean_err_c", "avg_ensemble_std_c",
    ]
    city_path = os.path.join(HERE, "comparison_multi_by_city.csv")
    with open(city_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=city_fields)
        writer.writeheader()
        for city in sorted(by_city.keys(), key=lambda c: -by_city[c]["avg_pct_hit_within_1c"]):
            writer.writerow(by_city[city])

    # 写 JSON
    json_path = os.path.join(HERE, "comparison_multi.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "detail": detail_rows,
            "by_city": by_city,
            "by_region_summary": {
                r: {
                    "n_city_days": len(stats_list),
                    "avg_pct_hit_exact": round(sum(s["pct_hit_exact"] for s in stats_list) / len(stats_list), 1),
                    "avg_pct_hit_within_1c": round(sum(s["pct_hit_within_1c"] for s in stats_list) / len(stats_list), 1),
                    "avg_pct_hit_within_2c": round(sum(s["pct_hit_within_2c"] for s in stats_list) / len(stats_list), 1),
                    "avg_abs_mean_err_c": round(sum(s["abs_mean_error_c"] for s in stats_list) / len(stats_list), 2),
                    "avg_ensemble_std_c": round(sum(s["ensemble_std_c"] for s in stats_list) / len(stats_list), 2),
                }
                for r, stats_list in by_region.items()
            },
        }, f, indent=2, ensure_ascii=False)

    # 打印报告
    valid = [r for r in detail_rows if r["n_members"] > 0 and r["settlement_int_c"] is not None]
    n_valid = len(valid)

    print(f"{'='*100}")
    print(f"多城市 Ensemble 40 成员 vs Polymarket 结算 对比报告")
    print(f"{'='*100}")

    print(f"\n样本概况:")
    print(f"  城市数: {len(all_cities)}")
    print(f"  有效对齐样本 (city-day): {n_valid}")
    print(f"  总成员-日样本数: {sum(r['n_members'] for r in valid)}")

    # 全局汇总
    if n_valid > 0:
        avg_exact = sum(r["pct_hit_exact"] for r in valid) / n_valid
        avg_within1 = sum(r["pct_hit_within_1c"] for r in valid) / n_valid
        avg_within2 = sum(r["pct_hit_within_2c"] for r in valid) / n_valid
        avg_abs_err = sum(r["abs_mean_error_c"] for r in valid) / n_valid
        avg_std = sum(r["ensemble_std_c"] for r in valid) / n_valid

        print(f"\n全局平均:")
        print(f"  精确命中率 (floor == 结算整数):    {avg_exact:>6.1f}%")
        print(f"  ±1°C 命中率 (|floor-结算| ≤ 1):    {avg_within1:>6.1f}%")
        print(f"  ±2°C 命中率 (|floor-结算| ≤ 2):    {avg_within2:>6.1f}%")
        print(f"  集合均值与结算绝对误差:            {avg_abs_err:>6.2f}°C")
        print(f"  平均 ensemble std (40成员离散度):  {avg_std:>6.2f}°C")

    # 按地区
    print(f"\n按地区汇总:")
    print(f"  {'region':<12} {'n':>4} {'exact%':>8} {'±1C%':>8} {'±2C%':>8} {'abs_err':>8} {'ens_std':>8}")
    print(f"  {'-'*70}")
    for region in sorted(by_region.keys()):
        sl = by_region[region]
        n = len(sl)
        if n == 0:
            continue
        print(f"  {region:<12} {n:>4} "
              f"{sum(s['pct_hit_exact'] for s in sl)/n:>8.1f} "
              f"{sum(s['pct_hit_within_1c'] for s in sl)/n:>8.1f} "
              f"{sum(s['pct_hit_within_2c'] for s in sl)/n:>8.1f} "
              f"{sum(s['abs_mean_error_c'] for s in sl)/n:>8.2f} "
              f"{sum(s['ensemble_std_c'] for s in sl)/n:>8.2f}")

    # 按城市排名（±1°C 命中率）
    print(f"\n按城市排名 (按 ±1°C 命中率降序):")
    print(f"  {'rank':>4} {'city':<15} {'region':<12} {'n':>3} {'exact%':>8} {'±1C%':>8} {'±2C%':>8} {'abs_err':>8} {'ens_std':>8}")
    print(f"  {'-'*85}")
    ranked = sorted(by_city.keys(), key=lambda c: -by_city[c]["avg_pct_hit_within_1c"])
    for i, city in enumerate(ranked):
        s = by_city[city]
        print(f"  {i+1:>4} {city:<15} {s['region']:<12} {s['n_days']:>3} "
              f"{s['avg_pct_hit_exact']:>8.1f} "
              f"{s['avg_pct_hit_within_1c']:>8.1f} "
              f"{s['avg_pct_hit_within_2c']:>8.1f} "
              f"{s['avg_abs_mean_err_c']:>8.2f} "
              f"{s['avg_ensemble_std_c']:>8.2f}")

    # 明细表格
    print(f"\n明细 (按日期):")
    print(f"  {'city':<15} {'date':<12} {'stl':>5} {'ens_mean':>9} {'ens_std':>8} {'abs_err':>8} {'exact%':>8} {'±1C%':>8} {'±2C%':>8}")
    print(f"  {'-'*90}")
    for r in sorted(detail_rows, key=lambda x: (x["target_date"], x["city"])):
        if r["n_members"] == 0 or r["settlement_int_c"] is None:
            print(f"  {r['city']:<15} {r['target_date']:<12} {'-':>5} {'-':>9} {'-':>8} {'-':>8} {'-':>8} {'-':>8} {'-':>8}")
            continue
        print(f"  {r['city']:<15} {r['target_date']:<12} {r['settlement_int_c']:>5} "
              f"{r['ensemble_mean_c']:>9.2f} {r['ensemble_std_c']:>8.2f} {r['abs_mean_error_c']:>8.2f} "
              f"{r['pct_hit_exact']:>8.1f} {r['pct_hit_within_1c']:>8.1f} {r['pct_hit_within_2c']:>8.1f}")

    print(f"\n输出文件:")
    print(f"  明细:   {detail_path}")
    print(f"  城市汇总: {city_path}")
    print(f"  JSON:    {json_path}")


if __name__ == "__main__":
    main()
