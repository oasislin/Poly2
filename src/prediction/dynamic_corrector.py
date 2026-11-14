#!/usr/bin/env python3
"""
DynamicCorrector: Real-time observation integration and conditional probability truncation (Ticket 3.2-01 / Issue #27).

Implements (Phase 1C / v5.9.2):
    1. Maximum Temperature conditional truncation:
       - If L <= T_now: P(X >= L | X >= T_now) = 1.0 (F_post(L) = 0.0)
       - If L > T_now: P(X >= L | X >= T_now) = (1 - F(L)) / (1 - F(T_now))
         => F_post(L) = (F(L) - F(T_now)) / (1 - F(T_now))
    2. Minimum Temperature conditional truncation:
       - If L >= T_now: P(X <= L | X <= T_now) = 1.0 (F_post(L) = 1.0)
       - If L < T_now: P(X <= L | X <= T_now) = F(L) / F(T_now)
         => F_post(L) = F(L) / F(T_now)
    3. Strict invariant guarantees:
       - Posterior CDF F_post is monotonic non-decreasing on (-inf, +inf) and bounded in [0, 1].
       - Closed-form analytical quantile function for truncated distribution.
    4. Safety & numerical protections:
       - Safe epsilon clipping (eps=1e-7) against division by near-zero denominators.
       - Missing observation (None / NaN) transparently falls back to prior distribution.
"""

from dataclasses import dataclass
from datetime import datetime, time
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence, Tuple, Union
import numpy as np
import pandas as pd
from scipy import stats

from src.modeling.gaussian_emos import GaussianEMOS

logger = logging.getLogger(__name__)

_DEFAULT_COOLING_DRIFT_ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "evidence"
    / "p8_mu_r_rho_released_calibration_20261114.json"
)


def _coerce_t_local_hour(
    t_local: Optional[Union[float, int, str, time, datetime]]
) -> Optional[float]:
    """Normalize local observation time into decimal local solar hour in [0, 24]."""
    if t_local is None:
        return None
    if isinstance(t_local, (int, float)) and not isinstance(t_local, bool):
        val = float(t_local)
        return val if math.isfinite(val) else None
    if isinstance(t_local, datetime):
        return float(t_local.hour + t_local.minute / 60.0 + t_local.second / 3600.0)
    if isinstance(t_local, time):
        return float(t_local.hour + t_local.minute / 60.0 + t_local.second / 3600.0)
    if isinstance(t_local, str):
        s = t_local.strip()
        if not s:
            return None
        try:
            parsed = datetime.strptime(s, "%H:%M").time()
        except ValueError:
            parsed = pd.to_datetime(s).time()
        return float(parsed.hour + parsed.minute / 60.0 + parsed.second / 3600.0)
    return None


def _rho_weight_and_deriv(t_hour: float) -> Tuple[float, float]:
    """Remaining daytime heating weight rho(t) = clip((20 - t)/14, 0, 1) and drho/dt."""
    t = float(t_hour)
    if t <= 6.0:
        return 1.0, 0.0
    if t >= 20.0:
        return 0.0, 0.0
    return (20.0 - t) / 14.0, -1.0 / 14.0


def _eval_piecewise_linear_and_deriv(
    t_hour: float,
    knots: Sequence[float],
    values: Sequence[float],
) -> Tuple[float, float]:
    """Evaluate continuous piecewise-linear curve and closed-form d/dt on each segment."""
    t = float(t_hour)
    if len(knots) == 0 or len(values) == 0:
        return 0.0, 0.0
    if t <= float(knots[0]):
        return float(values[0]), 0.0
    if t >= float(knots[-1]):
        return float(values[-1]), 0.0
    for i in range(len(knots) - 1):
        k0, k1 = float(knots[i]), float(knots[i + 1])
        if k0 <= t < k1 or (i == len(knots) - 2 and t <= k1):
            v0, v1 = float(values[i]), float(values[i + 1])
            slope = (v1 - v0) / (k1 - k0)
            return v0 + slope * (t - k0), slope
    return float(values[-1]), 0.0


@dataclass(frozen=True)
class MuRResult:
    """Output of a swappable mu_R(t, m, X_t) conditional bridge drift hook."""

    mu_r: float
    d_mu_r_dt: float = 0.0
    rho: float = 0.0
    kappa: float = 0.0
    delta: float = 0.0
    heat_term: float = 0.0
    cooling_term: float = 0.0
    post_peak_term: float = 0.0
    scheme: str = "custom"


