"""Real-data ingestion: validation, discovery and distribution shift.

The live APIs cannot be reached from a test run, so these cover the parts
that do not need the network: the Bronze→Silver validation gate (fed
deliberately broken tables), the preflight's layer logic, and the
distribution-shift report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from floodsense.ingest.discovery import (
    FLOOD_ALERT_CANDIDATES,
    KNOWN_ENDPOINTS,
    OPTIONAL_HOSTS,
    REQUIRED_HOSTS,
    PreflightReport,
    ProbeResult,
    probe_dns,
)
from floodsense.ingest.validate import (
    ERROR,
    IMPLAUSIBLE_MM_PER_5MIN,
    WARN,
    validate_alerts,
    validate_all,
    validate_rainfall,
    validate_stations,
)
from floodsense.schema import TIMEZONE


def rainfall_frame(n=200, station="S50", start="2026-01-01"):
    ts = pd.date_range(start, periods=n, freq="5min", tz=TIMEZONE)
    return pd.DataFrame(
        {
            "ts": ts,
            "station_id": [station] * n,
            "rainfall_mm": np.zeros(n, dtype=np.float32),
        }
    )


def station_frame(ids=("S50",)):
    return pd.DataFrame(
        {
            "station_id": list(ids),
            "station_name": [f"Station {i}" for i in ids],
            "longitude": [103.8] * len(ids),
            "latitude": [1.35] * len(ids),
        }
    )


def alert_frame(n=3, start="2026-01-01"):
    ts = pd.date_range(start, periods=n, freq="6h", tz=TIMEZONE)
    return pd.DataFrame(
        {
            "alert_id": [f"A{i}" for i in range(n)],
            "ts_start": ts,
            "ts_end": ts + pd.Timedelta(minutes=45),
            "location_name": ["somewhere"] * n,
            "longitude": [103.8] * n,
            "latitude": [1.35] * n,
            "severity": ["Moderate"] * n,
            "urgency": ["Immediate"] * n,
        }
    )


class TestRainfallValidation:
    def test_clean_table_passes_unchanged(self):
        frame = rainfall_frame()
        out, report = validate_rainfall(frame)
        assert len(out) == len(frame)
        assert report.passed
        assert not report.errors

    def test_negative_rainfall_is_dropped(self):
        frame = rainfall_frame()
        frame.loc[5, "rainfall_mm"] = -3.0
        out, report = validate_rainfall(frame)
        assert len(out) == len(frame) - 1
        assert any(i.code == "negative_rainfall" for i in report.errors)

    def test_implausible_reading_is_dropped_as_a_gauge_fault(self):
        frame = rainfall_frame()
        frame.loc[7, "rainfall_mm"] = IMPLAUSIBLE_MM_PER_5MIN + 50
        out, report = validate_rainfall(frame)
        assert len(out) == len(frame) - 1
        assert any(i.code == "implausible_rainfall" for i in report.issues)

    def test_implausible_can_be_kept_when_asked(self):
        frame = rainfall_frame()
        frame.loc[7, "rainfall_mm"] = IMPLAUSIBLE_MM_PER_5MIN + 50
        out, report = validate_rainfall(frame, drop_implausible=False)
        assert len(out) == len(frame)
        issue = next(i for i in report.issues if i.code == "implausible_rainfall")
        assert issue.level == WARN

    def test_a_genuine_downpour_survives(self):
        """The fault threshold must not clip real extreme rainfall."""
        frame = rainfall_frame()
        frame.loc[9, "rainfall_mm"] = 20.0        # very heavy but real
        out, _ = validate_rainfall(frame)
        assert len(out) == len(frame)

    def test_unparseable_timestamps_are_dropped(self):
        frame = rainfall_frame()
        frame["ts"] = frame["ts"].astype(str)
        frame.loc[3, "ts"] = "not a date"
        out, report = validate_rainfall(frame)
        assert len(out) == len(frame) - 1
        assert any(i.code == "unparseable_timestamp" for i in report.errors)

    def test_naive_timestamps_become_singapore_time(self):
        frame = rainfall_frame()
        frame["ts"] = frame["ts"].dt.tz_localize(None)
        out, _ = validate_rainfall(frame)
        assert str(out["ts"].dt.tz) == "Asia/Singapore"

    def test_duplicates_are_reported_not_silently_kept(self):
        frame = pd.concat([rainfall_frame(10), rainfall_frame(10)], ignore_index=True)
        _, report = validate_rainfall(frame)
        issue = next(i for i in report.issues if i.code == "duplicate_readings")
        assert issue.n_rows == 10

    def test_missing_columns_fail_loudly(self):
        out, report = validate_rainfall(pd.DataFrame({"ts": [1]}))
        assert len(out) == 0
        assert any(i.code == "missing_columns" for i in report.errors)

    def test_coverage_is_reported(self):
        _, report = validate_rainfall(rainfall_frame())
        assert any(i.code == "coverage" for i in report.issues)


class TestAlertValidation:
    def test_clean_alerts_pass(self):
        out, report = validate_alerts(alert_frame())
        assert len(out) == 3
        assert report.passed

    def test_empty_alerts_is_an_error_not_an_empty_pass(self):
        """No positive class is a hard stop, not a quiet zero."""
        out, report = validate_alerts(pd.DataFrame())
        assert not report.passed
        assert any(i.code == "no_alerts" for i in report.errors)

    def test_alerts_outside_singapore_are_dropped(self):
        frame = alert_frame()
        frame.loc[1, ["longitude", "latitude"]] = [-74.0, 40.7]
        out, report = validate_alerts(frame)
        assert len(out) == 2
        assert any(i.code == "coordinates_outside_singapore" for i in report.errors)

    def test_alerts_without_coordinates_are_dropped(self):
        frame = alert_frame()
        frame.loc[0, "longitude"] = np.nan
        out, report = validate_alerts(frame)
        assert len(out) == 2
        assert any(i.code == "missing_coordinates" for i in report.errors)

    def test_end_before_start_is_cleared(self):
        frame = alert_frame()
        frame.loc[0, "ts_end"] = frame.loc[0, "ts_start"] - pd.Timedelta(hours=1)
        out, report = validate_alerts(frame)
        assert pd.isna(out.loc[0, "ts_end"])
        assert any(i.code == "end_before_start" for i in report.issues)

    def test_duplicate_alert_ids_collapse(self):
        frame = pd.concat([alert_frame(2), alert_frame(2)], ignore_index=True)
        out, report = validate_alerts(frame)
        assert len(out) == 2
        assert any(i.code == "duplicate_alert_id" for i in report.issues)

    def test_short_history_is_flagged(self):
        _, report = validate_alerts(alert_frame())
        assert any(i.code == "short_alert_history" for i in report.issues)


class TestStationValidation:
    def test_clean_stations_pass(self):
        out, report = validate_stations(station_frame(("S1", "S2", "S3", "S4", "S5")))
        assert len(out) == 5
        assert report.passed

    def test_stations_outside_bounds_dropped(self):
        frame = station_frame(("S1", "S2"))
        frame.loc[1, "longitude"] = 0.0
        out, report = validate_stations(frame)
        assert len(out) == 1
        assert any(i.code == "coordinates_outside_singapore" for i in report.errors)

    def test_few_stations_warned(self):
        _, report = validate_stations(station_frame(("S1",)))
        assert any(i.code == "few_stations" for i in report.issues)


class TestValidateAll:
    def test_readings_without_station_metadata_are_dropped(self):
        readings = pd.concat(
            [rainfall_frame(20, "S50"), rainfall_frame(20, "GHOST")],
            ignore_index=True,
        )
        clean, reports = validate_all(readings, station_frame(("S50",)), alert_frame())
        assert set(clean["readings"]["station_id"]) == {"S50"}
        assert any(
            i.code == "readings_without_station_metadata"
            for i in reports["rainfall"].issues
        )

    def test_reports_cover_every_table(self):
        _, reports = validate_all(rainfall_frame(), station_frame(), alert_frame())
        assert set(reports) == {"rainfall", "stations", "flood_alerts"}

    def test_report_serialises(self):
        _, reports = validate_all(rainfall_frame(), station_frame(), alert_frame())
        payload = reports["rainfall"].to_dict()
        assert {"table", "n_rows_in", "n_rows_out", "issues"} <= set(payload)


class TestDiscovery:
    def test_required_hosts_are_the_data_hosts(self):
        assert "api-open.data.gov.sg" in REQUIRED_HOSTS
        assert "data.gov.sg" in REQUIRED_HOSTS
        assert "www.pub.gov.sg" in OPTIONAL_HOSTS

    def test_only_the_documented_endpoint_is_hardcoded(self):
        """The flood-alerts path must be discovered, never asserted."""
        assert set(KNOWN_ENDPOINTS) == {"rainfall"}
        assert KNOWN_ENDPOINTS["rainfall"].startswith(
            "https://api-open.data.gov.sg/v2/real-time/api/"
        )
        assert len(FLOOD_ALERT_CANDIDATES) >= 2

    def test_dns_probe_reports_resolution(self):
        probe = probe_dns("localhost")
        assert probe.layer == "dns"
        assert isinstance(probe.ok, bool)

    def test_dns_probe_reports_failure_for_a_bad_host(self):
        probe = probe_dns("no-such-host.invalid")
        assert probe.ok is False
        assert "failed" in probe.detail

    def test_report_serialises_with_required_hosts(self):
        report = PreflightReport(
            probes=[ProbeResult("dns", "x", True, "ok")],
            reachable=False,
            blocked_hosts=["data.gov.sg"],
            blocking_layer="egress_policy",
            remedy="allow it",
        )
        payload = report.to_dict()
        assert payload["reachable"] is False
        assert payload["blocking_layer"] == "egress_policy"
        assert payload["required_hosts"] == list(REQUIRED_HOSTS)
        assert "BLOCKED" in report.summary()


class TestDistributionShift:
    @pytest.fixture(scope="class")
    def prepared(self):
        from floodsense.config import Config
        from floodsense.pipeline import prepare
        from floodsense.synthetic import SyntheticConfig, generate

        cfg = Config()
        cfg.features.accumulation_minutes = (15, 60)
        cfg.features.ewm_halflife_minutes = (60,)
        cfg.features.rolling_stat_windows_minutes = (30,)
        cfg.features.lag_minutes = (5,)
        cfg.features.acceleration_windows_minutes = (15,)
        cfg.features.percent_change_windows_minutes = (30,)
        cfg.features.neighbour_window_minutes = (30,)
        cfg.windows.sequence_steps = 12
        data = generate(SyntheticConfig(days=60, n_stations=8, seed=42))
        return prepare(
            readings=data.readings,
            stations=data.stations,
            alerts=data.alerts,
            cfg=cfg,
        )

    def test_profiles_every_split(self, prepared):
        from floodsense.distribution import build_report

        report = build_report(prepared, data_source="synthetic test fixture")
        assert {p.name for p in report.profiles} == {"train", "validation", "test"}

    def test_profiles_carry_prevalence_and_rainfall(self, prepared):
        from floodsense.distribution import build_report

        for p in build_report(prepared).profiles:
            assert p.n_samples > 0
            assert 0.0 <= p.event_prevalence <= 1.0
            assert 0.0 <= p.rain_wet_share <= 1.0
            assert p.station_days > 0
            assert p.months

    def test_periods_are_chronological(self, prepared):
        from floodsense.distribution import build_report

        profiles = {p.name: p for p in build_report(prepared).profiles}
        assert profiles["train"].end < profiles["validation"].start
        assert profiles["validation"].end < profiles["test"].start

    def test_prevalence_ratio_is_reported(self, prepared):
        from floodsense.distribution import build_report

        comparisons = build_report(prepared).comparisons
        assert "test_vs_validation_prevalence_ratio" in comparisons
        assert "validation_event_prevalence" in comparisons
        assert "test_event_prevalence" in comparisons

    def test_builder_flags_a_prevalence_gap(self, prepared):
        """The warning must fire exactly when the ratio leaves [0.7, 1.43].

        This is the check that would have predicted the synthetic run's
        threshold-transfer failure before the test split was ever read.
        """
        import math

        from floodsense.distribution import build_report

        report = build_report(prepared)
        ratio = report.comparisons["test_vs_validation_prevalence_ratio"]
        flagged = any("Event prevalence differs" in w for w in report.warnings)

        outside = math.isfinite(ratio) and (ratio < 0.7 or ratio > 1.43)
        assert flagged == outside, (
            f"ratio {ratio} outside={outside} but flagged={flagged}"
        )
        if flagged:
            message = next(w for w in report.warnings if "Event prevalence" in w)
            assert "will not transfer cleanly" in message

    def test_report_serialises(self, prepared, tmp_path):
        import json

        from floodsense.distribution import build_report

        report = build_report(prepared, data_source="synthetic test fixture")
        path = tmp_path / "shift.json"
        report.write(path)
        payload = json.loads(path.read_text())
        assert payload["data_source"] == "synthetic test fixture"
        assert len(payload["profiles"]) == 3
        assert "Descriptive only" in payload["note"]

    def test_training_subsampling_does_not_distort_the_comparison(self, prepared):
        """Train prevalence must be reported on the eligible region.

        The training split subsamples negatives, so its *sampled* prevalence
        is an artefact of that choice. Comparing it to validation would
        suggest a shift that does not exist in the data.
        """
        from floodsense.distribution import build_report

        report = build_report(prepared)
        train = next(p for p in report.profiles if p.name == "train")

        assert train.subsampled is True
        assert train.event_prevalence > train.event_prevalence_unsampled
        # The comparison uses the comparable figure.
        assert report.comparisons["train_event_prevalence"] == pytest.approx(
            round(train.event_prevalence_unsampled, 6)
        )
        assert report.comparisons["train_event_prevalence_as_sampled"] == pytest.approx(
            round(train.event_prevalence, 6)
        )
        assert report.comparisons["train_negatives_subsampled"] is True

    def test_evaluation_splits_are_not_marked_subsampled(self, prepared):
        from floodsense.distribution import build_report

        report = build_report(prepared)
        for name in ("validation", "test"):
            profile = next(p for p in report.profiles if p.name == name)
            assert profile.subsampled is False
            assert profile.event_prevalence == pytest.approx(
                profile.event_prevalence_unsampled, rel=0.05
            )
