"""The Flood Risk Score (0-100).

**This is a project-defined decision-support score.  It is not an official
Singapore government flood rating, it does not replace PUB warnings, and
its weights have not been validated against outcomes.**  It exists because
a bare probability is hard to triage on: operators want one comparable
number per location, and they want it to move when rainfall intensity or
known vulnerability moves, not only when the classifier's probability does.

    score = 100 * ( w_p * P(flood in 30-60 min)
                  + w_i * normalised rainfall intensity
                  + w_a * normalised recent accumulation
                  + w_v * normalised location vulnerability )
            + recent-alert bonus

Bands: 0-30 Low, 31-60 Moderate, 61-80 High, 81-100 Critical.

The three non-probability components are normalised against **percentiles
measured on the training split**, not against invented thresholds: there is
no published rainfall threshold for "high intensity", so the score says
"high relative to what this station network actually records".  Changing
the reference period changes the score, which is why ``fit`` records what
it used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import RiskConfig

BAND_NAMES = ("Low", "Moderate", "High", "Critical")


@dataclass
class RiskScorer:
    """Blends a calibrated probability with context into a 0-100 score."""

    cfg: RiskConfig
    intensity_reference: float
    accumulation_reference: float
    vulnerability_reference: float
    fitted_on: dict[str, object] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    @classmethod
    def fit(
        cls,
        intensity: np.ndarray,
        accumulation: np.ndarray,
        vulnerability: np.ndarray,
        cfg: RiskConfig | None = None,
        *,
        description: str = "",
    ) -> "RiskScorer":
        """Measure normalisation references from training-period data.

        Args:
            intensity: raw intensity values (mm/h) over the training region.
            accumulation: raw accumulation values (mm) over the same region.
            vulnerability: per-station vulnerability proxy.
            description: free text recorded on the scorer for provenance.
        """
        cfg = cfg or RiskConfig()

        def reference(values: np.ndarray, percentile: float) -> float:
            flat = np.asarray(values, dtype=np.float64).reshape(-1)
            flat = flat[np.isfinite(flat)]
            if flat.size == 0:
                return 1.0
            value = float(np.percentile(flat, percentile))
            return value if value > 1e-6 else 1.0

        vul = np.asarray(vulnerability, dtype=np.float64).reshape(-1)
        vul_ref = float(np.max(vul)) if vul.size and np.max(vul) > 0 else 1.0

        return cls(
            cfg=cfg,
            intensity_reference=reference(
                intensity, cfg.intensity_reference_percentile
            ),
            accumulation_reference=reference(
                accumulation, cfg.accumulation_reference_percentile
            ),
            vulnerability_reference=vul_ref,
            fitted_on={
                "description": description,
                "intensity_percentile": cfg.intensity_reference_percentile,
                "accumulation_percentile": cfg.accumulation_reference_percentile,
                "n_intensity_samples": int(np.size(intensity)),
            },
        )

    @classmethod
    def from_prepared(cls, prepared, cfg: RiskConfig | None = None) -> "RiskScorer":
        """Fit from a ``Prepared`` bundle, using the training region only."""
        lo, hi = prepared.splits.eligible_from, prepared.splits.train_end_step
        # The scaled feature tensor is standardised, so the references are
        # recomputed from the raw grid in physical units (mm, mm/h).
        from .features import rolling_sum
        from .schema import STEP_MINUTES

        rain = prepared.grid.filled(0.0)[lo:hi]
        intensity = rain * (60.0 / STEP_MINUTES)
        accumulation = rolling_sum(prepared.grid.filled(0.0), 6)[lo:hi]

        statics = prepared.statics
        if "alerts_per_year" in statics.names:
            vulnerability = statics.values[:, statics.index_of("alerts_per_year")]
        else:
            vulnerability = np.zeros(statics.values.shape[0], dtype=np.float32)

        return cls.fit(
            intensity,
            accumulation,
            vulnerability,
            cfg,
            description=(
                f"training region steps [{lo}, {hi}) of "
                f"{prepared.grid.n_steps}; "
                f"{prepared.splits.boundaries_iso.get('data_start', '')} to "
                f"{prepared.splits.boundaries_iso.get('train_end', '')}"
            ),
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(
        self,
        probability: np.ndarray | float,
        intensity_mm_hr: np.ndarray | float = 0.0,
        accumulation_mm: np.ndarray | float = 0.0,
        vulnerability: np.ndarray | float = 0.0,
        recent_alert: np.ndarray | bool = False,
    ) -> np.ndarray:
        """Return the 0-100 score, broadcasting over array inputs."""
        c = self.cfg
        p = np.clip(np.asarray(probability, dtype=np.float64), 0.0, 1.0)
        i = _unit(intensity_mm_hr, self.intensity_reference)
        a = _unit(accumulation_mm, self.accumulation_reference)
        v = _unit(vulnerability, self.vulnerability_reference)

        total_weight = (
            c.weight_probability
            + c.weight_intensity
            + c.weight_accumulation
            + c.weight_vulnerability
        )
        blended = (
            c.weight_probability * p
            + c.weight_intensity * i
            + c.weight_accumulation * a
            + c.weight_vulnerability * v
        ) / max(total_weight, 1e-9)

        score = 100.0 * blended
        score = score + np.asarray(recent_alert, dtype=np.float64) * c.recent_alert_bonus
        return np.clip(score, 0.0, 100.0)

    def band(self, score: np.ndarray | float) -> np.ndarray:
        """Map scores onto the four band names."""
        edges = self.cfg.band_edges
        s = np.asarray(score, dtype=np.float64)
        index = np.digitize(s, bins=np.asarray(edges, dtype=np.float64), right=True)
        return np.asarray(BAND_NAMES, dtype=object)[np.clip(index, 0, 3)]

    def band_counts(self, scores: np.ndarray) -> dict[str, int]:
        """Count locations per band - the dashboard's headline tiles."""
        bands = np.atleast_1d(self.band(scores))
        return {name: int((bands == name).sum()) for name in BAND_NAMES}

    def to_dict(self) -> dict:
        return {
            "intensity_reference": self.intensity_reference,
            "accumulation_reference": self.accumulation_reference,
            "vulnerability_reference": self.vulnerability_reference,
            "weights": {
                "probability": self.cfg.weight_probability,
                "intensity": self.cfg.weight_intensity,
                "accumulation": self.cfg.weight_accumulation,
                "vulnerability": self.cfg.weight_vulnerability,
            },
            "band_edges": list(self.cfg.band_edges),
            "recent_alert_bonus": self.cfg.recent_alert_bonus,
            "fitted_on": self.fitted_on,
            "disclaimer": (
                "Project-defined decision-support score. Not an official "
                "Singapore government flood rating. Weights are an initial "
                "proposal and have not been validated against outcomes."
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RiskScorer":
        weights = data.get("weights", {})
        cfg = RiskConfig(
            weight_probability=weights.get("probability", 0.60),
            weight_intensity=weights.get("intensity", 0.15),
            weight_accumulation=weights.get("accumulation", 0.15),
            weight_vulnerability=weights.get("vulnerability", 0.10),
            band_edges=tuple(data.get("band_edges", (30, 60, 80))),
            recent_alert_bonus=data.get("recent_alert_bonus", 10.0),
        )
        return cls(
            cfg=cfg,
            intensity_reference=float(data["intensity_reference"]),
            accumulation_reference=float(data["accumulation_reference"]),
            vulnerability_reference=float(data["vulnerability_reference"]),
            fitted_on=data.get("fitted_on", {}),
        )


def _unit(values: np.ndarray | float, reference: float) -> np.ndarray:
    """Scale to ``[0, 1]`` against a reference, saturating above it."""
    return np.clip(
        np.asarray(values, dtype=np.float64) / max(reference, 1e-9), 0.0, 1.0
    )
