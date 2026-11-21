"""M2 (S3-02) Forecast Distribution Engine: Affine Prior Families, Hurdle Bridge, and P5 v1.1.

Design & protocol anchors:
- `P8-T8-ALGO4-DESIGN v0.3 §2` (PriorAffineFamilyModel, HurdleCdfBridge, IntegerGridDiscretizer)
- `P8-T4-M4M5-INTERFACE v1.0 §3.3` (`P5 ForecastDistributionSnapshot v1.1`, 4 hard invariants,
  M1->M2 observation age gate, latest issue/as_of win without rollback)
- `P8-T2-M7-LOGGING v1.0 §1.4 & §2.3` (`P17 ForecastSnapshotLog` schema & canonical record_sha256)
- `P8-ALGO-DEF-SPEC v2.0 §阶段3 L206` (`sigma_rem = max(sigma_0 * sqrt(eta_s(t)), 0.9°F)`)

Strict boundaries:
- Never modifies any file in the F-2 locked `src/pricing/` zone.
- `TMIN` conditional bridge drift remains uncalibrated (`NotImplementedError` via `MuRHook`)
  until W3 calibration; never fabricates uncalibrated formulas.
- No single-field dual semantics: `p_stay_phys` (universal unclipped physical atom) and
  `p_bin_stay` (containment bin retention probability, 1.0 in open tail) are strictly separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)
import uuid

from scipy.special import ndtr

from src.data_acquisition.settlement_metar_stream import (
    FreshnessPolicy,
    StationDayState,
    compute_record_sha256,
    resolve_station_timezone,
    settle_round_pos_inf,
)
from src.modeling.resampling import evaluate_evt_tail_cdf
from src.prediction.dynamic_corrector import MuRHook, MuRResult, SpecV2BaselineMuRHook

TargetType = Literal["TMAX", "TMIN"]
ExecutionMode = Literal["PAPER", "LIVE"]
PriorFamily = Literal["gaussian", "johnsonsu", "evt_hybrid"]

# Statutory physical instrument accuracy floor anchored in P8-ALGO-DEF-SPEC v2.0 §阶段3 L206
ASOS_PRT_INSTRUMENT_FLOOR_F: float = 0.9

_FORECAST_ID_NAMESPACE = uuid.UUID("b7c12a8e-3f41-4a22-910c-202611210002")
_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


class UnsupportedPriorFamilyError(ValueError):
    """Raised when prior distribution family is not in {gaussian, johnsonsu, evt_hybrid}."""


class BinLadderValidationError(ValueError):
    """Raised when integer bin ladder violates contiguous complete partition preconditions."""


class CausalInputError(ValueError):
    """Raised when M2 receives naive timestamps or future P11 observation states."""


def _ensure_utc(dt: datetime, *, field_name: str) -> datetime:
    if not isinstance(dt, datetime):
        raise CausalInputError(f"{field_name} must be a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CausalInputError(f"{field_name} must be timezone-aware UTC, got naive {dt!r}")
    return dt.astimezone(timezone.utc)


def _season_for_date(target_date: date) -> str:
    month = target_date.month
    if month in (12, 1, 2):
        return "Winter"
    if month in (3, 4, 5):
        return "Spring"
    if month in (6, 7, 8):
        return "Summer"
    return "Autumn"


@dataclass(frozen=True)
class PriorAffineFamilyModel:
    """Affine prior distribution `Y = mu0 + sigma0 * Z` over {gaussian, johnsonsu, evt_hybrid}."""

    family: PriorFamily
    mu0: float
    sigma0: float
    shape_params: Mapping[str, Any] = ()  # type: ignore[assignment]

    def __post_init__(self) -> None:
        fam = str(self.family).strip().lower()
        if fam not in ("gaussian", "johnsonsu", "evt_hybrid"):
            raise UnsupportedPriorFamilyError(
                f"Unsupported prior family {self.family!r}; expected 'gaussian', 'johnsonsu', or 'evt_hybrid'"
            )
        object.__setattr__(self, "family", fam)

        if isinstance(self.mu0, bool) or not math.isfinite(float(self.mu0)):
            raise ValueError(f"mu0 must be finite float, got {self.mu0!r}")
        if (
            isinstance(self.sigma0, bool)
            or not math.isfinite(float(self.sigma0))
            or float(self.sigma0) <= 0.0
        ):
            raise ValueError(f"sigma0 must be finite and > 0, got {self.sigma0!r}")
        object.__setattr__(self, "mu0", float(self.mu0))
        object.__setattr__(self, "sigma0", float(self.sigma0))

        params = dict(self.shape_params) if self.shape_params else {}
        if fam == "johnsonsu":
            for key in ("gamma", "delta", "xi", "lambda"):
                if key not in params or isinstance(params[key], bool):
                    raise ValueError(f"johnsonsu missing valid parameter {key!r}")
                val = float(params[key])
                if not math.isfinite(val):
                    raise ValueError(f"johnsonsu parameter {key!r} must be finite, got {val!r}")
                params[key] = val
            if params["delta"] <= 0.0 or params["lambda"] <= 0.0:
                raise ValueError("johnsonsu parameters delta and lambda must be > 0")
        elif fam == "evt_hybrid":
            for key in ("u_left", "u_right"):
                if key not in params or isinstance(params[key], bool):
                    raise ValueError(f"evt_hybrid missing boundary {key!r}")
                params[key] = float(params[key])
                if not math.isfinite(params[key]):
                    raise ValueError(f"evt_hybrid {key!r} must be finite")
            if params["u_left"] >= params["u_right"]:
                raise ValueError("evt_hybrid requires u_left < u_right")
            for tail_key in ("gpd_left", "gpd_right"):
                tail = params.get(tail_key)
                if not isinstance(tail, Mapping):
                    raise ValueError(f"evt_hybrid missing mapping {tail_key!r}")
                xi = float(tail["shape_xi"])
                beta = float(tail["scale_beta"])
                if not math.isfinite(xi) or not math.isfinite(beta) or beta <= 0.0:
                    raise ValueError(f"evt_hybrid {tail_key} invalid (shape_xi={xi}, scale_beta={beta})")
                if abs(xi) < 1e-12:
                    raise ValueError("evt_hybrid shape_xi too close to 0 for GPD power formula")
                params[tail_key] = {"shape_xi": xi, "scale_beta": beta}
        object.__setattr__(self, "shape_params", params)

    def cdf(self, x: float) -> float:
        """Evaluate continuous prior CDF F_Y(x) strictly in [0.0, 1.0]."""
        if math.isinf(x):
            return 1.0 if x > 0.0 else 0.0
        if math.isnan(x):
            raise ValueError("PriorAffineFamilyModel.cdf received NaN")
        z = (float(x) - self.mu0) / self.sigma0
        if self.family == "gaussian":
            val = float(ndtr(z))
        elif self.family == "johnsonsu":
            g = float(self.shape_params["gamma"])
            d = float(self.shape_params["delta"])
            xi = float(self.shape_params["xi"])
            lam = float(self.shape_params["lambda"])
            zn = g + d * math.asinh((z - xi) / lam)
            val = float(ndtr(zn))
        else:
            val = float(evaluate_evt_tail_cdf(z, dict(self.shape_params)))
        return min(1.0, max(0.0, val))


class EtaProvider(Protocol):
    """Port supplying remaining variance fraction eta_s(t) in (0, 1] with provenance."""

    provenance: str

    def get_eta_s(
        self,
        *,
        station_id: str,
        season: str,
        t_local_hour: float,
    ) -> float:
        ...


@dataclass(frozen=True)
class ConstantEtaProvider:
    """Explicitly configured eta_s provider for controlled testing or uniform fallbacks."""

    eta_s: float
    provenance: str

    def __post_init__(self) -> None:
        if not self.provenance or not self.provenance.strip():
            raise ValueError("ConstantEtaProvider.provenance must be non-empty")
        if (
            isinstance(self.eta_s, bool)
            or not math.isfinite(float(self.eta_s))
            or not (0.0 < float(self.eta_s) <= 1.0)
        ):
            raise ValueError(f"eta_s must lie in (0, 1], got {self.eta_s!r}")

    def get_eta_s(
        self,
        *,
        station_id: str,
        season: str,
        t_local_hour: float,
    ) -> float:
        return float(self.eta_s)


class CalibrationJsonEtaProvider:
    """Loads calibrated station x season eta_s(t) splines from Inspection A evidence JSON."""

    def __init__(
        self,
        *,
        curves: Mapping[str, Mapping[str, Tuple[Tuple[float, ...], Tuple[float, ...]]]],
        provenance: str,
    ) -> None:
        if not provenance or not provenance.strip():
            raise ValueError("CalibrationJsonEtaProvider.provenance must be non-empty")
        self._curves = curves
        self.provenance = provenance

    @classmethod
    def from_json(
        cls,
        path: Path,
        *,
        provenance: Optional[str] = None,
    ) -> "CalibrationJsonEtaProvider":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_curves = payload.get("curves", {})
        parsed: Dict[str, Dict[str, Tuple[Tuple[float, ...], Tuple[float, ...]]]] = {}
        for station, season_map in raw_curves.items():
            st_code = str(station).strip().upper()
            parsed[st_code] = {}
            for season, entry in season_map.items():
                t_hours = tuple(float(v) for v in entry["t_hours"])
                raw_etas = entry["eta_calibrated"] if "eta_calibrated" in entry else entry["eta_s"]
                etas = tuple(min(1.0, max(1e-8, float(v))) for v in raw_etas)
                if len(t_hours) != len(etas) or len(t_hours) == 0:
                    raise ValueError(f"Invalid eta_s curve for {st_code}/{season}")
                parsed[st_code][str(season)] = (t_hours, etas)
        prov = provenance or str(payload.get("schema_version") or Path(path).name)
        return cls(curves=parsed, provenance=prov)

    def get_eta_s(
        self,
        *,
        station_id: str,
        season: str,
        t_local_hour: float,
    ) -> float:
        st_code = station_id.strip().upper()
        st_map = self._curves.get(st_code)
        if not st_map or season not in st_map:
            raise KeyError(
                f"No calibrated eta_s curve found for station={st_code!r}, season={season!r}"
            )
        xs, ys = st_map[season]
        t = float(t_local_hour)
        if t <= xs[0]:
            return ys[0]
        if t >= xs[-1]:
            return ys[-1]
        for idx in range(len(xs) - 1):
            x0, x1 = xs[idx], xs[idx + 1]
            if x0 <= t <= x1:
                if x1 == x0:
                    return ys[idx]
                w = (t - x0) / (x1 - x0)
                return min(1.0, max(1e-8, ys[idx] + w * (ys[idx + 1] - ys[idx])))
        return ys[-1]


def compute_sigma_rem(sigma0: float, eta_s: float) -> float:
    """Compute remaining conditional standard deviation anchored at 0.9°F sensor floor."""
    if isinstance(sigma0, bool) or not math.isfinite(sigma0) or sigma0 <= 0.0:
        raise ValueError(f"sigma0 must be positive finite, got {sigma0!r}")
    if isinstance(eta_s, bool) or not math.isfinite(eta_s) or not (0.0 < eta_s <= 1.0):
        raise ValueError(f"eta_s must lie in (0, 1], got {eta_s!r}")
    return max(float(sigma0) * math.sqrt(float(eta_s)), ASOS_PRT_INSTRUMENT_FLOOR_F)


@dataclass(frozen=True)
class IntegerBinSpec:
    """Closed integer settlement bin boundary ('.5°F' boundaries strictly eliminated)."""

    bin_id: str
    label: str
    lower_int_f: Optional[int]
    upper_int_f: Optional[int]

    def __post_init__(self) -> None:
        if not self.bin_id or not self.bin_id.strip():
            raise BinLadderValidationError("bin_id must be non-empty")
        for attr in ("lower_int_f", "upper_int_f"):
            val = getattr(self, attr)
            if val is not None and (isinstance(val, bool) or not isinstance(val, int)):
                raise BinLadderValidationError(
                    f"{attr} must be Optional[int] (no floats/half-degrees), got {val!r}"
                )
        if self.lower_int_f is None and self.upper_int_f is None:
            raise BinLadderValidationError("Bin cannot be open on both lower and upper ends")
        if (
            self.lower_int_f is not None
            and self.upper_int_f is not None
            and self.lower_int_f > self.upper_int_f
        ):
            raise BinLadderValidationError(
                f"Inverted integer bin bounds: {self.lower_int_f} > {self.upper_int_f}"
            )

    @property
    def continuous_lower(self) -> float:
        return -math.inf if self.lower_int_f is None else float(self.lower_int_f) - 0.5

    @property
    def continuous_upper(self) -> float:
        return math.inf if self.upper_int_f is None else float(self.upper_int_f) + 0.5

    def contains_int(self, k: int) -> bool:
        low_ok = self.lower_int_f is None or k >= self.lower_int_f
        high_ok = self.upper_int_f is None or k <= self.upper_int_f
        return low_ok and high_ok


def build_integer_bin_ladder(
    *,
    first_interior_start_f: int,
    num_interior_bins: int,
    bin_width_f: int = 2,
) -> Tuple[IntegerBinSpec, ...]:
    """Build standard Polymarket integer contract ladder (`<= k0`, contiguous interior, `>= k1`)."""
    if isinstance(bin_width_f, bool) or not isinstance(bin_width_f, int) or bin_width_f < 1:
        raise ValueError(f"bin_width_f must be integer >= 1, got {bin_width_f!r}")
    if (
        isinstance(num_interior_bins, bool)
        or not isinstance(num_interior_bins, int)
        or num_interior_bins < 1
    ):
        raise ValueError(f"num_interior_bins must be >= 1, got {num_interior_bins!r}")

    bins: List[IntegerBinSpec] = []
    lower_tail_max = first_interior_start_f - 1
    bins.append(
        IntegerBinSpec(
            bin_id=f"le_{lower_tail_max}F",
            label=f"<={lower_tail_max}°F",
            lower_int_f=None,
            upper_int_f=lower_tail_max,
        )
    )
    cursor = first_interior_start_f
    for _ in range(num_interior_bins):
        upper = cursor + bin_width_f - 1
        bid = f"{cursor}F" if cursor == upper else f"{cursor}-{upper}F"
        lbl = f"{cursor}°F" if cursor == upper else f"{cursor}-{upper}°F"
        bins.append(
            IntegerBinSpec(
                bin_id=bid,
                label=lbl,
                lower_int_f=cursor,
                upper_int_f=upper,
            )
        )
        cursor = upper + 1

    bins.append(
        IntegerBinSpec(
            bin_id=f"ge_{cursor}F",
            label=f">={cursor}°F",
            lower_int_f=cursor,
            upper_int_f=None,
        )
    )
    validate_contiguous_bin_ladder(bins)
    return tuple(bins)


def validate_contiguous_bin_ladder(bins: Sequence[IntegerBinSpec]) -> None:
    """Fail-closed guard guaranteeing integer bins partition Z cleanly for telescoping sums (§2.3)."""
    if len(bins) < 2:
        raise BinLadderValidationError(f"Bin ladder requires >= 2 bins, got {len(bins)}")
    if bins[0].lower_int_f is not None or bins[0].upper_int_f is None:
        raise BinLadderValidationError(
            "First bin must be lower-open (lower_int_f=None) and upper-bounded"
        )
    if bins[-1].upper_int_f is not None or bins[-1].lower_int_f is None:
        raise BinLadderValidationError(
            "Last bin must be upper-open (upper_int_f=None) and lower-bounded"
        )
    for idx in range(1, len(bins) - 1):
        b = bins[idx]
        if b.lower_int_f is None or b.upper_int_f is None:
            raise BinLadderValidationError(f"Interior bin {idx} ({b.bin_id}) must have finite bounds")
        if b.lower_int_f > b.upper_int_f:
            raise BinLadderValidationError(f"Interior bin {idx} inverted: {b}")

    seen_ids = set()
    for b in bins:
        if b.bin_id in seen_ids:
            raise BinLadderValidationError(f"Duplicate bin_id {b.bin_id!r}")
        seen_ids.add(b.bin_id)

    for idx in range(len(bins) - 1):
        cur_u = bins[idx].upper_int_f
        nxt_l = bins[idx + 1].lower_int_f
        if cur_u is None or nxt_l is None or cur_u + 1 != nxt_l:
            raise BinLadderValidationError(
                f"Discontiguous or overlapping bin ladder between {bins[idx].bin_id!r} "
                f"(upper={cur_u}) and {bins[idx + 1].bin_id!r} (lower={nxt_l})"
            )


@dataclass(frozen=True)
class BinProbV11:
    """Single integer-bounded probability bin in `P5 ForecastDistributionSnapshot v1.1`."""

    bin_id: str
    label: str
    lower_int_f: Optional[int]
    upper_int_f: Optional[int]
    p_model: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bin_id": self.bin_id,
            "label": self.label,
            "lower_int_f": self.lower_int_f,
            "upper_int_f": self.upper_int_f,
            "p_model": self.p_model,
        }


@dataclass(frozen=True)
class ForecastDistributionSnapshotV11:
    """`P5 ForecastDistributionSnapshot v1.1` (`M2 -> M4 / M7`) matching interface §3.3."""

    schema_version: str
    forecast_id: str
    issue_ts_utc: datetime
    station_id: str
    target_date: date
    target_type: TargetType
    gefs_lead_hours: int
    tau_hours: float
    settle_close_utc: datetime
    model_hash: str
    prior_mu0: float
    prior_sigma0: float
    family: PriorFamily
    m_now_f: Optional[float]
    m_now_int_f: Optional[int]
    oracle_compliant: bool
    upstream_obs_fresh: bool
    is_bridge_active: bool
    p_stay_phys: Optional[float]
    p_bin_stay: Optional[float]
    bin_probs: Tuple[BinProbV11, ...]
    sigma_delta_sample: float
    mu_r_used: Optional[float] = None
    sigma_rem_used: Optional[float] = None
    eta_s_provenance: Optional[str] = None
    mu_r_scheme: Optional[str] = None

    def to_p17_dict_without_hash(
        self,
        *,
        session_id: str,
        execution_mode: ExecutionMode,
        config_hash: str,
    ) -> Dict[str, Any]:
        return {
            "schema_version": "p17.v1",
            "p5_schema_version": self.schema_version,
            "session_id": session_id,
            "execution_mode": execution_mode,
            "config_hash": config_hash,
            "forecast_id": self.forecast_id,
            "issue_ts_utc": self.issue_ts_utc.isoformat(),
            "station_id": self.station_id,
            "target_date": self.target_date.isoformat(),
            "target_type": self.target_type,
            "gefs_lead_hours": self.gefs_lead_hours,
            "tau_hours": self.tau_hours,
            "settle_close_utc": self.settle_close_utc.isoformat(),
            "model_hash": self.model_hash,
            "prior_mu0": self.prior_mu0,
            "prior_sigma0": self.prior_sigma0,
            "family": self.family,
            "m_now_f": self.m_now_f,
            "m_now_int_f": self.m_now_int_f,
            "oracle_compliant": self.oracle_compliant,
            "upstream_obs_fresh": self.upstream_obs_fresh,
            "is_bridge_active": self.is_bridge_active,
            "p_stay_phys": self.p_stay_phys,
            "p_bin_stay": self.p_bin_stay,
            "bin_probs": [bp.to_dict() for bp in self.bin_probs],
            "sigma_delta_sample": self.sigma_delta_sample,
        }

    def to_p17_json_line(
        self,
        *,
        session_id: str,
        execution_mode: ExecutionMode,
        config_hash: str,
    ) -> str:
        payload = self.to_p17_dict_without_hash(
            session_id=session_id,
            execution_mode=execution_mode,
            config_hash=config_hash,
        )
        payload["record_sha256"] = compute_record_sha256(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_p17_json_line(line: str) -> bool:
    """Verify canonical `record_sha256` integrity of a serialized P17 JSONL record."""
    data = json.loads(line)
    expected = data.pop("record_sha256", None)
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    return compute_record_sha256(data) == expected


@dataclass(frozen=True)
class P5InvariantReport:
    """Structured mechanical self-certification report for `P5 v1.1` four hard invariants."""

    inv1_simplex_ok: bool
    inv2_dual_atom_domain_ok: bool
    inv3_dead_bin_zeroed_ok: bool
    inv4_dual_inclusion_ok: bool
    q_b2_state_ok: bool
    ladder_contiguous_ok: bool
    all_passed: bool
    prob_sum: float
    boundary_bin_id: Optional[str]
    boundary_p_model: Optional[float]
    p_stay_phys: Optional[float]
    p_bin_stay: Optional[float]
    boundary_is_open_tail: bool
    failures: Tuple[str, ...]


def validate_p5_v11_invariants(
    snapshot: ForecastDistributionSnapshotV11,
    *,
    sum_tol: float = 1e-5,
) -> P5InvariantReport:
    """Mechanically check all four `P5 v1.1` invariants + `Q-B2` 3-state validity."""
    failures: List[str] = []

    # 0. Ladder contiguity check
    ladder_contiguous_ok = True
    try:
        validate_contiguous_bin_ladder(
            [
                IntegerBinSpec(b.bin_id, b.label, b.lower_int_f, b.upper_int_f)
                for b in snapshot.bin_probs
            ]
        )
    except BinLadderValidationError as exc:
        ladder_contiguous_ok = False
        failures.append(f"LADDER_CONTIGUITY: {exc}")

    # Invariant 1: Simplex completeness
    probs = [b.p_model for b in snapshot.bin_probs]
    prob_sum = float(sum(probs))
    bounds_ok = all(math.isfinite(p) and 0.0 <= p <= 1.0 for p in probs)
    sum_ok = math.isfinite(prob_sum) and abs(prob_sum - 1.0) <= sum_tol
    inv1_simplex_ok = bool(bounds_ok and sum_ok)
    if not inv1_simplex_ok:
        failures.append(f"INV1_SIMPLEX: sum={prob_sum}, bounds_ok={bounds_ok}")

    # Invariant 2: Dual-atom orthogonal domain (p_stay_phys & p_bin_stay)
    if snapshot.is_bridge_active:
        inv2_dual_atom_domain_ok = bool(
            snapshot.p_stay_phys is not None
            and snapshot.p_bin_stay is not None
            and math.isfinite(snapshot.p_stay_phys)
            and math.isfinite(snapshot.p_bin_stay)
            and 0.0 <= snapshot.p_stay_phys <= 1.0
            and 0.0 <= snapshot.p_bin_stay <= 1.0
        )
    else:
        inv2_dual_atom_domain_ok = bool(
            snapshot.p_stay_phys is None and snapshot.p_bin_stay is None
        )
    if not inv2_dual_atom_domain_ok:
        failures.append(
            f"INV2_DUAL_ATOM: bridge={snapshot.is_bridge_active}, "
            f"p_stay_phys={snapshot.p_stay_phys}, p_bin_stay={snapshot.p_bin_stay}"
        )

    # Q-B2 3-state matrix
    if snapshot.is_bridge_active:
        q_b2_state_ok = bool(
            snapshot.m_now_f is not None
            and snapshot.m_now_int_f is not None
            and snapshot.oracle_compliant
            and snapshot.upstream_obs_fresh
        )
    else:
        q_b2_state_ok = True
    if not q_b2_state_ok:
        failures.append("Q_B2_INVALID_ACTIVE_BRIDGE_STATE")

    # Invariant 3 & 4 (active bridge only)
    boundary_bin_id: Optional[str] = None
    boundary_p_model: Optional[float] = None
    boundary_is_open_tail = False

    if not snapshot.is_bridge_active:
        inv3_dead_bin_zeroed_ok = True
        inv4_dual_inclusion_ok = True
    else:
        m_int = snapshot.m_now_int_f
        assert m_int is not None
        if snapshot.target_type == "TMAX":
            dead_ok = all(
                b.p_model == 0.0
                for b in snapshot.bin_probs
                if b.upper_int_f is not None and b.upper_int_f < m_int
            )
        else:
            dead_ok = all(
                b.p_model == 0.0
                for b in snapshot.bin_probs
                if b.lower_int_f is not None and b.lower_int_f > m_int
            )
        inv3_dead_bin_zeroed_ok = bool(dead_ok)
        if not inv3_dead_bin_zeroed_ok:
            failures.append(f"INV3_DEAD_BIN_NONZERO: m_now_int_f={m_int}")

        matching = [
            b
            for b in snapshot.bin_probs
            if (b.lower_int_f is None or m_int >= b.lower_int_f)
            and (b.upper_int_f is None or m_int <= b.upper_int_f)
        ]
        if len(matching) != 1:
            inv4_dual_inclusion_ok = False
            failures.append(f"INV4_BOUNDARY_BIN_COUNT={len(matching)}")
        else:
            jb = matching[0]
            boundary_bin_id = jb.bin_id
            boundary_p_model = jb.p_model
            boundary_is_open_tail = (
                (snapshot.target_type == "TMAX" and jb.upper_int_f is None)
                or (snapshot.target_type == "TMIN" and jb.lower_int_f is None)
            )
            eq_ok = (
                snapshot.p_bin_stay is not None
                and snapshot.p_stay_phys is not None
                and jb.p_model == snapshot.p_bin_stay
                and snapshot.p_bin_stay >= snapshot.p_stay_phys
            )
            tail_ok = True
            if boundary_is_open_tail:
                tail_ok = bool(snapshot.p_bin_stay == 1.0 and jb.p_model == 1.0)
            inv4_dual_inclusion_ok = bool(eq_ok and tail_ok)
            if not inv4_dual_inclusion_ok:
                failures.append(
                    f"INV4_INCLUSION: jb.p_model={jb.p_model}, p_bin_stay={snapshot.p_bin_stay}, "
                    f"p_stay_phys={snapshot.p_stay_phys}, open_tail={boundary_is_open_tail}"
                )

    all_passed = bool(
        ladder_contiguous_ok
        and inv1_simplex_ok
        and inv2_dual_atom_domain_ok
        and inv3_dead_bin_zeroed_ok
        and inv4_dual_inclusion_ok
        and q_b2_state_ok
    )
    return P5InvariantReport(
        inv1_simplex_ok=inv1_simplex_ok,
        inv2_dual_atom_domain_ok=inv2_dual_atom_domain_ok,
        inv3_dead_bin_zeroed_ok=inv3_dead_bin_zeroed_ok,
        inv4_dual_inclusion_ok=inv4_dual_inclusion_ok,
        q_b2_state_ok=q_b2_state_ok,
        ladder_contiguous_ok=ladder_contiguous_ok,
        all_passed=all_passed,
        prob_sum=prob_sum,
        boundary_bin_id=boundary_bin_id,
        boundary_p_model=boundary_p_model,
        p_stay_phys=snapshot.p_stay_phys,
        p_bin_stay=snapshot.p_bin_stay,
        boundary_is_open_tail=boundary_is_open_tail,
        failures=tuple(failures),
    )


def select_latest_p11_state(
    states: Sequence[StationDayState],
    *,
    station_id: str,
    target_date: date,
    as_of_ts_utc: datetime,
) -> Optional[StationDayState]:
    """Select the single winning P11 state with latest `as_of_ts_utc <= query_as_of` (no rollback).

    Mirrors M4's latest-timestamp win & no-rollback discipline: if the latest visible P11 state
    is uncompliant or stale, callers MUST degrade to prior rather than rolling back to an earlier P11.
    """
    cutoff = _ensure_utc(as_of_ts_utc, field_name="as_of_ts_utc")
    code = station_id.strip().upper()
    candidates = [
        s
        for s in states
        if s.station_id == code
        and s.target_date == target_date
        and _ensure_utc(s.as_of_ts_utc, field_name="state.as_of_ts_utc") <= cutoff
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda s: (
            _ensure_utc(s.as_of_ts_utc, field_name="state.as_of_ts_utc"),
            _ensure_utc(s.latest_obs_utc, field_name="state.latest_obs_utc")
            if s.latest_obs_utc is not None
            else _EPOCH_UTC,
        ),
    )


def evaluate_m1_to_m2_obs_freshness(
    p11_state: Optional[StationDayState],
    *,
    issue_ts_utc: datetime,
    freshness_policy: FreshnessPolicy,
) -> bool:
    """Enforce M2's M1->M2 observation age segment (`v0.3 §2.1 #2`, `interface §3.3`)."""
    issue_ts = _ensure_utc(issue_ts_utc, field_name="issue_ts_utc")
    if p11_state is None:
        return False
    state_asof = _ensure_utc(p11_state.as_of_ts_utc, field_name="p11_state.as_of_ts_utc")
    if state_asof > issue_ts:
        raise CausalInputError(
            f"P11 state as_of_ts_utc={state_asof.isoformat()} exceeds M2 issue_ts_utc={issue_ts.isoformat()}"
        )
    if not p11_state.oracle_compliant or not p11_state.freshness_ok:
        return False
    if p11_state.m_now_exact_f is None or p11_state.m_now_int_f is None:
        return False
    if settle_round_pos_inf(p11_state.m_now_exact_f) != p11_state.m_now_int_f:
        raise ValueError(
            f"Malformed P11 state: m_now_exact_f={p11_state.m_now_exact_f} != m_now_int_f={p11_state.m_now_int_f}"
        )
    if p11_state.latest_obs_utc is None:
        return False

    latest_obs = _ensure_utc(p11_state.latest_obs_utc, field_name="p11_state.latest_obs_utc")
    phys_age_at_issue = (issue_ts - latest_obs).total_seconds()
    if not (0.0 <= phys_age_at_issue <= freshness_policy.physical_age_limit_sec):
        return False

    if p11_state.dispatch_age_available and p11_state.latest_dispatch_ts_utc is not None:
        latest_disp = _ensure_utc(
            p11_state.latest_dispatch_ts_utc, field_name="p11_state.latest_dispatch_ts_utc"
        )
        disp_age_at_issue = (issue_ts - latest_disp).total_seconds()
        if disp_age_at_issue < 0.0:
            return False
        if (
            freshness_policy.dispatch_age_limit_sec is not None
            and disp_age_at_issue > freshness_policy.dispatch_age_limit_sec
        ):
            return False
    elif freshness_policy.require_dispatch_age:
        return False

    return True


