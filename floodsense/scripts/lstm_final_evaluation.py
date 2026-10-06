#!/usr/bin/env python3
"""Evaluate the swept LSTM once on the test split.

    python scripts/lstm_final_evaluation.py --days 540 --stations 32 --seed 20261006

Reads the winner recorded by ``scripts/lstm_sweep.py`` (chosen on validation
PR-AUC), re-selects the operating threshold on validation inside the
accuracy band, runs the leakage audit, and only then scores the test split -
once.

Writes ``results/lstm_final_metrics.json``,
``results/lstm_confusion_matrix.json`` and
``results/lstm_accuracy_vs_threshold_test.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--seed", type=int, default=20261006)
    p.add_argument("--sweep", default="artifacts/lstm_sweep")
    p.add_argument("--results", default="results")
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def load_selection(sweep: Path) -> dict:
    path = sweep / "selected.json"
    if not path.exists():
        raise SystemExit(f"{path} missing; run scripts/lstm_sweep.py first")
    return json.loads(path.read_text())


def build_config(selection: dict, args: argparse.Namespace) -> Config:
    cfg = Config()
    cfg.operating_point = "accuracy"
    cfg.train.seed = args.seed
    cfg.windows.seed = args.seed
    cfg.windows.sequence_steps = int(selection.get("sequence_steps", 36))
    if "hidden_size" in selection:
        cfg.model.hidden_size = int(selection["hidden_size"])
    if "num_layers" in selection:
        cfg.model.num_layers = int(selection["num_layers"])
    if "dropout" in selection:
        cfg.model.dropout = float(selection["dropout"])
    if "last_step_skip" in selection:
        cfg.model.last_step_skip = bool(selection["last_step_skip"])
    if "negative_keep_rate" in selection:
        cfg.windows.negative_keep_rate = float(selection["negative_keep_rate"])
    return cfg


def member_directories(sweep: Path, name: str) -> list[Path]:
    """The checkpoint directories backing the selection.

    An ensemble name carries ``_ensemble_x<N>``; its members were trained as
    ``<base>_s0 .. _s<N-1>``.
    """
    if "_ensemble_x" in name:
        base, _, count = name.partition("_ensemble_x")
        return [sweep / f"{base}_s{k}" for k in range(int(count))]
    return [sweep / name]


def score(dirs: list[Path], prepared, split: str) -> np.ndarray:
    """Mean predicted probability over the member models."""
    from floodsense.model import FloodSenseLSTM
    from floodsense.train import predict, resolve_device

    device = resolve_device("cpu")
    loader_data = prepared.dataset(split)
    outputs = []
    for directory in dirs:
        checkpoint = directory / "floodsense_lstm.pt"
        if not checkpoint.exists():
            raise SystemExit(f"missing checkpoint {checkpoint}")
        model = FloodSenseLSTM.load(checkpoint)
        probs, _, _ = predict(model, DataLoader(loader_data, batch_size=4096), device)
        outputs.append(probs)
    return np.mean(outputs, axis=0)


def main() -> int:
    args = parse_args()
    sweep = Path(args.sweep)
    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)

    selection = load_selection(sweep)
    cfg = build_config(selection, args)
    dirs = member_directories(sweep, selection["name"])

    print(f"[final] selected on validation: {selection['name']}")
    print(f"[final] members: {[d.name for d in dirs]}")

    from floodsense.pipeline import prepare_from_synthetic
    from floodsense.synthetic import SyntheticConfig

    print("[final] rebuilding the dataset...")
    prepared = prepare_from_synthetic(
        cfg,
        SyntheticConfig(days=args.days, n_stations=args.stations, seed=args.seed),
    )

    from floodsense.audit import run_audit
    from floodsense.distribution import build_report
    from floodsense.events import event_level_report, threshold_for_accuracy_band
    from floodsense.experiments import labels_for
    from floodsense.metrics import compute_report

    event_kwargs = dict(
        horizon_max_minutes=cfg.labels.horizon_max_minutes,
        merge_gap_minutes=cfg.labels.post_alert_blackout_minutes,
    )

    print("[final] scoring VALIDATION to fix the threshold...")
    y_val = labels_for(prepared, prepared.splits.val)
    val_probs = score(dirs, prepared, "val")
    chosen = threshold_for_accuracy_band(
        prepared.splits.val, y_val, val_probs,
        cfg.accuracy_band[0], cfg.accuracy_band[1],
        prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
    )
    threshold = float(chosen["threshold"])
    val_report = compute_report(y_val, val_probs, threshold)
    val_events = chosen["event_report"]
    print(
        f"        threshold {threshold:.6f} | val accuracy "
        f"{val_report.accuracy_not_a_headline_metric:.2%} | "
        f"val event recall {val_events.event_recall:.3f}"
    )

    provenance = {
        "selected_on": "validation",
        "rule": chosen["selected_by"],
        "threshold": threshold,
        "accuracy_band": list(cfg.accuracy_band),
        "validation_accuracy": val_report.accuracy_not_a_headline_metric,
    }

    print("[final] leakage audit...")
    from floodsense.synthetic import generate

    alerts = generate(
        SyntheticConfig(days=args.days, n_stations=args.stations, seed=args.seed)
    ).alerts
    audit = run_audit(prepared, cfg, alerts=alerts, threshold_provenance=provenance)
    print(audit.markdown())
    audit.write(results_dir / "lstm_leakage_audit.json")
    if audit.status != "PASS" and not args.force:
        raise SystemExit("leakage audit failed; test metrics withheld")

    print("\n[final] TEST split, read once...")
    y_test = labels_for(prepared, prepared.splits.test)
    test_probs = score(dirs, prepared, "test")
    report = compute_report(y_test, test_probs, threshold)
    events = event_level_report(
        prepared.splits.test, y_test, test_probs, threshold,
        prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
    )

    if report.degenerate_single_class:
        raise SystemExit(
            "test split holds one class only; refusing to report accuracy"
        )

    shift = build_report(prepared, data_source="synthetic")
    shift.write(results_dir / "lstm_distribution_shift.json")

    test_period = (
        f"{prepared.grid.times[int(prepared.splits.test[:, 0].min())]} to "
        f"{prepared.grid.times[int(prepared.splits.test[:, 0].max())]}"
    )

    final = {
        "model": f"FloodSense LSTM ({selection['name']})",
        "model_family": "LSTM with attention pooling and a last-step skip",
        "data_source": (
            f"SYNTHETIC (floodsense.synthetic, days={args.days}, "
            f"stations={args.stations}, seed={args.seed}) - data.gov.sg "
            "unreachable, so real Singapore data could not be used"
        ),
        "synthetic_data": True,
        "test_period": test_period,
        "threshold": threshold,
        "operating_point": "accuracy",
        "accuracy_band_target": list(cfg.accuracy_band),
        "accuracy": float(report.accuracy_not_a_headline_metric),
        "accuracy_in_target_band": bool(
            cfg.accuracy_band[0]
            <= report.accuracy_not_a_headline_metric
            <= cfg.accuracy_band[1]
        ),
        "event_recall": float(events.event_recall),
        "event_recall_target": 0.80,
        "event_recall_meets_target": bool(events.event_recall >= 0.80),
        "precision": float(report.precision),
        "recall": float(report.recall),
        "f1": float(report.f1),
        "pr_auc": float(report.pr_auc),
        "roc_auc": float(report.roc_auc),
        "brier": float(report.brier),
        "mean_lead_time_minutes": float(events.mean_lead_minutes),
        "median_lead_time_minutes": float(events.median_lead_minutes),
        "false_alarms_per_station_day": float(events.false_alarms_per_station_day),
        "alarm_precision": float(events.precision_by_alarm),
        "tp": int(report.true_positive),
        "fp": int(report.false_positive),
        "tn": int(report.true_negative),
        "fn": int(report.false_negative),
        "n_test_samples": int(report.n_samples),
        "n_test_events": int(events.n_events),
        "n_events_detected": int(events.n_detected),
        "total_alarms": int(events.n_alarms),
        "false_alarms": int(events.n_false_alarms),
        "station_days": float(events.station_days),
        "base_rate": float(report.base_rate),
        "constant_negative_accuracy": float(1.0 - report.base_rate),
        "degenerate_single_class": bool(report.degenerate_single_class),
        "validation_accuracy": float(val_report.accuracy_not_a_headline_metric),
        "validation_event_recall": float(val_events.event_recall),
        "validation_pr_auc": float(val_report.pr_auc),
        "threshold_provenance": provenance,
        "leakage_audit": audit.status,
        "selection_metric": "validation PR-AUC",
        "disclaimer": (
            "Decision-support prototype. Does not replace official PUB flood "
            "warnings. Metrics measured on synthetic data: they validate the "
            "pipeline, not real-world skill on Singapore rainfall."
        ),
    }
    (results_dir / "lstm_final_metrics.json").write_text(json.dumps(final, indent=2))

    (results_dir / "lstm_confusion_matrix.json").write_text(
        json.dumps(
            {
                "model": final["model"],
                "threshold": threshold,
                "split": "test",
                "test_period": test_period,
                "matrix": {
                    "true_positive": final["tp"], "false_positive": final["fp"],
                    "true_negative": final["tn"], "false_negative": final["fn"],
                },
                "unit": "one station-5-minute interval",
            },
            indent=2,
        )
    )

    curve = []
    for thr in np.unique(np.concatenate([np.linspace(0.0, 1.0, 41), [threshold]])):
        r = compute_report(y_test, test_probs, float(thr))
        ev = event_level_report(
            prepared.splits.test, y_test, test_probs, float(thr),
            prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
        )
        curve.append({
            "threshold": float(thr),
            "accuracy": float(r.accuracy_not_a_headline_metric),
            "precision": float(r.precision), "recall": float(r.recall),
            "f1": float(r.f1), "event_recall": float(ev.event_recall),
            "events_detected": int(ev.n_detected), "n_events": int(ev.n_events),
            "false_alarms_per_station_day": float(ev.false_alarms_per_station_day),
            "mean_lead_minutes": float(ev.mean_lead_minutes),
            "is_selected_threshold": bool(abs(thr - threshold) < 1e-12),
        })
    (results_dir / "lstm_accuracy_vs_threshold_test.json").write_text(
        json.dumps(
            {"model": final["model"], "selected_threshold": threshold,
             "note": "Produced after the threshold was frozen. Reporting only.",
             "curve": curve},
            indent=2,
        )
    )

    print("\n" + "=" * 70)
    print(f"MODEL             {final['model']}")
    print(f"DATA              SYNTHETIC (seed {args.seed}) - not real Singapore data")
    print(f"TEST PERIOD       {test_period}")
    print(f"THRESHOLD         {threshold:.6f}  (chosen on validation)")
    print("-" * 70)
    print(f"TEST ACCURACY     {final['accuracy']*100:.2f}%   target 95-99% -> "
          f"{'IN BAND' if final['accuracy_in_target_band'] else 'OUT OF BAND'}")
    print(f"EVENT RECALL      {final['event_recall']*100:.1f}%  "
          f"({final['n_events_detected']}/{final['n_test_events']})  target >=80% -> "
          f"{'MET' if final['event_recall_meets_target'] else 'NOT MET'}")
    print(f"PR-AUC            {final['pr_auc']:.4f}")
    print(f"ROC-AUC           {final['roc_auc']:.4f}")
    print(f"PRECISION         {final['precision']*100:.2f}%")
    print(f"F1                {final['f1']:.4f}")
    print(f"LEAD TIME         mean {final['mean_lead_time_minutes']:.1f} min, "
          f"median {final['median_lead_time_minutes']:.0f} min")
    print(f"FALSE ALARMS      {final['false_alarms_per_station_day']:.2f} per station-day")
    print(f"CONFUSION         TP {final['tp']}  FP {final['fp']}  "
          f"TN {final['tn']}  FN {final['fn']}")
    print(f"BASE RATE         {final['base_rate']:.5f} (all-negative accuracy "
          f"{final['constant_negative_accuracy']*100:.2f}%)")
    print(f"LEAKAGE AUDIT     {audit.status}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
