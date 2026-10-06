"""Why is this location at risk?

Two complementary signals, both read straight out of the trained network:

**Feature attribution** - gradient x input on the scaled feature tensor.
For each (timestep, channel) the product of the input value and the
gradient of the logit with respect to it is a first-order estimate of that
cell's contribution.  Summing over time gives a per-channel contribution
with a sign: positive pushed the risk up.

**Temporal attention** - the attention weights the model already computes
for pooling.  They say *when* in the three-hour window the evidence sits,
which is what turns "rainfall accumulation is high" into "and nearly all of
it arrived in the last half hour".

Limits, stated plainly: these are local, first-order attributions of one
model's output.  They explain what the model responded to.  They are not a
hydrological causal claim, and two correlated channels (15-minute and
30-minute accumulation, say) will share credit arbitrarily between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch

from .model import FloodSenseLSTM
from .schema import STEP_MINUTES

#: Channel name -> phrase used in the generated sentence.
PHRASES: dict[str, str] = {
    "rain_5min": "rainfall in the current 5-minute interval",
    "acc_15m": "15-minute rainfall accumulation",
    "acc_30m": "30-minute rainfall accumulation",
    "acc_1h": "1-hour rainfall accumulation",
    "acc_3h": "3-hour rainfall accumulation",
    "acc_6h": "6-hour rainfall accumulation",
    "acc_1d": "24-hour rainfall accumulation",
    "acc_3d": "3-day rainfall accumulation",
    "intensity_mm_hr": "current rainfall intensity",
    "peak_5min_30m": "the heaviest 5-minute burst in the last half hour",
    "mean_intensity_30m": "average rainfall intensity over 30 minutes",
    "mean_intensity_1h": "average rainfall intensity over the last hour",
    "rate_15m": "the rate at which 15-minute rainfall is increasing",
    "rate_30m": "the rate at which 30-minute rainfall is increasing",
    "trend_slope_30m": "the rising trend in rainfall over 30 minutes",
    "dry_spell_log": "how long it had been dry beforehand",
    "wet_ratio_24h_72h": "how much of the recent multi-day rain fell today",
    "observed": "the completeness of the station's reporting",
    "gap_log": "a gap in this station's reporting",
    "nbr_acc_30m": "rainfall at nearby stations over 30 minutes",
    "nbr_max_acc_30m": "the heaviest 30-minute rainfall at a nearby station",
    "nbr_acc_1h": "rainfall at nearby stations over the last hour",
    "nbr_max_acc_1h": "the heaviest 1-hour rainfall at a nearby station",
    "hour_sin": "the time of day",
    "hour_cos": "the time of day",
    "doy_sin": "the time of year",
    "doy_cos": "the time of year",
    # static
    "lon_norm": "the location itself",
    "lat_norm": "the location itself",
    "alerts_per_year": "this location's record of past flood alerts",
    "alert_count_log": "this location's record of past flood alerts",
    "dist_floodprone_km": "proximity to a known flood-prone location",
    "floodprone_within_1000m": "flood-prone locations within 1 km",
    "floodprone_within_2000m": "flood-prone locations within 2 km",
}


@dataclass
class Factor:
    name: str
    phrase: str
    contribution: float
    direction: str          # "raises" or "lowers"
    kind: str               # "dynamic" or "static"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "phrase": self.phrase,
            "contribution": self.contribution,
            "direction": self.direction,
            "kind": self.kind,
        }


@dataclass
class Explanation:
    probability: float
    factors: list[Factor]
    attention: np.ndarray                  # (L,) weights over the window
    attention_recent_share: float          # mass in the last 30 minutes
    attention_peak_minutes_ago: float
    sentence: str
    caveat: str = (
        "First-order attribution of this model's output, not a hydrological "
        "causal claim. Correlated rainfall windows may share credit."
    )
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "probability": self.probability,
            "factors": [f.to_dict() for f in self.factors],
            "attention_recent_share": self.attention_recent_share,
            "attention_peak_minutes_ago": self.attention_peak_minutes_ago,
            "sentence": self.sentence,
            "caveat": self.caveat,
            **self.extra,
        }


def explain_sample(
    model: FloodSenseLSTM,
    sequence: np.ndarray | torch.Tensor,
    static: np.ndarray | torch.Tensor,
    *,
    top_k: int = 4,
    recent_minutes: int = 30,
    step_minutes: int = STEP_MINUTES,
) -> Explanation:
    """Explain one scored sample.

    Args:
        sequence: ``(L, F)`` scaled dynamic features for one station/time.
        static: ``(G,)`` scaled static features.
        top_k: how many factors to name.
    """
    model.eval()
    seq = _as_tensor(sequence).unsqueeze(0).requires_grad_(True)
    stat = _as_tensor(static).unsqueeze(0).requires_grad_(True)

    logit, attention = model(seq, stat, return_attention=True)
    model.zero_grad(set_to_none=True)
    logit.sum().backward()

    probability = float(torch.sigmoid(logit.detach()).item())
    seq_attr = (seq.grad * seq).detach().squeeze(0).numpy()      # (L, F)
    stat_attr = (stat.grad * stat).detach().squeeze(0).numpy()   # (G,)
    weights = attention.detach().squeeze(0).numpy()              # (L,)

    dynamic_names = model.feature_names or [
        f"feature_{i}" for i in range(seq_attr.shape[1])
    ]
    static_names = model.static_names or [
        f"static_{i}" for i in range(stat_attr.shape[0])
    ]

    per_channel = seq_attr.sum(axis=0)
    candidates: list[Factor] = []
    for name, value in zip(dynamic_names, per_channel):
        candidates.append(_factor(name, float(value), "dynamic"))
    for name, value in zip(static_names, stat_attr):
        candidates.append(_factor(name, float(value), "static"))

    candidates.sort(key=lambda f: abs(f.contribution), reverse=True)
    top = _dedupe_phrases(candidates, top_k)

    steps_recent = max(int(round(recent_minutes / step_minutes)), 1)
    recent_share = float(weights[-steps_recent:].sum()) if weights.size else 0.0
    peak_offset = (
        float((len(weights) - 1 - int(np.argmax(weights))) * step_minutes)
        if weights.size
        else 0.0
    )

    return Explanation(
        probability=probability,
        factors=top,
        attention=weights,
        attention_recent_share=recent_share,
        attention_peak_minutes_ago=peak_offset,
        sentence=compose_sentence(probability, top, recent_share, recent_minutes),
    )


def _factor(name: str, value: float, kind: str) -> Factor:
    return Factor(
        name=name,
        phrase=PHRASES.get(name, name.replace("_", " ")),
        contribution=value,
        direction="raises" if value >= 0 else "lowers",
        kind=kind,
    )


def _dedupe_phrases(factors: list[Factor], top_k: int) -> list[Factor]:
    """Keep the strongest factor per distinct phrase.

    Several channels map to the same human phrase (hour_sin/hour_cos, the
    two alert-history columns).  Naming the same thing twice reads as a bug.
    """
    seen: set[str] = set()
    out: list[Factor] = []
    for factor in factors:
        if factor.phrase in seen:
            continue
        seen.add(factor.phrase)
        out.append(factor)
        if len(out) >= top_k:
            break
    return out


def compose_sentence(
    probability: float,
    factors: list[Factor],
    recent_share: float,
    recent_minutes: int,
) -> str:
    """Build the dashboard's explanation line from the top factors."""
    raising = [f for f in factors if f.direction == "raises"]
    level = (
        "High" if probability >= 0.50
        else "Elevated" if probability >= 0.20
        else "Low"
    )

    if not raising:
        return (
            f"{level} modelled risk. No single factor is pushing risk up right "
            "now; the strongest signals are currently reducing it."
        )

    phrases = [f.phrase for f in raising[:3]]
    if len(phrases) == 1:
        drivers = phrases[0]
    elif len(phrases) == 2:
        drivers = f"{phrases[0]} and {phrases[1]}"
    else:
        drivers = f"{phrases[0]}, {phrases[1]} and {phrases[2]}"

    sentence = f"{level} modelled risk, driven mainly by {drivers}."
    if recent_share >= 0.5:
        sentence += (
            f" Most of the evidence ({recent_share * 100:.0f}% of the model's "
            f"attention) is in the last {recent_minutes} minutes, so the "
            "situation is developing now."
        )
    elif recent_share <= 0.15:
        sentence += (
            " The evidence is spread across the earlier part of the window, "
            "pointing to accumulated rather than sudden rainfall."
        )
    return sentence


