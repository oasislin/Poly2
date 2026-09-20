#!/usr/bin/env python3
"""
ModelRegistry: Standardized model persistence and unified inference query facade (Ticket 2.2-06 / Issue #19).

Implements (v5.9.1 §4.4):
    - Persistence naming: {StationID}_{Season}_{Max|Min}_lead{Hours}h.pkl
    - Storage payload: GaussianEMOS model object + rich diagnostic & degradation metadata
    - Unified inference facade:
        get_model(station_id, target_date, target_type, lead_hours)
        predict(station_id, target_date, target_type, lead_hours, ens_mean, ens_var, sigma_clim_sq)
    - Automatic season mapping, dense grid generation, and on-the-fly interpolation
"""

from datetime import date, datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import pickle
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
import pandas as pd

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.modeling.degradation import DegradationDecision, DegradationHandler
from src.modeling.emos_trainer import ModelTrainingDiagnostics
from src.modeling.gaussian_emos import GaussianEMOS
from src.modeling.interpolator import LeadTimeInterpolator
from src.modeling.matrix_trainer import MatrixScorecard
from src.modeling.partitioner import DatasetPartitioner, TRAIN_START_YEAR, TRAIN_END_YEAR

logger = logging.getLogger(__name__)

MANIFEST_VERSION = "2.0.0"
DEFAULT_DATASET_REF = "calib-dataset-v2.0"


class ManifestVerificationError(Exception):
    """Raised when model manifest verification fails due to missing files or SHA256 checksum mismatches."""
    pass


def _atomic_write_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Atomically write dictionary as formatted JSON with fsync guarantee."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file_path.with_suffix(file_path.suffix + f".tmp.{os.getpid()}")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, file_path)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


