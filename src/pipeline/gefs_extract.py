#!/usr/bin/env python3
"""GEFS reforecast station feature extractor.

Implements Task C (ADR-0008 D3, GEFS-WI-v1.1 §3, and specs):
Extracts temperature forecast time series for requested stations from raw
global GRIB2 subsets, using vectorized grid-point nearest-neighbor slicing.

Gates implemented / supported:
- V1: Raw file preservation (pure read-only extraction)
- V2: Coverage assertion (per-station x fxx grid)
- V3: Deduplication and idempotency
- V4: Golden sample zero-error reproduction
- V5 / V6: Physical interval and TMAX >= TMIN relation checks
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
import xarray as xr

from src.data_processing.constants import STATION_METADATA

logger = logging.getLogger("gefs_extract")

ACTIVE_11_STATIONS = (
    "KORD", "KLGA", "KATL", "KDAL", "KSEA", "KLAX",
    "KMIA", "KSFO", "KHOU", "KBKF", "KAUS"
)
DEFAULT_12_STATIONS = ACTIVE_11_STATIONS + ("KDCA",)


def _load_default_storage_root() -> str:
    """Load storage root dynamically from env or configs/default.yaml."""
    env_p = os.getenv("GEFS_DATA_ROOT")
    if env_p:
        return env_p
    cfg_file = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"
    if cfg_file.exists():
        try:
            import yaml
            with open(cfg_file, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
                root = d.get("storage", {}).get("cold_storage_root")
                if root:
                    return str(root)
        except (OSError, KeyError) as exc:
            logger.debug(f"Failed to load storage config: {exc}")
    return "data/raw"


@dataclass
class ExtractionArtifact:
    """Encapsulates output metadata for a single station-year Parquet file."""
    station: str
    year: int
    parquet_rel_path: str
    size_bytes: int
    sha256: str
    row_count: int
    lead_hours_steps: List[int]


@dataclass(frozen=True)
class ExtractionRecord:
    """Standardized extracted factor row representing a single forecast point."""
    init_date: str
    target_date: str
    station: str
    variable: str
    member: str
    lead_hours: int
    value_K: float
    vintage: str = "reforecast"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_station_id(identifier: str) -> str:
    """Resolve station identifier from ICAO code or city name (GEFS-WI-v1.1 §3)."""
    raw_upper = identifier.strip().upper()
    if raw_upper in STATION_METADATA:
        return raw_upper
    raw_lower = identifier.strip().lower()
    for icao, meta in STATION_METADATA.items():
        city = str(meta.get("city", "")).lower()
        poly_id = str(meta.get("polymarket_id", "")).lower()
        if city == raw_lower or poly_id == raw_lower:
            return icao
    raise KeyError(f"Station identifier or city '{identifier}' not found in STATION_METADATA")


def get_git_commit_sha() -> str:
    """Retrieve current Git commit SHA."""
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def compute_file_sha256(path: Union[str, Path]) -> str:
    """Compute SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_station_coords(
    stations: Optional[Sequence[str]] = None,
    include_zspd: bool = False,
) -> Dict[str, Tuple[float, float]]:
    """Return a mapping of station_id -> (latitude, longitude_360)."""
    selected = [resolve_station_id(s) for s in stations] if stations else list(DEFAULT_12_STATIONS)
    if include_zspd and "ZSPD" not in selected:
        selected.append("ZSPD")

    coords = {}
    for st in selected:
        meta = STATION_METADATA[st]
        lat = float(meta["latitude"])
        lon = float(meta["longitude"])
        lon_360 = (360.0 + lon) % 360.0 if lon < 0 else lon
        coords[st] = (lat, lon_360)
    return coords


def parse_grib_filename(filename: str) -> Optional[Dict[str, Any]]:
    """Parse GEFS reforecast subset filename, ignoring hidden/AppleDouble shadow files."""
    if filename.startswith(".") or not filename.endswith(".grib2"):
        return None

    base = filename[:-6]
    prefix, core = base.split("__", 1) if "__" in base else ("", base)
    pattern = r"^(tmax|tmin)_2m_(\d{8})(\d{2})_([a-z0-9]+)$"
    match = re.match(pattern, core)
    if not match:
        return None

    var_raw, init_date, cycle, member = match.groups()
    var_clean = "tmax" if "tmax" in var_raw else "tmin"
    subset_hash = prefix.replace("subset_", "") if prefix.startswith("subset_") else prefix
    return {
        "prefix": prefix,
        "subset_hash": subset_hash,
        "variable": var_clean,
        "init_date": f"{init_date[:4]}-{init_date[4:6]}-{init_date[6:]}",
        "cycle": int(cycle),
        "member": member,
    }


