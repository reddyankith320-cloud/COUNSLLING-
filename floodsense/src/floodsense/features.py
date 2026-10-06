"""Temporal and spatial feature engineering.

A flash flood is not a function of "rainfall now".  It is a function of how
much water has already fallen, how fast it is falling, whether the rate is
rising, how wet the ground already was, and how vulnerable the location is.
This module turns the raw 5-minute grid into those quantities.

All rolling operators are implemented with cumulative sums or fixed-width
shifts, so cost is O(T x S) per feature and independent of window length.
Every feature at step ``t`` uses only data at or before ``t`` - there is no
look-ahead anywhere in this file, which is what makes the training labels
honest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import FeatureConfig
from .grid import RainGrid, pairwise_km
from .schema import STEP_MINUTES

_EPS = 1e-6


@dataclass
class FeatureMatrix:
    """Dynamic features on the station x time grid.

    Attributes:
        values: ``(T, S, F)`` float32.
        names: ``F`` feature names, in column order.
        warmup_steps: number of leading steps whose longest rolling window
            is incomplete.  Samples before this index must be dropped.
        times: the grid's time index.
        station_ids: the grid's station order.
    """

    values: np.ndarray
    names: list[str]
    warmup_steps: int
    times: pd.DatetimeIndex
    station_ids: np.ndarray

    @property
    def n_features(self) -> int:
        return self.values.shape[2]

    def index_of(self, name: str) -> int:
        return self.names.index(name)

    def channel(self, name: str) -> np.ndarray:
        """``(T, S)`` view of one named feature."""
        return self.values[:, :, self.index_of(name)]


@dataclass
class StaticFeatures:
    """Per-station features that do not change with time.

    Attributes:
        values: ``(S, G)`` float32.
        names: ``G`` feature names.
        station_ids: station order, matching the grid.
    """

    values: np.ndarray
    names: list[str]
    station_ids: np.ndarray

    def index_of(self, name: str) -> int:
        return self.names.index(name)


# --------------------------------------------------------------------------
# Rolling primitives
# --------------------------------------------------------------------------


def rolling_sum(x: np.ndarray, window: int) -> np.ndarray:
    """Sum over the ``window`` steps ending at (and including) each step.

    Leading positions use whatever history exists (a partial window).  Those
    steps are excluded from training via ``FeatureMatrix.warmup_steps``.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    if window == 1:
        return x.astype(np.float32, copy=True)
    cs = np.cumsum(x, axis=0, dtype=np.float64)
    out = cs.copy()
    out[window:] = cs[window:] - cs[:-window]
    return out.astype(np.float32)


def rolling_max(x: np.ndarray, window: int) -> np.ndarray:
    """Maximum over the ``window`` steps ending at each step."""
    if window < 1:
        raise ValueError("window must be >= 1")
    out = x.astype(np.float32, copy=True)
    for shift in range(1, window):
        shifted = np.empty_like(out)
        shifted[:shift] = x[0] if x.ndim == 1 else x[:1]
        shifted[shift:] = x[:-shift]
        np.maximum(out, shifted, out=out)
    return out


def shift_down(x: np.ndarray, steps: int) -> np.ndarray:
    """Shift forward in time by ``steps``; the head repeats the first row."""
    if steps <= 0:
        return x.astype(np.float32, copy=True)
    out = np.empty_like(x, dtype=np.float32)
    out[:steps] = x[:1]
    out[steps:] = x[:-steps]
    return out


