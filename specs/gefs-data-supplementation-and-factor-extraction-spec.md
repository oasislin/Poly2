# Specification: GEFS 数据补全、站点提取与质量验证 (Phase 1.5 Task 09)

## Problem Statement

当前 GEFS 再预报存量数据存在两大核心断层：
1. **时效截断与年份缺口**：存量 lead 仅覆盖 {24, 30, 36}h 与 {42, 48, 54}h，短 lead（0–21h）与长 lead（60h+）因历史下载脚本硬编码 `target_date = init_day + timedelta(days=1)` 从未被调度；存量年份在 2005–2009 与 2015–2017 存在未知缺口。
2. **时区与站点脱节**：旧节点体系按上海（UTC+8）投影，美洲 12 站本地日投影整体右移，夏冬令时交替导致归桶产生 6h 漂移；且存量 GRIB 虽为全球场，但未建立统一参数化提取工具，下游 Task 06 特征库无法直接消费。同时必须确保原始 GRIB 零删除冷归档、去重决策透明、金样本数值百分之百复现。

## Solution

1. **确立权威采购清单与时区自适应规则（Task 0 & Task A 已完成）**：基于 ADR-0008 裁决与探针实测，锁定全池权威并集 `GEFS_FXX_UNION = [12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78]`；
2. **存量盘点与下载补齐（Task B）**：
   - 扫描外部存储 `/Volumes/EricSSD/Poly RawData/gefs_reforecast/`，实施每日 20 报文完整性盘点（V1），出具缺口与冗余报告；
   - 修复批量下载器多目标日调度 Bug（`target_date ∈ {init, init+1, init+2}`），B1 补齐存量段缺口年份，B2 抓取新增 6 个 lead 段（2000–2019 全期）；
3. **参数化提取器开发（Task C）**：
   - 实现 `src/pipeline/gefs_extract.py`，支持递归扫描、内容去重（基于日期/变量/成员/lead 内容指纹，严禁按文件名去重）、cfgrib 防御性读取（`indexpath=""`, `compat='override'`）、金样本实时断言；
   - 产出 `{station}/{year}.parquet`，长表结构 `(date, station, variable, member, lead, value_K, vintage)` 直接对接 Task 06 特征库；输出 `manifest.json` 固化审计四元组；
4. **全量质检与终验报告（Task D）**：逐项执行 V1–V13 门禁验收，出具综合 QC 报告 `docs/reports/gefs_task09_qc_v1.0.md`。

## User Stories

1. As a data pipeline engineer, I want the external storage raw GRIB directory to be comprehensively inventoried (20 files/day benchmark), so that missing dates and redundant file pairs are mathematically identified before downloading.
2. As a pipeline maintainer, I want the batch downloader scheduler fixed to iterate through `{init, init+1, init+2}` driven by `select_contained_6h_windows`, so that Day 0 and Day 2 windows are never dropped.
3. As a quant developer, I want all raw GRIB files retained on external cold storage without any physical deletions or file moves, so that raw data assets are permanently auditable and preserve unextracted meteorological fields.
4. As an ML engineer, I want a single parameterized CLI `src.pipeline.gefs_extract` accepting `--input`, `--out`, `--stations`, `--years`, and `--dry-run`, so that extraction is decoupled from local file layout.
5. As a quality engineer, I want deduplication performed strictly on semantic content tuples `(init_date, variable, ensemble_member, lead_hour)` rather than filename prefixes, so that redundant or mislabeled chunks do not create duplicates or corrupt factors.
6. As a systems engineer, I want `cfgrib` invocations hardened with `backend_kwargs={"indexpath": ""}` and `xr.merge` configured with `compat='override', coords='minimal'`, so that corrupted `.idx` sidecars or NOAA coordinate attribute differences never crash extraction.
7. As a quant risk manager, I want the extraction runner to assert golden samples (KORD and ZSPD at 2004-01-01 00Z) upon every run and exit non-zero immediately upon mismatch, so that data drift or indexing regressions are blocked at the source.
8. As a feature pipeline consumer, I want station factors written to `{station}/{year}.parquet` using a uniform long-table schema with vintage tracking, so that Task 06 can consume calibrated factors without schema transformations.
9. As an operations engineer, I want extraction to be fully idempotent with sha256 checksum caching, so that interrupted batch jobs resume instantly without recomputing completed station-years.
10. As an auditor, I want a comprehensive QC report generated verifying all 13 gates (V1–V13), so that downstream Phase 1.5 training has mathematically proven data integrity.

## Implementation Decisions

- **Architecture Seam**: The primary test and operational seam is the CLI module `src/pipeline/gefs_extract.py`. All scanning, reading, decoding, deduping, interpolating, and writing flows through this interface.
- **Deduplication Engine**: A two-pass scanner that inspects file header metadata / GRIB message headers to construct unique canonical entries mapped to physical file offsets, logging every duplicate resolution.
- **Extraction Format Alignment**: Direct output to Parquet with PyArrow backend, partitioned by `station/year.parquet`, containing columns: `[init_date, target_date, station, variable, member, lead_hours, value_K, vintage]`.
- **Downloader Multi-Day Loop**: Modify `GEFSBatchDownloader` to compute candidate target dates dynamically for each station timezone and query Herbie across all fxx segments in the union list.
- **Manifest Provenance**: Write `manifest.json` in the factor directory containing timestamp, git commit sha, source path, file checksums, and golden sample verification results.

## Testing Decisions

- **Single Primary Seam**: Tests invoke `gefs_extract` end-to-end against cached local probe GRIBs (`data/raw/gefs_probe/`) to test dry-run, deduplication, golden verification, and parquet generation.
- **Contract Testing**: Explicit unit tests for GRIB variable extraction, unit preservation, and golden sample equality (tolerance < 0.005 K).
- **Network Exemption**: Downloader scheduler unit tests mock Herbie/AWS calls. Real network downloads are gated behind `RUN_NETWORK_TESTS=1`.

## Out of Scope

- Deletion, relocation, or renaming of any raw GRIB files on `/Volumes/EricSSD/`.
- Training EMOS parameters or refactoring Phase 1 models (Task 05 / Phase 2 scope).
- Handling non-temperature weather variables (wind, pressure, precipitation).

## Further Notes

- Task 0 (ADR-0008) and Task A (fxx probe) are completed and documented.
- All subsequent execution must strictly proceed one ticket at a time.
