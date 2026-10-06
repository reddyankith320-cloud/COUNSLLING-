#!/usr/bin/env python3
"""The real-data pipeline, end to end.

    # 1. check access (exits 2 when the egress policy blocks the hosts)
    python scripts/network_preflight.py

    # 2. fetch and stage, then run the whole chain
    python scripts/real_data_pipeline.py --fetch --from 2025-11-01 --to 2026-09-30 \
        --historical-dir ~/nea_rainfall_csvs \
        --flood-prone-points data/flood_prone_points.csv

    # or, with data already staged by scripts/fetch_data.py
    python scripts/real_data_pipeline.py --data-dir data/

Chain:

    official API -> raw ingest -> bronze -> validation -> silver
      -> temporal/spatial event matching -> features -> gold
      -> chronological train/val/test -> model comparison (validation)
      -> threshold (validation) -> freeze -> leakage audit
      -> one test evaluation -> distribution-shift report

The evaluation rules are the ones the synthetic pipeline already uses and are
not relaxed here: chronological splits with an embargo, model chosen on
validation PR-AUC, threshold chosen on validation inside the accuracy band,
test read exactly once, no resampling of validation or test.

**Provenance is enforced, not asserted.** This script writes
``results/real_*.json`` only when the data genuinely came from the official
sources. Pointed at synthetic data it refuses, because a file called
``real_data_metrics.json`` holding synthetic numbers is the one output that
could mislead someone downstream.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402

#: Marker written beside staged data recording where it came from.
PROVENANCE_FILE = "provenance.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data-dir", default="data", help="staged canonical tables")
    p.add_argument("--fetch", action="store_true", help="fetch from the official APIs first")
    p.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD")
    p.add_argument("--historical-dir", default=None, help="annual NEA rainfall CSVs")
    p.add_argument("--flood-prone-points", default=None, help="geocoded PUB list")
    p.add_argument(
        "--api-key", default=os.environ.get("DATAGOV_API_KEY"), help="data.gov.sg API key"
    )
    p.add_argument("--results", default="results")
    p.add_argument("--outdir", default="artifacts/real")
    p.add_argument("--skip-preflight", action="store_true")
    p.add_argument(
        "--allow-unverified-provenance",
        action="store_true",
        help="write real_* artifacts without a provenance marker (not advised)",
    )
    p.add_argument("--no-mlflow", action="store_true")
    return p.parse_args()


def run_preflight(api_key: str | None) -> None:
    from floodsense.ingest.discovery import preflight

    report = preflight(api_key=api_key)
    print(report.summary())
    if not report.reachable:
        raise SystemExit(
            "\nABORT: the official Singapore hosts are not reachable, so there "
            "is no real data to run on. Allow the hosts listed above in the "
            "environment's network settings and re-run. FloodSense will not "
            "substitute synthetic data behind a real-data label."
        )
    print()


def fetch_and_stage(args: argparse.Namespace) -> None:
    """Pull from the official APIs into the canonical staged layout."""
    from floodsense.ingest.discovery import discover_flood_alert_endpoint
    from floodsense.ingest.flood_prone import (
        fetch_flood_prone_areas,
        load_flood_prone_areas,
        load_flood_prone_points,
    )
    from floodsense.ingest.historical import load_historical_dir
    from floodsense.ingest.local import save_canonical
    from floodsense.ingest.realtime import fetch_flood_alerts, fetch_rainfall

    readings_parts, stations_parts = [], []
    sources: list[str] = []

    if args.historical_dir:
        print(f"[fetch] historical CSVs from {args.historical_dir}")
        readings, stations = load_historical_dir(args.historical_dir)
        print(f"        {len(readings):,} readings, {len(stations)} stations")
        readings_parts.append(readings)
        stations_parts.append(stations)
        sources.append(f"NEA historical rainfall CSVs ({args.historical_dir})")

    if args.date_from and args.date_to:
        dates = pd.date_range(args.date_from, args.date_to, freq="D")
        print(f"[fetch] real-time rainfall for {len(dates)} day(s)")
        for day in dates:
            label = day.strftime("%Y-%m-%d")
            try:
                readings, stations = fetch_rainfall(date=label, api_key=args.api_key)
            except Exception as exc:
                print(f"        {label}: FAILED ({exc})")
                continue
            readings_parts.append(readings)
            stations_parts.append(stations)
        sources.append(
            "NEA Rainfall across Singapore API "
            f"({args.date_from} to {args.date_to})"
        )

    if not readings_parts:
        raise SystemExit(
            "no rainfall fetched; pass --historical-dir and/or --from/--to"
        )

    readings = (
        pd.concat(readings_parts, ignore_index=True)
        .drop_duplicates(["ts", "station_id"])
        .sort_values(["ts", "station_id"], ignore_index=True)
    )
    stations = pd.concat(stations_parts, ignore_index=True).drop_duplicates(
        "station_id", ignore_index=True
    )

    endpoint, _ = discover_flood_alert_endpoint(api_key=args.api_key)
    alerts = pd.DataFrame()
    if endpoint:
        print(f"[fetch] flood alerts from {endpoint}")
        try:
            alerts = fetch_flood_alerts(url=endpoint, api_key=args.api_key)
            print(f"        {len(alerts)} alert(s)")
            sources.append(f"PUB Flood Alerts API ({endpoint})")
        except Exception as exc:
            print(f"        FAILED ({exc})")
    else:
        print("[fetch] flood-alerts endpoint not discovered; see the dataset page")

    existing = Path(args.data_dir) / "alerts.csv"
    if existing.exists() and len(alerts):
        previous = pd.read_csv(existing)
        alerts = pd.concat([previous, alerts], ignore_index=True).drop_duplicates(
            "alert_id", ignore_index=True
        )
        print(f"        merged with existing history: {len(alerts)} total")

    try:
        areas = fetch_flood_prone_areas()
        sources.append("PUB Flood Prone Areas (CKAN datastore)")
    except Exception:
        areas = load_flood_prone_areas()

    points = (
        load_flood_prone_points(args.flood_prone_points)
        if args.flood_prone_points
        else None
    )

    save_canonical(
        args.data_dir,
        readings=readings,
        stations=stations,
        alerts=alerts,
        flood_prone_points=points,
        flood_prone_areas=areas,
    )

    (Path(args.data_dir) / PROVENANCE_FILE).write_text(
        json.dumps(
            {
                "origin": "official_singapore_open_data",
                "sources": sources,
                "fetched_at": pd.Timestamp.now(tz="Asia/Singapore").isoformat(),
                "api_key_used": bool(args.api_key),
            },
            indent=2,
        )
    )
    print(f"[fetch] staged to {args.data_dir} with a provenance marker")


def check_provenance(data_dir: str, allow_unverified: bool) -> dict:
    path = Path(data_dir) / PROVENANCE_FILE
    if path.exists():
        payload = json.loads(path.read_text())
        if payload.get("origin") == "official_singapore_open_data":
            return payload
        raise SystemExit(
            f"{path} does not record official-source provenance "
            f"(origin={payload.get('origin')!r}). Refusing to write real_* "
            "artifacts from it."
        )
    if allow_unverified:
        return {"origin": "unverified", "sources": [f"staged at {data_dir}"]}
    raise SystemExit(
        f"No {PROVENANCE_FILE} in {data_dir}. This script writes files named "
        "real_*.json, so it requires evidence the data came from the official "
        "APIs. Run with --fetch, or pass --allow-unverified-provenance if you "
        "staged the official data by hand and understand the labelling."
    )


def main() -> int:
    args = parse_args()
    cfg = Config()
    cfg.operating_point = "accuracy"
    cfg.train.use_mlflow = not args.no_mlflow

    if not args.skip_preflight:
        run_preflight(args.api_key)

    if args.fetch:
        fetch_and_stage(args)

    provenance = check_provenance(args.data_dir, args.allow_unverified_provenance)
    print(f"[provenance] {provenance['origin']}: {provenance.get('sources')}\n")

    # ---- bronze -> validation -> silver -----------------------------------
    from floodsense.ingest.local import load_canonical
    from floodsense.ingest.validate import validate_all

    tables = load_canonical(args.data_dir)
    print("[validate] bronze -> silver")
    clean, reports = validate_all(
        tables["readings"], tables["stations"], tables["alerts"]
    )
    for report in reports.values():
        print(report.summary())
    if not all(r.passed for r in reports.values()):
        failed = [name for name, r in reports.items() if not r.passed]
        raise SystemExit(f"\nABORT: validation emptied {failed}.")

    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "real_validation_report.json").write_text(
        json.dumps({k: v.to_dict() for k, v in reports.items()}, indent=2)
    )

    # ---- event matching, features, gold -----------------------------------
    from floodsense.pipeline import prepare

    print("\n[features] event matching and feature engineering")
    prepared = prepare(
        readings=clean["readings"],
        stations=clean["stations"],
        alerts=clean["alerts"],
        cfg=cfg,
        flood_prone_points=tables.get("flood_prone_points"),
    )
    print(json.dumps(prepared.report(), indent=2, default=str))

    if prepared.labels.labels.sum() == 0:
        raise SystemExit(
            "\nABORT: no positive labels after event matching. With no flood "
            "alerts inside the rainfall period there is nothing to learn. "
            "Accumulate alert history (scripts/fetch_data.py --append-alerts)."
        )

    # ---- model comparison on validation -----------------------------------
    from floodsense.experiments import (
        comparison_markdown,
        run_tabular_experiments,
        select_best,
        write_comparison,
    )

    print("\n[models] comparing candidates on VALIDATION")
    experiment_dir = Path(args.outdir) / "experiments"
    results = run_tabular_experiments(
        prepared,
        cfg,
        feature_kinds=("last_step", "window_summary"),
        use_mlflow=cfg.train.use_mlflow,
        save_dir=experiment_dir,
    )
    if not results:
        raise SystemExit("no model fitted successfully")
    print("\n" + comparison_markdown(results))

    best = select_best(results)
    print(f"\n[models] selected {best.name} (validation PR-AUC {best.val_pr_auc:.4f})")

    data_source = (
        "REAL Singapore government open data (data.gov.sg): "
        + "; ".join(provenance.get("sources", []))
    )
    write_comparison(
        results,
        results_dir / "real_model_comparison.json",
        extra={"data_source": data_source, "selected_model": best.name},
    )

    # ---- threshold on validation, then freeze -----------------------------
    from floodsense.events import event_level_report, threshold_for_accuracy_band
    from floodsense.experiments import labels_for
    from floodsense.metrics import compute_report

    event_kwargs = dict(
        horizon_max_minutes=cfg.labels.horizon_max_minutes,
        merge_gap_minutes=cfg.labels.post_alert_blackout_minutes,
    )
    y_val = labels_for(prepared, prepared.splits.val)
    val_probs = _score(prepared, cfg, best.name, experiment_dir, "val")

    selection = threshold_for_accuracy_band(
        prepared.splits.val, y_val, val_probs,
        cfg.accuracy_band[0], cfg.accuracy_band[1],
        prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
    )
    threshold = float(selection["threshold"])
    val_report = compute_report(y_val, val_probs, threshold)
    val_events = selection["event_report"]
    print(
        f"\n[threshold] {threshold:.6f} from validation | "
        f"val accuracy {val_report.accuracy_not_a_headline_metric:.2%} | "
        f"val event recall {val_events.event_recall:.3f}"
    )

    provenance_record = {
        "selected_on": "validation",
        "rule": selection["selected_by"],
        "threshold": threshold,
        "accuracy_band": list(cfg.accuracy_band),
        "validation_accuracy": val_report.accuracy_not_a_headline_metric,
    }

    # ---- leakage audit ----------------------------------------------------
    from floodsense.audit import run_audit

    print("\n[audit] leakage audit")
    audit = run_audit(
        prepared, cfg, alerts=clean["alerts"], threshold_provenance=provenance_record
    )
    audit.write(results_dir / "real_leakage_audit.json")
    print(audit.markdown())
    if audit.status != "PASS":
        raise SystemExit("\nABORT: leakage audit failed; test metrics withheld.")

    # ---- the single test evaluation ---------------------------------------
    print("\n[test] reading the test split, once")
    y_test = labels_for(prepared, prepared.splits.test)
    test_probs = _score(prepared, cfg, best.name, experiment_dir, "test")
    test_report = compute_report(y_test, test_probs, threshold)
    test_events = event_level_report(
        prepared.splits.test, y_test, test_probs, threshold,
        prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
    )

    # ---- distribution shift ------------------------------------------------
    from floodsense.distribution import build_report

    shift = build_report(prepared, data_source=data_source)
    shift.write(results_dir / "real_distribution_shift.json")
    print("\n[shift] distribution across splits")
    print(shift.summary())

    periods = {
        name: (
            f"{prepared.grid.times[int(idx[:, 0].min())]} to "
            f"{prepared.grid.times[int(idx[:, 0].max())]}"
        )
        for name, idx in (
            ("train", prepared.splits.train),
            ("validation", prepared.splits.val),
            ("test", prepared.splits.test),
        )
    }

    final = {
        "data_source": data_source,
        "dataset_versions": {
            "realtime_rainfall": "d_6580738cdd7db79374ed3152159fbd69",
            "flood_alerts": "d_f1404e08587ce555b9ea3f565e2eb9a3",
            "flood_prone_areas": "d_c4aed98f1533eb3a66f65dbb1a30da46",
            "historical_rainfall_collection": "2279",
            "provenance": provenance,
        },
        "train_period": periods["train"],
        "validation_period": periods["validation"],
        "test_period": periods["test"],
        "n_train": int(len(prepared.splits.train)),
        "n_validation": int(len(prepared.splits.val)),
        "n_test": int(len(prepared.splits.test)),
        "event_prevalence": {
            p.name: p.event_prevalence for p in shift.profiles
        },
        "model": best.name,
        "threshold": threshold,
        "accuracy": float(test_report.accuracy_not_a_headline_metric),
        "event_recall": float(test_events.event_recall),
        "precision": float(test_report.precision),
        "f1": float(test_report.f1),
        "pr_auc": float(test_report.pr_auc),
        "roc_auc": float(test_report.roc_auc),
        "mean_lead_time_minutes": float(test_events.mean_lead_minutes),
        "median_lead_time_minutes": float(test_events.median_lead_minutes),
        "false_alarms_per_station_day": float(
            test_events.false_alarms_per_station_day
        ),
        "alarm_precision": float(test_events.precision_by_alarm),
        "confusion_matrix": {
            "tp": int(test_report.true_positive),
            "fp": int(test_report.false_positive),
            "tn": int(test_report.true_negative),
            "fn": int(test_report.false_negative),
        },
        "tp": int(test_report.true_positive),
        "fp": int(test_report.false_positive),
        "tn": int(test_report.true_negative),
        "fn": int(test_report.false_negative),
        "leakage_audit": audit.status,
        "threshold_provenance": provenance_record,
        "validation_accuracy": float(val_report.accuracy_not_a_headline_metric),
        "validation_event_recall": float(val_events.event_recall),
        "validation_pr_auc": float(val_report.pr_auc),
        "base_rate": float(test_report.base_rate),
        "constant_negative_accuracy": float(1.0 - test_report.base_rate),
        "n_test_events": int(test_events.n_events),
        "n_events_detected": int(test_events.n_detected),
        "total_alarms": int(test_events.n_alarms),
        "true_alarms": int(test_events.n_alarms - test_events.n_false_alarms),
        "false_alarms": int(test_events.n_false_alarms),
        "station_days": float(test_events.station_days),
        "n_test_samples": int(test_report.n_samples),
        "operating_point": "accuracy",
        "accuracy_band_target": list(cfg.accuracy_band),
        "accuracy_in_target_band": bool(
            cfg.accuracy_band[0]
            <= test_report.accuracy_not_a_headline_metric
            <= cfg.accuracy_band[1]
        ),
        "event_recall_target": 0.80,
        "event_recall_meets_target": bool(test_events.event_recall >= 0.80),
        "selection_metric": "validation PR-AUC",
        "synthetic_data": False,
        "disclaimer": (
            "Decision-support prototype built on Singapore government open "
            "data. Does not replace official PUB flood warnings."
        ),
    }
    (results_dir / "real_data_metrics.json").write_text(json.dumps(final, indent=2))

    curve = []
    for thr in np.unique(np.concatenate([np.linspace(0.0, 1.0, 41), [threshold]])):
        r = compute_report(y_test, test_probs, float(thr))
        ev = event_level_report(
            prepared.splits.test, y_test, test_probs, float(thr),
            prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
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
                "false_alarms_per_station_day": float(ev.false_alarms_per_station_day),
                "mean_lead_minutes": float(ev.mean_lead_minutes),
                "is_selected_threshold": bool(abs(thr - threshold) < 1e-12),
            }
        )
    (results_dir / "real_accuracy_vs_threshold.json").write_text(
        json.dumps(
            {
                "model": best.name,
                "data_source": data_source,
                "selected_threshold": threshold,
                "note": "Produced after the threshold was frozen. Reporting only.",
                "curve": curve,
            },
            indent=2,
        )
    )

    print("\n" + "=" * 68)
    print(f"REAL DATA   {data_source}")
    print(f"MODEL       {best.name}")
    print(f"THRESHOLD   {threshold:.6f} (validation)")
    print(f"ACCURACY    {final['accuracy'] * 100:.2f}%  "
          f"{'IN BAND' if final['accuracy_in_target_band'] else 'OUT OF BAND'}")
    print(f"EVENT RECALL {final['event_recall'] * 100:.1f}% "
          f"({final['n_events_detected']}/{final['n_test_events']})  "
          f"{'MET' if final['event_recall_meets_target'] else 'NOT MET'}")
    print(f"PR-AUC {final['pr_auc']:.4f} | ROC-AUC {final['roc_auc']:.4f}")
    print(f"LEAD {final['mean_lead_time_minutes']:.1f} min mean, "
          f"{final['median_lead_time_minutes']:.0f} median")
    print(f"FALSE ALARMS {final['false_alarms_per_station_day']:.2f}/station-day")
    print(f"LEAKAGE AUDIT {audit.status}")
    print("=" * 68)
    print(f"\nartifacts written to {results_dir}/real_*.json")
    return 0


def _score(prepared, cfg, name: str, experiment_dir: Path, split: str) -> np.ndarray:
    import joblib

    from floodsense.experiments import last_step_features, window_summary_features

    base, kind = name.split(":")
    model = joblib.load(experiment_dir / f"{base}__{kind}.joblib")
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


if __name__ == "__main__":
    raise SystemExit(main())
