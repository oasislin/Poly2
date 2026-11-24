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
from decimal import Decimal
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
    resolve_station_timezone,
    settle_round_pos_inf,
)
from src.modeling.resampling import evaluate_evt_tail_cdf
from src.prediction.discrete_bin_engine import (
    BinLadderValidationError,
    BinProbV11,
    DiscreteBinEngine,
    IntegerBinSpec,
    build_integer_bin_ladder,
    validate_contiguous_bin_ladder,
)
from src.prediction.dynamic_corrector import MuRHook, MuRResult, SpecV2BaselineMuRHook
from src.utils.causal_utils import (
    CausalInputError,
    compute_record_sha256,
    ensure_utc_datetime,
    verify_record_sha256_line,
)

TargetType = Literal["TMAX", "TMIN"]
ExecutionMode = Literal["PAPER", "LIVE"]
PriorFamily = Literal["gaussian", "johnsonsu", "evt_hybrid"]

# Statutory physical instrument accuracy floor anchored in P8-ALGO-DEF-SPEC v2.0 §阶段3 L206
ASOS_PRT_INSTRUMENT_FLOOR_F: float = 0.9

_FORECAST_ID_NAMESPACE = uuid.UUID("b7c12a8e-3f41-4a22-910c-202611210002")
_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)

verify_p17_json_line = verify_record_sha256_line


class UnsupportedPriorFamilyError(ValueError):
    """Raised when prior distribution family is not in {gaussian, johnsonsu, evt_hybrid}."""


def _season_for_date(target_date: date) -> str:
    month = target_date.month
    if month in (12, 1, 2):
        return "Winter"
    if month in (3, 4, 5):
        return "Spring"
    if month in (6, 7, 8):
        return "Summer"
    return "Autumn"


