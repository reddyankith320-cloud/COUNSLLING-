"""Distribution-shift report across the chronological splits.

The synthetic run made the case for this module: a threshold chosen on
validation at 95.25% accuracy / 82.2% event recall landed on test at 98.24% /
68.6%, purely because the test period was drier. Nothing was wrong with the
model or the split — accuracy at a fixed threshold simply depends on the base
rate, and the base rate moved.

A chronological split on weather data *guarantees* some of this: the splits
are different seasons. So the shift is measured and reported rather than
discovered afterwards in a confusing metric.

What is compared across train / validation / test:

* event prevalence — the single number that moves an accuracy operating point
* rainfall distribution — mean, wet-interval share, quantiles, dry spells
* flood-event structure — count, events per station-day, duration
* station coverage — reporting completeness, which differs by era in real data
* seasonal and monsoon composition — which months each split actually contains

Nothing here reads labels for *fitting*. It is a descriptive report, produced
alongside the frozen evaluation, and it is explicitly allowed to describe the
test split: describing a split is not selecting on it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .pipeline import Prepared
from .schema import STEP_MINUTES

#: Singapore's two monsoon seasons, by month.
NORTHEAST_MONSOON = (12, 1, 2, 3)
SOUTHWEST_MONSOON = (6, 7, 8, 9)


@dataclass
class SplitProfile:
    """Everything measured about one split."""

    name: str
    start: str
    end: str
    n_samples: int
    n_steps: int
    n_stations: int
    station_days: float

    n_positive: int
    event_prevalence: float
    #: Prevalence over *every eligible* cell in the split's time range,
    #: ignoring negative subsampling. The training split is subsampled, so
    #: its sampled prevalence is an artefact of that choice and is not
    #: comparable with validation or test - this field is.
    event_prevalence_unsampled: float
    subsampled: bool
    n_events: int
    events_per_station_day: float
    mean_event_length_steps: float

    rain_mean_mm_per_step: float
    rain_wet_share: float
    rain_p50_wet: float
    rain_p95_wet: float
    rain_p99_wet: float
    rain_total_mm_per_station: float
    mean_dry_spell_steps: float
    observed_share: float

    months: dict[str, int] = field(default_factory=dict)
    northeast_monsoon_share: float = 0.0
    southwest_monsoon_share: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ShiftReport:
    profiles: list[SplitProfile]
    comparisons: dict[str, dict[str, float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    data_source: str = ""

    def to_dict(self) -> dict:
        return {
            "data_source": self.data_source,
            "profiles": [p.to_dict() for p in self.profiles],
            "comparisons": self.comparisons,
            "warnings": self.warnings,
            "note": (
                "Descriptive only. Computed after the model and threshold were "
                "frozen; describing a split is not selecting on it."
            ),
        }

    def write(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    def summary(self) -> str:
        rows = [
            f"{'split':<12} {'period':<26} {'events':>7} {'prevalence':>11} "
            f"{'wet share':>10} {'mm/step':>9}  note",
        ]
        for p in self.profiles:
            period = f"{p.start[:10]} to {p.end[:10]}"
            note = "negatives subsampled" if p.subsampled else ""
            rows.append(
                f"{p.name:<12} {period:<26} {p.n_events:>7} "
                f"{p.event_prevalence_unsampled:>11.5f} {p.rain_wet_share:>10.4f} "
                f"{p.rain_mean_mm_per_step:>9.5f}  {note}"
            )
        if self.comparisons:
            rows.append("")
            for key, value in self.comparisons.items():
                rows.append(f"  {key}: {value}")
        for warning in self.warnings:
            rows.append(f"  WARNING: {warning}")
        return "\n".join(rows)


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    from .events import _runs as runs

    return runs(flags)


def profile_split(
    prepared: Prepared, name: str, index: np.ndarray
) -> SplitProfile:
    """Measure one split."""
    grid = prepared.grid
    labels = prepared.labels.labels

    t_lo, t_hi = int(index[:, 0].min()), int(index[:, 0].max())
    times = grid.times[t_lo : t_hi + 1]
    rain = grid.rain[t_lo : t_hi + 1]
    observed = ~np.isnan(rain)
    filled = np.where(observed, rain, 0.0)

    y = labels[index[:, 0], index[:, 1]]
    n_positive = int(y.sum())

    # Prevalence over the whole eligible region, so splits stay comparable
    # even when one of them was subsampled for training.
    valid_region = prepared.labels.valid[t_lo : t_hi + 1]
    labels_region = labels[t_lo : t_hi + 1]
    n_eligible = int(valid_region.sum())
    n_eligible_positive = int(labels_region[valid_region].sum())
    prevalence_unsampled = (
        float(n_eligible_positive / n_eligible) if n_eligible else 0.0
    )
    subsampled = n_eligible > 0 and abs(len(index) - n_eligible) > 0.02 * n_eligible

    stations = np.unique(index[:, 1])
    n_events, lengths = 0, []
    for station in stations:
        for start, stop in _runs(labels[t_lo : t_hi + 1, station] > 0):
            n_events += 1
            lengths.append(stop - start)

    station_days = float(observed.sum()) * STEP_MINUTES / (60.0 * 24.0)
    wet = filled[observed & (filled > 0.0)]

    months = pd.Series(times.month).value_counts().sort_index()
    month_counts = {str(int(k)): int(v) for k, v in months.items()}
    total_steps = max(len(times), 1)
    ne = sum(v for k, v in month_counts.items() if int(k) in NORTHEAST_MONSOON)
    sw = sum(v for k, v in month_counts.items() if int(k) in SOUTHWEST_MONSOON)

    dry_spells = []
    for s in range(rain.shape[1]):
        wet_flags = filled[:, s] >= 0.2
        gaps = _runs(~wet_flags)
        dry_spells.extend(stop - start for start, stop in gaps)

    return SplitProfile(
        name=name,
        start=str(times[0]),
        end=str(times[-1]),
        n_samples=int(len(index)),
        n_steps=int(len(times)),
        n_stations=int(len(stations)),
        station_days=station_days,
        n_positive=n_positive,
        event_prevalence=float(n_positive / len(index)) if len(index) else 0.0,
        event_prevalence_unsampled=prevalence_unsampled,
        subsampled=subsampled,
        n_events=n_events,
        events_per_station_day=float(n_events / station_days) if station_days else 0.0,
        mean_event_length_steps=float(np.mean(lengths)) if lengths else 0.0,
        rain_mean_mm_per_step=float(filled[observed].mean()) if observed.any() else 0.0,
        rain_wet_share=float((filled[observed] > 0).mean()) if observed.any() else 0.0,
        rain_p50_wet=float(np.percentile(wet, 50)) if wet.size else 0.0,
        rain_p95_wet=float(np.percentile(wet, 95)) if wet.size else 0.0,
        rain_p99_wet=float(np.percentile(wet, 99)) if wet.size else 0.0,
        rain_total_mm_per_station=(
            float(filled.sum() / rain.shape[1]) if rain.shape[1] else 0.0
        ),
        mean_dry_spell_steps=float(np.mean(dry_spells)) if dry_spells else 0.0,
        observed_share=float(observed.mean()),
        months=month_counts,
        northeast_monsoon_share=float(ne / total_steps),
        southwest_monsoon_share=float(sw / total_steps),
    )


def build_report(prepared: Prepared, data_source: str = "") -> ShiftReport:
    """Profile every split and flag the shifts that move an operating point."""
    splits = {
        "train": prepared.splits.train,
        "validation": prepared.splits.val,
        "test": prepared.splits.test,
    }
    profiles = [
        profile_split(prepared, name, index)
        for name, index in splits.items()
        if len(index)
    ]
    report = ShiftReport(profiles=profiles, data_source=data_source)
    by_name = {p.name: p for p in profiles}

    if "validation" in by_name and "test" in by_name:
        val, test = by_name["validation"], by_name["test"]

        ratio = (
            test.event_prevalence_unsampled / val.event_prevalence_unsampled
            if val.event_prevalence_unsampled > 0
            else float("nan")
        )
        report.comparisons["test_vs_validation_prevalence_ratio"] = round(float(ratio), 4)
        report.comparisons["validation_event_prevalence"] = round(
            val.event_prevalence_unsampled, 6
        )
        report.comparisons["test_event_prevalence"] = round(
            test.event_prevalence_unsampled, 6
        )
        report.comparisons["validation_wet_share"] = round(val.rain_wet_share, 5)
        report.comparisons["test_wet_share"] = round(test.rain_wet_share, 5)
        report.comparisons["test_vs_validation_rain_ratio"] = round(
            float(test.rain_mean_mm_per_step / val.rain_mean_mm_per_step)
            if val.rain_mean_mm_per_step > 0
            else float("nan"),
            4,
        )

        if np.isfinite(ratio) and (ratio < 0.7 or ratio > 1.43):
            report.warnings.append(
                f"Event prevalence differs by {ratio:.2f}x between validation "
                f"and test ({val.event_prevalence_unsampled:.5f} -> "
                f"{test.event_prevalence_unsampled:.5f}). An accuracy-based operating "
                "point will not transfer cleanly: at these base rates accuracy "
                "is close to 1 - false-positive rate, so the drier split reads "
                "as more accurate and less sensitive at the same threshold."
            )

        shared_months = set(val.months) & set(test.months)
        if not shared_months:
            report.warnings.append(
                f"Validation and test share no calendar months "
                f"(validation {sorted(val.months)}, test {sorted(test.months)}). "
                "A chronological split on weather data compares seasons, so "
                "some shift is structural rather than a defect."
            )

        if abs(val.northeast_monsoon_share - test.northeast_monsoon_share) > 0.3:
            report.warnings.append(
                "Northeast-monsoon share differs markedly between validation "
                f"({val.northeast_monsoon_share:.0%}) and test "
                f"({test.northeast_monsoon_share:.0%})."
            )

        if abs(val.observed_share - test.observed_share) > 0.1:
            report.warnings.append(
                f"Station reporting completeness differs: validation "
                f"{val.observed_share:.1%} of slots observed, test "
                f"{test.observed_share:.1%}. Gauge coverage changes over time "
                "in real records."
            )

    if "train" in by_name and "validation" in by_name:
        train, val = by_name["train"], by_name["validation"]
        report.comparisons["train_event_prevalence"] = round(
            train.event_prevalence_unsampled, 6
        )
        report.comparisons["train_event_prevalence_as_sampled"] = round(
            train.event_prevalence, 6
        )
        report.comparisons["train_negatives_subsampled"] = bool(train.subsampled)
        report.comparisons["validation_vs_train_prevalence_ratio"] = round(
            float(val.event_prevalence_unsampled / train.event_prevalence_unsampled)
            if train.event_prevalence_unsampled > 0
            else float("nan"),
            4,
        )

    for profile in profiles:
        if profile.n_events < 30:
            report.warnings.append(
                f"The {profile.name} split holds only {profile.n_events} flood "
                "events; event-level metrics on it carry wide error bars."
            )

    return report
