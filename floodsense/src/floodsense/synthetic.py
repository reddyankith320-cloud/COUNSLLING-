"""Synthetic rainfall and flood-alert generator.

**Why this exists.** The official datasets live on data.gov.sg.  When that
host is unreachable - a locked-down CI runner, an offline review, a network
policy that does not allow it - the pipeline still has to be runnable and
testable end to end.  This module produces data in exactly the canonical
schema the real loaders emit, so every downstream stage is exercised
unchanged.

**What it is not.** It is not a calibrated model of Singapore's climate, and
metrics measured on it say nothing about real-world skill.  They validate
the *pipeline*: that features are causal, that the splits do not leak, that
the LSTM trains and beats its baselines on a signal that requires memory.

The generator is deliberately built so that a last-reading-only model cannot
do well: an alert fires on a hidden state that integrates rainfall over
hours (a saturation term), interacted with per-station vulnerability.
Storms also ramp before they peak, so the 30-60 minute horizon is
genuinely - but only partially - predictable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .schema import SG_BOUNDS, STEP_MINUTES, TIMEZONE


@dataclass
class SyntheticConfig:
    n_stations: int = 32
    start: str = "2023-01-01"
    days: int = 270
    seed: int = 20260101

    #: Mean storms per day, before monsoon modulation.
    storms_per_day: float = 4.5

    #: Share of storms whose onset is drawn from the afternoon convective
    #: peak rather than uniformly across the day.
    afternoon_share: float = 0.6
    afternoon_hours: tuple[int, int] = (13, 18)

    #: Storm geometry and life cycle.
    radius_km_range: tuple[float, float] = (2.5, 12.0)
    duration_minutes_range: tuple[int, int] = (45, 300)
    speed_kmh_range: tuple[float, float] = (4.0, 28.0)
    peak_gamma_shape: float = 2.0
    peak_gamma_scale: float = 2.2

    #: Fraction of the life cycle at which a storm peaks.
    peak_phase: float = 0.45

    #: Reporting realism.
    missing_rate: float = 0.004
    outage_count: int = 6
    outage_hours_range: tuple[float, float] = (2.0, 30.0)

    #: Hidden drainage-saturation decay per 5-minute step.
    saturation_decay: float = 0.9975

    #: Hazard weights on (acc30, peak30, log1p(saturation), vulnerability,
    #: acc3h).  Antecedent wetness and multi-hour accumulation carry most of
    #: the weight: a flash flood follows sustained rain on an already-loaded
    #: drainage system, and those terms are the ones a model can still see
    #: 30-60 minutes before the alert.  A hazard driven only by the
    #: instantaneous burst would be unpredictable at that lead time by
    #: construction, which would test nothing.
    hazard_weights: tuple[float, float, float, float, float] = (
        0.30, 0.45, 1.35, 1.50, 0.10,
    )
    hazard_sharpness: float = 1.9

    #: The generator solves for the hazard offset that produces this alert
    #: frequency, so the class balance is a knob rather than an accident.
    target_alerts_per_station_month: float = 3.0

    #: No second alert at a station within this many minutes.
    refractory_minutes: int = 180
    alert_delay_steps_max: int = 3
    alert_duration_minutes_range: tuple[int, int] = (20, 90)

    #: Alerts are reported at a jittered location near the station, so the
    #: radius-based station/alert association has real work to do.
    alert_jitter_km: float = 1.2

    n_flood_prone_points: int = 35

    _unused: tuple[()] = field(default=(), repr=False)


@dataclass
class SyntheticBundle:
    """Everything a loader would return, plus the hidden ground truth."""

    readings: pd.DataFrame
    stations: pd.DataFrame
    alerts: pd.DataFrame
    flood_prone_points: pd.DataFrame
    flood_prone_areas: pd.DataFrame
    truth: dict[str, np.ndarray]

    def describe(self) -> dict[str, float]:
        return {
            "stations": float(len(self.stations)),
            "readings": float(len(self.readings)),
            "alerts": float(len(self.alerts)),
            "days": float(
                (self.readings["ts"].max() - self.readings["ts"].min()).days + 1
            ),
            "mean_rain_mm_per_step": float(self.readings["rainfall_mm"].mean()),
            "wet_step_share": float((self.readings["rainfall_mm"] > 0.0).mean()),
        }


def generate(cfg: SyntheticConfig | None = None) -> SyntheticBundle:
    """Generate a synthetic bundle in the canonical schema."""
    cfg = cfg or SyntheticConfig()
    rng = np.random.default_rng(cfg.seed)

    times = pd.date_range(
        pd.Timestamp(cfg.start, tz=TIMEZONE),
        periods=int(cfg.days * 24 * 60 / STEP_MINUTES),
        freq=f"{STEP_MINUTES}min",
    )
    n_t = len(times)

    stations = _make_stations(cfg, rng)
    n_s = len(stations)
    lon = stations["longitude"].to_numpy()
    lat = stations["latitude"].to_numpy()
    vuln = stations["vulnerability"].to_numpy()

    rain = _simulate_rainfall(cfg, rng, times, lon, lat)
    saturation = _saturation(rain, cfg.saturation_decay)
    alerts, alert_steps = _simulate_alerts(
        cfg, rng, times, rain, saturation, vuln, stations
    )
    rain_reported = _apply_missingness(cfg, rng, rain)

    readings = _to_long(times, stations, rain_reported)
    flood_prone_points = _make_flood_prone_points(cfg, rng, stations)

    # The real PUB "Flood Prone Areas" dataset is two columns (year,
    # hectares).  Mirror that shape, with the published 2022-2025 values, so
    # downstream trend code is exercised against the real schema.
    flood_prone_areas = pd.DataFrame(
        {"year": [2022, 2023, 2024, 2025], "hectares": [27.0, 24.1, 23.6, 23.3]}
    )

    return SyntheticBundle(
        readings=readings,
        stations=stations.drop(columns=["vulnerability"]),
        alerts=alerts,
        flood_prone_points=flood_prone_points,
        flood_prone_areas=flood_prone_areas,
        truth={
            "rain_true": rain,
            "saturation": saturation,
            "vulnerability": vuln,
            "alert_steps": alert_steps,
        },
    )


# --------------------------------------------------------------------------
# Pieces
# --------------------------------------------------------------------------


def _make_stations(cfg: SyntheticConfig, rng: np.random.Generator) -> pd.DataFrame:
    """Spread stations over a jittered lattice covering the island."""
    n = cfg.n_stations
    cols = int(np.ceil(np.sqrt(n * 1.8)))
    rows = int(np.ceil(n / cols))
    lon_edges = np.linspace(SG_BOUNDS["lon_min"], SG_BOUNDS["lon_max"], cols + 1)
    lat_edges = np.linspace(SG_BOUNDS["lat_min"], SG_BOUNDS["lat_max"], rows + 1)

    lons, lats = [], []
    for r in range(rows):
        for c in range(cols):
            if len(lons) >= n:
                break
            lons.append(rng.uniform(lon_edges[c], lon_edges[c + 1]))
            lats.append(rng.uniform(lat_edges[r], lat_edges[r + 1]))

    return pd.DataFrame(
        {
            "station_id": [f"SY{i:03d}" for i in range(n)],
            "station_name": [f"Synthetic Station {i:03d}" for i in range(n)],
            "longitude": np.asarray(lons[:n]),
            "latitude": np.asarray(lats[:n]),
            # Skewed: a few locations are much more flood-prone, as in the
            # real flood-prone-area list.
            "vulnerability": rng.beta(1.8, 4.5, size=n),
        }
    )


def _monsoon_factor(times: pd.DatetimeIndex) -> np.ndarray:
    """Seasonal storm-rate multiplier (NE monsoon wetter, Feb driest)."""
    doy = times.dayofyear.to_numpy().astype(np.float64)
    return 1.0 + 0.45 * np.cos(2.0 * np.pi * (doy - 350.0) / 365.25)


def _simulate_rainfall(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    times: pd.DatetimeIndex,
    lon: np.ndarray,
    lat: np.ndarray,
) -> np.ndarray:
    """``(T, S)`` rainfall in mm per 5-minute interval."""
    n_t, n_s = len(times), len(lon)
    rain = np.zeros((n_t, n_s), dtype=np.float32)

    steps_per_day = int(24 * 60 / STEP_MINUTES)
    season = _monsoon_factor(times)
    day_starts = np.arange(0, n_t, steps_per_day)

    km_per_deg_lat = 110.57
    km_per_deg_lon = 111.32 * float(np.cos(np.radians(lat.mean())))

    for day_start in day_starts:
        rate = cfg.storms_per_day * float(season[day_start])
        for _ in range(rng.poisson(rate)):
            if rng.random() < cfg.afternoon_share:
                h0, h1 = cfg.afternoon_hours
                onset_min = rng.uniform(h0 * 60, h1 * 60)
            else:
                onset_min = rng.uniform(0, 24 * 60)
            t0 = int(day_start + onset_min / STEP_MINUTES)

            duration_min = rng.uniform(*cfg.duration_minutes_range)
            n_steps = max(int(duration_min / STEP_MINUTES), 2)
            if t0 >= n_t:
                continue
            n_steps = min(n_steps, n_t - t0)

            radius = rng.uniform(*cfg.radius_km_range)
            peak = rng.gamma(cfg.peak_gamma_shape, cfg.peak_gamma_scale)
            cx = rng.uniform(SG_BOUNDS["lon_min"] - 0.08, SG_BOUNDS["lon_max"] + 0.08)
            cy = rng.uniform(SG_BOUNDS["lat_min"] - 0.05, SG_BOUNDS["lat_max"] + 0.05)
            speed = rng.uniform(*cfg.speed_kmh_range)
            heading = rng.uniform(0.0, 2.0 * np.pi)
            dx_km = speed * np.cos(heading) * (STEP_MINUTES / 60.0)
            dy_km = speed * np.sin(heading) * (STEP_MINUTES / 60.0)

            phase = np.arange(n_steps, dtype=np.float64) / max(n_steps - 1, 1)
            temporal = _life_cycle(phase, cfg.peak_phase)

            for k in range(n_steps):
                ox = cx + (dx_km * k) / km_per_deg_lon
                oy = cy + (dy_km * k) / km_per_deg_lat
                d_km = np.sqrt(
                    ((lon - ox) * km_per_deg_lon) ** 2
                    + ((lat - oy) * km_per_deg_lat) ** 2
                )
                spatial = np.exp(-2.2 * (d_km / radius) ** 2)
                amount = peak * temporal[k] * spatial
                # Multiplicative noise: convective rainfall is spiky.
                amount = amount * rng.gamma(4.0, 0.25, size=n_s)
                rain[t0 + k] += amount.astype(np.float32)

    # Light widespread drizzle, independent of the storm field.
    drizzle = (rng.random((n_t, n_s)) < 0.012) * rng.gamma(
        1.2, 0.18, size=(n_t, n_s)
    )
    rain += drizzle.astype(np.float32)

    # Tipping-bucket quantisation (0.2 mm per tip).
    np.round(rain / 0.2, 0, out=rain)
    rain *= 0.2
    return np.clip(rain, 0.0, None)


def _life_cycle(phase: np.ndarray, peak_phase: float) -> np.ndarray:
    """Rise-then-decay storm envelope, peaking at ``peak_phase``."""
    rise = np.clip(phase / max(peak_phase, 1e-3), 0.0, 1.0) ** 1.8
    decay = np.exp(-np.clip(phase - peak_phase, 0.0, None) / 0.30)
    return rise * decay


def _saturation(rain: np.ndarray, decay: float) -> np.ndarray:
    """Hidden drainage/soil saturation: a leaky integral of rainfall.

    This is the state that makes the problem a *sequence* problem - it is not
    recoverable from the latest reading alone.
    """
    n_t, n_s = rain.shape
    sat = np.zeros((n_t, n_s), dtype=np.float32)
    acc = np.zeros(n_s, dtype=np.float32)
    for t in range(n_t):
        acc = acc * decay + rain[t]
        sat[t] = acc
    return sat


def _simulate_alerts(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    times: pd.DatetimeIndex,
    rain: np.ndarray,
    saturation: np.ndarray,
    vuln: np.ndarray,
    stations: pd.DataFrame,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Draw alerts from a hazard function, then solve for the target rate."""
    from .features import rolling_max, rolling_sum

    acc30 = rolling_sum(rain, 6)
    acc3h = rolling_sum(rain, 36)
    peak30 = rolling_max(rain, 6)
    w = cfg.hazard_weights
    drive = (
        w[0] * acc30
        + w[1] * peak30
        + w[2] * np.log1p(saturation)
        + w[3] * vuln[None, :]
        + w[4] * acc3h
    ).astype(np.float32)

    n_t, n_s = rain.shape
    refractory = max(int(cfg.refractory_minutes / STEP_MINUTES), 1)
    months = n_t * STEP_MINUTES / (60.0 * 24.0 * 30.4375)
    target = cfg.target_alerts_per_station_month * months * n_s

    # Noise first, then a calibrated threshold.  Drawing the noise once and
    # solving for the threshold that yields the target number of *distinct*
    # events is what makes the alert rate controllable: a plain Bernoulli
    # draw concentrates its probability mass inside single storms, so the
    # expected-count calibration and the realised event count diverge by an
    # order of magnitude once the refractory period collapses each cluster.
    score = drive + rng.normal(0.0, 0.45 / cfg.hazard_sharpness, drive.shape).astype(
        np.float32
    )
    offset = _solve_offset(score, target, refractory)
    fires = score > offset
    rows = []
    alert_steps = np.zeros((n_t, n_s), dtype=bool)
    for s in range(n_s):
        t = 0
        hits = np.flatnonzero(fires[:, s])
        for t_fire in hits:
            if t_fire < t:
                continue
            delay = int(rng.integers(0, cfg.alert_delay_steps_max + 1))
            t_report = int(min(t_fire + delay, n_t - 1))
            duration = float(rng.uniform(*cfg.alert_duration_minutes_range))
            jitter_km = rng.uniform(0.0, cfg.alert_jitter_km)
            bearing = rng.uniform(0.0, 2.0 * np.pi)
            rows.append(
                {
                    "alert_id": f"SYN-{s:03d}-{t_report:06d}",
                    "ts_start": times[t_report],
                    "ts_end": times[t_report]
                    + pd.Timedelta(minutes=duration),
                    "location_name": stations["station_name"].iloc[s],
                    "longitude": float(
                        stations["longitude"].iloc[s]
                        + jitter_km * np.cos(bearing) / 111.32
                    ),
                    "latitude": float(
                        stations["latitude"].iloc[s]
                        + jitter_km * np.sin(bearing) / 110.57
                    ),
                    "severity": "Moderate",
                    "urgency": "Immediate",
                }
            )
            alert_steps[t_report, s] = True
            t = int(t_fire) + refractory

    alerts = pd.DataFrame(rows)
    if alerts.empty:
        alerts = pd.DataFrame(
            columns=[
                "alert_id", "ts_start", "ts_end", "location_name",
                "longitude", "latitude", "severity", "urgency",
            ]
        )
    else:
        alerts = alerts.sort_values("ts_start").reset_index(drop=True)
    return alerts, alert_steps


