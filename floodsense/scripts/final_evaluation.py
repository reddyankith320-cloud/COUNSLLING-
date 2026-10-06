#!/usr/bin/env python3
"""Phase 3 — freeze the winner, audit, then read the test split once.

    python scripts/final_evaluation.py --days 540 --stations 32 --seed 20260601

Order of operations, which is the whole point of this script:

1. rebuild the dataset deterministically and check it against the
   fingerprint the experiment phase recorded;
2. score every candidate on **validation** and pick the best by PR-AUC;
3. choose the operating threshold on **validation**, inside the required
   accuracy band, maximising event recall;
4. freeze model and threshold, and run the leakage audit;
5. only then score the **test** split, once.

Writes ``results/final_metrics.json``, ``results/confusion_matrix.json``,
``results/accuracy_vs_threshold_test.json`` and
``results/leakage_audit.json``. The accuracy-vs-threshold curve is produced
*after* the threshold is frozen and is reporting output only — nothing
selects on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--source", choices=("synthetic", "local"), default="synthetic")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--alerts-per-station-month", type=float, default=3.0)
    p.add_argument("--experiments", default="artifacts/experiments")
    p.add_argument(
        "--lstm", default="artifacts/lstm_v5", help="LSTM artifact directory, or ''"
    )
    p.add_argument("--results", default="results")
    p.add_argument(
        "--accuracy-low", type=float, default=None, help="default from config"
    )
    p.add_argument("--accuracy-high", type=float, default=None)
    p.add_argument(
        "--force",
        action="store_true",
        help="write artifacts even if the leakage audit fails",
    )
    return p.parse_args()


def load_prepared(args: argparse.Namespace, cfg: Config):
    if args.source == "synthetic":
        from floodsense.pipeline import prepare_from_synthetic
        from floodsense.synthetic import SyntheticConfig, generate

        synth = SyntheticConfig(
            days=args.days,
            n_stations=args.stations,
            seed=args.seed,
            target_alerts_per_station_month=args.alerts_per_station_month,
        )
        prepared = prepare_from_synthetic(cfg, synth)
        alerts = generate(synth).alerts
        source = (
            f"SYNTHETIC (floodsense.synthetic, days={args.days}, "
            f"stations={args.stations}, seed={args.seed}) - data.gov.sg was "
            "unreachable from this environment"
        )
        return prepared, alerts, source

    from floodsense.ingest.local import load_canonical
    from floodsense.pipeline import prepare

    tables = load_canonical(args.data_dir)
    prepared = prepare(
        readings=tables["readings"],
        stations=tables["stations"],
        alerts=tables["alerts"],
        cfg=cfg,
        flood_prone_points=tables.get("flood_prone_points"),
    )
    return (
        prepared,
        tables["alerts"],
        f"REAL Singapore open data (data.gov.sg) staged at {args.data_dir}",
    )


def check_fingerprint(prepared, path: Path) -> str:
    """Confirm the dataset matches the one the models were fitted on."""
    if not path.exists():
        return "no fingerprint recorded; could not verify the dataset matches"
    saved = json.loads(path.read_text())
    actual = {
        "n_steps": int(prepared.grid.n_steps),
        "n_stations": int(prepared.grid.n_stations),
        "positive_label_sum": float(prepared.labels.labels.sum()),
        "n_dynamic_features": len(prepared.features.names),
    }
    mismatches = {
        k: (saved.get(k), v) for k, v in actual.items() if saved.get(k) != v
    }
    if mismatches:
        raise SystemExit(
            f"dataset does not match the models in {path.parent}: {mismatches}. "
            "Re-run scripts/experiments.py with the same --days/--stations/--seed."
        )
    return "dataset matches the fingerprint recorded during model comparison"


def score_candidates(prepared, cfg, args) -> list:
    """Validation probabilities for every saved candidate."""
    from floodsense.experiments import (
        build_matrices,
        evaluate_on_validation,
        labels_for,
    )

    results = []
    probabilities: dict[str, np.ndarray] = {}

    exp_dir = Path(args.experiments)
    models = sorted(exp_dir.glob("*.joblib"))
    by_kind: dict[str, list[Path]] = {}
    for path in models:
        kind = path.stem.split("__")[-1]
        by_kind.setdefault(kind, []).append(path)

    import joblib

    for kind, paths in by_kind.items():
        matrices = build_matrices(prepared, cfg, kind)
        for path in paths:
            name = path.stem.split("__")[0]
            model = joblib.load(path)
            probs = model.predict_proba(matrices["val"])[:, 1]
            result = evaluate_on_validation(
                prepared,
                cfg,
                probs,
                name=f"{name}:{kind}",
                family=type(model).__module__.split(".")[0],
                feature_kind=kind,
                n_features=matrices["val"].shape[1],
                fit_seconds=0.0,
                params={},
                note="loaded from artifacts/experiments",
            )
            results.append(result)
            probabilities[result.name] = probs
            del model
        del matrices

    if args.lstm:
        lstm_dir = Path(args.lstm)
        checkpoint = lstm_dir / "floodsense_lstm.pt"
        if checkpoint.exists():
            probs = score_lstm(prepared, cfg, checkpoint)
            result = evaluate_on_validation(
                prepared,
                cfg,
                probs,
                name="floodsense_lstm:sequence",
                family="torch",
                feature_kind="sequence",
                n_features=len(prepared.features.names),
                fit_seconds=0.0,
                params={},
                note=f"loaded from {checkpoint}",
            )
            results.append(result)
            probabilities[result.name] = probs
        else:
            print(f"[final] no LSTM checkpoint at {checkpoint}; skipping it")

    return results, probabilities


def score_lstm(prepared, cfg, checkpoint: Path, split: str = "val") -> np.ndarray:
    from torch.utils.data import DataLoader

    from floodsense.model import FloodSenseLSTM
    from floodsense.train import predict, resolve_device

    model = FloodSenseLSTM.load(checkpoint)
    probs, _, _ = predict(
        model,
        DataLoader(prepared.dataset(split), batch_size=4096),
        resolve_device("cpu"),
    )
    return probs


def score_model_on(prepared, cfg, name: str, args, split: str) -> np.ndarray:
    """Probabilities for the chosen model on a named split."""
    base, kind = name.split(":")
    if kind == "sequence":
        return score_lstm(prepared, cfg, Path(args.lstm) / "floodsense_lstm.pt", split)

    import joblib

    from floodsense.experiments import (
        last_step_features,
        window_summary_features,
    )

    model = joblib.load(Path(args.experiments) / f"{base}__{kind}.joblib")
    index = {
        "train": prepared.splits.train,
        "val": prepared.splits.val,
        "test": prepared.splits.test,
    }[split]
    matrix = (
        last_step_features(prepared, index)
        if kind == "last_step"
        else window_summary_features(prepared, index, cfg.windows.sequence_steps)
    )
    return model.predict_proba(matrix)[:, 1]


def main() -> int:
    args = parse_args()
    cfg = Config()
    cfg.train.seed = args.seed
    cfg.windows.seed = args.seed
    cfg.operating_point = "accuracy"
    low = args.accuracy_low if args.accuracy_low is not None else cfg.accuracy_band[0]
    high = (
        args.accuracy_high if args.accuracy_high is not None else cfg.accuracy_band[1]
    )
    cfg.accuracy_band = (low, high)

    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)

    print("[final] step 1/5  rebuild dataset")
    prepared, alerts, data_source = load_prepared(args, cfg)
    fingerprint_note = check_fingerprint(
        prepared, Path(args.experiments) / "fingerprint.json"
    )
    print(f"         {fingerprint_note}")
    print(f"         source: {data_source}")

    from floodsense.events import event_level_report, threshold_for_accuracy_band
    from floodsense.experiments import (
        comparison_markdown,
        labels_for,
        select_best,
        write_comparison,
    )
    from floodsense.metrics import compute_report

    event_kwargs = dict(
        horizon_max_minutes=cfg.labels.horizon_max_minutes,
        merge_gap_minutes=cfg.labels.post_alert_blackout_minutes,
    )

    print("[final] step 2/5  score candidates on VALIDATION")
    results, val_probabilities = score_candidates(prepared, cfg, args)
    if not results:
        raise SystemExit("no candidate models found; run scripts/experiments.py first")
    print("\n" + comparison_markdown(results) + "\n")

    best = select_best(results)
    print(
        f"[final] selected {best.name} on validation PR-AUC {best.val_pr_auc:.4f} "
        f"(event recall {best.val_event_recall:.3f}, F1 {best.val_f1:.3f})"
    )

    print(f"[final] step 3/5  choose threshold on VALIDATION in [{low}, {high}]")
    y_val = labels_for(prepared, prepared.splits.val)
    selection = threshold_for_accuracy_band(
        prepared.splits.val,
        y_val,
        val_probabilities[best.name],
        low,
        high,
        prepared.grid.n_steps,
        prepared.grid.n_stations,
        **event_kwargs,
    )
    threshold = float(selection["threshold"])
    val_report = compute_report(y_val, val_probabilities[best.name], threshold)
    val_events = selection["event_report"]
    print(
        f"         threshold {threshold:.6f} | val accuracy "
        f"{val_report.accuracy_not_a_headline_metric * 100:.2f}% | "
        f"val event recall {val_events.event_recall:.3f} | "
        f"{selection['n_candidates_in_band']} candidates in band | "
        f"rule: {selection['selected_by']}"
    )

    provenance = {
        "selected_on": "validation",
        "rule": selection["selected_by"],
        "threshold": threshold,
        "accuracy_band": [low, high],
        "validation_accuracy": val_report.accuracy_not_a_headline_metric,
    }

    print("[final] step 4/5  leakage audit (model and threshold now frozen)")
    from floodsense.audit import run_audit

    audit = run_audit(prepared, cfg, alerts=alerts, threshold_provenance=provenance)
    audit.write(results_dir / "leakage_audit.json")
    print(audit.markdown())
    if audit.status != "PASS" and not args.force:
        raise SystemExit(
            "\n[final] leakage audit FAILED; refusing to report test metrics. "
            "Fix the findings above, or pass --force if you understand why."
        )

    print("\n[final] step 5/5  TEST split, read once")
    y_test = labels_for(prepared, prepared.splits.test)
    test_probs = score_model_on(prepared, cfg, best.name, args, "test")
    test_report = compute_report(y_test, test_probs, threshold)
    test_events = event_level_report(
        prepared.splits.test,
        y_test,
        test_probs,
        threshold,
        prepared.grid.n_steps,
        prepared.grid.n_stations,
        **event_kwargs,
    )

    test_period = (
        f"{prepared.grid.times[int(prepared.splits.test[:, 0].min())]} to "
        f"{prepared.grid.times[int(prepared.splits.test[:, 0].max())]}"
    )

    final = {
        "accuracy": float(test_report.accuracy_not_a_headline_metric),
        "event_recall": float(test_events.event_recall),
        "precision": float(test_report.precision),
        "f1": float(test_report.f1),
        "pr_auc": float(test_report.pr_auc),
        "roc_auc": float(test_report.roc_auc),
        "threshold": threshold,
        "mean_lead_time_minutes": float(test_events.mean_lead_minutes),
        "median_lead_time_minutes": float(test_events.median_lead_minutes),
        "false_alarms_per_station_day": float(
            test_events.false_alarms_per_station_day
        ),
        "alarm_precision": float(test_events.precision_by_alarm),
        "tp": int(test_report.true_positive),
        "fp": int(test_report.false_positive),
        "tn": int(test_report.true_negative),
        "fn": int(test_report.false_negative),
        "data_source": data_source,
        "test_period": test_period,
        "model": best.name,
        "operating_point": "accuracy",
        # Context that stops any single number being read out of context.
        "accuracy_band_target": [low, high],
        "accuracy_in_target_band": bool(
            low <= test_report.accuracy_not_a_headline_metric <= high
        ),
        "event_recall_target": 0.80,
        "event_recall_meets_target": bool(test_events.event_recall >= 0.80),
        "base_rate": float(test_report.base_rate),
        "constant_negative_accuracy": float(1.0 - test_report.base_rate),
        "brier": float(test_report.brier),
        "n_test_samples": int(test_report.n_samples),
        "n_test_events": int(test_events.n_events),
        "n_events_detected": int(test_events.n_detected),
        "total_alarms": int(test_events.n_alarms),
        "true_alarms": int(test_events.n_alarms - test_events.n_false_alarms),
        "false_alarms": int(test_events.n_false_alarms),
        "station_days": float(test_events.station_days),
        "validation_accuracy": float(val_report.accuracy_not_a_headline_metric),
        "validation_event_recall": float(val_events.event_recall),
        "validation_pr_auc": float(val_report.pr_auc),
        "threshold_provenance": provenance,
        "leakage_audit": audit.status,
        "synthetic_data": args.source == "synthetic",
        "selection_metric": "validation PR-AUC",
        "disclaimer": (
            "Decision-support prototype. Does not replace official PUB flood "
            "warnings."
            + (
                " Metrics measured on synthetic data: they validate the "
                "pipeline, not real-world skill."
                if args.source == "synthetic"
                else ""
            )
        ),
    }
    (results_dir / "final_metrics.json").write_text(json.dumps(final, indent=2))

    (results_dir / "confusion_matrix.json").write_text(
        json.dumps(
            {
                "model": best.name,
                "threshold": threshold,
                "split": "test",
                "test_period": test_period,
                "matrix": {
                    "true_positive": int(test_report.true_positive),
                    "false_positive": int(test_report.false_positive),
                    "true_negative": int(test_report.true_negative),
                    "false_negative": int(test_report.false_negative),
                },
                "derived": {
                    "accuracy": float(test_report.accuracy_not_a_headline_metric),
                    "precision": float(test_report.precision),
                    "recall": float(test_report.recall),
                    "specificity": float(test_report.specificity),
                    "f1": float(test_report.f1),
                },
                "unit": "one station-5-minute interval",
                "note": (
                    "Interval-level counts. The event-level view in "
                    "final_metrics.json collapses each flood episode and each "
                    "alarm burst to one unit, which is the operationally "
                    "meaningful count."
                ),
            },
            indent=2,
        )
    )

    # Reporting only: the threshold above is already frozen.
    curve = []
    for thr in np.unique(
        np.concatenate(
            [np.linspace(0.0, 1.0, 41), np.array([threshold])]
        )
    ):
        r = compute_report(y_test, test_probs, float(thr))
        ev = event_level_report(
            prepared.splits.test,
            y_test,
            test_probs,
            float(thr),
            prepared.grid.n_steps,
            prepared.grid.n_stations,
            **event_kwargs,
        )
        curve.append(
            {
                "threshold": float(thr),
                "accuracy": float(r.accuracy_not_a_headline_metric),
                "precision": float(r.precision),
                "recall": float(r.recall),
                "f1": float(r.f1),
                "event_recall": float(ev.event_recall),
                "events_detected": int(ev.n_detected),
                "n_events": int(ev.n_events),
                "false_alarms_per_station_day": float(
                    ev.false_alarms_per_station_day
                ),
                "mean_lead_minutes": float(ev.mean_lead_minutes),
                "is_selected_threshold": bool(abs(thr - threshold) < 1e-12),
            }
        )
    (results_dir / "accuracy_vs_threshold_test.json").write_text(
        json.dumps(
            {
                "model": best.name,
                "note": (
                    "Produced after the threshold was frozen on validation. "
                    "Reporting only - nothing selects on these values."
                ),
                "selected_threshold": threshold,
                "curve": curve,
            },
            indent=2,
        )
    )

    write_comparison(
        results,
        results_dir / "model_comparison.json",
        extra={
            "data_source": data_source,
            "selected_model": best.name,
            "final_threshold": threshold,
        },
    )

    print("\n" + "=" * 68)
    print(f"MODEL                 {best.name}")
    print(f"DATA                  {data_source}")
    print(f"TEST PERIOD           {test_period}")
    print(f"THRESHOLD             {threshold:.6f}  (chosen on validation)")
    print("-" * 68)
    print(
        f"TEST ACCURACY         {final['accuracy'] * 100:.2f}%   "
        f"target {low * 100:.0f}-{high * 100:.0f}%  "
        f"-> {'IN BAND' if final['accuracy_in_target_band'] else 'OUT OF BAND'}"
    )
    print(
        f"TEST EVENT RECALL     {final['event_recall'] * 100:.1f}%   "
        f"({final['n_events_detected']}/{final['n_test_events']} events)  "
        f"target >=80% -> "
        f"{'MET' if final['event_recall_meets_target'] else 'NOT MET'}"
    )
    print(f"TEST PR-AUC           {final['pr_auc']:.4f}")
    print(f"TEST ROC-AUC          {final['roc_auc']:.4f}")
    print(f"TEST PRECISION        {final['precision'] * 100:.2f}%")
    print(f"TEST F1               {final['f1']:.4f}")
    print(
        f"LEAD TIME             mean {final['mean_lead_time_minutes']:.1f} min, "
        f"median {final['median_lead_time_minutes']:.0f} min"
    )
    print(
        f"FALSE ALARMS          {final['false_alarms_per_station_day']:.2f} per "
        f"station-day  ({final['false_alarms']} of {final['total_alarms']} alarms)"
    )
    print(f"ALARM PRECISION       {final['alarm_precision'] * 100:.1f}%")
    print(
        f"CONFUSION             TP {final['tp']}  FP {final['fp']}  "
        f"TN {final['tn']}  FN {final['fn']}"
    )
    print(
        f"BASE RATE             {final['base_rate']:.5f}  "
        f"(constant-negative accuracy {final['constant_negative_accuracy'] * 100:.2f}%)"
    )
    print(f"LEAKAGE AUDIT         {audit.status}")
    print(f"SYNTHETIC DATA        {final['synthetic_data']}")
    print("=" * 68)
    print(f"\nartifacts written to {results_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
