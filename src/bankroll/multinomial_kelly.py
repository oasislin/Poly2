"""
Multinomial Kelly SLSQP Optimizer with Sunk-Cost Incremental Sizing (Phase 2 Task 05 - Ticket 03 / Issue #85).
Implements Phase 2 Execution Document v2.0 §4.3:
max_f G_incr(f) = sum_i p_i^{new} * ln(W_free + N_i + f_i / q_i - sum_j f_j)
Injects existing positions N_i as exogenous sunk-cost constants for frictionless natural forward hedging.
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional
import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KellyAllocationResult:
    """Output vector of optimal incremental betting allocations."""
    optimal_allocations: List[float]
    total_allocation: float
    expected_growth_rate: float
    success: bool
    message: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize result to dictionary."""
        return {
            "optimal_allocations": [float(x) for x in self.optimal_allocations],
            "total_allocation": float(self.total_allocation),
            "expected_growth_rate": float(self.expected_growth_rate),
            "success": self.success,
            "message": self.message,
        }


@dataclass(frozen=True)
class MultinomialKellyConfig:
    """Configuration parameters for SLSQP solver."""
    initial_guess: float = 1e-4
    epsilon_boundary: float = 1e-7
    maxiter: int = 200
    ftol: float = 1e-9


class MultinomialKellyOptimizer:
    """
    Solves the constrained incremental multinomial Kelly criterion using SLSQP.
    Guarantees input log-safety and fails closed to zero vector on non-convergence.
    """

    def __init__(self, config: Optional[MultinomialKellyConfig] = None):
        self.config = config or MultinomialKellyConfig()

    def optimize(
        self,
        probabilities: List[float],
        prices: List[float],
        existing_payouts: Optional[List[float]] = None,
        w_free: float = 1000.0,
        max_allocable: Optional[float] = None,
    ) -> KellyAllocationResult:
        """
        Solve optimal incremental allocation vector f = [f_1, ..., f_k].
        """
        k = len(probabilities)
        zero_alloc = [0.0] * k

        # 1. Input Validation
        if k == 0 or len(prices) != k:
            return KellyAllocationResult(
                optimal_allocations=zero_alloc,
                total_allocation=0.0,
                expected_growth_rate=0.0,
                success=False,
                message="Dimension mismatch between probabilities and prices.",
            )

        if w_free <= 0.0:
            return KellyAllocationResult(
                optimal_allocations=zero_alloc,
                total_allocation=0.0,
                expected_growth_rate=0.0,
                success=False,
                message="Available free bankroll must be strictly positive.",
            )

        p = np.asarray(probabilities, dtype=np.float64)
        q = np.asarray(prices, dtype=np.float64)
        n = np.asarray(existing_payouts if existing_payouts else [0.0] * k, dtype=np.float64)

        if np.any(q <= 0.0) or np.any(q > 1.0):
            return KellyAllocationResult(
                optimal_allocations=zero_alloc,
                total_allocation=0.0,
                expected_growth_rate=0.0,
                success=False,
                message="Prices must be in (0.0, 1.0].",
            )

        if len(n) != k:
            n = np.zeros(k, dtype=np.float64)

        # Budget cap
        budget_cap = min(w_free, max_allocable) if max_allocable is not None else w_free
        budget_cap = max(0.0, budget_cap)

        # 2. Objective Function: Negative Log-Wealth
        eps = self.config.epsilon_boundary

        def objective(f_vec: np.ndarray) -> float:
            sum_f = np.sum(f_vec)
            # Wealth under scenario i: W_free + N_i + f_i / q_i - sum(f)
            wealth_i = w_free + n + (f_vec / q) - sum_f

            # Smooth penalty if wealth approaches or dips below eps
            penalty = 0.0
            bad_mask = wealth_i < eps
            if np.any(bad_mask):
                penalty = 1e6 * np.sum((eps - wealth_i[bad_mask]) ** 2)
                wealth_safe = np.where(bad_mask, eps, wealth_i)
            else:
                wealth_safe = wealth_i

            log_wealth = np.log(wealth_safe)
            expected_log_wealth = np.sum(p * log_wealth)
            return float(-expected_log_wealth + penalty)

        # 3. Constraints & Bounds
        # Bounds: 0.0 <= f_i <= budget_cap
        bounds = [(0.0, budget_cap) for _ in range(k)]

        # Inequality constraint: budget_cap - sum(f) >= 0
        constraints = [
            {"type": "ineq", "fun": lambda f_vec: budget_cap - np.sum(f_vec)}
        ]

        # Initial point: 1e-4 per coordinate
        f0 = np.full(k, self.config.initial_guess, dtype=np.float64)
        if np.sum(f0) > budget_cap:
            f0 = np.zeros(k, dtype=np.float64)

        # Baseline log-wealth with f = 0
        baseline_neg_growth = objective(np.zeros(k))

        # 4. SLSQP Optimization
        try:
            res = minimize(
                objective,
                f0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={
                    "maxiter": self.config.maxiter,
                    "ftol": self.config.ftol,
                    "disp": False,
                },
            )

            if not res.success or np.any(np.isnan(res.x)):
                logger.warning(f"SLSQP did not converge: {res.message}. Safe fallback to zero vector.")
                return KellyAllocationResult(
                    optimal_allocations=zero_alloc,
                    total_allocation=0.0,
                    expected_growth_rate=0.0,
                    success=False,
                    message=f"Solver did not converge: {res.message}",
                )

            f_opt = np.maximum(0.0, res.x)
            # Clean tiny floating dust < 1e-4 to exact 0.0
            f_opt = np.where(f_opt < 1e-4, 0.0, f_opt)
            total_alloc = float(np.sum(f_opt))

            # If optimal growth does not beat zero-investment baseline, allocate 0
            if res.fun >= baseline_neg_growth - 1e-7 or total_alloc < 1e-3:
                return KellyAllocationResult(
                    optimal_allocations=zero_alloc,
                    total_allocation=0.0,
                    expected_growth_rate=0.0,
                    success=True,
                    message="No positive expected log-wealth gain found. Allocation 0.0.",
                )

            growth_rate = float(baseline_neg_growth - res.fun)
            return KellyAllocationResult(
                optimal_allocations=[round(float(x), 4) for x in f_opt],
                total_allocation=round(total_alloc, 4),
                expected_growth_rate=round(growth_rate, 6),
                success=True,
                message="Optimal Kelly sizing found.",
            )

        except Exception as e:
            logger.error(f"Exception during SLSQP optimization: {e}", exc_info=True)
            return KellyAllocationResult(
                optimal_allocations=zero_alloc,
                total_allocation=0.0,
                expected_growth_rate=0.0,
                success=False,
                message=f"Optimizer exception: {e}",
            )