def _solve_offset(
    score: np.ndarray, target_count: float, refractory: int, iters: int = 40
) -> float:
    """Bisect for the threshold giving ``target_count`` distinct events.

    ``count_events`` is non-increasing in the threshold, so bisection is
    well-posed.  The cell-count short circuit keeps early iterations - where
    a low threshold would select millions of cells - cheap.
    """
    lo = float(np.quantile(score, 0.90))
    hi = float(score.max()) + 1.0
    cap = int(max(4_000.0, 60.0 * target_count))
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if _count_events(score, mid, refractory, cap) > target_count:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _count_events(
    score: np.ndarray, offset: float, refractory: int, cap: int
) -> int:
    """Distinct alerts above ``offset`` once the refractory period applies."""
    above = score > offset
    n_above = int(above.sum())
    if n_above > cap:
        return n_above
    total = 0
    for s in range(score.shape[1]):
        last = -(10**9)
        for h in np.flatnonzero(above[:, s]):
            if h - last >= refractory:
                total += 1
                last = int(h)
    return total


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40.0, 40.0)))


def _apply_missingness(
    cfg: SyntheticConfig, rng: np.random.Generator, rain: np.ndarray
) -> np.ndarray:
    """Punch scattered gaps and a few station outages into the record."""
    out = rain.astype(np.float32).copy()
    n_t, n_s = out.shape

    scattered = rng.random((n_t, n_s)) < cfg.missing_rate
    out[scattered] = np.nan

    for _ in range(cfg.outage_count):
        s = int(rng.integers(0, n_s))
        hours = rng.uniform(*cfg.outage_hours_range)
        length = max(int(hours * 60 / STEP_MINUTES), 1)
        t0 = int(rng.integers(0, max(n_t - length, 1)))
        out[t0 : t0 + length, s] = np.nan

    return out