class MuRHook(Protocol):
    """Protocol for swappable intraday bridge drift mu_R(t, m, X_t) implementations."""

    def compute(
        self,
        t_local: float,
        extreme_m: float,
        instant_x_t: float,
        mu_0: float,
        target_type: str = "max",
        station_id: Optional[str] = None,
        season: Optional[str] = None,
    ) -> MuRResult:
        """Compute conditional bridge mean drift mu_R and Stage 9.7 derivative d_mu_r/dt."""
        ...


class SpecV2BaselineMuRHook:
    """Legacy SPEC v2.0#L208 non-negative drift: mu_R = rho(t) * max(0, mu_0 - m)."""

    def compute(
        self,
        t_local: float,
        extreme_m: float,
        instant_x_t: float,
        mu_0: float,
        target_type: str = "max",
        station_id: Optional[str] = None,
        season: Optional[str] = None,
    ) -> MuRResult:
        if target_type.lower() != "max":
            raise NotImplementedError(
                "SpecV2BaselineMuRHook only covers T_max; T_min bridge awaits W3 signed mirror calibration."
            )
        rho, drho_dt = _rho_weight_and_deriv(t_local)
        deficit = max(0.0, float(mu_0) - float(extreme_m))
        heat = rho * deficit
        return MuRResult(
            mu_r=heat,
            d_mu_r_dt=drho_dt * deficit,
            rho=rho,
            kappa=0.0,
            delta=0.0,
            heat_term=heat,
            cooling_term=0.0,
            post_peak_term=0.0,
            scheme="spec_v2_baseline",
        )


