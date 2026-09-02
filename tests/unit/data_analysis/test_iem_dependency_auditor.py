"""
Unit Tests for IEM Upstream Dependency Auditor.
"""

from src.data_analysis.iem_dependency_auditor import (
    IemUpstreamDependencyAuditor,
    IemDependencyAuditResult,
)


class TestIemUpstreamDependencyAuditor:
    """Test programmatic evaluation of IEM data source topology."""

    def test_audit_upstream_pipeline(self):
        auditor = IemUpstreamDependencyAuditor(station="ZSPD", network="CN__ASOS")
        res = auditor.audit_upstream_pipeline()

        assert isinstance(res, IemDependencyAuditResult)
        assert res.network == "CN__ASOS"
        assert res.station == "ZSPD"
        assert res.mesowest_dependency is False
        assert "Unidata" in res.upstream_ingestion_protocol
        assert res.dual_source_redundancy_grade == "PASS_DUAL_LIVE_DECOUPLED"

        d = res.to_dict()
        assert d["network"] == "CN__ASOS"
        assert d["mesowest_dependency"] is False
