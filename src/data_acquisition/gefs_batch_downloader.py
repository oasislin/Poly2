#!/usr/bin/env python3
"""
GEFS Batch Download and State Machine Manager (Task 1.2 T07).

Coordinates yearly chunk downloads of GEFS reforecast data across 2000-2019,
applies regional cropping immediately, and tracks state using a CSV state machine:
pending -> downloading -> downloaded -> cropped -> raw_ready -> (user_check=moved) -> done.
"""

import csv
import logging
from pathlib import Path
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

import xarray as xr

from src.data_acquisition.gefs_fetcher import (
    DEFAULT_REGIONS,
    GEFSFetcher,
    GEFSDownloadError,
    VALID_MEMBERS,
)

logger = logging.getLogger(__name__)

CSV_COLUMNS = ["year", "download", "crop", "user_check", "note"]
DEFAULT_TARGET_OFFSETS = (0, 1, 2)
GEFS_FXX_UNION = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]


@dataclass
class YearState:
    year: int
    download: str  # pending, in_progress, done, failed
    crop: str  # pending, in_progress, done, failed
    user_check: str  # empty or 'moved'
    note: str = ""

    def is_fully_done(self) -> bool:
        return self.download == "done" and self.crop == "done" and self.user_check == "moved"


def compute_init_windows(
    fetcher: GEFSFetcher,
    init_day: date,
    station: str,
    target_offsets: Sequence[int] = DEFAULT_TARGET_OFFSETS,
    fxx_filter: Optional[Sequence[int]] = None,
) -> List[int]:
    """Compute union of contained 6h forecast windows across target day offsets."""
    init_time = datetime(init_day.year, init_day.month, init_day.day, 0, 0)
    all_windows = set()
    for offset in target_offsets:
        target_date = init_day + timedelta(days=offset)
        wins = fetcher.select_contained_windows(init_time, target_date, station)
        if wins:
            all_windows.update(wins)
    if fxx_filter is not None:
        all_windows = all_windows.intersection(set(fxx_filter))
    return sorted(all_windows)


def check_and_prepare_shard(out_dir: Path, init_day: date) -> Tuple[Path, Path, bool]:
    """Check if shard already exists and md5 passes without deleting files."""
    out_path = out_dir / f"{init_day:%Y%m%d}.nc"
    md5_path = out_dir / f"{init_day:%Y%m%d}.nc.md5"
    if out_path.exists() and md5_path.exists():
        if GEFSFetcher.verify_file_md5(out_path, md5_path.read_text().strip()):
            return out_path, md5_path, True
    return out_path, md5_path, False


def _download_day_with_retry(
    fetcher: GEFSFetcher,
    bounds: Dict[str, Any],
    init_day: date,
    windows: List[int],
    station: str,
    max_retries: int = 3,
) -> Optional[xr.Dataset]:
    """Attempt download of single day reforecast with backoff retries."""
    for attempt in range(max_retries):
        try:
            return fetcher.download_reforecast(
                region_bounds=bounds,
                date_range=(init_day, init_day),
                members=list(VALID_MEMBERS),
                cycles=[0],
                forecast_hours=windows,
            )
        except Exception as exc:
            health_fn = getattr(fetcher, "check_link_health", GEFSFetcher.check_link_health)
            health = health_fn()
            logger.warning(
                f"⚠️ [{station.upper()} {init_day}] 单日下载异常 ({exc})，"
                f"第 {attempt + 1}/{max_retries} 轮重试... 诊断: {health['message']}"
            )
            if attempt < max_retries - 1:
                time.sleep(5.0 * (attempt + 1))
    return None


def _sweep_pass_failed_days(
    fetcher: GEFSFetcher,
    bounds: Dict[str, Any],
    station: str,
    failed_days: List[Tuple[date, List[int], Path, Path]],
) -> None:
    """Concentrated secondary sweep for days that failed initial download loop."""
    if not failed_days:
        return
    logger.info(f"🔄 [{station.upper()}] 开始对 {len(failed_days)} 个遗留异常日期集中补扫...")
    still_failed = []
    for init_d, wins, out_p, md5_p in failed_days:
        try:
            ds = fetcher.download_reforecast(
                region_bounds=bounds,
                date_range=(init_d, init_d),
                members=list(VALID_MEMBERS),
                cycles=[0],
                forecast_hours=wins,
            )
            ds.to_netcdf(out_p, engine="scipy")
            md5_p.write_text(GEFSFetcher.calculate_md5(out_p))
            logger.info(f"  ✨ [{station.upper()} {init_d}] 二次补扫成功落盘！")
        except Exception as exc:
            logger.error(f"  ❌ [{station.upper()} {init_d}] 补扫依然失败: {exc}")
            still_failed.append(init_d)
    if still_failed:
        raise GEFSDownloadError(f"{station} has {len(still_failed)} missing days: {still_failed}")


