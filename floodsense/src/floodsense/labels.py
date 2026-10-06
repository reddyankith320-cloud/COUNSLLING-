"""Label construction: "will this location flood in 30-60 minutes?"

``label[t, s] = 1`` iff some PUB flood alert within ``radius_km`` of station
``s`` *starts* in the half-open interval
``(t + horizon_min, t + horizon_max]``.

Two sample-validity rules keep the target honest:

* An alert already active at ``t`` is excluded.  FloodSense forecasts; it
  does not re-report a flood that is already happening, and leaving those
  rows in would let the model score points on the easiest cases.
* A blackout window after an alert clears is excluded, because whether the
  same location "floods again" there is genuinely ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import LabelConfig
from .grid import RainGrid, pairwise_km
from .schema import STEP_MINUTES

#: Assumed alert duration when PUB has not published ``ts_end`` (the alert
#: is still open, or the field is absent).
DEFAULT_ALERT_MINUTES = 60


@dataclass
class LabelSet:
    """Targets and sample validity on the station x time grid.

    Attributes:
        labels: ``(T, S)`` float32 in {0, 1}.
        valid: ``(T, S)`` bool - usable as a training/eval sample.
        alert_active: ``(T, S)`` bool - an alert was open at this step.
        horizon_steps: the ``(lo, hi)`` step offsets used.
    """

    labels: np.ndarray
    valid: np.ndarray
    alert_active: np.ndarray
    horizon_steps: tuple[int, int]

    @property
    def positive_rate(self) -> float:
        denom = int(self.valid.sum())
        if denom == 0:
            return 0.0
        return float(self.labels[self.valid].mean())

    def summary(self) -> dict[str, float]:
        valid_n = int(self.valid.sum())
        pos_n = int(self.labels[self.valid].sum()) if valid_n else 0
        return {
            "valid_samples": float(valid_n),
            "positive_samples": float(pos_n),
            "positive_rate": self.positive_rate,
            "excluded_samples": float(self.valid.size - valid_n),
            "imbalance_ratio": float((valid_n - pos_n) / pos_n) if pos_n else float("inf"),
        }


def build_labels(
    grid: RainGrid,
    alerts: pd.DataFrame,
    cfg: LabelConfig | None = None,
) -> LabelSet:
    """Build the target matrix for a grid and a set of alerts.

    Args:
        grid: the rainfall grid defining the time/station axes.
        alerts: canonical alerts with ``ts_start``, ``longitude``,
            ``latitude`` and optionally ``ts_end``.
        cfg: horizon, association radius and exclusion settings.
    """
    cfg = cfg or LabelConfig()
    t, s = grid.n_steps, grid.n_stations

    labels = np.zeros((t, s), dtype=np.float32)
    active = np.zeros((t, s), dtype=bool)

    lo = _steps(cfg.horizon_min_minutes)
    hi = _steps(cfg.horizon_max_minutes)
    if hi <= lo:
        raise ValueError("horizon_max_minutes must exceed horizon_min_minutes")

    if len(alerts) > 0:
        frame = alerts.dropna(subset=["ts_start", "longitude", "latitude"]).copy()
    else:
        frame = alerts

    if len(frame) > 0:
        ts_start = pd.to_datetime(frame["ts_start"])
        if ts_start.dt.tz is None:
            ts_start = ts_start.dt.tz_localize(grid.times.tz)
        else:
            ts_start = ts_start.dt.tz_convert(grid.times.tz)

        if "ts_end" in frame.columns:
            ts_end = pd.to_datetime(frame["ts_end"])
            if ts_end.dt.tz is None:
                ts_end = ts_end.dt.tz_localize(grid.times.tz)
            else:
                ts_end = ts_end.dt.tz_convert(grid.times.tz)
        else:
            ts_end = pd.Series(pd.NaT, index=frame.index)
        ts_end = ts_end.fillna(
            ts_start + pd.Timedelta(minutes=DEFAULT_ALERT_MINUTES)
        )

        # Station <-> alert association by great-circle distance.
        near = (
            pairwise_km(
                grid.longitude,
                grid.latitude,
                frame["longitude"].to_numpy(dtype=np.float64),
                frame["latitude"].to_numpy(dtype=np.float64),
            )
            <= cfg.radius_km
        )  # (S, A)

        start_idx = step_index(grid, ts_start)
        end_idx = step_index(grid, ts_end)

        blackout = _steps(cfg.post_alert_blackout_minutes)

        for a in range(len(frame)):
            stations = np.flatnonzero(near[:, a])
            if stations.size == 0:
                continue

            a_idx = int(start_idx[a])
            # label[t] = 1 for a_idx - hi <= t <= a_idx - lo - 1
            w0 = max(a_idx - hi, 0)
            w1 = min(a_idx - lo, t)
            if w1 > w0:
                labels[w0:w1, stations] = 1.0

            e0 = max(a_idx, 0)
            e1 = min(int(end_idx[a]) + blackout, t)
            if e1 > e0:
                active[e0:e1, stations] = True

    valid = np.ones((t, s), dtype=bool)
    if cfg.exclude_active_alerts:
        # A step that is both "alert open" and "another alert incoming" is
        # kept as a positive: the forecast is still the useful output.
        valid &= ~(active & (labels < 0.5))

    return LabelSet(
        labels=labels, valid=valid, alert_active=active, horizon_steps=(lo, hi)
    )


def _steps(minutes: int) -> int:
    return max(int(round(minutes / STEP_MINUTES)), 0)


def step_index(grid: RainGrid, ts: pd.Series) -> np.ndarray:
    """Grid step index for each timestamp, by integer arithmetic.

    Computed from the grid origin and step size rather than with
    ``searchsorted``, which trips over mismatched datetime resolutions
    (pandas refuses a lossless-cast of ns into a us-unit index).
    """
    step_ns = STEP_MINUTES * 60 * 1_000_000_000
    origin_ns = int(grid.times[0].value)
    naive = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    values = naive.to_numpy().astype("datetime64[ns]").astype("int64")
    return (values - origin_ns) // step_ns