def _as_tensor(values: np.ndarray | torch.Tensor) -> torch.Tensor:
    if isinstance(values, torch.Tensor):
        return values.detach().clone().float()
    return torch.from_numpy(np.ascontiguousarray(values, dtype=np.float32))


def permutation_importance(
    model: FloodSenseLSTM,
    sequences: np.ndarray,
    statics: np.ndarray,
    labels: np.ndarray,
    *,
    n_repeats: int = 3,
    seed: int = 0,
    batch_size: int = 1024,
) -> list[dict[str, float]]:
    """Global channel importance by PR-AUC drop under permutation.

    Slower than attribution and model-agnostic.  Use it to sanity-check
    that the model leans on rainfall dynamics rather than, say, the station
    identity encoded in the coordinates.
    """
    from sklearn.metrics import average_precision_score

    model.eval()
    rng = np.random.default_rng(seed)

    def score(seq: np.ndarray, stat: np.ndarray) -> float:
        probs = []
        with torch.no_grad():
            for start in range(0, len(seq), batch_size):
                s = torch.from_numpy(seq[start : start + batch_size])
                t = torch.from_numpy(stat[start : start + batch_size])
                probs.append(torch.sigmoid(model(s, t)).numpy())
        return float(average_precision_score(labels, np.concatenate(probs)))

    baseline = score(sequences, statics)
    names = model.feature_names or [
        f"feature_{i}" for i in range(sequences.shape[2])
    ]

    rows = []
    for channel, name in enumerate(names):
        drops = []
        for _ in range(n_repeats):
            shuffled = sequences.copy()
            order = rng.permutation(len(shuffled))
            shuffled[:, :, channel] = shuffled[order, :, channel]
            drops.append(baseline - score(shuffled, statics))
        rows.append(
            {
                "feature": name,
                "mean_pr_auc_drop": float(np.mean(drops)),
                "std": float(np.std(drops)),
            }
        )

    rows.sort(key=lambda r: r["mean_pr_auc_drop"], reverse=True)
    return rows