def _report_monthly_progress(
    init_day: date,
    current_month: int,
    completed: int,
    total: int,
    month_count: int,
    month_elapsed: float,
    fetcher: GEFSFetcher,
) -> Tuple[int, float, int]:
    """Print monthly download progress and link diagnostics."""
    pct = (completed / total) * 100
    avg_speed = month_elapsed / max(month_count, 1)
    rem_minutes = ((total - completed) * avg_speed) / 60.0
    health_fn = getattr(fetcher, "check_link_health", None)
    status_text, rtt_str = "正常", "未探测"
    if health_fn:
        health = health_fn()
        status_text = "正常" if health["healthy"] else "异常"
        rtt_str = f"RTT {health['rtt_ms']}ms" if health["rtt_ms"] is not None else "未知"
    print(
        f"[{init_day.year}-{current_month:02d} 完成] {month_count:2d} 天 ({pct:5.1f}%) | "
        f"平均: {avg_speed:4.1f}s/天 | 链路: {status_text} ({rtt_str}) | "
        f"预估剩余: {rem_minutes:4.1f} 分钟"
    )
    return init_day.month, 0.0, 0


def _download_station_dates(
    fetcher: GEFSFetcher,
    station: str,
    dates: Sequence[date],
    out_dir: Path,
    target_offsets: Sequence[int],
    fxx_filter: Optional[Sequence[int]],
) -> None:
    """Download reforecast data for a sequence of init dates for one station."""
    bounds = DEFAULT_REGIONS.get(station.lower(), DEFAULT_REGIONS.get("shanghai", {}))
    out_dir.mkdir(parents=True, exist_ok=True)
    total_days = len(dates)
    completed, month_count, month_elapsed = 0, 0, 0.0
    current_month = dates[0].month if dates else 1
    failed_days = []

    for init_day in dates:
        out_path, md5_path, skipped = check_and_prepare_shard(out_dir, init_day)
        t_start = time.perf_counter()
        if not skipped:
            windows = compute_init_windows(fetcher, init_day, station, target_offsets, fxx_filter)
            if not windows:
                continue
            ds = _download_day_with_retry(fetcher, bounds, init_day, windows, station)
            if ds is not None:
                ds.to_netcdf(out_path, engine="scipy")
                md5_path.write_text(GEFSFetcher.calculate_md5(out_path))
            else:
                failed_days.append((init_day, windows, out_path, md5_path))

        t_elapsed = time.perf_counter() - t_start
        completed += 1
        month_count += 1
        month_elapsed += t_elapsed
        next_day = init_day + timedelta(days=1)
        if (next_day.month != current_month or completed == total_days) and month_count > 0:
            current_month, month_elapsed, month_count = _report_monthly_progress(
                init_day, current_month, completed, total_days, month_count, month_elapsed, fetcher
            )

    _sweep_pass_failed_days(fetcher, bounds, station, failed_days)


def _heal_damaged_shard(
    fetcher: GEFSFetcher,
    src: Path,
    station: str,
    target_offsets: Sequence[int],
    max_heal_retries: int = 3,
) -> xr.Dataset:
    """Attempt opening dataset; self-heal with fresh re-download if corrupt."""
    for attempt in range(1, max_heal_retries + 1):
        try:
            return xr.open_dataset(src, engine="scipy")
        except Exception as exc:
            logger.warning(f"⚠️ 校验损坏文件 {src.name} ({exc})，第 {attempt}/{max_heal_retries} 次自愈重拉...")
            if attempt == max_heal_retries:
                raise RuntimeError(f"【熔断保护】文件 {src.name} 经修复后依然无法读取: {exc}")
            init_d = datetime.strptime(src.stem, "%Y%m%d").date()
            windows = compute_init_windows(fetcher, init_d, station, target_offsets)
            bounds = DEFAULT_REGIONS.get(station.lower(), DEFAULT_REGIONS.get("shanghai", {}))
            ds_fresh = fetcher.download_reforecast(
                region_bounds=bounds,
                date_range=(init_d, init_d),
                members=list(VALID_MEMBERS),
                cycles=[0],
                forecast_hours=windows,
            )
            if ds_fresh is not None:
                ds_fresh.to_netcdf(src, engine="scipy")
                src.with_suffix(".nc.md5").write_text(GEFSFetcher.calculate_md5(src))