def _open_grib_dataset(file_path: Path, backend_kwargs: Optional[dict] = None) -> Optional[xr.Dataset]:
    """Safely open GRIB2 file using cfgrib with in-memory index by default."""
    kw = backend_kwargs or {"indexpath": ""}
    try:
        return xr.open_dataset(file_path, engine="cfgrib", backend_kwargs=kw)
    except Exception as exc:
        logger.warning(f"Failed to open GRIB2 {file_path.name}: {exc}")
        return None


def merge_datasets_defensively(datasets: Sequence[Optional[xr.Dataset]]) -> xr.Dataset:
    """Defensively merge xarray Datasets with NOAA coordinate attribute tolerance.

    Implements Spec User Story 6:
    Configures xr.merge with compat='override', combine_attrs='override' so that corrupted
    .idx sidecars or minor NOAA coordinate attribute differences never crash extraction.
    """
    valid_dss = [ds for ds in datasets if ds is not None]
    if not valid_dss:
        return xr.Dataset()
    if len(valid_dss) == 1:
        return valid_dss[0]
    return xr.merge(valid_dss, compat="override", combine_attrs="override")


def _slice_stations_grid(da: xr.DataArray, station_coords: Dict[str, Tuple[float, float]]) -> Tuple[List[str], np.ndarray]:
    """Vectorized nearest-neighbor slice for all stations using fast static grid indexing."""
    st_names = list(station_coords.keys())
    # Fast path: GEFS 0.25° standard global grid (721, 1440) -> sub-millisecond NumPy indexing
    if da.shape[-2:] == (721, 1440):
        lat_indices = [int(round((90.0 - float(station_coords[s][0])) / 0.25)) for s in st_names]
        lon_indices = [int(round(float(station_coords[s][1]) / 0.25)) % 1440 for s in st_names]
        vals = da.values
        if vals.ndim == 2:
            vals = vals[np.newaxis, ...]
        return st_names, vals[:, lat_indices, lon_indices]

    # Fallback: xarray nearest-neighbor matching for arbitrary test grids
    lat_da = xr.DataArray([station_coords[s][0] for s in st_names], dims="station")
    lon_da = xr.DataArray([station_coords[s][1] for s in st_names], dims="station")
    st_da = xr.DataArray(st_names, dims="station", name="station")
    sliced = da.sel(latitude=lat_da, longitude=lon_da, method="nearest").assign_coords(station=st_da)
    return st_names, sliced.values


def _matrix_to_records(
    meta: Dict[str, Any],
    st_names: List[str],
    fxx_hours: Sequence[int],
    val_matrix: np.ndarray,
    fxx_filter: Optional[Set[int]] = None,
) -> List[ExtractionRecord]:
    """Convert sliced value matrix to standardized typed ExtractionRecord instances."""
    init_d = meta["init_date"]
    records = []
    for step_idx, fxx in enumerate(fxx_hours):
        if fxx_filter and fxx not in fxx_filter:
            continue
        target_d = (datetime.strptime(init_d, "%Y-%m-%d") + timedelta(hours=int(fxx))).strftime("%Y-%m-%d")
        for st_idx, st_name in enumerate(st_names):
            raw_k = float(val_matrix[step_idx, st_idx])
            if np.isnan(raw_k):
                continue
            records.append(
                ExtractionRecord(
                    init_date=init_d,
                    target_date=target_d,
                    station=st_name,
                    variable=meta["variable"],
                    member=meta["member"],
                    lead_hours=int(fxx),
                    value_K=round(raw_k, 4),
                    vintage="reforecast",
                )
            )
    return records


