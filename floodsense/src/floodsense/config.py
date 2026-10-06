"""Configuration objects.

Plain dataclasses, serialisable to/from JSON, so a training run can be
reproduced from the ``config.json`` written next to its checkpoint.  No YAML
dependency: the config travels with the artifact.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class FeatureConfig:
    """Temporal feature windows, in minutes."""

    #: Rolling accumulation windows.  Each becomes one feature channel.
    accumulation_minutes: tuple[int, ...] = (15, 30, 60, 180, 360, 1440, 4320)

    #: Window for "max 5-minute rainfall within", i.e. peak intensity.
    peak_window_minutes: int = 30

    #: Windows over which the rate of change of accumulation is measured.
    rate_windows_minutes: tuple[int, ...] = (15, 30)

    #: Window for the least-squares slope of the raw rainfall series.
    trend_window_minutes: int = 30

    #: A reading at or above this depth counts as "raining" when measuring
    #: the length of the preceding dry spell.
    wet_threshold_mm: float = 0.2

    #: Number of nearest neighbour stations averaged into the spatial
    #: context feature.  0 disables it.
    neighbour_k: int = 3

    #: Windows for the neighbour-station accumulation features.  Two
    #: windows give the model a crude storm-approach signal: a cell already
    #: raining upstream reaches this station in tens of minutes.
    neighbour_window_minutes: tuple[int, ...] = (30, 60)

    #: Include hour-of-day / day-of-year cyclical encodings.
    calendar_features: bool = True

    #: Radii (metres) for "number of flood-prone locations within" static
    #: features.
    flood_prone_radii_m: tuple[float, ...] = (1000.0, 2000.0)


@dataclass
class LabelConfig:
    """How a positive example is defined."""

    #: Prediction horizon.  ``label[t] = 1`` iff a flood alert starts in
    #: ``(t + horizon_min_minutes, t + horizon_max_minutes]``.
    horizon_min_minutes: int = 30
    horizon_max_minutes: int = 60

    #: A station is associated with an alert if the alert is within this
    #: distance of the station.
    radius_km: float = 2.0

    #: Drop samples where an alert is *already* active at time ``t``: the
    #: model is a forecaster, not a nowcaster, and such rows would otherwise
    #: pollute the negative class.
    exclude_active_alerts: bool = True

    #: Also drop samples inside this many minutes *after* an alert clears,
    #: where the label is ambiguous.
    post_alert_blackout_minutes: int = 30


@dataclass
class WindowConfig:
    """Sequence construction."""

    #: LSTM input length in steps (36 steps x 5 min = 3 hours of history).
    sequence_steps: int = 36

    #: Keep every negative with this probability.  Flood intervals are rare;
    #: full negative sampling makes an epoch needlessly large.  Validation
    #: and test splits are *never* subsampled (see dataset.py).
    negative_keep_rate: float = 0.08

    #: Random seed for negative subsampling.
    seed: int = 20260101


@dataclass
class SplitConfig:
    """Chronological split boundaries (ISO dates, SGT).

    Splits are by time, never random: a random split would leak the same
    storm into train and test.
    """

    train_end: str | None = None   # None -> derive from fractions
    val_end: str | None = None
    train_fraction: float = 0.70
    val_fraction: float = 0.15


@dataclass
class ModelConfig:
    hidden_size: int = 96
    num_layers: int = 2
    dropout: float = 0.2
    bidirectional: bool = False     # causal forecasting: keep False
    attention: bool = True          # attention pooling -> temporal explanations
    static_hidden: int = 32
    head_hidden: int = 64

    #: Feed the final timestep's feature vector straight to the head,
    #: alongside the pooled recurrent state.  The engineered channels
    #: (accumulations, intensity, rate of increase) are already strong
    #: predictors *at time t*; without this the recurrence has to
    #: reconstruct them through its hidden state, which wastes capacity and
    #: positives.  The LSTM then models what it is actually for - how the
    #: sequence got here - rather than re-deriving the present.
    last_step_skip: bool = True
    skip_hidden: int = 48

    #: Input normalisation: ``"none"`` or ``"layer"``.
    #:
    #: Default is "none", and that is a deliberate correction. LayerNorm here
    #: normalises across the *feature* axis within each timestep, so it
    #: subtracts that timestep's cross-channel mean - which is precisely the
    #: absolute rainfall magnitude the flood signal lives in. "Every
    #: accumulation window is high" and "every one is low" normalise to the
    #: same vector. The Scaler has already standardised each channel on the
    #: training split, so no further input normalisation is needed.
    input_norm: str = "none"


@dataclass
class TrainConfig:
    epochs: int = 30
    batch_size: int = 512
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    grad_clip: float = 1.0

    #: "weighted_bce" or "focal".
    loss: str = "focal"
    focal_gamma: float = 2.0
    focal_alpha: float = 0.25

    #: Cap on the positive-class weight for weighted BCE.
    max_pos_weight: float = 50.0

    #: Early stopping on validation PR-AUC.
    patience: int = 6
    min_delta: float = 1e-4

    num_workers: int = 0
    seed: int = 20260101
    device: str = "auto"            # "auto" | "cpu" | "cuda"

    #: Log to MLflow when the package is importable.  Silently skipped
    #: otherwise, so the same script runs locally and on Databricks.
    use_mlflow: bool = True
    mlflow_experiment: str = "/Shared/floodsense"


@dataclass
class RiskConfig:
    """Flood Risk Score (0-100).

    PROJECT-DEFINED decision-support score.  It is NOT an official Singapore
    government flood rating, and the weights below are an initial proposal
    that has not been validated against outcomes.
    """

    weight_probability: float = 0.60
    weight_intensity: float = 0.15
    weight_accumulation: float = 0.15
    weight_vulnerability: float = 0.10

    #: Normalisation references for the non-probability components.  These
    #: are percentiles computed from the training split at fit time, not
    #: fixed thresholds - see risk.RiskScorer.fit.
    intensity_reference_percentile: float = 99.0
    accumulation_reference_percentile: float = 99.0

    #: Band edges, inclusive upper bound: Low 0-30, Moderate 31-60,
    #: High 61-80, Critical 81-100.
    band_edges: tuple[int, int, int] = (30, 60, 80)

    #: A recent nearby alert adds this many points, capped at 100.
    recent_alert_bonus: float = 10.0
    recent_alert_window_minutes: int = 60


#: Nested config sections, by field name.  Declared explicitly because
#: postponed annotations make ``field.type`` a string (see from_dict).
SECTIONS: dict[str, type] = {
    "features": FeatureConfig,
    "labels": LabelConfig,
    "windows": WindowConfig,
    "splits": SplitConfig,
    "model": ModelConfig,
    "train": TrainConfig,
    "risk": RiskConfig,
}


@dataclass
class Config:
    features: FeatureConfig = field(default_factory=FeatureConfig)
    labels: LabelConfig = field(default_factory=LabelConfig)
    windows: WindowConfig = field(default_factory=WindowConfig)
    splits: SplitConfig = field(default_factory=SplitConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    #: Operating point: pick the decision threshold that reaches at least
    #: this recall on the validation split.  Missing a flood costs far more
    #: than a false alarm, so recall - not accuracy - sets the operating
    #: point.  See metrics.threshold_for_recall.
    target_recall: float = 0.95

    def to_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))

    @classmethod
    def from_json(cls, path: str | Path) -> "Config":
        return cls.from_dict(json.loads(Path(path).read_text()))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Rebuild a Config, restoring the nested dataclasses.

        The section types are looked up in ``SECTIONS`` rather than read off
        the field annotations: this module uses postponed annotation
        evaluation, so ``field.type`` is the *string* ``"ModelConfig"``, and
        any check against it silently fails - leaving ``cfg.model`` as a
        plain dict that only breaks later, at the first attribute access
        inside the inference service.
        """
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for name, value in data.items():
            if name in SECTIONS and isinstance(value, dict):
                kwargs[name] = _build(SECTIONS[name], value)
            elif name in known:
                kwargs[name] = value
        return cls(**kwargs)


def _build(cls: type, data: dict[str, Any]) -> Any:
    """Instantiate a dataclass from a dict, restoring tuple fields."""
    names = {f.name: f for f in fields(cls)}
    kwargs = {}
    for key, value in data.items():
        if key not in names:
            continue
        if isinstance(value, list):
            value = tuple(value)
        kwargs[key] = value
    return cls(**kwargs)