@dataclass(frozen=True)
class HurdleBridgeOutput:
    """Kernel evaluation holding left-limit CDF and decoupled physical atom `p_stay_phys`."""

    is_bridge_active: bool
    left_limit_cdf: Callable[[float], float]
    p_stay_phys: Optional[float]
    mu_r_result: Optional[MuRResult]
    sigma_rem: Optional[float]


class HurdleCdfBridge:
    """Constructs prior or hurdle-conditioned left-limit CDF consistent with `MuRHook`."""

    def __init__(self, mu_r_hook: Optional[MuRHook] = None) -> None:
        self._mu_r_hook: MuRHook = mu_r_hook if mu_r_hook is not None else SpecV2BaselineMuRHook()

    def build(
        self,
        *,
        prior: PriorAffineFamilyModel,
        target_type: TargetType,
        station_id: str,
        target_date: date,
        issue_ts_utc: datetime,
        m_now_f: Optional[float],
        instant_x_t_f: Optional[float],
        bridge_allowed: bool,
        eta_provider: EtaProvider,
        station_timezones: Optional[Mapping[str, str]] = None,
    ) -> HurdleBridgeOutput:
        issue_ts = _ensure_utc(issue_ts_utc, field_name="issue_ts_utc")
        if not bridge_allowed or m_now_f is None:
            return HurdleBridgeOutput(
                is_bridge_active=False,
                left_limit_cdf=prior.cdf,
                p_stay_phys=None,
                mu_r_result=None,
                sigma_rem=None,
            )

        station_tz = resolve_station_timezone(station_id, station_timezones)
        local_dt = issue_ts.astimezone(station_tz)
        t_local_hour = float(local_dt.hour + local_dt.minute / 60.0 + local_dt.second / 3600.0)
        season = _season_for_date(target_date)
        eta_s = eta_provider.get_eta_s(
            station_id=station_id,
            season=season,
            t_local_hour=t_local_hour,
        )
        sigma_rem = compute_sigma_rem(prior.sigma0, eta_s)

        x_t = float(instant_x_t_f) if instant_x_t_f is not None else float(m_now_f)
        hook_target = "min" if target_type == "TMIN" else "max"
        # Intentionally delegates TMIN to MuRHook -> preserves NotImplementedError until W3 calibration
        mu_r_res = self._mu_r_hook.compute(
            t_local=t_local_hour,
            extreme_m=float(m_now_f),
            instant_x_t=x_t,
            mu_0=prior.mu0,
            target_type=hook_target,
            station_id=station_id,
            season=season,
        )

        m_val = float(m_now_f)
        mu_r = float(mu_r_res.mu_r)
        p_stay_phys = min(1.0, max(0.0, float(ndtr(-mu_r / sigma_rem))))

        def hurdle_left_limit_cdf(x: float) -> float:
            if math.isinf(x):
                return 0.0 if x < 0.0 else 1.0
            if x <= m_val:
                return 0.0
            val = float(ndtr((float(x) - m_val - mu_r) / sigma_rem))
            return min(1.0, max(0.0, val))

        return HurdleBridgeOutput(
            is_bridge_active=True,
            left_limit_cdf=hurdle_left_limit_cdf,
            p_stay_phys=p_stay_phys,
            mu_r_result=mu_r_res,
            sigma_rem=sigma_rem,
        )