class Proposal1CoolingDriftMuRHook:
    """Proposal 1 signed bridge drift with station x season piecewise-smooth (rho, kappa, delta) curves.

    mu_R(t, m, X_t) = rho_{s,se}(t) * max(0, mu_0 - m)
                      - kappa_{s,se}(t) * max(0, M_t - X_t)
                      - delta_{s,se}(t) * 1_{t > t_peak}
    """

    def __init__(self, curves: Optional[Mapping[str, Mapping[str, Dict[str, Any]]]] = None):
        self._curves: Dict[str, Dict[str, Dict[str, Any]]] = (
            {str(st).upper(): {str(se): dict(cfg) for se, cfg in smap.items()} for st, smap in curves.items()}
            if curves is not None
            else {}
        )

    @classmethod
    def from_calibration_artifact(
        cls,
        artifact_path: Union[str, Path] = _DEFAULT_COOLING_DRIFT_ARTIFACT,
    ) -> "Proposal1CoolingDriftMuRHook":
        """Load calibrated station x season spline parameters from evidence artifact."""
        path = Path(artifact_path)
        if not path.exists():
            logger.warning(
                "Proposal 1 calibration artifact missing at %s; initializing empty curves (zero kappa/delta).",
                path,
            )
            return cls(curves={})
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(curves=payload.get("curves", {}))

    def _resolve_curve(
        self, station_id: Optional[str], season: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        if not self._curves or not station_id:
            return None
        s_map = self._curves.get(station_id.upper())
        if not s_map:
            return None
        if season and season in s_map:
            return s_map[season]
        if season:
            seas_l = season.strip().lower()
            for k, v in s_map.items():
                if k.lower() == seas_l:
                    return v
        return None

    def compute(
        self,
        t_local: float,
        extreme_m: float,
        instant_x_t: float,
        mu_0: float,
        target_type: str = "max",
        station_id: Optional[str] = None,
        season: Optional[str] = None,
    ) -> MuRResult:
        if target_type.lower() != "max":
            raise NotImplementedError(
                "Proposal1CoolingDriftMuRHook currently covers T_max only; T_min signed mirror pending W3 calibration."
            )
        t_h = float(t_local)
        deficit = max(0.0, float(mu_0) - float(extreme_m))
        cooling_drop = max(0.0, float(extreme_m) - float(instant_x_t))

        curve = self._resolve_curve(station_id, season)
        if curve is None:
            rho, drho_dt = _rho_weight_and_deriv(t_h)
            heat = rho * deficit
            return MuRResult(
                mu_r=heat,
                d_mu_r_dt=drho_dt * deficit,
                rho=rho,
                kappa=0.0,
                delta=0.0,
                heat_term=heat,
                cooling_term=0.0,
                post_peak_term=0.0,
                scheme="proposal1_no_curve_fallback",
            )

        if "rho_knots" in curve and "rho_values" in curve:
            rho, drho_dt = _eval_piecewise_linear_and_deriv(
                t_h, curve["rho_knots"], curve["rho_values"]
            )
        else:
            rho, drho_dt = _rho_weight_and_deriv(t_h)
        heat = rho * deficit

        kap, dkap_dt = _eval_piecewise_linear_and_deriv(
            t_h, curve["kappa_knots"], curve["kappa_values"]
        )
        t_peak = float(curve.get("t_peak", 13.5))
        if t_h > t_peak:
            delt, ddelt_dt = _eval_piecewise_linear_and_deriv(
                t_h, curve["delta_knots"], curve["delta_values"]
            )
        else:
            delt, ddelt_dt = 0.0, 0.0

        cool_term = kap * cooling_drop
        mu_r = heat - cool_term - delt
        d_mu_r_dt = drho_dt * deficit - dkap_dt * cooling_drop - ddelt_dt
        return MuRResult(
            mu_r=float(mu_r),
            d_mu_r_dt=float(d_mu_r_dt),
            rho=float(rho),
            kappa=float(kap),
            delta=float(delt),
            heat_term=float(heat),
            cooling_term=float(cool_term),
            post_peak_term=float(delt),
            scheme="proposal1_cooling_drift",
        )


class TruncatedDistribution:
    """Posterior probability distribution conditioned on real-time temperature observation."""

    def __init__(
        self,
        base_distribution: GaussianEMOS,
        target_type: str,
        extreme_m: Optional[float] = None,
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, int, str, time, datetime]] = None,
        mu: Optional[float] = None,
        sigma: Optional[float] = None,
        mu_r_result: Optional[MuRResult] = None,
    ):
        self.base_distribution = base_distribution
        self.target_type = target_type.lower()
        if self.target_type not in ["max", "min"]:
            raise ValueError(f"Invalid target_type '{target_type}'. Must be 'max' or 'min'.")

        self.t_local = t_local
        self.observation_time = t_local if isinstance(t_local, datetime) else None
        self.t_local_hour: Optional[float] = _coerce_t_local_hour(t_local)
        self.mu_r_result: Optional[MuRResult] = mu_r_result

        # Validate extreme observation M_t / m_t (conditioning boundary)
        if extreme_m is not None and not np.isnan(extreme_m):
            self.extreme_m: Optional[float] = float(extreme_m)
            self.is_truncated: bool = True
            self.fallback_warning: Optional[str] = None
        else:
            self.extreme_m = None
            self.is_truncated = False
            self.fallback_warning = (
                "Observation missing (extreme_m is None/NaN). Transparently fallen back to static prior Gaussian distribution."
            )
            logger.warning(
                "DynamicCorrector fallback: Observation missing (extreme_m is None/NaN). Reverting to static prior Gaussian distribution."
            )

        if instant_x_t is not None and not np.isnan(instant_x_t):
            self.instant_x_t: Optional[float] = float(instant_x_t)
        else:
            self.instant_x_t = self.extreme_m

        # Extract or resolve distribution parameters
        if mu is not None and sigma is not None:
            self.mu = float(mu)
            self.sigma = float(sigma)
        elif base_distribution.mu is not None and base_distribution.sigma is not None:
            self.mu = float(base_distribution.mu)
            self.sigma = float(base_distribution.sigma)
        else:
            self.mu = float(base_distribution.a)
            self.sigma = float(np.sqrt(base_distribution.c ** 2 + 1e-6))

    @property
    def current_temperature(self) -> Optional[float]:
        """Compatibility alias exposing conditioning extremum extreme_m (distinct from instant_x_t)."""
        return self.extreme_m

    def cdf(self, x: Union[float, np.ndarray, pd.Series, Sequence[float]]) -> Union[float, np.ndarray]:
        """Compute the conditionally truncated cumulative distribution function F_post(x)."""
        x_arr = np.asarray(x, dtype=np.float64)
        is_scalar = (np.ndim(x) == 0)

        # 1. Non-truncated fallback
        if not self.is_truncated or self.current_temperature is None:
            prior_cdf = self.base_distribution.cdf(x=x_arr, mu=self.mu, sigma=self.sigma)
            return float(prior_cdf) if is_scalar else prior_cdf

        t_now = self.current_temperature
        f_t_now = float(self.base_distribution.cdf(x=t_now, mu=self.mu, sigma=self.sigma))
        f_x = np.asarray(self.base_distribution.cdf(x=x_arr, mu=self.mu, sigma=self.sigma), dtype=np.float64)

        if self.target_type == "max":
            # Max Temp: Daily max >= T_now
            # If x <= T_now: F_post(x) = 0.0
            # If x > T_now: F_post(x) = (F(x) - F(T_now)) / (1.0 - F(T_now))
            denom = max(1.0 - f_t_now, 1e-7)
            f_post = np.where(
                x_arr <= t_now,
                0.0,
                (f_x - f_t_now) / denom,
            )
        else:
            # Min Temp: Daily min <= T_now
            # If x >= T_now: F_post(x) = 1.0
            # If x < T_now: F_post(x) = F(x) / F(T_now)
            denom = max(f_t_now, 1e-7)
            f_post = np.where(
                x_arr >= t_now,
                1.0,
                f_x / denom,
            )

        f_post = np.clip(f_post, 0.0, 1.0)
        return float(f_post) if is_scalar else f_post

    def probability_greater_than_or_equal(
        self,
        threshold: Union[float, np.ndarray, pd.Series],
    ) -> Union[float, np.ndarray]:
        """Compute P(X >= threshold | observation)."""
        cdf_val = self.cdf(threshold)
        return 1.0 - cdf_val

    def probability_less_than_or_equal(
        self,
        threshold: Union[float, np.ndarray, pd.Series],
    ) -> Union[float, np.ndarray]:
        """Compute P(X <= threshold | observation)."""
        return self.cdf(threshold)

    def probability_between(
        self,
        low: float,
        high: float,
    ) -> float:
        """Compute P(low <= X <= high | observation) = F_post(high) - F_post(low)."""
        if low > high:
            return 0.0
        p = float(self.cdf(high) - self.cdf(low))
        return max(0.0, min(1.0, p))

    def quantile(self, p: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Closed-form inverse CDF (quantile function) for the truncated Gaussian."""
        p_arr = np.asarray(p, dtype=np.float64)
        is_scalar = (np.ndim(p) == 0)

        if not self.is_truncated or self.current_temperature is None:
            q_prior = self.base_distribution.quantile(p=p_arr, mu=self.mu, sigma=self.sigma)
            return float(q_prior) if is_scalar else q_prior

        t_now = self.current_temperature
        f_t_now = float(self.base_distribution.cdf(x=t_now, mu=self.mu, sigma=self.sigma))

        if self.target_type == "max":
            # For Max: p = (F(x) - F(T_now)) / (1 - F(T_now)) => F(x) = F(T_now) + p * (1 - F(T_now))
            target_cdf = f_t_now + p_arr * (1.0 - f_t_now)
        else:
            # For Min: p = F(x) / F(T_now) => F(x) = p * F(T_now)
            target_cdf = p_arr * f_t_now

        target_cdf = np.clip(target_cdf, 1e-7, 1.0 - 1e-7)
        q_val = self.base_distribution.quantile(p=target_cdf, mu=self.mu, sigma=self.sigma)
        return float(q_val) if is_scalar else q_val

    def to_dict(self) -> Dict[str, Any]:
        """Serialize distribution metadata."""
        return {
            "target_type": self.target_type,
            "mu": self.mu,
            "sigma": self.sigma,
            "is_truncated": self.is_truncated,
            "extreme_m": self.extreme_m,
            "instant_x_t": self.instant_x_t,
            "t_local_hour": self.t_local_hour,
            "current_temperature": self.current_temperature,
            "observation_time": self.observation_time.isoformat() if self.observation_time else None,
            "mu_r": self.mu_r_result.mu_r if self.mu_r_result is not None else None,
            "mu_r_scheme": self.mu_r_result.scheme if self.mu_r_result is not None else None,
            "fallback_warning": self.fallback_warning,
        }


class DynamicCorrector:
    """Three-real-time-input (extreme_m, instant_x_t, t_local) corrector & swappable mu_R bridge engine."""

    def __init__(
        self,
        extreme_m: Optional[float] = None,
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, int, str, time, datetime]] = None,
        mu_r_hook: Optional[MuRHook] = None,
    ):
        self.extreme_m = extreme_m
        self.instant_x_t = instant_x_t
        self.t_local = t_local
        self.observation_time = t_local if isinstance(t_local, datetime) else None
        self.mu_r_hook: MuRHook = (
            mu_r_hook
            if mu_r_hook is not None
            else Proposal1CoolingDriftMuRHook.from_calibration_artifact()
        )

    def set_mu_r_hook(self, mu_r_hook: MuRHook) -> None:
        """Hot-swap the intraday bridge drift mu_R(t, m, X_t) strategy hook."""
        self.mu_r_hook = mu_r_hook

    def update_observation(
        self,
        extreme_m: Optional[float],
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, int, str, time, datetime]] = None,
    ) -> None:
        """Update three-real-time-input state (running extreme, instant temp, local time)."""
        self.extreme_m = extreme_m
        self.instant_x_t = instant_x_t if instant_x_t is not None else extreme_m
        self.t_local = t_local
        self.observation_time = t_local if isinstance(t_local, datetime) else None
        logger.debug(
            "Updated observation: extreme_m=%.2f, instant_x_t=%.2f at %s",
            extreme_m if extreme_m is not None else np.nan,
            self.instant_x_t if self.instant_x_t is not None else np.nan,
            t_local,
        )

    def evaluate_mu_r(
        self,
        t_local: Union[float, int, str, time, datetime],
        extreme_m: float,
        instant_x_t: float,
        mu_0: float,
        target_type: str = "max",
        station_id: Optional[str] = None,
        season: Optional[str] = None,
        mu_r_hook: Optional[MuRHook] = None,
    ) -> MuRResult:
        """Evaluate intraday remaining-increment bridge drift mu_R via active or injected hook."""
        t_hour = _coerce_t_local_hour(t_local)
        if t_hour is None:
            raise ValueError(f"Valid t_local is required to evaluate mu_R, got {t_local!r}")
        hook = mu_r_hook if mu_r_hook is not None else self.mu_r_hook
        return hook.compute(
            t_local=t_hour,
            extreme_m=float(extreme_m),
            instant_x_t=float(instant_x_t),
            mu_0=float(mu_0),
            target_type=target_type,
            station_id=station_id,
            season=season,
        )

    def compute_bridge_no_new_extremum_prob(
        self,
        t_local: Union[float, int, str, time, datetime],
        extreme_m: float,
        instant_x_t: float,
        mu_0: float,
        sigma_rem: float,
        target_type: str = "max",
        station_id: Optional[str] = None,
        season: Optional[str] = None,
        mu_r_hook: Optional[MuRHook] = None,
    ) -> float:
        """Compute conditional no-new-high atom Phi(-mu_R / sigma_rem) using swappable mu_R hook."""
        if sigma_rem <= 0 or not math.isfinite(sigma_rem):
            raise ValueError(f"sigma_rem must be positive finite, got {sigma_rem}")
        res = self.evaluate_mu_r(
            t_local=t_local,
            extreme_m=extreme_m,
            instant_x_t=instant_x_t,
            mu_0=mu_0,
            target_type=target_type,
            station_id=station_id,
            season=season,
            mu_r_hook=mu_r_hook,
        )
        return float(stats.norm.cdf(-res.mu_r / float(sigma_rem)))

    def correct(
        self,
        base_distribution: Union[GaussianEMOS, Any],
        target_type: str,
        extreme_m: Optional[float] = None,
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, int, str, time, datetime]] = None,
        station_id: Optional[str] = None,
        season: Optional[str] = None,
        mu_r_hook: Optional[MuRHook] = None,
    ) -> TruncatedDistribution:
        """Apply conditional truncation + hook-driven mu_R evaluation using (extreme_m, instant_x_t, t_local)."""
        # Check if base_distribution is StaticPredictionResult or GaussianEMOS
        if hasattr(base_distribution, "distribution") and hasattr(base_distribution, "mu"):
            emos_model = base_distribution.distribution
            mu = base_distribution.mu
            sigma = base_distribution.sigma
            station_id = station_id or getattr(base_distribution, "station_id", None)
            season = season or getattr(base_distribution, "season", None)
        elif isinstance(base_distribution, GaussianEMOS):
            emos_model = base_distribution
            mu = base_distribution.mu
            sigma = base_distribution.sigma
        else:
            emos_model = base_distribution
            mu = getattr(base_distribution, "mu", None)
            sigma = getattr(base_distribution, "sigma", None)
            station_id = station_id or getattr(base_distribution, "station_id", None)
            season = season or getattr(base_distribution, "season", None)

        m_val = extreme_m if extreme_m is not None else self.extreme_m
        x_val = instant_x_t if instant_x_t is not None else (
            self.instant_x_t if self.instant_x_t is not None else m_val
        )
        t_val = t_local if t_local is not None else self.t_local

        mu_r_res: Optional[MuRResult] = None
        t_hour = _coerce_t_local_hour(t_val)
        resolved_mu = mu if mu is not None else getattr(emos_model, "a", None)
        if (
            target_type.lower() == "max"
            and m_val is not None
            and not np.isnan(m_val)
            and x_val is not None
            and not np.isnan(x_val)
            and t_hour is not None
            and resolved_mu is not None
        ):
            hook = mu_r_hook if mu_r_hook is not None else self.mu_r_hook
            mu_r_res = hook.compute(
                t_local=t_hour,
                extreme_m=float(m_val),
                instant_x_t=float(x_val),
                mu_0=float(resolved_mu),
                target_type=target_type,
                station_id=station_id,
                season=season,
            )

        return TruncatedDistribution(
            base_distribution=emos_model,
            target_type=target_type,
            extreme_m=m_val,
            instant_x_t=x_val,
            t_local=t_val,
            mu=mu,
            sigma=sigma,
            mu_r_result=mu_r_res,
        )

    def correct_with_station_state(
        self,
        base_distribution: Union[GaussianEMOS, Any],
        station_state: Any,
        target_type: str,
        t_local: Optional[Union[float, int, str, time, datetime]] = None,
        station_id: Optional[str] = None,
        season: Optional[str] = None,
        mu_r_hook: Optional[MuRHook] = None,
    ) -> TruncatedDistribution:
        """Apply conditional truncation using separated extreme_m and instant_x_t from StationDayState."""
        t_type = target_type.lower()
        m_val = station_state.tmax_so_far if t_type == "max" else station_state.tmin_so_far
        frame_instant = getattr(station_state, "current_temp_f", None)
        x_val = frame_instant if frame_instant is not None else m_val
        t_val = t_local if t_local is not None else getattr(station_state, "last_update_utc", None)
        return self.correct(
            base_distribution=base_distribution,
            target_type=target_type,
            extreme_m=m_val,
            instant_x_t=x_val,
            t_local=t_val,
            station_id=station_id or getattr(station_state, "station_id", None),
            season=season,
            mu_r_hook=mu_r_hook,
        )

    def correct_max_temp_probability(
        self,
        base_distribution: Union[GaussianEMOS, Any],
        threshold: float,
        extreme_m: Optional[float] = None,
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, int, str, time, datetime]] = None,
    ) -> float:
        """Calculate P(X >= threshold | extreme_m, instant_x_t, t_local) for maximum temperature."""
        dist = self.correct(
            base_distribution=base_distribution,
            target_type="max",
            extreme_m=extreme_m,
            instant_x_t=instant_x_t,
            t_local=t_local,
        )
        return float(dist.probability_greater_than_or_equal(threshold))

    def correct_min_temp_probability(
        self,
        base_distribution: Union[GaussianEMOS, Any],
        threshold: float,
        extreme_m: Optional[float] = None,
        instant_x_t: Optional[float] = None,
        t_local: Optional[Union[float, int, str, time, datetime]] = None,
    ) -> float:
        """Calculate P(X <= threshold | extreme_m, instant_x_t, t_local) for minimum temperature."""
        dist = self.correct(
            base_distribution=base_distribution,
            target_type="min",
            extreme_m=extreme_m,
            instant_x_t=instant_x_t,
            t_local=t_local,
        )
        return float(dist.probability_less_than_or_equal(threshold))