def extract_file_records(
    file_path: Union[str, Path],
    station_coords: Dict[str, Tuple[float, float]],
    fxx_filter: Optional[Set[int]] = None,
    backend_kwargs: Optional[dict] = None,
) -> List[ExtractionRecord]:
    """Extract temperature records from a single GRIB2 file for all stations."""
    p = Path(file_path)
    meta = parse_grib_filename(p.name)
    if not meta:
        return []

    # GEFS-WI-v1.1 §1.7 技术坑防御: backend_kwargs 传入 indexpath="" 杜绝生成外部 .idx
    ds = _open_grib_dataset(p, backend_kwargs)
    if ds is None:
        return []

    var_name = meta["variable"]
    if var_name not in ds:
        data_vars = list(ds.data_vars)
        if len(data_vars) == 1:
            var_name = data_vars[0]
        else:
            ds.close()
            return []

    st_names, val_matrix = _slice_stations_grid(ds[var_name], station_coords)
    step_vals = ds["step"].values
    # GEFS-WI-v1.1 §1.7 技术坑防御: lead 换算小时统一用 / np.timedelta64(1, "h")
    if np.issubdtype(step_vals.dtype, np.timedelta64):
        fxx_hours = (step_vals / np.timedelta64(1, "h")).astype(int)
    else:
        fxx_hours = [int(s) for s in step_vals]
    ds.close()

    return _matrix_to_records(meta, st_names, fxx_hours, val_matrix, fxx_filter)


def extract_day_records(
    day_dir: Union[str, Path],
    station_coords: Dict[str, Tuple[float, float]],
    fxx_filter: Optional[Set[int]] = None,
    max_workers: int = 4,
) -> List[Dict[str, Any]]:
    """Extract and deduplicate all station records in a single date directory."""
    d = Path(day_dir)
    if not d.exists() or not d.is_dir():
        return []

    # GEFS-WI-v1.1 约束: 严格过滤 ._* macOS 属性文件
    grib_files = [f for f in d.iterdir() if f.is_file() and f.name.endswith(".grib2") and not f.name.startswith(".")]
    if not grib_files:
        return []

    all_records = []
    if max_workers > 1 and len(grib_files) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(extract_file_records, gf, station_coords, fxx_filter) for gf in grib_files]
            for fut in futures:
                all_records.extend(fut.result())
    else:
        for gf in grib_files:
            all_records.extend(extract_file_records(gf, station_coords, fxx_filter))

    # Deduplicate strictly on (station, member, variable, lead_hours) with decision logging
    seen = {}
    for r in all_records:
        key = (r.station, r.member, r.variable, r.lead_hours)
        if key in seen:
            logger.debug(f"去重决策: 发现重复切片 {key}，采纳权威内容副本")
        else:
            seen[key] = r
    return [r.to_dict() for r in seen.values()]


