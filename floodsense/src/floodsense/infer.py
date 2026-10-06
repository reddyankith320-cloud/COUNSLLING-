"""Real-time scoring service.

Loads a training run's artifacts and turns a rainfall grid into the payload
the dashboard needs: a risk row per station, an explanation for a selected
location, and the what-if table.

The static feature vector is loaded from the run rather than recomputed.
That is deliberate: it contains a per-station historical alert rate that was
measured on the training period, and recomputing it live - over a window
that now includes the evaluation period - would quietly change the model's
inputs between training and serving.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config
from .dataset import Scaler
from .explain import Explanation, explain_sample
from .features import rolling_sum
from .grid import RainGrid
from .model import FloodSenseLSTM
from .risk import RiskScorer
from .schema import STEP_MINUTES
from .simulate import SimulationReport, score_grid_at, simulate


@dataclass
class StaticTable:
    """Per-station static features, as fitted during training."""

    station_ids: np.ndarray
    names: list[str]
    values: np.ndarray                   # (S, G) raw (unscaled)

    def to_dict(self) -> dict:
        return {
            "station_ids": [str(s) for s in self.station_ids],
            "names": self.names,
            "values": self.values.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StaticTable":
        return cls(
            station_ids=np.asarray(data["station_ids"], dtype=object),
            names=list(data["names"]),
            values=np.asarray(data["values"], dtype=np.float32),
        )

    def aligned_to(self, station_ids: np.ndarray) -> np.ndarray:
        """Reorder rows to match a grid's station order.

        A station present in the grid but absent from training gets a
        zero vector, which after scaling is the training mean - the
        least-assuming default for an unknown location.
        """
        lookup = {str(s): i for i, s in enumerate(self.station_ids)}
        out = np.zeros((len(station_ids), self.values.shape[1]), dtype=np.float32)
        for row, sid in enumerate(station_ids):
            index = lookup.get(str(sid))
            if index is not None:
                out[row] = self.values[index]
        return out


@dataclass
class FloodSenseService:
    """Everything needed to score, explain and simulate."""

    model: FloodSenseLSTM
    scaler: Scaler
    config: Config
    scorer: RiskScorer
    statics: StaticTable

    @classmethod
    def from_artifacts(cls, directory: str | Path) -> "FloodSenseService":
        directory = Path(directory)
        model_path = directory / "floodsense_lstm.pt"
        for required in (model_path, directory / "scaler.json", directory / "config.json"):
            if not required.exists():
                raise FileNotFoundError(f"missing artifact: {required}")

        statics_path = directory / "statics.json"
        if not statics_path.exists():
            raise FileNotFoundError(
                f"missing {statics_path}; re-run training to emit it"
            )

        risk_path = directory / "risk_scorer.json"
        scorer = (
            RiskScorer.from_dict(json.loads(risk_path.read_text()))
            if risk_path.exists()
            else None
        )

        config = Config.from_json(directory / "config.json")
        if scorer is None:
            raise FileNotFoundError(
                f"missing {risk_path}; the risk score needs its fitted "
                "normalisation references"
            )

        return cls(
            model=FloodSenseLSTM.load(model_path),
            scaler=Scaler.from_dict(json.loads((directory / "scaler.json").read_text())),
            config=config,
            scorer=scorer,
            statics=StaticTable.from_dict(json.loads(statics_path.read_text())),
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _static_scaled(self, grid: RainGrid) -> np.ndarray:
        return self.scaler.transform_static(self.statics.aligned_to(grid.station_ids))

    def _vulnerability(self, grid: RainGrid) -> np.ndarray:
        raw = self.statics.aligned_to(grid.station_ids)
        if "alerts_per_year" in self.statics.names:
            return raw[:, self.statics.names.index("alerts_per_year")]
        return np.zeros(grid.n_stations, dtype=np.float32)

    def score(
        self, grid: RainGrid, t_end: int | None = None
    ) -> tuple[pd.DataFrame, np.ndarray]:
        """Score every station at one step.

        Returns the risk table and the scaled model inputs ``(S, L, F)``,
        so an explanation can be produced without rescoring.
        """
        t_end = grid.n_steps - 1 if t_end is None else int(t_end)
        static_scaled = self._static_scaled(grid)

        probabilities, sequences = score_grid_at(
            self.model, grid, static_scaled, self.scaler, self.config, t_end
        )

        rain = grid.filled(0.0)
        intensity = rain[t_end] * (60.0 / STEP_MINUTES)
        acc_30 = rolling_sum(rain, 6)[t_end]
        acc_60 = rolling_sum(rain, 12)[t_end]
        vulnerability = self._vulnerability(grid)

        scores = self.scorer.score(
            probability=probabilities,
            intensity_mm_hr=intensity,
            accumulation_mm=acc_30,
            vulnerability=vulnerability,
        )
        bands = np.atleast_1d(self.scorer.band(scores))

        table = pd.DataFrame(
            {
                "station_id": grid.station_ids,
                "station_name": grid.station_names,
                "longitude": grid.longitude,
                "latitude": grid.latitude,
                "ts": grid.times[t_end],
                "flood_probability_30_60min": probabilities.astype(np.float32),
                "flood_risk_score": scores.astype(np.float32),
                "risk_band": bands,
                "rain_5min_mm": rain[t_end],
                "rain_30min_mm": acc_30,
                "rain_60min_mm": acc_60,
                "intensity_mm_hr": intensity,
                "observed": grid.observed_mask()[t_end],
                "past_alerts_per_year": vulnerability,
            }
        ).sort_values("flood_risk_score", ascending=False, ignore_index=True)

        return table, sequences

    def explain(
        self,
        grid: RainGrid,
        station_id: str,
        t_end: int | None = None,
        sequences: np.ndarray | None = None,
        top_k: int = 4,
    ) -> Explanation:
        """Explain one station's score."""
        t_end = grid.n_steps - 1 if t_end is None else int(t_end)
        index = grid.station_index().get(str(station_id))
        if index is None:
            raise KeyError(f"station {station_id!r} is not in this grid")

        if sequences is None:
            static_scaled = self._static_scaled(grid)
            _, sequences = score_grid_at(
                self.model, grid, static_scaled, self.scaler, self.config, t_end
            )

        static_scaled = self._static_scaled(grid)
        return explain_sample(
            self.model,
            sequences[index],
            static_scaled[index],
            top_k=top_k,
        )

    def simulate(
        self,
        grid: RainGrid,
        t_end: int | None = None,
        factors: tuple[float, ...] = (1.0, 1.25, 1.5, 2.0),
        scale_window_minutes: int = 60,
    ) -> SimulationReport:
        """Run the rainfall-scaling scenarios."""
        t_end = grid.n_steps - 1 if t_end is None else int(t_end)
        return simulate(
            self.model,
            grid,
            self._static_scaled(grid),
            self.scaler,
            self.scorer,
            self.config,
            t_end,
            factors=factors,
            scale_window_minutes=scale_window_minutes,
            vulnerability=self._vulnerability(grid),
        )

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def dashboard_payload(
        self,
        grid: RainGrid,
        t_end: int | None = None,
        *,
        top_n: int = 10,
        simulate_factors: tuple[float, ...] = (1.0, 1.25, 1.5, 2.0),
    ) -> dict:
        """One JSON object with everything the dashboard renders.

        Keys map to the dashboard panels: ``map`` (every station),
        ``priority`` (the triage list), ``selected`` (the location panel
        with its explanation), ``simulation`` (the what-if table) and
        ``disclaimer``.
        """
        t_end = grid.n_steps - 1 if t_end is None else int(t_end)
        table, sequences = self.score(grid, t_end)

        selected_id = str(table.iloc[0]["station_id"]) if len(table) else None
        explanation = (
            self.explain(grid, selected_id, t_end, sequences=sequences)
            if selected_id is not None
            else None
        )
        simulation = self.simulate(
            grid, t_end, factors=simulate_factors
        )

        return {
            "generated_for": str(grid.times[t_end]),
            "map": json.loads(
                table.drop(columns=["ts"]).to_json(orient="records")
            ),
            "priority": json.loads(
                table.head(top_n).drop(columns=["ts"]).to_json(orient="records")
            ),
            "band_counts": self.scorer.band_counts(
                table["flood_risk_score"].to_numpy()
            ),
            "selected": {
                "station_id": selected_id,
                "explanation": explanation.to_dict() if explanation else None,
            },
            "simulation": simulation.to_dict(),
            "risk_score_definition": self.scorer.to_dict(),
            "disclaimer": (
                "FloodSense is a decision-support prototype built on public "
                "data. It does not replace official PUB flood warnings."
            ),
        }
