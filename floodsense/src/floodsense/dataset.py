"""Sequence windowing, chronological splits and scaling.

Three things in here matter more than the model architecture:

**Windows are views, not copies.**  A sample is identified by ``(t, s)``;
``__getitem__`` slices ``features[t-L+1 : t+1, s, :]``.  Materialising every
window would multiply the feature tensor by the sequence length.

**Splits are chronological with an embargo.**  A random split would put the
same storm in train and test.  Even a clean date cut leaks: a sample at the
last training step shares input steps with the first validation sample, and
its label looks up to an hour ahead.  So the splits are separated by an
embargo of ``sequence_steps + horizon_steps``.

**The scaler is fitted on the training region only**, and heavy-tailed
rainfall channels are log-compressed before standardisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
from torch.utils.data import Dataset

from .config import Config
from .features import FeatureMatrix, StaticFeatures
from .labels import LabelSet

#: Channel-name prefixes that are non-negative and heavy-tailed.
_LOG1P_PREFIXES = (
    "rain_", "acc_", "peak_", "intensity_", "mean_intensity_", "nbr_",
)
#: Channel-name prefixes that are signed and heavy-tailed.
_SIGNED_LOG1P_PREFIXES = ("rate_", "trend_slope_")


@dataclass
class Scaler:
    """Per-channel compression then standardisation.

    Attributes:
        modes: one of ``"log1p"``, ``"signed_log1p"``, ``"identity"`` per
            dynamic channel.
        mean / std: dynamic channel statistics, post-compression.
        static_mean / static_std: static feature statistics.
    """

    modes: list[str]
    mean: np.ndarray
    std: np.ndarray
    static_mean: np.ndarray
    static_std: np.ndarray

    def to_dict(self) -> dict:
        return {
            "modes": self.modes,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "static_mean": self.static_mean.tolist(),
            "static_std": self.static_std.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Scaler":
        return cls(
            modes=list(data["modes"]),
            mean=np.asarray(data["mean"], dtype=np.float32),
            std=np.asarray(data["std"], dtype=np.float32),
            static_mean=np.asarray(data["static_mean"], dtype=np.float32),
            static_std=np.asarray(data["static_std"], dtype=np.float32),
        )

    def compress(self, values: np.ndarray) -> np.ndarray:
        """Apply the per-channel compression to a ``(..., F)`` array."""
        out = values.astype(np.float32, copy=True)
        for i, mode in enumerate(self.modes):
            if mode == "log1p":
                np.log1p(np.clip(out[..., i], 0.0, None), out=out[..., i])
            elif mode == "signed_log1p":
                col = out[..., i]
                out[..., i] = np.sign(col) * np.log1p(np.abs(col))
        return out

    def transform_dynamic(self, values: np.ndarray) -> np.ndarray:
        return (self.compress(values) - self.mean) / self.std

    def transform_static(self, values: np.ndarray) -> np.ndarray:
        return (values.astype(np.float32) - self.static_mean) / self.static_std


def choose_modes(names: list[str]) -> list[str]:
    modes = []
    for name in names:
        if name.startswith(_SIGNED_LOG1P_PREFIXES):
            modes.append("signed_log1p")
        elif name.startswith(_LOG1P_PREFIXES):
            modes.append("log1p")
        else:
            modes.append("identity")
    return modes


@dataclass
class Splits:
    """Sample indices per split, plus the step boundaries that produced them."""

    train: np.ndarray            # (N, 2) int32 of (t, s)
    val: np.ndarray
    test: np.ndarray
    train_end_step: int
    val_end_step: int
    embargo_steps: int
    eligible_from: int
    n_train_before_subsample: int = 0
    boundaries_iso: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, float]:
        def rate(idx: np.ndarray, labels: np.ndarray) -> float:
            if len(idx) == 0:
                return 0.0
            return float(labels[idx[:, 0], idx[:, 1]].mean())

        return {
            "train_samples": float(len(self.train)),
            "val_samples": float(len(self.val)),
            "test_samples": float(len(self.test)),
            "train_before_subsample": float(self.n_train_before_subsample),
            "embargo_steps": float(self.embargo_steps),
        }


def build_splits(
    features: FeatureMatrix,
    labels: LabelSet,
    cfg: Config,
) -> Splits:
    """Assemble chronologically separated train/val/test sample indices."""
    n_t = features.values.shape[0]
    seq = cfg.windows.sequence_steps
    horizon = labels.horizon_steps[1]
    embargo = seq + horizon

    eligible_from = max(features.warmup_steps, seq - 1)
    if eligible_from >= n_t:
        raise ValueError(
            f"warm-up ({eligible_from} steps) exceeds the record ({n_t} steps); "
            "generate or load a longer period"
        )

    if cfg.splits.train_end is not None and cfg.splits.val_end is not None:
        train_end = int(features.times.searchsorted(cfg.splits.train_end))
        val_end = int(features.times.searchsorted(cfg.splits.val_end))
    else:
        usable = n_t - eligible_from
        train_end = eligible_from + int(usable * cfg.splits.train_fraction)
        val_end = train_end + int(usable * cfg.splits.val_fraction)

    train_end = int(np.clip(train_end, eligible_from + 1, n_t))
    val_end = int(np.clip(val_end, train_end + 1, n_t))

    valid = labels.valid.copy()
    valid[:eligible_from] = False

    def pairs(lo: int, hi: int) -> np.ndarray:
        lo = max(lo, eligible_from)
        if hi <= lo:
            return np.zeros((0, 2), dtype=np.int32)
        mask = valid[lo:hi]
        t_idx, s_idx = np.nonzero(mask)
        return np.stack([t_idx.astype(np.int32) + lo, s_idx.astype(np.int32)], axis=1)

    train_idx = pairs(eligible_from, train_end)
    val_idx = pairs(train_end + embargo, val_end)
    test_idx = pairs(val_end + embargo, n_t)

    n_before = len(train_idx)
    if 0.0 < cfg.windows.negative_keep_rate < 1.0 and len(train_idx):
        train_idx = subsample_negatives(
            train_idx,
            labels.labels,
            keep_rate=cfg.windows.negative_keep_rate,
            seed=cfg.windows.seed,
        )

    return Splits(
        train=train_idx,
        val=val_idx,
        test=test_idx,
        train_end_step=train_end,
        val_end_step=val_end,
        embargo_steps=embargo,
        eligible_from=eligible_from,
        n_train_before_subsample=n_before,
        boundaries_iso={
            "data_start": str(features.times[0]),
            "train_end": str(features.times[min(train_end, n_t - 1)]),
            "val_end": str(features.times[min(val_end, n_t - 1)]),
            "data_end": str(features.times[-1]),
        },
    )


def subsample_negatives(
    index: np.ndarray, labels: np.ndarray, keep_rate: float, seed: int
) -> np.ndarray:
    """Keep every positive and a random share of the negatives.

    Applied to the training split only.  Validation and test keep every
    eligible sample, so reported precision reflects the true base rate.
    """
    y = labels[index[:, 0], index[:, 1]]
    pos = index[y > 0.5]
    neg = index[y <= 0.5]
    rng = np.random.default_rng(seed)
    keep = rng.random(len(neg)) < keep_rate
    out = np.concatenate([pos, neg[keep]], axis=0)
    order = rng.permutation(len(out))
    return out[order]


def fit_scaler(
    features: FeatureMatrix,
    statics: StaticFeatures,
    labels: LabelSet,
    splits: Splits,
) -> Scaler:
    """Fit compression + standardisation on the training region only."""
    modes = choose_modes(features.names)
    lo, hi = splits.eligible_from, splits.train_end_step
    region = features.values[lo:hi]
    mask = labels.valid[lo:hi]

    flat = region[mask]                       # (N, F)
    if len(flat) == 0:
        raise ValueError("no valid training steps to fit the scaler on")

    scaler_shell = Scaler(
        modes=modes,
        mean=np.zeros(len(modes), dtype=np.float32),
        std=np.ones(len(modes), dtype=np.float32),
        static_mean=np.zeros(statics.values.shape[1], dtype=np.float32),
        static_std=np.ones(statics.values.shape[1], dtype=np.float32),
    )
    compressed = scaler_shell.compress(flat)
    mean = compressed.mean(axis=0).astype(np.float32)
    std = compressed.std(axis=0).astype(np.float32)
    std[std < 1e-6] = 1.0

    s_mean = statics.values.mean(axis=0).astype(np.float32)
    s_std = statics.values.std(axis=0).astype(np.float32)
    s_std[s_std < 1e-6] = 1.0

    return Scaler(
        modes=modes,
        mean=mean,
        std=std,
        static_mean=s_mean,
        static_std=s_std,
    )


def apply_scaler(
    features: FeatureMatrix, statics: StaticFeatures, scaler: Scaler
) -> tuple[np.ndarray, np.ndarray]:
    """Return scaled copies of the dynamic and static tensors.

    Done once for the whole tensor so that ``__getitem__`` is a pure slice.
    """
    dynamic = scaler.transform_dynamic(features.values).astype(np.float32)
    static = scaler.transform_static(statics.values).astype(np.float32)
    return np.ascontiguousarray(dynamic), np.ascontiguousarray(static)


class SequenceDataset(Dataset):
    """``(sequence, static, label)`` samples addressed by ``(t, s)`` pairs."""

    def __init__(
        self,
        dynamic: np.ndarray,
        static: np.ndarray,
        labels: np.ndarray,
        index: np.ndarray,
        sequence_steps: int,
    ) -> None:
        self.dynamic = dynamic
        self.static = static
        self.labels = labels
        self.index = index
        self.sequence_steps = int(sequence_steps)

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, i: int):
        t, s = int(self.index[i, 0]), int(self.index[i, 1])
        lo = t - self.sequence_steps + 1
        seq = self.dynamic[lo : t + 1, s, :]
        return (
            torch.from_numpy(np.ascontiguousarray(seq)),
            torch.from_numpy(self.static[s]),
            torch.tensor(self.labels[t, s], dtype=torch.float32),
        )

    def label_vector(self) -> np.ndarray:
        return self.labels[self.index[:, 0], self.index[:, 1]].astype(np.float32)

    def positive_weight(self, cap: float = 50.0) -> float:
        """``n_negative / n_positive``, capped - for weighted BCE."""
        y = self.label_vector()
        pos = float(y.sum())
        if pos == 0:
            return 1.0
        return float(min((len(y) - pos) / pos, cap))