def extract_day_to_dataframe(
    day_dir: Union[str, Path],
    station_coords: Dict[str, Tuple[float, float]],
    fxx_filter: Optional[Set[int]] = None,
    max_workers: int = 4,
) -> pd.DataFrame:
    """Extract day records and return as a sorted pandas DataFrame."""
    records = extract_day_records(day_dir, station_coords, fxx_filter, max_workers)
    cols = ["init_date", "target_date", "station", "variable", "member", "lead_hours", "value_K", "vintage"]
    if not records:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(records)
    df.sort_values(by=["init_date", "station", "variable", "member", "lead_hours"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def validate_physical_bounds(df: pd.DataFrame, min_k: float = 213.15, max_k: float = 333.15) -> None:
    """Gate V5 / V6: Verify temperature interval [-60, +60] C (213.15K to 333.15K) and TMAX >= TMIN."""
    if df.empty:
        return

    if df["value_K"].isna().any() or np.isinf(df["value_K"]).any():
        raise ValueError("Gate V6 Violation: NaN or Inf values detected in value_K")

    val_min, val_max = df["value_K"].min(), df["value_K"].max()
    if val_min < min_k or val_max > max_k:
        raise ValueError(f"Gate V6 Violation: Temperature [{val_min:.2f}K, {val_max:.2f}K] outside [-60, +60]C [{min_k}K, {max_k}K]")

    # Check TMAX >= TMIN for same (init_date, station, member, lead_hours)
    piv = df.pivot_table(index=["init_date", "station", "member", "lead_hours"], columns="variable", values="value_K")
    if "tmax" in piv.columns and "tmin" in piv.columns:
        diff = piv["tmax"] - piv["tmin"]
        if (diff < -0.01).any():
            bad = piv[diff < -0.01].head(2).to_dict()
            raise ValueError(f"Gate V6 Violation: TMAX < TMIN observed: {bad}")


def validate_coverage_dimensions(
    df: pd.DataFrame,
    expected_stations: Sequence[str],
    expected_members: Sequence[str] = ("c00", "p01", "p02", "p03", "p04"),
    expected_vars: Sequence[str] = ("tmax", "tmin"),
    expected_fxx: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Gate V2: Dimension completeness validation."""
    if df.empty:
        raise ValueError("Gate V2 Violation: Dataframe is empty")

    missing_st = set(expected_stations) - set(df["station"].unique())
    if missing_st:
        raise ValueError(f"Gate V2 Violation: Missing stations: {sorted(missing_st)}")

    missing_mem = set(expected_members) - set(df["member"].unique())
    if missing_mem:
        raise ValueError(f"Gate V2 Violation: Missing members: {sorted(missing_mem)}")

    missing_v = set(expected_vars) - set(df["variable"].unique())
    if missing_v:
        raise ValueError(f"Gate V2 Violation: Missing variables: {sorted(missing_v)}")

    present_fxx = sorted(df["lead_hours"].unique())
    if expected_fxx and (set(expected_fxx) - set(present_fxx)):
        raise ValueError(f"Gate V2 Violation: Missing fxx: {sorted(set(expected_fxx) - set(present_fxx))}")

    return {
        "stations": len(df["station"].unique()),
        "members": len(df["member"].unique()),
        "variables": len(df["variable"].unique()),
        "lead_hours": present_fxx,
        "rows": len(df),
    }


def assert_golden_samples_gate(grib_root: Union[str, Path]) -> str:
    """Gate V4 Runner Gate: Verify golden reproduction on 20040101 (GEFS-WI-v1.1 §1.6 & §4 V4).

    Hard golden contract (tolerance <= 0.005 K):
    - ZSPD p03 (tmax_2m, 24h lead) = 282.53 K (historical benchmark)
    - KORD c00 / p03 (tmax_2m, 24h lead) = 278.81 K / 278.79 K
    - KORD c00 / p03 (tmin_2m, 24h lead) = 277.31 K / 277.34 K
    """
    p_day = Path(grib_root) / "20040101"
    if not p_day.exists():
        raise FileNotFoundError(f"Gate V4 FATAL: Golden sample benchmark directory {p_day} not found")

    logger.info("Executing Gate V4 golden sample startup assertion on 20040101...")
    coords = get_station_coords(stations=["KORD"], include_zspd=True)
    df = extract_day_to_dataframe(p_day, coords, fxx_filter={24}, max_workers=2)

    # 1. ZSPD golden assertion (benchmark: 282.53 K)
    zspd_val = float(df[(df["station"] == "ZSPD") & (df["member"] == "p03") & (df["variable"] == "tmax")]["value_K"].iloc[0])
    if abs(zspd_val - 282.53) > 0.005:
        raise RuntimeError(f"Gate V4 FATAL: ZSPD p03 tmax mismatch: {zspd_val:.4f} != 282.53 (tol 0.005K)")

    # 2. KORD tmax golden assertions (c00 = 278.81 K, p03 = 278.79 K)
    k_max_c00 = float(df[(df["station"] == "KORD") & (df["member"] == "c00") & (df["variable"] == "tmax")]["value_K"].iloc[0])
    if abs(k_max_c00 - 278.81) > 0.005:
        raise RuntimeError(f"Gate V4 FATAL: KORD c00 tmax mismatch: {k_max_c00:.4f} != 278.81")
    k_max_p03 = float(df[(df["station"] == "KORD") & (df["member"] == "p03") & (df["variable"] == "tmax")]["value_K"].iloc[0])
    if abs(k_max_p03 - 278.79) > 0.005:
        raise RuntimeError(f"Gate V4 FATAL: KORD p03 tmax mismatch: {k_max_p03:.4f} != 278.79")

    # 3. KORD tmin golden assertions (c00 = 277.31 K, p03 = 277.34 K)
    k_min_c00 = float(df[(df["station"] == "KORD") & (df["member"] == "c00") & (df["variable"] == "tmin")]["value_K"].iloc[0])
    if abs(k_min_c00 - 277.31) > 0.005:
        raise RuntimeError(f"Gate V4 FATAL: KORD c00 tmin mismatch: {k_min_c00:.4f} != 277.31")
    k_min_p03 = float(df[(df["station"] == "KORD") & (df["member"] == "p03") & (df["variable"] == "tmin")]["value_K"].iloc[0])
    if abs(k_min_p03 - 277.34) > 0.005:
        raise RuntimeError(f"Gate V4 FATAL: KORD p03 tmin mismatch: {k_min_p03:.4f} != 277.34")

    logger.info("✅ Gate V4 Golden sample verification PASSED (tolerance <= 0.005 K)")
    return "PASS"


class ManifestManager:
    """Manages manifest.json tracking extraction provenance and file checksums."""

    def __init__(self, manifest_path: Union[str, Path], source_path: str = "", golden_result: str = ""):
        self.manifest_path = Path(manifest_path)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path = str(source_path)
        self.golden_result = golden_result
        self.files: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.files = data.get("files", {})
                    if not self.source_path:
                        self.source_path = data.get("source_path", "")
                    if not self.golden_result:
                        self.golden_result = data.get("golden_sample_verification", "")
            except Exception:
                self.files = {}

    def record_artifact(self, art: ExtractionArtifact) -> None:
        """Record successful station-year artifact."""
        self.files[art.parquet_rel_path] = {
            "station": art.station,
            "year": art.year,
            "row_count": art.row_count,
            "size_bytes": art.size_bytes,
            "sha256": art.sha256,
            "lead_hours_steps": art.lead_hours_steps,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        """Serialize manifest.json to disk."""
        data = {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": get_git_commit_sha(),
            "source_path": self.source_path,
            "golden_sample_verification": self.golden_result,
            "total_station_years": len(self.files),
            "total_rows": sum(e["row_count"] for e in self.files.values()),
            "files": dict(sorted(self.files.items())),
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def save_station_year_parquet(df: pd.DataFrame, out_dir: Path, station: str, year: int) -> ExtractionArtifact:
    """Save dataframe to {out_dir}/{station}/{year}.parquet using Snappy compression."""
    st_dir = out_dir / station
    st_dir.mkdir(parents=True, exist_ok=True)
    pq_path = st_dir / f"{year}.parquet"

    df_out = df.copy()
    df_out["station"] = df_out["station"].astype("category")
    df_out["member"] = df_out["member"].astype("category")
    df_out["variable"] = df_out["variable"].astype("category")
    df_out["vintage"] = df_out["vintage"].astype("category")
    df_out["lead_hours"] = df_out["lead_hours"].astype("int32")
    df_out["value_K"] = df_out["value_K"].astype("float32")

    df_out.to_parquet(pq_path, compression="snappy", index=False)
    sz = pq_path.stat().st_size
    sha = compute_file_sha256(pq_path)
    rel_p = str(pq_path.relative_to(out_dir))
    steps = sorted(int(x) for x in df_out["lead_hours"].unique())

    return ExtractionArtifact(
        station=station,
        year=year,
        parquet_rel_path=rel_p,
        size_bytes=sz,
        sha256=sha,
        row_count=len(df_out),
        lead_hours_steps=steps,
    )


def extract_station_year(
    input_dir: Path,
    out_dir: Path,
    station: str,
    year: int,
    fxx_filter: Optional[Set[int]] = None,
    force: bool = False,
    max_workers: int = 2,
) -> Optional[ExtractionArtifact]:
    """Extract a single station-year with idempotency check."""
    target_pq = out_dir / station / f"{year}.parquet"
    if target_pq.exists() and not force:
        logger.info(f"Skipping completed station-year: {station}/{year} (idempotent)")
        return None

    coords = get_station_coords(stations=[station], include_zspd=(station == "ZSPD"))
    d_start = date(year, 1, 1)
    d_end = date(year, 12, 31)

    records = []
    curr = d_start
    while curr <= d_end:
        p_day = input_dir / curr.strftime("%Y%m%d")
        if p_day.exists():
            records.extend(extract_day_records(p_day, coords, fxx_filter, max_workers))
        curr += timedelta(days=1)

    if not records:
        logger.warning(f"No records found for {station}/{year}")
        return None

    df = pd.DataFrame(records)
    validate_physical_bounds(df)
    return save_station_year_parquet(df, out_dir, station, year)


def parse_years_arg(years_str: str) -> List[int]:
    """Parse year specification (e.g. '2004', '2000-2019', '2000,2004')."""
    if "-" in years_str:
        s, e = years_str.split("-", 1)
        return list(range(int(s.strip()), int(e.strip()) + 1))
    return [int(y.strip()) for y in years_str.split(",") if y.strip()]


def audit_input_directory(input_dir: Path, years: Sequence[int]) -> Dict[str, Any]:
    """Audit input directory against V1 criterion (20 GRIB2 files/day)."""
    total_days, complete_days, redundant_days = 0, 0, 0
    incomplete_days, missing_days, total_grib_files = 0, 0, 0

    for yr in years:
        d_curr = date(yr, 1, 1)
        d_end = date(yr, 12, 31)
        while d_curr <= d_end:
            total_days += 1
            day_p = input_dir / d_curr.strftime("%Y%m%d")
            if not day_p.exists():
                missing_days += 1
            else:
                gribs = [f for f in day_p.iterdir() if f.is_file() and not f.name.startswith(".") and f.name.endswith(".grib2")]
                cnt = len(gribs)
                total_grib_files += cnt
                if cnt >= 20:
                    complete_days += 1
                    if cnt > 20:
                        redundant_days += 1
                else:
                    incomplete_days += 1
            d_curr += timedelta(days=1)

    return {
        "total_expected_days": total_days,
        "complete_days_v1": complete_days,
        "redundant_days_v1": redundant_days,
        "incomplete_days_v1": incomplete_days,
        "missing_days": missing_days,
        "total_grib_files": total_grib_files,
    }


def _run_batch_dry_run(
    inp: Path,
    stations: Sequence[str],
    years: Sequence[int],
    fxx_filter: Optional[Set[int]],
    golden_status: str,
) -> Dict[str, Any]:
    """Execute dry-run pre-scan audit without modifying disk."""
    audit = audit_input_directory(inp, years)
    lead_count = len(fxx_filter) if fxx_filter else 2
    est_rows = audit["complete_days_v1"] * len(stations) * 5 * 2 * lead_count
    logger.info(
        f"[DRY RUN] Audit complete: {audit['complete_days_v1']}/{audit['total_expected_days']} complete days (V1). "
        f"Est. rows: {est_rows} across {len(stations)} stations."
    )
    return {
        "golden_sample_verification": golden_status,
        "dry_run": True,
        "audit_v1": audit,
        "estimated_rows": est_rows,
        "stations": list(stations),
        "years": list(years),
    }


def _extract_year_single_pass(
    inp: Path,
    yr: int,
    needed_stations: Sequence[str],
    fxx_filter: Optional[Set[int]],
    max_workers: int,
) -> Dict[str, list]:
    """Extract records for multiple stations in a single pass across one year's files."""
    coords = get_station_coords(stations=needed_stations, include_zspd=("ZSPD" in needed_stations))
    d_start = date(yr, 1, 1)
    d_end = date(yr, 12, 31)
    total_days = (d_end - d_start).days + 1

    station_records: Dict[str, list] = {st: [] for st in needed_stations}
    t_year_start = time.perf_counter()
    curr = d_start
    day_idx = 0

    while curr <= d_end:
        day_idx += 1
        p_day = inp / curr.strftime("%Y%m%d")
        if p_day.exists():
            day_recs = extract_day_records(p_day, coords, fxx_filter, max_workers)
            for r in day_recs:
                st_name = r.get("station")
                if st_name in station_records:
                    station_records[st_name].append(r)

        if day_idx % 10 == 0 or day_idx == total_days:
            elapsed = time.perf_counter() - t_year_start
            eta = (elapsed / day_idx) * (total_days - day_idx) if day_idx < total_days else 0
            logger.info(
                f"[PROGRESS] {yr} 年 {day_idx}/{total_days} ({day_idx/total_days*100:.1f}%) "
                f"[已耗时 {int(elapsed)}s, 预估剩余 {int(eta)}s] | {len(needed_stations)} 站特征同步抽取中"
            )
        curr += timedelta(days=1)
    return station_records


def _save_year_station_artifacts(
    out: Path,
    yr: int,
    needed_stations: Sequence[str],
    station_records: Dict[str, list],
    manifest: ManifestManager,
) -> Tuple[int, int]:
    """Validate and persist parquet files for each station, returning (count, rows)."""
    extracted_count, total_rows = 0, 0
    for st in needed_stations:
        recs = station_records.get(st, [])
        if not recs:
            logger.warning(f"No records found for {st}/{yr}")
            continue
        df = pd.DataFrame(recs)
        validate_physical_bounds(df)
        art = save_station_year_parquet(df, out, st, yr)
        manifest.record_artifact(art)
        extracted_count += 1
        total_rows += art.row_count
    return extracted_count, total_rows


def extract_batch(
    input_dir: Union[str, Path],
    out_dir: Union[str, Path],
    stations: Sequence[str],
    years: Sequence[int],
    fxx_filter: Optional[Set[int]] = None,
    dry_run: bool = False,
    force: bool = False,
    max_workers: int = 2,
) -> Dict[str, Any]:
    """Batch extract multiple stations and years in a single pass with golden verification and manifest logging."""
    inp, out = Path(input_dir), Path(out_dir)
    resolved_stations = [resolve_station_id(st) for st in stations]
    golden_status = assert_golden_samples_gate(inp)

    if dry_run:
        return _run_batch_dry_run(inp, resolved_stations, years, fxx_filter, golden_status)

    manifest_file = out / "manifest.json"
    manifest = ManifestManager(manifest_file, source_path=str(inp), golden_result=golden_status)
    extracted_count, skipped_count, total_rows = 0, 0, 0

    for yr in years:
        needed = [st for st in resolved_stations if force or not (out / st / f"{yr}.parquet").exists()]
        skipped_count += (len(resolved_stations) - len(needed))
        if not needed:
            continue

        st_records = _extract_year_single_pass(inp, yr, needed, fxx_filter, max_workers)
        e_cnt, r_cnt = _save_year_station_artifacts(out, yr, needed, st_records, manifest)
        extracted_count += e_cnt
        total_rows += r_cnt

    manifest.save()
    return {
        "golden_sample_verification": golden_status,
        "extracted_station_years": extracted_count,
        "skipped_station_years": skipped_count,
        "total_rows": total_rows,
        "manifest_path": str(manifest_file),
    }


def main():
    parser = argparse.ArgumentParser(description="GEFS station feature extractor CLI.")
    parser.add_argument("--input", "--grib-dir", dest="input", type=str, default=_load_default_storage_root(), help="Root path to raw GEFS storage")
    parser.add_argument("--out", "--output-dir", dest="out", type=str, default="data/processed/gefs_factors", help="Root path for Parquet output")
    parser.add_argument("--stations", type=str, default=",".join(DEFAULT_12_STATIONS), help="Comma-separated station IDs (default: all 12 stations)")
    parser.add_argument("--years", type=str, default="2000-2019", help="Years specification: YYYY or YYYY-YYYY")
    parser.add_argument("--fxx", type=str, default="", help="Optional comma-separated fxx filter")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without saving")
    parser.add_argument("--force", action="store_true", help="Overwrite existing station-year Parquet files")
    parser.add_argument("--max-workers", type=int, default=2, help="ThreadPool max workers (default 2 to protect external SSD)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )

    st_list = [resolve_station_id(s.strip()) for s in args.stations.split(",") if s.strip()]
    yr_list = parse_years_arg(args.years)
    fxx_set = set(int(x.strip()) for x in args.fxx.split(",") if x.strip()) if args.fxx else None

    res = extract_batch(args.input, args.out, st_list, yr_list, fxx_set, args.dry_run, args.force, args.max_workers)
    print("Extraction Summary:\n", json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

