"""
src/modeling/resampling.py: 30-Day Block Cross-Validation (Block-CV) Engine.

Mandated by R2 Mainline Protocol & P3 Specification:
1. Block Resampling Unit: 30 consecutive calendar days per block (breaking meteorological
   temporal autocorrelation / synoptic scale persistence).
2. Data Boundary: Strictly restricted to 2000-01-01 through 2018-12-31.
   2019 data is strictly airgapped and forbidden.
3. Protocol:
   - 20 rounds of Monte Carlo Block-CV.
   - 10% holdout blocks for validation, 90% blocks for fitting.
   - Deterministic pseudo-random seed locked to 20260923.
4. Refitting Constraint: Model refitting MUST be invoked strictly inside the sampling loop.
   Pre-fitting outside the fold and running inference-only is strictly prohibited.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union
import numpy as np
import pandas as pd

from src.utils.airgap import AirgapViolationError, SEALED_YEAR, verify_year_whitelist


DEFAULT_SEED = 20260923
DEFAULT_BLOCK_DAYS = 30
DEFAULT_N_ROUNDS = 20
DEFAULT_HOLDOUT_RATIO = 0.10
TRAIN_START_DATE = date(2000, 1, 1)
TRAIN_END_DATE = date(2018, 12, 31)


@dataclass(frozen=True)
class CalendarBlock:
    """A contiguous calendar time block for resampling."""
    block_id: int
    start_date: date
    end_date: date
    duration_days: int
    dates: Tuple[date, ...] = field(repr=False)

    def contains_date(self, d: date) -> bool:
        return self.start_date <= d <= self.end_date


@dataclass
class BlockCVSplit:
    """A single split (fold) in Block Cross-Validation."""
    round_id: int
    train_block_ids: List[int]
    val_block_ids: List[int]
    train_dates: Set[date] = field(repr=False)
    val_dates: Set[date] = field(repr=False)


def partition_into_30day_blocks(
    start_date: date = TRAIN_START_DATE,
    end_date: date = TRAIN_END_DATE,
    block_days: int = DEFAULT_BLOCK_DAYS,
) -> List[CalendarBlock]:
    """
    Partition the date range [start_date, end_date] into contiguous non-overlapping blocks of `block_days`.
    The final block may have <= block_days to capture remaining tail days.
    """
    if start_date > end_date:
        raise ValueError(f"start_date ({start_date}) must be <= end_date ({end_date})")

    # Airgap assertion: neither boundary can be 2019
    if start_date.year == SEALED_YEAR or end_date.year == SEALED_YEAR:
        raise AirgapViolationError(
            f"Cannot create cross-validation blocks in sealed year {SEALED_YEAR}!"
        )

    blocks: List[CalendarBlock] = []
    curr_start = start_date
    block_id = 0

    while curr_start <= end_date:
        curr_end = min(curr_start + timedelta(days=block_days - 1), end_date)
        # Verify no 2019 date slips in
        if curr_start.year == SEALED_YEAR or curr_end.year == SEALED_YEAR:
            raise AirgapViolationError(f"Block crosses into sealed year {SEALED_YEAR}!")

        # Enumerate dates in block
        block_dates_list = []
        d = curr_start
        while d <= curr_end:
            block_dates_list.append(d)
            d += timedelta(days=1)

        b = CalendarBlock(
            block_id=block_id,
            start_date=curr_start,
            end_date=curr_end,
            duration_days=len(block_dates_list),
            dates=tuple(block_dates_list),
        )
        blocks.append(b)
        block_id += 1
        curr_start = curr_end + timedelta(days=1)

    return blocks


class BlockCrossValidator:
    """
    30-Day Block Cross-Validation Splitter for 2000-2018 Training Data.
    Generates 20 rounds of 90% fit / 10% holdout blocks using fixed seed.
    """

    def __init__(
        self,
        n_rounds: int = DEFAULT_N_ROUNDS,
        holdout_ratio: float = DEFAULT_HOLDOUT_RATIO,
        block_days: int = DEFAULT_BLOCK_DAYS,
        start_date: date = TRAIN_START_DATE,
        end_date: date = TRAIN_END_DATE,
        seed: int = DEFAULT_SEED,
    ):
        if n_rounds <= 0:
            raise ValueError(f"n_rounds must be > 0, got {n_rounds}")
        if not (0.0 < holdout_ratio < 1.0):
            raise ValueError(f"holdout_ratio must be in (0, 1), got {holdout_ratio}")
        if start_date.year > 2018 or end_date.year >= 2019:
            raise AirgapViolationError(
                f"BlockCrossValidator date range [{start_date}, {end_date}] touches or exceeds {SEALED_YEAR}!"
            )

        self.n_rounds = n_rounds
        self.holdout_ratio = holdout_ratio
        self.block_days = block_days
        self.start_date = start_date
        self.end_date = end_date
        self.seed = seed

        # Precompute blocks
        self.blocks = partition_into_30day_blocks(
            start_date=self.start_date,
            end_date=self.end_date,
            block_days=self.block_days,
        )
        self.n_blocks = len(self.blocks)
        self.n_val_blocks = max(1, int(round(self.n_blocks * self.holdout_ratio)))

    def split_blocks(self) -> List[BlockCVSplit]:
        """Generate list of 20 deterministic BlockCVSplit splits."""
        rng = np.random.default_rng(self.seed)
        splits: List[BlockCVSplit] = []

        all_block_ids = np.arange(self.n_blocks)

        for round_id in range(self.n_rounds):
            # Select random 10% of block IDs without replacement
            val_block_ids_arr = rng.choice(
                all_block_ids,
                size=self.n_val_blocks,
                replace=False,
            )
            val_block_ids_set = set(val_block_ids_arr.tolist())
            train_block_ids_set = set(all_block_ids.tolist()) - val_block_ids_set

            # Enumerate exact dates
            val_dates: Set[date] = set()
            for bid in val_block_ids_set:
                val_dates.update(self.blocks[bid].dates)

            train_dates: Set[date] = set()
            for bid in train_block_ids_set:
                train_dates.update(self.blocks[bid].dates)

            # Mathematical orthogonality assertion: zero date leakage
            leakage = val_dates.intersection(train_dates)
            assert len(leakage) == 0, f"Critical leakage detected between train and val: {leakage}"

            splits.append(
                BlockCVSplit(
                    round_id=round_id,
                    train_block_ids=sorted(list(train_block_ids_set)),
                    val_block_ids=sorted(list(val_block_ids_set)),
                    train_dates=train_dates,
                    val_dates=val_dates,
                )
            )

        return splits

    def split_dataframe(
        self,
        df: pd.DataFrame,
        date_col: str = "target_date",
    ) -> Iterator[Tuple[int, pd.DataFrame, pd.DataFrame]]:
        """
        Yields (round_id, train_df, val_df) for each of the 20 rounds.
        Guarantees zero 2019 contamination and zero train/val overlap.
        """
        if df.empty:
            raise ValueError("Input DataFrame is empty")
        if date_col not in df.columns:
            raise KeyError(f"Date column '{date_col}' not found in dataframe")

        # Convert date column to python date objects
        dates_series = pd.to_datetime(df[date_col]).dt.date

        # Check year whitelist on dataframe
        years = pd.to_datetime(df[date_col]).dt.year.unique()
        verify_year_whitelist(years, "BlockCrossValidator.split_dataframe")

        splits = self.split_blocks()

        for split in splits:
            val_mask = dates_series.isin(split.val_dates)
            train_mask = dates_series.isin(split.train_dates)

            train_df = df[train_mask].copy().reset_index(drop=True)
            val_df = df[val_mask].copy().reset_index(drop=True)

            # Re-verify zero index/date overlap
            val_date_set = set(pd.to_datetime(val_df[date_col]).dt.date.unique())
            train_date_set = set(pd.to_datetime(train_df[date_col]).dt.date.unique())
            overlap = val_date_set.intersection(train_date_set)
            assert len(overlap) == 0, f"Round {split.round_id} has {len(overlap)} overlapping dates!"

            yield split.round_id, train_df, val_df


def run_block_cv(
    df: pd.DataFrame,
    fit_fn: Callable[[pd.DataFrame], Any],
    eval_fn: Callable[[Any, pd.DataFrame], Dict[str, float]],
    date_col: str = "target_date",
    n_rounds: int = DEFAULT_N_ROUNDS,
    holdout_ratio: float = DEFAULT_HOLDOUT_RATIO,
    seed: int = DEFAULT_SEED,
) -> Dict[str, Any]:
    """
    Executes 20-round Block-CV loop.
    CRITICAL CONSTRAINT: Model refitting (fit_fn) is called STRICTLY inside each round.
    """
    # Enforce airgap on dataset
    years = pd.to_datetime(df[date_col]).dt.year.unique()
    verify_year_whitelist(years, "run_block_cv input dataframe")

    cv = BlockCrossValidator(
        n_rounds=n_rounds,
        holdout_ratio=holdout_ratio,
        seed=seed,
    )

    round_results: List[Dict[str, Any]] = []

    for round_id, train_df, val_df in cv.split_dataframe(df, date_col=date_col):
        # 1. Refit model STRICTLY inside the loop on train_df (90% blocks)
        model = fit_fn(train_df)

        # 2. Evaluate model on val_df (10% holdout blocks)
        metrics = eval_fn(model, val_df)

        result_entry = {
            "round_id": round_id,
            "train_samples": len(train_df),
            "val_samples": len(val_df),
            **metrics,
        }
        round_results.append(result_entry)

    # Aggregate metric summary across rounds
    metric_keys = [k for k in round_results[0].keys() if k not in ("round_id", "train_samples", "val_samples")]
    summary: Dict[str, Dict[str, float]] = {}

    for k in metric_keys:
        vals = [r[k] for r in round_results if isinstance(r[k], (int, float)) and not math.isnan(r[k])]
        if vals:
            summary[k] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
            }

    return {
        "n_rounds": n_rounds,
        "seed": seed,
        "holdout_ratio": holdout_ratio,
        "round_results": round_results,
        "summary": summary,
    }


# ==============================================================================
# Full Statutory Pipeline Fold Implementation (Addressing P3 Review Committee Query)
# ==============================================================================

@dataclass
class StatutoryFoldModel:
    """
    Encapsulates the complete statutory pipeline state re-fitted inside a single CV fold.
    Guarantees: EMOS (a,b,c,d) + c_train + shape model + mapping competition are ALL fold-local.
    """
    station: str
    variable: str
    lead_hour: int
    seasonal_emos_params: Dict[str, Tuple[float, float, float, float]]
    seasonal_c_train: Dict[str, float]
    selected_family: str  # 'gaussian', 'johnsonsu', or 'evt_hybrid'
    shape_params: Dict[str, Any]
    selection_audit: Dict[str, Any]


def fit_statutory_pipeline_fold(
    train_df: pd.DataFrame,
    station: str,
    variable: str = "tmax",
    lead_hour: int = 18,
    sigma_floor: float = 0.90,
) -> StatutoryFoldModel:
    """
    Full statutory fitting pipeline executed STRICTLY inside each CV fold:
    1. Fits seasonal EMOS (a, b, c, d) with c >= sigma_floor on fold train_df.
    2. Derives fold-specific causal trailing bias and un-biased residuals.
    3. Derives fold-specific seasonal c_train = sqrt(Var(r) / E[sigma_raw^2]).
    4. Computes fold-specific Fisher excess kurtosis and skewness.
    5. Fits Johnson SU and/or EVT GPD if triggered, evaluates BIC competition.
    6. Selects optimal distribution family with EVT tie-breaker.
    """
    from scipy import optimize, stats

    SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
    seasonal_emos: Dict[str, Tuple[float, float, float, float]] = {}
    seasonal_c_train: Dict[str, float] = {}

    train_work = train_df.copy().sort_values("target_date").reset_index(drop=True)

    # Step 1: Fit seasonal EMOS parameters per season inside fold
    for season in SEASONS:
        s_mask = train_work["season"] == season
        df_season = train_work[s_mask]
        if len(df_season) < 100:  # Thin sample check
            # Fallback to simple identity baseline if insufficient data
            seasonal_emos[season] = (0.0, 1.0, sigma_floor, 0.1)
            continue

        ens_m = df_season["ens_mean"].to_numpy()
        ens_v = df_season["ens_var"].to_numpy()
        y_tr = df_season["obs_tmax_f"].to_numpy()

        def emos_crps_obj(p):
            a, b, c, d = p
            mu = a + b * ens_m
            var = (c ** 2) + (d ** 2) * ens_v
            sig = np.maximum(1e-6, np.sqrt(var))
            z = (y_tr - mu) / sig
            crps = sig * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1.0 / np.sqrt(np.pi))
            return float(np.mean(crps))

        init_p = [0.0, 1.0, max(sigma_floor, 1.0), 0.2]
        bounds = [(-15.0, 15.0), (0.5, 1.5), (sigma_floor, 10.0), (0.0, 5.0)]
        res = optimize.minimize(emos_crps_obj, init_p, bounds=bounds, method="L-BFGS-B")
        seasonal_emos[season] = tuple(res.x.tolist())

    # Step 2: Compute raw predictions and fold-local causal trailing bias
    mu_raw = np.zeros(len(train_work))
    sig_raw = np.zeros(len(train_work))

    for idx, row in train_work.iterrows():
        s = row["season"]
        a, b, c, d = seasonal_emos.get(s, (0.0, 1.0, sigma_floor, 0.1))
        m = a + b * row["ens_mean"]
        v = (c ** 2) + (d ** 2) * row["ens_var"]
        mu_raw[idx] = m
        sig_raw[idx] = math.sqrt(max(sigma_floor ** 2, v))

    train_work["mu_raw"] = mu_raw
    train_work["sig_raw"] = sig_raw
    train_work["resid_raw"] = train_work["obs_tmax_f"] - train_work["mu_raw"]
    train_work["b30"] = train_work["resid_raw"].shift(1).rolling(30, min_periods=10).mean().fillna(0.0)
    train_work["mu_calib"] = train_work["mu_raw"] + train_work["b30"]
    train_work["resid_calib"] = train_work["obs_tmax_f"] - train_work["mu_calib"]

    # Step 3: Derive fold-specific seasonal c_train
    for season in SEASONS:
        s_mask = train_work["season"] == season
        sub = train_work[s_mask]
        if len(sub) > 10:
            var_r = float(np.var(sub["resid_calib"], ddof=1))
            mean_sig2 = float(np.mean(sub["sig_raw"] ** 2))
            c_val = math.sqrt(var_r / mean_sig2) if mean_sig2 > 0 else 1.0
            seasonal_c_train[season] = float(np.clip(c_val, 0.8, 1.4))
        else:
            seasonal_c_train[season] = 1.0

    # Step 4: Standardized residuals across fold
    c_series = train_work["season"].map(seasonal_c_train).fillna(1.0)
    train_work["sig_eff"] = train_work["sig_raw"] * c_series
    z_scores = (train_work["resid_calib"] / train_work["sig_eff"]).dropna().to_numpy()
    n_samples = len(z_scores)

    # Step 5: Compute Fisher excess kurtosis and skewness
    skew_val = float(stats.skew(z_scores))
    kurt_fisher = float(stats.kurtosis(z_scores, fisher=True, bias=False))

    jsu_triggered = abs(skew_val) > 0.40
    evt_triggered = kurt_fisher > 1.0

    # Step 6: BIC Competition
    bic_gauss = 0.0 - 2.0 * float(np.sum(stats.norm.logpdf(z_scores)))
    bic_jsu = None
    bic_evt = None
    jsu_params = None
    evt_params = None

    if jsu_triggered:
        try:
            gamma, delta, xi, lam = stats.johnsonsu.fit(z_scores)
            loglik_jsu = float(np.sum(stats.johnsonsu.logpdf(z_scores, gamma, delta, loc=xi, scale=lam)))
            bic_jsu = 4.0 * math.log(n_samples) - 2.0 * loglik_jsu
            jsu_params = {"gamma": gamma, "delta": delta, "xi": xi, "lambda": lam}
        except Exception:
            bic_jsu = None

    if evt_triggered:
        try:
            # 5% and 95% tails
            u_l = float(np.percentile(z_scores, 5.0))
            u_r = float(np.percentile(z_scores, 95.0))
            ex_l = - (z_scores[z_scores < u_l] - u_l)
            ex_r = z_scores[z_scores > u_r] - u_r
            c_l, loc_l, scale_l = stats.genpareto.fit(ex_l, floc=0.0)
            c_r, loc_r, scale_r = stats.genpareto.fit(ex_r, floc=0.0)
            # Approximate hybrid loglik
            loglik_evt = float(np.sum(stats.norm.logpdf(z_scores[(z_scores >= u_l) & (z_scores <= u_r)])))
            loglik_evt += float(np.sum(stats.genpareto.logpdf(ex_l, c_l, scale=scale_l)))
            loglik_evt += float(np.sum(stats.genpareto.logpdf(ex_r, c_r, scale=scale_r)))
            bic_evt = 4.0 * math.log(n_samples) - 2.0 * loglik_evt
            evt_params = {
                "u_left": u_l, "u_right": u_r,
                "gpd_left": {"shape_xi": c_l, "scale_beta": scale_l},
                "gpd_right": {"shape_xi": c_r, "scale_beta": scale_r},
            }
        except Exception:
            bic_evt = None

    # Step 7: Resolve priority and selection
    selected_family = "gaussian"
    shape_params = {}
    delta_bic_winner = 0.0

    delta_jsu = (bic_jsu - bic_gauss) if bic_jsu is not None else 0.0
    delta_evt = (bic_evt - bic_gauss) if bic_evt is not None else 0.0

    if jsu_triggered and evt_triggered and bic_jsu is not None and bic_evt is not None:
        if abs(delta_jsu - delta_evt) <= 2.0:
            # EVT tie-breaker priority (Patch 2)
            if delta_evt < -10.0:
                selected_family = "evt_hybrid"
                shape_params = evt_params
                delta_bic_winner = delta_evt
        elif delta_evt < delta_jsu and delta_evt < -10.0:
            selected_family = "evt_hybrid"
            shape_params = evt_params
            delta_bic_winner = delta_evt
        elif delta_jsu <= delta_evt and delta_jsu < -10.0:
            selected_family = "johnsonsu"
            shape_params = jsu_params
            delta_bic_winner = delta_jsu
    elif jsu_triggered and bic_jsu is not None and delta_jsu < -10.0:
        selected_family = "johnsonsu"
        shape_params = jsu_params
        delta_bic_winner = delta_jsu
    elif evt_triggered and bic_evt is not None and delta_evt < -10.0:
        selected_family = "evt_hybrid"
        shape_params = evt_params
        delta_bic_winner = delta_evt

    audit = {
        "n_samples": n_samples,
        "skewness": skew_val,
        "kurtosis_fisher": kurt_fisher,
        "jsu_triggered": jsu_triggered,
        "evt_triggered": evt_triggered,
        "bic_gaussian": bic_gauss,
        "bic_jsu": bic_jsu,
        "bic_evt": bic_evt,
        "delta_bic_winner": delta_bic_winner,
        "selected_family": selected_family,
    }

    return StatutoryFoldModel(
        station=station,
        variable=variable,
        lead_hour=lead_hour,
        seasonal_emos_params=seasonal_emos,
        seasonal_c_train=seasonal_c_train,
        selected_family=selected_family,
        shape_params=shape_params,
        selection_audit=audit,
    )

