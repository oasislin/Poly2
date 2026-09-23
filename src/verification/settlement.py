"""
Settlement Hit Determination: Single Source of Truth for Discretization Jitter.

Mathematical definition and precedent:
Under measurement jitter eps ~ U(-delta, delta) (delta=0.05°F), the true continuous temperature
is T = obs_y + eps ~ U(obs_y - delta, obs_y + delta).
The probability that T falls into interval [lb, ub] is the overlap length divided by 2 * delta:
    P(hit) = max(0.0, min(ub, obs_y + delta) - max(lb, obs_y - delta)) / (2 * delta)

Precedent:
Adheres strictly to the Round 3 KMIA (D, p) arbitration precedent and Active 10 settlement standard,
where +-0.05°F ASOS PRT-1088 discretization jitter is accounted for analytically at bracket boundaries,
preventing staircase artifacts and reconciling deterministic cutoffs with continuous sensor physics.
"""

import math
import numpy as np


def compute_settlement_hit_probability(
    obs_y: float,
    lb: float,
    ub: float,
    jitter_half_width: float = 0.05,
) -> float:
    """
    Compute expected hit probability of observation y in bracket [lb, ub] under uniform jitter.

    Parameters
    ----------
    obs_y : float
        Observed temperature value (°F).
    lb : float
        Lower bracket boundary (may be -inf).
    ub : float
        Upper bracket boundary (may be +inf).
    jitter_half_width : float, default 0.05
        Discretization jitter half-width delta (°F).

    Returns
    -------
    float
        Expected hit probability in [0.0, 1.0].
    """
    if math.isnan(obs_y):
        return 0.0

    delta = float(jitter_half_width)
    width = 2.0 * delta

    if width <= 0.0:
        return 1.0 if (lb <= obs_y < ub) else 0.0

    left_edge = obs_y - delta
    right_edge = obs_y + delta

    # If the jitter interval is completely within bracket bounds, hit probability is identically 1.0
    if (math.isinf(lb) or left_edge >= lb) and (math.isinf(ub) or right_edge <= ub):
        return 1.0

    # If the jitter interval is completely outside bracket bounds, hit probability is identically 0.0
    if (not math.isinf(ub) and left_edge >= ub) or (not math.isinf(lb) and right_edge <= lb):
        return 0.0

    left = left_edge if math.isinf(lb) and lb < 0 else max(lb, left_edge)
    right = right_edge if math.isinf(ub) and ub > 0 else min(ub, right_edge)

    overlap = max(0.0, right - left)
    prob = overlap / width
    return float(np.clip(prob, 0.0, 1.0))
