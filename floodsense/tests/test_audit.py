"""The leakage audit.

Two kinds of test here. The PASS tests assert the audit approves a correctly
built pipeline. The FAIL tests matter more: they deliberately break each
guarantee and assert the audit *notices*. An audit that only ever returns
PASS is indistinguishable from one that is not looking.
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from floodsense.audit import (
    FAIL,
    INFO,
    PASS,
    AuditReport,
    Check,
    check_evaluation_split_integrity,
    check_future_rainfall_leakage,
    check_label_horizon_causality,
    check_scaler_fit_region,
    check_split_disjoint,
    check_split_embargo,
    check_temporal_split_order,
    check_threshold_provenance,
    check_warmup_respected,
    run_audit,
)
from floodsense.config import Config
from floodsense.synthetic import SyntheticConfig, generate


def small_config() -> Config:
    """A config whose warm-up is short enough for a fast fixture."""
    cfg = Config()
    cfg.features.accumulation_minutes = (15, 30, 60)
    cfg.features.ewm_halflife_minutes = (60,)
    cfg.features.rolling_stat_windows_minutes = (30,)
    cfg.features.lag_minutes = (5, 15)
    cfg.features.acceleration_windows_minutes = (15,)
    cfg.features.percent_change_windows_minutes = (30,)
    cfg.features.neighbour_window_minutes = (30,)
    cfg.windows.sequence_steps = 12
    cfg.windows.negative_keep_rate = 0.3
    return cfg


@pytest.fixture(scope="module")
def bundle():
    cfg = small_config()
    synth = SyntheticConfig(days=45, n_stations=8, seed=99)
    data = generate(synth)
    from floodsense.pipeline import prepare

    prepared = prepare(
        readings=data.readings,
        stations=data.stations,
        alerts=data.alerts,
        cfg=cfg,
        flood_prone_points=data.flood_prone_points,
    )
    return prepared, cfg, data.alerts


class TestAuditPasses:
    def test_overall_status_is_pass(self, bundle):
        prepared, cfg, alerts = bundle
        report = run_audit(
            prepared,
            cfg,
            alerts=alerts,
            threshold_provenance={
                "selected_on": "validation",
                "rule": "max_event_recall_within_accuracy_band",
                "threshold": 0.2,
            },
        )
        assert report.status == PASS, [c.detail for c in report.failures]

    def test_no_check_is_missing(self, bundle):
        prepared, cfg, alerts = bundle
        report = run_audit(prepared, cfg, alerts=alerts)
        names = {c.name for c in report.checks}
        for expected in (
            "future_rainfall_leakage",
            "future_alert_leakage",
            "label_horizon_causality",
            "temporal_split_order",
            "split_embargo",
            "split_disjoint",
            "duplicate_events_across_splits",
            "scaler_fit_region",
            "warmup_respected",
            "evaluation_split_integrity",
            "station_overlap",
            "feature_selection_on_test",
        ):
            assert expected in names

    def test_future_rainfall_check_passes(self, bundle):
        prepared, cfg, _ = bundle
        check = check_future_rainfall_leakage(prepared, cfg, slice_steps=2000)
        assert check.status == PASS

    def test_label_horizon_check_passes(self, bundle):
        prepared, cfg, _ = bundle
        assert check_label_horizon_causality(prepared, cfg).status == PASS

    def test_splits_checks_pass(self, bundle):
        prepared, cfg, _ = bundle
        assert check_temporal_split_order(prepared).status == PASS
        assert check_split_embargo(prepared, cfg).status == PASS
        assert check_split_disjoint(prepared).status == PASS

    def test_scaler_and_warmup_checks_pass(self, bundle):
        prepared, cfg, _ = bundle
        assert check_scaler_fit_region(prepared).status == PASS
        assert check_warmup_respected(prepared, cfg).status == PASS

    def test_evaluation_splits_not_resampled(self, bundle):
        prepared, _, _ = bundle
        assert check_evaluation_split_integrity(prepared).status == PASS

    def test_report_serialises(self, bundle, tmp_path):
        prepared, cfg, alerts = bundle
        report = run_audit(prepared, cfg, alerts=alerts)
        path = tmp_path / "audit.json"
        report.write(path)
        payload = json.loads(path.read_text())
        assert payload["overall"] in {PASS, FAIL}
        assert len(payload["checks"]) == len(report.checks)
        assert "Leakage Audit" in report.markdown()


class TestAuditCatchesBreakage:
    """Each guarantee, deliberately broken."""

    def test_overlapping_splits_fail(self, bundle):
        prepared, _, _ = bundle
        broken = copy.copy(prepared)
        broken.splits = copy.copy(prepared.splits)
        # Put a validation-era sample into training.
        broken.splits.train = np.vstack(
            [prepared.splits.train, prepared.splits.val[-1:]]
        )
        assert check_temporal_split_order(broken).status == FAIL

    def test_shared_samples_fail(self, bundle):
        prepared, _, _ = bundle
        broken = copy.copy(prepared)
        broken.splits = copy.copy(prepared.splits)
        broken.splits.val = np.vstack(
            [prepared.splits.val, prepared.splits.train[:5]]
        )
        assert check_split_disjoint(broken).status == FAIL

    def test_too_small_embargo_fails(self, bundle):
        prepared, cfg, _ = bundle
        broken = copy.copy(prepared)
        broken.splits = copy.copy(prepared.splits)
        broken.splits.embargo_steps = 1
        assert check_split_embargo(broken, cfg).status == FAIL

    def test_scaler_fitted_elsewhere_fails(self, bundle):
        prepared, _, _ = bundle
        broken = copy.copy(prepared)
        broken.scaler = copy.deepcopy(prepared.scaler)
        broken.scaler.mean = broken.scaler.mean + 1.0
        assert check_scaler_fit_region(broken).status == FAIL

    def test_nowcast_horizon_fails(self, bundle):
        prepared, cfg, _ = bundle
        broken_cfg = copy.deepcopy(cfg)
        broken_cfg.labels.horizon_min_minutes = 0
        assert check_label_horizon_causality(prepared, broken_cfg).status == FAIL

    def test_warmup_violation_fails(self, bundle):
        prepared, cfg, _ = bundle
        broken = copy.copy(prepared)
        broken.splits = copy.copy(prepared.splits)
        broken.splits.train = np.array([[0, 0]], dtype=np.int32)
        assert check_warmup_respected(broken, cfg).status == FAIL

    def test_subsampled_validation_fails(self, bundle):
        prepared, _, _ = bundle
        broken = copy.copy(prepared)
        broken.splits = copy.copy(prepared.splits)
        broken.splits.val = prepared.splits.val[::4]      # thin it out
        assert check_evaluation_split_integrity(broken).status == FAIL

    def test_threshold_from_test_fails(self):
        check = check_threshold_provenance(
            {"selected_on": "test", "rule": "whatever", "threshold": 0.3}
        )
        assert check.status == FAIL

    def test_threshold_from_validation_passes(self):
        check = check_threshold_provenance(
            {"selected_on": "validation", "rule": "band", "threshold": 0.3}
        )
        assert check.status == PASS

    def test_missing_provenance_is_info_not_pass(self):
        assert check_threshold_provenance(None).status == INFO


class TestReportAggregation:
    def test_one_failure_fails_the_report(self):
        report = AuditReport(
            checks=[
                Check("a", PASS, ""),
                Check("b", FAIL, "broken"),
                Check("c", INFO, ""),
            ]
        )
        assert report.status == FAIL
        assert len(report.failures) == 1
        payload = report.to_dict()
        assert payload["n_pass"] == 1 and payload["n_fail"] == 1 and payload["n_info"] == 1

    def test_info_alone_does_not_fail(self):
        report = AuditReport(checks=[Check("a", PASS, ""), Check("b", INFO, "")])
        assert report.status == PASS

    def test_markdown_marks_failures(self):
        report = AuditReport(checks=[Check("bad", FAIL, "it leaked")])
        assert "**FAIL**" in report.markdown()