def linear_filter(x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Causal FIR filter: ``out[t] = sum_k weights[k] * x[t - (W-1) + k]``.

    ``weights[-1]`` multiplies the current step.  Used for the least-squares
    trend slope, which is a fixed linear functional of the window.
    """
    w = len(weights)
    out = np.zeros_like(x, dtype=np.float32)
    for k, coef in enumerate(weights):
        if coef == 0.0:
            continue
        out += coef * shift_down(x, w - 1 - k)
    return out


def trend_slope(x: np.ndarray, window: int) -> np.ndarray:
    """Ordinary-least-squares slope of ``x`` over the trailing ``window``.

    Units: mm per step.  Positive means rainfall is intensifying.  For a
    fixed window the slope is a constant linear filter, so one pass of
    ``linear_filter`` is exact.
    """
    if window < 2:
        raise ValueError("trend window must be >= 2")
    k = np.arange(window, dtype=np.float64)
    centred = k - k.mean()
    denom = float((centred**2).sum())
    return linear_filter(x, (centred / denom).astype(np.float32))


def ewm(x: np.ndarray, halflife_steps: float) -> np.ndarray:
    """Causal exponentially weighted mean along the time axis.

    ``y[t] = a * x[t] + (1 - a) * y[t-1]`` with ``a = 1 - 0.5 ** (1 /
    halflife)``.  This is a leaky integrator, which is the natural form for
    antecedent wetness: rainfall charges the state and drainage discharges
    it at a roughly constant fractional rate.

    Implemented with ``scipy.signal.lfilter`` so the recursion runs in C
    rather than as a Python loop over 100k+ timesteps; the pure-numpy
    fallback is used only if scipy is unavailable.
    """
    if halflife_steps <= 0:
        raise ValueError("halflife_steps must be positive")
    alpha = 1.0 - 0.5 ** (1.0 / halflife_steps)

    try:
        from scipy.signal import lfilter

        out = lfilter([alpha], [1.0, -(1.0 - alpha)], x, axis=0)
        return np.ascontiguousarray(out, dtype=np.float32)
    except ImportError:
        out = np.empty_like(x, dtype=np.float32)
        state = np.zeros(x.shape[1:], dtype=np.float64)
        for t in range(x.shape[0]):
            state = alpha * x[t] + (1.0 - alpha) * state
            out[t] = state
        return out


def rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    """Standard deviation over the trailing ``window`` steps.

    From the cumulative sums of ``x`` and ``x**2``, so it costs two passes
    regardless of window length.  The variance is clipped at zero because
    the sum-of-squares identity can go slightly negative on cancellation.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    mean = rolling_sum(x, window) / window
    mean_sq = rolling_sum(np.square(x.astype(np.float64)), window) / window
    return np.sqrt(np.clip(mean_sq - np.square(mean), 0.0, None)).astype(np.float32)


def steps_since(condition: np.ndarray, cap: int) -> np.ndarray:
    """Steps elapsed since ``condition`` was last true, per column.

    ``cap`` bounds the result so a station that has never satisfied the
    condition does not produce an unbounded value.
    """
    t = condition.shape[0]
    idx = np.arange(t, dtype=np.int64)[:, None]
    last = np.where(condition, idx, -1)
    np.maximum.accumulate(last, axis=0, out=last)
    out = np.where(last >= 0, idx - last, cap)
    return np.minimum(out, cap).astype(np.float32)


# --------------------------------------------------------------------------
# Dynamic features
# --------------------------------------------------------------------------


def _minutes_to_steps(minutes: int, step_minutes: int = STEP_MINUTES) -> int:
    steps = int(round(minutes / step_minutes))
    return max(steps, 1)


def _label(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def build_dynamic_features(
    grid: RainGrid, cfg: FeatureConfig | None = None
) -> FeatureMatrix:
    """Compute the ``(T, S, F)`` dynamic feature tensor.

    The channels, in order:

    ==========================  =======================================
    channel                     meaning
    ==========================  =======================================
    ``rain_5min``               depth in the current interval (mm)
    ``acc_<w>``                 trailing accumulation per window (mm)
    ``intensity_mm_hr``         current rate (mm/h)
    ``peak_5min_<w>``           heaviest single interval in the window
    ``mean_intensity_<w>``      window accumulation as a rate (mm/h)
    ``rate_<w>``                change in that accumulation vs one window
                                ago (mm) - the "is it accelerating" signal
    ``trend_slope_<w>``         OLS slope of rainfall (mm/step)
    ``dry_spell_log``           log1p(steps since it last rained)
    ``wet_ratio_24h_72h``       recent share of multi-day wetness
    ``observed``                1 if this interval was reported
    ``gap_log``                 log1p(length of the current reporting gap)
    ``nbr_acc_<w>``             mean accumulation at the k nearest stations
    ``nbr_max_acc_<w>``         worst accumulation among those neighbours
    ``hour_sin`` / ``hour_cos`` diurnal cycle (convective afternoon peak)
    ``doy_sin`` / ``doy_cos``   seasonal cycle (monsoon surges)
    ==========================  =======================================
    """
    cfg = cfg or FeatureConfig()
    rain = grid.filled(0.0)
    observed = grid.observed_mask()
    t, s = rain.shape

    channels: list[np.ndarray] = []
    names: list[str] = []

    def add(name: str, arr: np.ndarray) -> None:
        channels.append(np.ascontiguousarray(arr, dtype=np.float32))
        names.append(name)

    add("rain_5min", rain)

    acc: dict[int, np.ndarray] = {}
    for minutes in cfg.accumulation_minutes:
        steps = _minutes_to_steps(minutes)
        acc[minutes] = rolling_sum(rain, steps)
        add(f"acc_{_label(minutes)}", acc[minutes])

    add("intensity_mm_hr", rain * (60.0 / STEP_MINUTES))

    peak_steps = _minutes_to_steps(cfg.peak_window_minutes)
    add(f"peak_5min_{_label(cfg.peak_window_minutes)}", rolling_max(rain, peak_steps))

    for minutes in cfg.rolling_stat_windows_minutes:
        steps = _minutes_to_steps(minutes)
        if minutes not in acc:
            acc[minutes] = rolling_sum(rain, steps)
        add(f"roll_mean_{_label(minutes)}", acc[minutes] / steps)
        add(f"roll_max_{_label(minutes)}", rolling_max(rain, steps))
        if steps >= 2:
            # Separates a steady soak from burst-and-pause of equal depth.
            add(f"roll_std_{_label(minutes)}", rolling_std(rain, steps))

    for minutes in (cfg.peak_window_minutes, 60):
        if minutes in acc:
            add(
                f"mean_intensity_{_label(minutes)}",
                acc[minutes] * (60.0 / minutes),
            )

    for minutes in cfg.rate_windows_minutes:
        if minutes not in acc:
            acc[minutes] = rolling_sum(rain, _minutes_to_steps(minutes))
        steps = _minutes_to_steps(minutes)
        add(f"rate_{_label(minutes)}", acc[minutes] - shift_down(acc[minutes], steps))

    for minutes in cfg.acceleration_windows_minutes:
        if minutes not in acc:
            acc[minutes] = rolling_sum(rain, _minutes_to_steps(minutes))
        steps = _minutes_to_steps(minutes)
        series = acc[minutes]
        # Second difference: is the rate of accumulation itself rising?
        add(
            f"accel_{_label(minutes)}",
            series - 2.0 * shift_down(series, steps) + shift_down(series, 2 * steps),
        )

    for minutes in cfg.percent_change_windows_minutes:
        if minutes not in acc:
            acc[minutes] = rolling_sum(rain, _minutes_to_steps(minutes))
        steps = _minutes_to_steps(minutes)
        series = acc[minutes]
        previous = shift_down(series, steps)
        # Scale-free: distinguishes 1 mm -> 2 mm from 40 mm -> 41 mm.
        add(
            f"pct_change_{_label(minutes)}",
            (series - previous) / (previous + 1.0),
        )

    for minutes in cfg.lag_minutes:
        add(f"lag_rain_{_label(minutes)}", shift_down(rain, _minutes_to_steps(minutes)))

    trend_steps = _minutes_to_steps(cfg.trend_window_minutes)
    add(
        f"trend_slope_{_label(cfg.trend_window_minutes)}",
        trend_slope(rain, max(trend_steps, 2)),
    )

    day_steps = _minutes_to_steps(1440)
    dry = steps_since(rain >= cfg.wet_threshold_mm, cap=day_steps)
    add("dry_spell_log", np.log1p(dry))

    if 1440 in acc and 4320 in acc:
        add("wet_ratio_24h_72h", acc[1440] / (acc[4320] + _EPS))

    # Antecedent wetness as a leaky integrator - see FeatureConfig.
    for minutes in cfg.ewm_halflife_minutes:
        add(
            f"ewm_{_label(minutes)}",
            ewm(rain, float(_minutes_to_steps(minutes))),
        )

    add("observed", observed)
    gap = steps_since(observed > 0.5, cap=day_steps)
    add("gap_log", np.log1p(gap))

    if cfg.neighbour_k > 0 and s > 1:
        neighbours = nearest_neighbours(grid, k=min(cfg.neighbour_k, s - 1))
        windows = cfg.neighbour_window_minutes
        if isinstance(windows, int):
            windows = (windows,)
        for nbr_minutes in windows:
            if nbr_minutes not in acc:
                acc[nbr_minutes] = rolling_sum(rain, _minutes_to_steps(nbr_minutes))
            gathered = acc[nbr_minutes][:, neighbours]       # (T, S, k)
            neighbour_mean = gathered.mean(axis=2)
            add(f"nbr_acc_{_label(nbr_minutes)}", neighbour_mean)
            add(f"nbr_max_acc_{_label(nbr_minutes)}", gathered.max(axis=2))
            if cfg.spatial_gradient:
                # Positive = the cell is centred here rather than district-wide.
                add(
                    f"gradient_{_label(nbr_minutes)}",
                    acc[nbr_minutes] - neighbour_mean,
                )

    if cfg.calendar_features:
        minute_of_day = (
            grid.times.hour.to_numpy() * 60 + grid.times.minute.to_numpy()
        ).astype(np.float32)
        day_of_year = grid.times.dayofyear.to_numpy().astype(np.float32)
        two_pi = 2.0 * np.pi
        channels_1d: list[tuple[str, np.ndarray]] = [
            ("hour_sin", np.sin(two_pi * minute_of_day / 1440.0)),
            ("hour_cos", np.cos(two_pi * minute_of_day / 1440.0)),
            ("doy_sin", np.sin(two_pi * day_of_year / 365.25)),
            ("doy_cos", np.cos(two_pi * day_of_year / 365.25)),
        ]

        if cfg.seasonal_features:
            weekday = grid.times.dayofweek.to_numpy().astype(np.float32)
            month = grid.times.month.to_numpy()
            channels_1d += [
                ("dow_sin", np.sin(two_pi * weekday / 7.0)),
                ("dow_cos", np.cos(two_pi * weekday / 7.0)),
                # Singapore's two monsoon seasons, as indicators alongside
                # the smooth day-of-year encoding: the transition into a
                # monsoon surge is abrupt, and a sinusoid cannot represent
                # a step.
                ("monsoon_ne", np.isin(month, (12, 1, 2, 3)).astype(np.float32)),
                ("monsoon_sw", np.isin(month, (6, 7, 8, 9)).astype(np.float32)),
            ]

        for name, arr in channels_1d:
            add(name, np.repeat(np.asarray(arr, dtype=np.float32)[:, None], s, axis=1))

    values = np.stack(channels, axis=2).astype(np.float32)
    # The longest fixed window, but also enough burn-in for the slowest
    # exponential state: an EWM initialised at zero reads low until a few
    # half-lives have passed, and training on that bias would teach the
    # model that every record starts dry.
    warmup = max(
        (_minutes_to_steps(m) for m in cfg.accumulation_minutes), default=1
    )
    if cfg.ewm_halflife_minutes:
        warmup = max(
            warmup, 3 * max(_minutes_to_steps(m) for m in cfg.ewm_halflife_minutes)
        )
    return FeatureMatrix(
        values=values,
        names=names,
        warmup_steps=int(warmup),
        times=grid.times,
        station_ids=grid.station_ids,
    )


def nearest_neighbours(grid: RainGrid, k: int) -> np.ndarray:
    """``(S, k)`` indices of the k nearest *other* stations."""
    d = pairwise_km(grid.longitude, grid.latitude, grid.longitude, grid.latitude)
    np.fill_diagonal(d, np.inf)
    return np.argsort(d, axis=1)[:, :k]


# --------------------------------------------------------------------------
# Static features
# --------------------------------------------------------------------------


def build_static_features(
    grid: RainGrid,
    flood_prone_points: pd.DataFrame | None = None,
    historical_alerts: pd.DataFrame | None = None,
    cfg: FeatureConfig | None = None,
    *,
    alert_radius_km: float = 2.0,
    reference_days: float | None = None,
) -> StaticFeatures:
    """Per-station vulnerability features.

    Args:
        grid: supplies station coordinates.
        flood_prone_points: geocoded PUB flood-prone locations
            (``longitude``, ``latitude``).  Optional.
        historical_alerts: past PUB flood alerts used to derive a per-station
            alert rate.  **Pass only alerts from the training period** - this
            feature is a target-derived statistic and leaks the label if
            computed over the whole record.
        reference_days: span of ``historical_alerts`` in days, used to turn
            counts into a rate.  Derived from the alerts when omitted.

    Returns:
        ``StaticFeatures`` with channels ``lon_norm``, ``lat_norm``,
        ``alerts_per_year``, ``alert_count_log``, ``dist_floodprone_km``,
        ``floodprone_within_<r>m``.
    """
    cfg = cfg or FeatureConfig()
    s = grid.n_stations
    cols: list[np.ndarray] = []
    names: list[str] = []

    def add(name: str, arr: np.ndarray) -> None:
        cols.append(np.asarray(arr, dtype=np.float32).reshape(s))
        names.append(name)

    # Centred coordinates: lets the model learn a smooth spatial prior
    # without memorising absolute positions.
    add("lon_norm", (grid.longitude - grid.longitude.mean()) * 10.0)
    add("lat_norm", (grid.latitude - grid.latitude.mean()) * 10.0)

    if historical_alerts is not None and len(historical_alerts) > 0:
        alerts = historical_alerts.dropna(subset=["longitude", "latitude"])
        d = pairwise_km(
            grid.longitude,
            grid.latitude,
            alerts["longitude"].to_numpy(dtype=np.float64),
            alerts["latitude"].to_numpy(dtype=np.float64),
        )
        counts = (d <= alert_radius_km).sum(axis=1).astype(np.float64)
        if reference_days is None:
            span = pd.to_datetime(alerts["ts_start"]).agg(["min", "max"])
            reference_days = max(
                (span["max"] - span["min"]).total_seconds() / 86400.0, 1.0
            )
        add("alerts_per_year", counts * (365.25 / reference_days))
        add("alert_count_log", np.log1p(counts))
    else:
        add("alerts_per_year", np.zeros(s))
        add("alert_count_log", np.zeros(s))

    if flood_prone_points is not None and len(flood_prone_points) > 0:
        pts = flood_prone_points.dropna(subset=["longitude", "latitude"])
        d = pairwise_km(
            grid.longitude,
            grid.latitude,
            pts["longitude"].to_numpy(dtype=np.float64),
            pts["latitude"].to_numpy(dtype=np.float64),
        )
        add("dist_floodprone_km", d.min(axis=1))
        for radius_m in cfg.flood_prone_radii_m:
            add(
                f"floodprone_within_{int(radius_m)}m",
                (d <= radius_m / 1000.0).sum(axis=1),
            )
    else:
        add("dist_floodprone_km", np.full(s, 99.0))
        for radius_m in cfg.flood_prone_radii_m:
            add(f"floodprone_within_{int(radius_m)}m", np.zeros(s))

    # Station density: how well observed this station's surroundings are.
    # A station with few neighbours has a weaker spatial-context feature, so
    # telling the model how much to trust those channels is worth a column.
    if s > 1:
        distances = pairwise_km(
            grid.longitude, grid.latitude, grid.longitude, grid.latitude
        )
        np.fill_diagonal(distances, np.inf)
        for radius_m in cfg.station_density_radii_m:
            add(
                f"stations_within_{int(radius_m)}m",
                (distances <= radius_m / 1000.0).sum(axis=1),
            )
        add("dist_nearest_station_km", distances.min(axis=1))
    else:
        for radius_m in cfg.station_density_radii_m:
            add(f"stations_within_{int(radius_m)}m", np.zeros(s))
        add("dist_nearest_station_km", np.full(s, 99.0))

    return StaticFeatures(
        values=np.stack(cols, axis=1).astype(np.float32),
        names=names,
        station_ids=grid.station_ids,
    )