class IntegerGridDiscretizer:
    """Discretizes continuous/hurdle CDFs across validated integer ladders into `BinProbV11`."""

    @staticmethod
    def discretize(
        *,
        bins: Sequence[IntegerBinSpec],
        left_limit_cdf: Callable[[float], float],
        m_now_int_f: Optional[int],
        is_bridge_active: bool,
    ) -> Tuple[Tuple[BinProbV11, ...], Optional[float]]:
        validate_contiguous_bin_ladder(bins)

        out: List[BinProbV11] = []
        p_bin_stay: Optional[float] = None
        for b in bins:
            f_low = float(left_limit_cdf(b.continuous_lower))
            f_high = float(left_limit_cdf(b.continuous_upper))
            p_bin = min(1.0, max(0.0, f_high - f_low))
            bp = BinProbV11(
                bin_id=b.bin_id,
                label=b.label,
                lower_int_f=b.lower_int_f,
                upper_int_f=b.upper_int_f,
                p_model=p_bin,
            )
            out.append(bp)
            if is_bridge_active and m_now_int_f is not None and b.contains_int(m_now_int_f):
                p_bin_stay = p_bin

        return tuple(out), p_bin_stay


class ForecastDistributionEngine:
    """End-to-end M2 engine producing self-certified `P5 ForecastDistributionSnapshot v1.1`."""

    def __init__(
        self,
        *,
        freshness_policy: FreshnessPolicy,
        eta_provider: EtaProvider,
        mu_r_hook: Optional[MuRHook] = None,
        station_timezones: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._freshness_policy = freshness_policy
        self._eta_provider = eta_provider
        self._bridge = HurdleCdfBridge(mu_r_hook=mu_r_hook)
        self._station_timezones = station_timezones

    def build_snapshot(
        self,
        *,
        station_id: str,
        target_date: date,
        target_type: TargetType,
        issue_ts_utc: datetime,
        settle_close_utc: datetime,
        gefs_lead_hours: int,
        model_hash: str,
        prior: PriorAffineFamilyModel,
        bins: Sequence[IntegerBinSpec],
        p11_state: Optional[StationDayState] = None,
        p11_history: Optional[Sequence[StationDayState]] = None,
        sigma_delta_sample: float = 0.0,
        validate_invariants: bool = True,
    ) -> Tuple[ForecastDistributionSnapshotV11, P5InvariantReport]:
        """Build `P5 v1.1` snapshot and verify its four hard invariants mechanically.

        If `p11_history` is passed, uses latest `as_of_ts_utc <= issue_ts_utc` winning rule
        without rollback to older snapshots.
        """
        issue_ts = _ensure_utc(issue_ts_utc, field_name="issue_ts_utc")
        close_ts = _ensure_utc(settle_close_utc, field_name="settle_close_utc")
        code = station_id.strip().upper()
        if not model_hash or not model_hash.strip():
            raise ValueError("model_hash must be non-empty")

        tau_hours = max(0.0, (close_ts - issue_ts).total_seconds() / 3600.0)

        if p11_history is not None and p11_state is not None:
            raise ValueError("Provide either p11_state or p11_history, not both")

        selected_p11 = (
            select_latest_p11_state(
                p11_history,
                station_id=code,
                target_date=target_date,
                as_of_ts_utc=issue_ts,
            )
            if p11_history is not None
            else p11_state
        )

        if selected_p11 is not None and selected_p11.station_id != code:
            raise ValueError(
                f"P11 station_id mismatch: {selected_p11.station_id!r} != {code!r}"
            )

        upstream_obs_fresh = evaluate_m1_to_m2_obs_freshness(
            selected_p11,
            issue_ts_utc=issue_ts,
            freshness_policy=self._freshness_policy,
        )

        oracle_compliant = bool(selected_p11.oracle_compliant) if selected_p11 is not None else True
        m_now_f = float(selected_p11.m_now_exact_f) if (selected_p11 and selected_p11.m_now_exact_f is not None) else None
        m_now_int_f = selected_p11.m_now_int_f if selected_p11 is not None else None
        instant_x_t_f = (
            float(selected_p11.latest_instant_temp_f)
            if (selected_p11 and selected_p11.latest_instant_temp_f is not None)
            else m_now_f
        )

        bridge_allowed = bool(
            selected_p11 is not None
            and oracle_compliant
            and upstream_obs_fresh
            and m_now_f is not None
            and m_now_int_f is not None
        )

        bridge_out = self._bridge.build(
            prior=prior,
            target_type=target_type,
            station_id=code,
            target_date=target_date,
            issue_ts_utc=issue_ts,
            m_now_f=m_now_f,
            instant_x_t_f=instant_x_t_f,
            bridge_allowed=bridge_allowed,
            eta_provider=self._eta_provider,
            station_timezones=self._station_timezones,
        )

        bin_probs, p_bin_stay = IntegerGridDiscretizer.discretize(
            bins=bins,
            left_limit_cdf=bridge_out.left_limit_cdf,
            m_now_int_f=m_now_int_f,
            is_bridge_active=bridge_out.is_bridge_active,
        )

        forecast_key = "|".join(
            [
                code,
                target_date.isoformat(),
                target_type,
                issue_ts.isoformat(),
                model_hash,
                str(gefs_lead_hours),
                "BRIDGE" if bridge_out.is_bridge_active else "PRIOR",
                str(m_now_int_f),
            ]
        )
        forecast_id = str(uuid.uuid5(_FORECAST_ID_NAMESPACE, forecast_key))

        snapshot = ForecastDistributionSnapshotV11(
            schema_version="p5.v1.1",
            forecast_id=forecast_id,
            issue_ts_utc=issue_ts,
            station_id=code,
            target_date=target_date,
            target_type=target_type,
            gefs_lead_hours=int(gefs_lead_hours),
            tau_hours=float(tau_hours),
            settle_close_utc=close_ts,
            model_hash=model_hash,
            prior_mu0=prior.mu0,
            prior_sigma0=prior.sigma0,
            family=prior.family,
            m_now_f=m_now_f,
            m_now_int_f=m_now_int_f,
            oracle_compliant=oracle_compliant,
            upstream_obs_fresh=upstream_obs_fresh,
            is_bridge_active=bridge_out.is_bridge_active,
            p_stay_phys=bridge_out.p_stay_phys,
            p_bin_stay=p_bin_stay,
            bin_probs=bin_probs,
            sigma_delta_sample=float(sigma_delta_sample),
            mu_r_used=bridge_out.mu_r_result.mu_r if bridge_out.mu_r_result is not None else None,
            sigma_rem_used=bridge_out.sigma_rem,
            eta_s_provenance=self._eta_provider.provenance if bridge_out.is_bridge_active else None,
            mu_r_scheme=bridge_out.mu_r_result.scheme if bridge_out.mu_r_result is not None else None,
        )

        report = validate_p5_v11_invariants(snapshot)
        if validate_invariants and not report.all_passed:
            raise AssertionError(f"P5 v1.1 invariant check failed: {report.failures}")

        return snapshot, report


__all__ = [
    "ASOS_PRT_INSTRUMENT_FLOOR_F",
    "BinLadderValidationError",
    "BinProbV11",
    "CalibrationJsonEtaProvider",
    "CausalInputError",
    "ConstantEtaProvider",
    "EtaProvider",
    "ExecutionMode",
    "ForecastDistributionEngine",
    "ForecastDistributionSnapshotV11",
    "HurdleBridgeOutput",
    "HurdleCdfBridge",
    "IntegerBinSpec",
    "IntegerGridDiscretizer",
    "P5InvariantReport",
    "PriorAffineFamilyModel",
    "PriorFamily",
    "TargetType",
    "UnsupportedPriorFamilyError",
    "build_integer_bin_ladder",
    "compute_sigma_rem",
    "evaluate_m1_to_m2_obs_freshness",
    "select_latest_p11_state",
    "validate_contiguous_bin_ladder",
    "validate_p5_v11_invariants",
    "verify_p17_json_line",
]
