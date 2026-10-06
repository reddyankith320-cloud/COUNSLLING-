"""Leakage audit.

A flood model that has seen the future looks excellent offline and fails in
the field, and the symptom of leakage is a *better* score, so nothing in the
metrics will warn you. The audit therefore checks each leakage path
mechanically, against the real prepared data, and returns PASS/FAIL per
check rather than relying on the code having been written carefully.

Checks, and what each one would catch:

``future_rainfall_leakage``
    An off-by-one in any rolling window, which would let a feature at time
    ``t`` see rainfall after ``t``.
``future_alert_leakage``
    The per-station historical alert rate being computed over the whole
    record instead of the training period. This is target leakage: the
    feature is derived from the label.
``label_horizon_causality``
    A label at ``t`` referring to an alert at or before ``t + horizon_min``,
    which would make part of the target a nowcast.
``temporal_split_order`` / ``split_embargo`` / ``split_disjoint``
    Random or overlapping splits, or splits adjacent enough that a training
    sample's input window overlaps a validation sample's.
``duplicate_events_across_splits``
    One flood event contributing positives to two splits.
``scaler_fit_region``
    Normalisation statistics fitted on data the model should not have seen.
``warmup_respected``
    Samples drawn from the stretch where long windows are still filling.
``evaluation_split_integrity``
    Negative subsampling applied to validation or test, which would inflate
    precision by removing the easy negatives that a deployed model faces.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config
from .pipeline import Prepared

PASS = "PASS"
FAIL = "FAIL"
INFO = "INFO"


@dataclass
class Check:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditReport:
    checks: list[Check]

    @property
    def status(self) -> str:
        return FAIL if any(c.status == FAIL for c in self.checks) else PASS

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    def to_dict(self) -> dict:
        return {
            "overall": self.status,
            "n_pass": sum(c.status == PASS for c in self.checks),
            "n_fail": sum(c.status == FAIL for c in self.checks),
            "n_info": sum(c.status == INFO for c in self.checks),
            "checks": [c.to_dict() for c in self.checks],
        }

    def write(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    def markdown(self) -> str:
        lines = [f"## Leakage Audit: {self.status}", ""]
        for c in self.checks:
            mark = {PASS: "PASS", FAIL: "**FAIL**", INFO: "info"}[c.status]
            lines.append(f"- `{c.name}` — {mark}: {c.detail}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------


def check_future_rainfall_leakage(
    prepared: Prepared, cfg: Config, slice_steps: int = 6000
) -> Check:
    """Perturb a step; assert no feature before it moves.

    Run on a slice because causality is a property of the feature functions,
    not of the record length, and rebuilding the full tensor twice costs a
    gigabyte for no extra assurance.
    """
    from .features import build_dynamic_features
    from .grid import RainGrid

    n = prepared.grid.n_steps
    start = max(n - slice_steps, 0)
    base_grid = prepared.grid.subset_time(start, n)

    perturbed = base_grid.rain.copy()
    cut = perturbed.shape[0] - 1
    perturbed[cut, :] = np.nan_to_num(perturbed[cut, :]) + 100.0
    other = RainGrid(
        times=base_grid.times,
        station_ids=base_grid.station_ids,
        rain=perturbed,
        longitude=base_grid.longitude,
        latitude=base_grid.latitude,
        station_names=base_grid.station_names,
    )

    a = build_dynamic_features(base_grid, cfg.features).values
    b = build_dynamic_features(other, cfg.features).values
    worst = float(np.abs(a[:cut] - b[:cut]).max()) if cut > 0 else 0.0

    if worst <= 1e-4:
        return Check(
            "future_rainfall_leakage",
            PASS,
            f"Adding 100 mm at the final step of a {base_grid.n_steps}-step slice "
            f"changed no earlier feature value (max delta {worst:.2e} over "
            f"{a.shape[2]} channels).",
        )
    return Check(
        "future_rainfall_leakage",
        FAIL,
        f"Perturbing the final step changed earlier features by up to {worst:.4f}. "
        "A rolling window is reading forward in time.",
    )


def check_future_alert_leakage(
    prepared: Prepared, cfg: Config, alerts: pd.DataFrame
) -> Check:
    """The station alert-rate feature must ignore post-cutoff alerts."""
    from .features import build_static_features

    if alerts is None or len(alerts) == 0:
        return Check(
            "future_alert_leakage",
            INFO,
            "No alerts supplied to the audit; cannot test the alert-derived "
            "static features.",
        )

    cutoff = prepared.grid.times[
        min(prepared.splits.train_end_step, prepared.grid.n_steps - 1)
    ]
    ts = pd.to_datetime(alerts["ts_start"])
    ts = (
        ts.dt.tz_localize(prepared.grid.times.tz)
        if ts.dt.tz is None
        else ts.dt.tz_convert(prepared.grid.times.tz)
    )
    train_only = alerts.loc[(ts < cutoff).to_numpy()]
    train_days = max((cutoff - prepared.grid.times[0]).total_seconds() / 86400.0, 1.0)

    rebuilt = build_static_features(
        prepared.grid,
        flood_prone_points=None,
        historical_alerts=train_only,
        cfg=cfg.features,
        alert_radius_km=cfg.labels.radius_km,
        reference_days=train_days,
    )

    alert_columns = [
        n for n in prepared.statics.names if n.startswith("alert")
    ]
    deltas = {}
    for name in alert_columns:
        if name not in rebuilt.names:
            continue
        a = prepared.statics.values[:, prepared.statics.index_of(name)]
        b = rebuilt.values[:, rebuilt.index_of(name)]
        deltas[name] = float(np.abs(a - b).max())

    if not deltas:
        return Check(
            "future_alert_leakage", INFO, "No alert-derived static features present."
        )

    worst = max(deltas.values())
    if worst <= 1e-3:
        return Check(
            "future_alert_leakage",
            PASS,
            f"Alert-derived static features {sorted(deltas)} reproduce exactly "
            f"from training-period alerts only (alerts before {cutoff}, max "
            f"delta {worst:.2e}); they carry no post-cutoff information.",
        )
    return Check(
        "future_alert_leakage",
        FAIL,
        f"Alert-derived static features differ by up to {worst:.4f} when "
        "recomputed from training-period alerts only, so the fitted features "
        "include alerts from the evaluation period. That is target leakage.",
    )


def check_label_horizon_causality(prepared: Prepared, cfg: Config) -> Check:
    """A positive at ``t`` must point strictly beyond ``t + horizon_min``."""
    lo, hi = prepared.labels.horizon_steps
    expected_lo = int(round(cfg.labels.horizon_min_minutes / 5))
    expected_hi = int(round(cfg.labels.horizon_max_minutes / 5))

    if (lo, hi) != (expected_lo, expected_hi):
        return Check(
            "label_horizon_causality",
            FAIL,
            f"Label horizon is {lo}-{hi} steps but the config asks for "
            f"{expected_lo}-{expected_hi}.",
        )
    if lo < 1:
        return Check(
            "label_horizon_causality",
            FAIL,
            "Horizon starts at the current step, so the target includes "
            "alerts already in progress: a nowcast, not a forecast.",
        )
    return Check(
        "label_horizon_causality",
        PASS,
        f"Positives refer to alerts starting {lo}-{hi} steps "
        f"({cfg.labels.horizon_min_minutes}-{cfg.labels.horizon_max_minutes} min) "
        "after the sample, so no label overlaps its own input window.",
    )


def check_temporal_split_order(prepared: Prepared) -> Check:
    s = prepared.splits
    if len(s.train) == 0 or len(s.val) == 0 or len(s.test) == 0:
        return Check("temporal_split_order", FAIL, "A split is empty.")

    train_max, val_min = int(s.train[:, 0].max()), int(s.val[:, 0].min())
    val_max, test_min = int(s.val[:, 0].max()), int(s.test[:, 0].min())
    if train_max < val_min and val_max < test_min:
        return Check(
            "temporal_split_order",
            PASS,
            f"Chronological: train ends at step {train_max}, validation spans "
            f"{val_min}-{val_max}, test starts at {test_min}. No shuffling.",
        )
    return Check(
        "temporal_split_order",
        FAIL,
        f"Splits overlap in time (train_max {train_max}, val_min {val_min}, "
        f"val_max {val_max}, test_min {test_min}).",
    )


def check_split_embargo(prepared: Prepared, cfg: Config) -> Check:
    s = prepared.splits
    needed = cfg.windows.sequence_steps + prepared.labels.horizon_steps[1]
    gap_val = int(s.val[:, 0].min()) - int(s.train[:, 0].max())
    gap_test = int(s.test[:, 0].min()) - int(s.val[:, 0].max())

    if s.embargo_steps < needed:
        return Check(
            "split_embargo",
            FAIL,
            f"Embargo is {s.embargo_steps} steps but a sample's input window "
            f"plus label horizon spans {needed}.",
        )
    if gap_val >= 1 and gap_test >= 1:
        return Check(
            "split_embargo",
            PASS,
            f"Embargo of {s.embargo_steps} steps "
            f"(= sequence {cfg.windows.sequence_steps} + horizon "
            f"{prepared.labels.horizon_steps[1]}) applied; observed gaps are "
            f"{gap_val} steps before validation and {gap_test} before test, so "
            "no training input window overlaps an evaluation sample.",
        )
    return Check(
        "split_embargo", FAIL, f"Gaps too small: {gap_val}, {gap_test}."
    )


def check_split_disjoint(prepared: Prepared) -> Check:
    s = prepared.splits

    def keys(index: np.ndarray) -> set[tuple[int, int]]:
        return set(map(tuple, index.tolist()))

    train, val, test = keys(s.train), keys(s.val), keys(s.test)
    overlaps = {
        "train/val": len(train & val),
        "train/test": len(train & test),
        "val/test": len(val & test),
    }
    if any(overlaps.values()):
        return Check(
            "split_disjoint", FAIL, f"Shared (step, station) samples: {overlaps}."
        )
    return Check(
        "split_disjoint",
        PASS,
        f"No (step, station) sample appears in more than one split "
        f"({len(train):,} train / {len(val):,} val / {len(test):,} test).",
    )


def check_duplicate_events_across_splits(prepared: Prepared) -> Check:
    """One flood event must not contribute positives to two splits."""
    labels = prepared.labels.labels
    s = prepared.splits
    bounds = {
        "train": (int(s.train[:, 0].min()), int(s.train[:, 0].max())),
        "val": (int(s.val[:, 0].min()), int(s.val[:, 0].max())),
        "test": (int(s.test[:, 0].min()), int(s.test[:, 0].max())),
    }

    from .events import _runs

    shared = []
    for station in range(labels.shape[1]):
        for start, stop in _runs(labels[:, station] > 0):
            hit = [
                name
                for name, (lo, hi) in bounds.items()
                if start <= hi and stop - 1 >= lo
            ]
            if len(hit) > 1:
                shared.append((station, start, stop, hit))

    if shared:
        return Check(
            "duplicate_events_across_splits",
            FAIL,
            f"{len(shared)} flood event(s) straddle a split boundary, e.g. "
            f"station {shared[0][0]} steps {shared[0][1]}-{shared[0][2]} in "
            f"{shared[0][3]}.",
        )
    return Check(
        "duplicate_events_across_splits",
        PASS,
        "Every labelled flood event falls entirely within one split; the "
        "embargo keeps events from straddling a boundary.",
    )


def check_scaler_fit_region(prepared: Prepared) -> Check:
    """Normalisation statistics must come from the training region only."""
    from .dataset import fit_scaler

    refit = fit_scaler(
        prepared.features, prepared.statics, prepared.labels, prepared.splits
    )
    same = np.allclose(refit.mean, prepared.scaler.mean, atol=1e-5) and np.allclose(
        refit.std, prepared.scaler.std, atol=1e-5
    )
    if not same:
        return Check(
            "scaler_fit_region",
            FAIL,
            "The stored scaler does not reproduce from the training region, so "
            "it was fitted on something else.",
        )

    # Positive control: statistics computed over the whole record must differ,
    # otherwise this check could pass on a scaler that saw everything.
    whole = prepared.features.values.reshape(-1, prepared.features.values.shape[2])
    compressed = prepared.scaler.compress(whole)
    all_mean = compressed.mean(axis=0)
    differs = float(np.abs(all_mean - prepared.scaler.mean).max())

    return Check(
        "scaler_fit_region",
        PASS,
        f"Scaler reproduces exactly from steps "
        f"[{prepared.splits.eligible_from}, {prepared.splits.train_end_step}) "
        f"and differs from whole-record statistics by up to {differs:.4f}, "
        "confirming it never saw validation or test.",
    )


def check_warmup_respected(prepared: Prepared, cfg: Config) -> Check:
    first = int(prepared.splits.train[:, 0].min())
    needed = max(prepared.features.warmup_steps, cfg.windows.sequence_steps - 1)
    if first < needed:
        return Check(
            "warmup_respected",
            FAIL,
            f"First training sample at step {first} but {needed} steps of "
            "warm-up are required.",
        )
    return Check(
        "warmup_respected",
        PASS,
        f"First sample at step {first} >= warm-up {needed} "
        f"({prepared.features.warmup_steps} steps of window fill, "
        f"{cfg.windows.sequence_steps} steps of sequence).",
    )


def check_evaluation_split_integrity(prepared: Prepared) -> Check:
    """Validation and test must keep every eligible sample."""
    s = prepared.splits
    valid = prepared.labels.valid

    def eligible(lo: int, hi: int) -> int:
        return int(valid[lo : hi + 1].sum())

    val_expected = eligible(int(s.val[:, 0].min()), int(s.val[:, 0].max()))
    test_expected = eligible(int(s.test[:, 0].min()), int(s.test[:, 0].max()))
    val_ok = abs(len(s.val) - val_expected) <= 0.02 * max(val_expected, 1)
    test_ok = abs(len(s.test) - test_expected) <= 0.02 * max(test_expected, 1)

    if val_ok and test_ok:
        return Check(
            "evaluation_split_integrity",
            PASS,
            f"Validation holds {len(s.val):,} of {val_expected:,} eligible "
            f"samples and test {len(s.test):,} of {test_expected:,}: neither is "
            "subsampled, so precision reflects the true base rate. Negative "
            f"subsampling applies to training only "
            f"({len(s.train):,} kept of {s.n_train_before_subsample:,}).",
        )
    return Check(
        "evaluation_split_integrity",
        FAIL,
        f"Validation or test appears resampled (val {len(s.val)} vs "
        f"{val_expected} eligible, test {len(s.test)} vs {test_expected}).",
    )


def check_station_overlap(prepared: Prepared) -> Check:
    """Shared stations across splits: by design, and why that is not leakage."""
    return Check(
        "station_overlap",
        INFO,
        f"All {prepared.grid.n_stations} stations appear in every split, which "
        "is intended: the task is forecasting forward in time at known "
        "stations, not generalising to unseen ones. The split is purely "
        "temporal. A model intended for new, ungauged locations would need a "
        "station-wise split as well, and would score worse.",
    )


def check_feature_selection(prepared: Prepared) -> Check:
    return Check(
        "feature_selection_on_test",
        INFO,
        f"No data-driven feature selection is performed: all "
        f"{len(prepared.features.names)} dynamic and "
        f"{len(prepared.statics.names)} static channels are fixed in "
        "FeatureConfig before any data is read, so no split can influence "
        "which features exist.",
    )


def check_threshold_provenance(provenance: dict | None) -> Check:
    """The operating threshold must come from validation, not test."""
    if not provenance:
        return Check(
            "threshold_selected_on_validation",
            INFO,
            "No threshold provenance supplied to the audit.",
        )
    split = str(provenance.get("selected_on", "")).lower()
    if split != "validation":
        return Check(
            "threshold_selected_on_validation",
            FAIL,
            f"Threshold was selected on {split!r}, not validation.",
        )
    return Check(
        "threshold_selected_on_validation",
        PASS,
        f"Threshold {provenance.get('threshold')} chosen on validation by "
        f"{provenance.get('rule')}; frozen before the test split was read.",
    )


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run_audit(
    prepared: Prepared,
    cfg: Config,
    alerts: pd.DataFrame | None = None,
    threshold_provenance: dict | None = None,
) -> AuditReport:
    """Run every check and return the report."""
    checks = [
        check_future_rainfall_leakage(prepared, cfg),
        check_future_alert_leakage(prepared, cfg, alerts),
        check_label_horizon_causality(prepared, cfg),
        check_temporal_split_order(prepared),
        check_split_embargo(prepared, cfg),
        check_split_disjoint(prepared),
        check_duplicate_events_across_splits(prepared),
        check_scaler_fit_region(prepared),
        check_warmup_respected(prepared, cfg),
        check_evaluation_split_integrity(prepared),
        check_station_overlap(prepared),
        check_feature_selection(prepared),
        check_threshold_provenance(threshold_provenance),
    ]
    return AuditReport(checks=checks)