def _crop_single_station(
    fetcher: GEFSFetcher,
    src_dir: Path,
    dst_dir: Path,
    station: str,
    year: int,
    target_offsets: Sequence[int],
) -> None:
    """Persist and verify single station cropped files."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(src_dir.glob("*.nc")) if src_dir.exists() else []
    if not files:
        if list(dst_dir.glob("*.nc")):
            return
        raise FileNotFoundError(f"no staged cropped data for {station} {year} under {src_dir}")

    for src in files:
        ds = _heal_damaged_shard(fetcher, src, station, target_offsets)
        dst = dst_dir / src.name
        ds.to_netcdf(dst, engine="scipy")
        _ = xr.open_dataset(dst, engine="scipy")
    logger.info(f"Cropped {station} {year}: {len(files)} files -> {dst_dir}")
    # Clean up temporary NetCDF staging directory (Note: raw GRIB files on SSD are never deleted)
    shutil.rmtree(src_dir)


class GEFSBatchDownloader:
    """Orchestrates yearly GEFS downloads with a CSV state machine."""

    def __init__(
        self,
        state_file: str = "data/gefs_download_state.csv",
        raw_cache_dir: str = "data/raw/gefs",
        processed_dir: str = "data/processed/gefs",
        stations: Optional[List[str]] = None,
        fetcher: Optional[GEFSFetcher] = None,
        target_offsets: Sequence[int] = DEFAULT_TARGET_OFFSETS,
        fxx_filter: Optional[Sequence[int]] = None,
        auto_continue: bool = False,
        check_interval: float = 2.0,
        verbose: bool = False,
    ):
        self.state_file = Path(state_file)
        self.raw_cache_dir = Path(raw_cache_dir)
        self.processed_dir = Path(processed_dir)
        self.stations = stations or ["shanghai", "denver"]
        self.fetcher = fetcher or GEFSFetcher(cache_dir=str(self.raw_cache_dir), verbose=verbose)
        self.target_offsets = tuple(target_offsets)
        self.fxx_filter = list(fxx_filter) if fxx_filter is not None else None
        self.auto_continue = auto_continue
        self.check_interval = check_interval
        self.verbose = verbose

        self.raw_cache_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load_or_init_state(self, start_year: int, end_year: int) -> Dict[int, YearState]:
        """Load state from CSV file or initialize with pending states."""
        states = {}
        if self.state_file.exists():
            with open(self.state_file, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row or not row.get("year"):
                        continue
                    yr = int(row["year"])
                    states[yr] = YearState(
                        year=yr,
                        download=row.get("download", "pending"),
                        crop=row.get("crop", "pending"),
                        user_check=row.get("user_check", ""),
                        note=row.get("note", ""),
                    )

        for yr in range(start_year, end_year + 1):
            if yr not in states:
                states[yr] = YearState(yr, "pending", "pending", "", "")

        self.save_state(states)
        return states

    def save_state(self, states: Dict[int, YearState]) -> None:
        """Persist states dictionary to CSV with atomic merge across processes."""
        merged = {}
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row and row.get("year"):
                            yr = int(row["year"])
                            merged[yr] = YearState(
                                yr, row.get("download", "pending"), row.get("crop", "pending"),
                                row.get("user_check", ""), row.get("note", "")
                            )
            except Exception:
                pass

        merged.update(states)
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for yr in sorted(merged.keys()):
                st = merged[yr]
                writer.writerow({"year": st.year, "download": st.download, "crop": st.crop, "user_check": st.user_check, "note": st.note})
        temp_file.replace(self.state_file)

    def _step_download(self, year: int, st: YearState, states: Dict[int, YearState], download_func: Optional[Callable]) -> None:
        if st.download != "done":
            st.download = "in_progress"
            self.save_state(states)
            try:
                if download_func:
                    download_func(year)
                else:
                    self._default_download_year(year)
                st.download = "done"
                st.note = f"Downloaded on {datetime.now().isoformat()}"
                self.save_state(states)
            except Exception as exc:
                st.download = "failed"
                st.note = f"Download failed: {exc}"
                self.save_state(states)
                raise

    def _step_crop(self, year: int, st: YearState, states: Dict[int, YearState], crop_func: Optional[Callable]) -> None:
        if st.crop != "done":
            st.crop = "in_progress"
            self.save_state(states)
            try:
                if crop_func:
                    crop_func(year)
                else:
                    self._default_crop_year(year)
                st.crop = "done"
                st.note = f"Cropped on {datetime.now().isoformat()}"
                self.save_state(states)
            except Exception as exc:
                st.crop = "failed"
                st.note = f"Crop failed: {exc}"
                self.save_state(states)
                raise

    def _step_user_check(self, year: int, st: YearState, states: Dict[int, YearState]) -> None:
        if st.user_check != "moved":
            print(f"\n{'='*70}\n[SIGNAL] Year {year} cropping completed!\nPlease mark user_check='moved' to proceed.\n{'='*70}\n")
            if self.auto_continue:
                logger.info(f"--auto-continue enabled: setting user_check='moved' for {year}")
                st.user_check = "moved"
                self.save_state(states)
            else:
                self._wait_for_user_moved(year, states)

    def process_year(
        self,
        year: int,
        states: Dict[int, YearState],
        download_func: Optional[Callable] = None,
        crop_func: Optional[Callable] = None,
    ) -> bool:
        """Execute state machine transitions for a single year chunk."""
        st = states[year]
        if st.is_fully_done():
            logger.info(f"Year {year} is already completed. Skipping.")
            return True
        self._step_download(year, st, states, download_func)
        self._step_crop(year, st, states, crop_func)
        self._step_user_check(year, st, states)
        return True

    def _wait_for_user_moved(self, year: int, states: Dict[int, YearState]) -> None:
        """Poll the CSV state file until user marks user_check='moved' for the year."""
        logger.info(f"Waiting for user to set user_check='moved' for year {year}...")
        while True:
            time.sleep(self.check_interval)
            updated = self.load_or_init_state(year, year)
            if updated[year].user_check.strip().lower() == "moved":
                states[year].user_check = "moved"
                self.save_state(states)
                logger.info(f"User check confirmed for year {year}. Resuming.")
                break

    def _default_download_year(self, year: int) -> None:
        """Download full year reforecast for all stations across target offsets."""
        init_start = max(date(year - 1, 12, 31), date(2000, 1, 1))
        init_end = date(year, 12, 30)
        dates = [init_start + timedelta(days=i) for i in range((init_end - init_start).days + 1)]
        staging_dir = self.raw_cache_dir / "cropped" / str(year)

        for station in self.stations:
            logger.info(f"==> 开始下载 {station.upper()} {year} 年数据 (共 {len(dates)} 个时次)...")
            _download_station_dates(
                fetcher=self.fetcher,
                station=station,
                dates=dates,
                out_dir=staging_dir / station,
                target_offsets=self.target_offsets,
                fxx_filter=self.fxx_filter,
            )

    def _default_crop_year(self, year: int) -> None:
        """Persist staged cropped data into the processed tree."""
        staging_dir = self.raw_cache_dir / "cropped" / str(year)
        for station in self.stations:
            _crop_single_station(
                fetcher=self.fetcher,
                src_dir=staging_dir / station,
                dst_dir=self.processed_dir / str(year) / station,
                station=station,
                year=year,
                target_offsets=self.target_offsets,
            )
        if staging_dir.exists() and not any(staging_dir.iterdir()):
            staging_dir.rmdir()

    def download_gap_days(
        self,
        gap_dates: Sequence[Union[str, date]],
        target_offsets: Optional[Sequence[int]] = None,
    ) -> None:
        """Download specified gap dates (B1 repair)."""
        if not gap_dates:
            logger.warning("No gap dates provided to download_gap_days.")
            return
        parsed_dates = [
            datetime.strptime(d, "%Y-%m-%d").date() if isinstance(d, str) else d
            for d in gap_dates
        ]
        offsets = target_offsets or self.target_offsets
        for yr in sorted(set(d.year for d in parsed_dates)):
            staging_dir = self.raw_cache_dir / "cropped" / str(yr)
            for station in self.stations:
                st_dates = [d for d in parsed_dates if d.year == yr]
                _download_station_dates(
                    fetcher=self.fetcher,
                    station=station,
                    dates=st_dates,
                    out_dir=staging_dir / station,
                    target_offsets=offsets,
                    fxx_filter=self.fxx_filter,
                )

    def run(
        self,
        start_year: int = 2000,
        end_year: int = 2019,
        download_func: Optional[Callable] = None,
        crop_func: Optional[Callable] = None,
    ) -> None:
        """Run the batch download scheduler from start_year to end_year."""
        states = self.load_or_init_state(start_year, end_year)
        for yr in range(start_year, end_year + 1):
            logger.info(f"--- Processing chunk: Year {yr} ---")
            self.process_year(yr, states, download_func=download_func, crop_func=crop_func)
        logger.info("All requested years completed successfully.")

