"""End-to-end assembly: raw tables in, tensors and splits out.

The ordering in ``prepare`` is not arbitrary.  Static vulnerability features
include a per-station historical alert rate, which is derived from the
target.  It must therefore be computed from alerts *inside the training
period only*, which means the split boundary has to be known before the
static features are built:

    grid -> dynamic features -> labels -> splits
         -> static features (training-period alerts only)
         -> scaler (training region only) -> datasets

Getting that order wrong is the single easiest way to produce a model that
looks excellent offline and fails in production.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .dataset import (
    Scaler,
    SequenceDataset,
    Splits,
    apply_scaler,
    build_splits,
    fit_scaler,
)
from .features import (
    FeatureMatrix,
    StaticFeatures,
    build_dynamic_features,
    build_static_features,
)
from .grid import RainGrid
from .labels import LabelSet, build_labels


@dataclass
class Prepared:
    """Everything the training script needs."""

    grid: RainGrid
    features: FeatureMatrix
    statics: StaticFeatures
    labels: LabelSet
    splits: Splits
    scaler: Scaler
    dynamic_scaled: np.ndarray
    static_scaled: np.ndarray

    def dataset(self, which: str) -> SequenceDataset:
        index = {
            "train": self.splits.train,
            "val": self.splits.val,
            "test": self.splits.test,
        }[which]
        return SequenceDataset(
            dynamic=self.dynamic_scaled,
            static=self.static_scaled,
            labels=self.labels.labels,
            index=index,
            sequence_steps=self._sequence_steps,
        )

    _sequence_steps: int = 36

    def report(self) -> dict[str, object]:
        return {
            "grid": {
                "steps": self.grid.n_steps,
                "stations": self.grid.n_stations,
                "missing_fraction": round(self.grid.missing_fraction, 5),
                "start": str(self.grid.times[0]),
                "end": str(self.grid.times[-1]),
            },
            "features": {
                "dynamic": self.features.names,
                "static": self.statics.names,
                "warmup_steps": self.features.warmup_steps,
            },
            "labels": self.labels.summary(),
            "splits": self.splits.summary() | self.splits.boundaries_iso,
        }


def prepare(
    readings: pd.DataFrame,
    stations: pd.DataFrame,
    alerts: pd.DataFrame,
    cfg: Config,
    flood_prone_points: pd.DataFrame | None = None,
) -> Prepared:
    """Build grid, features, labels, splits, scaler and scaled tensors."""
    grid = RainGrid.from_long(readings, stations)

    features = build_dynamic_features(grid, cfg.features)
    labels = build_labels(grid, alerts, cfg.labels)
    splits = build_splits(features, labels, cfg)

    # Alerts strictly before the end of the training window only.
    train_cutoff = grid.times[min(splits.train_end_step, grid.n_steps - 1)]
    if len(alerts) > 0:
        ts = pd.to_datetime(alerts["ts_start"])
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize(grid.times.tz)
        else:
            ts = ts.dt.tz_convert(grid.times.tz)
        train_alerts = alerts.loc[(ts < train_cutoff).to_numpy()]
    else:
        train_alerts = alerts

    train_days = max(
        (train_cutoff - grid.times[0]).total_seconds() / 86400.0, 1.0
    )
    statics = build_static_features(
        grid,
        flood_prone_points=flood_prone_points,
        historical_alerts=train_alerts,
        cfg=cfg.features,
        alert_radius_km=cfg.labels.radius_km,
        reference_days=train_days,
    )

    scaler = fit_scaler(features, statics, labels, splits)
    dynamic_scaled, static_scaled = apply_scaler(features, statics, scaler)

    return Prepared(
        grid=grid,
        features=features,
        statics=statics,
        labels=labels,
        splits=splits,
        scaler=scaler,
        dynamic_scaled=dynamic_scaled,
        static_scaled=static_scaled,
        _sequence_steps=cfg.windows.sequence_steps,
    )


def prepare_from_synthetic(cfg: Config, synthetic_cfg=None) -> Prepared:
    """Convenience path used by tests and the offline demo."""
    from .synthetic import SyntheticConfig, generate

    bundle = generate(synthetic_cfg or SyntheticConfig())
    return prepare(
        readings=bundle.readings,
        stations=bundle.stations,
        alerts=bundle.alerts,
        cfg=cfg,
        flood_prone_points=bundle.flood_prone_points,
    )
