#!/usr/bin/env python3
"""
Unit tests for short-lead physical variance decay in LeadTimeInterpolator
and statutory master node bit-level regression protection.

Work Order: P7-W1-POOLPHASE (Subtask W1-A)
Permit: P7-W1-GO-A
"""

import pickle
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.modeling.gaussian_emos import GaussianEMOS
from src.modeling.interpolator import LeadTimeInterpolator

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MODELS_DIR = PROJECT_ROOT / "data" / "models"


@pytest.fixture
def anchor_models_24h_min_max():
    """Identical 24h anchor models for Max and Min Temp to verify strict symmetry."""
    model_24 = GaussianEMOS(a=0.5, b=0.98, c=0.4, d=0.85)
    model_48 = GaussianEMOS(a=1.2, b=0.92, c=0.7, d=1.05)
    return {
        "max": {24: model_24, 48: model_48},
        "min": {24: model_24, 48: model_48},
    }


class TestMaxTempShortLeadVarianceDecay:
    """Verifies Max Temp variance decay formula σ_L = σ_24h * sqrt(max(0, L)/24.0) and Min Temp symmetry."""

    def test_tmax_short_lead_decay_numerical_values(self, anchor_models_24h_min_max):
        interpolator = LeadTimeInterpolator()
        anchors_max = anchor_models_24h_min_max["max"]
        base_model_24h = anchors_max[24]

        ens_mean = 25.0
        ens_var = 4.0
        clim_var = 5.0

        mu_24h, sigma_24h = base_model_24h.compute_params(ens_mean, ens_var, clim_var)

        test_leads = [0.0, 3.0, 6.0, 12.0, 18.0, 23.9]
        for lead in test_leads:
            dist = interpolator.predict_distribution(
                target_type="max",
                lead_hours=lead,
                ensemble_mean=ens_mean,
                ensemble_variance=ens_var,
                sigma_clim_squared=clim_var,
                anchor_models=anchors_max,
            )
            expected_factor = np.sqrt(max(0.0, lead) / 24.0)
            expected_sigma = max(1e-4, sigma_24h * expected_factor)

            assert np.isclose(dist.mu, mu_24h, atol=1e-12), f"Mean drifted at lead={lead}"
            assert np.isclose(dist.sigma, expected_sigma, atol=1e-12), f"Decayed sigma mismatch at lead={lead}"

    def test_symmetry_between_max_and_min_temp(self, anchor_models_24h_min_max):
        """Max Temp and Min Temp must yield identical (mu, sigma) when given identical 24h anchors and inputs."""
        interpolator = LeadTimeInterpolator()
        anchors_max = anchor_models_24h_min_max["max"]
        anchors_min = anchor_models_24h_min_max["min"]

        ens_mean = 18.5
        ens_var = 3.2
        clim_var = 4.8

        test_leads = [0.0, 1.5, 6.0, 12.0, 18.0, 23.5]
        for lead in test_leads:
            dist_max = interpolator.predict_distribution(
                target_type="max",
                lead_hours=lead,
                ensemble_mean=ens_mean,
                ensemble_variance=ens_var,
                sigma_clim_squared=clim_var,
                anchor_models=anchors_max,
            )
            dist_min = interpolator.predict_distribution(
                target_type="min",
                lead_hours=lead,
                ensemble_mean=ens_mean,
                ensemble_variance=ens_var,
                sigma_clim_squared=clim_var,
                anchor_models=anchors_min,
            )

            assert np.isclose(dist_max.mu, dist_min.mu, atol=1e-14), f"Symmetry broken for mu at lead={lead}"
            assert np.isclose(dist_max.sigma, dist_min.sigma, atol=1e-14), f"Symmetry broken for sigma at lead={lead}"

    def test_decay_boundary_conditions(self, anchor_models_24h_min_max):
        interpolator = LeadTimeInterpolator()
        anchors_max = anchor_models_24h_min_max["max"]
        base_model_24h = anchors_max[24]

        ens_mean = 10.0
        ens_var = 1.0
        clim_var = 2.0

        # Boundary L = 0: must return physical floor 1e-4
        dist_0 = interpolator.predict_distribution(
            target_type="max",
            lead_hours=0.0,
            ensemble_mean=ens_mean,
            ensemble_variance=ens_var,
            sigma_clim_squared=clim_var,
            anchor_models=anchors_max,
        )
        assert dist_0.sigma == 1e-4

        # Boundary L < 0 (e.g. -6h negative lead defense): must clamp to max(0, L) = 0 -> 1e-4
        dist_neg = interpolator.predict_distribution(
            target_type="max",
            lead_hours=-6.0,
            ensemble_mean=ens_mean,
            ensemble_variance=ens_var,
            sigma_clim_squared=clim_var,
            anchor_models=anchors_max,
        )
        assert dist_neg.sigma == 1e-4

        # Boundary L = 24.0: must NOT decay; exactly equals 24h anchor output
        mu_24h, sigma_24h = base_model_24h.compute_params(ens_mean, ens_var, clim_var)
        dist_24 = interpolator.predict_distribution(
            target_type="max",
            lead_hours=24.0,
            ensemble_mean=ens_mean,
            ensemble_variance=ens_var,
            sigma_clim_squared=clim_var,
            anchor_models=anchors_max,
        )
        assert np.isclose(dist_24.mu, mu_24h, atol=1e-14)
        assert np.isclose(dist_24.sigma, sigma_24h, atol=1e-14)

    def test_anchor_selection_and_keyerror_exceptions(self):
        interpolator = LeadTimeInterpolator()
        dummy_model = GaussianEMOS(a=0.0, b=1.0, c=0.5, d=0.5)

        # 1. Missing 24h anchor when anchor set only has 48h
        with pytest.raises(KeyError, match="Max Temp interpolation requires 24h anchor model"):
            interpolator.predict_distribution(
                target_type="max",
                lead_hours=12.0,
                ensemble_mean=20.0,
                ensemble_variance=2.0,
                sigma_clim_squared=2.0,
                anchor_models={48: dummy_model},
            )

        # 2. Empty anchor models dict
        with pytest.raises(KeyError, match="Max Temp interpolation requires 24h anchor model"):
            interpolator.predict_distribution(
                target_type="max",
                lead_hours=12.0,
                ensemble_mean=20.0,
                ensemble_variance=2.0,
                sigma_clim_squared=2.0,
                anchor_models={},
            )

        # 3. Missing 24h anchor when lead is below minimum anchor (extrapolation)
        with pytest.raises(KeyError, match="Max Temp interpolation requires 24h anchor model"):
            interpolator.predict_distribution(
                target_type="max",
                lead_hours=3.0,
                ensemble_mean=20.0,
                ensemble_variance=2.0,
                sigma_clim_squared=2.0,
                anchor_models={6: dummy_model, 30: dummy_model},
            )

        # 4. Interior node (e.g. 18h between 6h and 30h) without 24h falls back to linear interpolation
        dist_interior = interpolator.predict_distribution(
            target_type="max",
            lead_hours=18.0,
            ensemble_mean=20.0,
            ensemble_variance=2.0,
            sigma_clim_squared=2.0,
            anchor_models={6: dummy_model, 30: dummy_model},
        )
        assert dist_interior.mu is not None
        assert dist_interior.sigma is not None

    def test_vectorized_and_scalar_broadcast(self, anchor_models_24h_min_max):
        interpolator = LeadTimeInterpolator()
        anchors_max = anchor_models_24h_min_max["max"]

        ens_mean_arr = np.array([20.0, 22.0, 25.0])
        ens_var_arr = np.array([2.0, 3.0, 4.0])
        clim_var_arr = np.array([3.0, 3.0, 3.0])

        dist_arr = interpolator.predict_distribution(
            target_type="max",
            lead_hours=12.0,
            ensemble_mean=ens_mean_arr,
            ensemble_variance=ens_var_arr,
            sigma_clim_squared=clim_var_arr,
            anchor_models=anchors_max,
        )

        assert isinstance(dist_arr.mu, np.ndarray)
        assert isinstance(dist_arr.sigma, np.ndarray)
        assert len(dist_arr.mu) == 3
        assert len(dist_arr.sigma) == 3

        # Compare element-by-element with scalar calls
        for i in range(3):
            dist_sc = interpolator.predict_distribution(
                target_type="max",
                lead_hours=12.0,
                ensemble_mean=float(ens_mean_arr[i]),
                ensemble_variance=float(ens_var_arr[i]),
                sigma_clim_squared=float(clim_var_arr[i]),
                anchor_models=anchors_max,
            )
            assert np.isclose(dist_arr.mu[i], dist_sc.mu, atol=1e-12)
            assert np.isclose(dist_arr.sigma[i], dist_sc.sigma, atol=1e-12)


