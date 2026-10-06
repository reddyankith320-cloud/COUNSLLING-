"""Model comparison and the accuracy-band operating point."""

from __future__ import annotations

import json

import numpy as np
import pytest

from floodsense.events import (
    accuracy_curve,
    event_level_report,
    threshold_for_accuracy_band,
)
from floodsense.experiments import (
    ExperimentResult,
    available_families,
    build_matrices,
    comparison_markdown,
    feature_names,
    last_step_features,
    select_best,
    write_comparison,
)


def result(name: str, pr_auc: float, event_recall: float = 0.5, f1: float = 0.1):
    return ExperimentResult(
        name=name,
        family="sklearn",
        feature_kind="last_step",
        val_pr_auc=pr_auc,
        val_roc_auc=0.8,
        val_brier=0.01,
        val_threshold=0.2,
        val_accuracy=0.96,
        val_recall=0.5,
        val_precision=0.05,
        val_f1=f1,
        val_event_recall=event_recall,
        val_false_alarms_per_station_day=1.5,
        val_mean_lead_minutes=50.0,
        n_features=63,
        fit_seconds=1.0,
    )


class TestSelection:
    def test_picks_highest_pr_auc(self):
        best = select_best([result("a", 0.10), result("b", 0.14), result("c", 0.09)])
        assert best.name == "b"

    def test_ties_broken_by_event_recall(self):
        best = select_best(
            [result("a", 0.12, event_recall=0.70), result("b", 0.12, event_recall=0.85)]
        )
        assert best.name == "b"

    def test_ties_then_broken_by_f1(self):
        best = select_best(
            [
                result("a", 0.12, event_recall=0.80, f1=0.05),
                result("b", 0.12, event_recall=0.80, f1=0.09),
            ]
        )
        assert best.name == "b"

    def test_nan_pr_auc_never_wins(self):
        best = select_best([result("nan", float("nan")), result("ok", 0.01)])
        assert best.name == "ok"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            select_best([])

    def test_accuracy_does_not_decide(self):
        """A model with better accuracy but worse PR-AUC must not win."""
        worse = result("high_accuracy", 0.05)
        worse.val_accuracy = 0.995
        better = result("better_ranking", 0.13)
        better.val_accuracy = 0.951
        assert select_best([worse, better]).name == "better_ranking"


class TestComparisonOutput:
    def test_markdown_has_a_row_per_model(self):
        table = comparison_markdown([result("a", 0.1), result("b", 0.2)])
        assert table.count("\n") == 3          # header, rule, two rows
        assert "a" in table and "b" in table

    def test_markdown_sorted_by_pr_auc(self):
        table = comparison_markdown([result("low", 0.05), result("high", 0.20)])
        assert table.index("high") < table.index("low")

    def test_written_payload_records_that_test_was_untouched(self, tmp_path):
        path = tmp_path / "cmp.json"
        write_comparison([result("a", 0.1)], path)
        payload = json.loads(path.read_text())
        assert payload["test_set_used"] is False
        assert "PR-AUC" in payload["selection_metric"]
        assert "accuracy_is_not_a_selection_metric" in payload
        assert len(payload["models"]) == 1

    def test_available_families_reports_sklearn(self):
        families = available_families()
        assert families["sklearn"] is True
        assert set(families) >= {"sklearn", "xgboost", "lightgbm", "torch"}


class TestFeatureMatrices:
    """The test split must be unreachable from this module."""

    def _prepared(self):
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
        cfg.windows.sequence_steps = 8
        data = generate(SyntheticConfig(days=30, n_stations=6, seed=5))
        return (
            prepare(
                readings=data.readings,
                stations=data.stations,
                alerts=data.alerts,
                cfg=cfg,
            ),
            cfg,
        )

    def test_build_matrices_never_returns_test(self):
        prepared, cfg = self._prepared()
        matrices = build_matrices(prepared, cfg, "last_step")
        assert set(matrices) == {"train", "val"}
        assert "test" not in matrices

    def test_last_step_width_matches_feature_names(self):
        prepared, cfg = self._prepared()
        matrix = last_step_features(prepared, prepared.splits.val)
        assert matrix.shape[1] == len(feature_names(prepared, "last_step"))
        assert matrix.shape[1] == (
            len(prepared.features.names) + len(prepared.statics.names)
        )

    def test_window_summary_width_matches_names(self):
        prepared, cfg = self._prepared()
        matrices = build_matrices(prepared, cfg, "window_summary")
        assert matrices["val"].shape[1] == len(
            feature_names(prepared, "window_summary")
        )

    def test_unknown_feature_kind_raises(self):
        prepared, cfg = self._prepared()
        with pytest.raises(ValueError, match="feature kind"):
            build_matrices(prepared, cfg, "tea_leaves")