class ModelRegistry:
    """Model storage repository and runtime inference facade for calibrated Gaussian EMOS models."""

    def __init__(self, base_dir: Union[str, Path] = "data/models"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.interpolator = LeadTimeInterpolator()
        self.partitioner = DatasetPartitioner()
        self._cache: Dict[str, Tuple[GaussianEMOS, Dict[str, Any]]] = {}

    @staticmethod
    def format_model_filename(station_id: str, season: str, target_type: str, lead_hours: int) -> str:
        """Format filename per v5.9.1 convention: {StationID}_{Season}_{Max|Min}_lead{Hours}h.pkl."""
        st = station_id.upper()
        seas = season.capitalize()
        t_name = "Max" if target_type.lower() == "max" else "Min"
        lead = int(round(lead_hours))
        return f"{st}_{seas}_{t_name}_lead{lead}h.pkl"

    @staticmethod
    def format_model_relpath_json(station_id: str, season: str, target_type: str, lead_hours: int) -> Path:
        """Format relative path per Spec #59 convention: emos/{station}/{variable}_{season}_{lead}h.json."""
        st = station_id.upper()
        seas = season.capitalize()
        var = target_type.lower()
        lead = int(round(lead_hours))
        return Path("emos") / st / f"{var}_{seas}_{lead}h.json"

    def save_model_json(
        self,
        model: GaussianEMOS,
        station_id: str,
        season: str,
        target_type: str,
        lead_hours: int,
        diagnostics: Optional[ModelTrainingDiagnostics] = None,
        decision: Optional[DegradationDecision] = None,
        is_interpolated: bool = False,
    ) -> Path:
        """Persist a single GaussianEMOS model and rich diagnostics as standard JSON."""
        relpath = self.format_model_relpath_json(station_id, season, target_type, lead_hours)
        file_path = self.base_dir / relpath

        diag_dict = diagnostics.to_dict() if diagnostics is not None else None
        dec_dict = decision.to_dict() if decision is not None else None
        health_grade = diag_dict.get("health_grade", "HEALTHY") if diag_dict else "HEALTHY"

        payload: Dict[str, Any] = {
            "format_version": MANIFEST_VERSION,
            "station": station_id.upper(),
            "variable": target_type.lower(),
            "season": season.capitalize(),
            "lead_hours": int(round(lead_hours)),
            "parameters": {
                "a": float(model.a),
                "b": float(model.b),
                "c": float(model.c),
                "d": float(model.d),
            },
            "diagnostics": diag_dict,
            "health_grade": health_grade,
            "decision": dec_dict,
            "is_interpolated": is_interpolated,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        _atomic_write_json(file_path, payload)
        cache_key = f"json::{relpath.as_posix()}"
        self._cache[cache_key] = (model, payload)
        logger.debug("Persisted JSON EMOS model to %s", file_path)
        return file_path

    def load_model_json(
        self,
        station_id: str,
        season: str,
        target_type: str,
        lead_hours: int,
    ) -> Tuple[GaussianEMOS, Dict[str, Any]]:
        """Load a persisted GaussianEMOS model and metadata from JSON file."""
        relpath = self.format_model_relpath_json(station_id, season, target_type, lead_hours)
        cache_key = f"json::{relpath.as_posix()}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        file_path = self.base_dir / relpath
        if not file_path.exists():
            raise FileNotFoundError(f"Model JSON file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        params = payload["parameters"]
        model = GaussianEMOS(
            a=float(params["a"]),
            b=float(params["b"]),
            c=float(params["c"]),
            d=float(params["d"]),
        )
        self._cache[cache_key] = (model, payload)
        return model, payload

    def generate_manifest(
        self,
        saved_relpaths: Optional[Sequence[Union[str, Path]]] = None,
        train_start_year: int = TRAIN_START_YEAR,
        train_end_year: int = TRAIN_END_YEAR,
        dataset_ref: str = DEFAULT_DATASET_REF,
    ) -> Path:
        """Compute SHA256 checksums and build tamper-evident manifest.json."""
        manifest_path = self.base_dir / "manifest.json"

        if saved_relpaths is None:
            json_files = sorted((self.base_dir / "emos").glob("**/*.json"))
            saved_relpaths = [p.relative_to(self.base_dir) for p in json_files]

        models_meta: Dict[str, Any] = {}
        stations_found = set()

        for rel in saved_relpaths:
            rel_p = Path(rel)
            full_p = self.base_dir / rel_p
            if not full_p.exists():
                continue
            with open(full_p, "rb") as f:
                content = f.read()
            sha256 = hashlib.sha256(content).hexdigest()
            size_bytes = len(content)

            try:
                data = json.loads(content.decode("utf-8"))
                st = data.get("station", rel_p.parent.name)
                var = data.get("variable", "max")
                seas = data.get("season", "Winter")
                lead = data.get("lead_hours", 0)
            except Exception:
                st = rel_p.parent.name
                var = "max"
                seas = "Winter"
                lead = 0

            stations_found.add(st)
            models_meta[rel_p.as_posix()] = {
                "station": st,
                "variable": var,
                "season": seas,
                "lead_hours": lead,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }

        station_universe = [s for s in ACTIVE_10_STATIONS if s in stations_found]
        if not station_universe:
            station_universe = sorted(list(stations_found))

        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset_ref": dataset_ref,
            "train_start_year": train_start_year,
            "train_end_year": train_end_year,
            "station_universe": station_universe,
            "station_count": len(station_universe),
            "total_models": len(models_meta),
            "models": models_meta,
        }

        _atomic_write_json(manifest_path, manifest)
        logger.info("Generated manifest with %d models at %s", len(models_meta), manifest_path)
        return manifest_path

    def save_scorecard_json(
        self,
        scorecard: MatrixScorecard,
        train_start_year: int = TRAIN_START_YEAR,
        train_end_year: int = TRAIN_END_YEAR,
    ) -> Tuple[List[Path], Path]:
        """Persist full matrix scorecard to JSON hierarchy and generate tamper-evident manifest."""
        saved_paths: List[Path] = []
        relpaths: List[Path] = []

        for (station, season, target_type, lead), (model, diag, decision) in scorecard.models.items():
            path = self.save_model_json(
                model=model,
                station_id=station,
                season=season,
                target_type=target_type,
                lead_hours=lead,
                diagnostics=diag,
                decision=decision,
                is_interpolated=False,
            )
            saved_paths.append(path)
            relpaths.append(path.relative_to(self.base_dir))

        manifest_path = self.generate_manifest(
            saved_relpaths=relpaths,
            train_start_year=train_start_year,
            train_end_year=train_end_year,
        )
        return saved_paths, manifest_path

    def verify_and_load_manifest(
        self,
        manifest_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Fail-Closed verification of manifest.json and SHA256 checksums of all declared models."""
        m_path = Path(manifest_path) if manifest_path is not None else (self.base_dir / "manifest.json")
        if not m_path.exists():
            raise ManifestVerificationError(f"Manifest file not found: {m_path}")

        try:
            with open(m_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as exc:
            raise ManifestVerificationError(f"Failed to parse manifest JSON: {exc}") from exc

        required_keys = {"manifest_version", "station_universe", "total_models", "models"}
        missing_keys = required_keys - set(manifest.keys())
        if missing_keys:
            raise ManifestVerificationError(f"Manifest missing required keys: {missing_keys}")

        models = manifest.get("models", {})
        if not isinstance(models, dict):
            raise ManifestVerificationError("Manifest 'models' entry must be a dictionary")

        for rel_str, meta in models.items():
            file_path = self.base_dir / rel_str
            if not file_path.exists():
                msg = f"Missing model parameter file declared in manifest: {file_path}"
                logger.error(msg)
                raise ManifestVerificationError(msg)

            try:
                with open(file_path, "rb") as f:
                    content = f.read()
            except Exception as exc:
                msg = f"Failed to read model parameter file {file_path}: {exc}"
                logger.error(msg)
                raise ManifestVerificationError(msg) from exc

            actual_sha256 = hashlib.sha256(content).hexdigest()
            expected_sha256 = meta.get("sha256", "")

            if actual_sha256.lower() != expected_sha256.lower():
                msg = (
                    f"Tampered or corrupt model file detected! File: {file_path}. "
                    f"Expected SHA256: {expected_sha256}, actual: {actual_sha256}"
                )
                logger.error(msg)
                raise ManifestVerificationError(msg)

        logger.info("Manifest verification PASSED for %d models in %s", len(models), m_path)
        return manifest

    def save_model(
        self,
        model: GaussianEMOS,
        station_id: str,
        season: str,
        target_type: str,
        lead_hours: int,
        diagnostics: Optional[ModelTrainingDiagnostics] = None,
        decision: Optional[DegradationDecision] = None,
        is_interpolated: bool = False,
    ) -> Path:
        """Persist a single GaussianEMOS model and its metadata to disk."""
        filename = self.format_model_filename(station_id, season, target_type, lead_hours)
        file_path = self.base_dir / filename

        metadata: Dict[str, Any] = {
            "station_id": station_id.upper(),
            "season": season.capitalize(),
            "target_type": target_type.lower(),
            "lead_hours": int(round(lead_hours)),
            "is_interpolated": is_interpolated,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "diagnostics": diagnostics.to_dict() if diagnostics is not None else None,
            "decision": decision.to_dict() if decision is not None else None,
        }

        payload = {
            "model": model,
            "metadata": metadata,
        }

        with open(file_path, "wb") as f:
            pickle.dump(payload, f)

        # Update cache
        self._cache[filename] = (model, metadata)
        logger.debug("Persisted EMOS model to %s", file_path)
        return file_path

    def load_model(
        self,
        station_id: str,
        season: str,
        target_type: str,
        lead_hours: int,
    ) -> Tuple[GaussianEMOS, Dict[str, Any]]:
        """Load a persisted model and its metadata from disk/cache (JSON-first with PKL fallback)."""
        # 1. Try loading JSON format first
        try:
            return self.load_model_json(station_id, season, target_type, lead_hours)
        except FileNotFoundError:
            pass

        # 2. Fallback to legacy PKL format
        filename = self.format_model_filename(station_id, season, target_type, lead_hours)
        if filename in self._cache:
            return self._cache[filename]

        file_path = self.base_dir / filename
        if not file_path.exists():
            raise FileNotFoundError(f"Model file not found (tried JSON and PKL): {filename}")

        with open(file_path, "rb") as f:
            payload = pickle.load(f)

        model: GaussianEMOS = payload["model"]
        metadata: Dict[str, Any] = payload.get("metadata", {})
        self._cache[filename] = (model, metadata)
        return model, metadata

    def save_scorecard(
        self,
        scorecard: MatrixScorecard,
        build_dense_grid: bool = True,
    ) -> List[Path]:
        """Persist all 40 models from MatrixScorecard and optionally interpolate full 6h-dense grid."""
        saved_paths: List[Path] = []

        # 1. Save all trained anchor models
        anchor_dict: Dict[Tuple[str, str, str], Dict[int, GaussianEMOS]] = {}
        for (station, season, target_type, lead), (model, diag, decision) in scorecard.models.items():
            path = self.save_model(
                model=model,
                station_id=station,
                season=season,
                target_type=target_type,
                lead_hours=lead,
                diagnostics=diag,
                decision=decision,
                is_interpolated=False,
            )
            saved_paths.append(path)

            key = (station, season, target_type)
            if key not in anchor_dict:
                anchor_dict[key] = {}
            anchor_dict[key][lead] = model

        # 2. Build and save dense 6h-grid models across 6h to 54h
        if build_dense_grid:
            all_leads = [6, 12, 18, 24, 30, 36, 42, 48, 54]
            for (station, season, target_type), anchors in anchor_dict.items():
                dense_grid = self.interpolator.build_full_grid(
                    target_type=target_type,
                    anchor_models=anchors,
                    grid_leads=all_leads,
                )
                for lead, interp_model in dense_grid.items():
                    if lead not in anchors:  # Intermediate interpolated model
                        path = self.save_model(
                            model=interp_model,
                            station_id=station,
                            season=season,
                            target_type=target_type,
                            lead_hours=lead,
                            is_interpolated=True,
                        )
                        saved_paths.append(path)

        return saved_paths

    def get_model(
        self,
        station_id: str,
        target_date: Union[date, str, pd.Timestamp],
        target_type: str,
        lead_hours: Union[int, float],
    ) -> GaussianEMOS:
        """Facade query: fetch or interpolate appropriate GaussianEMOS model for station, date, target, and lead time."""
        season = self.partitioner.get_season(target_date)
        int_lead = int(round(lead_hours))

        # Check if model exists directly on disk/cache
        try:
            model, _ = self.load_model(station_id, season, target_type, int_lead)
            return model
        except FileNotFoundError:
            # Fallback: dynamically load available anchor models and interpolate on the fly
            anchors = self._load_available_anchors(station_id, season, target_type)
            if not anchors:
                raise FileNotFoundError(
                    f"No models or anchors found for {station_id} {season} {target_type}"
                )
            return self.interpolator.get_model_at_lead(target_type, lead_hours, anchors)

    def predict(
        self,
        station_id: str,
        target_date: Union[date, str, pd.Timestamp],
        target_type: str,
        lead_hours: Union[int, float],
        ensemble_mean: Union[float, np.ndarray, pd.Series],
        ensemble_variance: Union[float, np.ndarray, pd.Series],
        sigma_clim_squared: Union[float, np.ndarray, pd.Series],
    ) -> GaussianEMOS:
        """Facade inference: predict calibrated Gaussian distribution with short-lead decay handling."""
        season = self.partitioner.get_season(target_date)
        anchors = self._load_available_anchors(station_id, season, target_type)

        if not anchors:
            # If no anchors loaded, try loading direct model
            model = self.get_model(station_id, target_date, target_type, lead_hours)
            mu, sigma = model.compute_params(ensemble_mean, ensemble_variance, sigma_clim_squared)
            return GaussianEMOS.from_params(mu=mu, sigma=sigma)

        return self.interpolator.predict_distribution(
            target_type=target_type,
            lead_hours=lead_hours,
            ensemble_mean=ensemble_mean,
            ensemble_variance=ensemble_variance,
            sigma_clim_squared=sigma_clim_squared,
            anchor_models=anchors,
        )

    def _load_available_anchors(
        self,
        station_id: str,
        season: str,
        target_type: str,
    ) -> Dict[int, GaussianEMOS]:
        """Load all anchor models available on disk for a station-season-target tuple."""
        try:
            anchor_leads = self.partitioner.get_station_lead_nodes(station_id, season=season, target_type=target_type)
        except Exception:
            anchor_leads = self.partitioner.get_lead_time_nodes(target_type)

        anchors: Dict[int, GaussianEMOS] = {}
        for lead in anchor_leads:
            try:
                model, _ = self.load_model(station_id, season, target_type, lead)
                anchors[lead] = model
            except FileNotFoundError:
                continue
        return anchors

    def list_inventory(self) -> pd.DataFrame:
        """List all models currently persisted in the registry directory (both JSON and PKL)."""
        records = []
        # 1. Scan PKL files
        for file_path in sorted(self.base_dir.glob("*.pkl")):
            try:
                with open(file_path, "rb") as f:
                    payload = pickle.load(f)
                meta = payload.get("metadata", {})
                records.append({
                    "filename": file_path.name,
                    "relpath": file_path.relative_to(self.base_dir).as_posix(),
                    "format": "pkl",
                    "station_id": meta.get("station_id"),
                    "season": meta.get("season"),
                    "target_type": meta.get("target_type"),
                    "lead_hours": meta.get("lead_hours"),
                    "is_interpolated": meta.get("is_interpolated", False),
                    "saved_at": meta.get("saved_at"),
                })
            except Exception as e:
                logger.warning("Error reading model payload from %s: %s", file_path, e)

        # 2. Scan JSON files in emos/
        emos_dir = self.base_dir / "emos"
        if emos_dir.exists():
            for json_path in sorted(emos_dir.glob("**/*.json")):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    records.append({
                        "filename": json_path.name,
                        "relpath": json_path.relative_to(self.base_dir).as_posix(),
                        "format": "json",
                        "station_id": meta.get("station"),
                        "season": meta.get("season"),
                        "target_type": meta.get("variable"),
                        "lead_hours": meta.get("lead_hours"),
                        "is_interpolated": meta.get("is_interpolated", False),
                        "saved_at": meta.get("saved_at"),
                    })
                except Exception as e:
                    logger.warning("Error reading JSON model from %s: %s", json_path, e)

        return pd.DataFrame(records)