class TestStatutory12hMasterNodeBitInvariance:
    """
    Mandated by Committee Verdict P7-W1-PREREG-VERDICT-R2 (B1):
    Asserts bit-for-bit (IEEE 754 bit-representation) exact invariance for statutory 12h master nodes.
    """

    @pytest.mark.parametrize("station", ["KORD", "KMIA"])
    @pytest.mark.parametrize("season", ["Winter", "Spring", "Summer", "Autumn"])
    def test_12h_statutory_master_node_bit_invariance(self, station, season):
        model_filename = f"{station}_{season}_Max_lead12h.pkl"
        model_path = MODELS_DIR / model_filename
        assert model_path.exists(), f"12h Statutory master node model file {model_path} missing!"

        with open(model_path, "rb") as pf:
            payload = pickle.load(pf)

        model_12h: GaussianEMOS = payload["model"]
        meta = payload["metadata"]

        assert meta["lead_hours"] == 12
        assert meta["target_type"] == "max"
        assert meta["station_id"] == station

        # Static parameters (a, b, c, d) bit-level invariance
        p_dict = meta["params"]
        np.testing.assert_equal(model_12h.a, p_dict["a"])
        np.testing.assert_equal(model_12h.b, p_dict["b"])
        np.testing.assert_equal(model_12h.c, p_dict["c"])
        np.testing.assert_equal(model_12h.d, p_dict["d"])

        # Forward prediction pass bit-level invariance
        test_ens_mean = 32.5
        test_ens_var = 4.25
        test_clim_var = 5.75

        mu, sigma = model_12h.compute_params(test_ens_mean, test_ens_var, test_clim_var)

        # Bitwise hex representation check: ensuring zero drift from mathematical specification
        expected_mu = model_12h.a + model_12h.b * test_ens_mean
        expected_var = (model_12h.c ** 2) + (model_12h.d ** 2) * test_ens_var + test_clim_var
        expected_sigma = np.sqrt(expected_var)

        np.testing.assert_equal(mu, expected_mu)
        np.testing.assert_equal(sigma, expected_sigma)
        assert float(mu).hex() == float(expected_mu).hex()
        assert float(sigma).hex() == float(expected_sigma).hex()