class TestAccuracyBandSelection:
    def _synthetic_scores(self, seed=0, n_events=8):
        rng = np.random.default_rng(seed)
        T, S = 4000, 3
        index = np.array([[t, s] for t in range(T) for s in range(S)], dtype=np.int32)
        labels = np.zeros((T, S))
        for i in range(n_events):
            labels[300 + i * 400 : 306 + i * 400, i % S] = 1.0
        probs = np.clip(0.45 * labels + rng.normal(0.06, 0.13, labels.shape), 0, 1)
        return (
            index,
            labels[index[:, 0], index[:, 1]],
            probs[index[:, 0], index[:, 1]],
            T,
            S,
        )

    def test_selected_accuracy_lies_inside_the_band(self):
        index, y, p, T, S = self._synthetic_scores()
        out = threshold_for_accuracy_band(index, y, p, 0.95, 0.99, T, S)
        assert 0.95 <= out["accuracy"] <= 0.99
        assert out["selected_by"] == "max_event_recall_within_accuracy_band"

    def test_reports_how_many_candidates_qualified(self):
        index, y, p, T, S = self._synthetic_scores()
        out = threshold_for_accuracy_band(index, y, p, 0.95, 0.99, T, S)
        assert out["n_candidates_in_band"] >= 1

    def test_no_higher_recall_available_inside_the_band(self):
        """The returned threshold must be the best in the band, not merely in it."""
        index, y, p, T, S = self._synthetic_scores(seed=3)
        out = threshold_for_accuracy_band(index, y, p, 0.95, 0.99, T, S)
        chosen = out["event_report"].event_recall

        candidates = np.unique(np.quantile(p, np.linspace(0.90, 1.0, 40)))
        for thr in candidates:
            accuracy = float(((p >= thr) == (y > 0)).mean())
            if not (0.95 <= accuracy <= 0.99):
                continue
            recall = event_level_report(
                index, y, p, float(thr), T, S
            ).event_recall
            assert recall <= chosen + 1e-9

    def test_unreachable_band_is_flagged_not_faked(self):
        index, y, p, T, S = self._synthetic_scores()
        out = threshold_for_accuracy_band(index, y, p, 0.999999, 1.0, T, S)
        assert out["n_candidates_in_band"] == 0
        assert out["selected_by"] == "closest_accuracy_band_unreachable"

    def test_accuracy_ceiling_is_representable(self):
        """Flag-nothing accuracy must be reachable, else the scan is truncated."""
        index, y, p, T, S = self._synthetic_scores()
        base_rate = float((y > 0).mean())
        ceiling = 1.0 - base_rate
        out = threshold_for_accuracy_band(
            index, y, p, ceiling - 1e-6, 1.0, T, S
        )
        assert out["accuracy"] >= ceiling - 1e-6

    def test_accuracy_curve_is_monotone_overall(self):
        """Rising thresholds trend toward the flag-nothing ceiling."""
        index, y, p, T, S = self._synthetic_scores()
        thresholds = np.linspace(0.0, 1.0, 25)
        curve = accuracy_curve(y, p, thresholds)
        assert curve[0] < curve[-1]
        assert curve[-1] == pytest.approx(1.0 - float((y > 0).mean()), abs=1e-9)

    def test_band_with_zero_positives_does_not_crash(self):
        index, y, p, T, S = self._synthetic_scores()
        out = threshold_for_accuracy_band(
            index, np.zeros_like(y), p, 0.95, 0.99, T, S
        )
        assert np.isfinite(out["threshold"])
