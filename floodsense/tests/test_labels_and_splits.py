"""Labels, splits and scaling - the places leakage hides.

Each test here corresponds to a way the headline metric could be silently
inflated: a label window off by one step, a validation sample whose input
window overlaps training, a scaler fitted on data the model should not have
seen, or a station-level alert rate computed over the whole record.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from floodsense.config import Config, LabelConfig
from floodsense.dataset import (
    SequenceDataset,
    apply_scaler,
    build_splits,
    choose_modes,
    fit_scaler,
    subsample_negatives,
)
from floodsense.features import build_dynamic_features, build_static_features
from floodsense.grid import RainGrid
from floodsense.labels import build_labels
from floodsense.schema import TIMEZONE

from .test_features import make_grid


def make_alerts(steps: list[int], grid: RainGrid, station: int = 0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "alert_id": [f"A{i}" for i in range(len(steps))],
            "ts_start": [grid.times[s] for s in steps],
            "ts_end": [grid.times[min(s + 6, grid.n_steps - 1)] for s in steps],
            "location_name": ["somewhere"] * len(steps),
            "longitude": [grid.longitude[station]] * len(steps),
            "latitude": [grid.latitude[station]] * len(steps),
            "severity": ["Moderate"] * len(steps),
            "urgency": ["Immediate"] * len(steps),
        }
    )


class TestLabels:
    def test_label_window_is_exactly_the_horizon(self):
        grid = make_grid(np.zeros((400, 1), dtype=np.float32))
        alerts = make_alerts([200], grid)
        labels = build_labels(grid, alerts, LabelConfig())

        positives = np.flatnonzero(labels.labels[:, 0] > 0.5)
        # horizon 30-60 min = steps 6-12 before the alert at step 200,
        # i.e. t in [188, 193].
        assert positives.min() == 188
        assert positives.max() == 193
        assert len(positives) == 6

    def test_no_positive_at_or_after_the_alert(self):
        grid = make_grid(np.zeros((400, 1), dtype=np.float32))
        labels = build_labels(grid, make_alerts([200], grid), LabelConfig())
        assert labels.labels[200, 0] == 0.0
        assert labels.labels[199, 0] == 0.0       # inside the 30-min blind zone

    def test_distant_alert_does_not_label_a_station(self):
        grid = make_grid(np.zeros((400, 2), dtype=np.float32), 2)
        alerts = make_alerts([200], grid, station=0)
        alerts.loc[:, ["longitude", "latitude"]] = [103.0, 1.0]   # far away
        labels = build_labels(grid, alerts, LabelConfig(radius_km=2.0))
        assert labels.labels.sum() == 0.0

    def test_active_alert_steps_are_excluded_from_negatives(self):
        grid = make_grid(np.zeros((400, 1), dtype=np.float32))
        labels = build_labels(
            grid, make_alerts([200], grid), LabelConfig(exclude_active_alerts=True)
        )
        assert not labels.valid[200, 0]
        assert labels.valid[150, 0]

    def test_exclusion_can_be_disabled(self):
        grid = make_grid(np.zeros((400, 1), dtype=np.float32))
        labels = build_labels(
            grid, make_alerts([200], grid), LabelConfig(exclude_active_alerts=False)
        )
        assert labels.valid.all()

    def test_empty_alerts_yields_no_positives(self):
        grid = make_grid(np.zeros((400, 1), dtype=np.float32))
        empty = pd.DataFrame(
            columns=["alert_id", "ts_start", "ts_end", "longitude", "latitude"]
        )
        labels = build_labels(grid, empty, LabelConfig())
        assert labels.labels.sum() == 0.0
        assert labels.positive_rate == 0.0

    def test_summary_reports_imbalance(self):
        grid = make_grid(np.zeros((1000, 1), dtype=np.float32))
        labels = build_labels(grid, make_alerts([500], grid), LabelConfig())
        summary = labels.summary()
        assert summary["positive_samples"] == 6.0
        assert summary["imbalance_ratio"] > 100


class TestSplits:
    def _prepared_bits(self, n_steps: int = 2500, n_stations: int = 2):
        rng = np.random.default_rng(0)
        grid = make_grid(
            rng.gamma(1.0, 0.3, (n_steps, n_stations)).astype(np.float32), n_stations
        )
        features = build_dynamic_features(grid)
        # Place alerts proportionally so the fixture also works for the
        # deliberately-too-short record used below.
        steps = [int(n_steps * 0.48), int(n_steps * 0.80)]
        labels = build_labels(grid, make_alerts(steps, grid), LabelConfig())
        return grid, features, labels

    def test_splits_are_chronological_and_disjoint(self):
        grid, features, labels = self._prepared_bits()
        splits = build_splits(features, labels, Config())

        assert splits.train[:, 0].max() < splits.val[:, 0].min()
        assert splits.val[:, 0].max() < splits.test[:, 0].min()

    def test_embargo_separates_window_overlap(self):
        """The gap must exceed sequence length plus label horizon."""
        grid, features, labels = self._prepared_bits()
        cfg = Config()
        splits = build_splits(features, labels, cfg)

        gap = splits.val[:, 0].min() - splits.train[:, 0].max()
        needed = cfg.windows.sequence_steps + labels.horizon_steps[1]
        assert gap >= needed - cfg.windows.sequence_steps
        assert splits.embargo_steps == needed

    def test_samples_start_after_warmup(self):
        grid, features, labels = self._prepared_bits()
        cfg = Config()
        splits = build_splits(features, labels, cfg)
        assert splits.train[:, 0].min() >= features.warmup_steps
        assert splits.train[:, 0].min() >= cfg.windows.sequence_steps - 1

    def test_short_record_raises_a_useful_error(self):
        grid, features, labels = self._prepared_bits(n_steps=100)
        with pytest.raises(ValueError, match="warm-up"):
            build_splits(features, labels, Config())

    def test_negative_subsampling_keeps_every_positive(self):
        index = np.array([[i, 0] for i in range(1000)], dtype=np.int32)
        labels = np.zeros((1000, 1), dtype=np.float32)
        labels[::100, 0] = 1.0

        kept = subsample_negatives(index, labels, keep_rate=0.1, seed=0)
        kept_labels = labels[kept[:, 0], kept[:, 1]]
        assert kept_labels.sum() == labels.sum()
        assert len(kept) < len(index)

    def test_validation_is_not_subsampled(self):
        grid, features, labels = self._prepared_bits()
        cfg = Config()
        cfg.windows.negative_keep_rate = 0.01
        splits = build_splits(features, labels, cfg)
        assert len(splits.train) < splits.n_train_before_subsample
        # Every eligible validation cell survives.
        val_cells = labels.valid[
            splits.val[:, 0].min() : splits.val[:, 0].max() + 1
        ].sum()
        assert len(splits.val) == pytest.approx(val_cells, rel=0.05)


class TestScaler:
    def test_modes_match_channel_semantics(self):
        modes = choose_modes(["rain_5min", "rate_30m", "hour_sin", "acc_1h"])
        assert modes == ["log1p", "signed_log1p", "identity", "log1p"]

    def test_signed_log1p_preserves_sign(self):
        from floodsense.dataset import Scaler

        scaler = Scaler(
            modes=["signed_log1p"],
            mean=np.zeros(1, dtype=np.float32),
            std=np.ones(1, dtype=np.float32),
            static_mean=np.zeros(1, dtype=np.float32),
            static_std=np.ones(1, dtype=np.float32),
        )
        out = scaler.compress(np.array([[-5.0], [5.0]], dtype=np.float32))
        assert out[0, 0] < 0 and out[1, 0] > 0
        assert out[0, 0] == pytest.approx(-out[1, 0])

    def test_scaler_sees_only_the_training_region(self):
        """A huge anomaly after the training cut must not move the scaler."""
        rng = np.random.default_rng(5)
        rain = rng.gamma(1.0, 0.3, (2500, 2)).astype(np.float32)
        grid_a = make_grid(rain, 2)

        rain_b = rain.copy()
        rain_b[2400:, :] += 500.0                 # extreme, far past train_end
        grid_b = make_grid(rain_b, 2)

        cfg = Config()
        out = []
        for grid in (grid_a, grid_b):
            features = build_dynamic_features(grid)
            labels = build_labels(grid, make_alerts([1200], grid), LabelConfig())
            splits = build_splits(features, labels, cfg)
            statics = build_static_features(grid)
            out.append(fit_scaler(features, statics, labels, splits))

        assert np.allclose(out[0].mean, out[1].mean, atol=1e-5)
        assert np.allclose(out[0].std, out[1].std, atol=1e-5)

    def test_scaled_features_are_standardised(self):
        rng = np.random.default_rng(6)
        grid = make_grid(rng.gamma(1.0, 0.3, (2500, 2)).astype(np.float32), 2)
        features = build_dynamic_features(grid)
        labels = build_labels(grid, make_alerts([1200], grid), LabelConfig())
        cfg = Config()
        splits = build_splits(features, labels, cfg)
        statics = build_static_features(grid)
        scaler = fit_scaler(features, statics, labels, splits)
        dynamic, static = apply_scaler(features, statics, scaler)

        region = dynamic[splits.eligible_from : splits.train_end_step]
        assert abs(float(region.mean())) < 0.2
        assert np.isfinite(dynamic).all()
        assert np.isfinite(static).all()


class TestSequenceDataset:
    def test_window_ends_at_the_sample_step(self):
        dynamic = np.arange(100 * 1 * 2, dtype=np.float32).reshape(100, 1, 2)
        static = np.zeros((1, 3), dtype=np.float32)
        labels = np.zeros((100, 1), dtype=np.float32)
        index = np.array([[50, 0]], dtype=np.int32)

        ds = SequenceDataset(dynamic, static, labels, index, sequence_steps=10)
        seq, stat, y = ds[0]

        assert seq.shape == (10, 2)
        assert np.allclose(seq[-1].numpy(), dynamic[50, 0])
        assert np.allclose(seq[0].numpy(), dynamic[41, 0])
        assert stat.shape == (3,)
        assert float(y) == 0.0

    def test_positive_weight_is_capped(self):
        labels = np.zeros((1000, 1), dtype=np.float32)
        labels[0, 0] = 1.0
        index = np.array([[i, 0] for i in range(1000)], dtype=np.int32)
        ds = SequenceDataset(
            np.zeros((1000, 1, 2), dtype=np.float32),
            np.zeros((1, 1), dtype=np.float32),
            labels,
            index,
            sequence_steps=4,
        )
        assert ds.positive_weight(cap=50.0) == 50.0

    def test_positive_weight_without_positives_is_one(self):
        labels = np.zeros((10, 1), dtype=np.float32)
        index = np.array([[i, 0] for i in range(10)], dtype=np.int32)
        ds = SequenceDataset(
            np.zeros((10, 1, 2), dtype=np.float32),
            np.zeros((1, 1), dtype=np.float32),
            labels,
            index,
            sequence_steps=2,
        )
        assert ds.positive_weight() == 1.0