def _validate_gaussian_params(raw: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(raw)


def _cdf_gaussian(z: float, _: Mapping[str, Any]) -> float:
    return float(ndtr(z))


def _validate_johnsonsu_params(raw: Mapping[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for key in ("gamma", "delta", "xi", "lambda"):
        if key not in raw or isinstance(raw[key], bool):
            raise ValueError(f"johnsonsu missing valid parameter {key!r}")
        val = float(raw[key])
        if not math.isfinite(val):
            raise ValueError(f"johnsonsu parameter {key!r} must be finite, got {val!r}")
        params[key] = val
    if params["delta"] <= 0.0 or params["lambda"] <= 0.0:
        raise ValueError("johnsonsu parameters delta and lambda must be > 0")
    return params


def _cdf_johnsonsu(z: float, params: Mapping[str, Any]) -> float:
    zn = params["gamma"] + params["delta"] * math.asinh((z - params["xi"]) / params["lambda"])
    return float(ndtr(zn))


def _validate_evt_hybrid_params(raw: Mapping[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for key in ("u_left", "u_right"):
        if key not in raw or isinstance(raw[key], bool) or not math.isfinite(float(raw[key])):
            raise ValueError(f"evt_hybrid missing finite boundary {key!r}")
        params[key] = float(raw[key])
    if params["u_left"] >= params["u_right"]:
        raise ValueError("evt_hybrid requires u_left < u_right")
    for tail_key in ("gpd_left", "gpd_right"):
        tail = raw.get(tail_key)
        if not isinstance(tail, Mapping):
            raise ValueError(f"evt_hybrid missing mapping {tail_key!r}")
        xi, beta = float(tail["shape_xi"]), float(tail["scale_beta"])
        if not math.isfinite(xi) or not math.isfinite(beta) or beta <= 0.0 or abs(xi) < 1e-12:
            raise ValueError(f"evt_hybrid {tail_key} invalid (shape_xi={xi}, scale_beta={beta})")
        params[tail_key] = {"shape_xi": xi, "scale_beta": beta}
    return params


def _cdf_evt_hybrid(z: float, params: Mapping[str, Any]) -> float:
    return float(evaluate_evt_tail_cdf(z, dict(params)))


@dataclass(frozen=True)
class _PriorFamilySpec:
    validate: Callable[[Mapping[str, Any]], Dict[str, Any]]
    cdf: Callable[[float, Mapping[str, Any]], float]


_PRIOR_FAMILY_REGISTRY: Mapping[str, _PriorFamilySpec] = {
    "gaussian": _PriorFamilySpec(_validate_gaussian_params, _cdf_gaussian),
    "johnsonsu": _PriorFamilySpec(_validate_johnsonsu_params, _cdf_johnsonsu),
    "evt_hybrid": _PriorFamilySpec(_validate_evt_hybrid_params, _cdf_evt_hybrid),
}


@dataclass(frozen=True)
class PriorAffineFamilyModel:
    """Affine prior distribution `Y = mu0 + sigma0 * Z` over {gaussian, johnsonsu, evt_hybrid}."""

    family: PriorFamily
    mu0: float
    sigma0: float
    shape_params: Mapping[str, Any] = ()  # type: ignore[assignment]

    def __post_init__(self) -> None:
        fam = str(self.family).strip().lower()
        spec = _PRIOR_FAMILY_REGISTRY.get(fam)
        if spec is None:
            raise UnsupportedPriorFamilyError(
                f"Unsupported prior family {self.family!r}; expected {sorted(_PRIOR_FAMILY_REGISTRY)}"
            )
        if isinstance(self.mu0, bool) or not math.isfinite(float(self.mu0)):
            raise ValueError(f"mu0 must be finite float, got {self.mu0!r}")
        if isinstance(self.sigma0, bool) or not math.isfinite(float(self.sigma0)) or float(self.sigma0) <= 0.0:
            raise ValueError(f"sigma0 must be finite and > 0, got {self.sigma0!r}")
        object.__setattr__(self, "family", fam)
        object.__setattr__(self, "mu0", float(self.mu0))
        object.__setattr__(self, "sigma0", float(self.sigma0))
        validated_params = spec.validate(dict(self.shape_params) if self.shape_params else {})
        object.__setattr__(self, "shape_params", validated_params)

    def cdf(self, x: float) -> float:
        """Evaluate continuous prior CDF F_Y(x) strictly in [0.0, 1.0]."""
        if math.isinf(x):
            return 1.0 if x > 0.0 else 0.0
        if math.isnan(x):
            raise ValueError("PriorAffineFamilyModel.cdf received NaN")
        z = (float(x) - self.mu0) / self.sigma0
        val = _PRIOR_FAMILY_REGISTRY[self.family].cdf(z, self.shape_params)
        return min(1.0, max(0.0, val))


class EtaProvider(Protocol):
    """Port supplying remaining variance fraction eta_s(t) in (0, 1] with provenance."""

    provenance: str

    def get_eta_s(self, *, station_id: str, season: str, t_local_hour: float) -> float:
        ...


@dataclass(frozen=True)
class ConstantEtaProvider:
    """Explicitly configured eta_s provider for controlled testing or uniform fallbacks."""

    eta_s: float
    provenance: str

    def __post_init__(self) -> None:
        if not self.provenance or not self.provenance.strip():
            raise ValueError("ConstantEtaProvider.provenance must be non-empty")
        if isinstance(self.eta_s, bool) or not math.isfinite(float(self.eta_s)) or not (0.0 < float(self.eta_s) <= 1.0):
            raise ValueError(f"eta_s must lie in (0, 1], got {self.eta_s!r}")

    def get_eta_s(self, *, station_id: str, season: str, t_local_hour: float) -> float:
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
        cls, path: Path, *, provenance: Optional[str] = None
    ) -> "CalibrationJsonEtaProvider":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        parsed: Dict[str, Dict[str, Tuple[Tuple[float, ...], Tuple[float, ...]]]] = {}
        for station, season_map in payload.get("curves", {}).items():
            st_code = str(station).strip().upper()
            parsed[st_code] = {}
            for season, entry in season_map.items():
                t_hours = tuple(float(v) for v in entry["t_hours"])
                raw_etas = entry["eta_calibrated"] if "eta_calibrated" in entry else entry["eta_s"]
                etas = tuple(min(1.0, max(1e-8, float(v))) for v in raw_etas)
                if len(t_hours) != len(etas) or not t_hours:
                    raise ValueError(f"Invalid eta_s curve for {st_code}/{season}")
                parsed[st_code][str(season)] = (t_hours, etas)
        prov = provenance or str(payload.get("schema_version") or Path(path).name)
        return cls(curves=parsed, provenance=prov)

    def get_eta_s(self, *, station_id: str, season: str, t_local_hour: float) -> float:
        st_code = station_id.strip().upper()
        st_map = self._curves.get(st_code)
        if not st_map or season not in st_map:
            raise KeyError(f"No calibrated eta_s curve for station={st_code!r}, season={season!r}")
        xs, ys = st_map[season]
        t = float(t_local_hour)
        if t <= xs[0]:
            return ys[0]
        if t >= xs[-1]:
            return ys[-1]
        for idx in range(len(xs) - 1):
            x0, x1 = xs[idx], xs[idx + 1]
            if x0 <= t <= x1:
                w = 0.0 if x1 == x0 else (t - x0) / (x1 - x0)
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
class ForecastDistributionSnapshotV11:
    """`P5 ForecastDistributionSnapshot v1.1` (`M2 -> M4 / M7`) matching `interface §3.3` exactly."""

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
    obs_temp_f: Optional[float] = None
    obs_ts_utc: Optional[datetime] = None
    obs_source: Optional[str] = None

    def to_p17_dict_without_hash(
        self,
        *,
        session_id: str,
        execution_mode: ExecutionMode,
        config_hash: str,
    ) -> Dict[str, Any]:
        return {
            "schema_version": "p17.v2",
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
            "obs_temp_f": self.obs_temp_f,
            "obs_ts_utc": self.obs_ts_utc.isoformat() if self.obs_ts_utc is not None else None,
            "obs_source": self.obs_source,
            "oracle_compliant": self.oracle_compliant,
            "upstream_obs_fresh": self.upstream_obs_fresh,
            "is_bridge_active": self.is_bridge_active,
            "p_stay_phys": self.p_stay_phys,
            "p_bin_stay": self.p_bin_stay,
            "bin_probs": [bp.to_dict() for bp in self.bin_probs],
            "sigma_delta_sample": self.sigma_delta_sample,
        }

    def to_p17_json_line(
        self, *, session_id: str, execution_mode: ExecutionMode, config_hash: str
    ) -> str:
        payload = self.to_p17_dict_without_hash(
            session_id=session_id, execution_mode=execution_mode, config_hash=config_hash
        )
        payload["record_sha256"] = compute_record_sha256(payload)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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


def _check_ladder_contiguity(bin_probs: Sequence[BinProbV11], failures: List[str]) -> bool:
    try:
        validate_contiguous_bin_ladder(
            [IntegerBinSpec(b.bin_id, b.label, b.lower_int_f, b.upper_int_f) for b in bin_probs]
        )
        return True
    except BinLadderValidationError as exc:
        failures.append(f"LADDER_CONTIGUITY: {exc}")
        return False


def _check_inv1_simplex(
    bin_probs: Sequence[BinProbV11], sum_tol: float, failures: List[str]
) -> Tuple[bool, float]:
    probs = [b.p_model for b in bin_probs]
    prob_sum = float(sum(probs))
    bounds_ok = all(math.isfinite(p) and 0.0 <= p <= 1.0 for p in probs)
    sum_ok = math.isfinite(prob_sum) and abs(prob_sum - 1.0) <= sum_tol
    ok = bool(bounds_ok and sum_ok)
    if not ok:
        failures.append(f"INV1_SIMPLEX: sum={prob_sum}, bounds_ok={bounds_ok}")
    return ok, prob_sum


def _check_inv2_and_qb2(
    snapshot: ForecastDistributionSnapshotV11, failures: List[str]
) -> Tuple[bool, bool]:
    if snapshot.is_bridge_active:
        inv2_ok = bool(
            snapshot.p_stay_phys is not None
            and snapshot.p_bin_stay is not None
            and math.isfinite(snapshot.p_stay_phys)
            and math.isfinite(snapshot.p_bin_stay)
            and 0.0 <= snapshot.p_stay_phys <= 1.0
            and 0.0 <= snapshot.p_bin_stay <= 1.0
        )
        qb2_ok = bool(
            snapshot.m_now_f is not None
            and snapshot.m_now_int_f is not None
            and snapshot.oracle_compliant
            and snapshot.upstream_obs_fresh
        )
    else:
        inv2_ok = bool(snapshot.p_stay_phys is None and snapshot.p_bin_stay is None)
        qb2_ok = True
    if not inv2_ok:
        failures.append(
            f"INV2_DUAL_ATOM: bridge={snapshot.is_bridge_active}, "
            f"p_stay_phys={snapshot.p_stay_phys}, p_bin_stay={snapshot.p_bin_stay}"
        )
    if not qb2_ok:
        failures.append("Q_B2_INVALID_ACTIVE_BRIDGE_STATE")
    return inv2_ok, qb2_ok


def _check_inv3_inv4_bridge(
    snapshot: ForecastDistributionSnapshotV11, failures: List[str]
) -> Tuple[bool, bool, Optional[str], Optional[float], bool]:
    if not snapshot.is_bridge_active:
        return True, True, None, None, False
    m_int = snapshot.m_now_int_f
    assert m_int is not None
    if snapshot.target_type == "TMAX":
        inv3_ok = all(
            b.p_model == 0.0 for b in snapshot.bin_probs if b.upper_int_f is not None and b.upper_int_f < m_int
        )
    else:
        inv3_ok = all(
            b.p_model == 0.0 for b in snapshot.bin_probs if b.lower_int_f is not None and b.lower_int_f > m_int
        )
    if not inv3_ok:
        failures.append(f"INV3_DEAD_BIN_NONZERO: m_now_int_f={m_int}")

    matching = [
        b
        for b in snapshot.bin_probs
        if (b.lower_int_f is None or m_int >= b.lower_int_f)
        and (b.upper_int_f is None or m_int <= b.upper_int_f)
    ]
    if len(matching) != 1:
        failures.append(f"INV4_BOUNDARY_BIN_COUNT={len(matching)}")
        return inv3_ok, False, None, None, False

    jb = matching[0]
    open_tail = (
        (snapshot.target_type == "TMAX" and jb.upper_int_f is None)
        or (snapshot.target_type == "TMIN" and jb.lower_int_f is None)
    )
    eq_ok = (
        snapshot.p_bin_stay is not None
        and snapshot.p_stay_phys is not None
        and jb.p_model == snapshot.p_bin_stay
        and snapshot.p_bin_stay >= snapshot.p_stay_phys
    )
    tail_ok = (not open_tail) or (snapshot.p_bin_stay == 1.0 and jb.p_model == 1.0)
    inv4_ok = bool(eq_ok and tail_ok)
    if not inv4_ok:
        failures.append(
            f"INV4_INCLUSION: jb.p_model={jb.p_model}, p_bin_stay={snapshot.p_bin_stay}, "
            f"p_stay_phys={snapshot.p_stay_phys}, open_tail={open_tail}"
        )
    return inv3_ok, inv4_ok, jb.bin_id, jb.p_model, open_tail


def validate_p5_v11_invariants(
    snapshot: ForecastDistributionSnapshotV11, *, sum_tol: float = 1e-5
) -> P5InvariantReport:
    """Mechanically check all four `P5 v1.1` invariants + `Q-B2` 3-state validity."""
    failures: List[str] = []
    ladder_ok = _check_ladder_contiguity(snapshot.bin_probs, failures)
    inv1_ok, prob_sum = _check_inv1_simplex(snapshot.bin_probs, sum_tol, failures)
    inv2_ok, qb2_ok = _check_inv2_and_qb2(snapshot, failures)
    inv3_ok, inv4_ok, boundary_id, boundary_p, open_tail = _check_inv3_inv4_bridge(snapshot, failures)
    all_passed = bool(ladder_ok and inv1_ok and inv2_ok and inv3_ok and inv4_ok and qb2_ok)
    return P5InvariantReport(
        inv1_simplex_ok=inv1_ok,
        inv2_dual_atom_domain_ok=inv2_ok,
        inv3_dead_bin_zeroed_ok=inv3_ok,
        inv4_dual_inclusion_ok=inv4_ok,
        q_b2_state_ok=qb2_ok,
        ladder_contiguous_ok=ladder_ok,
        all_passed=all_passed,
        prob_sum=prob_sum,
        boundary_bin_id=boundary_id,
        boundary_p_model=boundary_p,
        p_stay_phys=snapshot.p_stay_phys,
        p_bin_stay=snapshot.p_bin_stay,
        boundary_is_open_tail=open_tail,
        failures=tuple(failures),
    )


def _extract_p11_target_observables(
    p11_state: Optional[StationDayState], target_type: TargetType
) -> Tuple[Optional[Decimal], Optional[int], Optional[float]]:
    if p11_state is None:
        return None, None, None
    if target_type == "TMIN":
        m_exact, m_int = p11_state.m_now_min_exact_f, p11_state.m_now_min_int_f
    else:
        m_exact, m_int = p11_state.m_now_exact_f, p11_state.m_now_int_f
    instant_x = (
        float(p11_state.latest_instant_temp_f)
        if p11_state.latest_instant_temp_f is not None
        else (float(m_exact) if m_exact is not None else None)
    )
    return m_exact, m_int, instant_x


def select_latest_p11_state(
    states: Sequence[StationDayState],
    *,
    station_id: str,
    target_date: date,
    as_of_ts_utc: datetime,
) -> Optional[StationDayState]:
    """Select the single winning P11 state with latest `as_of_ts_utc <= query_as_of` (no rollback)."""
    cutoff = ensure_utc_datetime(as_of_ts_utc, field_name="as_of_ts_utc")
    code = station_id.strip().upper()
    candidates = [
        s
        for s in states
        if s.station_id == code
        and s.target_date == target_date
        and ensure_utc_datetime(s.as_of_ts_utc, field_name="state.as_of_ts_utc") <= cutoff
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda s: (
            ensure_utc_datetime(s.as_of_ts_utc, field_name="state.as_of_ts_utc"),
            ensure_utc_datetime(s.latest_obs_utc, field_name="state.latest_obs_utc")
            if s.latest_obs_utc is not None
            else _EPOCH_UTC,
        ),
    )


def evaluate_m1_to_m2_obs_freshness(
    p11_state: Optional[StationDayState],
    *,
    issue_ts_utc: datetime,
    freshness_policy: FreshnessPolicy,
    target_type: TargetType = "TMAX",
) -> bool:
    """Enforce M2's M1->M2 observation age segment (`v0.3 §2.1 #2`, `interface §3.3`)."""
    issue_ts = ensure_utc_datetime(issue_ts_utc, field_name="issue_ts_utc")
    if p11_state is None:
        return False
    state_asof = ensure_utc_datetime(p11_state.as_of_ts_utc, field_name="p11_state.as_of_ts_utc")
    if state_asof > issue_ts:
        raise CausalInputError(
            f"P11 state as_of_ts_utc={state_asof.isoformat()} exceeds M2 issue_ts_utc={issue_ts.isoformat()}"
        )
    if not p11_state.oracle_compliant or not p11_state.freshness_ok or p11_state.latest_obs_utc is None:
        return False
    m_exact, m_int, _ = _extract_p11_target_observables(p11_state, target_type)
    if m_exact is None or m_int is None:
        return False
    if settle_round_pos_inf(m_exact) != m_int:
        raise ValueError(f"Malformed P11 {target_type} extremum: {m_exact} != {m_int}")
    latest_obs = ensure_utc_datetime(p11_state.latest_obs_utc, field_name="p11_state.latest_obs_utc")
    phys_age = (issue_ts - latest_obs).total_seconds()
    if not (0.0 <= phys_age <= freshness_policy.physical_age_limit_sec):
        return False
    if p11_state.dispatch_age_available and p11_state.latest_dispatch_ts_utc is not None:
        latest_disp = ensure_utc_datetime(
            p11_state.latest_dispatch_ts_utc, field_name="p11_state.latest_dispatch_ts_utc"
        )
        disp_age = (issue_ts - latest_disp).total_seconds()
        limit = freshness_policy.dispatch_age_limit_sec
        return disp_age >= 0.0 and (limit is None or disp_age <= limit)
    return not freshness_policy.require_dispatch_age


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
        issue_ts = ensure_utc_datetime(issue_ts_utc, field_name="issue_ts_utc")
        if not bridge_allowed or m_now_f is None:
            return HurdleBridgeOutput(False, prior.cdf, None, None, None)

        local_dt = issue_ts.astimezone(resolve_station_timezone(station_id, station_timezones))
        t_local_hour = float(local_dt.hour + local_dt.minute / 60.0 + local_dt.second / 3600.0)
        season = _season_for_date(target_date)
        eta_s = eta_provider.get_eta_s(station_id=station_id, season=season, t_local_hour=t_local_hour)
        sigma_rem = compute_sigma_rem(prior.sigma0, eta_s)
        x_t = float(instant_x_t_f) if instant_x_t_f is not None else float(m_now_f)
        hook_target = "min" if target_type == "TMIN" else "max"
        mu_r_res = self._mu_r_hook.compute(
            t_local=t_local_hour,
            extreme_m=float(m_now_f),
            instant_x_t=x_t,
            mu_0=prior.mu0,
            target_type=hook_target,
            station_id=station_id,
            season=season,
        )
        m_val, mu_r = float(m_now_f), float(mu_r_res.mu_r)
        p_stay_phys = min(1.0, max(0.0, float(ndtr(-mu_r / sigma_rem))))

        def hurdle_left_limit_cdf(x: float) -> float:
            if math.isinf(x):
                return 0.0 if x < 0.0 else 1.0
            if x <= m_val:
                return 0.0
            return min(1.0, max(0.0, float(ndtr((float(x) - m_val - mu_r) / sigma_rem))))

        return HurdleBridgeOutput(True, hurdle_left_limit_cdf, p_stay_phys, mu_r_res, sigma_rem)


class IntegerGridDiscretizer:
    """Discretizes continuous/hurdle CDFs across validated integer ladders via DiscreteBinEngine."""

    @staticmethod
    def discretize(
        *,
        bins: Sequence[IntegerBinSpec],
        left_limit_cdf: Callable[[float], float],
        m_now_int_f: Optional[int],
        is_bridge_active: bool,
    ) -> Tuple[Tuple[BinProbV11, ...], Optional[float]]:
        return DiscreteBinEngine.calculate_integer_bin_probabilities(
            bins, left_limit_cdf, m_now_int_f=m_now_int_f, is_bridge_active=is_bridge_active
        )


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

    def _resolve_selected_p11(
        self,
        code: str,
        target_date: date,
        issue_ts: datetime,
        p11_state: Optional[StationDayState],
        p11_history: Optional[Sequence[StationDayState]],
    ) -> Optional[StationDayState]:
        if p11_history is not None and p11_state is not None:
            raise ValueError("Provide either p11_state or p11_history, not both")
        selected = (
            select_latest_p11_state(
                p11_history, station_id=code, target_date=target_date, as_of_ts_utc=issue_ts
            )
            if p11_history is not None
            else p11_state
        )
        if selected is not None and selected.station_id != code:
            raise ValueError(f"P11 station_id mismatch: {selected.station_id!r} != {code!r}")
        return selected

    def build_snapshot(
        self, *, station_id: str, target_date: date, target_type: TargetType,
        issue_ts_utc: datetime, settle_close_utc: datetime, gefs_lead_hours: int,
        model_hash: str, prior: PriorAffineFamilyModel, bins: Sequence[IntegerBinSpec],
        p11_state: Optional[StationDayState] = None,
        p11_history: Optional[Sequence[StationDayState]] = None,
        sigma_delta_sample: float = 0.0, validate_invariants: bool = True,
    ) -> Tuple[ForecastDistributionSnapshotV11, P5InvariantReport]:
        """Build `P5 v1.1` snapshot and verify its four hard invariants mechanically."""
        issue_ts = ensure_utc_datetime(issue_ts_utc, field_name="issue_ts_utc")
        close_ts = ensure_utc_datetime(settle_close_utc, field_name="settle_close_utc")
        code = station_id.strip().upper()
        if not model_hash or not model_hash.strip():
            raise ValueError("model_hash must be non-empty")

        selected = self._resolve_selected_p11(code, target_date, issue_ts, p11_state, p11_history)
        fresh = evaluate_m1_to_m2_obs_freshness(
            selected, issue_ts_utc=issue_ts, freshness_policy=self._freshness_policy, target_type=target_type
        )
        m_exact, m_int_f, x_t = _extract_p11_target_observables(selected, target_type)
        m_now_f = float(m_exact) if m_exact is not None else None
        obs_temp_f = (
            float(selected.latest_instant_temp_f)
            if (selected is not None and selected.latest_instant_temp_f is not None)
            else None
        )
        obs_ts_utc = (
            ensure_utc_datetime(selected.latest_obs_utc, field_name="p11.latest_obs_utc")
            if (selected is not None and selected.latest_obs_utc is not None)
            else None
        )
        obs_source = (
            str(selected.oracle_source_tier)
            if (selected is not None and selected.oracle_source_tier)
            else None
        )
        oracle_ok = bool(selected.oracle_compliant) if selected is not None else True
        bridge_allowed = bool(selected is not None and oracle_ok and fresh and m_now_f is not None and m_int_f is not None)
        bridge_out = self._bridge.build(
            prior=prior, target_type=target_type, station_id=code, target_date=target_date,
            issue_ts_utc=issue_ts, m_now_f=m_now_f, instant_x_t_f=x_t, bridge_allowed=bridge_allowed,
            eta_provider=self._eta_provider, station_timezones=self._station_timezones,
        )
        bin_probs, p_bin_stay = IntegerGridDiscretizer.discretize(
            bins=bins, left_limit_cdf=bridge_out.left_limit_cdf, m_now_int_f=m_int_f, is_bridge_active=bridge_out.is_bridge_active
        )
        snapshot = self._assemble_snapshot(
            code, target_date, target_type, issue_ts, close_ts, gefs_lead_hours, model_hash,
            prior, m_now_f, m_int_f, oracle_ok, fresh, bridge_out, bin_probs, p_bin_stay, sigma_delta_sample,
            obs_temp_f=obs_temp_f, obs_ts_utc=obs_ts_utc, obs_source=obs_source,
        )
        report = validate_p5_v11_invariants(snapshot)
        if validate_invariants and not report.all_passed:
            raise AssertionError(f"P5 v1.1 invariant check failed: {report.failures}")
        return snapshot, report

    @staticmethod
    def _assemble_snapshot(
        code: str,
        target_date: date,
        target_type: TargetType,
        issue_ts: datetime,
        close_ts: datetime,
        gefs_lead_hours: int,
        model_hash: str,
        prior: PriorAffineFamilyModel,
        m_now_f: Optional[float],
        m_now_int_f: Optional[int],
        oracle_ok: bool,
        fresh: bool,
        bridge_out: HurdleBridgeOutput,
        bin_probs: Tuple[BinProbV11, ...],
        p_bin_stay: Optional[float],
        sigma_delta_sample: float,
        *,
        obs_temp_f: Optional[float] = None,
        obs_ts_utc: Optional[datetime] = None,
        obs_source: Optional[str] = None,
    ) -> ForecastDistributionSnapshotV11:
        forecast_key = "|".join([
            code, target_date.isoformat(), target_type, issue_ts.isoformat(), model_hash,
            str(gefs_lead_hours), "BRIDGE" if bridge_out.is_bridge_active else "PRIOR", str(m_now_int_f),
        ])
        return ForecastDistributionSnapshotV11(
            schema_version="p5.v1.1",
            forecast_id=str(uuid.uuid5(_FORECAST_ID_NAMESPACE, forecast_key)),
            issue_ts_utc=issue_ts,
            station_id=code,
            target_date=target_date,
            target_type=target_type,
            gefs_lead_hours=int(gefs_lead_hours),
            tau_hours=max(0.0, (close_ts - issue_ts).total_seconds() / 3600.0),
            settle_close_utc=close_ts,
            model_hash=model_hash,
            prior_mu0=prior.mu0,
            prior_sigma0=prior.sigma0,
            family=prior.family,
            m_now_f=m_now_f,
            m_now_int_f=m_now_int_f,
            oracle_compliant=oracle_ok,
            upstream_obs_fresh=fresh,
            is_bridge_active=bridge_out.is_bridge_active,
            p_stay_phys=bridge_out.p_stay_phys,
            p_bin_stay=p_bin_stay,
            bin_probs=bin_probs,
            sigma_delta_sample=float(sigma_delta_sample),
            obs_temp_f=obs_temp_f,
            obs_ts_utc=obs_ts_utc,
            obs_source=obs_source,
        )


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