def _to_long(
    times: pd.DatetimeIndex, stations: pd.DataFrame, rain: np.ndarray
) -> pd.DataFrame:
    """Flatten to canonical long form, dropping unreported intervals."""
    n_t, n_s = rain.shape
    ts = times.repeat(n_s)
    sid = np.tile(stations["station_id"].to_numpy(), n_t)
    lonv = np.tile(stations["longitude"].to_numpy(), n_t)
    latv = np.tile(stations["latitude"].to_numpy(), n_t)
    values = rain.reshape(-1)

    frame = pd.DataFrame(
        {
            "ts": ts,
            "station_id": sid,
            "rainfall_mm": values.astype(np.float32),
            "longitude": lonv,
            "latitude": latv,
        }
    )
    return frame.dropna(subset=["rainfall_mm"]).reset_index(drop=True)


def _make_flood_prone_points(
    cfg: SyntheticConfig, rng: np.random.Generator, stations: pd.DataFrame
) -> pd.DataFrame:
    """Place flood-prone locations preferentially near vulnerable stations."""
    weights = stations["vulnerability"].to_numpy() ** 2
    weights = weights / weights.sum()
    picks = rng.choice(len(stations), size=cfg.n_flood_prone_points, p=weights)

    rows = []
    for i, s in enumerate(picks):
        bearing = rng.uniform(0.0, 2.0 * np.pi)
        dist = rng.uniform(0.0, 1.0)
        rows.append(
            {
                "location_name": f"Synthetic Flood-Prone Location {i:02d}",
                "longitude": float(
                    stations["longitude"].iloc[s] + dist * np.cos(bearing) / 111.32
                ),
                "latitude": float(
                    stations["latitude"].iloc[s] + dist * np.sin(bearing) / 110.57
                ),
                "as_of": "2025-11-01",
            }
        )
    return pd.DataFrame(rows)
