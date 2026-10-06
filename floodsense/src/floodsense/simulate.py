"""What-if: scenario analysis on rainfall intensity.

**This is scenario analysis, not a forecast.**  It answers "if rainfall over
the last hour had been 50% heavier, what would the model say?", which is a
planning question about sensitivity and exposure.  It does not predict that
rainfall will increase.

The important engineering point: the scaling is applied to the **raw
rainfall grid**, and every derived feature is then recomputed from it.
Scaling the derived channels directly - multiplying ``acc_1h`` by 1.5 and
leaving ``rate_30m`` alone - produces a feature vector that no real weather
could generate, and the model's response to it means nothing.  So the
simulator rebuilds a slice of the grid instead.

Only a window ending at the scored step needs rebuilding: every feature is
causal with a longest window of ``max(accumulation_minutes)``, so a slice
of ``that + sequence_steps`` steps reproduces the real features exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from .config import Config
from .dataset import Scaler
from .features import build_dynamic_features
from .grid import RainGrid
from .model import FloodSenseLSTM
from .risk import RiskScorer
from .schema import STEP_MINUTES


@dataclass
class ScenarioResult:
    """One rainfall-scaling scenario, scored across every station."""

    factor: float
    label: str
    probabilities: np.ndarray            # (S,)
    risk_scores: np.ndarray              # (S,)
    bands: np.ndarray                    # (S,) band names
    band_counts: dict[str, int]
    high_or_critical: int
    mean_probability: float

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "label": self.label,
            "band_counts": self.band_counts,
            "high_or_critical": self.high_or_critical,
            "mean_probability": self.mean_probability,
        }


@dataclass
class SimulationReport:
    scenarios: list[ScenarioResult]
    station_ids: np.ndarray
    scaled_window_minutes: int
    scored_at: str
    disclaimer: str = (
        "Scenario analysis: the model re-scored against hypothetically "
        "heavier rainfall. Not a forecast, and not an official PUB warning."
    )

    def to_dict(self) -> dict:
        return {
            "scored_at": self.scored_at,
            "scaled_window_minutes": self.scaled_window_minutes,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "disclaimer": self.disclaimer,
        }

    def table(self) -> str:
        """Markdown summary - the dashboard's simulator panel in text form."""
        rows = [
            "| scenario | Low | Moderate | High | Critical | High+Critical |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for s in self.scenarios:
            c = s.band_counts
            rows.append(
                f"| {s.label} | {c['Low']} | {c['Moderate']} | {c['High']} | "
                f"{c['Critical']} | {s.high_or_critical} |"
            )
        return "\n".join(rows)


def scale_recent_rainfall(
    grid: RainGrid, t_end: int, factor: float, window_steps: int
) -> RainGrid:
    """Copy the grid with the last ``window_steps`` of rainfall scaled.

    Observed-but-dry intervals stay dry: multiplying zero by 1.5 is zero.
    That is the intended semantics - "the rain that fell was heavier", not
    "it rained where it did not".
    """
    rain = grid.rain.copy()
    lo = max(t_end - window_steps + 1, 0)
    rain[lo : t_end + 1] = rain[lo : t_end + 1] * factor
    return RainGrid(
        times=grid.times,
        station_ids=grid.station_ids,
        rain=rain,
        longitude=grid.longitude,
        latitude=grid.latitude,
        station_names=grid.station_names,
    )


def score_grid_at(
    model: FloodSenseLSTM,
    grid: RainGrid,
    static_scaled: np.ndarray,
    scaler: Scaler,
    cfg: Config,
    t_end: int,
    *,
    batch_size: int = 256,
) -> tuple[np.ndarray, np.ndarray]:
    """Score every station at step ``t_end``.

    Returns ``(probabilities, sequences)``; the sequences are the scaled
    model inputs, returned so the caller can feed them to ``explain``
    without recomputing.
    """
    seq_steps = cfg.windows.sequence_steps
    history = max(
        (int(round(m / STEP_MINUTES)) for m in cfg.features.accumulation_minutes),
        default=1,
    )
    lo = max(t_end - (history + seq_steps) + 1, 0)

    window_grid = grid.subset_time(lo, t_end + 1)
    features = build_dynamic_features(window_grid, cfg.features)
    if features.values.shape[0] < seq_steps:
        raise ValueError(
            f"only {features.values.shape[0]} steps available at t={t_end}; "
            f"need {seq_steps}. Score a later step."
        )

    tail = features.values[-seq_steps:]                     # (L, S, F)
    scaled = scaler.transform_dynamic(tail)
    sequences = np.ascontiguousarray(
        np.transpose(scaled, (1, 0, 2)), dtype=np.float32
    )                                                        # (S, L, F)

    model.eval()
    probabilities = np.empty(sequences.shape[0], dtype=np.float32)
    with torch.no_grad():
        for start in range(0, len(sequences), batch_size):
            stop = start + batch_size
            s = torch.from_numpy(sequences[start:stop])
            t = torch.from_numpy(
                np.ascontiguousarray(static_scaled[start:stop], dtype=np.float32)
            )
            probabilities[start:stop] = torch.sigmoid(model(s, t)).numpy()

    return probabilities, sequences


def simulate(
    model: FloodSenseLSTM,
    grid: RainGrid,
    static_scaled: np.ndarray,
    scaler: Scaler,
    scorer: RiskScorer,
    cfg: Config,
    t_end: int,
    *,
    factors: tuple[float, ...] = (1.0, 1.25, 1.5, 2.0),
    scale_window_minutes: int = 60,
    vulnerability: np.ndarray | None = None,
) -> SimulationReport:
    """Re-score every station under each rainfall-scaling factor."""
    from .features import rolling_sum

    window_steps = max(int(round(scale_window_minutes / STEP_MINUTES)), 1)
    scenarios: list[ScenarioResult] = []

    if vulnerability is None:
        vulnerability = np.zeros(grid.n_stations, dtype=np.float32)

    for factor in factors:
        scenario_grid = (
            grid if factor == 1.0
            else scale_recent_rainfall(grid, t_end, factor, window_steps)
        )
        probabilities, _ = score_grid_at(
            model, scenario_grid, static_scaled, scaler, cfg, t_end
        )

        rain = scenario_grid.filled(0.0)
        intensity = rain[t_end] * (60.0 / STEP_MINUTES)
        lo = max(t_end - 5, 0)
        accumulation = rain[lo : t_end + 1].sum(axis=0)

        scores = scorer.score(
            probability=probabilities,
            intensity_mm_hr=intensity,
            accumulation_mm=accumulation,
            vulnerability=vulnerability,
        )
        bands = np.atleast_1d(scorer.band(scores))
        counts = scorer.band_counts(scores)

        scenarios.append(
            ScenarioResult(
                factor=float(factor),
                label="Current rainfall" if factor == 1.0 else f"+{int((factor - 1) * 100)}% rainfall",
                probabilities=probabilities,
                risk_scores=scores,
                bands=bands,
                band_counts=counts,
                high_or_critical=counts["High"] + counts["Critical"],
                mean_probability=float(probabilities.mean()),
            )
        )

    return SimulationReport(
        scenarios=scenarios,
        station_ids=grid.station_ids,
        scaled_window_minutes=scale_window_minutes,
        scored_at=str(grid.times[t_end]),
    )
