"""Model plumbing, loss behaviour and the evaluation metrics."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from floodsense.config import ModelConfig
from floodsense.events import (
    _merge,
    _runs,
    event_level_report,
    threshold_for_event_recall,
)
from floodsense.losses import FocalLossWithLogits, WeightedBCEWithLogits, build_loss
from floodsense.metrics import (
    compute_report,
    lift_over_base_rate,
    precision_at_recall_table,
    threshold_for_recall,
)
from floodsense.model import AdditiveAttention, FloodSenseLSTM


class TestModel:
    def test_forward_shapes(self):
        model = FloodSenseLSTM(n_dynamic=7, n_static=3, cfg=ModelConfig(hidden_size=16))
        logits = model(torch.randn(5, 12, 7), torch.randn(5, 3))
        assert logits.shape == (5,)

    def test_attention_weights_sum_to_one(self):
        attention = AdditiveAttention(hidden_size=8)
        context, weights = attention(torch.randn(4, 9, 8))
        assert context.shape == (4, 8)
        assert weights.shape == (4, 9)
        assert torch.allclose(weights.sum(dim=1), torch.ones(4), atol=1e-5)

    def test_return_attention_matches_sequence_length(self):
        model = FloodSenseLSTM(n_dynamic=4, n_static=2, cfg=ModelConfig(hidden_size=8))
        logits, weights = model(
            torch.randn(3, 15, 4), torch.randn(3, 2), return_attention=True
        )
        assert logits.shape == (3,)
        assert weights.shape == (3, 15)

    def test_without_attention_uses_last_step(self):
        cfg = ModelConfig(hidden_size=8, attention=False)
        model = FloodSenseLSTM(n_dynamic=4, n_static=2, cfg=cfg)
        _, weights = model(
            torch.randn(2, 6, 4), torch.randn(2, 2), return_attention=True
        )
        assert weights[:, -1].tolist() == [1.0, 1.0]

    def test_is_causal_by_default(self):
        """Unidirectional: the architecture cannot read the future."""
        model = FloodSenseLSTM(n_dynamic=3, n_static=1)
        assert model.lstm.bidirectional is False

    def test_missing_static_raises(self):
        model = FloodSenseLSTM(n_dynamic=3, n_static=2, cfg=ModelConfig(hidden_size=8))
        with pytest.raises(ValueError, match="static"):
            model(torch.randn(2, 5, 3), None)

    def test_save_and_load_round_trip(self, tmp_path):
        model = FloodSenseLSTM(
            n_dynamic=5,
            n_static=2,
            cfg=ModelConfig(hidden_size=12, num_layers=1),
            feature_names=[f"f{i}" for i in range(5)],
            static_names=["a", "b"],
        )
        model.eval()
        seq, stat = torch.randn(3, 8, 5), torch.randn(3, 2)
        with torch.no_grad():
            before = model(seq, stat)

        path = tmp_path / "model.pt"
        model.save(path)
        restored = FloodSenseLSTM.load(path)

        with torch.no_grad():
            after = restored(seq, stat)
        assert torch.allclose(before, after, atol=1e-6)
        assert restored.feature_names == [f"f{i}" for i in range(5)]
        assert (tmp_path / "model.meta.json").exists()

    def test_predict_proba_in_range(self):
        model = FloodSenseLSTM(n_dynamic=4, n_static=1, cfg=ModelConfig(hidden_size=8))
        probs = model.predict_proba(torch.randn(10, 6, 4), torch.randn(10, 1))
        assert torch.all((probs >= 0) & (probs <= 1))


class TestLosses:
    def test_focal_downweights_easy_examples(self):
        loss = FocalLossWithLogits(gamma=2.0, alpha=None)
        easy = loss(torch.tensor([6.0]), torch.tensor([1.0]))
        hard = loss(torch.tensor([0.2]), torch.tensor([1.0]))
        assert float(easy) < float(hard)

    def test_focal_gamma_zero_is_plain_bce(self):
        import torch.nn.functional as F

        logits, target = torch.tensor([0.4]), torch.tensor([1.0])
        focal = FocalLossWithLogits(gamma=0.0, alpha=None)(logits, target)
        bce = F.binary_cross_entropy_with_logits(logits, target)
        assert float(focal) == pytest.approx(float(bce), abs=1e-6)

    def test_weighted_bce_penalises_missed_positives_more(self):
        loss = WeightedBCEWithLogits(pos_weight=10.0)
        missed_positive = loss(torch.tensor([-3.0]), torch.tensor([1.0]))
        false_positive = loss(torch.tensor([3.0]), torch.tensor([0.0]))
        assert float(missed_positive) > float(false_positive)

    def test_build_loss_factory(self):
        assert isinstance(
            build_loss("focal", pos_weight=5, gamma=2, alpha=0.25),
            FocalLossWithLogits,
        )
        assert isinstance(
            build_loss("weighted_bce", pos_weight=5, gamma=2, alpha=0.25),
            WeightedBCEWithLogits,
        )
        with pytest.raises(ValueError):
            build_loss("hinge", pos_weight=1, gamma=1, alpha=0.5)

    def test_losses_are_finite_at_extreme_logits(self):
        for loss in (
            FocalLossWithLogits(gamma=2.0, alpha=0.25),
            WeightedBCEWithLogits(pos_weight=100.0),
        ):
            value = loss(
                torch.tensor([-60.0, 60.0]), torch.tensor([1.0, 0.0])
            )
            assert torch.isfinite(value)


class TestMetrics:
    def test_perfect_separation(self):
        y = np.array([0, 0, 1, 1])
        p = np.array([0.01, 0.02, 0.98, 0.99])
        report = compute_report(y, p, threshold=0.5)
        assert report.recall == 1.0
        assert report.precision == 1.0
        assert report.pr_auc == pytest.approx(1.0)
        assert report.roc_auc == pytest.approx(1.0)

    def test_constant_predictor_is_exposed_by_pr_auc(self):
        """The 'always no flood' model: high accuracy, no skill."""
        y = np.zeros(1000, dtype=int)
        y[:2] = 1
        p = np.full(1000, 0.001)
        report = compute_report(y, p, threshold=0.5)

        assert report.accuracy_not_a_headline_metric > 0.99
        assert report.recall == 0.0
        assert report.f1 == 0.0

    def test_threshold_for_recall_reaches_target(self):
        rng = np.random.default_rng(0)
        y = (rng.random(5000) < 0.02).astype(int)
        p = np.clip(0.5 * y + rng.normal(0, 0.25, 5000), 0, 1)

        thr, recall, _ = threshold_for_recall(y, p, 0.9)
        assert recall >= 0.9
        assert compute_report(y, p, thr).recall >= 0.9

    def test_threshold_degrades_gracefully_without_positives(self):
        y = np.zeros(100, dtype=int)
        thr, recall, precision = threshold_for_recall(y, np.random.random(100), 0.95)
        assert (thr, recall, precision) == (0.5, 0.0, 0.0)

    def test_higher_recall_targets_cost_precision(self):
        rng = np.random.default_rng(1)
        y = (rng.random(8000) < 0.02).astype(int)
        p = np.clip(0.4 * y + rng.normal(0, 0.3, 8000), 0, 1)

        table = precision_at_recall_table(y, p, recalls=(0.5, 0.95))
        assert table[0]["precision"] >= table[1]["precision"]
        assert table[0]["threshold"] >= table[1]["threshold"]

    def test_lift_over_base_rate(self):
        report = compute_report(
            np.array([0, 0, 0, 1]), np.array([0.1, 0.1, 0.1, 0.9]), 0.5
        )
        assert lift_over_base_rate(report) == pytest.approx(4.0)

    def test_single_class_yields_nan_aucs_not_a_crash(self):
        report = compute_report(np.zeros(10, dtype=int), np.full(10, 0.3), 0.5)
        assert np.isnan(report.pr_auc)
        assert np.isnan(report.roc_auc)

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            compute_report(np.array([0, 1]), np.array([0.5]), 0.5)


class TestEventLevel:
    def test_runs_finds_contiguous_blocks(self):
        flags = np.array([False, True, True, False, True])
        assert _runs(flags) == [(1, 3), (4, 5)]

    def test_merge_joins_nearby_runs(self):
        assert _merge([(0, 2), (4, 6)], gap=3) == [(0, 6)]
        assert _merge([(0, 2), (10, 12)], gap=3) == [(0, 2), (10, 12)]

    def test_event_caught_when_any_cell_fires(self):
        # One station, one event over steps 10-15, model fires only at 12.
        n_steps, n_stations = 40, 1
        index = np.array([[t, 0] for t in range(n_steps)], dtype=np.int32)
        y = np.zeros(n_steps)
        y[10:16] = 1.0
        p = np.zeros(n_steps)
        p[12] = 0.9

        report = event_level_report(index, y, p, 0.5, n_steps, n_stations)
        assert report.n_events == 1
        assert report.n_detected == 1
        assert report.event_recall == 1.0
        assert report.n_false_alarms == 0

    def test_false_alarm_counted_once_per_episode(self):
        n_steps, n_stations = 60, 1
        index = np.array([[t, 0] for t in range(n_steps)], dtype=np.int32)
        y = np.zeros(n_steps)
        p = np.zeros(n_steps)
        p[20:26] = 0.9                       # one continuous burst

        report = event_level_report(index, y, p, 0.5, n_steps, n_stations)
        assert report.n_events == 0
        assert report.n_false_alarms == 1     # not six

    def test_lead_time_is_within_the_horizon(self):
        n_steps, n_stations = 40, 1
        index = np.array([[t, 0] for t in range(n_steps)], dtype=np.int32)
        y = np.zeros(n_steps)
        y[10:16] = 1.0                       # alert sits at step 22
        p = np.zeros(n_steps)
        p[10] = 0.9                          # earliest possible warning

        report = event_level_report(
            index, y, p, 0.5, n_steps, n_stations, horizon_max_minutes=60
        )
        assert report.mean_lead_minutes == pytest.approx(60.0)

    def test_event_recall_falls_as_threshold_rises(self):
        rng = np.random.default_rng(2)
        n_steps, n_stations = 500, 2
        index = np.array(
            [[t, s] for t in range(n_steps) for s in range(n_stations)],
            dtype=np.int32,
        )
        y = np.zeros((n_steps, n_stations))
        y[100:106, 0] = 1.0
        y[300:306, 1] = 1.0
        p = np.clip(0.6 * y + rng.normal(0, 0.1, y.shape), 0, 1)

        flat_y = y[index[:, 0], index[:, 1]]
        flat_p = p[index[:, 0], index[:, 1]]

        low = event_level_report(index, flat_y, flat_p, 0.2, n_steps, n_stations)
        high = event_level_report(index, flat_y, flat_p, 0.95, n_steps, n_stations)
        assert low.event_recall >= high.event_recall

    def test_threshold_for_event_recall_hits_target(self):
        rng = np.random.default_rng(3)
        n_steps, n_stations = 600, 2
        index = np.array(
            [[t, s] for t in range(n_steps) for s in range(n_stations)],
            dtype=np.int32,
        )
        y = np.zeros((n_steps, n_stations))
        for start, station in ((100, 0), (250, 1), (400, 0)):
            y[start : start + 6, station] = 1.0
        p = np.clip(0.5 * y + rng.normal(0, 0.15, y.shape), 0, 1)

        flat_y = y[index[:, 0], index[:, 1]]
        flat_p = p[index[:, 0], index[:, 1]]

        thr, report = threshold_for_event_recall(
            index, flat_y, flat_p, 1.0, n_steps, n_stations
        )
        assert report.event_recall == 1.0
        assert 0.0 <= thr <= 1.0


class TestLastStepSkip:
    """The skip branch, and that old checkpoints still load."""

    def test_skip_changes_the_parameter_count(self):
        with_skip = FloodSenseLSTM(
            n_dynamic=6, n_static=2,
            cfg=ModelConfig(hidden_size=16, last_step_skip=True, skip_hidden=8),
        )
        without = FloodSenseLSTM(
            n_dynamic=6, n_static=2,
            cfg=ModelConfig(hidden_size=16, last_step_skip=False),
        )
        assert with_skip.n_parameters() > without.n_parameters()
        assert with_skip.skip_mlp is not None
        assert without.skip_mlp is None

    def test_skip_model_forward_shape(self):
        model = FloodSenseLSTM(
            n_dynamic=6, n_static=2,
            cfg=ModelConfig(hidden_size=16, last_step_skip=True, skip_hidden=8),
        )
        assert model(torch.randn(4, 10, 6), torch.randn(4, 2)).shape == (4,)

    def test_skip_reads_the_final_timestep(self):
        """Perturbing only the last step must change the output."""
        torch.manual_seed(0)
        model = FloodSenseLSTM(
            n_dynamic=5, n_static=1,
            cfg=ModelConfig(hidden_size=16, last_step_skip=True, skip_hidden=8),
        ).eval()

        seq = torch.zeros(1, 8, 5)
        stat = torch.zeros(1, 1)
        bumped = seq.clone()
        bumped[0, -1, :] = 5.0

        with torch.no_grad():
            assert not torch.allclose(model(seq, stat), model(bumped, stat))

    def test_checkpoint_without_the_flag_loads_as_disabled(self, tmp_path):
        """Backwards compatibility: defaults must not reshape a saved model."""
        import json

        import torch as _torch

        model = FloodSenseLSTM(
            n_dynamic=4, n_static=1,
            cfg=ModelConfig(hidden_size=8, num_layers=1, last_step_skip=False),
        )
        path = tmp_path / "legacy.pt"
        meta = model.metadata()
        meta["model_config"].pop("last_step_skip")
        meta["model_config"].pop("skip_hidden")
        meta["model_config"]["unknown_future_flag"] = True   # must be ignored
        _torch.save({"state_dict": model.state_dict(), "metadata": meta}, path)

        restored = FloodSenseLSTM.load(path)
        assert restored.skip_mlp is None
        assert restored(torch.randn(2, 6, 4), torch.randn(2, 1)).shape == (2,)
        assert json.dumps(restored.metadata())      # still serialisable


class TestInputNormalisation:
    """Why the default is "none" - encoded as a test, not just a comment."""

    def test_layer_norm_erases_absolute_magnitude(self):
        """A uniformly high step and a uniformly low one collapse together.

        This is the failure mode that makes LayerNorm across the feature
        axis the wrong choice for this problem: the absolute level of
        rainfall is the signal, and LayerNorm removes exactly that.
        """
        torch.manual_seed(0)
        model = FloodSenseLSTM(
            n_dynamic=5, n_static=1,
            cfg=ModelConfig(hidden_size=8, num_layers=1, input_norm="layer"),
        ).eval()

        low = torch.full((1, 6, 5), 0.1)
        high = torch.full((1, 6, 5), 9.0)
        with torch.no_grad():
            assert torch.allclose(
                model(low, torch.zeros(1, 1)),
                model(high, torch.zeros(1, 1)),
                atol=1e-5,
            )

    def test_default_preserves_absolute_magnitude(self):
        torch.manual_seed(0)
        model = FloodSenseLSTM(
            n_dynamic=5, n_static=1, cfg=ModelConfig(hidden_size=8, num_layers=1)
        ).eval()
        assert model.cfg.input_norm == "none"

        low = torch.full((1, 6, 5), 0.1)
        high = torch.full((1, 6, 5), 9.0)
        with torch.no_grad():
            assert not torch.allclose(
                model(low, torch.zeros(1, 1)),
                model(high, torch.zeros(1, 1)),
                atol=1e-3,
            )

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError, match="input_norm"):
            FloodSenseLSTM(
                n_dynamic=3, n_static=1, cfg=ModelConfig(input_norm="batch")
            )

    def test_legacy_checkpoint_keeps_layer_norm(self, tmp_path):
        """An old state_dict carries LayerNorm weights and must still load."""
        import torch as _torch

        model = FloodSenseLSTM(
            n_dynamic=4, n_static=1,
            cfg=ModelConfig(hidden_size=8, num_layers=1, input_norm="layer",
                            last_step_skip=False),
        )
        meta = model.metadata()
        meta["model_config"].pop("input_norm")
        meta["model_config"].pop("last_step_skip")
        meta["model_config"].pop("skip_hidden")
        path = tmp_path / "legacy_norm.pt"
        _torch.save({"state_dict": model.state_dict(), "metadata": meta}, path)

        restored = FloodSenseLSTM.load(path)
        assert isinstance(restored.input_norm, torch.nn.LayerNorm)


class TestAccuracyOperatingPoint:
    """Threshold selection by accuracy, and why it needs care.

    Accuracy is not monotone in the threshold on an imbalanced problem: it
    rises from near zero (flag everything) to 1 - base_rate (flag nothing).
    So a target is met by an interval of thresholds, and which one you
    return decides how many floods you catch.
    """

    def _data(self, n=4000, base_rate=0.01, seed=0):
        rng = np.random.default_rng(seed)
        y = (rng.random(n) < base_rate).astype(np.int8)
        p = np.clip(0.45 * y + rng.normal(0.08, 0.12, n), 0.0, 1.0)
        return y, p

    def test_reaches_the_target(self):
        from floodsense.metrics import threshold_for_accuracy

        y, p = self._data()
        thr, accuracy, _ = threshold_for_accuracy(y, p, 0.90)
        assert accuracy >= 0.90
        report = compute_report(y, p, thr)
        assert report.accuracy_not_a_headline_metric >= 0.90

    def test_returns_the_highest_recall_threshold_meeting_the_target(self):
        """Of the thresholds that satisfy the constraint, pick the kindest.

        A higher threshold also satisfies a reached accuracy target but
        catches fewer events, so returning the lowest is what makes the
        constraint cost as little recall as possible.
        """
        from floodsense.metrics import threshold_for_accuracy

        y, p = self._data()
        thr, accuracy, recall = threshold_for_accuracy(y, p, 0.90)
        higher = compute_report(y, p, min(thr + 0.15, 1.0))
        if higher.accuracy_not_a_headline_metric >= 0.90:
            assert recall >= higher.recall

    def test_trivial_target_is_met_without_flagging_nothing(self):
        from floodsense.metrics import threshold_for_accuracy

        y, p = self._data(base_rate=0.01)
        _, accuracy, recall = threshold_for_accuracy(y, p, 0.50)
        assert accuracy >= 0.50
        assert recall > 0.0          # not the degenerate corner

    def test_unreachable_target_returns_the_best_available(self):
        from floodsense.metrics import threshold_for_accuracy

        y, p = self._data()
        _, accuracy, _ = threshold_for_accuracy(y, p, 1.01)
        assert accuracy < 1.01
        assert accuracy > 0.0

    def test_flag_nothing_is_reachable(self):
        """The base-rate ceiling must be attainable, or the search is wrong."""
        from floodsense.metrics import threshold_for_accuracy

        y, p = self._data(base_rate=0.01)
        ceiling = 1.0 - float(y.mean())
        thr, accuracy, _ = threshold_for_accuracy(y, p, ceiling)
        assert accuracy >= ceiling - 1e-9

    def test_empty_input_is_safe(self):
        from floodsense.metrics import threshold_for_accuracy

        thr, accuracy, recall = threshold_for_accuracy(
            np.zeros(0), np.zeros(0), 0.95
        )
        assert (thr, accuracy, recall) == (0.5, 0.0, 0.0)
