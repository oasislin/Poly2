"""Regression tests for P0 short-lead routing defects (D2 & D3).

缺陷单对应关系（docs/handoffs/P8-ALGO-DEF_短时效路由P0缺陷单_20261110.md）：
- D2 (`src/pipeline/main_pipeline.py::MainPipeline._execute_predict`, commit `ca7dbc8`):
  异常注入时严禁静默吞异常或伪报 SUCCESS，必须以 logger.error 落盘并在产出不足或异常计数 > 0 时返回
  status="FAILED" 与精确 exceptions_count。
- D3 (`src/modeling/registry.py::ModelRegistry.predict`, commit `fccae33`):
  预测入口强绑定契约层 AUTHORIZED_LEAD_HOURS 白名单校验机制，非授权 lead 必须在加载锚点前
  显式拒绝并记录 ERROR 日志、抛出 ValueError。
- D1-Max (`src/modeling/interpolator.py`, commit `f2e01d2`):
  按业主分层裁决推迟固化，待 D1-Max 并入 D1-Min 边界策略整体审完后一次性固化（见登记册 G 部待办）。

变更协议：
行为若经裁决变更（例如后续经正式裁决将 6h 纳入 AUTHORIZED_LEAD_HOURS），测试同步更新并在登记册记录。
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.contract.parameter_contract import AUTHORIZED_LEAD_HOURS
from src.modeling.registry import ModelRegistry
from src.pipeline.config import PipelineConfig
from src.pipeline.main_pipeline import MainPipeline


class TestD2ExecutePredictLoudFailure:
    """D2: MainPipeline._execute_predict must surface exceptions loudly as FAILED."""

    @pytest.fixture
    def pipeline(self, tmp_path) -> MainPipeline:
        config = PipelineConfig()
        config.data.raw_dir = str(tmp_path / "raw")
        config.data.processed_dir = str(tmp_path / "processed")
        config.data.models_dir = str(tmp_path / "models")
        config.data.db_dir = str(tmp_path / "db")
        config.data.predictions_db_path = str(tmp_path / "db" / "predictions.db")
        return MainPipeline(config)

    def test_d2_execute_predict_all_failures_loud_fail(self, pipeline: MainPipeline, caplog):
        """Injecting exceptions into every predict_single call yields FAILED and full exceptions_count."""
        mock_pred_pipeline = MagicMock()
        mock_pred_pipeline.predict_single.side_effect = RuntimeError("injected D2 failure")

        with caplog.at_level(logging.ERROR), patch(
            "src.modeling.registry.ModelRegistry", return_value=MagicMock()
        ), patch(
            "src.prediction.prediction_pipeline.PredictionPipeline",
            return_value=mock_pred_pipeline,
        ):
            res = pipeline._execute_predict(target_date="2026-11-13", station="KORD")

        assert res["status"] == "FAILED"
        assert res["predictions_count"] == 0
        assert res["exceptions_count"] == 2
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) == 2
        assert all("injected D2 failure" in r.getMessage() for r in error_records)

    def test_d2_execute_predict_partial_failure_returns_failed(self, pipeline: MainPipeline, caplog):
        """Even a single exception among multiple predictions must flip status to FAILED."""
        mock_pred_pipeline = MagicMock()
        mock_pred_pipeline.predict_single.side_effect = [
            ValueError("injected partial D2 error"),
            None,
        ]

        with caplog.at_level(logging.ERROR), patch(
            "src.modeling.registry.ModelRegistry", return_value=MagicMock()
        ), patch(
            "src.prediction.prediction_pipeline.PredictionPipeline",
            return_value=mock_pred_pipeline,
        ):
            res = pipeline._execute_predict(target_date="2026-11-13", station="KORD")

        assert res["status"] == "FAILED"
        assert res["predictions_count"] == 1
        assert res["exceptions_count"] == 1
        assert any(
            r.levelno == logging.ERROR and "injected partial D2 error" in r.getMessage()
            for r in caplog.records
        )


class TestD3RegistryAuthorizedLeadEnforcement:
    """D3: ModelRegistry.predict must enforce the AUTHORIZED_LEAD_HOURS whitelist mechanism."""

    @pytest.mark.parametrize("unauthorized_lead", [6.0, 96.0])
    def test_d3_rejects_unauthorized_lead_with_error_log(
        self, tmp_path, caplog, unauthorized_lead: float
    ):
        """Passing a currently unauthorized lead value logs ERROR and raises ValueError before model lookup."""
        assert int(round(float(unauthorized_lead))) not in AUTHORIZED_LEAD_HOURS
        registry = ModelRegistry(base_dir=tmp_path)

        with caplog.at_level(logging.ERROR), patch.object(
            registry, "_load_available_anchors"
        ) as mock_anchors, pytest.raises(ValueError, match="AUTHORIZED_LEAD_HOURS"):
            registry.predict(
                station_id="KORD",
                target_date="2026-11-13",
                target_type="max",
                lead_hours=unauthorized_lead,
                ensemble_mean=50.0,
                ensemble_variance=4.0,
                sigma_clim_squared=9.0,
            )

        mock_anchors.assert_not_called()
        assert any(
            r.levelno == logging.ERROR
            and "rejected" in r.getMessage()
            and "AUTHORIZED_LEAD_HOURS" in r.getMessage()
            for r in caplog.records
        )

    def test_d3_whitelist_mechanism_follows_contract_binding(
        self, tmp_path, monkeypatch, caplog
    ):
        """Mechanism check: binding to contract AUTHORIZED_LEAD_HOURS controls rejection dynamically."""
        registry = ModelRegistry(base_dir=tmp_path)
        sample_authorized = float(AUTHORIZED_LEAD_HOURS[0])

        # Removing an ordinarily valid lead from the active whitelist must trigger rejection.
        monkeypatch.setattr(
            "src.modeling.registry.AUTHORIZED_LEAD_HOURS",
            tuple(h for h in AUTHORIZED_LEAD_HOURS if h != int(sample_authorized)),
        )

        with caplog.at_level(logging.ERROR), pytest.raises(ValueError, match="rejected"):
            registry.predict(
                station_id="KORD",
                target_date="2026-11-13",
                target_type="max",
                lead_hours=sample_authorized,
                ensemble_mean=50.0,
                ensemble_variance=4.0,
                sigma_clim_squared=9.0,
            )

        assert any(r.levelno == logging.ERROR for r in caplog.records)
