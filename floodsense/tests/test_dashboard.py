"""The dashboard contract.

The dashboard's whole job is to show the *actual* operating point, so the
important property is negative: no metric may be written into the page. A
hardcoded number is the failure mode that survives a model change silently
and is still sitting there, wrong, at the demo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard" / "index.html"
FINAL_METRICS = ROOT / "results" / "final_metrics.json"

#: Every key the dashboard and the reporting spec rely on.
REQUIRED_KEYS = (
    "accuracy",
    "event_recall",
    "precision",
    "f1",
    "pr_auc",
    "roc_auc",
    "threshold",
    "mean_lead_time_minutes",
    "median_lead_time_minutes",
    "false_alarms_per_station_day",
    "alarm_precision",
    "tp",
    "fp",
    "tn",
    "fn",
    "data_source",
    "test_period",
    "model",
    "operating_point",
)


class TestDashboardSource:
    def test_dashboard_exists(self):
        assert DASHBOARD.exists(), f"{DASHBOARD} is missing"

    def test_loads_metrics_from_the_results_file(self):
        html = DASHBOARD.read_text()
        assert "results/final_metrics.json" in html
        assert "fetch(" in html

    def test_every_required_key_is_read_by_the_page(self):
        html = DASHBOARD.read_text()
        missing = [k for k in REQUIRED_KEYS if k not in html]
        assert not missing, f"dashboard never reads: {missing}"

    def test_no_metric_value_is_hardcoded_in_the_markup(self):
        """The static markup must carry no numbers at all.

        Scanned with <style> and <script> removed, because that is where a
        hardcoded display value would actually sit: anything the viewer reads
        has to arrive from the fetched JSON, so every metric slot in the
        markup is an empty placeholder. Scanning the script too would only
        flag axis ticks and geometry constants.
        """
        html = DASHBOARD.read_text()
        html = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
        html = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", html)

        numbers = re.findall(r"(?<![\w-])\d+(?:\.\d+)?(?![\w-])", text)
        assert not numbers, (
            f"static markup contains numbers {numbers}; every displayed value "
            "must come from results/final_metrics.json"
        )

    def test_metric_slots_are_empty_placeholders(self):
        """The hero value ships as a dash, not as a number."""
        html = DASHBOARD.read_text()
        hero = re.search(
            r'id="hero-value"[^>]*>(.*?)</div>', html, flags=re.S
        )
        assert hero is not None
        assert not re.search(r"\d", hero.group(1))

    def test_disclaimer_and_synthetic_warning_are_driven_by_data(self):
        html = DASHBOARD.read_text()
        assert "synthetic_data" in html
        assert "disclaimer" in html
        assert "leakage_audit" in html

    def test_states_the_selection_metric_rather_than_accuracy(self):
        """The page must not present accuracy as the selection metric."""
        html = DASHBOARD.read_text()
        assert "selection_metric" in html

    def test_single_hero_figure(self):
        html = DASHBOARD.read_text()
        assert html.count('class="figure"') == 1

    def test_has_a_table_view_for_accessibility(self):
        html = DASHBOARD.read_text()
        assert "curve-table" in html
        assert "<table" in html

    def test_declares_dark_mode_under_both_scopes(self):
        html = DASHBOARD.read_text()
        assert "prefers-color-scheme: dark" in html
        assert '[data-theme="dark"]' in html

    def test_legend_present_for_the_two_series_chart(self):
        html = DASHBOARD.read_text()
        assert "Flood-event recall" in html and "Accuracy" in html
        assert 'class="legend"' in html


@pytest.mark.skipif(
    not FINAL_METRICS.exists(), reason="run scripts/final_evaluation.py first"
)
class TestFinalMetricsFile:
    @pytest.fixture(scope="class")
    def metrics(self) -> dict:
        return json.loads(FINAL_METRICS.read_text())

    def test_has_every_required_key(self, metrics):
        missing = [k for k in REQUIRED_KEYS if k not in metrics]
        assert not missing, f"final_metrics.json missing {missing}"

    def test_rates_are_in_range(self, metrics):
        for key in (
            "accuracy",
            "event_recall",
            "precision",
            "f1",
            "pr_auc",
            "roc_auc",
            "alarm_precision",
            "threshold",
        ):
            assert 0.0 <= metrics[key] <= 1.0, f"{key}={metrics[key]} out of range"

    def test_confusion_matrix_sums_to_the_sample_count(self, metrics):
        total = metrics["tp"] + metrics["fp"] + metrics["tn"] + metrics["fn"]
        assert total == metrics["n_test_samples"]

    def test_accuracy_matches_the_confusion_matrix(self, metrics):
        total = metrics["tp"] + metrics["fp"] + metrics["tn"] + metrics["fn"]
        derived = (metrics["tp"] + metrics["tn"]) / total
        assert derived == pytest.approx(metrics["accuracy"], abs=1e-9)

    def test_event_recall_matches_the_event_counts(self, metrics):
        assert metrics["event_recall"] == pytest.approx(
            metrics["n_events_detected"] / metrics["n_test_events"], abs=1e-9
        )

    def test_threshold_came_from_validation(self, metrics):
        assert metrics["threshold_provenance"]["selected_on"] == "validation"
        assert metrics["threshold_provenance"]["threshold"] == pytest.approx(
            metrics["threshold"]
        )

    def test_operating_point_is_accuracy(self, metrics):
        assert metrics["operating_point"] == "accuracy"

    def test_selection_metric_is_not_accuracy(self, metrics):
        assert "accuracy" not in metrics["selection_metric"].lower()

    def test_synthetic_runs_say_so(self, metrics):
        if metrics["synthetic_data"]:
            assert "SYNTHETIC" in metrics["data_source"].upper()
            assert "synthetic" in metrics["disclaimer"].lower()

    def test_leakage_audit_recorded(self, metrics):
        assert metrics["leakage_audit"] in {"PASS", "FAIL"}

    def test_band_membership_flag_is_consistent(self, metrics):
        low, high = metrics["accuracy_band_target"]
        assert metrics["accuracy_in_target_band"] == (
            low <= metrics["accuracy"] <= high
        )

    def test_alarm_counts_are_consistent(self, metrics):
        assert (
            metrics["true_alarms"] + metrics["false_alarms"] == metrics["total_alarms"]
        )

    def test_does_not_claim_real_data_when_synthetic(self, metrics):
        """The one claim that must never slip through."""
        if metrics["synthetic_data"]:
            text = (metrics["data_source"] + metrics["disclaimer"]).lower()
            assert "real-world skill" not in text.replace(
                "not real-world skill", ""
            ), "a synthetic run must not claim real-world skill"


class TestLiveVersusDemoMode:
    """The page must say which dataset it is showing, and never merge them."""

    def test_both_datasets_are_declared(self):
        html = DASHBOARD.read_text()
        assert "real_data_metrics.json" in html
        assert "final_metrics.json" in html
        assert "real_accuracy_vs_threshold.json" in html
        assert "accuracy_vs_threshold_test.json" in html

    def test_real_data_is_preferred_over_synthetic(self):
        html = DASHBOARD.read_text()
        assert html.index("real_data_metrics.json") < html.index(
            '"../results/final_metrics.json"'
        ), "the LIVE dataset must be tried first"

    def test_mode_labels_are_present(self):
        html = DASHBOARD.read_text()
        assert "LIVE / REAL DATA" in html
        assert "DEMO / SYNTHETIC DATA" in html
        assert "Singapore Government Open Data" in html
        assert "Synthetic Demo Dataset" in html
        assert "DATA SOURCE:" in html

    def test_a_synthetic_file_cannot_be_shown_as_live(self):
        """A mislabelled file must not be able to claim LIVE mode."""
        html = DASHBOARD.read_text()
        assert 'd.mode === "LIVE" && synthetic' in html

    def test_mode_badge_is_an_empty_placeholder(self):
        html = DASHBOARD.read_text()
        assert '<div id="mode-badge"></div>' in html
