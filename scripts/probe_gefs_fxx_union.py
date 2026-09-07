#!/usr/bin/env python3
"""
Task A: GEFS fxx union probe script.
Calculates completely contained 6h windows for all 12 stations x (Winter, Summer) x (D+0, D+1, D+2).
Outputs the detailed breakdown and final union list to docs/reports/gefs_fxx_union_probe.md.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_processing.constants import STATION_METADATA
from src.data_processing.time_aligner import (
    select_contained_6h_windows,
    select_contained_window_objects,
    get_local_day_bounds_utc,
)
from src.modeling.partitioner import (
    DatasetPartitioner,
    NOMINAL_LOCAL_HOURS,
    STATION_UTC_OFFSETS,
)

STATIONS_12 = [
    "KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX",
    "KMIA", "KSFO", "KHOU", "KBKF", "KAUS", "KDCA"
]

SEASONS_INFO = [
    ("Winter", date(2024, 1, 15)),
    ("Summer", date(2024, 7, 15)),
]

TARGET_OFFSETS = [
    ("D+0", 0),
    ("D+1", 1),
    ("D+2", 2),
]

def main():
    records = []
    all_fxx_union = set()
    per_season_union = {"Winter": set(), "Summer": set()}
    per_day_union = {"D+0": set(), "D+1": set(), "D+2": set()}
    per_station_union = {st: set() for st in STATIONS_12}

    print("=== Running Task A Probe for 12 Stations ===")

    for season_name, base_date in SEASONS_INFO:
        init_utc = datetime(base_date.year, base_date.month, base_date.day, 0, 0, tzinfo=timezone.utc)
        for st in STATIONS_12:
            tz_str = STATION_METADATA[st]["timezone"]
            tz = ZoneInfo(tz_str)
            for day_label, day_offset in TARGET_OFFSETS:
                target_date = base_date + timedelta(days=day_offset)
                bounds_start_utc, bounds_end_utc = get_local_day_bounds_utc(target_date, st)
                
                # Windows
                fxx_list = select_contained_6h_windows(init_utc, target_date, st, max_lead_hours=120)
                all_fxx_union.update(fxx_list)
                per_season_union[season_name].update(fxx_list)
                per_day_union[day_label].update(fxx_list)
                per_station_union[st].update(fxx_list)

                # Window objects
                win_objs = select_contained_window_objects(init_utc, target_date, st, max_lead_hours=120)
                win_strs = [f"f{w.fxx:03d}({w.start_lt.strftime('%H:%M')}-{w.end_lt.strftime('%H:%M')}LT)" for w in win_objs]

                # Partitioner nominal lead hours & round_to_nearest_6h
                # Compute continuous lead to nominal peak (15:00 LT for Max, 06:00 LT for Min)
                # Note: timezone aware local dt
                local_max_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=NOMINAL_LOCAL_HOURS["max"], tzinfo=tz)
                local_min_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=NOMINAL_LOCAL_HOURS["min"], tzinfo=tz)
                
                utc_max_dt = local_max_dt.astimezone(timezone.utc)
                utc_min_dt = local_min_dt.astimezone(timezone.utc)
                
                cont_lead_max = (utc_max_dt - init_utc).total_seconds() / 3600.0
                cont_lead_min = (utc_min_dt - init_utc).total_seconds() / 3600.0
                
                bucket_max = DatasetPartitioner.round_to_nearest_6h(cont_lead_max)
                bucket_min = DatasetPartitioner.round_to_nearest_6h(cont_lead_min)

                records.append({
                    "station": st,
                    "city": STATION_METADATA[st]["city"],
                    "timezone": tz_str,
                    "season": season_name,
                    "base_date": base_date.isoformat(),
                    "day_label": day_label,
                    "target_date": target_date.isoformat(),
                    "bounds_utc": f"{bounds_start_utc.strftime('%m-%d %H:%M')} ~ {bounds_end_utc.strftime('%m-%d %H:%M')}",
                    "fxx_list": fxx_list,
                    "windows_lt": ", ".join(win_strs),
                    "cont_lead_max": cont_lead_max,
                    "bucket_max": bucket_max,
                    "cont_lead_min": cont_lead_min,
                    "bucket_min": bucket_min,
                })

    df = pd.DataFrame(records)

    # Summary analysis
    sorted_union = sorted(list(all_fxx_union))
    print(f"\n>>> Total fxx Union across all 12 stations, both seasons, D+0..D+2: {sorted_union}")
    for d, s in per_day_union.items():
        print(f"  {d} Union: {sorted(list(s))}")
    for s_name, s in per_season_union.items():
        print(f"  {s_name} Union: {sorted(list(s))}")

    # Generate Markdown Report
    report_path = Path("docs/reports/gefs_fxx_union_probe.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# GEFS fxx 并集探针报告（Task A）\n\n")
        f.write("- **执行日期**：2026-09-07\n")
        f.write("- **前置依据**：ADR-0008（D1、D4）、GEFS-WI-v1.1 §3 Task A\n")
        f.write("- **探针方法**：调用 `src/data_processing/time_aligner.py::select_contained_6h_windows(init, target_date, station)`\n")
        f.write("- **测试矩阵**：12 站 × 2 季节代表日 (2024-01-15 冬季, 2024-07-15 夏季) × 3 目标日 (D+0, D+1, D+2 相对 00Z 起报)\n\n")
        
        f.write("## 1. 核心结论与权威采购清单\n\n")
        f.write("### 1.1 全池唯一权威 fxx 采购并集\n\n")
        f.write(f"```python\nGEFS_FXX_UNION = {sorted_union}\n```\n\n")
        f.write(f"- **总时效段数**：共 **{len(sorted_union)}** 个 6 小时步长时效段。\n")
        f.write("- **存量已覆盖段**：`{24, 30, 36}` 与 `{42, 48, 54}`（共 6 段）。\n")
        
        stock_set = {24, 30, 36, 42, 48, 54}
        new_short = sorted([x for x in sorted_union if x < 24])
        new_mid = sorted([x for x in sorted_union if 24 <= x <= 54 and x not in stock_set])
        new_long = sorted([x for x in sorted_union if x > 54])
        
        f.write(f"- **存量外新增采购段 (Task B2 范围)**：\n")
        f.write(f"  - 短 lead 段：`{new_short}`\n")
        f.write(f"  - 中 lead 缝隙段：`{new_mid}`\n")
        f.write(f"  - 长 lead 段：`{new_long}`\n")
        f.write(f"  - 新增合计：`{sorted(new_short + new_mid + new_long)}`（共 **{len(new_short + new_mid + new_long)}** 段）。\n\n")

        f.write("### 1.2 按目标日 (D+0 / D+1 / D+2) 拆解并集\n\n")
        f.write("| 目标日 | 覆盖 fxx 集合 | 解释 |\n")
        f.write("|---|---|---|\n")
        for d_lbl in ["D+0", "D+1", "D+2"]:
            u = sorted(list(per_day_union[d_lbl]))
            f.write(f"| **{d_lbl}** | `{u}` | 本地日 D+{d_lbl[-1]} 完整包含的 6h 窗口 |\n")
        f.write("\n")

        f.write("## 2. 站点明细表 (12 站 × 冬夏 × D+0..D+2)\n\n")
        f.write("| 站点 | 城市 | 时区 | 季节 | 目标日 | 本地日 UTC 区间 | 完整包含的 6h 窗口 (fxx) | 对应本地时间窗口 (LT) |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in records:
            f.write(f"| `{r['station']}` | {r['city']} | `{r['timezone']}` | {r['season']} | {r['day_label']} | `{r['bounds_utc']}` | `{r['fxx_list']}` | {r['windows_lt']} |\n")
        f.write("\n")

        f.write("## 3. 归桶语义分析（round_to_nearest_6h 与名义极值）\n\n")
        f.write("### 3.1 partitioner.py 的输入语义\n")
        f.write("- **名义发生时刻**：`TMAX = 15:00 LT`, `TMIN = 06:00 LT`。\n")
        f.write("- **连续 lead 计算公式**：`lead_hours = (nominal_local_dt.astimezone(UTC) - init_00Z_utc).total_seconds() / 3600.0`。\n")
        f.write("- **离散归桶**：`round_to_nearest_6h(lead) = int(np.round(lead / 6.0) * 6.0)`。\n\n")

        f.write("### 3.2 冬夏 DST 对归桶结果的影响\n\n")
        f.write("| 站点 | 时区 | 季节 | UTC 偏移 | D+0 TMAX (连续/桶) | D+1 TMAX (连续/桶) | D+2 TMAX (连续/桶) | D+0 TMIN (连续/桶) | D+1 TMIN (连续/桶) | D+2 TMIN (连续/桶) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        
        # Unique station x season
        seen = set()
        for r in records:
            key = (r["station"], r["season"])
            if key in seen:
                continue
            seen.add(key)
            # Find D+0, D+1, D+2 for this key
            d0_rec = [x for x in records if x["station"] == r["station"] and x["season"] == r["season"] and x["day_label"] == "D+0"][0]
            d1_rec = [x for x in records if x["station"] == r["station"] and x["season"] == r["season"] and x["day_label"] == "D+1"][0]
            d2_rec = [x for x in records if x["station"] == r["station"] and x["season"] == r["season"] and x["day_label"] == "D+2"][0]
            
            # UTC offset string
            tz = ZoneInfo(r["timezone"])
            dt = datetime.fromisoformat(r["base_date"]).replace(tzinfo=tz)
            offset_hrs = int(dt.utcoffset().total_seconds() / 3600)
            offset_str = f"UTC{offset_hrs:+d}"

            f.write(f"| `{r['station']}` | `{r['timezone']}` | {r['season']} | {offset_str} | "
                    f"{d0_rec['cont_lead_max']:.1f}h / **{d0_rec['bucket_max']}h** | "
                    f"{d1_rec['cont_lead_max']:.1f}h / **{d1_rec['bucket_max']}h** | "
                    f"{d2_rec['cont_lead_max']:.1f}h / **{d2_rec['bucket_max']}h** | "
                    f"{d0_rec['cont_lead_min']:.1f}h / **{d0_rec['bucket_min']}h** | "
                    f"{d1_rec['cont_lead_min']:.1f}h / **{d1_rec['bucket_min']}h** | "
                    f"{d2_rec['cont_lead_min']:.1f}h / **{d2_rec['bucket_min']}h** |\n")
        f.write("\n")

        f.write("### 3.3 关键观察与规避陷阱\n\n")
        f.write("1. **美洲站点的投影位移**：\n")
        f.write("   - 东八区（ZSPD，UTC+8）D+0 15:00 LT 对应 07:00 UTC -> 归桶为 6h；\n")
        f.write("   - 但美洲站点（UTC-4 至 UTC-8）D+0 15:00 LT 发生在起报日晚间至次日凌晨 UTC（19:00 UTC ~ 23:00 UTC） -> 归桶为 **18h 或 24h**！\n")
        f.write("   - 对应 D+1 归桶为 **42h 或 48h**，D+2 归桶为 **66h 或 72h**。\n")
        f.write("2. **DST 切换带来的 6h 跨桶漂移**：\n")
        f.write("   - 例如中部时区（Chicago KORD）：冬季 UTC-6，D+0 TMAX 为 21.0h -> 归桶 **24h**；夏季 UTC-5，D+0 TMAX 为 20.0h -> 归桶 **18h**（因 20/6=3.33，round 为 3 -> 18h）！\n")
        f.write("   - 这铁证了 **ADR-0008 D4（时区与节点自适应）** 的绝对必要性：任何静态硬编码 {6, 30, 54} 都会在美洲站点的夏冬令时交界处导致致命的特征对齐错位！\n")
        f.write("3. **完全包含规则（subseteq）的窗口特征**：\n")
        f.write("   - 美洲各站每个本地日能够完全包含 3 个或 4 个 6 小时窗口；\n")
        f.write("   - 全池在 D+0 / D+1 / D+2 的包含窗口总并集精确收敛在上述权威采购清单中，下载调度器必须按全量并集统一抓取。\n")

    print(f"\nReport written to {report_path}")

if __name__ == "__main__":
    main()
