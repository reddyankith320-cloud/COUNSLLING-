#!/usr/bin/env python3
"""Phase 1 — compare candidate models on validation. Test is never read.

    python scripts/experiments.py --days 540 --stations 32 --seed 20260601

Fits every available tabular model on each requested feature set, scores
them on validation, and writes:

* ``results/model_comparison.json`` — the full table
* ``artifacts/experiments/<name>.joblib`` — each fitted model, so the final
  evaluation can load the winner instead of refitting it
* ``artifacts/experiments/fingerprint.json`` — identifies the dataset these
  models were fitted on, so a mismatch is caught rather than silently
  producing nonsense

The LSTM is trained separately by ``scripts/train.py`` (with
``--no-test-eval``) because it needs its own loop; its validation score is
merged in by ``scripts/final_evaluation.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    p.add_argument(
        "--alerts-per-station-month", type=float, default=3.0
    )
    p.add_argument(
        "--feature-kinds",
        nargs="+",
        default=["last_step", "window_summary"],
        choices=["last_step", "window_summary"],
    )
    p.add_argument("--outdir", default="artifacts/experiments")
    p.add_argument("--results", default="results/model_comparison.json")
    p.add_argument("--no-mlflow", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config()
    cfg.train.seed = args.seed
    cfg.windows.seed = args.seed
    cfg.train.use_mlflow = not args.no_mlflow

    from floodsense.experiments import (
        available_families,
        comparison_markdown,
        run_tabular_experiments,
        select_best,
        write_comparison,
    )

    if args.source == "synthetic":
        from floodsense.pipeline import prepare_from_synthetic
        from floodsense.synthetic import SyntheticConfig

        print(
            "[floodsense] SYNTHETIC DATA (data.gov.sg unreachable). Every number "
            "below validates the pipeline, not real-world skill."
        )
        prepared = prepare_from_synthetic(
            cfg,
            SyntheticConfig(
                days=args.days,
                n_stations=args.stations,
                seed=args.seed,
                target_alerts_per_station_month=args.alerts_per_station_month,
            ),
        )
        data_source = (
            f"synthetic:floodsense.synthetic/days={args.days}/"
            f"stations={args.stations}/seed={args.seed}"
        )
    else:
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
        data_source = f"real:data.gov.sg staged at {args.data_dir}"

    print(json.dumps(prepared.report(), indent=2, default=str))
    print(f"\n[floodsense] model families available: {available_families()}")

    outdir = Path(args.outdir)
    results = run_tabular_experiments(
        prepared,
        cfg,
        feature_kinds=tuple(args.feature_kinds),
        use_mlflow=cfg.train.use_mlflow,
        save_dir=outdir,
    )
    if not results:
        print("[floodsense] no model fitted successfully")
        return 1

    fingerprint = {
        "data_source": data_source,
        "n_steps": int(prepared.grid.n_steps),
        "n_stations": int(prepared.grid.n_stations),
        "positive_label_sum": float(prepared.labels.labels.sum()),
        "n_dynamic_features": len(prepared.features.names),
        "n_static_features": len(prepared.statics.names),
        "train_samples": int(len(prepared.splits.train)),
        "val_samples": int(len(prepared.splits.val)),
        "seed": args.seed,
        "days": args.days,
        "stations": args.stations,
    }
    (outdir / "fingerprint.json").write_text(json.dumps(fingerprint, indent=2))

    write_comparison(
        results,
        args.results,
        extra={"data_source": data_source, "fingerprint": fingerprint},
    )

    print("\n" + comparison_markdown(results))
    best = select_best(results)
    print(
        f"\n[floodsense] best on validation PR-AUC: {best.name} "
        f"(PR-AUC {best.val_pr_auc:.4f}, event recall {best.val_event_recall:.3f})"
    )
    print(f"[floodsense] comparison written to {args.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
